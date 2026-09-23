"""``fermdb db ...``: schema version reporting and the explicit migration command.

Separate from `cli.py` the way `omics`, `atlas`, `extract` and `query` are.

`fermdb db migrate` is the only thing in this project that changes a database's shape, and it is
built to be boring about it: it says what it will do, takes a timestamped backup, and then does
exactly that. ``--dry-run`` is the default posture of the reporting command rather than a flag you
have to remember, because the interesting failure is not "the migration errored" -- SQLite rolls
that back -- but "the migration ran and I did not know what it would touch".
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from ..config import Settings
from . import SCHEMA_VERSION, DatabaseError, open_db, schema_version
from .migrations import MigrationError, copy_backup, migrate, pending

__all__ = ["add_db_subcommand"]


def cmd_db_status(_args: argparse.Namespace) -> int:
    """What version the database is at, and what would run to bring it up to date."""
    settings = Settings.load()
    database = Path(settings.db_file)
    if not database.is_file():
        print(f"no database at {database}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        found = schema_version(conn)
        print(f"database     {database}")
        print(f"on disk      v{found}")
        print(f"this build   v{SCHEMA_VERSION}")
        if found == SCHEMA_VERSION:
            print("status       up to date")
            return 0
        try:
            chain = pending(conn)
        except MigrationError as exc:
            print(f"status       no migration path: {exc}", file=sys.stderr)
            return 1
        print(f"status       {len(chain)} migration(s) pending")
        print()
        for migration in chain:
            print(f"  {migration.label}  {migration.summary}")
            for statement in migration.statements:
                print(f"      {' '.join(statement.split())[:96]}")
    finally:
        conn.close()
    return 0


def cmd_db_migrate(args: argparse.Namespace) -> int:
    """Back up, then apply every pending migration in one transaction."""
    settings = Settings.load()
    database = Path(settings.db_file)
    if not database.is_file():
        print(f"no database at {database}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        try:
            chain = pending(conn)
        except MigrationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if not chain:
            print(f"already at v{SCHEMA_VERSION}; nothing to do")
            return 0

        print(f"{database}")
        for migration in chain:
            print(f"  {migration.label}  {migration.summary}")
        if args.dry_run:
            print()
            print("--dry-run: nothing was changed")
            return 0

        if not args.no_backup:
            target = copy_backup(database)
            print(f"  backup    {target.name}")

        ran = migrate(conn)
    except DatabaseError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"  applied   {len(ran)} migration(s); database is at v{SCHEMA_VERSION}")
    print()
    print("New columns are NULL on existing rows, which is 'never assessed' rather than a value.")
    print(
        "Re-run the loader that owns them to backfill. v17's columns "
        "(gene.seqid, biotype, locus_tag, description) are owned by `fermdb genomics "
        "load-gff3 <RefSeq GFF3> --assembly-accession ... --organism-id ...` -- run it with "
        "--dry-run first; v6's pathway columns by `fermdb atlas pathways`."
    )
    return 0


def cmd_db_check(_args: argparse.Namespace) -> int:
    """Integrity and foreign-key check. Cheap, and worth running after a migration."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    try:
        integrity = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    ok = integrity == ["ok"] and not violations
    print(f"integrity_check    {', '.join(integrity)}")
    print(f"foreign_key_check  {len(violations)} violation(s)")
    for row in violations[:10]:
        print(f"  {tuple(row)}")
    return 0 if ok else 1


def add_db_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``fermdb db ...`` to an existing top-level subparsers action."""
    p_db = sub.add_parser("db", help="schema version, explicit migrations, integrity checks")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)

    p_status = db_sub.add_parser(
        "status", help="the on-disk schema version and what migrations are pending"
    )
    p_status.set_defaults(func=cmd_db_status)

    p_migrate = db_sub.add_parser(
        "migrate", help="apply pending migrations, after taking a timestamped backup"
    )
    p_migrate.add_argument(
        "--dry-run", action="store_true", help="show what would run and change nothing"
    )
    p_migrate.add_argument(
        "--no-backup",
        action="store_true",
        help="skip the backup copy (only for a database you can rebuild)",
    )
    p_migrate.set_defaults(func=cmd_db_migrate)

    p_check = db_sub.add_parser("check", help="integrity_check and foreign_key_check")
    p_check.set_defaults(func=cmd_db_check)
