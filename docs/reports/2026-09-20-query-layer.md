# The query layer, and three curated facts that never reach the database

2026-09-20. Commits `84baed2` (foundation) and `b5666ba` (pathway read).

## Why this was built before any UI

PLAN.md D.3 puts a `QUERY` tier between the domain tables and the interface, and names the
violation to guard against: *"the UI reaching into files directly."* There was nothing in that
tier. A UI started today would have committed that violation on its first line — not through
carelessness, but because no alternative existed.

`docs/reference/OPEN_QUESTIONS.md` Q2 also names a web UI as one of three triggers to revisit the
storage engine, and prescribes the mitigation: *"SQLite, accessed through SQLAlchemy Core from the
first line of code."* That was not followed — ~106 raw `execute(` call sites, no SQLAlchemy — so
the mitigation was due exactly now and did not exist.

## What landed

| module | what it is |
|---|---|
| `query/values.py` | `Value`, `Quantity`, `EvidenceLevel`, `Cited` — the evidence and missing-value rules as types |
| `query/builder.py` | read-only query builder: no interpolated values, pages that report their own truncation |
| `query/coverage.py` | the Dashboard read, including *why* each empty table is empty |
| `query/pathways.py` | the Pathway read, gaps included |
| `query/cli.py` | `fermdb query coverage \| pages \| pathway`, each with `--json` |

36 tests. Gate green: ruff, ruff format, mypy (51 files), full suite.

### The absences it refuses to flatten

CONVENTIONS.md's three missing-value states survive the database easily — `schema.sql` spends a
hundred CHECK constraints on them — and then die at the first `json.dumps`, because JSON has one
absence and `value ?? "—"` collapses all three in a single character. So a fact leaves this layer
as a `Value` holding either a value or an `Absence`, never both, serializing with `display`
already filled in. An absent one carries **no `value` key at all**, so a consumer reaching for it
gets `undefined` and a visible bug rather than `null` and a plausible dash.

The worse case is `EvidenceLevel`. The `assertion_level` view returns NULL for two opposite
reasons — `no_evidence` (nothing is known) and `direct_evidence_discordant` (direct evidence on
both sides, which the view deliberately declines to grade). An empty cell and an open scientific
dispute, arriving as the same NULL. The view distinguishes them in `basis`, so `EvidenceLevel`
requires the basis and refuses to construct without it.

## Coverage, measured

```
12 populated · 6 awaiting curation · 4 never looked · 4 of 9 P.2 pages renderable
```

The 22 empty tables are not one thing. Six are empty with **55 proposals queued** — `measurement`
18, `strain` 14, `modification` 12, `condition_context` 6, `bottleneck` 4,
`pathway_configuration` 1. The gate there is curation, not acquisition. Four — `experiment`,
`assertion`, `evidence_item`, `conflict` — are empty with nothing proposed: never looked.

Renderable today: **Dashboard, Gene, Pathway, Publication**. (My earlier estimate of two was low;
the layer's own measurement is the one to trust.)

## The finding: three facts are dropped on load

Building the Pathway reader turned up that the page cannot be built as P.2 specifies it. Each of
these is recorded in `data/pathways/*.yaml`, parsed by `metabolic/curated.py` into its
dataclasses, and then **not written**:

| fact | where it dies |
|---|---|
| `competing` | `reaction` has no such column; the INSERT doesn't mention one |
| `genes` | concatenated into the evidence sentence as `[genes: LEU4, LEU9]`, not joined to `gene` |
| `carrier` | `role` permits `'cofactor'` and the loader never writes it — 32 products, 29 substrates, **0 cofactors**; `metabolite` has no `carrier` column |

Consequences, concretely:

- Which reactions drain the 2-ketoisovalerate pool — the valine branch, the leucine branch, ECM31
  — is **not in the database**. That is the most decision-relevant fact in the isobutanol pathway.
- `fermdb atlas pathways` prints `(3 competing)` from the in-memory YAML objects, so the CLI looks
  like it knows while the atlas does not.
- NADPH is stored as an ordinary substrate of KARI, structurally identical to acetolactate. The
  DUET cofactor argument — matrix NADPH vs cytosolic NADH — cannot be drawn from these rows.
- 36 genes are resolved in `gene`/`gene_group` and no reaction links to any of them.

P.3's rule is that **a diagram that can disagree with the database is decoration**. A diagram
drawn from this database would show the three drains as ordinary reactions and NADPH as backbone
carbon, and would look complete doing it.

### How the reader handles it

It papers over none of them. Each is an absent `Value` with a reason rather than a default:
`competing: false` on the valine branch would not be a missing fact but a false one, and
`is_carrier: false` would report every carrier in the atlas as backbone carbon. `PathwayRead.gaps`
names all three in the payload so an interface can say *why* the picture is incomplete.

The genes are sitting right there in the evidence text and are **deliberately not parsed back
out**. Recovering a structured fact from free text would assert a link the atlas cannot defend and
would hide the loader bug behind a page that appears to work.

Nothing is hard-coded: `read_pathway` asks the database what columns and roles exist, so when the
loader is fixed the reader picks the facts up and the gap list shrinks on its own. Tests cover
both branches.

## Resolved: schema v6, applied

Authorised and done — commit `7b5ce4c`.

**Widened beyond the three above.** Reading the loader properly showed `metabolite` also dropping
`carbons`, `redox`, `pair` and `adenylate` — the same defect on the same line. A second migration
would have meant a second version bump and a second refusal of a database holding 5,164
publications, so batching was strictly cheaper than being narrowly faithful to what I had already
reported. `redox`/`pair` is also what makes the DUET argument expressible: without it NADH and
NADPH are two unrelated strings.

### The migration mechanism

There wasn't one. `open_db` has always refused to migrate and said why, but there was no reviewed
path either, so the only route past a version bump was delete-and-rebuild. `db/migrations.py` is
that path, and it is add-only: no `DROP`, no lossy `UPDATE`, enforced by a test on each
statement's leading verb. It backs up to a timestamped copy that takes the `-wal` with it, and
runs the whole chain in one transaction.

**Two bugs the tests caught before the real database saw them:**

1. **`with conn:` does not roll back DDL.** Python's `sqlite3` opens its implicit transaction only
   before `INSERT`/`UPDATE`/`DELETE`/`REPLACE` — not before DDL — so every `ALTER` was
   autocommitting and surviving the rollback. A failure on statement five would have left four
   applied and the version stamp unchanged: a database matching no schema at all. Fixed with
   `isolation_level = None` and an explicit `BEGIN`.
2. **SQLite has no `ADD CONSTRAINT`.** The table-level CHECKs I first wrote on `metabolite` were
   unreachable by `ALTER`, so a *migrated* database would have ended up with weaker constraints
   than a *fresh* one — and `PRAGMA table_info` does not report CHECKs, so no shape comparison
   would have caught it. Rewritten as column CHECKs referring to sibling columns, which do
   survive. Column order in the migration is now load-bearing and says so.

`tests/test_migrations.py` builds the v5 tables verbatim, migrates them, and compares against what
`schema.sql` produces today — shape by PRAGMA, constraints by behaviour. A future migration that
forgets to mirror an edit to `schema.sql` fails there rather than in production.

### Applied to the live database

```
60 tables identical row for row · 1 new empty table
integrity_check ok · 0 foreign-key violations
backup: fermdb.sqlite3.pre-v6.20260920T123452Z.bak
```

Backfilled by `fermdb atlas pathways`:

| | |
|---|---|
| competing reactions | **6** — including the three 2-KIV drains |
| `reaction_gene` rows | **29** — 22 resolved, **7 unresolved** |
| unresolved symbols | ADH1, ADH6, ADH7, GPD2, GPP1, GPP2 — none in `gene`, none guessed at |
| carriers with redox pools | **8** — NADPH `pair=nadp`, NADH `pair=nad` |

Those seven are the point of the three-state `resolution` column. LEU4 sits right beside LEU9 in
the same table; a similarity heuristic would have linked ADH1 to ADH2 and the row would have
rendered exactly as confidently as a correct one.

The Pathway page now reports **no gaps** and is renderable as P.2 specifies it. `PathwayRead.gaps`
stays, computed from the schema rather than hard-coded, so it shrank on its own and will grow
again by itself if a pathway arrives without these facts.

## Next

- Readers for the other renderable pages: **Publication** (5,164 rows, with extraction spans —
  P.2's *"click a value, see the sentence"*) and **Gene** (36 resolved, 675 annotations).
- A curation review surface over the 55 pending proposals, which is the fastest route to
  unblocking six of the empty tables and three more pages.
