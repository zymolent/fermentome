"""Detectors that raise a recorded doubt about a row, and never repair one.

A deposit's declared metadata is a claim, and claims can be wrong. SRP342112 declares
`SRR16481343` as the parent strain at 26 h; its transcriptome resembles a *producer* at 10 h more
closely than it resembles either of its own declared replicates. Something in that deposit is
mislabelled.

**The tempting fix is the one thing this module will not do.** Relabelling the run to whatever it
resembles uses the expression data to repair the metadata, and then analyses the expression data
under the repaired metadata. The evidence for the relabelling and the result that depends on it
come from the same numbers, so the correction can never be contradicted by them. That is
circular, and at n=3 it is circular in a direction that manufactures significance: moving one
sample out of a group shrinks that group's variance, which is exactly the quantity every p-value
in the contrast divides by.

So the detectors below **quarantine**. The row stays as the submitter deposited it, a
`data_quality_flag` records the statistic and the threshold beside it, and
`omics.contrasts.refusals` consults those flags so the sample cannot enter a future contrast
because somebody forgot about it. What to do next -- exclude, re-derive, or write to the
submitting authors -- stays a person's decision, and `resembles` gives them the lead without
acting on it.

## Gate A: replicate coherence

For each sample, two numbers on log counts:

* ``inside`` -- its **best** Spearman correlation to another sample in its own declared cell
  (same study, same condition context, same strain);
* ``outside`` -- its best correlation to any sample in a *different* cell.

``margin = inside - outside``. A correctly labelled sample agrees with its own replicates at
least as well as with anything else, so its margin is at or above zero. A mislabelled one is
negative. The cut is a **robust z** against the study's own median and MAD, so the threshold
adapts to how tight that study's replicates happen to be instead of importing a constant from
another experiment.

**Both halves use a maximum, not a mean**, and that is the part that took two attempts to get
right. A mean-based version flags the *innocent cell-mates* of a bad sample, because the outlier
drags their average down with it -- in the study this was built against it accused two blameless
runs alongside the real one. Asking "does this sample agree closely with **at least one** of its
declared replicates?" separates them cleanly: a good sample has a good partner even when a third
group member is wrong.

The identity of the best outside cell classifies the fault for free. A different condition context
and the same strain says the *timepoint* label slipped; the same context and a different strain
says the *genotype* label did.

## Gate B: declared-genotype marker consistency

Gate A cannot see a whole block of labels shifted by one position, because every sample still has
a well-correlated partner -- they are simply each other's. Gate B checks the declaration instead
of the neighbourhood: where a declared genotype names a gene the matrix actually measures, the
study's samples should fall into two clearly separated groups on that gene, and each sample should
sit on the side its own declaration puts it.

It **abstains** rather than guessing whenever the evidence is not there: no bimodal split, a gap
below ``MIN_MARKER_FOLD``, or a gene the quantification cannot resolve. In the study this was
built against it abstains on ILV2, ILV5 and ARO10 -- correctly, because a construct-augmented
reference is needed before any of those rows means anything (see
`metabolic.transcript_support`, ``confounded_by_construct``).
"""

from __future__ import annotations

import gzip
import hashlib
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "MARGIN_Z_FLOOR",
    "MIN_MARKER_FOLD",
    "QualityFlag",
    "active_quarantine",
    "coherence_flags",
    "marker_flags",
    "redundancy_flags",
    "robust_z",
    "write_flags",
]

DETECTOR_COHERENCE: Final[str] = "omics.quality:replicate_coherence"
DETECTOR_MARKER: Final[str] = "omics.quality:genotype_marker"

#: A sample is quarantined when its coherence margin sits this many robust standard deviations
#: below its study's median margin. Three is conventional and deliberately not tuned to the
#: sample it was first run against -- a threshold chosen to catch one known case is not a rule.
MARGIN_Z_FLOOR: Final[float] = -3.0

#: The minimum fold gap between the two modes of a marker gene before Gate B will read a side off
#: it. Below this the gene is reporting noise and the gate abstains.
MIN_MARKER_FOLD: Final[float] = 4.0


@dataclass(frozen=True, slots=True)
class QualityFlag:
    target_type: str
    target_id: str
    kind: str
    severity: str
    detector: str
    rationale: str
    statistic: float | None = None
    threshold: float | None = None
    resembles: str | None = None

    @property
    def id(self) -> str:
        digest = hashlib.sha256(
            f"{self.target_type}|{self.target_id}|{self.kind}|{self.detector}".encode()
        ).hexdigest()[:24]
        return f"YAA:DQFLAG:{digest}"


# --------------------------------------------------------------------------------- the statistic


def robust_z(values: Sequence[float]) -> list[float]:
    """(x - median) / (1.4826 * MAD), with a zero-MAD fallback that flags nothing.

    The 1.4826 makes the MAD a consistent estimator of the standard deviation for normal data.
    When every value is identical the MAD is zero and every z would be infinite, so the fallback
    returns zeros: a study whose samples are indistinguishable gives no evidence that any one of
    them is an outlier.
    """
    ordered = sorted(values)
    if not ordered:
        return []

    def median(xs: Sequence[float]) -> float:
        mid = len(xs) // 2
        return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2.0

    centre = median(ordered)
    deviations = sorted(abs(v - centre) for v in values)
    mad = median(deviations)
    if mad <= 0:
        return [0.0 for _ in values]
    return [(v - centre) / (1.4826 * mad) for v in values]


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    from scipy import stats  # type: ignore[import-untyped]

    value = float(stats.spearmanr(a, b).statistic)
    return 0.0 if math.isnan(value) else value


def _read_logged(matrix_path: Path, columns: Sequence[str]) -> dict[str, list[float]]:
    wanted = set(columns)
    collected: dict[str, list[float]] = {c: [] for c in columns}
    with gzip.open(matrix_path, "rt") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        index = {name: i for i, name in enumerate(header) if name in wanted}
        for line in handle:
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            for name, position in index.items():
                collected[name].append(math.log2(float(fields[position]) + 1.0))
    return {name: values for name, values in collected.items() if values}


# ------------------------------------------------------------------------------------- gate A


def coherence_flags(
    conn: sqlite3.Connection,
    *,
    matrix_path: Path,
    study_accession: str,
    raised_by: str,
    actor_kind: str = "agent",
) -> list[QualityFlag]:
    """Gate A over one study. Returns flags; writes nothing."""
    rows = list(
        conn.execute(
            "SELECT r.run_accession, s.condition_context_id, s.strain_id, "
            "COALESCE(st.canonical_name, s.strain_id) "
            "FROM sra_run r JOIN sample s ON s.id = 'YAA:SAMPLE:' || r.run_accession "
            "LEFT JOIN strain st ON st.id = s.strain_id "
            "WHERE r.study_accession = ? AND s.condition_context_id IS NOT NULL "
            "AND s.strain_id IS NOT NULL",
            (study_accession,),
        )
    )
    if len(rows) < 4:
        return []

    cell_of = {str(r[0]): (str(r[1]), str(r[2])) for r in rows}
    label_of = {str(r[0]): f"{r[3]} @ {str(r[1])[-6:]}" for r in rows}
    logged = _read_logged(matrix_path, list(cell_of))
    runs = [r for r in cell_of if r in logged]
    if len(runs) < 4:
        return []

    correlation: dict[tuple[str, str], float] = {}
    for i, left in enumerate(runs):
        for right in runs[i + 1 :]:
            value = _spearman(logged[left], logged[right])
            correlation[(left, right)] = value
            correlation[(right, left)] = value

    margins: dict[str, tuple[float, float, str | None]] = {}
    for run in runs:
        inside = [correlation[(run, o)] for o in runs if o != run and cell_of[o] == cell_of[run]]
        outside = [(correlation[(run, o)], o) for o in runs if cell_of[o] != cell_of[run]]
        if not inside or not outside:
            continue
        best_outside, best_outside_run = max(outside, key=lambda pair: pair[0])
        margins[run] = (max(inside) - best_outside, best_outside, label_of[best_outside_run])

    if len(margins) < 4:
        return []
    ordered_runs = sorted(margins)
    scores = robust_z([margins[r][0] for r in ordered_runs])

    flags: list[QualityFlag] = []
    for run, z in zip(ordered_runs, scores, strict=True):
        if z >= MARGIN_Z_FLOOR:
            continue
        margin, best_outside, resembles = margins[run]
        same_context = False
        for other in runs:
            if label_of[other] == resembles:
                same_context = cell_of[other][0] == cell_of[run][0]
                break
        fault = (
            "the best match is a different strain under the SAME condition, which points at the "
            "genotype label"
            if same_context
            else "the best match is a different condition, which points at the timepoint or "
            "treatment label"
        )
        flags.append(
            QualityFlag(
                target_type="sample",
                target_id=f"YAA:SAMPLE:{run}",
                kind="mislabel_suspected",
                severity="quarantine",
                detector=DETECTOR_COHERENCE,
                statistic=round(z, 3),
                threshold=MARGIN_Z_FLOOR,
                resembles=resembles,
                rationale=(
                    f"coherence margin {margin:+.3f} (robust z {z:.1f}) in {study_accession}: it "
                    f"agrees with its own declared replicates less well than with {resembles} "
                    f"(rho {best_outside:.3f}). {fault}. Quarantined, not relabelled -- the "
                    "expression data must not be used to repair the metadata it is then analysed "
                    "under. Clear this flag, or confirm it, after checking the deposit"
                ),
            )
        )
    return flags


# ------------------------------------------------------------------------------------- gate B


def marker_flags(
    conn: sqlite3.Connection,
    *,
    matrix_path: Path,
    study_accession: str,
    raised_by: str,
    symbols: Mapping[str, str],
    confounded_genes: frozenset[str] = frozenset(),
    actor_kind: str = "agent",
) -> list[QualityFlag]:
    """Gate B over one study: does each sample sit on the side its own declaration claims?

    ``confounded_genes`` names genes whose rows cannot be trusted as markers because the build
    carries its own copy and the reference does not. They are skipped outright -- reading a side
    off a spillover signal would turn a quantification artefact into a metadata accusation.
    """
    rows = list(
        conn.execute(
            "SELECT r.run_accession, s.strain_id, COALESCE(g.parsed_json, ''), "
            "COALESCE(st.canonical_name, s.strain_id) "
            "FROM sra_run r JOIN sample s ON s.id = 'YAA:SAMPLE:' || r.run_accession "
            "LEFT JOIN strain st ON st.id = s.strain_id "
            "LEFT JOIN genotype g ON g.strain_id = s.strain_id "
            "WHERE r.study_accession = ? AND s.strain_id IS NOT NULL",
            (study_accession,),
        )
    )
    if len(rows) < 4:
        return []

    import json

    declares: dict[str, frozenset[str]] = {}
    names: dict[str, str] = {}
    for run, _strain, parsed, name in rows:
        names[str(run)] = str(name)
        try:
            payload = json.loads(str(parsed)) if parsed else {}
        except ValueError:
            payload = {}
        declares[str(run)] = frozenset((payload.get("localization") or {}).keys())

    by_symbol = {symbol: locus for locus, symbol in symbols.items()}
    candidates = {g for genes in declares.values() for g in genes} - confounded_genes
    if not candidates:
        return []

    values = _read_matrix_rows(
        matrix_path, list(declares), {by_symbol[g] for g in candidates if g in by_symbol}
    )
    flags: list[QualityFlag] = []
    for gene in sorted(candidates):
        locus = by_symbol.get(gene)
        if locus is None or locus not in values:
            continue
        readings = values[locus]
        ordered = sorted(readings.items(), key=lambda kv: kv[1])
        gaps = [
            (ordered[i + 1][1] - ordered[i][1], i)
            for i in range(len(ordered) - 1)
            if ordered[i][1] > 0
        ]
        if not gaps:
            continue
        gap, position = max(gaps)
        low_top = ordered[position][1]
        high_bottom = ordered[position + 1][1]
        if low_top <= 0 or high_bottom / max(low_top, 1e-9) < MIN_MARKER_FOLD:
            continue  # abstain: no clean split, so this gene says nothing about any label
        high_side = {run for run, _ in ordered[position + 1 :]}
        for run in declares:
            if run not in readings:
                continue
            declared_high = gene in declares[run]
            observed_high = run in high_side
            if declared_high == observed_high:
                continue
            flags.append(
                QualityFlag(
                    target_type="sample",
                    target_id=f"YAA:SAMPLE:{run}",
                    kind="mislabel_suspected",
                    severity="quarantine",
                    detector=f"{DETECTOR_MARKER}:{gene}",
                    statistic=round(readings[run], 3),
                    threshold=round(high_bottom, 3),
                    resembles=None,
                    rationale=(
                        f"{study_accession} splits cleanly on {gene} "
                        f"({high_bottom / max(low_top, 1e-9):.1f}-fold gap), and {names[run]} "
                        f"sits on the "
                        f"{'low' if declared_high else 'high'} side while its declared genotype "
                        f"{'names' if declared_high else 'does not name'} {gene}. Quarantined "
                        "pending a check of the deposit; the declaration is not overwritten"
                    ),
                )
            )
    return flags


def _read_matrix_rows(
    matrix_path: Path, columns: Sequence[str], loci: set[str]
) -> dict[str, dict[str, float]]:
    wanted = set(columns)
    out: dict[str, dict[str, float]] = {}
    with gzip.open(matrix_path, "rt") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        index = {name: i for i, name in enumerate(header) if name in wanted}
        totals = {name: 0.0 for name in index}
        rows: dict[str, dict[str, float]] = {}
        for line in handle:
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            for name, position in index.items():
                totals[name] += float(fields[position])
            if fields[0] in loci:
                rows[fields[0]] = {
                    name: float(fields[position]) for name, position in index.items()
                }
    for locus, counts in rows.items():
        out[locus] = {
            name: (value / totals[name] * 1e6 if totals[name] else 0.0)
            for name, value in counts.items()
        }
    return out


# --------------------------------------------------------------------------------- redundancy


def redundancy_flags(
    conn: sqlite3.Connection,
    *,
    study_accession: str | None = None,
    raised_by: str = "",
    actor_kind: str = "agent",
) -> list[QualityFlag]:
    """Runs that are not independent observations, recorded as such.

    Two sequencing runs of one BioSample are one library measured twice. They are perfectly
    legitimate data -- `omics.contrasts` pools them and counts the *unit*, not the run -- but the
    redundancy is a property of the corpus that should be queryable rather than rediscovered by
    whichever analysis next divides by n. SRP321884 deposits 46 runs across 24 BioSamples, and an
    analysis that took 46 as its replicate count would halve every standard error on nothing.

    Severity is ``warn``, never ``quarantine``. The rows are usable and excluding them would
    discard real sequencing depth; what is wrong is only the arithmetic somebody might do with
    them, and a flag is how the atlas says so.
    """
    clause = "WHERE r.biosample IS NOT NULL AND r.biosample <> ''"
    params: tuple[str, ...] = ()
    if study_accession:
        clause += " AND r.study_accession = ?"
        params = (study_accession,)

    groups: dict[str, list[str]] = {}
    for run, biosample in conn.execute(
        f"SELECT r.run_accession, r.biosample FROM sra_run r {clause}", params
    ):
        groups.setdefault(str(biosample), []).append(str(run))

    flags: list[QualityFlag] = []
    for biosample, runs in sorted(groups.items()):
        if len(runs) < 2:
            continue
        for run in sorted(runs):
            flags.append(
                QualityFlag(
                    target_type="sra_run",
                    target_id=f"YAA:SRARUN:{run}",
                    kind="technical_replicate",
                    severity="warn",
                    detector="omics.quality:biosample_redundancy",
                    statistic=float(len(runs)),
                    threshold=1.0,
                    resembles=biosample,
                    rationale=(
                        f"{len(runs)} runs share BioSample {biosample} "
                        f"({', '.join(sorted(runs))}), so they are one biological observation "
                        "sequenced more than once. Usable, and already pooled by "
                        "omics.contrasts -- but counting these runs as independent replicates "
                        "would understate every standard error computed from them"
                    ),
                )
            )
    return flags


# -------------------------------------------------------------------------------------- storage


def write_flags(
    conn: sqlite3.Connection,
    flags: Sequence[QualityFlag],
    *,
    raised_by: str,
    actor_kind: str = "agent",
) -> tuple[int, int]:
    """Insert or refresh flags. Returns (written, left alone because already resolved).

    A flag a person has already `confirmed` or `cleared` is never silently reopened by a re-run:
    the detector's job is to notice, and a decision about what it noticed outranks noticing it
    again.
    """
    written = 0
    respected = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for flag in flags:
        existing = conn.execute(
            "SELECT status FROM data_quality_flag WHERE target_type = ? AND target_id = ? "
            "AND kind = ? AND detector = ?",
            (flag.target_type, flag.target_id, flag.kind, flag.detector),
        ).fetchone()
        if existing is not None and str(existing[0]) != "active":
            respected += 1
            continue
        conn.execute(
            "INSERT INTO data_quality_flag (id, target_type, target_id, kind, severity, detector, "
            "statistic, threshold, rationale, resembles, raised_by, actor_kind, created_at, "
            "status, zone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'active', 'I') "
            "ON CONFLICT(target_type, target_id, kind, detector) DO UPDATE SET "
            "statistic=excluded.statistic, threshold=excluded.threshold, "
            "rationale=excluded.rationale, resembles=excluded.resembles, "
            "created_at=excluded.created_at",
            (
                flag.id,
                flag.target_type,
                flag.target_id,
                flag.kind,
                flag.severity,
                flag.detector,
                flag.statistic,
                flag.threshold,
                flag.rationale,
                flag.resembles,
                raised_by,
                actor_kind,
                now,
            ),
        )
        written += 1
    return written, respected


def active_quarantine(
    conn: sqlite3.Connection, target_ids: Sequence[str], *, target_type: str = "sample"
) -> dict[str, str]:
    """target id -> rationale, for every active quarantine flag on the given targets.

    This is the function `omics.contrasts.refusals` calls. It is deliberately a plain lookup with
    no thresholds of its own: deciding what counts as quarantined happened when the flag was
    raised, and re-deciding it at read time is how two callers end up disagreeing about which
    samples are usable.
    """
    if not target_ids:
        return {}
    placeholders = ",".join("?" for _ in target_ids)
    return {
        str(target): str(rationale)
        for target, rationale in conn.execute(
            f"SELECT target_id, rationale FROM data_quality_flag "
            f"WHERE target_type = ? AND target_id IN ({placeholders}) "
            "AND severity = 'quarantine' AND status IN ('active', 'confirmed')",
            (target_type, *target_ids),
        )
    }
