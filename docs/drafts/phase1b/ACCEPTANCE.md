# Phase 1b acceptance, clause by clause

2026-09-22. Measured against the live database at `meta.schema_version = 12`: **4
`pathway_configuration` rows, 97 `measurement` rows, 10 `product_theoretical_yield` rows, 0
`condition_context` rows, 0 `modification_localization_change` rows.**

PLAN.md's phase 1b acceptance is five clauses, shared with phase 1:

> the landmark *E. coli* and *S. cerevisiae* builds each reproduce their paper's titer, yield and
> conditions; every configuration passes the 0.411 g/g bound check or is flagged; every
> localization claim carries a verification method or `none_reported`; **the activator map covers
> every mtDNA locus that could host an insert, with its leader and what inserting there
> displaces**; the precedents table for soluble heterologous enzymes from mtDNA is complete,
> however thin it turns out to be.

| # | clause | verdict |
|---|---|---|
| 1 | landmark builds reproduce titer, yield and conditions | **FAIL** — neither paper is extracted; and "conditions" is unstorable for *any* paper |
| 2 | every configuration passes the 0.411 g/g bound check or is flagged | **CANNOT BE EVALUATED** — the check now runs; 0 of 4 configurations are evaluable |
| 3 | every localization claim carries a verification method or `none_reported` | **FAIL, vacuously** — the column exists, nothing writes to it, and 5 stored localization claims carry no method |
| 4 | the activator map covers every mtDNA locus | **PASS** |
| 5 | the heterologous-ORF precedents table is complete | **PASS** |

**2 of 5 before this round, 2 of 5 after.** Nothing here moved a clause from fail to pass, and
that is the finding: clause 2 turned out to be unrunnable rather than failing, and knowing which
of those it is changes what to do next.

---

## Clause 2 — the 0.411 g/g bound check

### Was it wired?

**It was wired on the way in, and nowhere else.** One ceiling check existed before today:
`fermdb.llm.validate._check_yield`, reached through `validate_records`, which is called from
exactly one place — `fermdb.extract.harness`. It gates a record a model has just proposed. It
reads `data/vocabularies/theoretical_yields.tsv`, not the `product_theoretical_yield` table.
Nothing re-ran it over the rows that got through, and **nothing ran it against
`pathway_configuration` at all**, because a configuration is not a measurement-shaped record and
`validate_records` never sees one.

So it is not quite "recorded and never wired up" — it is *wired to the wrong side of the door*.
Phase 1b's clause is about stored configurations; the extraction gate cannot satisfy it.

### What was wired this round

`src/fermdb/metabolic/bound_check.py` (new, with `tests/test_bound_check.py`, 23 tests). It reads
the ceilings from `product_theoretical_yield`, evaluates every row of `measurement`, and rolls the
verdicts up to every `pathway_configuration` via `host_strain_id`. Run it with
`python -m fermdb.metabolic.bound_check`.

It **reports** rather than writes. S.3's action vocabulary is `flag` / `block_aggregation` /
`reject`, and the schema has nowhere to put any of them: there is no `qc_flag` table and no flag
column on `measurement`. Persisting a verdict needs a migration, which is not this round's.

### What it found

```
measurements: 97
  pass            2
  flag            0
  not_evaluable  95
  refused         0

pathway_configuration rows: 4
  pass            0
  flag            0
  not_evaluable   4
  refused         0
```

**0 configurations pass, 0 are flagged, 4 cannot be evaluated.** Not one of the four host strains
carries a yield measurement — they carry titers. A configuration with no yield neither passes the
bound nor violates it, and reporting 4/4 pass would be reporting the absence of data as a result.

The two passes are the corpus's only two yields:

* `YAA:MEAS:ab2a9e7b553b112c` — 0.016 g/g consumed, isobutanol, `doi:10.1186/1475-2859-12-119`.
  **3.9% of the 0.411 ceiling.** Substrate recovered as glucose from the originating curation
  task's payload, not from a column.
* `YAA:MEAS:c1c14f3cb90afb2d` — 0.0369 as a fraction of theoretical maximum,
  `doi:10.1016/j.btre.2026.e00959`. Within [0, 1]; `basis='theoretical_max_pct'` carries its own
  ceiling of 1 and needs no substrate.

The other 95 are not yields. 60 are titers; 35 are fold-changes, percent-changes, tolerance
readouts and one LC50.

**No violation exists in this corpus.** Given the 2026-09-22 re-derivation — 1 glucose → 1
isobutanol gives 74.12/180.16 = 0.41142 g/g, and 5 xylose → 6 isobutanol gives
6×74.12/(5×150.13) = 0.41142 g/g, agreeing to five figures — a flag would have been a real finding
about a paper. There is nothing to find yet, because there is almost nothing to check.

### A number the check confirmed from outside

Atsumi 2008 states the ceiling itself: *"The theoretical maximum yield of isobutanol is 0.41 g
g⁻¹"* (Fig. 2 legend). The `product_theoretical_yield` row for (isobutanol, glucose) currently
carries `confidence='unverified'` with the evidence *"cited only to PLAN.md, an internal document,
not to an external pathway reference checked in this session"*. **That external reference exists,
in the landmark paper itself, and is quotable at a verified offset** (see LANDMARK_BUILDS.md §1).
Raising that row's confidence is a curation act and is not done here.

### What clause 2 needs

**Three things, in this order.**

1. **A substrate column, or `condition_context` rows.** The ceiling is keyed on
   `(product_id, substrate)` and `measurement` has no substrate column. `condition_context` —
   where `carbon_source_main` lives — has **0 rows**, and not one of the 97 measurements points
   at an `experiment` or a `sample`; all 97 hang off a strain alone. `curate.promote` already
   names this as a holding position: the substrate *"travels in `evidence`, which is prose and
   queryable only by LIKE, and is therefore a holding position and not a home"* — and only its
   higher-alcohol writer does even that. **3 of 97 measurements carry a substrate in `evidence`.**
   The bound-check module works around it by also reading the originating `curation_task`
   payload (97 of 97 name their task; 19 of those carry a substrate), and that is string
   archaeology, not a schema. A measurement whose substrate neither route recovers is reported
   `not_evaluable`, never assumed onto glucose — **an assumed substrate is an invented ceiling**.
2. **Yields, at all.** 2 yields in 97 measurements, neither on a configuration's host strain.
   Clause 2 is a statement about configurations and the corpus has no configuration-linked yield.
3. **Somewhere to put a flag.** Without it, "is flagged" cannot be satisfied even by a
   configuration that violates the bound: the verdict exists only in a report.

### Two live holes worth naming separately

* **`unit='unknown'` is a silent bypass.** A yield stored with a unit that is not a mass ratio has
  nothing to compare to a g/g ceiling and is reported `not_evaluable`. Two of the three yield
  records this corpus has proposed were promoted or proposed with `unit='unknown'` — including
  `12.45 mg isobutanol/g glucose`, which is 0.01245 g/g and perfectly checkable once converted.
  The `mg/g` spelling is what does it. The *S. cerevisiae* landmark's headline yield
  (6.4 mg per g glucose) has exactly this shape, so promoting it carelessly puts the landmark
  outside the check the clause is about.
* **No xylose ceiling is recorded.** All ten `product_theoretical_yield` rows are
  `substrate='glucose'`. The 2026-09-22 derivation shows the isobutanol figure is the same
  0.41142 g/g from xylose, and the corpus already holds xylose measurements (6 curation payloads
  name xylose, 3 more name glucose/xylose mixtures). Until a xylose row exists, every xylose yield
  is correctly reported *unchecked* — which is right, and is also a gap in `data/`, not in code.

---

## Clause 3 — a verification method on every localization claim

### Does anywhere exist to store one?

**Yes, and it is unreachable.**

`modification_localization_change.verification_method` exists, is `NOT NULL DEFAULT
'none_reported'`, and is `CHECK`-constrained to `microscopy | fractionation | protease_protection
| activity_in_fraction | none_reported`. The schema comment states the reasoning exactly:

> A claimed relocalization with no localization evidence is common and consequential: the
> construct may simply not be imported, and every conclusion resting on it is then unsupported.
> A blank here would read as "fine".

The column is correct. **The table has 0 rows**, and the only code that has ever written to it is
`src/fermdb/db/fixture.py` — the test fixture. No promoter writes it: `curate/promote.py` maps
`'localization_change'` to a `modification` row and stops there, putting the compartment and the
targeting sequence into that row's free-text `details`. The extraction schema
(`extract/schemas.py`) has `localization_as_reported`, a free-text string, and **no
verification-method field at all**, so the model is never asked the question.

### The localization claims that are actually stored

**Five, none carrying a method.**

* **4 `pathway_configuration.description` strings**, each asserting a localization in prose:
  * `YAA:PCFG:fbe93c86372bc5bb` — "in their native locations (mitochondria and cytosol)"
  * `YAA:PCFG:6e7102e064ead4e7` — "or targeted exclusively to the mitochondria"
  * `YAA:PCFG:5f5ffbe5f654332e` — "Using the N-terminal mitochondrial localization signal from
    subunit IV of the yeast cytochrome c oxidase (Cox4)"
  * `YAA:PCFG:13a7bd4eac19633f` — "localized to mitochondria"
* **1 `modification` row of type `'localization_change'`** — `YAA:MOD:549819c3e9e779f7`, a Su9
  presequence targeting the mitochondrial matrix, from `doi:10.1016/j.meteno.2016.03.004`. It has
  **no `modification_localization_change` subtype row**, so the `NOT NULL DEFAULT 'none_reported'`
  never applies to it: the column that would carry the default is on a row that does not exist.

Note what the third of those says — *"Using the N-terminal mitochondrial localization signal from
subunit IV of the yeast cytochrome c oxidase"*. That is a targeting **method**, not a
verification. The distinction is the whole clause: how you aimed the protein is not evidence it
arrived.

### The schema gap, reported rather than migrated

Two gaps, one real and one arguable.

1. **`pathway_configuration` has no verification-method column, and its localization claim is
   prose.** Every configuration in this corpus makes a localization claim and none of them can
   carry a method. This is the gap that blocks the clause, because the clause's subject —
   configurations — is the table without the column. A fix would either add
   `localization_verification_method` to `pathway_configuration` or require a
   `modification_localization_change` row per configuration. **Not migrating**; DB is at v12 with
   other agents live.
2. **Nothing promotes into `modification_localization_change`, and nothing extracts the field.**
   This is fixable without a migration — it is a promoter and an extraction-schema change, both in
   packages owned by other agents this round.

### What clause 3 needs

* a verification-method field on the extraction schema, so the model is asked;
* a promoter that writes `modification_localization_change` when it writes a
  `'localization_change'` modification (the one existing such modification is orphaned today);
* a decision about where a *configuration's* localization claim carries its method;
* then a re-promotion of the five existing claims, four of which will honestly read
  `none_reported`.

**The test case is already in hand.** Avalos 2013 verifies its localization three ways —
subcellular fractionation with anti-PGK/anti-porin markers, GFP microscopy against MitoFluor Red,
and per-fraction enzyme quantification — and `verification_method` already accepts three of those
names. Promoting that paper is what would take clause 3 from vacuously-failing to actually
testable.

---

## Clause 1 — the landmark builds

### Which papers the clause means

PLAN.md phase 1 names *"the landmark E. coli and S. cerevisiae builds"* and does not name the
papers. The 2026-09-21 handover names **Atsumi 2008** and **Avalos 2013**. Both are in
`publication`, both have stored full text, and both are readable:

| | DOI | stored | extracted |
|---|---|---|---|
| *E. coli* | `doi:10.1038/nature06450` | PDF, checksum `bd4300b9...`, `oa_status='closed'` | **no** |
| *S. cerevisiae* | `doi:10.1038/nbt.2509` | PDF, checksum `38b38302...`, `oa_status='green'` | **no** |

`extraction` holds 11 rows across 8 publications; neither DOI is among them. `span` holds 267 rows
across the same 8. **Zero rows in the corpus derive from either landmark paper.**

### What each reports

Read out of the stored text, with every quote re-resolved at an exact offset. The full draft —
configurations, measurements, conditions and the traps — is in
**`docs/drafts/phase1b/LANDMARK_BUILDS.md`**. Headlines:

* **Atsumi 2008**, host JCL260 (JCL16 Δadh Δldh Δfrd Δfnr Δpta ΔpflB), *alsS*/*ilvC*/*ilvD* +
  *kivd*/*ADH2*: **~300 mM (22 g/L) at 112 h**, **0.35 g isobutanol per g glucose** over 40–112 h,
  **86% of theoretical**, in M9 + 36 g/L glucose + 5 g/L yeast extract, micro-aerobic, 30 °C,
  0.1 mM IPTG. It also states the ceiling: *"The theoretical maximum yield of isobutanol is
  0.41 g g⁻¹"*.
* **Avalos 2013**, strain JAy161, Ehrlich enzymes targeted to the matrix with the CoxIV
  presequence: **635 ± 23 mg/L** isobutanol in complete medium, **6.4 ± 0.2 mg per g glucose**,
  **20.5 ± 1.2 mg l⁻¹ h⁻¹**, 24-h high-cell-density fermentation, minimal medium 1× YNB with 20%
  glucose or SC−ura, semiaerobic, 30 °C, 350 r.p.m.; co-reported isopentanol 95 ± 12 mg/L and
  2-methyl-1-butanol 118 ± 28 mg/L.

### Why the clause fails, and what it needs

Three separate blockers, and only the first is an extraction job.

1. **Neither paper is extracted.** `fermdb extract` on both DOIs, then curation of the proposed
   records. Not run here: extraction is another agent's this round.
2. **A configuration's enzyme set is not fully in the stored text.** JAy161's specific α-KDC and
   ADH are in Avalos's **Supplementary Table 2**, which is not in the stored asset — only the
   candidate sets are in the main text. A configuration that names an enzyme set JAy161 may not
   have is worse than one that records it unresolved. The supplementary file needs acquiring.
3. **"Conditions" cannot be reproduced by any row the schema currently offers.**
   `condition_context` has 0 rows and no measurement points at an `experiment`. Medium, carbon
   source and loading, aeration, vessel, temperature, agitation, inducer, time — every facet both
   papers report has nowhere to go but `evidence` prose. **This blocker is not specific to the
   landmarks: no paper in the corpus has its conditions stored.** Clause 1 as written cannot be
   fully satisfied by extraction alone, however good the extraction.

A fourth, smaller one: both papers' yields are reported without stating consumed-versus-supplied,
so the `basis` for each will honestly be `'unknown'` unless the supplementary data settles it —
and an `'unknown'` basis is, by this project's own rule, not comparable across studies. The
landmark would reproduce the paper's number without reproducing a *comparable* number.

---

## Clauses 4 and 5 — unchanged

**Clause 4 passes.** `data/mitochondria/activator_map.yaml` covers all eight protein-coding loci
plus the intergenic site, each with its leader, its activator and what inserting there displaces;
`mtdna_locus` holds 9 rows and `loci_without_activator` returns empty.

**Clause 5 passes.** `data/mitochondria/heterologous_orf_precedents.yaml` is complete for soluble
heterologous enzymes from mtDNA, and is thin — which the clause explicitly allows. The
2026-09-21 corpus report records what it is thin *about*: **no paper has ever followed a
heterologous mtDNA ORF over generations**, so retention is unmeasured for every precedent in it.

---

## The one-line answer

Clause 4 and clause 5 pass. Clause 2's check now exists and runs, and its first honest output is
that **0 of 4 configurations can be evaluated** because the corpus has no configuration-linked
yield and `measurement` has no substrate column. Clause 3's column exists and nothing has ever
written to it. Clause 1 needs two extractions, one supplementary file, and a place to put
conditions.

**Phase 1b remains at 2 of 5, and the reason is curation volume and two schema gaps — not a broken
check.**
