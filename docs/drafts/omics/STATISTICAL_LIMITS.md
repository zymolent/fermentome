# The omics corpus's statistical limits

**Status:** draft, 2026-09-22. Written to close PLAN.md phase 4's fifth acceptance clause — *the
corpus's statistical limits are stated in writing … the atlas says so rather than implying
otherwise.*

**Every number below is measured from the corpus**, not taken from a rule of thumb, and is
reproducible with:

```
fermdb omics limits
```

The arithmetic lives in `src/fermdb/omics/limits.py` and is unit-tested against published normal
quantiles and against a sign test whose answer can be worked out by hand
(`tests/test_omics_limits.py`). This document is a snapshot; the command is the measurement.

---

## 0. The headline, in one paragraph

The yeast expression corpus is **99 samples from four SRA studies**, one of which is 46% of it.
Within a study, a well-designed contrast could see a lot — a doubling is detectable at three
samples a side in three of the four studies. Across studies there are four data points, and four
is not enough for anything. **Every one of the four studies agreeing on a gene's direction has
p = 0.125 — not significant even before a multiple-testing correction, and eighteen independent
studies would be needed for unanimity to survive a Bonferroni correction across 6,187 genes.**
The atlas therefore may not report cross-study consistency as evidence, and no `correlative_omics`
evidence item is derivable from this corpus at genome scale today. Separately and independently
of all of the above, **zero contrasts are currently definable at all**, because no sample carries
an approved `condition_context`.

---

## 1. The corpus, counted

| | |
|---|---|
| `sra_run` rows | **172** |
| distinct SRA studies | **15** |
| runs excluded (recorded, with a reason) | 10 |
| runs that reached an expression matrix | **107** |
| approved `condition_context` rows | **0** |
| samples carrying a condition context | **0** |
| `experiment` rows | 15 |
| `experiment` rows naming a publication | **0** |
| `correlative_omics` evidence items | **0** |

Three matrices exist, and they are never concatenated — different reference spaces:

| matrix | genes | samples | independent studies |
|---|---|---|---|
| `s288c` (*S. cerevisiae*) | 6,187 | **99** | **4** |
| `ecoli` (K-12 MG1655) | 4,440 | 4 | **1** |
| `lcremoris` (*L. cremoris*) | 2,325 | 4 | **1** |

The 8 Tn-Seq runs (*Z. mobilis* ZM4) are in none of them and are not expression data at all — see
`TNSEQ_UNIT.md`.

---

## 2. The number that binds is four, not ninety-nine

Sample count is the number that looks like a corpus. Study count is the number every cross-study
claim actually divides by.

| study | samples | share of the matrix |
|---|---|---|
| SRP321884 | 46 | 46% |
| SRP342112 | 33 | 33% |
| SRP156315 | 12 | 12% |
| ERP116462 | 8 | 8% |

Two further facts make four an **upper** bound rather than the true independence count:

* **PLAN.md J.3 counts independence by *group*, not by study**, because one lab publishing three
  times is not three independent observations. This corpus cannot count groups: `experiment`
  carries `publication_id IS NULL` on all fifteen rows, with a stated refusal
  (`src/fermdb/omics/experiments.py`). The lab behind each study is simply not recorded, so the
  effective *k* for J.3 is **unknown and at most 4**.
* **PLAN.md F.6**: a study with no internal contrast contributes nothing to differential-expression
  meta-analysis. Which of the four have an internal contrast cannot be determined until condition
  annotation exists, so the usable *k* may be smaller again.

---

## 3. How the spread was measured, and why there are two numbers

A power calculation needs a residual standard deviation. This corpus cannot supply one properly,
because a residual SD is defined against a design and there is no design here: no sample carries a
condition, so no sample is known to be anybody's replicate. Rather than assume a dispersion, two
**bounds** are measured per study, and every power figure is reported at both ends.

* **`within_study_sd`** — the median across expressed genes of the SD of log2(TPM+1) over *every*
  sample in the study. It contains the study's real condition differences as well as its noise, so
  it is the loosest upper bound.
* **`closest_pair_sd`** — the same statistic computed on the single most similar pair of samples
  in the study (robustly, as a median absolute deviation, so that a minority of genuinely changed
  genes cannot set the noise level), divided by √2 because it describes a difference. This is the
  tightest bound the corpus can offer. If that pair happens to be replicates it is close to the
  truth; if it is not, what it holds is condition signal *on top of* noise, so it still bounds
  from above.

"Expressed" means median TPM ≥ 1 in that study. Genes below it have a variance that describes the
detection floor, and including them would make the corpus look quieter than it is.

| study | n | expressed genes | `within_study_sd` | `closest_pair_sd` | closest pair |
|---|---|---|---|---|---|
| SRP321884 | 46 | 5,900 | 0.596 | **0.056** | SRR14687197 / SRR14687198 |
| SRP342112 | 33 | 5,625 | **0.741** | 0.120 | SRR16481347 / SRR16481349 |
| SRP156315 | 12 | 5,344 | 0.569 | 0.123 | SRR7642959 / SRR7642962 |
| ERP116462 | 8 | 4,735 | 0.648 | 0.430 | ERR3450097 / ERR3450101 |

All values are log2 units. The bracket for the yeast matrix as a whole is therefore
**σ ∈ [0.056, 0.741]**, and ERP116462 is visibly the noisiest study in the set — a fact worth
carrying into any contrast built from it.

---

## 4. Within a study: what a contrast could detect

Minimum detectable log2 fold change at 80% power, two-sided, balanced groups, reported as
**nominal α = 0.05 / Bonferroni α = 0.05 ÷ 6,187 = 8.08 × 10⁻⁶**:

| σ (log2) | n = 3 | n = 4 | n = 6 | n = 8 | n = 12 | n = 23 |
|---|---|---|---|---|---|---|
| 0.056 (tightest, SRP321884) | 0.13 / 0.24 | 0.11 / 0.21 | 0.09 / 0.17 | 0.08 / 0.15 | 0.06 / 0.12 | 0.05 / 0.09 |
| 0.120 (SRP342112, SRP156315) | 0.27 / 0.52 | 0.24 / 0.45 | 0.19 / 0.37 | 0.17 / 0.32 | 0.14 / 0.26 | 0.10 / 0.19 |
| 0.430 (ERP116462) | 0.98 / 1.86 | 0.85 / 1.61 | 0.70 / 1.32 | 0.60 / 1.14 | 0.49 / 0.93 | 0.36 / 0.67 |
| 0.741 (loosest) | 1.70 / 3.21 | 1.47 / 2.78 | 1.20 / 2.27 | 1.04 / 1.97 | 0.85 / 1.60 | 0.61 / 1.16 |

Read as samples needed to detect a **doubling** (log2FC = 1):

| σ | nominal α | genome-wide (Bonferroni) |
|---|---|---|
| 0.056 | 2 | 2 |
| 0.120 | 2 | 2 |
| 0.430 | 3 | **11** |
| 0.741 | **9** | **31** |

**The conclusion is not pessimistic.** Within-study contrasts are this corpus's strength, exactly
as `DATA_VOLUME.md` §4 says. At the tight end of the bracket a 9% change is visible at three
samples a side (log2 0.128 = 1.09×); even at the noisiest measured study a doubling needs only
three samples a side at nominal α. The caveats are
the ordinary ones, stated so they are not forgotten:

* These are **floors on what is detectable**, not achievable targets: σ is treated as known rather
  than estimated from the same tiny sample (a *t*-distribution demands more), and the model is a
  two-sample normal on log scale rather than a negative binomial fitted to counts. A negative
  binomial power model would need per-gene dispersions fitted under a design, and there is no
  design — which is itself the finding.
* `n = 23` is included for SRP321884 only as an arithmetic ceiling — half of 46. No real design
  puts every sample of a study into one two-group contrast.
* **None of these contrasts may be run today.** CONVENTIONS.md "Conditions": no sample enters a
  contrast without an approved condition context, and zero samples carry one.

---

## 5. Across studies: four is not enough, and the number needed is eighteen

PLAN.md F.6 fixes the unit of cross-study integration as **the contrast**, combined by
random-effects meta-analysis or rank aggregation — never a merged expression matrix. That is the
right design, and with *k* = 4 it still cannot support a genome-scale claim.

**Direction concordance (the sign test).** The probability that *k* independent studies all agree
on a gene's direction by chance is 2·(½)^k. This number needs no dispersion estimate and cannot be
argued down:

| independent studies | p for unanimity |
|---|---|
| **4** (this corpus) | **0.125** |
| 5 | 0.0625 |
| **6** | **0.031** — first *k* to clear α = 0.05 for one pre-specified gene |
| … | |
| **18** | **7.6 × 10⁻⁶** — first *k* to clear Bonferroni across 6,187 genes |

So: for **one gene named in advance**, six independent studies would be needed. For a **genome-wide
scan**, eighteen. The corpus has four. Unanimous direction across the entire yeast corpus is, at
genome scale, approximately 774 genes' worth of chance agreement out of 6,187 — not evidence.

**Effect-size meta-analysis.** Pooling *k* estimates shrinks the standard error by √k, which is a
weak lever at these values. Taking a plausible range of per-study standard errors on log2FC:

| per-study SE | k = 2 | k = 3 | **k = 4** | k = 6 |
|---|---|---|---|---|
| 0.20 | 0.40 | 0.32 | **0.28** | 0.23 |
| 0.35 | 0.69 | 0.57 | **0.49** | 0.40 |
| 0.50 | 0.99 | 0.81 | **0.70** | 0.57 |

(minimum detectable pooled log2FC, 80% power, nominal α = 0.05, **fixed-effect**). These are the
optimistic figures. A fixed-effect pool assumes the four studies estimate the same quantity, which
four unrelated deposits in four unstated backgrounds do not.

**Random effects are worse, and the reason is structural.** A random-effects model needs τ², the
between-study variance. With *k* = 4 the heterogeneity statistic *Q* has **3 degrees of freedom**;
τ² estimated from three degrees of freedom is so unstable that the model either collapses to the
fixed-effect answer (τ̂² = 0, overstating precision) or inflates the interval to uselessness. There
is no *k* in this corpus at which a random-effects meta-analysis is informative.

**And L3 needs three independent studies with concordant association** (PLAN.md J.3). Four studies
can in principle reach that bar for a *single pre-specified* gene. They cannot reach it for a gene
discovered by scanning all 6,187 — that is the multiple-testing burden above, and the distinction
between "tested" and "found" is the one this section exists to protect.

---

## 6. The bacterial matrices: meta-analysis is not underpowered, it is impossible

Both bacterial matrices are **one study of four samples**. With *k* = 1 there is nothing to
combine: `sign_test_p(1) = 1.0`. Cross-study integration is not weak here, it is undefined, and
the *E. coli* and *L. cremoris* results can only ever be within-study statements.

Four samples also means at best two per group, and at that size the measured bracket is wide
enough to be worth stating explicitly (minimum detectable change, n = 2 per group, nominal α):

| matrix | σ bracket | detectable at n = 2 |
|---|---|---|
| `ecoli` (3,383 expressed genes) | 0.094 – 0.363 | 1.2× – 2.0× |
| `lcremoris` (1,643 expressed genes) | 0.342 – 2.875 | 1.9× – **266×** |

The *L. cremoris* loose bound is not a typo. `within_study_sd` = 2.875 log2 units over four
samples means that if those four samples really do span four different conditions, nothing short
of a two-hundred-fold change is detectable between two of them. Which of the two ends of that
bracket applies depends entirely on condition annotation that does not exist.

These reach yeast questions only through `ortholog_link` — a claim carrying a method and a score
(PLAN.md C.3) — never as a merge.

---

## 7. What the atlas may and may not say

| claim | permitted? |
|---|---|
| "In SRP321884, gene X is Y-fold higher in condition A than B" | **Yes**, once a condition context is approved for those samples, with the effect size and its interval |
| "Gene X responds to isobutanol in yeast" | **No** — one study is one study, and the condition is not annotated |
| "Gene X is consistently up across the corpus" | **No.** Four studies. p ≥ 0.125 for unanimity, before correction |
| "No consistent response was found" | **No** — absence of a detectable signal at k = 4 is not absence of a signal, and this document is the reason |
| An L3 assertion from a genome-wide scan of this corpus | **No.** L3 needs ≥ 3 concordant independent studies; a gene found by scanning 6,187 needs 18 |
| An L3 assertion for one gene named in advance, from 3 concordant studies | **Possible in principle**, if the gene was pre-specified and the contrasts are real — and the pre-specification must be recorded before the scan, not after |
| Any contrast at all, today | **No.** Zero approved condition contexts |

The last row is a separate constraint from everything above it and will be lifted first; lifting it
does not change §5.

---

## 8. What would change these numbers

In order of how much power each buys:

1. **More independent studies.** This is the only lever on §5, and it is steep: k = 4 → 6 makes
   unanimity significant for a pre-specified gene; k = 4 → 18 makes it significant genome-wide.
   `DATA_VOLUME.md` §2 says the isobutanol SRA query is close to exhausted, so additional studies
   have to come paper → BioProject → runs.
2. **Condition annotation** (PLAN.md F.3). Buys the first contrast, hence everything in §4. It
   changes nothing in §5.
3. **Harvesting `elink(bioproject → pubmed)`.** Would let independence be counted by *group*
   rather than by study, which is what J.3 actually asks for. It cannot raise *k*; it can only
   reveal that *k* is smaller than four.
4. **Pre-specifying the genes.** The gap between six studies and eighteen is entirely the
   multiple-testing burden. A pre-registered panel — the DUET gene set already resolved by
   `fermdb.omics.genes` is 36 genes — moves the bar from 18 independent studies to **11**
   (smallest *k* with 2^(1-k) ≤ 0.05/36). Still above four, but it is the cheapest real gain
   available and it costs only the discipline of naming the genes before the scan rather than
   after.

---

## 9. What this document does not model

Stated so that its silence is not read as reassurance.

* **Batch and lab effects.** In a corpus of four studies, study identity is very nearly aliased
  with any biological factor of interest. No power calculation addresses a confounded design; §5's
  numbers assume the four studies estimate the same thing, which is the assumption most likely to
  be false.
* **Count-level modelling.** Low-count genes have a mean-variance relationship a log-scale normal
  does not capture; for those genes the figures in §4 are optimistic.
* **Paired and time-course designs**, which are more efficient than the two-group model used here
  and would improve §4 (not §5) once conditions are annotated.
* **The 65 runs that never reached a matrix** (172 − 107), including the 8 Tn-Seq screens, the 31
  AMPLICON runs and the 10 recorded exclusions. Their absence is documented elsewhere and is not a
  power question.
