"""The Dashboard read: what the atlas holds, and -- the useful half -- what it does not.

PLAN.md P.2 states the requirement for this page in one line:

    Coverage, not just totals -- *which* conditions and products are thin is the actionable number

A count of rows per table satisfies the letter of that and none of the intent. Twenty-two of this
atlas's sixty-one tables are empty right now, and a dashboard reporting twenty-two zeros has told
the reader nothing they can act on, because **the zeros do not all mean the same thing**:

  * ``measurement`` is empty and **18 proposed measurements are queued for curation**. Nothing is
    missing; a person has to review them. The number to show is 18, not 0.
  * ``conflict`` is empty and nothing is queued. No conflict has been proposed, found or ruled
    out. The honest reading is "never looked", which is a different call to action entirely.
  * A table absent from the schema altogether would also count zero rows, and that is a build
    problem rather than a data one. It is reported as its own state rather than folded in.

So an empty table is classified by *why* it is empty, which is the same three-state discipline
`values.py` applies to a single field, applied to a whole entity. The curation queue is the
evidence: `curation_task.record_kind` says which table each pending proposal is destined for, so
"empty but 18 waiting" is a fact the database already knows and nobody had asked it for.

:func:`page_readiness` is the second half, and exists because a query layer that cannot say
whether the interface above it has anything to render is missing the one question its first
caller will ask. Each page of PLAN.md P.2 declares the tables it reads; a page whose required
tables are all empty is reported as not renderable, with the reason. That mapping is data in
:data:`PAGES`, not branching logic -- CONVENTIONS.md, "Code": *"No `if product == 'ethanol'`."*
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..extract.schemas import RECORD_KINDS
from .builder import Select, count_of

__all__ = [
    "DESTINATION_TABLE",
    "ENTITIES",
    "PAGES",
    "Coverage",
    "EntityCoverage",
    "PageReadiness",
    "read_coverage",
    "page_readiness",
]

#: Which table each proposed record kind becomes once a curator accepts it.
#:
#: ``co_reported_higher_alcohols`` maps to ``measurement`` because `extract/schemas.py` gives that
#: section the same fields as a measurement -- it is a measurement of a different product, kept in
#: its own section only to record that it was admitted as a co-reported value (PLAN.md B.1) rather
#: than sought on its own.
DESTINATION_TABLE: Final[Mapping[str, str]] = {
    "strains": "strain",
    "modifications": "modification",
    "pathway_configurations": "pathway_configuration",
    "measurements": "measurement",
    "conditions": "condition_context",
    "bottlenecks": "bottleneck",
    "co_reported_higher_alcohols": "measurement",
}

#: The entities PLAN.md P.2 names for the dashboard, with the label the interface shows.
ENTITIES: Final[tuple[tuple[str, str], ...]] = (
    ("organism", "organisms"),
    ("strain", "strains"),
    ("product", "products"),
    ("experiment", "experiments"),
    ("gene", "genes"),
    ("gene_group", "gene groups"),
    ("pathway", "pathways"),
    ("reaction", "reactions"),
    ("pathway_route", "enumerated routes"),
    ("publication", "publications"),
    ("dataset", "datasets"),
    ("sra_run", "SRA runs"),
    ("measurement", "measurements"),
    ("condition_context", "condition contexts"),
    ("modification", "modifications"),
    ("pathway_configuration", "pathway configurations"),
    ("bottleneck", "bottlenecks"),
    ("assertion", "assertions"),
    ("evidence_item", "evidence items"),
    ("conflict", "conflicts"),
    ("knowledge_gap", "knowledge gaps"),
    ("curation_task", "curation tasks"),
)

#: Each page of PLAN.md P.2 and the tables it cannot render without. A page is listed against the
#: tables that carry its *subject*, not every table it touches -- the Gene page reads annotations
#: and expression too, but with no ``gene`` rows there is no page at all.
PAGES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("Dashboard", ()),
    ("Gene", ("gene",)),
    ("Strain", ("strain",)),
    ("Pathway", ("pathway", "reaction")),
    ("Experiment", ("experiment",)),
    ("Publication", ("publication",)),
    ("Product", ("product", "measurement")),
    ("Evidence", ("assertion", "evidence_item")),
    ("Compare", ("strain", "experiment")),
)


@dataclass(frozen=True)
class EntityCoverage:
    """One entity's row count, its queued proposals, and what the combination means."""

    entity: str
    label: str
    count: int
    pending: int
    exists: bool = True

    @property
    def state(self) -> str:
        """``missing_table`` | ``populated`` | ``awaiting_curation`` | ``never_populated``.

        The last two are both "zero rows" and are the distinction the whole module is for.
        """
        if not self.exists:
            return "missing_table"
        if self.count > 0:
            return "populated"
        return "awaiting_curation" if self.pending > 0 else "never_populated"

    @property
    def note(self) -> str:
        return {
            "missing_table": "no such table in this schema -- a build problem, not a data one",
            "populated": f"{self.count} row(s)",
            "awaiting_curation": (
                f"empty, but {self.pending} proposal(s) are queued for review; "
                "the gate is curation, not acquisition"
            ),
            "never_populated": "empty, and nothing has been proposed -- never looked",
        }[self.state]

    @property
    def is_actionable(self) -> bool:
        """True where a person acting today would change this number."""
        return self.state == "awaiting_curation"

    def as_json(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "label": self.label,
            "count": self.count,
            "pending_curation": self.pending,
            "state": self.state,
            "note": self.note,
            "is_actionable": self.is_actionable,
        }


@dataclass(frozen=True)
class PageReadiness:
    """Whether one PLAN.md P.2 page has anything to render, and why not if it has not."""

    page: str
    requires: tuple[str, ...]
    empty_requirements: tuple[str, ...]
    blocked_by_curation: bool

    @property
    def renderable(self) -> bool:
        return not self.empty_requirements

    @property
    def note(self) -> str:
        if self.renderable:
            return "has content"
        missing = ", ".join(self.empty_requirements)
        if self.blocked_by_curation:
            return f"empty: {missing} -- proposals are queued, awaiting curation"
        return f"empty: {missing} -- nothing proposed"

    def as_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "requires": list(self.requires),
            "renderable": self.renderable,
            "empty_requirements": list(self.empty_requirements),
            "blocked_by_curation": self.blocked_by_curation,
            "note": self.note,
        }


@dataclass(frozen=True)
class Coverage:
    """The whole dashboard payload."""

    entities: tuple[EntityCoverage, ...]
    pending_by_kind: Mapping[str, int]
    pages: tuple[PageReadiness, ...]

    @property
    def pending_total(self) -> int:
        return sum(self.pending_by_kind.values())

    def by_state(self, state: str) -> tuple[EntityCoverage, ...]:
        return tuple(entity for entity in self.entities if entity.state == state)

    def as_json(self) -> dict[str, Any]:
        return {
            "entities": [entity.as_json() for entity in self.entities],
            "pending_by_kind": dict(self.pending_by_kind),
            "pending_total": self.pending_total,
            "pages": [page.as_json() for page in self.pages],
            "summary": {
                "populated": len(self.by_state("populated")),
                "awaiting_curation": len(self.by_state("awaiting_curation")),
                "never_populated": len(self.by_state("never_populated")),
                "missing_table": len(self.by_state("missing_table")),
                "renderable_pages": sum(1 for page in self.pages if page.renderable),
                "total_pages": len(self.pages),
            },
        }


def _existing_tables(conn: sqlite3.Connection) -> frozenset[str]:
    rows = (
        Select("sqlite_master").columns("name").where("type IN (?, ?)", "table", "view").page(conn)
    )
    return frozenset(str(row["name"]) for row in rows)


def _pending_by_kind(conn: sqlite3.Connection) -> dict[str, int]:
    """Pending proposals per record kind, with every kind present even at zero.

    Every `RECORD_KINDS` entry is seeded to 0 first. A kind missing from the output would be
    ambiguous between "none queued" and "this kind is not a thing", and the extraction schema
    already answers the second question -- so the reader answers only the first.
    """
    counts = dict.fromkeys(RECORD_KINDS, 0)
    rows = (
        Select("curation_task")
        .columns("record_kind", "COUNT(*) AS n")
        .where("status = ?", "pending")
        .group_by("record_kind")
        .page(conn)
    )
    for row in rows:
        counts[str(row["record_kind"])] = int(row["n"])
    return counts


def _pending_by_table(pending_by_kind: Mapping[str, int]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for kind, count in pending_by_kind.items():
        table = DESTINATION_TABLE.get(kind)
        if table is not None:
            totals[table] = totals.get(table, 0) + count
    return totals


def read_coverage(
    conn: sqlite3.Connection, *, entities: Sequence[tuple[str, str]] = ENTITIES
) -> Coverage:
    """Read the dashboard in one pass.

    One query per entity plus two, which at this size is cheaper than the single clever query that
    would produce the same numbers less legibly.
    """
    present = _existing_tables(conn)
    pending_by_kind = _pending_by_kind(conn)
    pending_by_table = _pending_by_table(pending_by_kind)

    rows: list[EntityCoverage] = []
    for table, label in entities:
        if table not in present:
            rows.append(EntityCoverage(entity=table, label=label, count=0, pending=0, exists=False))
            continue
        total = int(count_of(table).scalar(conn) or 0)
        rows.append(
            EntityCoverage(
                entity=table,
                label=label,
                count=total,
                pending=pending_by_table.get(table, 0),
            )
        )

    counts = {row.entity: row.count for row in rows}
    return Coverage(
        entities=tuple(rows),
        pending_by_kind=pending_by_kind,
        pages=page_readiness(conn, counts=counts, pending_by_table=pending_by_table),
    )


def page_readiness(
    conn: sqlite3.Connection,
    *,
    counts: Mapping[str, int] | None = None,
    pending_by_table: Mapping[str, int] | None = None,
) -> tuple[PageReadiness, ...]:
    """Which PLAN.md P.2 pages have content, and what is blocking the ones that do not.

    ``counts`` and ``pending_by_table`` are accepted so :func:`coverage` can pass work it has
    already done; called on its own, this reads what it needs.
    """
    if counts is None or pending_by_table is None:
        present = _existing_tables(conn)
        needed = {table for _, requires in PAGES for table in requires}
        counts = {
            table: (int(count_of(table).scalar(conn) or 0) if table in present else 0)
            for table in needed
        }
        pending_by_table = _pending_by_table(_pending_by_kind(conn))

    readiness: list[PageReadiness] = []
    for page, requires in PAGES:
        empty = tuple(table for table in requires if counts.get(table, 0) == 0)
        readiness.append(
            PageReadiness(
                page=page,
                requires=requires,
                empty_requirements=empty,
                blocked_by_curation=any(pending_by_table.get(t, 0) > 0 for t in empty),
            )
        )
    return tuple(readiness)
