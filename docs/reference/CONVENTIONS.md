# Conventions

Decided once, binding on every module. If code disagrees with this file, the code is wrong.

This is a **draft**: nothing is implemented yet, so every rule here is still cheap to change.
Once phase 0 lands, changes to this file require a migration plan. Rules marked **[carried]** are
taken from `D:\project\genome-db\docs\reference\CONVENTIONS.md`, where they were arrived at by
experience; the reasoning there is worth reading before overturning one.

## Data zones

Every table, file and API response belongs to exactly one zone, and carries it.

| zone | meaning | mutable | may support a conclusion |
|---|---|---|---|
| **R** — reported | exactly as the source stated it | append-only revisions | yes |
| **H** — harmonized | derived from R by recorded code | freely; it is rebuilt | yes |
| **I** — inferred | statistical, model or LLM output | freely; it is regenerated | **no**, until promoted by a curator |

Zone H must be reconstructible from Zone R by running recorded code. If it cannot be, it is
misfiled and belongs in R.

## Missing values

Three distinct states, never collapsed. **[carried]**

| state | meaning | storage |
|---|---|---|
| `NULL` | the source never recorded it | SQL NULL |
| `'NA'` | recorded as not applicable | the literal string |
| `'unknown'` | recorded, but could not be resolved to a controlled value | the literal string |

`unknown` records are excluded from analyses rather than defaulted. Never coerce any of the three
into another, and never into zero. The UI renders "not recorded", "not applicable" and "unknown"
differently.

## Identifiers

* Internal ids are CURIEs in the project namespace: `YAA:<TYPE>:<slug>` — for example
  `YAA:STRAIN:cen-pk113-7d`, `YAA:GG:ygr192c`. Slugs are lowercase, hyphenated, and stable.
* External identifiers use registered prefixes resolvable through Bioregistry (`sgd:`, `uniprot:`,
  `chebi:`, `rhea:`, `taxonomy:`, `doi:`, `pmid:`, `insdc.sra:`).
* **A public identifier never changes meaning.** If an entity turns out to be two entities, the
  old id is retired with pointers to both; it is never silently re-pointed.
* **Every other identifier is an alias**, stored with its `source`, `evidence` and `confidence`.
  **[carried]**
* An identifier that cannot be resolved is recorded as `UNRESOLVED:<as-written>`, never mapped to
  the nearest plausible match. **[carried]**

### Genetic code and compartment

* **The genetic code follows the encoding genome, not the destination compartment.** A nuclear
  gene is translated on cytosolic ribosomes under table 1 no matter where its product ends up, so
  a presequence-targeted matrix construct needs **no recoding**. Only genes physically carried on
  mtDNA use table 3.
* The mitochondrial matrix and inner membrane hold proteins from **both** genomes. Asking "what
  code does the matrix use" is a malformed question, and the API raises rather than answering it.
* Compartment plus `encoding_genome` determines the code. `encoding_genome` is required wherever
  the compartment alone is ambiguous.

### Gene identity

* The join key for everything cross-strain and cross-study is `gene_group`, never a raw gene id.
* The anchor namespace for yeast is the *S. cerevisiae* S288C systematic name (`YGR192C`).
* A gene id is meaningless without its assembly. Never join on a gene id, a chromosome name or a
  contig name alone. **[carried]**
* Cross-species relationships are `ortholog_link` rows with method and score — a claim, not an
  identity. They are never merged into a gene group.

## Units and quantities

* **The declared unit is the only authority.** A quantity's scale is never inferred from its
  numbers. Every matrix, column and measurement declares its unit, and every operation refuses
  input whose unit it cannot accept. **[carried]**
* `value_as_reported` and `unit_as_reported` are Zone R and are **never** overwritten or converted
  in place. Conversions write `value_si` alongside, with the conversion rule recorded.
* Rates and fractions are stored as fractions in `[0, 1]` with a CHECK constraint, never as
  percentages. The UI formats percentages. **[carried]**
* `basis` is mandatory on any yield (`consumed` | `supplied` | `theoretical_max_pct` |
  `per_biomass` | `per_volume`). **Where the source does not state it, `basis` is `'unknown'`, not
  NULL**, and the value is not usable for cross-study comparison. *(Amended 2026-09-19: this
  section previously said NULL, contradicting the "Missing values" rule above. A curator who read
  the paper and found no basis has learned something; NULL would claim nobody looked.)*
* A numeric column that can be "recorded but unresolved" carries a companion
  `<col>_state` in (`recorded`, `not_applicable`, `unknown`), with the number NULL unless the
  state is `recorded`. A bare nullable REAL cannot express the three states the rule above
  requires.
* Ethanol `% v/v` ↔ `g/L` conversion uses a stated ethanol density and is recorded as a derivation,
  not applied silently.
* A value read from a figure is marked `digitized` and is a distinct evidence grade from a
  tabulated one.

## Coordinates and sequence **[carried]**

* 0-based half-open `[start, end)` in the database, the API and all internal code. 1-based
  inclusive only in the UI and in exported files, converted at exactly two places: parsers in,
  formatters out.
* Length is always `end - start`. Never `end - start + 1`.
* Strand is `+1` forward, `-1` reverse, `0` unknown. Never `"+"`/`"-"` outside a parser or
  formatter.
* Exons and CDS segments are stored in ascending genomic order regardless of strand.
* Variants are matched across references by interval overlap with a repeat-length tolerance,
  **never** by exact lifted position.

## Evidence

* Every assertion carries an evidence level L1–L5, and the level is **derived** from evidence type
  and support by the stated rule in PLAN.md J.3. It is a view, not a stored column.
* An override requires a reason and a curator, and is displayed as an override.
* Each `evidence_type` has required fields enforced by CHECK constraints. In particular,
  `ai_inference` may not carry a `measurement_id`.
* Conflicts are recorded in both directions and are never silently resolved. **[carried]**
* Null and negative results are stored with the same status as positive ones.

## Conditions

* `condition_context` is immutable and deduplicated by `context_hash` over its recorded facets.
* Every facet has an `as_reported` shadow field.
* No sample enters a contrast, and no measurement enters an aggregate, without an approved
  condition context.
* Every cross-study comparison names its comparability class **and that class's version**.

## Thresholds

* QC thresholds are fixed in one module **before** the data they gate is seen, and are reviewed as
  a diff. **[carried]**
* Changing a threshold requires re-running what it gated.

## Pipelines and provenance

* Every computed row names a `processing_run`, which records pipeline version, container digest,
  tool versions, parameter hash, input content hashes and seed.
* Every pipeline is idempotent on a declared key and resumable through a per-unit marker file.
* Check the *producer's* exit status, not only the consumer's success: a truncated input that
  still parses is the failure mode that matters. **[carried]**

## Paths and configuration **[carried]**

* No path is written in source code. Every directory, database and binary location is a key with a
  default, resolvable and reportable by a `config` command.
* Every key is also an environment variable.
* Three tiers: **repo** (committed, curated, small), **derived** (rebuildable), **source**
  (read-only, never written to). Only the derived tier is auto-created.
* The database and working set live on a native Linux filesystem, not a mounted Windows drive.

## Curation

* A curated fact arrives as a row in a commented TSV or YAML file in the repo tier, is reviewed as
  a diff, and is loaded by a CLI command that validates every identifier before writing.
* Every curated row carries `evidence` (free text naming the source) and `confidence`.
* `confidence` is a closed set: `unverified` | `low` | `medium` | `high`. **`unverified` means
  asserted but never checked against a source** — a real and common state, distinct from `low`,
  which means checked and weak.
* **Never write high confidence from memory.** A value recalled rather than checked is
  `unverified`, and must say so. **[carried]**
* **Citing a file in this repository is not evidence** when that file was itself written from
  background knowledge — it is citing memory with an extra hop. Cite the external, checkable
  source, or write `unverified`.
* Comments explaining *why a row is absent* are part of the data and are preserved. **[carried]**

## API

* REST under `/api`, JSON, `snake_case` matching the database columns. **[carried]**
* Every response carrying a fact also carries its `zone` and, where applicable, its `level`.
* Nothing that can exceed a few seconds is synchronous; long work returns a job id and streams
  progress. **[carried]**
* Results trimmed for size say what was cut. A silent truncation causes a consumer to report a
  count that is really a limit. **[carried]**

## Code

* Python: `ruff` (line length 100) and `mypy`. No bare `except`. Public functions carry types.
* TypeScript: strict mode.
* Every parser, query and derivation rule adds a case to the fixture atlas.
* No `if product == 'ethanol'`. Product-specific behaviour lives in data.
