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

# The three tables as v5 declared them, verbatim. Kept here rather than derived from the current
# schema, because a test that builds "the old shape" out of the new one cannot detect the drift it
# exists to detect.
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


@pytest.mark.parametrize("table", ["reaction", "metabolite"])
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
