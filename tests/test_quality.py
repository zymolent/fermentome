"""Tests for `fermdb.omics.quality` — recording a doubt without acting on it.

The property that matters most here is a negative one: **a detector must not repair the row it
doubts.** Relabelling a sample to whatever it resembles uses the expression data to fix the
metadata and then analyses the data under the fixed metadata, and at n=3 that circularity moves
p-values in the direction that manufactures significance. So the tests check that a flag is
raised, that it is *machine-readable by the contrast gate*, and that nothing about the sample row
itself changes.

The second property is the one that cost an iteration: the statistic must accuse the sample that
is wrong and **not** its blameless groupmates. A mean-based coherence score flags all three
members of a group containing one outlier. The max-based one does not, and there is a test for
exactly that shape.
"""

from __future__ import annotations

import gzip
import math
from pathlib import Path

from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import quality as Q


def _matrix(tmp_path: Path, columns: list[str], profiles: dict[str, list[float]]) -> Path:
    """One row per gene; `profiles` gives each column's value for that gene index."""
    path = tmp_path / "counts.tsv.gz"
    n_genes = len(next(iter(profiles.values())))
    with gzip.open(path, "wt", newline="\n") as handle:
        handle.write("gene\t" + "\t".join(columns) + "\n")
        for g in range(n_genes):
            handle.write(f"YGENE{g:04d}\t" + "\t".join(str(profiles[c][g]) for c in columns) + "\n")
    return path


def _db(cells: dict[str, tuple[str, str]], study: str = "SRPQ"):
    """run -> (context id, strain id)."""
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 'R', 't', 'high')"
    )
    conn.execute(
        "INSERT INTO dataset (id, accession, repository, omics_type, zone, evidence, confidence) "
        "VALUES ('YAA:DATASET:q', ?, 'SRA', 'transcriptomics', 'R', 't', 'high')",
        (study,),
    )
    for context_id in {c for c, _ in cells.values()}:
        conn.execute(
            "INSERT INTO condition_context (id, context_hash, zone, evidence, confidence) "
            "VALUES (?, ?, 'R', 't', 'high')",
            (context_id, context_id),
        )
    for strain_id in {s for _, s in cells.values()}:
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:sc', ?, 'engineered', 'R', 't', 'medium')",
            (strain_id, strain_id.rsplit(":", 1)[-1]),
        )
    for run, (context_id, strain_id) in cells.items():
        conn.execute(
            "INSERT INTO sample (id, dataset_id, strain_id, condition_context_id, zone, "
            "evidence, confidence) VALUES (?, 'YAA:DATASET:q', ?, ?, 'R', 't', 'high')",
            (f"YAA:SAMPLE:{run}", strain_id, context_id),
        )
        conn.execute(
            "INSERT INTO sra_run (id, run_accession, dataset_id, study_accession, organism, "
            "library_strategy, retrieved_at, zone, evidence, confidence) VALUES "
            "(?, ?, 'YAA:DATASET:q', ?, 'Saccharomyces cerevisiae', 'RNA-Seq', "
            "'2026-09-22T00:00:00Z', 'R', 't', 'high')",
            (f"YAA:SRARUN:{run}", run, study),
        )
    return conn


def test_robust_z_flags_nothing_when_every_value_agrees() -> None:
    """A study whose samples are indistinguishable gives no evidence that one is an outlier."""
    assert Q.robust_z([0.5, 0.5, 0.5, 0.5]) == [0.0, 0.0, 0.0, 0.0]


def test_robust_z_is_centred_on_the_median() -> None:
    scores = Q.robust_z([1.0, 2.0, 3.0, 20.0])
    assert scores[3] > 3.0
    assert abs(scores[1]) < 1.0


def test_robust_z_returns_zeros_when_the_mad_collapses() -> None:
    """Three identical values and one outlier give MAD 0, and a zero MAD must accuse nobody.

    An infinite z here would quarantine a sample on the strength of a degenerate denominator.
    """
    assert Q.robust_z([1.0, 1.0, 1.0, 10.0]) == [0.0, 0.0, 0.0, 0.0]


def _swapped_corpus(tmp_path: Path):
    """Four declared cells of three. One member of cell p@t1 really belongs to q@t2.

    Four cells rather than two, because the cut is a robust z against the study's own spread: with
    a single pair of groups an impostor and its victims produce a near-symmetric margin
    distribution and the MAD swallows the signal. A real study has a grid -- this corpus is the
    smallest one shaped like it.
    """
    n = 300
    base = [float(10 * (i % 50) + 5) for i in range(n)]

    def variant(seed: int, lifted: range, factor: float) -> list[float]:
        out = []
        for i, value in enumerate(base):
            noise = 1.0 + ((seed * 37 + i * 17) % 100) / 100.0 * 0.01
            out.append(value * (factor if i in lifted else 1.0) * noise)
        return out

    # Each cell lifts a different block of genes, so cells are distinguishable but all four
    # remain far more similar to themselves than to each other.
    blocks = {
        "p_t1": range(0, 30),
        "p_t2": range(30, 60),
        "q_t1": range(60, 90),
        "q_t2": range(90, 120),
    }
    profiles: dict[str, list[float]] = {}
    cells: dict[str, tuple[str, str]] = {}
    for index, (cell, block) in enumerate(blocks.items()):
        strain, context = cell.split("_")
        for replicate in (1, 2, 3):
            run = f"{cell}_{replicate}"
            profiles[run] = variant(index * 10 + replicate, block, 8.0)
            cells[run] = (f"YAA:CCTX:{context}", f"YAA:STRAIN:{strain}")

    # The impostor: declared in p@t1, carrying q@t2's profile.
    profiles["p_t1_3"] = variant(99, blocks["q_t2"], 8.0)

    matrix = _matrix(tmp_path, list(profiles), profiles)
    return _db(cells), matrix


def test_gate_a_accuses_the_impostor_and_not_its_groupmates(tmp_path: Path) -> None:
    """The shape a mean-based statistic gets wrong: the outlier's innocent cell-mates."""
    conn, matrix = _swapped_corpus(tmp_path)
    flags = Q.coherence_flags(conn, matrix_path=matrix, study_accession="SRPQ", raised_by="test")
    accused = {f.target_id for f in flags}
    assert "YAA:SAMPLE:p_t1_3" in accused
    assert "YAA:SAMPLE:p_t1_1" not in accused
    assert "YAA:SAMPLE:p_t1_2" not in accused


def test_gate_a_records_what_the_sample_resembles_without_applying_it(tmp_path: Path) -> None:
    conn, matrix = _swapped_corpus(tmp_path)
    flags = Q.coherence_flags(conn, matrix_path=matrix, study_accession="SRPQ", raised_by="test")
    flag = next(f for f in flags if f.target_id == "YAA:SAMPLE:p_t1_3")
    assert flag.resembles is not None and "q" in flag.resembles
    assert flag.severity == "quarantine"
    assert flag.kind == "mislabel_suspected"

    Q.write_flags(conn, flags, raised_by="test")
    # The row it doubts is untouched: still declared strain p, still in its declared context.
    strain, context = conn.execute(
        "SELECT strain_id, condition_context_id FROM sample WHERE id = 'YAA:SAMPLE:p_t1_3'"
    ).fetchone()
    assert strain == "YAA:STRAIN:p"
    assert context == "YAA:CCTX:t1"


def test_a_written_flag_is_honoured_by_the_contrast_gate(tmp_path: Path) -> None:
    """The point of storing the doubt rather than reporting it."""
    from fermdb.omics.contrasts import ContrastGroup, ContrastSpec, refusals

    conn, matrix = _swapped_corpus(tmp_path)
    Q.write_flags(
        conn,
        Q.coherence_flags(conn, matrix_path=matrix, study_accession="SRPQ", raised_by="test"),
        raised_by="test",
    )
    spec = ContrastSpec(
        id="YAA:CONTRAST:q",
        study_accession="SRPQ",
        reference=ContrastGroup(
            "p",
            ("YAA:SAMPLE:p_t1_1", "YAA:SAMPLE:p_t1_2", "YAA:SAMPLE:p_t1_3"),
            "YAA:CCTX:t1",
        ),
        treatment=ContrastGroup(
            "q",
            ("YAA:SAMPLE:q_t1_1", "YAA:SAMPLE:q_t1_2", "YAA:SAMPLE:q_t1_3"),
            "YAA:CCTX:t1",
        ),
        axis="genotype",
    )
    problems = refusals(conn, spec)
    assert any("quarantined by a data_quality_flag" in p for p in problems)


def test_a_cleared_flag_is_not_silently_reopened(tmp_path: Path) -> None:
    """A person's decision outranks the detector noticing the same thing again."""
    conn, matrix = _swapped_corpus(tmp_path)
    flags = Q.coherence_flags(conn, matrix_path=matrix, study_accession="SRPQ", raised_by="test")
    Q.write_flags(conn, flags, raised_by="test")
    conn.execute(
        "UPDATE data_quality_flag SET status = 'cleared', resolved_by = 'curator', "
        "resolved_reason = 'checked the deposit; the label is right'"
    )
    written, respected = Q.write_flags(conn, flags, raised_by="test")
    assert written == 0 and respected == len(flags)
    assert Q.active_quarantine(conn, ["YAA:SAMPLE:p_t1_3"]) == {}


def test_gate_b_abstains_when_no_clean_split_exists(tmp_path: Path) -> None:
    """A marker gene with no bimodal gap says nothing about any label, and must not pretend to."""
    n = 50
    columns = ["A1", "A2", "B1", "B2"]
    profiles = {c: [100.0 + i for i in range(n)] for c in columns}
    matrix = _matrix(tmp_path, columns, profiles)
    conn = _db(
        {
            "A1": ("YAA:CCTX:t1", "YAA:STRAIN:p"),
            "A2": ("YAA:CCTX:t1", "YAA:STRAIN:p"),
            "B1": ("YAA:CCTX:t1", "YAA:STRAIN:q"),
            "B2": ("YAA:CCTX:t1", "YAA:STRAIN:q"),
        }
    )
    conn.execute(
        "INSERT INTO genotype (id, strain_id, as_reported, parsed_json, zone, evidence, "
        "confidence) VALUES ('YAA:GENOTYPE:q', 'YAA:STRAIN:q', 'q with MARK', "
        "'{\"localization\": {\"MARK\": {\"compartment\": \"cytosol\"}}}', 'R', 't', 'medium')"
    )
    flags = Q.marker_flags(
        conn,
        matrix_path=matrix,
        study_accession="SRPQ",
        raised_by="test",
        symbols={"YGENE0000": "MARK"},
    )
    assert flags == []


def test_confounded_marker_genes_are_never_used_to_accuse(tmp_path: Path) -> None:
    """A gene whose row mixes native expression with cassette spillover is not evidence."""
    n = 40
    columns = ["A1", "A2", "B1", "B2"]
    profiles = {
        "A1": [10.0] * n,
        "A2": [10.0] * n,
        "B1": [1000.0] * n,
        "B2": [1000.0] * n,
    }
    matrix = _matrix(tmp_path, columns, profiles)
    conn = _db(
        {
            "A1": ("YAA:CCTX:t1", "YAA:STRAIN:p"),
            "A2": ("YAA:CCTX:t1", "YAA:STRAIN:p"),
            "B1": ("YAA:CCTX:t1", "YAA:STRAIN:q"),
            "B2": ("YAA:CCTX:t1", "YAA:STRAIN:q"),
        }
    )
    conn.execute(
        "INSERT INTO genotype (id, strain_id, as_reported, parsed_json, zone, evidence, "
        "confidence) VALUES ('YAA:GENOTYPE:p', 'YAA:STRAIN:p', 'p with MARK', "
        "'{\"localization\": {\"MARK\": {\"compartment\": \"cytosol\"}}}', 'R', 't', 'medium')"
    )
    flags = Q.marker_flags(
        conn,
        matrix_path=matrix,
        study_accession="SRPQ",
        raised_by="test",
        symbols={"YGENE0000": "MARK"},
        confounded_genes=frozenset({"MARK"}),
    )
    assert flags == []


def test_flag_ids_are_stable_so_a_rerun_updates_rather_than_duplicates() -> None:
    first = Q.QualityFlag(
        target_type="sample",
        target_id="YAA:SAMPLE:X",
        kind="mislabel_suspected",
        severity="quarantine",
        detector=Q.DETECTOR_COHERENCE,
        rationale="a",
    )
    second = Q.QualityFlag(
        target_type="sample",
        target_id="YAA:SAMPLE:X",
        kind="mislabel_suspected",
        severity="quarantine",
        detector=Q.DETECTOR_COHERENCE,
        rationale="b (recomputed later)",
    )
    assert first.id == second.id


def test_margin_is_negative_only_when_the_label_is_wrong(tmp_path: Path) -> None:
    conn, matrix = _swapped_corpus(tmp_path)
    flags = Q.coherence_flags(conn, matrix_path=matrix, study_accession="SRPQ", raised_by="test")
    flag = next(f for f in flags if f.target_id == "YAA:SAMPLE:p_t1_3")
    assert flag.statistic is not None
    assert flag.statistic < Q.MARGIN_Z_FLOOR
    assert not math.isnan(flag.statistic)
