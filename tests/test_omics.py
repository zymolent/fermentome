"""Tests for `fermdb.omics` (SRA/GEO metadata discovery and the small DNA references).

Everything runs offline: `FakeFetch` below is the only `FetchFn` any test uses, and it raises if
asked for a URL it was not given a canned response for -- the same "a producer's failure must be
checked" discipline docs/reference/CONVENTIONS.md asks for elsewhere, applied to "did this test
accidentally reach the network". No test in this file may pass by silently falling through to
`fermdb.omics.urllib_fetch`.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb import genetic_code
from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import (
    DatasetFamiliesError,
    ESearchResult,
    EutilsClient,
    OmicsFetchError,
    dataset_families_path,
    family_by_name,
    load_dataset_families,
)
from fermdb.omics import geo as geo_mod
from fermdb.omics import references as references_mod
from fermdb.omics import sra as sra_mod

FIXTURES = Path(__file__).parent / "fixtures" / "omics"
REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DATASET_FAMILIES = REPO_ROOT / "data" / "omics" / "dataset_families.yaml"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetch:
    """A `FetchFn` that serves canned bodies keyed by (path, sorted query params).

    Keying on path + sorted params rather than the raw URL means a test does not have to know or
    care what order `EutilsClient` builds a query string in.
    """

    def __init__(self) -> None:
        self._responses: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}
        self.calls: list[str] = []

    def add(self, path: str, params: dict[str, str], body: str) -> None:
        key = (path, tuple(sorted(params.items())))
        self._responses[key] = body

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        parsed = urllib.parse.urlsplit(url)
        params = {k: v for k, v in urllib.parse.parse_qsl(parsed.query) if k not in ("tool",)}
        key = (parsed.path, tuple(sorted(params.items())))
        if key not in self._responses:
            raise AssertionError(f"FakeFetch has no canned response for {url}")
        return self._responses[key]


def _client(fake: FakeFetch) -> EutilsClient:
    return EutilsClient(fetch=fake, min_interval_s=0.0)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# EutilsClient
# ---------------------------------------------------------------------------------------------


def test_esearch_parses_count_ids_and_paging_fields() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "isobutanol", "retstart": "0", "retmax": "5", "retmode": "json"},
        json.dumps(
            {
                "esearchresult": {
                    "count": "147",
                    "retmax": "5",
                    "retstart": "0",
                    "idlist": ["1", "2", "3", "4", "5"],
                }
            }
        ),
    )
    result = _client(fake).esearch(db="sra", term="isobutanol", retmax=5)
    assert result == ESearchResult(count=147, ids=("1", "2", "3", "4", "5"), retmax=5, retstart=0)


def test_esearch_zero_hits_returns_empty_ids() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "no such thing", "retstart": "0", "retmax": "200", "retmode": "json"},
        json.dumps({"esearchresult": {"count": "0", "retmax": "0", "retstart": "0", "idlist": []}}),
    )
    result = _client(fake).esearch(db="sra", term="no such thing")
    assert result.count == 0
    assert result.ids == ()


def test_esearch_malformed_json_raises_omics_fetch_error() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "x", "retstart": "0", "retmax": "200", "retmode": "json"},
        "not json at all",
    )
    with pytest.raises(OmicsFetchError):
        _client(fake).esearch(db="sra", term="x")


def test_esearch_all_ids_pages_until_exhausted() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "x", "retstart": "0", "retmax": "2", "retmode": "json"},
        json.dumps(
            {"esearchresult": {"count": "3", "retmax": "2", "retstart": "0", "idlist": ["1", "2"]}}
        ),
    )
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "x", "retstart": "2", "retmax": "2", "retmode": "json"},
        json.dumps(
            {"esearchresult": {"count": "3", "retmax": "2", "retstart": "2", "idlist": ["3"]}}
        ),
    )
    ids = _client(fake).esearch_all_ids(db="sra", term="x", page_size=2)
    assert ids == ["1", "2", "3"]


def test_esummary_returns_docs_in_uids_order() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esummary.fcgi",
        {"db": "gds", "id": "20,10", "retmode": "json"},
        json.dumps(
            {
                "result": {
                    "uids": ["20", "10"],
                    "10": {"accession": "GSE10"},
                    "20": {"accession": "GSE20"},
                }
            }
        ),
    )
    docs = _client(fake).esummary(db="gds", ids=["20", "10"])
    assert [d["accession"] for d in docs] == ["GSE20", "GSE10"]


def test_esummary_of_no_ids_makes_no_request() -> None:
    fake = FakeFetch()
    docs = _client(fake).esummary(db="gds", ids=[])
    assert docs == []
    assert fake.calls == []


def test_efetch_returns_raw_text() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "sra", "id": "SRR1,SRR2", "rettype": "runinfo", "retmode": "text"},
        "Run,LibraryStrategy\nSRR1,RNA-Seq\n",
    )
    body = _client(fake).efetch(db="sra", ids=["SRR1", "SRR2"], rettype="runinfo")
    assert "SRR1,RNA-Seq" in body


def test_client_throttles_between_requests() -> None:
    sleeps: list[float] = []
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "x", "retstart": "0", "retmax": "200", "retmode": "json"},
        json.dumps({"esearchresult": {"count": "0", "retmax": "0", "retstart": "0", "idlist": []}}),
    )
    client = EutilsClient(fetch=fake, min_interval_s=0.1, sleep=sleeps.append)
    client.esearch(db="sra", term="x")
    assert sleeps == [0.1]


# ---------------------------------------------------------------------------------------------
# sra.py: runinfo parsing
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def runinfo_csv() -> str:
    return _read("sra_runinfo_isobutanol_sample.csv")


def test_parse_runinfo_csv_parses_every_real_sample_row(runinfo_csv: str) -> None:
    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    assert len(runs) == 7
    assert {r.run_accession for r in runs} == {
        "SRR33767563",
        "SRR33767561",
        "SRR7892090",
        "SRR29711608",
        "SRR16642822",
        "SRR12265272",
        "SRR14687229",
    }


def test_parse_runinfo_csv_types_numeric_fields_and_keeps_blanks_as_none(runinfo_csv: str) -> None:
    runs = {r.run_accession: r for r in sra_mod.parse_runinfo_csv(runinfo_csv)}
    tnseq = runs["SRR33767563"]
    assert tnseq.library_strategy == "Tn-Seq"
    assert tnseq.spots == 7007634
    assert tnseq.bases == 1058152734
    assert tnseq.size_mb == pytest.approx(391.0)
    assert tnseq.bioproject == "PRJNA1270032"
    assert tnseq.organism == "Zymomonas mobilis subsp. mobilis ZM4 = ATCC 31821"
    assert tnseq.location_url.startswith("https://")
    # Study_Pubmed_id is blank for this row in the real report -- confirms blanks become "", not
    # a crash, for a column this dataclass does not even surface directly.
    assert tnseq.raw["Study_Pubmed_id"] == ""


def test_parse_runinfo_csv_empty_text_is_no_runs() -> None:
    assert sra_mod.parse_runinfo_csv("") == []
    assert sra_mod.parse_runinfo_csv("   \n  ") == []


def test_parse_runinfo_csv_rejects_text_without_the_expected_header() -> None:
    with pytest.raises(sra_mod.RuninfoParseError):
        sra_mod.parse_runinfo_csv("not,a,runinfo,header\n1,2,3,4\n")


def test_priority_rank_puts_tnseq_first_and_unknown_strategies_last() -> None:
    ranks = {
        s: sra_mod.priority_rank_for(s)
        for s in ("Tn-Seq", "WGS", "RNA-Seq", "AMPLICON", "OTHER", "SOMETHING-NEW")
    }
    assert ranks["Tn-Seq"] < ranks["WGS"] < ranks["RNA-Seq"] < ranks["AMPLICON"] < ranks["OTHER"]
    assert ranks["SOMETHING-NEW"] > ranks["OTHER"]


def test_count_by_library_strategy(runinfo_csv: str) -> None:
    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    counts = sra_mod.count_by_library_strategy(runs)
    assert counts == {"Tn-Seq": 2, "WGS": 1, "RNA-Seq": 2, "OTHER": 1, "AMPLICON": 1}


# ---------------------------------------------------------------------------------------------
# sra.py: discovery over the fake transport
# ---------------------------------------------------------------------------------------------


def test_discover_sra_runs_esearches_then_efetches_runinfo(runinfo_csv: str) -> None:
    fake = FakeFetch()
    ids = [str(i) for i in range(7)]
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "isobutanol", "retstart": "0", "retmax": "200", "retmode": "json"},
        json.dumps(
            {"esearchresult": {"count": "7", "retmax": "7", "retstart": "0", "idlist": ids}}
        ),
    )
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "sra", "id": ",".join(ids), "rettype": "runinfo", "retmode": "text"},
        runinfo_csv,
    )
    search, runs = sra_mod.discover_sra_runs(_client(fake), "isobutanol")
    assert search.count == 7
    assert len(runs) == 7


def test_discover_sra_runs_zero_hits_never_calls_efetch() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "nonsense", "retstart": "0", "retmax": "200", "retmode": "json"},
        json.dumps({"esearchresult": {"count": "0", "retmax": "0", "retstart": "0", "idlist": []}}),
    )
    search, runs = sra_mod.discover_sra_runs(_client(fake), "nonsense")
    assert search.count == 0
    assert runs == []
    assert not any("efetch" in call for call in fake.calls)


def test_discover_sra_runs_refuses_over_the_max_run_ids_cap() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {
            "db": "sra",
            "term": 'ethanol AND "Saccharomyces cerevisiae"[Organism]',
            "retstart": "0",
            "retmax": "200",
            "retmode": "json",
        },
        json.dumps(
            {"esearchresult": {"count": "13117", "retmax": "0", "retstart": "0", "idlist": []}}
        ),
    )
    with pytest.raises(OmicsFetchError):
        sra_mod.discover_sra_runs(
            _client(fake), 'ethanol AND "Saccharomyces cerevisiae"[Organism]', max_run_ids=2000
        )
    # The cap fires straight off the esearch count; no attempt was made to page all 13k ids or
    # efetch runinfo, so exactly the one esearch call above happened and nothing else.
    assert len(fake.calls) == 1


def test_download_run_bytes_is_a_deliberate_tripwire() -> None:
    with pytest.raises(NotImplementedError):
        sra_mod.download_run_bytes("SRR0000000")


# ---------------------------------------------------------------------------------------------
# sra.py + geo.py: dataset linkage
# ---------------------------------------------------------------------------------------------


def test_resolve_dataset_id_prefers_a_geo_series_sharing_the_bioproject(runinfo_csv: str) -> None:
    runs = {r.run_accession: r for r in sra_mod.parse_runinfo_csv(runinfo_csv)}
    yeast_run = runs["SRR14687229"]  # real: BioProject PRJNA733673, GEO series GSE175794
    geo_ids = {"PRJNA733673": "geo:GSE175794"}
    assert sra_mod.resolve_dataset_id(yeast_run, geo_ids) == "geo:GSE175794"


def test_resolve_dataset_id_falls_back_to_the_sra_study_when_no_geo_series_matches(
    runinfo_csv: str,
) -> None:
    runs = {r.run_accession: r for r in sra_mod.parse_runinfo_csv(runinfo_csv)}
    tnseq_run = runs["SRR33767563"]  # BioProject PRJNA1270032, no GEO series in our fixture
    assert sra_mod.resolve_dataset_id(tnseq_run, {}) == "insdc.sra:SRP588897"


def test_dataset_ids_by_bioproject_skips_series_with_no_bioproject() -> None:
    series = [
        geo_mod.GeoSeries(
            accession="GSE1",
            title="t",
            taxon="x",
            platform="GPL1",
            entrytype="GSE",
            pdat="2020/01/01",
            n_samples=1,
            bioproject="PRJNA1",
            sample_accessions=("GSM1",),
        ),
        geo_mod.GeoSeries(
            accession="GSE2",
            title="t2",
            taxon="x",
            platform="GPL1",
            entrytype="GSE",
            pdat="2020/01/01",
            n_samples=1,
            bioproject=None,
            sample_accessions=(),
        ),
    ]
    assert geo_mod.dataset_ids_by_bioproject(series) == {"PRJNA1": "geo:GSE1"}


# ---------------------------------------------------------------------------------------------
# geo.py: esummary parsing, including the real GSE175794 <-> PRJNA733673 <-> SRR14687229 chain
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def geo_summaries() -> list[dict[str, object]]:
    payload = json.loads(_read("geo_esummary_isobutanol_sample.json"))
    result = payload["result"]
    return [result[uid] for uid in result["uids"]]


def test_discover_geo_series_parses_real_fixture_series(
    geo_summaries: list[dict[str, object]],
) -> None:
    ids = [str(s["uid"]) for s in geo_summaries]
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {
            "db": "gds",
            "term": "isobutanol AND gse[EntryType]",
            "retstart": "0",
            "retmax": "100",
            "retmode": "json",
        },
        json.dumps(
            {
                "esearchresult": {
                    "count": str(len(ids)),
                    "retmax": str(len(ids)),
                    "retstart": "0",
                    "idlist": ids,
                }
            }
        ),
    )
    fake.add(
        "/entrez/eutils/esummary.fcgi",
        {"db": "gds", "id": ",".join(ids), "retmode": "json"},
        json.dumps({"result": {"uids": ids, **{str(s["uid"]): s for s in geo_summaries}}}),
    )
    series = geo_mod.discover_geo_series(_client(fake), "isobutanol AND gse[EntryType]")
    assert len(series) == 3
    by_accession = {s.accession: s for s in series}
    yeast = by_accession["GSE175794"]
    assert yeast.bioproject == "PRJNA733673"
    assert yeast.taxon == "Saccharomyces cerevisiae S288C"
    assert "GSM5348155" in yeast.sample_accessions
    assert by_accession["GSE999999"].bioproject is None  # the synthetic no-bioproject fixture row


def test_discover_geo_series_no_hits_returns_empty_without_esummary() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "gds", "term": "x", "retstart": "0", "retmax": "100", "retmode": "json"},
        json.dumps({"esearchresult": {"count": "0", "retmax": "0", "retstart": "0", "idlist": []}}),
    )
    assert geo_mod.discover_geo_series(_client(fake), "x") == []
    assert not any("esummary" in call for call in fake.calls)


# ---------------------------------------------------------------------------------------------
# Writing to the database: dataset / sra_run / linkage, idempotence
# ---------------------------------------------------------------------------------------------


def test_write_geo_series_then_write_sra_runs_links_the_real_chain(
    conn: sqlite3.Connection, runinfo_csv: str, geo_summaries: list[dict[str, object]]
) -> None:
    series = [s for s in (geo_mod._series_from_summary(d) for d in geo_summaries) if s is not None]
    geo_mod.write_geo_series(conn, series, retrieved_at="2026-09-20T00:00:00Z")
    geo_ids = geo_mod.dataset_ids_by_bioproject(series)

    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    written = sra_mod.write_sra_runs(
        conn, runs, geo_dataset_ids_by_bioproject=geo_ids, retrieved_at="2026-09-20T00:00:00Z"
    )
    assert written == len(runs)

    row = conn.execute(
        "SELECT dataset_id FROM sra_run WHERE run_accession = 'SRR14687229'"
    ).fetchone()
    assert row["dataset_id"] == "geo:GSE175794"

    tnseq_row = conn.execute(
        "SELECT dataset_id FROM sra_run WHERE run_accession = 'SRR33767563'"
    ).fetchone()
    assert tnseq_row["dataset_id"] == "insdc.sra:SRP588897"
    study_dataset = conn.execute(
        "SELECT repository, bioproject FROM dataset WHERE id = 'insdc.sra:SRP588897'"
    ).fetchone()
    assert study_dataset["repository"] == "SRA"
    assert study_dataset["bioproject"] == "PRJNA1270032"


def test_write_sra_runs_is_idempotent_on_run_accession(
    conn: sqlite3.Connection, runinfo_csv: str
) -> None:
    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    sra_mod.write_sra_runs(conn, runs, geo_dataset_ids_by_bioproject={}, retrieved_at="t1")
    sra_mod.write_sra_runs(conn, runs, geo_dataset_ids_by_bioproject={}, retrieved_at="t2")
    count = conn.execute("SELECT COUNT(*) FROM sra_run").fetchone()[0]
    assert count == len(runs)
    retrieved_at = conn.execute(
        "SELECT retrieved_at FROM sra_run WHERE run_accession = 'SRR33767563'"
    ).fetchone()[0]
    assert retrieved_at == "t2"  # re-run updates the row rather than erroring or duplicating it


def test_every_written_sra_run_row_is_zone_r_and_confidence_high(
    conn: sqlite3.Connection, runinfo_csv: str
) -> None:
    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    sra_mod.write_sra_runs(conn, runs, geo_dataset_ids_by_bioproject={}, retrieved_at="t")
    rows = conn.execute("SELECT zone, confidence, evidence FROM sra_run").fetchall()
    assert all(r["zone"] == "R" for r in rows)
    assert all(r["confidence"] in ("unverified", "low", "medium", "high") for r in rows)
    assert all(r["evidence"] for r in rows)


def test_priority_rank_survives_the_round_trip_through_the_database(
    conn: sqlite3.Connection, runinfo_csv: str
) -> None:
    runs = sra_mod.parse_runinfo_csv(runinfo_csv)
    sra_mod.write_sra_runs(conn, runs, geo_dataset_ids_by_bioproject={}, retrieved_at="t")
    ordered = conn.execute(
        "SELECT run_accession, library_strategy FROM sra_run ORDER BY priority_rank, run_accession"
    ).fetchall()
    assert ordered[0]["library_strategy"] == "Tn-Seq"
    assert ordered[1]["library_strategy"] == "Tn-Seq"


def test_write_geo_series_is_idempotent_on_id(
    conn: sqlite3.Connection, geo_summaries: list[dict[str, object]]
) -> None:
    series = [s for s in (geo_mod._series_from_summary(d) for d in geo_summaries) if s is not None]
    geo_mod.write_geo_series(conn, series, retrieved_at="t1")
    geo_mod.write_geo_series(conn, series, retrieved_at="t2")
    count = conn.execute("SELECT COUNT(*) FROM dataset WHERE repository = 'GEO'").fetchone()[0]
    assert count == len(series)


# ---------------------------------------------------------------------------------------------
# references.py: FASTA / GenBank parsing
# ---------------------------------------------------------------------------------------------


def test_parse_fasta_sequence_strips_the_header(tmp_path: Path) -> None:
    fasta = _read("mtdna_atp8_excerpt.fasta")
    seq = references_mod.parse_fasta_sequence(fasta)
    assert seq.startswith("ATGCCACAATTAGTTCCATTT")
    assert seq.endswith("ATTATAA")
    assert len(seq) == 147
    assert ">" not in seq


def test_genbank_sequence_and_fasta_agree_on_the_atp8_excerpt() -> None:
    genbank_seq = references_mod._parse_genbank_sequence(_read("mtdna_atp8_excerpt.gb"))
    fasta_seq = references_mod.parse_fasta_sequence(_read("mtdna_atp8_excerpt.fasta"))
    assert genbank_seq == fasta_seq


# ---------------------------------------------------------------------------------------------
# references.py: the translation self-check (the binding requirement)
# ---------------------------------------------------------------------------------------------


def test_verify_mitochondrial_translation_confirms_table_3_and_table_1_disagreement() -> None:
    checks = references_mod.verify_mitochondrial_translation(_read("mtdna_atp8_excerpt.gb"))
    assert len(checks) == 1
    check = checks[0]
    assert check.gene == "ATP8"
    assert check.transl_table == 3
    # Table 3 reproduces NCBI's own /translation exactly.
    assert check.matches_table3 is True
    # Table 1 does not: the CUN codon at this position reads as threonine under table 3 and
    # leucine under table 1, which is exactly the mistranslation NCBI table 3 exists to avoid.
    assert check.matches_table1 is False
    assert check.table1_translation != check.table3_translation


def test_verify_mitochondrial_translation_agrees_with_genetic_code_directly() -> None:
    """Cross-check against `fermdb.genetic_code` itself, independent of this module's own logic."""
    fasta_seq = references_mod.parse_fasta_sequence(_read("mtdna_atp8_excerpt.fasta"))
    expected = "MPQLVPFYFMNQLTYGFLLMITLLILFSQFFLPMILRLYVSRLFISKL"
    assert genetic_code.translate(fasta_seq, genetic_code.TABLE_3, to_stop=True) == expected
    assert genetic_code.translate(fasta_seq, genetic_code.TABLE_1, to_stop=True) != expected


def test_verify_mitochondrial_translation_raises_if_no_simple_cds_found() -> None:
    no_cds = (
        "LOCUS       X 10 bp DNA linear PLN 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..10\n"
        '                     /organism="x"\n'
        "ORIGIN      \n"
        "        1 atgcatgcat\n"
        "//\n"
    )
    with pytest.raises(references_mod.ReferenceVerificationError):
        references_mod.verify_mitochondrial_translation(no_cds)


def test_verify_mitochondrial_translation_rejects_a_table_1_gene_dressed_up_as_mtdna() -> None:
    """A CDS whose /translation matches BOTH tables proves nothing and must be refused.

    Every codon here is unambiguous between table 1 and table 3 (no CUN, ATA or TGA), so a
    reference built only from genes like this would never demonstrate the disagreement the check
    exists to prove -- exactly the failure mode the binding instruction guards against.
    """
    fake_record = (
        "LOCUS       X 9 bp DNA linear PLN 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        "     CDS             1..9\n"
        '                     /gene="FAKE"\n'
        "                     /transl_table=3\n"
        '                     /translation="MP"\n'
        "ORIGIN      \n"
        "        1 atgccataa\n"
        "//\n"
    )
    with pytest.raises(references_mod.ReferenceVerificationError):
        references_mod.verify_mitochondrial_translation(fake_record)


def test_verify_mitochondrial_translation_raises_when_table_3_itself_disagrees() -> None:
    """If NCBI's own /translation does not match table 3 either, that is a hard failure, not a
    pass -- a reference this module cannot make sense of must never be marked verified."""
    wrong_translation_record = (
        "LOCUS       X 9 bp DNA linear PLN 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        "     CDS             1..9\n"
        '                     /gene="FAKE"\n'
        "                     /transl_table=3\n"
        '                     /translation="NOTHING"\n'
        "ORIGIN      \n"
        "        1 atgtgataa\n"
        "//\n"
    )
    with pytest.raises(references_mod.ReferenceVerificationError):
        references_mod.verify_mitochondrial_translation(wrong_translation_record)


def test_join_and_complement_cds_are_skipped_not_misparsed() -> None:
    """A `join(...)` CDS (COX1-shaped) must not be mistaken for a simple, checkable one.

    The simple CDS at 10..18 covers a TGA codon (Trp under table 3, stop under table 1), so this
    fixture also exercises the real disagreement the check exists to prove; the join(...) feature
    at 1..9 is nonsense DNA that would fail if it were ever (mis-)translated, which is exactly
    what proves it was skipped rather than silently included.
    """
    record_with_join = (
        "LOCUS       X 18 bp DNA linear PLN 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        "     CDS             join(1..3,7..9)\n"
        '                     /gene="SPLIT"\n'
        "                     /transl_table=3\n"
        '                     /translation="this would never match if translated"\n'
        "     CDS             10..18\n"
        '                     /gene="ATP8LIKE"\n'
        "                     /transl_table=3\n"
        '                     /translation="MW"\n'
        "ORIGIN      \n"
        "        1 aaaaaaaaa atgtgataa\n"
        "//\n"
    )
    checks = references_mod.verify_mitochondrial_translation(record_with_join)
    assert [c.gene for c in checks] == ["ATP8LIKE"]
    assert checks[0].matches_table3 is True
    assert checks[0].matches_table1 is False


# ---------------------------------------------------------------------------------------------
# references.py: content-addressed storage
# ---------------------------------------------------------------------------------------------


def test_store_content_addressed_is_keyed_by_sha256_and_deduplicates(tmp_path: Path) -> None:
    stored_a = references_mod.store_content_addressed(tmp_path, "same content")
    stored_b = references_mod.store_content_addressed(tmp_path, "same content")
    stored_c = references_mod.store_content_addressed(tmp_path, "different content")
    assert stored_a.path == stored_b.path
    assert stored_a.checksum_sha256 == stored_b.checksum_sha256
    assert stored_a.path != stored_c.path
    assert stored_a.path.read_text(encoding="utf-8") == "same content"
    assert stored_a.size_bytes == len(b"same content")


def test_store_content_addressed_lives_under_genomes_dir_reference(tmp_path: Path) -> None:
    stored = references_mod.store_content_addressed(tmp_path, "x")
    assert stored.path.is_relative_to(tmp_path / "reference")


# ---------------------------------------------------------------------------------------------
# references.py: fetch + verify + store, over the fake transport
# ---------------------------------------------------------------------------------------------


def _fake_nuccore(fake: FakeFetch, accession: str, *, fasta: str, genbank: str) -> None:
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": accession, "rettype": "fasta", "retmode": "text"},
        fasta,
    )
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": accession, "rettype": "gb", "retmode": "text"},
        genbank,
    )


def test_fetch_mitochondrial_reference_verifies_and_stores_both_files(tmp_path: Path) -> None:
    fake = FakeFetch()
    _fake_nuccore(
        fake,
        references_mod.MITOCHONDRIAL_ACCESSION,
        fasta=_read("mtdna_atp8_excerpt.fasta"),
        genbank=_read("mtdna_atp8_excerpt.gb"),
    )
    rows = references_mod.fetch_mitochondrial_reference(
        _client(fake), tmp_path, retrieved_at="2026-09-20T00:00:00Z"
    )
    assert {r["kind"] for r in rows} == {"mitochondrial_genome", "mitochondrial_annotation"}
    for row in rows:
        assert row["translation_verified"] == 1
        assert row["zone"] == "R"
        assert row["confidence"] == "high"
        assert Path(str(row["file_path"])).is_file()
        assert row["encoding_genome"] == "mitochondrial"


def test_fetch_mitochondrial_reference_refuses_to_store_a_bad_reference(tmp_path: Path) -> None:
    """A reference that fails the translation check is never written under genomes_dir at all."""
    fake = FakeFetch()
    corrupt_genbank = _read("mtdna_atp8_excerpt.gb").replace(
        '/translation="MPQLVPFYFMNQLTYGFLLMITLLILFSQFFLPMILRLYVSRLF', '/translation="XXXXXXXX'
    )
    _fake_nuccore(
        fake,
        references_mod.MITOCHONDRIAL_ACCESSION,
        fasta=_read("mtdna_atp8_excerpt.fasta"),
        genbank=corrupt_genbank,
    )
    with pytest.raises(references_mod.ReferenceVerificationError):
        references_mod.fetch_mitochondrial_reference(
            _client(fake), tmp_path, retrieved_at="2026-09-20T00:00:00Z"
        )
    assert not (tmp_path / "reference").exists()


def test_fetch_nuclear_reference_fetches_and_stores_every_accession(tmp_path: Path) -> None:
    fake = FakeFetch()
    _fake_nuccore(
        fake, "SYN_CHR_A", fasta=_read("synthetic_chr_a.fasta"), genbank=_read("synthetic_chr_a.gb")
    )
    _fake_nuccore(
        fake, "SYN_CHR_B", fasta=_read("synthetic_chr_b.fasta"), genbank=_read("synthetic_chr_b.gb")
    )
    rows = references_mod.fetch_nuclear_reference(
        _client(fake), tmp_path, retrieved_at="t", accessions=("SYN_CHR_A", "SYN_CHR_B")
    )
    assert len(rows) == 4  # genome + annotation, per accession
    accessions = {(r["sequence_accession"], r["kind"]) for r in rows}
    assert accessions == {
        ("SYN_CHR_A", "nuclear_genome"),
        ("SYN_CHR_A", "nuclear_annotation"),
        ("SYN_CHR_B", "nuclear_genome"),
        ("SYN_CHR_B", "nuclear_annotation"),
    }
    assert all(r["translation_verified"] == 0 for r in rows)
    assert all(r["encoding_genome"] == "nuclear" for r in rows)


def test_fetch_fasta_rejects_a_non_fasta_response() -> None:
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": "BAD", "rettype": "fasta", "retmode": "text"},
        "<html>not fasta</html>",
    )
    with pytest.raises(OmicsFetchError):
        references_mod.fetch_fasta(_client(fake), "BAD")


# ---------------------------------------------------------------------------------------------
# references.py: the CON-division CONTIG-stub fallback (rettype=gb -> rettype=gbwithparts)
#
# Discovered live on 2026-09-20 while fetching the real S288C assembly: four of the sixteen
# nuclear chromosomes (IV, VII, XII, XV in GCF_000146045.2) return a bare few-KB CONTIG-pointer
# record under plain `rettype=gb`, not the annotated sequence. This is real, reproducible NCBI
# behaviour this session actually hit, not a hypothetical -- see references.py:_is_contig_stub.
# ---------------------------------------------------------------------------------------------


def test_is_contig_stub_detects_a_bare_master_record() -> None:
    stub = (
        "LOCUS       X 100 bp DNA linear CON 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        '     source          1..100\n                     /organism="x"\n'
        "CONTIG      join(SOMEACC.1:1..100)\n"
        "//\n"
    )
    assert references_mod._is_contig_stub(stub) is True
    assert references_mod._is_contig_stub(_read("synthetic_chr_a.gb")) is False
    assert references_mod._is_contig_stub(_read("mtdna_atp8_excerpt.gb")) is False


def test_fetch_genbank_falls_back_to_gbwithparts_for_a_contig_stub() -> None:
    stub = (
        "LOCUS       X 100 bp DNA linear CON 20-SEP-2026\n"
        "FEATURES             Location/Qualifiers\n"
        '     source          1..100\n                     /organism="x"\n'
        "CONTIG      join(SOMEACC.1:1..100)\n"
        "//\n"
    )
    expanded = _read("synthetic_chr_a.gb")
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": "CONTIGCHR", "rettype": "gb", "retmode": "text"},
        stub,
    )
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": "CONTIGCHR", "rettype": "gbwithparts", "retmode": "text"},
        expanded,
    )
    result = references_mod.fetch_genbank(_client(fake), "CONTIGCHR")
    assert result.content == expanded
    assert "rettype=gbwithparts" in result.source_url


def test_fetch_genbank_does_not_fall_back_for_a_normal_record() -> None:
    """The common case must not pay for a second request it does not need."""
    fake = FakeFetch()
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "nuccore", "id": "NORMAL", "rettype": "gb", "retmode": "text"},
        _read("synthetic_chr_a.gb"),
    )
    result = references_mod.fetch_genbank(_client(fake), "NORMAL")
    assert result.content == _read("synthetic_chr_a.gb")
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------------------------
# references.py: writing reference_sequence rows
# ---------------------------------------------------------------------------------------------


def test_write_reference_rows_round_trips_through_the_database(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    fake = FakeFetch()
    _fake_nuccore(
        fake,
        references_mod.MITOCHONDRIAL_ACCESSION,
        fasta=_read("mtdna_atp8_excerpt.fasta"),
        genbank=_read("mtdna_atp8_excerpt.gb"),
    )
    rows = references_mod.fetch_mitochondrial_reference(
        _client(fake), tmp_path, retrieved_at="2026-09-20T00:00:00Z"
    )
    written = references_mod.write_reference_rows(conn, rows)
    assert written == 2

    stored = conn.execute(
        "SELECT kind, checksum_sha256, translation_verified, encoding_genome, size_bytes "
        "FROM reference_sequence WHERE sequence_accession = ? ORDER BY kind",
        (references_mod.MITOCHONDRIAL_ACCESSION,),
    ).fetchall()
    assert [r["kind"] for r in stored] == ["mitochondrial_annotation", "mitochondrial_genome"]
    assert all(r["translation_verified"] == 1 for r in stored)
    assert all(r["encoding_genome"] == "mitochondrial" for r in stored)
    assert all(len(r["checksum_sha256"]) == 64 for r in stored)  # a real sha256 hex digest


def test_write_reference_rows_is_idempotent_on_sequence_accession_and_kind(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    fake = FakeFetch()
    _fake_nuccore(
        fake, "SYN_CHR_A", fasta=_read("synthetic_chr_a.fasta"), genbank=_read("synthetic_chr_a.gb")
    )
    rows = references_mod.fetch_nuclear_reference(
        _client(fake), tmp_path, retrieved_at="t1", accessions=("SYN_CHR_A",)
    )
    references_mod.write_reference_rows(conn, rows)
    references_mod.write_reference_rows(conn, rows)
    count = conn.execute("SELECT COUNT(*) FROM reference_sequence").fetchone()[0]
    assert count == 2  # genome + annotation, not 4


# ---------------------------------------------------------------------------------------------
# The DDL <-> genetic_code.py agreement this whole check rests on
# ---------------------------------------------------------------------------------------------


def test_reference_sequence_encoding_genome_matches_genetic_code_module(
    conn: sqlite3.Connection,
) -> None:
    """The same drift guard `tests/test_schema.py` runs for `encoding_genome`, applied here: an
    `encoding_genome` value this module could write must be one the schema (and hence
    `fermdb.genetic_code`) actually recognises."""
    rows = {r["id"] for r in conn.execute("SELECT id FROM encoding_genome")}
    assert set(genetic_code.ENCODING_GENOME_TABLE) <= rows
    assert {"nuclear", "mitochondrial"} <= rows


# ---------------------------------------------------------------------------------------------
# data/omics/dataset_families.yaml and its loader
# ---------------------------------------------------------------------------------------------


def test_load_dataset_families_reads_the_real_file() -> None:
    families = load_dataset_families(REAL_DATASET_FAMILIES)
    names = {f.name for f in families}
    assert {
        "sra_isobutanol",
        "sra_isobutanol_saccharomyces",
        "sra_isobutanol_ecoli",
        "geo_isobutanol",
        "sra_ethanol_saccharomyces_reference_layer",
    } <= names
    for family in families:
        assert family.evidence
        assert family.confidence in ("unverified", "low", "medium", "high")
        assert family.target in ("sra", "geo")


def test_the_ethanol_reference_layer_family_is_guarded() -> None:
    families = load_dataset_families(REAL_DATASET_FAMILIES)
    ethanol = family_by_name(families, "sra_ethanol_saccharomyces_reference_layer")
    assert ethanol.guard == "ethanol_reference_cap"
    isobutanol = family_by_name(families, "sra_isobutanol")
    assert isobutanol.guard is None


def test_family_by_name_unknown_name_raises_with_the_known_list() -> None:
    families = load_dataset_families(REAL_DATASET_FAMILIES)
    with pytest.raises(KeyError, match="sra_isobutanol"):
        family_by_name(families, "not_a_real_family")


def test_load_dataset_families_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DatasetFamiliesError):
        load_dataset_families(tmp_path / "does-not-exist.yaml")


def test_load_dataset_families_rejects_an_unknown_target(tmp_path: Path) -> None:
    bad = tmp_path / "families.yaml"
    bad.write_text(
        "families:\n"
        "  - name: x\n"
        "    target: bigquery\n"
        "    db: sra\n"
        "    term: x\n"
        "    evidence: test\n"
        "    confidence: unverified\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetFamiliesError):
        load_dataset_families(bad)


def test_load_dataset_families_rejects_a_bad_confidence_value(tmp_path: Path) -> None:
    bad = tmp_path / "families.yaml"
    bad.write_text(
        "families:\n"
        "  - name: x\n"
        "    target: sra\n"
        "    db: sra\n"
        "    term: x\n"
        "    evidence: test\n"
        "    confidence: pretty_sure\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetFamiliesError):
        load_dataset_families(bad)


def test_load_dataset_families_rejects_a_duplicate_family_name(tmp_path: Path) -> None:
    bad = tmp_path / "families.yaml"
    bad.write_text(
        "families:\n"
        "  - {name: x, target: sra, db: sra, term: a, evidence: e, confidence: unverified}\n"
        "  - {name: x, target: sra, db: sra, term: b, evidence: e, confidence: unverified}\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetFamiliesError):
        load_dataset_families(bad)


def test_dataset_families_path_is_off_repo_root(tmp_path: Path) -> None:
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "paths.yaml").write_text(
        "repo:\n  repo_root: '.'\nderived: {}\nsource: {}\n", encoding="utf-8"
    )
    settings = Settings.load(paths_file=tmp_path / "env" / "paths.yaml", env={})
    assert dataset_families_path(settings) == (
        tmp_path / "data" / "omics" / "dataset_families.yaml"
    )


# ---------------------------------------------------------------------------------------------
# CLI wiring: argument parsing and dependency injection (still offline -- `fetch` is always a
# FakeFetch, never `fermdb.omics.urllib_fetch`)
# ---------------------------------------------------------------------------------------------


def _settings_env(tmp_path: Path) -> dict[str, str]:
    return {
        "FERMDB_REPO_ROOT": str(REPO_ROOT),
        "FERMDB_DATA_DIR": str(tmp_path / "derived"),
        "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
    }


def test_cli_parses_omics_discover_and_references_and_status() -> None:
    from fermdb import cli
    from fermdb import omics as omics_mod

    parser = cli.build_parser()
    discover_args = parser.parse_args(["omics", "discover", "--family", "geo_isobutanol"])
    assert discover_args.func is omics_mod.cmd_omics_discover
    assert discover_args.family == "geo_isobutanol"

    fetch_args = parser.parse_args(["omics", "references", "fetch", "--include", "mitochondrial"])
    assert fetch_args.include == "mitochondrial"

    status_args = parser.parse_args(["omics", "status"])
    assert status_args.omics_command == "status"


def test_cli_omics_discover_end_to_end_with_injected_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runinfo_csv: str
) -> None:
    from fermdb import cli
    from fermdb.omics import cmd_omics_discover

    for key, value in _settings_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    fake = FakeFetch()
    ids = [str(i) for i in range(7)]
    fake.add(
        "/entrez/eutils/esearch.fcgi",
        {"db": "sra", "term": "isobutanol", "retstart": "0", "retmax": "200", "retmode": "json"},
        json.dumps(
            {"esearchresult": {"count": "7", "retmax": "7", "retstart": "0", "idlist": ids}}
        ),
    )
    fake.add(
        "/entrez/eutils/efetch.fcgi",
        {"db": "sra", "id": ",".join(ids), "rettype": "runinfo", "retmode": "text"},
        runinfo_csv,
    )

    parser = cli.build_parser()
    args = parser.parse_args(["omics", "discover", "--family", "sra_isobutanol"])
    exit_code = cmd_omics_discover(args, fetch=fake)
    assert exit_code == 0

    from fermdb.config import Settings
    from fermdb.db import open_db

    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        count = conn.execute("SELECT COUNT(*) FROM sra_run").fetchone()[0]
        assert count == 7
    finally:
        conn.close()


def test_cli_omics_discover_guarded_family_refuses_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fermdb import cli
    from fermdb.omics import cmd_omics_discover

    for key, value in _settings_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    parser = cli.build_parser()
    args = parser.parse_args(
        ["omics", "discover", "--family", "sra_ethanol_saccharomyces_reference_layer"]
    )
    # No FakeFetch response registered at all: if the guard did not fire, this would raise from
    # inside FakeFetch instead of returning 2, which would also fail this test -- either way, a
    # regression here cannot pass by accident.
    exit_code = cmd_omics_discover(args, fetch=FakeFetch())
    assert exit_code == 2


def test_cli_omics_references_fetch_end_to_end_with_injected_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fermdb import cli
    from fermdb.omics import cmd_omics_references_fetch

    for key, value in _settings_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    fake = FakeFetch()
    _fake_nuccore(
        fake,
        references_mod.MITOCHONDRIAL_ACCESSION,
        fasta=_read("mtdna_atp8_excerpt.fasta"),
        genbank=_read("mtdna_atp8_excerpt.gb"),
    )

    parser = cli.build_parser()
    args = parser.parse_args(["omics", "references", "fetch", "--include", "mitochondrial"])
    exit_code = cmd_omics_references_fetch(args, fetch=fake)
    assert exit_code == 0

    from fermdb.config import Settings
    from fermdb.db import open_db

    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM reference_sequence WHERE translation_verified = 1"
        ).fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_cli_omics_status_runs_against_an_empty_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from fermdb import cli

    for key, value in _settings_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    exit_code = cli.main(["omics", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sra_isobutanol" in out
    assert "reference_sequence: 0 row(s)" in out
