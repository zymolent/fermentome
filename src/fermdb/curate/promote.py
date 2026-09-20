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
chain from row back to sentence stays walkable.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from ..config import Settings
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
            "quantity_kind": kind,
            "product_id": product_id,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "basis": basis,
            "source_locator": str(payload.get("source_locator") or "text"),
            "is_below_lod": 1 if payload.get("is_below_lod") else 0,
            "is_upper_bound": 1 if payload.get("is_upper_bound") else 0,
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


def _write_measurement(
    conn: sqlite3.Connection, plan: PromotionPlan, *, evidence: str, confidence: str
) -> bool:
    conn.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported, "
        "unit_as_reported, basis, source_locator, is_below_lod, is_upper_bound, zone, evidence, "
        "confidence) VALUES (?,?,?,?,?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["strain_id"],
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

#: `bottleneck.observation_type` is NOT NULL and closed. The extraction records a free-text
#: `support` instead, so the two are bridged for the values the vocabulary actually defines.
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

    support = str(payload.get("support") or "").strip()
    observation = support if support in _OBSERVATION_TYPES else supplied.get("observation_type")
    if observation is None:
        missing.append(
            Requirement(
                "observation_type",
                f"NOT NULL and closed; the record's support is {support or 'absent'!r}, which is "
                "not one of the six. A curator picks, because 'inferred' and 'flux_measurement' "
                "are very different evidence and the choice sets the level downstream",
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
            "observation_type": observation,
            "claim": str(payload.get("claim") or ""),
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
        "zone, evidence, confidence) VALUES (?,?,?,?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (
            plan.row["id"],
            plan.row["strain_id"],
            plan.row["type"],
            plan.row["target_locus"],
            plan.row["details"],
            plan.row["publication_id"],
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
    if plan.row["intervention"]:
        detail += f"; intervention: {plan.row['intervention']}"
    conn.execute(
        "INSERT INTO bottleneck (id, node, observation_type, zone, evidence, confidence) "
        "VALUES (?,?,?,'R',?,?) ON CONFLICT(id) DO NOTHING",
        (plan.row["id"], plan.row["node"], plan.row["observation_type"], detail, confidence),
    )
    return conn.total_changes > before


Planner = Callable[[sqlite3.Connection, Task, Mapping[str, Any]], PromotionPlan]
Writer = Callable[..., bool]

#: Record kinds that can become rows today, with the functions that do it.
#:
#: The two still absent are listed nowhere on purpose. :func:`plan_promotion` reports "no promoter
#: for this kind yet" rather than succeeding quietly, so a batch run cannot look complete while
#: skipping proposals.
#:
#: `conditions` is absent for a reason worth stating: the extraction emits **one record per
#: facet** ("carbon_sources: 2% glucose or galactose"), while `condition_context` is one immutable
#: row per *whole context*, deduplicated by a hash over its facets. Turning N facet records into
#: one context means deciding which facets belong together, and nothing in a payload says --
#: grouping by strain is a guess, and a wrong grouping produces a context that never existed and
#: that measurements would then be compared across. That is a curation decision, not a mapping.
PROMOTERS: Final[Mapping[str, tuple[Planner, Writer]]] = {
    "strains": (_plan_strain, _write_strain),
    "measurements": (_plan_measurement, _write_measurement),
    "modifications": (_plan_modification, _write_modification),
    "bottlenecks": (_plan_bottleneck, _write_bottleneck),
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
