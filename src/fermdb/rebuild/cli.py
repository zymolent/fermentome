"""``fermdb rebuild zone-h``: run the T.3 rebuild check and print what it found.

Separate from `cli.py` the way `omics`, `atlas`, `query` and `db` are, so the top-level parser
gains an import and one call.

**The database is opened read-only.** The check never needs to write, and the shared atlas is the
one file in this project a mistake cannot be taken back from -- so the connection is opened
through a `mode=ro` URI rather than trusting the check to behave. `just rebuild-check` copies the
database before running this; the read-only open is the second lock.

Exit status is the whole point of the command: 0 when everything declared rebuilt exactly, 1 when
anything did not. Uncovered Zone H rows are printed loudly and do not change the status -- see
`fermdb.rebuild.exit_code` for that argument.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ..config import Settings
from . import WHY_IT_MATTERS, RebuildReport, exit_code, rebuild_zone_h

__all__ = ["add_rebuild_subcommand"]


def _open_read_only(database: Path) -> sqlite3.Connection:
    """A connection that cannot write, whatever the code above it does.

    `db.open_db` is the project's only opener and stays that way for a writable connection; this
    is the deliberate exception, and it is an exception about *safety*, not about convenience.
    It also skips the schema-version check on purpose: a rebuild check run against a database one
    version behind should report what it can rather than refuse to look.
    """
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _print_report(report: RebuildReport) -> None:
    for table in report.tables:
        header = f"{table.table}  ({table.stored_rows} Zone H row(s), from {table.source})"
        print(header)
        print(
            f"  rebuilt   {len(table.checked_columns)} column(s): "
            f"{', '.join(table.checked_columns)}"
        )
        if table.carried_columns:
            print(
                f"  carried   {len(table.carried_columns)} column(s) taken from the stored row "
                f"because no Zone R source holds them: {', '.join(table.carried_columns)}"
            )
        if table.unchecked_columns:
            print(
                f"  unchecked {len(table.unchecked_columns)} column(s): "
                f"{', '.join(table.unchecked_columns)}"
            )
        if table.row_source == "store":
            print(
                "  row set   taken from the store: this check cannot tell you whether the "
                "right rows exist,"
            )
            print(
                "            only whether the rows that exist carry the values the rule produces."
            )
        if table.declined:
            print(f"  declined  {len(table.declined)} row(s) the regenerator refused, e.g.:")
            print(f"              {table.declined[0].key[0]}: {table.declined[0].reason}")
        if table.ok:
            print("  RESULT    rebuilt identically")
        else:
            print(f"  RESULT    {len(table.rows)} row(s) differ, {table.cell_count} cell(s)")
            for row in table.rows:
                if row.kind == "only_in_store":
                    print(f"    {row.label}: in the store, not produced by the rebuild")
                elif row.kind == "only_in_rebuild":
                    print(f"    {row.label}: produced by the rebuild, absent from the store")
                else:
                    print(f"    {row.label}:")
                    for cell in row.cells:
                        print(f"      {cell.column}")
                        print(f"        stored  {cell.stored!r}")
                        print(f"        rebuilt {cell.rebuilt!r}")
        print()

    if report.missing_tables:
        print(f"not in this database: {', '.join(report.missing_tables)}")
        print()

    if report.uncovered:
        print(f"Zone H that NOTHING rebuilds -- {report.uncovered_rows} row(s):")
        for item in report.uncovered:
            print(f"  {item.table:<28}{item.rows:>8}")
        print()
        print("Each of those rows is one the design calls regenerable and the code cannot")
        print("regenerate. They do not fail this check; they are what it is for.")
        print()

    if report.ok:
        print(f"OK: {report.covered_rows} covered Zone H row(s) rebuilt identically.")
    else:
        print(f"FAIL: {report.diff_count} row(s) did not reconstruct.")
        print()
        print(WHY_IT_MATTERS)


def cmd_rebuild_zone_h(args: argparse.Namespace) -> int:
    """Rebuild every declared Zone H derivation, diff, and report."""
    settings = Settings.load()
    database = Path(args.db) if args.db else Path(settings.db_file)
    if not database.is_file():
        print(f"no database at {database}", file=sys.stderr)
        return 2

    conn = _open_read_only(database)
    try:
        report = rebuild_zone_h(conn)
    finally:
        conn.close()

    if args.json:
        json.dump(report.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return exit_code(report)

    print(f"database  {database}")
    print()
    _print_report(report)
    return exit_code(report)


def add_rebuild_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_rebuild = sub.add_parser(
        "rebuild",
        help="regenerate Zone H from Zone R and diff (PLAN.md T.3)",
    )
    rb_sub = p_rebuild.add_subparsers(dest="rebuild_command", required=True)

    p_zone_h = rb_sub.add_parser(
        "zone-h",
        help="rebuild every declared Zone H derivation and report any difference",
    )
    p_zone_h.add_argument(
        "--db",
        dest="db",
        default=None,
        help="database to check; defaults to the configured db_file. Opened read-only either way",
    )
    p_zone_h.add_argument(
        "--json", action="store_true", help="emit the report as JSON instead of a table"
    )
    p_zone_h.set_defaults(func=cmd_rebuild_zone_h)
