# yeast-alcohol-db

A decision-support system for **engineering *Saccharomyces cerevisiae* to produce isobutanol**:
routes, parts, compartments, engineering records, fermentation phenotypes and literature —
integrated so that every statement traces back to the experiment supporting it, and so that the
answer to "what should I build next" is ranked rather than merely listed.

**Status (2026-09-21): the machinery is built and the atlas is nearly empty of curated content.**
Schema v9, 64 tables, 990 tests passing. 5,164 publications resolved and 1,310 full texts stored;
600 routes enumerated against six gates; the mitochondrial activator map and heterologous-ORF
precedents curated. But `measurement`, `strain`, `modification` and `pathway_configuration` all
read **zero**, and 95 extraction proposals are queued for a curator who has not started. That is
not a surprise — PLAN.md W.2 predicted it in writing: *"curation throughput, not compute, is the
rate limit."* It is now the observed state.

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
and the admission test is explicit: *an ethanol record is admitted only if it answers a question
the isobutanol program asks.*

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
