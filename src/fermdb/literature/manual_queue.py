"""The manual full-text download queue: export a worklist, ingest what comes back.

An explicit project-owner requirement (PLAN.md H.4): `acquire.py` never drops a paper it could
not get an open-access copy of, and never retries it forever either. Instead it writes a row into
`manual_download_queue` (schema.sql, "full text acquisition"), and this module is the two-way
bridge for a human to close that loop:

    export_queue     -- write the pending rows out as a TSV the owner can work through with their
                         own institutional access, most urgent first (`fermdb literature
                         manual-queue export --out queue.tsv`).
    ingest_directory  -- scan a folder of dropped-in files, match each one back to a queue row by
                         the PMID or DOI in its filename, store it exactly the way `acquire.py`
                         stores a network-fetched copy, and mark the row 'provided'
                         (`fermdb literature manual-queue ingest --dir <folder>`).

A file `ingest_directory` cannot confidently match is reported, never guessed at -- the same
"never fabricate a retrieval" discipline `acquire.py` follows for a network fetch.
"""

from __future__ import annotations

import csv
import mimetypes
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ..config import Settings
from ..extract.pdf import is_pdf, pdf_to_text
from . import acquire

__all__ = [
    "IngestMatch",
    "IngestReport",
    "export_queue",
    "ingest_directory",
]

#: Column order for the exported TSV. `best_known_link`/`publisher_url` are left as bare URLs,
#: which every common spreadsheet tool autolinks on open.
_EXPORT_COLUMNS: tuple[str, ...] = (
    "pmid",
    "doi",
    "title",
    "journal",
    "year",
    "publisher_url",
    "best_known_link",
    "why_unavailable",
    "priority",
    "priority_topic",
    "reports_titer_or_yield",
    "status",
    "added_at",
)

_PMID_STANDALONE_RE = re.compile(r"^\d{4,9}$")
_PMID_PREFIXED_RE = re.compile(r"pmid[_\-\s]?(\d{4,9})", re.IGNORECASE)
_DOI_WHOLE_RE = re.compile(r"^(10\.\d{4,9})[_/](.+)$")
_DOI_EMBEDDED_RE = re.compile(r"(10\.\d{4,9}/\S+)")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def export_queue(
    conn: sqlite3.Connection, out_path: Path, *, statuses: tuple[str, ...] = ("pending",)
) -> int:
    """Write the queue out as a TSV worklist, most urgent (lowest `priority`) first.

    Only rows whose `status` is in `statuses` are exported (default: just `'pending'` -- there is
    nothing left for the owner to act on in a row already `'provided'` or `'skipped'`). Returns
    the number of rows written.
    """
    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT {', '.join(_EXPORT_COLUMNS)} FROM manual_download_queue "  # noqa: S608
        f"WHERE status IN ({placeholders}) "
        "ORDER BY priority ASC, year ASC NULLS LAST, id ASC",
        statuses,
    ).fetchall()

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(_EXPORT_COLUMNS)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
    return len(rows)


def _extract_doi(stem: str) -> str | None:
    whole = _DOI_WHOLE_RE.match(stem)
    if whole:
        return f"{whole.group(1)}/{whole.group(2)}"
    embedded = _DOI_EMBEDDED_RE.search(stem)
    return embedded.group(1) if embedded else None


def _extract_pmid(stem: str) -> str | None:
    if _PMID_STANDALONE_RE.match(stem):
        return stem
    prefixed = _PMID_PREFIXED_RE.search(stem)
    return prefixed.group(1) if prefixed else None


def _extract_identifiers(stem: str) -> tuple[str | None, str | None]:
    """(doi, pmid) recognized in a dropped-in filename's stem.

    A DOI's own slash cannot survive most filesystems, so a filename that names the whole DOI is
    expected to spell it with the slash replaced by `_` (`10.1016_j.ymben.2020.01.001.pdf`); a
    literal slash embedded further into a longer name is also recognized. A bare run of digits, or
    one prefixed with `pmid`, is read as a PMID. The DOI takes precedence when both are present,
    being the more specific identifier.
    """
    return _extract_doi(stem), _extract_pmid(stem)


@dataclass(frozen=True)
class IngestMatch:
    """One dropped-in file successfully matched back to a queue row and stored."""

    path: Path
    queue_id: str
    fulltext_asset_id: str
    doi: str | None
    pmid: str | None


@dataclass(frozen=True)
class TitleMismatch:
    """A file whose own text does not look like the paper its filename claims it is."""

    path: Path
    doi: str | None
    pmid: str | None
    expected_title: str
    overlap: float


@dataclass(frozen=True)
class IngestReport:
    """Everything `ingest_directory` did or could not do, for the CLI (or a test) to report."""

    matched: tuple[IngestMatch, ...]
    already_provided: tuple[Path, ...]
    unmatched: tuple[Path, ...]
    title_mismatched: tuple[TitleMismatch, ...] = ()


#: Below this share of the expected title's distinctive words appearing in the document's opening
#: text, the file is refused rather than stored.
#:
#: Why it exists. A batch of 127 owner-supplied PDFs was triaged on 2026-09-21 and **three were a
#: different paper than the DOI in their filename**. The worst of them is a 1991 JBC paper on the
#: TIP1 cold-shock gene filed under a *Journal of Bioscience and Bioengineering* DOI -- it is a
#: yeast stress paper, so an extractor would have found entirely plausible content in it, every
#: span would have resolved, and the resulting rows would have carried a citation to a paper that
#: does not contain them. Nothing downstream could have caught that: `verify_span` proves a quote
#: is really in the stored document, not that the stored document is really the cited one.
#:
#: **Calibrated on that batch rather than chosen by taste**, which is the only reason to trust a
#: number like this. Scored against the 118 checkable correctly-filed PDFs and the two checkable
#: wrong-paper ones:
#:
#:     correctly filed (n=118)   min 71%   5th pct 88%   median 100%
#:     wrong paper      (n=2)    17%, 44%
#:
#: The classes do not overlap, so any threshold in (44%, 71%) separates them perfectly. 0.55 is
#: the midpoint: 11 points of margin above the worst true negative, 16 below the worst true
#: positive. Refusing a right paper costs a re-run with ``--no-title-check``; storing a wrong one
#: costs a citation to a paper that does not contain the rows, and nobody finds that later.
#:
#: **What this does NOT catch, stated so it is not mistaken for coverage.** The same batch held 4
#: preprint manuscripts filed under their published DOI; they score 100%, 100%, 88% and
#: unreadable, because a preprint *is* the same paper. That is a real provenance problem -- the
#: published title of one gained the word "Significantly" in review, and this atlas quotes
#: verbatim -- but it is a `version` field the schema does not have, not a threshold.
_TITLE_OVERLAP_MIN: Final[float] = 0.55

#: How much of the document's start to read. A cover sheet plus a title page is comfortably inside
#: this, and it keeps the check cheap enough to run on every file.
_TITLE_SCAN_CHARS: Final[int] = 4000

#: Words too common in this corpus to distinguish one paper from another. Kept as one string
#: because a 32-item set literal formats to 32 lines and reads as noise; `_TITLE_STOPWORDS` below
#: is the frozenset everything actually uses.
_TITLE_STOPWORD_TEXT: Final[str] = (
    "a an and as at by during for from in into is its of on or the to via with using "
    "effect effects role roles study studies analysis production yeast saccharomyces cerevisiae"
)
_TITLE_STOPWORDS: Final[frozenset[str]] = frozenset(_TITLE_STOPWORD_TEXT.split())


def _title_tokens(title: str) -> set[str]:
    """The distinctive words of a title, lowercased. Short and common words carry no signal."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", title.lower())
    return {w for w in words if w not in _TITLE_STOPWORDS}


def _title_overlap(expected_title: str, document_text: str) -> float | None:
    """Share of the expected title's distinctive words present in the document's opening text.

    ``None`` means the check could not be run at all -- no stored title, no extractable text, or a
    title with too few distinctive words to be evidence either way. An unrunnable check must not
    read as a failed one, so the caller stores the file in that case rather than refusing it.
    """
    wanted = _title_tokens(expected_title)
    if len(wanted) < 3:
        return None
    head = document_text[:_TITLE_SCAN_CHARS].lower()
    if not head.strip():
        return None
    found = sum(1 for token in wanted if token in head)
    return found / len(wanted)


def _publication_title(conn: sqlite3.Connection, publication_id: object) -> str:
    """The stored title for a publication row, or '' when there is none to compare against."""
    if not publication_id:
        return ""
    row = conn.execute("SELECT title FROM publication WHERE id = ?", (publication_id,)).fetchone()
    return str(row["title"]) if row is not None and row["title"] else ""


def _document_text(data: bytes, path: Path) -> str:
    """The file's own text, as far as it can be read. Never raises -- a check is not a gate."""
    try:
        if is_pdf(data):
            return pdf_to_text(data, source=path.name)
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def ingest_directory(
    conn: sqlite3.Connection,
    directory: Path,
    *,
    settings: Settings,
    check_titles: bool = True,
) -> IngestReport:
    """Match every file directly inside `directory` to a pending queue row and store it.

    For each file: recognize a PMID or DOI in its filename (`_extract_identifiers`), look up a
    `manual_download_queue` row for it, and if exactly one `'pending'` row matches, store the
    file's bytes the same content-addressed way `acquire.py` stores a network fetch and mark that
    row `'provided'`. A file that names no identifier, names one with no matching row, or matches
    a row that is not `'pending'`, is reported rather than guessed at.

    The stored `fulltext_asset` is recorded `oa_status='closed'` (and `resolved_via='none'`)
    unless a prior resolution already exists for the same DOI/PMID (a paper `acquire.py` found
    but could not store for a licence reason): a file the owner drops in came from their own
    access, not a confirmed open licence, and must never be treated as one just because a curator
    supplied it.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"not a directory: {directory}")

    matched: list[IngestMatch] = []
    already_provided: list[Path] = []
    unmatched: list[Path] = []
    title_mismatched: list[TitleMismatch] = []

    for path in sorted(candidate for candidate in directory.iterdir() if candidate.is_file()):
        doi, pmid = _extract_identifiers(path.stem)
        if doi is None and pmid is None:
            unmatched.append(path)
            continue

        row = acquire.find_manual_queue_row(conn, doi=doi, pmid=pmid)
        if row is None:
            unmatched.append(path)
            continue
        if row["status"] != "pending":
            already_provided.append(path)
            continue

        row_doi, row_pmid = row["doi"], row["pmid"]
        existing_asset = acquire.find_fulltext_asset(conn, doi=row_doi, pmid=row_pmid)
        if existing_asset is not None:
            oa_status = str(existing_asset["oa_status"])
            license_ = existing_asset["license"]
            text_mining_allowed = existing_asset["text_mining_allowed"]
        else:
            oa_status, license_, text_mining_allowed = "closed", None, "unknown"

        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0]

        # Is this file actually the paper its filename claims? `verify_span` can prove a quote is
        # really in the stored document; nothing downstream can prove the stored document is
        # really the cited one, so it is checked here or not at all.
        if check_titles:
            expected_title = _publication_title(conn, row["publication_id"])
            if expected_title:
                overlap = _title_overlap(expected_title, _document_text(data, path))
                if overlap is not None and overlap < _TITLE_OVERLAP_MIN:
                    title_mismatched.append(
                        TitleMismatch(
                            path=path,
                            doi=row["doi"],
                            pmid=row["pmid"],
                            expected_title=expected_title,
                            overlap=overlap,
                        )
                    )
                    continue
        content_path, checksum = acquire.store_bytes_content_addressed(
            settings, data, media_type=media_type
        )

        asset_id = acquire.write_fulltext_asset(
            conn,
            existing_id=str(existing_asset["id"]) if existing_asset is not None else None,
            doi=row_doi,
            pmid=row_pmid,
            publication_id=row["publication_id"],
            oa_status=oa_status,
            license_=license_,
            text_mining_allowed=text_mining_allowed,
            resolved_via="none",
            best_oa_url=None,
            storage_state="stored_fulltext",
            content_path=content_path,
            checksum_sha256=checksum,
            media_type=media_type,
            source_url=f"manual-upload:{path.name}",
            retrieved_at=_utc_now_iso(),
            fetch_error=None,
        )

        conn.execute(
            "UPDATE manual_download_queue SET status = 'provided', fulltext_asset_id = ?, "
            "updated_at = ? WHERE id = ?",
            (asset_id, _utc_now_iso(), row["id"]),
        )
        matched.append(
            IngestMatch(
                path=path,
                queue_id=str(row["id"]),
                fulltext_asset_id=asset_id,
                doi=row_doi,
                pmid=row_pmid,
            )
        )

    conn.commit()
    return IngestReport(
        matched=tuple(matched),
        already_provided=tuple(already_provided),
        unmatched=tuple(unmatched),
        title_mismatched=tuple(title_mismatched),
    )
