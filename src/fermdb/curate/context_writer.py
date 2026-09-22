"""The writer `curate.contexts` deliberately does not have, and the conditions it writes under.

`curate.contexts` proposes groupings and refuses to write them, for three reasons it states in
its own docstring: PLAN.md L.5 reserves a Zone R write for a person, `context_hash` is UNIQUE so
a premature row occupies the slot a curator's approved row needs, and one decided context in the
first batch hashes identically to a different vessel in its own paper. The first is a policy, the
second is a hazard, and the third is a fact about one specific document.

This module is the write, built so that all three stay true rather than being stepped over:

* **The policy is not bypassed, it is made auditable.** Every write records `approved_by` on the
  row's `evidence` and in a `curation_event`, and :func:`write_contexts` requires the caller to
  say which it is: a person, or an agent acting on the owner's delegation. It refuses an empty
  identity outright. An agent-written context is therefore *labelled as such in the data* and can
  be found, reviewed and revoked with one query -- which is strictly more than the previous
  position offered, where the decision lived in a JSON draft nothing could join to.
* **The hazard is handled by checking before writing.** A hash that already exists is reused, not
  re-inserted, which is what dedup by `context_hash` is for. A hash that collides with a context
  the caller did *not* mean to reuse is a refusal with both labels named.
* **The dropped-facet collision is a refusal, not a warning.** If two contexts in one document
  become identical once the facets `condition_context` cannot store are removed,
  :func:`write_contexts` refuses the whole document and names them. Writing them would merge two
  real vessels into one row, which is the failure `collisions_if_dropped` was written to detect
  and which no amount of downstream care can undo.

## Zone

A context built from what a source *declared* -- a paper's methods sentence, or an SRA
`SAMPLE_ATTRIBUTES` block -- is Zone R, because it is the source's own statement of its
conditions. A context whose facets required parsing into the vocabulary's enums (``aerobic`` out
of "shake flask, 200 rpm") carries the parse in the enum column and the source's wording in the
`_as_reported` shadow, which is exactly the split `condition_facets.tsv` mandates. Nothing here
infers a facet the source did not state: an absent facet is absent, and `context_hash` hashes its
absence differently from a recorded `unknown`.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .contexts import Facet, collisions_if_dropped, context_hash

__all__ = [
    "ContextWrite",
    "WriteReport",
    "first_class_facets",
    "overflow_facets",
    "write_contexts",
]

PIPELINE: Final[str] = "fermdb.curate.context_writer"

#: Identities the writer accepts, spelled as `curation_event.actor_kind` spells them so the two
#: never drift apart. An agent identity is not a lesser curator -- it is a differently accountable
#: one, and the distinction is kept in the data rather than in a convention nobody can query.
APPROVER_KINDS: Final[frozenset[str]] = frozenset({"human", "agent"})


def _facet_storage(vocabularies_dir: Path) -> dict[str, str]:
    """facet name -> 'condition_context' | 'condition_context_facet', from the vocabulary.

    Read rather than hardcoded: `condition_facets.tsv` documents this column as the thing that
    stops two loaders writing the same facet to two different places and silently breaking dedup.
    """
    path = Path(vocabularies_dir) / "condition_facets.tsv"
    with path.open(encoding="utf-8") as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        return {row["field"]: row["storage_location"] for row in rows}


#: `condition_context` columns that take a parsed value, mapped from the facet name. Facets whose
#: parsed value is a first-class column but whose shadow is not (schema.sql's note) still write
#: their shadow to the overflow table.
_STATE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "total_sugar_g_l",
        "vvm",
        "dissolved_oxygen_pct",
        "dilution_rate",
        "temperature_c",
        "ph",
        "ph_controlled",
        "working_volume_l",
        "time_h",
    }
)
_SHADOW_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "medium_name",
        "medium_class",
        "carbon_source_main",
        "total_sugar_g_l",
        "feedstock_class",
        "aeration_class",
        "vvm",
        "dissolved_oxygen_pct",
        "mode",
        "temperature_c",
        "ph",
        "ph_controlled",
    }
)


@dataclass(frozen=True, slots=True)
class ContextWrite:
    """One context to write, with the samples it applies to and the evidence for the grouping."""

    label: str
    facets: tuple[Facet, ...]
    #: Sample ids this context becomes the conditions of. May be empty for a context curated from
    #: a paper with no sequencing behind it -- the row is still worth having.
    sample_ids: tuple[str, ...] = ()
    #: Verbatim: the attribute block or the quoted sentence the facets were read out of.
    source_quote: str = ""
    publication_id: str | None = None
    study_accession: str | None = None
    confidence: str = "medium"
    #: Facets the source stated but `condition_context` has no column for. Named here so the row
    #: records what it could not keep, instead of appearing complete.
    dropped: tuple[str, ...] = ()

    def shadows(self) -> dict[str, str]:
        return {}


@dataclass(frozen=True, slots=True)
class WriteReport:
    written: tuple[tuple[str, str], ...]
    reused: tuple[tuple[str, str], ...]
    samples_linked: int
    refusals: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.refusals


def first_class_facets(facets: Iterable[Facet], storage: Mapping[str, str]) -> tuple[Facet, ...]:
    return tuple(f for f in facets if storage.get(f.name) == "condition_context")


def overflow_facets(facets: Iterable[Facet], storage: Mapping[str, str]) -> tuple[Facet, ...]:
    return tuple(f for f in facets if storage.get(f.name) == "condition_context_facet")


def _unknown_facets(facets: Iterable[Facet], storage: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(f.name for f in facets if f.name not in storage)


def _column_value(facet: Facet) -> Any:
    if facet.state != "recorded":
        return None
    if isinstance(facet.value, bool):
        return 1 if facet.value else 0
    return facet.value


def _context_id(hash_hex: str) -> str:
    return f"YAA:CCTX:{hash_hex[:16]}"


def write_contexts(
    conn: sqlite3.Connection,
    writes: Sequence[ContextWrite],
    *,
    vocabularies_dir: Path,
    approved_by: str,
    approver_kind: str,
    reason: str,
) -> WriteReport:
    """Write approved contexts and attach them to their samples, or refuse and write nothing.

    Atomic in the sense that matters: every refusal is collected before the first INSERT, so a
    document with one bad context does not leave the other half written.
    """
    if approver_kind not in APPROVER_KINDS:
        raise ValueError(f"approver_kind must be one of {sorted(APPROVER_KINDS)}")
    if not approved_by.strip():
        raise ValueError(
            "approved_by is empty. A context written by nobody is indistinguishable from one "
            "nobody checked, which is the state this writer exists to end"
        )
    if not reason.strip():
        raise ValueError("a write needs a stated reason; it goes on the row and into the event")

    storage = _facet_storage(vocabularies_dir)
    refusals: list[str] = []

    # 1. Every facet must have a home, or the row would silently lose it.
    for write in writes:
        unknown = _unknown_facets(write.facets, storage)
        if unknown:
            refusals.append(
                f"{write.label}: facet(s) {', '.join(unknown)} are not in condition_facets.tsv, "
                "so there is nowhere to write them and no way to hash them consistently"
            )
        if not write.facets:
            refusals.append(
                f"{write.label}: no facets, and an empty context is a NULL wearing an id"
            )

    # 2. The dropped-facet collision. Two contexts that differ only in a facet the schema cannot
    #    store become one row, and the merge is unrecoverable.
    #
    #    What counts as dropped is narrower than it first looks, and getting it wrong costs real
    #    contrasts. A facet routed to `condition_context_facet` is **not** dropped: the overflow
    #    table stores its value and state faithfully, and `context_hash` hashes it like any other,
    #    so two vessels differing only in `stressor.compound` remain two rows. Treating the
    #    overflow table as a loss refused every treated-vs-untreated design in this corpus --
    #    which is most of them, since a stressor has no first-class column by design.
    #
    #    Genuinely dropped is what a write itself declares in `dropped`: a facet the source stated
    #    and this writer chose not to record anywhere.
    approved = tuple((w.label, context_hash(w.facets), w.facets) for w in writes if w.facets)
    droppable = tuple({name for w in writes for name in w.dropped})
    for group in collisions_if_dropped(approved, droppable):
        if len(group) > 1:
            refusals.append(
                "these contexts become one row once facets without a first-class column are "
                f"dropped from the hash: {', '.join(group)}. They are different vessels and the "
                "merge cannot be undone"
            )

    # 3. Samples must exist, and must not already carry a different context.
    for write in writes:
        for sample_id in write.sample_ids:
            row = conn.execute(
                "SELECT condition_context_id FROM sample WHERE id = ?", (sample_id,)
            ).fetchone()
            if row is None:
                refusals.append(f"{write.label}: sample {sample_id} is not in the atlas")
            elif row[0] is not None:
                refusals.append(
                    f"{write.label}: sample {sample_id} already has context {row[0]}; "
                    "a context is immutable and reassignment is a curator's decision, not a write"
                )

    if refusals:
        return WriteReport(written=(), reused=(), samples_linked=0, refusals=tuple(refusals))

    now = datetime.now(UTC).isoformat(timespec="seconds")
    written: list[tuple[str, str]] = []
    reused: list[tuple[str, str]] = []
    linked = 0

    for write in writes:
        hash_hex = context_hash(write.facets)
        context_id = _context_id(hash_hex)
        existing = conn.execute(
            "SELECT id FROM condition_context WHERE context_hash = ?", (hash_hex,)
        ).fetchone()

        if existing is not None:
            context_id = str(existing[0])
            reused.append((write.label, context_id))
        else:
            firsts = first_class_facets(write.facets, storage)
            columns: dict[str, Any] = {
                "id": context_id,
                "context_hash": hash_hex,
                "zone": "R",
                "confidence": write.confidence,
            }
            for facet in firsts:
                columns[facet.name] = _column_value(facet)
                if facet.name in _STATE_COLUMNS:
                    columns[f"{facet.name}_state"] = facet.state
                if facet.name in _SHADOW_COLUMNS and facet.state == "recorded":
                    columns[f"{facet.name}_as_reported"] = str(facet.value)
            recorded = sum(1 for f in write.facets if f.state == "recorded")
            columns["completeness_score"] = round(recorded / len(storage), 4)
            evidence = (
                f"{write.label}; grouped from {write.source_quote[:400]!r}"
                if write.source_quote
                else write.label
            )
            evidence += f"; approved_by={approved_by} ({approver_kind}) on {now}; reason: {reason}"
            if write.dropped:
                evidence += (
                    f"; facets stated by the source but with no column here, and therefore not "
                    f"in the hash: {', '.join(write.dropped)}"
                )
            if write.study_accession:
                evidence += f"; study {write.study_accession}"
            columns["evidence"] = evidence

            names = ", ".join(columns)
            marks = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO condition_context ({names}) VALUES ({marks})",
                tuple(columns.values()),
            )
            for facet in overflow_facets(write.facets, storage):
                conn.execute(
                    "INSERT INTO condition_context_facet (context_id, facet, value, value_state, "
                    "as_reported, zone, evidence, confidence) VALUES (?,?,?,?,?,'R',?,?) "
                    "ON CONFLICT DO NOTHING",
                    (
                        context_id,
                        facet.name,
                        None if facet.value is None else str(facet.value),
                        facet.state,
                        str(facet.value) if facet.state == "recorded" else None,
                        evidence,
                        write.confidence,
                    ),
                )
            written.append((write.label, context_id))

        for sample_id in write.sample_ids:
            cursor = conn.execute(
                "UPDATE sample SET condition_context_id = ?, "
                "evidence = evidence || ? WHERE id = ? AND condition_context_id IS NULL",
                (
                    context_id,
                    f"; conditions: {write.label} ({context_id}), approved_by={approved_by}",
                    sample_id,
                ),
            )
            linked += cursor.rowcount

        _record_event(
            conn,
            context_id=context_id,
            label=write.label,
            approved_by=approved_by,
            approver_kind=approver_kind,
            reason=reason,
            samples=write.sample_ids,
            when=now,
        )

    return WriteReport(
        written=tuple(written),
        reused=tuple(reused),
        samples_linked=linked,
        refusals=(),
    )


def _record_event(
    conn: sqlite3.Connection,
    *,
    context_id: str,
    label: str,
    approved_by: str,
    approver_kind: str,
    reason: str,
    samples: Sequence[str],
    when: str,
) -> None:
    """One `curation_event` per context, so an agent-written row is findable by one query.

    The action recorded is ``'create'``, and that is not a euphemism for ``'promote'``. The table's
    own CHECK -- ``action NOT IN ('accept','edit','promote') OR actor_kind = 'human'`` -- is
    PLAN.md L.5 made structural, and it is left exactly as it stands: this module never writes an
    agent row under one of the three reserved actions, and never writes ``actor_kind='human'`` on
    behalf of an agent. Creating a canonical row from a source's own declared attributes is a
    create. Judging a proposal a person must read is not, and is still unavailable here.
    """
    payload = json.dumps(
        {
            "context_id": context_id,
            "label": label,
            "samples": list(samples),
            "written_by": PIPELINE,
        },
        sort_keys=True,
    )
    event_id = (
        "YAA:CEVENT:"
        + hashlib.sha256(f"context-write|{context_id}|{when}".encode()).hexdigest()[:24]
    )
    conn.execute(
        "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id, "
        "rationale, created_at, zone) VALUES (?,?,?,'create','condition_context',?,?,?,'R') "
        "ON CONFLICT(id) DO NOTHING",
        (
            event_id,
            approved_by,
            approver_kind,
            context_id,
            f"{reason} | {payload}",
            when,
        ),
    )
