"""Tests for `fermdb.omics.load` — getting the transcriptomics layer into the database.

The properties pinned here are the ones whose absence would be invisible. A load that silently
registers the wrong genome, drops the two excluded runs instead of recording why they were
excluded, or writes 0 where nobody has measured anything, produces a database that looks complete
and answers questions wrongly. Every check below is against an expectation independent of the
code: a FASTA's own headers, a manifest's own byte total, a schema's own CHECK vocabulary.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import load as L

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings whose derived tier is under tmp_path, never the developer's real ~/fermdb-data."""
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


def _genome(path: Path, header: str, sequence: str = "ACGTACGTAC") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(f">{header}\n{sequence}\n")
    return path


# ------------------------------------------------------------------- identity from the bytes


def test_fasta_identity_is_read_from_the_file(tmp_path: Path) -> None:
    path = _genome(tmp_path / "g.fna.gz", "NZ_CP035711.1 Zymomonas mobilis subsp. mobilis ZM4")
    accessions, bases, first = L.fasta_identity(path)
    assert accessions == ("NZ_CP035711.1",)
    assert bases == 10
    assert first.startswith("NZ_CP035711.1 Zymomonas")


def test_a_genome_whose_headers_name_another_organism_is_refused(tmp_path: Path) -> None:
    """The failure that actually happened: a manifest labelled GCF_000092685.1 — Chlamydia
    trachomatis — as this project's Zymomonas mobilis genome. The download was fine; the label
    was not, and nothing downstream could tell because everything downstream read the label."""
    path = _genome(tmp_path / "g.fna.gz", "NC_000117.1 Chlamydia trachomatis D/UW-3/CX")
    with pytest.raises(L.OmicsLoadError, match="refusing to register"):
        L._check_organism_matches(path, "Zymomonas mobilis subsp. mobilis ZM4", "GCF_000007105.1")


def test_strain_detail_in_a_header_does_not_break_the_match(tmp_path: Path) -> None:
    """RefSeq headers carry assembly and strain detail the catalog's name does not, so the check
    is genus-plus-species. Demanding an exact match would reject correct files."""
    path = _genome(
        tmp_path / "g.fna.gz",
        "NZ_CP035711.1 Zymomonas mobilis subsp. mobilis ZM4 = ATCC 31821 strain ZM4 chromosome",
    )
    measured = L._check_organism_matches(
        path, "Zymomonas mobilis subsp. mobilis ZM4 = ATCC 31821", "GCF_000007105.1"
    )
    assert "1 sequences" in measured


# ------------------------------------------------------------------------------ missing values


def test_a_missing_count_is_null_not_zero() -> None:
    """A run whose spot count SRA did not report has NULL spots. 0 would claim an empty run."""
    assert L._int_or_none("") is None
    assert L._int_or_none(None) is None
    assert L._int_or_none("0") == 0
    assert L._int_or_none("12345") == 12345


def test_size_mb_keeps_its_fraction() -> None:
    """`size_mb` is REAL in the schema; reading it as an int would silently truncate 143.5."""
    assert L._float_or_none("143.5") == 143.5
    assert L._float_or_none("") is None


# --------------------------------------------------------------------------------- matrices


def test_matrix_shape_is_read_from_the_file_not_a_manifest(tmp_path: Path) -> None:
    """The manifest beside these files has been wrong before. The file cannot be."""
    path = tmp_path / "m.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("gene\tS1\tS2\tS3\n")
        for gene in ("YAL001C", "YAL002W", "Q0020"):
            handle.write(f"{gene}\t1.0\t2.0\t3.0\n")
    assert L.matrix_shape(path) == (3, 3)


def test_matrices_register_as_files_not_as_rows(tmp_path: Path, settings: Settings) -> None:
    """600,000 expression values do not belong in a table — analysis_result says so itself
    ("Points at Parquet on disk, never a BLOB in the database")."""
    matrices = Path(settings.matrices_dir)
    matrices.mkdir(parents=True, exist_ok=True)
    with gzip.open(matrices / "s288c.tpm.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("gene\tS1\n YAL001C\t1.0\n")

    connection = open_db(IN_MEMORY)
    try:
        counts = L.load_matrices(connection, settings)
        assert counts["analysis_result"] == 1
        row = connection.execute("SELECT kind, payload_ref, zone FROM analysis_result").fetchone()
        assert row["kind"] == "expression_matrix"
        assert "s288c.tpm.tsv.gz" in row["payload_ref"]
        # Zone H: derived, and rebuildable by re-running the pipeline over the raw objects.
        assert row["zone"] == "H"
    finally:
        connection.close()


def test_an_empty_matrix_directory_is_an_error_not_an_empty_load(settings: Settings) -> None:
    Path(settings.matrices_dir).mkdir(parents=True, exist_ok=True)
    connection = open_db(IN_MEMORY)
    try:
        with pytest.raises(L.OmicsLoadError, match="no matrix files"):
            L.load_matrices(connection, settings)
    finally:
        connection.close()


# ------------------------------------------------------------------------------ missing input


def test_a_missing_provenance_file_refuses_rather_than_loading_nothing(settings: Settings) -> None:
    """Loading zero rows because an input vanished looks identical to a corpus with no runs."""
    connection = open_db(IN_MEMORY)
    try:
        with pytest.raises(L.OmicsLoadError, match="provenance"):
            L._read_json(L.omics_dir(settings) / "does-not-exist.json")
    finally:
        connection.close()


# ------------------------------------------------ the real corpus, against its own provenance


@pytest.mark.parametrize("name", [L.REFERENCE_MANIFEST, L.STAGING_MANIFEST, L.DROPPED_RUNS])
def test_the_committed_provenance_files_are_present_and_parse(name: str) -> None:
    """These were copied out of a session scratchpad, which is deleted with its session. If they
    go missing the load cannot be re-run and no row it wrote can be traced."""
    payload = json.loads((REPO_ROOT / L.OMICS_DIR / name).read_text(encoding="utf-8"))
    assert payload


def test_every_manifest_accession_is_in_the_curated_catalog() -> None:
    """The check that caught GCF_000092685.1. The catalog is what sra_run.reference_assembly
    joins on, so an asset outside it would be a reference nothing can select."""
    from fermdb.omics.references import load_reference_genomes, reference_genomes_path

    settings = Settings.load(paths_file=PATHS_FILE, env={})
    catalog = {
        entry.accession for entry in load_reference_genomes(reference_genomes_path(settings))
    }
    manifest = json.loads(
        (REPO_ROOT / L.OMICS_DIR / L.REFERENCE_MANIFEST).read_text(encoding="utf-8")
    )
    unknown = [entry["accession"] for entry in manifest if entry["accession"] not in catalog]
    assert not unknown, f"downloaded but not cataloged: {unknown}"


def test_the_staging_manifest_byte_total_matches_its_own_results() -> None:
    """An independent expectation: the manifest's headline total and the sum of its per-run
    records must agree, or one of them has drifted."""
    staging = json.loads((REPO_ROOT / L.OMICS_DIR / L.STAGING_MANIFEST).read_text(encoding="utf-8"))
    copied = [r for r in staging["results"] if r.get("status") == "copied"]
    assert len(copied) == staging["copied"] == staging["runs_requested"]
    assert sum(r["bytes"] for r in copied) == staging["total_bytes"]


def test_no_reference_genome_is_smaller_than_its_own_n50() -> None:
    """The contradiction that proved the Zymomonas manifest entry wrong rather than the file:
    an N50 cannot exceed the genome it is computed over."""
    from fermdb.omics.references import load_reference_genomes, reference_genomes_path

    settings = Settings.load(paths_file=PATHS_FILE, env={})
    catalog = {e.accession: e for e in load_reference_genomes(reference_genomes_path(settings))}
    manifest = json.loads(
        (REPO_ROOT / L.OMICS_DIR / L.REFERENCE_MANIFEST).read_text(encoding="utf-8")
    )
    for entry in manifest:
        cataloged = catalog.get(entry["accession"])
        if cataloged is None or cataloged.n50_bp is None:
            continue
        assert entry["bases"] >= cataloged.n50_bp, (
            f"{entry['accession']}: manifest records {entry['bases']} bases but the catalog's "
            f"n50 is {cataloged.n50_bp}"
        )


# ---------------------------------------------------------------------------------------------
# Samples and the yeast reference sequences.
#
# measurement's own CHECK requires a sample, strain or experiment, and all three were empty --
# which made a measurement unstorable however good the extraction. These close the cheapest one
# and register the two references whose translation table the whole project turns on.
# ---------------------------------------------------------------------------------------------


def _conn_with_runs() -> sqlite3.Connection:
    connection = open_db(IN_MEMORY)
    connection.execute(
        "INSERT INTO dataset (id, accession, repository, zone, evidence, confidence) "
        "VALUES ('YAA:DATASET:s1','SRP1','SRA','R','t','high')"
    )
    for accession in ("SRR1", "ERR2"):
        connection.execute(
            "INSERT INTO sra_run (id, run_accession, dataset_id, organism, acquisition_status, "
            "priority_rank, retrieved_at, zone, evidence, confidence, relevance_uncertain) "
            "VALUES (?,?,'YAA:DATASET:s1','S. cerevisiae','discovered',0,'2026-01-01','R','t',"
            "'high',0)",
            (f"YAA:SRARUN:{accession}", accession),
        )
    return connection


def test_one_sample_per_run_with_strain_and_conditions_left_null() -> None:
    """NULL is the honest state, not an omission: which strain a run used and under what
    conditions are curation questions, and a guess here would be indistinguishable from a
    curated answer."""
    connection = _conn_with_runs()
    try:
        assert L.load_samples(connection)["sample"] == 2
        rows = connection.execute(
            "SELECT id, dataset_id, strain_id, condition_context_id, zone FROM sample"
        ).fetchall()
        assert {row["id"] for row in rows} == {"YAA:SAMPLE:SRR1", "YAA:SAMPLE:ERR2"}
        assert all(row["strain_id"] is None for row in rows)
        assert all(row["condition_context_id"] is None for row in rows)
        assert all(row["dataset_id"] == "YAA:DATASET:s1" for row in rows)
        assert all(row["zone"] == "R" for row in rows)
    finally:
        connection.close()


def test_sample_loading_is_idempotent() -> None:
    connection = _conn_with_runs()
    try:
        L.load_samples(connection)
        L.load_samples(connection)
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 2
    finally:
        connection.close()


def test_a_measurement_can_attach_to_a_loaded_sample(settings: Settings) -> None:
    """The reason load_samples exists. Before it, measurement's CHECK had nothing to satisfy."""
    from fermdb.db.vocabularies import load_vocabularies

    connection = _conn_with_runs()
    try:
        L.load_samples(connection)
        load_vocabularies(connection, settings)
        connection.execute(
            "INSERT INTO measurement (id, sample_id, quantity_kind, product_id, "
            "value_as_reported, unit_as_reported, is_fraction, is_below_lod, is_upper_bound, "
            "is_digitized, source_locator, zone, evidence, confidence) "
            "VALUES ('YAA:M:1','YAA:SAMPLE:SRR1','titer','YAA:PRODUCT:isobutanol','22.6','g/L',"
            "0,0,0,0,'text','I','t','unverified')"
        )
        assert connection.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.skipif(
    not Path(os.path.expanduser("~/fermdb-data/genomes/nc_001224.gb")).is_file(),
    reason="the mitochondrial GenBank record lives in the derived tier",
)
def test_mitochondrial_translation_verified_is_earned_not_assumed() -> None:
    """The flag means 'this reference's CDS reproduce NCBI's own translation under table 3', and
    it is recomputed per load. Carrying it forward from a previous run would let a replaced file
    inherit a verification it never passed."""
    from fermdb.omics.mito_transcripts import parse_mitochondrial_cds

    text = Path(os.path.expanduser("~/fermdb-data/genomes/nc_001224.gb")).read_text(
        encoding="utf-8"
    )
    records, _ = parse_mitochondrial_cds(text)
    assert records
    assert any(record.table_1_would_differ for record in records), (
        "a mitochondrial reference that reads identically under table 1 does not demonstrate the "
        "disagreement it is kept to prove"
    )
