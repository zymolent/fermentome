"""Tests for `fermdb.omics.matrices`.

Offline: `_aws` is the only thing that touches the network and every test here either avoids it or
monkeypatches it. The properties pinned are the ones whose failure would produce a matrix that
looks fine — an unresolved transcript quietly dropped, an empty assembly written as if the corpus
were silent, a gene keyed on a symbol the atlas cannot join to.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from fermdb.omics import matrices as M


def _transcripts(tmp_path: Path, *headers: str) -> Path:
    path = tmp_path / "t.fna.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for header in headers:
            handle.write(header + "\nACGT\n")
    return path


# ---------------------------------------------------------------------- transcript -> gene


def test_the_locus_tag_wins_over_the_gene_symbol(tmp_path: Path) -> None:
    """gene.systematic_name holds the locus tag. A matrix keyed on symbols could not be joined
    to the atlas at all."""
    path = _transcripts(
        tmp_path, ">lcl|NC_001145.3_mrna_1 [gene=ADH3] [locus_tag=YMR083W] [product=p]"
    )
    assert M.transcript_to_gene(path) == {"lcl|NC_001145.3_mrna_1": "YMR083W"}


def test_a_header_with_only_a_symbol_falls_back_to_it(tmp_path: Path) -> None:
    path = _transcripts(tmp_path, ">tx1 [gene=ADH3] [product=p]")
    assert M.transcript_to_gene(path)["tx1"] == "ADH3"


def test_a_header_with_neither_maps_to_itself(tmp_path: Path) -> None:
    """So its counts survive under an id. Dropping it would be expression vanishing silently."""
    path = _transcripts(tmp_path, ">tx_unknown some description")
    assert M.transcript_to_gene(path)["tx_unknown"] == "tx_unknown"


def test_the_mitochondrial_cds_headers_resolve(tmp_path: Path) -> None:
    """The supplement is written in this header style precisely so this works; if it did not, the
    requantification would produce rows nothing could join to a gene."""
    path = _transcripts(
        tmp_path,
        ">lcl|NC_001224.1_cds_Q0045 [gene=COX1] [locus_tag=Q0045] [product=cox1] [gbkey=CDS]",
        ">lcl|NC_001224.1_cds_Q0105 [gene=COB] [locus_tag=Q0105] [product=cob] [gbkey=CDS]",
    )
    mapping = M.transcript_to_gene(path)
    assert set(mapping.values()) == {"Q0045", "Q0105"}


# ------------------------------------------------------------------------------ the matrix


def test_a_matrix_is_rectangular_with_explicit_zeros(tmp_path: Path) -> None:
    """Salmon reports every transcript for every sample, so a missing cell and a zero mean the
    same thing -- and a ragged file breaks anything that reads it."""
    path = tmp_path / "m.tsv.gz"
    M.write_matrix(
        path,
        genes=["YAL001C", "Q0045"],
        samples=["S1", "S2"],
        values={"S1": {"YAL001C": 5.0}, "S2": {"Q0045": 2.5}},
    )
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [line.rstrip("\n").split("\t") for line in handle]
    assert rows[0] == ["gene", "S1", "S2"]
    assert rows[1] == ["YAL001C", "5", "0"]
    assert rows[2] == ["Q0045", "0", "2.5"]
    assert all(len(row) == 3 for row in rows)


def test_run_accessions_reads_the_accession_out_of_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = (
        "2026-09-20 10:00:00  1234 quant-mito/20260920T085000Z/quant/SRR111/quant.sf\n"
        "2026-09-20 10:00:00   567 quant-mito/20260920T085000Z/quant/SRR111/meta_info.json\n"
        "2026-09-20 10:00:00  1234 quant-mito/20260920T085000Z/quant/ERR222/quant.sf\n"
    )
    monkeypatch.setattr(M, "_aws", lambda *a, **k: listing)
    found = M.run_accessions("quant-mito")
    assert set(found) == {"SRR111", "ERR222"}
    assert found["SRR111"].endswith("SRR111/quant.sf")


def test_an_empty_prefix_raises_rather_than_writing_empty_matrices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty matrices look exactly like a corpus in which nothing is expressed."""
    monkeypatch.setattr(M, "_aws", lambda *a, **k: "")
    with pytest.raises(M.MatrixError, match="nothing is expressed"):
        M.assemble(prefix="quant-mito", transcripts=tmp_path / "t.fna.gz", out_dir=tmp_path)


def test_assembly_sums_transcripts_to_genes_and_counts_the_mitochondrial_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transcripts = _transcripts(
        tmp_path,
        ">tx_a [locus_tag=YAL001C]",
        ">tx_b [locus_tag=YAL001C]",
        ">lcl|NC_001224.1_cds_Q0045 [gene=COX1] [locus_tag=Q0045] [gbkey=CDS]",
    )
    quant = (
        "Name\tLength\tEffectiveLength\tTPM\tNumReads\n"
        "tx_a\t100\t80\t10.0\t50\n"
        "tx_b\t100\t80\t5.0\t25\n"
        "lcl|NC_001224.1_cds_Q0045\t900\t880\t3.0\t12\n"
    )

    def fake_aws(args: list[str], **_: object) -> str:
        if args[2] == "ls":
            return "2026-09-20 10:00:00 1 quant-mito/x/quant/SRR1/quant.sf\n"
        if args[-2].endswith("meta_info.json"):
            return '{"percent_mapped": 78.6, "num_processed": 100, "num_mapped": 79}'
        return quant

    monkeypatch.setattr(M, "_aws", fake_aws)
    report = M.assemble(prefix="quant-mito", transcripts=transcripts, out_dir=tmp_path / "out")

    assert report.samples == 1
    assert report.genes == 2  # tx_a and tx_b summed into one gene
    assert report.mitochondrial_genes == 1
    assert report.unresolved_transcripts == 0
    assert report.qc[0]["percent_mapped"] == 78.6

    with gzip.open(tmp_path / "out" / "s288c.counts.tsv.gz", "rt", encoding="utf-8") as handle:
        rows = dict(line.rstrip("\n").split("\t", 1) for line in handle)
    assert rows["YAL001C"] == "75"  # 50 + 25, not two separate rows
    assert rows["Q0045"] == "12"


def test_a_dropped_run_is_excluded_from_the_matrix_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Its raw data and quantification stay in S3: a rejected run is a recorded decision, not a
    mistake to erase."""
    transcripts = _transcripts(tmp_path, ">tx_a [locus_tag=YAL001C]")
    quant = "Name\tLength\tEffectiveLength\tTPM\tNumReads\ntx_a\t100\t80\t10.0\t50\n"

    def fake_aws(args: list[str], **_: object) -> str:
        if args[2] == "ls":
            return (
                "2026-09-20 10:00:00 1 quant-mito/x/quant/KEEP1/quant.sf\n"
                "2026-09-20 10:00:00 1 quant-mito/x/quant/DROP1/quant.sf\n"
            )
        return "{}" if args[-2].endswith("meta_info.json") else quant

    monkeypatch.setattr(M, "_aws", fake_aws)
    report = M.assemble(
        prefix="quant-mito",
        transcripts=transcripts,
        out_dir=tmp_path / "out",
        dropped=frozenset({"DROP1"}),
    )
    assert report.samples == 1
    with gzip.open(tmp_path / "out" / "s288c.tpm.tsv.gz", "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
    assert header == ["gene", "KEEP1"]


def test_missing_meta_info_does_not_fail_the_assembly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """QC is best-effort: a missing meta_info.json does not invalidate the quantification beside
    it, and losing the whole assembly over one would be a poor trade."""
    transcripts = _transcripts(tmp_path, ">tx_a [locus_tag=YAL001C]")

    def fake_aws(args: list[str], **_: object) -> str:
        if args[2] == "ls":
            return "2026-09-20 10:00:00 1 quant-mito/x/quant/SRR1/quant.sf\n"
        if args[-2].endswith("meta_info.json"):
            raise M.MatrixError("not found")
        return "Name\tLength\tEffectiveLength\tTPM\tNumReads\ntx_a\t100\t80\t10.0\t50\n"

    monkeypatch.setattr(M, "_aws", fake_aws)
    report = M.assemble(prefix="quant-mito", transcripts=transcripts, out_dir=tmp_path / "out")
    assert report.samples == 1
    assert "error" in report.qc[0]
