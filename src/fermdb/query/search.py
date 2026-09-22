"""Cross-entity search: one box, several tables, and no pretence of ranking between them.

A single search over publications, genes, strains, products and pathways has an obvious trap:
merging the hits into one relevance-ordered list implies a scoring function that compares "a
paper whose title contains the word" with "a strain whose name is exactly the word". No such
function exists here, so results stay **grouped by kind**, each group ordered by its own
sensible key, and each group reporting its own truncation.

Matching is `LIKE '%term%'` over a small number of named columns. That is a substring match, not
a full-text index: it will miss a paper that says "isobutanol tolerance" when asked for
"tolerant", and it says so in `technique` rather than letting a caller assume recall it does not
have. PLAN.md's semantic and hybrid retrieval layer is a later phase; this is the honest
placeholder, and labelling it as one is what keeps it from being mistaken for the real thing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Page, Select

__all__ = ["SearchHits", "SearchGroup", "search"]

#: What each kind searches and how it orders. Kept as data so adding a kind is one entry and
#: cannot forget to report truncation.
_KINDS: dict[str, dict[str, Any]] = {
    "publication": {
        "table": "publication",
        "columns": ("id", "title", "year", "journal", "doi"),
        "match": ("title", "doi", "pmid"),
        "order": ("year DESC", "id"),
        "label": "Publications",
    },
    "gene": {
        "table": "gene",
        "columns": (
            "id",
            "systematic_name",
            "standard_name",
            "gene_group_id",
            "organism_id",
        ),
        # Both names are matched because both are used in the wild: a paper says ADH2, the
        # atlas keys on YMR303C, and a reader who knows only one of them still has to find it.
        "match": ("id", "systematic_name", "standard_name"),
        "order": ("standard_name", "systematic_name"),
        "label": "Genes",
    },
    "gene_group": {
        "table": "gene_group",
        "columns": ("id", "anchor_id", "standard_name", "scope"),
        "match": ("id", "anchor_id", "standard_name"),
        "order": ("standard_name",),
        "label": "Gene groups",
    },
    "strain": {
        "table": "strain",
        "columns": ("id", "canonical_name", "class", "organism_id"),
        "match": ("id", "canonical_name"),
        "order": ("canonical_name", "id"),
        "label": "Strains",
    },
    "product": {
        "table": "product",
        "columns": ("id", "name", "tier", "formula"),
        "match": ("id", "name", "formula"),
        "order": ("tier", "name"),
        "label": "Products",
    },
    "pathway": {
        "table": "pathway",
        "columns": ("id", "name"),
        "match": ("id", "name"),
        "order": ("name",),
        "label": "Pathways",
    },
    "metabolite": {
        "table": "metabolite",
        "columns": ("id", "name", "formula", "carrier"),
        "match": ("id", "name", "formula"),
        "order": ("name",),
        "label": "Metabolites",
    },
    "reaction": {
        "table": "reaction",
        "columns": ("id", "name", "ec_number", "compartment_id"),
        "match": ("id", "name", "ec_number"),
        "order": ("name",),
        "label": "Reactions",
    },
}


@dataclass(frozen=True)
class SearchGroup:
    """Hits of one kind, with the truncation flag that belongs to this group alone."""

    kind: str
    label: str
    page: Page

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            **self.page.as_json(),
        }


@dataclass(frozen=True)
class SearchHits:
    """Every group, plus what the search is and is not able to do."""

    term: str
    groups: tuple[SearchGroup, ...]

    @property
    def total(self) -> int:
        return sum(len(group.page) for group in self.groups)

    def as_json(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "total": self.total,
            "groups": [g.as_json() for g in self.groups if len(g.page)],
            "empty_kinds": [g.kind for g in self.groups if not len(g.page)],
            "technique": "substring match (LIKE) over named columns",
            "recall_caveat": (
                "substring matching only -- a morphological variant or a synonym will not match, "
                "and no result is ranked against a result of another kind"
            ),
        }


def _columns_of(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")'))


def search(
    conn: sqlite3.Connection,
    term: str,
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int = 10,
) -> SearchHits:
    """Search every kind (or the named ones) for ``term``.

    A blank term returns empty groups rather than everything: an empty box should not be a
    request for the whole atlas.
    """
    term = term.strip()
    if not term:
        return SearchHits(term="", groups=())

    wanted = kinds or tuple(_KINDS)
    pattern = f"%{term}%"
    groups: list[SearchGroup] = []

    for kind in wanted:
        spec = _KINDS.get(kind)
        if spec is None:
            continue
        # Columns are checked against the live schema rather than assumed: this module names
        # optional columns (`gene.symbol`) that a migration may not have added yet, and a hard
        # failure on the search box would take down every other kind with it.
        available = _columns_of(conn, str(spec["table"]))
        columns = tuple(c for c in spec["columns"] if c in available)
        match_on = tuple(c for c in spec["match"] if c in available)
        if not columns or not match_on:
            continue

        select = Select(str(spec["table"])).columns(*columns)
        clause = " OR ".join(f"{column} LIKE ?" for column in match_on)
        select = select.where(f"({clause})", *([pattern] * len(match_on)))
        order = tuple(o for o in spec["order"] if o.split()[0] in available)
        if order:
            select = select.order_by(*order)
        groups.append(
            SearchGroup(kind=kind, label=str(spec["label"]), page=select.page(conn, limit=limit))
        )

    return SearchHits(term=term, groups=tuple(groups))
