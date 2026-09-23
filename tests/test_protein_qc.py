"""Tests for the protein translation QC gate (PLAN.md E.3).

**What these run against, stated plainly.** Synthetic fixtures, built for this purpose and checked
in under `tests/fixtures/genomics/protein_qc/`: one genome FASTA and two annotation/protein pairs,
a clean one that scores 1.000 and a broken one in which every locus is a different named failure.
They are synthetic because the atlas's own `gene` table holds 36 hand-curated rows and no CDS
model at all -- `load_genes` has never been run -- so there is no real CDS/protein pair *in this
repository* to test against. There is one on disk: the gate was run over the whole of
GCF_000146045.2 (6,027 CDS, 6,021 exact, identity 0.99900, all 19 mtDNA CDS exact under table 3)
and the result is recorded in the commit message and in `protein_qc.phase_disagreement`'s
docstring. That run is not a test here, because it needs 6 MB of files that are not in the tree
and a test that silently skips when they are absent is a test that stops running.

**The one test that matters most is `test_mitochondrial_cds_is_wrong_under_table_1`.** Every other
assertion here would still pass if this gate hard-coded NCBI table 1, which is exactly how a
mitochondrial mistranslation gets shipped: 50 of 6,386 CDS lines is 0.8%, the gate is set at 0.5%,
and the corpus passes. So the mitochondrial fixture is built so that its ORF cannot be read under
table 1 at all -- every threonine is written `CTA` and every tryptophan `TGA` -- and the test
asserts the failure directly rather than inferring it from a corpus score.

Nothing here opens a database, reaches the network, or reads anything outside `tests/fixtures`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from fermdb.genetic_code import TABLE_1, TABLE_3, translate
from fermdb.genomics.cli import cmd_genomics_protein_qc, parse_genetic_code_options
from fermdb.genomics.gff3 import Gff3Error
from fermdb.genomics.protein_qc import (
    ALTERNATIVE_START,
    AMBIGUOUS,
    DECLARED_PHASE_DISAGREES,
    EXACT,
    INTERNAL_STOP,
    MIN_PROTEIN_IDENTITY,
    MISMATCH,
    MISSING_MODEL,
    MISSING_PROTEIN,
    NO_GENETIC_CODE,
    TRAILING_STOP_TRIMMED,
    UNSUPPORTED_GENETIC_CODE,
    UNTRANSLATABLE,
    ProteinQcReport,
    ProteinVerdict,
    format_report,
    parse_annotation,
    read_genome,
    read_proteins,
    resolve_genetic_code,
    run_protein_qc,
    splice_cds,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "genomics" / "protein_qc"
GENOME = FIXTURES / "mini.fna"
CLEAN_GFF3 = FIXTURES / "mini.clean.gff3"
CLEAN_FAA = FIXTURES / "mini.clean.faa"
BROKEN_GFF3 = FIXTURES / "mini.broken.gff3"
BROKEN_FAA = FIXTURES / "mini.broken.faa"


@pytest.fixture(scope="module")
def clean() -> ProteinQcReport:
    return run_protein_qc(CLEAN_GFF3, GENOME, CLEAN_FAA)


@pytest.fixture(scope="module")
def broken() -> ProteinQcReport:
    return run_protein_qc(BROKEN_GFF3, GENOME, BROKEN_FAA)


def _by_id(report: ProteinQcReport, protein_id: str) -> ProteinVerdict:
    for verdict in report.verdicts:
        if verdict.protein_id == protein_id:
            return verdict
    seen = [v.protein_id for v in report.verdicts]
    raise AssertionError(f"no verdict for {protein_id}; got {seen}")


# ------------------------------------------------------------------------------- the constant


def test_threshold_is_the_value_carried_from_genome_db() -> None:
    """PLAN.md S.2 says QC constants are fixed before the data is seen and reviewed as a diff.

    This asserts the number rather than the mechanism, so that lowering it to make a corpus pass
    shows up as a failing test in the same commit -- which is what "reviewed as a diff" means in
    practice. 0.995 is `genome-db`'s value, quoted in E.3; the owner has final say on changing it.
    """
    assert MIN_PROTEIN_IDENTITY == 0.995


# ---------------------------------------------------------------------------- the passing corpus


def test_clean_corpus_passes(clean: ProteinQcReport) -> None:
    assert clean.checked == 5
    assert clean.exact == 5
    assert clean.identity == 1.0
    assert clean.passed is True
    assert clean.failures() == ()


def test_clean_corpus_normalisations_are_counted_not_hidden(clean: ProteinQcReport) -> None:
    """Both normalisations fire on the clean corpus, and both are visible in the counts.

    Five terminal stops trimmed (every CDS encodes one, no protein record carries one) and one
    alternative start -- YTEST04W begins `TTG`, which table 1 reads as leucine and NCBI writes as
    methionine. If either were applied silently, this corpus would look identical to one in which
    the gate simply was not comparing those positions.
    """
    counts = clean.normalisation_counts()
    assert counts[TRAILING_STOP_TRIMMED] == 5
    assert counts[ALTERNATIVE_START] == 1
    assert counts[DECLARED_PHASE_DISAGREES] == 0
    assert ALTERNATIVE_START in _by_id(clean, "NP_TEST004.1").normalisations


def test_minus_strand_gene_is_exact(clean: ProteinQcReport) -> None:
    """YTEST03C is on the minus strand. A splice that reverse-complements the segments in the
    wrong order, or takes the wrong end's phase, produces a frameshift and not an error."""
    verdict = _by_id(clean, "NP_TEST003.1")
    assert verdict.verdict == EXACT
    assert verdict.strand == -1


def test_two_exon_gene_is_exact(clean: ProteinQcReport) -> None:
    verdict = _by_id(clean, "NP_TEST002.1")
    assert verdict.verdict == EXACT
    assert verdict.segments == 2


# ------------------------------------------------------------------- the genetic code, per sequence


def test_mitochondrial_cds_is_wrong_under_table_1() -> None:
    """The gate's reason for existing, asserted directly instead of through a corpus score.

    Q0TEST1 sits on NC_TEST24.1 with `transl_table=3`. Read under table 3 it reproduces its
    protein record exactly; read under table 1 the `CTA` threonines become leucines and the `TGA`
    tryptophans become stop codons. A gate that assumed table 1 would report this ORF as a
    handful of internal stops -- or, on a real S288C annotation, would report 6,336 passes and 50
    failures and still clear a 99.5% threshold.
    """
    genome = read_genome(GENOME)
    proteins = read_proteins(CLEAN_FAA)
    annotation = parse_annotation(CLEAN_GFF3.read_text(encoding="utf-8").splitlines())
    model = next(m for m in annotation.cds if m.protein_id == "NP_TEST024.1")

    spliced = splice_cds(model, genome[model.seqid])
    reference = proteins["NP_TEST024.1"]

    assert translate(spliced, TABLE_3) == reference + "*"
    under_table_1 = translate(spliced, TABLE_1)
    assert under_table_1 != reference + "*"
    assert "*" in under_table_1[:-1], "the table-1 reading must contain internal stops"


def test_mitochondrial_table_comes_from_the_annotation(clean: ProteinQcReport) -> None:
    verdict = _by_id(clean, "NP_TEST024.1")
    assert verdict.table_id == 3
    assert verdict.code_source == "annotation"
    assert clean.sequence_codes["NC_TEST24.1"] == (3, "annotation")
    assert clean.sequence_codes["NC_TEST01.1"] == (1, "region")


def test_mitochondrial_table_falls_back_to_the_region_feature(broken: ProteinQcReport) -> None:
    """The broken annotation drops `transl_table=` from Q0TEST1 entirely. It must still be read
    under table 3, via its sequence's `region genome=mitochondrion` and the same
    encoding-genome-to-table mapping the atlas's `encoding_genome` table holds."""
    verdict = _by_id(broken, "NP_TEST024.1")
    assert verdict.verdict == EXACT
    assert verdict.table_id == 3
    assert verdict.code_source == "region"


def test_a_sequence_that_states_no_genome_is_refused_not_defaulted(broken: ProteinQcReport) -> None:
    """NC_TEST90.1's region feature carries no `genome=`, so nothing states its code.

    Its ORF is an ordinary table-1 ORF and would have translated exactly under a default. That is
    the point: the verdict is `no_genetic_code` because the gate declines to guess, not because
    the guess would have been wrong.
    """
    verdict = _by_id(broken, "NP_TEST008.1")
    assert verdict.verdict == NO_GENETIC_CODE
    assert verdict.table_id is None
    assert verdict.code_source == "none"
    assert broken.sequence_codes["NC_TEST90.1"] == (None, "none")


def test_declared_code_rescues_an_undeclared_sequence() -> None:
    report = run_protein_qc(BROKEN_GFF3, GENOME, BROKEN_FAA, declared_tables={"NC_TEST90.1": 1})
    verdict = _by_id(report, "NP_TEST008.1")
    assert verdict.verdict == EXACT
    assert verdict.code_source == "declared"
    assert report.disagreements == ()


def test_a_declaration_that_contradicts_the_annotation_loses_and_is_reported() -> None:
    """`load_genes`'s rule, applied here: conflicts are recorded, never silently resolved."""
    report = run_protein_qc(CLEAN_GFF3, GENOME, CLEAN_FAA, declared_tables={"NC_TEST24.1": 1})
    assert len(report.disagreements) == 1
    clash = report.disagreements[0]
    assert (clash.seqid, clash.declared_table, clash.annotation_table) == ("NC_TEST24.1", 1, 3)
    assert _by_id(report, "NP_TEST024.1").table_id == 3
    assert report.passed is True


def test_unsupported_table_is_refused_by_name(broken: ProteinQcReport) -> None:
    """YTEST09W declares `transl_table=11`. `fermdb.genetic_code` implements 1 and 3.

    Table 11 differs from table 1 only in its start codons, so reading it as table 1 would have
    produced an exact match for this ORF and for most bacterial genes -- which is exactly why it
    has to be refused by name. Run against the real GCF_000005845.2 this verdict fires on all
    4,300 E. coli CDS and the gate refuses the annotation outright.
    """
    verdict = _by_id(broken, "NP_TEST009.1")
    assert verdict.verdict == UNSUPPORTED_GENETIC_CODE
    assert verdict.table_id == 11
    assert "11" in verdict.detail


# ----------------------------------------------------------------------------- the failure modes


@pytest.mark.parametrize(
    ("protein_id", "expected"),
    [
        ("NP_TEST001.1", INTERNAL_STOP),  # CDS start moved one base: the off-by-one
        ("NP_TEST002.1", EXACT),  # right coordinates, wrong declared phase
        ("NP_TEST003.1", INTERNAL_STOP),  # minus-strand coordinate error
        ("NP_TEST004.1", MISMATCH),  # stale protein record, one residue apart
        ("NP_TEST005.1", INTERNAL_STOP),  # an in-frame stop mid-CDS
        ("NP_TEST006.1", AMBIGUOUS),  # NNN in the assembly
        ("NP_TEST007.1", MISSING_PROTEIN),  # annotated, absent from the FASTA
        ("NP_TEST008.1", NO_GENETIC_CODE),  # no table stated for its sequence
        ("NP_TEST009.1", UNSUPPORTED_GENETIC_CODE),  # table 11
        ("NP_TEST010.1", AMBIGUOUS),  # a TGA read through as selenocysteine
        ("NP_TEST024.1", EXACT),  # table 3 via the region feature
        ("NP_TESTORPHAN.1", MISSING_MODEL),  # a protein record no CDS produces
    ],
)
def test_every_failure_mode_gets_its_own_verdict(
    broken: ProteinQcReport, protein_id: str, expected: str
) -> None:
    assert _by_id(broken, protein_id).verdict == expected


def test_off_by_one_start_is_caught_at_the_first_residue(broken: ProteinQcReport) -> None:
    """The failure E.3 names first. One base is the whole error, and the protein FASTA is the
    only witness to it: the CDS length is still a multiple of three and every schema CHECK in
    the atlas still passes."""
    verdict = _by_id(broken, "NP_TEST001.1")
    assert verdict.verdict == INTERNAL_STOP
    assert verdict.first_mismatch == 1


def test_declared_phase_disagreement_is_counted_even_when_translation_is_exact(
    broken: ProteinQcReport,
) -> None:
    """YTEST02W's second CDS segment declares phase 0 where its own exon lengths say 1.

    The translation comes from the coordinates and is still exact, so this defect contributes
    nothing to the identity fraction and would be entirely invisible without its own count.
    """
    verdict = _by_id(broken, "NP_TEST002.1")
    assert verdict.verdict == EXACT
    assert DECLARED_PHASE_DISAGREES in verdict.normalisations
    assert broken.normalisation_counts()[DECLARED_PHASE_DISAGREES] == 1
    assert "phase 0" in verdict.detail


def test_selenocysteine_is_an_ambiguity_not_an_internal_stop(broken: ProteinQcReport) -> None:
    """YTEST10W's protein record carries `U` where the CDS has an in-frame `TGA`.

    The translation does contain a `*`, so the ordering of the classification is what decides
    this: an explanation that accounts for every difference beats one that merely accounts for
    the symptom. It is still not a pass -- `U` is a residue no table produces.
    """
    verdict = _by_id(broken, "NP_TEST010.1")
    assert verdict.verdict == AMBIGUOUS
    assert verdict.is_pass is False


def test_missing_model_is_outside_the_identity_fraction(broken: ProteinQcReport) -> None:
    """A protein record with no CDS is counted and named, but there is no CDS to re-splice, so
    E.3's "every CDS" does not reach it and it stays out of the denominator."""
    orphan = _by_id(broken, "NP_TESTORPHAN.1")
    assert orphan.from_gene_model is False
    assert broken.checked == len(broken.verdicts) - 1
    assert broken.verdict_counts()[MISSING_MODEL] == 1


def test_broken_corpus_is_refused(broken: ProteinQcReport) -> None:
    assert broken.passed is False
    assert broken.identity < MIN_PROTEIN_IDENTITY
    assert broken.exact == 2


# ------------------------------------------------------------------------------ refusing to guess


def test_a_corpus_with_no_cds_is_refused(tmp_path: Path) -> None:
    """Zero of zero is not 100%. A gate that returns "pass" for a file it never read is worse
    than no gate, because it produces the evidence that the ingest was checked."""
    empty = tmp_path / "empty.gff3"
    empty.write_text("##gff-version 3\n", encoding="utf-8")
    report = run_protein_qc(empty, GENOME, CLEAN_FAA)
    assert report.checked == 0
    assert report.identity == 0.0
    assert report.passed is False
    assert "REFUSED" in "\n".join(format_report(report))


def test_a_cds_whose_sequence_is_absent_is_untranslatable(tmp_path: Path) -> None:
    """The annotation and the genome FASTA are not the same assembly. Reported, not crashed on."""
    partial = tmp_path / "partial.fna"
    genome = read_genome(GENOME)
    partial.write_text(f">NC_TEST01.1\n{genome['NC_TEST01.1']}\n", encoding="utf-8")
    report = run_protein_qc(CLEAN_GFF3, partial, CLEAN_FAA)
    verdict = _by_id(report, "NP_TEST024.1")
    assert verdict.verdict == UNTRANSLATABLE
    assert "NC_TEST24.1" in verdict.detail


def test_duplicate_fasta_ids_are_refused(tmp_path: Path) -> None:
    """With two records under one id there is no way to say which one a verdict was measured
    against, so every verdict from the file would be unattributable."""
    doubled = tmp_path / "doubled.faa"
    doubled.write_text(">NP_X.1\nMKV\n>NP_X.1\nMKW\n", encoding="utf-8")
    with pytest.raises(Gff3Error, match="duplicate record id"):
        read_proteins(doubled)


def test_a_cds_with_no_identifying_attribute_is_an_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.gff3"
    bad.write_text(
        "##gff-version 3\nNC_TEST01.1\tf\tCDS\t1\t9\t.\t+\t0\tgbkey=CDS\n", encoding="utf-8"
    )
    with pytest.raises(Gff3Error, match="protein_id"):
        run_protein_qc(bad, GENOME, CLEAN_FAA)


def test_cds_phase_must_be_stated(tmp_path: Path) -> None:
    """GFF3 requires 0, 1 or 2 on a CDS. A `.` is not quietly read as 0 -- that is a two-thirds
    chance of a frameshift taken silently."""
    bad = tmp_path / "bad.gff3"
    bad.write_text(
        "##gff-version 3\nNC_TEST01.1\tf\tCDS\t1\t9\t.\t+\t.\tprotein_id=NP_X.1\n",
        encoding="utf-8",
    )
    with pytest.raises(Gff3Error, match="phase"):
        run_protein_qc(bad, GENOME, CLEAN_FAA)


def test_resolution_detail_names_what_was_missing() -> None:
    annotation = parse_annotation(BROKEN_GFF3.read_text(encoding="utf-8").splitlines())
    model = next(m for m in annotation.cds if m.protein_id == "NP_TEST008.1")
    resolution = resolve_genetic_code(model, annotation.sequence_genome, {})
    assert resolution.table_id is None
    assert "genome=" in resolution.detail


# ----------------------------------------------------------------------------------- the reports


def test_report_lists_every_verdict_name_including_the_zeroes(clean: ProteinQcReport) -> None:
    """So a reader can tell "none of these happened" from "this gate does not look for that"."""
    text = "\n".join(format_report(clean))
    for name in (EXACT, MISMATCH, INTERNAL_STOP, AMBIGUOUS, UNTRANSLATABLE, MISSING_MODEL):
        assert name in text
    assert "PASS" in text


def test_report_names_the_failures_not_just_their_count(broken: ProteinQcReport) -> None:
    text = "\n".join(format_report(broken))
    assert "NP_TEST007.1" in text
    assert "REFUSED" in text
    assert "S.2" in text, "the report has to say why lowering the threshold is not the fix"


def test_json_payload_is_complete(broken: ProteinQcReport) -> None:
    payload = broken.as_json()
    assert payload["passed"] is False
    assert len(payload["failures"]) == len(broken.failures())
    assert payload["sequence_genetic_codes"]["NC_TEST90.1"] == {"table_id": None, "source": "none"}
    assert json.dumps(payload)  # every value survives a round trip to the wire


def test_human_report_truncates_and_says_so(broken: ProteinQcReport) -> None:
    text = "\n".join(format_report(broken, max_detail=2))
    assert "--json lists every one" in text


# --------------------------------------------------------------------------------------- the CLI


def _args(gff3: Path, genome: Path, proteins: Path, **kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(
        gff3=str(gff3),
        genome=str(genome),
        proteins=str(proteins),
        genetic_code=kwargs.get("genetic_code"),
        json=kwargs.get("json", False),
    )


def test_cli_exits_zero_on_a_passing_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_genomics_protein_qc(_args(CLEAN_GFF3, GENOME, CLEAN_FAA)) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_exits_one_on_a_refused_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    """E.3 says *refuse the ingest*. A warning that exits 0 is not a refusal, and a caller
    piping this into a load script would never know."""
    assert cmd_genomics_protein_qc(_args(BROKEN_GFF3, GENOME, BROKEN_FAA)) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_cli_json_still_exits_one_on_a_refused_corpus(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` chooses the output format, not the verdict."""
    assert cmd_genomics_protein_qc(_args(BROKEN_GFF3, GENOME, BROKEN_FAA, json=True)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["source"]["gff3"] == str(BROKEN_GFF3)


def test_cli_exits_two_when_the_run_never_happened(capsys: pytest.CaptureFixture[str]) -> None:
    """2, not 1. Conflating "this file is not here" with "this genome is wrong" would let a
    typo in a path read as a refused ingest, or worse be retried as one."""
    assert cmd_genomics_protein_qc(_args(FIXTURES / "nope.gff3", GENOME, CLEAN_FAA)) == 2
    assert "no such gff3 file" in capsys.readouterr().err


def test_cli_rejects_an_unreadable_genetic_code_option(capsys: pytest.CaptureFixture[str]) -> None:
    args = _args(CLEAN_GFF3, GENOME, CLEAN_FAA, genetic_code=["NC_TEST90.1=7"])
    assert cmd_genomics_protein_qc(args) == 2
    assert "implements tables" in capsys.readouterr().err


def test_genetic_code_option_parsing() -> None:
    assert parse_genetic_code_options(["NC_001224.1=3", " NC_X.1 =1"]) == {
        "NC_001224.1": 3,
        "NC_X.1": 1,
    }
    assert parse_genetic_code_options(None) == {}
    for bad in ("NC_001224.1", "=3", "NC_001224.1=three", "NC_001224.1=11"):
        with pytest.raises(ValueError, match="genetic-code"):
            parse_genetic_code_options([bad])
