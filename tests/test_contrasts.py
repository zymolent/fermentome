"""Tests for `fermdb.omics.contrasts` — the gate, the arithmetic, and the replicate check.

Three properties carry the weight here, and each of them fails silently if it breaks.

The **gate** is PLAN.md F.3 in code: no contrast over samples without an approved
`condition_context`. A regression that let it through would not raise; it would produce a
perfectly formatted result built on a grouping nobody approved. The tests therefore assert on
refusals, including the two that are easy to get backwards — a genotype contrast needs the
conditions to *match*, and every other axis needs them to *differ*.

The **pooling** rule decides what `n` means. Two runs of one library are one biological
observation, and counting them as two halves the standard error on nothing. The test pins that a
pooled contrast reports the number of units.

The **cohesion** check is the one that catches a contaminated replicate group. Without it, a
sample that does not belong to its group inflates the variance, every p-value rises, and the
contrast reports "nothing significant" — which is indistinguishable from a real negative. The
test builds exactly that situation and asserts the outlier is named.
"""

from __future__ import annotations

import gzip
import math
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import contrasts as C


def _matrix(tmp_path: Path, columns: list[str], rows: dict[str, list[float]]) -> Path:
    path = tmp_path / "counts.tsv.gz"
    with gzip.open(path, "wt", newline="\n") as handle:
        handle.write("gene\t" + "\t".join(columns) + "\n")
        for gene, values in rows.items():
            handle.write(gene + "\t" + "\t".join(str(v) for v in values) + "\n")
    return path


def _db(samples: dict[str, tuple[str | None, str | None]], study: str = "SRPTEST"):
    """samples: sample id -> (condition_context_id, strain_id)."""
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 'R', 'test', 'high')"
    )
    for context_id in {c for c, _ in samples.values() if c}:
        conn.execute(
            "INSERT INTO condition_context (id, context_hash, zone, evidence, confidence) "
            "VALUES (?, ?, 'R', 'test', 'high')",
            (context_id, context_id),
        )
    for strain_id in {s for _, s in samples.values() if s}:
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:sc', ?, 'engineered', 'R', 'test', 'medium')",
            (strain_id, strain_id.rsplit(":", 1)[-1]),
        )
    conn.execute(
        "INSERT INTO dataset (id, accession, repository, omics_type, zone, evidence, confidence) "
        "VALUES ('YAA:DATASET:t', ?, 'SRA', 'transcriptomics', 'R', 'test', 'high')",
        (study,),
    )
    for sample_id, (context_id, strain_id) in samples.items():
        run = sample_id.rsplit(":", 1)[-1]
        conn.execute(
            "INSERT INTO sample (id, dataset_id, strain_id, condition_context_id, zone, "
            "evidence, confidence) VALUES (?, 'YAA:DATASET:t', ?, ?, 'R', 'test', 'high')",
            (sample_id, strain_id, context_id),
        )
        conn.execute(
            "INSERT INTO sra_run (id, run_accession, dataset_id, study_accession, organism, "
            "library_strategy, retrieved_at, zone, evidence, confidence) "
            "VALUES (?, ?, 'YAA:DATASET:t', ?, 'Saccharomyces cerevisiae', 'RNA-Seq', "
            "'2026-09-22T00:00:00Z', 'R', 'test', 'high')",
            (f"YAA:SRARUN:{run}", run, study),
        )
    return conn


def _spec(
    reference: list[str],
    treatment: list[str],
    *,
    axis: str,
    contexts: tuple[str, str],
    pool: dict[str, str] | None = None,
) -> C.ContrastSpec:
    return C.ContrastSpec(
        id="YAA:CONTRAST:test",
        study_accession="SRPTEST",
        reference=C.ContrastGroup("ref", tuple(reference), contexts[0]),
        treatment=C.ContrastGroup("trt", tuple(treatment), contexts[1]),
        axis=axis,
        pool_by=pool,
    )


# ------------------------------------------------------------------------------------- the gate


def test_refuses_a_sample_without_a_context() -> None:
    conn = _db(
        {
            "YAA:SAMPLE:R1": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R2": (None, "YAA:STRAIN:p"),
            "YAA:SAMPLE:R3": ("YAA:CCTX:b", "YAA:STRAIN:q"),
            "YAA:SAMPLE:R4": ("YAA:CCTX:b", "YAA:STRAIN:q"),
        }
    )
    problems = C.refusals(
        conn,
        _spec(
            ["YAA:SAMPLE:R1", "YAA:SAMPLE:R2"],
            ["YAA:SAMPLE:R3", "YAA:SAMPLE:R4"],
            axis="time",
            contexts=("YAA:CCTX:a", "YAA:CCTX:b"),
        ),
    )
    assert any("no approved condition_context" in p for p in problems)


def test_genotype_contrast_requires_the_same_context() -> None:
    """The direction that is easy to get backwards: a strain comparison needs matched conditions."""
    conn = _db(
        {
            "YAA:SAMPLE:R1": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R2": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R3": ("YAA:CCTX:b", "YAA:STRAIN:q"),
            "YAA:SAMPLE:R4": ("YAA:CCTX:b", "YAA:STRAIN:q"),
        }
    )
    problems = C.refusals(
        conn,
        _spec(
            ["YAA:SAMPLE:R1", "YAA:SAMPLE:R2"],
            ["YAA:SAMPLE:R3", "YAA:SAMPLE:R4"],
            axis="genotype",
            contexts=("YAA:CCTX:a", "YAA:CCTX:b"),
        ),
    )
    assert any("must sit in the same condition_context" in p for p in problems)


def test_genotype_contrast_refuses_one_strain_on_both_sides() -> None:
    conn = _db(
        {
            "YAA:SAMPLE:R1": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R2": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R3": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R4": ("YAA:CCTX:a", "YAA:STRAIN:p"),
        }
    )
    problems = C.refusals(
        conn,
        _spec(
            ["YAA:SAMPLE:R1", "YAA:SAMPLE:R2"],
            ["YAA:SAMPLE:R3", "YAA:SAMPLE:R4"],
            axis="genotype",
            contexts=("YAA:CCTX:a", "YAA:CCTX:a"),
        ),
    )
    assert any("same strain" in p for p in problems)


def test_non_genotype_contrast_refuses_one_context_on_both_sides() -> None:
    conn = _db(
        {
            "YAA:SAMPLE:R1": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R2": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R3": ("YAA:CCTX:a", "YAA:STRAIN:p"),
            "YAA:SAMPLE:R4": ("YAA:CCTX:a", "YAA:STRAIN:p"),
        }
    )
    problems = C.refusals(
        conn,
        _spec(
            ["YAA:SAMPLE:R1", "YAA:SAMPLE:R2"],
            ["YAA:SAMPLE:R3", "YAA:SAMPLE:R4"],
            axis="isobutanol_exposure",
            contexts=("YAA:CCTX:a", "YAA:CCTX:a"),
        ),
    )
    assert any("no axis to contrast along" in p for p in problems)


def test_run_contrast_raises_when_the_gate_refuses(tmp_path: Path) -> None:
    conn = _db({"YAA:SAMPLE:R1": (None, None), "YAA:SAMPLE:R2": (None, None)})
    matrix = _matrix(tmp_path, ["R1", "R2"], {"YAL001C": [10.0, 12.0]})
    with pytest.raises(PermissionError):
        C.run_contrast(
            conn,
            _spec(
                ["YAA:SAMPLE:R1"],
                ["YAA:SAMPLE:R2"],
                axis="time",
                contexts=("YAA:CCTX:a", "YAA:CCTX:b"),
            ),
            matrix_path=matrix,
        )


# ------------------------------------------------------------------------------- the arithmetic


def test_size_factors_ignore_genes_with_a_zero() -> None:
    """A gene off in one library has an undefined log ratio and must not steer the factor."""
    rows = [[100.0, 100.0], [0.0, 500.0], [50.0, 50.0]]
    factors = C.size_factors(rows, n_samples=2)
    assert factors[0] == pytest.approx(factors[1])


def test_size_factors_fall_back_to_one_when_nothing_is_shared() -> None:
    rows = [[10.0, 0.0], [0.0, 10.0]]
    assert C.size_factors(rows, n_samples=2) == [1.0, 1.0]


def test_single_replicate_is_computed_but_never_tested() -> None:
    genes = ["YAL001C", "YAL002W"]
    rows = [[10.0, 100.0], [50.0, 50.0]]
    results, _factors, underpowered, tested, _filtered = C.differential_expression(
        genes, rows, n_reference=1, n_treatment=1
    )
    assert underpowered is True
    assert tested == 0
    assert all(r.p_value is None and r.p_adjusted is None for r in results)
    # The fold change is still reported: it is a number to look at, not a claim. It is smaller
    # than the raw 10:100 ratio because size-factor normalisation has already absorbed part of
    # the difference as a library-depth effect, which is the point of normalising.
    assert results[0].log2_fold_change > 1.5


def test_benjamini_hochberg_is_monotone_and_bounded() -> None:
    adjusted = C._benjamini_hochberg([0.001, 0.01, 0.2, 0.9])
    assert adjusted == sorted(adjusted)
    assert all(0.0 <= value <= 1.0 for value in adjusted)


def test_abundance_floor_excludes_rather_than_silently_passing() -> None:
    genes = ["low", "high"]
    rows = [[1.0, 1.0, 1.0, 2.0], [500.0, 520.0, 510.0, 1000.0]]
    results, _f, _u, tested, filtered = C.differential_expression(
        genes, rows, n_reference=2, n_treatment=2, min_base_mean=10.0
    )
    assert tested == 1 and filtered == 1
    by_gene = {r.gene: r for r in results}
    assert by_gene["low"].tested is False and by_gene["low"].p_adjusted is None
    assert by_gene["high"].tested is True


# ---------------------------------------------------------------------------------- the pooling


def test_pooling_makes_n_the_number_of_units(tmp_path: Path) -> None:
    samples = {f"YAA:SAMPLE:R{i}": ("YAA:CCTX:a", "YAA:STRAIN:p") for i in (1, 2, 3, 4)}
    samples.update({f"YAA:SAMPLE:R{i}": ("YAA:CCTX:a", "YAA:STRAIN:q") for i in (5, 6, 7, 8)})
    conn = _db(samples)
    columns = [f"R{i}" for i in range(1, 9)]
    matrix = _matrix(tmp_path, columns, {f"G{g}": [100.0 + g] * 8 for g in range(60)})
    pool = {
        "YAA:SAMPLE:R1": "B1",
        "YAA:SAMPLE:R2": "B1",
        "YAA:SAMPLE:R3": "B2",
        "YAA:SAMPLE:R4": "B2",
        "YAA:SAMPLE:R5": "B3",
        "YAA:SAMPLE:R6": "B3",
        "YAA:SAMPLE:R7": "B4",
        "YAA:SAMPLE:R8": "B4",
    }
    spec = _spec(
        ["YAA:SAMPLE:R1", "YAA:SAMPLE:R2", "YAA:SAMPLE:R3", "YAA:SAMPLE:R4"],
        ["YAA:SAMPLE:R5", "YAA:SAMPLE:R6", "YAA:SAMPLE:R7", "YAA:SAMPLE:R8"],
        axis="genotype",
        contexts=("YAA:CCTX:a", "YAA:CCTX:a"),
        pool=pool,
    )
    result = C.run_contrast(conn, spec, matrix_path=matrix)
    assert len(spec.units(spec.reference)) == 2
    assert any("pooled into 4 biological units" in note for note in result.notes)
    assert all(r.n_reference == 2 and r.n_treatment == 2 for r in result.genes)


# --------------------------------------------------------------------------------- the cohesion


def test_cohesion_names_the_sample_that_is_not_a_replicate() -> None:
    """One sample with an inverted profile must be named, not left to depress every p-value."""
    labels = ["A1", "A2", "A3"]
    # A1 and A2 agree; A3 runs the other way.
    rows = [[float(i), float(i) + 0.5, float(100 - i)] for i in range(1, 60)]
    cohesion = C.group_cohesion(rows, labels, {"group": labels})
    # A1 has a good partner (A2) and must not be accused of being the outlier; A3 has none.
    assert cohesion["A1"] > 0.9
    assert cohesion["A2"] > 0.9
    assert cohesion["A3"] < 0.0


def test_cohesion_is_nan_for_a_group_of_one() -> None:
    cohesion = C.group_cohesion([[1.0], [2.0]], ["only"], {"g": ["only"]})
    assert math.isnan(cohesion["only"])
