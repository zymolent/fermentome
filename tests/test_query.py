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
from fermdb.query import pathways as P
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


# --------------------------------------------------------------------------- pathways


@pytest.fixture()
def atlas_pathway() -> sqlite3.Connection:
    """A pathway shaped like the real one: no `competing` column, genes inside the evidence."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE pathway (
            id TEXT PRIMARY KEY, name TEXT, evidence TEXT, confidence TEXT, zone TEXT
        );
        CREATE TABLE reaction (
            id TEXT PRIMARY KEY, name TEXT, ec_number TEXT, equation TEXT,
            compartment_id TEXT, reversible INTEGER, evidence TEXT, confidence TEXT, zone TEXT
        );
        CREATE TABLE pathway_reaction (
            pathway_id TEXT, reaction_id TEXT, step_order INTEGER, step_role_id TEXT
        );
        CREATE TABLE metabolite (
            id TEXT PRIMARY KEY, name TEXT, formula TEXT, zone TEXT
        );
        CREATE TABLE reaction_participant (
            reaction_id TEXT, metabolite_id TEXT, role TEXT, coefficient REAL
        );
        INSERT INTO pathway VALUES ('YAA:PWY:test', 'test', 'curated', 'high', 'R');
        INSERT INTO reaction VALUES (
            'YAA:RXN:leu', '2-isopropylmalate synthase', '2.3.3.13',
            'kiv + accoa -> ipm + coa', 'mitochondrial_matrix', 0,
            'The leucine branch. LEU4 is the major isozyme, LEU9 minor. [genes: LEU4, LEU9]',
            'high', 'R'
        );
        INSERT INTO pathway_reaction VALUES ('YAA:PWY:test', 'YAA:RXN:leu', 1, 'transporter');
        INSERT INTO metabolite VALUES ('kiv', '2-ketoisovalerate', 'C5H7O3', 'R');
        INSERT INTO metabolite VALUES ('nadh', 'NADH', NULL, 'R');
        INSERT INTO reaction_participant VALUES ('YAA:RXN:leu', 'kiv', 'substrate', 1);
        -- NADH as the real loader stores it: a plain substrate, carrier flag dropped.
        INSERT INTO reaction_participant VALUES ('YAA:RXN:leu', 'nadh', 'substrate', 1);
        """
    )
    return connection


def test_competing_is_absent_rather_than_false(atlas_pathway: sqlite3.Connection) -> None:
    """The loader never writes `competing`, so the reader must not invent a value for it.

    Reporting `competing: false` for the valine branch would not be a missing fact but a false
    one -- and one a route ranker would act on.
    """
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    branch = read.reactions[0]
    assert branch.competing.is_known is False
    assert branch.competing.absence is V.Absence.NOT_RECORDED
    assert "value" not in branch.competing.as_json()
    assert branch.competing.display == "not recorded"


def test_the_page_says_it_cannot_be_rendered_as_specified(
    atlas_pathway: sqlite3.Connection,
) -> None:
    """PLAN.md P.3: a diagram that can disagree with the database is decoration."""
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    assert read.is_renderable_as_specified is False
    assert any("competing branches" in gap for gap in read.gaps)
    assert any("genes" in gap for gap in read.gaps)


def test_genes_are_not_parsed_back_out_of_the_evidence_string(
    atlas_pathway: sqlite3.Connection,
) -> None:
    """The names are sitting right there in the evidence text. Recovering them would be a lie.

    A structured gene link the atlas cannot defend is worse than a reported absence, and it would
    hide the loader bug behind a page that looks complete.
    """
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    reaction = read.reactions[0]
    assert "LEU4" in reaction.evidence  # the names ARE present, as free text
    assert reaction.genes.is_known is False  # and are still not claimed as a link


def test_the_reader_picks_up_a_competing_column_if_the_schema_grows_one(
    atlas_pathway: sqlite3.Connection,
) -> None:
    """So fixing the loader needs no change here, and the gap list shrinks on its own."""
    atlas_pathway.execute("ALTER TABLE reaction ADD COLUMN competing INTEGER")
    atlas_pathway.execute("UPDATE reaction SET competing = 1 WHERE id = 'YAA:RXN:leu'")
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    assert read.reactions[0].competing.unwrap() is True
    assert not any("competing branches" in gap for gap in read.gaps)


def test_a_carrier_stored_as_a_substrate_is_not_reported_as_a_non_carrier(
    atlas_pathway: sqlite3.Connection,
) -> None:
    """P.2 wants "cofactors on the edges" and the atlas cannot say which participants are edges.

    The loader never writes role 'cofactor' and `metabolite` has no `carrier` column, so NADH sits
    in `reaction_participant` as a plain substrate. Reporting `is_carrier: false` would be the
    quiet kind of wrong -- every carrier in the atlas confidently drawn as backbone carbon.
    """
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    reaction = read.reactions[0]
    nadh = next(p for p in reaction.participants if p.metabolite_id == "nadh")
    assert nadh.is_carrier.is_known is False
    assert nadh.is_carrier.absence is V.Absence.NOT_RECORDED
    assert reaction.cofactors == ()  # nothing is *known* to be a carrier
    assert any("cofactors" in gap for gap in read.gaps)


def test_an_explicit_cofactor_role_settles_it(atlas_pathway: sqlite3.Connection) -> None:
    """A loader that does use the role the CHECK already permits needs no other change."""
    atlas_pathway.execute(
        "UPDATE reaction_participant SET role = 'cofactor' WHERE metabolite_id = 'nadh'"
    )
    read = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert read is not None
    reaction = read.reactions[0]
    assert [p.metabolite_id for p in reaction.cofactors] == ["nadh"]
    assert [p.metabolite_id for p in reaction.substrates] == ["kiv"]
    assert not any("cofactors" in gap for gap in read.gaps)


def test_an_unknown_pathway_is_none_not_an_empty_graph(atlas_pathway: sqlite3.Connection) -> None:
    """An empty reaction list would read as "a pathway with no reactions", which is a claim."""
    assert P.read_pathway(atlas_pathway, "YAA:PWY:nope") is None


# ------------------------------------------------------- pathways, against the real v6 schema


@pytest.fixture()
def atlas_v6() -> sqlite3.Connection:
    """A pathway in the live schema, so these tests break if `schema.sql` moves under them.

    The `atlas_pathway` fixture above is deliberately v5-shaped and still earns its keep: it is
    the "schema has no such column" case, which an imported pathway or a future regression puts
    the reader back into. This one is the fixed case.
    """
    from fermdb.db import IN_MEMORY, open_db

    conn = open_db(IN_MEMORY)
    conn.executescript(
        """
        INSERT INTO gene_group (id, scope, membership_method, zone, evidence, confidence)
            VALUES ('YAA:GG:ynl104c', 'species', 'anchor', 'R', 'test', 'high');
        INSERT INTO organism (id, name, zone, evidence, confidence)
            VALUES ('YAA:ORG:scer', 'S. cerevisiae', 'R', 'test', 'high');
        INSERT INTO gene (id, organism_id, assembly_accession, standard_name, gene_group_id,
                          zone, evidence, confidence)
            VALUES ('YAA:GENE:leu4', 'YAA:ORG:scer', 'GCF_000146045.2', 'LEU4',
                    'YAA:GG:ynl104c', 'R', 'test', 'high');
        INSERT INTO pathway (id, name, zone, evidence, confidence)
            VALUES ('YAA:PWY:test', 'test', 'R', 'curated', 'high');
        INSERT INTO reaction (id, name, equation, reversible, competing, zone, evidence,
                              confidence)
            VALUES ('YAA:RXN:leu', '2-isopropylmalate synthase', 'kiv + accoa -> ipm + coa',
                    0, 1, 'R', 'the leucine branch', 'high');
        INSERT INTO pathway_reaction (pathway_id, reaction_id, step_order)
            VALUES ('YAA:PWY:test', 'YAA:RXN:leu', 1);
        INSERT INTO reaction_gene (reaction_id, gene_symbol, gene_id, gene_group_id, resolution)
            VALUES ('YAA:RXN:leu', 'LEU4', 'YAA:GENE:leu4', 'YAA:GG:ynl104c', 'resolved');
        INSERT INTO reaction_gene (reaction_id, gene_symbol, gene_id, gene_group_id, resolution)
            VALUES ('YAA:RXN:leu', 'LEU9', NULL, NULL, 'unresolved');
        INSERT INTO metabolite (id, name, carbons, carrier, zone, evidence, confidence)
            VALUES ('kiv', '2-ketoisovalerate', 5, 0, 'R', 'test', 'high');
        INSERT INTO metabolite (id, name, carbons, carrier, pair, redox, zone, evidence,
                                confidence)
            VALUES ('nadh', 'NADH', 0, 1, 'nad', 'reduced', 'R', 'test', 'high');
        INSERT INTO reaction_participant (reaction_id, metabolite_id, role, coefficient)
            VALUES ('YAA:RXN:leu', 'kiv', 'substrate', 1);
        INSERT INTO reaction_participant (reaction_id, metabolite_id, role, coefficient)
            VALUES ('YAA:RXN:leu', 'nadh', 'substrate', 1);
        """
    )
    yield conn
    conn.close()


def test_the_page_is_renderable_once_the_facts_are_stored(atlas_v6: sqlite3.Connection) -> None:
    read = P.read_pathway(atlas_v6, "YAA:PWY:test")
    assert read is not None
    assert read.gaps == ()
    assert read.is_renderable_as_specified is True


def test_competing_is_read_as_the_curator_set_it(atlas_v6: sqlite3.Connection) -> None:
    read = P.read_pathway(atlas_v6, "YAA:PWY:test")
    assert read is not None
    assert read.reactions[0].competing.unwrap() is True


def test_an_unresolved_gene_keeps_its_symbol_and_claims_no_identity(
    atlas_v6: sqlite3.Connection,
) -> None:
    """LEU9 is named by the curated file and absent from `gene`. It must stay LEU9.

    CONVENTIONS.md forbids mapping it to the nearest plausible match, and LEU4 is sitting right
    there -- a wrong link would render exactly as confidently as the right one beside it.
    """
    read = P.read_pathway(atlas_v6, "YAA:PWY:test")
    assert read is not None
    genes = {g.symbol: g for g in read.reactions[0].genes.unwrap()}
    assert genes["LEU4"].is_resolved
    assert genes["LEU4"].gene_id.unwrap() == "YAA:GENE:leu4"
    assert not genes["LEU9"].is_resolved
    assert genes["LEU9"].symbol == "LEU9"
    assert "value" not in genes["LEU9"].gene_id.as_json()


def test_a_carrier_that_is_also_a_substrate_is_both(atlas_v6: sqlite3.Connection) -> None:
    """Role says which side of the arrow; carrier says whether the skeleton runs through it."""
    read = P.read_pathway(atlas_v6, "YAA:PWY:test")
    assert read is not None
    reaction = read.reactions[0]
    assert [p.metabolite_id for p in reaction.cofactors] == ["nadh"]
    assert {p.metabolite_id for p in reaction.substrates} == {"kiv", "nadh"}
    kiv = next(p for p in reaction.participants if p.metabolite_id == "kiv")
    assert kiv.is_carrier.unwrap() is False  # assessed, and not a carrier


def test_no_genes_named_is_not_the_same_as_nowhere_to_record_them(
    atlas_v6: sqlite3.Connection, atlas_pathway: sqlite3.Connection
) -> None:
    """An empty list and an absence answer two different questions."""
    atlas_v6.execute("DELETE FROM reaction_gene WHERE reaction_id = 'YAA:RXN:leu'")
    with_table = P.read_pathway(atlas_v6, "YAA:PWY:test")
    without_table = P.read_pathway(atlas_pathway, "YAA:PWY:test")
    assert with_table is not None and without_table is not None
    assert with_table.reactions[0].genes.unwrap() == ()  # looked, found none
    assert without_table.reactions[0].genes.is_known is False  # nowhere to look


def test_a_join_may_carry_more_than_one_condition(conn: sqlite3.Connection) -> None:
    """A single-condition join on a non-unique column silently multiplies rows.

    `span` and `curation_task` share `record_path`, which is unique only within an extraction.
    Joining on it alone cross-joins every extraction of a publication against every other -- and
    the inflated count looks entirely plausible, which is why the builder has to express the
    second condition rather than leaving callers to bolt it on.
    """
    conn.execute("CREATE TABLE other (id TEXT, name TEXT, tag TEXT)")
    conn.executemany(
        "INSERT INTO other VALUES (?,?,?)",
        [("id1", "name1", "a"), ("id1", "name1", "b")],
    )
    one = (
        B.Select("thing", alias="t")
        .columns("t.id AS id")
        .join("other", "t.id = o.id", alias="o", kind="INNER")
        .where("t.id = ?", "id1")
        .page(conn)
    )
    assert len(one) == 2  # the multiplication

    both = (
        B.Select("thing", alias="t")
        .columns("t.id AS id")
        .join("other", ("t.id = o.id", "t.name = o.name"), alias="o", kind="INNER")
        .where("t.id = ? AND o.tag = ?", "id1", "a")
        .page(conn)
    )
    assert len(both) == 1


def test_every_join_condition_is_still_checked(conn: sqlite3.Connection) -> None:
    with pytest.raises(B.QueryError):
        B.Select("thing").join("other", ("a = b", "c; DROP TABLE thing = d"))
    with pytest.raises(B.QueryError):
        B.Select("thing").join("other", [])


# --------------------------------------------------------------------------- genes


def test_a_gene_is_findable_by_any_of_its_three_names(atlas_v6: sqlite3.Connection) -> None:
    """Internal id, systematic name and standard name are all how a person refers to a gene.

    Accepting only the atlas's own identifier would make the page usable only by someone who
    already knows the atlas.
    """
    from fermdb.query import genes as G

    by_id = G.read_gene(atlas_v6, "YAA:GENE:leu4")
    by_standard = G.read_gene(atlas_v6, "leu4")  # case-insensitive
    assert by_id is not None and by_standard is not None
    assert by_id.id == by_standard.id
    assert G.read_gene(atlas_v6, "NOSUCHGENE") is None


def test_the_gene_page_names_the_sections_it_cannot_fill(atlas_v6: sqlite3.Connection) -> None:
    """P.2 lists nine sections; this reader serves four. A page that drops five looks complete."""
    from fermdb.query import genes as G

    read = G.read_gene(atlas_v6, "LEU4")
    assert read is not None
    absent = read.absent_sections
    assert {"expression", "interactions", "regulators", "variants_across_strains"} <= set(absent)
    assert "matrices" in absent["expression"]  # says where the numbers actually are
    assert all(why for why in absent.values())  # every absence carries a reason
    assert absent["engineering_history"].startswith("no modification rows")


def test_a_competing_reaction_is_visible_on_the_gene(atlas_v6: sqlite3.Connection) -> None:
    """The field schema v6 recovered, surfacing where a reader would look for it.

    "LEU4 is in the pathway" and "LEU4 takes carbon out of it" are different facts, and before
    `reaction.competing` existed the page could only say the first.
    """
    from fermdb.query import genes as G

    atlas_v6.execute("UPDATE reaction SET competing = 1 WHERE id = 'YAA:RXN:leu'")
    read = G.read_gene(atlas_v6, "LEU4")
    assert read is not None
    assert len(read.reactions) == 1
    assert read.reactions[0].competing.unwrap() is True
    assert len(read.competing_reactions) == 1
    assert read.as_json()["counts"]["competing_reactions"] == 1


def test_an_unset_competing_flag_is_absent_not_false(atlas_v6: sqlite3.Connection) -> None:
    """An imported reaction nobody assessed must not read as "known not to compete"."""
    from fermdb.query import genes as G

    atlas_v6.execute("UPDATE reaction SET competing = NULL WHERE id = 'YAA:RXN:leu'")
    read = G.read_gene(atlas_v6, "LEU4")
    assert read is not None
    assert read.reactions[0].competing.is_known is False
    assert read.competing_reactions == ()  # not known to compete is not the same as not competing


# --------------------------------------------------------------------------- the review page


def test_the_review_page_is_self_contained_and_ordered(atlas: sqlite3.Connection) -> None:
    """Strains before measurements, because promotion depends on that order.

    The page is a snapshot that has to work offline, so everything it needs is embedded. And the
    generated commands must be runnable top to bottom -- a measurement's accept is useless before
    its strain exists.
    """
    from fermdb.query.reviewhtml import KIND_ORDER

    assert KIND_ORDER[0] == "strains"
    assert KIND_ORDER.index("strains") < KIND_ORDER.index("measurements")
    assert KIND_ORDER.index("measurements") < KIND_ORDER.index("modifications")


def test_the_page_never_writes_to_the_atlas(atlas_v6: sqlite3.Connection) -> None:
    """D.3's layering rule, and a browser cannot reach a local SQLite file anyway.

    Generating the page is a read. Decisions leave as `fermdb curate` commands, so a human is
    still the actor and the audit log still records one.
    """
    from fermdb.query.reviewhtml import build_review_page

    before = atlas_v6.total_changes
    page = build_review_page(atlas_v6, curator="tester")
    assert atlas_v6.total_changes == before
    assert "<script>" in page and "const DATA" in page
    # No path back to the database is embedded anywhere in it.
    assert "sqlite" not in page.lower()
    assert "fermdb curate accept" in page
