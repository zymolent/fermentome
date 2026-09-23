"""Tests for `fermdb.curate.modifications` and I.4's `is_isolated_effect`.

The property under test is mostly a refusal. A single-gene assertion is the most valuable thing
this atlas can produce and the easiest thing to produce wrongly, so the tests below are weighted
towards the two inferences the module must not make: deriving isolation from a row count, and
repairing a claim it finds suspicious.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

import pytest

from fermdb.curate.modifications import (
    ISOLATION_DETECTOR,
    NOT_RECORDED,
    RECORDED_COMBINATION,
    RECORDED_ISOLATED,
    as_quality_flags,
    describe_isolation,
    isolation_conflicts,
    persist_conflicts,
)
from fermdb.curate.promote import _plan_modification
from fermdb.curate.queue import Task
from fermdb.db import IN_MEMORY, open_db

STRAIN = "YAA:STRAIN:test-host"
PUB = "doi:10.0000/test"


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    connection.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 'R', 'test', 'high')"
    )
    connection.execute(
        "INSERT INTO strain (id, canonical_name, organism_id, zone, evidence, confidence) "
        "VALUES (?, 'test host', 'YAA:ORG:sc', 'R', 'test', 'high')",
        (STRAIN,),
    )
    connection.execute(
        "INSERT INTO publication (id, title, zone, evidence, confidence) "
        "VALUES (?, 'a paper', 'R', 'test', 'high')",
        (PUB,),
    )
    connection.commit()
    yield connection
    connection.close()


def _modification(
    conn: sqlite3.Connection,
    modification_id: str,
    *,
    isolated: int | None = None,
    strain_id: str | None = STRAIN,
    intent: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO modification (id, strain_id, type, target_locus, publication_id, "
        "is_isolated_effect, intent, zone, evidence, confidence) "
        "VALUES (?,?,'deletion','PDC1',?,?,?,'R','test','high')",
        (modification_id, strain_id, PUB, isolated, intent),
    )
    conn.commit()


# ------------------------------------------------------------------------- the three states


def test_the_column_carries_three_states_and_the_third_is_not_a_no(
    conn: sqlite3.Connection,
) -> None:
    _modification(conn, "YAA:MOD:alone", isolated=1)
    _modification(conn, "YAA:MOD:with-others", isolated=0)
    _modification(conn, "YAA:MOD:silent")
    assert describe_isolation(conn, "YAA:MOD:alone") == RECORDED_ISOLATED
    assert describe_isolation(conn, "YAA:MOD:with-others") == RECORDED_COMBINATION
    assert describe_isolation(conn, "YAA:MOD:silent") == NOT_RECORDED


def test_a_lone_modification_row_is_still_not_recorded(conn: sqlite3.Connection) -> None:
    """The refusal the module exists for.

    This strain has exactly one modification in the atlas, which is the shape that tempts the
    derivation. 10 modifications against 109 strains means nearly every strain looks like this,
    so deriving isolation here would manufacture single-gene assertions wholesale.
    """
    _modification(conn, "YAA:MOD:only-one")
    assert describe_isolation(conn, "YAA:MOD:only-one") == NOT_RECORDED


def test_an_unknown_modification_is_not_recorded_rather_than_an_error(
    conn: sqlite3.Connection,
) -> None:
    assert describe_isolation(conn, "YAA:MOD:nonexistent") == NOT_RECORDED


def test_the_schema_refuses_a_value_that_is_neither_yes_nor_no(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _modification(conn, "YAA:MOD:bad", isolated=2)


def test_the_schema_refuses_an_intent_outside_i4s_vocabulary(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _modification(conn, "YAA:MOD:bad-intent", intent="make_it_better")


# ----------------------------------------------------------------------------- the conflict


def test_a_claim_of_isolation_against_a_multi_change_strain_is_reported(
    conn: sqlite3.Connection,
) -> None:
    _modification(conn, "YAA:MOD:a", isolated=1)
    _modification(conn, "YAA:MOD:b")
    (conflict,) = isolation_conflicts(conn)
    assert conflict.modification_id == "YAA:MOD:a"
    assert conflict.sibling_ids == ("YAA:MOD:a", "YAA:MOD:b")
    assert "YAA:MOD:b" in conflict.rationale
    assert PUB in conflict.rationale


def test_nothing_is_repaired_by_reporting_it(conn: sqlite3.Connection) -> None:
    """The second refusal: the flag records the disagreement and never resolves it."""
    _modification(conn, "YAA:MOD:a", isolated=1)
    _modification(conn, "YAA:MOD:b")
    isolation_conflicts(conn)
    persist_conflicts(conn, raised_by="tester")
    assert describe_isolation(conn, "YAA:MOD:a") == RECORDED_ISOLATED
    assert describe_isolation(conn, "YAA:MOD:b") == NOT_RECORDED


def test_an_honest_isolated_claim_raises_nothing(conn: sqlite3.Connection) -> None:
    _modification(conn, "YAA:MOD:a", isolated=1)
    assert isolation_conflicts(conn) == ()


def test_a_combination_claim_raises_nothing_however_many_siblings(
    conn: sqlite3.Connection,
) -> None:
    """Two changes recorded as a combination is a correctly described combination strain."""
    _modification(conn, "YAA:MOD:a", isolated=0)
    _modification(conn, "YAA:MOD:b", isolated=0)
    assert isolation_conflicts(conn) == ()


def test_a_modification_with_no_strain_cannot_conflict(conn: sqlite3.Connection) -> None:
    _modification(conn, "YAA:MOD:orphan", isolated=1, strain_id=None)
    assert isolation_conflicts(conn) == ()


# ------------------------------------------------------------------------------ the flag it raises


def test_the_flag_targets_the_strain_and_only_warns(conn: sqlite3.Connection) -> None:
    """Confounding is a property of the set, and a bookkeeping dispute must not delete data."""
    _modification(conn, "YAA:MOD:a", isolated=1)
    _modification(conn, "YAA:MOD:b")
    (flag,) = as_quality_flags(isolation_conflicts(conn))
    assert flag.target_type == "strain"
    assert flag.target_id == STRAIN
    assert flag.kind == "confounded_measurement"
    assert flag.severity == "warn"
    assert flag.detector == ISOLATION_DETECTOR


def test_persisting_writes_one_row_a_curator_can_act_on(conn: sqlite3.Connection) -> None:
    _modification(conn, "YAA:MOD:a", isolated=1)
    _modification(conn, "YAA:MOD:b")
    assert persist_conflicts(conn, raised_by="tester") == (1, 0)
    row = conn.execute(
        "SELECT target_type, kind, severity, status FROM data_quality_flag WHERE target_id = ?",
        (STRAIN,),
    ).fetchone()
    assert tuple(row) == ("strain", "confounded_measurement", "warn", "active")


def test_a_rerun_updates_rather_than_stacking(conn: sqlite3.Connection) -> None:
    _modification(conn, "YAA:MOD:a", isolated=1)
    _modification(conn, "YAA:MOD:b")
    persist_conflicts(conn, raised_by="tester")
    persist_conflicts(conn, raised_by="tester")
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM data_quality_flag WHERE detector = ?", (ISOLATION_DETECTOR,)
    ).fetchone()
    assert count == 1


# ------------------------------------------------------------- the promoter carries the answer


def _task(payload: dict[str, object]) -> Task:
    """A minimal accepted task, built directly rather than through the queue.

    The property under test is what `_plan_modification` does with `supplied`, and routing a task
    through enqueue/claim/accept to reach it would test the queue instead.
    """
    return Task(
        id="YAA:CTASK:0000000000000001",
        extraction_id="YAA:EXTR:0000000000000001",
        publication_id=PUB,
        record_path="modifications[0]",
        record_kind="modifications",
        payload_json=json.dumps(payload),
        status="accepted",
        priority=0,
        claimed_by=None,
        claimed_at=None,
        lease_expires_at=None,
        attempt_count=0,
        curator="tester",
        curator_kind="human",
        resolved_at=None,
        resolution_reason=None,
        edited_payload_json=None,
        proposal_hash="0" * 32,
        repeat_of=None,
        created_at="2026-09-24T00:00:00+00:00",
    )


_PAYLOAD: dict[str, object] = {
    "modification_type": "deletion",
    "target_as_reported": "PDC1",
    "strain_name_as_reported": "test host",
}


def test_a_curators_no_is_not_dropped_on_the_way_to_the_row(conn: sqlite3.Connection) -> None:
    """The falsy-zero trap, tested because it is invisible once it happens.

    `supplied` is built by a dict comprehension that filters on truthiness, so a 0 would vanish
    and the column would read NULL -- turning a curator's recorded "made in combination" into
    "not recorded", which is the one direction I.4 cannot afford to lose.
    """
    plan = _plan_modification(conn, _task(_PAYLOAD), {"is_isolated_effect": "no"})
    assert plan.row["is_isolated_effect"] == 0


def test_a_curators_yes_reaches_the_row(conn: sqlite3.Connection) -> None:
    plan = _plan_modification(conn, _task(_PAYLOAD), {"is_isolated_effect": "yes"})
    assert plan.row["is_isolated_effect"] == 1


def test_saying_nothing_leaves_it_not_recorded(conn: sqlite3.Connection) -> None:
    plan = _plan_modification(conn, _task(_PAYLOAD), {})
    assert plan.row["is_isolated_effect"] is None
    assert plan.row["intent"] is None
