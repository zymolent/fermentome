"""Tests for the recoder and the compartment safety gate.

The property that matters most is round-trip protein identity: recoding must never change the
protein. That is asserted for every mode on randomised sequences, because a hand-picked example
would not have found the cases that matter.
"""

from __future__ import annotations

import random

import pytest

from fermdb.genetic_code import TABLE_1, TABLE_3, AmbiguousCompartmentError, translate
from fermdb.recode import (
    RecodeError,
    check_compartment_safety,
    dual_safe_codons,
    recode,
)


def _random_cds(rng: random.Random, n_codons: int = 40) -> str:
    """A random CDS: ATG start, no internal stop, TAA stop — valid under table 1."""
    sense = [c for c in TABLE_1.codon_to_aa if TABLE_1.codon_to_aa[c] != "*"]
    return "ATG" + "".join(rng.choice(sense) for _ in range(n_codons)) + "TAA"


# --------------------------------------------------------------------------- dual-safe codons


def test_every_amino_acid_has_a_dual_safe_codon() -> None:
    for aa in set(TABLE_1.codon_to_aa.values()):
        assert dual_safe_codons(aa), f"{aa} has no dual-safe codon"


def test_dual_safe_choices_for_the_awkward_residues() -> None:
    # Leucine cannot use CUN, because that is threonine in the matrix.
    assert set(dual_safe_codons("L")) == {"TTA", "TTG"}
    # Isoleucine cannot use ATA, because that is methionine in the matrix.
    assert set(dual_safe_codons("I")) == {"ATT", "ATC"}
    # Tryptophan cannot use TGA, because that is a stop in the cytosol.
    assert set(dual_safe_codons("W")) == {"TGG"}
    # Stop cannot use TGA, because that is tryptophan in the matrix.
    assert set(dual_safe_codons("*")) == {"TAA", "TAG"}


def test_dual_safe_prefers_at_rich_codons() -> None:
    assert dual_safe_codons("L")[0] == "TTA"  # 3 A/T, over TTG's 2
    assert dual_safe_codons("I")[0] == "ATT"


def test_absent_yeast_mito_codons_are_deprioritised() -> None:
    arg = dual_safe_codons("R")
    assert "CGA" not in arg[:2] and "CGC" not in arg[:2]


# --------------------------------------------------------------------------- protein identity


@pytest.mark.parametrize("mode", ["dual_safe", "to_table3", "to_table1"])
def test_recoding_preserves_the_protein(mode: str) -> None:
    rng = random.Random(20260919)
    for _ in range(200):
        cds = _random_cds(rng)
        result = recode(cds, source_table=1, mode=mode)
        target = TABLE_3 if mode == "to_table3" else TABLE_1
        assert translate(result.sequence, target) == result.protein
        assert result.protein == translate(cds, TABLE_1)


def test_dual_safe_output_is_table_independent() -> None:
    rng = random.Random(7)
    for _ in range(100):
        result = recode(_random_cds(rng), mode="dual_safe")
        assert result.is_dual_safe
        assert translate(result.sequence, TABLE_1) == translate(result.sequence, TABLE_3)


def test_recoding_from_table_3_back_to_the_nucleus() -> None:
    # An mtDNA-style ORF: CTT is threonine, TGA is tryptophan, ATA is methionine.
    mito = "ATGCTTTGAATATAA"
    assert translate(mito, TABLE_3) == "MTWM*"
    result = recode(mito, source_table=3, mode="to_table1")
    assert translate(result.sequence, TABLE_1) == "MTWM*"
    assert "TGA" not in [result.sequence[i : i + 3] for i in range(0, len(result.sequence) - 3, 3)]


def test_unchanged_codons_are_left_alone() -> None:
    # Already dual-safe: nothing should move.
    seq = "ATGTTAACTAAATAA"
    result = recode(seq, mode="dual_safe")
    assert result.sequence == seq
    assert result.changed == 0


def test_at_content_does_not_fall() -> None:
    rng = random.Random(11)
    for _ in range(50):
        result = recode(_random_cds(rng), mode="dual_safe")
        assert result.at_after >= result.at_before - 1e-9


# --------------------------------------------------------------------------- error handling


def test_empty_sequence_rejected() -> None:
    with pytest.raises(RecodeError, match="empty"):
        recode("AT")


def test_ambiguity_codes_rejected_with_position() -> None:
    with pytest.raises(RecodeError, match="codon 2"):
        recode("ATGNNNTAA")


def test_bad_mode_and_table_rejected() -> None:
    with pytest.raises(RecodeError, match="unknown mode"):
        recode("ATGTAA", mode="sideways")
    with pytest.raises(RecodeError, match="unsupported source_table"):
        recode("ATGTAA", source_table=11)


def test_missing_stop_is_reported_not_raised() -> None:
    result = recode("ATGTTA", mode="dual_safe")
    assert any("stop codon" in n for n in result.notes)


# --------------------------------------------------------------------------- the phase-0 gate


def test_unrecoded_cun_run_is_rejected_for_the_matrix() -> None:
    """PLAN.md Q phase 0 acceptance criterion, stated as a test.

    The criterion applies to a sequence going *into mtDNA*. A presequence-targeted construct is
    nuclear-encoded and is covered by the test below.
    """
    leucine_rich = "ATG" + "CTG" * 6 + "TAA"
    report = check_compartment_safety(
        leucine_rich, "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert not report.accepted
    assert len(report.cun_codons) == 6
    assert any("threonine" in r for r in report.reasons)


def test_nuclear_encoded_matrix_construct_needs_no_recoding() -> None:
    """D1: Ilv2/Ilv5/Ilv3 are nuclear-encoded and imported; table 1 applies, so no recoding."""
    leucine_rich = "ATG" + "CTG" * 6 + "TAA"
    report = check_compartment_safety(
        leucine_rich, "mitochondrial_matrix", encoding_genome="nuclear"
    )
    assert report.accepted
    assert report.table_id == 1
    assert report.encoding_genome == "nuclear"


def test_matrix_without_an_encoding_genome_raises() -> None:
    with pytest.raises(AmbiguousCompartmentError, match="both genomes"):
        check_compartment_safety("ATGTTATAA", "mitochondrial_matrix")


def test_the_same_sequence_is_fine_in_the_cytosol() -> None:
    leucine_rich = "ATG" + "CTG" * 6 + "TAA"
    report = check_compartment_safety(leucine_rich, "cytosol")
    assert report.accepted
    assert any("not portable" in r for r in report.reasons)


def test_terminal_tga_rejected_for_the_matrix() -> None:
    report = check_compartment_safety(
        "ATGTTATGA", "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert not report.accepted
    assert any("tryptophan" in r for r in report.reasons)


def test_recoded_sequence_passes_the_gate() -> None:
    leucine_rich = "ATG" + "CTG" * 6 + "TAA"
    recoded = recode(leucine_rich, mode="dual_safe").sequence
    report = check_compartment_safety(
        recoded, "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert report.accepted
    assert report.cun_codons == []
    # and it still encodes the same protein
    assert translate(recoded, TABLE_3) == translate(leucine_rich, TABLE_1)


def test_dual_safe_sequence_accepted_everywhere() -> None:
    seq = "ATGTTAACTAAATAA"
    for compartment, genome in (
        ("cytosol", None),
        ("mitochondrial_matrix", "nuclear"),
        ("mitochondrial_matrix", "mitochondrial"),
        ("mitochondrial_ims", None),
        ("peroxisome", None),
    ):
        assert check_compartment_safety(seq, compartment, encoding_genome=genome).accepted


def test_cga_cgc_flagged_but_not_fatal() -> None:
    report = check_compartment_safety(
        "ATGCGATAA", "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert report.accepted
    assert report.absent_codons == [1]
    assert any("absent from native yeast mtDNA" in r for r in report.reasons)
