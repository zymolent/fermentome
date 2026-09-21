"""Route enumeration and ranking — PLAN.md G.7, "the atlas's primary output".

Enumeration is **generative, not a catalogue of published builds**. That is what lets "what has
never been tried" be answered as the complement of the evidence rather than as a guess::

    pathway_route = { step -> part } x compartment assignment per step
                    x cofactor strategy x host x deletion set

**THE OPTIONAL SIXTH ROLE** (owner's ruling, 2026-09-22). Until today the five roles in
``STEP_ORDER`` all *consumed* reducing power and none regenerated it, so no route could close --
0 balanced, 600 unbalanced, 200 unknown -- and the atlas could not express the redox closure DUET
is built on (``ADH3`` makes matrix NADH, ``POS5`` turns it into the matrix NADPH Ilv5 needs).
``cofactor_cycle`` is now a role a route MAY carry. It is optional, expressed as a power set whose
empty member is first and is a real value; ``STEP_ORDER`` is deliberately unchanged. See
:data:`ROUTE_STEP_ROLES` for the whole argument and the alternative rejected.

Each enumerated route then passes six gates. Two of them can exclude a route outright; the rest
produce a score *component*.

**Scores are never summed.** ``pathway_route`` has five score columns and no total, which is the
schema enforcing G.7's rule: a route's rank must be explainable by naming which term dominated,
and a weighted total destroys exactly that. Ranking is lexicographic over named components, and
:func:`explain` prints the reason.

**A route with no supporting evidence is displayed, not hidden** -- that is the point of the
exercise -- but in its own Zone I band, never interleaved with demonstrated ones.

**PER-COMPARTMENT REDOX: FLAG, DO NOT EXCLUDE** (owner's ruling, 2026-09-22, settling decision D1
of ``docs/drafts/phase3/ACCEPTANCE.md``). G.7's gate table said a route whose per-compartment redox
balance does not close is *excluded* with the imbalance named. It is now **marked** with the
imbalance named, and stays in :func:`enumerate_routes` and in :func:`rank`. Nothing is dropped on
an unchecked premise. :func:`redox_balance` computes the sum **separately per compartment** from
the curated reaction stoichiometry, and where that stoichiometry is not in the atlas the answer is
``unknown`` -- never ``balanced``. See :class:`RedoxBalance` for where the flag lives and why, and
:func:`rank` for why it is deliberately not a sort key.

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
from dataclasses import dataclass, replace
from typing import Final

from ..genetic_code import table_for_compartment
from .chassis import ChassisGate, ChassisProfile, gates_for
from .curated import CuratedPathway, Metabolite, Part, Reaction
from .mtdna_loci import MtdnaLocus

__all__ = [
    "CARRIER_KNOWN",
    "COFACTOR_CYCLE",
    "COFACTOR_POOLS",
    "OBJECTIVES",
    "PROGRAMME_FIT",
    "ROUTE_PRODUCT",
    "ROUTE_STEP_ROLES",
    "STEP_ORDER",
    "STRATEGY_PLANS",
    "RedoxBalance",
    "Route",
    "RouteStep",
    "cofactor_cycle_sets",
    "cofactor_demand",
    "describe_demand",
    "insertion_plan",
    "enumerate_routes",
    "explain",
    "pathway_for_routes",
    "rank",
    "redox_balance",
    "write_routes",
]

#: The five catalytic steps, in pathway order, and **the five every route must fill**. Competing
#: reactions are not steps: they are what a deletion set acts on, not something a route chooses a
#: part for.
#:
#: THIS TUPLE IS NOT "THE ROLES A ROUTE CAN CARRY". It is the roles a route MUST carry, and that
#: distinction became load-bearing on 2026-09-22 when ``cofactor_cycle`` arrived -- see
#: :data:`ROUTE_STEP_ROLES` immediately below for where the optional role lives and why it is not
#: here.
STEP_ORDER: Final[tuple[str, ...]] = ("AHAS", "KARI", "DHAD", "KDC", "ADH")

#: The optional sixth role: a step that **regenerates** a cofactor rather than consuming one.
#: ``POS5``, ``ADH3`` and ``GPD`` are its parts.
COFACTOR_CYCLE: Final[str] = "cofactor_cycle"

#: Every role a :class:`RouteStep` can carry. The five required ones, then the optional one.
#:
#: ------------------------------------------------------------------------------------------
#: HOW OPTIONALITY IS EXPRESSED, AND THE ALTERNATIVE REJECTED (owner's ruling, 2026-09-22)
#: ------------------------------------------------------------------------------------------
#:
#: THE PROBLEM. Until today the five catalytic steps all *consumed* reducing power and none
#: regenerated it, so no route could ever close and the flag read 0 balanced / 600 unbalanced /
#: 200 unknown. That was structural, not a bug: there was no slot for a cofactor-regenerating
#: step. It is also exactly what DUET is -- ``ADH3`` oxidises matrix ethanol to matrix NADH and
#: ``POS5`` phosphorylates that NADH to the matrix NADPH Ilv5 needs (``DUET_TARGET.md`` §3) -- so
#: the atlas could not express the redox closure the whole programme depends on.
#:
#: **THE CHOICE: a power set over the cofactor-cycle parts, whose empty member is a first-class
#: value.** :func:`cofactor_cycle_sets` returns ``((), ("adh3_native",), ..., ("adh3_native",
#: "pos5_native"), ...)`` with ``()`` **first**, and the enumerator multiplies the five-step
#: product by it. A route with no cofactor cycle is the empty member: a real route, not a
#: deficient one, and byte-for-byte the route it was yesterday, because the route id appends
#: nothing for an empty set. The 800 pre-existing routes therefore still enumerate, with their
#: ids, their gates and their relative rank order unchanged.
#:
#: *Why a set rather than a single nullable slot.* DUET is **two genes acting in series**, and a
#: one-part slot can hold Adh3 or Pos5 but not both -- which would leave the exact gap this change
#: exists to close. A set can also say "no cofactor cycle" without a sentinel: the empty set is a
#: value, where ``None`` in a slot is an absence that every consumer has to remember to handle.
#:
#: *Why the role is NOT a member of* ``STEP_ORDER``, *although that is the obvious place for it.*
#: ``STEP_ORDER`` is read by ``metabolic/recall.py`` as **the roles a published configuration must
#: fill before it can be called re-discovered** (``resolve_roles`` seeds one bucket per member;
#: ``classify`` demands ``not unfilled``). No paper's enzyme list names POS5 -- it is a host gene,
#: not a pathway enzyme -- so putting the role in ``STEP_ORDER`` would leave ``cofactor_cycle``
#: permanently unfilled and make **every published configuration unmatchable**. That is not a
#: prediction: today's ``fermdb atlas recall`` matches two of the four configurations, and both
#: would have dropped to ``under_specified``. ``tests/test_recall.py``'s
#: ``test_a_cofactor_cycle_gene_is_recognised_but_fills_no_step_role`` asserts
#: ``unfilled_roles == STEP_ORDER`` for POS5 and pins the same contract from the other side.
#:
#: So the two tuples say two different things and both are needed: ``STEP_ORDER`` is the contract
#: with the literature ("a build is five choices"), ``ROUTE_STEP_ROLES`` is the contract with the
#: enumerator ("a route may also carry cofactor-cycle parts").
ROUTE_STEP_ROLES: Final[tuple[str, ...]] = (*STEP_ORDER, COFACTOR_CYCLE)

_MATRIX: Final[str] = "mitochondrial_matrix"
_CYTOSOL: Final[str] = "cytosol"
_PEROXISOME: Final[str] = "peroxisome"


@dataclass(frozen=True)
class StrategyPlan:
    """Where each step runs, and on which genome its gene is carried, for one strategy.

    **Covers the five catalytic steps only.** A compartment strategy is a statement about where
    the *pathway* is assembled; it says nothing about a cofactor-cycle enzyme, which takes its
    compartment and its encoding genome from its own part -- see :func:`_cofactor_cycle_step`.
    """

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
#:
#: SETTLED 2026-09-22 (decision D1). The owner's ruling is that the argument above holds and is
#: extended to the redox clause itself: flag, do not exclude. Note what this map still is NOT --
#: it says *which* cofactors a compartment has and never *how much*, so it cannot serve as the
#: supply side of :func:`redox_balance`. That function reports a demand that does not close; it
#: does not claim the compartment cannot meet it.
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


#: The product whose pathway the enumerator enumerates. ``STEP_ORDER``, the handoff metabolites in
#: ``_transport_gate`` and ``CARRIER_KNOWN`` are all isobutanol-specific already; naming it here is
#: what lets :func:`pathway_for_routes` pick the right curated file instead of pooling reactions by
#: step role across every pathway in ``data/pathways/``. That pooling would be wrong rather than
#: merely loose: ``ethanol_reference.yaml`` carries an ADH written in the **oxidative** direction
#: (``adh2_reverse``), so a route's ADH step would have two contradictory stoichiometries and the
#: honest verdict would collapse to ``unknown`` for all 600 routes.
ROUTE_PRODUCT: Final[str] = "isobutanol"

#: The reduced member of each redox pool, in the vocabulary ``parts_catalog.yaml`` uses for
#: ``cofactor_preference``. The curated metabolites name the *pool* (``nad``/``nadp``); the parts
#: name the *reduced species* (``NADH``/``NADPH``). One translation, in one place, rather than two
#: vocabularies quietly compared and found to differ.
_REDUCED_OF_POOL: Final[Mapping[str, str]] = {"nad": "NADH", "nadp": "NADPH"}

#: ``cofactor_preference`` values that are not the name of a pool. 'NA' means the step is not a
#: redox step; the other two mean the catalog declines to say which pool, which is a different
#: thing again and must not be read as 'neither'.
_NOT_A_POOL: Final[frozenset[str]] = frozenset({"NA"})
_POOL_UNDECLARED: Final[frozenset[str]] = frozenset({"unknown", "either"})

_SUBSTRATE: Final[str] = "substrate"
_PRODUCT: Final[str] = "product"

#: ``balance_status`` as ``pathway_route`` spells it. The route-level word is the left column and
#: the stored word is the right one; the mapping lives here so that the schema's three-value CHECK
#: and this module's three-value status cannot drift apart.
#:
#: 'fail' STORED ON A ROUTE THAT IS STILL OFFERED is the owner's 2026-09-22 ruling expressed in the
#: existing vocabulary: the column says whether the balance closes, and `excluded_because` says
#: whether the route is dropped. They were the same question until today and they are not any more.
_DB_BALANCE_STATUS: Final[Mapping[str, str]] = {
    "balanced": "pass",
    "unbalanced": "fail",
    "unknown": "not_evaluated",
}


@dataclass(frozen=True)
class RedoxBalance:
    """The per-compartment redox sum for one route, with the imbalance named where it is open.

    WHERE THE FLAG LIVES, AND WHY THIS AND NOT A BOOLEAN OR A COMPANION MAP.

    *Not a boolean.* ``unbalanced: true`` is not an artifact anybody can act on. "NADPH short by 2
    in the mitochondrial matrix" names a compartment, a pool and a magnitude, which is a design
    instruction -- overexpress Pos5, switch the KARI, or move the step. So the record carries
    :attr:`net` per ``(compartment, cofactor)`` and :attr:`imbalances` as sentences built from it.

    *Not a companion map keyed by route id.* Every other gate output a route carries --
    ``transport_gaps``, ``cofactor_risks``, ``chassis_gates``, ``construction_requirements`` -- is
    a field on :class:`Route`, and a sixth one delivered as a side table would have to be threaded
    through :func:`rank`, :func:`explain`, :func:`write_routes`, the CLI and the recall harness by
    hand. The first caller to forget it gets a route with no balance and **no way to tell that from
    a balanced one**, which is precisely the absence-is-not-zero failure this module refuses
    everywhere else. A field cannot be forgotten.

    *Three states, not two.* ``unknown`` is a first-class answer and is never rounded to
    ``balanced``. A route whose stoichiometry is not in the atlas has not been checked; saying it
    balances would be the fabricated reassurance the acceptance note warns against.
    """

    #: 'balanced' | 'unbalanced' | 'unknown'.
    status: str
    #: ``(compartment, reduced cofactor) -> net reduced equivalents``. Negative is a shortfall: the
    #: route consumes more in that compartment than its own steps regenerate there. Summed **per
    #: compartment**, never pooled across them -- PLAN.md B.6.4 is explicit that a route split
    #: across membranes must balance in each compartment separately, and the inner membrane does
    #: not pass NAD(P)(H).
    net: Mapping[tuple[str, str], float]
    #: One sentence per step whose contribution could not be derived. Non-empty forces ``unknown``:
    #: a sum with a missing term is not a sum.
    unknowns: tuple[str, ...]
    #: One sentence per step whose *pool* was taken from the part rather than from the reaction.
    #: Recorded rather than silent, because it is the one inference this calculation makes.
    substitutions: tuple[str, ...]

    @property
    def db_status(self) -> str:
        """The word ``pathway_route.balance_status`` accepts for this state."""
        return _DB_BALANCE_STATUS[self.status]

    @property
    def open_buckets(self) -> tuple[tuple[str, str, float], ...]:
        """``(compartment, cofactor, net)`` for every bucket that does not close, heaviest first."""
        return tuple(
            (compartment, cofactor, value)
            for (compartment, cofactor), value in sorted(
                ((key, value) for key, value in self.net.items() if value),
                key=lambda item: (-abs(item[1]), item[0]),
            )
        )

    @property
    def imbalances(self) -> tuple[str, ...]:
        """One sentence per open bucket, heaviest first.

        Derived from :attr:`net` rather than stored beside it, so the sentence a reader sees and
        the number a query reads cannot drift apart -- the same reason
        :attr:`Route.balance_status` is a property.
        """
        return tuple(
            _name_imbalance(compartment, cofactor, value)
            for compartment, cofactor, value in self.open_buckets
        )

    def summary(self) -> str:
        """The flag as one printable clause, naming the imbalance rather than asserting one."""
        if self.status == "balanced":
            return "balanced"
        detail = self.imbalances if self.status == "unbalanced" else self.unknowns
        if self.status == "unknown" and self.imbalances:
            # Some buckets resolved and some did not. Print both, or the reader sees "unknown" and
            # loses the part that IS known.
            detail = self.imbalances + ("not evaluated: " + self.unknowns[0],)
        return f"{self.status} ({'; '.join(detail) or 'no detail recorded'})"


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
    #: The per-compartment redox verdict. A record, not a boolean and not a status string: see
    #: :class:`RedoxBalance` for why it lives here rather than in a companion table.
    redox_balance: RedoxBalance
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
        """Whether the route is offered at all.

        **A failing redox balance does not enter here**, by the owner's 2026-09-22 ruling. A route
        whose balance does not close is flagged and stays; only a stoichiometric impossibility or a
        chassis disqualification takes a route out of the list.
        """
        return not self.excluded_because

    @property
    def cofactor_cycle(self) -> tuple[RouteStep, ...]:
        """The optional cofactor-regenerating steps, which most routes do not have.

        Empty is a **real answer and not a deficiency**: most published builds carry no
        cofactor-cycle gene, and a route without one is a route, not an incomplete one. Derived
        from :attr:`steps` rather than stored beside it so the two cannot disagree.
        """
        return tuple(step for step in self.steps if step.step_role == COFACTOR_CYCLE)

    @property
    def balance_status(self) -> str:
        """``pathway_route.balance_status``, DERIVED rather than stored beside the record.

        A status string and a structured record that can disagree is two sources of truth, and the
        one that gets written to the database would be the one nobody re-derives. This cannot
        disagree with :attr:`redox_balance` because there is nothing to disagree with.
        """
        return self.redox_balance.db_status


# ---------------------------------------------------------------------------------- the gates


def _cofactor_gate(steps: Sequence[RouteStep]) -> list[str]:
    """Steps whose cofactor the compartment is not recorded as supplying.

    A *risk*, not an exclusion, because :data:`COFACTOR_POOLS` is unverified. A route carrying
    this risk needs either a supply intervention (overexpress Pos5), a cofactor-switched part
    (the NADH-preferring KARI), or a measurement that settles the pool -- and naming which is the
    useful output, where dropping the route silently would not be.

    **A cofactor-cycle step is skipped**, and that is a judgement rather than an oversight. This
    gate asks "does the compartment supply the pool this step *needs*", and a cofactor-cycle
    part's ``cofactor_preference`` names the pool it **acts on**, with the direction living in the
    curated reaction and nowhere else. Adh3 declares ``NADH`` and *produces* it; asking whether
    the matrix supplies Adh3's NADH is the wrong question asked of the right field.
    :func:`redox_balance` asks the signed question, which is the one worth asking.
    """
    problems: list[str] = []
    for step in steps:
        if step.step_role == COFACTOR_CYCLE:
            continue
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

    **A cofactor-cycle step contributes no demand**, for the reason given in
    :func:`_cofactor_gate`: it is the supply side, its ``cofactor_preference`` carries no
    direction, and counting Adh3's NADH here would file a *source* of reducing power as a demand
    for it -- an error that would read as a measurement.
    """
    demand: dict[tuple[str, str], int] = {}
    for step in steps:
        if step.step_role == COFACTOR_CYCLE:
            continue
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


# -------------------------------------------------- the per-compartment redox balance (C2, D1)


def _merge_cofactor_cycle(
    product: CuratedPathway, pathways: Sequence[CuratedPathway]
) -> CuratedPathway:
    """``product`` plus every ``cofactor_cycle`` reaction curated in the other pathway files.

    THE ONE POOLING ACROSS FILES THIS MODULE PERMITS, and the reason it is safe where pooling the
    five catalytic roles is not.

    The catalytic roles are **product-specific**, and two files disagree about them:
    ``ethanol_reference.yaml`` writes its ADH in the *oxidative* direction, so pooling by role
    would hand the ADH step two contradictory stoichiometries and collapse every route to
    ``unknown``. That is why :func:`pathway_for_routes` picks one file by product.

    A cofactor-cycle reaction is not about the product at all. Pos5's NADH kinase phosphorylates
    matrix NADH whichever alcohol the route is making, and there is exactly **one** curated
    reaction per cofactor-cycle gene, so the three of them (``adh3_matrix``, ``pos5_nadh_kinase``,
    ``gpd_glycerol3p``) are distinguishable from each other by gene -- which is how
    :func:`redox_balance` picks the one a step's part refers to. They are curated in
    ``ethanol_reference.yaml`` because that is where the ethanol/acetaldehyde shuttle lives, and a
    second copy of them in the isobutanol file would be two records to disagree.

    Doing the merge HERE rather than as an extra parameter on :func:`enumerate_routes` is
    deliberate. A second argument threaded through the enumerator, the CLI's three call sites and
    the recall harness is one a caller can forget, and a caller who forgets it gets a route whose
    cofactor cycle contributes nothing with **no way to tell that from a route that has none** --
    the absence-is-not-zero failure this module refuses everywhere else.

    A metabolite id shared between the files whose definitions **differ** blocks the reaction that
    uses it: it is not merged, its step reports ``unknown`` with the role named, and nothing is
    summed from two records that do not agree about what a molecule is.
    """
    metabolites = dict(product.metabolites)
    existing = {reaction.id for reaction in product.reactions}
    merged: list[Reaction] = list(product.reactions)

    for pathway in pathways:
        if pathway is product:
            continue
        for reaction in pathway.reactions:
            if reaction.step_role != COFACTOR_CYCLE or reaction.id in existing:
                continue
            wanted = {
                p.metabolite: pathway.metabolites.get(p.metabolite) for p in reaction.participants
            }
            if any(
                metabolite is None or metabolites.get(key, metabolite) != metabolite
                for key, metabolite in wanted.items()
            ):
                continue
            metabolites.update({key: m for key, m in wanted.items() if m is not None})
            existing.add(reaction.id)
            merged.append(reaction)

    if len(merged) == len(product.reactions):
        return product
    return replace(product, metabolites=metabolites, reactions=tuple(merged))


def pathway_for_routes(pathways: Sequence[CuratedPathway]) -> CuratedPathway | None:
    """The curated pathway whose reactions the enumerator's step roles refer to.

    Picked by product rather than by pooling every curated reaction that carries a matching
    ``step_role``: ``ethanol_reference.yaml`` also declares a KDC and two ADH reactions, and one of
    those ADHs is written in the **oxidative** direction. Pooling them would give the ADH step two
    contradictory stoichiometries, and the only honest verdict for a contradiction is ``unknown``
    -- so the loose rule would not merely be sloppy, it would erase the answer for all 600 routes.

    The enumerator's step roles now include the optional ``cofactor_cycle``, whose reactions are
    curated in ``ethanol_reference.yaml`` beside the ethanol/acetaldehyde shuttle they belong to.
    Those, and only those, are merged in -- see :func:`_merge_cofactor_cycle` for why that one
    pooling is safe where pooling the catalytic roles is not.

    Returns None rather than raising when no pathway matches. An absent pathway is reported as
    ``unknown`` on every route, which is the correct state for "nothing was supplied to check
    against" and is what :func:`redox_balance` does with it.
    """
    for pathway in pathways:
        if pathway.product == ROUTE_PRODUCT:
            return _merge_cofactor_cycle(pathway, pathways)
    return None


def _reduced_equivalents(
    reaction: Reaction, metabolites: Mapping[str, Metabolite]
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Net reduced equivalents this reaction produces (+) or consumes (-), per redox pool.

    Read off ``reaction_participant``'s signed coefficient and ``metabolite``'s ``redox``/``pair``
    columns -- the curated data, not an assumption about what an EC number usually does.

    Only the **reduced** member is counted. Every curated reaction already conserves carriers
    (``curated.check_balance`` refuses to load one that does not), so counting NAD+ as well would
    make every reaction sum to zero and the check would be vacuous. What a route actually spends is
    reducing power, and that is the reduced member alone.

    The reaction is taken in the direction its curated equation is written; the Ehrlich ADH is
    ``reversible: true`` and is written reductively, which is the direction a route uses it in.

    Second return value: redox participants filed under role ``'cofactor'`` rather than
    substrate/product. That role carries no direction, so its contribution cannot be signed, and a
    step that has one is reported ``unknown`` instead of being silently dropped.
    """
    net: dict[str, float] = {}
    undirected: list[str] = []
    for participant in reaction.participants:
        metabolite = metabolites.get(participant.metabolite)
        if metabolite is None or metabolite.redox != "reduced" or metabolite.pair is None:
            continue
        if participant.role == _PRODUCT:
            sign = 1.0
        elif participant.role == _SUBSTRATE:
            sign = -1.0
        else:
            undirected.append(metabolite.name)
            continue
        net[metabolite.pair] = net.get(metabolite.pair, 0.0) + sign * participant.coefficient
    return {pool: value for pool, value in net.items() if value}, tuple(undirected)


def _name_imbalance(compartment: str, cofactor: str, value: float) -> str:
    """One named imbalance: a compartment, a pool and a magnitude.

    "NADPH short by 1 in mitochondrial_matrix", never "unbalanced: true" -- the first is a design
    instruction and the second is a fact nobody can act on.
    """
    direction = "short by" if value < 0 else "in surplus by"
    return f"{cofactor} {direction} {abs(value):g} in {compartment}"


def _reactions_for(step: RouteStep, candidates: Sequence[Reaction]) -> list[Reaction]:
    """The curated reaction(s) this step refers to, narrowed by gene symbol where it has to be.

    One role, one reaction, for the five catalytic steps in the isobutanol file -- so this returns
    the candidates untouched and the narrowing below never fires for them.

    ``cofactor_cycle`` is the role that needs it: three curated reactions share it, and they are
    three *different interventions* (Adh3 supplies matrix NADH, Pos5 converts it to matrix NADPH,
    Gpd spends cytosolic NADH on glycerol), not three descriptions of one. The part says which by
    the gene it carries, and that is an identity claim the curated files already make on both
    sides -- ``pos5_native`` carries POS5, ``pos5_nadh_kinase`` names POS5 -- rather than an
    inference this function invents.

    Exact, case-folded symbol equality, never substring: ADH3 and ADH1 differ by a character, and
    a loose match here would attach the matrix ethanol oxidation to the fermentative enzyme and
    sum a *source* of reducing power where a sink belongs. If the genes do not narrow the set to
    exactly one the candidates come back unnarrowed, and the caller reports ``unknown`` because
    the reactions disagree -- which is the honest answer to "the atlas does not say which".
    """
    if len(candidates) < 2:
        return list(candidates)
    genes = {gene.casefold() for gene in step.part.genes}
    narrowed = [r for r in candidates if genes & {gene.casefold() for gene in r.genes}]
    return narrowed if len(narrowed) == 1 else list(candidates)


def redox_balance(steps: Sequence[RouteStep], pathway: CuratedPathway | None) -> RedoxBalance:
    """Sum the route's cofactor stoichiometry **separately for each compartment**.

    PLAN.md B.6.4 and G.7: a route split across membranes must balance in each compartment
    separately, because the inner membrane does not pass NAD(P)(H). Summing globally would let a
    matrix NADPH debt be paid by a cytosolic NADH surplus, which is the exact error the DUET
    architecture exists because of.

    HOW A STEP'S CONTRIBUTION IS DERIVED, and the one inference this makes.

    The **magnitude and sign** come from the curated reaction for that step role -- real
    stoichiometry out of ``reaction_participant`` and ``metabolite``, never invented. The
    **compartment** comes from the route, not from the reaction: relocalizing a step is the whole
    point of a compartment strategy, so the reaction's own ``compartment`` column says where the
    enzyme natively sits and is deliberately not used here.

    The **pool** comes from the part. A curated reaction is written for one representative enzyme
    (``kari`` for Ilv5, on NADPH; ``adh_isobutanol`` for the Adh1 type, on NADH) while the catalog
    carries NADH-preferring KARI variants and the NADPH-preferring Adh6 -- which is the variation
    the atlas exists to reason about. Where the part's ``cofactor_preference`` differs from the
    reaction's pool, the coefficient is kept and the pool is taken from the part, and **that
    substitution is recorded by name** in :attr:`RedoxBalance.substitutions` rather than applied
    silently. It is the only step of this calculation that is not straight out of the data.

    THE COFACTOR-CYCLE STEP, added 2026-09-22, and the one case that is unlike every other.

    An optional ``cofactor_cycle`` step contributes **with the sign its curated reaction is written
    in**, through the same arithmetic as everything else -- nothing here special-cases "this one
    produces". Adh3 oxidises matrix ethanol, so ``adh3_matrix`` has NADH as a *product* and
    contributes ``+1`` to the matrix NADH bucket. Gpd reduces DHAP, so ``gpd_glycerol3p`` has NADH
    as a *substrate* and contributes ``-1`` to cytosolic NADH: a cofactor-cycle step is **not
    assumed to be a source**. It regenerates the member of the couple its reaction regenerates,
    and for Gpd that member is the *oxidised* one, which this function does not count. That is
    worth saying plainly because "cofactor cycle" sounds like "free reducing power" and is not.

    Which of the three curated cofactor-cycle reactions a step refers to is decided by **gene
    symbol** against the part: ``pos5_native`` carries POS5 and ``pos5_nadh_kinase`` names POS5.
    If the genes do not narrow it to one reaction the step is ``unknown``, never guessed.

    **Pos5 is the interesting case, and it is different in kind from every other step in this
    model.** It consumes matrix NADH and produces matrix **NADPH**: one compartment, two pools. It
    therefore moves reducing power *between pools within a compartment* rather than into or out of
    the route, and both terms are placed in the step's own compartment. ``curated.py`` already
    knows this reaction is special -- it is the only one carrying ``transfers_redox_pool``, and the
    per-pool half of ``check_balance`` is relaxed for it alone -- so this function keys on that
    declared flag rather than inferring a transfer from "two pools appeared".

    Two things must not happen there and neither does:

    * *the pool must not be taken from the part.* The substitution above answers "which pool does
      this enzyme draw on", and a transfer touches two; a single ``cofactor_preference`` cannot
      say how a different kinase would split them. The reaction's own pools are used verbatim.
    * *it must not create reducing power from nothing.* A transfer conserves total reduced
      equivalents -- ``-1 NADH + 1 NADPH = 0`` -- and that is **checked**, not assumed: a declared
      transfer whose terms do not sum to zero is reported ``unknown`` with the sum named. Without
      that check a mistyped coefficient would manufacture a balanced route out of a typo, and a
      balanced route is the one output nobody would re-derive.

    WHY NO ROUTE COMES BACK ``balanced`` EVEN NOW, and why that is a sharper finding than the one
    it replaces. It used to be that ``STEP_ORDER`` had no slot for a regenerating step, so closure
    was structurally unreachable. It is reachable now, and still unreached, for an arithmetic
    reason the slot exposed rather than caused: a route spends **two** reducing equivalents (the
    KARI and the ADH), the only curated cofactor-cycle reaction that *supplies* one is Adh3, and
    it supplies **one**. Pos5 moves a debt between pools and Gpd deepens it. So the best any route
    reaches is a single open bucket -- and on the native split with Pos5 and Adh3 together that
    bucket is in the **cytosol**, with the mitochondrial matrix closing completely, which is the
    DUET claim arriving as arithmetic rather than as prose. Closing the last one needs either a
    second equivalent of Adh3 flux (stoichiometric multiplicity this route model does not express,
    since a part is chosen once) or a cytosolic NADH-regenerating part the atlas has not curated.

    ``unknown`` is returned, never ``balanced``, when any step's contribution cannot be derived.
    """
    if pathway is None:
        return RedoxBalance(
            status="unknown",
            net={},
            unknowns=(
                "no curated pathway was supplied, so there is no reaction stoichiometry to sum; "
                "this is 'not evaluated' and must never be read as 'balanced'",
            ),
            substitutions=(),
        )

    by_role: dict[str, list[Reaction]] = {}
    for reaction in pathway.reactions:
        if reaction.step_role in ROUTE_STEP_ROLES:
            by_role.setdefault(reaction.step_role, []).append(reaction)

    net: dict[tuple[str, str], float] = {}
    unknowns: list[str] = []
    substitutions: list[str] = []

    for step in steps:
        where = f"{step.step_role} ({step.part.id}) in {step.compartment}"
        candidates = _reactions_for(step, by_role.get(step.step_role, []))
        if not candidates:
            unknowns.append(
                f"{where}: no reaction in curated pathway {pathway.id} carries step role "
                f"{step.step_role}, so its redox stoichiometry is not in the atlas"
            )
            continue

        tallies = [(r.id, *_reduced_equivalents(r, pathway.metabolites)) for r in candidates]
        unsigned = [(rid, names) for rid, _, names in tallies if names]
        if unsigned:
            rid, names = unsigned[0]
            unknowns.append(
                f"{where}: {rid} files {', '.join(names)} under role 'cofactor', which carries no "
                f"direction, so the sign of its contribution is not recorded"
            )
            continue
        distinct = {tuple(sorted(pools.items())) for _, pools, _ in tallies}
        if len(distinct) > 1:
            unknowns.append(
                f"{where}: {len(candidates)} curated reactions carry step role {step.step_role} "
                f"({', '.join(rid for rid, _, _ in tallies)}) and they disagree on the redox "
                f"stoichiometry, so the atlas does not say which one this step is"
            )
            continue

        reaction_id, pools, _ = tallies[0]
        unmapped = sorted(pool for pool in pools if pool not in _REDUCED_OF_POOL)
        if unmapped:
            unknowns.append(
                f"{where}: {reaction_id} uses redox pool(s) {', '.join(unmapped)}, which this "
                f"module has no cofactor name for, so the demand cannot be placed in a pool"
            )
            continue
        named = {_REDUCED_OF_POOL[pool]: value for pool, value in pools.items()}
        wanted = step.part.cofactor_preference
        reaction = candidates[0]

        if reaction.transfers_redox_pool:
            # POS5, AND NOTHING ELSE IN THE ATLAS. A declared pool transfer moves a reducing
            # equivalent from one pool to the other **inside one compartment**: Pos5 phosphorylates
            # matrix NADH to matrix NADPH, so its terms are -1 NADH and +1 NADPH and both belong
            # to the step's own compartment. Every other step in this model spends or makes
            # reducing power; this one only relocates it between pools, which is the DUET coupling
            # itself and the reason `transfers_redox_pool` is a declared column rather than
            # something inferred from "two pools turned up".
            #
            # `wanted` IS DELIBERATELY NOT CONSULTED. The substitution below answers "which single
            # pool does this enzyme draw on", and that question has no answer for a transfer. The
            # reaction's own pools are used verbatim, so nothing is inferred here at all.
            #
            # AND IT MUST NOT CREATE REDUCING POWER FROM NOTHING. A transfer conserves the total,
            # so the terms have to sum to zero; a declared transfer that does not is a curation
            # error and is reported `unknown` with the sum named. Skipping this check would let a
            # mistyped coefficient manufacture a *balanced* route -- the one verdict in this module
            # that nobody would go back and re-derive.
            moved = sum(named.values())
            if moved:
                unknowns.append(
                    f"{where}: {reaction_id} is declared as a redox-pool transfer but its reduced "
                    f"equivalents sum to {moved:+g} rather than 0 "
                    f"({', '.join(f'{k} {v:+g}' for k, v in sorted(named.items()))}); a transfer "
                    f"relocates reducing power between pools and cannot create it, so this is a "
                    f"curation error and the step is not summed"
                )
                continue
            for cofactor, value in named.items():
                key = (step.compartment, cofactor)
                net[key] = net.get(key, 0.0) + value
            continue

        if not named:
            if wanted in _NOT_A_POOL:
                # A non-redox step contributing nothing. This is KNOWN to be zero -- the reaction
                # has no redox participant and the part agrees -- and must not be filed as unknown,
                # or three of the five steps would poison every route's verdict.
                continue
            unknowns.append(
                f"{where}: {reaction_id} has no redox participant but the part is recorded as "
                f"using {wanted}; the atlas does not say how much of it the step consumes"
            )
            continue
        if wanted in _POOL_UNDECLARED:
            unknowns.append(
                f"{where}: {reaction_id} turns over {'/'.join(sorted(named))} but the part's "
                f"cofactor_preference is {wanted!r}, so which pool it draws on is not recorded"
            )
            continue
        if wanted in _NOT_A_POOL:
            unknowns.append(
                f"{where}: {reaction_id} turns over {'/'.join(sorted(named))} but the part is "
                f"recorded as using no cofactor; the catalog and the pathway file disagree and "
                f"this module will not pick a winner"
            )
            continue
        if len(named) > 1:
            unknowns.append(
                f"{where}: {reaction_id} touches both redox pools, and a single "
                f"cofactor_preference cannot say how a different enzyme would split them"
            )
            continue

        ((reaction_cofactor, value),) = named.items()
        if wanted != reaction_cofactor:
            substitutions.append(
                f"{where}: {reaction_id} is written for {reaction_cofactor}; the part declares "
                f"{wanted}, so the coefficient is kept and the pool is taken from the part"
            )
        key = (step.compartment, wanted)
        net[key] = net.get(key, 0.0) + value

    if unknowns:
        status = "unknown"
    elif any(net.values()):
        status = "unbalanced"
    else:
        status = "balanced"
    return RedoxBalance(
        status=status,
        net=dict(net),
        unknowns=tuple(unknowns),
        substitutions=tuple(substitutions),
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


def cofactor_cycle_sets(parts: Sequence[Part]) -> tuple[tuple[Part, ...], ...]:
    """Every combination of cofactor-cycle parts a route may carry, **empty set first**.

    THIS FUNCTION IS WHERE "OPTIONAL" IS EXPRESSED. See :data:`ROUTE_STEP_ROLES` for the full
    argument; the two properties that matter to a caller are here:

    * ``()`` is a **member**, not a missing value. A route with no cofactor cycle is one of the
      combinations this returns, so it is enumerated, gated, ranked and stored by exactly the same
      code as every other route. Nothing anywhere asks "is there a cycle step" and takes a second
      branch, which is the failure mode a nullable slot invites.
    * ``()`` is **first**, and that ordering is load-bearing rather than tidy. The routes for one
      five-part combination come out with the cycle-free one at the head, so the first route the
      recall harness finds agreeing with a published build is the one that adds no intervention
      the paper never made. A published configuration names five enzymes and no cofactor cycle;
      reporting its match as a route carrying Pos5 would be attributing an intervention.

    The rest are ordered by size and then by part id, so ``fermdb atlas routes`` lists the
    single-gene interventions before the pairs -- and an empty catalog of cofactor-cycle parts
    gives ``((),)``, which is the pre-2026-09-22 enumeration exactly.
    """
    candidates = sorted(
        (part for part in parts if part.step_role == COFACTOR_CYCLE), key=lambda part: part.id
    )
    return tuple(
        combination
        for size in range(len(candidates) + 1)
        for combination in itertools.combinations(candidates, size)
    )


def _cofactor_cycle_step(part: Part) -> RouteStep:
    """One cofactor-cycle step, placed in **its own part's** compartment and genome.

    A compartment strategy relocalizes the five catalytic steps and says nothing about a
    cofactor-cycle enzyme, so there is no strategy entry to read here. Taking the compartment from
    the part is the grounded choice and it is also how the literature treats the question: a
    cytosolic Pos5 is not "Pos5, relocalized" but a **different construct with its own name** --
    the corpus calls it ``cPOS5`` (10.1186/s12934-023-02123-0) and ``pos5D17``, expressed "without
    the mitochondrial targeting sequence" (10.1016/j.mec.2024.e00245). If the atlas ever wants it,
    it is a second part with its own evidence, not a second compartment for this one.

    The encoding genome comes from the part for the same reason. POS5, ADH3 and GPD1/2 are nuclear
    genes; strategy E moves KDC and ADH into the mtDNA and no DUET document proposes carrying a
    redox gene there, so a cofactor-cycle step is never flagged for recoding.
    """
    return RouteStep(
        step_role=COFACTOR_CYCLE,
        part=part,
        compartment=part.native_compartment,
        encoding_genome=part.sequence_encoding_genome,
    )


def enumerate_routes(
    parts: Sequence[Part],
    *,
    strategies: Sequence[str] | None = None,
    chassis: ChassisProfile | None = None,
    pathway: CuratedPathway | None = None,
) -> list[Route]:
    """Every {step -> part} x strategy x cofactor-cycle set combination, gated and scored.

    Generative: it does not ask what has been published, which is the only way the complement --
    what has never been tried -- can be read off the result.

    THE CATALYTIC PRODUCT IS UNCHANGED AND THE COFACTOR CYCLE MULTIPLIES IT. The five roles of
    :data:`STEP_ORDER` are required and every one of them must have a part, or this raises. The
    optional sixth role is a separate factor supplied by :func:`cofactor_cycle_sets`, whose first
    member is the empty set -- so the routes that existed before 2026-09-22 all still enumerate,
    **with their ids unchanged**, because a route id appends nothing for an empty cycle set. A
    catalog with no cofactor-cycle parts at all reproduces the old enumeration exactly.

    ``chassis`` applies `metabolic.chassis`'s per-strategy gates. Passing None ranks against no
    chassis at all, which is what happened to all 360 routes before schema v7, and the CLI says
    so rather than letting the ordering look considered.

    ``pathway`` supplies the curated reaction stoichiometry the per-compartment redox balance is
    summed from -- :func:`pathway_for_routes` picks it. Passing None is allowed and is **not**
    treated as "balanced": every route comes back flagged ``unknown``, with the reason stated, and
    :func:`explain` prints it. It is a deliberate parameter rather than a file read inside this
    function because which curated pathway a route's step roles refer to is a caller's decision,
    and two of the files in ``data/pathways/`` declare overlapping step roles.
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
    cycles = cofactor_cycle_sets(parts)
    routes: list[Route] = []
    for strategy in wanted:
        plan = STRATEGY_PLANS[strategy]
        for combination in itertools.product(*(by_role[role] for role in STEP_ORDER)):
            catalytic = tuple(
                RouteStep(
                    step_role=role,
                    part=part,
                    compartment=plan.compartments[role],
                    encoding_genome=plan.encoding_genomes[role],
                )
                for role, part in zip(STEP_ORDER, combination, strict=True)
            )
            base_id = f"{strategy}:" + "+".join(part.id for part in combination)
            gates = gates_for(chassis, strategy=strategy)
            disqualifying = tuple(g.message for g in gates if g.excludes)

            for cycle in cycles:
                steps = catalytic + tuple(_cofactor_cycle_step(part) for part in cycle)
                cofactor_risks = _cofactor_gate(steps)
                demand = cofactor_demand(steps)
                balance = redox_balance(steps, pathway)
                requirements = _code_gate(steps)
                gaps = _transport_gate(steps)

                # The empty cycle set appends NOTHING, so a cycle-free route keeps the id it had
                # before this axis existed. That is what lets the ranking, the stored rows and
                # `test_the_redox_flag_does_not_reorder_the_ranking` be compared across the
                # change instead of being declared incomparable.
                route_id = base_id + (
                    "+cycle:" + "+".join(part.id for part in cycle) if cycle else ""
                )
                routes.append(
                    Route(
                        id=route_id,
                        strategy=strategy,
                        steps=steps,
                        # The per-compartment redox verdict, computed rather than asserted. It
                        # USED to be the literal 'pass', on the argument that every curated
                        # reaction balances internally so route-level stoichiometry follows. That
                        # argument was wrong in a specific way: each reaction conserves its
                        # carriers, but the route as a whole is a net SINK for reducing power, and
                        # 'pass' claimed otherwise on all 600 rows.
                        redox_balance=balance,
                        # Stoichiometric impossibility was the only exclusion before v7, and there
                        # are none: every curated reaction balances. A chassis can now exclude
                        # too, but only for an impossibility -- a rho-zero strain cannot run a
                        # matrix pathway at all. Everything the chassis merely makes *expensive*
                        # stays in the list carrying its gate, because a cost is for the reader
                        # to weigh.
                        #
                        # `balance` IS NOT CONSULTED HERE, and that is the owner's 2026-09-22
                        # ruling rather than an oversight: flag, do not exclude.
                        excluded_because=disqualifying,
                        cofactor_risks=tuple(cofactor_risks),
                        redox_demand=demand,
                        construction_requirements=tuple(requirements),
                        chassis_gates=gates,
                        transport_gaps=tuple(gaps),
                        score_balance=1.0 / (1 + len(cofactor_risks)),
                        score_transport=1.0 / (1 + len(gaps)),
                        score_feasibility=plan.feasibility,
                        # NULL, not 0. Nothing has been extracted from the literature yet, so no
                        # route has demonstrated evidence -- and 0 would say "tried and failed",
                        # which is a different and much stronger claim than "not yet looked".
                        score_evidence=None,
                        # Likewise: no tolerance measurement is in the atlas, so no ceiling is
                        # known.
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
#: WHY EVERY VALUE WAS None UNTIL 2026-09-22 (superseded -- the values below are filled in now,
#: and the two objectives no longer agree). These numbers encode design intent, and design intent
#: is the owner's to state, not the atlas's to infer. They were seeded None so that
#: ``objective="programme"`` reproduced ``objective="easiest"`` exactly: the mechanism existed and
#: changed nothing until somebody filled it in. ``docs/design/DUET_TARGET.md`` §5 is where the
#: reasoning for a value had to come from, and is where these came from.
#:
#: THE OBSERVATION THIS EXISTS FOR (handover, 2026-09-21): confirming the chassis is rho+ cleared
#: strategy C's chassis gate and the ranking did not move, because ``rank`` separates B from C at
#: its *third* key -- feasibility, 0.80 against 0.60 -- while the chassis gate is the fourth. Those
#: constants encode technique difficulty, and DUET chose strategy C for reasons no measure of
#: technique difficulty knows about. The defect was never the constants; it was that the ranker
#: answers "easiest" while being read as "best".
#: FILLED IN BY THE OWNER, 2026-09-22. The ruling was: **favour C, and retain everything on B**,
#: so that B stays available as data accumulates and the choice can be revisited.
#:
#: That ruling is safe to implement literally, because of a property of `rank` worth stating
#: plainly: **programme fit is a sort key and never a filter.** No route is dropped, hidden or
#: excluded by any value here; the ordering changes and the population does not. `--objective
#: easiest` continues to return the historical order byte for byte, so both answers stay
#: available and comparable.
#:
#: Note also what still outranks it. `rank` consults transport gaps and cofactor risks *before*
#: programme fit, so a C route with a missing carrier still sorts below a clean B route. The hard
#: engineering constraints stay above the preference, which is the point of a lexicographic key
#: rather than a weighted total.
#:
#: WHERE EACH NUMBER COMES FROM. Not invented here -- each is the atlas's own documents read back:
#:
#: * **C, 1.00** -- `DUET_TARGET.md` §4, written before any of this curation: *"DUET is strategy
#:   C -- mitochondrial targeting of the Ehrlich pathway by nuclear-encoded, presequence-targeted
#:   enzymes."* It is not a preference among options; it is what the programme is.
#: * **B, 0.70** -- the principal published alternative, and deliberately kept high. The owner's
#:   ruling is explicit that B is retained for later decisions as more data arrives, and B is also
#:   genuinely *easier* (feasibility 0.80 against C's 0.60), which is real information this file
#:   must not bury.
#: * **A, 0.50** -- the architecture DUET starts from rather than one it moves to: the Ilv enzymes
#:   stay in the matrix either way, so the native split is the baseline every C build is measured
#:   against.
#: * **E, 0.30** -- in the programme but deferred. `DUET_TARGET.md` §4 calls mtDNA engineering
#:   *"a later, additional strategy"* behind a stated escalation condition (attempt E when C is
#:   demonstrated import-limited), and the 2026-09-21 corpus work predicts that condition will not
#:   fire. Above D because it is named in the plan; well below C because it is not the build.
#: * **D, 0.10** -- peroxisomal or other-organelle assembly. No DUET document mentions it. Low
#:   rather than None: None means *not recorded*, and this has been considered and set aside,
#:   which is a different fact.
PROGRAMME_FIT: Final[Mapping[str, float | None]] = {
    "A_native_split": 0.50,
    "B_cytosolic_relocalization": 0.70,
    "C_mitochondrial_ehrlich": 1.00,
    "D_alternative_compartment": 0.10,
    "E_mtdna_encoded": 0.30,
    # A prokaryotic host makes no compartment decision, so "how well does this compartment
    # strategy fit the programme" does not apply to it. None is the honest value: not recorded,
    # because the question does not arise -- and `rank` reads None as 0.0 for ordering, which
    # leaves these routes last under the programme objective and untouched under "easiest".
    "F_single_compartment_host": None,
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

    THE REDOX FLAG IS NOT A KEY HERE, AND THAT IS A DECISION. :class:`RedoxBalance` is printed by
    :func:`explain` and stored, and it does not appear in the sort key below. Three reasons, in
    order of weight:

    1. *Any scalar built from it is a weighted total in disguise.* Ordering "NADPH short by 2 in
       the matrix" against "NADPH short by 1 in the matrix **and** NADH short by 1 in the cytosol"
       requires an exchange rate between a matrix NADPH and a cytosolic NADH. The atlas has no such
       rate, and the reason it has none is that the pools are not freely interconvertible -- the
       claim the whole DUET argument rests on. ``pathway_route`` has five score columns and no
       total precisely to stop a number like that being invented.
    2. *Demand alone does not say which is worse.* ``COFACTOR_POOLS`` records which cofactors a
       compartment has and never how much, and it is unverified. A shortfall of 2 is not known to
       be harder to meet than a shortfall of 1 until a supply figure exists -- which is decision
       D1's option (b), and it is still not curated.
    3. *A flag that silently reorders is a gate wearing a disguise.* Excluding on an unchecked
       premise and demoting on one differ in degree, not in kind, and the demotion is the harder of
       the two to notice.

    THE ALTERNATIVE REJECTED: make the total shortfall -- ``sum(abs(v) for v in net.values())`` --
    the second key, ahead of feasibility, and print it in :func:`explain` as its own term. It was
    tempting because it would put the one-NADPH routes above the two-NADPH ones inside every
    strategy, which is a real design preference. It was rejected on (1): that sum adds a matrix
    NADPH to a cytosolic NADH as though they were the same quantity. It would also have been
    *constant across all 600 routes today at the strategy level*, moving only within a strategy,
    so it would have looked like a working term while separating almost nothing. If a measured
    per-compartment supply figure is ever curated, the right term is demand-against-supply per
    compartment -- not a pooled magnitude -- and it should arrive with its own ``explain`` line.
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
        # The redox flag is printed here too. An excluded route has no rank to explain, but its
        # balance is a property of the route rather than of its position, and a reader looking at
        # why a route was dropped is exactly the reader who needs to know it also does not close.
        cause = "; ".join(route.excluded_because)
        return f"EXCLUDED: {cause} | redox={route.redox_balance.summary()}"
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
        # The optional sixth role. Printed as a NAME or as the word 'none', never as a count: "0"
        # would read as a deficiency, and a route with no cofactor cycle is what most published
        # builds are. It is not a rank term either -- see `rank` -- so this is a stated property
        # of the route and not a hidden reason for its position.
        "cofactor_cycle=" + (", ".join(step.part.id for step in route.cofactor_cycle) or "none"),
        # The per-compartment redox flag (C2, and the owner's D1 ruling of 2026-09-22). It is NOT
        # one of `rank`'s keys -- see that function for the judgement and the alternative rejected
        # -- so it is printed as a stated property of the route, never as a hidden reason for its
        # position. It names the compartment, the pool and the magnitude, because "unbalanced" on
        # its own is not something a reader can act on.
        f"redox={route.redox_balance.summary()}",
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

        # Built by `extend` rather than by `+`, so each comprehension is checked against the
        # declared element type. A `+` of two list literals is inferred independently of the
        # annotation, and `list` is invariant, so the `None` compartment on three of the four
        # blocks made the concatenation a type error.
        gaps: list[tuple[str, str, str, str | None]] = []
        gaps.extend(
            [
                (
                    "transport_carrier_unknown",
                    description,
                    "a metabolite with no carrier either does not move or moves by an unrecorded "
                    "mechanism; either way the route's flux is not predictable",
                    None,
                )
                for description in route.transport_gaps
            ]
            + [
                (
                    "quantitative_value_missing",
                    description,
                    "the compartment's cofactor pool is asserted from background knowledge and "
                    "has never been measured, so this is a supply risk to resolve rather than a "
                    "reason to drop the route",
                    None,
                )
                for description in route.cofactor_risks
            ]
            # The named imbalance, as a row rather than as a status word. `balance_status` can now
            # say 'fail', and a 'fail' with nothing beside it saying WHICH pool in WHICH
            # compartment is short is the boolean the owner's ruling rejects. The compartment goes
            # in its own column, so "what does not close in the matrix" is a query rather than a
            # string search.
            + [
                (
                    "quantitative_value_missing",
                    f"per-compartment redox: {_name_imbalance(compartment, cofactor, value)}",
                    "the route is flagged, not excluded (owner's ruling, 2026-09-22): closing "
                    "this needs a cofactor_cycle part that regenerates THIS pool in THIS "
                    "compartment, a measured supply figure for that compartment, or a "
                    "cofactor-switched part that moves the demand to the other pool",
                    compartment,
                )
                for compartment, cofactor, value in route.redox_balance.open_buckets
            ]
            + [
                (
                    "quantitative_value_missing",
                    f"per-compartment redox not evaluated: {description}",
                    "an unevaluated balance is not a balanced one; until the stoichiometry this "
                    "names is curated, the route's redox closure is unknown and is reported as "
                    "such rather than assumed to pass",
                    None,
                )
                for description in route.redox_balance.unknowns
            ]
        )
        for kind, description, why, compartment in gaps:
            conn.execute(
                "INSERT INTO knowledge_gap (id, kind, route_id, compartment_id, description, "
                "why_it_matters, status, zone, evidence, confidence) "
                "VALUES (?,?,?,?,?,?,'open','I',?,'unverified') ON CONFLICT(id) DO NOTHING",
                (
                    f"YAA:GAP:{_stable_id(route.id + description)}",
                    kind,
                    route_id,
                    compartment,
                    description,
                    why,
                    "fermdb.metabolic.routes gate output",
                ),
            )
            counts["knowledge_gap"] += 1
    conn.commit()
    return counts
