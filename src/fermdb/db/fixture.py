"""Loader for the phase-0 mini-atlas fixture.

The fixture itself lives at ``tests/fixtures/mini_atlas/`` as one YAML file per table, each
holding a plain list of row-mappings whose keys are column names. This module knows nothing about
what any table means; it only knows the order tables must be inserted in so that every foreign
key a row names already exists (`TABLE_ORDER`), and it inserts each row's mapping verbatim.

That "verbatim" property is the point (PLAN.md Q, "fixture loads"; docs/reference/CONVENTIONS.md
"Missing values"): a key a row's mapping omits is simply not part of the ``INSERT``, so the
column keeps whatever the schema itself does with an absent value (its default, or SQL ``NULL``);
a YAML ``null`` is bound as SQL ``NULL`` explicitly; and the literal strings ``'NA'`` and
``'unknown'`` pass straight through as the strings they are. None of the three is ever coerced
into either of the others, or into zero, by this loader.

Table and column names are the one thing this module does *not* take on trust: they cannot be
bound as SQL parameters, so before either is interpolated into a statement it is checked against
the live schema (``sqlite_master`` and ``pragma_table_info``), which is read with bound
parameters. A fixture file is curated and reviewed as a diff, but a loader that splices a YAML
key straight into SQL will eventually be pointed at a file nobody reviewed.

No path is hardcoded here: the caller supplies the fixture directory, per
docs/reference/CONVENTIONS.md ("Paths and configuration").
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

#: Insertion order. A table is loaded only after every table its rows can reference, so foreign
#: keys never point forward. Not every table in schema.sql appears here -- only the ones the
#: phase-0 fixture populates; a table with no matching file simply contributes zero rows.
TABLE_ORDER: tuple[str, ...] = (
    "organism",
    "strain",
    "product",
    "product_theoretical_yield",
    "publication",
    "gene_group",
    "part",
    "pathway",
    "pathway_configuration",
    "pathway_route",
    "pathway_route_step",
    "condition_context",
    "condition_context_facet",
    "measurement",
    "modification",
    "modification_localization_change",
    "modification_mtdna_edit",
    "mtdna_insertion",
    "assertion",
    "evidence_item",
    "conflict",
    "conflict_member",
    # Last, and deliberately. `curation_event` declares no foreign key at all -- `target_id` is
    # polymorphic, so it can name a row in any table above it -- which means "after everything it
    # can reference" is the end of the list rather than any particular slot. It is also the reason
    # it was missed: nothing in the schema forced it into this tuple, so PLAN.md J.5's third arm
    # (curator -> date -> rationale) had no file to load from and every fixture assertion resolved
    # to nobody. `fermdb query traceability` over the fixture is what found that.
    "curation_event",
)

__all__ = ["TABLE_ORDER", "FixtureError", "load_fixture"]


class FixtureError(RuntimeError):
    """The fixture directory is missing, or one of its files is not shaped as expected."""


def _load_rows(file_path: Path) -> list[dict[str, Any]]:
    """Parse one `<table>.yaml` file into a list of row-mappings."""
    with file_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if document is None:
        return []
    if not isinstance(document, list):
        raise FixtureError(f"{file_path}: expected a YAML list of rows at the top level")
    for row in document:
        if not isinstance(row, dict):
            raise FixtureError(f"{file_path}: every row must be a mapping, got {row!r}")
    return document


def _schema_tables(conn: sqlite3.Connection) -> frozenset[str]:
    """Every table name the connected database actually has."""
    return frozenset(
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    )


def _schema_columns(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    """Every column name `table` actually has, read from the database itself.

    `pragma_table_info` is the table-valued form of `PRAGMA table_info`, which takes the table
    name as a **bound parameter**. The plain pragma statement does not accept one.
    """
    return frozenset(
        str(row[0]) for row in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))
    )


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> int:
    """Insert each row's mapping into `table`, columns taken from the mapping's own keys.

    Table and column names cannot be bound as parameters, so they are interpolated into the
    statement -- and are therefore checked against the live schema first, and quoted after. A
    fixture file is a repo-tier curated file rather than user input, but a loader that splices
    an arbitrary YAML key straight into SQL is a loader that will do it to the wrong file one
    day; and the same check turns a typo'd column into a named error instead of an opaque
    `sqlite3.OperationalError` from somewhere inside the driver.
    """
    allowed = _schema_columns(conn, table)
    if not allowed:  # pragma: no cover - _insert_rows is only reached for a known table
        raise FixtureError(f"{table}: no such table in the connected database")

    for index, row in enumerate(rows):
        columns = list(row.keys())
        unknown = sorted(set(columns) - allowed)
        if unknown:
            raise FixtureError(
                f"{table} row {index}: no such column(s) {', '.join(unknown)}; "
                f"{table} has {', '.join(sorted(allowed))}"
            )
        # Quoted so that a column name that is also a SQL keyword ('mode', 'class', 'references')
        # is still addressable. The name is known-good by the check above.
        column_list = ", ".join(f'"{name}"' for name in columns)
        placeholders = ", ".join(f":{name}" for name in columns)
        conn.execute(
            f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})',  # noqa: S608
            row,
        )
    return len(rows)


def load_fixture(conn: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    """Load the mini-atlas fixture at `path` into `conn` and return the rows inserted per table.

    `conn` must already have the schema applied (as `fermdb.db.open_db` does). `path` is a
    directory of `<table>.yaml` files in the shape of `tests/fixtures/mini_atlas/`; a table in
    `TABLE_ORDER` with no matching file contributes 0 rows and is left untouched -- this loader
    only ever inserts, never truncates or deletes.

    Raises:
        FixtureError: `path` is not a directory, a fixture file is not a YAML list of mappings,
            or a row names a table or column the connected schema does not have.
        sqlite3.IntegrityError: a row violates the schema (a bad fixture fails loudly rather than
            silently -- this loader does not catch or paper over it).
    """
    root = Path(path)
    if not root.is_dir():
        raise FixtureError(f"no fixture directory at {root}")

    # Whitelist the table names against the live schema before any of them reaches a statement.
    # TABLE_ORDER is source, not data, but a name in it that the schema has dropped would
    # otherwise surface as a driver error halfway through a partial load.
    known = _schema_tables(conn)
    missing = [table for table in TABLE_ORDER if table not in known]
    if missing:
        raise FixtureError(
            "the connected database has no table(s) named " + ", ".join(missing) + "; "
            "TABLE_ORDER and schema.sql have drifted apart"
        )

    counts: dict[str, int] = {}
    for table in TABLE_ORDER:
        file_path = root / f"{table}.yaml"
        if not file_path.is_file():
            counts[table] = 0
            continue
        counts[table] = _insert_rows(conn, table, _load_rows(file_path))

    conn.commit()
    return counts
