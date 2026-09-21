"""Tests for the recoder and the compartment safety gate.

The property that matters most is round-trip protein identity: recoding must never change the
protein. That is asserted for every mode on randomised sequences, because a hand-picked example
would not have found the cases that matter.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from fermdb.config import Settings
from fermdb.genetic_code import (
    TABLE_1,
    TABLE_3,
    AmbiguousCompartmentError,
    at_fraction,
    codons_of,
    diff_tables,
    translate,
)
from fermdb.recode import (
    RECODING_CONTROLS_FILE,
    RecodeError,
    RecodingControl,
    RecodingControlError,
    check_compartment_safety,
    codons_for,
    compare_codons,
    dual_safe_codons,
    load_recoding_comparison,
    load_recoding_controls,
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


# ------------------------------------------------ the published control (PLAN.md Q, phase 0)
#
# The last open clause of phase 0's acceptance: "the recoder round-trips a known mitochondrial
# gene and reproduces the published recoded marker sequence for a control". It had never run,
# because the control is ARG8m and no paper in this project's corpus prints its sequence
# (docs/drafts/warnings/PLAN.yaml line 2387). It was fetched from GenBank instead -- U31093.1,
# Steele/Butler/Fox, PNAS 93:5253-5257 (1996) -- into data/mitochondria/recoding_controls.yaml.
#
# The two halves are tested separately because they have different answers. The round-trip half
# passes outright. The reproduction half does NOT: the recoder encodes the identical protein but
# chooses different synonymous codons at 206 of 424 positions, because it recodes minimally while
# Fox re-optimized the whole ORF to the mitochondrial codon bias. That is asserted below as a
# precise, enumerated census rather than waved away, and the data file explains it at length.


@pytest.fixture(scope="module")
def controls() -> dict[str, RecodingControl]:
    return load_recoding_controls(Settings.load())


@pytest.fixture(scope="module")
def census() -> dict[str, Any]:
    return load_recoding_comparison(Settings.load())


def test_published_controls_load_and_match_their_checksums(
    controls: dict[str, RecodingControl],
) -> None:
    """The loader verifies sha256 and declared length on every read; this is that check firing."""
    assert set(controls) == {"cox3_arg8m_fusion_cds", "arg8m_orf", "arg8_nuclear_cds"}
    assert controls["cox3_arg8m_fusion_cds"].accession == "U31093.1"
    assert controls["arg8m_orf"].accession == "U31093.1"
    assert controls["arg8_nuclear_cds"].accession == "NM_001183394.1"
    for control in controls.values():
        assert set(control.sequence) <= set("ACGT")  # no ambiguity codes to resolve
        assert len(control.sequence) % 3 == 0
        assert control.confidence == "high"
        assert control.source_url.startswith("https://eutils.ncbi.nlm.nih.gov/")


def test_stored_proteins_are_ncbis_translation_not_ours(
    controls: dict[str, RecodingControl],
) -> None:
    """`protein` is the GenBank /translation verbatim, so the round-trip test is not circular.

    If this project's `translate` had written these strings, the next test would be checking
    `translate` against itself. The two independent records agreeing -- AAC53660.1's residues
    10-432 against NP_014501.1 in full -- is what makes them usable as ground truth.
    """
    fusion = controls["cox3_arg8m_fusion_cds"]
    orf = controls["arg8m_orf"]
    nuclear = controls["arg8_nuclear_cds"]
    assert fusion.protein_accession == "AAC53660.1"
    assert nuclear.protein_accession == "NP_014501.1"
    assert orf.protein_accession is None  # a sub-region; it has no protein record of its own
    assert fusion.protein[9:] == orf.protein  # the nine-codon COX3 leader is the only difference
    assert orf.protein == nuclear.protein  # recoded and nuclear genes encode the same protein


def test_recoder_round_trips_a_known_mitochondrial_gene(
    controls: dict[str, RecodingControl],
) -> None:
    """First half of the phase-0 clause, on the real cox3::ARG8m CDS from U31093.1.

    Four things, in order of how badly each would hurt: the gene translates under table 3 to
    NCBI's own /translation; it does NOT under table 1, so the table genuinely matters here; every
    codon is assigned and no stop appears internally; and recoding it out to the nucleus and back
    into the matrix returns the same protein both times.
    """
    fusion = controls["cox3_arg8m_fusion_cds"]
    assert fusion.translation_table == 3
    assert fusion.encoding_genome == "mitochondrial"

    # Table 3 reproduces NCBI's curated translation exactly; table 1 does not.
    assert translate(fusion.sequence, TABLE_3) == fusion.protein + "*"
    assert translate(fusion.sequence, TABLE_1) != fusion.protein + "*"

    protein = translate(fusion.sequence, TABLE_3)
    assert len(protein) - 1 == fusion.protein_length_aa
    assert "X" not in protein, "an unassigned codon in a published mitochondrial CDS"
    assert "*" not in protein[:-1], "an internal stop under the table the gene is read by"

    # Out to the nucleus (table 3 -> table 1) and back in (table 1 -> table 3). The protein must
    # survive both legs, and the outbound leg must clear the internal TGAs that would terminate
    # translation on a cytosolic ribosome.
    outbound = recode(fusion.sequence, source_table=3, mode="to_table1")
    assert outbound.protein == fusion.protein + "*"
    assert translate(outbound.sequence, TABLE_1) == fusion.protein + "*"
    assert "TGA" not in codons_of(outbound.sequence)[:-1]

    inbound = recode(outbound.sequence, source_table=1, mode="to_table3")
    assert translate(inbound.sequence, TABLE_3) == fusion.protein + "*"
    assert [c for c in codons_of(inbound.sequence) if c.startswith("CT")] == []
    assert check_compartment_safety(
        inbound.sequence, "mitochondrial_matrix", encoding_genome="mitochondrial"
    ).accepted


def test_published_arg8m_is_legal_for_mtdna_but_is_not_dual_safe(
    controls: dict[str, RecodingControl], census: dict[str, Any]
) -> None:
    """A fact about the published marker, checked rather than assumed.

    ARG8m clears the phase-0 compartment gate -- no CUN, no terminal TGA, no CGA/CGC -- but it is
    NOT portable back to the cytosol: two internal TGA codons read as tryptophan in the matrix and
    as STOP on a cytosolic ribosome, which would truncate the marker at residue 167.
    """
    orf = controls["arg8m_orf"]
    report = check_compartment_safety(
        orf.sequence, "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert report.accepted
    assert report.table_id == 3
    assert report.cun_codons == []
    assert report.absent_codons == []
    assert any("internal TGA" in r for r in report.reasons)

    internal_tga = [i + 1 for i, c in enumerate(codons_of(orf.sequence)[:-1]) if c == "TGA"]
    assert internal_tga == census["published_internal_tga_positions"]
    assert len(internal_tga) == census["published_internal_tga_codons"]
    assert [d.codon for d in diff_tables(orf.sequence)] == ["TGA", "TGA"]
    assert translate(orf.sequence, TABLE_1).index("*") == internal_tga[0] - 1


def test_nuclear_arg8_is_rejected_for_mtdna(
    controls: dict[str, RecodingControl], census: dict[str, Any]
) -> None:
    """The phase-0 gate on a real gene instead of a synthetic CTG run: ARG8 has 12 CUN codons."""
    nuclear = controls["arg8_nuclear_cds"]
    report = check_compartment_safety(
        nuclear.sequence, "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert not report.accepted
    assert len(report.cun_codons) == census["nuclear_cun_codons"]
    assert len(report.absent_codons) == census["nuclear_absent_in_mito_codons"]
    # ...and the same sequence is perfectly fine as a nuclear-encoded, imported matrix protein,
    # which is exactly what ARG8 natively is.
    assert check_compartment_safety(
        nuclear.sequence, "mitochondrial_matrix", encoding_genome="nuclear"
    ).accepted


def test_recoder_reproduces_the_published_markers_protein_exactly(
    controls: dict[str, RecodingControl],
) -> None:
    """Second half of the clause, the part that passes: the protein is reproduced exactly."""
    nuclear = controls["arg8_nuclear_cds"]
    orf = controls["arg8m_orf"]
    result = recode(nuclear.sequence, source_table=1, mode="to_table3")
    assert result.protein == nuclear.protein + "*"
    assert translate(result.sequence, TABLE_3) == orf.protein + "*"
    assert translate(result.sequence, TABLE_3) == translate(orf.sequence, TABLE_3)
    # ...and the recoder's output clears the gate the nuclear input failed.
    report = check_compartment_safety(
        result.sequence, "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert report.accepted
    assert report.cun_codons == []
    assert report.absent_codons == []


def test_recoder_does_not_reproduce_the_published_arg8m_codons(
    controls: dict[str, RecodingControl], census: dict[str, Any]
) -> None:
    """THE FINDING. Second half of the clause, the part that does not pass -- stated exactly.

    This test deliberately does not assert equality and does not assert a loose "close enough"
    either. It pins the census recorded in data/mitochondria/recoding_controls.yaml, so that the
    day someone changes the recoder's codon ranking, this fails and they have to look at why.

    What the numbers say: same protein, same legality, 206 of 424 codons chosen differently --
    because `recode` keeps an already-acceptable codon (a minimal recode, 20 codons changed) while
    Steele/Butler/Fox re-optimized the whole ORF to the mitochondrial codon bias.
    """
    nuclear = controls["arg8_nuclear_cds"]
    orf = controls["arg8m_orf"]
    result = recode(nuclear.sequence, source_table=1, mode="to_table3")

    assert census["reproduces_exactly"] is False
    comparison = compare_codons(result.sequence, orf.sequence, TABLE_3)
    assert not comparison.is_identical, (
        "the recoder now reproduces published ARG8m exactly -- that is a change worth "
        "celebrating, but the recorded census in data/mitochondria/recoding_controls.yaml "
        "says otherwise and must be updated deliberately"
    )
    assert comparison.total_codons == census["total_codons"]
    assert comparison.identical_codons == census["identical_codons"]
    assert len(comparison.differing_positions) == census["differing_codons"]
    assert comparison.identical_nucleotides == census["identical_nucleotides"]
    assert result.changed == census["codons_changed_from_input"]

    # Every single difference is synonymous: the two sequences never disagree about the protein.
    assert comparison.encodes_the_same_protein
    assert comparison.substitution_positions == ()
    assert len(comparison.synonymous_positions) == census["synonymous_differences"]


def test_every_arg8m_disagreement_is_a_codon_the_recoder_would_itself_accept(
    controls: dict[str, RecodingControl], census: dict[str, Any]
) -> None:
    """The disagreement is about preference only -- never about legality under table 3.

    At all 206 differing positions the published codon is inside the recoder's own candidate set
    for that residue; it simply is not the recoder's first choice. That is what makes this a
    policy difference rather than a bug, and the distinction is the whole reason the clause could
    not simply be relaxed to "protein matches".
    """
    nuclear = controls["arg8_nuclear_cds"]
    published = codons_of(controls["arg8m_orf"].sequence)
    ours = codons_of(recode(nuclear.sequence, source_table=1, mode="to_table3").sequence)

    acceptable = 0
    for index in compare_codons("".join(ours), "".join(published), TABLE_3).differing_positions:
        residue = TABLE_3.codon_to_aa[published[index]]
        assert TABLE_3.codon_to_aa[ours[index]] == residue
        if published[index] in codons_for(residue, TABLE_3):
            acceptable += 1
    assert acceptable == census["published_codon_acceptable_to_recoder"]


def test_the_recoder_is_less_at_rich_than_the_published_marker(
    controls: dict[str, RecodingControl], census: dict[str, Any]
) -> None:
    """The measurable consequence of recoding minimally, and the reason the codons differ.

    `_rank` prefers AT-rich synonyms, but `recode` only ever consults it for a codon it has to
    change -- so the output keeps the nuclear gene's codon bias almost everywhere and lands far
    short of the published marker. `test_at_content_does_not_fall` above could not have caught
    this, because AT content does rise; it just barely rises.
    """
    nuclear = controls["arg8_nuclear_cds"]
    published = controls["arg8m_orf"]
    result = recode(nuclear.sequence, source_table=1, mode="to_table3")

    assert at_fraction(nuclear.sequence) == pytest.approx(census["at_fraction_input"], abs=5e-5)
    assert at_fraction(result.sequence) == pytest.approx(census["at_fraction_recoded"], abs=5e-5)
    assert at_fraction(published.sequence) == pytest.approx(
        census["at_fraction_published"], abs=5e-5
    )
    assert at_fraction(nuclear.sequence) < at_fraction(result.sequence)
    assert at_fraction(result.sequence) < at_fraction(published.sequence)


def test_dual_safe_mode_refuses_the_published_markers_two_tga_codons(
    controls: dict[str, RecodingControl],
) -> None:
    """The one place the recoder is strictly stricter than the published marker, and right to be.

    ARG8m's internal TGAs make it mitochondria-only. `dual_safe` produces a sequence encoding the
    same protein that is legal in both compartments -- which is what MITOCHONDRIAL_PROGRAM.md §4's
    strategy C versus strategy E comparison needs from one construct.
    """
    nuclear = controls["arg8_nuclear_cds"]
    result = recode(nuclear.sequence, mode="dual_safe")
    assert result.is_dual_safe
    assert translate(result.sequence, TABLE_1) == translate(result.sequence, TABLE_3)
    assert translate(result.sequence, TABLE_3) == controls["arg8m_orf"].protein + "*"
    assert "TGA" not in codons_of(result.sequence)
    assert not diff_tables(result.sequence)


# ------------------------------------------------------- the control loader's own error paths


def test_compare_codons_refuses_to_align(controls: dict[str, RecodingControl]) -> None:
    with pytest.raises(RecodeError, match="does not align"):
        compare_codons(
            controls["arg8m_orf"].sequence,
            controls["cox3_arg8m_fusion_cds"].sequence,
            TABLE_3,
        )


def test_a_tampered_control_sequence_is_fatal(tmp_path: Path) -> None:
    """A drifted control would let the acceptance test pass against a different sequence."""
    original = (
        Path(Settings.load().repo_root) / "data" / "mitochondria" / RECODING_CONTROLS_FILE
    ).read_text(encoding="utf-8")
    tampered = tmp_path / "recoding_controls.yaml"
    tampered.write_text(original.replace("ATGACACATTTAGAAAGA", "ATGACACATTTAGAAAGG", 1), "utf-8")
    with pytest.raises(RecodingControlError, match="checksum mismatch"):
        load_recoding_controls(Settings.load(), path=tampered)


def test_a_control_whose_length_disagrees_with_its_sequence_is_fatal(tmp_path: Path) -> None:
    original = (
        Path(Settings.load().repo_root) / "data" / "mitochondria" / RECODING_CONTROLS_FILE
    ).read_text(encoding="utf-8")
    bad = tmp_path / "recoding_controls.yaml"
    bad.write_text(original.replace("length_nt: 1299", "length_nt: 1300", 1), encoding="utf-8")
    with pytest.raises(RecodingControlError, match="length_nt says 1300"):
        load_recoding_controls(Settings.load(), path=bad)


def test_a_missing_control_file_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(RecodingControlError, match="not generated"):
        load_recoding_controls(Settings.load(), path=tmp_path / "absent.yaml")


def test_a_control_file_without_sequences_is_fatal(tmp_path: Path) -> None:
    empty = tmp_path / "recoding_controls.yaml"
    empty.write_text("version: 1\nzone: R\nsequences: []\n", encoding="utf-8")
    with pytest.raises(RecodingControlError, match="non-empty list"):
        load_recoding_controls(Settings.load(), path=empty)
    with pytest.raises(RecodingControlError, match="'comparison' must be a mapping"):
        load_recoding_comparison(Settings.load(), path=empty)
