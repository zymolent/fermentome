"""Tests for `fermdb.omics.genes` — the DUET gene-set resolution.

PLAN.md E.4 marks every gene in the day-one set unverified and says the resolution *is* the
phase-1 genomics acceptance criterion. So the properties pinned here are the ones that decide
whether a resolution can be trusted: that identity comes from parsing and never from recall, that
a symbol which is not in the source becomes a recorded gap rather than a guess, and above all
that the encoding genome is derived from the sequence accession and refuses to default.

Fixtures are synthetic. The real transcript FASTA lives in the derived data tier, not the repo,
and a test that depends on it would pass or fail according to what someone happens to have
downloaded.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import genes as g

# Two real headers, copied verbatim from s288c.transcripts.fna.gz, plus one mitochondrial.
ADH3 = (
    ">lcl|NC_001145.3_mrna_NM_001182582.1_4662 [gene=ADH3] [locus_tag=YMR083W] "
    "[db_xref=GeneID:855107] [product=alcohol dehydrogenase ADH3] [transcript_id=NM_001182582.1] "
    "[gbkey=mRNA] [location=434788..435915]"
)
COX1 = (
    ">lcl|NC_001224.1_mrna_NM_001228704.1_1 [gene=COX1] [locus_tag=Q0045] "
    "[db_xref=GeneID:854598] [product=cytochrome c oxidase subunit 1] "
    "[transcript_id=NM_001228704.1] [gbkey=mRNA] [location=13818..26701]"
)
UNNAMED = (
    ">lcl|NC_001133.9_mrna_NM_001184582.1_2 [locus_tag=YAL067W-A] [db_xref=GeneID:1466426] "
    "[product=uncharacterized protein] [transcript_id=NM_001184582.1] [gbkey=mRNA] "
    "[location=complement(2170..2707)]"
)


def test_a_header_yields_every_identity_fact_without_recall() -> None:
    header = g.parse_transcript_header(ADH3)
    assert header.gene == "ADH3"
    assert header.locus_tag == "YMR083W"
    assert header.gene_id == "855107"
    assert header.sequence_accession == "NC_001145.3"
    assert header.product == "alcohol dehydrogenase ADH3"
    assert (header.start_pos, header.end_pos, header.strand) == (434787, 435915, 1)


def test_a_feature_with_no_standard_name_records_null_not_unknown() -> None:
    """993 of this file's features are uncharacterised ORFs. RefSeq recorded no name; that is
    NULL, not the string 'unknown' (CONVENTIONS.md, "Missing values")."""
    header = g.parse_transcript_header(UNNAMED)
    assert header.gene is None
    assert header.locus_tag == "YAL067W-A"


def test_a_complement_location_is_read_as_the_minus_strand() -> None:
    header = g.parse_transcript_header(UNNAMED)
    assert header.strand == -1
    assert header.start_pos < header.end_pos


def test_a_malformed_header_raises_rather_than_half_filling_a_record() -> None:
    with pytest.raises(g.GeneResolutionError, match="missing"):
        g.parse_transcript_header(">lcl|NC_001145.3_mrna_1 [gene=ADH3]")
    with pytest.raises(g.GeneResolutionError, match="no sequence accession"):
        g.parse_transcript_header(
            ">nonsense [locus_tag=X] [product=p] [gbkey=mRNA] [location=1..2]"
        )


# --------------------------------------------------------------- the encoding-genome decision


def test_the_encoding_genome_comes_from_the_accession() -> None:
    """The load-bearing one. ADH3 works in the matrix but is nuclear-encoded, so it reads under
    NCBI table 1 and a presequence-targeted construct of it needs no recoding. Only a gene
    physically carried on the mtDNA reads under table 3."""
    assert g.encoding_genome_for_accession("NC_001145.3") == "nuclear"
    assert g.encoding_genome_for_accession("NC_001224.1") == "mitochondrial"


def test_an_unknown_accession_refuses_to_default() -> None:
    """Defaulting to 'nuclear' would read a table-3 gene under table 1 — the exact mistake
    fermdb.genetic_code exists to make impossible."""
    with pytest.raises(g.GeneResolutionError, match="refusing to assume"):
        g.encoding_genome_for_accession("NC_999999.9")


# ------------------------------------------------------------------------------- resolution


def _fasta(tmp_path: Path, *headers: str) -> Path:
    path = tmp_path / "transcripts.fna.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for header in headers:
            handle.write(header + "\nACGT\n")
    return path


def _resolve(path: Path, wanted: tuple[str, ...]) -> g.Resolution:
    """resolve_symbols over a fixture file, with the source recorded the way build() does."""
    return g.resolve_symbols(
        wanted,
        g.iter_transcript_headers(path),
        {},
        source_path=path.name,
        source_sha256=g.sha256_of(path),
    )


def test_a_symbol_absent_from_the_source_becomes_a_gap_not_a_guess(tmp_path: Path) -> None:
    resolution = _resolve(_fasta(tmp_path, ADH3), ("ADH3", "NOTAGENE"))
    assert [gene.symbol for gene in resolution.genes] == ["ADH3"]
    assert [gap.symbol for gap in resolution.gaps] == ["NOTAGENE"]
    assert "no feature" in resolution.gaps[0].reason


def test_a_mitochondrial_gene_resolves_to_the_mitochondrial_genome(tmp_path: Path) -> None:
    resolution = _resolve(_fasta(tmp_path, ADH3, COX1), ("ADH3", "COX1"))
    by_symbol = {gene.symbol: gene for gene in resolution.genes}
    assert by_symbol["ADH3"].encoding_genome == "nuclear"
    assert by_symbol["COX1"].encoding_genome == "mitochondrial"


def test_a_symbol_on_two_features_refuses_to_choose(tmp_path: Path) -> None:
    twin = ADH3.replace("YMR083W", "YMR083W-B").replace("_4662", "_4663")
    with pytest.raises(g.GeneResolutionError, match="refusing to choose"):
        _resolve(_fasta(tmp_path, ADH3, twin), ("ADH3",))


def test_the_source_is_recorded_by_checksum(tmp_path: Path) -> None:
    """A resolution has to say which bytes produced it, or it cannot be re-derived."""
    path = _fasta(tmp_path, ADH3)
    resolution = _resolve(path, ("ADH3",))
    assert resolution.source_sha256 == g.sha256_of(path)
    assert len(resolution.source_sha256) == 64


# --------------------------------------------------------------------- matrix cross-check


def test_a_resolved_gene_missing_from_the_matrix_is_reported(tmp_path: Path) -> None:
    """The independent check: a systematic name that does not appear as a matrix row means the
    resolution and the quantification disagree, which is a finding rather than a nuisance."""
    resolution = _resolve(_fasta(tmp_path, ADH3, COX1), ("ADH3", "COX1"))
    check = g.verify_against_matrix(resolution, ["YMR083W", "YAL001C"])
    assert check.present == ("YMR083W",)
    assert check.missing == ("Q0045",)


# ------------------------------------------------------------------------------- the rows


def test_rows_carry_the_right_zones(tmp_path: Path) -> None:
    """A gene is Zone R — it is what RefSeq says. A gene_group is Zone H — it is our grouping,
    rebuildable from the anchor."""
    resolution = _resolve(_fasta(tmp_path, ADH3), ("ADH3",))
    assert g.gene_rows(resolution)[0]["zone"] == "R"
    assert g.gene_group_rows(resolution)[0]["zone"] == "H"


def test_writing_is_idempotent(tmp_path: Path) -> None:
    """Re-running a resolution must update in place, not accumulate a second copy of the set."""
    resolution = _resolve(_fasta(tmp_path, ADH3, COX1), ("ADH3", "COX1"))
    connection: sqlite3.Connection = open_db(IN_MEMORY)
    try:
        first = g.write_resolution(connection, resolution)
        g.write_resolution(connection, resolution)
        assert first["gene"] == 2
        assert connection.execute("SELECT COUNT(*) FROM gene").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM gene_group").fetchone()[0] == 2
    finally:
        connection.close()
