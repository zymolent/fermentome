# yeast-alcohol-db

A decision-support system for **engineering *Saccharomyces cerevisiae* to produce isobutanol**:
routes, parts, compartments, engineering records, fermentation phenotypes and literature —
integrated so that every statement traces back to the experiment supporting it, and so that the
answer to "what should I build next" is ranked rather than merely listed.

**Status (2026-09-22): the transcript layer is wired end to end and now answers the question it
was built for.** Schema v15, 65 tables, 1,466 tests passing. 5,164 publications resolved and 1,429 full texts stored; 6,400 routes enumerated
against six gates; the mitochondrial activator map and heterologous-ORF precedents curated.

`condition_context` went from **0 to 9** and 87 of 172 samples now carry an approved context and a
declared strain, so the F.3 gate that blocked every contrast is satisfied for the studies whose
deposits declare their design. **36 differential-expression contrasts** are stored where there
were none (50 computable, 14 withheld over quarantined samples), and `pathway_route.score_evidence` is populated where it was NULL on all 6,400 rows.

SRP342112 was then requantified against its deposited cassette (GenBank MZ541859.1, 33/33 runs,
$0.96 of EC2), which is what makes the transcript layer say anything: **the engineered steps are
not transcriptionally limited.** All four pathway constructs run 13-17 log2 above the parent, and
`adhA` is among the most abundant transcripts in every producer. It also showed that the native
`ILV3` row in the older matrices was **88% cassette spillover** — a reminder that a native gene's
row is not a measurement of that gene when the build carries its own codon-optimized copy.
`docs/reports/2026-09-22-transcript-backed-routes.md` has the arithmetic and the three claims an
adversarial review destroyed along the way.

Doubts about specific rows are now data rather than prose. `data_quality_flag` (schema v15) holds
**4 quarantined samples** whose declared labels contradict their own transcriptomes — the cassette
rows separate a build from a parent by three orders of magnitude, so the check is threshold-free —
and **77 runs** recorded as technical replicates of one another. A quarantined sample cannot enter
a contrast, because `omics.contrasts` reads the table — not because somebody remembers the report.
Nothing is ever relabelled or deleted: using expression data to repair metadata and then analysing
the data under the repaired metadata is circular, and at n=3 it is circular in the direction that
manufactures significance.

The loop is closed end to end: the four strains with transcript evidence now carry their own
titers, and `python ops/answer.py` prints feasibility, transcript backing and measured
performance together. The result inverts the obvious guess — **the mitochondrial build makes
170 mg/L against 46 for the cytosolic one and 37 for the parent, and the redox-balanced cytosolic
build is the worst strain in its study.** Expression does not discriminate between them; the
limitation is 2Fe-2S cluster assembly at Ilv3p, which is a metabolite and genetics finding, not a
transcript one.

Curation is still the rate limit, exactly as PLAN.md W.2 predicted: 894 proposals are queued, and
136 newly harvested isobutanol yields are quote-verified but unreviewed.

Scope is set to **route answers first**: phases 0–4 plus a decision checkpoint, roughly 5.5–6.5
months solo full-time, ending in a ranked evidence-backed route list, an isobutanol omics layer
and a build recommendation. UI, agents and the knowledge graph are deferred —
[PLAN.md](PLAN.md) Q.5 lists each with what it would cost to add. Mitochondrial genome
engineering is a stated research goal, so the mitochondrial genetics corpus is in the critical
path.

Measured volumes: the **entire** isobutanol SRA corpus is **120 runs / 51 GB** (a second runinfo
fetch of the same query returned ~148 runs / ~48 GB; `DATA_VOLUME.md` §2 records both rather than
picking one, because no decision turns on the difference), against 13,117 runs for
ethanol + *S. cerevisiae* — an 89× asymmetry that is why the ethanol layer is capped. 172 runs
have been acquired and quantified. Retained project size ~4–6 GB; AWS cost for the whole omics
campaign under $25.

## Scope, in one table

| tier | product | policy |
|---|---|---|
| **Primary** | isobutanol | Comprehensive, **all host organisms** — yeast, *E. coli*, *C. glutamicum*, *B. subtilis*, cyanobacteria. Most of the pathway biochemistry was established outside yeast and transfers as parts and strategy |
| **Reference** | ethanol | Bounded and **capped**. Admitted only against **six** criteria and seven named slots: the competing pyruvate sink (the counterfactual, not the plan), the performance ceiling, wild-type baselines, transferable tolerance mechanisms, **ethanol as mitochondrial redox shuttle**, and **the genetic basis of industrial performance**. See `docs/reference/ETHANOL_REFERENCE_SLOTS.md` |
| **Adjacent** | isoamyl alcohol, 2-methyl-1-butanol, *n*-butanol | Captured only when co-measured with isobutanol — their ratios diagnose where flux is leaking |
| **Reserved** | organic acids, diols | Rows with no data, proving the schema is product-generic |

Ethanol is in the atlas because isobutanol engineering needs it — principally because pyruvate
decarboxylase is the sink that isobutanol must outcompete. It is not a second product of interest,
and the admission test is explicit: *an ethanol record is admitted only if it answers a question the isobutanol program asks.*

## Documents

* [PLAN.md](PLAN.md) — the master blueprint, sections A–X. Read **X** for the recommended
  architecture in one page, **B** for scope and the admission policy, **Q** for the phase plan,
  **W** for what is most likely to go wrong.
* [docs/design/ISOBUTANOL_PROGRAM.md](docs/design/ISOBUTANOL_PROGRAM.md) — the scientific core:
  the route as the database will hold it, the four compartment strategies, the parts catalog,
  knowledge gaps as first-class objects, and what a route recommendation looks like.
* [docs/design/MITOCHONDRIAL_PROGRAM.md](docs/design/MITOCHONDRIAL_PROGRAM.md) — the mtDNA
  engineering programme: the translational-activator constraint that decides where an insert can
  go, recoding for translation table 3, the Arg8ᵐ precedent and its limits, transformation and
  homoplasmy, and why strategy C should be run before strategy E.
* [docs/reference/DATA_VOLUME.md](docs/reference/DATA_VOLUME.md) — dry volume assessment against
  **measured** PubMed corpus counts. Verdict: a laptop-scale project, under 4 GB on disk; the
  binding constraint is ~450 hours of curation, not bytes.
* [docs/reference/CONVENTIONS.md](docs/reference/CONVENTIONS.md) — rules binding every module:
  units, identifiers, evidence levels, the reported/harmonized/inferred split.
* [docs/reference/OPEN_QUESTIONS.md](docs/reference/OPEN_QUESTIONS.md) — decisions deliberately
  left open, each with what blocks it and a fallback default.
* [docs/reports/2026-09-22-transcript-backed-routes.md](docs/reports/2026-09-22-transcript-backed-routes.md)
  — the transcript layer: what it measures, what it refuses to claim, and the four commands that
  rebuild it (`ops/apply_run_conditions.py` → `ops/flag_quality.py` → `ops/run_contrasts.py` →
  `ops/score_routes.py` → `ops/answer.py`).
* [docs/reports/2026-09-22-transgene-requantification.md](docs/reports/2026-09-22-transgene-requantification.md)
  — the cassette-aware requantification: what was added to the index and from where, the mapping-rate
  control, and the per-strain cassette expression the transcript answer rests on.

## Asking the atlas the question it was built for

```bash
python ops/answer.py --verbose
```

Prints the feasible routes, what fraction of each is actually backed by transcript data, and the
reported yield ceiling — as **three separate columns**, never fused into one score. A route can be
feasible and unevidenced, or evidenced and low-yielding, and collapsing those into a single
ranking would hide which of the three is carrying it.

## The web interface

```bash
python -m pip install -e ".[web]"   # FastAPI + uvicorn, an optional extra
pnpm install && pnpm build          # once, to build the client
just ui                             # http://127.0.0.1:8000
```

Eleven pages over the query layer: Dashboard, Literature, Genomes, Annotations, Data,
Transcripts, Networks, Evidence, Curation, Search, plus the publication / gene / route detail
views. To develop against it, `just api` and `just web` in two terminals gives Vite on `:5173`
with hot reload, proxying `/api` to the API on `:8000`.

**It cannot write.** There is no POST, PUT, PATCH or DELETE anywhere in `fermdb.api`, the
connection is opened `mode=ro` at the SQLite level, and a test asserts both. That is PLAN.md D.3's
layering rule made structural rather than documented: promotion is recorded against a **named
human** in the audit log, and a browser click is not a named human. The Curation page shows what
is queued, the sentence each proposal rests on, and the exact `fermdb curate` command — you run it.

What the interface is built to make visible is the *absence* as much as the content, because
that is where this atlas's honesty lives:

| the page says | rather than |
|---|---|
| 705 papers included and unreadable, remedy: acquisition | a corpus size |
| 0 of 172 runs downloaded — accessions only | "172 RNA-seq runs" |
| 0 of 6,400 routes pass the balance check | a route leaderboard |
| `score_toxicity` never computed — not zero | a five-axis composite score |
| 0 of 105 measurements reach a condition context | a best-titer ranking |
| `mitochondrial_matrix` is read by two genetic codes | a compartment list |

"Not recorded", "not applicable" and "unknown" render as three visually distinct states, and
none of them looks like zero. Every value carries its zone badge (R reported / H harmonized /
I inferred). Those are PLAN.md P.4 requirements, not styling: getting them wrong discards the
value of everything underneath.

To run it against a copy rather than the shared atlas — which is how it should be run against
anything you are not prepared to have open while curating:

```bash
just ui-on /path/to/atlas-copy.sqlite3   # or set FERMDB_DB_FILE
```

## Running it on a second machine

The repository is one of three things this project needs, and the only one `git clone` brings. The
other two are deliberately outside the tree: the derived data under `data_dir` — the atlas, the
stored full texts, the genomes, the quantification matrices — and `env/secrets.local.env`.

Neither has to sit where it sits here. Every key in `env/paths.yaml` is also an environment
variable, `FERMDB_<KEY>` upper-cased, and the one that matters is the root:

```bash
FERMDB_DATA_DIR=E:/fermdb-data python ops/answer.py    # one run
```

To set it once for a machine instead, copy `env/paths.local.yaml.example` to
`env/paths.local.yaml` — gitignored, overrides paths.yaml key by key — and edit `data_dir` there.

One line is enough because the override is applied **before** `${...}` interpolation: moving
`data_dir` moves `db_file`, `matrices_dir`, `quant_dir`, `genomes_dir`, `index_dir` and
`exports_dir` with it, and also the directories the code derives from `data_dir` directly rather
than naming them in paths.yaml — `fulltext/`, `annotations/`, `contrasts/`, `llm-cache/`,
`matrices_mito/`, `matrices_transgene/`. Windows (`E:/x`) and WSL (`/mnt/e/x`) spellings are both
accepted and translated per platform, so the same value serves either.

```bash
python -m fermdb.cli config
```

prints every resolved path with where its value came from — `default`, `file` or `env` — and
whether it exists. Run it first on a new machine, and read the `exists` column, not just the
values. `data_dir` is derived-tier, which is the one tier fermdb creates on its own, and
`open_db` defaults to `create=True`: a mistyped root does not raise, it makes a fresh empty atlas
at the wrong place and keeps going. `config` writes nothing, so it is the safe way to find that
out first.

### Carrying the data across: `ops/transfer.py`

Configuration says *where* the tiers live; this says how to *move* them. One archive holds
`data_dir`, `source_root` if it exists, and optionally `env/secrets.local.env`:

```bash
python ops/transfer.py export --dry-run      # what would be packed, and how big
python ops/transfer.py export                # -> <exports_dir>/transfer/<UTC stamp>/
```

Measured on this machine: **1,816 files, 767 MB**, or 1,864 files and 1.8 GB with
`--include-backups`. The `.bak` snapshots and the secrets file are both excluded by default —
the second because it holds the NCBI key, and an archive carrying it must not be uploaded
anywhere shared. Pass `--include-secrets` deliberately, or copy that one file by hand.

On the other machine, restore against *its* resolved paths — set `FERMDB_DATA_DIR` or
`env/paths.local.yaml` first, and the archive follows:

```bash
python ops/transfer.py import --archive fermdb-transfer-<stamp>.zip           # reports only
python ops/transfer.py import --archive fermdb-transfer-<stamp>.zip --apply   # writes
```

Three properties worth knowing, because they are why this exists rather than `zip -r`:

* **Databases are snapshotted, not copied.** The atlas runs in WAL mode, so a file-level copy can
  leave committed transactions behind in the `-wal` sidecar. Every SQLite file — including the
  `.bak` snapshots, detected by header rather than by extension — goes through
  `sqlite3.Connection.backup` on a `mode=ro` connection, the same mechanism `just rebuild-check`
  uses, and the sidecars are then skipped as redundant.
* **Every member carries its sha256**, written into `MANIFEST.json` at export and re-checked on
  restore. A corrupted transfer is reported as a checksum failure and a non-zero exit, not as an
  atlas that happens to open.
* **Import refuses by default, twice.** Nothing is written without `--apply`, and a file that
  already exists is left alone unless `--overwrite` is also given — so restoring onto a populated
  `data_dir` cannot silently replace a curated atlas with an older one. `env/secrets.local.env` is
  never overwritten at all.

`--into <dir>` redirects the data tier for a one-off restore; the source tier and the secrets file
still go to their resolved locations, and the report prints all three before it does anything.

## The distinction that matters most

Two different things are called "mitochondrial engineering", and conflating them would be the most
expensive modelling error available here:

* **Compartment targeting** — a *nuclear* gene given or stripped of a mitochondrial targeting
  sequence. Routine, and what essentially all published mitochondrial isobutanol work actually is.
  Requires no recoding, because translation still happens on cytosolic ribosomes.
* **Mitochondrial genome engineering** — editing mtDNA itself. Biolistic transformation into a ρ⁰
  recipient, or nuclease-based heteroplasmy shifting. Guide-RNA import remains unsolved, but
  "no CRISPR route" is no longer accurate: a 2020 paper in this corpus demonstrates Cas9/gRNA
  donor-DNA insertion in yeast mitochondria by expressing the machinery from a biolistically
  delivered plasmid that replicates inside the organelle — sidestepping import rather than
  solving it. Its insert was undetectable within ~30–40 generations without selection. **No
  published isobutanol precedent**, which a recorded search confirms.

The schema stores these as distinct modification types with distinct feasibility ratings, so a
route needing true mtDNA editing is never ranked as if it were as easy as adding a presequence.
And because yeast mitochondria translate by NCBI table 3 — `CUN` reads as threonine, not leucine —
`genetic_code_table` is a property of `compartment`, and a sequence filed against the matrix that
carries an unrecoded `CUN` run is rejected.

## Relationship to `genome-db`

A sibling of `D:\project\genome-db` (the *Trichoderma reesei* cellulase atlas), reusing its
conventions where they transfer: no hardcoded paths, curated TSV/YAML in the repository as the
human-curation layer, `evidence` plus `confidence` on every curated row, published data kept
distinct from locally reprocessed data, and fixture-based tests.

Two of the three departures this section used to claim have since been revised by the project's
own decision record, and are corrected here rather than left to mislead:

* **The engine is SQLite, not PostgreSQL.** `OPEN_QUESTIONS.md` Q2 revisits the original
  recommendation and withdraws it: the route-first scope removed four of the five premises the
  Postgres case rested on. The migration trigger is a second concurrent user, a web UI or semantic
  search — any one, and it is a connection string plus dialect work, not a rewrite.
* **The CLI is argparse, not Typer, and there is no FastAPI backend.** Deliberate while the
  dependency footprint has to stay small enough to run on a bare interpreter; `src/fermdb/cli.py`
  states the reasoning and the condition for changing it.

What does still hold: gene identity anchored on ortholog groups rather than one source's primary
id, and experimental context as a first-class structured object rather than columns on a sample.
