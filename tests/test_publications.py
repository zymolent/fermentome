"""Tests for `fermdb.query.publications`.

Two things this page can get wrong while looking right, and both are covered below.

The first is echoing the extraction's stored quote back as though it were the paper. It always
renders, it always looks like provenance, and it proves only that a model once emitted that
string. So the tests check what happens when the stored quote and the document *disagree*.

The second is counting. A finding count is the number a reader trusts without checking, and a
join on `record_path` alone -- which is unique only within an extraction -- multiplies it by the
number of times a paper has been extracted. That produced 111 findings for a paper with 37 on the
first real run, and nothing about the output looked wrong.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.query import publications as P

QUOTE = "the isobutanol titer reached 1.62 g/L at 24 h"
SOURCE = "Results. Cells grew to stationary phase. " + QUOTE + " Strain BSW191 was grown in YPD."
START = SOURCE.index(QUOTE)
END = START + len(QUOTE)


def _publication(conn: sqlite3.Connection, pid: str, **cols: object) -> None:
    conn.execute(
        "INSERT INTO publication (id, doi, title, year, journal, zone, evidence, confidence) "
        "VALUES (?,?,?,?,?,'R','test','high')",
        (
            pid,
            cols.get("doi"),
            cols.get("title"),
            cols.get("year"),
            cols.get("journal"),
        ),
    )


def _asset(conn: sqlite3.Connection, pid: str, state: str, path: str | None = None) -> None:
    conn.execute(
        "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
        "storage_state, content_path, checksum_sha256, source_url, media_type, retrieved_at, "
        "zone) VALUES (?,?,?,'gold','europepmc',?,?,?,?,'text/plain',?,'R')",
        (
            f"YAA:FTA:{pid}",
            pid,
            f"10.1/{pid}",
            state,
            path,
            "sha" if path else None,
            "https://example.org/x" if path else None,
            "2026-09-20T00:00:00Z" if path else None,
        ),
    )


def _extraction(conn: sqlite3.Connection, eid: str, pid: str, version: str) -> None:
    conn.execute(
        "INSERT INTO extraction (id, publication_id, extractor, extractor_version, model, "
        "prompt_version, input_hash, review_state, zone) "
        "VALUES (?,?,'test','1','test-model',?,?,'proposed','I')",
        (eid, pid, version, f"hash-{eid}"),
    )


def _record(
    conn: sqlite3.Connection,
    eid: str,
    pid: str,
    path: str,
    *,
    quote: str = QUOTE,
    start: int = START,
    end: int = END,
    status: str = "pending",
) -> None:
    resolved = status in {"accepted", "edited", "rejected"}
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, record_kind, "
        "payload, status, priority, attempt_count, proposal_hash, curator, curator_kind, "
        "resolved_at, resolution_reason, zone) VALUES (?,?,?,?,'measurements','{}',?,1,0,?,"
        "?,?,?,?,'I')",
        (
            f"YAA:CTASK:{eid}-{path}",
            eid,
            pid,
            path,
            status,
            f"ph-{eid}-{path}",
            "kangkon" if resolved else None,
            "human" if resolved else None,
            "2026-09-20T00:00:00Z" if resolved else None,
            "test" if resolved else None,
        ),
    )
    conn.execute(
        "INSERT INTO span (id, publication_id, extraction_id, section, char_start, char_end, "
        "quoted_text, record_path, zone) VALUES (?,?,?,'results',?,?,?,?,'I')",
        (f"YAA:SPAN:{eid}-{path}", pid, eid, start, end, quote, path),
    )


@pytest.fixture()
def atlas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FERMDB_DB_FILE", str(tmp_path / "data" / "fermdb.sqlite3"))
    settings = Settings.load()
    conn = open_db(settings.db_file)

    relative = Path("fulltext") / "aa" / "paper.txt"
    (settings.data_dir / relative).parent.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / relative).write_text(SOURCE, encoding="utf-8")

    _publication(conn, "YAA:PUB:held", title="A held paper", year=2019, journal="J Test")
    _asset(conn, "YAA:PUB:held", "stored_fulltext", relative.as_posix())
    _extraction(conn, "YAA:EXTR:one", "YAA:PUB:held", "v1")
    _record(conn, "YAA:EXTR:one", "YAA:PUB:held", "measurements[0]")

    _publication(conn, "YAA:PUB:pointer", title="Known but not held", year=2020)
    _asset(conn, "YAA:PUB:pointer", "pointer_only")

    _publication(conn, "YAA:PUB:missing", title="Looked for, not obtainable", year=2021)
    _asset(conn, "YAA:PUB:missing", "not_found")

    _publication(conn, "YAA:PUB:untouched", title="Never looked", year=2022)

    conn.commit()
    yield conn
    conn.close()


# --------------------------------------------------------------------- having the paper


def test_the_four_availability_states_are_distinct(atlas: sqlite3.Connection) -> None:
    """A boolean `has_fulltext` collapses "not looked" into "not obtainable"."""
    states = {
        pid: P.read_publication(atlas, pid).fulltext  # type: ignore[union-attr]
        for pid in ("YAA:PUB:held", "YAA:PUB:pointer", "YAA:PUB:missing", "YAA:PUB:untouched")
    }
    assert [s.state for s in states.values()] == [
        "stored_fulltext",
        "pointer_only",
        "not_found",
        "never_looked",
    ]
    assert len({s.display for s in states.values()}) == 4
    assert [s.is_readable for s in states.values()] == [True, False, False, False]


def test_a_stored_asset_whose_bytes_are_unreadable_is_not_reported_as_stored(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """Claiming to hold a paper that cannot be opened is worse than admitting it is missing."""
    (tmp_path / "data" / "fulltext" / "aa" / "paper.txt").unlink()
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    assert read.fulltext.state == "not_found"
    assert not read.fulltext.is_readable


def test_the_character_count_is_measured_not_claimed(atlas: sqlite3.Connection) -> None:
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    assert read.fulltext.characters.unwrap() == len(SOURCE)
    assert read.fulltext.characters.as_json()["zone"] == "H"  # derived, not reported


def test_corpus_shape_accounts_for_every_publication(atlas: sqlite3.Connection) -> None:
    shape = P.corpus_shape(atlas)
    assert shape["publications"] == 4
    assert shape["stored_fulltext"] == 1
    assert shape["pointer_only"] == 1
    assert shape["not_found"] == 1
    assert shape["never_looked"] == 1
    counted = sum(v for k, v in shape.items() if k != "publications")
    assert counted == shape["publications"], "a publication fell out of the accounting"


# --------------------------------------------------------------------- provenance


def test_the_quote_is_read_back_from_the_document(atlas: sqlite3.Connection) -> None:
    """P.2: click a value, see the sentence. The sentence, not the extraction's copy of it."""
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    finding = read.findings[0]
    assert finding.resolves
    assert finding.quote_in_source.unwrap() == QUOTE
    assert finding.quote_in_source.as_json()["zone"] == "R"
    # The extraction's own copy is Zone I and travels separately, so the two can be compared.
    assert finding.quote_as_recorded.as_json()["zone"] == "I"
    assert "stationary phase" in finding.before
    assert "YPD" in finding.after


def test_a_quote_that_disagrees_with_the_document_is_reported_unresolved(
    atlas: sqlite3.Connection,
) -> None:
    """The page's own integrity check, and the reason both quotes travel."""
    atlas.execute("UPDATE span SET quoted_text = 'a sentence the paper does not contain'")
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    assert not read.findings[0].resolves
    assert len(read.unresolved_findings) == 1
    assert read.as_json()["counts"]["unresolved_spans"] == 1


def test_a_pending_proposal_is_not_an_established_finding(atlas: sqlite3.Connection) -> None:
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    assert not read.findings[0].is_established

    atlas.execute(
        "UPDATE curation_task SET status='accepted', curator='k', curator_kind='human', "
        "resolved_at='2026-09-20T00:00:00Z', resolution_reason='ok'"
    )
    reread = P.read_publication(atlas, "YAA:PUB:held")
    assert reread is not None
    assert reread.findings[0].is_established
    assert reread.as_json()["counts"]["established"] == 1


def test_findings_are_not_multiplied_by_re_extraction(atlas: sqlite3.Connection) -> None:
    """The regression. `record_path` is unique within an extraction, not across them.

    Joining on it alone cross-joins every extraction of a paper against every other. On the first
    real run that turned 37 findings into 111, and the page looked entirely normal.
    """
    _extraction(atlas, "YAA:EXTR:two", "YAA:PUB:held", "v2")
    _record(atlas, "YAA:EXTR:two", "YAA:PUB:held", "measurements[0]")
    atlas.commit()

    spans = atlas.execute(
        "SELECT COUNT(*) FROM span WHERE publication_id = 'YAA:PUB:held'"
    ).fetchone()[0]
    read = P.read_publication(atlas, "YAA:PUB:held")
    assert read is not None
    assert spans == 2
    assert len(read.findings) == spans


def test_a_publication_with_no_stored_text_still_lists_its_findings(
    atlas: sqlite3.Connection,
) -> None:
    """The extraction's quotes are all that is left, and they must not pretend to be resolved."""
    _extraction(atlas, "YAA:EXTR:ptr", "YAA:PUB:pointer", "v1")
    _record(atlas, "YAA:EXTR:ptr", "YAA:PUB:pointer", "measurements[0]")
    atlas.commit()
    read = P.read_publication(atlas, "YAA:PUB:pointer")
    assert read is not None
    finding = read.findings[0]
    assert finding.quote_as_recorded.unwrap() == QUOTE
    assert finding.quote_in_source.is_known is False
    assert not finding.resolves
    assert finding.context == ""


def test_an_unknown_publication_is_none(atlas: sqlite3.Connection) -> None:
    assert P.read_publication(atlas, "YAA:PUB:nope") is None


# --------------------------------------------------------------------- search


def test_readable_only_is_the_facet_that_matters(atlas: sqlite3.Connection) -> None:
    """1,308 of 5,164 in the real corpus. Without this a count reads as "papers about X"
    when it means "papers whose title we know"."""
    assert len(P.search_publications(atlas)) == 4
    readable = P.search_publications(atlas, readable_only=True)
    assert [r["id"] for r in readable] == ["YAA:PUB:held"]


def test_search_reports_its_own_truncation(atlas: sqlite3.Connection) -> None:
    page = P.search_publications(atlas, limit=2)
    assert len(page) == 2
    assert page.truncated is True
    assert "page, not a total" in page.as_json()["note"]


def test_search_filters_compose(atlas: sqlite3.Connection) -> None:
    assert len(P.search_publications(atlas, year=2019)) == 1
    assert len(P.search_publications(atlas, query="Never")) == 1
    assert len(P.search_publications(atlas, year=2019, query="Never")) == 0
