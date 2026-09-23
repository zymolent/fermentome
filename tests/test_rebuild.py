"""Tests for the Zone H rebuild check — PLAN.md T.3, `fermdb.rebuild`.

T.3 calls rebuild-and-diff "the strongest guarantee in the whole design", which puts an unusual
burden on this file: a rebuild check that cannot fail is worse than no check at all, because it
claims that guarantee while verifying nothing. So the tests here are in two halves.

The first half asserts the check passes on an unmodified fixture. On its own that proves nothing
-- a function returning `ok=True` unconditionally passes it too.

The second half is the half that matters. Every kind of difference the harness claims to detect
is deliberately introduced into a scratch copy and the test asserts it is caught, named to the
column, and reported with both values: a changed cell, a dropped row, an invented row, a
hand-edited triage state. Plus the two failure modes that would hollow out the check itself --
a regenerator echoing back the column it is being tested on, and a curator-held row being
rebuilt over.

The third, smaller half is the coverage inventory: what Zone H the harness does *not* rebuild is
pinned here, so the gap can shrink freely and cannot grow without somebody noticing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.db.fixture import load_fixture
from fermdb.rebuild import (
    Regenerated,
    Regenerator,
    exit_code,
    rebuild_table,
    rebuild_zone_h,
    uncovered_zone_h,
)
from fermdb.rebuild.regenerators import REGENERATORS, gene_group_evidence, source_clause

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mini_atlas"

#: Zone H the harness does not rebuild, as of 2026-09-24, in the fixture atlas. Pinned rather
#: than derived, for the same reason `test_fixture.EXPECTED_COUNTS` is: the number that matters
#: is the one nobody chose. A new Zone H row in a table with no regenerator fails this test,
#: which is the only mechanism that stops T.3's coverage from quietly eroding.
#:
#: `conflict` and `pathway_route` are Zone H in the fixture and nothing in `src/` writes either
#: value: `routes.write_routes` stamps 'I' on every route it enumerates, and no module inserts a
#: `conflict` row at all. `condition_context_facet` is the parsed-from-prose case D.2 describes
#: ("shaken at 200 rpm" -> 200) and `curate.context_writer` writes 'R'. All three are Zone H rows
#: that no recorded code produces.
EXPECTED_UNCOVERED: dict[str, int] = {
    "condition_context_facet": 1,
    "conflict": 1,
    "pathway_route": 1,
}


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    """The phase-0 mini-atlas, in memory."""
    connection = open_db(IN_MEMORY)
    try:
        load_fixture(connection, FIXTURE_DIR)
        yield connection
    finally:
        connection.close()


# ------------------------------------------------------------------- the check passes as built


def test_the_fixture_rebuilds_identically(atlas: sqlite3.Connection) -> None:
    report = rebuild_zone_h(atlas)
    assert report.ok, [row.as_json() for table in report.tables for row in table.rows]
    assert exit_code(report) == 0
    assert report.missing_tables == ()


def test_both_declared_regenerators_actually_had_rows_to_rebuild(
    atlas: sqlite3.Connection,
) -> None:
    """A green check over zero rows is the commonest way this kind of test rots.

    `rebuild_zone_h` reports `ok` when nothing differs, and nothing differs when nothing exists.
    The fixture carries Zone H rows for both declared tables precisely so that cannot happen
    silently here.
    """
    by_table = {table.table: table for table in rebuild_zone_h(atlas).tables}
    assert by_table["gene_group"].stored_rows == 2
    assert by_table["gene_group"].rebuilt_rows == 2
    assert by_table["screening_record"].stored_rows == 4
    # Three rebuilt, one declined: the curator-held row.
    assert by_table["screening_record"].rebuilt_rows == 3


def test_every_branch_of_the_triage_rule_is_exercised(atlas: sqlite3.Connection) -> None:
    """The fixture covers all three outcomes `discovery._triage` can return.

    Without this the check could pass while only ever testing 'included', which is the branch
    that needs no inputs and cannot be got wrong.
    """
    states = {
        row[0]
        for row in atlas.execute(
            "SELECT triage_state FROM screening_record WHERE review_state = 'proposed'"
        )
    }
    assert states == {"included", "excluded", "needs_full_text"}


# ---------------------------------------------------------------- the check can, in fact, fail


def test_a_changed_cell_is_caught_and_named(atlas: sqlite3.Connection) -> None:
    """Perturb one Zone H column and the harness must name the table, row, column and both values.

    This is the test the whole module exists to make possible. "Rebuild as a test" is worth
    nothing unless a wrong Zone H value produces a red run, so the wrong value is written here on
    purpose.
    """
    atlas.execute("UPDATE gene_group SET standard_name = 'WRONG' WHERE id = 'YAA:GG:fxa001w'")

    report = rebuild_zone_h(atlas)

    assert not report.ok
    assert exit_code(report) == 1
    table = next(item for item in report.tables if item.table == "gene_group")
    assert len(table.rows) == 1
    diff = table.rows[0]
    assert diff.kind == "changed"
    assert diff.key == ("YAA:GG:fxa001w",)
    assert [(cell.column, cell.stored, cell.rebuilt) for cell in diff.cells] == [
        ("standard_name", "WRONG", "FXA1")
    ]


def test_a_hand_edited_triage_state_is_caught(atlas: sqlite3.Connection) -> None:
    """The realistic `screening_record` failure: a state edited in place, not by the rule.

    `screening_record` is the atlas's largest Zone H table and its rebuild is a rule check rather
    than a provenance rebuild (see `fermdb.rebuild.regenerators`). This is the failure that check
    does catch, so it is pinned.
    """
    atlas.execute(
        "UPDATE screening_record SET triage_state = 'included', exclusion_reason = NULL "
        "WHERE id = 'YAA:SCREEN:fx-eth-a'"
    )

    report = rebuild_zone_h(atlas)

    assert not report.ok
    table = next(item for item in report.tables if item.table == "screening_record")
    changed = {cell.column for row in table.rows for cell in row.cells}
    assert changed == {"triage_state", "exclusion_reason"}


def test_a_reworded_exclusion_reason_is_caught(atlas: sqlite3.Connection) -> None:
    """T.3's "undeclared input" case, in the form it will actually arrive in.

    Nobody will hand-edit a `triage_state`. What will happen is that the wording of
    `discovery._triage`'s exclusion reason gets improved and the 1,884 rows already carrying the
    old wording are not rebuilt. Simulated here from the data side, which is the same diff.
    """
    atlas.execute(
        "UPDATE screening_record SET exclusion_reason = 'excluded by policy' "
        "WHERE id = 'YAA:SCREEN:fx-eth-a'"
    )

    table = next(item for item in rebuild_zone_h(atlas).tables if item.table == "screening_record")
    assert [cell.column for row in table.rows for cell in row.cells] == ["exclusion_reason"]


def test_a_deleted_zone_h_row_is_caught(atlas: sqlite3.Connection) -> None:
    """A `gene_group` the rebuild produces and the store does not have."""
    atlas.execute("DELETE FROM gene WHERE id = 'YAA:GENE:fx-asm-1-fxa002c'")

    table = next(item for item in rebuild_zone_h(atlas).tables if item.table == "gene_group")
    assert [(row.key, row.kind) for row in table.rows] == [(("YAA:GG:fxa002c",), "only_in_store")]


def test_an_invented_zone_h_row_is_caught(atlas: sqlite3.Connection) -> None:
    """A Zone H row with no Zone R behind it: the shape a hand-written derived row takes."""
    atlas.execute(
        "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
        "membership_method, zone, evidence, confidence) VALUES "
        "('YAA:GG:invented', 'sgd_systematic', 'FXZ999W', 'FXZ9', 'species', 'anchor', 'H', "
        "'typed straight into the database', 'high')"
    )

    table = next(item for item in rebuild_zone_h(atlas).tables if item.table == "gene_group")
    assert [(row.key, row.kind) for row in table.rows] == [(("YAA:GG:invented",), "only_in_store")]


def test_a_curator_held_record_is_declined_rather_than_rebuilt_over(
    atlas: sqlite3.Connection,
) -> None:
    """The one row the rule must not touch, and the reason it must say so out loud.

    `discovery.py` stops refreshing `triage_state` once a curator moves `review_state` off
    'proposed'. A rebuild that ignored that would report every curator acceptance as a failure --
    43 of them in the live atlas on 2026-09-24 -- and the check would be muted within a week.
    Declining is right; declining *silently* is not, so the decline is counted and carries its
    reason.
    """
    table = next(item for item in rebuild_zone_h(atlas).tables if item.table == "screening_record")
    assert table.ok
    assert len(table.declined) == 1
    declined = table.declined[0]
    assert declined.key == ("doi:10.9999/fixture-b", "fx_ethanol_curated")
    assert "review_state='accepted'" in declined.reason


# ------------------------------------------------- the mechanisms that keep the check honest


def test_a_regenerator_cannot_see_the_columns_it_is_tested_on(atlas: sqlite3.Connection) -> None:
    """The harness projects the stored rows down to `key + carried` before handing them over.

    Enforced rather than documented, because a convention cannot fail a build. This is the guard
    against the one bug that would make every test above pass while checking nothing: a
    regenerator that reads the stored Zone H value and returns it.
    """
    seen: list[Mapping[str, Any]] = []

    def peeking(_conn: sqlite3.Connection, carried: tuple[Mapping[str, Any], ...]) -> Regenerated:
        seen.extend(carried)
        return Regenerated(rows=())

    rebuild_table(
        atlas,
        Regenerator(
            table="screening_record",
            key=("publication_id", "family"),
            rebuilt=("triage_state", "exclusion_reason"),
            carried=("review_state",),
            row_source="store",
            source="test",
            regenerate=peeking,
        ),
    )

    assert seen
    for row in seen:
        assert set(row) == {"publication_id", "family", "review_state"}
        assert "triage_state" not in row
        assert "exclusion_reason" not in row


def test_the_declared_coverage_is_reported_not_implied(atlas: sqlite3.Connection) -> None:
    """Partial coverage must be legible in the report, not inferable from the row count.

    `screening_record` has sixteen columns; two of them are rebuilt. A report that printed only
    "4 rows rebuilt identically" would read as the T.3 guarantee over that table, which it is
    not.
    """
    table = next(item for item in rebuild_zone_h(atlas).tables if item.table == "screening_record")
    assert table.row_source == "store"
    assert table.checked_columns == ("triage_state", "exclusion_reason")
    assert set(table.carried_columns) == {
        "product_tier",
        "default_disposition",
        "admitted_criterion",
        "review_state",
    }
    # The columns nobody checks: everything that records which PubMed hit this row came from.
    assert {"first_seen_run_id", "last_seen_run_id", "pmid", "doi"} <= set(table.unchecked_columns)

    groups = next(item for item in rebuild_zone_h(atlas).tables if item.table == "gene_group")
    assert groups.row_source == "zone_r"
    assert groups.carried_columns == ()
    # `zone` itself is the only column outside the key that `gene_group`'s rebuild does not
    # compute, and it is the constant the harness selects on.
    assert groups.unchecked_columns == ("zone",)


# ------------------------------------------------------------------- what nothing rebuilds yet


def test_the_uncovered_zone_h_inventory_is_what_it_was_last_measured_at(
    atlas: sqlite3.Connection,
) -> None:
    """Pinned so the gap can shrink freely and cannot grow unnoticed.

    A new Zone H row in a table no regenerator covers fails here. That is the whole enforcement
    mechanism for T.3's coverage: `exit_code` deliberately does not fail on uncovered rows (a
    check that is red the day it lands gets muted), so the ratchet lives in the test suite.
    """
    covered = frozenset(regenerator.table for regenerator in REGENERATORS)
    found = {item.table: item.rows for item in uncovered_zone_h(atlas, covered=covered)}
    assert found == EXPECTED_UNCOVERED


def test_a_new_uncovered_zone_h_row_shows_up(atlas: sqlite3.Connection) -> None:
    """The inventory walks the live schema, so a table nobody remembered still appears."""
    atlas.execute(
        "INSERT INTO conflict (id, kind, context_difference, status, zone) "
        "VALUES ('YAA:CONF:fx-2', 'direction', 'synthetic', 'open', 'H')"
    )
    found = {
        item.table: item.rows
        for item in uncovered_zone_h(atlas, covered=frozenset(r.table for r in REGENERATORS))
    }
    assert found["conflict"] == 2


# --------------------------------------------------------------------- the derivation details


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        # The shape `omics.genes.gene_rows` writes.
        (
            "[locus_tag=YMR083W] [gene=ADH3] [db_xref=GeneID:855107] "
            "[product=alcohol dehydrogenase ADH3] on NC_001145.3 (nuclear-encoded); "
            "RefSeq FASTA for GCF_000146045.2",
            "RefSeq FASTA for GCF_000146045.2",
        ),
        # A product containing a semicolon: the case that breaks a split on the first '; '.
        (
            "[locus_tag=FXA002C] [gene=FXA2] [db_xref=GeneID:none] "
            "[product=decarboxylase; fixture variant] on NC_FIXTURE01.1 (nuclear-encoded); "
            "synthetic test fixture transcript set",
            "synthetic test fixture transcript set",
        ),
        # Neither marker: returned whole rather than guessed at, so the diff names real text.
        ("written by something else entirely", "written by something else entirely"),
    ],
)
def test_source_clause_survives_a_semicolon_in_the_product(evidence: str, expected: str) -> None:
    assert source_clause(evidence) == expected


def test_gene_group_evidence_matches_the_producing_module(atlas: sqlite3.Connection) -> None:
    """The template is `omics.genes.gene_group_rows`'s, not a paraphrase of it."""
    row = atlas.execute(
        "SELECT systematic_name, evidence FROM gene WHERE id = 'YAA:GENE:fx-asm-1-fxa001w'"
    ).fetchone()
    stored = atlas.execute(
        "SELECT evidence FROM gene_group WHERE id = 'YAA:GG:fxa001w'"
    ).fetchone()["evidence"]
    assert gene_group_evidence(row["systematic_name"], row["evidence"]) == stored
