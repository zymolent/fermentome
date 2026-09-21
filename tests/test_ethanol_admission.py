"""Tests for `fermdb.literature.ethanol` — the capped ethanol layer's admission control.

Three properties carry the weight.

**The sub-budget is the whole point.** E5's outer bound is 642 publications against a ~150 total,
so without a per-criterion ceiling the broadest criterion eats the layer and E1–E4 arrive empty.
A budget that does not actually stop an admission is decoration.

**E6 exists.** PLAN.md's phase-2 acceptance still says "E1–E5", but the owner accepted E6 on
2026-09-20, the schema permits it, and discovery has tagged 279 records under it. A loader
enforcing E1–E5 would reject every one and make the phase unpassable.

**Unspent is reported, never reallocated.** "We found fewer admissible papers than expected" is a
finding about the literature, not slack to consume.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.literature.ethanol import (
    CRITERION_BUDGET,
    PUBLICATION_CAP,
    SLOTS,
    admit,
    budget_status,
    unspent_report,
    validate_admission,
)


def _seed(conn: sqlite3.Connection, publication_id: str, *, tier: str = "ethanol") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO publication (id, title, zone, evidence, confidence) "
        "VALUES (?, ?, 'R', 'test fixture', 'unverified')",
        (publication_id, f"title for {publication_id}"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO search_run "
        "(id, family, db, term, started_at, query_families_version) "
        "VALUES ('RUN', 'fam', 'pubmed', 'ethanol', '2026-01-01', 1)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, zone) "
        "VALUES (?, ?, 'fam', 'RUN', 'RUN', 'needs_full_text', ?, "
        "'exclude_unless_admitted', 'proposed', 'H')",
        (f"SCR:{publication_id}", publication_id, tier),
    )
    conn.commit()


def _accept(conn: sqlite3.Connection, publication_id: str, criterion: str) -> None:
    """Mark a row admitted directly, to build up a spent budget without going through `admit`."""
    conn.execute(
        "UPDATE screening_record SET review_state='accepted', triage_state='included', "
        "admitted_criterion=? WHERE publication_id=?",
        (criterion, publication_id),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    database = open_db(tmp_path / "eth.sqlite3")
    yield database
    database.close()


@pytest.fixture
def settings() -> Settings:
    return Settings.load()


# ----------------------------------------------------------------- the budget and the slots


def test_the_sub_budget_sums_to_the_publication_cap() -> None:
    """150, the number the owner accepted. If these drift apart the layer silently over- or
    under-commits and nobody notices until curation runs out of room."""
    assert sum(CRITERION_BUDGET.values()) == PUBLICATION_CAP


def test_every_slot_maps_to_a_budgeted_criterion() -> None:
    for slot in SLOTS:
        assert slot.criterion in CRITERION_BUDGET, f"slot {slot.number} has no budget"


def test_all_seven_slots_are_present_and_e4_carries_two() -> None:
    """Slots 3 and 4 share criterion E4 — acute shock and adapted growth are distinct biology and
    the plan forbids merging them, but they rest on one admission rule."""
    assert len(SLOTS) == 7
    assert [s.number for s in SLOTS] == [1, 2, 3, 4, 5, 6, 7]
    assert [s.number for s in SLOTS if s.criterion == "E4"] == [3, 4]


def test_e6_is_accepted_although_plan_md_still_says_e1_to_e5() -> None:
    """The discrepancy this module exists to survive. E6 was accepted 2026-09-20 with a
    25-publication budget and already tags 279 records; enforcing PLAN.md's stale sentence would
    reject all of them."""
    assert "E6" in CRITERION_BUDGET
    assert CRITERION_BUDGET["E6"] == 25
    assert any(slot.criterion == "E6" for slot in SLOTS)


def test_e5_holds_the_largest_share() -> None:
    """Load-bearing for DUET's architecture, and still only a seventh of its 642 outer bound."""
    assert CRITERION_BUDGET["E5"] == max(CRITERION_BUDGET.values())


# ------------------------------------------------------------------------------ validation


def test_an_unknown_criterion_is_refused(conn: sqlite3.Connection, settings: Settings) -> None:
    _seed(conn, "doi:10.1/a")
    problems = validate_admission(conn, settings, publication_id="doi:10.1/a", criterion="E9")
    assert [p.code for p in problems] == ["unknown_criterion"]


def test_an_isobutanol_tier_paper_cannot_be_admitted(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Admission criteria belong to the ethanol tier only — the schema says so too."""
    _seed(conn, "doi:10.1/iso", tier="isobutanol")
    problems = validate_admission(conn, settings, publication_id="doi:10.1/iso", criterion="E2")
    assert "wrong_tier" in {p.code for p in problems}


def test_a_paper_screened_into_both_tiers_is_still_admissible(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The regression that shipped. A publication carries one screening row per query family it
    matched, and 103 of them match both an ethanol family and an isobutanol one — a mitochondrial
    ethanol paper legitimately answers both.

    The first version of `validate_admission` took `LIMIT 1` with no ORDER BY and refused a real
    E5 candidate as 'wrong_tier' on the strength of its isobutanol row. Nothing caught it until
    the validator was pointed at the live database.
    """
    _seed(conn, "doi:10.1/dual", tier="ethanol")
    conn.execute(
        "INSERT INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, zone) "
        "VALUES ('SCR:dual-iso', 'doi:10.1/dual', 'mtdna_fam', 'RUN', 'RUN', 'included', "
        "'isobutanol', 'include_unless_excluded', 'proposed', 'H')"
    )
    conn.commit()
    problems = validate_admission(conn, settings, publication_id="doi:10.1/dual", criterion="E3")
    assert [p.code for p in problems] == [], "an ethanol row anywhere makes it ethanol-tier"


def test_an_unscreened_paper_cannot_be_admitted(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Admission has to be auditable back to a search run (PLAN.md R.2)."""
    conn.execute(
        "INSERT INTO publication (id, title, zone, evidence, confidence) "
        "VALUES ('doi:10.1/orphan', 't', 'R', 'x', 'unverified')"
    )
    conn.commit()
    problems = validate_admission(conn, settings, publication_id="doi:10.1/orphan", criterion="E2")
    assert "not_screened" in {p.code for p in problems}


def test_a_budget_that_is_full_refuses_the_next_admission(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The test that makes the sub-budget real rather than decorative."""
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")

    _seed(conn, "doi:10.4/one-too-many")
    problems = validate_admission(
        conn, settings, publication_id="doi:10.4/one-too-many", criterion="E4"
    )
    assert "budget_exhausted" in {p.code for p in problems}


def test_a_full_budget_does_not_block_a_different_criterion(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Budgets are per criterion. Exhausting E4 must not close the layer."""
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")

    _seed(conn, "doi:10.2/fine")
    problems = validate_admission(conn, settings, publication_id="doi:10.2/fine", criterion="E2")
    assert [p.code for p in problems] == []


def test_e5_without_a_stored_full_text_cannot_be_checked(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """E5 is the only criterion with a content rule, so it is the only one that needs the text.
    Refusing is right: an unchecked E5 admission is how the broadest criterion eats the layer."""
    _seed(conn, "doi:10.5/no-text")
    problems = validate_admission(conn, settings, publication_id="doi:10.5/no-text", criterion="E5")
    assert "e5_unreadable" in {p.code for p in problems}


def test_a_non_e5_criterion_needs_no_full_text(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _seed(conn, "doi:10.3/no-text")
    problems = validate_admission(conn, settings, publication_id="doi:10.3/no-text", criterion="E3")
    assert [p.code for p in problems] == []


# --------------------------------------------------------------------------------- admitting


def test_admit_writes_and_survives_reopening(tmp_path: Path, settings: Settings) -> None:
    database = tmp_path / "admit.sqlite3"
    first = open_db(database)
    try:
        _seed(first, "doi:10.2/keeper")
        assert admit(first, settings, publication_id="doi:10.2/keeper", criterion="E2") == ()
    finally:
        first.close()

    second = open_db(database, create=False)
    try:
        row = second.execute(
            "SELECT review_state, triage_state, admitted_criterion FROM screening_record "
            "WHERE publication_id = 'doi:10.2/keeper'"
        ).fetchone()
        assert row["review_state"] == "accepted"
        assert row["triage_state"] == "included"
        assert row["admitted_criterion"] == "E2"
    finally:
        second.close()


def test_a_failed_admission_writes_nothing(conn: sqlite3.Connection, settings: Settings) -> None:
    _seed(conn, "doi:10.1/iso2", tier="isobutanol")
    problems = admit(conn, settings, publication_id="doi:10.1/iso2", criterion="E2")
    assert problems
    row = conn.execute(
        "SELECT review_state FROM screening_record WHERE publication_id = 'doi:10.1/iso2'"
    ).fetchone()
    assert row["review_state"] == "proposed"


def test_a_slot_that_does_not_carry_the_criterion_is_refused(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Slot 6 is E5; admitting an E2 paper "into slot 6" is a curator slip worth catching."""
    _seed(conn, "doi:10.2/wrongslot")
    problems = admit(conn, settings, publication_id="doi:10.2/wrongslot", criterion="E2", slot=6)
    assert [p.code for p in problems] == ["slot_criterion_mismatch"]


# ---------------------------------------------------------------------------------- reporting


def test_an_empty_layer_reports_every_share_unspent(conn: sqlite3.Connection) -> None:
    lines = unspent_report(conn)
    assert len(lines) == len(CRITERION_BUDGET)
    assert all("unspent" in line for line in lines)


def test_a_filled_criterion_drops_out_of_the_unspent_report(conn: sqlite3.Connection) -> None:
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")
    assert not any(line.startswith("E4") for line in unspent_report(conn))


def test_budget_status_counts_a_paper_once_even_across_families(
    conn: sqlite3.Connection,
) -> None:
    """A paper matching several query families has several screening rows. Charging its criterion
    once per row would overstate the spend and close the budget early."""
    _seed(conn, "doi:10.5/multi")
    conn.execute(
        "INSERT INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, admitted_criterion, zone) "
        "VALUES ('SCR:second', 'doi:10.5/multi', 'other_fam', 'RUN', 'RUN', 'included', "
        "'ethanol', 'exclude_unless_admitted', 'accepted', 'E5', 'H')"
    )
    _accept(conn, "doi:10.5/multi", "E5")
    line = next(entry for entry in budget_status(conn) if entry.criterion == "E5")
    assert line.admitted == 1
