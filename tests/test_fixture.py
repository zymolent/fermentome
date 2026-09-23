"""Tests for the phase-0 mini-atlas fixture and its loader (`fermdb.db.fixture`).

Every future test in this project runs against this fixture, so what matters here is not just
"it loads" but that each deliberately-planted edge case behaves the way PLAN.md Q and
docs/reference/CONVENTIONS.md say it must: a claimed relocalization with no verification still
reads as `none_reported` rather than blank; NULL / 'NA' / 'unknown' stay three different things,
in text columns and in numerics alike; an AI-only assertion lands at L5 in Zone I while a
direct_perturbation-backed one lands at L1; and two conflicting measurements are recoverable as a
first-class conflict rather than one silently overwriting the other.

The fixture's centrepiece is the encoding-genome contrast: two parts, the same enzyme bound for
the same compartment, differing only in which genome carries the gene. The nuclear-encoded one
keeps its CUN run and is accepted (it is translated on cytosolic ribosomes under table 1 and then
imported); the mtDNA-encoded one is rejected until recoded. A model that keyed the genetic code
on the compartment would collapse the two and tell a bench scientist to recode the first.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.db.fixture import FixtureError, load_fixture
from fermdb.genetic_code import (
    TABLE_1,
    TABLE_3,
    AmbiguousCompartmentError,
    diff_tables,
    translate,
)
from fermdb.recode import check_compartment_safety

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mini_atlas"

#: Expected row count per table, kept here (rather than derived) so a change to the fixture that
#: silently drops a row fails a test instead of just producing a smaller atlas.
EXPECTED_COUNTS: dict[str, int] = {
    "organism": 1,
    "strain": 2,
    "product": 1,
    "product_theoretical_yield": 3,
    "publication": 2,
    # One per query family in screening_record.yaml.
    "search_run": 3,
    # One per branch of the R.2 triage rule, plus the curator-held row the rule may not rewrite.
    "screening_record": 4,
    # Five hand-written Zone R groups, plus the two Zone H groups the T.3 rebuild check
    # regenerates from the two `gene` rows below.
    "gene_group": 7,
    "gene": 2,
    "part": 7,
    "pathway": 1,
    "pathway_configuration": 1,
    "pathway_route": 1,
    "pathway_route_step": 5,
    "condition_context": 1,
    "condition_context_facet": 3,
    "measurement": 2,
    "modification": 2,
    "modification_localization_change": 1,
    "modification_mtdna_edit": 1,
    "mtdna_insertion": 1,
    "assertion": 4,
    "evidence_item": 4,
    "conflict": 1,
    "conflict_member": 2,
    # One per assertion. PLAN.md J.5's third arm: an assertion that resolves to a paper but to no
    # curator is the failure L.5 exists to prevent, so the count is tied to `assertion` above.
    "curation_event": 4,
}


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory atlas, schema applied but not yet carrying the fixture."""
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def loaded(conn: sqlite3.Connection) -> sqlite3.Connection:
    """The same atlas, with the mini-atlas fixture loaded into it."""
    load_fixture(conn, FIXTURE_DIR)
    return conn


# ---------------------------------------------------------------------------------------------
# Loading and row counts
# ---------------------------------------------------------------------------------------------


def test_fixture_loads_into_a_fresh_database(conn: sqlite3.Connection) -> None:
    counts = load_fixture(conn, FIXTURE_DIR)
    assert counts == EXPECTED_COUNTS
    for table, expected in EXPECTED_COUNTS.items():
        actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        assert actual == expected, f"{table}: expected {expected} rows, found {actual}"


def test_missing_fixture_directory_raises(conn: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(FixtureError):
        load_fixture(conn, tmp_path / "does-not-exist")


def test_a_table_with_no_fixture_file_loads_as_zero_rows(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    empty_dir = tmp_path / "empty_atlas"
    empty_dir.mkdir()
    counts = load_fixture(conn, empty_dir)
    assert counts == dict.fromkeys(EXPECTED_COUNTS, 0)


# ---------------------------------------------------------------------------------------------
# One complete pathway_configuration: parts, compartments, a measurement
# ---------------------------------------------------------------------------------------------


def test_complete_pathway_configuration_has_parts_compartments_and_a_measurement(
    loaded: sqlite3.Connection,
) -> None:
    config = loaded.execute(
        "SELECT host_strain_id, compartment_strategy_id FROM pathway_configuration "
        "WHERE id = 'YAA:PWCFG:fx-native-split'"
    ).fetchone()
    assert config is not None
    assert config["compartment_strategy_id"] == "A_native_split"

    steps = loaded.execute(
        "SELECT step_order, compartment_id, part_id FROM pathway_route_step "
        "JOIN pathway_route ON pathway_route.id = pathway_route_step.route_id "
        "WHERE pathway_route.pathway_configuration_id = 'YAA:PWCFG:fx-native-split' "
        "ORDER BY step_order"
    ).fetchall()
    assert [row["compartment_id"] for row in steps] == [
        "mitochondrial_matrix",
        "mitochondrial_matrix",
        "mitochondrial_matrix",
        "cytosol",
        "cytosol",
    ]
    assert all(row["part_id"] is not None for row in steps)

    measurement = loaded.execute(
        "SELECT value_as_reported, unit_as_reported FROM measurement "
        "WHERE strain_id = ? AND quantity_kind = 'titer' AND source_locator = 'table 1'",
        (config["host_strain_id"],),
    ).fetchone()
    assert measurement is not None
    assert measurement["value_as_reported"] == pytest.approx(1.8)
    assert measurement["unit_as_reported"] == "g/L"


# ---------------------------------------------------------------------------------------------
# Modifications: mtdna_edit and localization_change('none_reported')
# ---------------------------------------------------------------------------------------------


def test_mtdna_edit_modification_is_stored_with_its_subtype_fields(
    loaded: sqlite3.Connection,
) -> None:
    row = loaded.execute(
        "SELECT m.type, e.technique, e.recoded_for_table_3, i.displaced_gene "
        "FROM modification m "
        "JOIN modification_mtdna_edit e ON e.modification_id = m.id "
        "JOIN mtdna_insertion i ON i.modification_id = m.id "
        "WHERE m.id = 'YAA:MOD:fx-mtdna'"
    ).fetchone()
    assert row is not None
    assert row["type"] == "mtdna_edit"
    assert row["recoded_for_table_3"] == 1
    assert row["displaced_gene"] == "COX2"


def test_localization_change_verification_method_is_none_reported(
    loaded: sqlite3.Connection,
) -> None:
    row = loaded.execute(
        "SELECT verification_method, import_efficiency_reported "
        "FROM modification_localization_change WHERE modification_id = 'YAA:MOD:fx-loc'"
    ).fetchone()
    assert row is not None
    assert row["verification_method"] == "none_reported"
    # Never measured, because nothing verified the relocalization in the first place.
    assert row["import_efficiency_reported"] is None


# ---------------------------------------------------------------------------------------------
# Conflicting measurements
# ---------------------------------------------------------------------------------------------


def test_conflicting_measurements_are_retrievable_as_a_conflict(loaded: sqlite3.Connection) -> None:
    conflict = loaded.execute(
        "SELECT kind, status FROM conflict WHERE id = 'YAA:CONF:fx-1'"
    ).fetchone()
    assert conflict is not None
    assert conflict["kind"] == "magnitude"
    assert conflict["status"] == "open"

    members = loaded.execute(
        "SELECT a.effect_size, ev.measurement_id FROM conflict_member cm "
        "JOIN assertion a ON a.id = cm.assertion_id "
        "JOIN evidence_item ev ON ev.assertion_id = a.id "
        "WHERE cm.conflict_id = 'YAA:CONF:fx-1' ORDER BY a.effect_size"
    ).fetchall()
    assert [row["effect_size"] for row in members] == [1.8, 3.4]
    # Two distinct measurements back the two sides of the conflict, not the same one twice.
    assert members[0]["measurement_id"] != members[1]["measurement_id"]


# ---------------------------------------------------------------------------------------------
# The derived evidence level
# ---------------------------------------------------------------------------------------------


def test_level_view_gives_l1_for_the_direct_perturbation_assertion(
    loaded: sqlite3.Connection,
) -> None:
    row = loaded.execute(
        "SELECT level FROM assertion_level WHERE assertion_id = 'YAA:ASSERT:fx-l1'"
    ).fetchone()
    assert row is not None
    assert row["level"] == "L1"


def test_level_view_gives_l5_for_the_ai_inference_only_assertion_in_zone_i(
    loaded: sqlite3.Connection,
) -> None:
    level_row = loaded.execute(
        "SELECT level FROM assertion_level WHERE assertion_id = 'YAA:ASSERT:fx-l5'"
    ).fetchone()
    assert level_row is not None
    assert level_row["level"] == "L5"

    zone = loaded.execute("SELECT zone FROM assertion WHERE id = 'YAA:ASSERT:fx-l5'").fetchone()[
        "zone"
    ]
    assert zone == "I"


# ---------------------------------------------------------------------------------------------
# The compartment-safety gate against stored data
# ---------------------------------------------------------------------------------------------


def test_unrecoded_cun_sequence_is_rejected_for_an_mtdna_encoded_gene(
    loaded: sqlite3.Connection,
) -> None:
    seq = loaded.execute("SELECT sequence FROM part WHERE id = 'YAA:PART:fx-adh'").fetchone()[
        "sequence"
    ]
    assert seq is not None

    # The gate fires for a gene carried on mtDNA, where translation really is under table 3.
    report = check_compartment_safety(seq, "mitochondrial_matrix", encoding_genome="mitochondrial")
    assert report.accepted is False
    assert report.cun_codons, "expected the CUN run to be what trips the gate"

    # The same sequence is fine in the compartment it is actually filed against.
    native_report = check_compartment_safety(seq, "cytosol")
    assert native_report.accepted is True

    # And the compartment alone cannot be asked: the matrix is served by both genomes.
    with pytest.raises(AmbiguousCompartmentError):
        check_compartment_safety(seq, "mitochondrial_matrix")


# ---------------------------------------------------------------------------------------------
# The encoding-genome contrast: the same enzyme, the same compartment, two different answers
# ---------------------------------------------------------------------------------------------


def _part(conn: sqlite3.Connection, part_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT sequence, sequence_compartment_id, sequence_encoding_genome FROM part WHERE id = ?",
        (part_id,),
    ).fetchone()
    assert row is not None, f"fixture is missing {part_id}"
    return row


def test_a_nuclear_encoded_matrix_construct_needs_no_recoding(
    loaded: sqlite3.Connection,
) -> None:
    """The bug D1 fixed, as a fixture row.

    Ilv2/Ilv5/Ilv3 are nuclear-encoded, translated on cytosolic ribosomes under table 1 and then
    imported. A presequence-targeted construct bound for the matrix therefore keeps its CUN
    codons and must NOT be recoded -- the old compartment-keyed model would have told a bench
    scientist to recode it, producing a different protein.
    """
    row = _part(loaded, "YAA:PART:fx-kdc-matrix-nuclear")
    assert row["sequence_compartment_id"] == "mitochondrial_matrix"
    assert row["sequence_encoding_genome"] == "nuclear"

    report = check_compartment_safety(
        row["sequence"], "mitochondrial_matrix", encoding_genome="nuclear"
    )
    assert report.accepted is True
    assert report.table_id == 1
    # The CUN run is still there, and is still correct, because table 1 reads it as leucine.
    assert diff_tables(row["sequence"]), "the contrast needs a table-dependent sequence"
    assert translate(row["sequence"], TABLE_1) == "MLLLLEF*"


def test_the_same_enzyme_encoded_on_mtdna_is_recoded_instead(
    loaded: sqlite3.Connection,
) -> None:
    """The other half of the contrast: same enzyme, same compartment, other genome.

    Carried on mtDNA the gene is read by the mitoribosome under table 3, so the unrecoded ORF is
    rejected and the stored sequence is the recoded one -- which encodes the identical protein.
    """
    nuclear = _part(loaded, "YAA:PART:fx-kdc-matrix-nuclear")
    mtdna = _part(loaded, "YAA:PART:fx-kdc-mtdna")
    assert mtdna["sequence_compartment_id"] == "mitochondrial_matrix"
    assert mtdna["sequence_encoding_genome"] == "mitochondrial"
    assert mtdna["sequence"] != nuclear["sequence"]

    # Unrecoded, filed as mtDNA-encoded: rejected.
    assert (
        check_compartment_safety(
            nuclear["sequence"], "mitochondrial_matrix", encoding_genome="mitochondrial"
        ).accepted
        is False
    )
    # Recoded: accepted, under table 3, and the same protein as the nuclear version.
    report = check_compartment_safety(
        mtdna["sequence"], "mitochondrial_matrix", encoding_genome="mitochondrial"
    )
    assert report.accepted is True
    assert report.table_id == 3
    assert translate(mtdna["sequence"], TABLE_3) == translate(nuclear["sequence"], TABLE_1)


def test_the_native_split_route_recodes_nothing(loaded: sqlite3.Connection) -> None:
    """Three matrix steps, all nuclear-encoded: strategy A needs no recoding anywhere."""
    steps = loaded.execute(
        "SELECT compartment_id, encoding_genome FROM pathway_route_step "
        "WHERE route_id = 'YAA:ROUTE:fx-native-split-1' ORDER BY step_order"
    ).fetchall()
    assert [row["encoding_genome"] for row in steps] == ["nuclear"] * 5
    matrix_steps = [row for row in steps if row["compartment_id"] == "mitochondrial_matrix"]
    assert len(matrix_steps) == 3
    assert all(row["encoding_genome"] == "nuclear" for row in matrix_steps)


def test_the_localization_change_is_nuclear_and_the_mtdna_edit_is_not(
    loaded: sqlite3.Connection,
) -> None:
    """The same contrast at the modification layer, where a curator meets it."""
    loc = loaded.execute(
        "SELECT target_compartment_id, encoding_genome FROM modification_localization_change "
        "WHERE modification_id = 'YAA:MOD:fx-loc'"
    ).fetchone()
    assert loc["target_compartment_id"] == "mitochondrial_matrix"
    assert loc["encoding_genome"] == "nuclear"

    edit = loaded.execute(
        "SELECT recoded_for_table_3 FROM modification_mtdna_edit "
        "WHERE modification_id = 'YAA:MOD:fx-mtdna'"
    ).fetchone()
    assert edit["recoded_for_table_3"] == 1


def test_the_fixture_cannot_file_a_sequence_against_an_impossible_pair(
    loaded: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        loaded.execute(
            "INSERT INTO part (id, step_role_id, sequence, sequence_compartment_id, "
            "sequence_encoding_genome, zone, evidence, confidence) "
            "VALUES ('YAA:PART:fx-impossible', 'ADH', 'ATGTAA', 'cytosol', 'mitochondrial', "
            "'R', 'test', 'low')"
        )


# ---------------------------------------------------------------------------------------------
# Three-state numerics and as_reported shadows, as fixture rows
# ---------------------------------------------------------------------------------------------


def test_theoretical_yields_are_per_substrate_and_carry_their_states(
    loaded: sqlite3.Connection,
) -> None:
    rows = {
        row["substrate"]: row
        for row in loaded.execute(
            "SELECT substrate, g_per_g, g_per_g_state, mol_per_mol_state "
            "FROM product_theoretical_yield WHERE product_id = 'YAA:PROD:fx-isobutanol'"
        )
    }
    assert set(rows) == {"glucose", "xylose", "glycerol"}

    # Recorded: a number, and a state saying it is one.
    assert rows["glucose"]["g_per_g"] == pytest.approx(0.411)
    assert rows["glucose"]["g_per_g_state"] == "recorded"
    # Recorded-but-unresolved: the row the old CHECK (> 0) could not hold.
    assert rows["xylose"]["g_per_g"] is None
    assert rows["xylose"]["g_per_g_state"] == "unknown"
    # Not applicable, and (for g_per_g) never recorded at all -- four states, all distinct.
    assert rows["glycerol"]["mol_per_mol_state"] == "not_applicable"
    assert rows["glycerol"]["g_per_g_state"] is None


def test_condition_context_numeric_states_are_four_distinct_things(
    loaded: sqlite3.Connection,
) -> None:
    row = loaded.execute(
        "SELECT temperature_c, temperature_c_state, ph, ph_state, vvm, vvm_state, "
        "dilution_rate, dilution_rate_state FROM condition_context WHERE id = 'YAA:CTX:fx-1'"
    ).fetchone()
    assert (row["temperature_c"], row["temperature_c_state"]) == (30.0, "recorded")
    assert (row["ph"], row["ph_state"]) == (None, "unknown")  # mentioned, never stated
    assert (row["vvm"], row["vvm_state"]) == (None, "not_applicable")  # a flask has no sparging
    assert (row["dilution_rate"], row["dilution_rate_state"]) == (None, None)  # never recorded


def test_every_parsed_facet_keeps_the_string_the_paper_used(loaded: sqlite3.Connection) -> None:
    row = loaded.execute(
        "SELECT temperature_c, temperature_c_as_reported, mode, mode_as_reported, "
        "total_sugar_g_l, total_sugar_g_l_as_reported FROM condition_context "
        "WHERE id = 'YAA:CTX:fx-1'"
    ).fetchone()
    # The parsed value is Zone H and rebuildable; the verbatim string beside it is Zone R.
    assert row["temperature_c_as_reported"] == "30 C"
    assert row["total_sugar_g_l"] == pytest.approx(20.0)
    assert row["total_sugar_g_l_as_reported"] == "2% (w/v) glucose"
    # 'unknown' is what the parser resolved the prose to; the prose itself is still there.
    assert row["mode"] == "unknown"
    assert row["mode_as_reported"] == "cultures were fermented"


def test_long_tail_facets_carry_their_own_zone_and_state(loaded: sqlite3.Connection) -> None:
    rows = {
        row["facet"]: row
        for row in loaded.execute(
            "SELECT facet, value, value_state, as_reported, zone, confidence "
            "FROM condition_context_facet WHERE context_id = 'YAA:CTX:fx-1'"
        )
    }
    assert set(rows) == {"shaking_rpm", "inoculum_od600", "antifoam"}
    # A parsed facet is Zone H even though the context it hangs off is Zone R.
    assert rows["shaking_rpm"]["zone"] == "H"
    assert rows["shaking_rpm"]["value"] == "200"
    assert rows["inoculum_od600"]["value"] is None
    assert rows["inoculum_od600"]["value_state"] == "unknown"
    assert rows["antifoam"]["value_state"] == "not_applicable"
    # ... and every one of them still records the source's own words.
    assert all(row["as_reported"] for row in rows.values())


def test_a_recalled_identifier_is_unverified_rather_than_low(loaded: sqlite3.Connection) -> None:
    """'unverified' (asserted, never checked) is not 'low' (checked, weak).

    The hand-written gene_group anchor ids were recalled from background knowledge and never
    looked up, which is precisely the state the four-value vocabulary exists to name. Without it
    these rows would have to claim they had been checked.

    Scoped to Zone R. The two Zone H groups added beside them carry 'high', and that is not an
    exception to this rule but the other half of it: they were not asserted by anyone, they are
    the stated output of `omics.genes.gene_group_rows` over the `gene` rows in the same fixture,
    and the producing code's own argument for 'high' is that a verbatim locus_tag has nothing
    left to verify. `zone` is what separates the two claims, so the query says so.
    """
    confidences = {
        row["confidence"]
        for row in loaded.execute("SELECT confidence FROM gene_group WHERE zone = 'R'")
    }
    assert confidences == {"unverified"}
    evidence = loaded.execute(
        "SELECT evidence FROM gene_group WHERE id = 'YAA:GG:fx-ahas'"
    ).fetchone()["evidence"]
    assert "recalled from background knowledge" in evidence


# ---------------------------------------------------------------------------------------------
# The loader refuses identifiers the schema does not have
# ---------------------------------------------------------------------------------------------


def test_a_column_the_schema_does_not_have_is_named_not_spliced(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Table and column names cannot be bound, so they are whitelisted before interpolation."""
    bad = tmp_path / "bad_atlas"
    bad.mkdir()
    (bad / "organism.yaml").write_text(
        "- id: YAA:ORG:x\n"
        "  name: x\n"
        "  zone: R\n"
        "  evidence: test\n"
        "  confidence: low\n"
        '  "name) VALUES (1); DROP TABLE organism; --": x\n',
        encoding="utf-8",
    )
    with pytest.raises(FixtureError) as excinfo:
        load_fixture(conn, bad)
    assert "no such column" in str(excinfo.value)
    # Nothing was written, and the table the injected text named is still there.
    assert conn.execute("SELECT COUNT(*) FROM organism").fetchone()[0] == 0


# ---------------------------------------------------------------------------------------------
# NULL vs 'NA' vs 'unknown'
# ---------------------------------------------------------------------------------------------


def test_null_na_and_unknown_are_distinct_and_never_coerced(loaded: sqlite3.Connection) -> None:
    row = loaded.execute(
        "SELECT aeration_class, feedstock_class, mode FROM condition_context "
        "WHERE id = 'YAA:CTX:fx-1'"
    ).fetchone()
    assert row is not None
    assert row["aeration_class"] is None  # never recorded
    assert row["feedstock_class"] == "NA"  # recorded as not applicable
    assert row["mode"] == "unknown"  # recorded, but unresolved

    values = [row["aeration_class"], row["feedstock_class"], row["mode"]]
    assert len(set(values)) == 3  # pairwise distinct
    assert "NA" not in (row["aeration_class"], row["mode"])
    assert None not in (row["feedstock_class"], row["mode"])
