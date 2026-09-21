# The tier-routing defect: why re-running discovery does not admit the meteno paper, and who else is stuck

**DRAFT, 2026-09-22.** Nothing was written to `data/` and nothing to the database. The only network
activity was read-only: one `--dry-run` discovery pass (esearch counts only, writes nothing by
construction — `discovery.run_family` guards every write behind `if not dry_run:`) and four targeted
PubMed membership queries. No `confidence` value is set, no `verified` bit flipped, no record
admitted. `fermdb extract` was not run.

---

## 1. The answer, first

**`10.1016/j.meteno.2016.01.002` is still not admissible, and re-running discovery will not make it
admissible.** The owner chose the principled fix over an override. The principled fix does not work
on this paper, and the reason is worth more than the paper is.

`validate_admission` still returns `wrong_tier` for it, checked read-only against the live database
today. Its three screening rows are `isobutanol_all`, `isobutanol_production` and `isobutanol_yeast`,
all `product_tier='isobutanol'`, and the schema's CHECK — `admitted_criterion IS NULL OR
product_tier = 'ethanol'` — forbids an ethanol criterion on any of them.

For discovery to give it an ethanol-tier row, one of the six ethanol sub-queries in
`data/literature/query_families.yaml` has to retrieve it. **None of them can.**

---

## 2. Why not — tested against live PubMed rather than reasoned about

The sub-queries are `[tiab]`-scoped: they see the title and the abstract, and nothing else. The
paper's title is *"Excessive by-product formation: A key contributor to low isobutanol yields of
engineered Saccharomyces cerevisiae strains."* Its abstract (PMID 29142820) is about mass balance,
by-product accumulation, 2,3-butanediol, diacetyl, acetoin and a dihydroxyacid-dehydratase
bottleneck.

Four membership tests, each `29142820[uid] AND <the family's own terms>`, run against live PubMed:

| sub-query group tested | result |
|---|---|
| E1: `(PDC1 OR PDC5 OR PDC6 OR "pyruvate decarboxylase")[tiab] AND (deletion OR knockout OR "pdc-negative" OR "C2 auxotroph" OR "glucose-tolerant")[tiab]` | **0 hits** |
| The gene-name group alone, without the second clause | **0 hits** |
| `ethanol[tiab] OR ADH3 OR POS5 OR "NADH kinase" OR "mitochondrial NADPH" OR "mitochondrial redox" OR "redox shuttle" OR "mitochondrial alcohol dehydrogenase"` — the gate on E2, E3, E4, E5 and the `ethanol_mitochondria_yeast` family | **0 hits** |
| `industrial OR bioethanol OR "Ethanol Red" OR "PE-2" OR JAY270 OR "CAT-1"` — the gate on E6 | **0 hits** |

**The word "ethanol" does not appear in this paper's title or abstract at all.** E2, E3, E4 and the
`ethanol_mitochondria_yeast` family all require `ethanol[tiab]`, so all four are excluded at the
first clause. E5's distinctive gene terms are absent. E6's industrial-strain terms are absent — the
abstract says "reported by industry", and `industrial[tiab]` does not match "industry" because
PubMed does not stem a `[tiab]`-tagged term. E1 fails on both of its content clauses.

Its E1 relevance is entirely in the full text: `pdc1` ×25, `MTH1` ×27, the strain table listing
IMZ500 / IMI302 / IMX708 / IME305–308 as `pdc1::loxP pdc5::loxP pdc6::loxP MTH1ΔT`, and the
`E. coli ilvC6E6` NADH-dependent acetohydroxyacid reductoisomerase the caller's brief correctly
identifies as the NADH-preferring KARI. **All of that is below the abstract line, where no `[tiab]`
query can reach it.**

### And the re-run would return the identical set

`fermdb literature discover --family ethanol_scerevisiae_prod_ferm_tol --dry-run` was run as the
cheap check the brief suggested:

```
ethanol_scerevisiae_prod_ferm_tol [dry-run: esearch only, nothing written]
  hit_count=1586 (expected_count=1586) retrieved=0
```

**Zero drift against the 2026-09-20 baseline.** The corpus has not moved, so a full re-run would
retrieve the same 1,586 records discovery already holds, write 1,586 upserts that change nothing,
add a `search_run` row, and leave the meteno paper exactly where it is. It is not merely unhelpful;
it is provably a no-op for admissibility.

---

## 3. The second defect, which is the more general one

While testing the same question on the other stuck papers, a separate failure turned up that is
not about this paper's abstract at all.

`10.1186/s13068-015-0374-0` (PMID 26628917, Milne 2015) is the *other* Delft Pdc-minus paper, and
its abstract reads, verbatim: *"each 2-oxo acid decarboxylase was overexpressed in a
'decarboxylase-negative' (pdc1Δ pdc5Δ pdc6Δ aro10Δ) S. cerevisiae background."* It says the
genotype in the abstract. It is still not retrieved:

| query | result |
|---|---|
| `26628917[uid] AND (PDC1 OR PDC5 OR PDC6 OR "pyruvate decarboxylase")[tiab]` | **0 hits** |
| `26628917[uid] AND (decarboxylase[tiab] AND ethanol[tiab])` | **1 hit** — the paper |

The paper is indexed on `decarboxylase[tiab]` and on `ethanol[tiab]`. It is not indexed on
`PDC1[tiab]`, because the token in the abstract is **`pdc1Δ`**, not `PDC1`, and the delta binds
into the token.

**The E1 sub-query's gene terms are blind to the exact genotype notation the entire Pdc-minus
literature uses.** `pdc1Δ pdc5Δ pdc6Δ` is how Delft, Gevo and Butamax all write it. The query asks
for `PDC1[tiab]`, which matches prose ("the PDC1 gene") and misses genotypes. That is a defect in
`query_families.yaml`, not in discovery, and it is invisible to every existing check because
`fermdb literature status` compares hit counts against `expected_count` and the count is stable —
the query has been consistently missing the same papers since 2026-09-20.

**Neither file is editable from this task** (`data/` is write-forbidden here and `src/` belongs to
another agent), so this is reported rather than fixed. Section 6 states the fix.

---

## 4. How many other papers are stuck the same way

### The bound

| | |
|---|---|
| publications with screening rows in **both** tiers (fine — admissible) | 103 |
| publications with **ethanol-tier rows only** (fine — admissible) | 1,748 |
| publications with **isobutanol-tier rows only** | **3,313** |
| — of those, with stored full text, so testable | **761** |
| — of those, ≥1 ethanol criterion's terms present anywhere in the full text | 247 |
| — of those, carrying **substantive** ethanol-criterion content | **28** |
| — of those, surviving a read as a genuine ethanol record | **6** (+1 borderline) |

The 2,552 isobutanol-only publications with no stored full text cannot be content-tested at all, so
**28 is a floor, not a total.** The true number is unknowable without reading papers nobody can
read — which is the same acquisition wall E1 is already behind.

The "substantive" test is deliberately stricter than the loose boolean: E1 requires a `pdc1Δ`/`pdc1::`
genotype token plus ≥3 Pdc mentions (or ≥5 Pdc mentions with a deletion word); E5 requires ≥3
ADH3/POS5/NAD-kinase/shuttle/matrix-NAD(P)H hits; E3 requires a named background plus a chemostat or
carbon-balance regime; E6 requires a named industrial strain. E4 was excluded from the test on
purpose — an isobutanol paper that also measures ethanol tolerance is the ordinary dual case and
B.3.4 already admits it from the isobutanol side.

### The 6 that survive reading

**Five are E1, and all five are Pdc-minus experiments in *S. cerevisiae*:**

| stuck score | DOI | what it is |
|---|---|---|
| **219** | `10.1186/s13068-015-0374-0` | **THE WORST-AFFECTED — worse than the paper the brief named.** Milne 2015. Aro10 / KivD / KdcA compared in a `pdc1Δ pdc5Δ pdc6Δ aro10Δ` "decarboxylase-negative" background, with kinetics in cell extracts, in vivo conversion rates under oxygen limitation, and growth on valine as sole nitrogen source. 28 genotype tokens, 25 `MTH1` mentions. It is the companion paper to the meteno one, from the same chassis line, and it carries the *enzymology* that the meteno paper's mass balance argues from. |
| 152 | `10.1016/j.meteno.2016.01.002` | The paper the brief named. Same chassis, the mass balance, the NADH-preferring KARI. |
| 39 | `10.1186/1754-6834-6-68` | Uses CEN.PK RWB837 (`pdc1::loxP pdc5::loxP pdc6::loxP`) as a functional test that Pdc catalyses the last step of the butanol/isobutanol route. A Pdc-minus *measurement*, not a mention. |
| 27 | `10.1038/s41467-021-27852-x` | Optogenetic control of `PDC1` and the mitochondrial isobutanol pathway in a triple-PDC-deletion background. This is B.3.1's "Pdc promoter-replacement and dynamic-control strategies" clause, in the flesh. |
| 17 | `10.3389/fbioe.2022.1080024` | Uses strain GG570 (`pdc1Δ pdc5Δ pdc6Δ`) and states the consequence directly: it grows slowly on glucose aerobically and cannot grow on glucose anaerobically. The C2/growth cost, measured. |

**One is E6:**

`10.1186/s13068-021-02059-w` — *"Massive QTL analysis identifies pleiotropic genetic determinants for
stress resistance, aroma formation, and ethanol…"*. It does not stop at mapping: it swaps a `SUC2`
frameshift variant into **Ethanol Red**, CEN.PK and *S. boulardii* and measures end-of-fermentation
ethanol. That is past QTL correlation to allele-level causality by reconstruction — exactly the
argument that lifts `10.1101/gr.131698.111` out of B.3.6's QTL exclusion in PHASE2_STATUS.md §2 —
and it touches Ethanol Red, slot 7's proxy genome, directly.

**One borderline, not counted in the 6:** `10.3389/fmicb.2020.01204`, chemostat adaptation of a
heterogeneous population. Real chemostat data, but not the matched wild-type/parental pair B.3.3
asks for.

### The finding inside the finding

**Re-running discovery would rescue none of the six.** Every one was tested against the ethanol
sub-queries the same way the meteno paper was, and every one returned zero — but they fail at
*four different clauses*, which matters because it means no single edit fixes them all:

* **(a) No E1 gene token in the abstract at all.** The paper is *about* isobutanol and the Pdc-minus
  background is a methods fact, so neither "ethanol" nor any PDC term reaches the abstract.
  — `10.1016/j.meteno.2016.01.002`, `10.1038/s41467-021-27852-x`, `10.3389/fbioe.2022.1080024`.
  *(Verified: none of the three match `PDC1 OR "pyruvate decarboxylase" OR industrial`[tiab].)*
* **(b) Genotype-token blindness.** The abstract *does* state the genotype, and `PDC1[tiab]` cannot
  see `pdc1Δ`. — `10.1186/s13068-015-0374-0`. This is §3.
* **(c) The second clause's vocabulary.** The abstract says "pyruvate decarboxylase" and passes the
  gene clause, then fails on `(deletion OR knockout OR "pdc-negative" OR "C2 auxotroph" OR
  "glucose-tolerant")[tiab]` — it describes the work without using any of those five words.
  — `10.1186/1754-6834-6-68`. *(Verified: matches the gene clause, returns 0 on the second.)*
* **(d) E6's fourth clause.** `10.1186/s13068-021-02059-w` passes E6's organism, industrial-strain
  and genomics clauses — it *does* match `industrial`[tiab] and `QTL`[tiab] — and then fails on
  `(tolerance OR robustness OR "high gravity" OR productivity OR yield)[tiab]`. Its title says
  **"stress resistance"**, and "stress resistance" is not "tolerance". A one-word vocabulary gap at
  the last of four clauses.

So the four-clause AND structure is itself part of the defect: each additional clause is another
place a paper can be lost on a synonym, and nothing reports which clause did it.

**E5 has no routing defect at all.** Four isobutanol-only papers tripped the E5 content test and all
four are false positives on reading — a *Trypanosoma* proteomics paper, a *C. elegans* Ndi1 model, a
fungal ABC transporter, and a paper on the intoxicating degree of liquor. The E5 sub-query's terms
(`ADH3`, `POS5`, `"NADH kinase"`, `"redox shuttle"`) are distinctive enough that anything genuinely
E5 is already in the ethanol tier. **The defect is specific to E1, with one E6 instance.** That is
worth knowing before anyone widens all six queries.

---

## 5. What was **not** run, and exactly what it would have been

Per the brief's instruction to scope it precisely:

```
fermdb literature discover --family ethanol_scerevisiae_prod_ferm_tol
```

**There is no narrower scope available.** The CLI takes `--family` and `--max-records` and nothing
else; `run_family` runs *all* of a family's `sub_queries` unconditionally, so there is no
`--criterion E1`. `--max-records` caps and therefore *truncates*, which would drop papers rather
than target one. Scoping below family level would require editing `query_families.yaml` (under
`data/`, write-forbidden here) or `src/` (another agent's).

So the smallest runnable unit is: 6 esearch calls + paging, ~1,586 esummary records, ~1,586
`screening_record` upserts, 1 new `search_run` row. It took ~43 seconds on 2026-09-20.

**It was not run, for three reasons in descending order of importance:**

1. **It is provably inert.** Four membership tests say the target is unreachable; the dry run says
   the retrieved set has not changed. Running it would produce churn and a misleading audit trail —
   a `search_run` row dated today implying the question was re-asked and answered, when the answer
   was "the query cannot see this paper" both times.
2. **Credentials are not actually wired in.** `env/secrets.local.env` holds `FERMDB_NCBI_API_KEY`
   and `FERMDB_NCBI_EMAIL`, but **nothing in the codebase loads that file** — `grep` finds it only
   in docstrings. `EutilsClient.from_env()` reads `os.environ`, and neither variable is present in
   the process environment. A run started from this shell would go out unauthenticated at 3 req/s
   instead of 10, identifying nobody. That is a small operational problem worth fixing before
   *any* discovery re-run, and it means a run from here would not be the run the owner thinks it is.
3. **It writes ~1,586 rows.** They are safe writes — the upsert in `discovery.py` only refreshes
   triage while `review_state='proposed'`, so the 23 phase-2 admissions (`accepted`) are protected —
   but writing 1,586 rows to achieve nothing is not a trade worth making unattended.

---

## 6. What would actually fix it — the owner's call, not this task's

Three options, in what this pass thinks is descending order of value:

**(a) Widen the E1 sub-query to see genotypes and to reach the isobutanol literature.** The minimal
change is to add the genotype spellings and to relax the second clause, e.g. adding
`"pdc1Δ"[tiab] OR "pdc-minus"[tiab] OR "Pdc-negative"[tiab] OR "decarboxylase-negative"[tiab]` and
`MTH1[tiab]`, and loosening the second clause (which class (c) fails on) rather than only the
first. That is an edit to `data/literature/query_families.yaml` (which would bump `version` and
`expected_count`) plus a re-run. It fixes classes (b) and (c) — `s13068-015-0374-0` and
`1754-6834-6-68` — and is the only option that also fixes papers nobody has noticed yet. Adding
`"stress resistance"[tiab]` to E6's fourth clause fixes class (d). **It does not fix class (a), the
meteno paper included**, whose abstract contains none of those tokens either.

**(b) Accept that a `[tiab]` query cannot route a paper whose relevance is in its methods, and add
a full-text-based re-screening step.** The corpus already holds 1,429 readable publications; the
28 substantive candidates in §4 were found by a regex pass over stored full text taking about three
minutes. A `needs_full_text`→ethanol-tier promotion path driven by stored text, writing
`review_state='proposed'` rows, is a small piece of work and is the only mechanism that can catch
class (a) failures at all. This belongs to whoever owns `src/`.

**(c) The owner override the principled fix was chosen instead of.** For the meteno paper
specifically, (a) and (b) are the only alternatives, and (b) does not exist yet. If E1 needs this
record before (b) is built, an override is the remaining route — and it should be recorded as an
override, with this document as the reason it was necessary.

**Whatever is chosen, the reporting gap should be closed too.** The brief's own observation is the
sharpest thing in this document: *a paper that is both isobutanol-tier and ethanol-relevant, with
screening rows in one tier only, is unadmittable and nothing reports it.* There is no check, no CLI
subcommand and no test that would have surfaced any of this. `fermdb literature status` reports hit
counts against `expected_count` and those counts are stable, which is precisely why a systematically
blind query looks healthy.

---

## 7. Two smaller corrections found on the way

* **PHASE2_STATUS.md §4** reports E1 as 68 tagged / 16 readable. Live counts are **69 / 17**; the
  queue total of 52 is unchanged and the arithmetic still closes. Its queue breakdown (25 + 14 + 11)
  sums to 50, not 52 — the two missing rows are `why_unavailable='fetch_failed'`, a fourth category
  the summary omitted. See `docs/drafts/acquisition/E1_ACQUISITION_WORKLIST.md` §1.
* **PHASE2_STATUS.md §3b** says `10.1016/j.mec.2024.e00245` was *"Not on the slot-6 shortlist."* It
  was not among the three candidates, but it *was* in `slot6_E5_redox_shuttle.yaml`, under
  `not_shortlisted_but_notable`, with a stated and factually correct reason. See
  `slot6_E5_redox_shuttle_rerun.yaml`.
