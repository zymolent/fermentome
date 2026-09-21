# The Tn-Seq screens: what unit they belong in, and why they are not in one yet

**Status:** draft, 2026-09-22. Supports PLAN.md phase 4 clause 4 — *every Tn-Seq screen is
represented as perturbation evidence rather than folded in with expression.*

**Verdict: the clause has two halves. The first holds and is now checked. The second does not hold
and cannot be closed without a schema decision, which is the project owner's to make.**

Reproduce with `fermdb omics tnseq`. The code is `src/fermdb/omics/tnseq.py`; the invariants are
in `tests/test_omics_tnseq.py`.

---

## 1. What is actually there

One screen, eight runs:

| | |
|---|---|
| SRA study | **SRP588897** (BioProject PRJNA1270032) |
| runs | **8** — SRR33767555–61, SRR33767563 |
| organism | ***Zymomonas mobilis* subsp. *mobilis* ZM4 = ATCC 31821** |
| reference | GCF_000007105.1, `strain_matched` |
| total | ~1.0 × 10¹⁰ bases, ~3.7 GB |
| in any expression matrix | **no** |
| in `data/omics/quant_plan.json` | **no** |
| `evidence_item` rows | **0** |

**They are bacterial, not yeast.** `DATA_VOLUME.md` §2 records this as a correction to earlier
work, which read "10 Tn-Seq runs" beside a yeast-dominated organism tally and drew the wrong
conclusion. Interpreting them needs the *Z. mobilis* genome and annotation, which the atlas now
has. Anything they say reaches a yeast question only through `ortholog_link` — a claim with a
method and a score (PLAN.md C.3), never a merge.

**Eight, not the ten `DATA_VOLUME.md` §2 reports.** The committed runinfo export
(`data/omics/sra_isobutanol_runinfo.csv`) contains **eight** Tn-Seq rows and the atlas holds eight.
The export is also a **third** count of the corpus: 172 runs, against §2's fetch A (120) and fetch
B (~148). Its *Z. mobilis* total is 14 (8 Tn-Seq + 6 `OTHER`), against §2's 12 for fetch A and 11
for fetch B.

None of this is reconcilable after the fact, and §2 already says why: SRA text search drifts
between fetches, so the corpus size is not a constant in that document and every count is pinned to
a retrieval. The same rule applies here. **Eight is what this atlas holds, from the export it
holds.** Whether SRA has more is a re-fetch question, and re-fetching would produce a fourth number
that would have to be stored beside the others rather than replacing them.

**Six runs are in neither layer.** SRP591874 (PRJNA1276497) holds six *Z. mobilis* runs whose
library strategy SRA records as `OTHER`, at ~3 GB each. They are not prioritised as screens and
not quantified as expression. `OTHER` hides both; which this is, is a curation question and is
reported rather than guessed.

---

## 2. Half the clause holds: not folded in with expression

No Tn-Seq run is in the quant plan and none is a matrix column. But until now this was true **by
accident** — `references.select_reference` sends a *Z. mobilis* run to its own genome, and nobody
built a *Z. mobilis* expression matrix, so no screen could have got into one. An accident is not a
guarantee.

It is now a stated invariant. `ScreenReport.folded_into_expression` names any Tn-Seq run that has
reached the quant plan *or* a matrix header (both, because a run can be in one without the other),
and a test asserts it is empty against the real corpus. A second test proves the check fires, by
putting a screen run into a fixture quant plan and a fixture matrix and asserting both are named —
without that, "none folded in" would only ever mean "nobody looked".

**A defect found and fixed on the way.** `src/fermdb/omics/load.py` wrote `priority_rank = 0` for
every run it loaded. `sra.priority_rank_for` puts Tn-Seq at rank 1 and RNA-Seq at 50 — the one
mechanism in the codebase that marks a screen as different from an expression run, cited in
`DATA_VOLUME.md` §2, in `dataset_families.yaml`, in the schema comment beside the column, and unit
tested the whole time. It never reached the database: all 172 rows carry 0, so `ORDER BY
priority_rank` returns the corpus in accession order and nothing says otherwise. The loader now
calls the rule, and `tests/test_omics_load.py` pins a screen sorting ahead of an expression run
*after a load*. **The existing rows are still 0** — correcting them is a reload, which this work
did not run.

---

## 3. The other half does not hold: there is no unit for a screen

### 3.1 What the right unit is

A Tn-Seq fitness screen is a **genome-wide** result. One transposon library, one selection, and a
fitness statistic for every gene the library has insertions in — for *Z. mobilis* ZM4, on the order
of 1,800 genes from one deposit (unverified: the gene count is background knowledge, not read from
GCF_000007105.1's annotation in this work).

It is therefore **not one claim**, and an `assertion` is one claim: one subject, one predicate, one
direction. "SRP588897 screened *Z. mobilis* under isobutanol" is not an assertion about biology; it
is a description of an experiment, and the atlas already has a place for that (`dataset`,
`experiment`, `processing_run`).

The unit that is one claim is **one gene in one screen**:

> gene *g*, disrupted, in library *L*, under selection *s* against control *c*, has fitness
> statistic *w* with adjusted p-value *q*.

That is a perturbation — the gene was broken and a phenotype measured — which is exactly why
PLAN.md grades a screen L1/L2 rather than L3, and why `DATA_VOLUME.md` §4 calls these runs
"potentially the highest-value rows in the set". So the shape wanted is:

* one `processing_run` per screen analysis, plus one `analysis_result` pointing at the fitness
  table on disk (never a table of 1,800 rows of numbers in the database — `analysis_result` says
  so itself);
* one `assertion` + one `evidence_item` per gene the screen makes a call about, above a stated
  threshold, with the threshold recorded.

### 3.2 Why the schema cannot carry it

Three evidence types come close and each is wrong for a different reason. The near-misses matter,
because each would be an easy thing to write and each would make the atlas say something false.

| type | required fields | why it fails |
|---|---|---|
| `direct_perturbation` | `strain_id`, (`control_strain_id` \| `control_condition_id`), `measurement_id`, `direction` | **Right type, impossible fields.** A pooled library is one population, not one `strain` row per disrupted gene; a fitness score is a statistic over read counts, not a `measurement` anybody took of a `sample`. Satisfying the CHECK means inventing ~1,800 strain rows and ~1,800 measurement rows that would be indistinguishable downstream from ones a curator read out of a paper |
| `correlative_omics` | `contrast_id` \| `analysis_result_id`, `effect_size`, `p_adjusted` | **Fits perfectly, and is the differential-expression slot.** Using it *is* the folding-in this clause forbids, and it caps the screen at L3 — turning the corpus's only perturbation data into correlation by a choice of column |
| `comparative_genomic` | `variant_or_gene_set`, `strain_set`, `statistic` | Fits nearly as well, and means an association observed across strains **nobody perturbed**. A screen is not an association |

The `evidence_item` CHECK is `ELSE 0`, so an unlisted type is unstorable — deliberately, so that
adding a type forces a decision about what it must carry. That is the constraint working as
designed, and it is why this is reported rather than forced.

`tests/test_omics_tnseq.py` demonstrates the first row against the real CHECK rather than arguing
it: an `evidence_item` of type `direct_perturbation` carrying a fitness statistic and no strain or
measurement is refused by the database.

### 3.3 The decision that would close it

Two options, both edits to `src/fermdb/db/schema.sql` plus a migration, both outside this work's
file ownership and both the project owner's call:

**A. A new `evidence_type`: `pooled_perturbation_screen`.** Required fields:
`analysis_result_id` (the fitness table), `variant_or_gene_set` (the disrupted gene), the selection
and control `condition_context_id`s, `statistic` (fitness), `p_adjusted`, and `direction`. It must
be admitted alongside `direct_perturbation` in the `assertion_level` view's `n_direct` and
`n_direct_groups` counts, or a screen will be graded L5 while carrying L1-grade evidence. It must
**not** be allowed a `measurement_id`, for the same reason `ai_inference` is not: a screen
statistic is not a measurement.

**B. Widen `direct_perturbation`** to accept a disruption plus a screen statistic where it now
demands a strain plus a measurement. Fewer moving parts, but it weakens the constraint that
currently guarantees every `direct_perturbation` row names a real strain and a real measurement —
the guarantee that makes L1 mean something.

**A is the recommendation.** It adds a type rather than loosening the one constraint the evidence
layer's credibility rests on, and PLAN.md J.3's own design principle — "adding a type forces a
decision about what it must carry" — is an argument for adding types rather than widening them.

### 3.4 What else is needed before any of it is worth writing

A schema change alone does not produce evidence. The screen also needs:

1. **The fitness table itself.** The atlas holds the raw runs staged in S3; nobody has run a
   Tn-Seq analysis over them. There is no per-gene fitness statistic anywhere in this project.
   Producing one is a processing step (`bowtie` → insertion counts → per-gene fitness), not a
   representation step, and it is not covered by the existing salmon pipeline.
2. **The selection and control conditions**, as approved `condition_context` rows — the same
   blocker as everything else in phase 4. A fitness screen without its challenge condition is a
   number with no claim attached.
3. **A curated threshold**, fixed before the data is seen (CONVENTIONS.md "Thresholds"), deciding
   which genes the screen makes a call about. Without one, "one evidence item per gene" means 1,800
   evidence items per screen, most of them noise.
4. ***Z. mobilis* gene groups**, so a fitness call attaches to something an ortholog link can
   reach. `gene_group` currently holds 36 rows, all yeast.

---

## 4. Summary for the acceptance record

| | |
|---|---|
| Screens in the corpus | 1 (SRP588897, 8 runs, *Z. mobilis* ZM4) |
| Folded in with expression | **No** — now a tested invariant rather than an accident |
| Represented as perturbation evidence | **No** — 0 evidence items, and no `evidence_type` can carry a screen |
| Blocking | A schema decision (§3.3), then a fitness analysis, conditions, a threshold and bacterial gene groups (§3.4) |
| Fixed here | `load.py` now writes the real `priority_rank`, so a screen sorts first after a reload |
