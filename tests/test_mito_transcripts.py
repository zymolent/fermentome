"""Tests for `fermdb.omics.mito_transcripts`.

The safety property is the translation check. A mis-assembled CDS still translates to *something*,
so comparing the result against NCBI's own `/translation` is the only thing separating "assembled"
from "assembled correctly" — and it is what makes it safe to join exons at all. COX1 has eight of
them across a wrapped GenBank location; a parser that took the first line only would build four
exons' worth of sequence and be wrong rather than absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fermdb.omics import mito_transcripts as M
from fermdb.omics.baseline import missing_mitochondrial_proteins

GENBANK = Path(os.path.expanduser("~/fermdb-data/genomes/nc_001224.gb"))

# A minimal record: one plain CDS whose protein exercises UGA-as-tryptophan, so it translates
# under table 3 and not under table 1.
SIMPLE = """\
FEATURES             Location/Qualifiers
     CDS             1..12
                     /gene="TINY"
                     /locus_tag="Q9999"
                     /product="test protein"
                     /translation="MWK"
ORIGIN
        1 atgtgaaaat aa
//
"""


def test_a_plain_cds_is_extracted_and_verified() -> None:
    records, skipped = M.parse_mitochondrial_cds(SIMPLE)
    assert not skipped
    assert len(records) == 1
    record = records[0]
    assert record.gene == "TINY"
    assert record.locus_tag == "Q9999"
    assert record.translation == "MWK"
    assert record.exons == 1


def test_a_cds_that_needs_table_three_is_flagged() -> None:
    """TGA is a stop under table 1 and tryptophan under table 3. A CDS containing one is direct
    evidence that reading this supplement under the standard table would be wrong."""
    records, _ = M.parse_mitochondrial_cds(SIMPLE)
    assert records[0].table_1_would_differ is True


def test_a_translation_that_does_not_match_raises() -> None:
    """The whole safety argument. Nothing is added to an index on trust."""
    wrong = SIMPLE.replace('/translation="MWK"', '/translation="MAK"')
    with pytest.raises(M.MitoTranscriptError, match="Refusing to add a CDS"):
        M.parse_mitochondrial_cds(wrong)


def test_a_cds_with_no_translation_is_skipped_and_reported() -> None:
    """Reported, not silently dropped: a silently-skipped gene is a gene missing from the index
    for the second time."""
    without = SIMPLE.replace('                     /translation="MWK"\n', "")
    records, skipped = M.parse_mitochondrial_cds(without)
    assert not records
    assert any("no /translation" in reason for reason in skipped)


def test_an_empty_record_refuses_rather_than_writing_an_empty_supplement(tmp_path: Path) -> None:
    """An empty supplement would leave the index exactly as incomplete while looking fixed."""
    empty = "FEATURES             Location/Qualifiers\nORIGIN\n        1 aaa\n//\n"
    source = tmp_path / "empty.gb"
    source.write_text(empty, encoding="utf-8")
    with pytest.raises(M.MitoTranscriptError, match="no verifiable CDS"):
        M.build_supplement(source, tmp_path / "out.fna")


# ------------------------------------------------------------------------ location parsing


def test_a_wrapped_location_is_reassembled() -> None:
    """GenBank wraps a long location, and the continuation reaches the parser as a qualifier line.
    COX1's runs to two lines and eight exons."""
    location, remaining = M._full_location(
        "join(13818..13986,16435..16470,18954..18991,20508..20984,",
        ["21995..22246,23612..23746,25318..25342,26229..26701)", '/gene="COX1"'],
    )
    assert location.endswith("26229..26701)")
    assert len(M._exons(location)) == 8
    assert remaining == ['/gene="COX1"']


def test_a_complemented_join_reverses_both_strand_and_order() -> None:
    exons = M._exons("complement(join(100..200,300..400))")
    assert [start for start, _, _ in exons] == [299, 99]
    assert all(complement for _, _, complement in exons)


def test_the_header_style_matches_the_transcriptome() -> None:
    """The matrix builder derives a row name from [locus_tag=...]. A supplement written any other
    way would quantify fine and produce rows nothing could join to gene.systematic_name."""
    records, _ = M.parse_mitochondrial_cds(SIMPLE)
    header = M.format_supplement(records).splitlines()[0]
    assert "[locus_tag=Q9999]" in header
    assert "[gene=TINY]" in header
    assert "[gbkey=CDS]" in header
    assert header.startswith(f">lcl|{M.MITOCHONDRIAL_ACCESSION}")


# ------------------------------------------------------------- the real mitochondrial record


@pytest.mark.skipif(not GENBANK.is_file(), reason="NC_001224 lives in the derived tier")
def test_the_real_record_yields_the_whole_protein_complement() -> None:
    """The point of the exercise: every gene the transcriptome was missing, assembled and
    verified. COX1 and COB are intron-containing, so this also exercises the join path against
    real data rather than a fixture."""
    records, skipped = M.parse_mitochondrial_cds(GENBANK.read_text(encoding="utf-8"))
    symbols = {record.gene for record in records if record.gene}
    assert missing_mitochondrial_proteins(symbols) == ()
    assert not skipped

    by_gene = {record.gene: record for record in records}
    assert by_gene["COX1"].exons > 1, "COX1 is intron-containing in this assembly"
    assert by_gene["COB"].exons > 1
    # Every one of them exercises a codon the tables disagree on.
    assert all(record.table_1_would_differ for record in records)


@pytest.mark.skipif(not GENBANK.is_file(), reason="NC_001224 lives in the derived tier")
def test_atp9_is_found_under_its_oli1_synonym() -> None:
    """NC_001224 annotates ATP9 as OLI1. A check that only looked for 'ATP9' would report a gap
    that had already been closed, and send someone to fix it twice."""
    records, _ = M.parse_mitochondrial_cds(GENBANK.read_text(encoding="utf-8"))
    symbols = {record.gene for record in records if record.gene}
    assert "ATP9" not in symbols
    assert "OLI1" in symbols
    assert "ATP9" not in missing_mitochondrial_proteins(symbols)
