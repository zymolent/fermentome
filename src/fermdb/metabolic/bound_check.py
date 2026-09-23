"""The carbon-balance bound check of PLAN.md S.3, run against what is *stored*.

PLAN.md B.2 fixes the theoretical mass yield of isobutanol from glucose at **0.411 g/g**, stores
it per substrate in ``product_theoretical_yield``, and says it *"drives the automated carbon-
balance bound check of S.3"*. S.3 states the rule and its action:

    Mass yield <= theoretical maximum for that product and substrate (0.511 g/g ethanol,
    0.411 g/g isobutanol from glucose). A violation is flagged and blocked from aggregation,
    never silently stored.

**What was actually wired, before this module.** One ceiling check existed, in
:func:`fermdb.llm.validate._check_yield`, and it is called from exactly one place:
``fermdb.extract.harness``. It gates *records a model just proposed*, on the way in. Nothing ever
re-ran it against the rows that made it through, and nothing ran it against
``pathway_configuration`` at all — a configuration is not a measurement-shaped record, so
``validate_records`` never sees one. Phase 1b's acceptance clause is about configurations and the
stored corpus, so the extraction gate does not satisfy it. This module is that gap closed.

**Where the verdict is persisted, and why that took a second look.** The paragraph this replaces
said the schema had nowhere to put an S.3 action — *"there is no ``qc_flag`` table and no flag
column on ``measurement``"* — and concluded that persistence needed a migration. That was true
when it was written and was false by the end of the same day: schema **v15** added
``data_quality_flag``, *"a recorded, machine-readable doubt about a row"*, polymorphic over a
target type that already includes ``measurement``, carrying ``detector``, ``statistic``,
``threshold`` and ``rationale``, with a status only a person may move out of ``active``. That is
this check's verdict, column for column. The two landed on 2026-09-22 in different sessions and
crossed; nothing was missing, nothing was connected.

So **no migration was needed** and none was written. :func:`as_quality_flags` maps a verdict onto
a :class:`fermdb.omics.quality.QualityFlag` and ``python -m fermdb.metabolic.bound_check --write``
persists it through the writer v15 already ships.

**S.3's three actions against the column that carries them.** ``data_quality_flag.severity`` is
``quarantine`` / ``warn``, and the mapping is not a translation layer but the same distinction
under the older name:

* ``flag`` -- visible, still stored, excludes nothing -> ``severity='warn'``;
* ``block_aggregation`` -- usable alone, excluded from summaries -> ``severity='quarantine'``,
  which is what :func:`fermdb.omics.quality.active_quarantine` reports and what
  :func:`fermdb.query.answer` now consults before it picks a strain's best titer. A ceiling
  violation is `block_aggregation` and therefore `quarantine`: the row stays readable and stops
  being summarised, which is exactly S.3's sentence;
* ``reject`` -- *not stored*, logged with a reason. It has **no row to point at**, so it cannot be
  a flag on one, and it is not this module's action to take: rejection happens on the way in, at
  :func:`fermdb.llm.validate._check_yield`, before a record becomes a row. A check over the
  *stored* corpus can only ever flag or block, and saying so is more honest than adding a
  ``reject`` enum value that nothing could ever write.

**What is stored and what is derived.** Measurement verdicts are stored. Configuration verdicts
are **not**: a configuration's verdict is a roll-up of its measurements', recomputed by
:func:`check_configurations` on every read. Storing it would be storing a derived value that can
silently disagree with the rows under it the moment one of them is re-flagged.

**The substrate problem, which is the real finding.** The ceiling is keyed on
``(product_id, substrate)`` and ``measurement`` has no substrate column. ``condition_context``,
where the substrate belongs, has zero rows. ``curate.promote`` already documents this — *"it
travels in `evidence`, which is prose and queryable only by LIKE, and is therefore a holding
position and not a home"* — but only its higher-alcohol writer does even that. So this module
resolves a substrate through two provenance-backed routes, in order, and records which one
answered:

1. ``substrate as reported: X`` in ``measurement.evidence`` (what ``promote`` writes);
2. the ``substrate`` field of the ``curation_task`` payload named in ``measurement.evidence``,
   which is the value the curator saw when they accepted the row.

Both are string archaeology. Neither is a column, and a measurement whose substrate neither route
recovers is reported ``not_evaluable`` with reason ``substrate_unknown`` rather than assumed onto
glucose. **An assumed substrate is an invented ceiling**, and a wrong ceiling either launders a
violation or rejects a real number — the exact failure B.2 says the check exists to prevent.

**A failure here is a finding about a paper, not a units error.** The 0.411 figure was re-derived
on 2026-09-22 and holds: 1 glucose -> 1 isobutanol gives 74.12/180.16 = 0.41142 g/g, and 5 xylose
-> 6 isobutanol gives 6*74.12/(5*150.13) = 0.41142 g/g as well. The two routes agree to five
figures, so a flagged row is a claim about that paper's carbon balance.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ..omics.quality import QualityFlag, write_flags

__all__ = [
    "BOUND_CHECK_DETECTOR",
    "BoundCheckReport",
    "Ceiling",
    "ConfigurationVerdict",
    "MeasurementVerdict",
    "SubstrateResolution",
    "as_quality_flags",
    "check_configurations",
    "check_measurements",
    "format_report",
    "load_ceilings",
    "persist_verdicts",
    "resolve_substrate",
    "run_bound_check",
]

#: Relative slack on the comparison, matching ``fermdb.llm.validate``'s. A yield reported to two
#: significant figures must not be flagged by a float's last bit.
YIELD_EPSILON: Final[float] = 1e-9

#: The units this module recognises as a mass yield. Anything else is not a ratio of masses and
#: has no business being compared to a g/g ceiling.
MASS_YIELD_UNITS: Final[frozenset[str]] = frozenset({"g/g", "g g-1", "g/g-dw", "kg/kg"})

#: A basis that declares the value to already *be* a fraction of the theoretical maximum. Its
#: ceiling is 1 by definition and needs no substrate — which is why these rows are evaluable when
#: an ordinary g/g yield from the same paper is not.
FRACTION_BASES: Final[frozenset[str]] = frozenset({"theoretical_max_pct"})

#: The verdicts this module returns, deliberately not S.3's action words. S.3 says what to *do*
#: about a violation (`flag`, `block_aggregation`); this says what is *true* of the row. Nothing
#: is persisted, so claiming to have blocked an aggregation would be a lie.
_PASS: Final[str] = "pass"
_FLAG: Final[str] = "flag"
_NOT_EVALUABLE: Final[str] = "not_evaluable"
_REFUSED: Final[str] = "refused"

#: The detector name written onto every flag this module raises. `module:rule`, matching the
#: convention v15's schema comment gives (`'omics.quality:coherence'`). It is also the dedup key
#: component that makes a re-run *update* its own flags instead of stacking a second copy beside
#: them, so changing this string orphans every flag already raised under the old name.
BOUND_CHECK_DETECTOR: Final[str] = "metabolic.bound_check:ceiling"

_TASK_RE: Final[re.Pattern[str]] = re.compile(r"curation task (YAA:CTASK:[0-9a-f]+)")
_SUBSTRATE_RE: Final[re.Pattern[str]] = re.compile(r"substrate as reported:\s*([^;(]+)")

#: Substrate names the ceiling table may key on. Used only to pull a bare name out of a phrase a
#: curator wrote ("5% glucose"), never to invent one that is not there.
_KNOWN_SUBSTRATES: Final[tuple[str, ...]] = (
    "glucose",
    "xylose",
    "galactose",
    "glycerol",
    "sucrose",
    "arabinose",
    "cellobiose",
)


@dataclass(frozen=True)
class Ceiling:
    """One ``product_theoretical_yield`` row, as a ceiling or as a recorded absence of one."""

    product_id: str
    substrate: str
    g_per_g: float | None
    state: str
    stoichiometry: str | None

    @property
    def is_usable(self) -> bool:
        """True only for a recorded number. ``'unknown'`` means the assumed pathway is not
        settled, and S.3's own wording — a ceiling per product *and substrate* — is why that is
        reported as unchecked rather than filled in with a neighbouring product's figure."""
        return self.state == "recorded" and self.g_per_g is not None


@dataclass(frozen=True)
class SubstrateResolution:
    """Which route recovered a substrate for a measurement, and what it recovered."""

    #: 'evidence' | 'curation_task' | 'none' | 'ambiguous'
    route: str
    #: The normalised name, when exactly one known substrate was named.
    substrate: str | None
    #: What was actually on disk, before normalisation. Kept so a reader can audit the guess.
    raw: str | None
    #: Every known substrate the raw string named. Length > 1 means a mixture.
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class MeasurementVerdict:
    """The bound check's answer for one stored measurement."""

    measurement_id: str
    quantity_kind: str
    product_id: str | None
    value: float
    unit: str
    basis: str | None
    verdict: str
    reason: str
    substrate: SubstrateResolution
    ceiling: float | None
    publication_id: str | None
    strain_id: str | None

    @property
    def is_violation(self) -> bool:
        return self.verdict == _FLAG


@dataclass(frozen=True)
class ConfigurationVerdict:
    """The bound check's answer for one ``pathway_configuration``.

    A configuration has no yield of its own: the schema hangs measurements off a strain, not off a
    configuration. So its verdict is the aggregate of the yields measured on its host strain, and
    a configuration with no yield measurement at all is ``not_evaluable`` — which is the honest
    answer and the one phase 1b needs, because "passes the bound check" cannot be asserted of a
    configuration whose yield nobody recorded.
    """

    configuration_id: str
    name: str
    product_id: str | None
    host_strain_id: str | None
    verdict: str
    reason: str
    measurements: tuple[MeasurementVerdict, ...]


@dataclass(frozen=True)
class BoundCheckReport:
    """Everything the check found, in one object a caller can assert against."""

    ceilings: tuple[Ceiling, ...]
    measurements: tuple[MeasurementVerdict, ...]
    configurations: tuple[ConfigurationVerdict, ...]

    def counts(
        self, verdicts: Iterable[MeasurementVerdict | ConfigurationVerdict]
    ) -> dict[str, int]:
        tally: dict[str, int] = {_PASS: 0, _FLAG: 0, _NOT_EVALUABLE: 0, _REFUSED: 0}
        for item in verdicts:
            tally[item.verdict] = tally.get(item.verdict, 0) + 1
        return tally

    @property
    def measurement_counts(self) -> dict[str, int]:
        return self.counts(self.measurements)

    @property
    def configuration_counts(self) -> dict[str, int]:
        return self.counts(self.configurations)

    @property
    def violations(self) -> tuple[MeasurementVerdict, ...]:
        return tuple(m for m in self.measurements if m.is_violation)


# ------------------------------------------------------------------------------ the ceilings


def load_ceilings(conn: sqlite3.Connection) -> tuple[Ceiling, ...]:
    """Every ``product_theoretical_yield`` row, recorded and unknown alike.

    The unknown ones are kept because they are the difference between "this yield is under the
    ceiling" and "nobody has settled what the ceiling is" — two answers a summary that dropped
    them would conflate.
    """
    rows = conn.execute(
        "SELECT product_id, substrate, g_per_g, g_per_g_state, stoichiometry "
        "FROM product_theoretical_yield ORDER BY product_id, substrate"
    ).fetchall()
    return tuple(
        Ceiling(
            product_id=str(row[0]),
            substrate=str(row[1]),
            g_per_g=None if row[2] is None else float(row[2]),
            state=str(row[3] or "unknown"),
            stoichiometry=None if row[4] is None else str(row[4]),
        )
        for row in rows
    )


def _ceiling_index(ceilings: Sequence[Ceiling]) -> Mapping[tuple[str, str], Ceiling]:
    return {(c.product_id, c.substrate): c for c in ceilings}


# ------------------------------------------------------------------------- the substrate hunt


def _named_substrates(raw: str) -> tuple[str, ...]:
    lowered = raw.lower()
    return tuple(name for name in _KNOWN_SUBSTRATES if name in lowered)


def resolve_substrate(conn: sqlite3.Connection, evidence: str) -> SubstrateResolution:
    """Recover the substrate a measurement was taken on, or say that it cannot be recovered.

    Two routes, in order of directness, both reading prose that ``curate.promote`` wrote. Neither
    is a column; see this module's header for why that is the finding rather than the workaround.
    A phrase naming two sugars ("1:1 medium (glucose: xylose)") resolves to ``'ambiguous'`` with
    both candidates kept, so the caller can still evaluate it when the candidates share a ceiling.
    """
    text = evidence or ""

    inline = _SUBSTRATE_RE.search(text)
    if inline is not None:
        raw = inline.group(1).strip()
        names = _named_substrates(raw)
        if len(names) == 1:
            return SubstrateResolution("evidence", names[0], raw, names)
        return SubstrateResolution("ambiguous" if names else "none", None, raw, names)

    task = _TASK_RE.search(text)
    if task is None:
        return SubstrateResolution("none", None, None, ())

    row = conn.execute(
        "SELECT payload, edited_payload FROM curation_task WHERE id = ?", (task.group(1),)
    ).fetchone()
    if row is None:
        return SubstrateResolution("none", None, None, ())

    # The edited payload wins where it exists: it is what the curator actually accepted.
    for candidate in (row[1], row[0]):
        if not candidate:
            continue
        try:
            payload = json.loads(str(candidate))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        raw = str(payload.get("substrate") or "").strip()
        if not raw:
            continue
        names = _named_substrates(raw)
        if len(names) == 1:
            return SubstrateResolution("curation_task", names[0], raw, names)
        return SubstrateResolution("ambiguous" if names else "none", None, raw, names)

    return SubstrateResolution("none", None, None, ())


def _ceiling_for(
    index: Mapping[tuple[str, str], Ceiling],
    product_id: str,
    resolution: SubstrateResolution,
) -> tuple[Ceiling | None, str]:
    """The ceiling to compare against, plus a reason when there is none.

    A mixture is evaluable when every sugar it names carries the *same* recorded ceiling: the
    bound is then well defined whatever the ratio. That is not a convenience — 0.411 g/g holds for
    isobutanol from glucose and from xylose alike, so a glucose/xylose co-fermentation has one
    unambiguous ceiling and refusing to check it would discard a real answer.
    """
    if resolution.substrate is not None:
        ceiling = index.get((product_id, resolution.substrate))
        if ceiling is None:
            return None, (
                f"product_theoretical_yield has no row for ({product_id}, {resolution.substrate})"
            )
        if not ceiling.is_usable:
            return None, (
                f"product_theoretical_yield records state={ceiling.state!r} for "
                f"({product_id}, {resolution.substrate}): the assumed pathway is not settled"
            )
        return ceiling, ""

    if resolution.candidates:
        found = [index.get((product_id, name)) for name in resolution.candidates]
        usable = [c for c in found if c is not None and c.is_usable]
        if len(usable) == len(found) and usable:
            values = {c.g_per_g for c in usable}
            if len(values) == 1:
                return usable[0], ""
            return None, (
                f"the reported substrate {resolution.raw!r} names "
                f"{', '.join(resolution.candidates)}, whose ceilings differ "
                f"({sorted(v for v in values if v is not None)}); no single bound applies"
            )
        return None, (
            f"the reported substrate {resolution.raw!r} names "
            f"{', '.join(resolution.candidates)}, and at least one has no recorded ceiling"
        )

    return None, (
        "no substrate is recoverable for this measurement: `measurement` has no substrate "
        "column, `condition_context` is empty, and neither `evidence` nor the originating "
        "curation task names one. A ceiling needs (product, substrate) and assuming glucose "
        "would be inventing one"
    )


# ------------------------------------------------------------------------------- the check


def _check_row(
    conn: sqlite3.Connection,
    index: Mapping[tuple[str, str], Ceiling],
    row: sqlite3.Row,
) -> MeasurementVerdict:
    measurement_id = str(row["id"])
    kind = str(row["quantity_kind"])
    unit = str(row["unit_as_reported"] or "")
    basis = None if row["basis"] is None else str(row["basis"])
    product_id = None if row["product_id"] is None else str(row["product_id"])
    value = float(row["value_as_reported"])
    empty = SubstrateResolution("none", None, None, ())

    def verdict(
        outcome: str,
        reason: str,
        *,
        substrate: SubstrateResolution = empty,
        ceiling: float | None = None,
    ) -> MeasurementVerdict:
        return MeasurementVerdict(
            measurement_id=measurement_id,
            quantity_kind=kind,
            product_id=product_id,
            value=value,
            unit=unit,
            basis=basis,
            verdict=outcome,
            reason=reason,
            substrate=substrate,
            ceiling=ceiling,
            publication_id=None if row["publication_id"] is None else str(row["publication_id"]),
            strain_id=None if row["strain_id"] is None else str(row["strain_id"]),
        )

    # PLAN.md's "a yield with no `basis` is refused". The schema already forbids NULL there, so
    # this can only fire on a database written around the constraint -- which is exactly when a
    # second, independent statement of the rule earns its keep.
    if kind == "yield" and basis is None:
        return verdict(
            _REFUSED,
            "a yield with no `basis` is not comparable to anything: g/g-consumed and "
            "g/g-supplied are different numbers. The schema forbids NULL here, so this row "
            "reached the database around its CHECK constraint",
        )

    if basis in FRACTION_BASES:
        # A fraction of the theoretical maximum carries its own ceiling: 1. No substrate needed,
        # which is the one case where the missing column costs nothing.
        if value > 1 + YIELD_EPSILON:
            return verdict(
                _FLAG,
                f"basis {basis!r} means a fraction of the theoretical maximum, and {value} "
                "claims more product than the substrate contains",
                ceiling=1.0,
            )
        if value < 0:
            return verdict(_FLAG, f"a negative fraction of the maximum ({value})", ceiling=1.0)
        return verdict(
            _PASS,
            f"{value} is within [0, 1] as a fraction of the theoretical maximum",
            ceiling=1.0,
        )

    if kind != "yield":
        return verdict(
            _NOT_EVALUABLE,
            f"quantity_kind={kind!r} is not a mass yield; the 0.411 g/g bound applies to "
            "mass yields and nothing else",
        )

    if unit.lower() not in MASS_YIELD_UNITS:
        return verdict(
            _NOT_EVALUABLE,
            f"unit {unit!r} is not a mass ratio, so there is nothing to compare to a g/g "
            "ceiling. A yield stored with unit 'unknown' escapes this check entirely",
        )

    if product_id is None:
        return verdict(_NOT_EVALUABLE, "a yield with no product_id has no ceiling to check")

    resolution = resolve_substrate(conn, str(row["evidence"] or ""))
    ceiling, why = _ceiling_for(index, product_id, resolution)
    if ceiling is None or ceiling.g_per_g is None:
        return verdict(_NOT_EVALUABLE, why, substrate=resolution)

    maximum = ceiling.g_per_g
    if value > maximum * (1 + YIELD_EPSILON):
        return verdict(
            _FLAG,
            f"{value} {unit} exceeds the theoretical maximum {maximum} {unit} for "
            f"{product_id} from {ceiling.substrate}. A yield above the stoichiometric ceiling "
            "is not a measurement; block it from aggregation and re-read the paper",
            substrate=resolution,
            ceiling=maximum,
        )
    return verdict(
        _PASS,
        f"{value} {unit} is within the {maximum} {unit} ceiling for {product_id} from "
        f"{ceiling.substrate} ({100 * value / maximum:.1f}% of it)",
        substrate=resolution,
        ceiling=maximum,
    )


def check_measurements(
    conn: sqlite3.Connection, *, ceilings: Sequence[Ceiling] | None = None
) -> tuple[MeasurementVerdict, ...]:
    """Run the bound check over every row in ``measurement``.

    Every row, not only the yields: a caller needs to be able to say how many of the stored
    measurements the check *could not* reach, and that number is only meaningful if the
    denominator is the whole table.
    """
    index = _ceiling_index(load_ceilings(conn) if ceilings is None else ceilings)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, strain_id, publication_id, quantity_kind, product_id, value_as_reported, "
        "unit_as_reported, basis, evidence FROM measurement ORDER BY id"
    ).fetchall()
    return tuple(_check_row(conn, index, row) for row in rows)


def check_configurations(
    conn: sqlite3.Connection, *, measurements: Sequence[MeasurementVerdict] | None = None
) -> tuple[ConfigurationVerdict, ...]:
    """Roll the measurement verdicts up to the ``pathway_configuration`` rows phase 1b names.

    The join is ``pathway_configuration.host_strain_id -> measurement.strain_id``, because that is
    the only link the schema offers. It is a weak one — two configurations from the same paper can
    share a host strain row and then inherit each other's numbers — and a configuration whose
    yields are wrongly attributed is worse than one with none. So a strain carrying yields for
    more than one configuration is reported with that stated in the reason.
    """
    verdicts = check_measurements(conn) if measurements is None else tuple(measurements)
    by_strain: dict[str, list[MeasurementVerdict]] = {}
    for verdict in verdicts:
        if verdict.strain_id is None:
            continue
        by_strain.setdefault(verdict.strain_id, []).append(verdict)

    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, product_id, host_strain_id FROM pathway_configuration ORDER BY id"
    ).fetchall()
    shared: dict[str, int] = {}
    for row in rows:
        if row["host_strain_id"] is not None:
            key = str(row["host_strain_id"])
            shared[key] = shared.get(key, 0) + 1

    out: list[ConfigurationVerdict] = []
    for row in rows:
        host = None if row["host_strain_id"] is None else str(row["host_strain_id"])
        mine = tuple(
            v
            for v in (by_strain.get(host, []) if host else [])
            if v.verdict in (_PASS, _FLAG, _REFUSED)
        )
        if host is None:
            outcome, reason = (
                _NOT_EVALUABLE,
                ("the configuration names no host strain, and a measurement hangs off a strain"),
            )
        elif not mine:
            outcome, reason = (
                _NOT_EVALUABLE,
                (
                    f"no yield measurement on host strain {host} could be evaluated against a "
                    "ceiling, so this configuration neither passes the bound nor violates it"
                ),
            )
        elif any(v.verdict == _REFUSED for v in mine):
            outcome, reason = _REFUSED, "a yield on the host strain has no basis"
        elif any(v.verdict == _FLAG for v in mine):
            outcome, reason = (
                _FLAG,
                (
                    f"{sum(1 for v in mine if v.verdict == _FLAG)} of {len(mine)} evaluable yields "
                    "on the host strain exceed the ceiling"
                ),
            )
        else:
            outcome, reason = (
                _PASS,
                (f"all {len(mine)} evaluable yields on host strain {host} are within the ceiling"),
            )
        if host is not None and shared.get(host, 0) > 1 and mine:
            reason += (
                f" -- but {shared[host]} configurations share this host strain, so the "
                "attribution is by strain and not by configuration"
            )
        out.append(
            ConfigurationVerdict(
                configuration_id=str(row["id"]),
                name=str(row["name"]),
                product_id=None if row["product_id"] is None else str(row["product_id"]),
                host_strain_id=host,
                verdict=outcome,
                reason=reason,
                measurements=mine,
            )
        )
    return tuple(out)


def run_bound_check(conn: sqlite3.Connection) -> BoundCheckReport:
    """The whole check: ceilings, every measurement, every configuration."""
    ceilings = load_ceilings(conn)
    measurements = check_measurements(conn, ceilings=ceilings)
    configurations = check_configurations(conn, measurements=measurements)
    return BoundCheckReport(
        ceilings=ceilings, measurements=measurements, configurations=configurations
    )


# -------------------------------------------------------------------------------- S.3 persistence


def as_quality_flags(report: BoundCheckReport) -> tuple[QualityFlag, ...]:
    """The violations, as `data_quality_flag` rows. Only violations: a pass is not a doubt.

    ``kind`` is ``value_implausible`` -- v15's own gloss for it is *"the value is outside what the
    system can produce"*, and a mass yield above the thermodynamic ceiling for its substrate is
    the purest case of that the atlas has. It is **not** ``mislabel_suspected``: the ceiling says
    the number cannot be right, not that the row belongs to a different strain.

    ``statistic`` is the reported yield and ``threshold`` the ceiling it broke, so the pair a
    curator needs to judge the flag sits on the flag rather than only in the prose beside it.

    Rows that are ``not_evaluable`` raise nothing. This is the one that would be tempting to get
    wrong: 103 of the 105 measurements in the atlas today cannot be evaluated at all, mostly
    because no substrate is recoverable, and emitting a flag for each would bury two real findings
    under a hundred statements that the check did not run. *"The check could not run"* is a gap in
    the atlas, which `knowledge_gap` is for; it is not a doubt about the row.
    """
    flags: list[QualityFlag] = []
    for verdict in report.violations:
        ceiling = verdict.ceiling
        substrate = verdict.substrate.substrate or "unknown"
        flags.append(
            QualityFlag(
                target_type="measurement",
                target_id=verdict.measurement_id,
                kind="value_implausible",
                # block_aggregation, in the column that carries it -- see the module docstring.
                severity="quarantine",
                detector=BOUND_CHECK_DETECTOR,
                statistic=verdict.value,
                threshold=ceiling,
                rationale=(
                    f"{verdict.value:g} {verdict.unit} exceeds the theoretical mass yield of "
                    f"{ceiling:g} g/g for {verdict.product_id} from {substrate} "
                    f"(substrate resolved via {verdict.substrate.route}). "
                    "PLAN.md S.3: flagged and blocked from aggregation, never silently stored. "
                    "A yield above the carbon ceiling is a claim about this paper's carbon "
                    "balance, not a units error -- the 0.411 g/g figure agrees to five figures "
                    "by two independent routes. Re-read the paper before clearing this."
                ),
            )
        )
    return tuple(flags)


def persist_verdicts(
    conn: sqlite3.Connection, report: BoundCheckReport, *, raised_by: str
) -> tuple[int, int]:
    """Write the violations as flags. Returns (written, left alone because already resolved).

    ``raised_by`` is required and not defaulted. Every other writer in this repo names its actor,
    and a flag whose origin is ``"someone"`` is a flag nobody can follow up.
    """
    return write_flags(conn, as_quality_flags(report), raised_by=raised_by, actor_kind="agent")


def format_report(report: BoundCheckReport) -> str:
    """A plain-text rendering, so the check can be read as well as asserted against."""
    lines: list[str] = []
    counts = report.measurement_counts
    total = len(report.measurements)
    lines.append(f"measurements: {total}")
    for key in (_PASS, _FLAG, _NOT_EVALUABLE, _REFUSED):
        lines.append(f"  {key:<14} {counts.get(key, 0)}")

    reasons: dict[str, int] = {}
    for verdict in report.measurements:
        if verdict.verdict != _NOT_EVALUABLE:
            continue
        head = verdict.reason.split(";")[0].split(",")[0][:72]
        reasons[head] = reasons.get(head, 0) + 1
    if reasons:
        lines.append("  why not evaluable:")
        for reason, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {n:>3}  {reason}")

    lines.append("")
    conf = report.configuration_counts
    lines.append(f"pathway_configuration rows: {len(report.configurations)}")
    for key in (_PASS, _FLAG, _NOT_EVALUABLE, _REFUSED):
        lines.append(f"  {key:<14} {conf.get(key, 0)}")
    for configuration in report.configurations:
        lines.append(
            f"  {configuration.configuration_id}  {configuration.verdict}: {configuration.reason}"
        )

    if report.violations:
        lines.append("")
        lines.append("VIOLATIONS (block from aggregation, re-read the paper):")
        for verdict in report.violations:
            lines.append(f"  {verdict.measurement_id} ({verdict.publication_id}): {verdict.reason}")
    return "\n".join(lines)


def _main() -> int:  # pragma: no cover - a convenience entry point, not part of the API
    """``python -m fermdb.metabolic.bound_check [--write --raised-by NAME]``.

    Reporting is the default and writing is opt-in, which is the way round this repo does it
    everywhere: a read never surprises anyone, and a run that raises flags against the shared
    atlas should have been asked for in so many words.
    """
    import argparse

    from ..config import Settings
    from ..db import open_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="persist the violations as data_quality_flag rows (PLAN.md S.3 block_aggregation)",
    )
    parser.add_argument(
        "--raised-by",
        help="who is raising these flags. Required with --write; a flag nobody can follow up "
        "is not a finding",
    )
    args = parser.parse_args()
    if args.write and not args.raised_by:
        parser.error("--write requires --raised-by")

    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    try:
        report = run_bound_check(conn)
        print(format_report(report))
        if args.write:
            written, respected = persist_verdicts(conn, report, raised_by=str(args.raised_by))
            conn.commit()
            print(f"\nflags written: {written}; left alone because already resolved: {respected}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
