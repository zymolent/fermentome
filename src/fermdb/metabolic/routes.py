"""Route enumeration and ranking — PLAN.md G.7, "the atlas's primary output".

Enumeration is **generative, not a catalogue of published builds**. That is what lets "what has
never been tried" be answered as the complement of the evidence rather than as a guess::

    pathway_route = { step -> part } x compartment assignment per step
                    x cofactor strategy x host x deletion set

Each enumerated route then passes six gates. Two of them can exclude a route outright; the rest
produce a score *component*.

**Scores are never summed.** ``pathway_route`` has five score columns and no total, which is the
schema enforcing G.7's rule: a route's rank must be explainable by naming which term dominated,
and a weighted total destroys exactly that. Ranking is lexicographic over named components, and
:func:`explain` prints the reason.

**A route with no supporting evidence is displayed, not hidden** -- that is the point of the
exercise -- but in its own Zone I band, never interleaved with demonstrated ones.

THE CODE GATE IS WHERE THIS PROJECT HAS BEEN WRONG BEFORE, so it is worth stating plainly: a
nuclear gene targeted to the matrix by a presequence needs **no recoding**, because it is
transcribed and translated in the cytosol under NCBI table 1 and only then imported. Only a gene
physically carried in the mtDNA is read under table 3. The gate therefore keys on the step's
``encoding_genome``, which the enumerator sets per step, and calls
:func:`fermdb.genetic_code.table_for_compartment` with that genome explicitly rather than letting
it infer one from a compartment that has two.
"""

from __future__ import annotations

import hashlib
import itertools
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ..genetic_code import table_for_compartment
from .curated import Part

__all__ = [
    "CARRIER_KNOWN",
    "COFACTOR_POOLS",
    "STEP_ORDER",
    "STRATEGY_PLANS",
    "Route",
    "RouteStep",
    "enumerate_routes",
    "explain",
    "rank",
    "write_routes",
]

#: The five catalytic steps, in pathway order. Competing reactions are not steps: they are what a
#: deletion set acts on, not something a route chooses a part for.
STEP_ORDER: Final[tuple[str, ...]] = ("AHAS", "KARI", "DHAD", "KDC", "ADH")

_MATRIX: Final[str] = "mitochondrial_matrix"
_CYTOSOL: Final[str] = "cytosol"
_PEROXISOME: Final[str] = "peroxisome"


@dataclass(frozen=True)
class StrategyPlan:
    """Where each step runs, and on which genome its gene is carried, for one strategy."""

    strategy: str
    compartments: Mapping[str, str]
    encoding_genomes: Mapping[str, str]
    #: Maturity of the technique the strategy needs, 0..1. Not a probability -- a stated ranking
    #: of how routinely the manipulation is done, used only to order routes against each other.
    feasibility: float
    feasibility_reason: str


def _plan(
    strategy: str,
    compartments: Mapping[str, str],
    feasibility: float,
    reason: str,
    mtdna_steps: Sequence[str] = (),
) -> StrategyPlan:
    return StrategyPlan(
        strategy=strategy,
        compartments=dict(compartments),
        encoding_genomes={
            step: ("mitochondrial" if step in mtdna_steps else "nuclear") for step in STEP_ORDER
        },
        feasibility=feasibility,
        feasibility_reason=reason,
    )


#: The five compartment strategies, as seeded in ``compartment_strategy``.
STRATEGY_PLANS: Final[Mapping[str, StrategyPlan]] = {
    "A_native_split": _plan(
        "A_native_split",
        {"AHAS": _MATRIX, "KARI": _MATRIX, "DHAD": _MATRIX, "KDC": _CYTOSOL, "ADH": _CYTOSOL},
        feasibility=1.0,
        reason="the native arrangement; no relocalization is attempted at all",
    ),
    "B_cytosolic_relocalization": _plan(
        "B_cytosolic_relocalization",
        dict.fromkeys(STEP_ORDER, _CYTOSOL),
        feasibility=0.8,
        reason="ordinary nuclear expression without targeting sequences; routine",
    ),
    "C_mitochondrial_ehrlich": _plan(
        "C_mitochondrial_ehrlich",
        dict.fromkeys(STEP_ORDER, _MATRIX),
        feasibility=0.6,
        reason="presequence targeting of the Ehrlich enzymes; established but per-protein",
    ),
    "D_alternative_compartment": _plan(
        "D_alternative_compartment",
        dict.fromkeys(STEP_ORDER, _PEROXISOME),
        feasibility=0.35,
        reason="PTS1/PTS2 targeting into the peroxisome; less characterised for this pathway",
    ),
    "E_mtdna_encoded": _plan(
        "E_mtdna_encoded",
        dict.fromkeys(STEP_ORDER, _MATRIX),
        feasibility=0.1,
        reason=(
            "requires mitochondrial transformation and recoding to NCBI table 3. Biolistic mtDNA "
            "transformation in S. cerevisiae is demonstrated but is not a routine technique "
            "(unverified)"
        ),
        mtdna_steps=("KDC", "ADH"),
    ),
}

#: Which reducing cofactors a compartment can supply. Seeded rather than measured: this is the
#: standard picture (unverified), and because it IS unverified a mismatch against it is recorded
#: as a named risk rather than used to exclude a route. G.7 reserves exclusion for a stoichiometric
#: impossibility -- carbon, redox or ATP that cannot balance -- and "this compartment probably does
#: not supply that cofactor" is a supply question, not an impossibility. Excluding 56 routes on an
#: unverified premise would delete exactly the options the atlas exists to surface.
COFACTOR_POOLS: Final[Mapping[str, frozenset[str]]] = {
    _CYTOSOL: frozenset({"NADH", "NADPH"}),
    # The matrix has NADH abundantly; its NADPH comes from Pos5 acting on that NADH, which is the
    # DUET coupling and is why NADPH is listed here but is the thin one.
    _MATRIX: frozenset({"NADH", "NADPH"}),
    _PEROXISOME: frozenset({"NADH"}),
}

#: Metabolite movements for which this atlas knows of a carrier. Everything else that has to cross
#: a membrane is a named gap, never an assumed diffusion.
CARRIER_KNOWN: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        # Ethanol and its aldehyde cross the inner membrane freely; this is what lets ADH3 deliver
        # reducing equivalents to the matrix without a shuttle.
        ("ethanol", _MATRIX, _CYTOSOL),
        ("ethanol", _CYTOSOL, _MATRIX),
        ("isobutanol", _MATRIX, _CYTOSOL),
    }
)


@dataclass(frozen=True)
class RouteStep:
    step_role: str
    part: Part
    compartment: str
    encoding_genome: str

    @property
    def needs_recoding(self) -> bool:
        """True only when the gene is carried IN the mtDNA, so it is read under table 3.

        A presequence-targeted nuclear gene working in the matrix is False here, and that is the
        distinction the whole gate exists for.
        """
        return self.encoding_genome == "mitochondrial"


@dataclass(frozen=True)
class Route:
    id: str
    strategy: str
    steps: tuple[RouteStep, ...]
    balance_status: str
    excluded_because: tuple[str, ...]
    cofactor_risks: tuple[str, ...]
    construction_requirements: tuple[str, ...]
    transport_gaps: tuple[str, ...]
    score_balance: float | None
    score_transport: float | None
    score_feasibility: float | None
    score_evidence: float | None
    score_toxicity: float | None

    @property
    def viable(self) -> bool:
        return not self.excluded_because


# ---------------------------------------------------------------------------------- the gates


def _cofactor_gate(steps: Sequence[RouteStep]) -> list[str]:
    """Steps whose cofactor the compartment is not recorded as supplying.

    A *risk*, not an exclusion, because :data:`COFACTOR_POOLS` is unverified. A route carrying
    this risk needs either a supply intervention (overexpress Pos5), a cofactor-switched part
    (the NADH-preferring KARI), or a measurement that settles the pool -- and naming which is the
    useful output, where dropping the route silently would not be.
    """
    problems: list[str] = []
    for step in steps:
        wanted = step.part.cofactor_preference
        if wanted in {"NA", "unknown", "either"}:
            continue
        available = COFACTOR_POOLS.get(step.compartment, frozenset())
        if wanted not in available:
            problems.append(
                f"{step.step_role} ({step.part.id}) needs {wanted} but {step.compartment} "
                f"supplies only {', '.join(sorted(available)) or 'nothing recorded'}"
            )
    return problems


def _code_gate(steps: Sequence[RouteStep]) -> list[str]:
    """Construction requirements, not exclusions: a gene that must be recoded still can be.

    ``table_for_compartment`` is called with the step's encoding genome explicitly. The matrix is
    served by two genomes, so asking it for "the" table raises -- and being made to pass the
    genome is what stops a presequence-targeted nuclear gene being recoded as though it were
    mtDNA-carried.
    """
    requirements: list[str] = []
    for step in steps:
        code = table_for_compartment(step.compartment, step.encoding_genome)
        if step.needs_recoding:
            requirements.append(
                f"{step.step_role} ({step.part.id}) is carried in the mtDNA, so its sequence must "
                f"be recoded to NCBI table {code.table_id} before it will translate correctly"
            )
    return requirements


def _transport_gate(steps: Sequence[RouteStep]) -> list[str]:
    """Every metabolite handed from one compartment to another needs a carrier, or it is a gap."""
    gaps: list[str] = []
    handoffs = {
        ("KARI", "DHAD"): "2,3-dihydroxyisovalerate",
        ("DHAD", "KDC"): "2-ketoisovalerate",
        ("KDC", "ADH"): "isobutyraldehyde",
        ("AHAS", "KARI"): "2-acetolactate",
    }
    by_role = {step.step_role: step for step in steps}
    for (upstream, downstream), metabolite in handoffs.items():
        source = by_role[upstream].compartment
        sink = by_role[downstream].compartment
        if source == sink:
            continue
        if (metabolite, source, sink) in CARRIER_KNOWN:
            continue
        gaps.append(
            f"{metabolite} must cross from {source} to {sink} between {upstream} and "
            f"{downstream}, and this atlas records no carrier for it"
        )
    return gaps


# ------------------------------------------------------------------------------- enumeration


def enumerate_routes(
    parts: Sequence[Part], *, strategies: Sequence[str] | None = None
) -> list[Route]:
    """Every {step -> part} x strategy combination, gated and scored.

    Generative: it does not ask what has been published, which is the only way the complement --
    what has never been tried -- can be read off the result.
    """
    by_role: dict[str, list[Part]] = {role: [] for role in STEP_ORDER}
    for part in parts:
        if part.step_role in by_role:
            by_role[part.step_role].append(part)
    missing = [role for role, candidates in by_role.items() if not candidates]
    if missing:
        raise ValueError(
            f"no candidate part for step role(s) {missing}; the enumeration product would be "
            f"empty and would look like 'no routes exist' rather than 'the catalog is incomplete'"
        )

    wanted = list(strategies) if strategies is not None else list(STRATEGY_PLANS)
    routes: list[Route] = []
    for strategy in wanted:
        plan = STRATEGY_PLANS[strategy]
        for combination in itertools.product(*(by_role[role] for role in STEP_ORDER)):
            steps = tuple(
                RouteStep(
                    step_role=role,
                    part=part,
                    compartment=plan.compartments[role],
                    encoding_genome=plan.encoding_genomes[role],
                )
                for role, part in zip(STEP_ORDER, combination, strict=True)
            )
            cofactor_risks = _cofactor_gate(steps)
            requirements = _code_gate(steps)
            gaps = _transport_gate(steps)

            route_id = f"{strategy}:" + "+".join(part.id for part in combination)
            routes.append(
                Route(
                    id=route_id,
                    strategy=strategy,
                    steps=steps,
                    # 'pass': a route is a selection of curated reactions, and every
                    # curated reaction balances on carbon, redox and adenylates --
                    # curated.py refuses to load one that does not, so route-level
                    # stoichiometry follows. Cofactor SUPPLY is a separate question and
                    # is carried in cofactor_risks, not folded in here.
                    balance_status="pass",
                    # Empty today, and that is itself a finding: the atlas cannot yet exclude any
                    # route on evidence. Exclusion is reserved for a stoichiometric impossibility,
                    # and every reaction in the curated pathways balances.
                    excluded_because=(),
                    cofactor_risks=tuple(cofactor_risks),
                    construction_requirements=tuple(requirements),
                    transport_gaps=tuple(gaps),
                    score_balance=1.0 / (1 + len(cofactor_risks)),
                    score_transport=1.0 / (1 + len(gaps)),
                    score_feasibility=plan.feasibility,
                    # NULL, not 0. Nothing has been extracted from the literature yet, so no route
                    # has demonstrated evidence -- and 0 would say "tried and failed", which is a
                    # different and much stronger claim than "not yet looked".
                    score_evidence=None,
                    # Likewise: no tolerance measurement is in the atlas, so no ceiling is known.
                    score_toxicity=None,
                )
            )
    return routes


def rank(routes: Sequence[Route]) -> list[Route]:
    """Order viable routes by named components, lexicographically. Never by a weighted total.

    Order: transport gaps first (a missing carrier is a hard engineering problem), then cofactor
    supply risks, then feasibility, then construction requirements. Evidence would lead if any
    existed; see :func:`enumerate_routes` on why it is NULL for every route today.
    """
    return sorted(
        (route for route in routes if route.viable),
        key=lambda r: (
            len(r.transport_gaps),
            len(r.cofactor_risks),
            -(r.score_feasibility or 0.0),
            len(r.construction_requirements),
            r.id,
        ),
    )


def explain(route: Route) -> str:
    """Why this route ranks where it does, by naming the dominating term."""
    if not route.viable:
        return f"EXCLUDED: {'; '.join(route.excluded_because)}"
    parts = [
        f"strategy={route.strategy}",
        f"feasibility={route.score_feasibility:.2f}",
        f"transport_gaps={len(route.transport_gaps)}",
        f"cofactor_risks={len(route.cofactor_risks)}",
        f"construction_requirements={len(route.construction_requirements)}",
        "evidence=unknown (nothing extracted yet)",
        "toxicity=unknown (no tolerance measurement)",
    ]
    return " | ".join(parts)


# ----------------------------------------------------------------------------------- storage


def _stable_id(text: str) -> str:
    """A deterministic id. `hash()` is salted per process, so a re-run would write new rows."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_routes(conn: sqlite3.Connection, routes: Sequence[Route]) -> dict[str, int]:
    """Store routes, their steps, and every gap they carry. Zone I: all inferred, none demonstrated.

    Transport gaps and cofactor-supply risks become ``knowledge_gap`` rows against the route
    rather than free text on it. G.8's point is that a gap with a predicate and a route to hang
    off is actionable -- it can be counted, assigned and closed -- where a sentence in an evidence
    column is a note nobody queries.
    """
    counts = {"pathway_route": 0, "pathway_route_step": 0, "knowledge_gap": 0}
    for route in routes:
        route_id = f"YAA:ROUTE:{_stable_id(route.id)}"
        conn.execute(
            "INSERT INTO pathway_route (id, cofactor_strategy, score_balance, score_evidence, "
            "score_feasibility, score_transport, score_toxicity, balance_status, zone) "
            "VALUES (?,?,?,?,?,?,?,?,'I') ON CONFLICT(id) DO UPDATE SET "
            "score_feasibility=excluded.score_feasibility, balance_status=excluded.balance_status",
            (
                route_id,
                route.strategy,
                route.score_balance,
                route.score_evidence,
                route.score_feasibility,
                route.score_transport,
                route.score_toxicity,
                route.balance_status,
            ),
        )
        counts["pathway_route"] += 1

        for order, step in enumerate(route.steps, start=1):
            conn.execute(
                "INSERT INTO pathway_route_step (route_id, step_order, step_role_id, part_id, "
                "compartment_id, encoding_genome) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(route_id, step_order) DO UPDATE SET part_id=excluded.part_id",
                (
                    route_id,
                    order,
                    step.step_role,
                    f"YAA:PART:{step.part.id.replace('_', '-')}",
                    step.compartment,
                    step.encoding_genome,
                ),
            )
            counts["pathway_route_step"] += 1

        gaps: list[tuple[str, str, str]] = [
            (
                "transport_carrier_unknown",
                description,
                "a metabolite with no carrier either does not move or moves by an unrecorded "
                "mechanism; either way the route's flux is not predictable",
            )
            for description in route.transport_gaps
        ] + [
            (
                "quantitative_value_missing",
                description,
                "the compartment's cofactor pool is asserted from background knowledge and has "
                "never been measured, so this is a supply risk to resolve rather than a reason to "
                "drop the route",
            )
            for description in route.cofactor_risks
        ]
        for kind, description, why in gaps:
            conn.execute(
                "INSERT INTO knowledge_gap (id, kind, route_id, description, why_it_matters, "
                "status, zone, evidence, confidence) "
                "VALUES (?,?,?,?,?,'open','I',?,'unverified') ON CONFLICT(id) DO NOTHING",
                (
                    f"YAA:GAP:{_stable_id(route.id + description)}",
                    kind,
                    route_id,
                    description,
                    why,
                    "fermdb.metabolic.routes gate output",
                ),
            )
            counts["knowledge_gap"] += 1
    conn.commit()
    return counts
