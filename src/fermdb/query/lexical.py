"""The lexical modality of PLAN.md O.1: FTS5 over the atlas, a synonym dictionary built from
the alias tables, and a ranking that says out loud what moved each result.

`search.py` is the substring placeholder this replaces for the cases it can serve, and its own
header says so: *"PLAN.md's semantic and hybrid retrieval layer is a later phase; this is the
honest placeholder."* Three things separate this module from it.

* **It is an index, not a scan.** `LIKE '%term%'` cannot use an index, has no notion of a term,
  and cannot rank. FTS5 gives a tokenized inverted index and `bm25()`, which is a real relevance
  score rather than an ordering by whatever column happened to be handy.
* **It ranks across kinds, which `search.py` deliberately refuses to do.** That refusal was
  correct for what it described: it had no scoring function that could compare "a paper whose
  title contains the word" with "a strain whose name is exactly the word", so it grouped instead
  of inventing one. Here every entity becomes a *document* with the same two fields (`name`,
  `body`) in one index, scored by one function with one set of weights. A cross-kind order
  therefore exists and is defensible; it is not the old comparison with a number bolted on.
* **Evidence level participates in the ranking.** PLAN.md O.1: *"Evidence level participating in
  ranking is a deliberate scientific choice: an L1 result should outrank a textually
  better-matching L5 one."* That is implemented as a guarantee rather than a hope -- see
  `_EVIDENCE_WEIGHT` for the arithmetic that makes it one -- and every component of the score is
  reported separately, so a reader can see *why* a result is where it is instead of being handed
  one opaque number.

**SQLite FTS5, not Postgres FTS.** O.1 says "Postgres FTS with a synonym dictionary built from
the alias tables", written when N.1 still recommended PostgreSQL. `docs/reference/
OPEN_QUESTIONS.md` Q2 withdrew that and the engine is SQLite, so the modality is FTS5 -- which
ships inside the stdlib `sqlite3` in every build this project has met, but is a *compile-time*
option and so is checked at runtime rather than assumed (`fts5_available`). Without it this
module refuses to build an index and says which command and which interpreter to blame, because
the alternative -- quietly falling back to `LIKE` -- would hand a caller the recall of a
substring scan under the name of a full-text index.

**One thing FTS5 does not have, and what is done instead.** Postgres has a synonym *dictionary*
inside the tokenizer: `ts_lexize` folds an alias to its canonical form at index time and at query
time, invisibly. FTS5's equivalent hook is a custom tokenizer, which is a C extension. So the
dictionary here is built in two places instead, both of them visible:

1. *At index time*, every alias of an entity is written into that entity's own `name` field. A
   strain is findable by any name it has ever been called.
2. *At query time*, `lexical_synonym` expands a query term to the other names of the entity it
   belongs to, so searching `YMR303C` also finds the **paper** whose title says `ADH2`. This is
   the half that matters, and the half a `LIKE` scan can never do.

The dictionary's honest coverage today is in the build report, and it is thin:
`strain_alias` holds **0 rows** on the live atlas, so the strain half of the dictionary is
empty; the gene and gene-group name pairs (36 of each) are the only live synonyms. The machinery
is correct and tested against fixture aliases; nothing here should be read as a claim that a rich
synonym layer exists.

**This index is a derived artifact, not a fact** (PLAN.md Zone H, D.2): it is regenerable from
the tables in full, so it is built by an explicit `index-build` command (M.2's pipeline of that
name), never by a schema migration, and `schema.sql` does not mention it. It owns four tables of
its own, all prefixed `lexical_`, all droppable, and none of them carrying a foreign key into the
core schema -- a derived artifact that constrains its own sources is not derived any more.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fermdb.query.values import EvidenceLevel

__all__ = [
    "BUILDER_VERSION",
    "BUILD_COMMAND",
    "Contribution",
    "Fts5Unavailable",
    "IndexNotBuilt",
    "IndexReport",
    "LexicalError",
    "LexicalHit",
    "LexicalHits",
    "SynonymCoverage",
    "build_index",
    "fts5_available",
    "index_status",
    "search_lexical",
]

#: Bumped when the shape of the `lexical_*` tables changes. A mismatch drops and rebuilds rather
#: than migrating: for a derived artifact, "throw it away and regenerate" is always available and
#: is always cheaper than a migration, which is exactly what makes it derived.
BUILDER_VERSION: Final[int] = 1

#: Named in every error that means "there is no index", so the reader is never left to guess.
BUILD_COMMAND: Final[str] = "fermdb query index-build"

#: How much of one publication's quoted spans are indexed. The atlas stores **no abstracts** --
#: `publication` has title, journal, doi, pmid, year and nothing else -- so the nearest thing to
#: the "abstracts" O.1 names is `span.quoted_text`, the sentences extraction quoted out of full
#: text. Those are real, in-atlas, evidence-bearing words and they are indexed; on the live atlas
#: that is 2,548 spans over 31 of 5,164 publications, so it deepens a few papers rather than
#: covering the corpus. The cap keeps one heavily extracted paper from dominating the index by
#: length alone, and the build report counts the documents it truncated instead of hiding them.
SPAN_CHAR_CAP: Final[int] = 8000

# ------------------------------------------------------------------------------- the ranking

#: Text weight. The unit against which the other two are set.
_TEXT_WEIGHT: Final[float] = 1.0

#: Recency weight, applied to publication years only -- see `_recency_score` for the bias this
#: carries and why it is reported rather than papered over.
_RECENCY_WEIGHT: Final[float] = 0.25

#: Evidence level as a 0..1 score, one step of 0.2 per level. Ungraded (no assertion about this
#: entity at all, or direct evidence in open conflict) scores 0.0 -- the ranking cannot invent a
#: level the evidence view declines to give. A conflicted entity and an unevidenced one therefore
#: rank alike, and are *displayed* differently: the hit carries an `EvidenceLevel`, whose
#: `is_conflicted` keeps PLAN.md J.4's distinction visible where a reader can act on it.
_EVIDENCE_SCORES: Final[Mapping[str, float]] = {
    "L1": 1.0,
    "L2": 0.8,
    "L3": 0.6,
    "L4": 0.4,
    "L5": 0.2,
}

#: 7.0, and the value is derived rather than chosen by taste.
#:
#: O.1 requires that "an L1 result should outrank a textually better-matching L5 one". A weighted
#: sum only *guarantees* that if one evidence step outweighs everything the other terms can swing.
#: The text term is min-max normalized over the candidate pool, so its full range is exactly
#: `_TEXT_WEIGHT` (1.0); recency's is `_RECENCY_WEIGHT` (0.25). Their combined range is 1.25, and
#: one evidence step is ``0.2 * 7.0 = 1.4 > 1.25``. So **no textual or recency difference can
#: overturn any evidence-level difference**, which is stronger than the rule O.1 states and is
#: the only version of it that holds for every pair of results rather than most of them.
#:
#: The cost is stated plainly: within a level, text decides; between levels, it does not. A
#: reader who wants the textually best match irrespective of evidence is asking for a different
#: ranking, and should be given a flag, not a fudged weight.
_EVIDENCE_WEIGHT: Final[float] = 7.0

#: The recency ramp. Below the floor a paper scores 0, at or above the top it scores 1.
_RECENCY_FLOOR_YEAR: Final[int] = 1990
_RECENCY_TOP_YEAR: Final[int] = 2020

#: bm25 column weights: a hit in `name` (identifiers, gene and strain names, accessions, aliases)
#: is worth ten of a hit in `body` (titles, journals, GO labels, curator evidence prose). The
#: modality O.1 assigns to lexical search is "exact identifiers, gene names, strain names,
#: accessions" -- so an exact name match losing to a paper that mentions the word three times in
#: passing would be the wrong answer to the question this modality exists to serve.
_NAME_WEIGHT: Final[float] = 10.0
_BODY_WEIGHT: Final[float] = 1.0

#: How many bm25-ranked candidates are re-ranked before the limit is applied. Every re-ranking
#: scheme has this hole and most do not admit to it: a document that bm25 placed below the pool
#: cutoff cannot be lifted into view by its evidence level, however good that level is. The pool
#: is generous relative to a page, and `LexicalHits.pool_saturated` tells the caller when more
#: candidates existed than were re-ranked, which is the only honest way to report the hole.
_POOL_MULTIPLE: Final[int] = 10
_POOL_MINIMUM: Final[int] = 100

# ------------------------------------------------------------------------------- tokenizing

#: The query-side twin of FTS5's `unicode61` tokenizer: runs of letters and digits are tokens,
#: everything else separates. Kept deliberately simple *and* deliberately matched to the indexer,
#: because a query tokenizer that disagrees with the index tokenizer produces silent misses --
#: `CEN.PK113-7D` indexed as three tokens and queried as one matches nothing at all.
_TOKEN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> tuple[str, ...]:
    """`CEN.PK113-7D` -> `('cen', 'pk113', '7d')`. Lowercased, as unicode61 folds case."""
    return tuple(match.group(0).lower() for match in _TOKEN.finditer(text))


def _key(text: str) -> str:
    """A name reduced to its token sequence, which is how the synonym dictionary is keyed.

    Keying on tokens rather than on the raw string is what makes `CEN.PK113-7D`, `CEN.PK113 7D`
    and `cen-pk113-7d` one dictionary entry instead of three misses.
    """
    return " ".join(_tokens(text))


# ------------------------------------------------------------------------------- exceptions


class LexicalError(RuntimeError):
    """The lexical modality is not usable, for a reason the message names."""


class Fts5Unavailable(LexicalError):
    """This interpreter's sqlite3 was built without FTS5.

    Not hypothetical enough to skip: FTS5 is a compile-time option (`SQLITE_ENABLE_FTS5`), and a
    distribution that omits it produces a database that opens perfectly and cannot be indexed.
    """


class IndexNotBuilt(LexicalError):
    """The `lexical_*` tables are absent or empty. Derived artifacts do not build themselves."""


# ------------------------------------------------------------------------------- availability


def fts5_available(conn: sqlite3.Connection | None = None) -> bool:
    """Whether FTS5 can actually be used, established by using it.

    `PRAGMA compile_options` is the other way to ask and is the worse one: it reports how the
    library was configured, not whether a virtual table can be created right now, and it misses a
    build where FTS5 exists as a loadable extension. So this creates a throwaway table in `temp`
    and drops it. The cost is microseconds; the benefit is that a "yes" here cannot be wrong.
    """
    target = conn if conn is not None else sqlite3.connect(":memory:")
    try:
        target.execute("CREATE VIRTUAL TABLE temp.fermdb_fts5_probe USING fts5(probe)")
    except sqlite3.Error:
        return False
    else:
        target.execute("DROP TABLE temp.fermdb_fts5_probe")
        return True
    finally:
        if conn is None:
            target.close()


def require_fts5(conn: sqlite3.Connection) -> None:
    """Raise `Fts5Unavailable` unless this connection can create an FTS5 table."""
    if not fts5_available(conn):
        raise Fts5Unavailable(
            "this interpreter's sqlite3 was built without FTS5, so the lexical index cannot be "
            f"created (sqlite {sqlite3.sqlite_version}). The structured search "
            "(`fermdb.query.search`) still works and is unaffected; it is a substring scan, and "
            "nothing here will pretend otherwise by falling back to it silently."
        )


# ------------------------------------------------------------------------------- the schema

#: The index's own tables. No foreign keys into the core schema, on purpose: a derived artifact
#: that constrains its sources stops being droppable, and being droppable is the whole point.
_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS lexical_document (
        docid          INTEGER PRIMARY KEY,
        kind           TEXT NOT NULL,
        entity_id      TEXT NOT NULL,
        label          TEXT NOT NULL,
        -- The two indexed fields. `name` holds identifiers and every alias; `body` holds prose.
        name           TEXT NOT NULL,
        body           TEXT NOT NULL,
        year           INTEGER,
        -- NULL means ungraded, and `evidence_basis` is then the only thing that says whether
        -- that is "nothing known" or "direct evidence, in open conflict".
        evidence_level TEXT,
        evidence_basis TEXT NOT NULL,
        UNIQUE (kind, entity_id)
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS lexical_index USING fts5(
        name,
        body,
        content='lexical_document',
        content_rowid='docid',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lexical_synonym (
        term      TEXT NOT NULL,     -- normalized token sequence, e.g. 'ymr303c'
        expansion TEXT NOT NULL,     -- another name of the same entity, normalized the same way
        source    TEXT NOT NULL,     -- which table the equivalence came from
        kind      TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        PRIMARY KEY (term, expansion, kind, entity_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS lexical_synonym_by_term ON lexical_synonym(term)",
    """
    CREATE TABLE IF NOT EXISTS lexical_build (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

_DROP: Final[tuple[str, ...]] = (
    "DROP TABLE IF EXISTS lexical_index",
    "DROP TABLE IF EXISTS lexical_document",
    "DROP TABLE IF EXISTS lexical_synonym",
    "DROP TABLE IF EXISTS lexical_build",
)

_REPORT_KEY: Final[str] = "report"


# ------------------------------------------------------------------------------- documents


@dataclass(frozen=True)
class _Document:
    """One indexable thing, before its evidence level is attached."""

    kind: str
    entity_id: str
    label: str
    names: tuple[str, ...]
    body: tuple[str, ...]
    year: int | None = None

    @property
    def name_text(self) -> str:
        return " ".join(part for part in self.names if part)

    @property
    def body_text(self) -> str:
        return " ".join(part for part in self.body if part)


#: Every kind the lexical index covers, with the label the UI shows. This list is a superset of
#: `search._KINDS`: `tests/test_lexical.py` asserts that, so the faster modality can never quietly
#: cover *less* than the substring scan it is meant to supersede.
KIND_LABELS: Final[Mapping[str, str]] = {
    "publication": "Publications",
    "gene": "Genes",
    "gene_group": "Gene groups",
    "strain": "Strains",
    "product": "Products",
    "pathway": "Pathways",
    "metabolite": "Metabolites",
    "reaction": "Reactions",
}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns_of(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")'))


def _text(value: Any) -> str:
    """A column as indexable text. NULL becomes empty rather than the string 'None'."""
    return "" if value is None else str(value)


def _grouped(rows: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """`[(parent, text), ...]` -> `{parent: [text, ...]}`, preserving the query's order."""
    grouped: dict[str, list[str]] = {}
    for parent, text in rows:
        if text:
            grouped.setdefault(parent, []).append(text)
    return grouped


def _publication_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    """Title, journal, identifiers -- plus the quoted spans, which stand in for the abstracts.

    `publication.evidence` is deliberately **not** indexed, and it is the only curated `evidence`
    column that is skipped. On the live atlas every one of its 5,164 values is the same generated
    sentence, "NCBI E-utilities esummary, PMID <n>": it discriminates nothing, and the PMID it
    carries is already in the `name` field as a column. Indexing it would add 5,164 near-identical
    documents' worth of tokens to the corpus statistics for no recall at all, which is how a bm25
    score gets quietly worse.
    """
    quotes: dict[str, list[str]] = {}
    if _has_table(conn, "span"):
        quotes = _grouped(
            (str(row[0]), _text(row[1]))
            for row in conn.execute(
                "SELECT publication_id, quoted_text FROM span "
                "WHERE quoted_text IS NOT NULL ORDER BY publication_id, id"
            )
        )

    truncated = 0
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, doi, pmid, title, journal, year FROM publication ORDER BY id"
    ):
        entity_id = str(row[0])
        quoted = " ".join(quotes.get(entity_id, ()))
        if len(quoted) > SPAN_CHAR_CAP:
            quoted = quoted[:SPAN_CHAR_CAP]
            truncated += 1
        documents.append(
            _Document(
                kind="publication",
                entity_id=entity_id,
                label=_text(row[3]) or entity_id,
                names=(entity_id, _text(row[1]), _text(row[2])),
                body=(_text(row[3]), _text(row[4]), quoted),
                year=int(row[5]) if row[5] is not None else None,
            )
        )
    if truncated:
        notes.append(
            f"{truncated} publication(s) had their quoted spans cut at {SPAN_CHAR_CAP} characters; "
            "text past the cut is not searchable"
        )
    return documents


def _annotation_labels(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """GO/KEGG/Pfam term labels per gene group -- the closest thing the atlas has to a gene
    description, and the reason `gene` is findable by what it *does* and not only by its names."""
    if not _has_table(conn, "gene_annotation"):
        return {}
    seen: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT gene_group_id, term_label FROM gene_annotation "
        "WHERE term_label IS NOT NULL ORDER BY gene_group_id, term_id"
    ):
        labels = seen.setdefault(str(row[0]), [])
        label = _text(row[1])
        if label and label not in labels:
            labels.append(label)
    return seen


def _gene_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    labels = _annotation_labels(conn)
    available = _columns_of(conn, "gene")
    # `biotype` and `seqid` arrived in schema v17. Checked rather than assumed, for the reason
    # `search.py` checks: one optional column must not take the whole index build down.
    optional = tuple(column for column in ("biotype", "seqid") if column in available)
    columns = ("id", "systematic_name", "standard_name", "gene_group_id", "evidence", *optional)
    documents: list[_Document] = []
    for row in conn.execute(f"SELECT {', '.join(columns)} FROM gene ORDER BY id"):
        group_id = _text(row[3])
        documents.append(
            _Document(
                kind="gene",
                entity_id=str(row[0]),
                label=_text(row[2]) or _text(row[1]) or str(row[0]),
                names=(str(row[0]), _text(row[1]), _text(row[2])),
                body=(
                    *(_text(value) for value in row[4:]),
                    " ".join(labels.get(group_id, ())),
                ),
            )
        )
    return documents


def _gene_group_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    labels = _annotation_labels(conn)
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, anchor_id, standard_name, scope, membership_method, evidence "
        "FROM gene_group ORDER BY id"
    ):
        entity_id = str(row[0])
        documents.append(
            _Document(
                kind="gene_group",
                entity_id=entity_id,
                label=_text(row[2]) or _text(row[1]) or entity_id,
                names=(entity_id, _text(row[1]), _text(row[2])),
                body=(
                    _text(row[3]),
                    _text(row[4]),
                    _text(row[5]),
                    " ".join(labels.get(entity_id, ())),
                ),
            )
        )
    return documents


def _strain_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    """Canonical name, id, class, curator prose -- and every alias, written into `name`.

    This is half of O.1's "synonym dictionary built from the alias tables": a strain is findable
    by any name it has ever been called, without a query-time lookup. The other half, which
    reaches *other* documents that mention the alias, is `lexical_synonym`.
    """
    aliases: dict[str, list[str]] = {}
    if _has_table(conn, "strain_alias"):
        aliases = _grouped(
            (str(row[0]), _text(row[1]))
            for row in conn.execute(
                "SELECT strain_id, alias FROM strain_alias ORDER BY strain_id, alias"
            )
        )
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, canonical_name, class, organism_id, evidence FROM strain ORDER BY id"
    ):
        entity_id = str(row[0])
        documents.append(
            _Document(
                kind="strain",
                entity_id=entity_id,
                label=_text(row[1]) or entity_id,
                names=(entity_id, _text(row[1]), *aliases.get(entity_id, ())),
                body=(_text(row[2]), _text(row[3]), _text(row[4])),
            )
        )
    return documents


def _product_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, name, formula, inchikey, chebi_id, tier, canonical_unit, evidence "
        "FROM product ORDER BY id"
    ):
        documents.append(
            _Document(
                kind="product",
                entity_id=str(row[0]),
                label=_text(row[1]) or str(row[0]),
                names=(str(row[0]), _text(row[1]), _text(row[2]), _text(row[3]), _text(row[4])),
                body=(_text(row[5]), _text(row[6]), _text(row[7])),
            )
        )
    return documents


def _pathway_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    documents: list[_Document] = []
    for row in conn.execute("SELECT id, name, evidence FROM pathway ORDER BY id"):
        documents.append(
            _Document(
                kind="pathway",
                entity_id=str(row[0]),
                label=_text(row[1]) or str(row[0]),
                names=(str(row[0]), _text(row[1])),
                body=(_text(row[2]),),
            )
        )
    return documents


def _metabolite_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, name, formula, inchikey, chebi_id, carrier, evidence "
        "FROM metabolite ORDER BY id"
    ):
        documents.append(
            _Document(
                kind="metabolite",
                entity_id=str(row[0]),
                label=_text(row[1]) or str(row[0]),
                names=(str(row[0]), _text(row[1]), _text(row[2]), _text(row[3]), _text(row[4])),
                body=(_text(row[5]), _text(row[6])),
            )
        )
    return documents


def _reaction_documents(conn: sqlite3.Connection, notes: list[str]) -> list[_Document]:
    documents: list[_Document] = []
    for row in conn.execute(
        "SELECT id, name, ec_number, rhea_id, equation, compartment_id, evidence "
        "FROM reaction ORDER BY id"
    ):
        documents.append(
            _Document(
                kind="reaction",
                entity_id=str(row[0]),
                label=_text(row[1]) or str(row[0]),
                names=(str(row[0]), _text(row[1]), _text(row[2]), _text(row[3])),
                body=(_text(row[4]), _text(row[5]), _text(row[6])),
            )
        )
    return documents


#: One builder per kind, keyed the way `search._KINDS` is, so adding a kind is one entry here and
#: one entry in `KIND_LABELS` rather than an edit spread over the file. Each builder is handed the
#: shared `notes` list so that a truncation or a skipped column is reported by the build that
#: caused it rather than discovered later by whoever wonders why a search misses.
_DocumentBuilder = Callable[[sqlite3.Connection, list[str]], list[_Document]]

_BUILDERS: Final[Mapping[str, _DocumentBuilder]] = {
    "publication": _publication_documents,
    "gene": _gene_documents,
    "gene_group": _gene_group_documents,
    "strain": _strain_documents,
    "product": _product_documents,
    "pathway": _pathway_documents,
    "metabolite": _metabolite_documents,
    "reaction": _reaction_documents,
}


# ------------------------------------------------------------------------------- evidence


#: Best-first, so "the best level any active assertion gives this entity" is a `min` over ranks.
_LEVEL_RANK: Final[Mapping[str, int]] = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

#: Which ungraded basis wins when an entity has assertions but none of them grade. An open
#: direction conflict is a *stronger* statement than silence -- PLAN.md J.4 -- so it survives.
_UNGRADED_PRIORITY: Final[Mapping[str, int]] = {
    "direct_evidence_discordant": 0,
    "no_evidence": 1,
}


def _evidence_by_entity(conn: sqlite3.Connection) -> dict[tuple[str, str], EvidenceLevel]:
    """The best evidence level of any active assertion an entity appears in, either side of it.

    **Both positions, deliberately.** On the live atlas the 17 assertions have `gene_group`,
    `modification` and `part` as subjects and `product` and `strain` as objects -- so grading only
    by subject would leave every strain and every product ungraded, which is not what the atlas
    knows about them. "Evidence about this entity" does not care which side of the predicate it
    sits on.

    The level itself is never computed here. It comes from the `assertion_level` view, which is
    where `schema.sql` says it belongs: *"NOTE: there is deliberately no `level` column. A stored
    level silently becomes a lie the first time a new paper lands."* An index that derived its own
    level would be that stored lie with extra steps, which is why this is recomputed on every
    build and why the build is cheap enough to re-run whenever the evidence moves.

    What is *not* carried across: `is_overridden`. An override is a curator's judgement about one
    assertion, and this is a rollup over many, so "overridden" has no meaning at the entity level
    and is not claimed. The level the view produced -- override applied -- is what ranks.
    """
    if not (_has_table(conn, "assertion") and _has_table(conn, "assertion_level")):
        return {}

    best: dict[tuple[str, str], tuple[int, str, str | None]] = {}
    statement = """
        SELECT a.subject_type, a.subject_id, v.level, v.derived_reason
          FROM assertion a JOIN assertion_level v ON v.assertion_id = a.id
         WHERE a.status = 'active'
        UNION ALL
        SELECT a.object_type, a.object_id, v.level, v.derived_reason
          FROM assertion a JOIN assertion_level v ON v.assertion_id = a.id
         WHERE a.status = 'active' AND a.object_type <> 'literal' AND a.object_id IS NOT NULL
    """
    for row in conn.execute(statement):
        key = (str(row[0]), str(row[1]))
        level = None if row[2] is None else str(row[2])
        basis = str(row[3])
        # Graded beats ungraded; within graded, the lower level number wins; within ungraded, a
        # conflict beats silence. One sort key expresses all three.
        rank = _LEVEL_RANK.get(level or "", 100 + _UNGRADED_PRIORITY.get(basis, 9))
        current = best.get(key)
        if current is None or rank < current[0]:
            best[key] = (rank, basis, level)

    return {key: EvidenceLevel(level=level, basis=basis) for key, (_, basis, level) in best.items()}


# ------------------------------------------------------------------------------- synonyms


@dataclass(frozen=True)
class SynonymCoverage:
    """What one source contributed to the dictionary, including when that is nothing.

    `rows` and `groups` are reported separately from `pairs` because "the table is empty" and
    "the table is full of entities with exactly one name" are different facts with different
    fixes, and both render as an empty dictionary.
    """

    source: str
    rows: int
    groups: int
    pairs: int
    note: str

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "rows": self.rows,
            "groups_with_two_or_more_names": self.groups,
            "pairs": self.pairs,
            "note": self.note,
        }


def _synonym_groups(conn: sqlite3.Connection) -> tuple[list[tuple[str, str, tuple[str, ...]]], ...]:
    """Per source, the equivalence groups: every name that denotes one entity."""
    strains: list[tuple[str, str, tuple[str, ...]]] = []
    if _has_table(conn, "strain") and _has_table(conn, "strain_alias"):
        aliases = _grouped(
            (str(row[0]), _text(row[1]))
            for row in conn.execute(
                "SELECT strain_id, alias FROM strain_alias ORDER BY strain_id, alias"
            )
        )
        for row in conn.execute("SELECT id, canonical_name FROM strain ORDER BY id"):
            entity_id = str(row[0])
            names = (_text(row[1]), *aliases.get(entity_id, ()))
            strains.append(("strain", entity_id, names))

    genes: list[tuple[str, str, tuple[str, ...]]] = []
    if _has_table(conn, "gene"):
        for row in conn.execute("SELECT id, systematic_name, standard_name FROM gene ORDER BY id"):
            genes.append(("gene", str(row[0]), (_text(row[1]), _text(row[2]))))

    groups: list[tuple[str, str, tuple[str, ...]]] = []
    if _has_table(conn, "gene_group"):
        for row in conn.execute("SELECT id, anchor_id, standard_name FROM gene_group ORDER BY id"):
            groups.append(("gene_group", str(row[0]), (_text(row[1]), _text(row[2]))))

    return (strains, genes, groups)


def _build_synonyms(conn: sqlite3.Connection) -> tuple[int, tuple[SynonymCoverage, ...]]:
    """Write `lexical_synonym` and return what it actually covers.

    An equivalence group of n distinct names yields n*(n-1) ordered pairs: the dictionary is
    symmetric, because a reader who knows only the alias and a reader who knows only the canonical
    name have the same right to find the thing.
    """
    sources = (
        ("strain_alias", "strain alias -> canonical strain name"),
        ("gene", "systematic name <-> standard name"),
        ("gene_group", "anchor id <-> standard name"),
    )
    coverage: list[SynonymCoverage] = []
    written = 0

    for kind_rows, (source, description) in zip(_synonym_groups(conn), sources, strict=True):
        rows = (
            int(conn.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0])
            if _has_table(conn, source)
            else 0
        )
        groups = 0
        pairs = 0
        for kind, entity_id, names in kind_rows:
            keys = []
            for name in names:
                key = _key(name)
                if key and key not in keys:
                    keys.append(key)
            if len(keys) < 2:
                continue
            groups += 1
            for term in keys:
                for expansion in keys:
                    if term == expansion:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO lexical_synonym "
                        "(term, expansion, source, kind, entity_id) VALUES (?, ?, ?, ?, ?)",
                        (term, expansion, source, kind, entity_id),
                    )
                    pairs += 1
        written += pairs
        note = description
        if rows == 0:
            note = f"{description} -- source table is EMPTY, so this contributes nothing today"
        elif groups == 0:
            note = f"{description} -- no entity here carries two distinct names"
        coverage.append(SynonymCoverage(source, rows, groups, pairs, note))

    return written, tuple(coverage)


# ------------------------------------------------------------------------------- the build


@dataclass(frozen=True)
class IndexReport:
    """What one `index-build` produced, kept in the database so a reader can ask later.

    A search result's worth depends entirely on when the index was last built and on what it
    covers. Holding this beside the index -- rather than printing it once and losing it -- is what
    lets `index_status` answer "is this stale?" without a rebuild.
    """

    built_at: str
    builder_version: int
    documents: int
    by_kind: Mapping[str, int]
    skipped_kinds: Mapping[str, str]
    graded_documents: int
    synonym_pairs: int
    synonym_sources: tuple[SynonymCoverage, ...]
    notes: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "built_at": self.built_at,
            "builder_version": self.builder_version,
            "documents": self.documents,
            "by_kind": dict(self.by_kind),
            "skipped_kinds": dict(self.skipped_kinds),
            "graded_documents": self.graded_documents,
            "ungraded_documents": self.documents - self.graded_documents,
            "synonym_pairs": self.synonym_pairs,
            "synonym_sources": [source.as_json() for source in self.synonym_sources],
            "notes": list(self.notes),
            "fts5": {
                "tokenizer": "unicode61 remove_diacritics 2",
                "name_weight": _NAME_WEIGHT,
                "body_weight": _BODY_WEIGHT,
            },
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> IndexReport:
        return cls(
            built_at=str(payload["built_at"]),
            builder_version=int(payload["builder_version"]),
            documents=int(payload["documents"]),
            by_kind={str(k): int(v) for k, v in dict(payload["by_kind"]).items()},
            skipped_kinds={str(k): str(v) for k, v in dict(payload["skipped_kinds"]).items()},
            graded_documents=int(payload["graded_documents"]),
            synonym_pairs=int(payload["synonym_pairs"]),
            synonym_sources=tuple(
                SynonymCoverage(
                    source=str(item["source"]),
                    rows=int(item["rows"]),
                    groups=int(item["groups_with_two_or_more_names"]),
                    pairs=int(item["pairs"]),
                    note=str(item["note"]),
                )
                for item in payload["synonym_sources"]
            ),
            notes=tuple(str(note) for note in payload["notes"]),
        )


def _recorded_builder_version(conn: sqlite3.Connection) -> int | None:
    if not _has_table(conn, "lexical_build"):
        return None
    row = conn.execute("SELECT value FROM lexical_build WHERE key = ?", (_REPORT_KEY,)).fetchone()
    if row is None:
        return None
    try:
        return int(json.loads(str(row[0]))["builder_version"])
    except (ValueError, KeyError, TypeError):
        return None


def _ensure_tables(conn: sqlite3.Connection) -> None:
    require_fts5(conn)
    recorded = _recorded_builder_version(conn)
    if recorded is not None and recorded != BUILDER_VERSION:
        # A schema change to a *derived* artifact is a drop, never a migration. `migrations.py`
        # exists because the fact tables cannot be thrown away; these can, in a second.
        for statement in _DROP:
            conn.execute(statement)
    for statement in _DDL:
        conn.execute(statement)


def build_index(conn: sqlite3.Connection, *, commit: bool = True) -> IndexReport:
    """Build (or rebuild) the lexical index over `conn`, and report what it covers.

    Idempotent and rebuildable from scratch: the document and synonym tables are emptied, the FTS5
    index is told to `rebuild` from its content table, and a second run over an unchanged database
    produces byte-identical contents. Nothing in the core schema is read for anything but SELECT,
    and nothing in it is written.

    **The caller chooses the database.** This function takes a connection it was handed, exactly
    like every other reader in this package, so "build against a copy, not the shared atlas" is a
    decision made once at the CLI (`--db`, or `FERMDB_DB_FILE`) rather than a rule this module has
    to be trusted to remember.
    """
    _ensure_tables(conn)

    notes: list[str] = []
    documents: list[_Document] = []
    skipped: dict[str, str] = {}
    for kind, builder in _BUILDERS.items():
        if not _has_table(conn, kind):
            skipped[kind] = f"no `{kind}` table in this database"
            continue
        documents.extend(builder(conn, notes))

    evidence = _evidence_by_entity(conn)

    conn.execute("DELETE FROM lexical_document")
    conn.execute("DELETE FROM lexical_synonym")
    by_kind: dict[str, int] = {kind: 0 for kind in _BUILDERS if kind not in skipped}
    graded = 0
    for document in documents:
        level = evidence.get(
            (document.kind, document.entity_id), EvidenceLevel(level=None, basis="no_evidence")
        )
        if level.level is not None:
            graded += 1
        conn.execute(
            "INSERT INTO lexical_document "
            "(kind, entity_id, label, name, body, year, evidence_level, evidence_basis) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.kind,
                document.entity_id,
                document.label,
                document.name_text,
                document.body_text,
                document.year,
                level.level,
                level.basis,
            ),
        )
        by_kind[document.kind] = by_kind.get(document.kind, 0) + 1

    # External-content FTS5: the index is told to re-read its content table wholesale rather than
    # being kept in step by triggers. Triggers would put index maintenance on every write to the
    # core tables -- that is, a derived artifact reaching into the fact tables, which is the
    # coupling this design exists to avoid.
    conn.execute("INSERT INTO lexical_index(lexical_index) VALUES('rebuild')")

    synonym_pairs, coverage = _build_synonyms(conn)
    if synonym_pairs == 0:
        notes.append(
            "the synonym dictionary is EMPTY: no entity in this database carries two distinct "
            "names. O.1's dictionary is built and tested, and today it expands nothing"
        )
    if graded == 0 and documents:
        notes.append(
            "no document carries an evidence level, so the evidence term contributes 0 to every "
            "result and the ranking is text-only in practice"
        )

    report = IndexReport(
        built_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        builder_version=BUILDER_VERSION,
        documents=len(documents),
        by_kind=by_kind,
        skipped_kinds=skipped,
        graded_documents=graded,
        synonym_pairs=synonym_pairs,
        synonym_sources=coverage,
        notes=tuple(notes),
    )
    conn.execute(
        "INSERT OR REPLACE INTO lexical_build (key, value) VALUES (?, ?)",
        (_REPORT_KEY, json.dumps(report.as_json(), sort_keys=True)),
    )
    if commit:
        conn.commit()
    return report


def index_status(conn: sqlite3.Connection) -> IndexReport | None:
    """The last build's report, or None if this database has no lexical index."""
    if not _has_table(conn, "lexical_build"):
        return None
    row = conn.execute("SELECT value FROM lexical_build WHERE key = ?", (_REPORT_KEY,)).fetchone()
    if row is None:
        return None
    payload = json.loads(str(row[0]))
    if not isinstance(payload, dict):
        return None
    return IndexReport.from_json(payload)


def _require_index(conn: sqlite3.Connection) -> None:
    if not (_has_table(conn, "lexical_document") and _has_table(conn, "lexical_index")):
        raise IndexNotBuilt(
            f"this database has no lexical index; build one with `{BUILD_COMMAND}`. "
            "It is a derived artifact and is not created by opening the database, on purpose: "
            "an index that builds itself on first read makes a read command a writer."
        )


# ------------------------------------------------------------------------------- searching


@dataclass(frozen=True)
class Contribution:
    """One term of the score, with the number it came from and the number it added.

    The point of this type is that the score is never handed over as a single figure. A reader
    who cannot see that a result is first because of its evidence level, not its text match,
    cannot argue with the ranking -- and a ranking nobody can argue with is a ranking nobody
    should trust.
    """

    name: str
    raw: Any
    normalized: float
    weight: float
    note: str

    @property
    def contribution(self) -> float:
        return round(self.weight * self.normalized, 6)

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw": self.raw,
            "normalized": round(self.normalized, 6),
            "weight": self.weight,
            "contribution": self.contribution,
            "note": self.note,
        }


@dataclass(frozen=True)
class LexicalHit:
    """One ranked document, carrying its evidence level and its full score breakdown."""

    kind: str
    label: str
    entity_id: str
    year: int | None
    evidence: EvidenceLevel
    snippet: str
    components: tuple[Contribution, ...]

    @property
    def score(self) -> float:
        return round(sum(component.contribution for component in self.components), 6)

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "kind_label": KIND_LABELS.get(self.kind, self.kind),
            "id": self.entity_id,
            "label": self.label,
            "year": self.year,
            "evidence": self.evidence.as_json(),
            "snippet": self.snippet,
            "score": self.score,
            "ranking": [component.as_json() for component in self.components],
        }


@dataclass(frozen=True)
class LexicalHits:
    """A ranked list across kinds, with what the ranking did and what it could not see."""

    term: str
    words: tuple[str, ...]
    expansions: Mapping[str, tuple[str, ...]]
    hits: tuple[LexicalHit, ...]
    pool_size: int
    pool_saturated: bool
    kinds: tuple[str, ...]

    @property
    def total(self) -> int:
        return len(self.hits)

    def as_json(self) -> dict[str, Any]:
        caveats = [
            "scores are not comparable between queries: the text term is normalized over this "
            "query's candidate pool, so 4.1 here and 4.1 in another search mean nothing to "
            "each other",
            "matching is by token, not by substring: 'tolerant' does not match 'tolerance'. "
            "FTS5 does no stemming under this tokenizer, and a stemmer that folds gene names "
            "was not worth the identifiers it would break",
        ]
        if self.pool_saturated:
            caveats.append(
                f"more than {self.pool_size} documents matched, so only the {self.pool_size} "
                "best-matching by text were re-ranked; a high-evidence document that text ranked "
                "below that cutoff could not be lifted into view"
            )
        if not any(expansion for expansion in self.expansions.values()):
            caveats.append(
                "no query term had a synonym in the dictionary, so nothing here was expanded"
            )
        return {
            "term": self.term,
            "words": list(self.words),
            "synonyms_applied": {
                word: list(expansions) for word, expansions in self.expansions.items() if expansions
            },
            "kinds": list(self.kinds),
            "total": self.total,
            "hits": [hit.as_json() for hit in self.hits],
            "ranking": {
                "weights": {
                    "text": _TEXT_WEIGHT,
                    "evidence": _EVIDENCE_WEIGHT,
                    "recency": _RECENCY_WEIGHT,
                },
                "rule": (
                    "score = 1.0*text + 7.0*evidence + 0.25*recency, each term normalized to "
                    "0..1. One evidence level is 1.4 points and text+recency can swing at most "
                    "1.25, so an evidence-level difference is never overturned by a textual one "
                    "-- PLAN.md O.1's 'an L1 result should outrank a textually better-matching "
                    "L5 one', as a guarantee rather than a tendency"
                ),
                "technique": "SQLite FTS5 bm25 over name/body, re-ranked by evidence and recency",
            },
            "caveats": caveats,
        }


def _recency_score(year: int | None) -> tuple[float, str]:
    """A publication year as 0..1, and the note that goes with it.

    An undated document scores 0. That is a real bias and it is stated rather than smoothed:
    `publication` is the only table in the atlas that carries a year, so when text and evidence
    tie, a paper edges out a strain. The alternative -- giving undated rows a neutral date -- is
    inventing a fact to make a sort look fairer, which this project does not do anywhere else.
    """
    if year is None:
        return 0.0, "no year: nothing but `publication` carries one, so this term is 0 here"
    span = _RECENCY_TOP_YEAR - _RECENCY_FLOOR_YEAR
    scaled = (year - _RECENCY_FLOOR_YEAR) / span
    clamped = max(0.0, min(1.0, scaled))
    return clamped, f"{_RECENCY_FLOOR_YEAR} or earlier scores 0, {_RECENCY_TOP_YEAR} or later 1"


def _match_expression(
    conn: sqlite3.Connection, term: str
) -> tuple[str, tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Turn a user's box contents into an FTS5 MATCH expression, expanding known synonyms.

    Each whitespace-separated word becomes a *phrase* of its own tokens, so `CEN.PK113-7D` is
    searched as the three adjacent tokens it was indexed as rather than as three independent
    words that might occur anywhere. Words are ANDed (FTS5's own default); the synonyms of a word
    are ORed with it.

    Nothing the caller typed reaches the expression: only tokens matched by `_TOKEN`, which is
    `[A-Za-z0-9]+` and therefore cannot contain a quote, an operator or a column filter. That is
    the same rule `builder.py` enforces for SQL, applied to the other little language in play.
    """
    words = tuple(word for word in term.split() if _tokens(word))
    expansions: dict[str, tuple[str, ...]] = {}
    clauses: list[str] = []
    has_dictionary = _has_table(conn, "lexical_synonym")

    for word in words:
        key = _key(word)
        found: tuple[str, ...] = ()
        if has_dictionary:
            found = tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT expansion FROM lexical_synonym WHERE term = ? "
                    "ORDER BY expansion",
                    (key,),
                )
            )
        expansions[word] = found
        phrases = [f'"{key}"'] + [f'"{expansion}"' for expansion in found]
        clauses.append(f"({' OR '.join(phrases)})")

    return " AND ".join(clauses), words, expansions


def search_lexical(
    conn: sqlite3.Connection,
    term: str,
    *,
    kinds: Sequence[str] | None = None,
    limit: int = 10,
) -> LexicalHits:
    """Rank every indexed document against `term`, across kinds, with the score broken out.

    A blank term returns nothing rather than everything, for `search.py`'s reason: an empty box is
    not a request for the whole atlas.

    Raises:
        IndexNotBuilt: there is no lexical index in this database.
        LexicalError: `kinds` names something the index does not hold.
    """
    _require_index(conn)
    wanted = tuple(kinds) if kinds else tuple(KIND_LABELS)
    unknown = [kind for kind in wanted if kind not in KIND_LABELS]
    if unknown:
        raise LexicalError(
            f"unknown kind(s) {unknown}; the index holds {sorted(KIND_LABELS)}. "
            "Reported rather than silently dropped: a filter that quietly matches nothing looks "
            "exactly like a search with no results"
        )

    expression, words, expansions = _match_expression(conn, term)
    pool = max(_POOL_MINIMUM, limit * _POOL_MULTIPLE)

    def _empty() -> LexicalHits:
        return LexicalHits(
            term=term.strip(),
            words=words,
            expansions=expansions,
            hits=(),
            pool_size=pool,
            pool_saturated=False,
            kinds=wanted,
        )

    if not expression:
        return _empty()

    # Written out rather than built with `builder.Select`: that builder cannot express `MATCH`,
    # `bm25()` or `snippet()`, and widening its grammar to admit them would widen it for every
    # other caller too. Every value here is still a bound parameter, which is the rule that
    # actually matters.
    placeholders = ", ".join("?" for _ in wanted)
    statement = f"""
        SELECT d.kind, d.entity_id, d.label, d.year, d.evidence_level, d.evidence_basis,
               bm25(lexical_index, {_NAME_WEIGHT}, {_BODY_WEIGHT}) AS rank_bm25,
               snippet(lexical_index, 1, '', '', ' ... ', 14) AS body_snippet
          FROM lexical_index
          JOIN lexical_document d ON d.docid = lexical_index.rowid
         WHERE lexical_index MATCH ?
           AND d.kind IN ({placeholders})
         ORDER BY rank_bm25
         LIMIT ?
    """
    try:
        rows = conn.execute(statement, (expression, *wanted, pool + 1)).fetchall()
    except sqlite3.OperationalError as exc:  # pragma: no cover - defensive
        raise LexicalError(f"FTS5 rejected the query {expression!r}: {exc}") from exc

    saturated = len(rows) > pool
    rows = rows[:pool]
    if not rows:
        return _empty()

    # bm25 returns a negative number, better matches more negative. Negate first so that "higher
    # is better" holds for every term in the sum, then min-max over the pool so the text term has
    # a known range -- which is what makes the evidence guarantee above arithmetic rather than
    # hope. bm25 itself is unbounded, and no fixed weight can dominate an unbounded term.
    raw_scores = [-float(row[6]) for row in rows]
    lowest, highest = min(raw_scores), max(raw_scores)
    spread = highest - lowest

    hits: list[LexicalHit] = []
    for row, raw in zip(rows, raw_scores, strict=True):
        # Every candidate equally good is not "every candidate worst": a flat pool gets 1.0, so
        # the text term drops out of the ordering instead of silently zeroing every result.
        normalized = 1.0 if spread == 0 else (raw - lowest) / spread
        level = EvidenceLevel(level=None if row[4] is None else str(row[4]), basis=str(row[5]))
        evidence_score = _EVIDENCE_SCORES.get(level.level or "", 0.0)
        year = int(row[3]) if row[3] is not None else None
        recency, recency_note = _recency_score(year)
        hits.append(
            LexicalHit(
                kind=str(row[0]),
                label=str(row[2]),
                entity_id=str(row[1]),
                year=year,
                evidence=level,
                snippet=str(row[7]),
                components=(
                    Contribution(
                        name="text",
                        raw=round(raw, 6),
                        normalized=normalized,
                        weight=_TEXT_WEIGHT,
                        note=(
                            f"bm25 over name (weight {_NAME_WEIGHT}) and body "
                            f"(weight {_BODY_WEIGHT}), min-max scaled over this query's "
                            f"{len(rows)} candidates"
                        ),
                    ),
                    Contribution(
                        name="evidence",
                        raw=level.display,
                        normalized=evidence_score,
                        weight=_EVIDENCE_WEIGHT,
                        note=(
                            "best level of any active assertion this entity appears in, from the "
                            "`assertion_level` view; one level is worth more than the whole text "
                            "range, by design (PLAN.md O.1)"
                        ),
                    ),
                    Contribution(
                        name="recency",
                        raw=year,
                        normalized=recency,
                        weight=_RECENCY_WEIGHT,
                        note=recency_note,
                    ),
                ),
            )
        )

    # Deterministic beyond the score: two documents with identical scores must not swap places
    # between runs, or a paged UI loses and repeats rows for no reason a reader could explain.
    hits.sort(key=lambda hit: (-hit.score, hit.kind, hit.entity_id))
    return LexicalHits(
        term=term.strip(),
        words=words,
        expansions=expansions,
        hits=tuple(hits[:limit]),
        pool_size=pool,
        pool_saturated=saturated,
        kinds=wanted,
    )
