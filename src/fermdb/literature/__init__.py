"""Literature discovery: NCBI E-utilities search, corpus definition, and inclusion triage.

Three modules, three responsibilities (PLAN.md H.2 "Corpus construction", H.3 "Relevance ranking
and inclusion", R.2 "Relevance pipeline"):

    eutils.py     A polite, rate-limited, retrying E-utilities client over a pluggable transport.
                  Owns nothing about fermdb's data model; it only knows esearch/esummary/efetch.
    queries.py    Parses and validates data/literature/query_families.yaml, and the read queries
                  (`family_status`, `excluded_records`, `needs_full_text`) that report corpus
                  health against it.
    discovery.py  Runs one query family end-to-end: esearch, esummary, dedupe by DOI/PMID/
                  normalized title, and the R.2 product-tier-aware triage into `screening_record`.

See `src/fermdb/cli.py`'s `literature discover` / `literature status` subcommands for the CLI, and
`src/fermdb/db/schema.sql`'s "14. Literature discovery" section for the tables this writes to.
"""

from __future__ import annotations

from .discovery import FamilyRunResult, Hit, canonical_publication_id, normalize_title, run_family
from .eutils import EsearchResult, EutilsClient, EutilsError, Transport, UrllibTransport
from .queries import (
    FamilyStatus,
    QueryFamilies,
    QueryFamiliesError,
    QueryFamily,
    SubQuery,
    excluded_records,
    family_status,
    load_query_families,
    needs_full_text,
)

__all__ = [
    "EsearchResult",
    "EutilsClient",
    "EutilsError",
    "FamilyRunResult",
    "FamilyStatus",
    "Hit",
    "QueryFamilies",
    "QueryFamiliesError",
    "QueryFamily",
    "SubQuery",
    "Transport",
    "UrllibTransport",
    "canonical_publication_id",
    "excluded_records",
    "family_status",
    "load_query_families",
    "needs_full_text",
    "normalize_title",
    "run_family",
]
