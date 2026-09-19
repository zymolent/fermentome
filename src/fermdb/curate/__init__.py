"""Human curation of model proposals — the second, parallel half of the extraction pipeline.

Extraction writes ``review_state='proposed'`` rows and moves on. This package turns them into
reviewable work and records what a human decided. It is deliberately a *separate* job, on its own
schedule, with its own workers: the project owner asked for curation to run as a secondary,
parallel, background process, and :mod:`fermdb.curate.queue` is built for that rather than adapted
to it — leased tasks, concurrent claims, one task per proposed record.

The rule this package exists to enforce is PLAN.md L.5: **no agent may promote its own proposal.**
Accepting or editing a task requires a curator whose ``kind`` is ``'human'`` and whose name is not
the model, model version or extractor that made the proposal; the ``curation_task`` and
``curation_event`` CHECK constraints refuse the row regardless. An agent worker can claim a task,
look at it, and hand it back. It cannot decide.

And nothing is ever deleted. A rejected task stays, with the hash of what was proposed, so that a
model re-proposing something a curator already threw out is visible
(:func:`~fermdb.curate.queue.repeat_offenders`) instead of quietly costing a reviewer the same
minute twice.

Typical background worker::

    from fermdb.curate import claim_next, release
    task = claim_next(conn, worker_id="curation-worker-3")
    if task is not None:
        release(conn, task.id, worker_id="curation-worker-3", reason="needs a human")

Typical curator::

    from fermdb.curate import Curator, accept, peek
    for task in peek(conn, limit=5):
        print(task.summary())
    accept(conn, task_id, curator=Curator("k.saikia"), reason="checked against table 2")
"""

from __future__ import annotations

from .queue import (
    ACTOR_KINDS,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_PRIORITY,
    OPEN_STATUSES,
    QUEUE_ACTOR,
    STALLED_ATTEMPTS,
    TASK_STATUSES,
    TERMINAL_STATUSES,
    CurationError,
    Curator,
    LeaseLost,
    PromotionRefused,
    QueueStats,
    RepeatSignal,
    Task,
    TaskNotFound,
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
