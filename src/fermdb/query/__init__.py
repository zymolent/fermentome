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

What is deliberately **not** here yet: graph traversal, lexical and semantic search (PLAN.md O.1
lists four modalities; this package implements the first). They are additive and are listed as
deferred in Q.5. Nothing above this package should be written in a way that assumes only one
modality will ever exist.
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
    "DESTINATION_TABLE",
    "ENTITIES",
    "MAX_ROWS",
    "PAGES",
    "Absence",
    "CONTEXT_CHARS",
    "Cited",
    "Coverage",
    "EntityCoverage",
    "EvidenceLevel",
    "Finding",
    "FullTextAvailability",
    "Page",
    "PageReadiness",
    "ProposedField",
    "PublicationRead",
    "Quantity",
    "QueryError",
    "QueryValueError",
    "ReviewPacket",
    "Select",
    "ScreeningRead",
    "SpanView",
    "Value",
    "Zone",
    "corpus_shape",
    "count_of",
    "read_coverage",
    "read_publication",
    "review_packet",
    "review_queue",
    "search_publications",
    "from_state_column",
    "from_text_column",
    "page_readiness",
]
