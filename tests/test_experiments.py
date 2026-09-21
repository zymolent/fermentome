"""Tests for `fermdb.omics.experiments` — which `experiment` rows recorded metadata supports.

Almost every test here is about a refusal, because the expensive mistake in this module is not
missing an experiment: it is producing one that names the wrong paper. A missing
`experiment.publication_id` is visible to every query that asks for it. A wrong one is visible to
none of them, and it mis-attributes every sample underneath.

So the properties pinned below are: the grouping comes only from what SRA's submitter declared;
the publication link is refused and stays refused even when the writer is handed a row that
claims one; and the refusal's stated reason is checked against the committed runinfo export
rather than remembered — `Study_Pubmed_id` is the column that would fool a future reader, so the
test reads it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import experiments as E

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNINFO = REPO_ROOT / "data" / "omics" / "sra_isobutanol_runinfo.csv"


def _dataset(conn: sqlite3.Connection, local: str, accession: str | None, project: str | None):
    conn.execute(
        "INSERT INTO dataset (id, accession, bioproject, repository, zone, evidence, confidence) "
        "VALUES (?,?,?,'SRA','R','test','high')",
        (f"YAA:DATASET:{local}", accession, project),
    )


def _sample(conn: sqlite3.Connection, run: str, dataset_local: str | None) -> None:
    conn.execute(
        "INSERT INTO sample (id, dataset_id, zone, evidence, confidence) "
        "VALUES (?,?,'R','one sample per SRA run','high')",
        (f"YAA:SAMPLE:{run}", f"YAA:DATASET:{dataset_local}" if dataset_local else None),
    )


@pytest.fixture
def atlas() -> sqlite3.Connection:
    """Two SRA studies, five runs between them, and no publication link anywhere."""
    conn = open_db(IN_MEMORY)
    _dataset(conn, "srp321884", "SRP321884", "PRJNA733673")
    _dataset(conn, "srp003312", "SRP003312", None)
    for run in ("SRR1", "SRR2", "SRR3"):
        _sample(conn, run, "srp321884")
    for run in ("SRR9", "SRR8"):
        _sample(conn, run, "srp003312")
    conn.commit()
    return conn


# ----------------------------------------------------------------- what is soundly derivable


def test_one_experiment_per_sra_study_because_the_submitter_declared_that_grouping(
    atlas: sqlite3.Connection,
) -> None:
    """The grouping is recorded, not inferred: a run belongs to exactly one SRA study because
    whoever deposited it said so, and `dataset` is where that statement already lives."""
    report = E.derive_experiments(atlas)
    assert len(report.experiments) == 2
    assert report.samples_covered == 5
    assert {e.sample_count for e in report.experiments} == {3, 2}


def test_the_experiment_id_is_derived_from_the_dataset_so_rerunning_writes_no_second_set(
    atlas: sqlite3.Connection,
) -> None:
    """A generated id (a uuid, a hash of a timestamp) would make the derivation non-idempotent:
    the second run would produce a parallel set of experiments and every sample would be pointed
    at the newer one, silently orphaning the older."""
    first = {e.id for e in E.derive_experiments(atlas).experiments}
    second = {e.id for e in E.derive_experiments(atlas).experiments}
    assert first == second == {"YAA:EXPERIMENT:srp321884", "YAA:EXPERIMENT:srp003312"}


def test_a_study_with_no_bioproject_still_gets_an_experiment(atlas: sqlite3.Connection) -> None:
    """SRP003312 has no BioProject in this corpus's runinfo. The SRA study accession is still the
    submitter's grouping, so the absent BioProject costs the experiment nothing but is recorded as
    absent rather than filled in from the study accession."""
    derived = {e.id: e for e in E.derive_experiments(atlas).experiments}
    assert derived["YAA:EXPERIMENT:srp003312"].bioproject is None
    assert derived["YAA:EXPERIMENT:srp003312"].accession == "SRP003312"


def test_the_evidence_names_the_study_and_the_count_it_groups(atlas: sqlite3.Connection) -> None:
    """`evidence` is NOT NULL in the schema, and a string like "derived" satisfies the constraint
    while telling a later reader nothing. It has to say what was read."""
    derived = {e.id: e for e in E.derive_experiments(atlas).experiments}
    evidence = derived["YAA:EXPERIMENT:srp321884"].evidence
    assert "SRP321884" in evidence
    assert "PRJNA733673" in evidence
    assert "3 run(s)" in evidence


def test_objective_and_design_type_stay_empty_because_sra_records_neither(
    atlas: sqlite3.Connection,
) -> None:
    """Both columns are free text, which makes them the easiest place in this table to write a
    sentence nobody said. SRA's runinfo has no field for either."""
    for experiment in E.derive_experiments(atlas).experiments:
        assert experiment.objective is None
        assert experiment.design_type is None


def test_every_derived_row_is_zone_r(atlas: sqlite3.Connection) -> None:
    """The grouping is the submitter's own statement, at the same grade as the `dataset` row it
    is read from — not a curator's reading of it and not a model's."""
    assert {e.zone for e in E.derive_experiments(atlas).experiments} == {"R"}


# ------------------------------------------------------------------------ what is refused


def test_no_derived_experiment_names_a_publication(atlas: sqlite3.Connection) -> None:
    """The headline refusal. Nothing recorded in this atlas links an SRA study to a paper, and an
    experiment wrongly attached to one mis-attributes every sample under it."""
    report = E.derive_experiments(atlas)
    assert report.with_publication == ()
    assert len(report.without_publication) == 2
    for experiment in report.experiments:
        assert experiment.publication.publication_id is None
        assert experiment.publication.state == "refused"


def test_the_refusal_travels_in_the_evidence_string(atlas: sqlite3.Connection) -> None:
    """So that a curator who later attaches a publication is overruling a stated reason rather
    than filling in a blank they assumed nobody had thought about."""
    for experiment in E.derive_experiments(atlas).experiments:
        assert E.PUBLICATION_LINK_REFUSAL in experiment.evidence


def test_the_runinfo_pubmed_column_is_the_same_value_for_unrelated_studies() -> None:
    """The fact the refusal rests on, read from the committed corpus export rather than recalled.

    `Study_Pubmed_id` is the one runinfo column that looks like a publication link. If it were
    one, its values would differ per study. In this corpus it reads '3' for five unrelated
    deposits — four S. cerevisiae studies and one Lactococcus — which is a legacy link-type code,
    not a PMID. Reading it as a PMID would attach one arbitrary record to 98 of 172 runs.
    """
    values = E.runinfo_pubmed_values(RUNINFO)
    threes = sorted(study for study, seen in values.items() if seen == ("3",))
    assert len(threes) > 1, "if this column identified studies, no two would share a value"
    assert threes == [
        "SRP126584",
        "SRP156315",
        "SRP321884",
        "SRP342112",
        "SRP343868",
    ]


def test_a_runinfo_export_without_the_pubmed_column_is_refused_not_skipped(tmp_path: Path) -> None:
    """A silently-absent column would make the refusal's evidence silently absent too, and the
    function would return an empty mapping that reads like "nothing to worry about"."""
    path = tmp_path / "runinfo.csv"
    path.write_text("Run,SRAStudy\nSRR1,SRP1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Study_Pubmed_id"):
        E.runinfo_pubmed_values(path)


def test_a_publication_link_that_claims_no_publication_is_rejected_at_construction() -> None:
    """`state='derived'` is the shape a future, evidenced link takes. It has to carry the
    publication it derived, or "derived" means nothing at all."""
    with pytest.raises(ValueError, match="must name the publication"):
        E.PublicationLink(state="derived", publication_id=None, reason="elink said so")


def test_a_refused_link_cannot_also_name_a_publication() -> None:
    """The contradiction that would let a refusal ship a value anyway."""
    with pytest.raises(ValueError, match="cannot also name"):
        E.PublicationLink(state="refused", publication_id="pmid:1", reason="no")


def test_the_writer_refuses_a_row_that_claims_a_publication(atlas: sqlite3.Connection) -> None:
    """The writer has no `publication_id` column in its INSERT, so a claimed link could only be
    silently dropped. Dropping it silently would let a caller believe a link was stored."""
    derived = list(E.derive_experiments(atlas).experiments)
    claimed = E.DerivedExperiment(
        id=derived[0].id,
        dataset_id=derived[0].dataset_id,
        accession=derived[0].accession,
        bioproject=derived[0].bioproject,
        sample_ids=derived[0].sample_ids,
        publication=E.PublicationLink(
            state="derived", publication_id="doi:10.1/x", reason="a curator said so"
        ),
        evidence=derived[0].evidence,
    )
    with pytest.raises(ValueError, match="no column for one"):
        E.load_experiments(atlas, experiments=[claimed])


def test_a_sample_with_no_dataset_gets_no_experiment_and_is_reported() -> None:
    """The alternative — an "unassigned" experiment — is a bucket, and a bucket eventually gets
    treated as a study. There is no such sample in the atlas today; the point is that there being
    none is asserted rather than assumed."""
    conn = open_db(IN_MEMORY)
    _dataset(conn, "srp1", "SRP1", "PRJNA1")
    _sample(conn, "SRR1", "srp1")
    _sample(conn, "SRR2", None)
    conn.commit()
    report = E.derive_experiments(conn)
    assert report.orphan_sample_ids == ("YAA:SAMPLE:SRR2",)
    assert report.samples_covered == 1
    assert len(report.experiments) == 1


def test_deriving_writes_nothing(atlas: sqlite3.Connection) -> None:
    """The derivation is also the report, and a report that mutated the atlas to produce itself
    could not be run against a live database to decide whether to run it."""
    before = atlas.total_changes
    E.derive_experiments(atlas)
    assert atlas.total_changes == before
    assert atlas.execute("SELECT COUNT(*) FROM experiment").fetchone()[0] == 0


# ------------------------------------------------------------------------- what writing does


def test_loading_links_every_sample_to_its_study_and_is_idempotent(
    atlas: sqlite3.Connection,
) -> None:
    """Running the load twice must leave one experiment per study, not two, and must leave every
    sample pointing at the same row it pointed at the first time."""
    E.load_experiments(atlas)
    E.load_experiments(atlas)
    assert atlas.execute("SELECT COUNT(*) FROM experiment").fetchone()[0] == 2
    rows = atlas.execute(
        "SELECT experiment_id, COUNT(*) n FROM sample GROUP BY experiment_id ORDER BY 1"
    ).fetchall()
    assert [(str(r[0]), r[1]) for r in rows] == [
        ("YAA:EXPERIMENT:srp003312", 2),
        ("YAA:EXPERIMENT:srp321884", 3),
    ]


def test_the_written_row_leaves_publication_id_null(atlas: sqlite3.Connection) -> None:
    """The refusal has to survive the trip into the database, or it was only a docstring."""
    E.load_experiments(atlas)
    rows = atlas.execute("SELECT publication_id FROM experiment").fetchall()
    assert rows and all(row[0] is None for row in rows)
