"""Tests for the genetic code tables.

The tables are the foundation of the compartment model, so they are checked against
independently-stated biological facts rather than against the strings they were built from.
"""

from __future__ import annotations

import pytest

from fermdb.genetic_code import (
    AMBIGUOUS_CODONS,
    CODONS,
    COMPARTMENT_ENCODING_GENOMES,
    ENCODING_GENOME_TABLE,
    TABLE_1,
    TABLE_3,
    AmbiguousCompartmentError,
    at_fraction,
    diff_tables,
    table_for_compartment,
    table_for_encoding_genome,
    translate,
)


def test_sixty_four_codons_no_duplicates() -> None:
    assert len(CODONS) == 64
    assert len(set(CODONS)) == 64


def test_codon_order_matches_ncbi_layout() -> None:
    # Base 1 slowest, base 3 fastest.
    assert CODONS[0] == "TTT"
    assert CODONS[1] == "TTC"
    assert CODONS[4] == "TCT"
    assert CODONS[16] == "CTT"
    assert CODONS[-1] == "GGG"


@pytest.mark.parametrize(
    ("codon", "aa"),
    [("TTT", "F"), ("ATG", "M"), ("TGG", "W"), ("TAA", "*"), ("TAG", "*"), ("TGA", "*")],
)
def test_standard_code_landmarks(codon: str, aa: str) -> None:
    assert TABLE_1.codon_to_aa[codon] == aa


@pytest.mark.parametrize(
    ("codon", "aa"),
    [
        ("TGA", "W"),  # stop in the standard code
        ("ATA", "M"),  # isoleucine in the standard code
        ("CTT", "T"),  # the CUN block: leucine in the standard code
        ("CTC", "T"),
        ("CTA", "T"),
        ("CTG", "T"),
        ("TAA", "*"),  # still a stop
        ("TAG", "*"),
        ("ATG", "M"),
    ],
)
def test_yeast_mitochondrial_code_landmarks(codon: str, aa: str) -> None:
    assert TABLE_3.codon_to_aa[codon] == aa


def test_exactly_six_codons_differ() -> None:
    assert set(AMBIGUOUS_CODONS) == {"TGA", "ATA", "CTT", "CTC", "CTA", "CTG"}


def test_cun_block_is_the_dangerous_difference() -> None:
    # Every CUN codon is leucine in the nucleus and threonine in the matrix.
    for codon in ("CTT", "CTC", "CTA", "CTG"):
        assert TABLE_1.codon_to_aa[codon] == "L"
        assert TABLE_3.codon_to_aa[codon] == "T"


def test_stop_codons_per_table() -> None:
    assert {c for c in CODONS if TABLE_1.codon_to_aa[c] == "*"} == {"TAA", "TAG", "TGA"}
    assert {c for c in CODONS if TABLE_3.codon_to_aa[c] == "*"} == {"TAA", "TAG"}


def test_every_amino_acid_is_encodable_in_both_tables() -> None:
    for table in (TABLE_1, TABLE_3):
        for aa in set(table.codon_to_aa.values()):
            assert table.synonyms(aa), f"table {table.table_id} cannot encode {aa}"


def test_translate_handles_partial_trailing_codon() -> None:
    assert translate("ATGATGA", TABLE_1) == "MM"  # trailing "A" discarded


def test_translate_to_stop() -> None:
    assert translate("ATGAAATAAATG", TABLE_1, to_stop=True) == "MK"


def test_translate_unknown_base_is_x() -> None:
    assert translate("ATGNNN", TABLE_1) == "MX"


def test_rna_input_is_accepted() -> None:
    assert translate("AUGUUU", TABLE_1) == "MF"


def test_same_sequence_two_proteins() -> None:
    # The whole point of the compartment model, in one assertion.
    seq = "ATGCTTCTGATATGA"
    assert translate(seq, TABLE_1) == "MLLI*"
    assert translate(seq, TABLE_3) == "MTTMW"


def test_diff_tables_finds_the_ambiguous_codons() -> None:
    diffs = diff_tables("ATGCTTCTGATATGA")
    assert [d.codon for d in diffs] == ["CTT", "CTG", "ATA", "TGA"]
    assert [d.index for d in diffs] == [1, 2, 3, 4]


def test_diff_tables_empty_for_dual_safe_sequence() -> None:
    assert diff_tables("ATGTTATTGACTAAATAA") == []


def test_compartment_lookup() -> None:
    assert table_for_compartment("cytosol").table_id == 1
    # The matrix holds proteins from both genomes, so the compartment alone does not decide.
    assert table_for_compartment("mitochondrial_matrix", "nuclear").table_id == 1
    assert table_for_compartment("mitochondrial_matrix", "mitochondrial").table_id == 3


def test_encoding_genome_decides_the_table() -> None:
    assert table_for_encoding_genome("nuclear").table_id == 1
    assert table_for_encoding_genome("mitochondrial").table_id == 3
    assert ENCODING_GENOME_TABLE == {"nuclear": 1, "mitochondrial": 3}


def test_ims_is_nuclear_only() -> None:
    # Corrected under D1: the old model filed the IMS under table 3, which was wrong.
    assert COMPARTMENT_ENCODING_GENOMES["mitochondrial_ims"] == ("nuclear",)
    assert table_for_compartment("mitochondrial_ims").table_id == 1


def test_dual_genome_compartment_is_ambiguous_without_the_genome() -> None:
    for compartment in ("mitochondrial_matrix", "mitochondrial_inner_membrane"):
        assert COMPARTMENT_ENCODING_GENOMES[compartment] == ("nuclear", "mitochondrial")
        with pytest.raises(AmbiguousCompartmentError, match="both genomes"):
            table_for_compartment(compartment)


def test_genome_not_served_by_the_compartment_is_rejected() -> None:
    with pytest.raises(ValueError, match="holds no 'mitochondrial'-encoded proteins"):
        table_for_compartment("cytosol", "mitochondrial")


def test_unknown_compartment_raises_rather_than_defaulting() -> None:
    with pytest.raises(KeyError, match="unknown compartment"):
        table_for_compartment("unknown")
    with pytest.raises(KeyError):
        table_for_compartment("mitochondria")  # not the canonical name


def test_at_fraction() -> None:
    assert at_fraction("AATT") == 1.0
    assert at_fraction("GGCC") == 0.0
    assert at_fraction("ATGC") == 0.5
    assert at_fraction("") == 0.0
    assert at_fraction("NNNN") == 0.0
