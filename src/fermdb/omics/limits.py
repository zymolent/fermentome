"""What this corpus can and cannot detect: the statistical limits, computed rather than asserted.

PLAN.md phase 4 makes "the corpus's statistical limits are stated in writing" an acceptance
clause, and says what the statement has to concede: *with this few independent studies,
cross-study meta-analysis is underpowered for anything but large effects, and the atlas says so
rather than implying otherwise.* This module is where the numbers behind that sentence come from,
so that the written statement (`docs/drafts/omics/STATISTICAL_LIMITS.md`) is a report of a
measurement and can be re-run when the corpus changes.

**Nothing here is a rule of thumb.** Two quantities normally taken from convention are instead
read off the corpus itself:

* **The number of independent studies.** Not "a handful" -- the count of distinct SRA studies
  whose runs actually appear in each expression matrix, which is smaller than the number of
  studies in `dataset` because only quantified runs reach a matrix.
* **The residual spread a contrast would have to beat.** Two measured bounds rather than an
  assumed dispersion, because the corpus has no approved `condition_context` and therefore no
  replicate groups to estimate one from properly:

  * ``within_study_sd`` -- the median across genes of the SD of log2(TPM+1) over every sample in
    a study. It contains real condition differences as well as noise, so it is the **loosest**
    upper bound.
  * ``closest_pair_sd`` -- the same statistic for the single most similar pair of samples in the
    study, divided by sqrt(2) because it describes a difference. The **tightest** upper bound the
    corpus can offer: that pair may be replicates, and if it is not, what it holds is still
    condition signal on top of noise rather than noise alone.

  The true residual SD of a properly designed contrast lies between them, and every power number
  below is therefore reported at **both** ends rather than at one invented middle.

The power arithmetic is the ordinary two-sample normal approximation, stated explicitly in
:func:`min_detectable_log2_fold_change` so the assumption is visible instead of buried. It is
deliberately not a negative-binomial/DESeq2 power model: that would need per-gene dispersions
fitted to counts under a design, and there is no design -- which is itself the finding.

Standard library only (CONVENTIONS.md "Code"): :func:`normal_quantile` is an inverse-normal
approximation rather than a SciPy import, and it is tested against known quantiles.
"""

from __future__ import annotations

import gzip
import math
import sqlite3
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..config import Settings

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_POWER",
    "EXPRESSED_TPM",
    "CorpusInventory",
    "LimitsReport",
    "MatrixLimits",
    "StudyDispersion",
    "bonferroni_alpha",
    "build_limits",
    "corpus_inventory",
    "matrix_limits",
    "min_detectable_log2_fold_change",
    "normal_quantile",
    "required_n_per_group",
    "sign_test_p",
    "studies_needed_for_unanimous_direction",
    "study_dispersions",
]

#: A gene enters the dispersion estimate only if its median TPM in that study reaches this.
#: Genes nobody detected have a variance that is a property of the detection floor, not of
#: biology, and including them would make the corpus look quieter than it is.
EXPRESSED_TPM: Final[float] = 1.0

#: Conventional two-sided significance and power. Named here once, reported with every number
#: that depends on them (CONVENTIONS.md "Thresholds").
DEFAULT_ALPHA: Final[float] = 0.05
DEFAULT_POWER: Final[float] = 0.80


# ------------------------------------------------------------------------------- the arithmetic


_ACKLAM_A: Final[tuple[float, ...]] = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B: Final[tuple[float, ...]] = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C: Final[tuple[float, ...]] = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D: Final[tuple[float, ...]] = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_ACKLAM_SPLIT: Final[float] = 0.02425


def normal_quantile(p: float) -> float:
    """The standard-normal quantile for `p`, to about seven significant figures.

    Acklam's rational approximation, refined by one Halley step against the error function, so
    that the Bonferroni tail (`p` around 1 - 4e-6) is accurate -- that is the regime every
    genome-scale threshold below lives in, and it is exactly where a cheap approximation drifts.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"a quantile needs 0 < p < 1, not {p}")
    if p < _ACKLAM_SPLIT:
        q = math.sqrt(-2.0 * math.log(p))
        x = _poly(_ACKLAM_C, q) / _poly_d(_ACKLAM_D, q)
    elif p > 1.0 - _ACKLAM_SPLIT:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -_poly(_ACKLAM_C, q) / _poly_d(_ACKLAM_D, q)
    else:
        q = p - 0.5
        r = q * q
        x = _poly(_ACKLAM_A, r) * q / (_poly_b(_ACKLAM_B, r))
    error = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    derivative = math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)
    return x - error / (derivative + error * x / 2.0)


def _poly(coefficients: Sequence[float], x: float) -> float:
    total = 0.0
    for c in coefficients:
        total = total * x + c
    return total


def _poly_b(coefficients: Sequence[float], x: float) -> float:
    return _poly(coefficients, x) * x + 1.0


def _poly_d(coefficients: Sequence[float], x: float) -> float:
    return _poly(coefficients, x) * x + 1.0


def bonferroni_alpha(alpha: float, n_tests: int) -> float:
    """`alpha` spread over `n_tests` genes. The honest denominator for a genome-wide scan.

    Bonferroni rather than Benjamini-Hochberg because BH's effective threshold depends on how
    many genes are truly changed, which is the unknown. Bonferroni is the conservative end of the
    bracket, and it is reported as such rather than presented as the only option.
    """
    if n_tests < 1:
        raise ValueError(f"a multiple-testing correction needs at least one test, not {n_tests}")
    return alpha / n_tests


def min_detectable_log2_fold_change(
    *,
    sigma: float,
    n_per_group: int,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> float:
    """The smallest log2 fold change a balanced two-group contrast could detect.

    ``delta = (z(1 - alpha/2) + z(power)) * sigma * sqrt(2 / n)`` -- the two-sample normal
    approximation, written out because the assumption matters more than the number: equal group
    sizes, equal variances, a log-scale response, and a *known* sigma rather than one estimated
    from the same tiny sample. The last is optimistic at these group sizes (a t-distribution
    would demand more), so every figure this returns is a **floor on what is detectable**, not an
    achievable target.
    """
    if sigma < 0:
        raise ValueError(f"sigma cannot be negative: {sigma}")
    if n_per_group < 2:
        raise ValueError(
            f"a two-group contrast needs at least 2 samples per group, not {n_per_group}"
        )
    z = normal_quantile(1.0 - alpha / 2.0) + normal_quantile(power)
    return z * sigma * math.sqrt(2.0 / n_per_group)


def required_n_per_group(
    *,
    sigma: float,
    log2_fold_change: float,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> int:
    """Samples per group needed to detect `log2_fold_change`. The inverse of the function above.

    The ceiling is taken with a relative tolerance rather than exactly: a value that is
    mathematically an integer arrives from the floating-point round trip as 9.000000000000002,
    and rounding that up to ten would report a sample the design does not need.
    """
    if log2_fold_change <= 0:
        raise ValueError(f"an effect size must be positive: {log2_fold_change}")
    z = normal_quantile(1.0 - alpha / 2.0) + normal_quantile(power)
    exact = 2.0 * (z * sigma / log2_fold_change) ** 2
    return max(2, math.ceil(exact - 1e-9 * max(1.0, exact)))


def sign_test_p(n_studies: int) -> float:
    """Two-sided p for every one of `n_studies` independent studies agreeing on a direction.

    This is the whole of what contrast-level meta-analysis can claim when the constituent studies
    report a direction and nothing reliable about magnitude (PLAN.md F.6: across studies, the unit
    is the effect size **or its rank**). With four studies the answer is 0.125 -- unanimity across
    the entire yeast corpus is not significant even before any multiple-testing correction.
    """
    if n_studies < 1:
        raise ValueError(f"a sign test needs at least one study, not {n_studies}")
    return min(1.0, 2.0 ** (1 - n_studies))


def studies_needed_for_unanimous_direction(
    *, n_tests: int = 1, alpha: float = DEFAULT_ALPHA
) -> int:
    """How many independent studies must agree before unanimity survives the testing burden.

    Solves :func:`sign_test_p` against a Bonferroni-corrected threshold. At one test it is six
    studies; over a 6,187-gene transcriptome it is eighteen. This is the single most useful number
    in the module, because it is exact, needs no dispersion estimate, and cannot be argued down:
    it depends only on how many independent studies exist and how many genes are being scanned.
    """
    threshold = bonferroni_alpha(alpha, n_tests)
    studies = 1
    while sign_test_p(studies) > threshold:
        studies += 1
        if studies > 1000:  # pragma: no cover - unreachable for any sane alpha
            raise ValueError(f"no study count satisfies alpha={alpha} over {n_tests} tests")
    return studies


# ------------------------------------------------------------------------------ the measurement


@dataclass(frozen=True)
class StudyDispersion:
    """The two measured spread bounds for one study, and the pair the tighter one came from."""

    study_accession: str
    samples: int
    expressed_genes: int
    #: Median across genes of the SD of log2(TPM+1) over all of the study's samples. Loose bound:
    #: it contains whatever real condition differences the study's design holds.
    within_study_sd: float
    #: Half the variance of the difference between the study's two most similar samples,
    #: expressed as an SD. Tight bound; `None` when the study has fewer than two samples.
    closest_pair_sd: float | None
    closest_pair: tuple[str, str] | None

    @property
    def max_group_size(self) -> int:
        """The largest balanced two-group split this study could support, if every sample were
        usable in one contrast. An upper bound nothing in the corpus reaches: a study's samples
        are spread over its own conditions and timepoints."""
        return self.samples // 2


@dataclass(frozen=True)
class MatrixLimits:
    """One expression matrix, its studies, and what a contrast within it could detect."""

    reference: str
    path: str
    genes: int
    samples: int
    dispersions: tuple[StudyDispersion, ...]

    @property
    def independent_studies(self) -> int:
        """Distinct SRA studies contributing a sample. The `k` of any meta-analysis over this
        matrix -- and an **upper** bound on the number of independent *groups*, which PLAN.md J.3
        counts instead and which this corpus cannot count at all (see
        :class:`CorpusInventory.experiments_naming_a_publication`)."""
        return len(self.dispersions)

    @property
    def sigma_bracket(self) -> tuple[float, float]:
        """`(tightest, loosest)` measured residual-SD bound across this matrix's studies."""
        tight = [d.closest_pair_sd for d in self.dispersions if d.closest_pair_sd is not None]
        loose = [d.within_study_sd for d in self.dispersions]
        return (min(tight) if tight else 0.0, max(loose) if loose else 0.0)


@dataclass(frozen=True)
class CorpusInventory:
    """The denominators. Every one of these is a count, not an estimate."""

    sra_runs: int
    sra_studies: int
    runs_excluded: int
    #: There is no `approval_state` column on `condition_context`: a context exists only because a
    #: curator wrote it, and what admits a sample to a contrast is `sample.condition_context_id`.
    #: Both are counted, because "contexts exist" and "samples carry one" are different facts and
    #: only the second one gates a contrast.
    condition_contexts: int
    samples_with_condition_context: int
    experiments: int
    experiments_naming_a_publication: int
    correlative_omics_evidence_items: int

    @property
    def contrastable_samples(self) -> int:
        """Samples that may currently enter a contrast.

        CONVENTIONS.md "Conditions": no sample enters a contrast without an approved condition
        context. Derived from the count above rather than stored, so it cannot drift from it.
        """
        return self.samples_with_condition_context


@dataclass(frozen=True)
class LimitsReport:
    inventory: CorpusInventory
    matrices: tuple[MatrixLimits, ...]

    def matrix(self, reference: str) -> MatrixLimits:
        for entry in self.matrices:
            if entry.reference == reference:
                return entry
        known = [m.reference for m in self.matrices]
        raise KeyError(f"no matrix named {reference!r}; have {known}")

    @property
    def largest_matrix(self) -> MatrixLimits:
        return max(self.matrices, key=lambda m: m.samples)

    @property
    def quantified_runs(self) -> int:
        """Runs that reached a matrix. Read off the matrices, not off `acquisition_status`.

        `acquisition_status` has no `'quantified'` state -- the vocabulary stops at `'queued'` --
        so a run's presence in a matrix column is the only record in the atlas that it was ever
        quantified. Counting the status column instead would report zero.
        """
        return sum(matrix.samples for matrix in self.matrices)

    def summary(self) -> str:
        """One paragraph naming the binding constraint rather than the biggest number."""
        biggest = self.largest_matrix
        return (
            f"{self.inventory.sra_runs} runs in {self.inventory.sra_studies} SRA studies; "
            f"{self.quantified_runs} reached an expression matrix. The largest matrix "
            f"({biggest.reference}) holds {biggest.samples} samples from "
            f"{biggest.independent_studies} independent studies. "
            f"{self.inventory.condition_contexts} condition context(s) exist and "
            f"{self.inventory.contrastable_samples} sample(s) carry one, so "
            f"{self.inventory.correlative_omics_evidence_items} correlative_omics evidence "
            f"item(s) exist."
        )


def _median_absolute_sd(values: Sequence[float]) -> float:
    """A median-absolute-deviation SD estimate, scaled to the normal.

    Robust rather than plain, because the difference between two samples contains a minority of
    genes that genuinely changed; a plain SD would let those few genes set the noise level for
    the other six thousand.
    """
    centre = statistics.median(values)
    return 1.4826 * statistics.median([abs(value - centre) for value in values])


def study_dispersions(
    matrix_path: Path,
    study_by_run: Mapping[str, str],
    *,
    expressed_tpm: float = EXPRESSED_TPM,
) -> tuple[StudyDispersion, ...]:
    """Measure both spread bounds for every study represented in `matrix_path`.

    A matrix column whose run is not in `study_by_run` raises rather than being bucketed into an
    "unknown" study: an unattributed sample silently inflates a study's apparent sample count,
    which is the one number this whole module turns on.
    """
    with gzip.open(matrix_path, "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")[1:]
        rows = [
            [float(cell) for cell in line.rstrip("\n").split("\t")[1:]]
            for line in handle
            if line.strip()
        ]

    missing = [run for run in header if run not in study_by_run]
    if missing:
        raise ValueError(
            f"{matrix_path.name}: {len(missing)} sample(s) name no SRA study "
            f"({', '.join(missing[:5])}). A sample with no study cannot be counted toward one."
        )

    columns: dict[str, list[int]] = {}
    for index, run in enumerate(header):
        columns.setdefault(study_by_run[run], []).append(index)

    results: list[StudyDispersion] = []
    for study, indices in sorted(columns.items(), key=lambda item: (-len(item[1]), item[0])):
        expressed = [
            row for row in rows if statistics.median([row[i] for i in indices]) >= expressed_tpm
        ]
        within = (
            statistics.median(
                [statistics.stdev([_log2p1(row[i]) for i in indices]) for row in expressed]
            )
            if len(indices) >= 2 and expressed
            else 0.0
        )
        pair_sd, pair = _closest_pair(expressed, indices, header)
        results.append(
            StudyDispersion(
                study_accession=study,
                samples=len(indices),
                expressed_genes=len(expressed),
                within_study_sd=within,
                closest_pair_sd=pair_sd,
                closest_pair=pair,
            )
        )
    return tuple(results)


def _log2p1(value: float) -> float:
    return math.log2(value + 1.0)


def _closest_pair(
    expressed: Sequence[Sequence[float]], indices: Sequence[int], header: Sequence[str]
) -> tuple[float | None, tuple[str, str] | None]:
    """The most similar pair of samples in a study, and half the SD of their log-ratio.

    Dividing by sqrt(2) converts the spread of a *difference* of two samples into the spread of
    one sample, which is what the power formula wants.
    """
    if len(indices) < 2 or not expressed:
        return None, None
    best: tuple[float, tuple[str, str]] | None = None
    for a in range(len(indices)):
        for b in range(a + 1, len(indices)):
            left, right = indices[a], indices[b]
            spread = _median_absolute_sd(
                [_log2p1(row[left]) - _log2p1(row[right]) for row in expressed]
            )
            if best is None or spread < best[0]:
                best = (spread, (header[left], header[right]))
    if best is None:  # pragma: no cover - guarded by the length check above
        return None, None
    return best[0] / math.sqrt(2.0), best[1]


def corpus_inventory(conn: sqlite3.Connection) -> CorpusInventory:
    """Count what the power arithmetic divides by. Reads only."""

    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return CorpusInventory(
        sra_runs=one("SELECT COUNT(*) FROM sra_run"),
        sra_studies=one("SELECT COUNT(DISTINCT study_accession) FROM sra_run"),
        runs_excluded=one("SELECT COUNT(*) FROM sra_run WHERE acquisition_status = 'excluded'"),
        condition_contexts=one("SELECT COUNT(*) FROM condition_context"),
        samples_with_condition_context=one(
            "SELECT COUNT(*) FROM sample WHERE condition_context_id IS NOT NULL"
        ),
        experiments=one("SELECT COUNT(*) FROM experiment"),
        experiments_naming_a_publication=one(
            "SELECT COUNT(*) FROM experiment WHERE publication_id IS NOT NULL"
        ),
        correlative_omics_evidence_items=one(
            "SELECT COUNT(*) FROM evidence_item "
            "WHERE evidence_type = 'correlative_omics' AND status = 'active'"
        ),
    )


def matrix_limits(
    matrix_path: Path, study_by_run: Mapping[str, str], *, reference: str
) -> MatrixLimits:
    dispersions = study_dispersions(matrix_path, study_by_run)
    with gzip.open(matrix_path, "rt", encoding="utf-8") as handle:
        samples = len(handle.readline().rstrip("\n").split("\t")) - 1
        genes = sum(1 for line in handle if line.strip())
    return MatrixLimits(
        reference=reference,
        path=str(matrix_path),
        genes=genes,
        samples=samples,
        dispersions=dispersions,
    )


def study_by_run(conn: sqlite3.Connection) -> dict[str, str]:
    """`{run accession: SRA study accession}` from the atlas, not from a re-read of the runinfo."""
    return {
        str(row["run_accession"]): str(row["study_accession"])
        for row in conn.execute(
            "SELECT run_accession, study_accession FROM sra_run WHERE study_accession IS NOT NULL"
        )
    }


def build_limits(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    references: Iterable[str] = ("s288c", "ecoli", "lcremoris"),
) -> LimitsReport:
    """Everything the written statement cites, measured in one pass."""
    mapping = study_by_run(conn)
    matrices_dir = Path(settings.matrices_dir)
    matrices: list[MatrixLimits] = []
    for reference in references:
        path = matrices_dir / f"{reference}.tpm.tsv.gz"
        if not path.is_file():
            continue
        matrices.append(matrix_limits(path, mapping, reference=reference))
    if not matrices:
        raise FileNotFoundError(
            f"no TPM matrix under {matrices_dir}. Reporting limits for an empty corpus would "
            f"produce a document that looks measured and is not."
        )
    return LimitsReport(inventory=corpus_inventory(conn), matrices=tuple(matrices))
