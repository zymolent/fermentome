"""Tests for `fermdb.db.migrations`.

The failure mode a migration test has to catch is drift: `schema.sql` and the migration are two
descriptions of the same thing, and nothing makes them agree except a test. A database created
fresh and a database migrated into place must be the same database, or the schema has two
definitions and whichever one you did not read is the one that is wrong.

So the central test builds the *old* tables from the v5 DDL, migrates them, and compares the
result against what `schema.sql` produces today -- column for column, and by behaviour for the
constraints, which `PRAGMA table_info` does not report.

Column *order* is deliberately not compared. `ALTER TABLE ADD COLUMN` appends, while `schema.sql`
puts `competing` in the middle of `reaction`, so the orders will never match and cannot be made
to. Nothing in this codebase reads a column positionally; comparing as a set is the real
invariant, and pretending otherwise would mean a permanently failing test or a contorted schema.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, SCHEMA_VERSION, create_schema, open_db, schema_version
from fermdb.db import migrations as M

# The tables the migrations touch, as v5 declared them, verbatim. Kept here rather than derived
# from the current schema, because a test that builds "the old shape" out of the new one cannot
# detect the drift it exists to detect.
#
# `measurement` and `bottleneck` joined the list at v12, which is the first migration to add a
# column to a table that was already full of rows. `publication`, `curation_task`,
# `curation_event`, `processing_run`, `dataset` and `analysis_result` joined for a different
# reason: v12's backfill READS those three, so a
# v5 database without them cannot be migrated at all. They are reduced to the columns that
# backfill touches and are deliberately never shape-compared -- see the note above them below, so
# nobody later mistakes a stub for a record of what v5 declared.
V5_TABLES = """
CREATE TABLE gene (id TEXT PRIMARY KEY, standard_name TEXT, gene_group_id TEXT);
CREATE TABLE gene_group (id TEXT PRIMARY KEY);
CREATE TABLE metabolite (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    inchikey   TEXT,
    chebi_id   TEXT,
    formula    TEXT,
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);
CREATE TABLE reaction (
    id             TEXT PRIMARY KEY,
    name           TEXT,
    ec_number      TEXT,
    rhea_id        TEXT,
    equation       TEXT,
    compartment_id TEXT,
    reversible     INTEGER CHECK (reversible IN (0, 1)),
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);
CREATE TABLE product (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    inchikey       TEXT,
    chebi_id       TEXT,
    formula        TEXT,
    carbon_number  INTEGER,
    canonical_unit TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);
CREATE TABLE compartment_strategy (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    definition TEXT,
    source     TEXT NOT NULL
);
INSERT INTO compartment_strategy (id, label, source) VALUES
    ('A_native_split', 'Native split: Ilv in matrix, Ehrlich in cytosol',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('B_cytosolic_relocalization', 'Ilv enzymes relocalized to the cytosol',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('C_mitochondrial_ehrlich', 'Ehrlich pathway targeted to the matrix',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('D_alternative_compartment', 'Peroxisomal or other-organelle assembly',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('E_mtdna_encoded', 'Recoded Ehrlich enzymes encoded in mtDNA',
     'docs/design/MITOCHONDRIAL_PROGRAM.md section 4');
CREATE TABLE measurement (
    id                TEXT PRIMARY KEY,
    sample_id         TEXT,
    strain_id         TEXT,
    experiment_id     TEXT,
    quantity_kind     TEXT NOT NULL,
    product_id        TEXT,
    value_as_reported REAL NOT NULL,
    unit_as_reported  TEXT NOT NULL,
    value_si          REAL,
    unit_si           TEXT,
    basis             TEXT CHECK (basis IN ('consumed', 'supplied', 'theoretical_max_pct',
                                            'per_biomass', 'per_volume', 'NA', 'unknown')),
    is_fraction       INTEGER NOT NULL DEFAULT 0 CHECK (is_fraction IN (0, 1)),
    assay_method      TEXT,
    assay_details     TEXT,
    detection_limit   REAL,
    is_below_lod      INTEGER NOT NULL DEFAULT 0 CHECK (is_below_lod IN (0, 1)),
    is_upper_bound    INTEGER NOT NULL DEFAULT 0 CHECK (is_upper_bound IN (0, 1)),
    uncertainty_sd    REAL CHECK (uncertainty_sd IS NULL OR uncertainty_sd >= 0),
    uncertainty_sem   REAL CHECK (uncertainty_sem IS NULL OR uncertainty_sem >= 0),
    ci_low            REAL,
    ci_high           REAL,
    n_replicates      INTEGER CHECK (n_replicates IS NULL OR n_replicates >= 1),
    replicate_type    TEXT CHECK (replicate_type IN ('biological', 'technical', 'unknown')),
    derived_by        TEXT,
    is_digitized      INTEGER NOT NULL DEFAULT 0 CHECK (is_digitized IN (0, 1)),
    source_locator    TEXT NOT NULL,
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (sample_id IS NOT NULL OR strain_id IS NOT NULL OR experiment_id IS NOT NULL),
    CHECK (quantity_kind <> 'yield' OR basis IS NOT NULL)
);
CREATE INDEX measurement_by_strain ON measurement(strain_id);
CREATE INDEX measurement_by_sample ON measurement(sample_id);
CREATE INDEX measurement_by_product ON measurement(product_id, quantity_kind);
CREATE TABLE bottleneck (
    id                TEXT PRIMARY KEY,
    assertion_id      TEXT,
    reaction_id       TEXT,
    transport_step    TEXT,
    node              TEXT,
    route_context_id  TEXT,
    observation_type  TEXT NOT NULL
                      CHECK (observation_type IN ('metabolite_accumulation', 'flux_measurement',
                                                  'overexpression_relieved', 'deletion_worsened',
                                                  'in_vitro_kinetics', 'inferred')),
    recurrence        INTEGER CHECK (recurrence IS NULL OR recurrence >= 0),
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (reaction_id IS NOT NULL OR transport_step IS NOT NULL OR node IS NOT NULL)
);
-- The next three are NOT a record of what v5 declared and are never shape-compared. They are cut
-- down to exactly what v12's backfill reads, because that backfill joins through them and a
-- database missing them cannot be migrated. Their real definitions live in schema.sql.
CREATE TABLE publication (id TEXT PRIMARY KEY);
CREATE TABLE curation_task (
    id             TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL REFERENCES publication(id),
    record_kind    TEXT NOT NULL,
    proposal_hash  TEXT NOT NULL
);
CREATE TABLE curation_event (
    id          TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL
);
-- Likewise stubs, and likewise never shape-compared: v16 adds `analysis_result.dataset_id`, so
-- both tables must exist for the migration to run at all. Reduced to the columns v16 touches.
CREATE TABLE processing_run (id TEXT PRIMARY KEY);
CREATE TABLE dataset (id TEXT PRIMARY KEY);
CREATE TABLE analysis_result (
    id                TEXT PRIMARY KEY,
    processing_run_id TEXT NOT NULL REFERENCES processing_run(id),
    kind              TEXT NOT NULL,
    payload_ref       TEXT NOT NULL,
    zone              TEXT NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta VALUES ('schema_version', '5');
"""


def _v5() -> sqlite3.Connection:
    conn = sqlite3.connect(IN_MEMORY)
    conn.row_factory = sqlite3.Row
    conn.executescript(V5_TABLES)
    return conn


def _shape(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, int, int]]:
    """``{(name, type, notnull, pk)}`` -- the part of a table's shape that is order-independent."""
    return {
        (str(r["name"]), str(r["type"]).upper(), int(r["notnull"]), int(r["pk"]))
        for r in conn.execute(f"PRAGMA table_info({table})")
    }


@pytest.fixture()
def fresh() -> sqlite3.Connection:
    conn = open_db(IN_MEMORY)
    yield conn
    conn.close()


# --------------------------------------------------------------------- the drift-catching test


@pytest.mark.parametrize(
    "table", ["reaction", "metabolite", "product", "measurement", "bottleneck"]
)
def test_migrated_tables_match_freshly_created_ones(fresh: sqlite3.Connection, table: str) -> None:
    """The invariant the whole module rests on: two routes, one schema."""
    old = _v5()
    try:
        M.migrate(old)
        assert _shape(old, table) == _shape(fresh, table)
    finally:
        old.close()


def test_the_new_table_matches_too(fresh: sqlite3.Connection) -> None:
    old = _v5()
    try:
        M.migrate(old)
        assert _shape(old, "reaction_gene") == _shape(fresh, "reaction_gene")
        migrated_indexes = {
            str(r["name"])
            for r in old.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='reaction_gene'"
            )
        }
        fresh_indexes = {
            str(r["name"])
            for r in fresh.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='reaction_gene'"
            )
        }
        assert migrated_indexes == fresh_indexes
    finally:
        old.close()


def test_the_new_indexes_match_too(fresh: sqlite3.Connection) -> None:
    """v12 adds an index as well as a column, and an index is as easy to forget to mirror."""
    old = _v5()
    try:
        M.migrate(old)
        for table in ("measurement", "bottleneck"):
            query = "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?"
            migrated = {str(r["name"]) for r in old.execute(query, (table,))}
            created = {str(r["name"]) for r in fresh.execute(query, (table,))}
            assert migrated == created, table
            assert f"{table}_by_publication" in created
    finally:
        old.close()


# ------------------------------------------------- v12's backfill: from the task, not the prose


def _promoted(conn: sqlite3.Connection) -> None:
    """One promoted measurement and one promoted bottleneck, as the promoter actually leaves them.

    The publication appears **twice and differently**: as `curation_task.publication_id`, which is
    a column, and inside the `evidence` sentence, which is prose. The two are deliberately given
    different values here. Anything that recovers the prose one is parsing a string, and the tests
    below say which value came back.
    """
    conn.executescript(
        """
        INSERT INTO publication (id) VALUES ('doi:10.1/from-the-task');
        INSERT INTO publication (id) VALUES ('doi:10.1/from-the-prose');
        INSERT INTO curation_task (id, publication_id, record_kind, proposal_hash) VALUES
            ('YAA:CTASK:m', 'doi:10.1/from-the-task', 'measurements',
             'aaaaaaaaaaaaaaaabbbbbbbb'),
            ('YAA:CTASK:b', 'doi:10.1/from-the-task', 'bottlenecks',
             'ccccccccccccccccdddddddd');
        INSERT INTO curation_event (id, action, target_type, target_id) VALUES
            ('YAA:CUEV:m', 'promote', 'measurement', 'YAA:MEAS:aaaaaaaaaaaaaaaa'),
            ('YAA:CUEV:b', 'promote', 'bottleneck', 'YAA:BNK:cccccccccccccccc');
        INSERT INTO measurement (id, strain_id, quantity_kind, value_as_reported,
                                 unit_as_reported, source_locator, zone, evidence, confidence)
            VALUES ('YAA:MEAS:aaaaaaaaaaaaaaaa', 'YAA:STRAIN:x', 'titer', 1.62, 'g/L', 'text',
                    'R',
                    'promoted from curation task YAA:CTASK:m on doi:10.1/from-the-prose (m[0])',
                    'medium');
        INSERT INTO bottleneck (id, node, observation_type, zone, evidence, confidence)
            VALUES ('YAA:BNK:cccccccccccccccc', 'pyruvate node', 'inferred', 'R',
                    'promoted from curation task YAA:CTASK:b on doi:10.1/from-the-prose (b[0])',
                    'medium');
        """
    )


@pytest.mark.parametrize(
    ("table", "row_id"),
    [("measurement", "YAA:MEAS:aaaaaaaaaaaaaaaa"), ("bottleneck", "YAA:BNK:cccccccccccccccc")],
)
def test_the_backfill_takes_the_publication_from_the_task_not_the_evidence(
    table: str, row_id: str
) -> None:
    """The point of v12, stated as the one thing that could have been done wrong.

    The evidence sentence names `doi:10.1/from-the-prose` and the curation task names
    `doi:10.1/from-the-task`. A backfill that regexed the DOI out of `evidence` would pass every
    other test in this module and fail this one -- which is the whole reason the two differ.
    """
    old = _v5()
    try:
        _promoted(old)
        M.migrate(old)
        row = old.execute(
            f"SELECT publication_id, evidence FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        assert row["publication_id"] == "doi:10.1/from-the-task"
        # And the prose it did not read is still there, unedited. A backfill may add; it may not
        # rewrite what was already recorded.
        assert "doi:10.1/from-the-prose" in row["evidence"]
    finally:
        old.close()


def test_a_row_with_no_curation_task_is_left_null_rather_than_guessed() -> None:
    """A measurement from a deposited dataset has no paper, and must stay storable and honest.

    NULL here means "there is no publication", which is a fact. The alternative -- reaching for
    the nearest plausible paper, or for whatever a sentence happens to contain -- would be
    indistinguishable afterwards from a publication someone checked.
    """
    old = _v5()
    try:
        _promoted(old)
        old.execute(
            "INSERT INTO measurement (id, strain_id, quantity_kind, value_as_reported, "
            "unit_as_reported, source_locator, zone, evidence, confidence) "
            "VALUES ('YAA:MEAS:dataset', 'YAA:STRAIN:x', 'titer', 4.2, 'g/L', 'table 1', 'R', "
            "'from the deposited dataset, not from a paper', 'medium')"
        )
        M.migrate(old)
        row = old.execute(
            "SELECT publication_id FROM measurement WHERE id = 'YAA:MEAS:dataset'"
        ).fetchone()
        assert row["publication_id"] is None
        # The one that could be linked still was; an unlinkable row does not suppress the rest.
        linked = old.execute(
            "SELECT COUNT(*) FROM measurement WHERE publication_id IS NOT NULL"
        ).fetchone()
        assert linked[0] == 1
    finally:
        old.close()


def test_an_ambiguous_hash_prefix_is_left_null_rather_than_picked() -> None:
    """Two tasks from two papers sharing a 16-character prefix must not resolve to either.

    The id derivation truncates `proposal_hash`, so a collision is possible in principle. The
    `HAVING COUNT(DISTINCT ...) = 1` is what makes "never guessed" a property rather than a hope,
    and this is the test that holds it there.
    """
    old = _v5()
    try:
        _promoted(old)
        old.executescript(
            """
            INSERT INTO publication (id) VALUES ('doi:10.1/other-paper');
            INSERT INTO curation_task (id, publication_id, record_kind, proposal_hash) VALUES
                ('YAA:CTASK:m2', 'doi:10.1/other-paper', 'measurements',
                 'aaaaaaaaaaaaaaaaeeeeeeee');
            """
        )
        M.migrate(old)
        row = old.execute(
            "SELECT publication_id FROM measurement WHERE id = 'YAA:MEAS:aaaaaaaaaaaaaaaa'"
        ).fetchone()
        assert row["publication_id"] is None
    finally:
        old.close()


def test_a_row_that_was_never_promoted_is_not_linked() -> None:
    """The `curation_event` leg is a real condition, not decoration.

    A row written by hand or by a loader is not a promotion, and must not acquire a paper from a
    task that merely hashes the same way.
    """
    old = _v5()
    try:
        _promoted(old)
        old.execute("DELETE FROM curation_event WHERE target_type = 'measurement'")
        M.migrate(old)
        row = old.execute(
            "SELECT publication_id FROM measurement WHERE id = 'YAA:MEAS:aaaaaaaaaaaaaaaa'"
        ).fetchone()
        assert row["publication_id"] is None
    finally:
        old.close()


def test_the_seeded_vocabulary_matches_too(fresh: sqlite3.Connection) -> None:
    """Drift is not only a column problem.

    `compartment_strategy` is seeded by `schema.sql` rather than loaded from a TSV, so extending it
    means writing the same row twice -- once in the seed and once in a migration -- and nothing but
    this test makes the two agree. `PRAGMA table_info` cannot see a row, so the shape comparison
    above would pass a migration that added the strategy with a different id, a different label or
    no definition, and the two databases would then disagree about what a stored
    `compartment_strategy_id` is allowed to be.

    Compared in full rather than by id: the label and the definition are the vocabulary, not
    decoration, and a migration that inserted the right id with the wrong meaning would be the
    harder bug to find.
    """
    old = _v5()
    try:
        M.migrate(old)
        query = "SELECT id, label, definition, source FROM compartment_strategy ORDER BY id"
        migrated = [tuple(r) for r in old.execute(query)]
        created = [tuple(r) for r in fresh.execute(query)]
        assert migrated == created
        assert "F_single_compartment_host" in {row[0] for row in created}
    finally:
        old.close()


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        # competing is 0/1 or NULL, never 7.
        (
            "INSERT INTO reaction (id, competing, zone, evidence, confidence) "
            "VALUES ('r', 7, 'R', 'e', 'high')",
            (),
        ),
        # A redox half with no pool cannot be matched to its partner.
        (
            "INSERT INTO metabolite (id, name, carrier, redox, zone, evidence, confidence) "
            "VALUES ('m', 'n', 1, 'reduced', 'R', 'e', 'high')",
            (),
        ),
        # Only carriers carry redox state.
        (
            "INSERT INTO metabolite (id, name, carrier, redox, pair, zone, evidence, confidence) "
            "VALUES ('m', 'n', 0, 'reduced', 'nad', 'R', 'e', 'high')",
            (),
        ),
    ],
)
def test_constraints_survive_the_migration(statement: str, params: tuple[object, ...]) -> None:
    """CHECK constraints are invisible to PRAGMA table_info, so they are tested by behaviour.

    An ALTER that dropped a CHECK would pass a shape comparison and fail here.
    """
    old = _v5()
    try:
        M.migrate(old)
        with pytest.raises(sqlite3.IntegrityError):
            old.execute(statement, params)
    finally:
        old.close()


# --------------------------------------------------------------------- safety properties


def test_no_migration_destroys_anything() -> None:
    """The design rule of the module, enforced rather than documented.

    A migration that drops a column or deletes rows is not reviewable as a diff, because the thing
    it removed is no longer there to compare against.

    Matched on the statement's leading verb rather than on substrings. "ON DELETE CASCADE" is a
    referential action inside a CREATE TABLE and destroys nothing; an earlier version of this test
    failed on it, which is a false positive that would have trained someone to ignore the test.
    """
    allowed_verbs = {"ALTER", "CREATE", "INSERT", "UPDATE"}
    for migration in M.MIGRATIONS:
        for statement in migration.statements:
            normalised = " ".join(statement.upper().split())
            verb = normalised.split(" ", 1)[0]
            assert verb in allowed_verbs, (
                f"{migration.label} starts a statement with {verb}: {statement[:60]}"
            )
            # ALTER may add; it may not drop or rename away.
            assert " DROP " not in normalised, (
                f"{migration.label} drops something: {statement[:60]}"
            )


def test_existing_rows_survive_and_gain_nulls_not_defaults() -> None:
    """A pre-existing reaction must not come out claiming it does not compete.

    `ALTER TABLE ADD COLUMN` with no DEFAULT gives NULL, which is "never assessed" -- the honest
    value. A DEFAULT 0 would have quietly asserted a fact about every row already in the table.
    """
    old = _v5()
    try:
        old.execute(
            "INSERT INTO reaction (id, name, zone, evidence, confidence) "
            "VALUES ('r1', 'old reaction', 'R', 'from v5', 'high')"
        )
        M.migrate(old)
        row = old.execute("SELECT name, competing, evidence FROM reaction WHERE id='r1'").fetchone()
        assert row["name"] == "old reaction"
        assert row["evidence"] == "from v5"
        assert row["competing"] is None
    finally:
        old.close()


def test_the_version_is_stamped() -> None:
    old = _v5()
    try:
        assert schema_version(old) == 5
        ran = M.migrate(old)
        # Asserted as a chain reaching the current version rather than a fixed list, so adding a
        # migration does not break this test -- only a broken chain should.
        assert ran[0].from_version == 5
        assert ran[-1].to_version == SCHEMA_VERSION
        assert [m.to_version for m in ran] == [m.from_version for m in ran[1:]] + [SCHEMA_VERSION]
        assert schema_version(old) == SCHEMA_VERSION
    finally:
        old.close()


def test_migrating_an_up_to_date_database_does_nothing(fresh: sqlite3.Connection) -> None:
    assert M.pending(fresh) == ()
    assert M.migrate(fresh) == ()


def test_a_newer_database_is_refused_rather_than_downgraded(fresh: sqlite3.Connection) -> None:
    """Downgrading would mean dropping whatever the newer version added."""
    fresh.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (SCHEMA_VERSION + 1,))
    with pytest.raises(M.MigrationError, match="ahead of"):
        M.pending(fresh)


def test_a_broken_chain_is_refused() -> None:
    """A version with no migration out of it must not be silently skipped over."""
    orphan = sqlite3.connect(IN_MEMORY)
    orphan.row_factory = sqlite3.Row
    orphan.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO meta VALUES ('schema_version', '2');"
    )
    try:
        with pytest.raises(M.MigrationError, match="no migration from v2"):
            M.pending(orphan)
    finally:
        orphan.close()


def test_an_empty_database_is_created_not_migrated() -> None:
    empty = sqlite3.connect(IN_MEMORY)
    try:
        with pytest.raises(M.MigrationError, match="create it rather than migrating"):
            M.pending(empty)
    finally:
        empty.close()


def test_a_failing_migration_leaves_the_version_alone() -> None:
    """Half a migration is worse than none: the stamp would no longer describe the file."""
    old = _v5()
    broken = M.Migration(
        from_version=5,
        to_version=6,
        summary="deliberately invalid",
        statements=("ALTER TABLE reaction ADD COLUMN competing INTEGER", "SELECT nonexistent()"),
    )
    try:
        with pytest.raises(sqlite3.OperationalError):
            M.migrate(old, steps=[broken])
        assert schema_version(old) == 5
        assert "competing" not in {n for n, _, _, _ in _shape(old, "reaction")}
    finally:
        old.close()


def test_backups_are_timestamped_not_overwritten(tmp_path: Path) -> None:
    """The backup you want is the one from before the migration that broke things, not the last."""
    database = tmp_path / "fermdb.sqlite3"
    first = M.backup_path(database, now=datetime(2026, 9, 20, 10, 0, tzinfo=UTC))
    second = M.backup_path(database, now=datetime(2026, 9, 20, 11, 0, tzinfo=UTC))
    assert first != second
    assert first.name.startswith("fermdb.sqlite3.pre-v")


def test_a_backup_takes_the_wal_with_it(tmp_path: Path) -> None:
    """A WAL-mode backup without its log can be missing the newest transactions.

    That is the kind of backup that is worse than none, because it looks like one.
    """
    database = tmp_path / "fermdb.sqlite3"
    conn = open_db(database)
    conn.execute("INSERT INTO meta (key, value) VALUES ('probe', 'x')")
    conn.commit()
    conn.close()
    (tmp_path / "fermdb.sqlite3-wal").write_bytes(b"fake wal")

    target = M.copy_backup(database)
    assert target.is_file()
    assert target.with_name(target.name + "-wal").read_bytes() == b"fake wal"


def test_a_missing_database_is_not_backed_up_silently(tmp_path: Path) -> None:
    with pytest.raises(M.MigrationError, match="no database at"):
        M.copy_backup(tmp_path / "absent.sqlite3")


def test_open_db_still_refuses_to_migrate_implicitly(tmp_path: Path) -> None:
    """The reason this module exists is that open_db does not do this. It must keep not doing it."""
    database = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(database)
    conn.executescript(V5_TABLES)
    conn.commit()
    conn.close()

    from fermdb.db import SchemaVersionError

    with pytest.raises(SchemaVersionError, match="does not migrate"):
        open_db(database)


def test_create_schema_stamps_the_current_version(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "new.sqlite3")
    try:
        create_schema(conn)
        assert schema_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()
