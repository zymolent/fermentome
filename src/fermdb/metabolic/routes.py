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
from .chassis import ChassisGate, ChassisProfile, gates_for
from .curated import Part
from .mtdna_loci import MtdnaLocus

__all__ = [
    "CARRIER_KNOWN",
    "COFACTOR_POOLS",
    "OBJECTIVES",
    "PROGRAMME_FIT",
    "STEP_ORDER",
    "STRATEGY_PLANS",
    "Route",
    "RouteStep",
    "cofactor_demand",
    "describe_demand",
    "insertion_plan",
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
    #: Reducing equivalents wanted per (compartment, cofactor). Empty for a route with no redox
    #: step, which no real route is.
    redox_demand: Mapping[tuple[str, str], int]
    score_balance: float | None
    score_transport: float | None
    score_feasibility: float | None
    score_evidence: float | None
    score_toxicity: float | None
    # Defaulted, so it sorts last among the fields. What the selected chassis does to this route:
    # empty when no chassis is selected, which the CLI reports as "ranked against none" rather
    # than as "nothing stands in the way".
    chassis_gates: tuple[ChassisGate, ...] = ()

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


def insertion_plan(steps: Sequence[RouteStep], loci: Sequence[MtdnaLocus]) -> tuple[str, ...]:
    """For a route carrying genes in mtDNA: where each could go, and what it costs.

    PLAN.md's phase-3 acceptance asks that strategy E routes be ranked "as *reachable but costly*
    rather than either dropped or flattered, and each names its **locus, leader, displaced gene
    and recoding requirement**." Until `mtdna_locus` existed the ranker could name only the last
    of those four, because the activator map was a YAML file nothing read.

    The plan is offered per mtDNA-carried step and is deliberately NOT a choice: the ranker states
    the cheapest option and what the alternatives cost, and a curator picks. Choosing a locus is
    construct design.
    """
    carried = [step for step in steps if step.needs_recoding]
    if not carried or not loci:
        return ()

    free = [locus for locus in loci if locus.is_free]
    costly = [locus for locus in loci if not locus.is_free and locus.activators]
    lines: list[str] = []
    for step in carried:
        if free:
            site = free[0]
            activators = ", ".join(site.activators or ()) or "none recorded"
            lines.append(
                f"{step.step_role} ({step.part.id}) -> locus {site.locus}, leader "
                f"{site.utr_source}, activator {activators}, displaces nothing, respiration "
                f"kept; recode to NCBI table 3"
            )
        else:
            site = costly[0]
            activators = ", ".join(site.activators or ()) or "none recorded"
            lines.append(
                f"{step.step_role} ({step.part.id}) -> locus {site.locus}, leader "
                f"{site.utr_source}, activator {activators}, displaces "
                f"{site.displaced_if_used}, respiration lost; recode to NCBI table 3"
            )
    if free and costly:
        lines.append(
            f"alternative: any of {len(costly)} gene loci "
            f"({', '.join(locus.locus for locus in costly[:3])}...) would instead displace that "
            f"gene and cost respiration -- see data/mitochondria/activator_map.yaml"
        )
    return tuple(lines)


def cofactor_demand(steps: Sequence[RouteStep]) -> dict[tuple[str, str], int]:
    """Reducing equivalents this route consumes, per compartment and per cofactor.

    ``_cofactor_gate`` above asks whether a compartment supplies a cofactor **at all**. This asks
    **how much** is wanted there, which is a different question and the one PLAN.md G.7's
    per-compartment redox criterion turns on. A route can be composed entirely of reactions that
    each balance -- ``curated.py`` refuses to load one that does not -- and still concentrate two
    NADPH demands in a compartment whose supply is the thin one.

    That is not hypothetical. The published yeast route is KivD + **Adh6**, and Adh6 is NADPH-
    dependent, so running it in the matrix wants **2 NADPH there** (Ilv5 and Adh6) rather than the
    one NADPH and one NADH that ISOBUTANOL_PROGRAM.md's prose describes. The parts catalog has
    carried the right cofactor per part all along; nothing added them up.
    """
    demand: dict[tuple[str, str], int] = {}
    for step in steps:
        wanted = step.part.cofactor_preference
        # 'either' is a genuine third answer for a promiscuous enzyme and is not a demand for a
        # particular pool; 'NA' means the step is not a redox step at all.
        if wanted in {"NA", "unknown", "either"}:
            continue
        key = (step.compartment, wanted)
        demand[key] = demand.get(key, 0) + 1
    return demand


def describe_demand(demand: Mapping[tuple[str, str], int]) -> tuple[str, ...]:
    """The demand tally as lines a route card can print, heaviest first."""
    return tuple(
        f"{count}x {cofactor} in {compartment}"
        for (compartment, cofactor), count in sorted(
            demand.items(), key=lambda item: (-item[1], item[0])
        )
    )


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
    parts: Sequence[Part],
    *,
    strategies: Sequence[str] | None = None,
    chassis: ChassisProfile | None = None,
) -> list[Route]:
    """Every {step -> part} x strategy combination, gated and scored.

    Generative: it does not ask what has been published, which is the only way the complement --
    what has never been tried -- can be read off the result.

    ``chassis`` applies `metabolic.chassis`'s per-strategy gates. Passing None ranks against no
    chassis at all, which is what happened to all 360 routes before schema v7, and the CLI says
    so rather than letting the ordering look considered.
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
            demand = cofactor_demand(steps)
            requirements = _code_gate(steps)
            gaps = _transport_gate(steps)

            gates = gates_for(chassis, strategy=strategy)
            disqualifying = tuple(g.message for g in gates if g.excludes)
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
                    # Stoichiometric impossibility was the only exclusion before v7, and there
                    # are none: every curated reaction balances. A chassis can now exclude too,
                    # but only for an impossibility -- a rho-zero strain cannot run a matrix
                    # pathway at all. Everything the chassis merely makes *expensive* stays in
                    # the list carrying its gate, because a cost is for the reader to weigh.
                    excluded_because=disqualifying,
                    cofactor_risks=tuple(cofactor_risks),
                    redox_demand=demand,
                    construction_requirements=tuple(requirements),
                    chassis_gates=gates,
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


#: The two questions ``rank`` can answer. They are different questions and the answer to one is
#: not the answer to the other, which is the whole reason this parameter exists.
OBJECTIVES: Final[tuple[str, ...]] = ("easiest", "programme")


#: How well each strategy fits **this programme's design intent**, 0..1, or None for "not
#: recorded".
#:
#: DELIBERATELY SEPARATE FROM ``feasibility``, and the separation is the point.
#: ``MITOCHONDRIAL_PROGRAM.md`` §4 already keeps two questions apart -- *is this technique
#: possible at all* (``feasibility_rating``) and *is it possible for you* (``available_here``).
#: This is a third question again: *is this what the programme is trying to build at all*. Folding
#: it into ``feasibility`` would destroy the first distinction to express the third, which is why
#: the obvious fix -- making feasibility chassis-aware -- is the wrong one.
#:
#: WHY EVERY VALUE IS None. These numbers encode design intent, and design intent is the owner's
#: to state, not the atlas's to infer. Seeded None so that ``objective="programme"`` currently
#: reproduces ``objective="easiest"`` exactly: the mechanism exists, and it changes nothing until
#: somebody fills it in. ``docs/design/DUET_TARGET.md`` §5 is where the reasoning for a value
#: would have to come from.
#:
#: THE OBSERVATION THIS EXISTS FOR (handover, 2026-09-21): confirming the chassis is rho+ cleared
#: strategy C's chassis gate and the ranking did not move, because ``rank`` separates B from C at
#: its *third* key -- feasibility, 0.80 against 0.60 -- while the chassis gate is the fourth. Those
#: constants encode technique difficulty, and DUET chose strategy C for reasons no measure of
#: technique difficulty knows about. The defect was never the constants; it was that the ranker
#: answers "easiest" while being read as "best".
PROGRAMME_FIT: Final[Mapping[str, float | None]] = {
    "A_native_split": None,
    "B_cytosolic_relocalization": None,
    "C_mitochondrial_ehrlich": None,
    "D_alternative_compartment": None,
    "E_mtdna_encoded": None,
}


def rank(
    routes: Sequence[Route],
    *,
    objective: str = "easiest",
    programme_fit: Mapping[str, float | None] = PROGRAMME_FIT,
) -> list[Route]:
    """Order viable routes by named components, lexicographically. Never by a weighted total.

    ``objective`` names **which question is being asked**, because there are two and they have
    different answers:

    ``"easiest"`` (the default, and the historical behaviour byte-for-byte)
        Transport gaps first -- a missing carrier is a hard engineering problem -- then cofactor
        supply risks, then feasibility, then chassis burdens, then construction requirements.
        This answers *what would be least trouble to build*.

    ``"programme"``
        The same order, except that programme fit is consulted **before** feasibility. This
        answers *what is this programme trying to build*, which is a question a measure of
        technique difficulty cannot reach. With ``PROGRAMME_FIT`` unfilled it returns the same
        order as ``"easiest"``; that is intended, not a stub.

    Evidence would lead under either objective if any existed; see :func:`enumerate_routes` on why
    it is NULL for every route today.
    """
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}, got {objective!r}")

    def key(route: Route) -> tuple[object, ...]:
        head: tuple[object, ...] = (len(route.transport_gaps), len(route.cofactor_risks))
        if objective == "programme":
            head += (-(programme_fit.get(route.strategy) or 0.0),)
        return head + (
            -(route.score_feasibility or 0.0),
            len([g for g in route.chassis_gates if not g.excludes]),
            len(route.construction_requirements),
            route.id,
        )

    return sorted((route for route in routes if route.viable), key=key)


def explain(
    route: Route,
    *,
    objective: str = "easiest",
    programme_fit: Mapping[str, float | None] = PROGRAMME_FIT,
) -> str:
    """Why this route ranks where it does, by naming the dominating term.

    The objective is printed rather than assumed. A reader who does not know which question was
    asked cannot read the answer, and "easiest" being the default makes that misreading easy.
    """
    if not route.viable:
        return f"EXCLUDED: {'; '.join(route.excluded_because)}"
    fit = programme_fit.get(route.strategy)
    parts = [
        f"objective={objective}",
        f"strategy={route.strategy}",
        f"feasibility={route.score_feasibility:.2f}",
        f"programme_fit={'unrecorded' if fit is None else format(fit, '.2f')}",
        f"transport_gaps={len(route.transport_gaps)}",
        f"cofactor_risks={len(route.cofactor_risks)}",
        # The fourth key of `rank`, and it was the one term the ranker used and `explain` did not
        # print. PLAN.md phase 3 asks that "every rank is explainable term by term"; with this
        # missing, two routes separated ONLY by a chassis gate -- which is exactly what happens to
        # strategy E under a chassis with mtDNA tooling recorded -- were ordered for a reason the
        # explanation did not contain.
        f"chassis_gates={len([g for g in route.chassis_gates if not g.excludes])}",
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
