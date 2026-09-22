# The transcript layer, wired end to end — and the three claims it cost me to get there

**2026-09-22.** The atlas can now answer *"what pathway engineering is feasible, backed by
transcript data, for high isobutanol yield?"* — as a command, from evidence, with the answer
partitioned so that no layer's strength covers another layer's absence.

**The headline, after a requantification against the deposited cassette: the engineered steps
are not transcriptionally limited.** All four pathway constructs run 13-17 log2 above the parent,
and the heterologous alcohol dehydrogenase `adhA` sits at ~11,600 TPM in every producer against
0.5 in every parent run. Whatever limits isobutanol yield in these strains, it is not that the
pathway genes are failing to be transcribed.

That answer took three refuted claims and one rebuilt reference to reach, and the route there is
the more useful half of this report.

---

## 1. What was missing, and what now exists

`omics.baseline` recorded the blocker precisely: PLAN.md F.3 requires an approved
`condition_context` before any contrast, none was curated, and grouping 99 runs by anything else
"would invent exactly the metadata F.3 says this corpus lacks". That refusal was right. What was
missing was the other half — once contexts exist, something has to compute the contrast, and
nothing did.

| new | what it does |
|---|---|
| `curate/context_writer.py` | The writer `curate.contexts` deliberately lacks. Refuses an unnamed approver, reuses an existing hash instead of re-inserting, and refuses a document whose contexts collide once genuinely-dropped facets are removed |
| `omics/run_conditions.py` | Reads declared SRA `SAMPLE_ATTRIBUTES` into strains, genotypes and contexts. Parses a declared construct into a per-gene compartment map, against the atlas's own curated reaction compartments rather than a hardcoded table |
| `omics/contrasts.py` | Differential expression: median-of-ratios normalisation, Welch t on log2, BH FDR, technical-replicate pooling, and a within-group cohesion check |
| `metabolic/transcript_support.py` | Maps routes to builds and steps to evidence; writes `pathway_route.score_evidence` |
| `query/answer.py` | Assembles the answer, with feasible / transcript-backed / high-yield kept as three separate columns |
| `omics/quality.py` | Detectors that raise a recorded doubt about a row and never repair one; `refusals` honours them automatically (section 6) |
| `db` schema **v15** | `data_quality_flag` — the doubt as a queryable row, with its detector, statistic and threshold |
| `ops/apply_run_conditions.py`, `ops/flag_quality.py`, `ops/run_contrasts.py`, `ops/score_routes.py`, `ops/answer.py` | The five commands that run it |
| `tests/test_contrasts.py`, `tests/test_quality.py` | 23 tests. Suite: **1,466 passing**, ruff, format and mypy clean |

## 2. What was measured

* **87 of 172 samples** now carry an approved `condition_context` and a declared strain, up from
  **0**. `condition_context` went 0 → 9, `condition_context_facet` 0 → 20.
* **36 differential-expression contrasts** stored as `analysis_result` rows with a
  `processing_run` recipe each, up from **0**. Fifty were computable; fourteen are withheld
  because they draw on one of four quarantined samples (section 6).
* **SRP342112 requantified against the deposited cassette** (GenBank MZ541859.1), 33/33 runs, on
  a self-terminating EC2 instance for **$0.96**. Mapping rate moved **+4.11 points in the
  cassette-bearing runs and +0.00 in the parent** — the cleanest possible confirmation that the
  recovered reads are cassette reads.
* **SRP342112 is the study that makes this possible**: parent Y795 plus three producers, each a
  different compartment/cofactor design, three timepoints, n≈3. Y797 mitochondrial, Y799
  cytosolic with an *E. coli* NADH-preferring KARI, Y812 cytosolic with the native NADPH KARI.
  The paper is Gambacorta *et al.* 2022, `10.1016/j.synbio.2022.02.007` (PMID 35387233,
  GEO GSE186126), and the cassette is deposited as **GenBank MZ541859.1**.
* **136 isobutanol yields from 47 papers**, every one carrying a machine-verified verbatim quote,
  against the **2** the atlas previously held.

## 3. The three claims the review destroyed, and why that is the valuable part

A first pass produced three findings. An adversarial review reproduced every number from the
matrix and then broke two of them outright. Both are recorded here because the failure mode is
general.

**"ILV3 is overexpressed 30-fold in every producer" — refuted.** Every cassette ORF is
codon-optimized, but the synthetic *ILV3* retains a **44 nt exact match** to the native
transcript, long enough to seed a `k=31` salmon index. The modelled leak is ~12% of cassette
reads landing on the native `YJR016C` row — which is the entire apparent signal. The rank order
of retained-substring length across *ILV3* (44 nt), *ILV2* (32), *ILV5* (29), *ARO10* (17)
reproduces the rank order of observed "expression" exactly. **A native gene's row is not a
measurement of that gene when the build carries its own copy and the reference does not.**

This is now enforced rather than remembered: `_status` returns `confounded_by_construct` for any
step whose gene the matched build also carries on its cassette, unless the reference includes the
constructs. Wiring that guard in dropped the best route's evidence score from **1.00 to 0.20** and
removed every `elevated` verdict in the atlas. The ranking got worse, and it got right.

**"The outlier run is why the 26 h contrasts find nothing" — refuted.** Re-running with the
suspect sample removed, and even with a perfect relabelling, still returns **0 genes**. The cause
is the test: a per-gene Welch t at n≤3 with no dispersion sharing, BH-corrected over ~5,800 genes.
The published analysis of the same data recovers hundreds of DE genes using edgeR. `contrasts.py`
now emits an explicit note that a null result at this replication is **uninformative rather than
negative**, so it can never be recorded as evidence of no effect.

**"SRR16481343 is mislabelled" — confirmed, and understated.** It correlates 0.752 with its
declared group against 0.949–0.987 for every other run, and matches Y812 @ 10 h at 0.974 —
replicate-grade. The reviewer went further: **the entire 26 h block appears label-shifted by one
position**, corroborated independently by within-group dispersion dropping for *both* groups under
relabelling. This is quarantine-worthy, not delete-worthy, and section 6 is what was done about it.

A fourth correction was mine, caught before it shipped: routes were grouped by step signature
*without* `encoding_genome`, so **strategy E inherited the evidence of a nuclear presequence
fusion** — precisely the conflation the README calls "the most expensive modelling error available
here". With encoding in the signature, all 1,280 E routes correctly score **0.00**.

## 4. The answer, as it stands

```
$ python ops/answer.py --verbose
```

* **Feasibility and evidence disagree, and the answer says so.** `A_native_split` is the most
  feasible (1.00) and the least evidenced (0.00) — nobody has built it. `B_cytosolic` and
  `C_mitochondrial` both reach evidence **1.00** on 48 routes, because every catalytic step of
  both is now measured on a cassette row that shares reads with nothing.
* **The engineered steps are expressed, hugely.** In Y812: ILV2 +13.15, ILV5 +15.18, ILV3 +15.22,
  ARO10 +16.00 log2 over the parent, all at FDR < 0.05. `adhA` is among the most abundant
  transcripts in every producer; `ilvC` reads **1,426 TPM in Y799 and exactly 0.0 in all 24 other
  runs** — perfect genotype correlation across 33 samples, which is also the cleanest label check
  in the corpus.
* **The mitochondrial build shows the same fold changes and cannot resolve them.** Y797's four
  constructs sit +12.66 to +16.97 log2 above the parent and no contrast clears FDR 0.05, because
  quarantining its mislabelled T14 run leaves too few. Those steps are reported
  `elevated_not_resolved` — underpowered, explicitly **not** a finding of no effect.
* **Strategy E scores 0.00 on evidence and 0.10 on feasibility.** No mtDNA-encoded build exists,
  so nothing about it has been measured.
* **The yield answer is a host answer, not a route answer.** Best credible *S. cerevisiae* yield
  in the corpus: **0.0596 g/g**, 14.5% of the 0.411 g/g ceiling (JWY23, `10.1186/s13068-019-1486-8`).
  Best anywhere: **0.411 g/g** in *E. coli*. A **6.9× gap**, and no enumerated route closes it.
  One outlier claim of 0.156 g/g in yeast (`10.1093/femsyr/foae006`) is flagged doubtful and
  excluded — its own introduction contradicts it. **Please check its Table 1 before anyone
  promotes it**, because it is the only thing standing between the atlas and a clean statement
  that yeast tops out near 0.06 g/g.

## 5. What a person still has to do

**The live atlas is written.** Schema is at **v15**; backups kept at each step
(`fermdb.sqlite3.pre-transcript-layer.*.bak`, `.pre-v15.*.bak`, `.pre-conditions.*.bak`,
`.pre-contrasts.*.bak`, `.pre-evidence.*.bak`, `.pre-flags.*.bak`). The pipeline rebuilds with:

```bash
python ops/apply_run_conditions.py --apply --curator <you> --actor human
python ops/flag_quality.py --apply --curator <you>
python ops/run_contrasts.py --apply
python ops/score_routes.py --apply
python ops/answer.py --verbose
```

Contexts were written with `--actor agent`, so every one of them is labelled as agent-written in
its `evidence` and in a `curation_event` — findable and revocable with one query.
`curation_event`'s CHECK still forbids an agent recording an accept, edit or promote, and that was
not worked around.

Then, in priority order:

1. **The requantification against MZ541859.1 is the single highest-value next step** and is
   already running. Until it lands, two of five catalytic steps per route are uninterpretable and
   the other three are invisible. It converts `confounded_by_construct` and `not_measurable` into
   real measurements, and it is the difference between an evidence score of 0.20 and a real one.
2. **Share dispersion across genes in `contrasts.py`.** At n≤3 the current test cannot see what
   the published analysis of the same data sees. Everything else is built; this is the statistic.
3. **Answer the two quarantine flags** (section 6). They are recorded and enforced; what is
   outstanding is a person confirming or clearing them, and an email to the submitting authors.
4. **Review the 136 harvested yields.** They are quote-verified but unreviewed, and the answer
   labels them as such on every line.

## 6. The mislabelled run, and why the answer is a table rather than a fix

**Recommendation: quarantine, never relabel, and tell the authors.**

The tempting fix is to move `SRR16481343` to whatever it resembles — it matches Y812 @ 10 h at
ρ 0.974, replicate-grade. That fix is circular. It uses the expression data to repair the
metadata and then analyses the expression data under the repaired metadata, so the correction can
never be contradicted by the thing that depends on it. At n=3 the circularity runs in the
direction that manufactures significance: moving one sample out of a group shrinks that group's
variance, which is exactly what every p-value divides by.

Deleting the run is no better — it silently discards a deposit that may be perfectly good data
under a different label, and leaves nothing to re-examine when the authors answer.

So the doubt is now **a row in the database**, schema v15:

```
data_quality_flag(target_type, target_id, kind, severity, detector,
                  statistic, threshold, rationale, resembles, status, ...)
```

`omics.contrasts.refusals` consults it, so a quarantined sample **cannot enter a future contrast
because somebody forgot**. That is the whole reason for storing the doubt rather than writing it
in a report — this report would not have stopped it; the table does. Re-running the contrasts now
refuses 9 of 50 and **prunes the stored results computed before the flag existed**, so a
quarantine cannot leave a stale `analysis_result` behind that nothing downstream distrusts.

The detectors are study-generic, not tuned to this case (`ops/flag_quality.py`):

* **Gate A — replicate coherence.** `margin = best ρ inside the declared cell − best ρ outside
  it`, cut at robust z < −3 against the study's own median and MAD. **Maximum, not mean**: a
  mean-based version accuses the outlier's blameless cell-mates, which it demonstrably did at
  ρ 0.807 and 0.891 before the statistic was changed. Run over all three contextualised studies it
  flags **SRR16481343 (z −42.4)** and **SRR16481349 (z −5.2)** and nothing else — no false
  positives in 87 samples. The identity of the best outside cell classifies the fault: a different
  condition says the *timepoint* label slipped, the same condition and a different strain says the
  *genotype* label did.
* **Gate B — declared-genotype marker consistency.** Catches a whole block shifted by one
  position, which Gate A cannot see because the shifted samples are each other's good partners.
  It **abstains** here on every marker gene — correctly, because all of them are
  `confounded_by_construct` until the augmented reference lands.

What remains a person's call is `status`: a flag stays `active` until somebody `confirms` or
`clears` it, and a re-run never silently reopens a decided one. **The next step is to write to the
submitting authors** — a flag with `resembles` filled in is exactly what that email needs.

## 7. Redundancy is recorded the same way, for every future record

The same table takes `kind = 'technical_replicate'` at severity `warn`: **77 runs across 27
BioSamples** in this corpus are one library sequenced more than once. They are legitimate data and
nothing excludes them — `omics.contrasts` already pools them and counts the *unit* — but the
redundancy is now queryable instead of being rediscovered by whichever analysis next divides by n.
SRP321884 alone deposits 46 runs across 24 BioSamples; an analysis taking 46 as its replicate count
would understate every standard error it computed.

The `kind` vocabulary is deliberately wider than what is in use, so the next class of doubt has a
home rather than a new mechanism: `mislabel_suspected`, `replicate_incoherent`, `redundant_record`,
`technical_replicate`, `value_implausible`, `confounded_measurement`. Anything that is a doubt
*about* a row — a duplicate publication, an implausible yield, a measurement that cannot be
attributed — goes here, and downstream code honours `severity = 'quarantine'` automatically.

## 8. What this still does not establish

Transcript abundance is not flux. No yield in the atlas is linked to any sequenced sample —
`measurement.sample_id` is NULL on every row — so no route's expression profile can be regressed
on its titer. And the transcript evidence is one study in one background: replication across
three timepoints, not across laboratories.

---

# Addendum — the loop closed, and the answer inverted

The four gaps named in section 5 are closed. `ops/load_gambacorta.py`, `omics/evidence.py`,
`omics/contrasts.py`'s moderated test and migration v16 between them turn three separate columns
into one answer with an evidence chain. **1,476 tests, ruff/format/mypy clean, J.5 walks 17
assertions with 0 broken and no unwalkable hops.**

## A1. The answer, now that performance is in the atlas

`doi:10.1016/j.synbio.2022.02.007` reports the four strains that carry every scrap of transcript
evidence this atlas holds. Its numbers, now loaded, are the opposite of the obvious guess:

| strain | design | titer | vs parent |
|---|---|--:|--:|
| **Y797** mIBA^ILV5 | **mitochondrial** | **170 mg/L** (1.8 mg/g glucose) | **4.6×** |
| Y812 cIBA^ILV5 | cytosolic, native NADPH KARI | 46 mg/L | 1.2× |
| Y795 | parent, no pathway | 37 mg/L | — |
| Y799 cIBA^IlvC6E6 | cytosolic, **NADH-balanced** KARI | 31 mg/L | **0.8×** |

**Both cytosolic producers sit at or below the parent, and the redox-balanced one is the worst
strain in the study.** Localization beats cofactor balance 3.8-fold (P<5e-6), and cofactor
balance is *negatively* signed: the NADPH-imbalanced Y812 beats the NADH-balanced Y799 by 1.5×.
Every strain is at <0.2% of theoretical while making 45–47 g/L ethanol at >90% of theoretical.

`ops/answer.py` now prints this beside the ranking and says plainly that its own ordering — by
how much of a route has been *measured* — is not an ordering by how well the route *works*.

## A2. The transcript layer's real verdict: it does not discriminate

All four constructs are expressed 13–17 log2 over parent in **both** topologies, at FDR 1e-8 to
1e-11. The paper reaches the same place from its own data: *"neither the mRNA counts nor the
protein abundance data yielded an explanation for the differences in isobutanol production."*

So the honest answer to *"which pathway engineering is backed by transcript data"* is: **the
transcript data backs the constructs, and refuses to choose between them.** What chooses is
metabolite and genetic evidence — DHIV accumulates 8.6–16× over wild type in the cytosolic
strains and is *depleted* 2.8–4.5× in the mitochondrial one, implicating Ilv3p/DHAD, whose
**2Fe–2S** cluster is assembled across three compartments. Deleting the iron-regulon repressor
*FRA2* raises Y812 2.4× to 190 mg/L and does **nothing** in Y797 — the negative control the
hypothesis predicts.

That is a route-selecting finding, and it is not a transcript finding. An atlas that only knew
how to measure expression would have concluded "all strategies equally supported" and been
useless here.

## A3. The statistics that made it visible

`omics.contrasts` now defaults to an empirical-Bayes moderated t (Smyth's variance prior,
implemented in-module rather than imported). On the same contrasts:

| contrast | n | Welch | moderated |
|---|--:|--:|--:|
| Y797 vs Y795, 10 h | 3v3 | 0 | 245 |
| Y812 vs Y797, 10 h | 3v2 | 0 | 1,502 |
| Y799 vs Y795, 10 h | 3v3 | 791 | 2,357 |
| **Y812 vs Y799, 10 h** | 3v2 | 1 | **6** |

Validated in both directions rather than assumed: the fitted prior is **finite** (df_prior 4.85
against df_residual 4, s0² at the median of observed variances), and **permuting the labels
yields 0–2 "significant" genes with a raw p≤0.05 fraction of 0.007–0.019** — below nominal, so
the test is conservative, not liberal. Both properties are pinned in `tests/test_moderated.py`.

The last row is a finding in itself: the two cytosolic strains differ in **6 genes**. Swapping
the KARI's cofactor preference changes almost nothing transcriptionally while halving the titer.

## A4. Two things the extraction found that need a person

* **A conflict with the paper, unresolvable here.** It states cassette expression follows
  predicted promoter strength, putting *ilvC* above *adhA*; the atlas measures adhA 18,918 vs
  ilvC 1,426 TPM — 13-fold the other way. The paper's own RPKMs are in Table S4, which is not in
  the corpus. Flagged, not settled.
* **A likely defect of ours.** Y799/Y812 carry *ILV3*Δ2-19 while the cassette index row is the
  full-length ORF, so ~1.5–2% residual leak off a 15,600 TPM row plausibly explains the native
  *ILV3* spread (110 / 134 / 384 / 370). The two strains that read flat are exactly the two with
  an exact reference match. **Add a `cassette_ILV3_d2-19` row before anyone records native ILV3
  induction.** Note the cassette-vs-native separation is unaffected — this is a second-order leak
  on top of the 88% one already corrected.

Also corrected against my own brief: the cluster is **2Fe–2S**, not 4Fe–4S; the intervention is
*fra2Δ*, not iron supplementation; and the observed sensing signature is **Yap5p at the protein
level** — Aft1/Aft2 appears only as the target of the intervention, never as an observed regulon.
