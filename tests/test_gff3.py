"""Tests for `fermdb.genomics.gff3`.

The test that matters most is the first one. A GFF3 is 1-based inclusive and this atlas is
0-based half-open (CONVENTIONS.md, "Coordinates and sequence"), and an off-by-one applied
uniformly to 6,600 genes produces a table that looks entirely reasonable and is wrong everywhere.
So the round-trip is checked against three genes whose stored coordinates were read out of a copy
of the real atlas -- BDH1, ECM31 and GPD1 -- rather than against numbers this file made up.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from fermdb.genomics.gff3 import (
    GeneRecord,
    Gff3Error,
    iter_gene_records,
    parse_attributes,
    parse_gene_records,
    parse_strand,
)

FIXTURE = Path(__file__).parent / "fixtures" / "genomics" / "s288c.mini.gff3"

#: (systematic name, start_pos, end_pos) exactly as `gene` holds them today for three of the 36
#: curated rows. The fixture states the same loci in 1-based inclusive GFF3 form; if the parser's
#: conversion is right these come back identical.
CURATED_COORDINATES = (
    ("YAL060W", 35154, 36303),  # BDH1
    ("YBR176W", 583719, 584658),  # ECM31
    ("YDL022W", 411824, 413000),  # GPD1
)


@pytest.fixture(scope="module")
def records() -> dict[str, GeneRecord]:
    return {r.locus_tag or r.gff_id: r for r in iter_gene_records(FIXTURE)}


# ------------------------------------------------------------------ the coordinate convention


@pytest.mark.parametrize(("locus_tag", "start_pos", "end_pos"), CURATED_COORDINATES)
def test_coordinates_land_where_the_curated_rows_already_are(
    records: dict[str, GeneRecord], locus_tag: str, start_pos: int, end_pos: int
) -> None:
    record = records[locus_tag]
    assert (record.start_pos, record.end_pos) == (start_pos, end_pos)


def test_length_is_end_minus_start_with_no_plus_one(records: dict[str, GeneRecord]) -> None:
    """BDH1's stored span is 1,149 bases -- the CDS including its stop codon, hence a multiple
    of three. Under 1-based inclusive storage it would be 1,148 and divisible by nothing."""
    bdh1 = records["YAL060W"]
    assert bdh1.length == 1149
    assert bdh1.length % 3 == 0


def test_every_protein_coding_span_is_a_whole_number_of_codons(
    records: dict[str, GeneRecord],
) -> None:
    """The check that caught the convention in the first place, applied to the fixture.

    Every single-exon protein-coding gene here spans a CDS plus its stop codon. Half-open, that
    is divisible by three; inclusive-minus-one it never is. A parser that dropped the `- 1`, or
    applied it to the wrong end, fails this for all of them at once.
    """
    single_exon = [
        r
        for r in records.values()
        if r.biotype == "protein_coding" and r.exon_count == 1 and not r.partial
    ]
    assert single_exon, "fixture must contain single-exon coding genes for this to mean anything"
    assert all(r.length % 3 == 0 for r in single_exon), [
        (r.locus_tag, r.length) for r in single_exon
    ]


def test_a_one_base_feature_is_half_open_not_empty() -> None:
    line = "NC_001133.9\tRefSeq\tgene\t500\t500\t.\t+\t.\tID=gene-X;locus_tag=X;gene_biotype=ncRNA"
    (record,) = parse_gene_records([line])
    assert (record.start_pos, record.end_pos, record.length) == (499, 500, 1)


def test_coordinates_that_are_not_1_based_inclusive_are_refused() -> None:
    line = "NC_001133.9\tRefSeq\tgene\t0\t100\t.\t+\t.\tID=gene-X;locus_tag=X"
    with pytest.raises(Gff3Error, match="1-based inclusive"):
        list(parse_gene_records([line]))


# ------------------------------------------------------------------------------------- strand


def test_strand_is_an_integer_never_a_sign(records: dict[str, GeneRecord]) -> None:
    assert records["YAL060W"].strand == 1
    assert records["YAL068C"].strand == -1
    assert records["YNCB0009C"].strand == -1
    assert all(r.strand in (-1, 0, 1) for r in records.values())


@pytest.mark.parametrize(("token", "expected"), [("+", 1), ("-", -1), (".", 0), ("?", 0)])
def test_every_gff3_strand_token_maps(token: str, expected: int) -> None:
    assert parse_strand(token) == expected


def test_an_unknown_strand_token_raises_rather_than_defaulting_to_forward() -> None:
    with pytest.raises(Gff3Error):
        parse_strand("1")


# ------------------------------------------------------------------------------------ biotype


def test_biotype_comes_off_the_gene_feature(records: dict[str, GeneRecord]) -> None:
    observed = {tag: r.biotype for tag, r in records.items()}
    assert observed["YAL060W"] == "protein_coding"
    assert observed["YNCA0002W"] == "tRNA"
    assert observed["YNCA0003W"] == "snoRNA"
    assert observed["Q0158"] == "rRNA"
    assert observed["YAR061W"] == "pseudogene"


def test_a_pseudogene_is_not_dropped_for_having_its_own_feature_type(
    records: dict[str, GeneRecord],
) -> None:
    """RefSeq writes `pseudogene` in column 3, not `gene`. Keying on `== "gene"` loses them all
    and leaves a count that still looks plausible."""
    pseudo = records["YAR061W"]
    assert pseudo.feature_type == "pseudogene"
    assert pseudo.pseudo is True
    assert pseudo.cds_count == 0


def test_a_biotype_nobody_anticipated_is_stored_rather_than_rejected() -> None:
    line = (
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\t"
        "ID=gene-X;locus_tag=X;gene_biotype=transposable_element"
    )
    (record,) = parse_gene_records([line])
    assert record.biotype == "transposable_element"


# ------------------------------------------------------------------------- names and xrefs


def test_a_name_that_differs_from_the_locus_tag_is_kept_separately(
    records: dict[str, GeneRecord],
) -> None:
    cox1 = records["Q0045"]
    assert (cox1.locus_tag, cox1.name, cox1.symbol) == ("Q0045", "COX1", "COX1")


def test_an_unnamed_orf_has_no_standard_name(records: dict[str, GeneRecord]) -> None:
    """RefSeq sets Name to the locus tag when there is no symbol, and omits `gene=` entirely."""
    orf = records["YAL067W-A"]
    assert orf.symbol is None
    assert orf.name == "YAL067W-A"


def test_dbxrefs_are_split_out(records: dict[str, GeneRecord]) -> None:
    bdh1 = records["YAL060W"]
    assert bdh1.ncbi_gene_id == "851239"
    assert bdh1.sgd_id == "S000000058"
    assert "GeneID:851239" in bdh1.dbxrefs


def test_synonyms_keep_every_value(records: dict[str, GeneRecord]) -> None:
    assert records["YDL022W"].synonyms == ("DAR1", "HOR1", "OSG1", "OSR5")


# ------------------------------------------------------------------------------- escaping


def test_an_escaped_comma_stays_inside_one_value(records: dict[str, GeneRecord]) -> None:
    """The classic GFF3 bug: unescape before splitting and this product becomes two products.

    BDH1's real RefSeq product is `(R,R)-butanediol dehydrogenase`, written `(R%2CR)-...` in the
    file, and the atlas holds the unescaped form -- so this is the round trip, not a contrivance.
    """
    bdh1 = records["YAL060W"]
    assert bdh1.description == "(R,R)-butanediol dehydrogenase"


def test_an_escaped_semicolon_does_not_end_the_attribute() -> None:
    line = (
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\t"
        "ID=gene-X;locus_tag=X;Note=drains the pool%3B competes with the route"
    )
    (record,) = parse_gene_records([line])
    assert record.description == "drains the pool; competes with the route"


def test_an_escaped_equals_survives() -> None:
    assert parse_attributes("Note=a%3Db") == {"Note": ("a=b",)}


def test_multi_value_attributes_keep_every_value() -> None:
    parsed = parse_attributes("Dbxref=GeneID:1,SGD:S1;Parent=rna-a,rna-b")
    assert parsed["Dbxref"] == ("GeneID:1", "SGD:S1")
    assert parsed["Parent"] == ("rna-a", "rna-b")


def test_an_attribute_without_an_equals_is_an_error() -> None:
    with pytest.raises(Gff3Error, match="tag=value"):
        parse_attributes("ID=gene-X;garbage")


# --------------------------------------------------------------------- children and products


def test_the_product_is_taken_from_the_child_when_the_gene_has_none(
    records: dict[str, GeneRecord],
) -> None:
    assert records["YNCA0002W"].description == "tRNA-Pro"
    assert records["Q0158"].description == "21S ribosomal RNA"


def test_exon_and_cds_counts_come_from_the_children(records: dict[str, GeneRecord]) -> None:
    assert (records["YAL003W"].exon_count, records["YAL003W"].cds_count) == (2, 2)
    assert (records["YAL060W"].exon_count, records["YAL060W"].cds_count) == (1, 1)
    assert (records["YNCA0002W"].exon_count, records["YNCA0002W"].cds_count) == (1, 0)


def test_a_grandchild_reaches_its_gene(records: dict[str, GeneRecord]) -> None:
    """A CDS's Parent is the mRNA, not the gene. Resolving only one hop loses every CDS count."""
    assert records["Q0045"].cds_count == 3


def test_a_gene_with_no_children_still_yields_a_record() -> None:
    line = "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-X;locus_tag=X"
    (record,) = parse_gene_records([line])
    assert (record.exon_count, record.cds_count, record.description) == (0, 0, None)


# ------------------------------------------------------------------------------ mitochondria


def test_mitochondrial_genes_parse_and_are_identifiable_by_seqid(
    records: dict[str, GeneRecord],
) -> None:
    """NC_001224.1 is the S288C mitochondrion. Which genome carries a gene decides which NCBI
    translation table it is read under, and `seqid` is the only thing on the record that says."""
    mito = {tag: r for tag, r in records.items() if r.seqid == "NC_001224.1"}
    assert set(mito) == {"tP(UGG)Q", "Q0045", "Q0140", "Q0158"}
    assert mito["Q0045"].symbol == "COX1"
    assert mito["Q0140"].symbol == "VAR1"
    assert mito["Q0045"].exon_count == 3  # the mosaic gene, intact


def test_parentheses_in_an_id_survive(records: dict[str, GeneRecord]) -> None:
    """NCBI writes `ID=gene-tP(UGG)Q` unescaped; a parser that unquotes too eagerly mangles it."""
    trna = records["tP(UGG)Q"]
    assert trna.gff_id == "gene-tP(UGG)Q"
    assert trna.locus_tag == "tP(UGG)Q"
    assert trna.name == "tP(UGG)Q"
    # RefSeq gives this feature no `gene=`, so it has no standard name -- NULL, not its own tag.
    assert trna.symbol is None


# ------------------------------------------------------------- directives, framing, streaming


def test_the_fixture_yields_exactly_its_genes(records: dict[str, GeneRecord]) -> None:
    assert len(records) == 14


def test_a_gene_nested_inside_another_one_is_not_lost(records: dict[str, GeneRecord]) -> None:
    """SNR18 really does sit inside EFB1's intron, so its gene feature opens while EFB1's span is
    still unclosed. Both must come out whole, with their own children."""
    efb1, snr18 = records["YAL003W"], records["YNCA0003W"]
    assert efb1.start_pos < snr18.start_pos < snr18.end_pos < efb1.end_pos
    assert (efb1.exon_count, efb1.cds_count) == (2, 2)
    assert (snr18.exon_count, snr18.cds_count) == (1, 0)
    assert snr18.description == "SNR18"


def test_region_features_are_not_genes(records: dict[str, GeneRecord]) -> None:
    assert not any(r.feature_type == "region" for r in records.values())
    assert not any(r.seqid.startswith("NC_001133.9:") for r in records.values())


def test_comments_blank_lines_and_directives_are_ignored() -> None:
    lines = [
        "##gff-version 3",
        "#!processor NCBI annotwriter",
        "",
        "##sequence-region NC_001133.9 1 230218",
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-X;locus_tag=X",
        "###",
    ]
    assert [r.locus_tag for r in parse_gene_records(lines)] == ["X"]


def test_everything_after_a_fasta_directive_is_sequence_not_features() -> None:
    lines = [
        "##gff-version 3",
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-X;locus_tag=X",
        "##FASTA",
        ">NC_001133.9",
        "ACGTACGTACGT",
    ]
    assert [r.locus_tag for r in parse_gene_records(lines)] == ["X"]


def test_a_gene_closes_without_a_separator_when_the_next_one_starts_past_it() -> None:
    """A file with no `###` at all must not accumulate; the position rule is what closes a gene."""
    lines = [
        "NC_001133.9\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-A;locus_tag=A",
        "NC_001133.9\tRefSeq\texon\t100\t200\t.\t+\t.\tID=e1;Parent=gene-A;product=alpha",
        "NC_001133.9\tRefSeq\tgene\t300\t400\t.\t-\t.\tID=gene-B;locus_tag=B",
        "NC_001133.9\tRefSeq\texon\t300\t400\t.\t-\t.\tID=e2;Parent=gene-B;product=beta",
    ]
    parsed = {r.locus_tag: r for r in parse_gene_records(lines)}
    assert parsed["A"].exon_count == 1
    assert parsed["B"].exon_count == 1
    assert parsed["A"].description == "alpha"
    assert parsed["B"].description == "beta"


def test_a_sequence_change_closes_every_open_gene() -> None:
    lines = [
        "NC_001133.9\tRefSeq\tgene\t100\t9000\t.\t+\t.\tID=gene-A;locus_tag=A",
        "NC_001134.8\tRefSeq\tgene\t100\t200\t.\t+\t.\tID=gene-B;locus_tag=B",
    ]
    assert [r.locus_tag for r in parse_gene_records(lines)] == ["A", "B"]


def test_a_wrong_column_count_is_an_error_not_a_skipped_line() -> None:
    with pytest.raises(Gff3Error, match="requires 9"):
        list(parse_gene_records(["NC_001133.9\tRefSeq\tgene\t1\t2"]))


def test_a_gene_with_nothing_to_identify_it_is_an_error() -> None:
    with pytest.raises(Gff3Error, match="ID="):
        list(parse_gene_records(["NC_001133.9\tRefSeq\tgene\t1\t2\t.\t+\t.\tgbkey=Gene"]))


def test_it_never_holds_more_than_the_open_genes(tmp_path: Path) -> None:
    """`parse_gene_records` is a generator over lines, so pulling one record must not require
    reading the file to the end. Checked by taking a single record from a handle and asserting
    the handle has not been exhausted."""
    with FIXTURE.open(encoding="utf-8") as handle:
        stream = parse_gene_records(handle)
        first = next(stream)
        assert first.locus_tag == "YAL068C"
        assert handle.read(1) != ""  # more file left: nothing was slurped


def test_a_gzipped_file_reads_the_same(tmp_path: Path) -> None:
    """RefSeq ships `.gff.gz`; the fixture is plain so it can be reviewed as a diff."""
    packed = tmp_path / "renamed-without-a-gz-suffix.gff"
    packed.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    assert [r.locus_tag for r in iter_gene_records(packed)] == [
        r.locus_tag for r in iter_gene_records(FIXTURE)
    ]
