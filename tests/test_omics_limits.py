"""Tests for `fermdb.omics.limits` — the arithmetic behind the written statistical limits.

Two kinds of check, and both matter for a different reason.

*The arithmetic* is checked against values that exist independently of this code: published
normal quantiles, the algebraic identity between a minimum detectable effect and the sample size
it implies, and a sign test whose answer can be worked out by hand. A power calculation that is
merely self-consistent would happily justify any document written from it.

*The corpus* is checked against the numbers `docs/drafts/omics/STATISTICAL_LIMITS.md` publishes.
The document's headline is that the 99-sample yeast matrix is **four** studies, and that number is
the one every conclusion in it rests on — so it is asserted here rather than left to be quietly
falsified the next time a matrix is rebuilt.
"""

from __future__ import annotations

import gzip
import math
import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import limits as L

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"


# ------------------------------------------------------------------------------- the arithmetic


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (0.5, 0.0),
        (0.975, 1.959963985),
        (0.80, 0.841621234),
        (0.995, 2.575829304),
        # The Bonferroni tail over a 6,187-gene transcriptome. This is the regime every
        # genome-wide number in the document lives in, and where a cheap approximation drifts.
        (1.0 - (0.05 / 6187) / 2.0, 4.463014422),
    ],
)
def test_normal_quantile_matches_published_values(p: float, expected: float) -> None:
    assert L.normal_quantile(p) == pytest.approx(expected, abs=1e-6)


def test_a_quantile_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="0 < p < 1"):
        L.normal_quantile(0.0)


def test_the_detectable_effect_shrinks_with_the_square_root_of_n() -> None:
    """The relationship that makes the whole document's point: four times the samples buys half
    the effect size, so a corpus does not get powerful by growing a little."""
    four = L.min_detectable_log2_fold_change(sigma=0.5, n_per_group=4)
    sixteen = L.min_detectable_log2_fold_change(sigma=0.5, n_per_group=16)
    assert four / sixteen == pytest.approx(2.0)


def test_the_detectable_effect_is_linear_in_the_dispersion() -> None:
    quiet = L.min_detectable_log2_fold_change(sigma=0.1, n_per_group=6)
    noisy = L.min_detectable_log2_fold_change(sigma=0.6, n_per_group=6)
    assert noisy / quiet == pytest.approx(6.0)


def test_required_n_inverts_the_detectable_effect() -> None:
    """An algebraic identity, so a sign error in either direction fails here rather than in a
    document nobody re-derives."""
    delta = L.min_detectable_log2_fold_change(sigma=0.4, n_per_group=9)
    assert L.required_n_per_group(sigma=0.4, log2_fold_change=delta) == 9


def test_a_two_sample_contrast_needs_two_samples_a_side() -> None:
    with pytest.raises(ValueError, match="at least 2 samples per group"):
        L.min_detectable_log2_fold_change(sigma=0.4, n_per_group=1)


def test_bonferroni_needs_at_least_one_test() -> None:
    with pytest.raises(ValueError, match="at least one test"):
        L.bonferroni_alpha(0.05, 0)


def test_unanimous_direction_across_four_studies_is_not_significant() -> None:
    """Worked by hand: two tails times one half to the fourth is 0.125. The yeast corpus has four
    studies, so every one of them agreeing about a gene fails to reach 0.05 before a single
    multiple-testing correction is applied."""
    assert L.sign_test_p(4) == pytest.approx(0.125)
    assert L.sign_test_p(1) == pytest.approx(1.0)


def test_the_number_of_studies_unanimity_would_need() -> None:
    """Six for a single pre-specified gene; eighteen across a 6,187-gene transcriptome. Both are
    checkable by hand against `sign_test_p`, and neither depends on any dispersion estimate."""
    assert L.studies_needed_for_unanimous_direction() == 6
    assert L.sign_test_p(6) <= 0.05 < L.sign_test_p(5)

    needed = L.studies_needed_for_unanimous_direction(n_tests=6187)
    assert needed == 18
    corrected = L.bonferroni_alpha(0.05, 6187)
    assert L.sign_test_p(needed) <= corrected < L.sign_test_p(needed - 1)


# --------------------------------------------------------------------------- the dispersion read


def _matrix(path: Path, samples: list[str], rows: dict[str, list[float]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("gene\t" + "\t".join(samples) + "\n")
        for gene, values in rows.items():
            handle.write(gene + "\t" + "\t".join(f"{v:g}" for v in values) + "\n")
    return path


def test_dispersion_is_measured_per_study_not_across_the_matrix(tmp_path: Path) -> None:
    """Two studies whose samples differ wildly from each other but not within themselves. A
    matrix-wide dispersion would report the between-study gap as noise; a per-study one does not,
    and the per-study one is what a within-study contrast would actually face."""
    samples = ["A1", "A2", "B1", "B2"]
    rows = {f"G{i}": [10.0, 10.0, 1000.0, 1000.0] for i in range(1, 21)}
    path = _matrix(tmp_path / "m.tpm.tsv.gz", samples, rows)
    study = {"A1": "SRP1", "A2": "SRP1", "B1": "SRP2", "B2": "SRP2"}

    dispersions = L.study_dispersions(path, study)
    assert [d.study_accession for d in dispersions] == ["SRP1", "SRP2"]
    assert all(d.samples == 2 for d in dispersions)
    assert all(d.within_study_sd == pytest.approx(0.0) for d in dispersions)


def test_the_closest_pair_is_the_tighter_bound(tmp_path: Path) -> None:
    """S3 is a near-copy of S1 and S2 disagrees with both, gene by gene. The within-study SD sees
    all three; the closest-pair estimate isolates S1/S3, which is the tightest evidence the corpus
    can offer about what replicate noise looks like.

    S2's offsets alternate rather than being a constant multiple, because the estimator is a
    median absolute deviation: a pair that differs by the *same* factor in every gene has a
    deviation of zero however large the factor, which is correct (a global scaling is a
    normalization difference, not noise) and would make a constant-offset fixture test nothing.
    """
    samples = ["S1", "S2", "S3"]
    rows = {
        f"G{i}": [100.0, 100.0 * (4.0 if i % 2 else 0.25), 101.0 if i % 3 else 99.0]
        for i in range(1, 31)
    }
    path = _matrix(tmp_path / "m.tpm.tsv.gz", samples, rows)
    dispersion = L.study_dispersions(path, dict.fromkeys(samples, "SRP1"))[0]

    assert dispersion.closest_pair == ("S1", "S3")
    assert dispersion.closest_pair_sd is not None
    assert dispersion.closest_pair_sd < 0.1
    assert dispersion.within_study_sd > 0.5
    assert dispersion.closest_pair_sd < dispersion.within_study_sd


def test_genes_nobody_detected_do_not_set_the_noise_level(tmp_path: Path) -> None:
    """A gene sitting on the detection floor has a variance that describes the floor. Counting it
    would make the corpus look quieter than it is, in the direction that flatters the atlas."""
    samples = ["S1", "S2"]
    rows: dict[str, list[float]] = {f"HIGH{i}": [100.0, 200.0] for i in range(1, 11)}
    rows.update({f"OFF{i}": [0.0, 0.0] for i in range(1, 51)})
    path = _matrix(tmp_path / "m.tpm.tsv.gz", samples, rows)
    dispersion = L.study_dispersions(path, dict.fromkeys(samples, "SRP1"))[0]

    assert dispersion.expressed_genes == 10
    assert dispersion.within_study_sd > 0.0


def test_a_sample_naming_no_study_is_refused_rather_than_bucketed(tmp_path: Path) -> None:
    """An "unknown study" bucket would inflate the study count, and the study count is the number
    every conclusion in the document rests on."""
    path = _matrix(tmp_path / "m.tpm.tsv.gz", ["S1", "S2"], {"G1": [1.0, 2.0]})
    with pytest.raises(ValueError, match="name no SRA study"):
        L.study_dispersions(path, {"S1": "SRP1"})


def test_max_group_size_is_half_the_samples() -> None:
    dispersion = L.StudyDispersion(
        study_accession="SRP1",
        samples=9,
        expressed_genes=100,
        within_study_sd=0.5,
        closest_pair_sd=0.1,
        closest_pair=("a", "b"),
    )
    assert dispersion.max_group_size == 4


# -------------------------------------------------------------------------------- the inventory


def _empty_db() -> sqlite3.Connection:
    return open_db(IN_MEMORY)


def test_no_condition_context_means_no_sample_may_enter_a_contrast() -> None:
    """CONVENTIONS.md "Conditions" as a counted fact rather than a sentence in a document."""
    connection = _empty_db()
    try:
        inventory = L.corpus_inventory(connection)
        assert inventory.condition_contexts == 0
        assert inventory.contrastable_samples == 0
        assert inventory.correlative_omics_evidence_items == 0
    finally:
        connection.close()


# -------------------------------------------------------- the real corpus, against the document


_REAL = Settings.load(paths_file=PATHS_FILE, env={})
MATRICES = Path(_REAL.matrices_dir)
#: Both, and `create=False` below, so that a missing derived tier skips rather than quietly
#: creating an empty atlas next to the developer's real one and testing that.
_HAVE_CORPUS = (MATRICES / "s288c.tpm.tsv.gz").is_file() and Path(_REAL.db_file).is_file()


def _study_by_run() -> dict[str, str]:
    connection = open_db(_REAL.db_file, create=False)
    try:
        return L.study_by_run(connection)
    finally:
        connection.close()


@pytest.mark.skipif(not _HAVE_CORPUS, reason="the corpus lives in the derived tier")
def test_the_yeast_matrix_is_four_studies_which_is_the_documents_headline() -> None:
    """99 samples looks like a corpus; four studies is what it actually is. The gap between those
    two numbers is the entire subject of STATISTICAL_LIMITS.md, so it is pinned here."""
    matrix = L.matrix_limits(MATRICES / "s288c.tpm.tsv.gz", _study_by_run(), reference="s288c")
    assert matrix.samples == 99
    assert matrix.independent_studies == 4
    assert sum(d.samples for d in matrix.dispersions) == matrix.samples
    # One study is nearly half the corpus. A meta-analysis over these four is not four votes.
    assert max(d.samples for d in matrix.dispersions) >= matrix.samples // 3


@pytest.mark.skipif(not _HAVE_CORPUS, reason="the corpus lives in the derived tier")
def test_the_measured_dispersion_brackets_the_documents_power_table() -> None:
    """The bracket is two measured bounds, not one assumed value, and the loose end must really be
    looser — if they ever collapse together the document's "reported at both ends" framing is a
    fiction."""
    matrix = L.matrix_limits(MATRICES / "s288c.tpm.tsv.gz", _study_by_run(), reference="s288c")
    tight, loose = matrix.sigma_bracket
    assert 0.0 < tight < loose
    # At the loosest measured spread, three samples a side cannot see a doubling.
    assert L.min_detectable_log2_fold_change(sigma=loose, n_per_group=3) > 1.0
    assert math.isfinite(L.min_detectable_log2_fold_change(sigma=tight, n_per_group=3))
