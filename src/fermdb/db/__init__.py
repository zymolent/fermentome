"""Database connection and schema versioning.

This module is the **only** place in the codebase that opens the database. Everything else takes
a `sqlite3.Connection` it was handed. That is a deliberate constraint: when SQLite stops being
enough (PLAN.md N.1 and K.5 both anticipate it), the engine changes by editing this one file
instead of by auditing every call site.

Three things every connection must have, and none of which SQLite gives you by default:

* ``PRAGMA foreign_keys = ON`` — SQLite ships with foreign keys *off*, and the setting is
  per-connection, not per-database. A connection that forgets it silently accepts orphan rows.
* ``PRAGMA journal_mode = WAL`` — a reader does not block the writer, which matters as soon as
  the CLI and a notebook are open at once. (This is persistent per database, unlike the above.)
* A checked ``meta.schema_version``. A database written by a newer schema is refused rather than
  migrated implicitly; guessing at a migration is how data gets quietly mangled.

No path is written here. The caller supplies one, resolved from configuration
(``docs/reference/CONVENTIONS.md``, "Paths and configuration"). The one location this module does
know is that of its own ``schema.sql``, which is package data rather than a configurable path.
"""

from __future__ import annotations

import os
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Final

#: Bumped whenever schema.sql changes in a way an existing database would not survive.
#:
#: 2: the genetic code moved off `compartment` and onto the new `encoding_genome` /
#:    `compartment_encoding_genome` tables; three-state `<col>_state` companions and
#:    `<facet>_as_reported` shadows were added; every `confidence` CHECK widened to four values.
#:    A version-1 database cannot be read as a version-2 one, and open_db refuses rather than
#:    guessing at the migration.
#: 4: ONE version covering everything the 2026-09-20 DUET round added to `schema.sql`. Two
#:    packages grew tables in the same round, in parallel, and each independently bumped the
#:    version it found on disk (3) by one; the second to merge renumbered itself to 5, which
#:    briefly made this file claim a version 4 that no database was ever stamped with. Reconciled
#:    back to a single 4 on review: the version counts *on-disk formats that exist*, not the number
#:    of agents that touched the file, and 3 -> 4 is the only real transition here. Both entries
#:    are kept below so the merge history stays legible.
#:
#:    4a (functional annotation) -- added section 17: `gene_annotation`, owned by
#:    src/fermdb/annotate/.
#:
#:    4b (omics acquisition) -- extended section 16: `sra_run` gained `reference_assembly`,
#:    `reference_match_quality` and `unmapped_fraction` (nullable; PLAN.md F.4's per-run
#:    reference-choice loss, measured later by quantification, not this build) and
#:    `relevance_uncertain` (NOT NULL, defaults 0; flags e.g. this corpus's 8 Fusarium graminearum
#:    runs for curator review). New table `reference_genome_asset` for fetched-and-checksummed
#:    bytes of any non-anchor reference genome (bacterial hosts; CEN.PK/Ethanol Red if ever
#:    fetched) -- kept separate from `reference_sequence` because that table's `kind` CHECK and
#:    `encoding_genome` foreign key are yeast-specific (nuclear/mitochondrial, NCBI genetic code
#:    tables 1/3) and would misrepresent a bacterial replicon (table 11). Owned by
#:    src/fermdb/omics/{references,sra}.py; see data/omics/reference_genomes.yaml.
#:
#:    The rule for the next parallel round, so this does not recur: a bump is per *round*, not per
#:    agent. An agent that finds the version already ahead of the last released one adds its note
#:    under that same integer instead of incrementing again.
#: 5: `manual_download_queue.reports_titer_or_yield` became tri-state.
#: 8: `chassis_profile.ploidy_candidates` -- the ploidies not yet excluded, as JSON. A single
#:    NULL says "unknown" and loses the costable half: the consequences differ per candidate and
#:    can be priced before the measurement exists.
#: 7: `chassis_profile`. ISOBUTANOL_PROGRAM.md §6 defined it and nothing implemented it, so all
#:    360 enumerated routes were ranked against no chassis -- a generic answer to a specific
#:    question. Carries §6's properties plus the two the owner's 2026-09-21 answers created:
#:    `respiration_policy` (M3) and `resolves_higher_alcohol_panel` (M4, with a `not_measured`
#:    state distinct from 0). One row may be `is_selected`, enforced by a partial unique index.
#: 6: the curated pathway facts that were parsed and then dropped on the way into storage.
#:    `data/pathways/*.yaml` recorded every one of them, `metabolic/curated.py` parsed them into
#:    its dataclasses and its balance checks used them -- and then the INSERT statements named
#:    none of them. Nothing ever failed, because a column that is never written raises nothing.
#:
#:    Added: `reaction.competing` (which reactions drain a shared intermediate -- the valine
#:    branch, the leucine branch, ECM31 -- the most decision-relevant property of a curated
#:    pathway, and absent from the database until now); `reaction_gene`, replacing the
#:    "[genes: LEU4, LEU9]" suffix the loader appended to the evidence sentence, with a
#:    three-state `resolution` because the pathway files name ADH1/ADH6/ADH7 and `gene` does not
#:    hold them; and `metabolite.carbons/carrier/redox/pair/adenylate`, without which NADPH is
#:    structurally identical to acetolactate.
#:
#:    **This is the first version with a migration.** `db/migrations.py` carries it, and
#:    `fermdb db migrate` applies it after taking a timestamped backup. Before v6 the only route
#:    past a bump was to delete and rebuild, which stopped being reasonable once the same file
#:    held 5,164 publications and 55 pending curation tasks.
#: 11: a sixth `compartment_strategy`, `F_single_compartment_host`. The five seeded strategies are
#:     all answers to "which compartment does each step run in" and all five presuppose a host with
#:     compartments to choose between; a prokaryote has one cytoplasm and no choice, so its honest
#:     `compartment_strategy` was 'NA' -- which is not a foreign key into this vocabulary and so
#:     could not be stored. PLAN.md phase 1 curates "any host", so those builds were in scope by
#:     the plan and unrepresentable by the schema. The first migration that adds a ROW: this list
#:     is seeded by `schema.sql` rather than loaded from a TSV, so extending it is a version bump.
SCHEMA_VERSION: Final[int] = 11

#: Passed as `path` to open an ephemeral database, mainly in tests.
IN_MEMORY: Final[str] = ":memory:"

_PACKAGE: Final[str] = "fermdb.db"
_SCHEMA_RESOURCE: Final[str] = "schema.sql"
_VERSION_KEY: Final[str] = "schema_version"

__all__ = [
    "IN_MEMORY",
    "SCHEMA_VERSION",
    "DatabaseError",
    "SchemaVersionError",
    "create_schema",
    "open_db",
    "schema_sql",
    "schema_version",
]


class DatabaseError(RuntimeError):
    """The database could not be opened or is not in a usable state."""


class SchemaVersionError(DatabaseError):
    """The database's schema version does not match `SCHEMA_VERSION`.

    Raised rather than migrating: an implicit migration is an unreviewed data change.
    """


def schema_sql() -> str:
    """Return the DDL text shipped beside this module."""
    return resources.files(_PACKAGE).joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the schema version recorded in `meta`, or None if the database is empty.

    "Empty" means the `meta` table does not exist. A `meta` table without the version row is a
    corrupted database, not an empty one, and is reported as such.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if row is None:
        return None
    value = conn.execute("SELECT value FROM meta WHERE key = ?", (_VERSION_KEY,)).fetchone()
    if value is None:
        raise DatabaseError(f"database has a meta table but no {_VERSION_KEY!r} row")
    try:
        return int(value[0])
    except (TypeError, ValueError) as exc:
        raise DatabaseError(f"{_VERSION_KEY} is not an integer: {value[0]!r}") from exc


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply `schema.sql` to an empty database and stamp it with `SCHEMA_VERSION`."""
    if schema_version(conn) is not None:
        raise DatabaseError("refusing to create a schema over an existing one")
    conn.executescript(schema_sql())
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (_VERSION_KEY, str(SCHEMA_VERSION)))
    conn.commit()


def open_db(path: str | os.PathLike[str], *, create: bool = True) -> sqlite3.Connection:
    """Open the atlas database and return a connection with the pragmas the schema assumes.

    Args:
        path: Filesystem location, or `IN_MEMORY`. Never defaulted here — the caller resolves it
            from configuration, because no path belongs in source code.
        create: Create the file, its parent directory and the schema if they are absent. Pass
            False when the database is expected to exist and its absence is an error worth
            hearing about rather than a fresh empty atlas.

    Raises:
        DatabaseError: The database is absent and `create` is False, or is malformed.
        SchemaVersionError: The database's schema version is not `SCHEMA_VERSION`.
    """
    target = os.fspath(path)
    if target != IN_MEMORY:
        location = Path(target)
        if not location.exists():
            if not create:
                raise DatabaseError(f"no database at {location}")
            # Only the derived tier is auto-created (CONVENTIONS.md), and a database file is
            # derived-tier by definition.
            location.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target)
    try:
        conn.row_factory = sqlite3.Row
        # Per-connection, and must be set outside a transaction, so it goes first.
        conn.execute("PRAGMA foreign_keys = ON")
        # A no-op on an in-memory database, which reports journal_mode 'memory'.
        conn.execute("PRAGMA journal_mode = WAL")

        found = schema_version(conn)
        if found is None:
            if not create:
                raise DatabaseError(f"{target} has no schema and create=False")
            create_schema(conn)
        elif found > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"{target} was written by schema version {found}; this build understands "
                f"{SCHEMA_VERSION}. Upgrade fermdb rather than downgrading the database."
            )
        elif found < SCHEMA_VERSION:
            raise SchemaVersionError(
                f"{target} is at schema version {found}; this build expects {SCHEMA_VERSION}. "
                "Run the migration explicitly — open_db does not migrate."
            )
    except Exception:
        conn.close()
        raise
    return conn
