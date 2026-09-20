"""Tests for `fermdb.annotate.ontology`.

Offline throughout: the fixture is a real UniProt response for ADH3, trimmed to a few
cross-references but structurally faithful. A test that needs the internet is a broken test.

The properties that matter are about what must NOT happen: a gene with no reviewed entry must
produce no rows rather than borrowed ones, and `evidence_code` must stay NULL for sources that
have no such concept rather than being filled with something plausible.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from fermdb.annotate import ontology as O
from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "annotate"

ADH3 = json.loads((FIXTURES / "uniprot_adh3.json").read_text(encoding="utf-8"))
EMPTY = json.loads((FIXTURES / "uniprot_empty.json").read_text(encoding="utf-8"))


class FakeTransport:
    """Returns a recorded payload and records every URL it was asked for."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        return self.payload


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


# -------------------------------------------------------------------------------------- parsing


def test_go_terms_carry_their_aspect_and_evidence_code() -> None:
    annotations = O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")
    go = [a for a in annotations if a.source == "uniprot_goa"]
    assert go, "the fixture has GO cross-references"
    matrix = next(a for a in go if a.term_id == "GO:0005759")
    assert matrix.term_label == "mitochondrial matrix"
    assert matrix.term_namespace == "cellular_component"
    # IDA: inferred from direct assay. The code is the part before the source, not the whole
    # "IDA:SGD" string — which is what makes it comparable across entries.
    assert matrix.evidence_code == "IDA"


def test_uniprot_independently_places_adh3_in_the_matrix() -> None:
    """A cross-check worth keeping: the DUET architecture rests on Adh3 acting in the matrix, and
    this is an experimental GO annotation saying so, from a source that knows nothing about this
    project's design documents."""
    annotations = O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")
    terms = {a.term_id: a for a in annotations}
    assert "GO:0005759" in terms
    assert terms["GO:0005759"].evidence_code in {"IDA", "EXP", "HDA", "IBA"}


def test_domains_have_no_evidence_code_because_the_concept_does_not_exist() -> None:
    """A structural absence, not an unknown. Pfam has no notion of a GO evidence code, so NULL is
    the right value and filling it with anything would invent a fact."""
    annotations = O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")
    domains = [a for a in annotations if a.term_namespace == "domain"]
    assert domains
    assert all(a.evidence_code is None for a in domains)
    assert {a.source for a in domains} <= {"pfam", "interpro"}


def test_the_ec_number_is_captured() -> None:
    annotations = O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")
    ec = [a for a in annotations if a.term_namespace == "ec"]
    assert [a.term_id for a in ec] == ["EC:1.1.1.1"]


def test_a_gene_with_no_reviewed_entry_yields_nothing_rather_than_a_guess() -> None:
    """Not a homolog's annotations, not an empty placeholder row. Nothing — and the gap is
    reported, because an annotation transferred by homology is a different claim from one
    recorded for this protein and they must not share a column."""
    assert O.parse_uniprot(EMPTY, "NOTAGENE", "http://example.invalid") == []


def test_a_malformed_response_raises_rather_than_returning_empty() -> None:
    """An empty result and an unusable response mean different things: one is 'UniProt has no
    reviewed entry', the other is 'something is wrong'."""
    with pytest.raises(O.AnnotationError, match="not an object"):
        O.parse_uniprot(["unexpected"], "ADH3", "http://example.invalid")


# --------------------------------------------------------------------------- query construction


def test_the_query_pins_the_organism_and_demands_a_reviewed_entry(settings: Settings) -> None:
    """Without the taxon pin a gene symbol can match a homolog in another yeast; without
    `reviewed:true` it can match an unreviewed TrEMBL entry."""
    transport = FakeTransport(ADH3)
    O.fetch_all(["ADH3"], settings, transport=transport, delay_s=0)
    url = transport.calls[0]
    assert O.YEAST_TAXON in url
    assert "reviewed%3Atrue" in url or "reviewed:true" in url
    assert "gene_exact" in url


# ------------------------------------------------------------------------- caching and resume


def test_a_cached_gene_costs_no_request(settings: Settings) -> None:
    transport = FakeTransport(ADH3)
    O.fetch_all(["ADH3"], settings, transport=transport, delay_s=0)
    assert len(transport.calls) == 1

    again = FakeTransport(ADH3)
    result = O.fetch_all(["ADH3"], settings, transport=again, delay_s=0)
    assert again.calls == [], "the second run must read the cache, not the network"
    assert result["ADH3"], "and must still produce the annotations"


def test_the_cache_is_written_before_parsing(settings: Settings) -> None:
    """So the bytes a row is traced to are the bytes that were received, even if parsing later
    changes or fails."""
    O.fetch_all(["ADH3"], settings, transport=FakeTransport(ADH3), delay_s=0)
    cached = O.annotations_dir(settings) / "ADH3.json"
    assert cached.is_file()
    assert json.loads(cached.read_text(encoding="utf-8")) == ADH3


# ------------------------------------------------------------------------------------ storage


def _conn_with_gene() -> sqlite3.Connection:
    connection = open_db(IN_MEMORY)
    connection.execute(
        "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
        "membership_method, zone, evidence, confidence) "
        "VALUES ('YAA:GG:ymr083w','sgd_systematic','YMR083W','ADH3','species','anchor','H','t',"
        "'high')"
    )
    connection.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc','S. cerevisiae','R','t','high')"
    )
    connection.execute(
        "INSERT INTO gene (id, organism_id, assembly_accession, systematic_name, standard_name, "
        "gene_group_id, zone, evidence, confidence) VALUES ('YAA:GENE:y','YAA:ORG:sc',"
        "'GCF_000146045.2','YMR083W','ADH3','YAA:GG:ymr083w','R','t','high')"
    )
    return connection


def test_annotations_are_stored_zone_r_against_the_gene_group() -> None:
    """Zone R: an annotation row is what a source reported, not something this atlas derived."""
    connection = _conn_with_gene()
    try:
        annotations = {"ADH3": O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")}
        counts = O.write_annotations(
            connection, annotations, retrieved_at="2026-09-20T00:00:00+00:00"
        )
        assert counts["gene_annotation"] == len(annotations["ADH3"])
        rows = connection.execute(
            "SELECT zone, gene_group_id, source_url, retrieved_at FROM gene_annotation"
        ).fetchall()
        assert all(row["zone"] == "R" for row in rows)
        assert all(row["gene_group_id"] == "YAA:GG:ymr083w" for row in rows)
        assert all(row["source_url"] and row["retrieved_at"] for row in rows)
    finally:
        connection.close()


def test_writing_is_idempotent() -> None:
    connection = _conn_with_gene()
    try:
        annotations = {"ADH3": O.parse_uniprot(ADH3, "ADH3", "http://example.invalid")}
        O.write_annotations(connection, annotations, retrieved_at="2026-09-20T00:00:00+00:00")
        O.write_annotations(connection, annotations, retrieved_at="2026-09-21T00:00:00+00:00")
        count = connection.execute("SELECT COUNT(*) FROM gene_annotation").fetchone()[0]
        assert count == len(annotations["ADH3"])
    finally:
        connection.close()


def test_an_annotation_for_an_unknown_gene_is_skipped_not_orphaned() -> None:
    """gene_annotation.gene_group_id is NOT NULL and a foreign key; a row with nothing to hang off
    cannot be stored, so it is skipped rather than attached to whatever is nearby."""
    connection = _conn_with_gene()
    try:
        annotations = {"NOTAGENE": O.parse_uniprot(ADH3, "NOTAGENE", "http://example.invalid")}
        counts = O.write_annotations(
            connection, annotations, retrieved_at="2026-09-20T00:00:00+00:00"
        )
        assert counts["gene_annotation"] == 0
    finally:
        connection.close()
