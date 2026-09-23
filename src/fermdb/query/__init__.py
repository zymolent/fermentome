"""The QUERY layer of PLAN.md D.3 -- everything an interface reads the atlas through.

::

    INTERFACE     web UI - REST API - MCP server - exports - notebooks
    QUERY         structured SQL - graph traversal - lexical - semantic     <- this package
    KNOWLEDGE     assertions - evidence - conflicts - curation queue
    DOMAIN        genomic - transcriptomic - metabolic - engineering - ...

D.3's rule is that each layer may call only the layer below it, and it names the violation to
guard against: *"the UI reaching into files directly"*. Until now there was nothing between the
interface tier and `sqlite3`, so any UI would have committed that violation on its first line --
not through carelessness, but because no alternative existed.

What is here:

* :mod:`~fermdb.query.values` -- the three-state `Value`, `Quantity`, `EvidenceLevel` and `Cited`.
  The evidence architecture of PLAN.md J and the missing-value rule of CONVENTIONS.md, expressed
  as types so that serializing cannot quietly discard them.
* :mod:`~fermdb.query.builder` -- a read-only query builder. No writes, no interpolated values,
  and pages that report their own truncation.
* :mod:`~fermdb.query.coverage` -- the Dashboard read, including why each empty table is empty.
* :mod:`~fermdb.query.pathways` -- the Pathway read, with what the atlas cannot yet draw.
* :mod:`~fermdb.query.review` -- one proposal with its re-resolved quote and what accepting
  it would write. The curation queue's read side.
* :mod:`~fermdb.query.publications` -- one paper, what is held of it, and every finding with
  the sentence it came from read back out of the document.
* :mod:`~fermdb.query.genes` -- one gene, its pathway role, and the P.2 sections the atlas
  cannot fill, named rather than omitted.
* :mod:`~fermdb.query.traceability` -- PLAN.md J.5's walk: every active assertion resolved hop
  by hop back to a source and a curator, with each break named and located. The CI gate, and the
  one read here whose job is to fail.

* :mod:`~fermdb.query.lexical` -- PLAN.md O.1's lexical modality: an FTS5 index over every
  searchable entity, a synonym dictionary built from the alias tables, and a ranking in which
  evidence level outranks textual fit. The index is derived and is built by
  ``fermdb query index-build``, never by a migration.

What is deliberately **not** here yet: graph traversal and semantic search (PLAN.md O.1 lists four
modalities; this package implements the structured and the lexical ones). They are additive and
are listed as deferred in Q.5. Nothing above this package should be written in a way that assumes
only one modality will ever exist.
"""

from __future__ import annotations

from .builder import MAX_ROWS, Page, QueryError, Select, count_of
from .coverage import (
    DESTINATION_TABLE,
    ENTITIES,
    PAGES,
    Coverage,
    EntityCoverage,
    PageReadiness,
    page_readiness,
    read_coverage,
)
from .genes import AnnotationRead, GeneRead, ReactionRoleRead, list_genes, read_gene
from .lexical import (
    IndexReport,
    LexicalError,
    LexicalHit,
    LexicalHits,
    build_index,
    fts5_available,
    index_status,
    search_lexical,
)
from .publications import (
    Finding,
    FullTextAvailability,
    PublicationRead,
    ScreeningRead,
    corpus_shape,
    read_publication,
    search_publications,
)
from .review import (
    CONTEXT_CHARS,
    ProposedField,
    ReviewPacket,
    SpanView,
    review_packet,
    review_queue,
)
from .traceability import (
    BREAK_KINDS,
    AssertionChain,
    Break,
    EvidenceChain,
    Gap,
    Walk,
    exit_code,
    walk_assertions,
)
from .values import (
    Absence,
    Cited,
    EvidenceLevel,
    Quantity,
    QueryValueError,
    Value,
    Zone,
    from_state_column,
    from_text_column,
)

__all__ = [
    "BREAK_KINDS",
    "IndexReport",
    "LexicalError",
    "LexicalHit",
    "LexicalHits",
    "build_index",
    "fts5_available",
    "index_status",
    "search_lexical",
    "DESTINATION_TABLE",
    "ENTITIES",
    "MAX_ROWS",
    "PAGES",
    "Absence",
    "AnnotationRead",
    "AssertionChain",
    "Break",
    "CONTEXT_CHARS",
    "Cited",
    "Coverage",
    "EntityCoverage",
    "EvidenceChain",
    "EvidenceLevel",
    "Finding",
    "Gap",
    "Walk",
    "GeneRead",
    "FullTextAvailability",
    "Page",
    "PageReadiness",
    "ProposedField",
    "PublicationRead",
    "Quantity",
    "QueryError",
    "QueryValueError",
    "ReactionRoleRead",
    "ReviewPacket",
    "Select",
    "ScreeningRead",
    "SpanView",
    "Value",
    "Zone",
    "corpus_shape",
    "count_of",
    "exit_code",
    "walk_assertions",
    "read_coverage",
    "read_gene",
    "read_publication",
    "review_packet",
    "review_queue",
    "search_publications",
    "from_state_column",
    "list_genes",
    "from_text_column",
    "page_readiness",
]
