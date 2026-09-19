# yeast-alcohol-db

A decision-support system for **engineering *Saccharomyces cerevisiae* to produce isobutanol**:
routes, parts, compartments, engineering records, fermentation phenotypes and literature —
integrated so that every statement traces back to the experiment supporting it, and so that the
answer to "what should I build next" is ranked rather than merely listed.

**Status: planning complete, ready to start. No code, no schema, no data yet.**

Scope is set to **route answers first**: phases 0–4 plus a decision checkpoint, roughly 5.5–6.5
months solo full-time, ending in a ranked evidence-backed route list, an isobutanol omics layer
and a build recommendation. UI, agents and the knowledge graph are deferred —
[PLAN.md](PLAN.md) Q.5 lists each with what it would cost to add. Mitochondrial genome
engineering is a stated research goal, so the mitochondrial genetics corpus is in the critical
path.

Measured volumes: the **entire** isobutanol SRA corpus is **120 runs / 51 GB**, against 13,117
runs for ethanol + *S. cerevisiae* — an 89× asymmetry that is why the ethanol layer is capped.
Retained project size ~4–6 GB; AWS cost for the whole omics campaign under $25.

## Scope, in one table

| tier | product | policy |
|---|---|---|
| **Primary** | isobutanol | Comprehensive, **all host organisms** — yeast, *E. coli*, *C. glutamicum*, *B. subtilis*, cyanobacteria. Most of the pathway biochemistry was established outside yeast and transfers as parts and strategy |
| **Reference** | ethanol | Bounded and **capped**. Admitted only against four criteria: the competing pyruvate sink, the performance ceiling, wild-type baselines, and transferable tolerance mechanisms |
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
  recipient, or nuclease-based heteroplasmy shifting; no routine CRISPR route, because guide RNA
  import is unsolved. No published isobutanol precedent.

The schema stores these as distinct modification types with distinct feasibility ratings, so a
route needing true mtDNA editing is never ranked as if it were as easy as adding a presequence.
And because yeast mitochondria translate by NCBI table 3 — `CUN` reads as threonine, not leucine —
`genetic_code_table` is a property of `compartment`, and a sequence filed against the matrix that
carries an unrecoded `CUN` run is rejected.

## Relationship to `genome-db`

A sibling of `D:\project\genome-db` (the *Trichoderma reesei* cellulase atlas), reusing its
conventions where they transfer: a Typer CLI over a FastAPI backend, no hardcoded paths, curated
TSV/YAML in the repository as the human-curation layer, `evidence` plus `confidence` on every
curated row, published data kept distinct from locally reprocessed data, and fixture-based tests.

It departs in three places, each argued in PLAN.md: one PostgreSQL system of record rather than
SQLite-per-assembly, because this atlas is cross-organism by definition; gene identity anchored on
ortholog groups rather than one source's primary id; and experimental context as a first-class
structured object rather than columns on a sample.
