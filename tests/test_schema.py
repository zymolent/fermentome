"""Tests for the core relational schema.

The interesting tests here are the ones that assert something is *impossible*: a mislabelled
evidence row, an edited Zone R value, a stored evidence level. Those constraints are the reason
the schema exists, and a constraint with no test is a comment.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb.db import (
    IN_MEMORY,
    SCHEMA_VERSION,
    DatabaseError,
    SchemaVersionError,
    open_db,
)
from fermdb.genetic_code import (
    COMPARTMENT_ENCODING_GENOMES,
    ENCODING_GENOME_TABLE,
    AmbiguousCompartmentError,
    table_for_compartment,
)

# ---------------------------------------------------------------------------------------------
# Fixtures and minimal seed rows
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory atlas."""
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


def _seed(conn: sqlite3.Connection) -> None:
    """The smallest set of rows that lets an assertion and its evidence be inserted."""
    conn.execute(
        "INSERT INTO organism (id, ncbi_taxid, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:scer', 4932, 'Saccharomyces cerevisiae', 'R', 'test fixture', 'low')"
    )
    for sid, name in (("YAA:STRAIN:test", "TEST-1"), ("YAA:STRAIN:ctrl", "TEST-CTRL")):
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:scer', ?, 'laboratory', 'R', 'test fixture', 'low')",
            (sid, name),
        )
    conn.execute(
        "INSERT INTO product (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:PROD:isobutanol', 'isobutanol', 'R', 'test fixture', 'low')"
    )
    conn.execute(
        "INSERT INTO publication (id, year, zone, evidence, confidence) "
        "VALUES ('doi:10.0000/test', 2020, 'R', 'test fixture', 'low')"
    )
    conn.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported, "
        "unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:MEAS:1', 'YAA:STRAIN:test', 'titer', 'YAA:PROD:isobutanol', 1.5, 'g/L', "
        "'table 2, row 3', 'R', 'test fixture', 'low')"
    )
    conn.commit()


def _insert_assertion(conn: sqlite3.Connection, assertion_id: str) -> None:
    conn.execute(
        "INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, object_id, "
        "product_id, direction, created_by_kind, created_by, zone, evidence, confidence) "
        "VALUES (?, 'gene_group', 'YAA:GG:ilv5', 'affects_production_of', 'product', "
        "'YAA:PROD:isobutanol', 'YAA:PROD:isobutanol', 'increases', 'curator', 'test', 'R', "
        "'test fixture', 'low')",
        (assertion_id,),
    )


def _level(conn: sqlite3.Connection, assertion_id: str) -> str | None:
    row = conn.execute(
        "SELECT level FROM assertion_level WHERE assertion_id = ?", (assertion_id,)
    ).fetchone()
    assert row is not None, f"no assertion_level row for {assertion_id}"
    level: str | None = row["level"]
    return level


# ---------------------------------------------------------------------------------------------
# Connection and versioning
# ---------------------------------------------------------------------------------------------


def test_schema_creates_cleanly(conn: sqlite3.Connection) -> None:
    names = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    # A spot-check across every section of the DDL, not an exhaustive list: the list would only
    # ever be updated to match the file it is meant to check.
    expected = {
        "meta",
        "predicate",
        "organism",
        "strain",
        "strain_alias",
        "strain_lineage",
        "genotype",
        "gene",
        "gene_group",
        "compartment",
        "encoding_genome",
        "compartment_encoding_genome",
        "product",
        "product_theoretical_yield",
        "publication",
        "extraction",
        "span",
        "condition_context",
        "condition_context_facet",
        "experiment",
        "sample",
        "dataset",
        "processing_run",
        "raw_object",
        "measurement",
        "modification",
        "modification_localization_change",
        "modification_mtdna_edit",
        "mtdna_insertion",
        "part",
        "part_expression_record",
        "pathway",
        "pathway_configuration",
        "pathway_route",
        "reaction",
        "metabolite",
        "assertion",
        "evidence_item",
        "conflict",
        "curation_event",
        "knowledge_gap",
        "bottleneck",
    }
    assert expected <= names

    views = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
    }
    assert "assertion_level" in views

    # assertion.level must not exist as a stored column: it is derived or it is a lie.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assertion)")}
    assert "level" not in columns
    assert "level_override" in columns

    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_foreign_keys_are_on(conn: sqlite3.Connection) -> None:
    # Per-connection and off by default in SQLite, so open_db must set it every time.
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_keys_are_actually_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
            "VALUES ('YAA:STRAIN:x', 'YAA:ORG:nonexistent', 'X', 'R', 'test', 'low')"
        )


def test_file_database_is_created_and_stamped(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "atlas.sqlite"
    with open_db(target) as db:
        row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        assert int(row[0]) == SCHEMA_VERSION
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert target.exists()


def test_open_db_refuses_a_newer_schema_version(tmp_path: Path) -> None:
    target = tmp_path / "atlas.sqlite"
    db = open_db(target)
    db.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION + 1),))
    db.commit()
    db.close()

    with pytest.raises(SchemaVersionError) as excinfo:
        open_db(target)
    assert str(SCHEMA_VERSION + 1) in str(excinfo.value)


def test_open_db_refuses_an_older_schema_version(tmp_path: Path) -> None:
    # Refused too: an implicit migration is an unreviewed data change in either direction.
    target = tmp_path / "atlas.sqlite"
    db = open_db(target)
    db.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    db.commit()
    db.close()

    with pytest.raises(SchemaVersionError):
        open_db(target)


def test_open_db_without_create_requires_an_existing_database(tmp_path: Path) -> None:
    with pytest.raises(DatabaseError):
        open_db(tmp_path / "absent.sqlite", create=False)


# ---------------------------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------------------------


def test_zone_must_be_one_of_the_three(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO organism (id, name, zone, evidence, confidence) "
            "VALUES ('YAA:ORG:bad', 'x', 'X', 'test', 'low')"
        )


def test_reported_measurement_value_cannot_be_edited(conn: sqlite3.Connection) -> None:
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE measurement SET value_as_reported = 2.0 WHERE id = 'YAA:MEAS:1'")
    # The derived value is written beside it instead.
    conn.execute(
        "UPDATE measurement SET value_si = 1.5, unit_si = 'g/L', "
        "derived_by = 'identity (already SI)' WHERE id = 'YAA:MEAS:1'"
    )
    assert (
        conn.execute(
            "SELECT value_as_reported FROM measurement WHERE id = 'YAA:MEAS:1'"
        ).fetchone()[0]
        == 1.5
    )


def test_yield_requires_a_basis(conn: sqlite3.Connection) -> None:
    _seed(conn)
    # g/g-consumed and g/g-supplied are different numbers; a blank basis is not an answer.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO measurement (id, strain_id, quantity_kind, value_as_reported, "
            "unit_as_reported, source_locator, zone, evidence, confidence) "
            "VALUES ('YAA:MEAS:y', 'YAA:STRAIN:test', 'yield', 0.2, 'g/g', 'table 1', 'R', "
            "'test', 'low')"
        )
    # 'unknown' is a recorded state and is allowed; it just is not comparable across studies.
    conn.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, basis, value_as_reported, "
        "unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:MEAS:y', 'YAA:STRAIN:test', 'yield', 'unknown', 0.2, 'g/g', 'table 1', "
        "'R', 'test', 'low')"
    )


def test_a_declared_fraction_must_lie_in_the_unit_interval(conn: sqlite3.Connection) -> None:
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO measurement (id, strain_id, quantity_kind, is_fraction, "
            "value_as_reported, unit_as_reported, source_locator, zone, evidence, confidence) "
            "VALUES ('YAA:MEAS:f', 'YAA:STRAIN:test', 'viability', 1, 85.0, 'percent', "
            "'table 1', 'R', 'test', 'low')"
        )


# ---------------------------------------------------------------------------------------------
# Compartments
# ---------------------------------------------------------------------------------------------


def test_encoding_genome_rows_agree_with_genetic_code_module(conn: sqlite3.Connection) -> None:
    """The DDL seed and `genetic_code.ENCODING_GENOME_TABLE` are independent sources on purpose.

    genetic_code.py is the authority; this test is what stops the two drifting. A sequence filed
    against the wrong code table mistranslates the whole CUN block without looking wrong.
    """
    rows = {
        row["id"]: row["genetic_code_table"]
        for row in conn.execute("SELECT id, genetic_code_table FROM encoding_genome")
    }
    assert rows == ENCODING_GENOME_TABLE


def test_compartment_encoding_genome_rows_agree_with_genetic_code_module(
    conn: sqlite3.Connection,
) -> None:
    """The seeded pairs must match `COMPARTMENT_ENCODING_GENOMES` exactly, pair for pair.

    This is the D1 agreement check. It is asserted as a set of pairs rather than by iterating the
    module's dict, so an extra row in the DDL fails just as loudly as a missing one -- a
    compartment the schema thinks mtDNA can encode, and the code module does not, is the exact
    drift that would send a construct to the wrong table.
    """
    rows = {
        (row["compartment_id"], row["encoding_genome"])
        for row in conn.execute(
            "SELECT compartment_id, encoding_genome FROM compartment_encoding_genome"
        )
    }
    expected = {
        (compartment, genome)
        for compartment, genomes in COMPARTMENT_ENCODING_GENOMES.items()
        for genome in genomes
    }
    assert rows == expected

    # Every compartment the module knows has a row, and nothing else does.
    compartments = {row["id"] for row in conn.execute("SELECT id FROM compartment")}
    assert compartments == set(COMPARTMENT_ENCODING_GENOMES)
    assert "mitochondrial_inner_membrane" in compartments


def test_the_code_table_is_reachable_only_through_the_encoding_genome(
    conn: sqlite3.Connection,
) -> None:
    """`compartment` must carry no genetic code column: the genome decides, not the destination.

    A `compartment.genetic_code_table` would answer "what code does the mitochondrial matrix
    use?", which is a malformed question with a dangerous-looking answer.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(compartment)")}
    assert "genetic_code_table" not in columns
    assert "genome" not in columns

    # The join that replaces it, for a compartment served by both genomes.
    rows = {
        row["encoding_genome"]: row["genetic_code_table"]
        for row in conn.execute(
            "SELECT ceg.encoding_genome, eg.genetic_code_table "
            "FROM compartment_encoding_genome ceg "
            "JOIN encoding_genome eg ON eg.id = ceg.encoding_genome "
            "WHERE ceg.compartment_id = 'mitochondrial_matrix'"
        )
    }
    assert rows == {"nuclear": 1, "mitochondrial": 3}
    # ... and the module refuses to answer without the genome, for the same reason.
    with pytest.raises(AmbiguousCompartmentError):
        table_for_compartment("mitochondrial_matrix")
    assert table_for_compartment("mitochondrial_matrix", "nuclear").table_id == 1


def test_encoding_genome_rejects_an_unknown_code_table(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO encoding_genome (id, genetic_code_table, table_name, ribosome, zone, "
            "evidence, confidence) VALUES ('plastid', 11, 'Bacterial', 'plastid', 'R', 'test', "
            "'low')"
        )


def test_a_sequence_cannot_claim_an_impossible_compartment_genome_pair(
    conn: sqlite3.Connection,
) -> None:
    """There is no mitochondrially-encoded cytosolic protein, and the composite FK says so."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO part (id, step_role_id, sequence, sequence_compartment_id, "
            "sequence_encoding_genome, zone, evidence, confidence) "
            "VALUES ('YAA:PART:bad', 'ADH', 'ATGTAA', 'cytosol', 'mitochondrial', 'R', 'test', "
            "'low')"
        )
    # The same sequence in a compartment mtDNA does serve is storable.
    conn.execute(
        "INSERT INTO part (id, step_role_id, sequence, sequence_compartment_id, "
        "sequence_encoding_genome, zone, evidence, confidence) "
        "VALUES ('YAA:PART:ok', 'ADH', 'ATGTAA', 'mitochondrial_matrix', 'mitochondrial', 'R', "
        "'test', 'low')"
    )


def test_a_stored_sequence_must_declare_both_compartment_and_genome(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO part (id, step_role_id, sequence, sequence_compartment_id, zone, "
            "evidence, confidence) "
            "VALUES ('YAA:PART:nogenome', 'ADH', 'ATGTAA', 'cytosol', 'R', 'test', 'low')"
        )


# ---------------------------------------------------------------------------------------------
# The confidence vocabulary
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["unverified", "low", "medium", "high"])
def test_every_confidence_value_in_the_closed_set_is_storable(
    conn: sqlite3.Connection, value: str
) -> None:
    """'unverified' is asserted-but-never-checked, and is NOT a synonym for 'low' (checked, weak).

    It is the honest label for a value recalled from memory, which CONVENTIONS.md forbids storing
    as 'high' -- without it, such a value has to masquerade as something that was looked at.
    """
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES (?, 'x', 'R', 'test', ?)",
        (f"YAA:ORG:{value}", value),
    )


def test_a_confidence_outside_the_closed_set_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO organism (id, name, zone, evidence, confidence) "
            "VALUES ('YAA:ORG:bad', 'x', 'R', 'test', 'probably')"
        )


# ---------------------------------------------------------------------------------------------
# Modifications: the two types stay apart
# ---------------------------------------------------------------------------------------------


def _insert_modification(conn: sqlite3.Connection, mod_id: str, mod_type: str) -> None:
    conn.execute(
        "INSERT INTO modification (id, strain_id, type, zone, evidence, confidence) "
        "VALUES (?, 'YAA:STRAIN:test', ?, 'R', 'test fixture', 'low')",
        (mod_id, mod_type),
    )


def test_localization_change_verification_defaults_to_none_reported(
    conn: sqlite3.Connection,
) -> None:
    _seed(conn)
    _insert_modification(conn, "YAA:MOD:loc", "localization_change")
    conn.execute(
        "INSERT INTO modification_localization_change (modification_id, target_compartment_id) "
        "VALUES ('YAA:MOD:loc', 'mitochondrial_matrix')"
    )
    row = conn.execute(
        "SELECT verification_method FROM modification_localization_change "
        "WHERE modification_id = 'YAA:MOD:loc'"
    ).fetchone()
    # A blank would read as "fine"; 'none_reported' reads as what it is.
    assert row["verification_method"] == "none_reported"


def test_mtdna_fields_cannot_be_attached_to_a_localization_change(
    conn: sqlite3.Connection,
) -> None:
    _seed(conn)
    _insert_modification(conn, "YAA:MOD:loc", "localization_change")
    # The composite FK (modification_id, type) is what keeps the two types from merging.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO modification_mtdna_edit (modification_id, technique) "
            "VALUES ('YAA:MOD:loc', 'biolistic_transformation')"
        )


def test_mtdna_edit_carries_its_own_fields(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_modification(conn, "YAA:MOD:mt", "mtdna_edit")
    conn.execute(
        "INSERT INTO modification_mtdna_edit (modification_id, technique, recipient_state, "
        "recoded_for_table_3, feasibility_rating, available_here) "
        "VALUES ('YAA:MOD:mt', 'biolistic_transformation', 'rho0', 1, 'frontier', 1)"
    )
    conn.execute(
        "INSERT INTO mtdna_insertion (id, modification_id, locus, utr_source, "
        "activator_required, displaced_gene, respiration_retained, rescue_strategy, zone, "
        "evidence, confidence) "
        "VALUES ('YAA:MTINS:1', 'YAA:MOD:mt', 'COX2', 'COX2', 'Pet111', 'COX2', 0, "
        "'nuclear_allotopic_copy', 'R', 'test fixture', 'low')"
    )
    row = conn.execute(
        "SELECT displaced_gene, respiration_retained FROM mtdna_insertion"
    ).fetchone()
    # Inserting costs you the gene whose UTR you borrowed; the schema records the trade.
    assert row["displaced_gene"] == "COX2"
    assert row["respiration_retained"] == 0


# ---------------------------------------------------------------------------------------------
# Evidence: per-type constraints
# ---------------------------------------------------------------------------------------------


def test_ai_inference_cannot_carry_a_measurement_id(conn: sqlite3.Connection) -> None:
    """The constraint this schema most exists for.

    An AI inference that could cite a measurement would be indistinguishable, downstream, from a
    measured result. The INSERT must fail, not be cleaned up later.
    """
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:ai")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence_item (id, assertion_id, evidence_type, model, model_version, "
            "prompt_version, review_state, measurement_id, zone, evidence, confidence) "
            "VALUES ('YAA:EV:bad', 'YAA:ASSERT:ai', 'ai_inference', 'some-model', 'v1', 'p1', "
            "'pending', 'YAA:MEAS:1', 'I', 'test', 'low')"
        )
    # Without the measurement_id the same row is storable.
    conn.execute(
        "INSERT INTO evidence_item (id, assertion_id, evidence_type, model, model_version, "
        "prompt_version, review_state, zone, evidence, confidence) "
        "VALUES ('YAA:EV:ok', 'YAA:ASSERT:ai', 'ai_inference', 'some-model', 'v1', 'p1', "
        "'pending', 'I', 'test', 'low')"
    )


def test_ai_inference_must_be_zone_i(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:ai")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence_item (id, assertion_id, evidence_type, model, model_version, "
            "prompt_version, review_state, zone, evidence, confidence) "
            "VALUES ('YAA:EV:z', 'YAA:ASSERT:ai', 'ai_inference', 'm', 'v1', 'p1', 'pending', "
            "'R', 'test', 'low')"
        )


def test_direct_perturbation_requires_a_control(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:dp")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence_item (id, assertion_id, evidence_type, strain_id, "
            "measurement_id, direction, zone, evidence, confidence) "
            "VALUES ('YAA:EV:nc', 'YAA:ASSERT:dp', 'direct_perturbation', 'YAA:STRAIN:test', "
            "'YAA:MEAS:1', 'increases', 'R', 'test', 'low')"
        )


def test_literature_assertion_cannot_cite_a_measurement(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:lit")
    conn.execute(
        "INSERT INTO span (id, publication_id, section, zone) "
        "VALUES ('YAA:SPAN:1', 'doi:10.0000/test', 'introduction', 'R')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence_item (id, assertion_id, evidence_type, publication_id, "
            "span_id, measurement_id, zone, evidence, confidence) "
            "VALUES ('YAA:EV:l', 'YAA:ASSERT:lit', 'literature_assertion', 'doi:10.0000/test', "
            "'YAA:SPAN:1', 'YAA:MEAS:1', 'R', 'test', 'low')"
        )


# ---------------------------------------------------------------------------------------------
# The derived level view
# ---------------------------------------------------------------------------------------------


def _add_direct_perturbation(
    conn: sqlite3.Connection, ev_id: str, assertion_id: str, group: str
) -> None:
    conn.execute(
        "INSERT INTO evidence_item (id, assertion_id, evidence_type, strain_id, "
        "control_strain_id, measurement_id, direction, independent_group, publication_id, "
        "zone, evidence, confidence) "
        "VALUES (?, ?, 'direct_perturbation', 'YAA:STRAIN:test', 'YAA:STRAIN:ctrl', "
        "'YAA:MEAS:1', 'increases', ?, 'doi:10.0000/test', 'R', 'test', 'low')",
        (ev_id, assertion_id, group),
    )


def test_level_is_l1_for_a_single_direct_perturbation(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:1")
    _add_direct_perturbation(conn, "YAA:EV:1", "YAA:ASSERT:1", "lab-a")
    assert _level(conn, "YAA:ASSERT:1") == "L1"


def test_level_is_l5_for_an_ai_inference(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:2")
    conn.execute(
        "INSERT INTO evidence_item (id, assertion_id, evidence_type, model, model_version, "
        "prompt_version, review_state, zone, evidence, confidence) "
        "VALUES ('YAA:EV:2', 'YAA:ASSERT:2', 'ai_inference', 'some-model', 'v1', 'p1', "
        "'pending', 'I', 'test', 'low')"
    )
    assert _level(conn, "YAA:ASSERT:2") == "L5"


def test_level_rises_to_l2_with_a_second_independent_group(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:3")
    _add_direct_perturbation(conn, "YAA:EV:3a", "YAA:ASSERT:3", "lab-a")
    assert _level(conn, "YAA:ASSERT:3") == "L1"
    _add_direct_perturbation(conn, "YAA:EV:3b", "YAA:ASSERT:3", "lab-b")
    # Recomputed on read, which is the entire reason the level is a view.
    assert _level(conn, "YAA:ASSERT:3") == "L2"


def test_level_is_null_with_no_evidence(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:4")
    assert _level(conn, "YAA:ASSERT:4") is None


def test_an_open_direction_conflict_withholds_the_level(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:5")
    _add_direct_perturbation(conn, "YAA:EV:5", "YAA:ASSERT:5", "lab-a")
    assert _level(conn, "YAA:ASSERT:5") == "L1"
    conn.execute(
        "INSERT INTO conflict (id, kind, status, zone) VALUES ('YAA:CONF:1', 'direction', "
        "'open', 'H')"
    )
    conn.execute(
        "INSERT INTO conflict_member (conflict_id, assertion_id) "
        "VALUES ('YAA:CONF:1', 'YAA:ASSERT:5')"
    )
    # L1 requires no unresolved discordance, so the honest answer is no level at all.
    assert _level(conn, "YAA:ASSERT:5") is None


def test_a_curator_override_is_applied_on_top_and_marked(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:6")
    _add_direct_perturbation(conn, "YAA:EV:6", "YAA:ASSERT:6", "lab-a")
    conn.execute(
        "UPDATE assertion SET level_override = 'L3', override_reason = 'control was not isogenic',"
        " override_curator = 'test curator' WHERE id = 'YAA:ASSERT:6'"
    )
    row = conn.execute(
        "SELECT level, derived_level, is_overridden FROM assertion_level "
        "WHERE assertion_id = 'YAA:ASSERT:6'"
    ).fetchone()
    assert row["level"] == "L3"
    assert row["derived_level"] == "L1"
    assert row["is_overridden"] == 1


def test_an_override_without_a_reason_is_rejected(conn: sqlite3.Connection) -> None:
    _seed(conn)
    _insert_assertion(conn, "YAA:ASSERT:7")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE assertion SET level_override = 'L1' WHERE id = 'YAA:ASSERT:7'")


# ---------------------------------------------------------------------------------------------
# Three-state numerics, and yields keyed on (product, substrate)
# ---------------------------------------------------------------------------------------------


def _insert_yield(conn: sqlite3.Connection, substrate: str, **columns: object) -> None:
    keys = ["product_id", "substrate", "zone", "evidence", "confidence", *columns]
    values: dict[str, object] = {
        "product_id": "YAA:PROD:isobutanol",
        "substrate": substrate,
        "zone": "R",
        "evidence": "test",
        "confidence": "unverified",
        **columns,
    }
    conn.execute(
        f"INSERT INTO product_theoretical_yield ({', '.join(keys)}) "  # noqa: S608
        f"VALUES ({', '.join(':' + k for k in keys)})",
        values,
    )


def test_a_theoretical_yield_is_per_product_and_substrate(conn: sqlite3.Connection) -> None:
    """0.411 g/g is a statement about glucose, and the key says so.

    Two substrates for one product must coexist; a schema that allowed only one is a schema in
    which glucose is an unnamed assumption baked into a column name.
    """
    _seed(conn)
    _insert_yield(conn, "glucose", g_per_g=0.411, g_per_g_state="recorded")
    _insert_yield(conn, "xylose", g_per_g=0.30, g_per_g_state="recorded")
    rows = {
        row["substrate"]: row["g_per_g"]
        for row in conn.execute(
            "SELECT substrate, g_per_g FROM product_theoretical_yield "
            "WHERE product_id = 'YAA:PROD:isobutanol'"
        )
    }
    assert rows == {"glucose": 0.411, "xylose": 0.30}
    # (product_id, substrate) is the key: the same pair twice is a duplicate.
    with pytest.raises(sqlite3.IntegrityError):
        _insert_yield(conn, "glucose", g_per_g=0.5, g_per_g_state="recorded")


def test_an_unresolved_theoretical_yield_is_storable_as_unknown(
    conn: sqlite3.Connection,
) -> None:
    """The state the old CHECK (g_per_g > 0) made unstorable.

    "A theoretical yield exists and nobody resolved it" must be a row, because an absent row is
    indistinguishable from an unfinished import -- and the QC bound must not quietly fall back to
    the glucose number.
    """
    _seed(conn)
    _insert_yield(conn, "xylose", g_per_g_state="unknown")
    row = conn.execute(
        "SELECT g_per_g, g_per_g_state FROM product_theoretical_yield WHERE substrate = 'xylose'"
    ).fetchone()
    assert row["g_per_g"] is None
    assert row["g_per_g_state"] == "unknown"

    # ... and "never recorded at all" is a fourth, different row: both columns NULL.
    _insert_yield(conn, "glycerol")
    never = conn.execute(
        "SELECT g_per_g, g_per_g_state FROM product_theoretical_yield WHERE substrate = 'glycerol'"
    ).fetchone()
    assert never["g_per_g"] is None
    assert never["g_per_g_state"] is None


def test_a_numeric_and_its_state_cannot_contradict_each_other(conn: sqlite3.Connection) -> None:
    _seed(conn)
    # A number filed as unresolved.
    with pytest.raises(sqlite3.IntegrityError):
        _insert_yield(conn, "glucose", g_per_g=0.411, g_per_g_state="unknown")
    # A state claiming a recorded value, with nothing recorded.
    with pytest.raises(sqlite3.IntegrityError):
        _insert_yield(conn, "glucose", g_per_g_state="recorded")
    # A state outside the closed set.
    with pytest.raises(sqlite3.IntegrityError):
        _insert_yield(conn, "glucose", g_per_g=0.411, g_per_g_state="probably")


def _insert_context(conn: sqlite3.Connection, context_id: str, **columns: object) -> None:
    keys = ["id", "context_hash", "zone", "evidence", "confidence", *columns]
    values: dict[str, object] = {
        "id": context_id,
        "context_hash": f"hash-{context_id}",
        "zone": "R",
        "evidence": "test",
        "confidence": "low",
        **columns,
    }
    conn.execute(
        f"INSERT INTO condition_context ({', '.join(keys)}) "  # noqa: S608
        f"VALUES ({', '.join(':' + k for k in keys)})",
        values,
    )


def test_condition_context_numerics_carry_their_three_states(conn: sqlite3.Connection) -> None:
    """Not-stated, not-applicable and never-recorded stay three different facts."""
    _insert_context(
        conn,
        "YAA:CTX:states",
        temperature_c=30.0,
        temperature_c_state="recorded",
        ph_state="unknown",  # the paper mentions pH but never gives it
        vvm_state="not_applicable",  # a shake flask has no sparging
        # dilution_rate and its state both omitted -> never recorded at all
    )
    row = conn.execute(
        "SELECT temperature_c, temperature_c_state, ph, ph_state, vvm, vvm_state, "
        "dilution_rate, dilution_rate_state FROM condition_context "
        "WHERE id = 'YAA:CTX:states'"
    ).fetchone()
    assert (row["temperature_c"], row["temperature_c_state"]) == (30.0, "recorded")
    assert (row["ph"], row["ph_state"]) == (None, "unknown")
    assert (row["vvm"], row["vvm_state"]) == (None, "not_applicable")
    assert (row["dilution_rate"], row["dilution_rate_state"]) == (None, None)
    # The four states are genuinely distinguishable, which is the whole point.
    assert len({row["temperature_c_state"], row["ph_state"], row["vvm_state"], None}) == 4


def test_a_condition_context_numeric_contradicting_its_state_is_rejected(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_context(conn, "YAA:CTX:bad1", ph=5.5, ph_state="unknown")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_context(conn, "YAA:CTX:bad2", temperature_c_state="recorded")


def test_parsed_from_prose_facets_have_an_as_reported_shadow(conn: sqlite3.Connection) -> None:
    """Every facet parsed out of prose has somewhere to put the string the paper actually used.

    The review found first-class facet columns with no such home; the parsed value is Zone H and
    rebuildable, the verbatim string is Zone R and is not.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(condition_context)")}
    for facet in (
        "temperature_c",
        "ph",
        "ph_controlled",
        "aeration_class",
        "vvm",
        "dissolved_oxygen_pct",
        "mode",
        "medium_name",
        "medium_class",
        "carbon_source_main",
        "total_sugar_g_l",
        "feedstock_class",
    ):
        assert f"{facet}_as_reported" in columns, f"{facet} has no as_reported shadow"

    _insert_context(
        conn,
        "YAA:CTX:verbatim",
        temperature_c=30.0,
        temperature_c_state="recorded",
        temperature_c_as_reported="30 +/- 1 C",
    )
    row = conn.execute(
        "SELECT temperature_c, temperature_c_as_reported FROM condition_context "
        "WHERE id = 'YAA:CTX:verbatim'"
    ).fetchone()
    assert row["temperature_c"] == 30.0
    assert row["temperature_c_as_reported"] == "30 +/- 1 C"


def test_condition_context_facet_carries_its_own_zone(conn: sqlite3.Connection) -> None:
    """A facet row holds a fact, so it declares its own zone rather than inheriting one.

    A parser's reading (H) and a curator's (R) can hang off the same context, and a consumer that
    cannot tell them apart cannot honour the "Zone I may not support a conclusion" rule.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(condition_context_facet)")}
    assert {"zone", "evidence", "confidence", "as_reported", "value_state"} <= columns

    _insert_context(conn, "YAA:CTX:facets")
    conn.execute(
        "INSERT INTO condition_context_facet (context_id, facet, value, value_state, "
        "as_reported, unit, zone, evidence, confidence) "
        "VALUES ('YAA:CTX:facets', 'shaking_rpm', '200', 'recorded', 'shaken at 200 rpm', "
        "'rpm', 'H', 'test', 'low')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO condition_context_facet (context_id, facet, value, value_state, zone, "
            "evidence, confidence) "
            "VALUES ('YAA:CTX:facets', 'antifoam', 'none', 'recorded', 'X', 'test', 'low')"
        )


# ---------------------------------------------------------------------------------------------
# The evidence level is a view, structurally
# ---------------------------------------------------------------------------------------------


def test_assertion_level_is_a_view_and_never_a_column(conn: sqlite3.Connection) -> None:
    """Until now only a source comment protected this rule.

    A stored level is a lie the moment a new paper lands, so the shape is checked against
    sqlite_master and PRAGMA table_info rather than trusted to survive the next edit: the level
    must exist as a VIEW named assertion_level, must not exist as a table of that name, and must
    not be a column on `assertion` under any of the obvious names.
    """
    objects = {
        row["name"]: row["type"]
        for row in conn.execute(
            "SELECT name, type FROM sqlite_master WHERE name = 'assertion_level'"
        )
    }
    assert objects == {"assertion_level": "view"}

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assertion)")}
    for forbidden in ("level", "evidence_level", "derived_level"):
        assert forbidden not in columns, f"assertion.{forbidden} must be derived, not stored"
    # The override is a stored column, and is a different thing: it is displayed as an override.
    assert "level_override" in columns

    # The view really does serve the column the table must not have.
    view_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assertion_level)")}
    assert {"level", "derived_level", "is_overridden"} <= view_columns
