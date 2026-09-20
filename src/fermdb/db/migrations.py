"""Explicit, reviewable schema migrations.

`db/__init__.py` refuses to migrate on open, and says why: *"an implicit migration is an
unreviewed data change."* That leaves a gap this module fills -- until now there was no reviewed
path either, so the only way past a version bump was to delete the database and rebuild it.

For this atlas that is not a real option. The pathway tables rebuild from committed YAML for
free, but the same file holds 5,164 publications, 1,308 stored full texts, 172 SRA runs and 55
pending curation tasks, none of which does. A migration mechanism is cheaper than re-acquiring
them, and much cheaper than the temptation to keep the schema wrong because fixing it is scary.

**The design rule here is that a migration may add and may backfill, and may not destroy.** Every
statement below is `ALTER TABLE ... ADD COLUMN`, `CREATE TABLE` or `CREATE INDEX`. There is no
DROP and no UPDATE that loses a value. That is not a limitation of SQLite; it is the property that
makes a migration reviewable as a diff, which is how everything else in this repo is reviewed
(CONVENTIONS.md, "Curation"). A migration that genuinely needs to drop a column should be written
as a new table plus a copy, so the old data is still there to compare against when it goes wrong.

**Fresh and migrated databases must end up identical.** A schema that can be reached two ways is
a schema with two definitions, and they drift. `schema.sql` stays the single source of truth for
what the current version looks like; the migrations below exist to get an *existing* file there.
`tests/test_migrations.py` asserts the two agree column for column, index for index -- so a future
migration that forgets to mirror an edit to `schema.sql` fails in CI rather than in production six
weeks later.

Migrations run inside an **explicit** transaction. SQLite's DDL is transactional, but Python's
`sqlite3` opens its implicit transaction only before INSERT/UPDATE/DELETE/REPLACE -- not before
DDL -- so under the default settings every `ALTER TABLE` would autocommit and survive a rollback.
:func:`migrate` sets `isolation_level = None` and issues `BEGIN` itself. See the comment there;
the first version of this module got it wrong and a test caught it.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from . import SCHEMA_VERSION, DatabaseError, schema_version

__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationError",
    "backup_path",
    "copy_backup",
    "migrate",
    "pending",
]

_VERSION_KEY: Final[str] = "schema_version"


class MigrationError(DatabaseError):
    """A migration could not be applied, or no path exists to the requested version."""


@dataclass(frozen=True)
class Migration:
    """One version step. ``statements`` run in order, inside the caller's transaction."""

    from_version: int
    to_version: int
    summary: str
    statements: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"v{self.from_version} -> v{self.to_version}"


#: v5 -> v6. The curated pathway facts that were parsed and then dropped on the way into storage.
#:
#: `data/pathways/*.yaml` recorded all of these and `metabolic/curated.py` parsed every one of
#: them into its dataclasses, where the balance checks used them -- and then the INSERT statements
#: mentioned none of them. The information existed, was validated, and was discarded one line
#: before it would have been persisted. Nothing failed, because a dropped column raises nothing.
#:
#: What it cost, concretely: the database could not say which reactions drain the 2-KIV pool, nor
#: tell NADPH from acetolactate, nor join a reaction to any of the 36 resolved genes.
_V5_TO_V6: Final[Migration] = Migration(
    from_version=5,
    to_version=6,
    summary=(
        "curated pathway facts that were parsed and then dropped: reaction.competing, "
        "reaction_gene, and metabolite carbons/carrier/redox/pair/adenylate"
    ),
    # Column order matters here and is not cosmetic: `redox`'s CHECK refers to `pair` and
    # `carrier`, so those columns must exist before it is added or the ALTER fails.
    statements=(
        "ALTER TABLE reaction ADD COLUMN competing INTEGER CHECK (competing IN (0, 1))",
        "ALTER TABLE metabolite ADD COLUMN carbons INTEGER CHECK (carbons IS NULL OR carbons >= 0)",
        "ALTER TABLE metabolite ADD COLUMN carrier INTEGER CHECK (carrier IN (0, 1))",
        "ALTER TABLE metabolite ADD COLUMN pair TEXT",
        "ALTER TABLE metabolite ADD COLUMN redox TEXT "
        "CHECK (redox IS NULL OR (redox IN ('reduced', 'oxidized') "
        "AND pair IS NOT NULL AND carrier = 1))",
        "ALTER TABLE metabolite ADD COLUMN adenylate TEXT "
        "CHECK (adenylate IS NULL OR (adenylate IN ('charged', 'discharged') AND carrier = 1))",
        """
        CREATE TABLE reaction_gene (
            reaction_id   TEXT NOT NULL REFERENCES reaction(id) ON DELETE CASCADE,
            gene_symbol   TEXT NOT NULL,
            gene_id       TEXT REFERENCES gene(id),
            gene_group_id TEXT REFERENCES gene_group(id),
            resolution    TEXT NOT NULL
                          CHECK (resolution IN ('resolved', 'unresolved', 'not_attempted')),
            PRIMARY KEY (reaction_id, gene_symbol),
            CHECK (resolution <> 'resolved' OR gene_id IS NOT NULL),
            CHECK (resolution = 'resolved' OR gene_id IS NULL)
        )
        """,
        "CREATE INDEX reaction_gene_by_gene ON reaction_gene(gene_id)",
        "CREATE INDEX reaction_gene_by_symbol ON reaction_gene(gene_symbol)",
    ),
)


#: v6 -> v7. `chassis_profile`: the properties that make "which route should I build" a question
#: about a particular strain rather than a generic one.
_V6_TO_V7: Final[Migration] = Migration(
    from_version=6,
    to_version=7,
    summary="chassis_profile -- ISOBUTANOL_PROGRAM.md §6, defined and never implemented",
    statements=(
        """CREATE TABLE chassis_profile (
    id                  TEXT PRIMARY KEY,
    -- A profile can exist before the strain row does: the owner knows their chassis long before
    -- a curated `strain` row is promoted for it.
    strain_id           TEXT REFERENCES strain(id),
    name_as_reported    TEXT NOT NULL,
    organism_id         TEXT REFERENCES organism(id),
    -- Editing scale. DUET names ~15 loci; in a polyploid the verification burden scales with
    -- this even where marker-free multiplex keeps the transformation count flat.
    ploidy              INTEGER CHECK (ploidy IS NULL OR ploidy >= 1),
    ploidy_state        TEXT CHECK (ploidy_state IN ('recorded', 'not_applicable', 'unknown')),
    marker_free_multiplex INTEGER CHECK (marker_free_multiplex IN (0, 1)),
    -- Whether mitochondrial work is possible at all. A rho-zero chassis disqualifies a matrix
    -- pathway outright rather than merely costing it.
    rho_status          TEXT CHECK (rho_status IN ('rho_plus', 'rho_zero', 'rho_minus',
                                                   'unknown')),
    -- DUET requires Pdc-POSITIVE (DUET_TARGET.md §5.1): the ethanol-acetaldehyde shuttle is the
    -- mechanism, not the competition.
    pdc_status          TEXT CHECK (pdc_status IN ('intact', 'attenuated', 'minus', 'unknown')),
    ferments_xylose     INTEGER CHECK (ferments_xylose IN (0, 1)),
    -- M3, 2026-09-21. 'preferred' is the owner's answer: not required for discovery, preferred
    -- for production, overridable by a demonstrated and scalable process advantage.
    respiration_policy  TEXT CHECK (respiration_policy IN ('required', 'preferred',
                                                           'not_required', 'unknown')),
    -- M4, 2026-09-21. 'not_measured' is distinct from 0: a gap, not a limitation.
    resolves_higher_alcohol_panel INTEGER
                        CHECK (resolves_higher_alcohol_panel IN (0, 1)),
    higher_alcohol_panel_state TEXT
                        CHECK (higher_alcohol_panel_state IN ('recorded', 'not_measured')),
    -- Caps the useful titre. While NULL, every route's ceiling line reads "toxicity-limited ~X".
    isobutanol_tolerance_g_l REAL CHECK (isobutanol_tolerance_g_l IS NULL
                                         OR isobutanol_tolerance_g_l >= 0),
    isobutanol_tolerance_state TEXT
                        CHECK (isobutanol_tolerance_state IN ('recorded', 'not_applicable',
                                                              'unknown')),
    tolerance_endpoint  TEXT,            -- 'growth rate 50% of control' | 'viability' | ...
    -- Strategy E tooling. M2: not in hand, purchasable in a lab background only.
    mtdna_tooling       TEXT CHECK (mtdna_tooling IN ('available_here',
                                                      'available_after_acquisition',
                                                      'available_after_strain_construction',
                                                      'unavailable', 'unknown')),
    is_selected         INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
    zone                TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence            TEXT NOT NULL,
    confidence          TEXT NOT NULL
                        CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (ploidy IS NULL OR ploidy_state = 'recorded'),
    CHECK (isobutanol_tolerance_g_l IS NULL OR isobutanol_tolerance_state = 'recorded')
);""",
        "CREATE UNIQUE INDEX chassis_profile_one_selected "
        "ON chassis_profile(is_selected) WHERE is_selected = 1",
    ),
)

#: Every known migration, in order. A version with no entry has no path and is refused.
MIGRATIONS: Final[tuple[Migration, ...]] = (_V5_TO_V6, _V6_TO_V7)


def pending(conn: sqlite3.Connection, *, to: int = SCHEMA_VERSION) -> tuple[Migration, ...]:
    """The migrations that would run, in order, or raise if no path reaches ``to``.

    Separated from :func:`migrate` so a caller -- and the CLI -- can show what is about to happen
    before anything happens.
    """
    found = schema_version(conn)
    if found is None:
        raise MigrationError("database has no schema; create it rather than migrating it")
    if found == to:
        return ()
    if found > to:
        raise MigrationError(
            f"database is at v{found}, ahead of the requested v{to}. Migrations only go forward; "
            "downgrading would mean dropping whatever the newer version added."
        )

    by_source = {migration.from_version: migration for migration in MIGRATIONS}
    chain: list[Migration] = []
    version = found
    while version < to:
        step = by_source.get(version)
        if step is None:
            raise MigrationError(
                f"no migration from v{version}; the chain to v{to} is broken at that point"
            )
        chain.append(step)
        version = step.to_version
    return tuple(chain)


def backup_path(database: Path, *, now: datetime | None = None) -> Path:
    """Where :func:`migrate` puts its copy: ``<name>.pre-v<N>.<timestamp>.bak``.

    Timestamped rather than fixed, so a second migration cannot overwrite the backup taken before
    the first one -- which is exactly the copy you want when a migration turns out to have been
    wrong two steps back.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return database.with_suffix(database.suffix + f".pre-v{SCHEMA_VERSION}.{stamp}.bak")


def migrate(
    conn: sqlite3.Connection,
    *,
    to: int = SCHEMA_VERSION,
    steps: Sequence[Migration] | None = None,
) -> tuple[Migration, ...]:
    """Apply every pending migration and stamp the new version. Returns what ran.

    The whole chain is one transaction. A half-migrated database is worse than an unmigrated one,
    because the version stamp would no longer describe the file.
    """
    chain = tuple(steps) if steps is not None else pending(conn, to=to)
    if not chain:
        return ()

    # An explicit BEGIN, not `with conn:`.
    #
    # Python's sqlite3 opens its implicit transaction before INSERT/UPDATE/DELETE/REPLACE and
    # **not before DDL**, so under the default isolation_level every `ALTER TABLE` here would run
    # in autocommit and survive a rollback. A migration that failed on its fifth statement would
    # leave four applied and the version stamp unchanged -- a database matching no schema at all,
    # and one that `open_db` would then refuse for the wrong reason.
    #
    # That is not theoretical: the first version of this function used `with conn:` and a test
    # caught it by failing a deliberately broken migration and finding the column still there.
    # With isolation_level = None and an explicit BEGIN, SQLite's own transactional DDL applies.
    previous_isolation = conn.isolation_level
    foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    # PRAGMA foreign_keys is a no-op inside a transaction, so it goes before BEGIN. The new tables
    # are created empty, so nothing here can violate a constraint; the check after COMMIT proves it.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        try:
            for migration in chain:
                for statement in migration.statements:
                    conn.execute(statement)
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = ?",
                (str(chain[-1].to_version), _VERSION_KEY),
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise MigrationError(
                f"migration left {len(violations)} foreign-key violation(s); "
                "the database is at the new version and needs inspection"
            )
    finally:
        conn.isolation_level = previous_isolation
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return chain


def copy_backup(database: Path, *, now: datetime | None = None) -> Path:
    """Copy the database file beside itself before anything touches it.

    Copies the `-wal` and `-shm` sidecars too when they exist. A WAL-mode database whose backup
    omits the write-ahead log can be missing its most recent transactions, which is the kind of
    backup that is worse than none because it looks like one.
    """
    if not database.is_file():
        raise MigrationError(f"no database at {database}")
    target = backup_path(database, now=now)
    shutil.copy2(database, target)
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))
    return target
