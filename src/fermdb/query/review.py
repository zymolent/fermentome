"""Everything needed to judge one proposed record, assembled in one read.

`fermdb curate next` prints a task summary and, on request, the raw JSON payload. That is enough
to see *what* was proposed and nothing about whether it is true. To decide, a curator has to open
the paper, find the sentence, check the number against it, and work out what accepting would
actually produce -- four steps outside the tool, per record, fifty-five times.

Gathering that context is the expensive part of curation, and it is the same work every time, so
it belongs in code. A packet carries:

* **the proposed fields**, typed through `values.Value`, so a field the model left out is visibly
  absent rather than missing from a JSON dump;
* **the span, re-resolved against the stored full text**, with the surrounding sentences. Not the
  stored quote echoed back -- the quote as the document has it *now*, at the offsets the record
  claims. A stored quote proves only that a model once emitted that string;
* **what accepting leads to**: the `PromotionPlan`, so the curator sees the row and the fields it
  still needs *before* deciding, rather than discovering at promotion time that every strain needs
  an organism;
* **warnings**, which are the point of the whole thing.

On warnings. Each is a fact the atlas already knows and nobody was asking it for:

* a span that no longer resolves -- the record cannot be traced to its source;
* a proposal a curator has already rejected, which the model then made again (`proposal_hash`
  history). Accepting it silently would undo a decision somebody made deliberately;
* a measurement whose strain **has no strain proposal in the same publication**. This one is not
  hypothetical: on the first real run, the Wess deletion series proposed six strains while its
  measurements referenced eight, and the two missing were its 1.32 and 2.09 g/L results -- the
  paper's best strains. Promotion blocks those, but blocking at promotion time means the curator
  has already accepted them and has to come back. Saying it during review is the same fact,
  delivered when it can still change what someone does.

Read-only, like everything in this package: it plans a promotion but never performs one, and the
verdict on a span comes from `curate.promote.verify_span` rather than a second implementation.
Two implementations of "does this quote resolve" would eventually disagree, and the bad direction
is the likely one -- a reviewer told the span is fine, promotion refusing it afterwards.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..config import Settings
from ..curate.promote import PromotionPlan, SpanVerdict, plan_promotion, verify_span
from ..curate.queue import Task, get_task, peek
from .values import Absence, Cited, Value, Zone

__all__ = [
    "CONTEXT_CHARS",
    "ProposedField",
    "ReviewPacket",
    "SpanView",
    "Warning_",
    "review_packet",
    "review_queue",
]

#: How much of the document to show either side of the quote. Enough for the sentence before and
#: after, which is usually what decides whether a number was read off the right row.
CONTEXT_CHARS: Final[int] = 260

#: Payload keys that are bookkeeping rather than proposed content, and are shown separately.
_META_KEYS: Final[frozenset[str]] = frozenset({"span", "zone", "review_state", "confidence"})


@dataclass(frozen=True)
class Warning_:
    """Something a curator should look at before deciding. Named to avoid the builtin."""

    code: str
    message: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ProposedField:
    """One field of the proposed record."""

    name: str
    value: Value[Any]

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value.as_json()}


@dataclass(frozen=True)
class SpanView:
    """The quote as the source document has it now, with what surrounds it."""

    verdict: SpanVerdict
    before: str = ""
    quote_in_source: str = ""
    after: str = ""
    truncated_before: bool = False
    truncated_after: bool = False

    @property
    def status(self) -> str:
        return self.verdict.status

    @property
    def resolves(self) -> bool:
        return self.verdict.ok

    @property
    def context(self) -> str:
        """The passage with the quote marked, for a terminal."""
        if not self.quote_in_source:
            return ""
        lead = "..." if self.truncated_before else ""
        tail = "..." if self.truncated_after else ""
        return f"{lead}{self.before}>>>{self.quote_in_source}<<<{self.after}{tail}"

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "resolves": self.resolves,
            "detail": self.verdict.detail,
            "quote_as_recorded": self.verdict.quote,
            "quote_in_source": self.quote_in_source or None,
            "char_start": self.verdict.start,
            "char_end": self.verdict.end,
            "found_at": self.verdict.found_at,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class ReviewPacket:
    """One proposal, with everything needed to judge it."""

    task_id: str
    record_kind: str
    record_path: str
    status: str
    citation: Cited[str]
    fields: tuple[ProposedField, ...]
    model_confidence: Value[str]
    span: SpanView
    plan: PromotionPlan
    warnings: tuple[Warning_, ...]
    times_proposed: int = 1
    times_rejected: int = 0

    @property
    def needs_attention(self) -> bool:
        return bool(self.warnings)

    def as_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "record_kind": self.record_kind,
            "record_path": self.record_path,
            "status": self.status,
            "citation": self.citation.as_json(),
            "fields": [f.as_json() for f in self.fields],
            "model_confidence": self.model_confidence.as_json(),
            "span": self.span.as_json(),
            "plan": self.plan.as_json(),
            "warnings": [w.as_json() for w in self.warnings],
            "times_proposed": self.times_proposed,
            "times_rejected": self.times_rejected,
            "needs_attention": self.needs_attention,
        }


def _record(task: Task) -> Mapping[str, Any]:
    raw = task.edited_payload_json or task.payload_json
    loaded: Any = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


def _fields(record: Mapping[str, Any]) -> tuple[ProposedField, ...]:
    """The proposed content, bookkeeping keys removed, in a stable order.

    A value of None becomes an absent `Value` rather than being dropped: "the model looked and
    found nothing" and "this key is not part of this record kind" are different, and only the
    first should show as a blank field on a review screen.
    """
    return tuple(
        ProposedField(
            name=key,
            value=(
                Value.absent(Absence.NOT_RECORDED, zone=Zone.INFERRED)
                if record[key] is None
                else Value.known(record[key], zone=Zone.INFERRED)
            ),
        )
        for key in sorted(record)
        if key not in _META_KEYS
    )


def _span_view(verdict: SpanVerdict) -> SpanView:
    text, at, quote = verdict.source_text, verdict.found_at, verdict.quote
    if text is None or at is None or quote is None:
        return SpanView(verdict=verdict)
    start = max(0, at - CONTEXT_CHARS)
    end = min(len(text), at + len(quote) + CONTEXT_CHARS)
    return SpanView(
        verdict=verdict,
        before=text[start:at],
        quote_in_source=text[at : at + len(quote)],
        after=text[at + len(quote) : end],
        truncated_before=start > 0,
        truncated_after=end < len(text),
    )


def _history(conn: sqlite3.Connection, task: Task) -> tuple[int, int]:
    """``(times_proposed, times_rejected)`` for this exact proposal.

    Keyed on `proposal_hash`, which `queue.proposal_hash` computes over the record with character
    offsets stripped -- so a re-extraction that shifts a span by one character is still recognised
    as the same proposal rather than looking new.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected "
        "FROM curation_task WHERE proposal_hash = ?",
        (task.proposal_hash,),
    ).fetchone()
    if row is None:
        return 1, 0
    return int(row["n"] or 1), int(row["rejected"] or 0)


def _proposed_strain_names(conn: sqlite3.Connection, publication_id: str) -> frozenset[str]:
    """Every strain name this publication has proposed, in any task state."""
    rows = conn.execute(
        "SELECT payload FROM curation_task WHERE publication_id = ? AND record_kind = 'strains'",
        (publication_id,),
    ).fetchall()
    names: set[str] = set()
    for row in rows:
        loaded: Any = json.loads(str(row["payload"]))
        if isinstance(loaded, dict):
            reported = loaded.get("name_as_reported")
            if isinstance(reported, str):
                names.add(reported.strip())
    return frozenset(names)


def _strain_warning(
    conn: sqlite3.Connection, task: Task, record: Mapping[str, Any]
) -> Warning_ | None:
    """Whether a measurement's strain was proposed at all by this publication.

    Promotion blocks on the strain not being *promoted*, which a curator can fix by promoting it.
    This is the worse case: the strain was never *proposed*, so no amount of reviewing produces
    it, and the measurement can never acquire a subject without a new extraction or a hand-written
    record. Worth knowing before accepting the measurement, not after.
    """
    name = str(record.get("strain_name_as_reported") or "").strip()
    if not name:
        return None
    proposed = _proposed_strain_names(conn, task.publication_id)
    if name in proposed:
        return None
    return Warning_(
        "strain_never_proposed",
        f"no strain proposal in this publication names {name!r} "
        f"({len(proposed)} strain(s) were proposed) -- this measurement has no subject to "
        "attach to, and reviewing cannot create one",
    )


def _better_anchored(
    conn: sqlite3.Connection, task: Task, record: Mapping[str, Any]
) -> Warning_ | None:
    """Another pending proposal reporting the same number against a strain that *was* proposed.

    This is the companion to `strain_never_proposed`, and it exists because that warning on its
    own leaves a curator stuck: the measurement cannot acquire a subject, but rejecting it might
    lose the number. If the same value is already proposed elsewhere with a real strain name, the
    number is not at risk and rejecting is the clean move.

    Matched on (product, quantity kind, value, unit) within one publication -- the same number
    reported twice about the same product in the same paper is the same result, whatever sentence
    it was read from. It is reported as an alternative to look at, never as an instruction: which
    of two records is better evidenced is the curator's call, not this function's.
    """
    value, unit = record.get("value"), record.get("unit")
    if value is None or unit is None:
        return None
    rows = conn.execute(
        "SELECT id, payload FROM curation_task WHERE publication_id = ? AND record_kind = ? "
        "AND status = 'pending' AND id <> ?",
        (task.publication_id, task.record_kind, task.id),
    ).fetchall()
    proposed = _proposed_strain_names(conn, task.publication_id)
    for row in rows:
        loaded: Any = json.loads(str(row["payload"]))
        if not isinstance(loaded, dict):
            continue
        if (loaded.get("value"), loaded.get("unit")) != (value, unit):
            continue
        if loaded.get("product_id") != record.get("product_id"):
            continue
        if loaded.get("quantity_kind") != record.get("quantity_kind"):
            continue
        other = str(loaded.get("strain_name_as_reported") or "").strip()
        if other and other in proposed:
            return Warning_(
                "alternative_with_known_strain",
                f"{row['id']} reports the same {value} {unit} against {other!r}, a strain this "
                "publication did propose -- so the number is not lost if this record is rejected",
            )
    return None


def _warnings(
    conn: sqlite3.Connection,
    task: Task,
    record: Mapping[str, Any],
    span: SpanView,
    plan: PromotionPlan,
    times_rejected: int,
) -> tuple[Warning_, ...]:
    found: list[Warning_] = []
    if not span.resolves:
        found.append(Warning_("span_unverified", span.verdict.detail))
    if times_rejected:
        found.append(
            Warning_(
                "previously_rejected",
                f"a curator rejected this exact proposal {times_rejected} time(s) before; "
                "accepting it now reverses that decision",
            )
        )
    if task.record_kind == "measurements":
        strain = _strain_warning(conn, task, record)
        if strain is not None:
            found.append(strain)
            alternative = _better_anchored(conn, task, record)
            if alternative is not None:
                found.append(alternative)
    if plan.target_table is None and task.status in {"accepted", "edited"}:
        found.append(
            Warning_(
                "no_promoter",
                f"nothing can write a {task.record_kind!r} record into a table yet, so accepting "
                "this leaves it in the queue",
            )
        )
    return tuple(found)


def review_packet(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    settings: Settings | None = None,
    supplied: Mapping[str, Any] | None = None,
) -> ReviewPacket:
    """Assemble the packet for one task. Reads only."""
    settings = settings or Settings.load()
    task = get_task(conn, task_id)
    record = _record(task)

    verdict = verify_span(conn, settings, task)
    span = _span_view(verdict)
    plan = plan_promotion(conn, task, settings=settings, supplied=supplied)
    times_proposed, times_rejected = _history(conn, task)

    return ReviewPacket(
        task_id=task.id,
        record_kind=task.record_kind,
        record_path=task.record_path,
        status=task.status,
        citation=Cited(
            payload=task.record_path,
            source_kind="publication",
            source_id=task.publication_id,
            locator=str(record.get("source_locator") or record.get("span", {}).get("section"))
            or None,
        ),
        fields=_fields(record),
        model_confidence=(
            Value.known(str(record["confidence"]), zone=Zone.INFERRED)
            if record.get("confidence")
            else Value.absent(Absence.NOT_RECORDED, zone=Zone.INFERRED)
        ),
        span=span,
        plan=plan,
        warnings=_warnings(conn, task, record, span, plan, times_rejected),
        times_proposed=times_proposed,
        times_rejected=times_rejected,
    )


def review_queue(
    conn: sqlite3.Connection,
    *,
    limit: int = 5,
    kinds: Sequence[str] | None = None,
    settings: Settings | None = None,
    supplied: Mapping[str, Any] | None = None,
) -> tuple[ReviewPacket, ...]:
    """Packets for the next tasks a curator would see, in queue order.

    Uses `queue.peek`, which takes no lease: looking at what is waiting is not starting work on
    it, and a listing that claimed tasks would strand one every time somebody checked the queue.
    """
    settings = settings or Settings.load()
    return tuple(
        review_packet(conn, task.id, settings=settings, supplied=supplied)
        for task in peek(conn, limit=limit, kinds=kinds)
    )
