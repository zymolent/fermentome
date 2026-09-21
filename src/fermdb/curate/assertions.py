"""Assertions: the statement the atlas had never made.

PLAN.md C.1 draws `ASSERTION` at the top of the entity diagram and calls it *"the unit of
knowledge"*; everything under it is *"the vocabulary assertions speak about"*. The atlas had the
vocabulary -- 101 strains, 97 measurements, 11 modifications, 4 bottlenecks, all promoted into
Zone R by `promote.py` -- and `assertion` read zero. So did `evidence_item`. Phase 0's acceptance
criterion, "an assertion resolves a complete J.5 chain", passed only against
`tests/fixtures/mini_atlas/`, which is four synthetic rows written by hand.

This module is the missing step: curated rows in, an `assertion` plus its `evidence_item`(s) out.
It is `promote.py`'s sibling and deliberately its mirror -- a planner that writes nothing and
names what it cannot supply, and a writer that refuses anything the planner did not call ready.
Five decisions are worth stating, because each is a refusal someone will eventually want to
soften:

**1. Nothing here ever writes a level.** `schema.sql` says it on the column that is not there:
*"there is deliberately no `level` column. The level is derived from the evidence by the
assertion_level view below. A stored level silently becomes a lie the first time a new paper
lands."* So this module writes `evidence_item` rows and reads the level back out of the view.
`level_override`, `override_reason` and `override_curator` are not parameters of any function
here, are not in the column list any INSERT names, and `tests/test_assertions.py` traces every
write statement this module executes to prove it. Overriding a level is a curator act with a
reason and a name attached (PLAN.md J.3, L.5), and an agent that could do it could grade its own
inference L1.

**2. `independent_group` is required for direct evidence, and is never derived from the
publication.** PLAN.md J.3's second axis counts independence *by group*, because one lab
publishing three times is not three independent observations. The column is nullable, and a NULL
one is counted by nothing: `assertion_level` takes `COUNT(DISTINCT independent_group) ... WHERE
independent_group IS NOT NULL`, so direct evidence with no group can never reach L2 however often
it is replicated. Defaulting the group to the publication id was the obvious alternative and is
exactly backwards -- three papers from one lab would then read as three independent groups and
the assertion would be promoted to L2 by the very conflation J.3 exists to prevent. So a curator
names the group, and this module says so rather than inventing one.

**3. The predicate is checked against the vocabulary, never coerced to the nearest match.**
`assertion.predicate` is a foreign key into `predicate`, 17 rows, closed and versioned (J.2). An
unknown predicate is refused by name with the vocabulary listed; a deprecated one is refused
separately, because "this term was retired" and "this term never existed" send a curator to two
different places.

**4. Every evidence item must close one arm of the J.5 chain, and for a measurement that arm
cannot be derived.** J.5 requires assertion -> evidence -> {analysis_result -> processing_run ->
dataset -> accession} u {extraction -> span -> publication} u {curation_event -> curator}. So an
evidence item must name a publication, an analysis_result, a processing_run or an extraction; one
that names none is refused, because the chain would not resolve and CI would fail on it later
with much less context. This used to have a sharp edge: `measurement` and `bottleneck` had no
`publication_id` column, so the paper survived only in the `evidence` prose ("promoted from
curation task ... on doi:10.1186/...") and J.5's last hop was a sentence rather than a join.
Parsing that string back out was rejected: it is citing a file in this repository, which
CONVENTIONS.md calls citing memory with an extra hop, and it would silently produce a wrong
publication the day the string's format changed. Schema v12 added the column to both and
backfilled every row (97/97 measurements, 4/4 bottlenecks), so **all three `from_*` helpers read
the publication off the row** the way `from_modification` always did. A curator is asked for it
only when the cited row's own column is NULL -- a measurement derived from a deposited dataset, a
bottleneck inferred from the curated pathway model -- which is a real state and not a gap.

**5. Building an assertion is a human act.** `promote.py` refuses an agent and so does this, for
the same reason and one more: `assertion_level` does not look at `zone`, so an agent-written
Zone I assertion carrying direct evidence would be graded L1 by the view and badged L1 by the UI,
with the zone column the only thing between an inference and an experimental claim and nothing on
the level path reading it. Letting an agent write Zone I assertions was the alternative and it is
a laundering route. :func:`plan_assertion` writes nothing and is open to anyone, which is the
half of the work an agent can usefully do.

An assertion is never edited (J.1). :func:`attach_evidence` therefore adds a row that points at
an assertion; it does not touch the assertion. A revision supersedes rather than edits, and
superseding is not implemented here because choosing what supersedes what is a curation decision,
not a mapping.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from .queue import CurationError, Curator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..query.values import EvidenceLevel

__all__ = [
    "ASSOCIATION_TYPES",
    "DIRECTIONS",
    "DIRECT_TYPES",
    "EVIDENCE_TYPES",
    "LEVEL_COLUMNS",
    "OBJECT_TABLES",
    "SUBJECT_TABLES",
    "AssertionPlan",
    "AssertionRequest",
    "AssertionResult",
    "EvidenceRequest",
    "NotAssertable",
    "Requirement",
    "assertion_id_for",
    "attach_evidence",
    "build_assertion",
    "evidence_id_for",
    "from_bottleneck",
    "from_measurement",
    "from_modification",
    "level_of",
    "plan_assertion",
    "plan_many",
    "with_evidence",
]


# ------------------------------------------------------------------------------- the vocabulary


#: `assertion.subject_type`'s closed set, mapped to the table each value points into.
#:
#: `assertion.subject_id` is polymorphic and carries no foreign key -- SQLite cannot express "FK
#: into one of eleven tables", as `schema.sql`'s header says -- so the integrity that a real FK
#: would give is checked here instead. PLAN.md J.5's traceability walk checks the same thing in
#: CI; doing it at write time means the dangling subject is caught by the person creating it
#: rather than by a nightly job with no idea who to tell.
SUBJECT_TABLES: Final[Mapping[str, str]] = {
    "gene_group": "gene_group",
    "gene": "gene",
    "strain": "strain",
    "reaction": "reaction",
    "pathway": "pathway",
    "modification": "modification",
    "part": "part",
    "metabolite": "metabolite",
    "product": "product",
    "compartment": "compartment",
    "pathway_route": "pathway_route",
}

#: `assertion.object_type`'s closed set. Narrower than the subject set -- no `modification` and no
#: `pathway_route` -- and `literal` is handled separately because it names no table.
OBJECT_TABLES: Final[Mapping[str, str]] = {
    "gene_group": "gene_group",
    "gene": "gene",
    "strain": "strain",
    "reaction": "reaction",
    "pathway": "pathway",
    "product": "product",
    "metabolite": "metabolite",
    "compartment": "compartment",
    "part": "part",
}

#: PLAN.md J.1's direction vocabulary, as `assertion.direction` and `evidence_item.direction`
#: both spell it.
DIRECTIONS: Final[frozenset[str]] = frozenset(
    {"increases", "decreases", "no_effect", "required_for", "not_required"}
)

#: PLAN.md J.3 axis 1, in `evidence_item.evidence_type`'s order.
EVIDENCE_TYPES: Final[tuple[str, ...]] = (
    "direct_perturbation",
    "direct_biochemical",
    "correlative_omics",
    "comparative_genomic",
    "computational_model",
    "literature_assertion",
    "ai_inference",
)

#: The two types that reach L1 and, replicated across groups, L2. They are also the only two the
#: schema lets cite a `measurement` at all.
DIRECT_TYPES: Final[frozenset[str]] = frozenset({"direct_perturbation", "direct_biochemical"})

#: The two types the view counts toward L3, by distinct publication rather than by group.
ASSOCIATION_TYPES: Final[frozenset[str]] = frozenset({"correlative_omics", "comparative_genomic"})

#: `evidence_item`'s per-type CHECK, restated in Python so the refusal can name the field.
#:
#: Restated, not re-derived: the constraint in `schema.sql` remains the authority and would refuse
#: the row anyway. What it cannot do is say *which* field is missing and why it matters -- a bare
#: `sqlite3.IntegrityError` naming `evidence_item_required_fields` sends a curator to read DDL.
#: A tuple inside the list means "at least one of these".
_REQUIRED_BY_TYPE: Final[Mapping[str, tuple[str | tuple[str, ...], ...]]] = {
    "direct_perturbation": (
        "strain_id",
        ("control_strain_id", "control_condition_id"),
        "measurement_id",
        "direction",
    ),
    "direct_biochemical": ("assay_method", "measurement_id"),
    "correlative_omics": (("contrast_id", "analysis_result_id"), "effect_size", "p_adjusted"),
    "comparative_genomic": ("variant_or_gene_set", "strain_set", "statistic"),
    "computational_model": ("model_id", "model_version", "processing_run_id"),
    "literature_assertion": ("publication_id", "span_id"),
    "ai_inference": ("model", "model_version", "prompt_version", "review_state"),
}

#: Why each required field is required, in the terms PLAN.md J.3 gives. Keyed by
#: (evidence_type, field) where the reason is type-specific, and by field alone otherwise.
_WHY_REQUIRED: Final[Mapping[str, str]] = {
    "strain_id": "a perturbation happened to a strain; the row must say which",
    "control_strain_id|control_condition_id": (
        "L1 requires a stated control. An isogenic control strain or the control condition -- "
        "either satisfies the schema, and neither can be inferred from the measurement"
    ),
    "measurement_id": "a direct claim must cite the number it rests on",
    "direction": (
        "increases | decreases | no_effect | required_for | not_required. A measurement is a "
        "number, not a direction: the direction is the comparison against the control, which is "
        "a reading of the experiment and not a property of the row"
    ),
    "assay_method": "which assay produced the number -- enzyme assay, isotope tracing, flux",
    "contrast_id|analysis_result_id": "an omics claim must name the contrast or the result it read",
    "effect_size": "an association with no effect size states nothing quantitative",
    "p_adjusted": "multiple-testing corrected, in [0, 1]",
    "variant_or_gene_set": "which variants or genes were compared",
    "strain_set": "across which strains",
    "statistic": "the association statistic",
    "model_id": "which model produced this",
    "model_version": "which version of it",
    "processing_run_id": "the run that computed it, so T.1's recipe resolves",
    "publication_id": "the paper that states it",
    "span_id": "the exact sentence, so the claim resolves to text a reader can check",
    "model": "which model inferred this",
    "prompt_version": "the prompt it was inferred under; L.3 needs it to be reproducible",
    "review_state": "pending | accepted | rejected -- an unreviewed inference says so",
}

#: The four ways an evidence item can close a J.5 arm. At least one must be present.
_CHAIN_COLUMNS: Final[tuple[str, ...]] = (
    "publication_id",
    "analysis_result_id",
    "processing_run_id",
    "extraction_id",
)

#: Columns this module will write on `evidence_item`, in INSERT order. `status` and `created_at`
#: take the schema's defaults.
_EVIDENCE_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "assertion_id",
    "evidence_type",
    "direction",
    "independent_group",
    "publication_id",
    "span_id",
    "strain_id",
    "control_strain_id",
    "control_condition_id",
    "measurement_id",
    "assay_method",
    "contrast_id",
    "analysis_result_id",
    "effect_size",
    "p_adjusted",
    "variant_or_gene_set",
    "strain_set",
    "statistic",
    "model_id",
    "processing_run_id",
    "model",
    "model_version",
    "prompt_version",
    "review_state",
    "extraction_id",
    "eco_id",
    "zone",
    "evidence",
    "confidence",
)

#: Columns this module will write on `assertion`. Note what is absent: the three override columns.
#: They are a curator act (J.3) and `curation_event.action` has an `override_level` value for it.
_ASSERTION_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "subject_type",
    "subject_id",
    "predicate",
    "object_type",
    "object_id",
    "object_literal",
    "object_unit",
    "context_id",
    "product_id",
    "direction",
    "effect_size",
    "effect_unit",
    "effect_ci_low",
    "effect_ci_high",
    "effect_n",
    "created_by_kind",
    "created_by",
    "zone",
    "evidence",
    "confidence",
)

#: The columns no statement in this module may name. Asserted by a test that traces every write.
LEVEL_COLUMNS: Final[frozenset[str]] = frozenset(
    {"level_override", "override_reason", "override_curator"}
)


class NotAssertable(CurationError):
    """A statement cannot be written yet, and the plan says exactly why."""


# -------------------------------------------------------------------------------- the requests


@dataclass(frozen=True)
class Requirement:
    """A column the row needs and the curated rows cannot supply.

    Deliberately a separate type from `promote.Requirement`, which is identical in shape. The two
    modules answer different questions -- promotion is about a `curation_task`, this is about
    rows that may never have been through one -- and coupling them would make `assertions` depend
    on the queue for a four-line dataclass. If they ever need to be one type, the move is to lift
    it into `curate/__init__.py`, not to import sideways.
    """

    field: str
    why: str

    def __str__(self) -> str:
        return f"{self.field}: {self.why}"


@dataclass(frozen=True)
class EvidenceRequest:
    """One `evidence_item` as a caller describes it, before anything checks it.

    Every column of `evidence_item` this module writes appears here, and `level` does not, because
    there is no such column and no way to ask for one.
    """

    evidence_type: str
    #: PLAN.md J.3 axis 2. Required for the direct types; see the module docstring.
    independent_group: str | None = None
    publication_id: str | None = None
    span_id: str | None = None
    direction: str | None = None

    # direct_perturbation
    strain_id: str | None = None
    control_strain_id: str | None = None
    control_condition_id: str | None = None

    # direct_perturbation | direct_biochemical
    measurement_id: str | None = None
    assay_method: str | None = None

    # correlative_omics
    contrast_id: str | None = None
    analysis_result_id: str | None = None
    effect_size: float | None = None
    p_adjusted: float | None = None

    # comparative_genomic
    variant_or_gene_set: str | None = None
    strain_set: str | None = None
    statistic: float | None = None

    # computational_model
    model_id: str | None = None
    processing_run_id: str | None = None

    # ai_inference
    model: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    review_state: str | None = None
    extraction_id: str | None = None

    eco_id: str | None = None
    zone: str = "R"
    #: Free text naming the source. Derived from the cited rows when left empty.
    note: str = ""
    confidence: str = "medium"

    @property
    def is_direct(self) -> bool:
        return self.evidence_type in DIRECT_TYPES

    def identity(self) -> dict[str, Any]:
        """The columns that make this evidence item *this* one.

        `note`, `confidence` and `eco_id` are excluded: re-running with a longer evidence sentence
        should update nothing and create nothing, not write a second row for the same observation.
        """
        return {
            name: getattr(self, name)
            for name in _EVIDENCE_COLUMNS
            if name not in {"id", "assertion_id", "evidence", "confidence", "eco_id"}
            and getattr(self, name, None) is not None
        }


@dataclass(frozen=True)
class AssertionRequest:
    """One statement and the evidence offered for it.

    There is no `level` field, and adding one would be the bug this module exists to prevent.
    """

    subject_type: str
    subject_id: str | None
    predicate: str
    object_type: str
    object_id: str | None = None
    object_literal: str | None = None
    object_unit: str | None = None
    context_id: str | None = None
    product_id: str | None = None
    direction: str | None = None
    effect_size: float | None = None
    effect_unit: str | None = None
    effect_ci_low: float | None = None
    effect_ci_high: float | None = None
    effect_n: int | None = None
    evidence: tuple[EvidenceRequest, ...] = ()
    #: Set by :func:`from_bottleneck`. `bottleneck.assertion_id` is filled in on write, which is
    #: the only column of an already-curated row this module touches.
    bottleneck_id: str | None = None
    #: Free text carried into `assertion.evidence` alongside the derived provenance.
    note: str = ""
    zone: str = "R"
    confidence: str = "medium"

    def identity(self) -> dict[str, Any]:
        """What makes this statement a distinct statement.

        `direction` is in here on purpose. Two papers reporting opposite directions are two
        assertions in a `conflict` (PLAN.md J.4), not one assertion that changed its mind, and
        hashing the direction is what keeps them from colliding onto the same id.
        """
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "object_literal": self.object_literal,
            "context_id": self.context_id,
            "product_id": self.product_id,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class AssertionPlan:
    """What building one assertion would write, and what stands in the way."""

    assertion_id: str
    request: AssertionRequest
    missing: tuple[Requirement, ...] = ()
    blockers: tuple[str, ...] = ()
    #: Reported, not refused. Something a curator should see that does not stop the write.
    warnings: tuple[str, ...] = ()
    #: The assertion id, if a row with it is already there.
    already: str | None = None
    #: Evidence ids already present, in request order; None where the row would be new.
    evidence_already: tuple[str | None, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.missing and not self.blockers

    @property
    def note(self) -> str:
        if self.blockers:
            return "; ".join(self.blockers)
        if self.missing:
            return "needs " + "; ".join(str(m) for m in self.missing)
        new_evidence = sum(1 for e in self.evidence_already if e is None)
        if self.already is not None and new_evidence == 0:
            return f"already asserted as {self.already}, with all of its evidence"
        if self.already is not None:
            return f"{self.already} exists; would add {new_evidence} evidence item(s)"
        return (
            f"ready to write assertion {self.assertion_id} "
            f"with {len(self.request.evidence)} evidence item(s)"
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "predicate": self.request.predicate,
            "ready": self.ready,
            "note": self.note,
            "missing": [{"field": m.field, "why": m.why} for m in self.missing],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "already": self.already,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class AssertionResult:
    """One statement that now exists, and the level the view gives it.

    ``level`` is read back out of `assertion_level` after the write. It is not computed here, not
    stored anywhere, and will be a different value tomorrow if a new paper lands -- which is the
    whole argument for the view.
    """

    assertion_id: str
    evidence_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    created: bool
    evidence_created: int
    level: EvidenceLevel
    #: What `plan_assertion` would have said, carried through the write instead of being dropped.
    #: `attach_evidence` discarded these until 2026-09-22, which is how a level demotion reached a
    #: curator as silence.
    warnings: tuple[str, ...] = ()
    #: The level before this write, when there was one. `None` on a newly built assertion, which
    #: had no level to move from. Present so a caller can see `L2 -> L1` rather than reconstruct it.
    level_before: EvidenceLevel | None = None


# ------------------------------------------------------------------------------------- id rules


def _digest(payload: Mapping[str, Any]) -> str:
    """A stable 16-hex digest over a row's identifying columns.

    Derived rather than random, for the reason `promote.py` gives: building the same statement
    twice must be a no-op, or a curator who re-runs a command doubles the evidence count and with
    it the derived level.
    """
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def assertion_id_for(request: AssertionRequest) -> str:
    """``YAA:ASSERT:<digest>`` over subject, predicate, object, context and direction."""
    return f"YAA:ASSERT:{_digest(request.identity())}"


def evidence_id_for(assertion_id: str, evidence: EvidenceRequest) -> str:
    """``YAA:EV:<digest>`` over the assertion and the evidence's identifying columns."""
    return f"YAA:EV:{_digest({'assertion_id': assertion_id, **evidence.identity()})}"


# -------------------------------------------------------------------------------- the checking


def _exists(conn: sqlite3.Connection, table: str, row_id: str) -> bool:
    # `table` is never caller-supplied: it comes from SUBJECT_TABLES / OBJECT_TABLES or is a
    # literal here, so there is nothing to interpolate that a user chose.
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone() is not None


def _check_predicate(conn: sqlite3.Connection, predicate: str) -> Requirement | None:
    """The closed vocabulary of PLAN.md J.2, checked rather than approximated."""
    if not predicate:
        return Requirement("predicate", "a statement with no predicate states nothing")
    row = conn.execute(
        "SELECT id, status, vocab_version FROM predicate WHERE id = ?", (predicate,)
    ).fetchone()
    if row is None:
        known = [str(r["id"]) for r in conn.execute("SELECT id FROM predicate ORDER BY id")]
        return Requirement(
            "predicate",
            f"{predicate!r} is not in the `predicate` vocabulary. PLAN.md J.2 closes it at "
            f"{len(known)} terms because an open predicate vocabulary makes the graph "
            "unqueryable within a year; adding a term is a versioned vocabulary change, not a "
            f"coercion to the nearest match. The vocabulary is: {', '.join(known)}",
        )
    if str(row["status"]) != "active":
        return Requirement(
            "predicate",
            f"{predicate!r} is deprecated in vocabulary version {row['vocab_version']}. It is "
            "retired rather than absent, so an existing assertion still resolves; a new one "
            "names its replacement",
        )
    return None


def _check_subject(conn: sqlite3.Connection, request: AssertionRequest) -> list[Requirement]:
    out: list[Requirement] = []
    table = SUBJECT_TABLES.get(request.subject_type)
    if table is None:
        out.append(
            Requirement(
                "subject_type",
                f"{request.subject_type!r} is not one of {sorted(SUBJECT_TABLES)}",
            )
        )
    if not request.subject_id:
        out.append(
            Requirement("subject_id", "the statement names no subject, so it is about nothing")
        )
    elif table is not None and not _exists(conn, table, request.subject_id):
        out.append(
            Requirement(
                "subject_id",
                f"no row {request.subject_id!r} in `{table}`. `assertion.subject_id` is "
                "polymorphic and carries no foreign key, so a dangling subject would be stored "
                "happily and found later by J.5's traceability walk with nobody to tell",
            )
        )
    return out


def _check_object(conn: sqlite3.Connection, request: AssertionRequest) -> list[Requirement]:
    out: list[Requirement] = []
    if request.object_type == "literal":
        if not request.object_literal:
            out.append(
                Requirement("object_literal", "a literal object must carry its literal value")
            )
        if request.object_id:
            out.append(
                Requirement(
                    "object_id",
                    "a literal object may not also name a typed row; the schema's CHECK refuses "
                    "the row and the two would disagree about what the statement is about",
                )
            )
        return out

    table = OBJECT_TABLES.get(request.object_type)
    if table is None:
        out.append(
            Requirement(
                "object_type",
                f"{request.object_type!r} is not one of {[*sorted(OBJECT_TABLES), 'literal']}",
            )
        )
    if not request.object_id:
        out.append(
            Requirement(
                "object_id",
                "a typed object must name its row; use object_type='literal' for a bare value",
            )
        )
    elif table is not None and not _exists(conn, table, request.object_id):
        out.append(Requirement("object_id", f"no row {request.object_id!r} in `{table}`"))
    return out


def _required_fields(evidence: EvidenceRequest) -> list[Requirement]:
    """`evidence_item`'s per-type CHECK, as named requirements instead of an IntegrityError."""
    out: list[Requirement] = []
    for requirement in _REQUIRED_BY_TYPE.get(evidence.evidence_type, ()):
        names = (requirement,) if isinstance(requirement, str) else requirement
        if any(getattr(evidence, name, None) is not None for name in names):
            continue
        key = "|".join(names)
        out.append(
            Requirement(
                key,
                _WHY_REQUIRED.get(key, f"required for {evidence.evidence_type}"),
            )
        )
    return out


def _check_evidence_agrees_with_itself(request: AssertionRequest) -> list[str]:
    """Warn when the **direct** evidence items disagree with each other about the direction.

    This is the disagreement PLAN.md J.4 is about, and it is the one that actually costs a level:
    ``assertion_level`` counts distinct directions among direct evidence and withholds L2 while
    there is more than one. Two labs reporting opposite effects is a finding, and the usual right
    answer is two assertions and a ``conflict`` row -- which is a curator act under J.4 and L.5,
    so this reports and does not refuse. Refusing would also make the view's own
    ``n_direct_directions <= 1`` branch unreachable through this module.

    SEPARATED from the per-item check against ``assertion.direction`` on 2026-09-22. The two were
    one test, and it warned on the atlas's first L2 -- subject ``gene_group BAT1``, assertion
    ``decreases``, both evidence items ``increases`` -- announcing that L2 was unreachable, while
    the view returned L2. Evidence disagreeing with the *assertion's* sign is normal wherever the
    subject is what the experiment acted on; evidence disagreeing with *itself* is not.
    """
    directions = {
        e.direction
        for e in request.evidence
        if e.direction is not None and e.evidence_type in DIRECT_TYPES
    }
    if len(directions) <= 1:
        return []
    return [
        "the direct evidence items disagree with each other about the direction "
        f"({', '.join(sorted(directions))}). `assertion_level` counts distinct directions and "
        "withholds L2 while more than one stands, so this assertion cannot be replicated-grade "
        "as it is. PLAN.md J.4 would record this as a `conflict` between two assertions rather "
        "than a disagreement inside one; recording that is a curator's decision, not this "
        "module's"
    ]


def _subject_is_its_own_perturbation(request: AssertionRequest) -> bool:
    """Is the assertion's subject the thing the experiment changed?

    This decides whether a sign mismatch between an evidence item and its assertion is suspect or
    expected, and the two cases are genuinely different:

    * subject ``modification`` -- the subject *is* the change, so "this deletion increased the
      titer" and "this deletion decreases production" are two statements about one thing and
      disagreeing is a real signal;
    * subject ``gene_group`` / ``gene`` -- the subject is what the change acted *on*, so the signs
      are expected to invert. Deleting BAT1 raises isobutanol precisely because BAT1 lowers it.

    Kept as a named predicate rather than inlined, because the distinction is the whole content of
    the warning it gates and a bare ``in`` test at the call site would read as an arbitrary list.
    """
    return request.subject_type == "modification"


def _check_evidence(
    conn: sqlite3.Connection, request: AssertionRequest, evidence: EvidenceRequest, index: int
) -> tuple[list[Requirement], list[str], list[str]]:
    """One evidence item: requirements, blockers, warnings."""
    missing: list[Requirement] = []
    blockers: list[str] = []
    warnings: list[str] = []
    where = f"evidence[{index}]"

    if evidence.evidence_type not in EVIDENCE_TYPES:
        missing.append(
            Requirement(
                f"{where}.evidence_type",
                f"{evidence.evidence_type!r} is not one of {list(EVIDENCE_TYPES)}. The set is "
                "closed by `evidence_item`'s CHECK, whose ELSE branch is 0 so that adding a type "
                "forces a decision about what it must carry",
            )
        )
        return missing, blockers, warnings

    for requirement in _required_fields(evidence):
        missing.append(Requirement(f"{where}.{requirement.field}", requirement.why))

    # PLAN.md J.3 axis 2, and the reason it is a requirement rather than a default.
    if evidence.is_direct and not evidence.independent_group:
        missing.append(
            Requirement(
                f"{where}.independent_group",
                "PLAN.md J.3 counts independence by group, not by publication, because one lab "
                "publishing three times is not three independent observations. A NULL group is "
                "counted by nothing -- `assertion_level` takes COUNT(DISTINCT independent_group) "
                "WHERE it IS NOT NULL -- so this evidence could never reach L2 however often it "
                "is replicated. Defaulting it to the publication id would do the opposite and "
                "read one lab's three papers as three groups. A curator names the group",
            )
        )

    # PLAN.md J.5. The chain has to close somewhere, and `measurement` cannot close it.
    if not any(getattr(evidence, column, None) for column in _CHAIN_COLUMNS):
        missing.append(
            Requirement(
                f"{where}.publication_id",
                "this evidence closes no J.5 chain: it names no publication, analysis_result, "
                "processing_run or extraction, so assertion -> evidence -> source does not "
                "resolve and CI's traceability walk will fail on it. A `measurement`, a "
                "`modification` and a `bottleneck` each carry a real `publication_id` now, and "
                "`from_measurement`, `from_modification` and `from_bottleneck` read it off the "
                "row -- so reaching this requirement means the cited row's own column is NULL "
                "(or nothing was cited), and a curator names the paper",
            )
        )

    if evidence.measurement_id is not None and not evidence.is_direct:
        blockers.append(
            f"{where} is {evidence.evidence_type} and cites measurement "
            f"{evidence.measurement_id}; only the two direct types may cite a measurement at all, "
            "or a correlative or inferred row quietly acquires the authority of a measured number"
        )

    if evidence.evidence_type == "ai_inference":
        if evidence.zone != "I":
            blockers.append(
                f"{where} is an ai_inference in zone {evidence.zone!r}. An AI inference is Zone I "
                "by definition (CONVENTIONS.md, PLAN.md D.2); promotion writes a new curated "
                "assertion citing it rather than relabelling the row"
            )
        if evidence.review_state is not None and evidence.review_state not in {
            "pending",
            "accepted",
            "rejected",
        }:
            missing.append(
                Requirement(
                    f"{where}.review_state",
                    f"{evidence.review_state!r} is not one of pending, accepted, rejected",
                )
            )
    elif evidence.zone not in {"R", "H", "I"}:
        missing.append(Requirement(f"{where}.zone", f"{evidence.zone!r} is not one of R, H, I"))

    if evidence.direction is not None and evidence.direction not in DIRECTIONS:
        missing.append(
            Requirement(f"{where}.direction", f"{evidence.direction!r} is not one of {DIRECTIONS}")
        )
    elif (
        evidence.direction is not None
        and request.direction is not None
        and evidence.direction != request.direction
        and _subject_is_its_own_perturbation(request)
    ):
        # Not refused. `assertion_level` counts distinct directions among **direct evidence**, and
        # withholds L2 when those disagree with *each other*. It never reads
        # `assertion.direction`, so a mismatch against the assertion's own sign costs nothing.
        #
        # NARROWED 2026-09-22, and the narrowing was found by the first L2 rather than reasoned
        # out. This warned on `YAA:ASSERT:893939228cea1ef4` -- subject `gene_group BAT1`,
        # direction `decreases`, both evidence items `increases` -- saying "the derived level will
        # not reach L2 while both stand". The view returned **L2**. The warning was conflating two
        # different things:
        #
        #   * evidence items that disagree with each *other* -- a real conflict, and what J.4 is
        #     about;
        #   * an evidence direction that differs from the *assertion's* sign, which is the normal
        #     and correct shape whenever the subject is a gene and the experiment is its deletion.
        #     "Deleting BAT1 increased isobutanol" and "BAT1 decreases isobutanol" are the same
        #     finding stated about two different subjects, and forcing them to agree would make
        #     the atlas assert the opposite of what its papers report.
        #
        # So the check now fires only where the subject is itself the perturbation -- a
        # `modification`, where the two signs describe the same thing and disagreeing really is
        # suspect. A wrong warning is worse than none: it teaches a curator to expect noise here,
        # and the next one may be real.
        warnings.append(
            f"{where} points {evidence.direction!r} and the assertion says "
            f"{request.direction!r}, and the subject IS the perturbation, so the two describe the "
            "same change and should agree. PLAN.md J.4 would record a genuine disagreement as a "
            "`conflict` between two assertions rather than inside one; recording that is a "
            "curator's decision, not this module's"
        )

    if evidence.confidence not in {"unverified", "low", "medium", "high"}:
        missing.append(
            Requirement(
                f"{where}.confidence",
                f"{evidence.confidence!r} is not one of unverified, low, medium, high",
            )
        )

    blockers.extend(_check_evidence_references(conn, evidence, where))
    return missing, blockers, warnings


def _check_evidence_references(
    conn: sqlite3.Connection, evidence: EvidenceRequest, where: str
) -> list[str]:
    """Every row this evidence cites must exist. A foreign key would raise later and say less."""
    blockers: list[str] = []
    for column, table in (
        ("publication_id", "publication"),
        ("span_id", "span"),
        ("strain_id", "strain"),
        ("control_strain_id", "strain"),
        ("control_condition_id", "condition_context"),
        ("measurement_id", "measurement"),
        ("analysis_result_id", "analysis_result"),
        ("processing_run_id", "processing_run"),
        ("extraction_id", "extraction"),
    ):
        value = getattr(evidence, column)
        if value and not _exists(conn, table, str(value)):
            blockers.append(f"{where}.{column}: no row {value!r} in `{table}`")

    # A span from another paper attached to this evidence is a traceability bug that resolves
    # cleanly and points at the wrong sentence, which is worse than one that fails to resolve.
    if evidence.span_id and evidence.publication_id:
        row = conn.execute(
            "SELECT publication_id FROM span WHERE id = ?", (evidence.span_id,)
        ).fetchone()
        if row is not None and str(row["publication_id"]) != evidence.publication_id:
            blockers.append(
                f"{where}: span {evidence.span_id} belongs to {row['publication_id']}, not to "
                f"{evidence.publication_id}. A span that resolves to the wrong paper is worse "
                "than one that does not resolve"
            )
    return blockers


def plan_assertion(conn: sqlite3.Connection, request: AssertionRequest) -> AssertionPlan:
    """What building ``request`` would write, and what stands in the way. Writes nothing.

    Open to any caller, agent included: computing the plan is the half of this work that does not
    need a person, and an agent that hands a curator a filled-in plan with one named gap has done
    something useful without deciding anything.
    """
    missing: list[Requirement] = []
    blockers: list[str] = []
    warnings: list[str] = []

    predicate_problem = _check_predicate(conn, request.predicate)
    if predicate_problem is not None:
        missing.append(predicate_problem)
    missing.extend(_check_subject(conn, request))
    missing.extend(_check_object(conn, request))

    if request.direction is not None and request.direction not in DIRECTIONS:
        missing.append(
            Requirement("direction", f"{request.direction!r} is not one of {sorted(DIRECTIONS)}")
        )
    if request.context_id and not _exists(conn, "condition_context", request.context_id):
        blockers.append(f"no condition_context {request.context_id!r}")
    if request.product_id and not _exists(conn, "product", request.product_id):
        blockers.append(f"no product {request.product_id!r}")
    if request.zone not in {"R", "H", "I"}:
        missing.append(Requirement("zone", f"{request.zone!r} is not one of R, H, I"))
    if request.confidence not in {"unverified", "low", "medium", "high"}:
        missing.append(
            Requirement(
                "confidence",
                f"{request.confidence!r} is not one of unverified, low, medium, high",
            )
        )

    # An assertion with no evidence is the one thing J.5 forbids outright: `assertion_level`
    # reports a NULL level with basis 'no_evidence', and the CI walk fails on it. Refused here,
    # where the person creating it is still in the room.
    if not request.evidence:
        missing.append(
            Requirement(
                "evidence",
                "an assertion with no evidence item cannot produce a J.5 chain and is graded "
                "NULL with basis 'no_evidence'. PLAN.md J.5 calls that a bug of the same "
                "severity as a failing unit test",
            )
        )

    assertion_id = assertion_id_for(request)
    for index, evidence in enumerate(request.evidence):
        item_missing, item_blockers, item_warnings = _check_evidence(conn, request, evidence, index)
        missing.extend(item_missing)
        blockers.extend(item_blockers)
        warnings.extend(item_warnings)

    warnings.extend(_check_evidence_agrees_with_itself(request))

    if request.bottleneck_id:
        row = conn.execute(
            "SELECT assertion_id FROM bottleneck WHERE id = ?", (request.bottleneck_id,)
        ).fetchone()
        if row is None:
            blockers.append(f"no bottleneck {request.bottleneck_id!r}")
        elif row["assertion_id"] and str(row["assertion_id"]) != assertion_id:
            blockers.append(
                f"bottleneck {request.bottleneck_id} already names assertion "
                f"{row['assertion_id']}. An assertion is never edited (PLAN.md J.1) and "
                "re-pointing the bottleneck would replace one statement with another in place"
            )

    evidence_ids = tuple(evidence_id_for(assertion_id, e) for e in request.evidence)
    existing_assertion = assertion_id if _exists(conn, "assertion", assertion_id) else None
    evidence_already = tuple(
        item_id if _exists(conn, "evidence_item", item_id) else None for item_id in evidence_ids
    )

    return AssertionPlan(
        assertion_id=assertion_id,
        request=request,
        missing=tuple(missing),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        already=existing_assertion,
        evidence_already=evidence_already,
        evidence_ids=evidence_ids,
    )


# --------------------------------------------------------------------------------- the writing


def _provenance(request: AssertionRequest, curator: Curator) -> str:
    """The J.5 chain in one string: what was cited, and who said it means this."""
    cited: list[str] = []
    for evidence in request.evidence:
        for column in ("measurement_id", "analysis_result_id", "publication_id", "span_id"):
            value = getattr(evidence, column)
            if value:
                cited.append(f"{column}={value}")
    if request.bottleneck_id:
        cited.append(f"bottleneck={request.bottleneck_id}")
    detail = "; ".join(dict.fromkeys(cited)) or "no cited row"
    head = f"{request.note}; " if request.note else ""
    return f"{head}asserted from curated rows ({detail}); curator {curator.name}"


def _evidence_sentence(evidence: EvidenceRequest, curator: Curator) -> str:
    if evidence.note:
        return evidence.note
    cited = [
        f"{column}={getattr(evidence, column)}"
        for column in _CHAIN_COLUMNS + ("measurement_id", "span_id")
        if getattr(evidence, column)
    ]
    return (
        f"{evidence.evidence_type} evidence ({'; '.join(cited) or 'no cited row'}); "
        f"curator {curator.name}"
    )


def _insert_assertion(conn: sqlite3.Connection, plan: AssertionPlan, curator: Curator) -> bool:
    request = plan.request
    values: dict[str, Any] = {
        "id": plan.assertion_id,
        "subject_type": request.subject_type,
        "subject_id": request.subject_id,
        "predicate": request.predicate,
        "object_type": request.object_type,
        "object_id": request.object_id,
        "object_literal": request.object_literal,
        "object_unit": request.object_unit,
        "context_id": request.context_id,
        "product_id": request.product_id,
        "direction": request.direction,
        "effect_size": request.effect_size,
        "effect_unit": request.effect_unit,
        "effect_ci_low": request.effect_ci_low,
        "effect_ci_high": request.effect_ci_high,
        "effect_n": request.effect_n,
        "created_by_kind": "curator",
        "created_by": curator.name,
        "zone": request.zone,
        "evidence": _provenance(request, curator),
        "confidence": request.confidence,
    }
    before = conn.total_changes
    placeholders = ", ".join("?" for _ in _ASSERTION_COLUMNS)
    conn.execute(
        f"INSERT INTO assertion ({', '.join(_ASSERTION_COLUMNS)}) VALUES ({placeholders}) "
        "ON CONFLICT(id) DO NOTHING",
        tuple(values[name] for name in _ASSERTION_COLUMNS),
    )
    return conn.total_changes > before


def _insert_evidence(
    conn: sqlite3.Connection,
    assertion_id: str,
    evidence_id: str,
    evidence: EvidenceRequest,
    curator: Curator,
) -> bool:
    values: dict[str, Any] = {name: getattr(evidence, name, None) for name in _EVIDENCE_COLUMNS}
    values["id"] = evidence_id
    values["assertion_id"] = assertion_id
    values["evidence"] = _evidence_sentence(evidence, curator)
    values["confidence"] = evidence.confidence
    before = conn.total_changes
    placeholders = ", ".join("?" for _ in _EVIDENCE_COLUMNS)
    conn.execute(
        f"INSERT INTO evidence_item ({', '.join(_EVIDENCE_COLUMNS)}) VALUES ({placeholders}) "
        "ON CONFLICT(id) DO NOTHING",
        tuple(values[name] for name in _EVIDENCE_COLUMNS),
    )
    return conn.total_changes > before


def _log(
    conn: sqlite3.Connection,
    curator: Curator,
    *,
    target_type: str,
    target_id: str,
    rationale: str,
    moment: datetime,
) -> str:
    event_id = f"YAA:CUEV:{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id, "
        "rationale, created_at, zone) VALUES (?,?,?,'create',?,?,?,?,'R')",
        (
            event_id,
            curator.name,
            curator.kind,
            target_type,
            target_id,
            rationale,
            moment.isoformat(timespec="seconds"),
        ),
    )
    return event_id


def _refuse_agent(curator: Curator, what: str) -> None:
    if curator.is_human:
        return
    raise NotAssertable(
        f"{curator.name} is an agent and may not {what}. PLAN.md L.5 reserves this for a person, "
        "and `assertion_level` does not look at `zone` -- an agent-written Zone I assertion "
        "carrying direct evidence would be graded L1 by the view and badged L1 by the UI. "
        "`plan_assertion` writes nothing and is open to an agent"
    )


def build_assertion(
    conn: sqlite3.Connection,
    request: AssertionRequest,
    *,
    curator: Curator,
    reason: str,
    now: datetime | None = None,
) -> AssertionResult:
    """Write the statement and its evidence, and report the level the view then gives it.

    Idempotent on the derived ids: building the same statement twice writes nothing the second
    time, which matters more here than elsewhere because a duplicated evidence item would change
    the derived level without anyone having learned anything.
    """
    _refuse_agent(curator, "create an assertion")
    plan = plan_assertion(conn, request)
    if not plan.ready:
        raise NotAssertable(f"{plan.assertion_id}: {plan.note}")

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    created = _insert_assertion(conn, plan, curator)
    events = [
        _log(
            conn,
            curator,
            target_type="assertion",
            target_id=plan.assertion_id,
            rationale=f"{reason} [{_provenance(request, curator)}]",
            moment=moment,
        )
    ]

    evidence_created = 0
    for evidence, evidence_id in zip(request.evidence, plan.evidence_ids, strict=True):
        if _insert_evidence(conn, plan.assertion_id, evidence_id, evidence, curator):
            evidence_created += 1
            events.append(
                _log(
                    conn,
                    curator,
                    target_type="evidence_item",
                    target_id=evidence_id,
                    rationale=f"{reason} [{_evidence_sentence(evidence, curator)}]",
                    moment=moment,
                )
            )

    if request.bottleneck_id:
        # The one already-curated column this module writes. `bottleneck.assertion_id` exists so
        # that a bottleneck is "an assertion with a required shape" (PLAN.md G.8) rather than a
        # second, parallel opinion; leaving it NULL would keep the two unconnected. Guarded on
        # IS NULL so an existing link is never re-pointed.
        conn.execute(
            "UPDATE bottleneck SET assertion_id = ? WHERE id = ? AND assertion_id IS NULL",
            (plan.assertion_id, request.bottleneck_id),
        )

    conn.commit()
    return AssertionResult(
        assertion_id=plan.assertion_id,
        evidence_ids=plan.evidence_ids,
        event_ids=tuple(events),
        created=created,
        evidence_created=evidence_created,
        level=level_of(conn, plan.assertion_id),
    )


#: The levels in strength order, strongest first. **This is not the numeric order**, and assuming
#: it was is a mistake worth naming: `L2` outranks `L1` because replication across independent
#: groups is the stronger claim, while `L3`-`L5` all sit *below* both because they rest on no
#: direct evidence at all. The sequence is read straight off `assertion_level`'s CASE ladder in
#: `schema.sql`, which tests each rule in descending strength and returns the first that matches,
#: so this constant stays true by construction as long as it mirrors that order.
_LEVEL_STRENGTH: Final[tuple[str, ...]] = ("L2", "L1", "L3", "L4", "L5")


def _level_rank(level: str | None) -> int:
    """Position in `_LEVEL_STRENGTH`, so "did this get weaker" is one comparison.

    `None` sorts last because it is not a level at all. The view returns it for two opposite
    states -- "no evidence yet" and "direct evidence on both sides, unresolved" -- and neither is
    stronger than an L5, which at least says something.
    """
    if level is None:
        return len(_LEVEL_STRENGTH)
    try:
        return _LEVEL_STRENGTH.index(level)
    except ValueError:
        return len(_LEVEL_STRENGTH)


def _existing_evidence(conn: sqlite3.Connection, assertion_id: str) -> tuple[EvidenceRequest, ...]:
    """The evidence an assertion already carries, as requests.

    Only the fields the checks actually read are reconstructed -- type, direction and group. This
    is not a faithful round-trip of the stored row and is not meant to be: it exists so that
    `attach_evidence` can ask "does the new item disagree with what is already here", which needs
    the directions and nothing else. Recreating every column would invite someone to write one of
    these back.
    """
    rows = conn.execute(
        "SELECT evidence_type, direction, independent_group, publication_id FROM evidence_item "
        "WHERE assertion_id = ? ORDER BY id",
        (assertion_id,),
    ).fetchall()
    return tuple(
        EvidenceRequest(
            evidence_type=str(row["evidence_type"]),
            direction=row["direction"],
            independent_group=str(row["independent_group"]),
            publication_id=row["publication_id"],
        )
        for row in rows
    )


def attach_evidence(
    conn: sqlite3.Connection,
    assertion_id: str,
    evidence: EvidenceRequest,
    *,
    curator: Curator,
    reason: str,
    now: datetime | None = None,
) -> AssertionResult:
    """Add one evidence item to an assertion that already exists.

    This is how an assertion reaches L2: a second group's direct evidence arrives and the view
    reports a different level for the same, untouched assertion row. The assertion is not edited
    -- PLAN.md J.1 says it never is -- and nothing recomputes or restores a level, because there
    is nowhere a level is kept.
    """
    _refuse_agent(curator, "add evidence to an assertion")
    row = conn.execute(
        "SELECT subject_type, subject_id, predicate, object_type, object_id, object_literal, "
        "context_id, product_id, direction FROM assertion WHERE id = ?",
        (assertion_id,),
    ).fetchone()
    if row is None:
        raise NotAssertable(
            f"no assertion {assertion_id!r}. Evidence points at a statement; there is no such "
            "thing as an evidence item on its own"
        )

    # Re-checked against the stored assertion rather than against a caller-supplied one, so that
    # the direction warning compares the evidence with the statement it will actually support.
    #
    # `already` is the evidence the assertion ALREADY carries, and leaving it out was a real
    # defect (found 2026-09-22 by rehearsal). `_check_evidence_agrees_with_itself` compares the
    # direct items in `request.evidence` with each other, so a request carrying only the new item
    # has nothing to disagree with and the check is vacuous on exactly the path a curator takes.
    # The consequence was silent and expensive: attaching a third group whose direction opposed
    # the existing two took `assertion_level`'s `n_direct_directions` from 1 to 2 and **demoted
    # the atlas's only L2 to L1**, with no warning anywhere. Demotion is a legitimate outcome --
    # a contradicting result is a finding, and J.4 wants a `conflict` row rather than a silent
    # merge -- but it must be something the curator is told about before they see the level move.
    already = _existing_evidence(conn, assertion_id)
    stored = AssertionRequest(
        subject_type=str(row["subject_type"]),
        subject_id=str(row["subject_id"]),
        predicate=str(row["predicate"]),
        object_type=str(row["object_type"]),
        object_id=row["object_id"],
        object_literal=row["object_literal"],
        context_id=row["context_id"],
        product_id=row["product_id"],
        direction=row["direction"],
        evidence=(*already, evidence),
    )
    missing, blockers, warnings = _check_evidence(conn, stored, evidence, 0)
    if missing or blockers:
        note = "; ".join([*blockers, *(str(m) for m in missing)])
        raise NotAssertable(f"{assertion_id}: {note}")
    warnings.extend(_check_evidence_agrees_with_itself(stored))
    # Read before the insert, so the caller can see a level move rather than infer it.
    before = level_of(conn, assertion_id)

    evidence_id = evidence_id_for(assertion_id, evidence)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    created = _insert_evidence(conn, assertion_id, evidence_id, evidence, curator)
    events: list[str] = []
    if created:
        events.append(
            _log(
                conn,
                curator,
                target_type="evidence_item",
                target_id=evidence_id,
                rationale=f"{reason} [{_evidence_sentence(evidence, curator)}]",
                moment=moment,
            )
        )
    conn.commit()
    after = level_of(conn, assertion_id)
    # Only a move to a WEAKER level warns. Reaching L2 is the happy path and the thing attaching
    # evidence is usually for; warning on it would bury the demotion warning in noise, and the
    # caller can see any move at all by comparing `level_before`.
    if _level_rank(after.level) > _level_rank(before.level):
        warnings.append(
            f"attaching this evidence moved the level from {before.level or 'none'} to "
            f"{after.level or 'none'} ({after.basis}) -- weaker than before. The assertion row "
            "itself is untouched: the level is a view (PLAN.md J.3), so this is the same "
            "statement being read differently now that the evidence behind it has changed"
        )
    return AssertionResult(
        assertion_id=assertion_id,
        evidence_ids=(evidence_id,),
        event_ids=tuple(events),
        created=False,
        evidence_created=1 if created else 0,
        level=after,
        warnings=tuple(warnings),
        level_before=before,
    )


def level_of(conn: sqlite3.Connection, assertion_id: str) -> EvidenceLevel:
    """Read L1-L5 out of the `assertion_level` view, with the basis that produced it.

    A read, always, and the only way this module ever speaks about a level. ``basis`` comes from
    the view's ``derived_reason``, which is what tells a NULL level meaning "nothing is known"
    apart from a NULL level meaning "direct evidence on both sides, unresolved" -- opposite
    states that arrive as the same NULL (see `fermdb.query.values.EvidenceLevel`).

    The import is inside the function on purpose: `fermdb.query` imports `fermdb.curate.promote`
    at module scope, so a top-level import here would close the cycle the moment
    `curate/__init__.py` exports this module.
    """
    from ..query.values import EvidenceLevel

    row = conn.execute(
        "SELECT level, derived_level, derived_reason, is_overridden, override_reason "
        "FROM assertion_level WHERE assertion_id = ?",
        (assertion_id,),
    ).fetchone()
    if row is None:
        raise NotAssertable(f"no assertion {assertion_id!r}, so it has no level")
    return EvidenceLevel(
        level=row["level"],
        basis=str(row["derived_reason"]),
        is_overridden=bool(row["is_overridden"]),
        override_reason=row["override_reason"],
    )


# ------------------------------------------------------------------- from already-curated rows


def _row(conn: sqlite3.Connection, table: str, row_id: str) -> sqlite3.Row:
    """Read one already-curated row, or refuse by name. ``table`` is never caller-supplied."""
    row: sqlite3.Row | None = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        raise NotAssertable(f"no row {row_id!r} in `{table}`")
    return row


def from_measurement(
    conn: sqlite3.Connection,
    measurement_id: str,
    *,
    predicate: str,
    evidence_type: str,
    independent_group: str,
    publication_id: str | None = None,
    direction: str | None = None,
    control_strain_id: str | None = None,
    control_condition_id: str | None = None,
    assay_method: str | None = None,
    span_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    context_id: str | None = None,
    note: str = "",
    confidence: str = "medium",
) -> AssertionRequest:
    """Draft the statement a promoted `measurement` supports.

    What the row supplies: its strain as the subject, its product as the object and as
    `product_id`, and its `assay_method` where it has one. What it does not, and is not guessed:

    * **the evidence type.** ``direct_perturbation`` and ``direct_biochemical`` are L1 and
      ``literature_assertion`` is L5, so choosing the type is choosing the level, which PLAN.md
      L.5 reserves for a person. There is no default.
    * **the direction.** A titer is a number. "Increases" is a comparison against a control, which
      lives in the reading of the experiment and not in the measurement row.
    * **the effect size.** The obvious wrong move is to copy `value_as_reported` into
      `assertion.effect_size`. A titer of 1.32 g/L is not an effect of 1.32; the effect is the
      difference from the control, and a fabricated one would be indistinguishable afterwards
      from a reported one.

    What it *does* supply, since schema v12, is the publication: `measurement.publication_id` is
    a real foreign key and all 97 rows were backfilled, so the paper is read off the row rather
    than asked for. An explicit ``publication_id`` still wins, for the case where the row's is
    NULL -- a measurement taken from a deposited dataset rather than from a paper.
    """
    row = _row(conn, "measurement", measurement_id)
    strain_id = row["strain_id"]
    product_id = row["product_id"]

    evidence = EvidenceRequest(
        evidence_type=evidence_type,
        independent_group=independent_group,
        # Read off the row, exactly as `from_modification` does. Schema v12 gave `measurement` a
        # real `publication_id` foreign key and backfilled all 97 rows, so J.5's last hop is a
        # join rather than a sentence, and asking a curator for what the row already knows would
        # be an invented gap. An explicit argument still wins, for a row whose column is NULL.
        publication_id=publication_id or row["publication_id"],
        span_id=span_id,
        direction=direction,
        strain_id=strain_id,
        control_strain_id=control_strain_id,
        control_condition_id=control_condition_id,
        measurement_id=measurement_id,
        # Copied, not invented: it is the same curated fact, in the column the evidence layer
        # keeps it in. An explicit argument still wins, because a curator who read the paper may
        # know the assay when the promoted row does not.
        assay_method=assay_method or row["assay_method"],
        confidence=confidence,
    )
    return AssertionRequest(
        subject_type=subject_type or "strain",
        subject_id=subject_id or strain_id,
        predicate=predicate,
        object_type=object_type or "product",
        object_id=object_id or product_id,
        context_id=context_id,
        product_id=product_id,
        direction=direction,
        evidence=(evidence,),
        note=note or f"from measurement {measurement_id} ({row['quantity_kind']})",
        confidence=confidence,
    )


def from_modification(
    conn: sqlite3.Connection,
    modification_id: str,
    *,
    predicate: str,
    evidence_type: str,
    object_type: str,
    object_id: str | None = None,
    object_literal: str | None = None,
    independent_group: str | None = None,
    publication_id: str | None = None,
    direction: str | None = None,
    span_id: str | None = None,
    measurement_id: str | None = None,
    control_strain_id: str | None = None,
    control_condition_id: str | None = None,
    assay_method: str | None = None,
    context_id: str | None = None,
    product_id: str | None = None,
    note: str = "",
    confidence: str = "medium",
) -> AssertionRequest:
    """Draft the statement a promoted `modification` supports.

    The modification is the subject: `assertion.subject_type` has a `modification` value, and a
    deletion of BAT1 is the thing the statement is about. The object is not derivable -- a
    modification affects *something*, and which product or phenotype is exactly the claim -- so it
    is an argument with no default.

    Unlike a measurement, this row closes its own J.5 chain: `modification.publication_id` is a
    real foreign key, so the publication is read from the row rather than asked for. An explicit
    ``publication_id`` still wins, for the case where the modification row's is NULL.
    """
    row = _row(conn, "modification", modification_id)
    evidence = EvidenceRequest(
        evidence_type=evidence_type,
        independent_group=independent_group,
        publication_id=publication_id or row["publication_id"],
        span_id=span_id,
        direction=direction,
        strain_id=row["strain_id"],
        control_strain_id=control_strain_id,
        control_condition_id=control_condition_id,
        measurement_id=measurement_id,
        assay_method=assay_method,
        confidence=confidence,
    )
    return AssertionRequest(
        subject_type="modification",
        subject_id=modification_id,
        predicate=predicate,
        object_type=object_type,
        object_id=object_id,
        object_literal=object_literal,
        context_id=context_id,
        product_id=product_id,
        direction=direction,
        evidence=(evidence,),
        note=note
        or f"from modification {modification_id} ({row['type']} of {row['target_locus']})",
        confidence=confidence,
    )


def from_bottleneck(
    conn: sqlite3.Connection,
    bottleneck_id: str,
    *,
    predicate: str,
    evidence_type: str,
    object_type: str,
    object_id: str | None = None,
    object_literal: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    independent_group: str | None = None,
    publication_id: str | None = None,
    span_id: str | None = None,
    measurement_id: str | None = None,
    strain_id: str | None = None,
    control_strain_id: str | None = None,
    control_condition_id: str | None = None,
    assay_method: str | None = None,
    direction: str | None = None,
    context_id: str | None = None,
    product_id: str | None = None,
    note: str = "",
    confidence: str = "medium",
) -> AssertionRequest:
    """Draft the statement a promoted `bottleneck` makes, and link the two.

    `bottleneck.assertion_id` is the column that makes a bottleneck "an assertion with a required
    shape" (PLAN.md G.8) rather than a free-floating opinion, and it is filled in on write.

    **The subject is the sharp edge, and it is worth knowing before you call this.**
    `assertion.subject_type` is a closed set of eleven typed references and `bottleneck` is not
    one of them; the subject has to be the *thing* that is bottlenecked. `bottleneck.reaction_id`
    gives that directly. `bottleneck.node` does not: it is free text, and all four bottlenecks in
    the atlas today carry only a node -- 'pyruvate node', 'compartment choice for the Ehrlich
    pathway'. Those are not identifiers and mapping them to the nearest reaction is the guess
    CONVENTIONS.md forbids, so the plan refuses and names `subject_id`. A curator says which
    reaction, metabolite or gene group the node means.

    The bottleneck row also carries no measurement, strain or control, so a direct evidence type
    asked for here will be refused for the fields it cannot produce -- which is the honest answer:
    a bottleneck record on its own is a claim about a paper, not a perturbation experiment.

    It does carry its paper: `bottleneck.publication_id` became a real foreign key in schema v12
    and all 4 rows were backfilled, so the publication is read off the row. An explicit argument
    still wins, for a bottleneck inferred from the curated pathway model rather than from a paper.
    """
    row = _row(conn, "bottleneck", bottleneck_id)
    if subject_type is None and subject_id is None and row["reaction_id"]:
        subject_type, subject_id = "reaction", str(row["reaction_id"])

    evidence = EvidenceRequest(
        evidence_type=evidence_type,
        independent_group=independent_group,
        # Schema v12 gave `bottleneck` the same real `publication_id` foreign key as
        # `modification` and backfilled all 4 rows, so the paper is read off the row here too.
        # An explicit argument still wins, for a bottleneck inferred from the curated pathway
        # model rather than from a paper, whose column is legitimately NULL.
        publication_id=publication_id or row["publication_id"],
        span_id=span_id,
        direction=direction,
        strain_id=strain_id,
        control_strain_id=control_strain_id,
        control_condition_id=control_condition_id,
        measurement_id=measurement_id,
        assay_method=assay_method,
        confidence=confidence,
    )
    described = row["reaction_id"] or row["transport_step"] or row["node"]
    return AssertionRequest(
        subject_type=subject_type or "reaction",
        subject_id=subject_id,
        predicate=predicate,
        object_type=object_type,
        object_id=object_id,
        object_literal=object_literal,
        context_id=context_id,
        product_id=product_id,
        direction=direction,
        evidence=(evidence,),
        bottleneck_id=bottleneck_id,
        note=note or f"from bottleneck {bottleneck_id} ({described}, {row['observation_type']})",
        confidence=confidence,
    )


def with_evidence(request: AssertionRequest, *evidence: EvidenceRequest) -> AssertionRequest:
    """Return ``request`` carrying additional evidence items.

    The requests are frozen, so a second group's evidence is added by building a new request
    rather than by mutating one -- which is the same rule the assertion itself follows.
    """
    return replace(request, evidence=(*request.evidence, *evidence))


def plan_many(
    conn: sqlite3.Connection, requests: Sequence[AssertionRequest]
) -> tuple[AssertionPlan, ...]:
    """Plan a batch, so a caller can report what would and would not be written in one pass.

    Nothing is skipped silently: every request comes back as a plan carrying its own reason, in
    the order given.
    """
    return tuple(plan_assertion(conn, request) for request in requests)
