"""Tests for `fermdb.genomics.load_genes`.

Two properties carry the whole module and both are about what the loader does *not* do: a second
run must change nothing, and a curated row must come out of a bulk RefSeq load exactly as it went
in. Everything else is bookkeeping around those two.

Every test runs against `fermdb.db.IN_MEMORY`. Nothing here opens a path.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.genomics.gff3 import GeneRecord, iter_gene_records, parse_gene_records
from fermdb.genomics.load_genes import (
    GeneLoadError,
    GffSource,
    load_gene_records,
    load_gff3,
)
from fermdb.omics.genes import ORGANISM_ID, gene_group_id, gene_id, organism_row

FIXTURE = Path(__file__).parent / "fixtures" / "genomics" / "s288c.mini.gff3"
ASSEMBLY = "GCF_000146045.2"

SOURCE = GffSource(
    assembly_accession=ASSEMBLY,
    file_name="s288c.mini.gff3",
    sha256="0" * 64,
)

#: The BDH1 row as the atlas actually holds it: coordinates from the transcript FASTA, an
#: evidence sentence naming that FASTA and its digest, and a gene_group anchor other tables point
#: at. Copied field for field from a read-only copy of the live database, so "a curated row
#: survives" is a claim about a real row rather than about a plausible-looking one.
CURATED_BDH1: dict[str, Any] = {
    "id": "YAA:GENE:gcf-000146045-2-yal060w",
    "organism_id": ORGANISM_ID,
    "assembly_accession": ASSEMBLY,
    "systematic_name": "YAL060W",
    "standard_name": "BDH1",
    "gene_group_id": "YAA:GG:yal060w",
    "start_pos": 35154,
    "end_pos": 36303,
    "strand": 1,
    "zone": "R",
    "evidence": (
        "[locus_tag=YAL060W] [gene=BDH1] [db_xref=GeneID:851239] "
        "[product=(R,R)-butanediol dehydrogenase] on NC_001133.9 (nuclear-encoded); RefSeq "
        "rna_from_genomic FASTA for assembly GCF_000146045.2, parsed from s288c.transcripts."
        "fna.gz (sha256 f783b29bd4220d9ee5665f303f2bd3bf33c8f0cab9444b2437ed2c8fe0c62900)"
    ),
    "confidence": "high",
}

CURATED_GROUP: dict[str, Any] = {
    "id": "YAA:GG:yal060w",
    "anchor_namespace": "sgd_systematic",
    "anchor_id": "YAL060W",
    "standard_name": "BDH1",
    "scope": "species",
    "membership_method": "anchor",
    "zone": "H",
    "evidence": "anchored on the S288C systematic name YAL060W; RefSeq rna_from_genomic FASTA",
    "confidence": "high",
}


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = open_db(IN_MEMORY)
    organism = organism_row()
    connection.execute(
        "INSERT INTO organism (id, ncbi_taxid, name, rank, zone, evidence, confidence) "
        "VALUES (:id, :ncbi_taxid, :name, :rank, :zone, :evidence, :confidence)",
        organism,
    )
    connection.commit()
    yield connection
    connection.close()


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(f":{name}" for name in row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", row)
    conn.commit()


def _seed_curated(conn: sqlite3.Connection) -> None:
    _insert(conn, "gene_group", CURATED_GROUP)
    _insert(conn, "gene", CURATED_BDH1)


def _load(conn: sqlite3.Connection) -> Any:
    return load_gene_records(
        conn, iter_gene_records(FIXTURE), source=SOURCE, organism_id=ORGANISM_ID
    )


def _parsed(lines: list[str]) -> Iterator[GeneRecord]:
    return parse_gene_records(lines)


def _row(conn: sqlite3.Connection, table: str, key: str) -> dict[str, Any]:
    cursor = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (key,))
    found = cursor.fetchone()
    assert found is not None, f"{table} row {key} is missing"
    return {column[0]: value for column, value in zip(cursor.description, found, strict=True)}


# ------------------------------------------------------------------------------ a plain load


def test_every_gene_in_the_file_lands(conn: sqlite3.Connection) -> None:
    report = _load(conn)
    assert report.inserted == 14
    assert report.skipped == ()
    assert conn.execute("SELECT COUNT(*) FROM gene").fetchone()[0] == 14


def test_ids_follow_the_convention_the_curated_rows_already_use(conn: sqlite3.Connection) -> None:
    """The id shape is copied from real rows, not assumed: `YAA:GENE:gcf-000146045-2-ymr303c` is
    what the atlas holds for ADH2 today, and the loader reuses `omics.genes.gene_id` so there is
    one authority for it rather than two that can drift."""
    _load(conn)
    assert gene_id("YAL060W", ASSEMBLY) == "YAA:GENE:gcf-000146045-2-yal060w"
    assert gene_group_id("YAL060W") == "YAA:GG:yal060w"
    assert _row(conn, "gene", "YAA:GENE:gcf-000146045-2-yal060w")["standard_name"] == "BDH1"


def test_the_new_columns_are_filled(conn: sqlite3.Connection) -> None:
    _load(conn)
    ecm31 = _row(conn, "gene", gene_id("YBR176W", ASSEMBLY))
    assert ecm31["seqid"] == "NC_001134.8"
    assert ecm31["biotype"] == "protein_coding"
    assert ecm31["locus_tag"] == "YBR176W"
    assert ecm31["description"] == "3-methyl-2-oxobutanoate hydroxymethyltransferase"


def test_coordinates_go_in_half_open(conn: sqlite3.Connection) -> None:
    _load(conn)
    bdh1 = _row(conn, "gene", gene_id("YAL060W", ASSEMBLY))
    assert (bdh1["start_pos"], bdh1["end_pos"]) == (35154, 36303)
    assert bdh1["end_pos"] - bdh1["start_pos"] == 1149


def test_a_mitochondrial_gene_is_findable_by_its_sequence(conn: sqlite3.Connection) -> None:
    """The query the whole `seqid` column exists for."""
    _load(conn)
    mito = [
        (str(row[0]), row[1])
        for row in conn.execute(
            "SELECT locus_tag, standard_name FROM gene WHERE assembly_accession = ? "
            "AND seqid = ? ORDER BY start_pos",
            (ASSEMBLY, "NC_001224.1"),
        )
    ]
    assert mito == [
        ("tP(UGG)Q", None),  # no gene= in RefSeq, so no standard name
        ("Q0045", "COX1"),
        ("Q0140", "VAR1"),
        ("Q0158", "21S_RRNA"),
    ]


def test_the_evidence_names_the_assembly_the_file_and_its_digest(
    conn: sqlite3.Connection,
) -> None:
    _load(conn)
    cox1 = _row(conn, "gene", gene_id("Q0045", ASSEMBLY))
    assert ASSEMBLY in cox1["evidence"]
    assert "s288c.mini.gff3" in cox1["evidence"]
    assert SOURCE.sha256 in cox1["evidence"]
    # The encoding genome, because it decides the translation table.
    assert "NC_001224.1 (mitochondrial-encoded)" in cox1["evidence"]
    assert cox1["zone"] == "R"


def test_an_unnamed_orf_gets_a_null_standard_name_not_its_own_locus_tag(
    conn: sqlite3.Connection,
) -> None:
    _load(conn)
    assert _row(conn, "gene", gene_id("YAL067W-A", ASSEMBLY))["standard_name"] is None


def test_gene_groups_are_anchored_like_the_curated_ones(conn: sqlite3.Connection) -> None:
    report = _load(conn)
    assert report.gene_groups_inserted == 14
    group = _row(conn, "gene_group", gene_group_id("YBR176W"))
    assert group["anchor_namespace"] == "sgd_systematic"
    assert group["anchor_id"] == "YBR176W"
    assert group["standard_name"] == "ECM31"
    assert group["membership_method"] == "anchor"
    assert group["scope"] == "species"
    assert group["zone"] == "H"


# ------------------------------------------------------------------------------ idempotency


def test_a_second_load_changes_nothing(conn: sqlite3.Connection) -> None:
    _load(conn)
    before = conn.execute("SELECT * FROM gene ORDER BY id").fetchall()
    report = _load(conn)
    after = conn.execute("SELECT * FROM gene ORDER BY id").fetchall()
    assert report.inserted == 0
    assert report.updated == 0
    assert report.unchanged == 14
    assert report.gene_groups_inserted == 0
    assert report.gene_groups_left_alone == 14
    assert after == before
    assert conn.execute("SELECT COUNT(*) FROM gene").fetchone()[0] == 14
    assert conn.execute("SELECT COUNT(*) FROM gene_group").fetchone()[0] == 14


def test_a_third_load_does_not_grow_the_evidence_string(conn: sqlite3.Connection) -> None:
    _seed_curated(conn)
    _load(conn)
    once = _row(conn, "gene", CURATED_BDH1["id"])["evidence"]
    _load(conn)
    _load(conn)
    assert _row(conn, "gene", CURATED_BDH1["id"])["evidence"] == once


# --------------------------------------------------------------- not clobbering curated work


def test_a_curated_row_keeps_its_evidence_group_and_coordinates(
    conn: sqlite3.Connection,
) -> None:
    _seed_curated(conn)
    report = _load(conn)
    bdh1 = _row(conn, "gene", CURATED_BDH1["id"])

    # Nothing that was already there moved.
    assert bdh1["gene_group_id"] == CURATED_BDH1["gene_group_id"]
    assert bdh1["start_pos"] == CURATED_BDH1["start_pos"]
    assert bdh1["end_pos"] == CURATED_BDH1["end_pos"]
    assert bdh1["strand"] == CURATED_BDH1["strand"]
    assert bdh1["standard_name"] == CURATED_BDH1["standard_name"]
    assert bdh1["confidence"] == CURATED_BDH1["confidence"]
    # The curated sentence is intact and the GFF3's clause was appended after it.
    assert bdh1["evidence"].startswith(CURATED_BDH1["evidence"])
    assert "s288c.mini.gff3" in bdh1["evidence"]
    # What the load was actually for.
    assert bdh1["seqid"] == "NC_001133.9"
    assert bdh1["biotype"] == "protein_coding"
    assert report.inserted == 13
    assert report.updated == 1


def test_a_curated_gene_group_is_never_rewritten(conn: sqlite3.Connection) -> None:
    """`omics.genes.write_resolution` upserts groups with DO UPDATE SET on every column. Running
    that over a whole genome would rewrite all 36 curated anchors' evidence."""
    _seed_curated(conn)
    report = _load(conn)
    group = _row(conn, "gene_group", CURATED_GROUP["id"])
    assert group == CURATED_GROUP
    assert report.gene_groups_left_alone == 1
    assert report.gene_groups_inserted == 13


def test_a_coordinate_disagreement_is_reported_not_applied(conn: sqlite3.Connection) -> None:
    """The failure this loader exists to avoid: the curated rows' spans come from the mRNA
    feature of a transcript FASTA, this loader reads the gene feature of a GFF3, and neither is a
    correction of the other."""
    moved = dict(CURATED_BDH1)
    moved["start_pos"] = 35100
    _insert(conn, "gene_group", CURATED_GROUP)
    _insert(conn, "gene", moved)

    report = _load(conn)

    assert _row(conn, "gene", moved["id"])["start_pos"] == 35100
    reported = {(d.column, d.stored, d.from_gff3) for d in report.disagreements}
    assert ("start_pos", 35100, 35154) in reported


def test_a_curated_row_with_no_coordinates_at_all_gets_them(conn: sqlite3.Connection) -> None:
    """Most of the 36 are fully populated, but `start_pos` is nullable and a hand-curated row
    without coordinates is exactly the row a genome load should complete."""
    bare = dict(CURATED_BDH1)
    bare["start_pos"] = None
    bare["end_pos"] = None
    bare["strand"] = None
    _insert(conn, "gene_group", CURATED_GROUP)
    _insert(conn, "gene", bare)

    _load(conn)

    filled = _row(conn, "gene", bare["id"])
    assert (filled["start_pos"], filled["end_pos"], filled["strand"]) == (35154, 36303, 1)
    assert filled["evidence"].startswith(CURATED_BDH1["evidence"])


# ------------------------------------------------------------------------ skips and refusals


def test_a_gene_with_no_locus_tag_is_skipped_with_a_reason(conn: sqlite3.Connection) -> None:
    lines = [
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-X;Name=X;gene_biotype=ncRNA",
        "NC_001133.9\tRefSeq\tgene\t300\t400\t.\t+\t.\tID=gene-Y;locus_tag=Y",
    ]
    report = load_gene_records(conn, _parsed(lines), source=SOURCE, organism_id=ORGANISM_ID)
    assert report.inserted == 1
    assert report.skipped_by_reason() == {"no_locus_tag": 1}
    assert "locus tag" in report.skipped[0].detail


def test_a_repeated_locus_tag_is_skipped_rather_than_silently_merged(
    conn: sqlite3.Connection,
) -> None:
    lines = [
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-A1;locus_tag=A",
        "NC_001133.9\tRefSeq\tgene\t300\t400\t.\t+\t.\tID=gene-A2;locus_tag=A",
    ]
    report = load_gene_records(conn, _parsed(lines), source=SOURCE, organism_id=ORGANISM_ID)
    assert report.inserted == 1
    assert report.skipped_by_reason() == {"duplicate_locus_tag": 1}
    assert conn.execute("SELECT start_pos FROM gene").fetchone()[0] == 99


def test_a_missing_organism_is_refused_rather_than_invented() -> None:
    connection = open_db(IN_MEMORY)
    try:
        with pytest.raises(GeneLoadError, match="organism"):
            load_gene_records(
                connection,
                iter_gene_records(FIXTURE),
                source=SOURCE,
                organism_id="YAA:ORG:nothing-here",
            )
    finally:
        connection.close()


def test_the_counts_reconcile_against_the_file(conn: sqlite3.Connection) -> None:
    report = _load(conn)
    assert report.considered == 14
    assert report.as_dict()["considered"] == 14


# ------------------------------------------------------------------------- the one-call form


def test_load_gff3_digests_the_file_it_read(conn: sqlite3.Connection) -> None:
    report = load_gff3(conn, FIXTURE, assembly_accession=ASSEMBLY, organism_id=ORGANISM_ID)
    assert report.inserted == 14
    evidence = _row(conn, "gene", gene_id("YAL060W", ASSEMBLY))["evidence"]
    assert "s288c.mini.gff3" in evidence
    # A real digest, not the placeholder the other tests use.
    assert "sha256 " + "0" * 64 not in evidence
