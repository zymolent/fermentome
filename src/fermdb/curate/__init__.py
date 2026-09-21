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

Accepting is not the end of the pipeline and neither is promotion. :mod:`fermdb.curate.promote`
turns a resolved task into a row -- a `strain`, a `measurement`, a `bottleneck` -- and
:mod:`fermdb.curate.assertions` turns those rows into the thing PLAN.md C.1 calls the unit of
knowledge: an `assertion` with `evidence_item`s under it, whose L1-L5 level is read from the
`assertion_level` view and never written anywhere::

    from fermdb.curate import build_assertion, from_measurement, level_of
    request = from_measurement(
        conn, "YAA:MEAS:...", predicate="affects_production_of",
        evidence_type="direct_perturbation", direction="increases",
        independent_group="atsumi-lab", publication_id="doi:10.1186/...",
        control_strain_id="YAA:STRAIN:...",
    )
    result = build_assertion(conn, request, curator=Curator("k.saikia"), reason="table 2")
    result.level.display     # 'L1', read back out of the view
"""

from __future__ import annotations

from .assertions import (
    DIRECT_TYPES,
    EVIDENCE_TYPES,
    AssertionPlan,
    AssertionRequest,
    AssertionResult,
    EvidenceRequest,
    NotAssertable,
    attach_evidence,
    build_assertion,
    from_bottleneck,
    from_measurement,
    from_modification,
    level_of,
    plan_assertion,
    plan_many,
    with_evidence,
)
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
    "DIRECT_TYPES",
    "EVIDENCE_TYPES",
    "OPEN_STATUSES",
    "QUEUE_ACTOR",
    "STALLED_ATTEMPTS",
    "TASK_STATUSES",
    "TERMINAL_STATUSES",
    "AssertionPlan",
    "AssertionRequest",
    "AssertionResult",
    "CurationError",
    "Curator",
    "EvidenceRequest",
    "LeaseLost",
    "NotAssertable",
    "PromotionRefused",
    "QueueStats",
    "RepeatSignal",
    "Task",
    "TaskNotFound",
    "accept",
    "attach_evidence",
    "build_assertion",
    "claim_next",
    "edit",
    "enqueue_extraction",
    "enqueue_pending_extractions",
    "from_bottleneck",
    "from_measurement",
    "from_modification",
    "get_task",
    "heartbeat",
    "level_of",
    "peek",
    "plan_assertion",
    "plan_many",
    "proposal_hash",
    "queue_stats",
    "reject",
    "release",
    "repeat_offenders",
    "with_evidence",
]
