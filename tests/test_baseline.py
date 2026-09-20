"""Tests for `fermdb.omics.baseline`.

The property that matters most here is negative: the baseline must not let a mitochondrial rRNA
be read as evidence about mitochondrial enzyme expression. A first pass at this analysis was
about to report `Q0020` and `Q0158` — the 15S and 21S ribosomal RNAs — as "mitochondrial genes
are lowly expressed", when in fact every mtDNA protein-coding gene is absent from the
transcriptome the index was built from and was never measured at all.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from fermdb.omics import baseline as B

HEADER = (
    ">lcl|{acc}_mrna_{n} [gene={gene}] [locus_tag={locus}] [product=p] [gbkey={kind}] "
    "[location=1..2]"
)


def _transcriptome(path: Path, features: list[tuple[str, str, str, str]]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for index, (acc, gene, locus, kind) in enumerate(features, 1):
            handle.write(
                HEADER.format(acc=acc, n=index, gene=gene, locus=locus, kind=kind) + "\nACGT\n"
            )
    return path


def _matrix(path: Path, rows: dict[str, list[float]], samples: int) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("gene\t" + "\t".join(f"S{i}" for i in range(samples)) + "\n")
        for name, values in rows.items():
            handle.write(name + "\t" + "\t".join(str(v) for v in values) + "\n")
    return path


# ------------------------------------------------------------------- feature class, not prefix


def test_feature_kind_comes_from_the_transcriptome_not_the_locus_name(tmp_path: Path) -> None:
    """`Q0158` is the 21S ribosomal RNA. Its locus prefix says mitochondrial, which is true, and
    says nothing about whether it is an enzyme, which is the question."""
    path = _transcriptome(
        tmp_path / "t.fna.gz",
        [
            ("NC_001224.1", "21S_RRNA", "Q0158", "rRNA"),
            ("NC_001224.1", "RPM1", "Q0285", "ncRNA"),
            ("NC_001145.3", "ADH3", "YMR083W", "mRNA"),
        ],
    )
    features = B.transcriptome_features(path)
    assert features["Q0158"] == ("21S_RRNA", "rRNA")
    assert features["Q0285"] == ("RPM1", "ncRNA")
    assert features["YMR083W"] == ("ADH3", "mRNA")


def test_the_mitochondrial_protein_complement_is_named_so_its_absence_is_visible() -> None:
    """An absence is exactly what a summary statistic cannot show, so it is checked by name."""
    assert "COX1" in B.MITOCHONDRIAL_PROTEIN_GENES
    assert "ATP9" in B.MITOCHONDRIAL_PROTEIN_GENES
    assert len(B.MITOCHONDRIAL_PROTEIN_GENES) == 8


# ------------------------------------------------------------------------------- distributions


def test_detection_counts_samples_at_or_above_the_threshold(tmp_path: Path) -> None:
    path = _matrix(tmp_path / "m.tsv.gz", {"YAL001C": [0.0, 0.5, 1.0, 50.0]}, samples=4)
    values, samples, total = B.read_matrix(path, {"YAL001C"})
    assert samples == 4
    assert total == 1
    detected = sum(1 for v in values["YAL001C"] if v >= B.DETECTION_TPM)
    assert detected == 2  # 1.0 is detected; 0.5 is not


def test_read_matrix_returns_only_the_wanted_rows(tmp_path: Path) -> None:
    path = _matrix(
        tmp_path / "m.tsv.gz", {"YAL001C": [1.0], "YAL002W": [2.0], "Q0158": [3.0]}, samples=1
    )
    values, _, total = B.read_matrix(path, {"YAL001C", "Q0158"})
    assert set(values) == {"YAL001C", "Q0158"}
    assert total == 3  # every row is counted even when only some are kept


def _profile(**kwargs: object) -> B.GeneProfile:
    defaults: dict[str, object] = {
        "systematic_name": "YAL001C",
        "standard_name": "TFC3",
        "role": None,
        "encoding_genome": "nuclear",
        "feature_kind": "mRNA",
        "median_tpm": 10.0,
        "min_tpm": 1.0,
        "max_tpm": 100.0,
        "detected_in": 99,
        "samples": 99,
    }
    defaults.update(kwargs)
    return B.GeneProfile(**defaults)  # type: ignore[arg-type]


def test_a_gene_undetected_somewhere_has_no_fold_spread() -> None:
    """None, not infinity and not a substituted floor: a ratio against zero is not a number, and
    putting one there would place a value where an absence belongs."""
    assert _profile(min_tpm=0.0).fold_spread is None
    assert _profile(min_tpm=2.0, max_tpm=8.0).fold_spread == 4.0


def test_sporadic_and_absent_are_distinguished() -> None:
    report = B.BaselineReport(
        profiles=(
            _profile(systematic_name="A", detected_in=99),
            _profile(systematic_name="B", detected_in=78),
            _profile(systematic_name="C", detected_in=0),
        ),
        samples=99,
        matrix_genes=6187,
        matrix_path="m",
    )
    assert [p.systematic_name for p in report.sporadic] == ["B"]
    assert [p.systematic_name for p in report.absent] == ["C"]


# ------------------------------------------------------- the real corpus, checked by its shape


def test_the_real_transcriptome_has_no_mitochondrial_protein_genes() -> None:
    """Pinned as a regression: if a future index does include them, this test fails and whoever
    changed it must revisit the strategy-C-versus-E claim in the baseline report, which currently
    says that comparison cannot be made."""
    settings_path = Path(__file__).resolve().parents[1] / "env" / "paths.yaml"
    from fermdb.config import Settings

    settings = Settings.load(paths_file=settings_path, env={})
    transcripts = Path(settings.genomes_dir) / "s288c.transcripts.fna.gz"
    if not transcripts.is_file():
        import pytest

        pytest.skip("the R64 transcriptome is in the derived tier and is not present here")

    symbols = {symbol for symbol, _ in B.transcriptome_features(transcripts).values() if symbol}
    present = [name for name in B.MITOCHONDRIAL_PROTEIN_GENES if name in symbols]
    assert not present, (
        f"the transcriptome now contains {present}; mitochondrial expression may be measurable, "
        f"so docs/reports/2026-09-20-duet-expression-baseline.md needs revisiting"
    )


# ---------------------------------------------------------------------------------------------
# Library selection.
#
# Measured on the requantified corpus: a poly(A)-selected run puts 0.01% of its reads on
# mitochondrial CDS, because yeast mitochondrial transcripts are not polyadenylated the way
# nuclear ones are. Only 8 of the 99 S. cerevisiae runs are RANDOM-primed. Averaging the two
# together would answer a question about library preparation while looking like an answer about
# the organelle -- which is worse than the original gap, because the original gap was visible.
# ---------------------------------------------------------------------------------------------


def test_only_random_primed_libraries_count_toward_a_mitochondrial_claim() -> None:
    readout = B.mitochondrial_readout(
        ["ERR1", "ERR2", "SRR1", "SRR2", "SRR3"],
        {"ERR1": "RANDOM", "ERR2": "RANDOM", "SRR1": "cDNA", "SRR2": "cDNA", "SRR3": "cDNA"},
    )
    assert readout.usable_samples == ("ERR1", "ERR2")
    assert readout.depleted_samples == ("SRR1", "SRR2", "SRR3")
    assert readout.answerable is True
    assert "2 of 5 samples" in readout.caveat()


def test_an_unknown_library_counts_as_depleted_not_usable() -> None:
    """An unrecorded selection is not evidence that the library retained anything, and the
    conservative direction keeps a claim off metadata nobody checked."""
    readout = B.mitochondrial_readout(["A", "B"], {"A": None})
    assert readout.usable_samples == ()
    assert set(readout.depleted_samples) == {"A", "B"}


def test_an_all_polya_corpus_says_the_claim_is_unsupportable() -> None:
    """Not a low number -- no number. The distinction is the whole point."""
    readout = B.mitochondrial_readout(["S1", "S2"], {"S1": "cDNA", "S2": "cDNA"})
    assert readout.answerable is False
    assert "No mitochondrial claim is supportable" in readout.caveat()
