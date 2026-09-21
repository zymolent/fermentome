"""Corpus discovery: run a query family end-to-end and write `screening_record` rows.

Pipeline per family (PLAN.md H.2, H.3, R.2):

    esearch (one term, or one per criterion-tagged sub-query)
      -> esummary (title/year/journal/DOI for every id)
      -> dedupe by DOI, else PMID, across every family this connection has ever seen
      -> triage, per the R.2 product-tier-aware default:
           isobutanol tier: include_unless_excluded -> 'included'
           ethanol tier:    exclude_unless_admitted  -> 'needs_full_text' + admitted_criterion if
                                                         the hit came from a criterion-tagged
                                                         sub-query (a *candidate* for that
                                                         criterion, not yet confirmed), else
                                                         'excluded' with a reason
      -> one screening_record per (publication, family), never silently dropped

    Actually confirming an ethanol candidate -- promoting 'needs_full_text' to 'included' once a
    curator (or a later classifier) has checked the full text against its candidate criterion -- is
    curation, not discovery, and is deliberately not implemented here; see the project owner's
    instruction that paper curation runs as a separate, parallel job.

Nothing here is an LLM call. The triage this module performs is a deterministic function of
`query_families.yaml` (repo-tier, Zone R) and this recorded code, so `screening_record.zone` is
'H' -- rebuildable by re-running discovery against the same family definitions, per
`docs/reference/CONVENTIONS.md`'s definition of Zone H. A future topical/relevance classifier
(PLAN.md H.3) that scores title+abstract is a different, model-driven step; it must write its own
Zone I table with `review_state='proposed'`, never overwrite `triage_state` here directly.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .eutils import EsearchResult, EutilsClient
from .queries import QueryFamily

_TITLE_STRIP_RE = re.compile(r"[^a-z0-9]+")
_YEAR_RE = re.compile(r"(\d{4})")

TriageState = str  # 'included' | 'needs_full_text' | 'excluded'


def _default_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_id() -> str:
    return uuid.uuid4().hex


def normalize_title(title: str | None) -> str | None:
    """Lowercase, strip punctuation, collapse whitespace. `None`/blank stays `None`.

    Used only as the last-resort dedupe key, for a hit with neither a DOI nor a PMID -- which does
    not happen for a PubMed hit today, but the schema and this function exist for the source that
    eventually does not supply one (per the task's "dedupe by DOI/PMID/normalised title").
    """
    if not title:
        return None
    collapsed = _TITLE_STRIP_RE.sub(" ", title.lower()).strip()
    return collapsed or None


def normalize_publication_id(publication_id: str) -> str:
    """Fold a publication id to the spelling `publication.id` is actually stored in.

    **The invariant, which was undocumented until this function existed:**

        publication.id == 'doi:' || lower(publication.doi)    -- for a DOI-keyed row
        publication.id == 'pmid:' || publication.pmid         -- for a PMID-keyed row

    Measured against the live atlas on 2026-09-22: `publication.id` is never uppercase (0 of
    5,164 rows), while 625 of the 4,864 DOI-keyed rows (12.9%) store a `doi` in the publisher's
    own casing -- `10.1128/AEM.00588-21` is a real one. So `id` and `doi` are deliberately *not*
    the same string, and a lookup that compares a caller's DOI against `id` with a bare `=` finds
    nothing for one DOI in eight.

    This is the one home of that fold. Minting goes through :func:`canonical_publication_id`,
    which calls this; reading goes through it directly, in
    :mod:`fermdb.extract.harness` (`load_source_text`, `find_publication`, `_publication_row`).
    One function rather than a `.lower()` at each call site, because a fold sprinkled across call
    sites is a fold the next call site forgets -- which is exactly how the read side came to be
    missing it while the write side had it.

    An id with neither scheme prefix (`YAA:PUB:...`, say) is returned stripped but otherwise
    untouched: nothing has been measured about its casing, so folding it would be a guess.
    """
    text = publication_id.strip()
    if text.lower().startswith("doi:"):
        # A DOI's prefix and suffix are both case-insensitive per the DOI handbook, and the atlas
        # resolves that by storing the whole id lowercased.
        return text.lower()
    if text.lower().startswith("pmid:"):
        # A PMID is digits, so only the scheme prefix can carry case; the number is left verbatim
        # rather than lowercased, so a malformed id stays visibly malformed in the error message.
        return "pmid:" + text[len("pmid:") :].strip()
    return text


def canonical_publication_id(*, doi: str | None, pmid: str | None) -> str | None:
    """DOI wins over PMID, matching `publication.id`'s own documented convention ('doi:...' or
    'pmid:...'). Returns None if neither is present.

    The casing fold lives in :func:`normalize_publication_id`, which this delegates to, so that
    minting and reading cannot drift apart.
    """
    if doi:
        return normalize_publication_id(f"doi:{doi}")
    if pmid:
        return normalize_publication_id(f"pmid:{pmid}")
    return None


def _parse_year(pubdate: str | None) -> int | None:
    if not pubdate:
        return None
    match = _YEAR_RE.match(pubdate.strip())
    return int(match.group(1)) if match else None


def _extract_doi(article_ids: Iterable[dict[str, Any]] | None) -> str | None:
    for entry in article_ids or ():
        if not isinstance(entry, dict):
            continue
        if entry.get("idtype") == "doi" and entry.get("value"):
            return str(entry["value"])
    return None


@dataclass(frozen=True)
class Hit:
    """One esummary document, reduced to what discovery needs."""

    pmid: str
    doi: str | None
    title: str | None
    year: int | None
    journal: str | None


@dataclass(frozen=True)
class SubQueryOutcome:
    criterion: str | None  # None for a family with a single plain `term`, else 'E1'..'E4'
    esearch: EsearchResult
    hits: tuple[Hit, ...]


@dataclass(frozen=True)
class FamilyRunResult:
    """The summary `fermdb literature discover` reports for one family."""

    run_id: str
    family: str
    started_at: str
    finished_at: str
    hit_count: int
    retrieved_count: int
    included: int
    needs_full_text: int
    excluded: int
    dry_run: bool


def _fetch_hits(client: EutilsClient, db: str, ids: list[str]) -> tuple[Hit, ...]:
    hits = []
    for doc in client.esummary(db=db, ids=ids):
        pmid = str(doc.get("uid") or "")
        if not pmid:
            continue
        hits.append(
            Hit(
                pmid=pmid,
                doi=_extract_doi(doc.get("articleids")),
                title=doc.get("title") or None,
                year=_parse_year(doc.get("pubdate")),
                journal=doc.get("fulljournalname") or doc.get("source") or None,
            )
        )
    return tuple(hits)


def _run_one_query(
    client: EutilsClient,
    *,
    db: str,
    term: str,
    criterion: str | None,
    max_records: int | None,
    dry_run: bool,
) -> SubQueryOutcome:
    esearch_result = client.esearch(db=db, term=term, retmax=min(max_records or 200, 200))
    if dry_run:
        return SubQueryOutcome(criterion=criterion, esearch=esearch_result, hits=())
    ids = client.esearch_all_ids(db=db, term=term, max_records=max_records)
    hits = _fetch_hits(client, db, ids)
    return SubQueryOutcome(criterion=criterion, esearch=esearch_result, hits=hits)


def _triage(
    family: QueryFamily, criterion: str | None
) -> tuple[TriageState, str | None, str | None]:
    """Apply the R.2 product-tier-aware default. Returns (state, exclusion_reason, candidate_for).

    Discovery alone never marks an ethanol hit 'included': "admitted" (R.2, B.3) means a curator
    (or a later, more capable classifier) has confirmed the paper actually satisfies one of the
    four criteria, which a keyword match cannot establish by itself. A hit from a criterion-tagged
    sub-query is therefore only a *candidate* for that criterion -- 'needs_full_text' -- and
    curation (run separately; see module docstring) is what can promote it to 'included'. An
    isobutanol hit, by contrast, genuinely is included by the stated default with nothing further
    to confirm, because no hits are excluded by anything this module implements yet.
    """
    if family.default_disposition == "include_unless_excluded":
        return "included", None, None
    if family.default_disposition == "exclude_unless_admitted":
        if criterion is not None:
            return "needs_full_text", None, criterion
        return (
            "excluded",
            (
                f"ethanol family '{family.name}' defaults to exclude-unless-admitted (PLAN.md "
                "R.2); this hit was retrieved by the family's plain term, not a criterion-tagged "
                "(E1-E4) sub-query, and has not been reviewed against the B.3 admission criteria"
            ),
            None,
        )
    # QueryFamily.__post_init__ already validates this; unreachable in practice.
    raise ValueError(  # pragma: no cover
        f"unknown default_disposition: {family.default_disposition!r}"
    )


def _upsert_publication(
    conn: sqlite3.Connection, hit: Hit, *, id_factory: Callable[[], str]
) -> str:
    pub_id = canonical_publication_id(doi=hit.doi, pmid=hit.pmid)
    if pub_id is None:
        # Should not happen for a genuine PubMed hit (a PMID is always present); an unresolvable
        # identifier is recorded as such rather than guessed at (CONVENTIONS.md "Identifiers").
        pub_id = f"UNRESOLVED:{id_factory()}"

    existing = conn.execute("SELECT doi, pmid FROM publication WHERE id = ?", (pub_id,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO publication "
            "(id, doi, pmid, title, year, journal, zone, evidence, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, 'R', ?, 'unverified')",
            (
                pub_id,
                hit.doi,
                hit.pmid,
                hit.title,
                hit.year,
                hit.journal,
                f"NCBI E-utilities esummary, PMID {hit.pmid}",
            ),
        )
        return pub_id

    # publication is Zone R (recorded exactly as the source stated it): fill in an identifier the
    # row did not have yet (a DOI turning up on a second, DOI-bearing family hit for the same
    # PMID), but never overwrite a value that is already there.
    updates: dict[str, str] = {}
    if hit.doi and not existing["doi"]:
        updates["doi"] = hit.doi
    if hit.pmid and not existing["pmid"]:
        updates["pmid"] = hit.pmid
    if updates:
        set_clause = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"UPDATE publication SET {set_clause} WHERE id = ?",  # noqa: S608 - column names are ours
            (*updates.values(), pub_id),
        )
    return pub_id


def _upsert_screening_record(
    conn: sqlite3.Connection,
    *,
    publication_id: str,
    family: QueryFamily,
    run_id: str,
    triage_state: TriageState,
    exclusion_reason: str | None,
    admitted_criterion: str | None,
    pmid: str,
    doi: str | None,
    title_normalized: str | None,
    id_factory: Callable[[], str],
    now: Callable[[], str],
) -> None:
    timestamp = now()
    existing = conn.execute(
        "SELECT id, review_state FROM screening_record WHERE publication_id = ? AND family = ?",
        (publication_id, family.name),
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO screening_record "
            "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
            "exclusion_reason, admitted_criterion, product_tier, default_disposition, pmid, doi, "
            "title_normalized, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id_factory(),
                publication_id,
                family.name,
                run_id,
                run_id,
                triage_state,
                exclusion_reason,
                admitted_criterion,
                family.product_tier,
                family.default_disposition,
                pmid,
                doi,
                title_normalized,
                timestamp,
                timestamp,
            ),
        )
        return

    if existing["review_state"] != "proposed":
        # A curator already accepted or rejected this screening decision. A re-run must still
        # record that the hit was seen again (last_seen_run_id), but it must never silently
        # overwrite a human judgement with a fresh automated one (CONVENTIONS.md: no exclusion, or
        # its reversal, is ever silent).
        conn.execute(
            "UPDATE screening_record SET last_seen_run_id = ?, updated_at = ? WHERE id = ?",
            (run_id, timestamp, existing["id"]),
        )
        return

    conn.execute(
        "UPDATE screening_record SET last_seen_run_id = ?, triage_state = ?, "
        "exclusion_reason = ?, admitted_criterion = ?, updated_at = ? WHERE id = ?",
        (run_id, triage_state, exclusion_reason, admitted_criterion, timestamp, existing["id"]),
    )


def run_family(
    conn: sqlite3.Connection,
    client: EutilsClient,
    family: QueryFamily,
    *,
    query_families_version: int,
    max_records: int | None = None,
    dry_run: bool = False,
    id_factory: Callable[[], str] = _default_id,
    now: Callable[[], str] = _default_now,
) -> FamilyRunResult:
    """Run one query family: esearch (+ any criterion sub-queries), esummary, dedupe, triage.

    `dry_run=True` still calls esearch (so the reported hit_count can be compared against
    `expected_count`) but never calls esummary and never writes to `conn` -- it is the mode
    `fermdb literature discover --dry-run` uses to check for corpus drift without ingesting
    anything or touching the database.

    All network access goes through `client.transport`; this function never imports `urllib`, so
    a test's fake transport is the only thing standing between it and the real network.
    """
    started_at = now()
    run_id = id_factory()

    if family.sub_queries:
        outcomes = [
            _run_one_query(
                client,
                db=family.db,
                term=sub.term,
                criterion=sub.criterion,
                max_records=max_records,
                dry_run=dry_run,
            )
            for sub in family.sub_queries
        ]
        term_recorded = " | ".join(f"{sub.criterion}: {sub.term}" for sub in family.sub_queries)
    else:
        assert family.term is not None  # guaranteed by QueryFamily.__post_init__
        outcomes = [
            _run_one_query(
                client,
                db=family.db,
                term=family.term,
                criterion=None,
                max_records=max_records,
                dry_run=dry_run,
            )
        ]
        term_recorded = family.term

    finished_at = now()
    # esearch counts across sub-queries are not deduplicated against each other (that only happens
    # once esummary/DOI data is in hand), so this is "total hits seen", not "total distinct papers".
    hit_count = sum(outcome.esearch.count for outcome in outcomes)
    retrieved_count = sum(len(outcome.hits) for outcome in outcomes)

    counts = {"included": 0, "needs_full_text": 0, "excluded": 0}

    if not dry_run:
        conn.execute(
            "INSERT INTO search_run "
            "(id, family, db, term, started_at, finished_at, hit_count, retrieved_count, "
            "query_families_version, dry_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                run_id,
                family.name,
                family.db,
                term_recorded,
                started_at,
                finished_at,
                hit_count,
                retrieved_count,
                query_families_version,
            ),
        )

        seen_in_this_run: set[str] = set()
        for outcome in outcomes:
            for hit in outcome.hits:
                triage_state, exclusion_reason, admitted_criterion = _triage(
                    family, outcome.criterion
                )
                publication_id = _upsert_publication(conn, hit, id_factory=id_factory)
                # A publication matched by more than one sub-query of the SAME family (e.g. both
                # an E1 and an E4 term) keeps only its first, most-specific triage for this family
                # rather than being counted twice.
                if publication_id in seen_in_this_run:
                    continue
                seen_in_this_run.add(publication_id)
                _upsert_screening_record(
                    conn,
                    publication_id=publication_id,
                    family=family,
                    run_id=run_id,
                    triage_state=triage_state,
                    exclusion_reason=exclusion_reason,
                    admitted_criterion=admitted_criterion,
                    pmid=hit.pmid,
                    doi=hit.doi,
                    title_normalized=normalize_title(hit.title),
                    id_factory=id_factory,
                    now=now,
                )
                counts[triage_state] += 1
        conn.commit()

    return FamilyRunResult(
        run_id=run_id,
        family=family.name,
        started_at=started_at,
        finished_at=finished_at,
        hit_count=hit_count,
        retrieved_count=retrieved_count,
        included=counts["included"],
        needs_full_text=counts["needs_full_text"],
        excluded=counts["excluded"],
        dry_run=dry_run,
    )
