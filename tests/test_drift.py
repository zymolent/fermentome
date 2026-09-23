"""Tests for `fermdb.query.drift` and the `quantity_kind` vocabulary gate.

Three properties. The vocabulary must admit what the atlas legitimately holds, the gate must
refuse a sentence on the way to a row, and the report must never repair what it finds.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb.curate.promote import _quantity_kind_blocker, _quantity_kinds
from fermdb.db import IN_MEMORY, open_db
from fermdb.query.drift import format_report, load_vocabulary, quantity_kind_drift

REPO_ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = REPO_ROOT / "data" / "vocabularies"
STRAIN = "YAA:STRAIN:test-host"
PUB = "doi:10.0000/test"


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    connection.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 'R', 'test', 'high')"
    )
    connection.execute(
        "INSERT INTO strain (id, canonical_name, organism_id, zone, evidence, confidence) "
        "VALUES (?, 'test host', 'YAA:ORG:sc', 'R', 'test', 'high')",
        (STRAIN,),
    )
    connection.execute(
        "INSERT INTO publication (id, title, zone, evidence, confidence) "
        "VALUES (?, 'a paper', 'R', 'test', 'high')",
        (PUB,),
    )
    connection.commit()
    yield connection
    connection.close()


def _measurement(conn: sqlite3.Connection, measurement_id: str, kind: str) -> None:
    conn.execute(
        "INSERT INTO measurement (id, strain_id, publication_id, quantity_kind, "
        "value_as_reported, unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES (?,?,?,?,1.0,'g/L','Table 1','R','test','high')",
        (measurement_id, STRAIN, PUB, kind),
    )
    conn.commit()


# ------------------------------------------------------------------------------ the vocabulary


def test_the_vocabulary_admits_the_terms_the_atlas_already_uses_well() -> None:
    """70 of 105 stored rows are `titer` or `yield`. A vocabulary that excluded them would be
    describing a different atlas."""
    vocabulary = load_vocabulary(VOCABULARIES)
    assert "titer" in vocabulary
    assert "yield" in vocabulary


def test_the_vocabulary_keeps_an_escape_hatch() -> None:
    """A forced choice from a closed list is how a list gets silently wrong (units.tsv's rule)."""
    assert "unknown" in load_vocabulary(VOCABULARIES)


def test_relative_kinds_are_one_signed_term_each_rather_than_a_direction_per_term() -> None:
    """`fold_increase`, `fold_improvement` and `fold_decrease` are one quantity under three
    names, and three names for one quantity is how a vocabulary stops being able to group."""
    vocabulary = load_vocabulary(VOCABULARIES)
    assert "fold_change" in vocabulary
    assert "percent_change" in vocabulary
    assert "fold_increase" not in vocabulary
    assert "fold_improvement" not in vocabulary


# ------------------------------------------------------------------------------------ the gate


def test_a_sentence_is_refused_on_the_way_to_a_row() -> None:
    from fermdb.curate.promote import PromotionPlan

    plan = PromotionPlan(
        task_id="YAA:CTASK:1",
        record_kind="measurements",
        target_table="measurement",
        row={"quantity_kind": "isobutanol concentration on SC agar permitting growth"},
    )
    blocker = _quantity_kind_blocker(plan, VOCABULARIES)
    assert blocker is not None
    assert "quantity_kinds.tsv" in blocker


def test_a_vocabulary_value_passes_the_gate() -> None:
    from fermdb.curate.promote import PromotionPlan

    plan = PromotionPlan(
        task_id="YAA:CTASK:1",
        record_kind="measurements",
        target_table="measurement",
        row={"quantity_kind": "titer"},
    )
    assert _quantity_kind_blocker(plan, VOCABULARIES) is None


def test_a_plan_with_no_quantity_kind_is_not_the_gates_business() -> None:
    """A strain or a modification has no such column, and the gate runs over every plan."""
    from fermdb.curate.promote import PromotionPlan

    plan = PromotionPlan(task_id="YAA:CTASK:1", record_kind="strains", target_table="strain")
    assert _quantity_kind_blocker(plan, VOCABULARIES) is None


def test_the_gate_reads_the_file_rather_than_a_list_in_the_code() -> None:
    """CONVENTIONS.md: adding a vocabulary value must not mean editing code."""
    _quantity_kinds.cache_clear()
    source = (REPO_ROOT / "src" / "fermdb" / "curate" / "promote.py").read_text(encoding="utf-8")
    assert "percent_change" not in source
    assert "specific_productivity" not in source


# ---------------------------------------------------------------------------------- the report


def test_drift_is_reported_with_the_rows_that_carry_it(conn: sqlite3.Connection) -> None:
    _measurement(conn, "YAA:MEAS:good", "titer")
    _measurement(conn, "YAA:MEAS:bad", "percent_decrease_in_isobutanol_titer_upon_valine_feeding")
    report = quantity_kind_drift(conn, VOCABULARIES)
    assert report.rows_total == 2
    assert report.rows_conforming == 1
    assert report.rows_drifted == 1
    (drifted,) = report.drifted
    assert drifted.measurement_ids == ("YAA:MEAS:bad",)
    assert drifted.publication_ids == (PUB,)


def test_reporting_changes_nothing(conn: sqlite3.Connection) -> None:
    """The remap is a curator's edit with the paper open, not a string substitution."""
    _measurement(conn, "YAA:MEAS:bad", "fold_increase")
    quantity_kind_drift(conn, VOCABULARIES)
    (stored,) = conn.execute(
        "SELECT quantity_kind FROM measurement WHERE id = 'YAA:MEAS:bad'"
    ).fetchone()
    assert stored == "fold_increase"


def test_the_report_names_the_paper_so_the_worklist_is_actionable(
    conn: sqlite3.Connection,
) -> None:
    _measurement(conn, "YAA:MEAS:bad", "LC50 (approximate)")
    text = format_report(quantity_kind_drift(conn, VOCABULARIES))
    assert "outside the vocabulary" in text
    assert PUB in text
    assert "YAA:MEAS:bad" in text


def test_an_atlas_with_no_measurements_reports_zero_rather_than_raising(
    conn: sqlite3.Connection,
) -> None:
    report = quantity_kind_drift(conn, VOCABULARIES)
    assert report.rows_total == 0
    assert report.drifted == ()
    assert report.vocabulary  # the file is still read, so the absence is of rows, not of a list
