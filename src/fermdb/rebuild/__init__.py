"""Zone H regeneration as a test — PLAN.md T.3, "rebuild as a test".

T.3 calls this "the strongest guarantee in the whole design": Zone H is regenerable by
definition (docs/reference/CONVENTIONS.md, "Data zones": *"Zone H must be reconstructible from
Zone R by running recorded code. If it cannot be, it is misfiled and belongs in R"*), so
regeneration is a test — drop Zone H, rebuild it, diff, and a non-empty diff is either
non-determinism or an undeclared input, both bugs.

WHAT WAS FOUND WHEN THIS WAS BUILT, 2026-09-24, AND WHY THE MODULE IS SHAPED THIS WAY
-------------------------------------------------------------------------------------
There is **no `harmonize` pipeline**. PLAN.md M.2 names one ("Zone R in, Zone H out, idempotent
on Zone R revision + recipe version"); `grep -rn harmoniz src/` finds four docstring mentions and
no callable. Zone H is produced piecemeal by five modules, and most of what they do is not a
Zone R -> Zone H derivation at all but an *ingest* that happens to emit a derived row alongside a
reported one. Measured against the live atlas on 2026-09-24:

| table             | Zone H rows | produced by                    | rebuildable from Zone R? |
|-------------------|-------------|--------------------------------|--------------------------|
| `screening_record`|       6,381 | `literature/discovery.py`      | the *rule* only — below  |
| `analysis_result` |          44 | `omics/contrasts.py`           | no: needs the matrices   |
| `assertion`       |          11 | `omics/evidence.py`            | no: needs the contrast   |
| `evidence_item`   |          11 | `omics/evidence.py`            | no: needs the contrast   |
| `gene_group`      |          36 | `omics/genes.py`               | **yes, entirely**        |

And the flagship Zone H column in the design — `measurement.value_si` / `unit_si`, the one D.2
uses to explain the zone at all — is written by nothing. `grep -rn value_si src/` reaches the
schema, two query-layer readers and zero writers. Unit harmonization is specified, not built.

So this harness is deliberately **not** a single `rebuild()` that claims to cover Zone H. It is a
registry of declared regenerators plus an inventory of everything they do not reach, and the
report prints both. Partial coverage that presents itself as the T.3 guarantee is worse than no
coverage, because T.3 is the one claim the rest of the design leans on.

WHY SNAPSHOT-AND-COMPARE RATHER THAN DROP-AND-REWRITE
-----------------------------------------------------
T.3 says "drop Zone H, rebuild, diff". This module reads the stored rows, rebuilds, and diffs
without writing anything. The two are equivalent as a test — a drop-and-rewrite would detect a
missing row, an extra row or a changed cell, and so does this — and the read-only version can be
pointed at a database opened `mode=ro`, which is what keeps an accidental run against the shared
atlas from being a data-loss event. `just rebuild-check` copies the database anyway; the
read-only construction is the second lock, not the only one.

THE TWO HONESTY MECHANISMS, WHICH ARE THE POINT OF THE DATACLASSES BELOW
------------------------------------------------------------------------
1. **A regenerator cannot see the columns it is being tested on.** :class:`Regenerator` declares
   `rebuilt` (the columns it computes, which the harness diffs) and `carried` (columns it is
   handed back verbatim because no Zone R source holds them). The harness projects the stored
   rows down to `key + carried` before handing them over, so a regenerator physically cannot
   read a `rebuilt` column and echo it. Without that, a "passing" rebuild can be Zone H diffed
   against itself, which is a test that cannot fail.
2. **`row_source` says whether the row *set* is a finding.** `"zone_r"` means the regenerator
   enumerates its rows from Zone R, so a row in the store that the rebuild does not produce is a
   real diff. `"store"` means the row set had to be taken from the store — the inputs that
   decided *which* rows exist were never persisted — so only cell values are checked, and the
   report says so per table rather than letting the row count imply coverage it does not have.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "CellDiff",
    "Declined",
    "Regenerated",
    "Regenerator",
    "RebuildReport",
    "RowDiff",
    "TableDiff",
    "Uncovered",
    "WHY_IT_MATTERS",
    "exit_code",
    "rebuild_table",
    "rebuild_zone_h",
    "uncovered_zone_h",
]

#: Printed above a non-empty diff. A reader who has just been told "3 cells differ" needs to know
#: what that means before they decide whether to care, and the answer is not obvious: a Zone H
#: diff is never "the data changed", it is always "the code and the data disagree about what the
#: code produces". Same role `query.traceability.WHY_IT_MATTERS` plays for a broken chain.
WHY_IT_MATTERS: Final[str] = (
    "Zone H is defined as reconstructible from Zone R by running recorded code "
    "(CONVENTIONS.md, 'Data zones'). A cell that does not reconstruct means one of three "
    "things, and all three are bugs: the producing code is non-deterministic; the producer "
    "reads an input nobody declared (a file, a clock, a network response); or the row was "
    "edited by hand after it was written, which makes it Zone R wearing an H."
)

#: The zone this module rebuilds. Named rather than spelled inline so a grep for the constant
#: finds every place the harness assumes 'H'.
ZONE_H: Final[str] = "H"


# ------------------------------------------------------------------------------- declarations


@dataclass(frozen=True)
class Declined:
    """One stored row a regenerator deliberately did not rebuild, and why.

    Distinct from "the rebuild lost a row", which is a finding. A curator who moved a
    `screening_record` from `needs_full_text` to `included` has taken that row out of the
    triage rule's hands on purpose (`discovery.py` stops refreshing it once `review_state` leaves
    `'proposed'`), so rebuilding it would report a diff that is the system working. It is still
    counted and printed: a rule that quietly declines most of its rows is not a test either.
    """

    key: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Regenerated:
    """What a regenerator returns: the rows it produced, and the rows it refused to produce."""

    rows: tuple[Mapping[str, Any], ...]
    declined: tuple[Declined, ...] = ()


#: A regenerator's signature. The second argument is the stored rows projected down to
#: `key + carried` — never the full row. See honesty mechanism 1 in the module docstring.
RegenerateFn = Callable[[sqlite3.Connection, tuple[Mapping[str, Any], ...]], Regenerated]


@dataclass(frozen=True)
class Regenerator:
    """One declared Zone R -> Zone H derivation, and an honest statement of its reach."""

    #: The table whose Zone H rows this rebuilds.
    table: str
    #: Columns that identify a row across the stored and rebuilt sets.
    key: tuple[str, ...]
    #: Columns this regenerator computes. These, and only these, are diffed.
    rebuilt: tuple[str, ...]
    #: Columns handed back to the regenerator verbatim from the stored row, because no Zone R
    #: source holds them. Every one of these is an undeclared input in T.3's sense and is printed
    #: as such.
    carried: tuple[str, ...]
    #: Whether the row *set* is derived (`zone_r`) or taken from the store (`store`).
    row_source: Literal["zone_r", "store"]
    #: The module whose recorded code this reproduces, for the reader of a diff.
    source: str
    #: The derivation itself.
    regenerate: RegenerateFn


# ------------------------------------------------------------------------------------ results


@dataclass(frozen=True)
class CellDiff:
    """One column that did not reconstruct."""

    column: str
    stored: Any
    rebuilt: Any

    def as_json(self) -> dict[str, Any]:
        return {"column": self.column, "stored": self.stored, "rebuilt": self.rebuilt}


@dataclass(frozen=True)
class RowDiff:
    """One row that did not reconstruct, named by its key."""

    key: tuple[str, ...]
    kind: Literal["changed", "only_in_store", "only_in_rebuild"]
    cells: tuple[CellDiff, ...] = ()

    @property
    def label(self) -> str:
        return " / ".join(self.key)

    def as_json(self) -> dict[str, Any]:
        return {
            "key": list(self.key),
            "kind": self.kind,
            "cells": [cell.as_json() for cell in self.cells],
        }


@dataclass(frozen=True)
class TableDiff:
    """The result of rebuilding one table's Zone H rows."""

    table: str
    source: str
    row_source: Literal["zone_r", "store"]
    stored_rows: int
    rebuilt_rows: int
    checked_columns: tuple[str, ...]
    carried_columns: tuple[str, ...]
    #: Columns of the table that this regenerator neither computes nor carries — they are simply
    #: not covered. Printed, because "the rebuild passed" must not be read as "the row is right".
    unchecked_columns: tuple[str, ...]
    declined: tuple[Declined, ...]
    rows: tuple[RowDiff, ...]

    @property
    def ok(self) -> bool:
        return not self.rows

    @property
    def cell_count(self) -> int:
        return sum(len(row.cells) for row in self.rows)

    def as_json(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "source": self.source,
            "row_source": self.row_source,
            "stored_rows": self.stored_rows,
            "rebuilt_rows": self.rebuilt_rows,
            "checked_columns": list(self.checked_columns),
            "carried_columns": list(self.carried_columns),
            "unchecked_columns": list(self.unchecked_columns),
            "declined": [{"key": list(d.key), "reason": d.reason} for d in self.declined],
            "diffs": [row.as_json() for row in self.rows],
        }


@dataclass(frozen=True)
class Uncovered:
    """A table holding Zone H rows that no registered regenerator rebuilds.

    Not an error and not a warning about this module: it is the measurement T.3 actually asks
    for. Every row counted here is a row the design says is regenerable and the code cannot
    regenerate.
    """

    table: str
    rows: int

    def as_json(self) -> dict[str, Any]:
        return {"table": self.table, "rows": self.rows}


@dataclass(frozen=True)
class RebuildReport:
    """Every rebuilt table, plus the inventory of Zone H that nothing rebuilds."""

    tables: tuple[TableDiff, ...] = ()
    uncovered: tuple[Uncovered, ...] = ()
    missing_tables: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return all(table.ok for table in self.tables)

    @property
    def diff_count(self) -> int:
        return sum(len(table.rows) for table in self.tables)

    @property
    def covered_rows(self) -> int:
        return sum(table.stored_rows for table in self.tables)

    @property
    def uncovered_rows(self) -> int:
        return sum(item.rows for item in self.uncovered)

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "covered_rows": self.covered_rows,
            "uncovered_rows": self.uncovered_rows,
            "tables": [table.as_json() for table in self.tables],
            "uncovered": [item.as_json() for item in self.uncovered],
            "missing_tables": list(self.missing_tables),
        }


# ------------------------------------------------------------------------------------ the run


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """Column names, read with a bound parameter rather than interpolated.

    Same rule `db.fixture` states for the same reason: a table name cannot be bound as a SQL
    parameter, so the only safe form is to read the live schema and compare against it.
    """
    rows = conn.execute("SELECT name FROM pragma_table_info(?)", (table,)).fetchall()
    return tuple(str(row[0]) for row in rows)


def _stored_zone_h(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Every Zone H row of `table`, as plain dicts.

    `table` is checked against `sqlite_master` by the caller before it reaches this statement.
    """
    cursor = conn.execute(f"SELECT * FROM '{table}' WHERE zone = ?", (ZONE_H,))
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _key_of(row: Mapping[str, Any], key: Sequence[str]) -> tuple[str, ...]:
    return tuple("" if row.get(name) is None else str(row[name]) for name in key)


def _project(
    rows: Sequence[Mapping[str, Any]], key: Sequence[str], carried: Sequence[str]
) -> tuple[Mapping[str, Any], ...]:
    """The stored rows with every column the regenerator is not allowed to see removed.

    This is honesty mechanism 1 from the module docstring, and it is enforced here rather than
    asked for in a docstring because a convention cannot fail a build. A regenerator that tries
    to read a `rebuilt` column gets a KeyError, in its own tests, on the first run.
    """
    allowed = (*key, *carried)
    return tuple({name: row.get(name) for name in allowed} for row in rows)


def _diff_rows(
    stored: Sequence[Mapping[str, Any]],
    rebuilt: Sequence[Mapping[str, Any]],
    *,
    key: Sequence[str],
    checked: Sequence[str],
    declined: frozenset[tuple[str, ...]],
) -> tuple[RowDiff, ...]:
    by_key_stored = {_key_of(row, key): row for row in stored}
    by_key_rebuilt = {_key_of(row, key): row for row in rebuilt}
    diffs: list[RowDiff] = []

    for row_key in sorted(by_key_stored.keys() | by_key_rebuilt.keys()):
        stored_row = by_key_stored.get(row_key)
        rebuilt_row = by_key_rebuilt.get(row_key)
        if stored_row is None:
            diffs.append(RowDiff(key=row_key, kind="only_in_rebuild"))
            continue
        if rebuilt_row is None:
            if row_key in declined:
                # Declared and counted elsewhere; reporting it here as a lost row would be a
                # false positive that trains the reader to ignore the real ones.
                continue
            # A finding under either `row_source`, for two different reasons. Under `zone_r` the
            # derivation did not produce a row the store holds, which is the Zone H row with no
            # Zone R behind it that T.3 is looking for. Under `store` the regenerator was handed
            # the row and returned nothing for it *without declining it*, which means the rule
            # fell through a case nobody wrote down. Neither is swallowed.
            diffs.append(RowDiff(key=row_key, kind="only_in_store"))
            continue
        cells = tuple(
            CellDiff(column=column, stored=stored_row.get(column), rebuilt=rebuilt_row.get(column))
            for column in checked
            if stored_row.get(column) != rebuilt_row.get(column)
        )
        if cells:
            diffs.append(RowDiff(key=row_key, kind="changed", cells=cells))
    return tuple(diffs)


def rebuild_table(conn: sqlite3.Connection, regenerator: Regenerator) -> TableDiff:
    """Snapshot one table's Zone H rows, rebuild them, and diff."""
    columns = _columns(conn, regenerator.table)
    stored = _stored_zone_h(conn, regenerator.table)
    produced = regenerator.regenerate(conn, _project(stored, regenerator.key, regenerator.carried))
    accounted = {*regenerator.key, *regenerator.rebuilt, *regenerator.carried}
    return TableDiff(
        table=regenerator.table,
        source=regenerator.source,
        row_source=regenerator.row_source,
        stored_rows=len(stored),
        rebuilt_rows=len(produced.rows),
        checked_columns=regenerator.rebuilt,
        carried_columns=regenerator.carried,
        unchecked_columns=tuple(name for name in columns if name not in accounted),
        declined=produced.declined,
        rows=_diff_rows(
            stored,
            produced.rows,
            key=regenerator.key,
            checked=regenerator.rebuilt,
            declined=frozenset(item.key for item in produced.declined),
        ),
    )


def uncovered_zone_h(
    conn: sqlite3.Connection, *, covered: frozenset[str] = frozenset()
) -> tuple[Uncovered, ...]:
    """Every table holding Zone H rows that no registered regenerator rebuilds.

    Walks the live schema rather than a hardcoded list, so a table added next round appears here
    the moment it holds its first Zone H row. That is the property worth having: the gap grows
    louder by itself instead of waiting for someone to remember this file.
    """
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    found: list[Uncovered] = []
    for (name,) in tables:
        table = str(name)
        if table in covered or "zone" not in _columns(conn, table):
            continue
        row = conn.execute(f"SELECT COUNT(*) FROM '{table}' WHERE zone = ?", (ZONE_H,)).fetchone()
        count = int(row[0])
        if count:
            found.append(Uncovered(table=table, rows=count))
    return tuple(found)


def rebuild_zone_h(
    conn: sqlite3.Connection, regenerators: Sequence[Regenerator] | None = None
) -> RebuildReport:
    """Rebuild every declared Zone H derivation and inventory everything else.

    A regenerator whose table does not exist in this database is reported by name in
    `missing_tables` rather than raising. The harness has to run against a fixture that does not
    populate every table and against a database one schema version behind, and a crash on the
    first absent table would mean the whole check stops at the first gap instead of reporting it.
    """
    from .regenerators import REGENERATORS

    chosen = REGENERATORS if regenerators is None else tuple(regenerators)
    tables: list[TableDiff] = []
    missing: list[str] = []
    for regenerator in chosen:
        if not _table_exists(conn, regenerator.table):
            missing.append(regenerator.table)
            continue
        tables.append(rebuild_table(conn, regenerator))
    covered = frozenset(regenerator.table for regenerator in chosen)
    return RebuildReport(
        tables=tuple(tables),
        uncovered=uncovered_zone_h(conn, covered=covered),
        missing_tables=tuple(missing),
    )


def exit_code(report: RebuildReport) -> int:
    """0 when everything declared rebuilt exactly; 1 when anything did not.

    Uncovered Zone H rows deliberately do **not** fail the run. They are the known, reported
    state of the atlas as of 2026-09-24, and a check that is red from the day it lands gets
    muted rather than fixed. The test suite pins the uncovered inventory instead
    (`tests/test_rebuild.py`), so the gap can shrink freely and cannot grow unnoticed.
    """
    return 0 if report.ok else 1
