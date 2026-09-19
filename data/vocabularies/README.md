# Controlled vocabularies

This directory is what makes "product-specific behaviour lives in data, never in code"
(`docs/reference/CONVENTIONS.md`, "Code") actually true. Every place the rest of fermdb would
otherwise need a hardcoded list — which products exist and at what tier, which compartments
translate by which genetic code table, what an evidence type requires, what a modification type
means, what a tolerance assay type measures, what units convert to what, what an assertion's
predicate can be, what fields make up a `condition_context` — is a row in one of these files
instead. Code reads these tables; it does not branch on the values in them
(`if product == 'ethanol': ...` is exactly what this directory exists to prevent).

## Files

| file | vocabulary | PLAN.md sections |
|---|---|---|
| `products.tsv` | product identity and tier (theoretical yields live in `theoretical_yields.tsv`) | B.1, C.4 |
| `theoretical_yields.tsv` | theoretical mass/molar fermentation yield, keyed by (product, substrate) | C.4; D5 |
| `compartments.tsv` | subcellular compartment -> encoding genome(s) -> NCBI genetic code table | B.6 point 3; `src/fermdb/genetic_code.py`; D1 |
| `evidence_types.tsv` | Axis 1 of the evidence model (kind of observation) and its required/forbidden fields | J.1, J.3 |
| `modification_types.tsv` | `modification.type` enum for the engineering atlas | I.4 |
| `assay_types.tsv` | tolerance `assay_type` enum — **tolerance is not one phenotype** | I.3 |
| `units.tsv` | unit definitions, density-based conversions, and yield `basis` values | C.4, C.6; `docs/reference/CONVENTIONS.md` "Units and quantities" |
| `predicates.tsv` | closed `assertion.predicate` vocabulary | J.1, J.2 |
| `condition_facets.tsv` | every field of `condition_context`, one row per field, plus where it is stored (first-class column vs. `condition_context_facet` overflow row) | C.5 |

## Conventions every file here follows

* **Zone.** These are curated, repo-tier reference tables (`docs/reference/CONVENTIONS.md`,
  "Curation": "a curated fact arrives as a row in a commented TSV ... in the repo tier, is
  reviewed as a diff"). Identity fields (names, ChEBI ids, formulas, enum values quoted from
  PLAN.md) are Zone R — recorded as the cited source stated them. A few numeric fields (the two
  theoretical mass yields, and the density-based unit conversions) are *computed* from stated
  inputs by a recorded rule, which is Zone H in spirit — reconstructible from the recorded MWs and
  stoichiometry by re-running the arithmetic in each row's `evidence` column. None of this
  directory is Zone I: nothing here is a statistical, model or LLM inference offered as a fact.
* **NULL vs `'NA'` vs `'unknown'` are three different states and this directory uses all three on
  purpose** (`docs/reference/CONVENTIONS.md`, "Missing values"):
  * an empty field is NULL — nothing was recorded for it (used sparingly here, since most columns
    in a hand-curated vocabulary table are filled by construction);
  * the literal string `NA` means the field does not apply to that row's kind (e.g. `from_unit`
    for a `basis` row in `units.tsv`, or `factor` for a `unit`-kind row in the same file);
  * the literal string `unknown` means a value was sought but not resolved with confidence (e.g.
    the theoretical yields left `unknown` in `products.tsv`, or the `OD600 -> g/L` factor in
    `units.tsv`, which cannot have a universal factor at all).
  Never coerce one into another, and never into zero or a guess.
* **`evidence` and `confidence` on every row, no exceptions**
  (`docs/reference/CONVENTIONS.md`, "Curation"). `tests/test_vocabularies.py` asserts this
  mechanically. `confidence` is a **closed vocabulary of exactly four values** — `unverified`,
  `low`, `medium`, `high` — everywhere in this directory (D2). `unverified` means *asserted but
  never checked against a source*: a real and common state, distinct from `low` (checked, but the
  check was weak). Confidence is never `high` from memory alone, and — following the compartments
  rewrite below — never `high` when the evidence names only another fermdb file (`PLAN.md`,
  `docs/reference/CONVENTIONS.md`, a source module, or another vocabulary TSV) rather than
  something actually checked outside the repo: citing an internal document for a factual claim is
  citing memory with an extra hop, and is marked `unverified`. Where a value was checked against a
  live source in this session (mainly: ChEBI identifiers and a few pure-substance densities, via
  web search on 2026-09-19), `evidence` names that source and `confidence` is `high` — but a search
  result is still not a primary reference a curator has read end to end, so treat `high` here as
  "checked against a database entry", not as "confirmed by a curator against the literature."
  Content recalled from general knowledge that is *not* dressed up as a file citation (e.g. a
  plain-language gloss the curator states as their own judgement) is capped at `medium`, per the
  older convention this replaces only for the specific case of an internal-citation-as-evidence.
* **A parser must NOT use pandas' default NA-sniffing on these files.** `pandas.read_csv`/
  `read_table` with its default settings treats the literal string `NA` (among others) as missing
  and silently turns it into `NaN`, which would collapse this project's `NA` state into the same
  representation as NULL — precisely the coercion `docs/reference/CONVENTIONS.md` forbids. Read
  these files with Python's `csv` module (as `tests/test_vocabularies.py` does), or with pandas
  using `keep_default_na=False, na_values=[]` and your own explicit NULL/`NA`/`unknown` handling
  downstream.
* **Header format.** Every file opens with a `#`-commented block explaining its purpose and
  columns (matching the convention carried from `genome-db`'s curated TSVs), followed by one
  tab-separated header row, then data rows. Comment lines are not part of the tabular data and
  must be skipped by any loader (skip lines starting with `#` before parsing as TSV).
* **No path is hardcoded.** These files are located by callers relative to the repository/package
  root, not by an absolute path baked into code (`docs/reference/CONVENTIONS.md`, "Paths and
  configuration"). `tests/test_vocabularies.py` resolves this directory from `__file__` for the
  same reason — there is no project-wide path-configuration module yet for it to use instead.

## Known gaps left for a curator (recorded, not silently filled)

* `predicates.tsv`: no Biolink Model or Relation Ontology mapping is recorded yet for any
  predicate. PLAN.md J.2 calls for one; this curator does not have a checked mapping and left both
  columns NULL rather than guess a CURIE (a wrong external identifier is worse than a missing one —
  see `docs/reference/CONVENTIONS.md` "Identifiers").
* `evidence_types.tsv`: no ECO (Evidence and Conclusion Ontology) code is recorded yet, for the
  same reason.
* `theoretical_yields.tsv` (formerly the yield columns of `products.tsv`): the yield is
  deliberately left `state='unknown'` (numeric fields NULL) for isoamyl alcohol,
  2-methyl-1-butanol, 1-propanol, succinate and itaconate, because their pathway/redox closure is
  not settled (PLAN.md C.4: "the stoichiometry depends on the assumed pathway and the assumed
  redox/ATP closure"). Ethanol and isobutanol's stoichiometric equations are given by PLAN.md B.2
  but are marked `unverified` (D2 evidence honesty: the equation is cited only to an internal
  document, not an external pathway reference checked in this session) even though their molar
  masses are ChEBI-verified; n-butanol, 2,3-butanediol and lactate's yields are this curator's own
  derivation from standard biochemistry and are marked accordingly.
* `compartments.tsv` (rewritten for D1): every row is `unverified`. The compartment -> encoding
  genome mapping now agrees with `src/fermdb/genetic_code.py::COMPARTMENT_ENCODING_GENOMES`, and
  the evidence names NCBI's Genetic Codes page, but nobody has actually re-checked each row against
  that page in this session — a curator should, especially for `mitochondrial_ims`, which a prior
  version of this file got wrong (it claimed table 3 at `high` confidence).
* `condition_facets.tsv`: `scale_class` and `growth_phase` are named by PLAN.md C.5 without a
  stated value set; this file does not invent one. The `storage_location` column (first-class
  `condition_context` column vs. `condition_context_facet` overflow row) is derived from
  `src/fermdb/db/schema.sql`'s actual column list, not from PLAN.md, and is cross-checked by
  `tests/test_vocabularies.py`.
* `units.tsv`: the isobutanol density used for the `%v/v <-> g/L` conversion does not carry a
  confirmed reference temperature.
