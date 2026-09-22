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


#: v7 -> v8. The ploidies not yet excluded, for a chassis whose ploidy is unknown. Requested so
#: that "unknown" does not throw away the costable part: what each candidate would imply.
_V7_TO_V8: Final[Migration] = Migration(
    from_version=7,
    to_version=8,
    summary="chassis_profile.ploidy_candidates -- keep the options open and costed",
    statements=("ALTER TABLE chassis_profile ADD COLUMN ploidy_candidates TEXT",),
)

#: v8 -> v9. `mtdna_locus`: the translational activator map as a table the atlas can be QUERIED
#: against, rather than a YAML file nothing reads.
#:
#: Why this exists. `MITOCHONDRIAL_PROGRAM.md` §2.1 calls the activator constraint "the binding
#: constraint" and §3 budgets the map as phase-1b curation. The map was curated -- all 8
#: protein-coding loci plus a non-displacing intergenic site -- into
#: `data/mitochondria/activator_map.yaml`, and then nothing loaded it. Benchmark BM-MIT-004's
#: query shape is a design lookup ("for a proposed insertion locus, return utr_source,
#: activator_required and displaced_gene") and it returned nothing, because the only table that
#: could answer it was `mtdna_insertion`, which holds proposed EDITS and not the catalogue of
#: sites an edit may target. Those are different things and they need different tables.
#:
#: This is the sixth instance of the failure mode the 2026-09-21 handover names: a fact recorded
#: faithfully and never wired to anything that reads it.
_V8_TO_V9: Final[Migration] = Migration(
    from_version=8,
    to_version=9,
    summary="mtdna_locus -- the activator map, queryable (MITOCHONDRIAL_PROGRAM.md §2.1)",
    statements=(
        """CREATE TABLE mtdna_locus (
    id                   TEXT PRIMARY KEY,
    -- A gene name for a real locus (COX2, VAR1), or a site name for one that is not a gene
    -- (intergenic_upstream_COX2). Unique because this is a catalogue, not an observation.
    locus                TEXT NOT NULL UNIQUE,
    encodes              TEXT,
    -- The nuclear-encoded translational activators that license this leader, as a JSON array.
    -- NULL means "not recorded", never "none required" -- an insert designed against a locus
    -- with NULL here is exactly the failure BM-MIT-004 exists to catch, so the two must not be
    -- spelled the same way.
    activators           TEXT,
    -- Whose 5' leader drives an insert placed here. Usually the locus's own; the intergenic site
    -- borrows COX2's, which is why this is a separate column rather than an assumption.
    utr_source           TEXT,
    -- NULL = an insert here displaces nothing. True of the intergenic site and of nothing else,
    -- which is the single most consequential fact in the map.
    displaced_if_used    TEXT,
    respiration_retained_if_used INTEGER
                         CHECK (respiration_retained_if_used IN (0, 1)),
    -- How a displaced gene can be re-provided, where the corpus documents a way.
    rescue_available     TEXT CHECK (rescue_available IN ('none', 'nuclear_allotopic_copy',
                                                          'second_locus', 'other', 'unknown')),
    zone                 TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL
                         CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);""",
        "CREATE INDEX mtdna_locus_by_displacement ON mtdna_locus(displaced_if_used)",
    ),
)

#: v9 -> v10. `product.tier` and `product.mw_g_mol` -- two curated columns that were read from the
#: vocabulary file and thrown away on the way in.
#:
#: Why this exists. PLAN.md B.1 opens the priority model with a claim about mechanism, not about
#: intent: *"the tier is a stored property of `product` that drives the acquisition policy in code.
#: It is not an informal understanding."* `data/vocabularies/products.tsv` honoured that -- `tier`
#: is its first column -- and `load_products` then folded it into an evidence sentence
#: (`f"{PRODUCTS_FILE}, tier={row.get('tier', '?')}"`) and wrote no column. The result is that the
#: sentence B.1 wrote to forbid an informal understanding described one: the tier survived only as
#: prose, nothing could filter on it, and no admission rule could consult it.
#:
#: `mw_g_mol` was dropped by the same INSERT. That one costs a number rather than a policy: B.6.7's
#: load-bearing claim is that isobutanol is more growth-inhibitory than ethanol **on a molar
#: basis**, and no g/L measurement can be moved onto a molar axis without it.
#:
#: This is the seventh and eighth instance of the failure mode the 2026-09-21 handover names.
#: Both are ADD COLUMN on an existing table with no backfill here -- `fermdb db vocabularies`
#: rewrites every product row from the TSV, which is where the values come from.
_V9_TO_V10: Final[Migration] = Migration(
    from_version=9,
    to_version=10,
    summary="product.tier + product.mw_g_mol -- the curated columns the loader was discarding",
    statements=(
        # SQLite cannot add a CHECK to an existing table via ALTER, so the constraint that the
        # rebuilt schema.sql carries is not enforced on a migrated database until it is rebuilt.
        # The loader validates the value against the same four tiers on the way in, which is where
        # a bad tier would actually come from.
        "ALTER TABLE product ADD COLUMN tier TEXT",
        "ALTER TABLE product ADD COLUMN mw_g_mol REAL",
    ),
)

#: v10 -> v11. A sixth `compartment_strategy`, for hosts that have no compartment to choose.
#:
#: The first migration in this module that adds a ROW rather than a column, which is worth saying
#: out loud: `compartment_strategy` is seeded by `schema.sql` itself because the five strategies of
#: ISOBUTANOL_PROGRAM.md §2 are vocabulary and not data, and a closed vocabulary that the schema
#: defines can only be extended the same way the schema is -- with a version bump and a reviewable
#: statement. `fermdb db vocabularies` cannot do it, because it reads TSVs and this list is not one.
#:
#: Why the row exists. A-E all answer "which compartment does each step run in", and all five
#: presuppose a eukaryotic host that has compartments to choose between. A prokaryote does not:
#: there is one cytoplasm and the route runs in it. The best-evidenced configuration waiting in
#: `curation_task` is `doi:10.1016/j.jbiotec.2022.09.012` -- *"The isobutanol producing strain
#: E. coli HM501 was used in this work as a host strain"* -- and its extracted
#: `compartment_strategy` is 'NA', which is the honest answer to a question that does not apply
#: and is also unstorable, because `pathway_configuration.compartment_strategy_id` is a foreign
#: key into this table. So a build that PLAN.md phase 1 puts in scope by name ("every published
#: microbial isobutanol production strain, in any host") was blocked by the vocabulary rather than
#: by its evidence. That is the kind of gap a data change fixes.
#:
#: Why this name and not a shorter one. 'F_no_compartmentalization' reads as a sixth CHOICE -- the
#: decision to leave the pathway uncompartmented -- and this is not a decision at all; a name that
#: implies one would eventually be scored against A-E as though the builder had weighed it.
#: 'F_prokaryotic_cytoplasm' fixes the row to a taxon and to a compartment, and the row has to keep
#: reading correctly when the C. glutamicum and B. subtilis configurations arrive, where the
#: cytoplasm is a different one and the reason it is the only option is the same.
#: 'F_single_compartment_host' names the property of the HOST that removes the choice, which is
#: what all of those builds share. The corollary is deliberate: a host that HAS compartments and a
#: build that declines to use them is not this row, because declining is a decision and needs its
#: own.
#:
#: This row is an INSERT and not an ALTER, so the module's "may add, may not destroy" rule holds in
#: the plainest possible way: nothing in a v10 database changes, and one value that could not be
#: stored becomes storable. `tests/test_migrations.py` compares the migrated vocabulary against the
#: freshly created one row for row, because a seeded row is exactly as prone to drifting away from
#: `schema.sql` as a column is, and has no `PRAGMA` to catch it.
_V10_TO_V11: Final[Migration] = Migration(
    from_version=10,
    to_version=11,
    summary=(
        "compartment_strategy gains F_single_compartment_host -- a prokaryotic host has no "
        "compartment decision to record, and A-E all assume one"
    ),
    statements=(
        "INSERT INTO compartment_strategy (id, label, definition, source) VALUES ("
        "'F_single_compartment_host', "
        "'Single-compartment host: no compartment choice to make', "
        "'The host has no internal compartment a pathway step could be placed in, so the whole "
        "route runs in its single cytoplasm and strategies A-E do not apply. This is the absence "
        "of a compartmentalization decision, not a sixth compartment. Distinct from NULL (not "
        "recorded) and from the extractor''s ''NA''/''unknown'' (the paper does not say): here "
        "the record is complete and the question does not arise.', "
        "'PLAN.md phase 1 scope, ''any host''; first required by "
        "doi:10.1016/j.jbiotec.2022.09.012, which states ''The isobutanol producing strain "
        "E. coli HM501 was used in this work as a host strain''.')",
    ),
)

#: v11 -> v12. `measurement.publication_id` and `bottleneck.publication_id` -- the last hop of
#: PLAN.md J.5's chain, which until now existed only as prose.
#:
#: What was broken. J.5 requires a walkable chain from an assertion to the sentence that supports
#: it: assertion -> evidence_item -> measurement -> publication. `modification` has carried a real
#: `publication_id` since v1 and so has `bottleneck_fix_attempt`; `measurement` and `bottleneck`
#: never did. Promotion had the paper in hand the whole time -- `curation_task.publication_id` is
#: NOT NULL -- and wrote it into `evidence` as a sentence ("promoted from curation task
#: YAA:CTASK:... on doi:10.1186/...") and into no column. The consequence was exact: a
#: measurement-backed `evidence_item` could not close its own arm of J.5, because the last hop was
#: not a join. `curate/assertions.py` reported it and declined to regex the DOI back out of the
#: prose, which was the right call -- CONVENTIONS.md calls citing a file in this repo "citing
#: memory with an extra hop", and a parser over an evidence sentence produces a confidently wrong
#: DOI the day the sentence's format changes.
#:
#: Both columns are nullable, and the nullability is a fact and not a convenience: a measurement
#: derived from a deposited dataset rather than from a paper has no publication to name, and must
#: stay storable. NULL therefore means "there is no paper", never "the paper is in the evidence
#: sentence".
#:
#: **The backfill, and where it gets its answer.** This is the first migration here that carries an
#: UPDATE, so the module's "may add and may backfill, may not destroy" rule is doing real work for
#: the first time: both statements write only into a column this same migration created, only where
#: it is NULL, and no existing value can be overwritten by either. `evidence` is untouched.
#:
#: The value comes from `curation_task`, reached two ways at once, and from nothing else:
#:
#: * the row must carry a `curation_event` with action 'promote' naming it, which is what makes it
#:   a promoted row rather than one written by hand or by a loader; and
#: * the task is found by the id derivation the promoter itself uses -- `_measurement_id` is
#:   ``YAA:MEAS:`` plus the first 16 characters of `curation_task.proposal_hash`, and the
#:   bottleneck promoter's is the same shape. That is a structural join against a column, not a
#:   parse of a sentence.
#:
#: The `HAVING COUNT(DISTINCT ...) = 1` is what makes "never guessed" true rather than intended:
#: if two tasks from different publications ever shared a 16-character hash prefix, the subquery
#: returns no row, the column stays NULL, and `fermdb db status` shows it as unlinked. A row that
#: cannot be linked this way is left NULL and reported. On the live database at v11 all 97
#: measurements and all 4 bottlenecks linked, none ambiguous, none left NULL.
_V11_TO_V12: Final[Migration] = Migration(
    from_version=11,
    to_version=12,
    summary=(
        "measurement.publication_id and bottleneck.publication_id -- J.5's last hop, backfilled "
        "from curation_task rather than from the evidence prose"
    ),
    statements=(
        "ALTER TABLE measurement ADD COLUMN publication_id TEXT REFERENCES publication(id)",
        "CREATE INDEX measurement_by_publication ON measurement(publication_id)",
        """
        UPDATE measurement
           SET publication_id = (
               SELECT MIN(t.publication_id) FROM curation_task t
                WHERE 'YAA:MEAS:' || substr(t.proposal_hash, 1, 16) = measurement.id
                  AND t.record_kind IN ('measurements', 'co_reported_higher_alcohols')
               HAVING COUNT(DISTINCT t.publication_id) = 1)
         WHERE publication_id IS NULL
           AND EXISTS (SELECT 1 FROM curation_event e
                        WHERE e.target_type = 'measurement' AND e.target_id = measurement.id
                          AND e.action = 'promote')
        """,
        "ALTER TABLE bottleneck ADD COLUMN publication_id TEXT REFERENCES publication(id)",
        "CREATE INDEX bottleneck_by_publication ON bottleneck(publication_id)",
        """
        UPDATE bottleneck
           SET publication_id = (
               SELECT MIN(t.publication_id) FROM curation_task t
                WHERE 'YAA:BNK:' || substr(t.proposal_hash, 1, 16) = bottleneck.id
                  AND t.record_kind = 'bottlenecks'
               HAVING COUNT(DISTINCT t.publication_id) = 1)
         WHERE publication_id IS NULL
           AND EXISTS (SELECT 1 FROM curation_event e
                        WHERE e.target_type = 'bottleneck' AND e.target_id = bottleneck.id
                          AND e.action = 'promote')
        """,
    ),
)

#: A curator's own include/exclude verdict on a publication, which the atlas had nowhere to put.
#:
#: `screening_record.triage_state` is NOT that place, and the schema says so in its own words: it
#: is "a deterministic function of query_families.yaml and the recorded rule in discovery.py",
#: stamped Zone H because re-running the same family reproduces it, and anything else "must never
#: overwrite `triage_state` here directly". Writing a human verdict there would be erased by the
#: next `fermdb literature discover`, silently, and the owner would have to re-read the papers.
#:
#: Deleting the rows is the other tempting answer and is worse. PLAN.md L.5 forbids an agent
#: deleting at all, and H.3 gives the reason that outlives the rule: **"an excluded paper is a
#: decision, not an absence."** A dropped row cannot say why it went, and the next discovery run
#: puts it straight back with no memory that anybody judged it. The `exclusion_reason` column on
#: `screening_record` already encodes that principle for machine triage; this table extends it to
#: the curator.
#:
#: Zone R, because a person read the paper and decided. One row per publication: a second verdict
#: on the same paper replaces the first through the curator's own path, and the `curation_event`
#: log is where the history lives, exactly as it does for `curation_task`.
_V12_TO_V13: Final[Migration] = Migration(
    from_version=12,
    to_version=13,
    summary=(
        "screening_decision -- the curator's own include/exclude verdict, which triage_state "
        "cannot hold because discovery rebuilds it"
    ),
    statements=(
        """
        CREATE TABLE screening_decision (
            publication_id  TEXT PRIMARY KEY REFERENCES publication(id),
            decision        TEXT NOT NULL
                            CHECK (decision IN ('include', 'exclude', 'borderline')),
            -- Never NULL, for the reason screening_record.exclusion_reason is never NULL on an
            -- exclusion: a changed policy must be able to ask what it would now include.
            reason          TEXT NOT NULL,
            -- Where the verdict was read from, so it can be re-derived: a folder the curator
            -- sorted PDFs into, a spreadsheet column, a session at the screen.
            source          TEXT NOT NULL,
            decided_by      TEXT NOT NULL,
            decided_at      TEXT NOT NULL,
            zone            TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
            evidence        TEXT NOT NULL,
            confidence      TEXT NOT NULL
        )
        """,
        "CREATE INDEX screening_decision_by_decision ON screening_decision(decision)",
    ),
)

#: Who made a screening verdict -- a person, or a model. Added the moment a classifier was about
#: to write into the same table the owner's own reading had just filled.
#:
#: Without it `install_decisions` upserts blind, so a `fermlit` run over 1,606 papers would
#: silently replace the 568 verdicts a person reached by opening the PDF. Those are not the same
#: grade of evidence and must not be interchangeable, which is the identical argument
#: `curation_event.actor_kind` already makes with its CHECK that accepting and promoting require
#: actor_kind = 'human'. This is that rule, applied to screening.
#:
#: Existing rows default to 'human': all 568 came from folders the owner sorted by hand.
_V13_TO_V14: Final[Migration] = Migration(
    from_version=13,
    to_version=14,
    summary=(
        "screening_decision.decided_by_kind -- so a classifier cannot overwrite a verdict a "
        "person reached by reading the paper"
    ),
    statements=(
        "ALTER TABLE screening_decision ADD COLUMN decided_by_kind TEXT NOT NULL "
        "DEFAULT 'human' CHECK (decided_by_kind IN ('human', 'model'))",
        "CREATE INDEX screening_decision_by_kind ON screening_decision(decided_by_kind)",
    ),
)

#: Every known migration, in order. A version with no entry has no path and is refused.
MIGRATIONS: Final[tuple[Migration, ...]] = (
    _V5_TO_V6,
    _V6_TO_V7,
    _V7_TO_V8,
    _V8_TO_V9,
    _V9_TO_V10,
    _V10_TO_V11,
    _V11_TO_V12,
    _V12_TO_V13,
    _V13_TO_V14,
)


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
