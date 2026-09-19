"""Tests for `fermdb.annotate` (functional annotation: sources.py + importers.py).

Everything here runs offline. `FakeTransport` below is the only `Transport` any test uses, and it
raises if asked for a URL it has no canned response for -- the same "an accidental network touch
must be caught, not silently pass" discipline `tests/test_omics.py`'s `FakeFetch` documents, applied
to this package's `Transport` protocol. No test in this file may reach `UrllibTransport`.

Fixtures under `tests/fixtures/annotate/` are hand-built to match this session's best-effort,
unverified reading of each source's response shape (see `data/annotation/annotation_sources.yaml`
for the per-source caveat) -- they are illustrative test data, not captured live responses.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fermdb.annotate import (
    KNOWN_SOURCE_IDS,
    AnnotationImportError,
    AnnotationSourcesError,
    FeSClusterAnnotation,
    GeneAnnotationRow,
    PresequencePrediction,
    UnknownGoEvidenceCodeError,
    annotate_fe_s_cluster,
    annotation_sources_path,
    fetch_kegg_entry,
    fetch_sgd_go,
    find_gene_annotation,
    go_evidence_category,
    load_annotation_sources,
    parse_generic_term_list,
    parse_kegg_flat_entry,
    parse_sgd_go_response,
    parse_uniprot_entry,
    parse_uniprot_goa_response,
    predict_mitochondrial_presequence,
    recommended_confidence_for_go_evidence,
    resolve_source_url,
    source_by_id,
    sources_for_organism,
    write_gene_annotation,
    write_gene_annotations,
)
from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db

FIXTURES = Path(__file__).parent / "fixtures" / "annotate"
REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_ANNOTATION_SOURCES = REPO_ROOT / "data" / "annotation" / "annotation_sources.yaml"


def _read_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _read_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeTransport:
    """A `Transport` that serves canned bodies keyed by exact URL; raises on an uncanned one."""

    def __init__(self) -> None:
        self._json: dict[str, Any] = {}
        self._text: dict[str, str] = {}
        self.calls: list[str] = []

    def add_json(self, url: str, payload: Any) -> None:
        self._json[url] = payload

    def add_text(self, url: str, text: str) -> None:
        self._text[url] = text

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        if url not in self._json:
            raise AssertionError(f"FakeTransport has no canned JSON for {url}")
        return self._json[url]

    def get_text(self, url: str) -> str:
        self.calls.append(url)
        if url not in self._text:
            raise AssertionError(f"FakeTransport has no canned text for {url}")
        return self._text[url]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


def _seed_gene_group(conn: sqlite3.Connection, gene_group_id: str = "YAA:GG:ilv3") -> None:
    conn.execute(
        "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
        "membership_method, zone, evidence, confidence) "
        "VALUES (?, 'sgd_systematic', 'YLR355C', 'ILV3', 'species', 'anchor', 'R', "
        "'test fixture', 'low')",
        (gene_group_id,),
    )
    conn.commit()


def _row(**overrides: Any) -> GeneAnnotationRow:
    defaults: dict[str, Any] = {
        "gene_group_id": "YAA:GG:ilv3",
        "source": "sgd_go",
        "term_id": "GO:0004160",
        "term_label": "dihydroxy-acid dehydratase activity",
        "term_namespace": "molecular_function",
        "evidence_code": "IDA",
        "reaction_id": None,
        "pathway_id": None,
        "source_url": None,
        "source_version": None,
        "retrieved_at": "2026-09-20T00:00:00Z",
        "zone": "R",
        "evidence": "test fixture",
        "confidence": "high",
    }
    defaults.update(overrides)
    return GeneAnnotationRow(**defaults)


# ---------------------------------------------------------------------------------------------
# data/annotation/annotation_sources.yaml and its loader
# ---------------------------------------------------------------------------------------------


def test_load_annotation_sources_reads_the_real_file() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    ids = {s.id for s in sources}
    assert ids == set(KNOWN_SOURCE_IDS)
    for source in sources:
        assert source.organisms
        assert source.confidence in ("unverified", "low", "medium", "high")
        assert source.evidence
        assert isinstance(source.redistributable, bool)


def test_kegg_tcdb_and_yeastract_are_marked_not_redistributable() -> None:
    """The licence-honesty requirement this build is explicit about."""
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    for source_id in ("kegg", "tcdb", "yeastract"):
        assert source_by_id(sources, source_id).redistributable is False


def test_sgd_and_yeastract_are_scoped_to_yeast_only() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    for source_id in ("sgd_go", "sgd_phenotype", "yeastract"):
        assert source_by_id(sources, source_id).organisms == ("saccharomyces_cerevisiae",)


def test_source_by_id_unknown_raises_with_the_known_list() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    with pytest.raises(KeyError, match="sgd_go"):
        source_by_id(sources, "not_a_real_source")


def test_sources_for_organism_includes_broad_sources() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    bacterial = sources_for_organism(sources, "escherichia_coli")
    ids = {s.id for s in bacterial}
    assert "uniprot_goa" in ids  # explicitly scoped to escherichia_coli
    assert "kegg" in ids  # 'broad'
    assert "sgd_go" not in ids  # yeast-only, not broad


def test_resolve_source_url_fills_the_pattern() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    kegg = source_by_id(sources, "kegg")
    assert resolve_source_url(kegg, kegg_id="K01687") == "https://rest.kegg.org/get/K01687"


def test_resolve_source_url_missing_field_raises() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    kegg = source_by_id(sources, "kegg")
    with pytest.raises(AnnotationSourcesError):
        resolve_source_url(kegg)


def test_load_annotation_sources_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(AnnotationSourcesError):
        load_annotation_sources(tmp_path / "does-not-exist.yaml")


def test_load_annotation_sources_rejects_an_unknown_covers_value(tmp_path: Path) -> None:
    bad = tmp_path / "sources.yaml"
    bad.write_text(
        "sources:\n"
        "  - id: x\n"
        "    name: X\n"
        "    organisms: [broad]\n"
        "    covers: astrology\n"
        "    url_pattern: 'http://example.org/{id}'\n"
        "    license: none\n"
        "    redistributable: true\n"
        "    update_cadence: unknown\n"
        "    evidence: test\n"
        "    confidence: unverified\n",
        encoding="utf-8",
    )
    with pytest.raises(AnnotationSourcesError):
        load_annotation_sources(bad)


def test_load_annotation_sources_rejects_a_non_bool_redistributable(tmp_path: Path) -> None:
    bad = tmp_path / "sources.yaml"
    bad.write_text(
        "sources:\n"
        "  - id: x\n"
        "    name: X\n"
        "    organisms: [broad]\n"
        "    covers: go_term\n"
        "    url_pattern: 'http://example.org/{id}'\n"
        "    license: none\n"
        "    redistributable: maybe\n"
        "    update_cadence: unknown\n"
        "    evidence: test\n"
        "    confidence: unverified\n",
        encoding="utf-8",
    )
    with pytest.raises(AnnotationSourcesError):
        load_annotation_sources(bad)


def test_load_annotation_sources_rejects_a_duplicate_id(tmp_path: Path) -> None:
    bad = tmp_path / "sources.yaml"
    bad.write_text(
        "sources:\n"
        "  - {id: x, name: X, organisms: [broad], covers: go_term, "
        "url_pattern: 'http://e/{id}', license: none, redistributable: true, "
        "update_cadence: u, evidence: e, confidence: unverified}\n"
        "  - {id: x, name: Y, organisms: [broad], covers: go_term, "
        "url_pattern: 'http://e/{id}', license: none, redistributable: true, "
        "update_cadence: u, evidence: e, confidence: unverified}\n",
        encoding="utf-8",
    )
    with pytest.raises(AnnotationSourcesError):
        load_annotation_sources(bad)


def test_annotation_sources_path_is_off_repo_root(tmp_path: Path) -> None:
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "paths.yaml").write_text(
        "repo:\n  repo_root: '.'\nderived: {}\nsource: {}\n", encoding="utf-8"
    )
    settings = Settings.load(paths_file=tmp_path / "env" / "paths.yaml", env={})
    assert annotation_sources_path(settings) == (
        tmp_path / "data" / "annotation" / "annotation_sources.yaml"
    )


# ---------------------------------------------------------------------------------------------
# GO evidence codes -> confidence
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("IDA", "experimental"),
        ("EXP", "experimental"),
        ("HDA", "experimental"),
        ("IBA", "phylogenetic"),
        ("IEA", "computational"),
        ("ISS", "computational"),
        ("TAS", "author_statement"),
        ("NAS", "author_statement"),
        ("IC", "curator_statement"),
        ("ND", "curator_statement"),
    ],
)
def test_go_evidence_category(code: str, category: str) -> None:
    assert go_evidence_category(code) == category
    assert go_evidence_category(code.lower()) == category  # case-insensitive


def test_go_evidence_category_rejects_an_unknown_code() -> None:
    with pytest.raises(UnknownGoEvidenceCodeError):
        go_evidence_category("XYZ")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("IDA", "high"),  # direct experimental (the task's own worked example)
        ("IMP", "high"),
        ("IEA", "low"),  # computational (the task's own worked example)
        ("TAS", "medium"),  # traceable author statement
        ("NAS", "low"),  # NOT traceable -- weaker than TAS despite sharing GO's category
        ("IC", "medium"),
        ("ND", "unverified"),  # "no data available" is not a positive claim
    ],
)
def test_recommended_confidence_for_go_evidence(code: str, expected: str) -> None:
    assert recommended_confidence_for_go_evidence(code) == expected


def test_recommended_confidence_for_go_evidence_rejects_an_unknown_code() -> None:
    with pytest.raises(UnknownGoEvidenceCodeError):
        recommended_confidence_for_go_evidence("NOTACODE")


# ---------------------------------------------------------------------------------------------
# SGD GO (yeast) and UniProt-GOA (bacteria) parsers
# ---------------------------------------------------------------------------------------------


def test_parse_sgd_go_response_carries_evidence_code_and_recommended_confidence() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "sgd_go")
    payload = _read_json("sgd_go_ilv3.json")

    rows = parse_sgd_go_response(
        payload, gene_group_id="YAA:GG:ilv3", source=source, retrieved_at="2026-09-20T00:00:00Z"
    )

    by_term = {row.term_id: row for row in rows}
    assert set(by_term) == {"GO:0004160", "GO:0009082", "GO:0051536", "GO:0005739"}

    ida_row = by_term["GO:0004160"]
    assert ida_row.evidence_code == "IDA"
    assert ida_row.confidence == "high"
    assert ida_row.term_namespace == "molecular_function"
    assert ida_row.source == "sgd_go"
    assert ida_row.zone == "R"

    iea_row = by_term["GO:0051536"]
    assert iea_row.evidence_code == "IEA"
    assert iea_row.confidence == "low"  # computational, not flattened to the same value as IDA


def test_parse_sgd_go_response_rejects_a_non_list_payload() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "sgd_go")
    with pytest.raises(AnnotationImportError):
        parse_sgd_go_response(
            {"not": "a list"}, gene_group_id="x", source=source, retrieved_at="now"
        )


def test_parse_sgd_go_response_skips_entries_with_no_go_id() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "sgd_go")
    rows = parse_sgd_go_response(
        [{"go_term": "nothing useful here"}],
        gene_group_id="x",
        source=source,
        retrieved_at="now",
    )
    assert rows == []


def test_parse_uniprot_goa_response_from_quickgo_shape() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "uniprot_goa")
    payload = _read_json("uniprot_goa_ilvd.json")

    rows = parse_uniprot_goa_response(
        payload, gene_group_id="YAA:GG:ilvd", source=source, retrieved_at="2026-09-20T00:00:00Z"
    )

    assert len(rows) == 2
    by_term = {row.term_id: row for row in rows}
    assert by_term["GO:0004160"].confidence == "high"  # IDA
    assert by_term["GO:0009082"].confidence == "low"  # IEA
    assert all(row.source == "uniprot_goa" for row in rows)


def test_parse_uniprot_goa_response_rejects_a_missing_results_list() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "uniprot_goa")
    with pytest.raises(AnnotationImportError):
        parse_uniprot_goa_response({}, gene_group_id="x", source=source, retrieved_at="now")


# ---------------------------------------------------------------------------------------------
# KEGG flat-file parsing (identifiers + links only -- redistributable: false)
# ---------------------------------------------------------------------------------------------


def test_parse_kegg_flat_entry_produces_ko_ec_and_pathway_rows() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "kegg")
    text = _read_text("kegg_k01687.txt")

    rows = parse_kegg_flat_entry(
        text, gene_group_id="YAA:GG:ilv3", source=source, retrieved_at="2026-09-20T00:00:00Z"
    )

    by_namespace: dict[str, list[GeneAnnotationRow]] = {}
    for row in rows:
        by_namespace.setdefault(row.term_namespace or "", []).append(row)

    ko_rows = by_namespace["ko"]
    assert len(ko_rows) == 1
    assert ko_rows[0].term_id == "K01687"
    assert ko_rows[0].term_label == "ilvD, EDD"
    assert ko_rows[0].source == "kegg"

    ec_ids = {row.term_id for row in by_namespace["ec"]}
    assert ec_ids == {"EC:4.2.1.9", "EC:4.2.1.12"}

    pathway_ids = {row.term_id for row in by_namespace["pathway"]}
    assert pathway_ids == {"ko00290", "ko00030"}
    pathway_by_id = {row.term_id: row for row in by_namespace["pathway"]}
    assert pathway_by_id["ko00290"].term_label == "Valine, leucine and isoleucine biosynthesis"

    # Identifiers + links only: nothing stores the full multi-EC bracket or a reaction list.
    for row in rows:
        assert row.term_label is None or "[EC:" not in row.term_label


def test_parse_kegg_flat_entry_missing_entry_field_raises() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "kegg")
    with pytest.raises(AnnotationImportError):
        parse_kegg_flat_entry(
            "NAME        nothing\n///\n", gene_group_id="x", source=source, retrieved_at="now"
        )


def test_fetch_kegg_entry_uses_the_injected_transport() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "kegg")
    transport = FakeTransport()
    transport.add_text("https://rest.kegg.org/get/K01687", _read_text("kegg_k01687.txt"))

    rows = fetch_kegg_entry(transport, source, gene_group_id="YAA:GG:ilv3", kegg_id="K01687")

    assert transport.calls == ["https://rest.kegg.org/get/K01687"]
    assert any(row.term_id == "K01687" for row in rows)


# ---------------------------------------------------------------------------------------------
# UniProt cofactor / subcellular location
# ---------------------------------------------------------------------------------------------


def test_parse_uniprot_entry_extracts_cofactor_and_location_and_ignores_other_comments() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "uniprot")
    payload = _read_json("uniprot_ilv3.json")

    rows = parse_uniprot_entry(
        payload, gene_group_id="YAA:GG:ilv3", source=source, retrieved_at="2026-09-20T00:00:00Z"
    )

    by_namespace = {row.term_namespace: row for row in rows}
    assert set(by_namespace) == {"cofactor", "subcellular_location"}
    assert by_namespace["cofactor"].term_id == "CHEBI:49883"
    assert by_namespace["cofactor"].term_label == "[4Fe-4S] cluster"
    assert by_namespace["subcellular_location"].term_id == "Mitochondrion matrix"


def test_parse_uniprot_entry_with_no_comments_returns_nothing() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "uniprot")
    rows = parse_uniprot_entry({}, gene_group_id="x", source=source, retrieved_at="now")
    assert rows == []


# ---------------------------------------------------------------------------------------------
# Generic (id, label) term list -- pfam/interpro/tcdb/complex_portal/sgd_phenotype/yeastract
# ---------------------------------------------------------------------------------------------


def test_parse_generic_term_list_from_a_bare_list() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "interpro")
    payload = _read_json("interpro_ilv3.json")

    rows = parse_generic_term_list(
        payload,
        gene_group_id="YAA:GG:ilv3",
        source=source,
        retrieved_at="now",
        namespace="domain",
    )

    assert {row.term_id for row in rows} == {"IPR000581", "IPR004404"}
    assert all(row.term_namespace == "domain" for row in rows)
    assert all(row.confidence == "high" for row in rows)


def test_parse_generic_term_list_from_a_results_envelope_with_custom_keys() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "tcdb")
    payload = _read_json("tcdb_pdr5.json")

    rows = parse_generic_term_list(
        payload,
        gene_group_id="YAA:GG:pdr5",
        source=source,
        retrieved_at="now",
        id_key="tcid",
        label_key="family",
        namespace="transporter_family",
    )

    assert len(rows) == 1
    assert rows[0].term_id == "3.A.1.205.1"
    assert rows[0].term_label == "ATP-binding Cassette (ABC) Superfamily"
    assert rows[0].source == "tcdb"


def test_parse_generic_term_list_rejects_an_unrecognized_shape() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "interpro")
    with pytest.raises(AnnotationImportError):
        parse_generic_term_list(
            "not a list or a mapping", gene_group_id="x", source=source, retrieved_at="now"
        )


def test_fetch_sgd_go_uses_the_injected_transport() -> None:
    sources = load_annotation_sources(REAL_ANNOTATION_SOURCES)
    source = source_by_id(sources, "sgd_go")
    transport = FakeTransport()
    url = "https://www.yeastgenome.org/backend/locus/YLR355C/go_details"
    transport.add_json(url, _read_json("sgd_go_ilv3.json"))

    rows = fetch_sgd_go(transport, source, gene_group_id="YAA:GG:ilv3", systematic_name="YLR355C")

    assert transport.calls == [url]
    assert len(rows) == 4


# ---------------------------------------------------------------------------------------------
# gene_annotation: schema constraints and the idempotent writer
# ---------------------------------------------------------------------------------------------


def test_source_outside_the_known_set_is_rejected(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(conn, _row(source="not_a_real_source"))


def test_every_known_source_id_is_storable(conn: sqlite3.Connection) -> None:
    """sources.py's KNOWN_SOURCE_IDS and schema.sql's CHECK must agree -- if they drift, exactly
    one of these two independently-written lists would reject a source id the other accepts."""
    _seed_gene_group(conn)
    for index, source_id in enumerate(sorted(KNOWN_SOURCE_IDS)):
        write_gene_annotation(conn, _row(source=source_id, term_id=f"T{index}", evidence_code=None))


def test_confidence_outside_the_closed_set_is_rejected(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(conn, _row(confidence="pretty_sure"))


def test_zone_must_be_one_of_the_three(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(conn, _row(zone="X"))


def test_evidence_code_cannot_be_set_for_a_non_go_source(conn: sqlite3.Connection) -> None:
    """The structural half of 'GO evidence codes only': a non-GO source cannot smuggle one in."""
    _seed_gene_group(conn)
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(conn, _row(source="kegg", term_id="K01687", evidence_code="IDA"))
    # The same row without an evidence_code is storable.
    write_gene_annotation(conn, _row(source="kegg", term_id="K01687", evidence_code=None))


def test_a_nonexistent_gene_group_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(conn, _row(gene_group_id="YAA:GG:does-not-exist"))


def test_write_gene_annotation_inserts_then_updates_in_place(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    first_id = write_gene_annotation(conn, _row(term_label="first label"))
    second_id = write_gene_annotation(conn, _row(term_label="updated label"))

    assert first_id == second_id  # same natural key -> same row, not a duplicate
    count = conn.execute("SELECT COUNT(*) FROM gene_annotation").fetchone()[0]
    assert count == 1
    stored_label = conn.execute(
        "SELECT term_label FROM gene_annotation WHERE id = ?", (first_id,)
    ).fetchone()[0]
    assert stored_label == "updated label"


def test_two_evidence_codes_for_the_same_term_are_two_distinct_rows(
    conn: sqlite3.Connection,
) -> None:
    """A GO term supported by both an IDA and an IEA record is two facts, not one -- collapsing
    them would silently discard the stronger evidence code."""
    _seed_gene_group(conn)
    write_gene_annotation(conn, _row(evidence_code="IDA", confidence="high"))
    write_gene_annotation(conn, _row(evidence_code="IEA", confidence="low"))
    count = conn.execute(
        "SELECT COUNT(*) FROM gene_annotation WHERE term_id = 'GO:0004160'"
    ).fetchone()[0]
    assert count == 2


def test_find_gene_annotation_matches_a_null_evidence_code(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    write_gene_annotation(conn, _row(source="interpro", term_id="IPR000581", evidence_code=None))
    found = find_gene_annotation(
        conn,
        gene_group_id="YAA:GG:ilv3",
        source="interpro",
        term_id="IPR000581",
        evidence_code=None,
    )
    assert found is not None


def test_the_dedup_unique_index_rejects_a_raw_duplicate_insert(conn: sqlite3.Connection) -> None:
    """Guards `write_gene_annotation`'s own find-then-write logic: even a caller that bypasses it
    and inserts directly cannot create two rows for the same natural key."""
    _seed_gene_group(conn)
    columns = "id, gene_group_id, source, term_id, evidence_code, zone, evidence, confidence"
    conn.execute(
        f"INSERT INTO gene_annotation ({columns}) "
        "VALUES ('YAA:ANNOT:a', 'YAA:GG:ilv3', 'interpro', 'IPR000581', NULL, 'R', 'test', 'high')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            f"INSERT INTO gene_annotation ({columns}) "
            "VALUES ('YAA:ANNOT:b', 'YAA:GG:ilv3', 'interpro', 'IPR000581', NULL, 'R', 'test', "
            "'high')"
        )


def test_reaction_id_and_pathway_id_are_nullable_but_fk_checked(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    # NULL (the overwhelming majority of rows) is fine.
    write_gene_annotation(conn, _row(reaction_id=None, pathway_id=None))
    # A reaction_id naming a row that does not exist is not.
    with pytest.raises(sqlite3.IntegrityError):
        write_gene_annotation(
            conn, _row(term_id="GO:other", reaction_id="YAA:REACT:does-not-exist")
        )


def test_write_gene_annotations_batch_is_idempotent(conn: sqlite3.Connection) -> None:
    _seed_gene_group(conn)
    rows = [
        _row(term_id="GO:0004160", evidence_code="IDA"),
        _row(term_id="GO:0009082", evidence_code="IMP"),
    ]
    first_count = write_gene_annotations(conn, rows)
    second_count = write_gene_annotations(conn, rows)
    assert (first_count, second_count) == (2, 2)  # rows written per call, not rows accumulated
    stored = conn.execute("SELECT COUNT(*) FROM gene_annotation").fetchone()[0]
    assert stored == 2


# ---------------------------------------------------------------------------------------------
# Predictor TODO stubs: the interface exists and is usable; the computation is not implemented.
# ---------------------------------------------------------------------------------------------


def test_presequence_prediction_dataclass_is_constructible() -> None:
    prediction = PresequencePrediction(
        gene_group_id="YAA:GG:ilv3",
        is_mitochondrial_presequence=True,
        cleavage_site=32,
        score=0.91,
        method="targetp2",
        method_version="2.0",
    )
    assert prediction.cleavage_site == 32


def test_predict_mitochondrial_presequence_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        predict_mitochondrial_presequence("MSTRINGOFAMINOACIDS", gene_group_id="YAA:GG:ilv3")


def test_fes_cluster_annotation_dataclass_is_constructible() -> None:
    annotation = FeSClusterAnnotation(
        gene_group_id="YAA:GG:ilv3",
        has_fe_s_cluster=True,
        cluster_type="[4Fe-4S]",
        maturation_pathway="cytosolic_cia",
        method="curated_seed_list",
        method_version="0",
    )
    assert annotation.cluster_type == "[4Fe-4S]"


def test_annotate_fe_s_cluster_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        annotate_fe_s_cluster("YAA:GG:ilv3")
