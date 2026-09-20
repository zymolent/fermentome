"""Tests for `fermdb.literature.acquire` and `fermdb.literature.manual_queue`.

Every OA/full-text source here is a fake `Transport` built from the JSON/XML fixtures in
`tests/fixtures/acquire/` -- these tests never touch the network (the harness's binding rule:
"tests MUST NOT hit the network").
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.literature import acquire, manual_queue
from fermdb.literature.acquire import FetchedContent, TransportError

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PATHS_YAML = REPO_ROOT / "env" / "paths.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquire"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@dataclass
class FakeTransport:
    """An offline `Transport`: responses (or errors) are matched by URL substring."""

    json_by_substring: dict[str, Any] = field(default_factory=dict)
    bytes_by_substring: dict[str, FetchedContent] = field(default_factory=dict)
    json_error_substrings: tuple[str, ...] = ()
    bytes_error_substrings: tuple[str, ...] = ()
    calls: list[str] = field(default_factory=list)

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        for key in self.json_error_substrings:
            if key in url:
                raise TransportError(f"fixture error for {key!r}")
        for key, payload in self.json_by_substring.items():
            if key in url:
                return payload
        raise TransportError(f"no fixture registered for {url}")

    def get_bytes(self, url: str) -> FetchedContent:
        self.calls.append(url)
        for key in self.bytes_error_substrings:
            if key in url:
                raise TransportError(f"fixture error for {key!r}")
        for key, content in self.bytes_by_substring.items():
            if key in url:
                return content
        raise TransportError(f"no fixture registered for {url}")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory atlas."""
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pinned entirely under `tmp_path`, never the developer's real `~/fermdb-data`."""
    return Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={
            "FERMDB_REPO_ROOT": str(tmp_path / "repo"),
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


# ---------------------------------------------------------------------------------------------
# classify_topic / compute_priority
# ---------------------------------------------------------------------------------------------


def test_classify_topic_examples() -> None:
    assert acquire.classify_topic("Isobutanol titer in an engineered strain") == "isobutanol"
    assert (
        acquire.classify_topic("Mitochondrial isobutanol pathway relocalization")
        == "isobutanol_mitochondria"
    )
    assert (
        acquire.classify_topic("mitoTALEN editing of the mitochondrial genome")
        == "mtdna_engineering"
    )
    assert acquire.classify_topic("Ethanol tolerance in industrial yeast") == "ethanol"
    assert acquire.classify_topic("An unrelated review of yeast metabolism") == "other"


def test_compute_priority_matches_the_stated_ranking() -> None:
    # isobutanol > isobutanol x mitochondria > mtDNA engineering > ethanol > other, and within a
    # tier, a paper reporting a titer/yield ranks before one that does not (lower = more urgent).
    ranking = [
        acquire.compute_priority("isobutanol", True),
        acquire.compute_priority("isobutanol", False),
        acquire.compute_priority("isobutanol_mitochondria", True),
        acquire.compute_priority("isobutanol_mitochondria", False),
        acquire.compute_priority("mtdna_engineering", True),
        acquire.compute_priority("mtdna_engineering", False),
        acquire.compute_priority("ethanol", True),
        acquire.compute_priority("ethanol", False),
        acquire.compute_priority("other", True),
        acquire.compute_priority("other", False),
    ]
    assert ranking == sorted(ranking)
    assert len(set(ranking)) == len(ranking)


# ---------------------------------------------------------------------------------------------
# _infer_text_mining_allowed
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("license_", "expected"),
    [
        (None, "unknown"),
        ("cc-by", "yes"),
        ("CC-BY-4.0", "yes"),
        ("cc0", "yes"),
        ("cc-by-nd", "no"),
        ("cc-by-nc", "unknown"),
        ("cc-by-nc-nd", "no"),
        ("all-rights-reserved", "unknown"),
    ],
)
def test_infer_text_mining_allowed(license_: str | None, expected: str) -> None:
    assert acquire._infer_text_mining_allowed(license_) == expected


# ---------------------------------------------------------------------------------------------
# resolve_oa_status
# ---------------------------------------------------------------------------------------------


def test_resolve_oa_status_requires_an_identifier() -> None:
    with pytest.raises(ValueError, match="doi or a pmid"):
        acquire.resolve_oa_status(doi=None, pmid=None, transport=FakeTransport())


def test_resolve_oa_status_prefers_europepmc_when_it_has_a_url() -> None:
    transport = FakeTransport(json_by_substring={"ebi.ac.uk": _load_json("europepmc_open.json")})

    resolution = acquire.resolve_oa_status(
        doi="10.9999/fixture-europepmc-open", pmid=None, transport=transport
    )

    assert resolution.resolved_via == "europepmc"
    assert resolution.oa_status == "gold"
    # Structured JATS outranks the PDF: it keeps section and paragraph boundaries, so the
    # character offsets span verification records stay stable. The PDF is not discarded, it is
    # the next candidate -- a landing page at the top must never cost us the copy underneath.
    assert resolution.best_oa_url == (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1000001/fullTextXML"
    )
    assert "https://europepmc.example.org/PMC1000001/fulltext.pdf" in resolution.candidate_urls
    assert resolution.text_mining_allowed == "yes"
    # Unpaywall is only consulted when Europe PMC did not already yield a URL.
    assert not any("unpaywall" in call for call in transport.calls)


def test_resolve_oa_status_falls_back_to_unpaywall_when_europepmc_is_closed() -> None:
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_closed.json"),
            "api.unpaywall.org": _load_json("unpaywall_gold.json"),
        }
    )

    resolution = acquire.resolve_oa_status(
        doi="10.9999/fixture-gold", pmid="10000002", transport=transport
    )

    assert resolution.resolved_via == "unpaywall"
    assert resolution.oa_status == "gold"
    assert resolution.best_oa_url == "https://fixture.example.org/gold/fulltext.pdf"


def test_resolve_oa_status_falls_back_to_pmc_oa_service() -> None:
    transport = FakeTransport(
        json_by_substring={"ebi.ac.uk": _load_json("europepmc_pmcid_only.json")},
        bytes_by_substring={
            "oa.fcgi": FetchedContent(
                data=_load_bytes("pmc_oa_found.xml"), content_type="application/xml", status=200
            )
        },
    )

    resolution = acquire.resolve_oa_status(doi=None, pmid="10000003", transport=transport)

    assert resolution.resolved_via == "pmc"
    # Europe PMC named a PMCID but listed no full-text URLs, so its derived fullTextXML endpoint
    # is the only thing it offered. That is not enough on its own -- if it 404s the paper has
    # nowhere else to go -- so PMC's OA service is still consulted and its locations appended.
    assert "ftp://fixture.example.org/PMC1000003.pdf" in resolution.candidate_urls
    assert resolution.best_oa_url == (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1000003/fullTextXML"
    )
    assert resolution.oa_status == "gold"
    assert resolution.pmid == "10000003"


def test_resolve_oa_status_falls_back_to_europepmc_when_pmc_oa_says_not_open() -> None:
    # Europe PMC named a PMCID but no direct URL, and the PMC OA web service itself then says
    # that id is not open access: resolve_oa_status must not crash or fabricate a URL, and falls
    # back to Europe PMC's own result rather than PMC's negative one.
    #
    # The two services disagree here, and that disagreement is not resolvable without trying:
    # Europe PMC flags the record open access, PMC OA says no. Europe PMC serves the fullTextXML
    # endpoint itself, so its own opinion governs it -- the URL is offered, and acquisition finds
    # out by fetching. What must not happen is a *fabricated* PMC location, and none is produced.
    transport = FakeTransport(
        json_by_substring={"ebi.ac.uk": _load_json("europepmc_pmcid_only.json")},
        bytes_by_substring={
            "oa.fcgi": FetchedContent(
                data=_load_bytes("pmc_oa_error.xml"), content_type="application/xml", status=200
            )
        },
    )

    resolution = acquire.resolve_oa_status(doi=None, pmid="10000003", transport=transport)

    assert resolution.resolved_via == "europepmc"
    assert resolution.oa_status == "green"
    assert resolution.candidate_urls == (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1000003/fullTextXML",
    )
    # Nothing from PMC's negative answer leaked into the result.
    assert not any("ftp://" in url for url in resolution.candidate_urls)


def test_resolve_oa_status_returns_unknown_when_every_source_is_unreachable() -> None:
    transport = FakeTransport(json_error_substrings=("ebi.ac.uk", "api.unpaywall.org"))

    resolution = acquire.resolve_oa_status(
        doi="10.9999/unreachable", pmid=None, transport=transport
    )

    assert resolution.oa_status == "unknown"
    assert resolution.best_oa_url is None
    assert resolution.resolved_via == "none"
    assert resolution.doi == "10.9999/unreachable"


# ---------------------------------------------------------------------------------------------
# acquire_fulltext
# ---------------------------------------------------------------------------------------------


def test_acquire_fulltext_requires_an_identifier(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    with pytest.raises(ValueError, match="doi or a pmid"):
        acquire.acquire_fulltext(
            doi=None, pmid=None, conn=conn, settings=settings, transport=FakeTransport()
        )


def test_acquire_fulltext_stores_gold_open_access(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    pdf_bytes = b"%PDF-1.4 fixture bytes for a gold OA isobutanol paper"
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_empty.json"),
            "api.unpaywall.org": _load_json("unpaywall_gold.json"),
        },
        bytes_by_substring={
            "fulltext.pdf": FetchedContent(
                data=pdf_bytes, content_type="application/pdf", status=200
            )
        },
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-gold",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=transport,
        title="A gold open-access isobutanol titer report",
        reports_titer_or_yield=True,
    )

    assert outcome.stored is True
    assert outcome.why_unavailable is None
    assert outcome.manual_queue_id is None

    row = conn.execute(
        "SELECT * FROM fulltext_asset WHERE id = ?", (outcome.fulltext_asset_id,)
    ).fetchone()
    assert row["storage_state"] == "stored_fulltext"
    assert row["oa_status"] == "gold"
    assert row["checksum_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()

    stored_path = settings.data_dir / row["content_path"]
    assert stored_path.read_bytes() == pdf_bytes

    queue_count = conn.execute("SELECT COUNT(*) FROM manual_download_queue").fetchone()[0]
    assert queue_count == 0


def test_acquire_fulltext_queues_a_paywalled_paper(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_closed.json"),
            "api.unpaywall.org": _load_json("unpaywall_closed.json"),
        }
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-closed",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=transport,
        title="A paywalled ethanol tolerance study",
        journal="Journal of Fermentation",
    )

    assert outcome.stored is False
    assert outcome.why_unavailable == "paywalled"

    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-closed",)
    ).fetchone()
    assert asset["storage_state"] == "not_found"

    queue_row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-closed",)
    ).fetchone()
    assert queue_row is not None
    assert queue_row["why_unavailable"] == "paywalled"
    assert queue_row["priority_topic"] == "ethanol"
    assert queue_row["status"] == "pending"


def test_acquire_fulltext_stores_bronze_as_a_pointer_only(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_empty.json"),
            "api.unpaywall.org": _load_json("unpaywall_bronze.json"),
        }
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-bronze",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=transport,
        title="mtDNA engineering with mitoTALEN in mitochondria",
    )

    assert outcome.why_unavailable == "licence_forbids"
    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-bronze",)
    ).fetchone()
    assert asset["storage_state"] == "pointer_only"
    assert asset["content_path"] is None
    assert asset["checksum_sha256"] is None
    assert asset["best_oa_url"] == "https://fixture.example.org/bronze/fulltext.pdf"

    queue_row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-bronze",)
    ).fetchone()
    assert queue_row["priority_topic"] == "mtdna_engineering"
    assert queue_row["why_unavailable"] == "licence_forbids"


def test_acquire_fulltext_records_a_failed_fetch_without_fabricating_one(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_empty.json"),
            "api.unpaywall.org": _load_json("unpaywall_gold.json"),
        },
        bytes_error_substrings=("fulltext.pdf",),
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-gold", pmid=None, conn=conn, settings=settings, transport=transport
    )

    assert outcome.why_unavailable == "fetch_failed"
    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-gold",)
    ).fetchone()
    assert asset["storage_state"] == "not_found"
    assert asset["fetch_error"]

    queue_row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-gold",)
    ).fetchone()
    assert queue_row["why_unavailable"] == "fetch_failed"


# ---------------------------------------------------------------------------------------------
# Payload validation.
#
# An HTTP 200 is not evidence that a paper came back. In the first real run over the corpus,
# three of four "stored" papers were HTML: a 2.7 kB <meta refresh> stub, a Nature consent page
# served from a URL ending .pdf, and a repository record page carrying only an abstract. All
# three looked acquired, so none reached the manual queue, and extraction would have run against
# them. Two papers answering with the *same* interstitial is what tripped the checksum index and
# exposed it -- the constraint was the only thing that noticed.
# ---------------------------------------------------------------------------------------------


def test_classify_payload_identifies_a_pdf_by_its_magic_bytes() -> None:
    check = acquire.classify_payload(b"%PDF-1.4 body", "application/pdf")
    assert check.usable is True
    assert check.kind == "pdf"


def test_classify_payload_trusts_bytes_over_a_mislabelled_content_type() -> None:
    # Servers mislabel in both directions; the bytes are evidence, the header is a claim.
    assert acquire.classify_payload(b"%PDF-1.4 body", "text/html").usable is True
    assert acquire.classify_payload(b"<!DOCTYPE html><html>", "application/pdf").usable is False


def test_classify_payload_rejects_a_redirect_stub() -> None:
    stub = b'<!DOCTYPE HTML><html><head><meta HTTP-EQUIV="REFRESH" content="0; url=...">'
    check = acquire.classify_payload(stub, "text/html;charset=UTF-8")
    assert check.usable is False
    assert check.kind == "html"
    assert check.reason and "landing page" in check.reason


def test_classify_payload_accepts_europe_pmc_jats() -> None:
    jats = b'<?xml version="1.0"?><article><front/><body><sec><p>Text.</p></sec></body></article>'
    check = acquire.classify_payload(jats, "application/xml")
    assert check.usable is True
    assert check.kind == "jats_xml"


def test_classify_payload_rejects_xml_that_is_not_an_article() -> None:
    # Europe PMC answers fullTextXML for a non-OA article with an error document, not a 404.
    check = acquire.classify_payload(b"<error>not open access</error>", "application/xml")
    assert check.usable is False
    assert check.reason and "not a JATS article" in check.reason


def test_classify_payload_rejects_an_empty_body() -> None:
    assert acquire.classify_payload(b"", "application/pdf").kind == "empty"


def test_acquire_fulltext_refuses_a_landing_page_and_queues_the_paper(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The regression this whole section exists for: HTML 200 must not count as full text."""
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_empty.json"),
            "api.unpaywall.org": _load_json("unpaywall_gold.json"),
        },
        bytes_by_substring={
            "fixture.example.org": FetchedContent(
                data=b"<!DOCTYPE html><html><body>Verifying you are human</body></html>",
                content_type="text/html; charset=utf-8",
                status=200,
            )
        },
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-gold", pmid=None, conn=conn, settings=settings, transport=transport
    )

    assert outcome.stored is False
    # Not 'fetch_failed': the network worked fine. Retrying returns the same page; a human is
    # the only way past it, which is exactly what the manual queue is for.
    assert outcome.why_unavailable == "no_pdf_found"

    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-gold",)
    ).fetchone()
    assert asset["storage_state"] == "not_found"
    assert asset["content_path"] is None
    assert "not a PDF" in asset["fetch_error"]

    queue_row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-gold",)
    ).fetchone()
    assert queue_row["why_unavailable"] == "no_pdf_found"
    # The owner downloads these by hand, so the link must survive the rejection.
    assert queue_row["best_known_link"]

    assert not list((settings.data_dir / "fulltext").rglob("*.html"))


def test_acquire_fulltext_falls_through_to_the_next_candidate(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """A consent wall on the publisher copy must not cost us the repository copy."""
    pdf_bytes = b"%PDF-1.4 the repository deposit"
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_empty.json"),
            "api.unpaywall.org": _load_json("unpaywall_gold_two_locations.json"),
        },
        bytes_by_substring={
            "consent-wall.pdf": FetchedContent(
                data=b"<!DOCTYPE html><html><body>Accept cookies</body></html>",
                content_type="text/html",
                status=200,
            ),
            "deposit.pdf": FetchedContent(
                data=pdf_bytes, content_type="application/pdf", status=200
            ),
        },
    )

    outcome = acquire.acquire_fulltext(
        doi="10.9999/fixture-two-locations",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=transport,
    )

    assert outcome.stored is True
    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-two-locations",)
    ).fetchone()
    assert asset["source_url"] == "https://repository.example.org/record/4242/deposit.pdf"
    assert asset["checksum_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    # The rejected location is still recorded -- a success that had to step over a failure says so.
    assert "consent-wall.pdf" in asset["fetch_error"]
    assert conn.execute("SELECT COUNT(*) FROM manual_download_queue").fetchone()[0] == 0


def test_acquire_fulltext_refuses_bytes_already_stored_for_another_paper(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Two papers cannot be the same document; the second must queue, not crash.

    Before this, the `fulltext_asset_checksum_uq` IntegrityError escaped `acquire_fulltext`
    after the bytes were already on disk, so the paper got neither an asset row nor a queue row
    -- invisible to both accounting paths, and retried into the same failure on every resume.
    """
    shared = b"%PDF-1.4 one document served for two different DOIs"
    served = {
        "fulltext.pdf": FetchedContent(data=shared, content_type="application/pdf", status=200)
    }
    first = acquire.acquire_fulltext(
        doi="10.9999/fixture-gold",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=FakeTransport(
            json_by_substring={
                "ebi.ac.uk": _load_json("europepmc_empty.json"),
                "api.unpaywall.org": _load_json("unpaywall_gold.json"),
            },
            bytes_by_substring=served,
        ),
    )
    assert first.stored is True

    # A genuinely different paper -- Unpaywall resolves it to its own DOI -- whose OA location
    # happens to answer with the very same file.
    second = acquire.acquire_fulltext(
        doi="10.9999/fixture-gold-twin",
        pmid=None,
        conn=conn,
        settings=settings,
        transport=FakeTransport(
            json_by_substring={
                "ebi.ac.uk": _load_json("europepmc_empty.json"),
                "api.unpaywall.org": _load_json("unpaywall_gold_twin.json"),
            },
            bytes_by_substring=served,
        ),
    )

    assert second.stored is False
    assert second.why_unavailable == "no_pdf_found"
    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-gold-twin",)
    ).fetchone()
    assert "byte-identical" in asset["fetch_error"]
    assert asset["checksum_sha256"] is None
    queue_row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-gold-twin",)
    ).fetchone()
    assert queue_row is not None


def test_repeat_failed_acquisition_updates_rather_than_duplicates(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    transport = FakeTransport(
        json_by_substring={
            "ebi.ac.uk": _load_json("europepmc_closed.json"),
            "api.unpaywall.org": _load_json("unpaywall_closed.json"),
        }
    )
    for _ in range(2):
        acquire.acquire_fulltext(
            doi="10.9999/fixture-closed",
            pmid=None,
            conn=conn,
            settings=settings,
            transport=transport,
        )

    asset_count = conn.execute(
        "SELECT COUNT(*) FROM fulltext_asset WHERE doi = ?", ("10.9999/fixture-closed",)
    ).fetchone()[0]
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM manual_download_queue WHERE doi = ?", ("10.9999/fixture-closed",)
    ).fetchone()[0]
    assert asset_count == 1
    assert queue_count == 1


# ---------------------------------------------------------------------------------------------
# enqueue_manual_download
# ---------------------------------------------------------------------------------------------


def test_enqueue_manual_download_requires_an_identifier(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="doi or a pmid"):
        acquire.enqueue_manual_download(conn, doi=None, pmid=None, why_unavailable="paywalled")


def test_enqueue_manual_download_rejects_an_unknown_reason(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="why_unavailable"):
        acquire.enqueue_manual_download(
            conn, doi="10.9999/x", pmid=None, why_unavailable="not_a_real_reason"
        )


def test_enqueue_manual_download_never_reopens_a_provided_row(conn: sqlite3.Connection) -> None:
    queue_id = acquire.enqueue_manual_download(
        conn,
        doi="10.9999/already-handled",
        pmid=None,
        why_unavailable="paywalled",
        title="An isobutanol titer paper",
        reports_titer_or_yield=True,
    )
    conn.execute("UPDATE manual_download_queue SET status = 'provided' WHERE id = ?", (queue_id,))
    conn.commit()

    same_id = acquire.enqueue_manual_download(
        conn, doi="10.9999/already-handled", pmid=None, why_unavailable="fetch_failed"
    )

    assert same_id == queue_id
    row = conn.execute("SELECT * FROM manual_download_queue WHERE id = ?", (queue_id,)).fetchone()
    assert row["status"] == "provided"
    assert row["why_unavailable"] == "paywalled"


# ---------------------------------------------------------------------------------------------
# schema-level guarantees ("never fabricate a retrieval")
# ---------------------------------------------------------------------------------------------


def test_schema_forbids_a_stored_asset_without_bytes(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO fulltext_asset (id, doi, oa_status, resolved_via, storage_state) "
            "VALUES ('x', '10.9999/x', 'gold', 'unpaywall', 'stored_fulltext')"
        )


# ---------------------------------------------------------------------------------------------
# manual_queue: export
# ---------------------------------------------------------------------------------------------


def test_export_queue_sorts_by_priority_and_skips_non_pending_rows(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    acquire.enqueue_manual_download(
        conn, doi="10.9999/eth", pmid=None, why_unavailable="paywalled", title="An ethanol study"
    )
    acquire.enqueue_manual_download(
        conn,
        doi="10.9999/iso",
        pmid=None,
        why_unavailable="paywalled",
        title="An isobutanol titer study",
        reports_titer_or_yield=True,
    )
    skipped_id = acquire.enqueue_manual_download(
        conn, doi="10.9999/skip", pmid=None, why_unavailable="no_pdf_found", title="Irrelevant"
    )
    conn.execute("UPDATE manual_download_queue SET status = 'skipped' WHERE id = ?", (skipped_id,))
    conn.commit()

    out_path = tmp_path / "queue.tsv"
    count = manual_queue.export_queue(conn, out_path)
    assert count == 2

    text = out_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].split("\t") == list(manual_queue._EXPORT_COLUMNS)
    assert "10.9999/iso" in lines[1]  # isobutanol + titer/yield is the single most urgent row
    assert "10.9999/skip" not in text


# ---------------------------------------------------------------------------------------------
# manual_queue: ingest
# ---------------------------------------------------------------------------------------------


def test_ingest_directory_matches_a_pmid_named_file(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    acquire.enqueue_manual_download(
        conn, doi=None, pmid="10000005", why_unavailable="paywalled", title="An isobutanol paper"
    )
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "10000005.pdf").write_bytes(b"%PDF-1.4 owner supplied copy")

    report = manual_queue.ingest_directory(conn, incoming, settings=settings)

    assert report.unmatched == ()
    assert report.already_provided == ()
    assert len(report.matched) == 1
    match = report.matched[0]
    assert match.pmid == "10000005"

    row = conn.execute(
        "SELECT * FROM manual_download_queue WHERE id = ?", (match.queue_id,)
    ).fetchone()
    assert row["status"] == "provided"
    assert row["fulltext_asset_id"] == match.fulltext_asset_id

    asset = conn.execute(
        "SELECT * FROM fulltext_asset WHERE id = ?", (match.fulltext_asset_id,)
    ).fetchone()
    assert asset["storage_state"] == "stored_fulltext"
    assert asset["oa_status"] == "closed"
    assert asset["resolved_via"] == "none"
    assert asset["source_url"] == "manual-upload:10000005.pdf"
    stored_bytes = (settings.data_dir / asset["content_path"]).read_bytes()
    assert stored_bytes == b"%PDF-1.4 owner supplied copy"


def test_ingest_directory_matches_a_doi_named_file_with_underscore_separator(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    acquire.enqueue_manual_download(
        conn,
        doi="10.1016/j.ymben.2020.01.001",
        pmid=None,
        why_unavailable="paywalled",
        title="An isobutanol paper",
    )
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "10.1016_j.ymben.2020.01.001.pdf").write_bytes(b"%PDF-1.4 owner supplied doi copy")

    report = manual_queue.ingest_directory(conn, incoming, settings=settings)

    assert len(report.matched) == 1
    assert report.matched[0].doi == "10.1016/j.ymben.2020.01.001"


def test_ingest_directory_reports_unmatched_and_already_provided_files(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    queue_id = acquire.enqueue_manual_download(
        conn,
        doi="10.1000/already-done",
        pmid=None,
        why_unavailable="paywalled",
        title="Already handled",
    )
    conn.execute("UPDATE manual_download_queue SET status = 'provided' WHERE id = ?", (queue_id,))
    conn.commit()

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "10.1000_already-done.pdf").write_bytes(b"a copy that arrived too late")
    (incoming / "unrelated_notes.txt").write_bytes(b"nothing recognizable in this filename")

    report = manual_queue.ingest_directory(conn, incoming, settings=settings)

    assert report.matched == ()
    assert len(report.already_provided) == 1
    assert report.already_provided[0].name == "10.1000_already-done.pdf"
    assert len(report.unmatched) == 1
    assert report.unmatched[0].name == "unrelated_notes.txt"


def test_ingest_directory_rejects_a_missing_directory(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        manual_queue.ingest_directory(conn, tmp_path / "does-not-exist", settings=settings)
