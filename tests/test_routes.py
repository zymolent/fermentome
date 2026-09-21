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
    STEP_ORDER,
    STRATEGY_PLANS,
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
    been tried' can be read off as the complement of the evidence."""
    per_role = {role: sum(1 for p in parts if p.step_role == role) for role in STEP_ORDER}
    expected = len(STRATEGY_PLANS)
    for count in per_role.values():
        expected *= count
    assert len(routes) == expected


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


def test_a_missing_stoichiometry_is_unknown_and_never_balanced(parts: tuple, routes: list) -> None:
    """The distinction the hard rule turns on. Where the reaction/cofactor data does not say what
    a step does to the redox pools, the answer is `unknown` — a state of its own, reported as
    such, and never quietly rounded to `balanced`.

    Two ways to get there, both real:

    * no curated pathway supplied at all, which is what `enumerate_routes(parts)` does; and
    * a part whose `cofactor_preference` is the literal 'unknown'. `adh7_native` is exactly that:
      it was read out of a paper that does not state the cofactor, and the catalog left it unknown
      rather than filling it in from background knowledge.
    """
    unchecked = enumerate_routes(parts, strategies=["A_native_split"])
    assert all(r.redox_balance.status == "unknown" for r in unchecked)
    assert all(not r.redox_balance.net for r in unchecked)
    assert all("never be read as 'balanced'" in r.redox_balance.unknowns[0] for r in unchecked)
    assert all(r.balance_status == "not_evaluated" for r in unchecked)

    undeclared = [
        r for r in routes if any(s.part.cofactor_preference == "unknown" for s in r.steps)
    ]
    if undeclared:  # only while the catalog carries such a part; it carries adh7_native today
        route = undeclared[0]
        assert route.redox_balance.status == "unknown"
        assert route.redox_balance.unknowns
        assert "cofactor_preference" in route.redox_balance.unknowns[0]
        # and the part that IS known is still reported, rather than the whole route going dark
        assert route.redox_balance.imbalances
        assert route.viable, "an unevaluated balance is not a reason to drop a route either"


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

    No route comes back balanced today and that is a finding, not a bug: the five catalytic steps
    consume reducing power and none of them regenerates it, so closure would need a
    `cofactor_cycle` part and STEP_ORDER has no slot for one. Substitute non-redox parts into the
    two redox steps and the same function returns `balanced` — which is what makes the three-state
    verdict a measurement rather than a constant.
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


def test_explain_prints_the_redox_flag_and_names_the_imbalance(routes: list) -> None:
    """Clause C4 says every rank is explainable term by term, and the flag is printed even though
    it is not a rank term — a stated property of the route rather than a hidden reason for its
    position. It must print the NAME, not just the verdict."""
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

    unknown = next(r for r in routes if r.redox_balance.status == "unknown")
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
