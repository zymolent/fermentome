"""Tests for `fermdb.omics.tnseq` — the Tn-Seq screens, and the clause they half satisfy.

PLAN.md phase 4: *every Tn-Seq screen is represented as perturbation evidence rather than folded
in with expression.* The two halves fail differently and are tested differently.

**Not folded in with expression** is true today and true by accident — nobody built a
*Zymomonas* expression matrix, so no screen could get into one. An accident is not a guarantee,
so the negative case here is tested with a fixture in which a screen *has* reached the expression
layer, proving the check fires rather than merely never firing.

**Represented as perturbation evidence** is false, and the test asserts it is false and that the
module says why. That is deliberate: a test that skipped the unmet half would let the gap close
silently in a report while remaining open in the data.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import sra as sra_mod
from fermdb.omics import tnseq as T

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings whose derived and repo tiers are both under tmp_path, so a test never reads the
    developer's real matrices or writes near the committed curation files."""
    repo = tmp_path / "repo"
    (repo / "data" / "omics").mkdir(parents=True)
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_REPO_ROOT": str(repo),
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


def _run_row(
    connection: sqlite3.Connection,
    accession: str,
    *,
    strategy: str,
    study: str = "SRP588897",
    organism: str = "Zymomonas mobilis subsp. mobilis ZM4 = ATCC 31821",
    priority_rank: int | None = None,
) -> None:
    connection.execute(
        "INSERT INTO sra_run (id, run_accession, study_accession, bioproject, organism, "
        "library_strategy, reference_assembly, reference_match_quality, bases, size_mb, "
        "acquisition_status, priority_rank, retrieved_at, zone, evidence, confidence, "
        "relevance_uncertain) "
        "VALUES (?,?,?,'PRJNA1270032',?,?,'GCF_000007105.1','strain_matched',1000,400.0,"
        "'discovered',?,'2026-01-01','R','runinfo','high',0)",
        (
            f"YAA:SRARUN:{accession}",
            accession,
            study,
            organism,
            strategy,
            sra_mod.priority_rank_for(strategy) if priority_rank is None else priority_rank,
        ),
    )


# ------------------------------------------------------------------------------- the screen unit


def test_a_screen_is_one_study_not_one_run() -> None:
    """Eight replicate runs of one challenged library are one screen. Counting runs would report
    eight screens; counting organisms would merge two unrelated deposits into one."""
    connection = open_db(IN_MEMORY)
    try:
        for index in range(8):
            _run_row(connection, f"SRR3376755{index}", strategy=T.TN_SEQ_STRATEGY)
        _run_row(connection, "SRR9999999", strategy=T.TN_SEQ_STRATEGY, study="SRP999999")

        found = T.screens(connection)
        assert [screen.study_accession for screen in found] == ["SRP588897", "SRP999999"]
        assert [screen.run_count for screen in found] == [8, 1]
        assert found[0].total_bases == 8000
    finally:
        connection.close()


def test_an_expression_run_is_not_a_screen() -> None:
    connection = open_db(IN_MEMORY)
    try:
        _run_row(connection, "SRR1", strategy="RNA-Seq", organism="Saccharomyces cerevisiae")
        assert T.screens(connection) == ()
    finally:
        connection.close()


# ------------------------------------------------------- half one: not folded in with expression


def test_a_screen_that_reached_the_expression_layer_is_named(settings: Settings) -> None:
    """The check has to be able to fail. Here a Tn-Seq run is in the quant plan and another is a
    matrix column, and both are reported — otherwise "none folded in" only ever means "nobody
    looked"."""
    plan = Path(settings.repo_root) / "data" / "omics" / "quant_plan.json"
    plan.write_text(json.dumps([{"run": "SRR33767555", "ref": "zm4"}]), encoding="utf-8")
    matrices = Path(settings.matrices_dir)
    matrices.mkdir(parents=True, exist_ok=True)
    with gzip.open(matrices / "zm4.tpm.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("gene\tSRR33767556\nZMO0001\t1.0\n")

    connection = open_db(IN_MEMORY)
    try:
        for accession in ("SRR33767555", "SRR33767556", "SRR33767557"):
            _run_row(connection, accession, strategy=T.TN_SEQ_STRATEGY)
        report = T.build_report(connection, settings)
    finally:
        connection.close()

    assert report.folded_into_expression == ("SRR33767555", "SRR33767556")
    assert not report.clause_not_folded_in_holds
    assert "FOLDED IN WITH EXPRESSION" in report.summary()


def test_both_the_plan_and_the_matrix_are_searched(settings: Settings) -> None:
    """A run can be in the plan without reaching a matrix, or in a matrix built before the plan
    was written. Either alone would miss half the ways a screen gets folded in."""
    matrices = Path(settings.matrices_dir)
    matrices.mkdir(parents=True, exist_ok=True)
    with gzip.open(matrices / "s288c.tpm.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("gene\tSRR_M\nYAL001C\t1.0\n")
    plan = Path(settings.repo_root) / "data" / "omics" / "quant_plan.json"
    plan.write_text(json.dumps([{"run": "SRR_P"}]), encoding="utf-8")

    assert T.expression_layer_runs(settings) == frozenset({"SRR_M", "SRR_P"})


# ------------------------------------------------ half two: represented as perturbation evidence


def test_no_evidence_type_can_carry_a_screen_and_the_module_says_so(settings: Settings) -> None:
    """The unmet half, asserted rather than skipped. `evidence_items` is zero and the refusal
    naming all three near-miss evidence types travels with the report."""
    connection = open_db(IN_MEMORY)
    try:
        _run_row(connection, "SRR33767555", strategy=T.TN_SEQ_STRATEGY)
        report = T.build_report(connection, settings)
    finally:
        connection.close()

    assert report.screen_count == 1
    assert report.screens[0].evidence_items == 0
    assert not report.screens[0].represented_as_perturbation_evidence
    assert not report.clause_represented_as_evidence_holds
    for near_miss in ("direct_perturbation", "correlative_omics", "comparative_genomic"):
        assert near_miss in report.refusal


def test_a_pooled_library_cannot_satisfy_direct_perturbations_constraint() -> None:
    """The schema-level reason the refusal exists, demonstrated against the real CHECK rather than
    argued in prose: `direct_perturbation` demands a strain and a measurement, and a per-gene
    fitness score from a pooled library has neither."""
    connection = open_db(IN_MEMORY)
    try:
        connection.execute(
            "INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, "
            "object_id, direction, created_by_kind, created_by, zone, evidence, confidence) "
            "VALUES ('YAA:ASSERT:t','gene_group','YAA:GG:zmo0001','affects_production_of',"
            "'product','YAA:PRODUCT:isobutanol','decreases','curator','test','H','t','low')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, "
                "statistic, zone, evidence, confidence) "
                "VALUES ('YAA:EV:t','YAA:ASSERT:t','direct_perturbation','decreases',-3.1,"
                "'H','Tn-Seq fitness score','low')"
            )
    finally:
        connection.close()


# ---------------------------------------------------------------------------- the priority rank


def test_a_stored_rank_that_disagrees_with_the_rule_is_reported(settings: Settings) -> None:
    """`load.py` wrote 0 for every run, so `ORDER BY priority_rank` returned the corpus in
    accession order and the one mechanism marking a screen as different from an expression run was
    silently inert. The disagreement is now surfaced instead of being invisible."""
    connection = open_db(IN_MEMORY)
    try:
        _run_row(connection, "SRR33767555", strategy=T.TN_SEQ_STRATEGY, priority_rank=0)
        _run_row(connection, "SRR33767556", strategy=T.TN_SEQ_STRATEGY)
        report = T.build_report(connection, settings)
    finally:
        connection.close()

    screen = report.screens[0]
    assert screen.misranked_runs == ("SRR33767555",)
    assert sra_mod.priority_rank_for(T.TN_SEQ_STRATEGY) == 1


# ---------------------------------------------------------------------- runs in neither layer


def test_a_catch_all_run_in_a_screened_organism_is_reported_not_assumed(
    settings: Settings,
) -> None:
    """SRA's `OTHER` label hides both perturbation screens and everything else. Such a run is in
    no layer at all, and that is a curation question rather than a state to leave unreported."""
    connection = open_db(IN_MEMORY)
    try:
        _run_row(connection, "SRR33767555", strategy=T.TN_SEQ_STRATEGY)
        _run_row(connection, "SRR33968977", strategy="OTHER", study="SRP591874")
        _run_row(
            connection,
            "SRR_YEAST",
            strategy="OTHER",
            study="SRP343868",
            organism="Saccharomyces cerevisiae",
        )
        report = T.build_report(connection, settings)
    finally:
        connection.close()

    # Only the organism that actually has screens: a yeast `OTHER` run is a different question.
    assert [run.run_accession for run in report.unclassified_candidates] == ["SRR33968977"]


# ---------------------------------------------------------- the real corpus, against the clause


_REAL = Settings.load(paths_file=PATHS_FILE, env={})
_HAVE_DB = Path(_REAL.db_file).is_file()


@pytest.mark.skipif(not _HAVE_DB, reason="the atlas database lives in the derived tier")
def test_no_screen_in_the_real_corpus_is_folded_in_with_expression() -> None:
    """The half of the clause that holds, asserted against the corpus rather than assumed from the
    absence of a *Zymomonas* matrix."""
    connection = open_db(_REAL.db_file, create=False)
    try:
        report = T.build_report(connection, _REAL)
    finally:
        connection.close()

    assert report.folded_into_expression == ()
    assert report.clause_not_folded_in_holds
    # And the screens really are bacterial: DATA_VOLUME.md section 2's correction.
    assert report.screens
    assert all("Zymomonas" in (screen.organism or "") for screen in report.screens)
