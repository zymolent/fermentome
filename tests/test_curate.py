"""Tests for `fermdb.curate.queue` — the leased, parallel, never-deleting curation queue.

Four things this file pins down, in order of how much damage their absence would do.

**No agent promotes its own proposal** (PLAN.md L.5). Tested three times, because it is enforced
three times: an agent curator is refused, a "human" curator whose name is the model that made the
proposal is refused, and the database refuses the row regardless. Any one of those alone is a
convention; all three is a rule.

**Rejections are retained.** A rejected task stays, a re-proposal of the same claim is linked back
to it, and `repeat_offenders` reports the pair. There is also a test that asserts this module
contains no delete at all — if that ever stops being true, the signal disappears silently and
`repeat_offenders` starts returning good news.

**Two workers never get the same task.** The claim is a compare-and-swap, so the test drives it
from two real connections to the same database file rather than trusting the single-threaded
happy path.

**A lease expires.** A worker that dies must not strand its task, and the reclaim must be visible
in `attempt_count` rather than silent.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fermdb.curate import (
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    CurationError,
    Curator,
    LeaseLost,
    PromotionRefused,
    accept,
    claim_next,
    edit,
    enqueue_extraction,
    enqueue_pending_extractions,
    get_task,
    heartbeat,
    peek,
    proposal_hash,
    queue_stats,
    reject,
    release,
    repeat_offenders,
)
from fermdb.db import IN_MEMORY, open_db

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_SOURCE = REPO_ROOT / "src" / "fermdb" / "curate" / "queue.py"

PUBLICATION_ID = "pmid:11112222"
MODEL = "qwen3.6:27b"
T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def payload_with(measurements: int = 2, strains: int = 1) -> dict[str, Any]:
    """A stored-shape payload: validated records, document offsets, provenance already forced."""
    return {
        "strains": [
            {
                "name_as_reported": f"IBA-{index}",
                "role": "engineered",
                "span": {"quote": f"IBA-{index}", "char_start": index, "char_end": index + 5},
                "confidence": "unverified",
                "zone": "I",
                "review_state": "proposed",
            }
            for index in range(strains)
        ],
        "modifications": [],
        "pathway_configurations": [],
        "measurements": [
            {
                "product_id": "YAA:PRODUCT:isobutanol",
                "product_as_reported": "isobutanol",
                "quantity_kind": "titer",
                "value": 20.0 + index,
                "unit": "g/L",
                "source_locator": "text",
                "span": {
                    "quote": f"{20.0 + index} g/L",
                    "char_start": 100 + index,
                    "char_end": 110 + index,
                },
                "confidence": "unverified",
                "zone": "I",
                "review_state": "proposed",
            }
            for index in range(measurements)
        ],
        "conditions": [],
        "bottlenecks": [],
        "co_reported_higher_alcohols": [],
        "self_confidence": "medium",
    }


def seed(
    conn: sqlite3.Connection,
    *,
    extraction_id: str = "YAA:EXTR:one",
    payload: dict[str, Any] | None = None,
    model: str = MODEL,
) -> str:
    """One publication and one proposed extraction, the state extraction leaves behind."""
    conn.execute(
        "INSERT OR IGNORE INTO publication (id, pmid, title, zone, evidence, confidence) "
        "VALUES (?, '11112222', 'Test paper', 'R', 'test fixture', 'unverified')",
        (PUBLICATION_ID,),
    )
    conn.execute(
        "INSERT INTO extraction (id, publication_id, section, extractor, extractor_version, "
        "model, model_version, prompt_version, payload, review_state, created_at, zone) "
        "VALUES (?, ?, 'methods,results', 'fermdb.extract.harness', '1', ?, ?, "
        "'extraction/v1+abc', ?, 'proposed', '2026-09-20T12:00:00+00:00', 'I')",
        (
            extraction_id,
            PUBLICATION_ID,
            model,
            f"{model}@deadbeef",
            json.dumps(payload if payload is not None else payload_with(), sort_keys=True),
        ),
    )
    conn.commit()
    return extraction_id


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def shared_db(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    """Two independent connections to one database file — two concurrent workers."""
    path = tmp_path / "atlas.sqlite3"
    first = open_db(path)
    second = open_db(path)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


# ----------------------------------------------------------------------------------- enqueueing


def test_one_task_per_proposed_record(conn: sqlite3.Connection) -> None:
    """Not one per extraction: a curator must be able to reject one record without the rest."""
    extraction_id = seed(conn)
    created = enqueue_extraction(conn, extraction_id, now=T0)
    assert len(created) == 3  # one strain + two measurements
    paths = {task.record_path for task in peek(conn, limit=10, now=T0)}
    assert paths == {"strains[0]", "measurements[0]", "measurements[1]"}


def test_enqueueing_twice_creates_nothing_new(conn: sqlite3.Connection) -> None:
    """The background scanner runs on its own schedule and may pass over the same row twice."""
    extraction_id = seed(conn)
    assert len(enqueue_extraction(conn, extraction_id, now=T0)) == 3
    assert enqueue_extraction(conn, extraction_id, now=T0) == ()
    assert conn.execute("SELECT COUNT(*) FROM curation_task").fetchone()[0] == 3


def test_the_scanner_picks_up_extractions_that_have_no_tasks(conn: sqlite3.Connection) -> None:
    seed(conn, extraction_id="YAA:EXTR:a")
    seed(conn, extraction_id="YAA:EXTR:b")
    created = enqueue_pending_extractions(conn, now=T0)
    assert len(created) == 6
    assert enqueue_pending_extractions(conn, now=T0) == ()


def test_a_reviewed_extraction_is_not_requeued(conn: sqlite3.Connection) -> None:
    extraction_id = seed(conn)
    conn.execute(
        "UPDATE extraction SET review_state = 'accepted', curator = 'someone', "
        "reviewed_at = ?, review_reason = 'done' WHERE id = ?",
        ("2026-09-20T13:00:00+00:00", extraction_id),
    )
    conn.commit()
    with pytest.raises(CurationError):
        enqueue_extraction(conn, extraction_id, now=T0)


def test_the_task_carries_the_record_it_is_about(conn: sqlite3.Connection) -> None:
    extraction_id = seed(conn)
    enqueue_extraction(conn, extraction_id, now=T0)
    task = next(t for t in peek(conn, limit=10, now=T0) if t.record_path == "measurements[0]")
    assert task.record["value"] == 20.0
    assert task.record["confidence"] == "unverified"
    assert task.record_kind == "measurements"


# ------------------------------------------------------------------------------------- claiming


def test_claiming_leases_a_task_to_one_worker(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-1", now=T0)
    assert task is not None
    assert task.status == "in_progress"
    assert task.claimed_by == "worker-1"
    assert task.attempt_count == 1
    assert task.lease_expires_at is not None and task.lease_expires_at > task.claimed_at


def test_peeking_does_not_claim(conn: sqlite3.Connection) -> None:
    """A curator checking how much is left has not started work on any of it."""
    enqueue_extraction(conn, seed(conn), now=T0)
    peek(conn, limit=5, now=T0)
    assert all(task.status == "pending" for task in peek(conn, limit=5, now=T0))


def test_two_connections_never_get_the_same_task(
    shared_db: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """The compare-and-swap, exercised the way it will actually be used."""
    first, second = shared_db
    enqueue_extraction(first, seed(first), now=T0)

    claimed_a = claim_next(first, worker_id="worker-a", now=T0)
    claimed_b = claim_next(second, worker_id="worker-b", now=T0)
    claimed_c = claim_next(first, worker_id="worker-c", now=T0)
    claimed_d = claim_next(second, worker_id="worker-d", now=T0)

    taken = [task for task in (claimed_a, claimed_b, claimed_c) if task is not None]
    assert len({task.id for task in taken}) == 3
    assert claimed_d is None  # three tasks, three workers, nothing left


def test_an_expired_lease_is_reclaimable_and_the_attempt_is_counted(
    conn: sqlite3.Connection,
) -> None:
    """A worker that dies must not strand its task, and the reclaim must be visible."""
    enqueue_extraction(conn, seed(conn), now=T0)
    first = claim_next(conn, worker_id="worker-dead", lease_seconds=60, now=T0)
    assert first is not None

    later = T0 + timedelta(seconds=120)
    second = claim_next(conn, worker_id="worker-live", now=later)
    assert second is not None and second.id == first.id
    assert second.claimed_by == "worker-live"
    assert second.attempt_count == 2


def test_a_live_lease_is_not_stolen(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn, payload=payload_with(measurements=0, strains=1)), now=T0)
    held = claim_next(conn, worker_id="worker-a", lease_seconds=600, now=T0)
    assert held is not None
    assert claim_next(conn, worker_id="worker-b", now=T0 + timedelta(seconds=60)) is None


def test_heartbeat_extends_a_held_lease(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", lease_seconds=60, now=T0)
    assert task is not None
    extended = heartbeat(
        conn, task.id, worker_id="worker-a", lease_seconds=600, now=T0 + timedelta(seconds=30)
    )
    assert extended > (task.lease_expires_at or "")


def test_heartbeat_from_the_wrong_worker_is_refused(conn: sqlite3.Connection) -> None:
    """Pretending the lease is still held is how two curators review the same record."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(LeaseLost):
        heartbeat(conn, task.id, worker_id="worker-b", now=T0)


def test_release_returns_a_task_to_the_queue(conn: sqlite3.Connection) -> None:
    """What a background agent does with almost everything it claims: hand it to a human."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    released = release(conn, task.id, worker_id="worker-a", reason="needs a human", now=T0)
    assert released.status == "pending"
    assert released.claimed_by is None
    assert _events(conn, task.id, "release")


def test_release_needs_a_reason(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(CurationError):
        release(conn, task.id, worker_id="worker-a", reason="  ", now=T0)


# ------------------------------------------------------------------ the rule: only humans decide


def _events(conn: sqlite3.Connection, task_id: str, action: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM curation_event WHERE target_type = 'curation_task' AND target_id = ? "
        "AND action = ?",
        (task_id, action),
    ).fetchall()


def test_an_agent_may_not_accept(conn: sqlite3.Connection) -> None:
    """PLAN.md L.5, first line of defence: the actor says what it is and is refused."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(PromotionRefused) as excinfo:
        accept(conn, task.id, curator=Curator("worker-a", kind="agent"), reason="looks fine")
    assert "L.5" in str(excinfo.value)
    assert get_task(conn, task.id).status == "in_progress"


def test_an_agent_may_not_reject_either(conn: sqlite3.Connection) -> None:
    """An automated rejection would bury the model's own output where nobody sees it."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(PromotionRefused):
        reject(conn, task.id, curator=Curator("worker-a", kind="agent"), reason="looks wrong")


def test_the_model_cannot_review_itself_even_calling_itself_human(
    conn: sqlite3.Connection,
) -> None:
    """Second line of defence: the name is checked against what produced the proposal."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(PromotionRefused) as excinfo:
        accept(conn, task.id, curator=Curator(MODEL, kind="human"), reason="I am sure")
    assert "cannot review itself" in str(excinfo.value)


def test_the_extractor_cannot_review_itself(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    with pytest.raises(PromotionRefused):
        accept(
            conn,
            task.id,
            curator=Curator("fermdb.extract.harness", kind="human"),
            reason="fine",
        )


def test_the_database_refuses_an_agent_accept_event(conn: sqlite3.Connection) -> None:
    """Third line of defence, below Python entirely."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, "
            "target_id, rationale, zone) VALUES ('YAA:CUEV:x', 'bot', 'agent', 'accept', "
            "'curation_task', 'YAA:CTASK:x', 'because', 'R')"
        )


def test_the_database_refuses_a_resolution_with_no_curator(conn: sqlite3.Connection) -> None:
    extraction_id = seed(conn)
    enqueue_extraction(conn, extraction_id, now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE curation_task SET status = 'accepted' WHERE id = ?", (task_id,))


def test_the_database_refuses_an_agent_resolution(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE curation_task SET status = 'accepted', curator = 'bot', "
            "curator_kind = 'agent', resolved_at = ?, resolution_reason = 'fine' WHERE id = ?",
            ("2026-09-20T13:00:00+00:00", task_id),
        )


# --------------------------------------------------------------------------------- resolutions


def test_a_human_accepts_and_the_event_records_who_and_why(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task = claim_next(conn, worker_id="worker-a", now=T0)
    assert task is not None
    resolved = accept(
        conn, task.id, curator=Curator("k.saikia"), reason="checked against table 2", now=T0
    )
    assert resolved.status == "accepted"
    assert resolved.curator == "k.saikia"
    assert resolved.curator_kind == "human"
    assert resolved.claimed_by is None  # the lease is given back on resolution
    event = _events(conn, task.id, "accept")[0]
    assert event["actor_kind"] == "human"
    assert event["rationale"] == "checked against table 2"


def test_accepting_writes_nothing_canonical(conn: sqlite3.Connection) -> None:
    """Accept marks a proposal reviewed. Turning it into an assertion is a separate action."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    accept(conn, task_id, curator=Curator("k.saikia"), reason="verified", now=T0)
    assert conn.execute("SELECT COUNT(*) FROM assertion").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 0


def test_a_verdict_needs_a_reason(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    with pytest.raises(CurationError):
        accept(conn, task_id, curator=Curator("k.saikia"), reason="", now=T0)


def test_an_edit_keeps_the_original_beside_the_correction(conn: sqlite3.Connection) -> None:
    """What the model proposed and what was actually true are two facts, not one."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task = next(t for t in peek(conn, limit=10, now=T0) if t.record_path == "measurements[0]")
    corrected = dict(task.record)
    corrected["value"] = 20.6
    resolved = edit(
        conn,
        task.id,
        curator=Curator("k.saikia"),
        reason="the paper says 20.6, not 20.0",
        edited_payload=corrected,
        now=T0,
    )
    assert resolved.status == "edited"
    assert json.loads(resolved.payload_json)["value"] == 20.0
    assert json.loads(resolved.edited_payload_json or "{}")["value"] == 20.6


def test_a_second_verdict_is_refused(conn: sqlite3.Connection) -> None:
    """The first verdict is the record of what a curator decided. It is not replaceable."""
    enqueue_extraction(conn, seed(conn), now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    reject(conn, task_id, curator=Curator("k.saikia"), reason="not in the paper", now=T0)
    with pytest.raises(CurationError) as excinfo:
        accept(conn, task_id, curator=Curator("someone.else"), reason="I disagree", now=T0)
    assert "already" in str(excinfo.value)
    assert get_task(conn, task_id).status == "rejected"


# ---------------------------------------------------------------- rejections are kept forever


def test_a_rejected_task_is_kept(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    task_id = peek(conn, limit=1, now=T0)[0].id
    reject(conn, task_id, curator=Curator("k.saikia"), reason="fabricated number", now=T0)
    row = conn.execute("SELECT * FROM curation_task WHERE id = ?", (task_id,)).fetchone()
    assert row is not None
    assert row["status"] == "rejected"
    assert row["resolution_reason"] == "fabricated number"


def test_a_re_proposal_is_linked_to_the_rejection_and_reported(
    conn: sqlite3.Connection,
) -> None:
    """The signal the retention exists for: the model proposing the same rejected thing again."""
    first_extraction = seed(conn, extraction_id="YAA:EXTR:a")
    enqueue_extraction(conn, first_extraction, now=T0)
    rejected = next(t for t in peek(conn, limit=10, now=T0) if t.record_path == "measurements[0]")
    reject(conn, rejected.id, curator=Curator("k.saikia"), reason="not in the paper", now=T0)

    # The same paper extracted again under a new prompt version proposes the same record.
    second_extraction = seed(conn, extraction_id="YAA:EXTR:b")
    enqueue_extraction(conn, second_extraction, now=T0 + timedelta(days=1))

    repeat = conn.execute(
        "SELECT * FROM curation_task WHERE extraction_id = ? AND record_path = 'measurements[0]'",
        (second_extraction,),
    ).fetchone()
    assert repeat["repeat_of"] == rejected.id

    signals = repeat_offenders(conn)
    assert len(signals) == 1
    assert signals[0].times_proposed == 2
    assert signals[0].times_rejected == 1
    assert signals[0].model == MODEL


def test_the_proposal_hash_ignores_span_offsets_but_not_the_quote() -> None:
    """A model that re-derives offsets has not proposed anything new; a new quote has."""
    base = {"value": 1.0, "span": {"quote": "one", "char_start": 10, "char_end": 13}}
    moved = {"value": 1.0, "span": {"quote": "one", "char_start": 99, "char_end": 102}}
    requoted = {"value": 1.0, "span": {"quote": "uno", "char_start": 10, "char_end": 13}}
    assert proposal_hash("p", "measurements", base) == proposal_hash("p", "measurements", moved)
    assert proposal_hash("p", "measurements", base) != proposal_hash("p", "measurements", requoted)


def test_the_queue_module_contains_no_delete() -> None:
    """A rejection that can be deleted is a signal that can be lost.

    Asserted against the source rather than against behaviour on purpose: the danger is not that
    today's code deletes something, it is that tomorrow's adds a tidy-up that does.
    """
    tree = ast.parse(QUEUE_SOURCE.read_text(encoding="utf-8"))

    # Docstrings say the word "delete" constantly, and should. Only executable strings — the SQL —
    # and function names are checked.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(getattr(node, "body", None), list)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    sql = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and "delete" in node.value.lower()
    ]
    assert not sql, f"queue.py must issue no DELETE, found: {sql}"

    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and "delete" in node.name.lower()
    ]
    assert not names, f"queue.py must expose no delete function, found: {names}"


# ------------------------------------------------------------------------------------ reporting


def test_stats_count_every_status_and_flag_expired_leases(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    tasks = peek(conn, limit=10, now=T0)
    accept(conn, tasks[0].id, curator=Curator("k.saikia"), reason="ok", now=T0)
    reject(conn, tasks[1].id, curator=Curator("k.saikia"), reason="no", now=T0)
    claim_next(conn, worker_id="worker-dead", lease_seconds=60, now=T0)

    stats = queue_stats(conn, now=T0 + timedelta(seconds=300))
    assert stats.total == 3
    assert stats.by_status["accepted"] == 1
    assert stats.by_status["rejected"] == 1
    assert stats.by_status["in_progress"] == 1
    assert stats.expired_leases == 1
    assert stats.open == 1
    assert "expired_leases=1" in stats.summary()


def test_the_status_sets_do_not_overlap() -> None:
    assert not set(OPEN_STATUSES) & set(TERMINAL_STATUSES)


def test_an_unknown_record_kind_filter_is_refused(conn: sqlite3.Connection) -> None:
    enqueue_extraction(conn, seed(conn), now=T0)
    with pytest.raises(CurationError):
        peek(conn, limit=5, kinds=("mesurements",), now=T0)


def test_a_curator_must_have_a_name() -> None:
    with pytest.raises(ValueError):
        Curator("   ")
    with pytest.raises(ValueError):
        Curator("someone", kind="robot")
