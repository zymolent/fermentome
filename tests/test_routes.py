"""Tests for `fermdb.metabolic.routes` — PLAN.md G.7's enumeration and ranking.

Three properties carry the weight here.

**The code gate.** A presequence-targeted nuclear gene working in the matrix needs no recoding;
only a gene physically carried in the mtDNA reads under NCBI table 3. Getting this backwards is
the mistake this project has actually made, and it is invisible downstream — a wrongly recoded
sequence is still a sequence.

**Scores are components, never a total.** `pathway_route` has five score columns and no total, so
a rank must be explainable by naming the term that dominated it.

**Absence is not zero.** No literature has been extracted and no tolerance measured, so evidence
and toxicity are NULL for every route. Zero would mean "tried and failed", which is a far stronger
claim than "not yet looked".
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.metabolic import load_parts, load_pathways, write_parts
from fermdb.metabolic.routes import (
    COFACTOR_CYCLE,
    ROUTE_STEP_ROLES,
    STEP_ORDER,
    STRATEGY_PLANS,
    cofactor_cycle_sets,
    enumerate_routes,
    explain,
    pathway_for_routes,
    rank,
    redox_balance,
    write_routes,
)

PATHS_FILE = Path(__file__).resolve().parents[1] / "env" / "paths.yaml"


def _db(parts: tuple) -> sqlite3.Connection:
    """An in-memory atlas with the parts catalog loaded, because pathway_route_step has a foreign
    key onto part and a route cannot be stored against parts that do not exist."""
    connection = open_db(IN_MEMORY)
    write_parts(connection, parts)
    return connection


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings.load(paths_file=PATHS_FILE, env={})


@pytest.fixture(scope="module")
def parts(settings: Settings) -> tuple:
    return load_parts(settings)


@pytest.fixture(scope="module")
def pathway(settings: Settings):  # noqa: ANN201 - a CuratedPathway
    """The curated stoichiometry the per-compartment redox balance is summed from.

    Picked by product, not by pooling every curated reaction with a matching `step_role`:
    `ethanol_reference.yaml` declares a KDC and two ADHs of its own, one of them written in the
    oxidative direction, and pooling them would give the ADH step two contradictory
    stoichiometries.
    """
    return pathway_for_routes(load_pathways(settings))


@pytest.fixture(scope="module")
def routes(parts: tuple, pathway) -> list:  # noqa: ANN001 - a CuratedPathway
    return enumerate_routes(parts, pathway=pathway)


# ------------------------------------------------------------------------------- enumeration


def test_enumeration_is_the_full_product_of_parts_and_strategies(
    parts: tuple, routes: list
) -> None:
    """Generative, not a catalogue of published builds — which is the only way 'what has never
    been tried' can be read off as the complement of the evidence.

    CHANGED 2026-09-22. The product gained a factor. It used to be
    `strategies x AHAS x KARI x DHAD x KDC x ADH`; the owner's ruling added an **optional**
    `cofactor_cycle` role, so it is now that same product times the number of *subsets* of the
    cofactor-cycle parts — `2 ** k`, whose first term is the empty subset. The five catalytic
    roles are still required and are still counted exactly as before, which is the half of the
    contract this test was protecting and still protects.

    The `2 ** k` is asserted against `cofactor_cycle_sets` rather than recomputed from
    `len(parts)`, because the thing worth pinning is that the enumerator multiplies by *the same
    set the catalog offers* — including, crucially, the empty one.
    """
    per_role = {role: sum(1 for p in parts if p.step_role == role) for role in STEP_ORDER}
    expected = len(STRATEGY_PLANS)
    for count in per_role.values():
        expected *= count

    cycles = cofactor_cycle_sets(parts)
    cycle_parts = [p for p in parts if p.step_role == "cofactor_cycle"]
    assert len(cycles) == 2 ** len(cycle_parts)
    assert cycles[0] == (), "the empty set is a member, and it is the first one"

    assert len(routes) == expected * len(cycles)
    # and the catalytic half of the product is untouched: exactly `expected` routes carry no
    # cofactor cycle at all, which is the population that existed before this axis did.
    assert sum(1 for r in routes if not r.cofactor_cycle) == expected


def test_a_missing_part_for_a_step_is_an_error_not_an_empty_result(parts: tuple) -> None:
    """An empty product reads as 'no routes exist' when it means 'the catalog is incomplete'."""
    without_kdc = [p for p in parts if p.step_role != "KDC"]
    with pytest.raises(ValueError, match="no candidate part"):
        enumerate_routes(without_kdc)


# -------------------------------------------------------------------------------- the code gate


def test_only_an_mtdna_carried_gene_is_flagged_for_recoding(routes: list) -> None:
    """The distinction the gate exists for. Strategy C targets the Ehrlich enzymes INTO the matrix
    with presequences — they stay nuclear-encoded, translate on cytosolic ribosomes under table 1,
    and need no recoding. Strategy E carries them in the mtDNA, where they read under table 3."""
    c_routes = [r for r in routes if r.strategy == "C_mitochondrial_ehrlich"]
    e_routes = [r for r in routes if r.strategy == "E_mtdna_encoded"]

    assert all(not r.construction_requirements for r in c_routes), (
        "a presequence-targeted nuclear gene must not be flagged for recoding"
    )
    assert all(r.construction_requirements for r in e_routes)
    assert all("table 3" in req for r in e_routes for req in r.construction_requirements)


def test_strategy_c_runs_in_the_matrix_without_being_mtdna_encoded(routes: list) -> None:
    """Same compartment as strategy E, different encoding genome — so compartment alone can never
    answer which translation table applies, which is exactly why the gate takes both."""
    c_step = next(
        s
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        for s in r.steps
        if s.step_role == "KDC"
    )
    e_step = next(
        s
        for r in routes
        if r.strategy == "E_mtdna_encoded"
        for s in r.steps
        if s.step_role == "KDC"
    )
    assert c_step.compartment == e_step.compartment == "mitochondrial_matrix"
    assert c_step.encoding_genome == "nuclear"
    assert e_step.encoding_genome == "mitochondrial"
    assert c_step.needs_recoding is False
    assert e_step.needs_recoding is True


# ------------------------------------------------------------------------------ transport gate


def test_the_native_split_carries_the_real_engineering_gap(routes: list) -> None:
    """2-ketoisovalerate is made in the matrix and decarboxylated in the cytosol, and this atlas
    records no carrier for it. That gap IS the isobutanol problem; a route enumerator that did not
    surface it would be describing a pathway that does not have one."""
    native = [r for r in routes if r.strategy == "A_native_split"]
    assert native and all(len(r.transport_gaps) == 1 for r in native)
    assert all("2-ketoisovalerate" in r.transport_gaps[0] for r in native)
    assert all("no carrier" in r.transport_gaps[0] for r in native)


def test_a_single_compartment_strategy_has_no_handoffs(routes: list) -> None:
    for strategy in ("B_cytosolic_relocalization", "C_mitochondrial_ehrlich"):
        group = [r for r in routes if r.strategy == strategy]
        assert all(not r.transport_gaps for r in group)


# ------------------------------------------------------------------ absence is not zero


def test_evidence_and_toxicity_are_null_not_zero(routes: list) -> None:
    """Nothing has been extracted from the literature and no tolerance has been measured. NULL
    says 'not yet looked'; 0 would say 'tried and failed'."""
    assert all(r.score_evidence is None for r in routes)
    assert all(r.score_toxicity is None for r in routes)


def test_a_cofactor_mismatch_is_a_risk_not_an_exclusion(routes: list) -> None:
    """COFACTOR_POOLS is unverified background knowledge. G.7 reserves exclusion for a
    stoichiometric impossibility, and excluding a route on an unverified premise would delete
    exactly the options this atlas exists to surface."""
    peroxisomal = [r for r in routes if r.strategy == "D_alternative_compartment"]
    risky = [r for r in peroxisomal if r.cofactor_risks]
    assert risky, "the NADPH-requiring parts in a NADH-only compartment should carry a risk"
    assert all(r.viable for r in risky)
    assert all("NADPH" in risk for r in risky for risk in r.cofactor_risks)


def test_nothing_is_excluded_today_and_that_is_the_honest_state(routes: list) -> None:
    """Every curated reaction balances, so no route is stoichiometrically impossible. If this ever
    starts failing, something genuinely cannot happen and the exclusion should be read."""
    assert all(r.viable for r in routes)


# ------------------------------------------------------------------------------------ ranking


def test_ranking_is_explainable_by_a_named_term(routes: list) -> None:
    best = rank(routes)[0]
    reason = explain(best)
    for term in ("transport_gaps", "cofactor_risks", "feasibility", "evidence", "toxicity"):
        assert term in reason


# ------------------------------------------- PLAN.md phase 3: "every rank is explainable term
# by term". Stronger than "the explanation mentions some terms": the term that actually decided
# each adjacent pair in the ranking must be one the explanation prints.


def _ranking_terms(route) -> dict:  # noqa: ANN001 - a Route, but the fixture hands them as `list`
    """The terms `rank` orders by, as a dict, in the order it consults them.

    Kept beside the test rather than imported from `rank` on purpose: if this drifts from the
    real sort key, the test below fails, which is the alarm we want. A helper that asked `rank`
    for its own key would agree with itself whatever the key became.
    """
    return {
        "transport_gaps": len(route.transport_gaps),
        "cofactor_risks": len(route.cofactor_risks),
        "feasibility": -(route.score_feasibility or 0.0),
        "chassis_gates": len([g for g in route.chassis_gates if not g.excludes]),
        "construction_requirements": len(route.construction_requirements),
    }


def test_every_adjacent_pair_in_the_ranking_is_separated_by_a_printed_term(routes: list) -> None:
    """Take every consecutive pair in the ranked list, find the FIRST term on which they differ,
    and require that `explain` prints that term for both. A ranking whose deciding term is absent
    from the explanation is ordered for a reason the reader cannot see, which is the specific
    failure the five-score-columns-and-no-total schema exists to prevent."""
    ordered = rank(routes)
    assert len(ordered) == len(routes)
    for upper, lower in zip(ordered, ordered[1:], strict=False):
        above, below = _ranking_terms(upper), _ranking_terms(lower)
        differing = [term for term in above if above[term] != below[term]]
        if not differing:
            # Identical on every named term; `rank` falls back to the route id purely to make the
            # order deterministic, and that tie is not a claim about the routes.
            continue
        term = differing[0]
        assert above[term] < below[term], f"{term} put {upper.id} above {lower.id} the wrong way"
        assert term in explain(upper) and term in explain(lower), (
            f"{term} decided {upper.id} against {lower.id} and `explain` does not print it"
        )


def test_the_chassis_term_is_printed_because_the_ranker_uses_it(parts: tuple) -> None:
    """The gap this test was written for. `rank`'s fourth key counts the chassis gates a route
    carries, and for the selected profile only strategy E carries any — so under a real chassis
    two routes can be separated by a term the explanation used not to contain."""
    from fermdb.config import Settings
    from fermdb.metabolic.chassis import gates_for, load_profiles, selected_profile

    chassis = selected_profile(load_profiles(Settings.load()))
    assert chassis is not None, "the curated file marks one profile selected"
    gated = [
        strategy
        for strategy in STRATEGY_PLANS
        if any(not g.excludes for g in gates_for(chassis, strategy=strategy))
    ]
    assert gated, "the selected chassis gates at least one strategy, or this test proves nothing"

    with_chassis = enumerate_routes(parts, chassis=chassis)
    burdened = next(r for r in with_chassis if r.strategy in gated)
    assert "chassis_gates=" in explain(burdened)
    assert f"chassis_gates={len(burdened.chassis_gates)}" in explain(burdened)


# ----------------------------------------- PLAN.md phase 3: per-compartment redox balance
#
# DECISION D1 WAS SETTLED BY THE OWNER ON 2026-09-22: **flag, do not exclude**. A route whose
# per-compartment redox balance does not close is marked, with the imbalance named, and keeps its
# place in the enumeration and in the ranking. Nothing is dropped on an unchecked premise.
#
# These tests used to pin the ABSENCE of the feature. They now pin the contract: flagged, named,
# still present — and `unknown` reported as `unknown`, never rounded to `balanced`.
# See docs/drafts/phase3/ACCEPTANCE.md, clause C2 and decision D1.


def test_a_redox_imbalance_is_flagged_and_named_and_the_route_is_not_excluded(
    routes: list,
) -> None:
    """The owner's ruling, as three assertions.

    *Flagged*: the verdict is one of three states and is computed, not the old literal 'pass'.
    *Named*: an unbalanced route says which cofactor is short by how much in WHICH compartment —
    "unbalanced: true" is not an artifact anybody can act on.
    *Not excluded*: every flagged route is still viable and still enumerated.
    """
    unbalanced = [r for r in routes if r.redox_balance.status == "unbalanced"]
    assert unbalanced, "the pathway consumes reducing power and no route regenerates it"

    for route in unbalanced:
        assert route.redox_balance.imbalances, route.id
        for line in route.redox_balance.imbalances:
            assert "short by" in line or "in surplus by" in line, line
            compartment = line.rsplit(" in ", 1)[1]
            assert compartment in {step.compartment for step in route.steps}, line
            assert line.split(" ", 1)[0] in {"NADH", "NADPH"}, line

    assert all(r.viable for r in unbalanced), "flag, do not exclude"
    assert all(not r.excluded_because for r in routes)


def test_a_route_with_a_known_imbalance_survives_enumeration_and_ranking(routes: list) -> None:
    """The specific thing the ruling protects. The published yeast route run in the matrix wants
    2 NADPH there — the imbalance the atlas most wants to talk about — and the route that carries
    it must be in the enumeration AND in the ranked list, not filtered out of either.

    A gate that removed it would delete exactly the option the atlas exists to surface, and the
    reader would never learn the imbalance existed.
    """
    flagged = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and any(s.part.id == "adh6_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    assert flagged.redox_balance.status == "unbalanced"
    assert flagged.redox_balance.imbalances == ("NADPH short by 2 in mitochondrial_matrix",)
    assert flagged.redox_balance.net[("mitochondrial_matrix", "NADPH")] == -2

    assert flagged in routes
    assert flagged.id in {r.id for r in rank(routes)}
    assert flagged.id in {r.id for r in rank(routes, objective="programme")}


def test_the_balance_is_summed_per_compartment_and_never_across_them(routes: list) -> None:
    """PLAN.md B.6.4: a route split across membranes must balance in each compartment separately.

    The native split consumes one NADPH in the matrix and one NADH in the cytosol. A global sum
    would report "2 reducing equivalents short" and lose the fact that they are short in different
    compartments on either side of a membrane that passes neither — which is the entire content of
    the clause.
    """
    native = next(
        r
        for r in routes
        if r.strategy == "A_native_split"
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh1_native" for s in r.steps)
    )
    assert native.redox_balance.net == {
        ("mitochondrial_matrix", "NADPH"): -1,
        ("cytosol", "NADH"): -1,
    }
    assert set(native.redox_balance.imbalances) == {
        "NADPH short by 1 in mitochondrial_matrix",
        "NADH short by 1 in cytosol",
    }

    # The same two parts with every step in one compartment: same total, one bucket, different
    # engineering problem. If the sum were global these two routes would be indistinguishable.
    cytosolic = next(
        r
        for r in routes
        if r.strategy == "B_cytosolic_relocalization"
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh1_native" for s in r.steps)
    )
    assert cytosolic.redox_balance.net == {
        ("cytosol", "NADPH"): -1,
        ("cytosol", "NADH"): -1,
    }
    assert cytosolic.redox_balance.net != native.redox_balance.net


def test_a_missing_stoichiometry_is_unknown_and_never_balanced(
    parts: tuple, routes: list, pathway
) -> None:  # noqa: ANN001 - a CuratedPathway
    """The distinction the hard rule turns on. Where the reaction/cofactor data does not say what
    a step does to the redox pools, the answer is `unknown` — a state of its own, reported as
    such, and never quietly rounded to `balanced`.

    Two ways to get there, both real:

    * no curated pathway supplied at all, which is what `enumerate_routes(parts)` does; and
    * a part whose `cofactor_preference` is the literal 'unknown'.

    CHANGED 2026-09-22 — THE CATALOG NO LONGER CARRIES A PART OF THE SECOND KIND, so this test now
    BUILDS one rather than finding one. `adh7_native` used to be it: read out of a paper that does
    not state the cofactor, and left `unknown` rather than filled in from background knowledge. Its
    `cofactor_preference` is now `NADPH`, grounded in `doi:10.1128/aem.00362-26` -- a source, not a
    memory -- so the catalog's last `unknown` cofactor is gone and the 1,600 routes that carried
    that part are now evaluated.

    The old assertions sat behind `if undeclared:` and so would have passed VACUOUSLY from today
    onwards, silently testing nothing. That is the worse failure of the two available here, so the
    branch is replaced by a substituted part: the contract "a part that declines to name its pool
    makes its route unevaluable, and unevaluable is never rounded to balanced" is permanent, even
    though no catalog entry exercises it right now. The first assertion below pins that absence
    explicitly, so the day a part comes back `unknown` this test says so rather than drifting.
    """
    unchecked = enumerate_routes(parts, strategies=["A_native_split"])
    assert all(r.redox_balance.status == "unknown" for r in unchecked)
    assert all(not r.redox_balance.net for r in unchecked)
    assert all("never be read as 'balanced'" in r.redox_balance.unknowns[0] for r in unchecked)
    assert all(r.balance_status == "not_evaluated" for r in unchecked)

    # The catalog has no undeclared pool today. Stated as an assertion, not assumed.
    assert not [r for r in routes if any(s.part.cofactor_preference == "unknown" for s in r.steps)]

    # ...so the contract is exercised on a part built to have one. Take a live route and blank the
    # ADH step's declared pool; everything else about the route is untouched.
    route = next(
        r
        for r in routes
        if r.strategy == "A_native_split"
        and not r.cofactor_cycle
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh1_native" for s in r.steps)
    )
    blanked = tuple(
        replace(step, part=replace(step.part, cofactor_preference="unknown"))
        if step.step_role == "ADH"
        else step
        for step in route.steps
    )
    verdict = redox_balance(blanked, pathway)
    assert verdict.status == "unknown"
    assert verdict.unknowns
    assert "cofactor_preference" in verdict.unknowns[0]
    # and the step that IS known is still reported, rather than the whole route going dark
    assert verdict.imbalances == ("NADPH short by 1 in mitochondrial_matrix",)
    assert verdict.db_status == "not_evaluated"


def test_every_route_carries_one_of_exactly_three_verdicts(routes: list) -> None:
    """No fourth state, and no None. A route with no verdict would be read as a passing one."""
    verdicts = {r.redox_balance.status for r in routes}
    assert verdicts <= {"balanced", "unbalanced", "unknown"}
    assert all(r.balance_status in {"pass", "fail", "not_evaluated"} for r in routes), (
        "the stored word must stay inside pathway_route.balance_status's CHECK"
    )


def test_a_route_of_non_redox_steps_balances_which_is_how_balanced_is_reachable(
    routes: list, pathway
) -> None:  # noqa: ANN001 - a CuratedPathway
    """`balanced` is not dead code, it is merely unreached by the current catalog.

    CHANGED 2026-09-22 — THE REASON NOTHING BALANCES IS NOW A DIFFERENT AND SHARPER ONE. This test
    used to say closure "would need a `cofactor_cycle` part and STEP_ORDER has no slot for one".
    That was true and is not any more: the enumerator has an optional cofactor-cycle role, routes
    carrying POS5 and ADH3 are enumerated, and `test_the_duet_pair_closes_the_mitochondrial_matrix`
    below shows a compartment closing for the first time. Nothing balances for an **arithmetic**
    reason the slot exposed rather than caused — a route spends two reducing equivalents (the KARI
    and the ADH) and the only curated cofactor-cycle reaction that supplies one, Adh3, supplies
    one — so the assertion below is kept, with its meaning restated, rather than deleted.

    Substitute non-redox parts into the two redox steps and the same function returns `balanced`,
    which is what makes the three-state verdict a measurement rather than a constant.
    """
    assert not [r for r in routes if r.redox_balance.status == "balanced"]

    route = next(r for r in routes if r.strategy == "B_cytosolic_relocalization")
    inert = tuple(
        replace(step, part=replace(step.part, cofactor_preference="NA")) for step in route.steps
    )
    balance = redox_balance(inert, pathway)
    assert balance.status == "unknown", (
        "a part claiming no cofactor against a reaction that turns one over is a disagreement "
        "between two curated files, and this module must not pick a winner"
    )

    # Whereas a route whose reactions genuinely have no redox participant does close.
    no_redox = replace(
        pathway,
        reactions=tuple(
            replace(r, participants=tuple(p for p in r.participants if "nad" not in p.metabolite))
            for r in pathway.reactions
        ),
    )
    all_na = tuple(
        replace(step, part=replace(step.part, cofactor_preference="NA")) for step in route.steps
    )
    closed = redox_balance(all_na, no_redox)
    assert closed.status == "balanced"
    assert closed.imbalances == ()
    assert closed.db_status == "pass"


def test_the_pool_is_taken_from_the_part_and_the_substitution_is_named(routes: list) -> None:
    """The one inference this calculation makes, and it is recorded rather than applied silently.

    The curated `adh_isobutanol` reaction is written for the Adh1 type, on NADH. `adh6_native` is
    NADPH-preferring, and no reaction is curated for it. The coefficient is kept and the pool is
    taken from the part — which is what lets the atlas reason about a cofactor-switched enzyme at
    all — and the record says so by name, so a reader can see where the number came from.
    """
    swapped = next(
        r
        for r in routes
        if r.strategy == "B_cytosolic_relocalization"
        and any(s.part.id == "adh6_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    assert swapped.redox_balance.substitutions
    note = swapped.redox_balance.substitutions[0]
    assert "adh6_native" in note and "adh_isobutanol" in note
    assert "written for NADH" in note and "declares NADPH" in note

    # and where part and reaction agree, nothing is substituted and nothing is claimed
    agreeing = next(
        r
        for r in routes
        if r.strategy == "B_cytosolic_relocalization"
        and any(s.part.id == "adh1_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    assert agreeing.redox_balance.substitutions == ()


# ------------------------------------------- the optional cofactor_cycle role (owner, 2026-09-22)
#
# THE RULING: add a `cofactor_cycle` step role so POS5, ADH3 and GPD can exist as parts, and make
# it OPTIONAL — most published builds have no cofactor-cycle step, and a route without one is a
# real route rather than a deficient one.
#
# Optionality is expressed as a POWER SET over the cofactor-cycle parts whose empty member is
# first and is a first-class value, and the role is deliberately NOT a member of `STEP_ORDER`.
# The tests below pin both halves, and the second one has teeth: `metabolic/recall.py` reads
# `STEP_ORDER` as "the roles a published configuration must fill", so a role added there would
# make every published build unmatchable.


def test_a_route_with_no_cofactor_cycle_is_a_route_and_not_a_deficient_one(
    parts: tuple, routes: list
) -> None:
    """The constraint that mattered most, as four assertions.

    *Enumerated*: the 800 routes that existed before this axis are all still here.
    *Identical*: byte for byte — same ids, because an empty cycle set appends nothing to a route
    id — and with the same redox verdicts, so the change added routes rather than moving any.
    *Not marked*: nothing about a cycle-free route says it is incomplete. It is viable, ranked,
    and `explain` prints `cofactor_cycle=none` rather than a count of zero.
    *Not required*: a catalog with no cofactor-cycle parts at all still enumerates.
    """
    without_cycle_parts = [p for p in parts if p.step_role != COFACTOR_CYCLE]
    baseline = enumerate_routes(without_cycle_parts)
    assert baseline, "the role is optional, so its absence is not an error"

    cycle_free = [r for r in routes if not r.cofactor_cycle]
    assert [r.id for r in cycle_free] == [r.id for r in baseline]
    assert all(len(r.steps) == len(STEP_ORDER) for r in cycle_free)
    assert all(r.viable for r in cycle_free)

    ranked = {r.id for r in rank(routes)}
    assert all(r.id in ranked for r in cycle_free)
    assert "cofactor_cycle=none" in explain(cycle_free[0])


def test_the_optional_role_is_not_in_step_order_and_that_is_the_whole_design(
    parts: tuple,
) -> None:
    """Where the role lives, and the alternative that was rejected.

    `STEP_ORDER` is not "the roles a route can carry" — it is the roles a route MUST carry, and
    `metabolic/recall.py` reads it as the roles a **published configuration** must fill before it
    can be called re-discovered. No paper's enzyme list names POS5; it is a host gene, not a
    pathway enzyme. So adding `cofactor_cycle` to `STEP_ORDER` would leave that role permanently
    unfilled and turn every matched configuration into `under_specified` — which is precisely the
    failure the ruling warned against, and it is not hypothetical: two of the four configurations
    in the live atlas match today.

    `ROUTE_STEP_ROLES` carries the optional role instead, so the two contracts stay separate.
    """
    assert COFACTOR_CYCLE not in STEP_ORDER
    assert (*STEP_ORDER, COFACTOR_CYCLE) == ROUTE_STEP_ROLES
    assert len(STEP_ORDER) == 5

    # And the catalog really does carry parts under the optional role, or the point is untested.
    assert {p.id for p in parts if p.step_role == COFACTOR_CYCLE} == {
        "adh3_native",
        "gpd1_gpd2_native",
        "pos5_native",
    }
    # `resolve_roles` seeds one bucket per STEP_ORDER member; POS5 filling none of them is the
    # property tests/test_recall.py pins from the other side, asserted here on the source of that
    # tuple so a change to it fails in this file too.
    assert all(part.step_role in ROUTE_STEP_ROLES for part in parts)


def test_a_cofactor_cycle_step_takes_its_compartment_and_genome_from_its_own_part(
    routes: list,
) -> None:
    """A compartment strategy relocalizes the five catalytic steps and says nothing about a redox
    enzyme, so there is no strategy entry to read. Pos5 sits in the matrix in a cytosolic route
    too — and that is not a bug, it is what makes the matrix bucket it opens visible.

    The literature agrees that a relocalized Pos5 is a different construct rather than the same
    one moved: the corpus calls it `cPOS5` and `pos5Δ17`, expressed without the targeting
    sequence. If the atlas wants it, it is a second part.

    The encoding genome comes from the part for the same reason, and the consequence is the one
    the code gate exists for: POS5/ADH3/GPD are nuclear, so a cofactor-cycle step is **never**
    flagged for recoding, not even in strategy E.
    """
    cytosolic = next(
        r
        for r in routes
        if r.strategy == "B_cytosolic_relocalization"
        and any(s.part.id == "pos5_native" for s in r.cofactor_cycle)
    )
    pos5 = next(s for s in cytosolic.cofactor_cycle if s.part.id == "pos5_native")
    assert pos5.compartment == "mitochondrial_matrix"
    assert all(s.compartment == "cytosol" for s in cytosolic.steps if s.step_role in STEP_ORDER)

    mtdna = [r for r in routes if r.strategy == "E_mtdna_encoded" and r.cofactor_cycle]
    assert mtdna
    for route in mtdna:
        assert all(not s.needs_recoding for s in route.cofactor_cycle), route.id
        assert all("cofactor_cycle" not in req for req in route.construction_requirements)


def test_a_cofactor_cycle_step_is_not_counted_as_a_demand_or_a_supply_risk(routes: list) -> None:
    """`cofactor_preference` means something different on a cofactor-cycle part, and two unsigned
    gates must not read it as though it did not.

    `cofactor_demand` counts reducing equivalents a route CONSUMES and `_cofactor_gate` asks
    whether a compartment supplies what a step NEEDS. Adh3 declares `NADH` and *produces* it, so
    counting it in either would file a source of reducing power as a demand for it — and a wrong
    number here would read as a measurement. The direction lives in the curated reaction, and
    `redox_balance` is the function that reads it.

    This is also what keeps the ranking of the pre-existing routes byte-identical: `rank`'s second
    key counts cofactor risks, so a cycle step that added one would silently reorder the atlas.
    """
    from fermdb.metabolic.routes import cofactor_demand

    with_adh3 = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and [s.part.id for s in r.cofactor_cycle] == ["adh3_native"]
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh6_native" for s in r.steps)
    )
    bare = next(r for r in routes if r.id == with_adh3.id.split("+cycle:")[0])

    assert cofactor_demand(with_adh3.steps) == cofactor_demand(bare.steps)
    assert with_adh3.cofactor_risks == bare.cofactor_risks
    # ...and the balance, which reads the signed stoichiometry, does NOT agree with them: that
    # difference is the whole content of the change.
    assert with_adh3.redox_balance.net != bare.redox_balance.net


def test_a_cofactor_cycle_step_contributes_the_sign_its_curated_reaction_is_written_in(
    routes: list,
) -> None:
    """Adh3 produces, Gpd consumes, and the atlas must not assume the first.

    "Cofactor cycle" sounds like free reducing power and is not. `adh3_matrix` has NADH as a
    product, so it contributes +1 to matrix NADH. `gpd_glycerol3p` has NADH as a substrate, so it
    contributes -1 to cytosolic NADH: what Gpd regenerates is the *oxidised* member, which a sum
    over reducing equivalents does not count. A model that treated every cofactor-cycle part as a
    source would report the most-deleted gene in the ethanol literature as a way to close a route.
    """

    def net_of(strategy: str, cycle: list[str], kari: str, adh: str) -> dict:
        route = next(
            r
            for r in routes
            if r.strategy == strategy
            and [s.part.id for s in r.cofactor_cycle] == cycle
            and any(s.part.id == kari for s in r.steps)
            and any(s.part.id == adh for s in r.steps)
        )
        return dict(route.redox_balance.net)

    bare = net_of("C_mitochondrial_ehrlich", [], "ilvc6e6_ecoli", "adh1_native")
    assert bare[("mitochondrial_matrix", "NADH")] == -2

    adh3 = net_of("C_mitochondrial_ehrlich", ["adh3_native"], "ilvc6e6_ecoli", "adh1_native")
    assert adh3[("mitochondrial_matrix", "NADH")] == -1, "Adh3 SUPPLIES one matrix NADH"

    gpd = net_of("B_cytosolic_relocalization", ["gpd1_gpd2_native"], "ilvc6e6_ecoli", "adh1_native")
    assert gpd[("cytosol", "NADH")] == -3, "Gpd is a further SINK, not a source"


def test_pos5_moves_reducing_power_between_pools_and_never_creates_it(routes: list) -> None:
    """The one step in this model that is different in kind, and the check that keeps it honest.

    Pos5 consumes matrix NADH and produces matrix NADPH: **one compartment, two pools**. Every
    other step spends or makes reducing power; this one only relocates it. So its two terms must
    land in the same compartment and must sum to zero — the total reducing power of the route is
    unchanged, only its distribution between the pools moves.
    """
    with_pos5 = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and [s.part.id for s in r.cofactor_cycle] == ["pos5_native"]
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh1_native" for s in r.steps)
    )
    bare = next(r for r in routes if r.id == with_pos5.id.split("+cycle:")[0])

    # Both terms in the matrix, and nowhere else: the inner membrane passes neither dinucleotide.
    moved = {
        key: with_pos5.redox_balance.net.get(key, 0.0) - bare.redox_balance.net.get(key, 0.0)
        for key in set(with_pos5.redox_balance.net) | set(bare.redox_balance.net)
    }
    assert {k for k, v in moved.items() if v} == {
        ("mitochondrial_matrix", "NADH"),
        ("mitochondrial_matrix", "NADPH"),
    }
    assert moved[("mitochondrial_matrix", "NADH")] == -1
    assert moved[("mitochondrial_matrix", "NADPH")] == +1
    # IT CREATES NOTHING. The route's total reducing-equivalent debt is identical either side.
    assert sum(moved.values()) == 0
    assert sum(with_pos5.redox_balance.net.values()) == sum(bare.redox_balance.net.values())

    # The pool is NOT taken from the part for a transfer: a single `cofactor_preference` cannot
    # say how a kinase splits two pools, so nothing is inferred and nothing is recorded as
    # inferred either.
    assert not any("pos5_native" in note for note in with_pos5.redox_balance.substitutions)


def test_a_declared_pool_transfer_that_does_not_conserve_is_unknown_not_balanced(
    routes: list, pathway
) -> None:  # noqa: ANN001 - a CuratedPathway
    """The guard on the one branch that could manufacture a balanced route out of a typo.

    A transfer relocates reducing power between pools and cannot create it, so its terms sum to
    zero. That is checked rather than assumed: mistype Pos5's NADPH coefficient as 2 and the step
    would appear to conjure an equivalent from ATP, and the route carrying it could come back
    `balanced` — the one verdict in this module nobody would go back and re-derive.
    """
    route = next(
        r
        for r in routes
        if [s.part.id for s in r.cofactor_cycle] == ["pos5_native"]
        and r.strategy == "C_mitochondrial_ehrlich"
    )
    assert route.redox_balance.status == "unbalanced"

    broken = replace(
        pathway,
        reactions=tuple(
            replace(
                reaction,
                participants=tuple(
                    replace(p, coefficient=2.0) if p.metabolite == "nadph" else p
                    for p in reaction.participants
                ),
            )
            if reaction.id == "pos5_nadh_kinase"
            else reaction
            for reaction in pathway.reactions
        ),
    )
    verdict = redox_balance(route.steps, broken)
    assert verdict.status == "unknown"
    assert any("transfer" in line and "sum to +1" in line for line in verdict.unknowns), (
        verdict.unknowns
    )


def test_the_duet_pair_closes_the_mitochondrial_matrix_for_the_first_time(routes: list) -> None:
    """THE RESULT THE WHOLE CHANGE EXISTS FOR, and it is checked by hand in the docstring.

    DUET is two genes in series: ADH3 oxidises matrix ethanol to matrix NADH, POS5 phosphorylates
    that NADH to the matrix NADPH Ilv5 consumes. The native split runs Ilv2/Ilv5/Ilv3 in the
    matrix and the Ehrlich steps in the cytosol. Term by term, on the route below:

        AHAS  ilv2_ilv6_native  matrix   `ahas`             no redox participant   0
        KARI  ilv5_native       matrix   `kari`             NADPH a substrate      -1 matrix NADPH
        DHAD  ilv3_native       matrix   `dhad`             no redox participant   0
        KDC   aro10_native      cytosol  `kdc`              no redox participant   0
        ADH   adh1_native       cytosol  `adh_isobutanol`   NADH a substrate       -1 cytosol NADH
        cycle adh3_native       matrix   `adh3_matrix`      NADH a PRODUCT         +1 matrix NADH
        cycle pos5_native       matrix   `pos5_nadh_kinase` a declared transfer    -1 matrix NADH,
                                                                                   +1 matrix NADPH

        matrix NADPH   -1 + 1 = 0
        matrix NADH    +1 - 1 = 0
        cytosol NADH        -1

    So **the mitochondrial matrix closes completely** — the first compartment the atlas has ever
    reported as closing — and one open bucket remains, in the cytosol, where the ADH sits. The
    route is still `unbalanced`, correctly: `COFACTOR_POOLS` records that the cytosol *has* NADH
    and never *how much*, so "glycolysis will cover it" is a supply claim the atlas cannot make.

    NOT A FULL CLOSURE, AND THE REASON IS WORTH KEEPING. A route spends two reducing equivalents
    and Adh3 supplies one, so one bucket is open whatever set of cofactor-cycle parts is chosen.
    Closing the last one needs a second equivalent of Adh3 flux — stoichiometric multiplicity a
    model that picks each part once cannot express — or a cytosolic regenerating part nobody has
    curated. Note also what this sum does NOT carry: Pos5 spends ATP, and an adenylate balance is
    not part of this calculation.
    """
    duet = next(
        r
        for r in routes
        if r.strategy == "A_native_split"
        and [s.part.id for s in r.cofactor_cycle] == ["adh3_native", "pos5_native"]
        and any(s.part.id == "ilv5_native" for s in r.steps)
        and any(s.part.id == "adh1_native" for s in r.steps)
    )
    assert duet.redox_balance.net[("mitochondrial_matrix", "NADPH")] == 0
    assert duet.redox_balance.net[("mitochondrial_matrix", "NADH")] == 0
    assert duet.redox_balance.net[("cytosol", "NADH")] == -1
    assert duet.redox_balance.imbalances == ("NADH short by 1 in cytosol",)
    assert duet.redox_balance.status == "unbalanced"
    assert duet.viable and duet.id in {r.id for r in rank(routes)}

    # Neither gene alone does it — which is why the axis holds a SET and not one nullable slot.
    for alone in (["adh3_native"], ["pos5_native"]):
        partial = next(
            r
            for r in routes
            if r.strategy == "A_native_split"
            and [s.part.id for s in r.cofactor_cycle] == alone
            and any(s.part.id == "ilv5_native" for s in r.steps)
            and any(s.part.id == "adh1_native" for s in r.steps)
        )
        matrix = [c for c, _, _ in partial.redox_balance.open_buckets]
        assert "mitochondrial_matrix" in matrix, alone


def test_the_curated_reaction_for_a_cycle_step_is_chosen_by_gene_and_never_guessed(
    routes: list, pathway
) -> None:  # noqa: ANN001 - a CuratedPathway
    """Three curated reactions share the `cofactor_cycle` role and they are three *different
    interventions*, not three descriptions of one. The part's gene symbol is what picks between
    them — an identity claim both curated files already make — and it is exact, never substring:
    a loose match would attach the matrix ethanol OXIDATION to Adh1 and sum a source where a sink
    belongs.

    Strip the genes off the part and the atlas stops being able to say which reaction the step is,
    so the verdict is `unknown` with the role named. It is not resolved by position, by order in
    the file, or by picking the first.
    """
    roles = {r.step_role for r in pathway.reactions}
    assert COFACTOR_CYCLE in roles, "the cofactor-cycle reactions must reach the enumerator"
    assert len([r for r in pathway.reactions if r.step_role == COFACTOR_CYCLE]) == 3

    route = next(r for r in routes if [s.part.id for s in r.cofactor_cycle] == ["adh3_native"])
    anonymous = tuple(
        replace(step, part=replace(step.part, genes=()))
        if step.step_role == COFACTOR_CYCLE
        else step
        for step in route.steps
    )
    verdict = redox_balance(anonymous, pathway)
    assert verdict.status == "unknown"
    assert any("cofactor_cycle" in line and "disagree" in line for line in verdict.unknowns), (
        verdict.unknowns
    )


def test_a_metabolite_the_two_files_disagree_about_blocks_the_merge_rather_than_the_sum(
    settings: Settings,
) -> None:
    """The merge that brings the cofactor-cycle reactions into the isobutanol pathway is the ONE
    pooling across curated files this module permits, and it has a guard.

    A metabolite id means the same thing in both files today — `nadh` is `nadh` — which is why the
    merge is safe. If it ever stopped being true, summing a reaction from one file against a
    metabolite table from the other would produce a number with no meaning. So a reaction whose
    participants resolve differently in the two files is **not merged**, and its step then reports
    `unknown` with the role named: the failure is loud and lands in the state reserved for "the
    atlas does not say", rather than quietly changing a coefficient.
    """
    pathways = load_pathways(settings)
    merged = pathway_for_routes(pathways)
    assert merged is not None
    assert len([r for r in merged.reactions if r.step_role == COFACTOR_CYCLE]) == 3

    # Redefine NADH in the DONOR file as something else, and the reactions that use it drop out.
    poisoned = tuple(
        replace(
            p,
            metabolites={
                **p.metabolites,
                "nadh": replace(p.metabolites["nadh"], pair="something_else"),
            },
        )
        if p.product != "isobutanol" and "nadh" in p.metabolites
        else p
        for p in pathways
    )
    blocked = pathway_for_routes(poisoned)
    assert blocked is not None
    assert not [r for r in blocked.reactions if r.step_role == COFACTOR_CYCLE], (
        "no cofactor-cycle reaction may survive a metabolite the two files disagree about"
    )

    # ...and the step then reports `unknown`, which is the state reserved for "not in the atlas".
    parts = load_parts(settings)
    cycled = next(
        r
        for r in enumerate_routes(parts, strategies=["A_native_split"], pathway=blocked)
        if [s.part.id for s in r.cofactor_cycle] == ["pos5_native"]
    )
    assert cycled.redox_balance.status == "unknown"
    assert any(COFACTOR_CYCLE in line for line in cycled.redox_balance.unknowns)


def test_the_redox_flag_does_not_reorder_the_ranking(parts: tuple, routes: list, pathway) -> None:  # noqa: ANN001
    """The judgement made in `rank`, pinned: the flag is reported and is NOT a sort key.

    A flag that silently reorders is a gate wearing a disguise. Ranking on it would also require
    an exchange rate between a matrix NADPH and a cytosolic NADH in order to compare two routes,
    and the reason the atlas has no such rate is that the pools are not interconvertible — the
    claim the whole DUET argument rests on.

    So: enumerate the same routes with and without the stoichiometry that produces the flag, and
    require the two rankings to be identical under both objectives.
    """
    unchecked = enumerate_routes(parts)
    assert {r.redox_balance.status for r in unchecked} == {"unknown"}
    assert {r.redox_balance.status for r in routes} != {"unknown"}, (
        "if the flagged routes were all unknown too this test would prove nothing"
    )
    for objective in ("easiest", "programme"):
        assert [r.id for r in rank(routes, objective=objective)] == [
            r.id for r in rank(unchecked, objective=objective)
        ]


def test_explain_prints_the_redox_flag_and_names_the_imbalance(parts: tuple, routes: list) -> None:
    """Clause C4 says every rank is explainable term by term, and the flag is printed even though
    it is not a rank term — a stated property of the route rather than a hidden reason for its
    position. It must print the NAME, not just the verdict.

    CHANGED 2026-09-22 — THE LIVE CATALOG NO LONGER PRODUCES AN `unknown` ROUTE, so the second half
    of this test now builds one instead of picking one out of `routes`. It used to read
    `next(r for r in routes if r.redox_balance.status == "unknown")` and that worked only because
    `adh7_native.cofactor_preference` was the literal 'unknown', which made all 1,600 routes
    carrying that part unevaluable. The field is now grounded in `doi:10.1128/aem.00362-26` and
    every one of the 6,400 enumerated routes has a computed verdict, so the old line raises
    StopIteration on a catalog that got BETTER.

    The assertion is kept rather than dropped, because what it pins is a property of `explain` and
    not a property of the catalog: `explain` must print `redox=unknown` when a route's balance was
    not evaluated. Enumerating with no curated pathway is the other, permanent way to reach that
    state — `enumerate_routes(parts)` — so the contract is tested against a route that is
    guaranteed to be `unknown` for a structural reason instead of one that happened to be.
    """
    flagged = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and any(s.part.id == "adh6_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    reason = explain(flagged)
    assert "redox=unbalanced" in reason
    assert "NADPH short by 2 in mitochondrial_matrix" in reason

    # No route in the live catalog is `unknown` any more, and that is the point of the change.
    assert not [r for r in routes if r.redox_balance.status == "unknown"]

    unknown = enumerate_routes(parts, strategies=["A_native_split"])[0]
    assert unknown.redox_balance.status == "unknown"
    assert "redox=unknown" in explain(unknown)

    # and on an excluded route too: a reader asking why it was dropped is exactly the reader who
    # needs to know it also does not close.
    dead = replace(flagged, excluded_because=("a chassis gate stands in the way",))
    assert explain(dead).startswith("EXCLUDED:")
    assert "redox=unbalanced" in explain(dead)


def test_the_named_imbalance_is_stored_as_a_gap_with_its_compartment(
    parts: tuple, routes: list
) -> None:
    """`balance_status` can now say 'fail'. A 'fail' with nothing beside it naming which pool in
    which compartment is short is the boolean the ruling rejects, so the named imbalance is a
    `knowledge_gap` row with the compartment in its own column — queryable, not a string search."""
    flagged = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and any(s.part.id == "adh6_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    connection = _db(parts)
    try:
        write_routes(connection, [flagged])
        status = connection.execute("SELECT balance_status FROM pathway_route").fetchone()[0]
        assert status == "fail"
        rows = connection.execute(
            "SELECT compartment_id, description FROM knowledge_gap "
            "WHERE description LIKE 'per-compartment redox:%'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "mitochondrial_matrix"
        assert "NADPH short by 2" in rows[0][1]
        # and the route it hangs off is still there, flagged rather than absent
        assert connection.execute("SELECT COUNT(*) FROM pathway_route").fetchone()[0] == 1
    finally:
        connection.close()


def test_the_per_compartment_demand_that_the_gate_would_need_is_computed(routes: list) -> None:
    """Still a different question from the balance, and still worth its own test.

    `cofactor_demand` counts how many STEPS want a pool in a compartment; `redox_balance` sums the
    curated STOICHIOMETRY and says what does not close there. They agree today because every redox
    step turns over one equivalent, and they would stop agreeing the moment a curated reaction had
    a coefficient of 2 — at which point the demand tally would be the wrong number to reason with
    and the balance would be the right one."""
    matrix_routes = [r for r in routes if r.strategy == "C_mitochondrial_ehrlich"]
    assert any(
        count >= 2
        for route in matrix_routes
        for (compartment, _), count in route.redox_demand.items()
        if compartment == "mitochondrial_matrix"
    ), "a route concentrating two demands in one compartment is exactly what the gate is for"


def test_an_exclusion_names_its_cause_wherever_one_can_occur(parts: tuple) -> None:
    """The clause no longer excludes for a redox reason — it flags — but exclusion still exists
    for a stoichiometric impossibility and for a chassis disqualification, and the MECHANISM is
    testable: `excluded_because` carries sentences, and `explain` leads with them rather than
    printing a rank for a dead route."""
    from fermdb.metabolic.chassis import ChassisGate
    from fermdb.metabolic.routes import Route

    route = enumerate_routes(parts, strategies=["A_native_split"])[0]
    dead = replace(
        route,
        excluded_because=("redox: mitochondrial_matrix wants 2 NADPH and supplies 0",),
        chassis_gates=(
            ChassisGate(kind="test", severity="disqualifying", message="stands in for a gate"),
        ),
    )
    assert isinstance(dead, Route)
    assert not dead.viable
    reason = explain(dead)
    assert reason.startswith("EXCLUDED:")
    assert "mitochondrial_matrix" in reason and "NADPH" in reason


def test_ranking_prefers_no_transport_gap_over_higher_feasibility(routes: list) -> None:
    """A_native_split has feasibility 1.0 — nothing is relocalized — but it carries the 2-KIV gap.
    A route with no gap must outrank it, or the ranker is rewarding the pathway's own problem.
    """
    ordered = rank(routes)
    first_native = next(i for i, r in enumerate(ordered) if r.strategy == "A_native_split")
    assert ordered[0].strategy != "A_native_split"
    assert first_native > 0
    assert not ordered[0].transport_gaps


def test_mtdna_routes_are_present_but_rank_below_the_routine_ones(routes: list) -> None:
    """Displayed, not hidden — that is the point of enumerating generatively — but the feasibility
    term puts them below every strategy whose manipulations are routine.

    Note it does NOT put them last: strategy A ranks lower still, because a missing carrier is a
    harder problem than a difficult technique, and the transport term leads."""
    ordered = rank(routes)
    position = {r.id: i for i, r in enumerate(ordered)}
    mtdna = [r for r in ordered if r.strategy == "E_mtdna_encoded"]
    assert mtdna, "strategy E must be enumerated, not filtered away"

    earliest_mtdna = min(position[r.id] for r in mtdna)
    for routine in ("B_cytosolic_relocalization", "C_mitochondrial_ehrlich"):
        latest = max(position[r.id] for r in ordered if r.strategy == routine)
        assert latest < earliest_mtdna, f"{routine} must outrank every mtDNA route"


# ------------------------------------------------------- the objective the ranking answers to


def test_the_default_objective_reproduces_the_historical_order_exactly(routes: list) -> None:
    """`objective` is additive. Adding it must not have silently re-ranked anything.

    This is the guard on the whole change: `programme_fit` exists so that a future decision CAN
    move strategy C above B, and until that decision is taken the ordering must be identical to
    what it was before the parameter existed.
    """
    assert [r.id for r in rank(routes)] == [r.id for r in rank(routes, objective="easiest")]


def test_the_recorded_programme_fit_puts_c_first_without_dropping_b(routes: list) -> None:
    """The owner filled PROGRAMME_FIT on 2026-09-22, so the mechanism is no longer inert.

    This replaces `test_programme_objective_changes_nothing_while_fit_is_unrecorded`, which pinned
    the seeded-None state and was written to fail the day values arrived.

    The ruling was "favour C, and retain everything on B", and both halves are asserted here
    because the second is the one a future change could quietly break. Programme fit is a **sort
    key and never a filter**: the two objectives must return the same *set* of routes and differ
    only in order. A version that scored B down by removing it would satisfy "favour C" and betray
    the instruction.
    """
    easiest = rank(routes)
    programme = rank(routes, objective="programme")

    # Same population, different order. Not one route fewer.
    assert {r.id for r in easiest} == {r.id for r in programme}
    assert [r.id for r in easiest] != [r.id for r in programme]

    assert programme[0].strategy == "C_mitochondrial_ehrlich"
    assert easiest[0].strategy == "B_cytosolic_relocalization"

    # And B is still reachable and ranked, not buried past the end of a listing.
    assert any(r.strategy == "B_cytosolic_relocalization" for r in programme)


def test_hard_constraints_still_outrank_the_programme_preference(routes: list) -> None:
    """Transport gaps and cofactor risks are consulted before programme fit, deliberately.

    A C route with a missing carrier must still sort below a clean B route: the preference says
    what the programme wants, not what is buildable, and a lexicographic key is what keeps the two
    from trading against each other. Asserted on the key itself rather than on an ordering, so it
    holds whatever the catalog happens to contain.
    """
    gapped_c = [r for r in routes if r.strategy == "C_mitochondrial_ehrlich" and r.transport_gaps]
    clean_b = [
        r
        for r in routes
        if r.strategy == "B_cytosolic_relocalization" and not r.transport_gaps and r.viable
    ]
    if not gapped_c or not clean_b:
        pytest.skip("catalog has no gapped C route or no clean B route to contrast")
    ordered = rank(gapped_c + clean_b, objective="programme")
    assert ordered[0].strategy == "B_cytosolic_relocalization"


def test_a_recorded_programme_fit_can_outrank_feasibility(routes: list) -> None:
    """The finding this parameter was built for: confirming rho+ cleared strategy C's chassis gate
    and the ranking did not move, because B beats C at the *third* key — feasibility, 0.80 against
    0.60 — while the chassis gate is the fourth.

    Feasibility is not wrong; it measures technique difficulty correctly. It simply cannot express
    that this programme is trying to build a matrix pathway. With fit recorded, it can.
    """
    fit = {"C_mitochondrial_ehrlich": 1.0, "B_cytosolic_relocalization": 0.2}
    easiest = rank(routes)
    programme = rank(routes, objective="programme", programme_fit=fit)

    def first(ordered: list, strategy: str) -> int:
        return next(i for i, r in enumerate(ordered) if r.strategy == strategy)

    assert first(easiest, "B_cytosolic_relocalization") < first(easiest, "C_mitochondrial_ehrlich")
    assert first(programme, "C_mitochondrial_ehrlich") < first(
        programme, "B_cytosolic_relocalization"
    )


def test_programme_fit_never_overrides_a_transport_gap(routes: list) -> None:
    """Fit is consulted third, after gaps and cofactor risks — never first.

    A missing carrier is a hard engineering problem and stays ahead of what the programme would
    prefer, or the ranker would let intent overrule biology.
    """
    fit = dict.fromkeys(("A_native_split",), 1.0)
    ordered = rank(routes, objective="programme", programme_fit=fit)
    assert not ordered[0].transport_gaps
    assert ordered[0].strategy != "A_native_split"


def test_explain_names_the_objective_it_answered(routes: list) -> None:
    """A reader who does not know which question was asked cannot read the answer, and `easiest`
    being the default makes that misreading easy."""
    best = rank(routes)[0]
    assert "objective=easiest" in explain(best)
    assert "objective=programme" in explain(best, objective="programme")
    # The fit is printed as a number now that the owner has recorded one. `unrecorded` is still
    # reachable and still means "not recorded" -- F_single_compartment_host carries None, because
    # a host with one cytoplasm makes no compartment decision for a fit to be measured against.
    assert "programme_fit=0.70" in explain(best)


def test_an_unknown_objective_is_refused_rather_than_guessed(routes: list) -> None:
    with pytest.raises(ValueError, match="objective must be one of"):
        rank(routes, objective="best")


# ------------------------------------------- per-compartment redox demand and the mtDNA plan


def test_the_published_yeast_route_wants_two_nadph_in_the_matrix(routes: list) -> None:
    """The error the 2026-09-21 ⚠ audit found in ISOBUTANOL_PROGRAM.md's prose, caught in data.

    The prose says the ADH step "typically takes NADH". The published yeast route is KivD +
    **Adh6**, and Adh6 is NADPH-dependent — so run in the matrix it wants 2 NADPH there, not one
    NADPH and one NADH. The parts catalog carried the right cofactor all along; nothing added
    them up, so no route card could show it.
    """
    from fermdb.metabolic.routes import cofactor_demand

    route = next(
        r
        for r in routes
        if r.strategy == "C_mitochondrial_ehrlich"
        and any(s.part.id == "adh6_native" for s in r.steps)
        and any(s.part.id == "ilv5_native" for s in r.steps)
    )
    demand = cofactor_demand(route.steps)
    assert demand[("mitochondrial_matrix", "NADPH")] == 2
    assert ("mitochondrial_matrix", "NADH") not in demand


def test_an_nadh_preferring_kari_halves_the_matrix_nadph_draw(routes: list) -> None:
    """Why the cofactor-switched part is in the catalog at all: it moves one of the two demands
    off the pool DUET's architecture treats as thin."""
    from fermdb.metabolic.routes import cofactor_demand

    def demand_for(kari: str) -> dict:
        route = next(
            r
            for r in routes
            if r.strategy == "C_mitochondrial_ehrlich"
            and any(s.part.id == kari for s in r.steps)
            and any(s.part.id == "adh6_native" for s in r.steps)
        )
        return cofactor_demand(route.steps)

    assert demand_for("ilv5_native")[("mitochondrial_matrix", "NADPH")] == 2
    switched = demand_for("ilvc6e6_ecoli")
    assert switched[("mitochondrial_matrix", "NADPH")] == 1
    assert switched[("mitochondrial_matrix", "NADH")] == 1


def test_a_non_redox_step_contributes_no_demand(routes: list) -> None:
    """AHAS and DHAD are 'NA'. Counting them would inflate every route equally, which is worse
    than useless — it would look like a measurement."""
    from fermdb.metabolic.routes import cofactor_demand

    route = routes[0]
    assert sum(cofactor_demand(route.steps).values()) <= len(route.steps) - 2


def test_strategy_e_names_its_locus_leader_and_displacement(routes: list) -> None:
    """PLAN.md phase 3: strategy E routes must each name "its locus, leader, displaced gene and
    recoding requirement". Before `mtdna_locus` the ranker could name only the recoding."""
    from fermdb.config import Settings
    from fermdb.metabolic.mtdna_loci import load_activator_map
    from fermdb.metabolic.routes import insertion_plan

    loci = load_activator_map(Settings.load())
    route = next(r for r in routes if r.strategy == "E_mtdna_encoded")
    plan = insertion_plan(route.steps, loci)

    assert plan, "a route carrying genes in mtDNA must produce an insertion plan"
    body = " ".join(plan)
    assert "locus" in body and "leader" in body
    assert "displaces" in body
    assert "table 3" in body


def test_the_plan_prefers_the_site_that_displaces_nothing(routes: list) -> None:
    """There is exactly one such site and it is the whole reason §2.1's 'inserting costs you the
    gene whose UTR you borrowed' is not true in general."""
    from fermdb.config import Settings
    from fermdb.metabolic.mtdna_loci import load_activator_map
    from fermdb.metabolic.routes import insertion_plan

    loci = load_activator_map(Settings.load())
    route = next(r for r in routes if r.strategy == "E_mtdna_encoded")
    plan = insertion_plan(route.steps, loci)
    assert any("displaces nothing" in line for line in plan)
    assert any("respiration kept" in line for line in plan)
    # and it must still say what the alternative costs, or the reader cannot weigh it
    assert any("would instead displace" in line for line in plan)


def test_every_strategy_e_route_names_all_four_things_not_just_one_of_them(routes: list) -> None:
    """The clause says "**each** names its locus, leader, displaced gene and recoding
    requirement". The test above checks one route; this checks all 120, and checks all four
    nouns rather than whichever happens to appear.

    'Displaced gene' is satisfied either by naming the gene or by saying the site displaces
    nothing — the second is a stronger answer and is the one the free locus gives, but it has to
    be *said*, because silence about displacement reads as "no displacement" and is not.
    """
    from fermdb.config import Settings
    from fermdb.metabolic.mtdna_loci import load_activator_map
    from fermdb.metabolic.routes import insertion_plan

    loci = load_activator_map(Settings.load())
    mtdna = [r for r in routes if r.strategy == "E_mtdna_encoded"]
    assert len(mtdna) == len(routes) // len(STRATEGY_PLANS)

    for route in mtdna:
        carried = [s for s in route.steps if s.needs_recoding]
        plan = insertion_plan(route.steps, loci)
        assert plan, route.id
        # one line per gene actually carried in the mtDNA, plus the alternatives line
        per_step = [line for line in plan if not line.startswith("alternative:")]
        assert len(per_step) == len(carried) == 2, route.id
        for line in per_step:
            assert "locus " in line, f"no locus named: {line}"
            assert "leader " in line, f"no leader named: {line}"
            assert "activator " in line, f"no activator named: {line}"
            assert "displaces " in line, f"nothing said about displacement: {line}"
            assert "recode to NCBI table 3" in line, f"no recoding requirement: {line}"
        body = " ".join(plan)
        assert any(locus.locus in body for locus in loci), route.id


def test_strategy_e_is_reachable_but_costly_rather_than_dropped_or_flattered(routes: list) -> None:
    """Three claims in one clause, so three assertions.

    *Not dropped*: every E route is viable and appears in the ranked list.
    *Costly*: every E route carries a construction requirement and the worst feasibility of any
    strategy, so nothing about it is free.
    *Not flattered*: no E route reaches the top of the ranking.
    """
    ordered = rank(routes)
    mtdna = [r for r in routes if r.strategy == "E_mtdna_encoded"]
    ranked_ids = {r.id for r in ordered}

    assert all(r.viable for r in mtdna)
    assert all(r.id in ranked_ids for r in mtdna), "a costly route is still an offered route"

    assert all(r.construction_requirements for r in mtdna)
    worst = min(p.feasibility for p in STRATEGY_PLANS.values())
    assert all(r.score_feasibility == worst for r in mtdna)
    assert STRATEGY_PLANS["E_mtdna_encoded"].feasibility_reason.strip()

    assert ordered[0].strategy != "E_mtdna_encoded"


def test_a_route_with_nothing_in_mtdna_has_no_insertion_plan(routes: list) -> None:
    from fermdb.config import Settings
    from fermdb.metabolic.mtdna_loci import load_activator_map
    from fermdb.metabolic.routes import insertion_plan

    loci = load_activator_map(Settings.load())
    route = next(r for r in routes if r.strategy == "B_cytosolic_relocalization")
    assert insertion_plan(route.steps, loci) == ()


# ------------------------------------------------------------------------------------ storage


def test_gaps_are_stored_as_knowledge_gap_rows_not_free_text(parts: tuple, routes: list) -> None:
    """G.8: a gap with a predicate and a route to hang off can be counted, assigned and closed.
    A sentence in an evidence column is a note nobody queries."""
    connection = _db(parts)
    try:
        counts = write_routes(connection, routes[:20])
        assert counts["knowledge_gap"] > 0
        kinds = {row[0] for row in connection.execute("SELECT DISTINCT kind FROM knowledge_gap")}
        assert kinds <= {"transport_carrier_unknown", "quantitative_value_missing"}
        linked = connection.execute(
            "SELECT COUNT(*) FROM knowledge_gap WHERE route_id IS NOT NULL"
        ).fetchone()[0]
        assert linked == counts["knowledge_gap"]
    finally:
        connection.close()


def test_writing_is_idempotent_across_processes(parts: tuple, routes: list) -> None:
    """Ids are content-derived. Python's hash() is salted per process, so using it would write a
    fresh set of rows on every run and the table would grow without anything changing."""
    connection = _db(parts)
    try:
        first = write_routes(connection, routes[:10])
        second = write_routes(connection, routes[:10])
        assert first == second
        assert connection.execute("SELECT COUNT(*) FROM pathway_route").fetchone()[0] == 10
    finally:
        connection.close()


def test_stored_routes_are_zone_i(parts: tuple, routes: list) -> None:
    connection = _db(parts)
    try:
        write_routes(connection, routes[:5])
        zones = {row[0] for row in connection.execute("SELECT DISTINCT zone FROM pathway_route")}
        assert zones == {"I"}
    finally:
        connection.close()
