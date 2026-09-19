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

from ..config import Settings
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
class IngestReport:
    """Everything `ingest_directory` did or could not do, for the CLI (or a test) to report."""

    matched: tuple[IngestMatch, ...]
    already_provided: tuple[Path, ...]
    unmatched: tuple[Path, ...]


def ingest_directory(
    conn: sqlite3.Connection, directory: Path, *, settings: Settings
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
    )
