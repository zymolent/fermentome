"""Tests for `fermdb.curate.assertions`.

An assertion is the only row in this atlas that is *read as a claim*. A `measurement` is a number
somebody wrote down; an assertion says what that number means, and PLAN.md C.1 calls it the unit
of knowledge with everything else "the vocabulary assertions speak about". Which makes the way it
can go wrong specific: not a bad number, but a claim that looks graded and sourced when nobody
graded or sourced it.

So these tests are mostly about what is refused, and each refusal is a way the atlas could
otherwise have acquired a graded, cited-looking statement that nobody stands behind:

* an unknown predicate coerced to the nearest one, which makes the knowledge graph unqueryable
  in the quiet way -- the edge is there, it is just the wrong edge;
* direct evidence with no `independent_group`, which can never reach L2 and would have looked
  like an ordinary L1 forever;
* an evidence item citing nothing, which is an assertion CI's J.5 walk will fail on later with
  nobody left who knows what it was meant to cite;
* an AI inference wearing a measurement id, which is the single thing `evidence_item`'s CHECKs
  were written to make unstorable.

And one test that is not about a refusal at all and matters more than any of them:
:func:`test_a_second_independent_group_changes_the_level_the_view_reports`. It proves the level
is derived by changing the evidence and watching the answer change, against an assertion row that
nothing rewrote.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from fermdb.curate import assertions as A
from fermdb.curate.queue import Curator
from fermdb.db import IN_MEMORY, open_db

HUMAN = Curator(name="kangkon", kind="human")
AGENT = Curator(name="curation-worker-3", kind="agent")

PUB_A = "doi:10.9999/paper-a"
PUB_B = "doi:10.9999/paper-b"


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory atlas holding what `promote.py` would have left behind.

    Two publications from two different labs, one engineered strain and its control, a measured
    titer from each paper, a modification and a bottleneck. Nothing here is an assertion: that is
    the gap.

    Every one of those rows now carries a real `publication_id`. Until schema v12 `measurement`
    and `bottleneck` did not have the column at all, and the paper survived only inside the
    `evidence` prose -- which is why that prose is still written here exactly as promotion leaves
    it, and why it deliberately says "paper-a" rather than the id. Anything that comes back with
    the publication got it from the column.
    """
    conn = open_db(IN_MEMORY)
    conn.executescript(
        """
        INSERT INTO organism (id, name, zone, evidence, confidence)
            VALUES ('YAA:ORG:scer', 'Saccharomyces cerevisiae', 'R', 'test fixture', 'low');
        INSERT INTO product (id, name, zone, evidence, confidence)
            VALUES ('YAA:PRODUCT:isobutanol', 'isobutanol', 'R', 'test fixture', 'low');
        INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence)
            VALUES ('YAA:STRAIN:host', 'YAA:ORG:scer', 'HOST-1', 'engineered', 'R', 'x', 'low'),
                   ('YAA:STRAIN:ctrl', 'YAA:ORG:scer', 'CTRL-1', 'laboratory', 'R', 'x', 'low');
        INSERT INTO publication (id, year, zone, evidence, confidence)
            VALUES ('doi:10.9999/paper-a', 2019, 'R', 'test fixture', 'low'),
                   ('doi:10.9999/paper-b', 2021, 'R', 'test fixture', 'low');
        INSERT INTO span (id, publication_id, char_start, char_end, quoted_text, record_path,
                          zone)
            VALUES ('YAA:SPAN:a', 'doi:10.9999/paper-a', 10, 40, 'the titer reached 1.32 g/L',
                    'measurements[0]', 'R'),
                   ('YAA:SPAN:b', 'doi:10.9999/paper-b', 10, 40, 'we measured 2.10 g/L',
                    'measurements[0]', 'R');
        INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported,
                                 unit_as_reported, source_locator, publication_id, zone,
                                 evidence, confidence)
            VALUES ('YAA:MEAS:a', 'YAA:STRAIN:host', 'titer', 'YAA:PRODUCT:isobutanol', 1.32,
                    'g/L', 'text', 'doi:10.9999/paper-a', 'R',
                    'promoted from curation task ... on paper-a', 'medium'),
                   ('YAA:MEAS:b', 'YAA:STRAIN:host', 'titer', 'YAA:PRODUCT:isobutanol', 2.10,
                    'g/L', 'table 2', 'doi:10.9999/paper-b', 'R',
                    'promoted from curation task ... on paper-b', 'medium');
        INSERT INTO modification (id, strain_id, type, target_locus, publication_id, zone,
                                  evidence, confidence)
            VALUES ('YAA:MOD:bat1', 'YAA:STRAIN:host', 'deletion', 'BAT1',
                    'doi:10.9999/paper-a', 'R', 'promoted', 'medium');
        INSERT INTO bottleneck (id, node, observation_type, publication_id, zone, evidence,
                                confidence)
            VALUES ('YAA:BNK:pyruvate', 'pyruvate node', 'inferred', 'doi:10.9999/paper-a', 'R',
                    'promoted', 'medium');
        INSERT INTO reaction (id, name, zone, evidence, confidence)
            VALUES ('YAA:RXN:ahas', 'acetolactate synthase', 'R', 'curated', 'medium');
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def _direct(**overrides: object) -> A.EvidenceRequest:
    """A complete `direct_perturbation` evidence item, for tests that break exactly one field."""
    fields: dict[str, object] = {
        "evidence_type": "direct_perturbation",
        "independent_group": "lab-atsumi",
        "publication_id": PUB_A,
        "span_id": "YAA:SPAN:a",
        "direction": "increases",
        "strain_id": "YAA:STRAIN:host",
        "control_strain_id": "YAA:STRAIN:ctrl",
        "measurement_id": "YAA:MEAS:a",
    }
    fields.update(overrides)
    return A.EvidenceRequest(**fields)  # type: ignore[arg-type]


def _request(**overrides: object) -> A.AssertionRequest:
    fields: dict[str, object] = {
        "subject_type": "strain",
        "subject_id": "YAA:STRAIN:host",
        "predicate": "affects_production_of",
        "object_type": "product",
        "object_id": "YAA:PRODUCT:isobutanol",
        "product_id": "YAA:PRODUCT:isobutanol",
        "direction": "increases",
        "evidence": (_direct(),),
    }
    fields.update(overrides)
    return A.AssertionRequest(**fields)  # type: ignore[arg-type]


def _why(plan: A.AssertionPlan) -> str:
    return plan.note


# ---------------------------------------------------------------------------------------------
# The predicate vocabulary
# ---------------------------------------------------------------------------------------------


def test_a_predicate_outside_the_vocabulary_is_refused_and_the_vocabulary_is_named(
    atlas: sqlite3.Connection,
) -> None:
    """A closed vocabulary that silently accepts a near miss has stopped being closed.

    PLAN.md J.2 closes the predicate set at 17 terms because an open one makes the graph
    unqueryable within a year. The failure this prevents is not a crash: it is an edge that is
    present, looks fine, and is the wrong edge -- `increases_production_of` and
    `affects_production_of` would sit side by side and every traversal would find half the data.
    """
    plan = A.plan_assertion(atlas, _request(predicate="increases_production_of"))
    assert not plan.ready
    assert "increases_production_of" in _why(plan)
    assert "affects_production_of" in _why(plan), "the refusal must name the terms that do exist"


def test_a_deprecated_predicate_is_refused_separately_from_an_absent_one(
    atlas: sqlite3.Connection,
) -> None:
    """Retired and never-existed send a curator to two different places.

    A retired term means "there is a replacement, find it"; an absent one means "you invented
    this". Collapsing them into one message costs the reader the only useful part.
    """
    atlas.execute("UPDATE predicate SET status = 'deprecated' WHERE id = 'competes_with'")
    plan = A.plan_assertion(atlas, _request(predicate="competes_with"))
    assert not plan.ready
    assert "deprecated" in _why(plan)


def test_an_assertion_whose_predicate_is_in_the_vocabulary_is_not_blocked_on_it(
    atlas: sqlite3.Connection,
) -> None:
    """The check is a vocabulary lookup, not a hardcoded list that will drift from the table."""
    plan = A.plan_assertion(atlas, _request())
    assert plan.ready, _why(plan)


# ---------------------------------------------------------------------------------------------
# What an evidence item must carry
# ---------------------------------------------------------------------------------------------


def test_direct_evidence_without_an_independent_group_is_refused(
    atlas: sqlite3.Connection,
) -> None:
    """A NULL group is counted by nothing, so the assertion could never reach L2.

    `assertion_level` counts `COUNT(DISTINCT independent_group) ... WHERE it IS NOT NULL`. Two
    group-less direct evidence items are therefore zero groups, and the assertion sits at L1
    looking exactly like one that genuinely has a single source. The schema permits the NULL;
    this module does not, because the consequence is invisible.
    """
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(independent_group=None),)))
    assert not plan.ready
    assert "independent_group" in _why(plan)
    assert "by group" in _why(plan)


def test_the_group_is_never_defaulted_to_the_publication(atlas: sqlite3.Connection) -> None:
    """The obvious default is the exact conflation PLAN.md J.3 axis 2 exists to prevent.

    One lab publishing three times would become three independent groups and the assertion would
    be promoted to L2 by the arithmetic. The refusal message has to say so, or the next person
    will add the default as an obvious convenience.
    """
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(independent_group=None),)))
    assert "publication" in _why(plan)
    assert plan.request.evidence[0].independent_group is None, "the plan must not fill it in"


def test_evidence_that_cites_nothing_at_all_is_refused(atlas: sqlite3.Connection) -> None:
    """PLAN.md J.5: an assertion that cannot produce a chain is a bug, not a soft warning.

    Refused here rather than in CI, because here there is still someone in the room who knows
    what the evidence was meant to cite.
    """
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(publication_id=None, span_id=None),)))
    assert not plan.ready
    assert "J.5" in _why(plan)


def test_a_measurement_carries_its_own_publication_and_from_measurement_reads_it(
    atlas: sqlite3.Connection,
) -> None:
    """The asymmetry this file used to record is gone, at both layers.

    What it used to say: `measurement` had no publication column, so promotion's
    "promoted from curation task ... on doi:10.1186/..." prose was the only record of the paper,
    and J.5's assertion -> evidence -> measurement -> publication walk had no last hop. Parsing
    that sentence back out was refused -- it is citing a file in this repository, which
    CONVENTIONS.md calls citing memory with an extra hop, and it would produce a confidently wrong
    publication the first time the format changed. The column was added instead, and the 97 rows
    already in the atlas were backfilled from `curation_task`, which is where promotion had the
    value all along.

    Schema v12 was half of it and this test used to assert the other half was still missing:
    `from_measurement` left `publication_id` None, so the plan asked a curator for something the
    row already knew. It now reads the column, `from_measurement` and `from_modification` behave
    the same way, and the two assertions below are the ones that flipped when it was wired --
    the plan no longer names J.5, and it no longer needs `publication_id` passed to stop.
    """
    columns = {row["name"] for row in atlas.execute("PRAGMA table_info(measurement)")}
    assert "publication_id" in columns

    walked = atlas.execute(
        "SELECT p.id FROM measurement m JOIN publication p ON p.id = m.publication_id "
        "WHERE m.id = 'YAA:MEAS:a'"
    ).fetchone()
    assert walked["id"] == PUB_A, "J.5's last hop is a join now, not a sentence"

    request = A.from_measurement(
        atlas,
        "YAA:MEAS:a",
        predicate="affects_production_of",
        evidence_type="direct_perturbation",
        independent_group="lab-atsumi",
        direction="increases",
        control_strain_id="YAA:STRAIN:ctrl",
    )
    assert request.evidence[0].publication_id == PUB_A, (
        "the paper comes off `measurement.publication_id`, not out of the `evidence` prose and "
        "not from the curator -- the `evidence` sentence in this fixture deliberately says "
        "'paper-a' rather than the id, so anything holding the id read the column"
    )
    assert "J.5" not in _why(A.plan_assertion(atlas, request))
    assert A.plan_assertion(atlas, request).ready

    # An explicit argument still wins, which is what a row whose own column is NULL needs.
    supplied = A.from_measurement(
        atlas,
        "YAA:MEAS:a",
        predicate="affects_production_of",
        evidence_type="direct_perturbation",
        independent_group="lab-atsumi",
        direction="increases",
        control_strain_id="YAA:STRAIN:ctrl",
        publication_id=PUB_B,
    )
    assert supplied.evidence[0].publication_id == PUB_B


def test_a_measurement_with_no_publication_of_its_own_still_asks_for_one(
    atlas: sqlite3.Connection,
) -> None:
    """NULL means "there is no paper", and the requirement is then real rather than invented.

    `measurement.publication_id` is nullable because a number read out of a deposited dataset
    rather than out of a paper is a legitimate row. Reading the column must therefore not turn
    into assuming it: when it is NULL nothing closed a J.5 arm, and the plan says so by name.
    """
    atlas.execute("UPDATE measurement SET publication_id = NULL WHERE id = 'YAA:MEAS:a'")
    request = A.from_measurement(
        atlas,
        "YAA:MEAS:a",
        predicate="affects_production_of",
        evidence_type="direct_perturbation",
        independent_group="lab-atsumi",
        direction="increases",
        control_strain_id="YAA:STRAIN:ctrl",
    )
    assert request.evidence[0].publication_id is None
    plan = A.plan_assertion(atlas, request)
    assert not plan.ready
    assert "J.5" in _why(plan)


def test_a_bottleneck_carries_its_own_publication_and_from_bottleneck_reads_it(
    atlas: sqlite3.Connection,
) -> None:
    """`bottleneck.publication_id` is the same v12 column and the same wiring.

    It was added for the same reason and left unread for the same reason, and it is checked here
    separately because `from_bottleneck` reaches a different row: the two consumers could easily
    have been fixed one at a time.
    """
    request = A.from_bottleneck(
        atlas,
        "YAA:BNK:pyruvate",
        predicate="is_bottleneck_for",
        evidence_type="literature_assertion",
        object_type="product",
        object_id="YAA:PRODUCT:isobutanol",
        subject_type="reaction",
        subject_id="YAA:RXN:ahas",
        span_id="YAA:SPAN:a",
    )
    assert request.evidence[0].publication_id == PUB_A
    assert "J.5" not in _why(A.plan_assertion(atlas, request))


def test_a_direct_perturbation_without_a_stated_control_is_refused(
    atlas: sqlite3.Connection,
) -> None:
    """L1 is "direct evidence *with a stated control*", and the control is the whole of it.

    A titer with nothing to compare it against is not a perturbation result; it is a number.
    """
    plan = A.plan_assertion(
        atlas, _request(evidence=(_direct(control_strain_id=None, control_condition_id=None),))
    )
    assert not plan.ready
    assert "control_strain_id|control_condition_id" in _why(plan)


def test_a_direction_is_required_of_a_perturbation_and_is_not_read_off_the_number(
    atlas: sqlite3.Connection,
) -> None:
    """A measurement is a number; "increases" is a comparison someone made."""
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(direction=None),)))
    assert not plan.ready
    assert "direction" in _why(plan)


def test_an_ai_inference_may_not_carry_a_measurement(atlas: sqlite3.Connection) -> None:
    """The one constraint `evidence_item` restates twice, refused before SQLite has to.

    An AI inference wearing a measurement id is an inference with the authority of a measured
    number. The CHECK would refuse the row; refusing here means the message says which row and
    why rather than naming a constraint.
    """
    inference = A.EvidenceRequest(
        evidence_type="ai_inference",
        model="fake-model",
        model_version="v0",
        prompt_version="p0",
        review_state="pending",
        publication_id=PUB_A,
        measurement_id="YAA:MEAS:a",
        zone="I",
    )
    plan = A.plan_assertion(atlas, _request(evidence=(inference,)))
    assert not plan.ready
    assert "only the two direct types may cite a measurement" in _why(plan)


def test_an_ai_inference_outside_zone_i_is_refused(atlas: sqlite3.Connection) -> None:
    """Zone I is what an AI inference *is*, not a label it can be talked out of.

    CONVENTIONS.md: Zone I may not support a conclusion until a curator promotes it, and
    promotion writes a new curated assertion citing the inference. It does not relabel the row.
    """
    inference = A.EvidenceRequest(
        evidence_type="ai_inference",
        model="fake-model",
        model_version="v0",
        prompt_version="p0",
        review_state="pending",
        publication_id=PUB_A,
        zone="R",
    )
    plan = A.plan_assertion(atlas, _request(evidence=(inference,)))
    assert not plan.ready
    assert "Zone I by definition" in _why(plan)


def test_an_evidence_type_outside_the_closed_set_is_refused(atlas: sqlite3.Connection) -> None:
    """`evidence_item`'s CHECK has `ELSE 0`, so an unlisted type is unstorable by design."""
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(evidence_type="vibes"),)))
    assert not plan.ready
    assert "vibes" in _why(plan)


def test_a_span_belonging_to_another_paper_is_refused(atlas: sqlite3.Connection) -> None:
    """A citation that resolves to the wrong sentence is worse than one that fails to resolve.

    A broken link is visible. A link to a real quote in a different paper reads as verified.
    """
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(span_id="YAA:SPAN:b"),)))
    assert not plan.ready
    assert "belongs to" in _why(plan)


def test_a_cited_row_that_does_not_exist_is_refused(atlas: sqlite3.Connection) -> None:
    """A foreign key would raise on write; this says which column and which id."""
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(measurement_id="YAA:MEAS:zzz"),)))
    assert not plan.ready
    assert "YAA:MEAS:zzz" in _why(plan)


# ---------------------------------------------------------------------------------------------
# What an assertion must carry
# ---------------------------------------------------------------------------------------------


def test_an_assertion_with_no_evidence_is_refused(atlas: sqlite3.Connection) -> None:
    """It would be graded NULL with basis 'no_evidence' and fail J.5's walk in CI.

    An unsupported claim in the unit-of-knowledge table is the worst row this atlas can hold,
    because everything downstream renders it exactly like a supported one minus a badge.
    """
    plan = A.plan_assertion(atlas, _request(evidence=()))
    assert not plan.ready
    assert "no_evidence" in _why(plan)


def test_a_dangling_subject_is_refused_although_no_foreign_key_would_catch_it(
    atlas: sqlite3.Connection,
) -> None:
    """`assertion.subject_id` is polymorphic TEXT: SQLite will store anything at all.

    `schema.sql`'s header says the integrity of these columns is checked by J.5's walk in CI.
    That is a nightly job with no idea who wrote the row; this check runs while the author is
    still here.
    """
    plan = A.plan_assertion(atlas, _request(subject_id="YAA:STRAIN:never-promoted"))
    assert not plan.ready
    assert "polymorphic" in _why(plan)


def test_a_literal_object_may_not_also_name_a_row(atlas: sqlite3.Connection) -> None:
    """The two would disagree about what the statement is about, and the CHECK refuses it."""
    plan = A.plan_assertion(
        atlas,
        _request(object_type="literal", object_literal="2-ketoisovalerate", object_id="YAA:X:1"),
    )
    assert not plan.ready
    assert "object_id" in _why(plan)


def test_a_typed_object_must_name_an_existing_row(atlas: sqlite3.Connection) -> None:
    """Same argument as the subject, on the other side of the triple."""
    plan = A.plan_assertion(atlas, _request(object_id="YAA:PRODUCT:nonesuch"))
    assert not plan.ready
    assert "YAA:PRODUCT:nonesuch" in _why(plan)


# ---------------------------------------------------------------------------------------------
# Who may write one
# ---------------------------------------------------------------------------------------------


def test_an_agent_may_not_build_an_assertion(atlas: sqlite3.Connection) -> None:
    """PLAN.md L.5, and one reason specific to this table.

    `assertion_level` never looks at `zone`. An agent-written Zone I assertion carrying direct
    evidence is graded L1 by the view and badged L1 by the UI, with `zone` the only thing between
    an inference and an experimental claim and nothing on the level path reading it.
    """
    with pytest.raises(A.NotAssertable) as excinfo:
        A.build_assertion(atlas, _request(), curator=AGENT, reason="looks right")
    assert "L.5" in str(excinfo.value)
    assert atlas.execute("SELECT COUNT(*) AS n FROM assertion").fetchone()["n"] == 0


def test_an_agent_may_still_plan_one(atlas: sqlite3.Connection) -> None:
    """The useful half of the work does not need a person.

    An agent that hands a curator a filled-in plan with one named gap has done something worth
    doing and decided nothing. Making the planner human-only would delete that.
    """
    plan = A.plan_assertion(atlas, _request(evidence=(_direct(independent_group=None),)))
    assert not plan.ready
    assert plan.as_json()["missing"], "an agent must be able to see what is missing"


def test_an_agent_may_not_attach_evidence_either(atlas: sqlite3.Connection) -> None:
    """Adding a second group is what moves an assertion from L1 to L2. Same rule, same reason."""
    A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2")
    with pytest.raises(A.NotAssertable):
        A.attach_evidence(
            atlas,
            A.assertion_id_for(_request()),
            _direct(independent_group="lab-b", publication_id=PUB_B),
            curator=AGENT,
            reason="found another paper",
        )


# ---------------------------------------------------------------------------------------------
# The derived level
# ---------------------------------------------------------------------------------------------


def test_a_second_independent_group_changes_the_level_the_view_reports(
    atlas: sqlite3.Connection,
) -> None:
    """The point of the whole design: the level moves because the evidence moved.

    One group's direct perturbation is L1. A second group's, concordant in direction, is L2 --
    and the `assertion` row is byte-for-byte what it was, because there is no level on it to
    update. Nothing recomputed anything; the view was simply asked again.
    """
    result = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2 of paper A")
    assert result.level.level == "L1"
    assert result.level.basis == "direct_evidence"

    before = atlas.execute(
        "SELECT * FROM assertion WHERE id = ?", (result.assertion_id,)
    ).fetchone()

    second = A.attach_evidence(
        atlas,
        result.assertion_id,
        _direct(
            independent_group="lab-liao",
            publication_id=PUB_B,
            span_id="YAA:SPAN:b",
            measurement_id="YAA:MEAS:b",
        ),
        curator=HUMAN,
        reason="paper B reproduces it",
    )
    assert second.evidence_created == 1
    assert second.level.level == "L2"
    assert second.level.basis == "direct_evidence_replicated"

    after = atlas.execute("SELECT * FROM assertion WHERE id = ?", (result.assertion_id,)).fetchone()
    assert tuple(after) == tuple(before), "the assertion row must be untouched"
    assert A.level_of(atlas, result.assertion_id).level == "L2"


def test_a_second_paper_from_the_same_group_does_not_reach_l2(
    atlas: sqlite3.Connection,
) -> None:
    """Two publications, one lab: the count that matters is groups, and it is still one.

    This is the test that would fail if `independent_group` were ever defaulted to the
    publication id, which is why it sits next to the one above.
    """
    result = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2")
    second = A.attach_evidence(
        atlas,
        result.assertion_id,
        _direct(
            independent_group="lab-atsumi",  # the same lab, a second paper
            publication_id=PUB_B,
            span_id="YAA:SPAN:b",
            measurement_id="YAA:MEAS:b",
        ),
        curator=HUMAN,
        reason="the same group again",
    )
    assert second.evidence_created == 1
    assert second.level.level == "L1", "one group publishing twice is one group"


def test_retracting_the_evidence_takes_the_level_away_again(
    atlas: sqlite3.Connection,
) -> None:
    """The derivation runs in both directions, which a stored level would not.

    `assertion_level` counts only `status = 'active'` evidence: a retracted paper stops
    supporting its conclusion. Nothing in this module was called to make that happen.
    """
    result = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2")
    assert result.level.level == "L1"
    atlas.execute(
        "UPDATE evidence_item SET status = 'retracted' WHERE assertion_id = ?",
        (result.assertion_id,),
    )
    level = A.level_of(atlas, result.assertion_id)
    assert level.level is None
    assert level.basis == "no_evidence"


def test_nothing_this_module_writes_ever_names_a_level(atlas: sqlite3.Connection) -> None:
    """Traced, not reviewed: every write statement the module issues is inspected.

    `schema.sql` is explicit that "a stored level silently becomes a lie the first time a new
    paper lands", and the assertion table has no level column to write to. The columns that do
    exist -- `level_override`, `override_reason`, `override_curator` -- are a curator act under
    PLAN.md J.3, and a module that could set them could grade its own evidence.

    Reads are excluded on purpose: the `assertion_level` view's own SQL names the override
    columns, and reading the derived level back is the entire point of the design.
    """
    statements: list[str] = []
    atlas.set_trace_callback(statements.append)
    try:
        result = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2")
        A.attach_evidence(
            atlas,
            result.assertion_id,
            _direct(
                independent_group="lab-liao",
                publication_id=PUB_B,
                span_id="YAA:SPAN:b",
                measurement_id="YAA:MEAS:b",
            ),
            curator=HUMAN,
            reason="paper B",
        )
    finally:
        atlas.set_trace_callback(None)

    writes = [
        sql
        for sql in statements
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
    ]
    assert writes, "the trace caught nothing, so this test would pass vacuously"
    for sql in writes:
        assert "level" not in sql.lower(), sql

    row = atlas.execute(
        "SELECT level_override, override_reason, override_curator FROM assertion WHERE id = ?",
        (result.assertion_id,),
    ).fetchone()
    assert tuple(row) == (None, None, None)


def test_no_request_type_has_a_level_field(atlas: sqlite3.Connection) -> None:
    """There is no way to ask for a level, which is stronger than refusing one.

    A parameter that is validated away can be un-validated by an edit. A parameter that does not
    exist has to be added on purpose, in a diff someone reviews.
    """
    for dataclass_type in (A.AssertionRequest, A.EvidenceRequest):
        names = set(dataclass_type.__dataclass_fields__)
        assert not {n for n in names if "level" in n or "override" in n}, dataclass_type


# ---------------------------------------------------------------------------------------------
# The J.5 chain, written and walked
# ---------------------------------------------------------------------------------------------


def test_an_assertion_from_a_measurement_resolves_a_complete_chain(
    atlas: sqlite3.Connection,
) -> None:
    """PLAN.md J.5's acceptance test, against a row this module wrote rather than a fixture.

    assertion -> evidence_item -> measurement, and -> span -> publication, and the
    `curation_event` naming the curator and the reason. Walked as a join, because a chain that
    only a Python function can follow is not a chain.
    """
    request = A.from_measurement(
        atlas,
        "YAA:MEAS:a",
        predicate="affects_production_of",
        evidence_type="direct_perturbation",
        independent_group="lab-atsumi",
        publication_id=PUB_A,
        span_id="YAA:SPAN:a",
        direction="increases",
        control_strain_id="YAA:STRAIN:ctrl",
    )
    result = A.build_assertion(atlas, request, curator=HUMAN, reason="table 2 of paper A")

    row = atlas.execute(
        "SELECT a.id AS assertion_id, m.value_as_reported, s.quoted_text, p.id AS publication_id,"
        " e.curator, e.rationale "
        "FROM assertion a "
        "JOIN evidence_item ev ON ev.assertion_id = a.id "
        "JOIN measurement m ON m.id = ev.measurement_id "
        "JOIN span s ON s.id = ev.span_id "
        "JOIN publication p ON p.id = ev.publication_id "
        "JOIN curation_event e ON e.target_id = a.id AND e.target_type = 'assertion' "
        "WHERE a.id = ?",
        (result.assertion_id,),
    ).fetchone()
    assert row is not None, "the chain did not resolve"
    assert row["value_as_reported"] == 1.32
    assert row["publication_id"] == PUB_A
    assert row["curator"] == "kangkon"
    assert "table 2 of paper A" in row["rationale"]


def test_the_subject_and_object_come_from_the_measurement_but_the_effect_size_does_not(
    atlas: sqlite3.Connection,
) -> None:
    """A titer of 1.32 g/L is not an effect of 1.32.

    The effect is the difference from the control, and this module has not seen the control's
    number. Copying `value_as_reported` into `assertion.effect_size` would be the obvious
    convenience and would produce a fabricated effect that is indistinguishable afterwards from a
    reported one.
    """
    request = A.from_measurement(
        atlas,
        "YAA:MEAS:a",
        predicate="affects_production_of",
        evidence_type="direct_perturbation",
        independent_group="lab-atsumi",
        publication_id=PUB_A,
        direction="increases",
        control_strain_id="YAA:STRAIN:ctrl",
    )
    assert request.subject_id == "YAA:STRAIN:host"
    assert request.object_id == "YAA:PRODUCT:isobutanol"
    assert request.effect_size is None
    assert request.effect_unit is None


def test_building_the_same_assertion_twice_writes_one_row_and_one_evidence_item(
    atlas: sqlite3.Connection,
) -> None:
    """Ids are derived, so a re-run is a no-op.

    This matters more here than in promotion: a duplicated evidence item changes the derived
    level without anybody having learned anything new.
    """
    first = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2")
    second = A.build_assertion(atlas, _request(), curator=HUMAN, reason="table 2, again")
    assert first.assertion_id == second.assertion_id
    assert second.created is False
    assert second.evidence_created == 0
    assert atlas.execute("SELECT COUNT(*) AS n FROM assertion").fetchone()["n"] == 1
    assert atlas.execute("SELECT COUNT(*) AS n FROM evidence_item").fetchone()["n"] == 1
    assert second.level.level == "L1"


def test_the_opposite_direction_is_two_assertions_not_one(atlas: sqlite3.Connection) -> None:
    """The id covers the direction, so a contradicting claim cannot land on the same row.

    PLAN.md J.4 wants both sides recorded. If the id ignored direction, the second would collide
    with the first, `ON CONFLICT DO NOTHING` would swallow it, and the disagreement would vanish
    into a no-op -- the silent resolution CONVENTIONS.md forbids.
    """
    up = A.assertion_id_for(_request(direction="increases"))
    down = A.assertion_id_for(_request(direction="decreases"))
    assert up != down


def test_evidence_pointing_the_other_way_is_reported_rather_than_refused(
    atlas: sqlite3.Connection,
) -> None:
    """`assertion_level` counts distinct directions, so the schema expects this to be storable.

    Refusing it would make the view's own `n_direct_directions <= 1` branch unreachable through
    this module. But it must not be silent either: the usual right answer is two assertions and a
    `conflict` row, and recording a conflict is a curator's act under PLAN.md J.4 and L.5.
    """
    plan = A.plan_assertion(
        atlas,
        _request(
            evidence=(
                _direct(),
                _direct(
                    direction="decreases",
                    independent_group="lab-liao",
                    publication_id=PUB_B,
                    span_id="YAA:SPAN:b",
                    measurement_id="YAA:MEAS:b",
                ),
            )
        ),
    )
    assert plan.ready, _why(plan)
    assert any("J.4" in warning for warning in plan.warnings)
    assert any("conflict" in warning for warning in plan.warnings)


# ---------------------------------------------------------------------------------------------
# From a modification, and from a bottleneck
# ---------------------------------------------------------------------------------------------


def test_a_modification_closes_its_own_chain_because_it_carries_its_publication(
    atlas: sqlite3.Connection,
) -> None:
    """The asymmetry with `measurement` is real and worth having a test about.

    `modification.publication_id` is a genuine foreign key, so the paper is read off the row
    instead of being asked for. That is the difference between a structural link and a sentence.
    """
    request = A.from_modification(
        atlas,
        "YAA:MOD:bat1",
        predicate="improves_when_modified_by",
        evidence_type="literature_assertion",
        object_type="product",
        object_id="YAA:PRODUCT:isobutanol",
        span_id="YAA:SPAN:a",
    )
    assert request.evidence[0].publication_id == PUB_A
    result = A.build_assertion(atlas, request, curator=HUMAN, reason="stated in the abstract")
    assert result.level.level == "L5", "a literature assertion alone is a hypothesis"
    assert result.level.basis == "hypothesis_or_insufficient_support"


def test_a_modification_assertion_still_needs_an_object_from_a_curator(
    atlas: sqlite3.Connection,
) -> None:
    """A modification affects *something*, and which something is the entire claim.

    Defaulting the object to isobutanol because this is an isobutanol atlas would file a
    tolerance result or a growth result as a production one.
    """
    request = A.from_modification(
        atlas,
        "YAA:MOD:bat1",
        predicate="improves_when_modified_by",
        evidence_type="literature_assertion",
        object_type="product",
        span_id="YAA:SPAN:a",
    )
    plan = A.plan_assertion(atlas, request)
    assert not plan.ready
    assert "object_id" in _why(plan)


def test_a_bottleneck_that_names_only_a_free_text_node_refuses_to_guess_its_subject(
    atlas: sqlite3.Connection,
) -> None:
    """All four bottlenecks in the atlas today are in exactly this state.

    'pyruvate node' is prose. `assertion.subject_id` is a typed reference into one of eleven
    tables, and mapping a phrase to the nearest reaction is the guess CONVENTIONS.md forbids in
    its identifier rules. A curator says which reaction, metabolite or gene group it means.
    """
    request = A.from_bottleneck(
        atlas,
        "YAA:BNK:pyruvate",
        predicate="is_bottleneck_for",
        evidence_type="literature_assertion",
        object_type="product",
        object_id="YAA:PRODUCT:isobutanol",
        publication_id=PUB_A,
        span_id="YAA:SPAN:a",
    )
    plan = A.plan_assertion(atlas, request)
    assert not plan.ready
    assert "subject_id" in _why(plan)


def test_naming_the_reaction_lets_the_bottleneck_become_an_assertion_and_links_the_two(
    atlas: sqlite3.Connection,
) -> None:
    """`bottleneck.assertion_id` is what makes a bottleneck "an assertion with a required shape".

    PLAN.md G.8 exists so a bottleneck cannot be recorded as a vague opinion. Leaving the link
    NULL would keep the shaped row and the statement as two unconnected things.
    """
    request = A.from_bottleneck(
        atlas,
        "YAA:BNK:pyruvate",
        predicate="is_bottleneck_for",
        evidence_type="literature_assertion",
        object_type="product",
        object_id="YAA:PRODUCT:isobutanol",
        subject_type="reaction",
        subject_id="YAA:RXN:ahas",
        publication_id=PUB_A,
        span_id="YAA:SPAN:a",
    )
    result = A.build_assertion(atlas, request, curator=HUMAN, reason="the authors state it")
    linked = atlas.execute(
        "SELECT assertion_id FROM bottleneck WHERE id = 'YAA:BNK:pyruvate'"
    ).fetchone()["assertion_id"]
    assert linked == result.assertion_id
    assert result.level.level == "L5"


def test_a_bottleneck_row_alone_cannot_produce_direct_evidence(
    atlas: sqlite3.Connection,
) -> None:
    """Asking for L1 from a claim about a paper is refused by naming the fields it cannot have.

    A bottleneck row carries no strain, no control and no measurement, so `direct_perturbation`
    is not a level it can be talked into. The message lists what is absent rather than saying
    "not allowed", because a curator who does have the measurement can then supply it.
    """
    request = A.from_bottleneck(
        atlas,
        "YAA:BNK:pyruvate",
        predicate="is_bottleneck_for",
        evidence_type="direct_perturbation",
        object_type="product",
        object_id="YAA:PRODUCT:isobutanol",
        subject_type="reaction",
        subject_id="YAA:RXN:ahas",
        publication_id=PUB_A,
    )
    plan = A.plan_assertion(atlas, request)
    assert not plan.ready
    for expected in ("strain_id", "measurement_id", "independent_group"):
        assert expected in _why(plan)


# ---------------------------------------------------------------------------------------------
# Batch reporting
# ---------------------------------------------------------------------------------------------


def test_a_batch_plan_reports_every_request_including_the_ones_that_cannot_be_written(
    atlas: sqlite3.Connection,
) -> None:
    """Nothing is skipped silently, for the reason `promote.promote_ready` gives.

    A caller that only saw the ready ones would report a count that is really a filter.
    """
    plans = A.plan_many(
        atlas,
        [_request(), _request(predicate="does_not_exist"), _request(evidence=())],
    )
    assert len(plans) == 3
    assert [plan.ready for plan in plans] == [True, False, False]
    assert all(plan.note for plan in plans)


def test_attaching_evidence_to_an_assertion_that_does_not_exist_says_so(
    atlas: sqlite3.Connection,
) -> None:
    """Evidence points at a statement; there is no such thing as a free-floating evidence item."""
    with pytest.raises(A.NotAssertable) as excinfo:
        A.attach_evidence(atlas, "YAA:ASSERT:nope", _direct(), curator=HUMAN, reason="paper B")
    assert "no assertion" in str(excinfo.value)
