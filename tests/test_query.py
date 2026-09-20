"""Tests for `fermdb.query`.

The theme is that every failure this layer can have produces *plausible output*, never an error.
A three-state absence flattened into JSON null renders as a dash and looks fine. An evidence level
that is NULL because two papers disagree renders as a dash and looks fine. A page of 20 rows that
is really a limit of 20 renders as 20 rows and looks fine. None of these throw, none are visible
in a screenshot, and all of them are wrong.

So most of what follows asserts on the *shape of the wire payload* rather than on Python objects:
the wire is where the distinctions get lost, and a test that only checks `Value.absence` would
pass right through a broken `as_json`.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from fermdb.query import builder as B
from fermdb.query import coverage as C
from fermdb.query import values as V

# --------------------------------------------------------------------------- the three states


def test_the_three_absences_are_distinct_on_the_wire() -> None:
    """The rule CONVENTIONS.md states, checked where it actually breaks: after serialization."""
    payloads = [
        V.from_text_column(None).as_json(),
        V.from_text_column("NA").as_json(),
        V.from_text_column("unknown").as_json(),
    ]
    displays = [payload["display"] for payload in payloads]
    assert displays == ["not recorded", "not applicable", "unknown"]
    assert len({json.dumps(payload, sort_keys=True) for payload in payloads}) == 3
    # Every one of them explains itself, so a tooltip needs no lookup table in the frontend.
    assert all(payload["absent_because"] for payload in payloads)


def test_an_absent_value_has_no_value_key_at_all() -> None:
    """`"value": null` is the bug this shape exists to prevent.

    A consumer writing `row.value ?? "-"` collapses all three states. With no `value` key, that
    same consumer gets `undefined`, which is a visible bug rather than a plausible dash.
    """
    absent = V.from_text_column(None).as_json()
    assert "value" not in absent
    assert absent["absent"] == "not_recorded"

    known = V.from_text_column("CEN.PK113-7D").as_json()
    assert known["value"] == "CEN.PK113-7D"
    assert "absent" not in known


def test_zero_is_not_an_absence() -> None:
    """ "Never coerce any of the three into another, and never into zero." The converse too."""
    zero = V.Value.known(0.0, zone=V.Zone.REPORTED)
    assert zero.is_known
    assert zero.as_json()["value"] == 0.0
    assert zero.display == "0.0"
    assert "absent" not in zero.as_json()


def test_a_value_cannot_hold_both_or_neither() -> None:
    with pytest.raises(V.QueryValueError):
        V.Value(held="x", absence=V.Absence.NOT_RECORDED)
    with pytest.raises(V.QueryValueError):
        V.Value(held=None, absence=None)


def test_state_column_pairs_are_read_as_written() -> None:
    assert V.from_state_column(30.0, "recorded").unwrap() == 30.0
    assert V.from_state_column(None, "not_applicable").absence is V.Absence.NOT_APPLICABLE
    assert V.from_state_column(None, "unknown").absence is V.Absence.UNKNOWN
    assert V.from_state_column(None, None).absence is V.Absence.NOT_RECORDED


def test_a_mismatched_numeric_and_state_pair_raises_rather_than_reporting_absent() -> None:
    """Both directions are schema-CHECK violations, so reaching this code means something broke.

    Reporting "not recorded" here would bury the bug in the one place nobody inspects: a field
    that looks empty on a page full of empty fields.
    """
    with pytest.raises(V.QueryValueError):
        V.from_state_column(None, "recorded")
    with pytest.raises(V.QueryValueError):
        V.from_state_column(7.0, None)


def test_zone_i_says_it_may_not_support_a_conclusion() -> None:
    assert V.Zone.INFERRED.may_support_a_conclusion is False
    assert V.Zone.REPORTED.may_support_a_conclusion is True
    assert V.Zone.HARMONIZED.may_support_a_conclusion is True
    payload = V.Value.known("proposed titre", zone=V.Zone.INFERRED).as_json()
    assert payload["zone"] == "I"
    assert payload["zone_display"] == "inferred"


# --------------------------------------------------------------------------- evidence levels


def test_no_evidence_and_an_unresolved_conflict_do_not_render_alike() -> None:
    """The `assertion_level` view returns NULL for both. They are opposite states.

    One means the atlas knows nothing. The other means it holds direct evidence on both sides and
    has declined to grade it (PLAN.md J.4, "conflicts are first-class"). Rendering both as a dash
    would hide the more interesting of the two completely.
    """
    nothing = V.EvidenceLevel(level=None, basis="no_evidence")
    conflicted = V.EvidenceLevel(level=None, basis="direct_evidence_discordant")

    assert nothing.display == "no evidence"
    assert conflicted.display == "conflicted"
    assert conflicted.is_conflicted and not nothing.is_conflicted
    assert nothing.as_json() != conflicted.as_json()


def test_an_ungraded_level_must_say_why() -> None:
    with pytest.raises(V.QueryValueError):
        V.EvidenceLevel(level=None, basis="")
    # A basis that *does* grade cannot carry a null level: that combination is incoherent.
    with pytest.raises(V.QueryValueError):
        V.EvidenceLevel(level=None, basis="direct_evidence")


def test_an_override_is_always_displayed_as_one() -> None:
    plain = V.EvidenceLevel(level="L2", basis="direct_evidence_replicated")
    overridden = V.EvidenceLevel(
        level="L2",
        basis="hypothesis_or_insufficient_support",
        is_overridden=True,
        override_reason="curator: the replication is in the supplement",
    )
    assert plain.display == "L2"
    assert overridden.display == "L2 (overridden)"
    assert overridden.as_json()["override_reason"]


def test_ungraded_bases_match_the_view() -> None:
    """If `schema.sql` grows a third ungraded basis, this fails rather than raising at runtime."""
    from fermdb.db import schema_sql

    sql = schema_sql()
    for basis in V.EvidenceLevel.UNGRADED_BASES:
        assert f"'{basis}'" in sql, f"{basis!r} is not a basis the assertion_level view emits"


def test_a_cited_payload_cannot_omit_its_source() -> None:
    """PLAN.md O.2.1 as a type: there is no way to build one without naming what it cites."""
    cited = V.Cited(payload={"titer": 2.09}, source_kind="publication", source_id="doi:10.1/x")
    assert cited.as_json()["source_id"] == "doi:10.1/x"
    with pytest.raises(TypeError):
        V.Cited(payload={})  # type: ignore[call-arg]


def test_a_quantity_keeps_the_reported_form_beside_the_derived_one() -> None:
    quantity = V.Quantity(
        reported=V.Value.known(2.09, zone=V.Zone.REPORTED),
        unit_reported=V.Value.known("g/L", zone=V.Zone.REPORTED),
        si=V.Value.known(2.09, zone=V.Zone.HARMONIZED),
        unit_si=V.Value.known("g/L", zone=V.Zone.HARMONIZED),
    )
    payload = quantity.as_json()
    assert payload["display"] == "2.09 g/L"
    assert payload["reported"]["zone"] == "R"
    assert payload["si"]["zone"] == "H"


def test_a_below_detection_value_is_not_rendered_as_a_number() -> None:
    quantity = V.Quantity(
        reported=V.Value.known(0.01, zone=V.Zone.REPORTED),
        unit_reported=V.Value.known("g/L", zone=V.Zone.REPORTED),
        si=V.Value.absent(V.Absence.NOT_RECORDED),
        unit_si=V.Value.absent(V.Absence.NOT_RECORDED),
        is_below_lod=True,
    )
    assert quantity.display == "<0.01 g/L"


# --------------------------------------------------------------------------- the builder


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE thing (id TEXT PRIMARY KEY, name TEXT, zone TEXT)")
    connection.executemany(
        "INSERT INTO thing VALUES (?,?,?)",
        [(f"id{n}", f"name{n}", "R") for n in range(10)],
    )
    return connection


def test_values_are_parameters_and_never_text(conn: sqlite3.Connection) -> None:
    statement, params = B.Select("thing").where("name = ?", "'; DROP TABLE thing; --").sql()
    assert "DROP" not in statement
    assert params == ("'; DROP TABLE thing; --",)
    assert B.Select("thing").where("name = ?", "'; DROP TABLE thing; --").page(conn).rows == ()
    assert conn.execute("SELECT COUNT(*) FROM thing").fetchone()[0] == 10


def test_identifiers_are_checked(conn: sqlite3.Connection) -> None:
    with pytest.raises(B.QueryError):
        B.Select("thing; DROP TABLE thing")
    with pytest.raises(B.QueryError):
        B.Select("thing").columns("name, (SELECT 1)")
    with pytest.raises(B.QueryError):
        B.Select("thing").order_by("name; DELETE FROM thing")
    with pytest.raises(B.QueryError):
        B.Select("thing").join("other", "a = b", kind="RIGHT")


def test_a_placeholder_count_mismatch_is_caught_at_build_time() -> None:
    with pytest.raises(B.QueryError):
        B.Select("thing").where("name = ? AND id = ?", "only-one")


def test_a_truncated_page_says_so(conn: sqlite3.Connection) -> None:
    """The failure this prevents: a consumer reporting a count that is really a limit."""
    page = B.Select("thing").page(conn, limit=3)
    assert len(page) == 3
    assert page.truncated is True
    assert "page, not a total" in page.as_json()["note"]

    whole = B.Select("thing").page(conn, limit=50)
    assert len(whole) == 10
    assert whole.truncated is False
    assert "note" not in whole.as_json()


def test_filtering_by_nothing_matches_nothing(conn: sqlite3.Connection) -> None:
    """An empty `IN ()` must not silently become "no filter", which would return everything."""
    assert B.Select("thing").where_in("id", []).page(conn).rows == ()
    assert len(B.Select("thing").where_in("id", ["id1", "id2"]).page(conn)) == 2


def test_one_refuses_to_pick_a_row_when_there_are_two(conn: sqlite3.Connection) -> None:
    assert B.Select("thing").where("id = ?", "id3").one(conn)["name"] == "name3"
    assert B.Select("thing").where("id = ?", "nope").one(conn) is None
    with pytest.raises(B.QueryError):
        B.Select("thing").one(conn)


def test_a_select_is_immutable_under_chaining(conn: sqlite3.Connection) -> None:
    base = B.Select("thing")
    narrowed = base.where("id = ?", "id1")
    assert len(base.page(conn)) == 10
    assert len(narrowed.page(conn)) == 1


def test_offset_without_limit_is_refused() -> None:
    with pytest.raises(B.QueryError):
        B.Select("thing").sql(offset=10)


# --------------------------------------------------------------------------- coverage


@pytest.fixture()
def atlas() -> sqlite3.Connection:
    """A miniature atlas: one populated table, two empty ones, one with proposals queued."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE publication (id TEXT PRIMARY KEY);
        CREATE TABLE measurement (id TEXT PRIMARY KEY);
        CREATE TABLE conflict (id TEXT PRIMARY KEY);
        CREATE TABLE curation_task (
            id TEXT PRIMARY KEY, record_kind TEXT NOT NULL, status TEXT NOT NULL
        );
        INSERT INTO publication VALUES ('pub1'), ('pub2');
        INSERT INTO curation_task VALUES
            ('t1', 'measurements', 'pending'),
            ('t2', 'measurements', 'pending'),
            ('t3', 'measurements', 'resolved');
        """
    )
    return connection


def test_an_empty_table_with_proposals_reads_differently_from_one_without(
    atlas: sqlite3.Connection,
) -> None:
    """The distinction the whole module exists for. Both tables hold zero rows."""
    report = C.read_coverage(
        atlas,
        entities=(
            ("publication", "publications"),
            ("measurement", "measurements"),
            ("conflict", "conflicts"),
        ),
    )
    states = {entity.entity: entity.state for entity in report.entities}
    assert states == {
        "publication": "populated",
        "measurement": "awaiting_curation",
        "conflict": "never_populated",
    }
    waiting = next(e for e in report.entities if e.entity == "measurement")
    assert waiting.pending == 2  # the resolved task is not queued
    assert waiting.is_actionable
    assert "curation, not acquisition" in waiting.note


def test_a_missing_table_is_not_reported_as_an_empty_one(atlas: sqlite3.Connection) -> None:
    """Zero rows and no such table are different problems with different owners."""
    report = C.read_coverage(atlas, entities=(("strain", "strains"),))
    assert report.entities[0].state == "missing_table"
    assert report.entities[0].is_actionable is False


def test_every_record_kind_appears_even_at_zero(atlas: sqlite3.Connection) -> None:
    """An omitted kind would be ambiguous between "none queued" and "not a thing"."""
    from fermdb.extract.schemas import RECORD_KINDS

    report = C.read_coverage(atlas, entities=(("publication", "publications"),))
    assert set(report.pending_by_kind) == set(RECORD_KINDS)
    assert report.pending_total == 2


def test_page_readiness_names_what_blocks_each_page(atlas: sqlite3.Connection) -> None:
    pages = {page.page: page for page in C.page_readiness(atlas)}
    assert pages["Publication"].renderable is True
    # Product needs `product` (missing here) and `measurement` (empty, but queued).
    assert pages["Product"].renderable is False
    assert pages["Product"].blocked_by_curation is True
    assert "awaiting curation" in pages["Product"].note
    # Evidence has nothing queued: a different message, because it is a different situation.
    assert pages["Evidence"].blocked_by_curation is False
    assert "nothing proposed" in pages["Evidence"].note


def test_every_record_kind_has_a_destination_table() -> None:
    """A kind with nowhere to land would be curated into a hole."""
    from fermdb.extract.schemas import RECORD_KINDS

    assert set(C.DESTINATION_TABLE) == set(RECORD_KINDS)


def test_every_page_requirement_is_a_real_table() -> None:
    """P.2's page map is written by hand; a typo would silently mark a page unrenderable."""
    from fermdb.db import IN_MEMORY, open_db

    connection = open_db(IN_MEMORY)
    try:
        present = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    finally:
        connection.close()
    required = {table for _, requires in C.PAGES for table in requires}
    assert required <= present, f"not in the schema: {sorted(required - present)}"


def test_coverage_entities_are_real_tables() -> None:
    from fermdb.db import IN_MEMORY, open_db

    connection = open_db(IN_MEMORY)
    try:
        present = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()
    listed = {table for table, _ in C.ENTITIES}
    assert listed <= present, f"not in the schema: {sorted(listed - present)}"
