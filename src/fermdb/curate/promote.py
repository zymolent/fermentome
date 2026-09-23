"""Turning an accepted proposal into a row. The step that was missing.

`queue.py` is explicit that accepting a task does not create data:

    This marks the task accepted and records who, when and why. It writes nothing into Zone R or
    Zone H: turning an accepted proposal into an assertion is a separate curator action, and
    collapsing the two would mean "accept" silently created canonical data.

That separation is right. The problem was that the separate action did not exist. Nothing in
`src/` wrote `measurement`, `strain`, `modification`, `condition_context`, `bottleneck` or
`experiment` -- only tests did -- so the pipeline ran extract -> curation_task -> accept -> *stop*.
A curator could have worked through all 55 pending proposals and every one of those tables would
still have been empty at the end, with nothing anywhere reporting that the work had not landed.

This module is that action. Four properties are worth stating, because each is a decision:

**1. The span is re-verified, and a proposal whose span no longer resolves is not promotable.**
Every payload carries a verbatim quote with character offsets into the source. Promotion re-reads
the stored full text and checks that the quote is still at those offsets. This is the last moment
at which that check is cheap: afterwards the number is a row in `measurement` that looks exactly
like a number anyone verified. A proposal that fails here is refused, not downgraded.

**2. What the payload cannot supply is named, never invented.** `strain.organism_id` is NOT NULL
and the extraction schema has no organism field at all -- the species is in the quoted sentence
("S. cerevisiae CKY263") and nowhere structured. So promotion refuses and says which field it
needs, and the curator supplies it. That is what a curator is *for*; a default of "probably
S. cerevisiae" would be a fact nobody checked, written into Zone R, indistinguishable afterwards
from one that was.

**3. Dependencies are refused, not skipped.** A measurement names its strain by name
(`strain_name_as_reported`), and `measurement` requires one of sample/strain/experiment. If the
strain has not been promoted yet, the measurement is blocked with that reason rather than written
with a NULL subject. Resolution is scoped to the **same publication**: two papers using "BSW191"
may or may not mean the same construction, and guessing across papers is the error CONVENTIONS.md
forbids in its identifier rules.

**4. Promotion is idempotent, and its ids are derived rather than random.** A strain's id comes
from its canonical name (`YAA:STRAIN:cen-pk113-7d`, exactly as CONVENTIONS.md writes it), so two
papers reporting CEN.PK113-7D converge on one row; a measurement's comes from the task's
`proposal_hash`, so re-promoting writes nothing new. The consequence for strains is deliberate and
has a known limit: same name means same strain here. If one turns out to be two, CONVENTIONS.md's
rule applies -- the id is retired with pointers to both, which is a curator action and not
something this module may do on its own.

Zone R is the destination. An extraction is Zone I because a model produced it; once a person has
read the span and agreed, the row records what the source stated, which is the definition of R
(PLAN.md D.2). The evidence string names the publication, the task and the curator, so the J.5
chain from row back to sentence stays readable by a person.

**And, since schema v12, the publication is also a column.** It was only ever the sentence, and a
sentence is not a join: `curate/assertions.py` could not close J.5's last hop for a
measurement-backed `evidence_item`, because the walk needs measurement -> publication to be a
foreign key. `curation_task.publication_id` is NOT NULL, so this module had the paper in hand at
every promotion and was dropping it on the floor -- the same "recorded faithfully and never wired
to anything that reads it" failure the migrations module keeps finding. `measurement` and
`bottleneck` now carry it; `modification` always did.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from ..config import Settings
from ..extract.schemas import MISSING_CHOICES
from .genotype import parse_genotype
from .queue import CurationError, Curator, Task, get_task

__all__ = [
    "PROMOTABLE_KINDS",
    "NotPromotable",
    "PromotionPlan",
    "PromotionResult",
    "Requirement",
    "SpanVerdict",
    "plan_promotion",
    "promote",
    "promote_ready",
    "verify_span",
]

#: Statuses a task must be in before it may become a row. 'pending' means nobody has looked.
_RESOLVED_STATUSES: Final[frozenset[str]] = frozenset({"accepted", "edited"})

#: `strain.class` is a closed set. A role outside it becomes NULL -- never 'unknown', which means
#: "recorded but unresolvable" and would be a different claim from "the paper did not say".
_STRAIN_CLASSES: Final[frozenset[str]] = frozenset(
    {"laboratory", "industrial", "wild", "engineered", "evolved", "unknown"}
)


class NotPromotable(CurationError):
    """A task cannot become a row yet, and the plan says exactly why."""


@dataclass(frozen=True)
class Requirement:
    """A column the row needs and the payload cannot supply."""

    field: str
    why: str

    def __str__(self) -> str:
        return f"{self.field}: {self.why}"


@dataclass(frozen=True)
class PromotionPlan:
    """What promoting one task would write, and what stands in the way."""

    task_id: str
    record_kind: str
    target_table: str | None
    row: Mapping[str, Any] = field(default_factory=dict)
    missing: tuple[Requirement, ...] = ()
    blockers: tuple[str, ...] = ()
    already: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.target_table is not None
            and not self.missing
            and not self.blockers
            and self.already is None
        )

    @property
    def note(self) -> str:
        # Blockers first. A task that is still 'pending' also has no target table, and reporting
        # "no promoter for kind 'strains'" would send a curator to fix the wrong thing -- the
        # kind is promotable, the task simply has not been reviewed.
        if self.blockers:
            return "; ".join(self.blockers)
        if self.target_table is None:
            return f"no promoter for record kind {self.record_kind!r} yet"
        if self.already is not None:
            return f"already promoted as {self.already}"
        if self.missing:
            return "needs " + "; ".join(str(m) for m in self.missing)
        return f"ready to write {self.target_table}"

    def as_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "record_kind": self.record_kind,
            "target_table": self.target_table,
            "ready": self.ready,
            "note": self.note,
            "missing": [{"field": m.field, "why": m.why} for m in self.missing],
            "blockers": list(self.blockers),
            "already": self.already,
        }


@dataclass(frozen=True)
class PromotionResult:
    """One promotion that happened."""

    task_id: str
    target_table: str
    row_id: str
    event_id: str
    created: bool


# ------------------------------------------------------------------------------- span checking


def _payload_of(task: Task) -> Mapping[str, Any]:
    """The curator's corrected record if there is one, otherwise the model's.

    An 'edited' verdict means the curator wrote down what was actually true, so that is what gets
    promoted. `queue.edit` keeps the model's original in `payload` either way, for the prompt-bug
    analysis its docstring describes.
    """
    raw = task.edited_payload_json or task.payload_json
    loaded: Any = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True)
class SpanVerdict:
    """Whether a proposal's quote still resolves against the source, and what went wrong if not.

    One implementation, used both by promotion (which gates on ``ok``) and by the review packet
    (which shows ``detail`` and the surrounding text). Two implementations would eventually
    disagree, and that failure mode is the bad one: a reviewer told the span is fine, promotion
    refusing it afterwards, and nobody able to see why.
    """

    ok: bool
    status: str
    detail: str
    quote: str | None = None
    start: int | None = None
    end: int | None = None
    found_at: int | None = None
    source_text: str | None = None

    @property
    def is_anchored(self) -> bool:
        """Whether there is a quote and offsets at all, whatever they resolve to."""
        return self.quote is not None and self.start is not None


def verify_span(conn: sqlite3.Connection, settings: Settings, task: Task) -> SpanVerdict:
    """Does the payload's quote still sit at its recorded offsets?

    ``load_source_text`` is imported inside the function rather than at module scope:
    `extract.harness` imports from `curate`, and a top-level import would close the cycle.
    """
    from ..extract.harness import load_source_text

    span = _payload_of(task).get("span")
    if not isinstance(span, Mapping):
        return SpanVerdict(
            False, "unanchored", "the record carries no span, so nothing ties it to the source"
        )
    quote = span.get("quote")
    start, end = span.get("char_start"), span.get("char_end")
    if not isinstance(quote, str) or not quote.strip():
        return SpanVerdict(False, "unanchored", "the span has no quoted text")
    if not isinstance(start, int) or not isinstance(end, int):
        return SpanVerdict(False, "unanchored", "the span has no character offsets", quote=quote)

    try:
        text, _ = load_source_text(conn, settings, publication_id=task.publication_id)
    except Exception as exc:  # the source may be absent, unreadable, or not stored at all
        return SpanVerdict(
            False,
            "unreadable",
            f"the source text could not be read ({exc})",
            quote=quote,
            start=start,
            end=end,
        )

    if text[start:end] == quote:
        return SpanVerdict(
            True,
            "verified",
            f"quote re-resolved at [{start}, {end})",
            quote=quote,
            start=start,
            end=end,
            found_at=start,
            source_text=text,
        )
    if quote in text:
        where = text.index(quote)
        return SpanVerdict(
            False,
            "moved",
            f"the quote is in the source but at [{where}, {where + len(quote)}), "
            f"not the recorded [{start}, {end}) -- the offsets are stale",
            quote=quote,
            start=start,
            end=end,
            found_at=where,
            source_text=text,
        )
    return SpanVerdict(
        False,
        "absent",
        "the quoted text is not in the source document at all",
        quote=quote,
        start=start,
        end=end,
        source_text=text,
    )


def _verify_span(conn: sqlite3.Connection, settings: Settings, task: Task) -> tuple[bool, str]:
    verdict = verify_span(conn, settings, task)
    return verdict.ok, verdict.detail


# ------------------------------------------------------------------------------------ id rules


def _slug(value: str) -> str:
    """``CEN.PK113-7D`` -> ``cen-pk113-7d``, the form CONVENTIONS.md writes."""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _strain_id(name: str) -> str:
    return f"YAA:STRAIN:{_slug(name)}"


def _stable_digest(text: str) -> str:
    """A deterministic 16-hex id fragment. `hash()` is salted per process and would not do."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _measurement_id(task: Task) -> str:
    """Derived from the proposal hash, so re-promoting the same proposal is a no-op."""
    return f"YAA:MEAS:{task.proposal_hash[:16]}"


def _evidence(task: Task, span_detail: str, curator: Curator) -> str:
    """The J.5 chain in one string: publication, task, span, and who agreed."""
    return (
        f"promoted from curation task {task.id} on {task.publication_id} "
        f"({task.record_path}); {span_detail}; curator {curator.name}"
    )


# ----------------------------------------------------------------------------------- promoters


def _plan_strain(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    payload = _payload_of(task)
    name = str(payload.get("name_as_reported") or "").strip()
    missing: list[Requirement] = []
    if not name:
        missing.append(Requirement("canonical_name", "the record names no strain"))

    organism = supplied.get("organism_id")
    if not organism:
        missing.append(
            Requirement(
                "organism_id",
                "NOT NULL on `strain`, and the extraction schema has no organism field -- "
                "the species is in the quoted sentence and nowhere structured, so a curator "
                "supplies it",
            )
        )
    elif conn.execute("SELECT 1 FROM organism WHERE id = ?", (organism,)).fetchone() is None:
        missing.append(Requirement("organism_id", f"no organism with id {organism!r}"))

    role = str(payload.get("role") or "").strip().lower()
    strain_id = _strain_id(name) if name else ""
    already = None
    if strain_id:
        row = conn.execute("SELECT id FROM strain WHERE id = ?", (strain_id,)).fetchone()
        already = str(row["id"]) if row is not None else None

    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="strain",
        row={
            "id": strain_id,
            "organism_id": organism,
            "canonical_name": name,
            # Outside the closed set means "the paper said something we do not model", which is
            # not the same as 'unknown' and is therefore NULL.
            "class": role if role in _STRAIN_CLASSES else None,
            "genotype_as_reported": payload.get("genotype_as_reported") or None,
        },
        missing=tuple(missing),
        already=already,
    )


def _plan_measurement(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    payload = _payload_of(task)
    missing: list[Requirement] = []
    blockers: list[str] = []

    value = payload.get("value")
    unit = payload.get("unit") or payload.get("unit_canonical")
    kind = str(payload.get("quantity_kind") or "").strip()
    if not isinstance(value, int | float):
        missing.append(Requirement("value_as_reported", "the record carries no numeric value"))
    if not unit:
        missing.append(Requirement("unit_as_reported", "the record carries no unit"))
    if not kind:
        missing.append(Requirement("quantity_kind", "the record does not say what was measured"))

    product_id = payload.get("product_id") or supplied.get("product_id")
    if product_id and (
        conn.execute("SELECT 1 FROM product WHERE id = ?", (product_id,)).fetchone() is None
    ):
        missing.append(
            Requirement("product_id", f"no product with id {product_id!r}; load the vocabularies")
        )

    # A yield without a basis is not comparable to any other yield, and `measurement` refuses it.
    basis = payload.get("basis") or supplied.get("basis")
    if kind == "yield" and not basis:
        missing.append(
            Requirement(
                "basis",
                "a yield must say g/g-consumed or g/g-supplied; the schema forbids NULL here "
                "because papers report both without saying which",
            )
        )

    # The subject. `measurement` requires one of sample/strain/experiment, and the record names
    # its strain by name only.
    strain_name = str(payload.get("strain_name_as_reported") or "").strip()
    strain_id: str | None = supplied.get("strain_id")
    if strain_id is None and strain_name:
        candidate = _strain_id(strain_name)
        row = conn.execute("SELECT id FROM strain WHERE id = ?", (candidate,)).fetchone()
        if row is not None:
            strain_id = str(row["id"])
        else:
            blockers.append(
                f"strain {strain_name!r} is not promoted yet (would be {candidate}); "
                "promote the strain proposals from this publication first"
            )
    if strain_id is None and not strain_name:
        missing.append(
            Requirement(
                "strain_id",
                "`measurement` needs a sample, strain or experiment and the record names none",
            )
        )

    row_id = _measurement_id(task)
    existing = conn.execute("SELECT id FROM measurement WHERE id = ?", (row_id,)).fetchone()

    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="measurement",
        row={
            "id": row_id,
            "strain_id": strain_id,
            # The task names its paper in a NOT NULL column, so the promoter has always had this
            # and used to drop it, leaving `evidence` prose as the only record. Prose is not a
            # join, and PLAN.md J.5's last hop is a join (schema v12).
            "publication_id": task.publication_id,
            "quantity_kind": kind,
            "product_id": product_id,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "basis": basis,
            "source_locator": str(payload.get("source_locator") or "text"),
            "is_below_lod": 1 if payload.get("is_below_lod") else 0,
            "is_upper_bound": 1 if payload.get("is_upper_bound") else 0,
            # Carried so `_write_measurement` can hang a `sample` off it. NOT a measurement
            # column -- see `_sample_for`.
            "time_h": _timepoint(payload),
        },
        missing=tuple(missing),
        blockers=tuple(blockers),
        already=str(existing["id"]) if existing is not None else None,
    )


def _write_strain(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    before = conn.total_changes
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence) "
        "VALUES (?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["organism_id"],
            plan.row["canonical_name"],
            plan.row["class"],
            evidence,
            confidence,
        ),
    )
    created = conn.total_changes > before
    _write_genotype(conn, plan, evidence=evidence, confidence=confidence)
    return created


def _write_genotype(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> None:
    """Store the reported genotype and its parse, if the record carried one.

    ``as_reported`` is Zone R and copied untouched. ``parsed_json`` is Zone H -- derived from it
    by `curate.genotype`, rebuildable, and carrying its own unparsed tokens so a partial parse
    cannot pass for a complete one. The row itself is filed Zone R because its NOT NULL content
    is the reported string; the derived column says what it is.
    """
    reported = plan.row.get("genotype_as_reported")
    if not reported:
        return
    parsed = parse_genotype(str(reported))
    conn.execute(
        "INSERT INTO genotype (id, strain_id, as_reported, parsed_json, zone, evidence, "
        "confidence) VALUES (?,?,?,?,'R',?,?) ON CONFLICT(id) DO UPDATE SET "
        "as_reported=excluded.as_reported, parsed_json=excluded.parsed_json",
        (
            f"YAA:GENOTYPE:{str(plan.row['id']).split(':')[-1]}",
            plan.row["id"],
            str(reported),
            json.dumps(parsed.as_json(), ensure_ascii=False, sort_keys=True),
            evidence,
            confidence,
        ),
    )


def _timepoint(payload: Mapping[str, Any]) -> float | None:
    """The hour the reading was taken, if the paper stated one. Never inferred.

    `extract/schemas.py` asks for `time_h` on every measurement and 43% of the phase-1 batch
    carries one. Anything unparseable returns None rather than a guess: a wrong timepoint is worse
    than no timepoint, because it looks like a measured fact.
    """
    raw = payload.get("time_h")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return None
    return hours if hours >= 0 else None


def _sample_for(conn: sqlite3.Connection, plan: PromotionPlan) -> str | None:
    """The `sample` a timed measurement hangs off, created if this is the first at that hour.

    **Why a sample and not a column on `measurement`.** Until now the timepoint was read,
    transported and dropped at this exact line, and the atlas holds the consequence: BSW205 with a
    titer of 1.62 g/L and another of 230 mg/L, same strain, same paper, same locator, nothing to
    tell them apart. They are 24 h and 48 h of one fermentation, and isobutanol is volatile, so
    the paper is consistent and the atlas lost the fact that makes it so.

    The schema already models this correctly and `measurement` is not where it goes: `sample`
    carries `time_h`, because a timepoint is a property of **the sample drawn**, not of the
    condition the culture was grown under -- 24 h and 48 h share one `condition_context`. Adding
    `measurement.time_h` would give the schema two homes for one fact and they would drift.

    `condition_context_id` is left NULL, and that is allowed rather than sloppy: the column is
    nullable, and CONVENTIONS' "no sample enters a contrast without an approved condition context"
    governs **contrasts**, not a sample's existence. Filling it is the next iteration's job.

    This is the chassis only. It preserves a fact that was being destroyed, so that the richer
    `condition_context` work can be done later against real rows instead of re-derived from spans.
    """
    time_h = plan.row.get("time_h")
    strain_id = plan.row.get("strain_id")
    if time_h is None or not strain_id:
        return None

    # Deterministic, like every other id here: promoting two measurements from one paper at one
    # hour on one strain must reuse the sample, not make a second.
    digest = _stable_digest(f"{plan.row['publication_id']}|{strain_id}|{time_h}")
    sample_id = f"YAA:SAMPLE:{digest}"
    conn.execute(
        "INSERT INTO sample (id, strain_id, time_h, zone, evidence, confidence) "
        "VALUES (?,?,?,'R',?,'medium') ON CONFLICT(id) DO NOTHING",
        (
            sample_id,
            strain_id,
            time_h,
            f"the {time_h} h reading of {strain_id} in {plan.row['publication_id']}, from the "
            f"paper's own stated timepoint; condition_context not yet curated",
        ),
    )
    return sample_id


def _write_measurement(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    sample_id = _sample_for(conn, plan)
    conn.execute(
        "INSERT INTO measurement (id, sample_id, strain_id, publication_id, quantity_kind, "
        "product_id, value_as_reported, unit_as_reported, basis, source_locator, is_below_lod, "
        "is_upper_bound, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            sample_id,
            plan.row["strain_id"],
            plan.row["publication_id"],
            plan.row["quantity_kind"],
            plan.row["product_id"],
            plan.row["value_as_reported"],
            plan.row["unit_as_reported"],
            plan.row["basis"],
            plan.row["source_locator"],
            plan.row["is_below_lod"],
            plan.row["is_upper_bound"],
            evidence,
            confidence,
        ),
    )
    return conn.total_changes > 0


#: `data/vocabularies/modification_types.tsv` defines 16 types; `modification.type`'s CHECK
#: accepts 9, and they are not the same 9. The curated file is the richer of the two and, per
#: CONVENTIONS.md, is the source of truth for a vocabulary -- so the table is the one that is
#: wrong, and widening it is a migration plus a curation decision that belongs to the owner.
#:
#: Only unambiguous pairs are mapped here. The rest are refused by name rather than collapsed
#: into 'other': a `type` column where 'other' covers nine different kinds of change is a
#: controlled vocabulary that has stopped controlling anything, and what was lost would survive
#: only in a free-text `details` nobody can query.
_MODIFICATION_TYPES: Final[Mapping[str, str]] = {
    "knockout": "deletion",
    "knockdown": "downregulation",
    "overexpression": "overexpression",
    "promoter_replacement": "promoter_swap",
    "heterologous_expression": "heterologous_insertion",
    "localization_change": "localization_change",
    "other": "other",
}

#: `bottleneck.observation_type` is NOT NULL and closed, and **the extraction schema has no field
#: that maps onto it**. The payload's `support` records how a *claim* is supported
#: (stated_by_authors / inferred_from_data / NA / unknown); `observation_type` records what kind of
#: *observation* the bottleneck rests on. Different axes, no overlap.
#:
#: An earlier version of this module tested `support in _OBSERVATION_TYPES` and would therefore
#: have refused every bottleneck forever, with a message implying the payload could have supplied
#: the value. It never could. Like `strain.organism_id`, this is a column only a curator can fill.
_OBSERVATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "metabolite_accumulation",
        "flux_measurement",
        "overexpression_relieved",
        "deletion_worsened",
        "in_vitro_kinetics",
        "inferred",
    }
)


def _modification_details(payload: Mapping[str, Any], reported_type: str) -> str:
    """The paper's own words for what changed, including its term for the change itself.

    The reported type travels even when it mapped cleanly: 'deletion' and 'knockout' are the same
    fact in two vocabularies, and only one of them is the paper's.
    """
    bits = [f"as reported: {reported_type}"] if reported_type else []
    for key in ("detail_as_reported", "compartment", "encoding_genome"):
        value = payload.get(key)
        if value:
            bits.append(f"{key}: {value}")
    return "; ".join(bits)


def _plan_modification(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    payload = _payload_of(task)
    missing: list[Requirement] = []
    blockers: list[str] = []

    reported_type = str(payload.get("modification_type") or "").strip()
    mapped = _MODIFICATION_TYPES.get(reported_type) or supplied.get("type")
    if not reported_type:
        missing.append(Requirement("type", "the record does not say what kind of change it is"))
    elif mapped is None:
        missing.append(
            Requirement(
                "type",
                f"the extraction vocabulary has {reported_type!r} and the table's CHECK does "
                "not; mapping it to 'other' would hide it, so this needs either a widened CHECK "
                "or an explicit type from a curator",
            )
        )

    target = str(payload.get("target_as_reported") or "").strip()
    if not target:
        missing.append(Requirement("target_locus", "the record names nothing that was changed"))

    strain_name = str(payload.get("strain_name_as_reported") or "").strip()
    strain_id: str | None = supplied.get("strain_id")
    if strain_id is None and strain_name:
        row = conn.execute(
            "SELECT id FROM strain WHERE id = ?", (_strain_id(strain_name),)
        ).fetchone()
        if row is not None:
            strain_id = str(row["id"])
        else:
            blockers.append(
                f"strain {strain_name!r} is not promoted yet (would be {_strain_id(strain_name)})"
            )

    # PLAN.md I.4's honesty field. `supplied` carries 'yes'/'no' rather than 1/0 so that the
    # absent case survives `cmd_curate_promote`'s `if v` filter -- 0 is falsy, and a curator who
    # answered "no" must not have their answer silently dropped and re-read as "not recorded".
    isolated_raw = str(supplied.get("is_isolated_effect") or "").strip()
    isolated = {"yes": 1, "no": 0, "": None}.get(isolated_raw)
    if isolated_raw and isolated is None:
        blockers.append(f"--isolated-effect takes 'yes' or 'no', not {isolated_raw!r}")
    intent = str(supplied.get("intent") or "").strip() or None

    row_id = f"YAA:MOD:{task.proposal_hash[:16]}"
    existing = conn.execute("SELECT id FROM modification WHERE id = ?", (row_id,)).fetchone()
    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="modification",
        row={
            "id": row_id,
            "strain_id": strain_id,
            "type": mapped,
            "target_locus": target,
            "details": _modification_details(payload, reported_type),
            "publication_id": task.publication_id,
            # Both stay NULL unless a curator said otherwise. There is no inference available
            # here worth making: whether a change was made alone is a fact about the paper's
            # strain table, and the extraction payload holds one sentence about one change.
            "is_isolated_effect": isolated,
            "intent": intent,
        },
        missing=tuple(missing),
        blockers=tuple(blockers),
        already=str(existing["id"]) if existing is not None else None,
    )


def _plan_bottleneck(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    payload = _payload_of(task)
    missing: list[Requirement] = []

    node = str(payload.get("node_as_reported") or "").strip()
    if not node:
        missing.append(
            Requirement(
                "node",
                "`bottleneck` needs a reaction, a transport step or a node, and the record "
                "names none",
            )
        )

    # `support` travels into the evidence string rather than into observation_type: it says how
    # the claim is supported, which is a different question from what kind of observation it is.
    support = str(payload.get("support") or "").strip()
    observation = supplied.get("observation_type")
    if observation is None:
        missing.append(
            Requirement(
                "observation_type",
                "NOT NULL and closed to six values, and the extraction schema has no field that "
                f"maps onto it -- the record's `support` is {support or 'absent'!r}, which says "
                "how the claim is supported, not what kind of observation it rests on. A curator "
                "picks, because 'inferred' and 'flux_measurement' are very different evidence "
                "and the choice sets the level downstream",
            )
        )
    elif observation not in _OBSERVATION_TYPES:
        missing.append(
            Requirement(
                "observation_type", f"{observation!r} is not one of {sorted(_OBSERVATION_TYPES)}"
            )
        )

    row_id = f"YAA:BNK:{task.proposal_hash[:16]}"
    existing = conn.execute("SELECT id FROM bottleneck WHERE id = ?", (row_id,)).fetchone()
    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="bottleneck",
        row={
            "id": row_id,
            "node": node,
            "publication_id": task.publication_id,
            "observation_type": observation,
            "claim": str(payload.get("claim") or ""),
            "support": support,
            "intervention": str(payload.get("intervention_as_reported") or ""),
        },
        missing=tuple(missing),
        already=str(existing["id"]) if existing is not None else None,
    )


def _write_modification(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    before = conn.total_changes
    conn.execute(
        "INSERT INTO modification (id, strain_id, type, target_locus, details, publication_id, "
        "is_isolated_effect, intent, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["strain_id"],
            plan.row["type"],
            plan.row["target_locus"],
            plan.row["details"],
            plan.row["publication_id"],
            plan.row.get("is_isolated_effect"),
            plan.row.get("intent"),
            evidence,
            confidence,
        ),
    )
    return conn.total_changes > before


def _write_bottleneck(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    before = conn.total_changes
    detail = f"{evidence}; claim: {plan.row['claim']}"
    if plan.row.get("support"):
        detail += f"; support as reported: {plan.row['support']}"
    if plan.row["intervention"]:
        detail += f"; intervention: {plan.row['intervention']}"
    conn.execute(
        "INSERT INTO bottleneck (id, node, publication_id, observation_type, zone, evidence, "
        "confidence) VALUES (?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["node"],
            plan.row["publication_id"],
            plan.row["observation_type"],
            detail,
            confidence,
        ),
    )
    return conn.total_changes > before


#: The companion a co-reported higher alcohol must have been measured beside.
#:
#: PLAN.md B.1 admits the adjacent tier on one condition, and states the condition as the reason
#: for the tier's existence: these products are captured **"only when measured in the same
#: experiment as isobutanol -- they are the by-products of the same promiscuous ketoacid
#: decarboxylases and their ratios are diagnostic of where flux is leaking."** A lone isoamyl
#: alcohol titer is not diagnostic of anything; it is the *ratio* that measures decarboxylase
#: specificity, and a ratio needs both terms.
_ADJACENT_COMPANION: Final[str] = "YAA:PRODUCT:isobutanol"


def _plan_higher_alcohol(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    """An adjacent-tier alcohol becomes a `measurement`, if B.1's companion rule is satisfied.

    The record is shaped like a measurement and becomes one: same table, same id derivation, a
    different `product_id`. What is not shared is admission. B.1 lets this product in only when it
    was measured alongside isobutanol, so the companion is checked here rather than assumed -- and
    checked against the database, which is the only place that can answer it.

    **Scope of the check, stated because it is weaker than B.1's words.** B.1 says "the same
    experiment". `experiment` has no rows and no sample links to a publication yet, so the
    strongest available scope is the same *strain*, which these payloads do name. That is a real
    weakening: one paper can measure a strain under conditions that never appeared in the same run.
    It is recorded here rather than papered over, and tightens to the experiment the moment
    `experiment` is populated -- at which point this constant becomes a join, not a lookup.
    """
    payload = _payload_of(task)
    missing: list[Requirement] = []
    blockers: list[str] = []

    value = payload.get("value")
    unit = payload.get("unit") or payload.get("unit_canonical")
    kind = str(payload.get("quantity_kind") or "").strip()
    if not isinstance(value, int | float):
        missing.append(Requirement("value_as_reported", "the record carries no numeric value"))
    if not unit:
        missing.append(Requirement("unit_as_reported", "the record carries no unit"))
    if not kind:
        missing.append(Requirement("quantity_kind", "the record does not say what was measured"))

    # The product must exist *and* be adjacent-tier. Promoting an isobutanol titer through this
    # planner would bypass nothing, but promoting an ethanol one would file a reference-layer
    # number as an isobutanol by-product, which is a scope error the tier column now catches.
    reported_product = str(payload.get("product_as_reported") or "").strip()
    product_id = payload.get("product_id") or supplied.get("product_id")
    if not product_id:
        missing.append(
            Requirement(
                "product_id",
                f"the record names {reported_product or 'a higher alcohol'} and no product id; "
                "a curator maps it to one of the adjacent-tier products in products.tsv",
            )
        )
    else:
        row = conn.execute("SELECT tier FROM product WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            missing.append(
                Requirement(
                    "product_id", f"no product with id {product_id!r}; load the vocabularies"
                )
            )
        elif row["tier"] is None:
            blockers.append(
                f"{product_id} has no tier; re-run `fermdb db vocabularies` so B.1's admission "
                "rule has something to read (schema v10 added the column)"
            )
        elif row["tier"] != "adjacent":
            missing.append(
                Requirement(
                    "product_id",
                    f"{product_id} is {row['tier']}-tier, and this record kind carries B.1's "
                    "adjacent-tier admission rule. A primary or reference product measured in "
                    "this paper is an ordinary `measurements` proposal, not a co-reported one",
                )
            )

    strain_name = str(payload.get("strain_name_as_reported") or "").strip()
    strain_id: str | None = supplied.get("strain_id")
    if strain_id is None and strain_name:
        candidate = _strain_id(strain_name)
        row = conn.execute("SELECT id FROM strain WHERE id = ?", (candidate,)).fetchone()
        if row is not None:
            strain_id = str(row["id"])
        else:
            blockers.append(
                f"strain {strain_name!r} is not promoted yet (would be {candidate}); "
                "promote the strain proposals from this publication first"
            )
    if strain_id is None and not strain_name:
        missing.append(
            Requirement(
                "strain_id",
                "`measurement` needs a sample, strain or experiment and the record names none",
            )
        )

    # B.1's companion rule.
    if strain_id is not None:
        companion = conn.execute(
            "SELECT 1 FROM measurement WHERE strain_id = ? AND product_id = ?",
            (strain_id, _ADJACENT_COMPANION),
        ).fetchone()
        if companion is None:
            blockers.append(
                f"no isobutanol measurement is promoted for {strain_id}. PLAN.md B.1 admits an "
                "adjacent-tier alcohol only when it was measured alongside isobutanol, because "
                "the ratio is the diagnostic and a ratio needs both terms. Promote that "
                "publication's isobutanol measurements first"
            )

    row_id = _measurement_id(task)
    existing = conn.execute("SELECT id FROM measurement WHERE id = ?", (row_id,)).fetchone()
    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="measurement",
        row={
            "id": row_id,
            "strain_id": strain_id,
            "publication_id": task.publication_id,
            "quantity_kind": kind,
            "product_id": product_id,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "basis": payload.get("basis") or supplied.get("basis"),
            "source_locator": str(payload.get("source_locator") or "text"),
            "is_below_lod": 1 if payload.get("is_below_lod") else 0,
            "is_upper_bound": 1 if payload.get("is_upper_bound") else 0,
            # Carried into `evidence` by the writer. See its docstring for why it cannot go
            # anywhere better yet.
            "substrate": str(payload.get("substrate") or "").strip(),
            "product_as_reported": reported_product,
        },
        missing=tuple(missing),
        blockers=tuple(blockers),
        already=str(existing["id"]) if existing is not None else None,
    )


def _write_higher_alcohol(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    """Write the measurement, with the substrate in the evidence because it has nowhere else.

    The three 2-methyl-1-butanol titers this promoter was written against are the same strain, the
    same product and the same quantity kind, differing **only** by carbon source -- 0.91 on xylose,
    0.68 on glucose, 0.93 on galactose. The substrate is what distinguishes them, and it belongs in
    `condition_context`, which `PROMOTERS` deliberately cannot write because grouping facets into a
    context is a curation decision (see that mapping's docstring).

    Dropping it would leave three rows that are indistinguishable except by id -- the exact shape
    of the "recorded and never wired up" loss this module keeps finding. So it travels in
    `evidence`, which is prose and queryable only by LIKE, and is therefore a holding position and
    not a home. When a context exists for these measurements, the substrate moves to it.
    """
    before = conn.total_changes
    detail = evidence
    if plan.row.get("product_as_reported"):
        detail += f"; product as reported: {plan.row['product_as_reported']}"
    if plan.row.get("substrate"):
        detail += (
            f"; substrate as reported: {plan.row['substrate']} "
            "(no condition_context yet; this is what distinguishes it from its siblings)"
        )
    conn.execute(
        "INSERT INTO measurement (id, strain_id, publication_id, quantity_kind, product_id, "
        "value_as_reported, unit_as_reported, basis, source_locator, is_below_lod, "
        "is_upper_bound, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["strain_id"],
            plan.row["publication_id"],
            plan.row["quantity_kind"],
            plan.row["product_id"],
            plan.row["value_as_reported"],
            plan.row["unit_as_reported"],
            plan.row["basis"],
            plan.row["source_locator"],
            plan.row["is_below_lod"],
            plan.row["is_upper_bound"],
            detail,
            confidence,
        ),
    )
    return conn.total_changes > before


def _configuration_description(payload: Mapping[str, Any]) -> str:
    """The enzyme set and the localization claim, in the paper's own terms.

    `localization_as_reported` is where a curator's correction lands -- the one proposal this was
    written against carries a note that the enzymes are the bacterial valine *degradation* route
    and not the Ehrlich pathway the strategy is named for. That note is the most valuable thing in
    the record and it must not be dropped on the way into a row.
    """
    bits: list[str] = []
    enzymes = payload.get("enzymes_as_reported")
    if isinstance(enzymes, list | tuple) and enzymes:
        bits.append("enzymes as reported: " + ", ".join(str(e) for e in enzymes))
    localization = str(payload.get("localization_as_reported") or "").strip()
    if localization:
        bits.append(f"localization as reported: {localization}")
    return "; ".join(bits)


def _plan_configuration(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    """A published build becomes a `pathway_configuration`.

    This is phase 1's headline deliverable -- PLAN.md Q phase 1 asks for "every published microbial
    isobutanol production strain, any host, as a `pathway_configuration`" -- and phase 3's
    acceptance test is recall of the route enumerator *against these rows*. With no promoter the
    table stayed empty, so 600 enumerated routes had nothing to be scored against and phase 3 could
    not be tested even in principle.

    Two columns a payload cannot supply, refused rather than guessed, in the manner of
    `strain.organism_id` and `bottleneck.observation_type`:

    * `host_strain_id` -- the configuration's host is the difference between a yeast build and an
      *E. coli* one, and inferring it from whichever strain the paper mentions most is the
      cross-paper guessing CONVENTIONS.md forbids.

      **Correction, 2026-09-22.** This paragraph used to begin "the extraction schema has no host
      field", and that was false: `pathway_configurations` carries `strain_name_as_reported`
      ("Which strain this configuration belongs to, as written"), and 31 of the 46 configurations
      in the queue populate it. The refusal stands, but not for the reason given -- resolving that
      name would be an ordinary strain lookup, no different from the one `_plan_measurement` does.

      What actually keeps a configuration unpromotable is the *other* bullet, which is still
      true. So wiring the host up would move nothing: every configuration would refuse one line
      later on `product_id` instead. That is worth knowing before someone spends an afternoon on
      the host and finds the table still empty.
    * `product_id` -- likewise absent. A configuration is *for* a product, and defaulting it to
      isobutanol because this is an isobutanol atlas would file a 3-HP or n-butanol build as an
      isobutanol one.

    `name` is derived rather than demanded: a configuration's name is a label, not a claim, and a
    deterministic one built from the strategy and the publication is reproducible and collides with
    nothing. A curator may override it.
    """
    payload = _payload_of(task)
    missing: list[Requirement] = []
    blockers: list[str] = []

    strategy = str(payload.get("compartment_strategy") or "").strip()
    strategy_id: str | None = supplied.get("compartment_strategy_id") or (strategy or None)
    if not strategy:
        missing.append(
            Requirement(
                "compartment_strategy_id",
                "the record does not say which compartment strategy the build used, and the "
                "strategy is what a configuration is grouped and compared by (PLAN.md B.5)",
            )
        )
    elif (
        conn.execute("SELECT 1 FROM compartment_strategy WHERE id = ?", (strategy_id,)).fetchone()
        is None
    ):
        missing.append(
            Requirement(
                "compartment_strategy_id",
                f"{strategy_id!r} is not a seeded compartment strategy; the vocabulary is "
                "`compartment_strategy` and adding a strategy is a data change a curator makes",
            )
        )

    host_strain_id: str | None = supplied.get("host_strain_id")
    if host_strain_id is None:
        missing.append(
            Requirement(
                "host_strain_id",
                "the extraction schema carries no host field, and the host is what makes a "
                "configuration comparable to another one. A curator names the strain",
            )
        )
    elif conn.execute("SELECT 1 FROM strain WHERE id = ?", (host_strain_id,)).fetchone() is None:
        blockers.append(
            f"host strain {host_strain_id!r} is not promoted yet; promote that strain first"
        )

    product_id: str | None = supplied.get("product_id")
    if product_id is None:
        missing.append(
            Requirement(
                "product_id",
                "a configuration is a route *to* something, and the record does not say to what. "
                "Defaulting to isobutanol would file any other build as an isobutanol one",
            )
        )
    elif conn.execute("SELECT 1 FROM product WHERE id = ?", (product_id,)).fetchone() is None:
        missing.append(
            Requirement("product_id", f"no product with id {product_id!r}; load the vocabularies")
        )

    row_id = f"YAA:PCFG:{task.proposal_hash[:16]}"
    name = str(
        supplied.get("name")
        or (f"{strategy} configuration from {task.publication_id}" if strategy else row_id)
    )
    existing = conn.execute(
        "SELECT id FROM pathway_configuration WHERE id = ?", (row_id,)
    ).fetchone()
    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="pathway_configuration",
        row={
            "id": row_id,
            "name": name,
            "pathway_id": supplied.get("pathway_id"),
            "product_id": product_id,
            "compartment_strategy_id": strategy_id,
            "host_strain_id": host_strain_id,
            "description": _configuration_description(payload),
        },
        missing=tuple(missing),
        blockers=tuple(blockers),
        already=str(existing["id"]) if existing is not None else None,
    )


def _write_configuration(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    before = conn.total_changes
    conn.execute(
        "INSERT INTO pathway_configuration (id, name, pathway_id, product_id, "
        "compartment_strategy_id, host_strain_id, description, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["name"],
            plan.row["pathway_id"],
            plan.row["product_id"],
            plan.row["compartment_strategy_id"],
            plan.row["host_strain_id"],
            plan.row["description"],
            evidence,
            confidence,
        ),
    )
    return conn.total_changes > before


#: The two closed sets `part_expression_record` uses, copied from its CHECK constraints.
#:
#: They are deliberately different: `expressed_ok` has 'partial' and `activity_measured` does not,
#: because a protein can appear in a truncated or partly-soluble form while "we assayed what it
#: does" has no half-way. The extraction section offers exactly these choices for the same reason.
#:
#: **Neither has room for 'NA'**, and that is the table's gap rather than the payload's.
#: `extract.schemas._choice` appends both recorded-missing answers to every enum, so a model can
#: legitimately answer 'NA' to either -- and there is nowhere to put it. See
#: :func:`_closed_outcome` for what happens then, and why it is a refusal and not a NULL.
_EXPRESSED_OK: Final[frozenset[str]] = frozenset({"yes", "no", "partial", "unknown"})
_ACTIVITY_MEASURED: Final[frozenset[str]] = frozenset({"yes", "no", "unknown"})


def _vocabulary_value(raw: Any) -> str | None:
    """A controlled payload answer, or None where it names no value at all.

    'NA' and 'unknown' collapse to None **only for columns that are foreign keys**, where there
    is no row to point at for either. What is lost is recovered in the evidence string by the
    caller -- CONVENTIONS.md forbids collapsing the three missing states into each other, and a
    silent NULL here would turn "the paper said the compartment and we could not resolve it" into
    "the paper never said".
    """
    value = str(raw or "").strip()
    return value if value and value not in MISSING_CHOICES else None


def _closed_outcome(
    raw: Any, allowed: frozenset[str], column: str
) -> tuple[str | None, str | None]:
    """Map one payload answer onto a closed column, returning ``(value, why_not)``.

    Absent is NULL: the source never said, which the column expresses. 'unknown' passes straight
    through because both CHECKs accept it and it means precisely what CONVENTIONS.md says.

    'NA' is refused. Writing NULL instead would collapse "recorded as not applicable" into "never
    recorded", and the two are different claims about the paper; writing 'unknown' would collapse
    it the other way. The honest answer is that this column cannot hold the value, which a curator
    can act on -- by correcting the record if 'NA' was a model error, or by asking for the CHECK to
    be widened if it was not. Silently storing something else is how the distinction dies.
    """
    value = str(raw or "").strip()
    if not value:
        return None, None
    if value in allowed:
        return value, None
    if value == "NA":
        return None, (
            f"the record answers 'NA' and `part_expression_record.{column}`'s CHECK accepts only "
            f"{sorted(allowed)}. Storing NULL would say the paper never mentioned it and "
            "'unknown' would say it did and could not be resolved -- both are claims the record "
            "does not make. Either the record is wrong and a curator should edit it, or the "
            "column needs widening, which is a migration and an owner's decision"
        )
    return None, f"{value!r} is not one of {sorted(allowed)}"


def _part_expression_detail(payload: Mapping[str, Any], derived_genome: str | None) -> str:
    """Everything true of this record that has no column of its own.

    Three things ride here. The part and the host **as reported** (the row holds a curator's
    resolution of each, and the paper's own wording is Zone R and not rebuildable from the id);
    the paper's phrasing of the localization, which is where the targeting method lives -- "via
    the Su9 presequence" is the difference between a construct that needs recoding and one that
    does not, and no column holds it; and, where it happened, the fact that `encoding_genome` was
    **derived from the pairing table rather than read from the paper**, so the row does not look
    like it is quoting a source that never said it.
    """
    bits: list[str] = []
    for key, label in (
        ("part_as_reported", "part as reported"),
        ("host_as_reported", "host as reported"),
        ("compartment_as_reported", "compartment as reported"),
        ("promoter_as_reported", "promoter as reported"),
        ("outcome_as_reported", "outcome as reported"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            bits.append(f"{label}: {value}")
    # 'unknown'/'NA' never reach a FK column, so say so here rather than lose it.
    stated = str(payload.get("compartment") or "").strip()
    if stated in MISSING_CHOICES:
        bits.append(f"compartment answered {stated!r}, which is not a compartment row")
    if derived_genome is not None:
        bits.append(
            f"encoding_genome {derived_genome!r} derived from compartment_encoding_genome, not "
            "stated by the paper: it is the only genome that can encode a protein in this "
            "compartment"
        )
    return "; ".join(bits)


def _plan_part_expression(
    conn: sqlite3.Connection, task: Task, supplied: Mapping[str, Any]
) -> PromotionPlan:
    """A demonstrated host x compartment becomes a `part_expression_record`.

    PLAN.md G.6 calls the expression records *"the field that makes the catalog worth having"*:
    `part` can say an enzyme exists, and only these rows can say whether anyone has ever got it to
    work, where, and whether they measured activity or only saw a band. Phase 1 asks for the
    catalog *with* them, and the table had zero rows.

    Two columns are refused rather than guessed, in the manner of `strain.organism_id` and
    `pathway_configuration.host_strain_id`:

    * `part_id` -- the payload names the enzyme in the paper's words and the catalog is 16 curated
      entries whose every identity claim is `unverified` background knowledge. Matching one to the
      other is a resolution, and CONVENTIONS.md is explicit that an identifier which cannot be
      resolved is recorded as unresolved and never mapped to the nearest plausible match.
    * `host_strain_id` -- stricter than the table, which allows NULL. G.6 is *one row per
      demonstrated host/compartment combination*; a row with neither is not an expression record,
      it is a claim that some enzyme was expressed somewhere. The strain is resolved from the
      paper's own host name where that strain has been promoted, exactly as a measurement's
      subject is, and blocks rather than inventing one where it has not.

    And one pair is refused **together**, which is the real point of this promoter.
    `(compartment_id, encoding_genome)` is a compound foreign key into `compartment_encoding_genome`
    because the mitochondrial matrix and inner membrane hold proteins from both genomes. "Expressed
    in the matrix" is therefore two different experiments -- a presequence-targeted nuclear
    construct that needs no recoding, or a gene physically placed on mtDNA that reads under NCBI
    table 3 -- and the pair is what tells them apart. Where the compartment admits only one genome
    the value is *derived* from that table and recorded as derived; where it admits two and the
    paper did not say, promotion refuses. Filling in the common case would put a fact in Zone R
    that would tell a bench scientist to recode a construct that must not be recoded, which is the
    single thing CONVENTIONS.md says this project has been wrong about before.
    """
    payload = _payload_of(task)
    missing: list[Requirement] = []
    blockers: list[str] = []

    part_as_reported = str(payload.get("part_as_reported") or "").strip()
    part_id: str | None = supplied.get("part_id")
    if not part_as_reported:
        missing.append(
            Requirement("part_id", "the record names no part, so there is nothing to resolve")
        )
    if not part_id:
        missing.append(
            Requirement(
                "part_id",
                f"NOT NULL on `part_expression_record`, and the extraction schema deliberately "
                f"carries no catalog id -- the record says {part_as_reported or 'nothing'!r}, "
                "which is the paper's wording and not an atlas identifier. A curator maps it to "
                "an entry in data/pathways/parts_catalog.yaml, or adds one",
            )
        )
    elif conn.execute("SELECT 1 FROM part WHERE id = ?", (part_id,)).fetchone() is None:
        missing.append(
            Requirement(
                "part_id",
                f"no part with id {part_id!r}; the catalog is data/pathways/parts_catalog.yaml "
                "and `fermdb atlas pathways` loads it",
            )
        )

    host_as_reported = str(payload.get("host_as_reported") or "").strip()
    host_strain_id: str | None = supplied.get("host_strain_id")
    if host_strain_id is not None:
        if conn.execute("SELECT 1 FROM strain WHERE id = ?", (host_strain_id,)).fetchone() is None:
            blockers.append(
                f"host strain {host_strain_id!r} is not promoted yet; promote that strain first"
            )
    elif host_as_reported:
        candidate = _strain_id(host_as_reported)
        row = conn.execute("SELECT id FROM strain WHERE id = ?", (candidate,)).fetchone()
        if row is not None:
            host_strain_id = str(row["id"])
        else:
            blockers.append(
                f"host {host_as_reported!r} is not promoted as a strain yet (would be "
                f"{candidate}); promote this publication's strain proposals first, or name the "
                "host with --host-strain"
            )
    else:
        missing.append(
            Requirement(
                "host_strain_id",
                "PLAN.md G.6 is one row per demonstrated host and compartment, and the record "
                "names no host. 'Worked in E. coli' and 'works in the yeast mitochondrial "
                "matrix' are different facts and this column is the whole of what keeps them "
                "apart",
            )
        )

    compartment_id = _vocabulary_value(payload.get("compartment"))
    encoding_genome = _vocabulary_value(payload.get("encoding_genome"))
    derived_genome: str | None = None
    if compartment_id is not None:
        genomes = tuple(
            str(row["encoding_genome"])
            for row in conn.execute(
                "SELECT encoding_genome FROM compartment_encoding_genome "
                "WHERE compartment_id = ? ORDER BY encoding_genome",
                (compartment_id,),
            ).fetchall()
        )
        if not genomes:
            missing.append(
                Requirement(
                    "compartment_id",
                    f"{compartment_id!r} has no row in `compartment_encoding_genome`, so the "
                    "compound foreign key has nothing to point at. Either it is not a compartment "
                    "this atlas models or the vocabularies have not been loaded",
                )
            )
        elif encoding_genome is None and len(genomes) == 1:
            # Derivation, not a guess: there is exactly one genome that can encode a protein
            # found here, so any other value would be unstorable. Recorded as derived in the
            # evidence string, because the paper did not say it.
            encoding_genome = derived_genome = genomes[0]
        elif encoding_genome is None:
            missing.append(
                Requirement(
                    "encoding_genome",
                    f"{compartment_id} holds proteins from both genomes ({', '.join(genomes)}), "
                    "so the compartment alone does not say which experiment this was, and the "
                    "compound foreign key (compartment_id, encoding_genome) has no row to point "
                    "at. A presequence-targeted construct is nuclear and needs no recoding; a "
                    "gene placed on mtDNA reads under NCBI table 3 and does. The record says "
                    "neither, and picking the common case would put the recoding advice in Zone R "
                    "for a construct nobody checked",
                )
            )
        elif encoding_genome not in genomes:
            missing.append(
                Requirement(
                    "encoding_genome",
                    f"nothing in {compartment_id} is encoded by the {encoding_genome} genome "
                    f"(the pairing table allows {', '.join(genomes)}), so this row is unstorable "
                    "and the pairing it claims does not exist",
                )
            )

    codon_optimized = _vocabulary_value(payload.get("codon_optimized"))
    if codon_optimized is not None and codon_optimized not in {"yes", "no"}:
        missing.append(Requirement("codon_optimized", f"{codon_optimized!r} is not 'yes' or 'no'"))
    elif codon_optimized == "yes" and encoding_genome is None:
        # The table's own comment: `codon_optimized` is unreadable without the genome --
        # optimized for which code? A 1 in this column with no genome beside it is a fact that
        # cannot be acted on, and the two codes differ at six codons.
        missing.append(
            Requirement(
                "encoding_genome",
                "the record says the sequence was codon-optimized and does not say for which "
                "genome. Optimized for which code? Table 1 and table 3 differ at six codons, so "
                "the claim is unreadable on its own -- and it is the claim a bench scientist "
                "would act on",
            )
        )

    expressed_ok, expressed_why = _closed_outcome(
        payload.get("expressed_ok"), _EXPRESSED_OK, "expressed_ok"
    )
    if expressed_why is not None:
        missing.append(Requirement("expressed_ok", expressed_why))
    activity_measured, activity_why = _closed_outcome(
        payload.get("activity_measured"), _ACTIVITY_MEASURED, "activity_measured"
    )
    if activity_why is not None:
        missing.append(Requirement("activity_measured", activity_why))

    # Nullable and left NULL when nobody supplies it, with no refusal: a part can be demonstrated
    # qualitatively, and `expressed_ok` / `activity_measured` exist precisely so that such a row
    # can be honest about having no number behind it. Demanding a measurement would make the
    # commonest kind of expression record unstorable.
    outcome_measurement_id: str | None = supplied.get("outcome_measurement_id")
    if outcome_measurement_id is not None and (
        conn.execute("SELECT 1 FROM measurement WHERE id = ?", (outcome_measurement_id,)).fetchone()
        is None
    ):
        blockers.append(
            f"outcome measurement {outcome_measurement_id!r} is not promoted yet; promote the "
            "measurement this record points at first"
        )

    row_id = f"YAA:PEXP:{task.proposal_hash[:16]}"
    existing = conn.execute(
        "SELECT id FROM part_expression_record WHERE id = ?", (row_id,)
    ).fetchone()
    return PromotionPlan(
        task_id=task.id,
        record_kind=task.record_kind,
        target_table="part_expression_record",
        row={
            "id": row_id,
            "part_id": part_id,
            "host_strain_id": host_strain_id,
            "compartment_id": compartment_id,
            "encoding_genome": encoding_genome,
            "codon_optimized": {"yes": 1, "no": 0}.get(codon_optimized or ""),
            "promoter": str(payload.get("promoter_as_reported") or "").strip() or None,
            "expressed_ok": expressed_ok,
            "activity_measured": activity_measured,
            "outcome_measurement_id": outcome_measurement_id,
            "publication_id": task.publication_id,
            "detail": _part_expression_detail(payload, derived_genome),
        },
        missing=tuple(missing),
        blockers=tuple(blockers),
        already=str(existing["id"]) if existing is not None else None,
    )


def _write_part_expression(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    """Write the expression record, Zone R, with what has no column in the evidence string.

    **A Zone R row pointing at a Zone I one.** `part` is written by `metabolic.curated.write_parts`
    as Zone I throughout -- the catalog says of itself that every functional and identity claim in
    it is background knowledge never checked against a source. This row is Zone R because its
    content is what the paper stated, and `part_id` is a curator's resolution onto that catalog.
    That is the right filing and it is worth saying out loud: the *expression* is reported, the
    *identity of the part it is an expression of* is only as good as the catalog entry, and
    tightening the catalog is a separate piece of work from promoting these rows.
    """
    before = conn.total_changes
    detail = evidence
    if plan.row["detail"]:
        detail += f"; {plan.row['detail']}"
    conn.execute(
        "INSERT INTO part_expression_record (id, part_id, host_strain_id, compartment_id, "
        "encoding_genome, codon_optimized, promoter, expressed_ok, activity_measured, "
        "outcome_measurement_id, publication_id, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["part_id"],
            plan.row["host_strain_id"],
            plan.row["compartment_id"],
            plan.row["encoding_genome"],
            plan.row["codon_optimized"],
            plan.row["promoter"],
            plan.row["expressed_ok"],
            plan.row["activity_measured"],
            plan.row["outcome_measurement_id"],
            plan.row["publication_id"],
            detail,
            confidence,
        ),
    )
    return conn.total_changes > before


Planner = Callable[[sqlite3.Connection, Task, Mapping[str, Any]], PromotionPlan]
Writer = Callable[..., bool]

#: Record kinds that can become rows today, with the functions that do it.
#:
#: :func:`plan_promotion` reports "no promoter for this kind yet" rather than succeeding quietly,
#: so a batch run cannot look complete while skipping proposals.
#:
#: `co_reported_higher_alcohols` and `pathway_configurations` were the two absent ones until they
#: were added here. Both had an extraction schema, a coverage mapping and a table, and no way to
#: cross the gap between them -- so accepted proposals sat resolved and unwritable, and
#: `pathway_configuration` read zero while being *phase 1's headline deliverable* and the thing
#: phase 3's acceptance test measures recall against.
#:
#: `part_expression_records` was the third, and was absent one level deeper than those two: there
#: was no extraction section either, so no proposal of that kind could exist to be stuck. G.6 calls
#: these rows "the field that makes the catalog worth having", and the catalog had 16 parts and no
#: record of any of them ever having been expressed anywhere.
#:
#: `conditions` is still absent, and for a reason worth stating: the extraction emits **one record
#: per facet** ("carbon_sources: 2% glucose or galactose"), while `condition_context` is one
#: immutable row per *whole context*, deduplicated by a hash over its facets. Turning N facet
#: records into one context means deciding which facets belong together, and nothing in a payload
#: says -- grouping by strain is a guess, and a wrong grouping produces a context that never
#: existed and that measurements would then be compared across. That is a curation decision, not a
#: mapping, and it stays open deliberately.
PROMOTERS: Final[Mapping[str, tuple[Planner, Writer]]] = {
    "strains": (_plan_strain, _write_strain),
    "measurements": (_plan_measurement, _write_measurement),
    "modifications": (_plan_modification, _write_modification),
    "bottlenecks": (_plan_bottleneck, _write_bottleneck),
    "co_reported_higher_alcohols": (_plan_higher_alcohol, _write_higher_alcohol),
    "pathway_configurations": (_plan_configuration, _write_configuration),
    "part_expression_records": (_plan_part_expression, _write_part_expression),
}

PROMOTABLE_KINDS: Final[tuple[str, ...]] = tuple(PROMOTERS)


# ---------------------------------------------------------------------------------- the action


def plan_promotion(
    conn: sqlite3.Connection,
    task: Task,
    *,
    settings: Settings | None = None,
    supplied: Mapping[str, Any] | None = None,
    check_span: bool = True,
) -> PromotionPlan:
    """What promoting ``task`` would write, and what stands in the way. Writes nothing."""
    supplied = supplied or {}
    if task.status not in _RESOLVED_STATUSES:
        return PromotionPlan(
            task_id=task.id,
            record_kind=task.record_kind,
            target_table=None,
            blockers=(
                f"task is {task.status!r}; only an accepted or edited proposal may be promoted",
            ),
        )

    promoter = PROMOTERS.get(task.record_kind)
    if promoter is None:
        return PromotionPlan(task_id=task.id, record_kind=task.record_kind, target_table=None)

    base = promoter[0](conn, task, supplied)
    if not check_span or base.already is not None:
        return base

    ok, detail = _verify_span(conn, settings or Settings.load(), task)
    if ok:
        return base
    return PromotionPlan(
        task_id=base.task_id,
        record_kind=base.record_kind,
        target_table=base.target_table,
        row=base.row,
        missing=base.missing,
        blockers=base.blockers + (f"span does not verify: {detail}",),
        already=base.already,
    )


def promote(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    curator: Curator,
    reason: str,
    settings: Settings | None = None,
    supplied: Mapping[str, Any] | None = None,
    confidence: str = "medium",
    now: datetime | None = None,
) -> PromotionResult:
    """Write the row a resolved task describes, and record who did it.

    ``confidence`` defaults to 'medium' rather than carrying the model's 'unverified' forward:
    by the time this runs a person has read the proposal and the span has re-resolved against the
    source, which is the definition CONVENTIONS.md gives for *checked*. It is not 'high', because
    that would claim more than one reader of one sentence establishes.
    """
    if not curator.is_human:
        raise NotPromotable(
            f"{curator.name} is an agent; PLAN.md L.5 reserves promotion for a person, and "
            "`curation_event` refuses a non-human 'promote' row in any case"
        )

    settings = settings or Settings.load()
    task = get_task(conn, task_id)
    plan = plan_promotion(conn, task, settings=settings, supplied=supplied)

    if plan.target_table is None or (not plan.ready and plan.already is None):
        raise NotPromotable(f"{task_id}: {plan.note}")

    ok, detail = _verify_span(conn, settings, task)
    span_detail = detail if ok else "span not re-checked (already promoted)"
    evidence = _evidence(task, span_detail, curator)
    writer = PROMOTERS[task.record_kind][1]

    created = False
    if plan.already is None:
        created = writer(conn, plan, evidence=evidence, confidence=confidence)

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    event_id = f"YAA:CUEV:{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id, "
        "rationale, created_at, zone) VALUES (?,?,?,'promote',?,?,?,?,'R')",
        (
            event_id,
            curator.name,
            curator.kind,
            plan.target_table,
            str(plan.row["id"]),
            f"{reason} [{evidence}]",
            moment.isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return PromotionResult(
        task_id=task_id,
        target_table=str(plan.target_table),
        row_id=str(plan.row["id"]),
        event_id=event_id,
        created=created,
    )


def promote_ready(
    conn: sqlite3.Connection,
    *,
    curator: Curator,
    reason: str,
    settings: Settings | None = None,
    supplied: Mapping[str, Any] | None = None,
    confidence: str = "medium",
) -> tuple[tuple[PromotionResult, ...], tuple[PromotionPlan, ...]]:
    """Promote every resolved task that can be, returning ``(done, not_done)``.

    Strains are promoted before measurements, because a measurement's subject is a strain and an
    unpromoted one blocks it. Doing this in one pass in the wrong order would report a blocker
    that the same run was about to resolve.

    Nothing is skipped silently: every task that did not promote comes back as a plan carrying the
    reason, so a caller cannot report success over a partial run.
    """
    settings = settings or Settings.load()
    done: list[PromotionResult] = []
    blocked: list[PromotionPlan] = []

    rows = conn.execute(
        "SELECT id, record_kind FROM curation_task WHERE status IN ('accepted', 'edited') "
        "ORDER BY CASE record_kind WHEN 'strains' THEN 0 ELSE 1 END, id"
    ).fetchall()

    for row in rows:
        task = get_task(conn, str(row["id"]))
        plan = plan_promotion(conn, task, settings=settings, supplied=supplied)
        if plan.already is not None:
            blocked.append(plan)
            continue
        if not plan.ready:
            blocked.append(plan)
            continue
        done.append(
            promote(
                conn,
                task.id,
                curator=curator,
                reason=reason,
                settings=settings,
                supplied=supplied,
                confidence=confidence,
            )
        )
    return tuple(done), tuple(blocked)
