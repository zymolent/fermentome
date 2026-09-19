"""Tests for `fermdb.literature`: the E-utilities client, the query-family definition, and the
discovery/triage pipeline that writes `search_run` / `screening_record` rows.

No test here reaches the network. `EutilsClient.transport` is always a `FakeTransport` built from
the recorded fixtures in `tests/fixtures/eutils/` (or, for parsing/error-path tests, from bytes
built inline); the CLI tests monkeypatch `fermdb.cli._literature_client` for the same reason.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fermdb import cli
from fermdb.db import IN_MEMORY, open_db
from fermdb.literature.discovery import canonical_publication_id, normalize_title, run_family
from fermdb.literature.eutils import EutilsClient, EutilsError
from fermdb.literature.queries import (
    QueryFamilies,
    QueryFamiliesError,
    QueryFamily,
    SubQuery,
    excluded_records,
    family_status,
    load_query_families,
    needs_full_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "eutils"
REAL_QUERY_FAMILIES_YAML = REPO_ROOT / "data" / "literature" / "query_families.yaml"


def _fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# A fake transport, built entirely from recorded (synthetic) fixtures
# ---------------------------------------------------------------------------------------------


@dataclass
class FakeTransport:
    """Maps a substring of the request URL to a queue of canned responses.

    Keying on just the endpoint name ('esearch.fcgi' / 'esummary.fcgi' / 'efetch.fcgi') is enough
    for every test below: no single test issues two differently-shaped calls to the same endpoint
    that need to be told apart by anything finer than call order, and a list under one key is
    consumed in order (the last entry repeats if a key is called more times than it has entries).
    """

    responses: dict[str, list[bytes]]
    fail_first_n: int = 0
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._index: dict[str, int] = {}
        self._remaining_failures = self.fail_first_n

    def get(self, url: str, *, timeout: float) -> bytes:
        self.calls.append(url)
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise OSError(f"FakeTransport: simulated transient failure for {url}")
        for key, sequence in self.responses.items():
            if key in url:
                index = self._index.get(key, 0)
                self._index[key] = index + 1
                return sequence[min(index, len(sequence) - 1)]
        raise AssertionError(f"FakeTransport: no fixture registered for URL: {url}")


@dataclass
class FakeClock:
    """A controllable monotonic clock: `sleep` advances `now` instead of blocking."""

    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# =================================================================================================
# eutils.py
# =================================================================================================


def test_esearch_parses_count_ids_and_translation() -> None:
    transport = FakeTransport({"esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")]})
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    result = client.esearch(db="pubmed", term="isobutanol[tiab] AND mitochondri*[tiab]")
    assert result.count == 3
    assert result.ids == ("20981231", "20981232", "20981233")
    assert result.query_translation == "isobutanol[tiab] AND mitochondri*[tiab]"


def test_esearch_all_ids_pages_through_every_result() -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [
                _fixture("esearch_paged_page1.json"),
                _fixture("esearch_paged_page2.json"),
                _fixture("esearch_paged_page3.json"),
            ]
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    ids = client.esearch_all_ids(db="pubmed", term="yeast[tiab] AND mtDNA[tiab]", page_size=2)
    assert ids == ["40000001", "40000002", "40000003", "40000004", "40000005"]
    assert len([c for c in transport.calls if "esearch.fcgi" in c]) == 3


def test_esearch_all_ids_stops_at_max_records() -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [
                _fixture("esearch_paged_page1.json"),
                _fixture("esearch_paged_page2.json"),
                _fixture("esearch_paged_page3.json"),
            ]
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    ids = client.esearch_all_ids(
        db="pubmed", term="yeast[tiab] AND mtDNA[tiab]", page_size=2, max_records=3
    )
    assert ids == ["40000001", "40000002", "40000003"]
    # Stops after the 2nd page (4 ids in hand >= 3 requested); never fetches page 3.
    assert len([c for c in transport.calls if "esearch.fcgi" in c]) == 2


def test_esummary_returns_one_dict_per_uid_in_server_order() -> None:
    transport = FakeTransport(
        {"esummary.fcgi": [_fixture("esummary_isobutanol_mitochondria.json")]}
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    docs = client.esummary(db="pubmed", ids=["20981231", "20981232", "20981233"])
    assert [d["uid"] for d in docs] == ["20981231", "20981232", "20981233"]
    assert docs[0]["articleids"][1] == {
        "idtype": "doi",
        "idtypen": 3,
        "value": "10.1000/example.nbt2013",
    }


def test_esummary_with_no_ids_never_touches_the_transport() -> None:
    transport = FakeTransport({})
    client = EutilsClient(transport=transport)
    assert client.esummary(db="pubmed", ids=[]) == []
    assert transport.calls == []


def test_efetch_with_no_ids_never_touches_the_transport() -> None:
    transport = FakeTransport({})
    client = EutilsClient(transport=transport)
    assert client.efetch(db="pubmed", ids=[]) == b""
    assert transport.calls == []


def test_efetch_returns_the_raw_payload_unparsed() -> None:
    transport = FakeTransport({"efetch.fcgi": [b"<PubmedArticleSet>...</PubmedArticleSet>"]})
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    raw = client.efetch(db="pubmed", ids=["1"], rettype="abstract", retmode="xml")
    assert raw == b"<PubmedArticleSet>...</PubmedArticleSet>"


def test_esearch_raises_eutils_error_on_invalid_json() -> None:
    transport = FakeTransport({"esearch.fcgi": [b"not json at all"]})
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    with pytest.raises(EutilsError):
        client.esearch(db="pubmed", term="x")


def test_esearch_raises_eutils_error_when_esearchresult_is_missing() -> None:
    transport = FakeTransport({"esearch.fcgi": [b'{"unexpected": true}']})
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    with pytest.raises(EutilsError):
        client.esearch(db="pubmed", term="x")


def test_transient_transport_failures_are_retried_then_succeed() -> None:
    transport = FakeTransport(
        {"esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")]},
        fail_first_n=2,
    )
    clock = FakeClock()
    client = EutilsClient(
        transport=transport, max_retries=5, sleep=clock.sleep, monotonic=clock.monotonic
    )
    result = client.esearch(db="pubmed", term="x")
    assert result.count == 3
    # 2 failures + 1 success = 3 attempts.
    assert len(transport.calls) == 3
    # Backoff actually happened between the failures (in addition to any rate-limit sleeps).
    assert len(clock.sleeps) >= 2


def test_retries_are_exhausted_and_raise_eutils_error() -> None:
    transport = FakeTransport({"esearch.fcgi": []}, fail_first_n=999)
    clock = FakeClock()
    client = EutilsClient(
        transport=transport, max_retries=3, sleep=clock.sleep, monotonic=clock.monotonic
    )
    with pytest.raises(EutilsError):
        client.esearch(db="pubmed", term="x")
    assert len(transport.calls) == 3


def test_rate_limit_without_api_key_is_three_per_second() -> None:
    transport = FakeTransport({"esearch.fcgi": [_fixture("esearch_ethanol_plain.json")] * 2})
    clock = FakeClock()
    client = EutilsClient(transport=transport, sleep=clock.sleep, monotonic=clock.monotonic)
    assert client.rate_limit_per_second == 3.0
    client.esearch(db="pubmed", term="x")
    assert clock.sleeps == []  # the very first call never throttles
    client.esearch(db="pubmed", term="x")
    assert clock.sleeps == [pytest.approx(1.0 / 3.0)]


def test_rate_limit_with_api_key_is_ten_per_second() -> None:
    transport = FakeTransport({"esearch.fcgi": [_fixture("esearch_ethanol_plain.json")] * 2})
    clock = FakeClock()
    client = EutilsClient(
        transport=transport, api_key="secret", sleep=clock.sleep, monotonic=clock.monotonic
    )
    assert client.rate_limit_per_second == 10.0
    client.esearch(db="pubmed", term="x")
    client.esearch(db="pubmed", term="x")
    assert clock.sleeps == [pytest.approx(0.1)]


def test_from_env_reads_ncbi_credentials_and_none_when_absent() -> None:
    client = EutilsClient.from_env(env={})
    assert client.api_key is None
    assert client.email is None
    assert client.rate_limit_per_second == 3.0

    client = EutilsClient.from_env(
        env={"FERMDB_NCBI_API_KEY": "abc123", "FERMDB_NCBI_EMAIL": "curator@example.org"}
    )
    assert client.api_key == "abc123"
    assert client.email == "curator@example.org"
    assert client.rate_limit_per_second == 10.0


# =================================================================================================
# queries.py -- parsing and validation of query_families.yaml
# =================================================================================================


def test_the_real_shipped_query_families_file_loads_and_matches_the_recorded_measurements() -> None:
    """Ties this test directly to the harness-supplied 2026-09-19/20 measurements.

    If a family's `expected_count` ever drifts from what the project owner actually measured, this
    test is what catches an accidental edit -- it is not exercising discovery.py at all.
    """
    families = load_query_families(REAL_QUERY_FAMILIES_YAML)
    assert families.version == 1

    # Re-baselined 2026-09-20 against the SHIPPED query strings, run live. The previous values
    # were measured with different, hand-written queries, so comparing a live count against them
    # could never converge -- the baseline and the query under test were not the same thing, which
    # made drift detection meaningless. These are now the counts the shipped terms actually
    # return, so `fermdb literature status` compares like with like.
    #
    # The one that mattered: mtdna_engineering_yeast returned 93 against a 823 baseline, an 89%
    # recall loss on a corpus the owner explicitly asked to cover, caused by a [tiab] restriction
    # plus a three-way AND. The term was widened and now returns 912.
    expected = {
        "isobutanol_all": 1309,
        "isobutanol_production": 649,
        "isobutanol_yeast": 257,
        "isobutanol_mitochondria": 29,
        "mtdna_engineering_yeast": 912,
        "mtdna_methods_yeast": 1298,
        "ethanol_mitochondria_yeast": 504,
        "ethanol_scerevisiae_prod_ferm_tol": 1586,
    }
    assert {f.name: f.expected_count for f in families.families} == expected

    # Guards against the failure this file just had: a bounded-edit bug silently dropped three
    # families and the count assertion above would still have passed on the survivors.
    assert len(families.families) == 8

    # The three required mtDNA scopes (harness "comments (1)") are each covered by >= 1 family.
    assert len(families.by_mtdna_scope("engineering_general")) >= 1
    assert len(families.by_mtdna_scope("isobutanol_x_mtdna")) >= 1
    assert len(families.by_mtdna_scope("ethanol_x_mtdna")) >= 1

    # Product-tier-aware defaults (R.2): isobutanol is include-unless-excluded, ethanol is
    # exclude-unless-admitted, with no exceptions in either direction.
    for f in families.families:
        if f.product_tier == "isobutanol":
            assert f.default_disposition == "include_unless_excluded"
        else:
            assert f.product_tier == "ethanol"
            assert f.default_disposition == "exclude_unless_admitted"

    # The ethanol capped layer runs its admission sub-queries and nothing else. E5
    # (mitochondrial redox shuttle) was added from docs/design/DUET_TARGET.md: in the target
    # architecture ethanol carries reducing equivalents into the matrix rather than only
    # competing for pyruvate, so that literature needs its own admission route.
    # E6 (genetic basis of industrial performance) was added at the owner's request: what makes
    # Ethanol Red hyper-producing and ethanol-tolerant. Ethanol Red is the proxy genome for the
    # real chassis, so it is the most directly transferable ethanol question available.
    capped = families["ethanol_scerevisiae_prod_ferm_tol"]
    assert [sq.criterion for sq in capped.sub_queries] == ["E1", "E2", "E3", "E4", "E5", "E6"]

    # And the ethanol x mtDNA family must actually be admissible. It previously ran as a bare
    # `term`, so every hit carried no criterion and defaulted to 'excluded' -- the coverage was
    # requested, collected, and then silently discarded. It now runs as an E5 sub-query.
    eth_mito = families["ethanol_mitochondria_yeast"]
    assert [sq.criterion for sq in eth_mito.sub_queries] == ["E5"]
    assert eth_mito.term is None


def test_a_family_key_the_parser_would_ignore_is_an_error(tmp_path: Path) -> None:
    """A key that parses but is ignored reads as policy while doing nothing.

    `admission_criteria` sat in the shipped file looking like an admission rule that discovery
    never consulted. Silently ignoring it is how that survived review.
    """
    path = tmp_path / "families.yaml"
    path.write_text(
        "version: 1\nfamilies:\n"
        "  - name: f\n    db: pubmed\n    product_tier: isobutanol\n"
        "    default_disposition: include_unless_excluded\n    expected_count: 1\n"
        "    term: x[tiab]\n    admission_criteria: [E1]\n",
        encoding="utf-8",
    )
    with pytest.raises(QueryFamiliesError, match="unknown key"):
        load_query_families(path)


def test_load_query_families_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(QueryFamiliesError):
        load_query_families(tmp_path / "nope.yaml")


def test_load_query_families_requires_families_key(tmp_path: Path) -> None:
    path = tmp_path / "families.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(QueryFamiliesError, match="families"):
        load_query_families(path)


def test_query_family_rejects_both_term_and_sub_queries() -> None:
    with pytest.raises(QueryFamiliesError, match="exactly one"):
        QueryFamily(
            name="bad",
            db="pubmed",
            product_tier="isobutanol",
            default_disposition="include_unless_excluded",
            expected_count=1,
            term="x",
            sub_queries=(SubQuery(criterion="E1", label="l", term="y"),),
        )


def test_query_family_rejects_neither_term_nor_sub_queries() -> None:
    with pytest.raises(QueryFamiliesError, match="exactly one"):
        QueryFamily(
            name="bad",
            db="pubmed",
            product_tier="isobutanol",
            default_disposition="include_unless_excluded",
            expected_count=1,
        )


def test_query_family_rejects_unknown_product_tier() -> None:
    with pytest.raises(QueryFamiliesError, match="product_tier"):
        QueryFamily(
            name="bad",
            db="pubmed",
            product_tier="butanol",
            default_disposition="include_unless_excluded",
            expected_count=1,
            term="x",
        )


def test_query_family_rejects_unknown_default_disposition() -> None:
    with pytest.raises(QueryFamiliesError, match="default_disposition"):
        QueryFamily(
            name="bad",
            db="pubmed",
            product_tier="isobutanol",
            default_disposition="maybe",
            expected_count=1,
            term="x",
        )


def test_sub_query_rejects_unknown_criterion() -> None:
    with pytest.raises(QueryFamiliesError, match="criterion"):
        SubQuery(criterion="E9", label="l", term="x")


def test_load_query_families_rejects_duplicate_names(tmp_path: Path) -> None:
    path = tmp_path / "dup.yaml"
    path.write_text(
        "version: 1\n"
        "families:\n"
        "  - name: fam\n"
        "    product_tier: isobutanol\n"
        "    default_disposition: include_unless_excluded\n"
        "    expected_count: 1\n"
        "    term: x\n"
        "  - name: fam\n"
        "    product_tier: isobutanol\n"
        "    default_disposition: include_unless_excluded\n"
        "    expected_count: 1\n"
        "    term: y\n",
        encoding="utf-8",
    )
    with pytest.raises(QueryFamiliesError, match="duplicate"):
        load_query_families(path)


# ------------------------------------------------------------------------------- read queries


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


def _one_family_universe(**overrides: object) -> QueryFamilies:
    defaults: dict[str, object] = dict(
        name="isobutanol_mitochondria",
        db="pubmed",
        product_tier="isobutanol",
        default_disposition="include_unless_excluded",
        expected_count=33,
        term="isobutanol[tiab] AND mitochondri*[tiab]",
    )
    defaults.update(overrides)
    return QueryFamilies(version=1, measured_on="test", families=(QueryFamily(**defaults),))


def test_family_status_reports_drift_and_triage_counts(conn: sqlite3.Connection) -> None:
    families = _one_family_universe()
    conn.execute(
        "INSERT INTO search_run (id, family, db, term, started_at, finished_at, hit_count, "
        "retrieved_count, query_families_version, dry_run) "
        "VALUES ('run-1', 'isobutanol_mitochondria', 'pubmed', 'x', 't0', 't1', 40, 40, 1, 0)"
    )
    for pub_id, triage in (("doi:a", "included"), ("doi:b", "included"), ("doi:c", "excluded")):
        conn.execute(
            "INSERT INTO publication (id, zone, evidence, confidence) "
            "VALUES (?, 'R', 'test', 'unverified')",
            (pub_id,),
        )
        conn.execute(
            "INSERT INTO screening_record (id, publication_id, family, first_seen_run_id, "
            "last_seen_run_id, triage_state, exclusion_reason, product_tier, "
            "default_disposition) "
            "VALUES (?, ?, 'isobutanol_mitochondria', 'run-1', 'run-1', ?, ?, 'isobutanol', "
            "'include_unless_excluded')",
            (f"sr-{pub_id}", pub_id, triage, None if triage == "included" else "test exclusion"),
        )
    conn.commit()

    [status] = family_status(conn, families)
    assert status.expected_count == 33
    assert status.last_hit_count == 40
    assert status.drift == 40 - 33
    assert status.included == 2
    assert status.excluded == 1
    assert status.needs_full_text == 0


def test_family_status_with_no_runs_yet_has_null_drift(conn: sqlite3.Connection) -> None:
    [status] = family_status(conn, _one_family_universe())
    assert status.last_hit_count is None
    assert status.drift is None
    assert status.included == status.needs_full_text == status.excluded == 0


def test_excluded_records_and_needs_full_text_are_disjoint_views(
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        "INSERT INTO search_run (id, family, db, term, started_at, query_families_version) "
        "VALUES ('run-1', 'fam', 'pubmed', 'x', 't0', 1)"
    )
    rows = [
        ("doi:a", "excluded", "no criterion admitted"),
        ("doi:b", "needs_full_text", None),
        ("doi:c", "included", None),
    ]
    for pub_id, triage, reason in rows:
        conn.execute(
            "INSERT INTO publication (id, zone, evidence, confidence) "
            "VALUES (?, 'R', 'test', 'unverified')",
            (pub_id,),
        )
        conn.execute(
            "INSERT INTO screening_record (id, publication_id, family, first_seen_run_id, "
            "last_seen_run_id, triage_state, exclusion_reason, product_tier, "
            "default_disposition) "
            "VALUES (?, ?, 'fam', 'run-1', 'run-1', ?, ?, 'ethanol', 'exclude_unless_admitted')",
            (f"sr-{pub_id}", pub_id, triage, reason),
        )
    conn.commit()

    excluded = excluded_records(conn)
    assert [r["publication_id"] for r in excluded] == ["doi:a"]
    assert excluded[0]["exclusion_reason"] == "no criterion admitted"

    pending = needs_full_text(conn)
    assert [r["publication_id"] for r in pending] == ["doi:b"]


# =================================================================================================
# discovery.py
# =================================================================================================


def test_normalize_title_lowercases_and_strips_punctuation() -> None:
    assert normalize_title("Isobutanol: A Review!") == "isobutanol a review"
    assert normalize_title(None) is None
    assert normalize_title("   ") is None


def test_canonical_publication_id_prefers_doi_over_pmid() -> None:
    assert canonical_publication_id(doi="10.1/X", pmid="123") == "doi:10.1/x"
    assert canonical_publication_id(doi=None, pmid="123") == "pmid:123"
    assert canonical_publication_id(doi=None, pmid=None) is None


def _isobutanol_mitochondria_family() -> QueryFamily:
    return QueryFamily(
        name="isobutanol_mitochondria",
        db="pubmed",
        product_tier="isobutanol",
        default_disposition="include_unless_excluded",
        expected_count=33,
        term="isobutanol[tiab] AND mitochondri*[tiab]",
    )


def test_run_family_isobutanol_tier_includes_and_dedupes_shared_doi(
    conn: sqlite3.Connection,
) -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")],
            "esummary.fcgi": [_fixture("esummary_isobutanol_mitochondria.json")],
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = _isobutanol_mitochondria_family()

    result = run_family(conn, client, family, query_families_version=1)

    assert result.dry_run is False
    assert result.hit_count == 3  # esearch's reported count
    assert result.retrieved_count == 3  # 3 raw hits from esummary, before dedupe
    # PMIDs 20981231 and 20981233 share one DOI and collapse into one publication.
    assert result.included == 2
    assert result.needs_full_text == 0
    assert result.excluded == 0

    pub_count = conn.execute("SELECT COUNT(*) FROM publication").fetchone()[0]
    assert pub_count == 2
    shared = conn.execute(
        "SELECT pmid, doi FROM publication WHERE id = 'doi:10.1000/example.nbt2013'"
    ).fetchone()
    # The first hit to create the row wins; the second hit's PMID does not overwrite it.
    assert shared["pmid"] == "20981231"

    screening_rows = conn.execute(
        "SELECT triage_state, exclusion_reason, admitted_criterion, product_tier, zone, "
        "review_state FROM screening_record WHERE family = 'isobutanol_mitochondria'"
    ).fetchall()
    assert len(screening_rows) == 2
    for row in screening_rows:
        assert row["triage_state"] == "included"
        assert row["exclusion_reason"] is None
        assert row["admitted_criterion"] is None
        assert row["product_tier"] == "isobutanol"
        assert row["zone"] == "H"
        assert row["review_state"] == "proposed"

    run_row = conn.execute(
        "SELECT hit_count, retrieved_count, dry_run FROM search_run WHERE id = ?", (result.run_id,)
    ).fetchone()
    assert (run_row["hit_count"], run_row["retrieved_count"], run_row["dry_run"]) == (3, 3, 0)


def test_run_family_ethanol_plain_term_excludes_with_a_reason(
    conn: sqlite3.Connection,
) -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_ethanol_plain.json")],
            "esummary.fcgi": [_fixture("esummary_ethanol_plain.json")],
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = QueryFamily(
        name="ethanol_mitochondria_yeast",
        db="pubmed",
        product_tier="ethanol",
        default_disposition="exclude_unless_admitted",
        expected_count=642,
        term="ethanol[tiab] AND mitochondri*[tiab]",
    )

    result = run_family(conn, client, family, query_families_version=1)

    assert result.excluded == 1
    assert result.included == 0
    assert result.needs_full_text == 0

    row = conn.execute(
        "SELECT triage_state, exclusion_reason, admitted_criterion, product_tier "
        "FROM screening_record WHERE family = 'ethanol_mitochondria_yeast'"
    ).fetchone()
    assert row["triage_state"] == "excluded"
    assert row["admitted_criterion"] is None
    assert row["product_tier"] == "ethanol"
    # Never a silent exclusion: the reason names the actual policy applied.
    assert row["exclusion_reason"] is not None
    assert "exclude-unless-admitted" in row["exclusion_reason"]
    assert "B.3" in row["exclusion_reason"]


def test_run_family_ethanol_criterion_subquery_is_needs_full_text_not_included(
    conn: sqlite3.Connection,
) -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_ethanol_e1.json")],
            "esummary.fcgi": [_fixture("esummary_ethanol_e1.json")],
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = QueryFamily(
        name="ethanol_scerevisiae_prod_ferm_tol",
        db="pubmed",
        product_tier="ethanol",
        default_disposition="exclude_unless_admitted",
        expected_count=6072,
        sub_queries=(SubQuery(criterion="E1", label="competing_sink", term="PDC1 AND deletion"),),
    )

    result = run_family(conn, client, family, query_families_version=1)

    # A criterion-tagged keyword match is a CANDIDATE, not a confirmed admission.
    assert result.needs_full_text == 1
    assert result.included == 0
    assert result.excluded == 0

    row = conn.execute(
        "SELECT triage_state, admitted_criterion, exclusion_reason "
        "FROM screening_record WHERE family = 'ethanol_scerevisiae_prod_ferm_tol'"
    ).fetchone()
    assert row["triage_state"] == "needs_full_text"
    assert row["admitted_criterion"] == "E1"
    assert row["exclusion_reason"] is None


def test_dry_run_calls_esearch_only_and_writes_nothing(conn: sqlite3.Connection) -> None:
    # No 'esummary.fcgi' entry registered at all: if dry_run leaked into fetching summaries, the
    # FakeTransport would raise AssertionError rather than the test merely getting zero rows.
    transport = FakeTransport({"esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")]})
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = _isobutanol_mitochondria_family()

    result = run_family(conn, client, family, query_families_version=1, dry_run=True)

    assert result.dry_run is True
    assert result.hit_count == 3
    assert result.retrieved_count == 0
    assert result.included == result.needs_full_text == result.excluded == 0
    assert len(transport.calls) == 1

    assert conn.execute("SELECT COUNT(*) FROM search_run").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM publication").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM screening_record").fetchone()[0] == 0


def test_rerunning_the_same_family_updates_last_seen_run_without_duplicating(
    conn: sqlite3.Connection,
) -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_ethanol_plain.json")] * 2,
            "esummary.fcgi": [_fixture("esummary_ethanol_plain.json")] * 2,
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = QueryFamily(
        name="ethanol_mitochondria_yeast",
        db="pubmed",
        product_tier="ethanol",
        default_disposition="exclude_unless_admitted",
        expected_count=642,
        term="ethanol[tiab] AND mitochondri*[tiab]",
    )

    first = run_family(conn, client, family, query_families_version=1)
    second = run_family(conn, client, family, query_families_version=1)

    assert first.run_id != second.run_id
    assert conn.execute("SELECT COUNT(*) FROM screening_record").fetchone()[0] == 1
    row = conn.execute(
        "SELECT first_seen_run_id, last_seen_run_id, triage_state FROM screening_record"
    ).fetchone()
    assert row["first_seen_run_id"] == first.run_id
    assert row["last_seen_run_id"] == second.run_id
    assert row["triage_state"] == "excluded"  # still the automated default; nothing to preserve


def test_a_curator_reviewed_screening_record_is_never_silently_overwritten_by_a_rerun(
    conn: sqlite3.Connection,
) -> None:
    transport = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")] * 2,
            "esummary.fcgi": [_fixture("esummary_isobutanol_mitochondria.json")] * 2,
        }
    )
    client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    family = _isobutanol_mitochondria_family()

    run_family(conn, client, family, query_families_version=1)

    # A curator reads one of the two publications and decides it is actually off-topic --
    # overriding the automated 'included' default and marking the review done.
    conn.execute(
        "UPDATE screening_record SET triage_state = 'excluded', "
        "exclusion_reason = 'curator: off-topic on full read', review_state = 'accepted' "
        "WHERE publication_id = 'doi:10.1000/example.nbt2013'"
    )
    conn.commit()

    second = run_family(conn, client, family, query_families_version=1)

    row = conn.execute(
        "SELECT triage_state, exclusion_reason, review_state, last_seen_run_id "
        "FROM screening_record WHERE publication_id = 'doi:10.1000/example.nbt2013'"
    ).fetchone()
    # The curator's judgement survived the rerun...
    assert row["triage_state"] == "excluded"
    assert row["exclusion_reason"] == "curator: off-topic on full read"
    assert row["review_state"] == "accepted"
    # ...but the rerun still recorded that the hit was seen again.
    assert row["last_seen_run_id"] == second.run_id

    # The still-'proposed' second publication, by contrast, is freely refreshed by the rerun.
    other = conn.execute(
        "SELECT review_state, last_seen_run_id FROM screening_record "
        "WHERE publication_id = 'pmid:20981232'"
    ).fetchone()
    assert other["review_state"] == "proposed"
    assert other["last_seen_run_id"] == second.run_id


def test_the_same_publication_found_by_two_families_shares_one_publication_row(
    conn: sqlite3.Connection,
) -> None:
    family_a = _isobutanol_mitochondria_family()
    family_b = QueryFamily(
        name="mtdna_engineering_yeast",
        db="pubmed",
        product_tier="isobutanol",
        default_disposition="include_unless_excluded",
        expected_count=823,
        term="mtDNA[tiab] AND engineering[tiab]",
    )

    transport_a = FakeTransport(
        {
            "esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")],
            "esummary.fcgi": [_fixture("esummary_isobutanol_mitochondria.json")],
        }
    )
    client_a = EutilsClient(transport=transport_a, sleep=lambda _: None, monotonic=lambda: 0.0)
    run_family(conn, client_a, family_a, query_families_version=1)

    # family_b's search turns up a DIFFERENT PMID that happens to carry the SAME DOI as one of
    # family_a's hits -- the cross-family dedupe case discovery.py must collapse to one row.
    transport_b = FakeTransport(
        {
            "esearch.fcgi": [b'{"esearchresult": {"count": "1", "idlist": ["60112233"]}}'],
            "esummary.fcgi": [
                (
                    b'{"result": {"uids": ["60112233"], "60112233": {"uid": "60112233", '
                    b'"title": "A different-PMID report of the same underlying paper", '
                    b'"pubdate": "2014", "fulljournalname": "Some Journal", '
                    b'"articleids": [{"idtype": "pubmed", "value": "60112233"}, '
                    b'{"idtype": "doi", "value": "10.1000/example.nbt2013"}]}}}'
                )
            ],
        }
    )
    client_b = EutilsClient(transport=transport_b, sleep=lambda _: None, monotonic=lambda: 0.0)
    run_family(conn, client_b, family_b, query_families_version=1)

    pub_rows = conn.execute(
        "SELECT id, pmid FROM publication WHERE id = 'doi:10.1000/example.nbt2013'"
    ).fetchall()
    assert len(pub_rows) == 1
    assert pub_rows[0]["pmid"] == "20981231"  # first writer (family_a) wins

    screening = conn.execute(
        "SELECT family FROM screening_record WHERE publication_id = 'doi:10.1000/example.nbt2013' "
        "ORDER BY family"
    ).fetchall()
    assert [r["family"] for r in screening] == [
        "isobutanol_mitochondria",
        "mtdna_engineering_yeast",
    ]


# =================================================================================================
# CLI: `fermdb literature discover` / `fermdb literature status`
# =================================================================================================


def test_build_parser_wires_literature_discover_arguments() -> None:
    args = cli.build_parser().parse_args(
        ["literature", "discover", "--family", "isobutanol_all", "--dry-run", "--max-records", "5"]
    )
    assert args.family == "isobutanol_all"
    assert args.dry_run is True
    assert args.max_records == 5
    assert args.func is cli.cmd_literature_discover


def test_build_parser_wires_literature_discover_defaults() -> None:
    args = cli.build_parser().parse_args(["literature", "discover"])
    assert args.family is None
    assert args.dry_run is False
    assert args.max_records is None


def test_build_parser_wires_literature_status() -> None:
    args = cli.build_parser().parse_args(["literature", "status"])
    assert args.func is cli.cmd_literature_status


def _write_single_family_yaml(path: Path) -> None:
    path.write_text(
        "version: 1\n"
        "measured_on: test\n"
        "families:\n"
        "  - name: isobutanol_mitochondria\n"
        "    db: pubmed\n"
        "    product_tier: isobutanol\n"
        "    default_disposition: include_unless_excluded\n"
        "    expected_count: 33\n"
        "    term: 'isobutanol[tiab] AND mitochondri*[tiab]'\n",
        encoding="utf-8",
    )


def test_cli_literature_discover_dry_run_writes_nothing_and_never_touches_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    literature_dir = tmp_path / "literature"
    literature_dir.mkdir()
    _write_single_family_yaml(literature_dir / "query_families.yaml")
    monkeypatch.setenv("FERMDB_LITERATURE_DIR", str(literature_dir))
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))

    transport = FakeTransport({"esearch.fcgi": [_fixture("esearch_isobutanol_mitochondria.json")]})
    fake_client = EutilsClient(transport=transport, sleep=lambda _: None, monotonic=lambda: 0.0)
    monkeypatch.setattr(cli, "_literature_client", lambda: fake_client)

    exit_code = cli.main(["literature", "discover", "--dry-run"])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "isobutanol_mitochondria" in out
    assert "dry-run" in out

    db_path = tmp_path / "derived" / "fermdb.sqlite3"
    assert db_path.exists()  # open_db still creates the (empty-of-literature-rows) schema
    with open_db(db_path, create=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM search_run").fetchone()[0] == 0


def test_cli_literature_discover_unknown_family_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    literature_dir = tmp_path / "literature"
    literature_dir.mkdir()
    _write_single_family_yaml(literature_dir / "query_families.yaml")
    monkeypatch.setenv("FERMDB_LITERATURE_DIR", str(literature_dir))
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))
    monkeypatch.setattr(
        cli, "_literature_client", lambda: EutilsClient(transport=FakeTransport({}))
    )

    exit_code = cli.main(["literature", "discover", "--family", "does_not_exist"])
    assert exit_code == 2
    assert "unknown family" in capsys.readouterr().err


def test_cli_literature_status_reports_every_shipped_family_with_no_runs_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Deliberately leaves FERMDB_LITERATURE_DIR unset, so this reads the REAL shipped
    # data/literature/query_families.yaml through the normal Settings resolution path.
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))

    exit_code = cli.main(["literature", "status"])
    assert exit_code == 0

    out = capsys.readouterr().out
    for family_name in (
        "isobutanol_all",
        "isobutanol_mitochondria",
        "mtdna_engineering_yeast",
        "mtdna_methods_yeast",
        "ethanol_mitochondria_yeast",
        "ethanol_scerevisiae_prod_ferm_tol",
    ):
        assert family_name in out
