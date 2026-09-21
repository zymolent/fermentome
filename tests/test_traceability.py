"""Tests for `fermdb.query.traceability` -- PLAN.md J.5's walk.

J.5's acceptance test is one sentence: *"a script walks every active assertion and fails if any
one of them cannot produce a complete chain."* Which makes the interesting property of this
module not "does it pass on a good atlas" but **does it fail, by name, on each specific way a
chain can break** -- because a walk that reports a bare FAIL sends a curator to read the database
by hand, and a walk that misses a break kind is worse than no walk at all: CI stays green while
the atlas carries a statement resolving to nothing.

So there is one test per break kind, each built by taking a chain that closes and damaging
exactly one hop:

* `no_evidence` -- a claim nothing supports;
* `dangling_subject` / `dangling_object` -- the polymorphic columns with no foreign key behind
  them, which is the only reason they can dangle at all;
* `evidence_cites_nothing` -- no J.5 source arm to close;
* `dangling_citation` -- a cited row that is not there;
* `span_publication_mismatch` -- the chain that closes cleanly onto the wrong paper, which is the
  break that looks like a pass;
* `no_curation_event` -- a statement that resolves to a source but to nobody.

Rows are written with raw SQL rather than through `curate.assertions`, deliberately. That module
refuses most of these at write time, so building them through it is impossible -- which is the
whole argument for this walk existing: it reads what is stored, not what was written through one
door. `PRAGMA foreign_keys` is dropped for the two tests that need a citation pointing into
space, because that is exactly the state `fermdb.db`'s header warns a forgetful connection
produces.

And the test that is not about a break: :func:`test_zero_assertions_is_not_a_silent_pass`. The
atlas holds zero assertions, so every other test here would pass against an empty database
without the walk having looked at a single row.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import traceability as T

PUB_A = "doi:10.9999/paper-a"
PUB_B = "doi:10.9999/paper-b"
ASSERT = "YAA:ASSERT:fx"
EVIDENCE = "YAA:EV:fx"


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    """An in-memory atlas holding one assertion whose J.5 chain closes end to end.

    Every hop is present: the subject strain and the object product exist, one active
    `direct_perturbation` evidence item cites a measurement and a span, the span belongs to the
    publication the evidence names, and a `curation_event` with a named curator targets the
    assertion. Each test below breaks exactly one of those.
    """
    conn = open_db(IN_MEMORY)
    conn.executescript(
        f"""
        INSERT INTO organism (id, name, zone, evidence, confidence)
            VALUES ('YAA:ORG:scer', 'Saccharomyces cerevisiae', 'R', 'fixture', 'low');
        INSERT INTO product (id, name, zone, evidence, confidence)
            VALUES ('YAA:PRODUCT:ibut', 'isobutanol', 'R', 'fixture', 'low');
        INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence)
            VALUES ('YAA:STRAIN:host', 'YAA:ORG:scer', 'HOST-1', 'engineered', 'R', 'x', 'low'),
                   ('YAA:STRAIN:ctrl', 'YAA:ORG:scer', 'CTRL-1', 'laboratory', 'R', 'x', 'low');
        INSERT INTO publication (id, year, zone, evidence, confidence)
            VALUES ('{PUB_A}', 2019, 'R', 'fixture', 'low'),
                   ('{PUB_B}', 2021, 'R', 'fixture', 'low');
        INSERT INTO span (id, publication_id, char_start, char_end, quoted_text, record_path,
                          zone)
            VALUES ('YAA:SPAN:a', '{PUB_A}', 10, 40, 'the titer reached 1.32 g/L',
                    'measurements[0]', 'R'),
                   ('YAA:SPAN:b', '{PUB_B}', 10, 40, 'we measured 2.10 g/L',
                    'measurements[0]', 'R');
        INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported,
                                 unit_as_reported, source_locator, zone, evidence, confidence)
            VALUES ('YAA:MEAS:a', 'YAA:STRAIN:host', 'titer', 'YAA:PRODUCT:ibut', 1.32,
                    'g/L', 'text', 'R', 'promoted', 'medium');
        INSERT INTO processing_run (id, pipeline, version)
            VALUES ('YAA:RUN:1', 'deseq2', '1.42.0');
        INSERT INTO analysis_result (id, processing_run_id, kind, payload_ref, zone)
            VALUES ('YAA:AR:1', 'YAA:RUN:1', 'differential_expression', 'de/1.parquet', 'R');

        INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, object_id,
                               product_id, direction, created_by_kind, created_by, zone,
                               evidence, confidence)
            VALUES ('{ASSERT}', 'strain', 'YAA:STRAIN:host', 'affects_production_of',
                    'product', 'YAA:PRODUCT:ibut', 'YAA:PRODUCT:ibut', 'increases',
                    'curator', 'kangkon', 'R', 'fixture', 'medium');
        INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, independent_group,
                                   publication_id, span_id, strain_id, control_strain_id,
                                   measurement_id, zone, evidence, confidence)
            VALUES ('{EVIDENCE}', '{ASSERT}', 'direct_perturbation', 'increases', 'lab-1',
                    '{PUB_A}', 'YAA:SPAN:a', 'YAA:STRAIN:host', 'YAA:STRAIN:ctrl',
                    'YAA:MEAS:a', 'R', 'fixture', 'medium');
        INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id,
                                    rationale, created_at, zone)
            VALUES ('YAA:CUEV:1', 'kangkon', 'human', 'create', 'assertion', '{ASSERT}',
                    'read the paper', '2026-09-22T10:00:00+00:00', 'R');
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def _kinds(walk: T.Walk) -> set[str]:
    return {item.kind for chain in walk.chains for item in chain.all_breaks}


def _detail(walk: T.Walk, kind: str) -> str:
    for chain in walk.chains:
        for item in chain.all_breaks:
            if item.kind == kind:
                return f"{item.where}: {item.detail}"
    raise AssertionError(f"no {kind} break in {_kinds(walk)}")


# ------------------------------------------------------------------------------ the chain closes


def test_a_complete_chain_closes_hop_by_hop(atlas: sqlite3.Connection) -> None:
    """The walk resolves every hop J.5 names, and says which arm it closed through."""
    walk = T.walk_assertions(atlas)

    assert walk.n_walked == 1
    assert walk.n_closed == 1
    assert not walk.broken
    assert not walk.is_vacuous
    assert T.exit_code(walk) == T.EXIT_OK

    chain = walk.chains[0]
    assert chain.closes
    assert chain.subject == "strain YAA:STRAIN:host"
    assert chain.object == "product YAA:PRODUCT:ibut"

    (item,) = chain.evidence
    assert item.closes
    assert item.arms == ("literature",)
    # The hops are the deliverable: assertion -> evidence -> the cited rows -> the paper.
    assert item.hops[0] == f"evidence_item {EVIDENCE}"
    assert "measurement YAA:MEAS:a" in item.hops
    assert "span YAA:SPAN:a" in item.hops
    assert f"publication {PUB_A}" in item.hops

    # J.5's third arm: curator, date, rationale.
    ((event, curator, at),) = chain.curation
    assert event == "YAA:CUEV:1"
    assert curator == "kangkon"
    assert at.startswith("2026-09-22")


def test_a_superseded_assertion_is_not_walked(atlas: sqlite3.Connection) -> None:
    """J.5 says *active* assertions. A superseded one is history, not a live claim."""
    atlas.execute("UPDATE assertion SET status = 'superseded' WHERE id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)
    assert walk.n_walked == 0
    assert walk.is_vacuous


def test_the_analysis_arm_closes_and_names_the_hop_it_cannot_walk(
    atlas: sqlite3.Connection,
) -> None:
    """analysis_result -> processing_run resolves; -> dataset -> accession has no column.

    Reported as a gap rather than a break. Failing here would fail every omics-backed assertion
    for a schema gap, and staying silent would let the walk claim a hop it never looked at.
    """
    atlas.execute(
        "INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, publication_id, "
        "analysis_result_id, effect_size, p_adjusted, zone, evidence, confidence) "
        "VALUES ('YAA:EV:omics', ?, 'correlative_omics', 'increases', ?, 'YAA:AR:1', 1.9, 0.01, "
        "'R', 'fixture', 'medium')",
        (ASSERT, PUB_A),
    )
    walk = T.walk_assertions(atlas)

    assert walk.n_closed == 1, _kinds(walk)
    item = next(e for e in walk.chains[0].evidence if e.evidence_id == "YAA:EV:omics")
    assert set(item.arms) == {"analysis", "literature"}
    assert "analysis_result YAA:AR:1" in item.hops
    assert "processing_run YAA:RUN:1" in item.hops

    assert walk.gaps_by_kind() == {"dataset_unreachable": 1}
    assert "dataset" in item.gaps[0].detail
    # A gap does not fail the gate.
    assert T.exit_code(walk) == T.EXIT_OK


# ----------------------------------------------------------------------- one break kind per test


def test_an_assertion_with_no_evidence_breaks_and_says_so(atlas: sqlite3.Connection) -> None:
    atlas.execute("DELETE FROM evidence_item WHERE id = ?", (EVIDENCE,))
    walk = T.walk_assertions(atlas)

    assert _kinds(walk) == {"no_evidence"}
    assert "no `evidence_item` points at this assertion" in _detail(walk, "no_evidence")
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_evidence_that_is_only_superseded_is_not_evidence(atlas: sqlite3.Connection) -> None:
    """The break names the distinction: rows exist, none of them active."""
    atlas.execute("UPDATE evidence_item SET status = 'retracted' WHERE id = ?", (EVIDENCE,))
    walk = T.walk_assertions(atlas)

    assert _kinds(walk) == {"no_evidence"}
    assert "superseded or retracted" in _detail(walk, "no_evidence")


def test_a_dangling_polymorphic_subject_is_caught(atlas: sqlite3.Connection) -> None:
    """`assertion.subject_id` carries no foreign key, so nothing else could have caught it."""
    atlas.execute("UPDATE assertion SET subject_id = 'YAA:STRAIN:ghost' WHERE id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)

    assert "dangling_subject" in _kinds(walk)
    detail = _detail(walk, "dangling_subject")
    assert "YAA:STRAIN:ghost" in detail
    assert "`strain`" in detail
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_dangling_polymorphic_object_is_caught(atlas: sqlite3.Connection) -> None:
    atlas.execute("UPDATE assertion SET object_id = 'YAA:PRODUCT:ghost' WHERE id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)

    assert "dangling_object" in _kinds(walk)
    assert "YAA:PRODUCT:ghost" in _detail(walk, "dangling_object")


def test_evidence_citing_no_source_at_all_breaks(atlas: sqlite3.Connection) -> None:
    """No publication, no analysis_result, no processing_run, no extraction, no span."""
    atlas.execute(
        "UPDATE evidence_item SET publication_id = NULL, span_id = NULL WHERE id = ?", (EVIDENCE,)
    )
    walk = T.walk_assertions(atlas)

    assert _kinds(walk) == {"evidence_cites_nothing"}
    detail = _detail(walk, "evidence_cites_nothing")
    assert EVIDENCE in detail
    # The reason a measurement cannot stand in for the citation is part of the message.
    assert "`measurement` has no publication column" in detail
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_span_alone_still_closes_the_literature_arm(atlas: sqlite3.Connection) -> None:
    """A span reaches a paper of its own, so this is not "cites nothing".

    The arms decide, not the column list. Reporting a break here would be a break the atlas does
    not have.
    """
    atlas.execute("UPDATE evidence_item SET publication_id = NULL WHERE id = ?", (EVIDENCE,))
    walk = T.walk_assertions(atlas)

    assert not walk.broken, _kinds(walk)
    (item,) = walk.chains[0].evidence
    assert item.arms == ("literature",)
    assert f"publication {PUB_A}" in item.hops


def test_evidence_citing_a_row_that_does_not_exist_names_the_column_and_the_table(
    atlas: sqlite3.Connection,
) -> None:
    """A citation pointing into space.

    Written with foreign keys off, which is the state `fermdb.db`'s header warns about: the
    pragma is per-connection, and a connection that forgot it accepts orphan rows silently.
    """
    atlas.execute("PRAGMA foreign_keys = OFF")
    atlas.execute(
        "UPDATE evidence_item SET measurement_id = 'YAA:MEAS:ghost' WHERE id = ?", (EVIDENCE,)
    )
    walk = T.walk_assertions(atlas)

    assert "dangling_citation" in _kinds(walk)
    detail = _detail(walk, "dangling_citation")
    assert "measurement_id" in detail
    assert "YAA:MEAS:ghost" in detail
    assert "`measurement`" in detail
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_deleted_publication_leaves_the_span_arm_dangling(atlas: sqlite3.Connection) -> None:
    """The paper goes; the span that pointed at it stays. Only a walk of stored rows sees this."""
    atlas.execute("PRAGMA foreign_keys = OFF")
    atlas.execute("DELETE FROM publication WHERE id = ?", (PUB_A,))
    walk = T.walk_assertions(atlas)

    assert "dangling_citation" in _kinds(walk)
    assert not walk.chains[0].evidence[0].arms
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_span_belonging_to_another_publication_is_the_break_that_looks_like_a_pass(
    atlas: sqlite3.Connection,
) -> None:
    """Every row resolves; the chain still points at the wrong sentence."""
    atlas.execute("UPDATE evidence_item SET span_id = 'YAA:SPAN:b' WHERE id = ?", (EVIDENCE,))
    walk = T.walk_assertions(atlas)

    assert "span_publication_mismatch" in _kinds(walk)
    detail = _detail(walk, "span_publication_mismatch")
    assert PUB_B in detail and PUB_A in detail
    assert "worse than one that does not resolve" in detail
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_an_extraction_of_a_different_paper_is_caught_the_same_way(
    atlas: sqlite3.Connection,
) -> None:
    atlas.executescript(
        f"""
        INSERT INTO extraction (id, publication_id, extractor, extractor_version, zone)
            VALUES ('YAA:EXT:b', '{PUB_B}', 'harness', '1.0', 'I');
        UPDATE evidence_item SET extraction_id = 'YAA:EXT:b' WHERE id = '{EVIDENCE}';
        """
    )
    walk = T.walk_assertions(atlas)

    assert "extraction_publication_mismatch" in _kinds(walk)
    assert PUB_B in _detail(walk, "extraction_publication_mismatch")


def test_an_assertion_with_no_curation_event_resolves_to_nobody(
    atlas: sqlite3.Connection,
) -> None:
    """J.5's third arm. A claim sourced to a paper but to no curator is PLAN.md L.5's failure."""
    atlas.execute("DELETE FROM curation_event WHERE target_id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)

    assert _kinds(walk) == {"no_curation_event"}
    assert "no curator, no date and no rationale" in _detail(walk, "no_curation_event")
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_curation_event_naming_nobody_is_a_judgement_made_by_nobody(
    atlas: sqlite3.Connection,
) -> None:
    atlas.execute("UPDATE curation_event SET curator = '  ' WHERE target_id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)

    assert _kinds(walk) == {"curation_event_unnamed"}
    assert T.exit_code(walk) == T.EXIT_BROKEN


def test_a_curation_event_for_a_different_assertion_does_not_count(
    atlas: sqlite3.Connection,
) -> None:
    """The event has to target *this* assertion, not merely exist somewhere in the log."""
    atlas.execute(
        "UPDATE curation_event SET target_id = 'YAA:ASSERT:other' WHERE target_id = ?", (ASSERT,)
    )
    walk = T.walk_assertions(atlas)
    assert _kinds(walk) == {"no_curation_event"}


# ---------------------------------------------------------------------------- reporting the walk


def test_every_break_kind_is_in_the_closed_list_and_carries_a_reason() -> None:
    """A break kind is what a curator greps for; an invented string would make that useless."""
    for kind in (*T.BREAK_KINDS, *T.GAP_KINDS):
        assert kind in T.WHY_IT_MATTERS
        assert len(T.WHY_IT_MATTERS[kind]) > 40


def test_breaks_are_counted_by_kind_across_assertions(atlas: sqlite3.Connection) -> None:
    """Two assertions broken two different ways, reported as two named kinds."""
    atlas.executescript(
        f"""
        INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, object_id,
                               created_by_kind, created_by, zone, evidence, confidence)
            VALUES ('YAA:ASSERT:second', 'strain', 'YAA:STRAIN:ghost', 'affects_production_of',
                    'product', 'YAA:PRODUCT:ibut', 'curator', 'kangkon', 'R', 'fx', 'medium');
        DELETE FROM curation_event WHERE target_id = '{ASSERT}';
        """
    )
    walk = T.walk_assertions(atlas)

    assert walk.n_walked == 2
    assert len(walk.broken) == 2
    counts = walk.breaks_by_kind()
    assert counts["no_curation_event"] == 2
    assert counts["dangling_subject"] == 1
    assert counts["no_evidence"] == 1


def test_a_named_assertion_can_be_walked_on_its_own(atlas: sqlite3.Connection) -> None:
    walk = T.walk_assertions(atlas, assertion_ids=[ASSERT])
    assert walk.n_walked == 1
    assert T.walk_assertions(atlas, assertion_ids=["YAA:ASSERT:nope"]).is_vacuous


def test_the_json_payload_carries_the_breaks_and_their_reasons(
    atlas: sqlite3.Connection,
) -> None:
    atlas.execute("DELETE FROM curation_event WHERE target_id = ?", (ASSERT,))
    payload = T.walk_assertions(atlas).as_json()

    assert payload["n_walked"] == 1
    assert payload["n_broken"] == 1
    assert payload["vacuous"] is False
    assert payload["breaks_by_kind"] == {"no_curation_event": 1}
    (assertion,) = payload["assertions"]
    assert assertion["closes"] is False
    (item,) = assertion["breaks"]
    assert item["kind"] == "no_curation_event"
    assert item["why"]


# ------------------------------------------------------------------------- the vacuous walk


def test_zero_assertions_is_not_a_silent_pass(atlas: sqlite3.Connection) -> None:
    """The trap this check exists inside.

    The atlas holds zero assertions, so a walk that folded "nothing to check" into success would
    be wired into CI as a green tick that has verified nothing -- and would be trusted exactly as
    much as one that verified something. It gets its own outcome and its own exit code.
    """
    atlas.executescript("DELETE FROM evidence_item; DELETE FROM assertion;")
    walk = T.walk_assertions(atlas)

    assert walk.n_walked == 0
    assert walk.is_vacuous
    assert not walk.broken
    assert walk.n_closed == 0

    assert T.exit_code(walk) == T.EXIT_VACUOUS
    assert T.EXIT_VACUOUS not in (T.EXIT_OK, T.EXIT_BROKEN)
    # Distinguishable from both a pass and a failure, which is the whole point.
    assert T.exit_code(walk, allow_empty=True) == T.EXIT_OK


def test_allow_empty_does_not_forgive_a_broken_chain(atlas: sqlite3.Connection) -> None:
    """The flag excuses an empty atlas, never a bad one. One is 'not yet'; the other is a bug."""
    atlas.execute("DELETE FROM curation_event WHERE target_id = ?", (ASSERT,))
    walk = T.walk_assertions(atlas)
    assert T.exit_code(walk, allow_empty=True) == T.EXIT_BROKEN


def test_the_vacuous_payload_says_vacuous_rather_than_reporting_nothing(
    atlas: sqlite3.Connection,
) -> None:
    atlas.executescript("DELETE FROM evidence_item; DELETE FROM assertion;")
    payload = T.walk_assertions(atlas).as_json()

    assert payload["vacuous"] is True
    assert payload["n_walked"] == 0
    assert payload["assertions"] == []


# ------------------------------------------------------------------------------- the CI gate


def test_the_cli_is_wired_so_ci_can_gate_on_it() -> None:
    """CI runs this exact command line; the parser has to accept it and route it."""
    from fermdb.cli import build_parser
    from fermdb.query.cli import cmd_query_traceability

    args = build_parser().parse_args(["query", "traceability", "--allow-empty"])
    assert args.func is cmd_query_traceability
    assert args.allow_empty is True
    assert args.assertion == []
    assert args.verbose is False
    assert args.json is False

    plain = build_parser().parse_args(["query", "traceability"])
    assert plain.allow_empty is False


def test_the_phase_zero_fixture_resolves_a_complete_chain() -> None:
    """What the walk finds against `tests/fixtures/mini_atlas/`, pinned exactly.

    **What changed.** This test used to be called
    `test_the_phase_zero_fixture_does_not_yet_resolve_a_complete_chain` and pinned the opposite
    result -- 4 assertions walked, 0 closed, `{"no_curation_event": 4,
    "evidence_cites_nothing": 1}` -- written so that it would fail the day the fixture was fixed.
    That day is this one, and the old name now states a falsehood, so the assertions and the name
    both move to the new contract. Two things were wrong and both are repaired:

    * `curation_event` was absent from `TABLE_ORDER` in `src/fermdb/db/fixture.py`, so no
      `curation_event.yaml` could ever have loaded and all four assertions resolved to nobody.
      The table is now last in that tuple (it declares no foreign key -- `target_id` is
      polymorphic -- so "after everything it can reference" is the end of the list), and
      `curation_event.yaml` carries one event per assertion with a named curator, a timestamp and
      a rationale.
    * `YAA:EV:fx-l5` was an `ai_inference` naming a model, a version and a prompt version and no
      source at all: storable, because `evidence_item`'s per-type CHECK asks an `ai_inference` for
      no citation, and resolving to nothing. It now names the publication the model was shown.
      The alternative -- keeping it broken as the fixture's worked example of a chain that does
      not close -- was rejected: the worked examples of every break kind are the tests above this
      one, each built by damaging exactly one hop of a chain that closes, which is strictly more
      informative than one permanently red row; and a fixture carrying a known break cannot be
      the CI gate, which is what `.github/workflows/ci.yml` now makes it.

    PLAN.md Q's phase-0 acceptance -- *"an assertion resolves a complete J.5 chain"* -- holds for
    the first time, and here holds in its stronger form: **every** assertion in the fixture does.
    """
    from pathlib import Path

    from fermdb.db.fixture import load_fixture

    conn = open_db(IN_MEMORY)
    try:
        load_fixture(conn, Path(__file__).resolve().parents[0] / "fixtures" / "mini_atlas")
        walk = T.walk_assertions(conn)
        rationales = {
            row["target_id"]: row["rationale"]
            for row in conn.execute(
                "SELECT target_id, rationale FROM curation_event WHERE target_type = 'assertion'"
            )
        }
    finally:
        conn.close()

    assert walk.n_walked == 4
    assert walk.n_closed == 4
    assert not walk.broken, walk.breaks_by_kind()
    assert not walk.is_vacuous
    assert walk.breaks_by_kind() == {}
    assert T.exit_code(walk) == T.EXIT_OK

    for chain in walk.chains:
        # Every one closes a source arm ...
        assert chain.closes
        assert all(item.arms for item in chain.evidence)
        # ... and J.5's third arm resolves to a name, a date and a reason, not just to a row.
        ((_, curator, at),) = chain.curation
        assert curator.strip()
        assert at.startswith("2026-09-19")
        assert rationales[chain.assertion_id].strip()

    # The two that were broken, named: fx-l1 was only ever missing its curator, fx-l5 was missing
    # both its curator and any source whatsoever.
    l1 = next(c for c in walk.chains if c.assertion_id == "YAA:ASSERT:fx-l1")
    assert l1.evidence[0].arms == ("literature",)

    l5 = next(c for c in walk.chains if c.assertion_id == "YAA:ASSERT:fx-l5")
    (item,) = l5.evidence
    assert item.evidence_type == "ai_inference"
    assert item.arms == ("literature",)
    assert "publication doi:10.9999/fixture-a" in item.hops
    # Proposed by the model, not accepted by a human: the event records the act that happened.
    assert l5.curation[0][1] == "fixture-fake-model@v0 (synthetic)"


def test_the_ci_workflow_gates_on_the_fixture_walk() -> None:
    """The check J.5 specifies has to *run in CI*, and has to be able to go red.

    Asserted against the workflow file rather than assumed: a walk nothing invokes is a module,
    not a gate, and a gate that cannot fail is a green tick asserting nothing. The workflow used
    to gate on an empty temp atlas with `--allow-empty` -- vacuous by construction -- while the
    fixture walk ran under `continue-on-error`. Now the fixture walk is the gate, so this test
    fails if someone drops the step or makes it non-gating again.
    """
    from pathlib import Path

    import yaml

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "query traceability" in text
    # The vacuous exemption must stay visible in the file rather than hide in the code -- and it
    # is now attached to the step that *asserts* an empty atlas exits 3, not to the gate.
    assert "--allow-empty" in text
    assert "EXIT_VACUOUS=3" in text

    # Parsed, not grepped: `continue-on-error` is the key that would make the gate toothless, and
    # a substring search for it hits the comment explaining why it was removed.
    steps = yaml.safe_load(text)["jobs"]["test"]["steps"]
    walking = [step for step in steps if "query traceability" in step.get("run", "")]
    assert len(walking) == 2, [step.get("name") for step in steps]
    assert not any(step.get("continue-on-error") for step in walking)

    # The gate is the one that loads the fixture, and it carries no `--allow-empty`: four closed
    # chains cannot be vacuous, so an emptied fixture must exit 3 and go red.
    (gate,) = [step for step in walking if "mini_atlas" in step["run"]]
    assert "--allow-empty" not in gate["run"]
