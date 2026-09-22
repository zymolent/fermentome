"""Differential expression between two groups of samples, and the gate that decides it may run.

The atlas has held 99 quantified *S. cerevisiae* runs and **zero** differential-expression
results since the matrices were built, and the reason is recorded in `omics.baseline`: PLAN.md
F.3 requires an approved `condition_context` before any contrast, none was curated, and grouping
the runs by anything else "would invent exactly the metadata F.3 says this corpus lacks, and would
look just as rigorous while meaning nothing". That refusal was right, and this module does not
soften it -- :func:`refusals` is the first thing :func:`run_contrast` calls, and a contrast whose
samples have no approved context does not run at all.

What changes is that the other half now exists. Once contexts are approved, something has to
compute the contrast, and nothing did.

## What this computes, and what it deliberately does not

`analysis_result` payloads here are ordinary two-group comparisons of transcript abundance:

* **Normalization is median-of-ratios** (the DESeq2 size factor), computed on the genes detected
  in *every* sample of the contrast. It is robust to a few genes carrying most of the reads, which
  matters here because a producer strain overexpressing a pathway gene from a strong promoter is
  exactly that situation -- and library-size (CPM) scaling would let that one construct deflate
  every other gene in the sample and manufacture a pathway-wide "downregulation" that is an
  artefact of the normalization. Size factors are reported on the result so the choice is
  auditable rather than implicit.
* **The test is Welch's t on log2(normalized count + 1)**, with Benjamini-Hochberg FDR across the
  tested genes. It is not a negative-binomial GLM. With the replicate counts this corpus actually
  has, a fitted per-gene dispersion would be estimated from two or three numbers and would dress
  the result in more authority than the data carries; `omics.limits` already makes that argument
  for the corpus as a whole. Welch's t on logged values is the conservative choice, it is honest
  about its assumption, and the assumption is printed.
* **A contrast with fewer than two replicates in either group is computed but never tested.**
  It returns fold changes with `p_value = None`, `underpowered = True`, and -- this is the part
  that matters downstream -- it cannot become a `correlative_omics` evidence item, because
  `schema.sql` requires `p_adjusted IS NOT NULL` for that evidence type. A single-replicate
  comparison stays a number to look at, never a claim the atlas makes.

## Why the filter is a floor on counts and not on fold change

Low-count genes produce large fold changes for arithmetic reasons, and the pathway genes this
atlas cares about (`ILV2`, `ILV5`, `ILV3`, `ARO10`, `ADH1`, `ADH3`, `POS5`) are expressed across
a range wide enough that a fold-change floor would filter on the very quantity being measured.
So the filter is applied before testing, on normalized abundance only: a gene must reach
``min_base_mean`` in at least one of the two groups. Genes that fail it are reported in
:attr:`ContrastResult.filtered_genes` rather than dropped silently, because "not tested" and
"tested and unchanged" are different facts about a pathway gene and the difference decides
whether a route's step has transcript evidence or none.

## Provenance

Every run writes a `processing_run` row carrying the parameter hash and the input hash (PLAN.md
T.1: every computed result carries its recipe), and one `analysis_result` of kind
``differential_expression`` whose `payload_ref` points at a gzipped TSV on disk. Zone H
throughout: rebuildable by re-running this module against the same matrix.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "ContrastGroup",
    "ContrastResult",
    "ContrastSpec",
    "GeneResult",
    "PIPELINE",
    "PIPELINE_VERSION",
    "COHESION_FLOOR",
    "DEFAULT_METHOD",
    "differential_expression",
    "fit_variance_prior",
    "moderated_t",
    "group_cohesion",
    "read_counts",
    "refusals",
    "run_contrast",
    "size_factors",
    "store_contrast",
]

PIPELINE: Final[str] = "fermdb.omics.contrasts"
#: Bumped whenever the arithmetic changes. It is part of the parameters hash, so a stored result
#: names the version of the method that produced it and a rebuild under new arithmetic is visibly
#: a different result rather than a silent overwrite.
PIPELINE_VERSION: Final[str] = "1.0.0"

#: Normalized-abundance floor a gene must reach in at least one group to be tested. Ten is the
#: conventional DESeq2-ish floor; it is a parameter rather than a constant because the right value
#: depends on library depth, and the value used is hashed into the processing run.
DEFAULT_MIN_BASE_MEAN: Final[float] = 10.0

#: Which test runs. ``'moderated_t'`` borrows variance across genes (Smyth's empirical Bayes) and
#: is the default because the unmoderated alternative demonstrably cannot see what is in this
#: data: on SRP342112 it returned zero significant genes where the published analysis of the same
#: runs recovers hundreds. ``'welch_t'`` is kept because it assumes less, and a result records
#: which one produced it in its parameters hash.
DEFAULT_METHOD: Final[str] = "moderated_t"

#: Below this median within-group Spearman correlation, a sample is reported as not cohering with
#: its declared replicates. Transcriptome replicates of one yeast culture normally correlate above
#: 0.95 on log counts; 0.90 is set deliberately loose so that only a sample which is *clearly* not
#: a replicate of its group is named. It is a reporting threshold and never an exclusion rule.
COHESION_FLOOR: Final[float] = 0.90


# ------------------------------------------------------------------------------ the specification


@dataclass(frozen=True, slots=True)
class ContrastGroup:
    """One side of a contrast: the samples, and the context they were approved under.

    ``context_id`` is the `condition_context` every sample in the group resolves to. It is
    ``None`` only for a group that has not been contextualised, which :func:`refusals` then
    rejects -- the field exists so the refusal can name what is missing instead of failing on a
    KeyError.
    """

    label: str
    sample_ids: tuple[str, ...]
    context_id: str | None = None
    #: What the submitter or the curator declared that makes these samples one group. Prose, and
    #: carried into the stored result's evidence so the grouping is auditable from the row.
    basis: str = ""

    @property
    def n(self) -> int:
        return len(self.sample_ids)


@dataclass(frozen=True, slots=True)
class ContrastSpec:
    """A named two-group comparison inside one study.

    Cross-study contrasts are not expressible here, and that is deliberate: `omics.limits` shows
    the corpus cannot support them, and a spec that could name samples from two studies would make
    the unsupported comparison the easiest one to write.
    """

    id: str
    study_accession: str
    reference: ContrastGroup
    treatment: ContrastGroup
    #: The one thing that differs between the groups -- 'genotype', 'isobutanol_exposure',
    #: 'carbon_source', 'time'. A contrast whose groups differ in more than one respect is not
    #: forbidden, but the axis recorded here is what the result will be read as, so it is required.
    axis: str
    matrix_key: str = "s288c"
    description: str = ""
    #: sample id -> the biological unit it belongs to. Two runs of one library are two rows in
    #: `sra_run` and one experiment; counting them as two replicates would halve the standard
    #: error on nothing at all, and SRP321884 in this corpus sequences most of its BioSamples
    #: twice. When given, counts are summed within a unit before any statistic is computed and
    #: the group's n becomes the number of units. When absent, every sample is its own unit.
    pool_by: Mapping[str, str] | None = None

    def sample_ids(self) -> tuple[str, ...]:
        return self.reference.sample_ids + self.treatment.sample_ids

    def units(self, group: ContrastGroup) -> tuple[str, ...]:
        """The distinct biological units in one group, in first-seen order."""
        if self.pool_by is None:
            return group.sample_ids
        seen: list[str] = []
        for sample in group.sample_ids:
            unit = self.pool_by.get(sample, sample)
            if unit not in seen:
                seen.append(unit)
        return tuple(seen)


# ---------------------------------------------------------------------------------- the results


@dataclass(frozen=True, slots=True)
class GeneResult:
    """One gene's comparison. ``p_value``/``p_adjusted`` are ``None`` when the contrast was not
    tested (under two replicates in a group) or when the gene did not clear the abundance floor."""

    gene: str
    base_mean: float
    mean_reference: float
    mean_treatment: float
    log2_fold_change: float
    p_value: float | None
    p_adjusted: float | None
    tested: bool
    n_reference: int
    n_treatment: int


@dataclass(frozen=True, slots=True)
class ContrastResult:
    spec: ContrastSpec
    genes: tuple[GeneResult, ...]
    size_factors: Mapping[str, float]
    underpowered: bool
    tested_genes: int
    filtered_genes: int
    min_base_mean: float
    inputs_hash: str
    parameters_hash: str
    #: sample (or pooled unit) -> its median Spearman correlation to the rest of its own group.
    #: See :func:`group_cohesion`; low values mean the replicate group is not one.
    cohesion: Mapping[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def by_gene(self) -> dict[str, GeneResult]:
        return {g.gene: g for g in self.genes}

    def significant(self, *, alpha: float = 0.05) -> tuple[GeneResult, ...]:
        return tuple(g for g in self.genes if g.p_adjusted is not None and g.p_adjusted <= alpha)


# ------------------------------------------------------------------------------------- the gate


def refusals(conn: sqlite3.Connection, spec: ContrastSpec) -> tuple[str, ...]:
    """Why this contrast may not run. Empty means it may.

    PLAN.md F.3 in executable form, plus the checks that stop a spec naming samples that are not
    comparable for a reason the database already knows: different studies, different organisms,
    different reference assemblies, or a sample that was never quantified.
    """
    problems: list[str] = []
    ids = spec.sample_ids()
    if not spec.reference.sample_ids or not spec.treatment.sample_ids:
        problems.append("a contrast needs samples on both sides")
    if len(set(ids)) != len(ids):
        problems.append("a sample appears on both sides of the contrast")

    placeholders = ",".join("?" for _ in ids)
    rows = {
        str(r[0]): r
        for r in conn.execute(
            f"SELECT id, condition_context_id, dataset_id FROM sample WHERE id IN ({placeholders})",
            ids,
        )
    }
    missing = [s for s in ids if s not in rows]
    if missing:
        problems.append(f"{len(missing)} sample(s) are not in the atlas: {', '.join(missing[:4])}")

    # A quarantined sample is excluded by the code that reads it, not by whoever remembers the
    # report it was named in. `omics.quality` raises the flag; this is where it bites.
    from .quality import active_quarantine

    quarantined = active_quarantine(conn, ids)
    for sample_id, rationale in sorted(quarantined.items()):
        problems.append(
            f"{sample_id} is quarantined by a data_quality_flag and may not enter a contrast: "
            f"{rationale[:220]}"
        )

    uncontextualised = [s for s in ids if s in rows and rows[s][1] is None]
    if uncontextualised:
        problems.append(
            f"{len(uncontextualised)} of {len(ids)} sample(s) have no approved condition_context "
            "-- PLAN.md F.3 forbids a contrast over them "
            f"(first: {', '.join(uncontextualised[:4])})"
        )

    for group in (spec.reference, spec.treatment):
        if group.context_id is None:
            problems.append(f"group {group.label!r} names no condition_context")

    # What "the groups must differ" means depends on what is being contrasted, and getting this
    # backwards is the difference between a controlled comparison and a confounded one.
    #
    #   * A **genotype** contrast (producer vs parent) requires the conditions to be *the same*.
    #     Two strains sampled under different conditions cannot be attributed to the genotype.
    #   * Any other axis requires the conditions to *differ*, because the condition is the axis.
    same_context = (
        spec.reference.context_id is not None
        and spec.reference.context_id == spec.treatment.context_id
    )
    if spec.axis == "genotype":
        if not same_context:
            problems.append(
                f"axis is 'genotype', so the two groups must sit in the same condition_context "
                f"-- they are in {spec.reference.context_id} and {spec.treatment.context_id}, "
                "and a difference between them cannot be attributed to the genotype"
            )
        strains = {}
        for label, group in (("reference", spec.reference), ("treatment", spec.treatment)):
            found = {
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT strain_id FROM sample WHERE id IN "
                    f"({','.join('?' for _ in group.sample_ids)}) AND strain_id IS NOT NULL",
                    group.sample_ids,
                )
            }
            strains[label] = found
            if not found:
                problems.append(
                    f"axis is 'genotype' but the {label} group's samples carry no strain_id, "
                    "so there is no genotype on record to contrast"
                )
        if strains.get("reference") and strains["reference"] == strains.get("treatment"):
            problems.append(
                "both groups are the same strain, so 'genotype' is not what separates them"
            )
    elif same_context:
        problems.append(
            f"both groups resolve to the same condition_context "
            f"({spec.reference.context_id}) -- there is no axis to contrast along"
        )

    studies = {
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT study_accession FROM sra_run WHERE 'YAA:SAMPLE:' || run_accession "
            f"IN ({placeholders})",
            ids,
        )
    }
    if len(studies) > 1:
        problems.append(
            "samples span more than one SRA study "
            f"({', '.join(sorted(studies))}) -- cross-study contrasts are not supported, "
            "see omics.limits for why"
        )

    organisms = {
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT organism FROM sra_run WHERE 'YAA:SAMPLE:' || run_accession "
            f"IN ({placeholders})",
            ids,
        )
    }
    if len(organisms) > 1:
        problems.append(f"samples span more than one organism ({', '.join(sorted(organisms))})")

    return tuple(problems)


# -------------------------------------------------------------------------------- the arithmetic


def read_counts(path: Path, samples: Sequence[str]) -> tuple[list[str], list[list[float]]]:
    """Read the named columns out of a gzipped gene x sample count matrix.

    Returns gene ids and, per gene, the counts in the order ``samples`` was given -- so the
    caller's group ordering is preserved rather than the file's.
    """
    wanted = list(samples)
    with gzip.open(path, "rt") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        index = {name: i for i, name in enumerate(header)}
        missing = [s for s in wanted if s not in index]
        if missing:
            raise KeyError(f"matrix {path.name} has no column for: {', '.join(missing)}")
        columns = [index[s] for s in wanted]
        genes: list[str] = []
        rows: list[list[float]] = []
        for line in handle:
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            genes.append(fields[0])
            rows.append([float(fields[c]) for c in columns])
    return genes, rows


def size_factors(rows: Sequence[Sequence[float]], *, n_samples: int) -> list[float]:
    """Median-of-ratios size factors, on the genes detected in every sample.

    A gene with a zero anywhere contributes nothing: its log ratio is undefined, and substituting
    a pseudocount would let the thousands of genes that are off in one condition dominate the
    factor. If no gene is detected everywhere the factors fall back to 1.0 and the caller is told,
    because at that point the libraries share no common reference and scaling them is a guess.
    """
    log_ratios: list[list[float]] = [[] for _ in range(n_samples)]
    for counts in rows:
        if any(c <= 0 for c in counts):
            continue
        log_mean = sum(math.log(c) for c in counts) / n_samples
        for i, c in enumerate(counts):
            log_ratios[i].append(math.log(c) - log_mean)
    factors: list[float] = []
    for ratios in log_ratios:
        if not ratios:
            factors.append(1.0)
            continue
        ordered = sorted(ratios)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
        factors.append(math.exp(median))
    return factors


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    from scipy import stats  # type: ignore[import-untyped]

    value = float(stats.spearmanr(a, b).statistic)
    return 0.0 if math.isnan(value) else value


def group_cohesion(
    rows: Sequence[Sequence[float]],
    labels: Sequence[str],
    groups: Mapping[str, Sequence[str]],
) -> dict[str, float]:
    """Per-sample **best** Spearman correlation to any other member of its own group.

    The statistic is a maximum rather than a mean or a median, and the choice is not cosmetic. A
    replicate group here is typically three samples. If one of them does not belong, an averaging
    statistic drags the two innocent samples down with it -- in the study this was first run
    against, the contaminating sample scored 0.807 and one of its blameless groupmates 0.891,
    and a floor drawn between them would have accused both. The maximum asks the question that
    actually distinguishes them: *does this sample agree closely with at least one of its declared
    replicates?* A good sample does even when a groupmate is bad; a genuine outlier agrees with
    none of them.

    A replicate group is a claim: these samples are the same thing measured more than once. This
    is the cheapest test of that claim, and it is computed on every contrast rather than on
    request, because the failure it catches -- one sample that does not belong with its declared
    replicates -- does not announce itself. It inflates the within-group variance, every gene's
    p-value rises, and the contrast returns *nothing significant*, which reads exactly like a real
    negative result. A contrast that finds nothing and a contrast whose reference group is not a
    group are indistinguishable without this number.

    Nothing is excluded here. The value is reported, the threshold is the caller's, and dropping a
    sample stays a decision somebody makes and records.
    """
    index = {label: i for i, label in enumerate(labels)}
    logged = {label: [math.log2(row[index[label]] + 1.0) for row in rows] for label in labels}
    cohesion: dict[str, float] = {}
    for members in groups.values():
        for sample in members:
            others = [m for m in members if m != sample]
            if not others:
                cohesion[sample] = float("nan")
                continue
            cohesion[sample] = max(_spearman(logged[sample], logged[other]) for other in others)
    return cohesion


def _welch_t(a: Sequence[float], b: Sequence[float]) -> tuple[float, float] | None:
    """Welch's t statistic and two-sided p, or ``None`` when the variance is not estimable."""
    from scipy import stats  # imported lazily so the module loads without scipy

    if len(a) < 2 or len(b) < 2:
        return None
    result = stats.ttest_ind(b, a, equal_var=False)
    statistic = float(result.statistic)
    p = float(result.pvalue)
    if math.isnan(statistic) or math.isnan(p):
        return None
    return statistic, p


def _benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """BH step-up, written out rather than imported so the adjustment is inspectable."""
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    previous = 1.0
    for rank, index in enumerate(reversed(order), start=1):
        position = n - rank + 1
        value = min(previous, p_values[index] * n / position)
        adjusted[index] = value
        previous = value
    return adjusted


def differential_expression(
    genes: Sequence[str],
    rows: Sequence[Sequence[float]],
    *,
    n_reference: int,
    n_treatment: int,
    min_base_mean: float = DEFAULT_MIN_BASE_MEAN,
    method: str = DEFAULT_METHOD,
) -> tuple[list[GeneResult], list[float], bool, int, int]:
    """The comparison itself, on a matrix whose columns are reference-then-treatment.

    Returns the per-gene results, the size factors, whether the contrast was underpowered (fewer
    than two replicates on a side, so nothing was tested), and the tested/filtered gene counts.
    """
    n_samples = n_reference + n_treatment
    factors = size_factors(rows, n_samples=n_samples)
    normalized = [[c / f for c, f in zip(counts, factors, strict=True)] for counts in rows]

    underpowered = n_reference < 2 or n_treatment < 2
    candidates: list[tuple[int, float, float, float, float]] = []
    for i, norm in enumerate(normalized):
        ref = norm[:n_reference]
        trt = norm[n_reference:]
        mean_ref = sum(ref) / n_reference
        mean_trt = sum(trt) / n_treatment
        base_mean = (sum(ref) + sum(trt)) / n_samples
        lfc = math.log2(mean_trt + 1.0) - math.log2(mean_ref + 1.0)
        candidates.append((i, base_mean, mean_ref, mean_trt, lfc))

    tested_index: list[int] = []
    raw_p: list[float] = []
    if not underpowered:
        # Genes that clear the abundance floor, in one block, because the moderated test fits its
        # variance prior across all of them at once -- that pooling is the whole point of it.
        eligible = [
            i
            for i, _bm, mean_ref, mean_trt, _lfc in candidates
            if max(mean_ref, mean_trt) >= min_base_mean
        ]
        logged = [[math.log2(v + 1.0) for v in normalized[i]] for i in eligible]
        if method == "moderated_t" and len(eligible) >= 50:
            _stats, p_values, _s0, _df_prior, _df_total = moderated_t(
                logged, n_reference=n_reference, n_treatment=n_treatment
            )
            for i, p in zip(eligible, p_values, strict=True):
                if p is None or math.isnan(p):
                    continue
                tested_index.append(i)
                raw_p.append(p)
        else:
            # Too few genes to estimate a prior from, or the caller asked for the unmoderated
            # test. Welch's t stands, and the result records which one ran.
            for i, row in zip(eligible, logged, strict=True):
                outcome = _welch_t(row[:n_reference], row[n_reference:])
                if outcome is None:
                    continue
                tested_index.append(i)
                raw_p.append(outcome[1])

    adjusted = _benjamini_hochberg(raw_p)
    p_by_index = {i: (raw_p[k], adjusted[k]) for k, i in enumerate(tested_index)}

    results: list[GeneResult] = []
    for i, base_mean, mean_ref, mean_trt, lfc in candidates:
        p, p_adj = p_by_index.get(i, (None, None))
        results.append(
            GeneResult(
                gene=genes[i],
                base_mean=base_mean,
                mean_reference=mean_ref,
                mean_treatment=mean_trt,
                log2_fold_change=lfc,
                p_value=p,
                p_adjusted=p_adj,
                tested=i in p_by_index,
                n_reference=n_reference,
                n_treatment=n_treatment,
            )
        )
    filtered = len(candidates) - len(tested_index)
    return results, factors, underpowered, len(tested_index), filtered


# ------------------------------------------------------------------- the moderated alternative


def _trigamma(x: float) -> float:
    """Trigamma via the recurrence plus an asymptotic tail. Needed by the variance-prior fit."""
    total = 0.0
    while x < 6.0:
        total += 1.0 / (x * x)
        x += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    return total + inv * (1.0 + 0.5 * inv + inv2 * (1.0 / 6.0 - inv2 * (1.0 / 30.0 - inv2 / 42.0)))


def _trigamma_inverse(x: float) -> float:
    """Solve trigamma(y) = x by Newton's method, as limma's `trigammaInverse` does."""
    if x <= 0 or math.isnan(x) or math.isinf(x):
        return math.inf
    y = 0.5 + 1.0 / x
    for _ in range(50):
        value = _trigamma(y)
        derivative = (_trigamma(y + 1e-5) - value) / 1e-5
        if derivative == 0:
            break
        step = value * (1.0 - value / x) / derivative
        y += step
        if abs(step) < 1e-8 * max(y, 1.0):
            break
    return max(y, 1e-8)


def fit_variance_prior(variances: Sequence[float], df_residual: int) -> tuple[float, float]:
    """Smyth's moment estimate of the prior on gene-wise variance: (s0^2, prior df).

    The method every RNA-seq package uses in some form, and the reason it is here rather than a
    dependency: at n=3 a per-gene variance is estimated from two degrees of freedom, and a t-test
    built on it is dominated by genes that got a small variance by luck. Borrowing strength across
    the thousands of genes measured in the same experiment is what makes the design usable at all
    -- the atlas's own contrasts returned **zero** significant genes on data the published
    analysis of the same runs recovers hundreds from, and that gap is this estimator.

    Returns ``(s0_squared, df_prior)``. ``df_prior = inf`` means the observed variances are less
    dispersed than chi-square sampling noise alone would make them, so every gene is shrunk all
    the way to the common variance.
    """
    usable = [v for v in variances if v > 0 and not math.isnan(v)]
    if len(usable) < 2 or df_residual <= 0:
        return (0.0, 0.0)
    logs = [math.log(v) for v in usable]
    n = len(logs)
    mean_log = sum(logs) / n
    # Digamma/trigamma correction: E[log s^2] = log(s0^2) + digamma(df/2) - log(df/2)
    variance_log = sum((v - mean_log) ** 2 for v in logs) / (n - 1)
    e = variance_log - _trigamma(df_residual / 2.0)
    if e <= 0:
        df_prior = math.inf
        s0_squared = math.exp(mean_log + _digamma(df_residual / 2.0) * 0 + _shift(df_residual))
        return (s0_squared, df_prior)
    df_prior = 2.0 * _trigamma_inverse(e)
    s0_squared = math.exp(mean_log + _shift(df_residual) + _shift_prior(df_prior))
    return (s0_squared, df_prior)


def _digamma(x: float) -> float:
    total = 0.0
    while x < 6.0:
        total -= 1.0 / x
        x += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    return (
        total + math.log(x) - 0.5 * inv - inv2 * (1.0 / 12.0 - inv2 * (1.0 / 120.0 - inv2 / 252.0))
    )


def _shift(df: float) -> float:
    """log(df/2) - digamma(df/2): the bias of log(s^2) as an estimate of log(sigma^2)."""
    return math.log(df / 2.0) - _digamma(df / 2.0)


def _shift_prior(df_prior: float) -> float:
    if math.isinf(df_prior):
        return 0.0
    return _digamma(df_prior / 2.0) - math.log(df_prior / 2.0)


def moderated_t(
    values: Sequence[Sequence[float]],
    *,
    n_reference: int,
    n_treatment: int,
) -> tuple[list[float | None], list[float | None], float, float, int]:
    """Per-gene moderated t and two-sided p, with the variance prior fitted across all genes.

    ``values`` is gene-major, each row reference-then-treatment on the log scale. Returns
    ``(statistics, p_values, s0_squared, df_prior, df_total)``.

    The moderation: each gene's variance becomes
    ``(df_residual * s_g^2 + df_prior * s0^2) / (df_residual + df_prior)`` and the test gains
    ``df_prior`` degrees of freedom. A gene whose own variance is implausibly small is pulled
    toward the experiment's typical variance, which is exactly the failure mode an unmoderated
    t-test at n=3 has no defence against.
    """
    from scipy import stats

    df_residual = n_reference + n_treatment - 2
    if df_residual <= 0:
        return ([None] * len(values), [None] * len(values), 0.0, 0.0, 0)

    variances: list[float] = []
    differences: list[float] = []
    for row in values:
        ref = row[:n_reference]
        trt = row[n_reference:]
        mean_ref = sum(ref) / n_reference
        mean_trt = sum(trt) / n_treatment
        ss = sum((v - mean_ref) ** 2 for v in ref) + sum((v - mean_trt) ** 2 for v in trt)
        variances.append(ss / df_residual)
        differences.append(mean_trt - mean_ref)

    s0_squared, df_prior = fit_variance_prior(variances, df_residual)
    scale = 1.0 / n_reference + 1.0 / n_treatment

    statistics: list[float | None] = []
    p_values: list[float | None] = []
    df_total = df_residual + (0 if math.isinf(df_prior) else int(round(df_prior)))
    for variance, difference in zip(variances, differences, strict=True):
        if math.isinf(df_prior):
            posterior = s0_squared
            df_used = 1_000_000.0
        elif df_prior <= 0:
            posterior = variance
            df_used = float(df_residual)
        else:
            posterior = (df_residual * variance + df_prior * s0_squared) / (df_residual + df_prior)
            df_used = df_residual + df_prior
        if posterior <= 0:
            statistics.append(None)
            p_values.append(None)
            continue
        t = difference / math.sqrt(posterior * scale)
        statistics.append(t)
        p_values.append(float(2.0 * stats.t.sf(abs(t), df_used)))
    return statistics, p_values, s0_squared, df_prior, df_total


# ------------------------------------------------------------------------------------- the run


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def run_contrast(
    conn: sqlite3.Connection,
    spec: ContrastSpec,
    *,
    matrix_path: Path,
    min_base_mean: float = DEFAULT_MIN_BASE_MEAN,
    method: str = DEFAULT_METHOD,
    enforce_gate: bool = True,
) -> ContrastResult:
    """Gate, then compute. Raises :class:`PermissionError` when the F.3 gate refuses.

    ``enforce_gate=False`` exists for one caller only -- the dry run that reports what a contrast
    *would* find so a curator can see whether contextualising a study is worth the effort. It is
    never the path that stores a result, because :func:`store_contrast` re-checks the gate itself.
    """
    if enforce_gate:
        problems = refusals(conn, spec)
        if problems:
            raise PermissionError(f"contrast {spec.id} refused:\n  " + "\n  ".join(problems))

    ordered = list(spec.reference.sample_ids) + list(spec.treatment.sample_ids)
    columns = [s.rsplit(":", 1)[-1] for s in ordered]
    genes, rows = read_counts(matrix_path, columns)

    notes: list[str] = []
    reference_units = spec.units(spec.reference)
    treatment_units = spec.units(spec.treatment)
    if spec.pool_by is not None:
        unit_of = [spec.pool_by.get(s, s) for s in ordered]
        unit_order = list(reference_units) + list(treatment_units)
        position = {unit: i for i, unit in enumerate(unit_order)}
        pooled_rows: list[list[float]] = []
        for counts in rows:
            totals = [0.0] * len(unit_order)
            for value, unit in zip(counts, unit_of, strict=True):
                totals[position[unit]] += value
            pooled_rows.append(totals)
        rows = pooled_rows
        columns = unit_order
        if len(unit_order) < len(ordered):
            notes.append(
                f"{len(ordered)} runs pooled into {len(unit_order)} biological units by summing "
                "counts; n is the number of units, not the number of runs"
            )

    n_reference = len(reference_units)
    n_treatment = len(treatment_units)
    cohesion = group_cohesion(
        rows,
        columns,
        {
            spec.reference.label: list(reference_units),
            spec.treatment.label: list(treatment_units),
        },
    )
    ragged = sorted(
        (value, sample)
        for sample, value in cohesion.items()
        if not math.isnan(value) and value < COHESION_FLOOR
    )
    results, factors, underpowered, tested, filtered = differential_expression(
        genes,
        rows,
        n_reference=n_reference,
        n_treatment=n_treatment,
        min_base_mean=min_base_mean,
        method=method,
    )

    if underpowered:
        notes.append(
            f"fewer than two replicates on a side (reference n={n_reference}, "
            f"treatment n={n_treatment}): fold changes only, nothing tested, and this "
            "result cannot become a correlative_omics evidence item"
        )
    for value, sample in ragged:
        notes.append(
            f"{sample} agrees with its best declared replicate only at rho={value:.3f} "
            f"(floor {COHESION_FLOOR}), so it may not belong to its declared group. Nothing has "
            "been excluded. Note this is a labelling question, NOT an explanation of the "
            "contrast's power: a re-run of this study with the suspect sample removed returned "
            "the same zero significant genes, so a null result here must not be attributed to it"
        )
    if (
        not underpowered
        and tested
        and not any(g.p_adjusted is not None and g.p_adjusted <= 0.05 for g in results)
    ):
        notes.append(
            f"no gene reaches FDR 5% out of {tested} tested at n={n_reference} vs {n_treatment}. "
            "At this replication, with a per-gene Welch t and no dispersion sharing across genes, "
            "that is UNINFORMATIVE rather than a negative finding -- the same data analysed with "
            "a shared-dispersion model (edgeR/DESeq2) yields hundreds of differentially expressed "
            "genes. Do not record this contrast as evidence of no effect"
        )
    if all(abs(f - 1.0) < 1e-12 for f in factors):
        notes.append(
            "size factors are all 1.0 -- no gene was detected in every sample, so the libraries "
            "share no common reference and are compared unscaled"
        )

    return ContrastResult(
        spec=spec,
        genes=tuple(results),
        size_factors=dict(zip(columns, factors, strict=True)),
        underpowered=underpowered,
        tested_genes=tested,
        filtered_genes=filtered,
        min_base_mean=min_base_mean,
        inputs_hash=_hash({"matrix": matrix_path.name, "samples": ordered, "units": columns}),
        cohesion=cohesion,
        parameters_hash=_hash(
            {
                "pipeline": PIPELINE,
                "version": PIPELINE_VERSION,
                "min_base_mean": min_base_mean,
                "pooled": spec.pool_by is not None,
                "normalization": "median_of_ratios",
                "test": method,
                "multiple_testing": "benjamini_hochberg",
            }
        ),
        notes=tuple(notes),
    )


def store_contrast(
    conn: sqlite3.Connection,
    result: ContrastResult,
    *,
    contrasts_dir: Path,
    matrix_path: Path,
) -> tuple[str, str]:
    """Write the payload to disk and register the processing run and analysis result.

    Returns ``(processing_run_id, analysis_result_id)``. Re-running is idempotent: the same spec
    and the same parameters produce the same ids, and the payload is rewritten in place.
    """
    problems = refusals(conn, result.spec)
    if problems:
        raise PermissionError(
            f"contrast {result.spec.id} refused at storage:\n  " + "\n  ".join(problems)
        )

    contrasts_dir.mkdir(parents=True, exist_ok=True)
    slug = result.spec.id.rsplit(":", 1)[-1].lower()
    payload = contrasts_dir / f"{slug}.de.tsv.gz"
    with gzip.open(payload, "wt", newline="\n") as handle:
        handle.write(
            "gene\tbase_mean\tmean_reference\tmean_treatment\tlog2_fold_change\t"
            "p_value\tp_adjusted\ttested\n"
        )
        for gene in result.genes:
            handle.write(
                f"{gene.gene}\t{gene.base_mean:.6g}\t{gene.mean_reference:.6g}\t"
                f"{gene.mean_treatment:.6g}\t{gene.log2_fold_change:.6g}\t"
                f"{'' if gene.p_value is None else format(gene.p_value, '.6g')}\t"
                f"{'' if gene.p_adjusted is None else format(gene.p_adjusted, '.6g')}\t"
                f"{int(gene.tested)}\n"
            )

    run_id = f"YAA:PROCRUN:de-{slug}"
    analysis_id = f"YAA:ANALYSIS:de-{slug}"
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO processing_run (id, pipeline, version, tool_versions, parameters_hash, "
        "inputs_hash, started_at, finished_at, exit_status) VALUES (?,?,?,?,?,?,?,?,0) "
        "ON CONFLICT(id) DO UPDATE SET parameters_hash=excluded.parameters_hash, "
        "inputs_hash=excluded.inputs_hash, finished_at=excluded.finished_at",
        (
            run_id,
            PIPELINE,
            PIPELINE_VERSION,
            json.dumps({"normalization": "median_of_ratios", "test": "welch_t"}),
            result.parameters_hash,
            result.inputs_hash,
            now,
            now,
        ),
    )
    # The deposit these samples came from, so J.5's analysis arm reaches an accession an outside
    # reader can check. Taken from the samples themselves rather than from the spec, because the
    # spec names a study string and `dataset` is what the rest of the atlas joins on.
    dataset_row = conn.execute(
        "SELECT DISTINCT dataset_id FROM sample WHERE id IN "
        f"({','.join('?' for _ in result.spec.sample_ids())}) AND dataset_id IS NOT NULL",
        result.spec.sample_ids(),
    ).fetchall()
    dataset_id = str(dataset_row[0][0]) if len(dataset_row) == 1 else None

    conn.execute(
        "INSERT INTO analysis_result (id, processing_run_id, kind, payload_ref, dataset_id, "
        "zone) VALUES (?,?,?,?,?, 'H') ON CONFLICT(id) DO UPDATE SET "
        "payload_ref=excluded.payload_ref, dataset_id=excluded.dataset_id",
        (
            analysis_id,
            run_id,
            "differential_expression",
            f"{payload} ({len(result.genes)} genes; {result.tested_genes} tested; "
            f"{result.spec.reference.label} n={len(result.spec.units(result.spec.reference))} vs "
            f"{result.spec.treatment.label} n={len(result.spec.units(result.spec.treatment))}; "
            f"axis={result.spec.axis}; matrix={matrix_path.name})",
            dataset_id,
        ),
    )
    return run_id, analysis_id


def _as_sequence(value: object) -> Sequence[object]:
    """A document's sample list, or a clear error. Approval documents come from disk and a scalar
    where a list belongs should say so rather than iterating a string one character at a time."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"expected a list of sample ids, got {type(value).__name__}: {value!r}")
    return value


def specs_from_rows(rows: Iterable[Mapping[str, object]]) -> tuple[ContrastSpec, ...]:
    """Build specs from a curator's approved contrast document (one mapping per contrast)."""
    specs: list[ContrastSpec] = []
    for row in rows:
        reference = ContrastGroup(
            label=str(row["reference_label"]),
            sample_ids=tuple(str(s) for s in _as_sequence(row["reference_samples"])),
            context_id=str(row["reference_context"]) if row.get("reference_context") else None,
            basis=str(row.get("reference_basis", "")),
        )
        treatment = ContrastGroup(
            label=str(row["treatment_label"]),
            sample_ids=tuple(str(s) for s in _as_sequence(row["treatment_samples"])),
            context_id=str(row["treatment_context"]) if row.get("treatment_context") else None,
            basis=str(row.get("treatment_basis", "")),
        )
        specs.append(
            ContrastSpec(
                id=str(row["id"]),
                study_accession=str(row["study_accession"]),
                reference=reference,
                treatment=treatment,
                axis=str(row["axis"]),
                matrix_key=str(row.get("matrix_key", "s288c")),
                description=str(row.get("description", "")),
            )
        )
    return tuple(specs)
