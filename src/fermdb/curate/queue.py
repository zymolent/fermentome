"""The curation queue: one proposed record, one task, one human verdict.

The project owner's requirement is that curation runs as a **secondary, parallel, background job**
— not as a step inside extraction, and not as a single reviewer working through a list. Three
design decisions follow from that, and the rest of this module is detail:

**A lease, not a lock.** :func:`claim_next` hands a task to a named worker with an expiry. Several
workers can pull at once because the claim is a compare-and-swap ``UPDATE`` — two workers that
select the same row both try to take it and exactly one ``rowcount`` comes back 1. A worker that
dies does not strand its task forever: once the lease lapses the row is claimable again, and
``attempt_count`` records how many times that has happened, which is how a task that kills every
worker that touches it becomes visible instead of invisible.

**A task per record, not per extraction.** A curator accepts or rejects one strain, one
measurement, one bottleneck claim. A whole-extraction verdict would force a reviewer to reject
eleven good records to get rid of one bad one, and the eleven would come back next run.

**Rejections are retained.** There is no delete in this module — no function, no ``DELETE``
statement, and a test in ``tests/test_curate.py`` asserts it stays that way. A rejected task keeps
its ``proposal_hash``, so when the model proposes the same thing again the new task is linked to
the old one through ``repeat_of`` and :func:`repeat_offenders` can report it. A model that keeps
re-proposing something a human already rejected is telling you about the model, and deleting the
rejection is what makes that signal unobservable.

Over all of it sits PLAN.md L.5: **no agent may promote its own proposal.** That is enforced three
times over, deliberately, because it is the rule whose violation would be hardest to notice:

1. :func:`accept` and :func:`edit` refuse a curator whose ``kind`` is not ``'human'``;
2. they also refuse a curator whose name matches the model, model version or extractor that
   produced the proposal, so a human account shared with an automation cannot launder it;
3. the ``curation_task`` and ``curation_event`` CHECK constraints refuse the row anyway.

Accepting a task marks it accepted and records who said so. It does **not** write an assertion,
an evidence item, or anything else in Zone R or Zone H — that promotion is a separate, curator-
driven step, and putting it here would make "accept" mean two things at once.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from ..extract.schemas import RECORD_KINDS, record_path

__all__ = [
    "ACTOR_KINDS",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_PRIORITY",
    "OPEN_STATUSES",
    "QUEUE_ACTOR",
    "STALLED_ATTEMPTS",
    "TASK_STATUSES",
    "TERMINAL_STATUSES",
    "CurationError",
    "Curator",
    "LeaseLost",
    "PromotionRefused",
    "QueueStats",
    "RepeatSignal",
    "Task",
    "TaskNotFound",
    "accept",
    "claim_next",
    "edit",
    "enqueue_extraction",
    "enqueue_pending_extractions",
    "get_task",
    "heartbeat",
    "peek",
    "proposal_hash",
    "queue_stats",
    "reject",
    "release",
    "repeat_offenders",
]

JsonObject = dict[str, Any]

#: The task lifecycle, as PLAN.md H.5 names it plus the ``in_progress`` a leased queue needs.
TASK_STATUSES: Final[tuple[str, ...]] = (
    "pending",
    "in_progress",
    "accepted",
    "edited",
    "rejected",
)

#: Statuses a task can still be worked on from.
OPEN_STATUSES: Final[tuple[str, ...]] = ("pending", "in_progress")

#: Statuses a task never leaves. A second verdict is refused rather than overwriting the first.
TERMINAL_STATUSES: Final[tuple[str, ...]] = ("accepted", "edited", "rejected")

#: Who may act. An agent claims and releases; only a human resolves (PLAN.md L.5).
ACTOR_KINDS: Final[tuple[str, str]] = ("human", "agent")

#: Recorded as the curator of the bookkeeping events this module writes on its own behalf.
QUEUE_ACTOR: Final[str] = "fermdb.curate.queue"

#: Long enough that a human reading a paper does not lose the task mid-review, short enough that a
#: crashed worker's task is back in the queue within the quarter hour.
DEFAULT_LEASE_SECONDS: Final[int] = 900

#: Lower sorts first. A flat default on purpose: a per-kind or per-product priority policy is a
#: curation policy, and CONVENTIONS.md puts policy in data, not in a constant here. Callers that
#: have such a policy pass ``priority``.
DEFAULT_PRIORITY: Final[int] = 100

# How many times claim_next re-reads and re-tries after losing a race. Bounded: a queue where a
# worker loses ten consecutive races is contended past the point where retrying helps, and the
# honest answer is "nothing available right now".
_CLAIM_RETRIES: Final[int] = 10


# ---------------------------------------------------------------------------------- exceptions


class CurationError(RuntimeError):
    """A curation action could not be performed."""


class TaskNotFound(CurationError):
    """No task with that id."""


class LeaseLost(CurationError):
    """The worker no longer holds this task — its lease expired and someone else took it."""


class PromotionRefused(CurationError):
    """The actor may not resolve this task (PLAN.md L.5).

    Its own exception type rather than a generic error because this is the rule the whole Zone I
    design rests on, and a caller catching ``CurationError`` broadly should still be able to
    notice that *this* is what happened.
    """


# -------------------------------------------------------------------------------------- actors


@dataclass(frozen=True)
class Curator:
    """Who is acting, and whether they are a person.

    ``kind`` is not decoration. ``'agent'`` can claim a task and hand it back; only ``'human'``
    can accept, edit or reject one. An automation that wants to resolve tasks has to lie about
    what it is, in a field that is written to the audit log either way.
    """

    name: str
    kind: str = "human"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a curator must have a name; an anonymous verdict is not a record")
        if self.kind not in ACTOR_KINDS:
            raise ValueError(f"curator kind must be one of {ACTOR_KINDS}, got {self.kind!r}")

    @property
    def is_human(self) -> bool:
        """True for a person."""
        return self.kind == "human"


# ---------------------------------------------------------------------------------------- time


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


# -------------------------------------------------------------------------------- the task row


@dataclass(frozen=True)
class Task:
    """One proposed record awaiting a human."""

    id: str
    extraction_id: str
    publication_id: str
    record_path: str
    record_kind: str
    payload_json: str
    status: str
    priority: int
    claimed_by: str | None
    claimed_at: str | None
    lease_expires_at: str | None
    attempt_count: int
    curator: str | None
    curator_kind: str | None
    resolved_at: str | None
    resolution_reason: str | None
    edited_payload_json: str | None
    proposal_hash: str
    repeat_of: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        """Build from a ``SELECT *`` over ``curation_task``."""
        return cls(
            id=str(row["id"]),
            extraction_id=str(row["extraction_id"]),
            publication_id=str(row["publication_id"]),
            record_path=str(row["record_path"]),
            record_kind=str(row["record_kind"]),
            payload_json=str(row["payload"]),
            status=str(row["status"]),
            priority=int(row["priority"]),
            claimed_by=row["claimed_by"],
            claimed_at=row["claimed_at"],
            lease_expires_at=row["lease_expires_at"],
            attempt_count=int(row["attempt_count"]),
            curator=row["curator"],
            curator_kind=row["curator_kind"],
            resolved_at=row["resolved_at"],
            resolution_reason=row["resolution_reason"],
            edited_payload_json=row["edited_payload"],
            proposal_hash=str(row["proposal_hash"]),
            repeat_of=row["repeat_of"],
            created_at=str(row["created_at"]),
        )

    @property
    def record(self) -> JsonObject:
        """The proposed record, parsed."""
        parsed: JsonObject = json.loads(self.payload_json)
        return parsed

    @property
    def is_repeat(self) -> bool:
        """True when this proposal was already rejected once before."""
        return self.repeat_of is not None

    def summary(self) -> str:
        """One line for a CLI listing."""
        flag = " REPEAT" if self.is_repeat else ""
        holder = f" held by {self.claimed_by}" if self.claimed_by else ""
        return (
            f"{self.id}  {self.status:<12} p{self.priority:<4} {self.publication_id} "
            f"{self.record_path}{flag}{holder}"
        )


# ------------------------------------------------------------------------------ proposal hash


def _strip_offsets(value: Any) -> Any:
    """Drop span offsets so the same claim hashes the same however it was located.

    The quote is kept: a different quote is a different piece of evidence and therefore a
    different proposal. The offsets are not, because a model that re-derives them a character
    differently has not proposed anything new, and a curator who rejected the claim rejected the
    claim.
    """
    if isinstance(value, Mapping):
        return {
            key: (
                {"quote": sub.get("quote")}
                if key == "span" and isinstance(sub, Mapping)
                else _strip_offsets(sub)
            )
            for key, sub in sorted(value.items())
        }
    if isinstance(value, list):
        return [_strip_offsets(item) for item in value]
    return value


def proposal_hash(publication_id: str, record_kind: str, record: Mapping[str, Any]) -> str:
    """A stable identity for "this claim, about this paper", independent of span offsets."""
    canonical = json.dumps(
        {
            "publication_id": publication_id,
            "record_kind": record_kind,
            "record": _strip_offsets(record),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------ events


def _record_event(
    conn: sqlite3.Connection,
    *,
    curator: str,
    actor_kind: str,
    action: str,
    target_type: str,
    target_id: str,
    rationale: str,
    now: datetime,
) -> str:
    event_id = f"YAA:CUEV:{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id, "
        "rationale, created_at, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'R')",
        (event_id, curator, actor_kind, action, target_type, target_id, rationale, _iso(now)),
    )
    return event_id


# --------------------------------------------------------------------------------- enqueueing


def enqueue_extraction(
    conn: sqlite3.Connection,
    extraction_id: str,
    *,
    priority: int = DEFAULT_PRIORITY,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Create one pending task per proposed record in an extraction. Idempotent.

    Safe to run repeatedly and concurrently: ``curation_task`` is unique on
    ``(extraction_id, record_path)``, so a second scanner pass over the same extraction inserts
    nothing. Returns the ids of the tasks this call actually created, which is empty on a repeat.

    Raises:
        CurationError: The extraction does not exist, is not ``'proposed'``, or has no payload.
    """
    moment = _now(now)
    row = conn.execute(
        "SELECT id, publication_id, payload, review_state FROM extraction WHERE id = ?",
        (extraction_id,),
    ).fetchone()
    if row is None:
        raise CurationError(f"no extraction {extraction_id!r}")
    if row["review_state"] != "proposed":
        raise CurationError(
            f"extraction {extraction_id} is {row['review_state']!r}, not 'proposed'; it has "
            f"already been through review and re-queueing it would ask for a second verdict on a "
            f"decided question"
        )
    if not row["payload"]:
        raise CurationError(f"extraction {extraction_id} has no payload to curate")

    publication_id = str(row["publication_id"])
    payload = json.loads(str(row["payload"]))
    created: list[str] = []

    for kind in RECORD_KINDS:
        records = payload.get(kind)
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            path = record_path(kind, index)
            digest = proposal_hash(publication_id, kind, record)
            task_id = f"YAA:CTASK:{uuid.uuid4().hex}"
            cursor = conn.execute(
                "INSERT OR IGNORE INTO curation_task (id, extraction_id, publication_id, "
                "record_path, record_kind, payload, status, priority, attempt_count, "
                "proposal_hash, repeat_of, created_at, zone) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?, ?, 'I')",
                (
                    task_id,
                    extraction_id,
                    publication_id,
                    path,
                    kind,
                    json.dumps(record, sort_keys=True),
                    priority,
                    digest,
                    _previously_rejected(conn, digest),
                    _iso(moment),
                ),
            )
            if cursor.rowcount:
                created.append(task_id)

    if created:
        _record_event(
            conn,
            curator=QUEUE_ACTOR,
            actor_kind="agent",
            action="create",
            target_type="extraction",
            target_id=extraction_id,
            rationale=f"queued {len(created)} proposed record(s) for curation",
            now=moment,
        )
    conn.commit()
    return tuple(created)


def _previously_rejected(conn: sqlite3.Connection, digest: str) -> str | None:
    """The oldest rejected task proposing the same thing, if there is one."""
    row = conn.execute(
        "SELECT id FROM curation_task WHERE proposal_hash = ? AND status = 'rejected' "
        "ORDER BY created_at ASC, id ASC LIMIT 1",
        (digest,),
    ).fetchone()
    return None if row is None else str(row["id"])


def enqueue_pending_extractions(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    priority: int = DEFAULT_PRIORITY,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Scan for proposed extractions that have no tasks yet and queue them.

    This is the entry point for the background job: extraction writes rows and moves on, and this
    runs on its own schedule to turn them into work. Returns every task id created across all the
    extractions it picked up.
    """
    query = (
        "SELECT e.id FROM extraction e WHERE e.review_state = 'proposed' "
        "AND NOT EXISTS (SELECT 1 FROM curation_task t WHERE t.extraction_id = e.id) "
        "ORDER BY e.created_at ASC, e.id ASC"
    )
    parameters: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (limit,)
    ids = [str(row["id"]) for row in conn.execute(query, parameters)]
    created: list[str] = []
    for extraction_id in ids:
        created.extend(enqueue_extraction(conn, extraction_id, priority=priority, now=now))
    return tuple(created)


# --------------------------------------------------------------------------------- the queue


def _kind_filter(kinds: Sequence[str] | None) -> tuple[str, tuple[str, ...]]:
    if not kinds:
        return "", ()
    unknown = [kind for kind in kinds if kind not in RECORD_KINDS]
    if unknown:
        raise CurationError(f"unknown record kind(s) {unknown}; expected from {RECORD_KINDS}")
    placeholders = ", ".join("?" for _ in kinds)
    return f" AND record_kind IN ({placeholders})", tuple(kinds)


def get_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """One task by id, or raise :class:`TaskNotFound`."""
    row = conn.execute("SELECT * FROM curation_task WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise TaskNotFound(f"no curation task {task_id!r}")
    return Task.from_row(row)


def peek(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
    kinds: Sequence[str] | None = None,
    now: datetime | None = None,
) -> tuple[Task, ...]:
    """The next tasks a worker would get, without claiming any of them.

    What ``fermdb curate next`` shows. Deliberately claim-free: a curator looking at the queue has
    not started work on it, and a listing that took leases would strand a task every time someone
    checked how much was left.
    """
    clause, parameters = _kind_filter(kinds)
    rows = conn.execute(
        "SELECT * FROM curation_task WHERE (status = 'pending' "
        "OR (status = 'in_progress' AND lease_expires_at <= ?))"  # noqa: S608 - fixed clause
        f"{clause} ORDER BY priority ASC, created_at ASC, id ASC LIMIT ?",
        (_iso(_now(now)), *parameters, limit),
    ).fetchall()
    return tuple(Task.from_row(row) for row in rows)


def claim_next(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    kinds: Sequence[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    actor_kind: str = "agent",
    now: datetime | None = None,
) -> Task | None:
    """Lease the next task to ``worker_id``, or return None if there is nothing to do.

    The claim is a compare-and-swap: the row is selected, then updated with a ``WHERE`` that pins
    the exact status and lease the ``SELECT`` saw. A worker whose update affects no rows lost the
    race and tries again with a fresh read. That is what lets several workers — in several
    processes — pull from this queue at once without a lock and without ever handing the same task
    to two of them.

    A task whose lease has expired is claimable again. ``attempt_count`` goes up each time, so a
    task that keeps being claimed and never resolved is visible in :func:`queue_stats` rather than
    silently cycling.
    """
    if not worker_id.strip():
        raise CurationError("a worker must have an id; an unattributed lease cannot be released")
    if actor_kind not in ACTOR_KINDS:
        raise CurationError(f"actor kind must be one of {ACTOR_KINDS}, got {actor_kind!r}")
    if lease_seconds <= 0:
        raise CurationError(f"lease_seconds must be positive, got {lease_seconds}")

    moment = _now(now)
    now_iso = _iso(moment)
    expires_iso = _iso(moment + timedelta(seconds=lease_seconds))
    clause, parameters = _kind_filter(kinds)

    for _ in range(_CLAIM_RETRIES):
        row = conn.execute(
            "SELECT id, status, lease_expires_at FROM curation_task "
            "WHERE (status = 'pending' "
            "OR (status = 'in_progress' AND lease_expires_at <= ?))"  # noqa: S608 - fixed clause
            f"{clause} ORDER BY priority ASC, created_at ASC, id ASC LIMIT 1",
            (now_iso, *parameters),
        ).fetchone()
        if row is None:
            return None

        cursor = conn.execute(
            "UPDATE curation_task SET status = 'in_progress', claimed_by = ?, claimed_at = ?, "
            "lease_expires_at = ?, attempt_count = attempt_count + 1 "
            "WHERE id = ? AND status = ? AND COALESCE(lease_expires_at, '') = ?",
            (
                worker_id,
                now_iso,
                expires_iso,
                row["id"],
                row["status"],
                row["lease_expires_at"] or "",
            ),
        )
        conn.commit()
        if cursor.rowcount != 1:
            continue  # another worker took it between the SELECT and the UPDATE

        _record_event(
            conn,
            curator=worker_id,
            actor_kind=actor_kind,
            action="claim",
            target_type="curation_task",
            target_id=str(row["id"]),
            rationale=f"leased until {expires_iso}",
            now=moment,
        )
        conn.commit()
        return get_task(conn, str(row["id"]))
    return None


def heartbeat(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> str:
    """Extend a held lease. Returns the new expiry.

    Raises :class:`LeaseLost` if the worker no longer holds the task, which is the honest outcome:
    the work it has done since losing the lease may duplicate someone else's, and pretending
    otherwise is how two curators end up reviewing the same record.
    """
    moment = _now(now)
    expires_iso = _iso(moment + timedelta(seconds=lease_seconds))
    cursor = conn.execute(
        "UPDATE curation_task SET lease_expires_at = ? "
        "WHERE id = ? AND status = 'in_progress' AND claimed_by = ?",
        (expires_iso, task_id, worker_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        task = get_task(conn, task_id)  # raises TaskNotFound if it is not merely a lost lease
        raise LeaseLost(
            f"{worker_id} does not hold {task_id}: it is {task.status!r} and held by "
            f"{task.claimed_by!r}"
        )
    return expires_iso


def release(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    worker_id: str,
    reason: str,
    actor_kind: str = "agent",
    now: datetime | None = None,
) -> Task:
    """Hand a task back to the queue unresolved, with a reason.

    Not a rejection: a released task goes back to ``'pending'`` and will be offered again. This is
    what a background worker does when it cannot decide — which is most of the time, because
    deciding is a human's job.
    """
    if not reason.strip():
        raise CurationError("release needs a reason; 'handed back, no reason given' is not a log")
    moment = _now(now)
    cursor = conn.execute(
        "UPDATE curation_task SET status = 'pending', claimed_by = NULL, claimed_at = NULL, "
        "lease_expires_at = NULL WHERE id = ? AND status = 'in_progress' AND claimed_by = ?",
        (task_id, worker_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        task = get_task(conn, task_id)
        raise LeaseLost(
            f"{worker_id} does not hold {task_id}: it is {task.status!r} and held by "
            f"{task.claimed_by!r}"
        )
    _record_event(
        conn,
        curator=worker_id,
        actor_kind=actor_kind,
        action="release",
        target_type="curation_task",
        target_id=task_id,
        rationale=reason,
        now=moment,
    )
    conn.commit()
    return get_task(conn, task_id)


# ----------------------------------------------------------------------------- the resolutions


def _refuse_non_human(curator: Curator, action: str) -> None:
    if curator.is_human:
        return
    raise PromotionRefused(
        f"{curator.name} is an agent and may not {action} a curation task. PLAN.md L.5: no agent "
        f"may promote its own proposal, and an automated verdict on model output is exactly that "
        f"whether it says yes or no. An agent may claim a task and release it; a person decides."
    )


def _refuse_self_review(conn: sqlite3.Connection, task: Task, curator: Curator) -> None:
    """Refuse a curator whose name is the thing that produced the proposal.

    The ``kind`` check above stops an agent that admits to being one. This stops the other case: a
    pipeline running under a curator name that is really the model, the model version or the
    extractor. Both are the same rule; only the second one survives someone passing
    ``kind='human'``.
    """
    row = conn.execute(
        "SELECT model, model_version, extractor, extractor_version FROM extraction WHERE id = ?",
        (task.extraction_id,),
    ).fetchone()
    if row is None:
        return
    proposers = {
        str(value).strip().lower()
        for value in (row["model"], row["model_version"], row["extractor"])
        if value
    }
    if curator.name.strip().lower() in proposers:
        raise PromotionRefused(
            f"{curator.name!r} is the thing that proposed this record (extraction "
            f"{task.extraction_id} names model={row['model']!r}, extractor={row['extractor']!r}). "
            f"A proposal cannot review itself (PLAN.md L.5)."
        )


def _resolve(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    status: str,
    action: str,
    curator: Curator,
    reason: str,
    edited_payload: Mapping[str, Any] | None,
    now: datetime | None,
) -> Task:
    if status not in TERMINAL_STATUSES:
        raise CurationError(f"{status!r} is not a resolution; expected {TERMINAL_STATUSES}")
    if not reason.strip():
        raise CurationError(
            f"a {status} verdict needs a reason. A verdict with no reason cannot be reviewed "
            f"later, and the reason is the only part of it that is useful to the next curator."
        )
    _refuse_non_human(curator, action)

    task = get_task(conn, task_id)
    if task.status in TERMINAL_STATUSES:
        raise CurationError(
            f"{task_id} is already {task.status!r} (by {task.curator!r} at {task.resolved_at}). "
            f"A second verdict is refused rather than overwriting the first: the first is the "
            f"record of what a curator decided, and it is not replaceable."
        )
    if status in ("accepted", "edited"):
        _refuse_self_review(conn, task, curator)

    moment = _now(now)
    cursor = conn.execute(
        "UPDATE curation_task SET status = ?, curator = ?, curator_kind = ?, resolved_at = ?, "
        "resolution_reason = ?, edited_payload = ?, claimed_by = NULL, claimed_at = NULL, "
        "lease_expires_at = NULL "
        "WHERE id = ? AND status IN ('pending', 'in_progress')",
        (
            status,
            curator.name,
            curator.kind,
            _iso(moment),
            reason,
            json.dumps(edited_payload, sort_keys=True) if edited_payload is not None else None,
            task_id,
        ),
    )
    conn.commit()
    if cursor.rowcount != 1:
        raise CurationError(
            f"{task_id} was resolved by someone else between reading it and writing the verdict"
        )
    _record_event(
        conn,
        curator=curator.name,
        actor_kind=curator.kind,
        action=action,
        target_type="curation_task",
        target_id=task_id,
        rationale=reason,
        now=moment,
    )
    conn.commit()
    return get_task(conn, task_id)


def accept(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    curator: Curator,
    reason: str,
    now: datetime | None = None,
) -> Task:
    """A human accepts the proposed record as it stands.

    This marks the task accepted and records who, when and why. It writes nothing into Zone R or
    Zone H: turning an accepted proposal into an assertion is a separate curator action, and
    collapsing the two would mean "accept" silently created canonical data.
    """
    return _resolve(
        conn,
        task_id,
        status="accepted",
        action="accept",
        curator=curator,
        reason=reason,
        edited_payload=None,
        now=now,
    )


def edit(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    curator: Curator,
    reason: str,
    edited_payload: Mapping[str, Any],
    now: datetime | None = None,
) -> Task:
    """A human accepts a corrected version of the record.

    The model's original stays in ``payload`` and the correction goes in ``edited_payload``. Both
    are kept because they are two different facts: what the model proposed, and what was actually
    true. A pile of edits that all fix the same field is a prompt bug, and overwriting the
    original would erase the evidence for it.
    """
    if not edited_payload:
        raise CurationError(
            "an 'edited' verdict needs the corrected record; if nothing changed, accept it instead"
        )
    return _resolve(
        conn,
        task_id,
        status="edited",
        action="edit",
        curator=curator,
        reason=reason,
        edited_payload=edited_payload,
        now=now,
    )


def reject(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    curator: Curator,
    reason: str,
    now: datetime | None = None,
) -> Task:
    """A human rejects the proposed record. The row is kept forever.

    Nothing is deleted, here or anywhere in this module. The rejected row's ``proposal_hash`` is
    what lets :func:`repeat_offenders` notice the model proposing the same rejected thing again,
    and that signal exists only for as long as the rejection does.
    """
    return _resolve(
        conn,
        task_id,
        status="rejected",
        action="reject",
        curator=curator,
        reason=reason,
        edited_payload=None,
        now=now,
    )


# -------------------------------------------------------------------------------- the reporting


@dataclass(frozen=True)
class QueueStats:
    """What ``fermdb curate stats`` prints."""

    by_status: Mapping[str, int]
    expired_leases: int
    repeat_proposals: int
    stalled: int
    oldest_pending_at: str | None

    @property
    def total(self) -> int:
        """Every task, in any status."""
        return sum(self.by_status.values())

    @property
    def open(self) -> int:
        """Tasks still awaiting a verdict."""
        return sum(self.by_status.get(status, 0) for status in OPEN_STATUSES)

    def summary(self) -> str:
        """A few lines for a terminal."""
        counts = "  ".join(f"{status}={self.by_status.get(status, 0)}" for status in TASK_STATUSES)
        return (
            f"{counts}\n"
            f"open={self.open}  total={self.total}\n"
            f"expired_leases={self.expired_leases}  stalled={self.stalled}  "
            f"repeat_proposals={self.repeat_proposals}\n"
            f"oldest_pending_at={self.oldest_pending_at or '-'}"
        )


#: A task claimed this many times without ever being resolved is stuck on something, not busy.
STALLED_ATTEMPTS: Final[int] = 3


def queue_stats(conn: sqlite3.Connection, *, now: datetime | None = None) -> QueueStats:
    """Counts by status, plus the three numbers that say whether the queue is healthy."""
    now_iso = _iso(_now(now))
    by_status = {
        str(row["status"]): int(row["n"])
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM curation_task GROUP BY status")
    }
    expired = conn.execute(
        "SELECT COUNT(*) AS n FROM curation_task WHERE status = 'in_progress' "
        "AND lease_expires_at <= ?",
        (now_iso,),
    ).fetchone()
    repeats = conn.execute(
        "SELECT COUNT(*) AS n FROM curation_task WHERE repeat_of IS NOT NULL"
    ).fetchone()
    stalled = conn.execute(
        "SELECT COUNT(*) AS n FROM curation_task WHERE status IN ('pending', 'in_progress') "
        "AND attempt_count >= ?",
        (STALLED_ATTEMPTS,),
    ).fetchone()
    oldest = conn.execute(
        "SELECT MIN(created_at) AS oldest FROM curation_task WHERE status = 'pending'"
    ).fetchone()
    return QueueStats(
        by_status=by_status,
        expired_leases=int(expired["n"]),
        repeat_proposals=int(repeats["n"]),
        stalled=int(stalled["n"]),
        oldest_pending_at=oldest["oldest"],
    )


@dataclass(frozen=True)
class RepeatSignal:
    """A proposal a curator rejected that the model went on proposing.

    Not a queue problem — a model problem, which is why it is reported separately and why the
    rejected rows are never cleaned up. ``model`` names what to look at.
    """

    proposal_hash: str
    record_kind: str
    publication_id: str
    model: str | None
    times_proposed: int
    times_rejected: int
    latest_task_id: str
    example_record_path: str


def repeat_offenders(
    conn: sqlite3.Connection, *, minimum_proposals: int = 2
) -> tuple[RepeatSignal, ...]:
    """Proposals that were rejected and then made again, most repeated first.

    Reads the retained rejections. If rejected tasks were deleted this function would return
    nothing forever and look like good news, which is the entire argument for keeping them.
    """
    rows = conn.execute(
        "SELECT t.proposal_hash AS proposal_hash, "
        "       MIN(t.record_kind) AS record_kind, "
        "       MIN(t.publication_id) AS publication_id, "
        "       MIN(t.record_path) AS record_path, "
        "       COUNT(*) AS times_proposed, "
        "       SUM(CASE WHEN t.status = 'rejected' THEN 1 ELSE 0 END) AS times_rejected, "
        "       MAX(t.id) AS latest_task_id, "
        "       MIN(e.model) AS model "
        "FROM curation_task t LEFT JOIN extraction e ON e.id = t.extraction_id "
        "GROUP BY t.proposal_hash "
        "HAVING times_rejected >= 1 AND times_proposed >= ? "
        "ORDER BY times_proposed DESC, proposal_hash ASC",
        (minimum_proposals,),
    ).fetchall()
    return tuple(
        RepeatSignal(
            proposal_hash=str(row["proposal_hash"]),
            record_kind=str(row["record_kind"]),
            publication_id=str(row["publication_id"]),
            model=row["model"],
            times_proposed=int(row["times_proposed"]),
            times_rejected=int(row["times_rejected"]),
            latest_task_id=str(row["latest_task_id"]),
            example_record_path=str(row["record_path"]),
        )
        for row in rows
    )
