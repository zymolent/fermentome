"""Tests for `fermdb genomics load-gff3` and the dry run underneath it.

The dry run is the one that has to be right. Its whole value is that a person believes its counts
and then runs the write, so a dry run that diverged from the write would be worse than no dry run
at all -- it would be a rehearsal of a different performance. The central test here therefore runs
both against the same file and asserts the counts are identical, rather than asserting the dry
run's numbers against hand-written expectations.

Everything runs against a database under `tmp_path` via `FERMDB_DATA_DIR`. Nothing here opens the
real atlas.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fermdb import cli
from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.genomics.cli import cmd_genomics_load_gff3, format_report
from fermdb.genomics.gff3 import iter_gene_records
from fermdb.genomics.load_genes import (
    Disagreement,
    GeneLoadReport,
    GffSource,
    SkippedGene,
    load_gene_records,
)
from fermdb.omics.genes import ORGANISM_ID, organism_row

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "genomics" / "s288c.mini.gff3"
ASSEMBLY = "GCF_000146045.2"
SOURCE = GffSource(assembly_accession=ASSEMBLY, file_name="s288c.mini.gff3", sha256="0" * 64)

_ORGANISM_SQL = (
    "INSERT INTO organism (id, ncbi_taxid, name, rank, zone, evidence, confidence) "
    "VALUES (:id, :ncbi_taxid, :name, :rank, :zone, :evidence, :confidence)"
)


def _settings_env(tmp_path: Path) -> dict[str, str]:
    return {
        "FERMDB_REPO_ROOT": str(REPO_ROOT),
        "FERMDB_DATA_DIR": str(tmp_path / "derived"),
        "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
    }


@pytest.fixture()
def atlas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A real on-disk database under tmp_path, with the organism row the loader requires."""
    for key, value in _settings_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    settings = Settings.load()
    connection = open_db(settings.db_file)
    try:
        connection.execute(_ORGANISM_SQL, organism_row())
        connection.commit()
    finally:
        connection.close()
    return Path(settings.db_file)


def _args(*argv: str) -> object:
    return cli.build_parser().parse_args(["genomics", "load-gff3", *argv])


def _gene_count(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM gene").fetchone()[0])
    finally:
        connection.close()


# --------------------------------------------------------------------------- parser wiring


def test_the_subcommand_is_registered_next_to_the_others() -> None:
    parsed = _args(
        str(FIXTURE), "--assembly-accession", ASSEMBLY, "--organism-id", ORGANISM_ID, "--dry-run"
    )
    assert parsed.func is cmd_genomics_load_gff3  # type: ignore[attr-defined]
    assert parsed.dry_run is True  # type: ignore[attr-defined]
    assert parsed.assembly_accession == ASSEMBLY  # type: ignore[attr-defined]
    assert parsed.anchor_namespace == "sgd_systematic"  # type: ignore[attr-defined]
    assert parsed.confidence == "high"  # type: ignore[attr-defined]


def test_the_assembly_is_required_rather_than_defaulted() -> None:
    """A defaulted assembly would stamp a CEN.PK annotation with the S288C accession, and a gene
    id is meaningless without its assembly."""
    with pytest.raises(SystemExit):
        _args(str(FIXTURE), "--organism-id", ORGANISM_ID)


def test_the_organism_is_required_too() -> None:
    with pytest.raises(SystemExit):
        _args(str(FIXTURE), "--assembly-accession", ASSEMBLY)


# ------------------------------------------------------------------------------- the dry run


def test_a_dry_run_writes_nothing(atlas: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _gene_count(atlas) == 0
    code = cmd_genomics_load_gff3(
        _args(  # type: ignore[arg-type]
            str(FIXTURE),
            "--assembly-accession",
            ASSEMBLY,
            "--organism-id",
            ORGANISM_ID,
            "--dry-run",
        )
    )
    assert code == 0
    assert _gene_count(atlas) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "nothing was written" in out
    assert "considered" in out


def test_the_dry_run_and_the_write_agree_exactly(atlas: Path) -> None:
    """The property the whole feature rests on: same loop, same merge, same numbers."""
    settings = Settings.load()
    connection = open_db(settings.db_file, create=False)
    try:
        rehearsal = load_gene_records(
            connection,
            iter_gene_records(FIXTURE),
            source=SOURCE,
            organism_id=ORGANISM_ID,
            dry_run=True,
        )
        assert _gene_count(atlas) == 0
        real = load_gene_records(
            connection, iter_gene_records(FIXTURE), source=SOURCE, organism_id=ORGANISM_ID
        )
    finally:
        connection.close()

    assert rehearsal.as_dict() == real.as_dict()
    assert rehearsal.by_seqid == real.by_seqid
    assert rehearsal.by_biotype == real.by_biotype
    assert rehearsal.dry_run is True
    assert real.dry_run is False
    assert _gene_count(atlas) == 14


def test_a_dry_run_over_a_populated_atlas_reports_the_merge_it_would_do(atlas: Path) -> None:
    """Run the write, then rehearse it again: every gene should come back `unchanged`, which is
    how a person tells "already loaded" from "about to load 6,600 rows"."""
    settings = Settings.load()
    connection = open_db(settings.db_file, create=False)
    try:
        load_gene_records(
            connection, iter_gene_records(FIXTURE), source=SOURCE, organism_id=ORGANISM_ID
        )
        again = load_gene_records(
            connection,
            iter_gene_records(FIXTURE),
            source=SOURCE,
            organism_id=ORGANISM_ID,
            dry_run=True,
        )
    finally:
        connection.close()
    assert again.unchanged == 14
    assert again.inserted == 0


def test_the_dry_run_takes_no_write_lock() -> None:
    """It can be pointed at an atlas another process is using, which is the normal state of this
    repo. `BEGIN IMMEDIATE` takes the write lock the moment it runs, so the check is that the
    connection is left outside a transaction entirely -- nothing to commit and nothing to roll
    back."""
    holder = open_db(IN_MEMORY)
    holder.execute(_ORGANISM_SQL, organism_row())
    holder.commit()
    try:
        report = load_gene_records(
            holder,
            iter_gene_records(FIXTURE),
            source=SOURCE,
            organism_id=ORGANISM_ID,
            dry_run=True,
        )
        assert report.inserted == 14
        assert holder.execute("SELECT COUNT(*) FROM gene").fetchone()[0] == 0
        # No transaction was opened, so the connection is still usable without a rollback.
        assert holder.in_transaction is False
    finally:
        holder.close()


# ------------------------------------------------------------------------------ the real run


def test_the_write_path_lands_the_genes(atlas: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cmd_genomics_load_gff3(
        _args(str(FIXTURE), "--assembly-accession", ASSEMBLY, "--organism-id", ORGANISM_ID)  # type: ignore[arg-type]
    )
    assert code == 0
    assert _gene_count(atlas) == 14
    out = capsys.readouterr().out
    assert "written and committed" in out
    assert "WRITE" in out


def test_a_missing_file_is_an_error_not_an_empty_load(
    atlas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cmd_genomics_load_gff3(
        _args(  # type: ignore[arg-type]
            str(atlas.parent / "nope.gff3"),
            "--assembly-accession",
            ASSEMBLY,
            "--organism-id",
            ORGANISM_ID,
        )
    )
    assert code == 2
    assert "no such file" in capsys.readouterr().err


def test_an_unknown_organism_is_an_error(atlas: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cmd_genomics_load_gff3(
        _args(  # type: ignore[arg-type]
            str(FIXTURE),
            "--assembly-accession",
            ASSEMBLY,
            "--organism-id",
            "YAA:ORG:nothing-here",
        )
    )
    assert code == 2
    assert "organism" in capsys.readouterr().err
    assert _gene_count(atlas) == 0


# ------------------------------------------------------------------------------ the output


def test_json_carries_every_skip_and_every_disagreement(
    atlas: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cmd_genomics_load_gff3(
        _args(  # type: ignore[arg-type]
            str(FIXTURE),
            "--assembly-accession",
            ASSEMBLY,
            "--organism-id",
            ORGANISM_ID,
            "--dry-run",
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["counts"]["inserted"] == 14
    assert payload["skipped"] == []
    assert payload["disagreements"] == []
    assert payload["source"]["assembly_accession"] == ASSEMBLY
    seqids = {entry["seqid"] for entry in payload["by_seqid"]}
    assert "NC_001224.1" in seqids
    biotypes = {entry["biotype"]: entry["genes"] for entry in payload["by_biotype"]}
    assert biotypes == {
        "protein_coding": 8,
        "tRNA": 2,
        "snoRNA": 2,
        "pseudogene": 1,
        "rRNA": 1,
    }
    assert sum(biotypes.values()) == payload["counts"]["considered"]


def test_the_human_table_shows_the_tallies(atlas: Path) -> None:
    settings = Settings.load()
    connection = open_db(settings.db_file, create=False)
    try:
        report = load_gene_records(
            connection,
            iter_gene_records(FIXTURE),
            source=SOURCE,
            organism_id=ORGANISM_ID,
            dry_run=True,
        )
    finally:
        connection.close()
    text = "\n".join(format_report(report))
    assert "genes per sequence" in text
    assert "NC_001224.1" in text
    assert "genes per biotype" in text
    assert "pseudogene" in text


def test_a_skip_is_visible_in_the_human_output_not_only_in_json() -> None:
    """A skipped gene nobody sees is a gene silently missing from the atlas."""
    report = GeneLoadReport(
        inserted=0,
        updated=0,
        unchanged=0,
        gene_groups_inserted=0,
        gene_groups_left_alone=0,
        skipped=(
            SkippedGene(
                gff_id="gene-X", locus_tag=None, reason="no_locus_tag", detail="nothing to key on"
            ),
        ),
        disagreements=(),
    )
    text = "\n".join(format_report(report))
    assert "SKIPPED" in text
    assert "gene-X" in text
    assert "no_locus_tag" in text
    assert "nothing to key on" in text


def test_a_disagreement_says_the_stored_value_was_kept() -> None:
    report = GeneLoadReport(
        inserted=0,
        updated=1,
        unchanged=0,
        gene_groups_inserted=0,
        gene_groups_left_alone=1,
        skipped=(),
        disagreements=(
            Disagreement(
                gene_id="YAA:GENE:gcf-000146045-2-yal060w",
                column="start_pos",
                stored=35100,
                from_gff3=35154,
            ),
        ),
    )
    text = "\n".join(format_report(report))
    assert "DISAGREEMENTS" in text
    assert "KEPT" in text
    assert "35100" in text and "35154" in text
    assert "never" in text  # "conflicts are recorded, never silently resolved"


def test_long_lists_are_truncated_and_say_so() -> None:
    many = tuple(
        SkippedGene(gff_id=f"gene-{n}", locus_tag=None, reason="no_locus_tag", detail="d")
        for n in range(30)
    )
    report = GeneLoadReport(
        inserted=0,
        updated=0,
        unchanged=0,
        gene_groups_inserted=0,
        gene_groups_left_alone=0,
        skipped=many,
        disagreements=(),
    )
    text = "\n".join(format_report(report, max_detail=5))
    assert "and 25 more" in text
    assert "--json lists every one" in text
