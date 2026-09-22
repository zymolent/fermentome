"""The assembled answer to: which pathway engineering is feasible, transcript-backed, high-yield?

This is the one query in the atlas that crosses every layer at once -- routes (G.7), builds and
their declared constructs, differential expression (F.3/F.4), and reported yields -- so it is also
the one place where the temptation to let a strong result in one layer stand in for a missing
result in another is strongest. The module is organised around refusing that.

Three separations are structural rather than editorial:

* **Feasible, transcript-backed and high-yield are reported as three independent columns**, never
  fused into one number. A route can be feasible and unevidenced, evidenced and low-yielding, or
  high-yielding in a host nobody has transcript data for. Collapsing them would produce a ranking
  that looks decisive and hides which of the three is carrying it.
* **Yield evidence is partitioned by who checked it.** A value a curator promoted after reading
  the paper and a value harvested by an extraction agent are both shown, and they are never
  summed, averaged or silently merged into one "best known yield".
* **A yield from another host is labelled as such, always.** The best isobutanol yield in this
  corpus is an *E. coli* number, and the best *S. cerevisiae* number is roughly seven times lower.
  Any answer that reports the former while the question is about engineering yeast is answering a
  different question, so the host is printed on every row and the gap is stated in words.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - typing only, and avoids a metabolic <-> query import cycle
    from ..metabolic.transcript_support import RouteSupport

__all__ = [
    "Answer",
    "RouteAnswer",
    "YieldRecord",
    "assemble",
    "render",
]

#: The theoretical maximum isobutanol yield on glucose, g/g. Used only to express a reported
#: yield as a fraction of the ceiling, never to convert a reported percentage into a mass yield --
#: four papers in this corpus compute their percentages against a different denominator, so a
#: single constant applied to all of them would corrupt them.
THEORETICAL_MAX_G_PER_G: Final[float] = 0.411

YIELD_HARVEST: Final[str] = "docs/drafts/extraction/2026-09-22-yield-harvest.tsv"


@dataclass(frozen=True, slots=True)
class YieldRecord:
    host: str
    strain: str
    value_g_per_g: float | None
    value_as_reported: str
    unit_as_reported: str
    carbon_source: str
    doi: str
    confidence: str
    reviewed: bool
    note: str = ""

    @property
    def percent_of_ceiling(self) -> float | None:
        if self.value_g_per_g is None:
            return None
        return 100.0 * self.value_g_per_g / THEORETICAL_MAX_G_PER_G


@dataclass(frozen=True, slots=True)
class RouteAnswer:
    route_id: str
    strategy: str
    parts: tuple[str, ...]
    compartments: tuple[str, ...]
    balance_status: str
    score_feasibility: float | None
    score_evidence: float | None
    transcript_steps_measured: int
    transcript_steps_total: int
    transcript_steps_elevated: int
    matched_builds: tuple[str, ...]
    step_notes: tuple[str, ...] = field(default_factory=tuple)
    caveats: tuple[str, ...] = field(default_factory=tuple)
    #: How many enumerated routes share this strategy. The listed route is the best-evidenced of
    #: them; the rest differ in choices the transcript data cannot distinguish between.
    variants: int = 0
    #: What the matched builds actually produced, as "<strain> <value> <unit>". This is the join
    #: the atlas was missing: without it a route can be transcript-backed and silently terrible.
    build_performance: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Answer:
    routes: tuple[RouteAnswer, ...]
    yeast_yields: tuple[YieldRecord, ...]
    other_host_yields: tuple[YieldRecord, ...]
    contrasts: int
    contextualised_samples: int
    total_samples: int
    builds: tuple[str, ...]
    unmeasurable_note: str
    gaps: tuple[str, ...]


# ------------------------------------------------------------------------------------ the inputs


def _read_harvest(repo_root: Path) -> list[YieldRecord]:
    path = repo_root / YIELD_HARVEST
    if not path.is_file():
        return []
    records: list[YieldRecord] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            raw = (row.get("value_g_per_g") or "").strip()
            try:
                value = float(raw) if raw else None
            except ValueError:
                value = None
            records.append(
                YieldRecord(
                    host=row.get("host_organism", "").strip(),
                    strain=row.get("strain_name_as_reported", "").strip(),
                    value_g_per_g=value,
                    value_as_reported=row.get("value_as_reported", "").strip(),
                    unit_as_reported=row.get("unit_as_reported", "").strip(),
                    carbon_source=row.get("carbon_source", "").strip(),
                    doi=row.get("doi", "").strip(),
                    confidence=row.get("confidence", "").strip(),
                    reviewed=False,
                    note=row.get("note", "").strip(),
                )
            )
    return records


def _curated_yields(conn: sqlite3.Connection) -> list[YieldRecord]:
    """Yields already in `measurement` -- the ones a curator promoted after reading the paper."""
    records: list[YieldRecord] = []
    for value, unit, strain, publication, confidence, evidence in conn.execute(
        "SELECT m.value_as_reported, m.unit_as_reported, COALESCE(s.canonical_name, ''), "
        "COALESCE(m.publication_id, ''), m.confidence, m.evidence "
        "FROM measurement m LEFT JOIN strain s ON s.id = m.strain_id "
        "WHERE m.quantity_kind = 'yield' AND m.product_id = 'YAA:PRODUCT:isobutanol'"
    ):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = None
        records.append(
            YieldRecord(
                host="Saccharomyces cerevisiae",
                strain=str(strain),
                value_g_per_g=numeric if str(unit).strip() == "g/g" else None,
                value_as_reported=str(value),
                unit_as_reported=str(unit),
                carbon_source="",
                doi=str(publication).replace("doi:", ""),
                confidence=str(confidence),
                reviewed=True,
                note=str(evidence)[:160],
            )
        )
    return records


def _build_performance(conn: sqlite3.Connection) -> dict[str, str]:
    """strain name -> its best-evidenced production measurement, for the builds with transcripts.

    Titer preferred over yield only because this corpus's titers are stated and its yields are
    mostly derived; both are printed where both exist. A build with transcript evidence and no
    measurement prints nothing, which is the state the atlas was in until this row existed.
    """
    out: dict[str, str] = {}
    for name, kind, value, unit in conn.execute(
        "SELECT s.canonical_name, m.quantity_kind, m.value_as_reported, m.unit_as_reported "
        "FROM measurement m JOIN strain s ON s.id = m.strain_id "
        "WHERE m.product_id = 'YAA:PRODUCT:isobutanol' "
        "AND m.quantity_kind IN ('titer', 'yield') "
        "ORDER BY s.canonical_name, CASE m.quantity_kind WHEN 'titer' THEN 0 ELSE 1 END"
    ):
        entry = f"{value:g} {unit}" if isinstance(value, (int, float)) else f"{value} {unit}"
        existing = out.get(str(name))
        out[str(name)] = f"{existing}; {kind} {entry}" if existing else f"{kind} {entry}"
    return out


# ---------------------------------------------------------------------------------- the assembly


def assemble(
    conn: sqlite3.Connection,
    *,
    repo_root: Path,
    supports: Mapping[str, RouteSupport],
    limit: int = 8,
) -> Answer:
    """Build the answer. ``supports`` maps route id -> RouteSupport from `transcript_support`."""
    routes: list[RouteAnswer] = []
    rows = conn.execute(
        "SELECT id, cofactor_strategy, balance_status, score_feasibility, score_evidence "
        "FROM pathway_route WHERE score_evidence IS NOT NULL "
        "ORDER BY score_evidence DESC, score_feasibility DESC, id"
    ).fetchall()

    # One row per strategy, not per route: 6,400 routes collapse into a handful of engineering
    # decisions, and a list whose first four entries differ only in which ADH they name reads as
    # four findings when it is one. The best-evidenced route of each strategy is the answer to
    # "which pathway engineering", and the count says how many variants sit behind it.
    per_strategy_count: dict[str, int] = defaultdict(int)
    for (strategy_name,) in conn.execute(
        "SELECT cofactor_strategy FROM pathway_route WHERE score_evidence IS NOT NULL"
    ):
        per_strategy_count[str(strategy_name)] += 1
    seen_strategies: set[str] = set()

    seen_signatures: set[tuple[str, ...]] = set()
    for route_id, strategy, balance, feasibility, evidence in rows:
        if str(strategy) in seen_strategies:
            continue
        support = supports.get(str(route_id))
        if support is None:
            continue
        steps = conn.execute(
            "SELECT step_role_id, part_id, compartment_id FROM pathway_route_step "
            "WHERE route_id = ? ORDER BY step_order",
            (str(route_id),),
        ).fetchall()
        parts = tuple(str(p).replace("YAA:PART:", "") for _, p, _ in steps)
        if parts in seen_signatures:
            continue
        seen_signatures.add(parts)
        seen_strategies.add(str(strategy))
        catalytic = [s for s in support.steps if s.role in {"AHAS", "KARI", "DHAD", "KDC", "ADH"}]
        routes.append(
            RouteAnswer(
                route_id=str(route_id),
                strategy=str(strategy),
                parts=parts,
                compartments=tuple(str(c) for _, _, c in steps),
                balance_status=str(balance),
                score_feasibility=feasibility,
                score_evidence=evidence,
                transcript_steps_measured=support.measured,
                transcript_steps_total=len(catalytic),
                transcript_steps_elevated=support.elevated,
                matched_builds=support.matched_strains,
                step_notes=tuple(f"{s.role}: {s.status} -- {s.note}" for s in catalytic),
                caveats=support.caveats,
                variants=per_strategy_count[str(strategy)],
            )
        )
        if len(routes) >= limit:
            break

    performance = _build_performance(conn)
    routes = [
        RouteAnswer(
            **{
                **{f.name: getattr(route, f.name) for f in fields(route)},
                "build_performance": tuple(
                    performance[name] for name in route.matched_builds if name in performance
                ),
            }
        )
        for route in routes
    ]

    harvested = _read_harvest(repo_root)
    curated = _curated_yields(conn)
    everything = curated + harvested
    yeast = tuple(
        sorted(
            (r for r in everything if "cerevis" in r.host.lower()),
            key=lambda r: -(r.value_g_per_g or 0),
        )
    )
    others = tuple(
        sorted(
            (r for r in everything if "cerevis" not in r.host.lower()),
            key=lambda r: -(r.value_g_per_g or 0),
        )
    )

    contrasts = conn.execute(
        "SELECT COUNT(*) FROM analysis_result WHERE kind = 'differential_expression'"
    ).fetchone()[0]
    contextualised = conn.execute(
        "SELECT COUNT(*) FROM sample WHERE condition_context_id IS NOT NULL"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    # Only strains whose construct was actually parsed into a localization map count as builds
    # with transcript evidence behind them. Every other strain in the atlas was curated from a
    # paper and has no sequencing attached, and listing it here would imply otherwise.
    builds = tuple(
        str(name)
        for (name,) in conn.execute(
            "SELECT DISTINCT s.canonical_name FROM strain s "
            "JOIN genotype g ON g.strain_id = s.id "
            "JOIN sample sa ON sa.strain_id = s.id "
            "WHERE g.parsed_json LIKE '%\"localization\"%' "
            "AND sa.condition_context_id IS NOT NULL ORDER BY s.canonical_name"
        )
    )

    gaps = tuple(
        str(description)
        for (description,) in conn.execute(
            "SELECT DISTINCT description FROM knowledge_gap "
            "WHERE kind = 'never_attempted' ORDER BY description LIMIT 6"
        )
    )

    return Answer(
        routes=tuple(routes),
        yeast_yields=yeast,
        other_host_yields=others,
        contrasts=int(contrasts),
        contextualised_samples=int(contextualised),
        total_samples=int(total),
        builds=builds,
        unmeasurable_note=(
            "the quantification these contrasts rest on used an S288C-only transcriptome, so "
            "every heterologous part (alsS, kivd, adhA, ilvC) is unmeasured rather than absent"
        ),
        gaps=gaps,
    )


def _titer_mg_per_l(entries: Sequence[str]) -> float:
    """The titer out of a performance string, in mg/L, or 0.0 when none is stated."""
    for entry in entries:
        for part in entry.split(";"):
            part = part.strip()
            if not part.startswith("titer"):
                continue
            pieces = part.split()
            if len(pieces) < 3:
                continue
            try:
                value = float(pieces[1])
            except ValueError:
                continue
            unit = pieces[2].lower()
            if unit.startswith("g/l"):
                return value * 1000.0
            return value
    return 0.0


# ----------------------------------------------------------------------------------- the render


def render(answer: Answer, *, verbose: bool = False) -> str:
    out: list[str] = []
    add = out.append

    add("WHICH PATHWAY ENGINEERING IS FEASIBLE, TRANSCRIPT-BACKED, AND HIGH-YIELDING?")
    add("=" * 78)
    add("")
    add("Feasible, transcript-backed and high-yield are three separate questions. They are")
    add("answered separately below, because in this corpus they do not point the same way.")
    add("")

    add("1. WHAT THE TRANSCRIPT EVIDENCE COVERS")
    add("-" * 78)
    add(
        f"  {answer.contrasts} stored differential-expression contrasts over "
        f"{answer.contextualised_samples} of {answer.total_samples} samples that carry an "
        "approved condition context."
    )
    add(f"  Built strains with a parsed construct: {', '.join(answer.builds) or 'none'}")
    add(f"  ! {answer.unmeasurable_note}")
    add("")

    add("2. ROUTES, RANKED BY HOW MUCH OF THEM HAS ACTUALLY BEEN MEASURED")
    add("-" * 78)
    if not answer.routes:
        add("  No route has any transcript evidence.")
    for i, route in enumerate(answer.routes, start=1):
        feasibility = (
            f"{route.score_feasibility:.2f}"
            if route.score_feasibility is not None
            else "not scored"
        )
        add(
            f"  {i}. {route.strategy}  ({route.variants} enumerated variants)  "
            f"evidence={route.score_evidence:.2f}  "
            f"feasibility={feasibility}  "
            f"redox={route.balance_status}"
        )
        add(f"     parts: {' + '.join(route.parts)}")
        if route.build_performance:
            add(f"     MEASURED: {' | '.join(route.build_performance)}")
        add(
            f"     transcript: {route.transcript_steps_measured}/"
            f"{route.transcript_steps_total} catalytic steps measured, "
            f"{route.transcript_steps_elevated} elevated in "
            f"{', '.join(route.matched_builds) or 'no build'}"
        )
        if verbose:
            for note in route.step_notes:
                add(f"       - {note}")
        for caveat in route.caveats:
            add(f"     ! {caveat}")
        add("")

    # Ordering by evidence is honest about what the ordering means, and it is not the same as
    # ordering by performance. Where the two disagree the answer must say so out loud, or a
    # reader takes "first" for "best" -- which is exactly backwards here.
    measured = [r for r in answer.routes if r.build_performance]
    if len(measured) > 1:
        add("   MEASURED PERFORMANCE RANKS THESE DIFFERENTLY:")
        for route in sorted(measured, key=lambda r: -_titer_mg_per_l(r.build_performance)):
            add(
                f"     {_titer_mg_per_l(route.build_performance):>8.0f} mg/L  "
                f"{route.strategy}  ({', '.join(route.matched_builds)})"
            )
        add(
            "   The list above is ordered by how much of each route has been MEASURED, not by "
            "how well it works."
        )
        add("")

    add("3. YIELD -- WHAT 'HIGH' ACTUALLY MEANS HERE")
    add("-" * 78)
    reviewed = [r for r in answer.yeast_yields if r.reviewed]
    harvested = [r for r in answer.yeast_yields if not r.reviewed and r.confidence != "low"]
    suspect = [r for r in answer.yeast_yields if not r.reviewed and r.confidence == "low"]

    add(f"  S. cerevisiae, curator-reviewed ({len(reviewed)}):")
    for record in reviewed[:4]:
        add(
            f"    {record.value_as_reported:>10} {record.unit_as_reported:<8} "
            f"{record.strain[:26]:26s} {record.doi}"
        )
    add(f"  S. cerevisiae, agent-harvested, not yet reviewed ({len(harvested)}):")
    for record in harvested[:5]:
        ceiling = record.percent_of_ceiling
        share = f"{ceiling:.1f}% of ceiling" if ceiling is not None else "not convertible"
        add(
            f"    {record.value_g_per_g if record.value_g_per_g is not None else '?':>10} g/g  "
            f"{record.strain[:26]:26s} {share:18s} {record.doi}"
        )
    if suspect:
        add(
            "  Flagged as doubtful by the harvest, excluded from the ceiling above "
            f"({len(suspect)}):"
        )
        for record in suspect[:3]:
            add(f"    {record.value_g_per_g} g/g  {record.strain[:26]:26s} {record.doi}")

    best_yeast = next(
        (r for r in answer.yeast_yields if r.value_g_per_g and r.confidence != "low"), None
    )
    best_other = next((r for r in answer.other_host_yields if r.value_g_per_g), None)
    add("")
    if best_yeast and best_other:
        ratio = best_other.value_g_per_g / best_yeast.value_g_per_g  # type: ignore[operator]
        add(
            f"  The gap that decides what 'high yield' can mean: the best credible "
            f"S. cerevisiae yield in this corpus is {best_yeast.value_g_per_g:.4f} g/g "
            f"({best_yeast.percent_of_ceiling:.1f}% of the 0.411 g/g ceiling, {best_yeast.strain}),"
        )
        add(
            f"  against {best_other.value_g_per_g:.3f} g/g in {best_other.host} "
            f"({best_other.strain[:40]}). That is {ratio:.1f}x, and it is a host gap, not a "
            "route gap --"
        )
        add("  no route ranked above closes it, and none of the transcript evidence bears on it.")
    add("")

    add("4. WHAT THIS ANSWER DOES NOT ESTABLISH")
    add("-" * 78)
    add("  - Transcript abundance is not flux. Every 'elevated' above means a construct is")
    add("    transcribed, not that its enzyme folds, imports, or carries carbon.")
    add("  - No yield in this atlas is linked to any sequenced sample: measurement.sample_id is")
    add("    NULL on every row, so no route's transcript profile can be regressed on its titer.")
    add("  - The transcript evidence comes from one study in one background. It is replication")
    add("    across timepoints, not across laboratories.")
    for gap in answer.gaps:
        add(f"  - open gap: {gap[:100]}")
    return "\n".join(out)
