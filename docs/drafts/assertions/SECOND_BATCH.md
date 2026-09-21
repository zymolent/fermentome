# The second batch — 17 drafted, 15 ready, and one correction that matters more than any of them

**Status: proposal. Nothing here has been written.** The live atlas held `assertion` = 6 and
`evidence_item` = 7 before this document and held exactly that after. `~/fermdb-data/fermdb.sqlite3`
was opened `mode=ro` throughout. `build_assertion` and `attach_evidence` ran only inside a
`:memory:` database taken with `sqlite3.Connection.backup`. No `fermdb extract` was run, and nothing
under `data/` was touched.

This batch keeps the two rules the first two documents set — **it does not choose a level**, and it
**puts no number in `effect_size`** — and adds the third rule `L2_BATCH.md` introduced: it does not
accept the route it was given without checking it.

**It was given a route, and the route is wrong in sign.** §1.

---

## 1. The correction: Boles is not a third group on BAT1, it is a *contradicting* group

The task named the JWY05 / JWY06 / JWY07 titers as the highest-value curation in the atlas, on the
reasoning that "a third group on an existing assertion is worth more than a new L1". That reasoning
is right. The premise under it is not. `L2_BATCH.md` §7 item 4 wrote the same thing and it should
be struck.

Two facts, both from the stored full text of `doi:10.1186/s13068-019-1486-8`.

**Fact one: there is no titer to curate.** `[17550, 17687)`:

> Since it was necessary to inoculate the pre-cultures in SCD media without valine, Bat1/2-deficient
> strain **JWY07** with its blocked valine biosynthesis **was not able to grow to a sufficient OD
> for fermentation experiments.**

JWY07 was never fermented. It has no titer because the experiment could not be run.

**Fact two: JWY05 and JWY06 were measured, and the result points the other way.** `[17687, 17874)`:

> However, even slight reductions of the valine synthesis by deleting only **BAT1 (JWY05)** or
> **BAT2 (JWY06)** had **negative effects on growth in media without valine and on isobutanol
> production**, **in contrast to other work** [].

"In contrast to other work" is Boles naming the disagreement with Hammer & Avalos in their own
sentence. No number is given for either strain — the finding is stated qualitatively and the figure
does not carry them — so there is nothing for a curator to promote as a `measurement` even if they
read the paper today.

### What it would do if the number existed

Rehearsed in a `:memory:` copy, with a **synthetic** measurement row (`YAA:MEAS:SYNTHETIC-…`,
`value_as_reported = -1.0`, `unit_as_reported = 'SYNTHETIC'`) whose only job is to let the view
count a third group. No titer is claimed for JWY05 anywhere in this document.

```
BEFORE            : n_evidence=2 n_direct=2 n_direct_groups=2  level=L2  direct_evidence_replicated
AFTER (decreases) : n_evidence=3 n_direct=3 n_direct_groups=3  level=L1  direct_evidence
AFTER (increases) : n_evidence=3 n_direct=3 n_direct_groups=3  level=L2  direct_evidence_replicated
```

**Curating JWY05's titer as a third direct evidence item would demote the atlas's only L2 to L1.**
`n_direct_groups` rises to 3 and `n_direct_directions` rises to 2, and `assertion_level`'s L2 branch
requires `n_direct_directions <= 1`, so the row falls through to L1. That is the view working
correctly. It is also the exact opposite of what the task expected, and it is why this was worth
checking before anything was queued.

### Two findings for whoever owns `src/`

1. **`attach_evidence` does not warn on a discordant direction.** The demotion above happened
   silently: `attach_evidence` calls `_check_evidence` and discards the warnings
   (`missing, blockers, _ = _check_evidence(...)`), and `_check_evidence_agrees_with_itself` is only
   ever called from `plan_assertion`, over a request that carries *all* the evidence at once. An
   `attach_evidence` request carries one item and is compared against a reconstructed
   `AssertionRequest` holding only that item, so the "items disagree with each other" check has
   nothing to compare. The path a curator will actually take — `attach_evidence` on an existing
   assertion — is the one path with no discordance warning on it.
2. **`plan_assertion` cannot tell whether a span states the claim.** Proposal P17 below cites
   `YAA:SPAN:6c4ab8fe017445d3b62abba5e2439b33`, which is the JWY05 *genotype table row*
   (`'JWY05 | Δilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1; Δbat1'`) and says nothing about
   isobutanol. The planner returned `ready = True`. The span belongs to the right publication, which
   is all `_check_evidence_references` can check. Reported, not fixed; `src/` is not mine.

### What this changes, and what it does not

* The BAT1 L2 stands. §4's P5 and P6 strengthen it with two more Princeton backgrounds.
* The honest place for Boles' contrary observation is a **separate assertion with the opposite
  direction** plus a `conflict` row of kind `direction` (PLAN.md J.4). That is P16/P17, and P16 is
  **blocked**: `literature_assertion` requires a `span_id` and **no span row covers `[17687, 17874)`**.
* `L2_BATCH.md` §7 item 4 should be replaced by "curate the Boles JWY05/JWY06 sentence as a *span*,
  and open a `conflict`", not by "curate the titers".

---

## 2. What the sweep covered

Every promoted Zone R row was swept, not only the perturbation candidates.

| source | rows | proposals drafted | refused |
|---|---|---|---|
| `measurement` | 97 | 13 cite one | — |
| `modification` | 10 | 2 as subject (P7, P8) | 5 (§5.6, §5.7, §5.8) |
| `bottleneck` | 4 | 2 (P14, P15) | 2 (§5.9) |
| `pathway_configuration` | 4 | 0 | 4 (§5.4) |
| `part` | 18 | 0 | 18 (§5.5) |
| `analysis_result` | 8 | 0 | 8 (§5.3) |
| `condition_context` | **0** | 0 | the reason for §5.10 and §5.11 |

Three whole evidence classes are unavailable and each is refused once rather than per row:
`direct_biochemical` (§5.2), `correlative_omics` and with it any L3 (§5.3), and every `part` claim
(§5.5).

### The predicate vocabulary, used and not matched

All 17 terms are active at `vocab_version` 1. Four were used: `affects_production_of`,
`affects_tolerance_to`, `is_bottleneck_for`, and `catalyzes` (only in a deliberately-blocked probe,
P19). Terms considered and **declined because no term fits**, rather than coerced:

* **"compartmentalising the Ehrlich pathway in mitochondria outproduces the native localisation"** —
  the claim the four `pathway_configuration` rows and two of the four `bottleneck` rows are really
  about. `is_localized_to` says *where* something is, not that putting it there helps.
  `affects_production_of` needs a subject, and the subject here is a *localisation choice*, which is
  not one of the eleven `subject_type` values. **No term fits. Refused (§5.4).**
* **"valine feeding suppresses isobutanol in bat1Δ strains"** — `affects_production_of` with a
  `metabolite` subject is structurally fine and the claim fails on the control, not the predicate
  (§5.10).
* `affects_yield_of` — rejected everywhere for the same reason as both prior batches: every cited
  number is a titer, a fold-change in titer, or a tolerance reading. The atlas holds exactly two
  promoted `yield` rows and neither has a control.
* `improves_when_modified_by` — still structurally impossible; `assertion.object_type` has no
  `modification` value.
* `confers_resistance_to` — considered for P10/P11 and declined. The phenotype is growth in the
  presence of the product the strain makes; `affects_tolerance_to` is the term for that, and
  `confers_resistance_to` would quietly recast a biofuel as a drug.

---

## 3. The groups, and one that is not what it looks like

Convention, settled by the owner 2026-09-22: **`group:<pi-surname>-<institution>`**, decided from
author affiliations, recorded as a curator judgement each time because `publication` stores no
author or affiliation column. Affiliations below are from PubMed.

| slug | publication | basis |
|---|---|---|
| `group:boles-goethe-frankfurt` | `doi:10.1186/s13068-019-1486-8` | as `FIRST_BATCH.md` §1 |
| `group:avalos-princeton` | `doi:10.1016/j.ymben.2017.10.001` | as `L2_BATCH.md` §3 |
| `group:koonthongkaew-chulalongkorn` | `doi:10.1016/j.btre.2026.e00959` | as `L2_BATCH.md` §3 |
| `group:avalos-princeton` | `doi:10.1186/s13068-019-1560-2` | Zhang, Lane, Chen, Hammer, Luttinger, Yang, **Jin** (UIUC), **Avalos** (Princeton, corresponding). As `L2_BATCH.md` §3's near miss predicted. |
| `group:kondo-kobe` | `doi:10.1186/1475-2859-12-119` | Matsuda, Ishii, Kondo T, Ida, Tezuka, **Kondo A** — corresponding, `akondo@kobe-u.ac.jp`, RIKEN CSRS. |
| `group:yang-konkuk` | `doi:10.1016/j.jbiotec.2022.09.012` | Lee, Kim B, Kim S, Cho, Jung, Bhatia, Gurav, Ahn, Park, Choi, **Yang Y-H** (corresponding, Konkuk University). Recorded although the whole paper is refused (§5.11). |
| `group:omalley-ucsb` | `doi:10.1016/j.meteno.2016.03.004` | Solomon, Ovadia, Yu, Mizunashi, **O'Malley** (UC Santa Barbara). Recorded although refused (§5.8). |

### `doi:10.1016/j.cels.2019.10.006` is **not** an independent group — it is Princeton

This is the batch's second independence trap and it is subtler than `L2_BATCH.md` §3's. The GLN3
paper's author list is:

> **Kuroda K** (Kyoto, corresponding), **Hammer SK** (Princeton), Watanabe Y (Kyoto),
> Montaño López J (Princeton), Fink GR (Whitehead), Stephanopoulos G (MIT), Ueda M (Kyoto),
> **Avalos JL** (Princeton, corresponding).

It is a joint Kyoto–Princeton paper with **Avalos as co-corresponding author and Hammer as an
author** — the same two people who are `group:avalos-princeton`. A slug like `group:kuroda-kyoto`
would read correctly for the first author and would let a future Princeton paper and this one count
as two independent groups on the same claim. **P9, P10 and P11 therefore carry
`group:avalos-princeton`**, which is the conservative choice: under-counting independence costs a
level that later evidence can restore, and over-counting it mints an L2 out of one lab.

This is an owner decision (§7 D2). It also means **four of the eight papers in the promoted corpus
are Avalos-connected**, which is worth knowing before anyone reads `n_direct_groups` as a measure of
how well-replicated this field is.

---

## 4. The fifteen ready proposals

Shared by all of them unless stated: `zone` = `R`, `confidence` = `medium`,
`effect_size` / `effect_unit` / `effect_ci_low` / `effect_ci_high` / `effect_n` all NULL,
`context_id` NULL (there are no `condition_context` rows to point at). Every `.ready`,
`.missing`, `.blockers` and `.warnings` below is copied from `plan_assertion` run against the live
atlas, `mode=ro`; every level is what `assertion_level` returned in the rehearsal, never chosen.

`plan_assertion` returned `ready = True` with **empty `missing`, `blockers` and `warnings` for all
fifteen**. The per-proposal tables therefore record only what is not empty.

### 4.1 Gene-group subjects — P1 to P4, and P5/P6 onto the existing L2

The owner's sign convention applies: where the subject is a gene or gene_group, `direction`
describes **the gene's own role**, and the evidence item's direction describes the comparison
against the control. The two invert for a deletion, and `_subject_is_its_own_perturbation` returns
False for a `gene_group`, so the planner correctly says nothing.

These four are the only single-gene, single-deletion, isogenic-control experiments in the corpus
whose gene has a `gene_group` row. Every other gene-level reading is refused in §5.6–§5.8.

| | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| assertion id | `YAA:ASSERT:f2e84e6a855aedfc` | `YAA:ASSERT:6ab398a9829f860a` | `YAA:ASSERT:6e98461d20d91d79` | `YAA:ASSERT:f5712c849fb98edf` |
| subject | `YAA:GG:ybr176w` ECM31 | `YAA:GG:ypl061w` ALD6 | `YAA:GG:yjr148w` BAT2 | `YAA:GG:ycl009c` ILV6 |
| direction | **`no_effect`** | `decreases` | **`no_effect`** | `decreases` |
| strain / control | JWY03 / JWY02 | JWY23 / JWY19 | SHy25 / SHy23 | SHy52 / SHy23 |
| measurement | `YAA:MEAS:6f685ea5b4b553f7` 0.52 g/L | `YAA:MEAS:a4cb6381273139ff` 2.09 g/L | `YAA:MEAS:4874331693867141` 35 mg/L | `YAA:MEAS:a9c3db4bc486d1cc` 2.1× and `YAA:MEAS:8a9253889e3ae2ff` 2.2× |
| evidence direction | `no_effect` | `increases` | `no_effect` | `increases` (both) |
| group | boles | boles | avalos | avalos |
| evidence items | 1 | 1 | 1 | **2** |
| level from the view | **L1** `direct_evidence` | **L1** `direct_evidence` | **L1** `direct_evidence` | **L1** `direct_evidence` |

**P1 ECM31.** The gene-level sibling of the existing `YAA:ASSERT:f75570bed59e4456`. Same experiment,
same span, different subject — and worth having separately because `no_effect` is the one direction
that carries no sign at all, so the gene-level reading adds a statement without adding an
interpretation. *"deletion of ECM31 (strain JWY03) had no statistically significant effect on
isobutanol production (0.52 g/L)"*. The direction comes from the authors' stated statistic, not from
0.52 > 0.50. **Caveat:** JWY02 already carries `Δilv2 Δbdh1 Δbdh2 Δleu4 Δleu9`, so this is "no effect
in that background". With `direction = no_effect` that caveat weakens the claim rather than
inverting it, which is why P1 is proposed and P2's siblings are not.

**P2 ALD6.** *"The ald6 deletion accelerated glucose consumption and isobutanol formation and further
increased isobutanol production up to a titer of 2.09 g/L after 96 h (Fig. b) … in JWY23"*, and Fig.
7's caption lists JWY23 as JWY19 + `Δald6`. The cleanest single-gene pair in the Boles series.
**Caveat**, carried from `FIRST_BATCH.md` A6: the authors note JWY19 *"had obviously not reached
maximal isobutanol titers even after 120 h"* while JWY23 peaked at 96 h. That weakens a future
effect size and not the direction.

**P3 BAT2.** *"When BAT2 is deleted in CEN.PK2-1C (SHy25) isobutanol production (35 ± 12 mg/L)
remains approximately the same as in the wild type control (42 ± 11 mg/L), (SHy23)"*. The second
negative result in the atlas, and the one that gives the BAT1 L2 its meaning: the same lab, the same
figure panel, the same fermentation, and the paralog does nothing. A reader who sees only "BAT1
decreases isobutanol" cannot tell whether the BCAT family matters or whether *this* BCAT matters.
**Curation note:** no single span covers the claim. The measurement's span is the fragment
`[31228, 31273)` *"(35 ± 12 mg/L) remains approximately the same"*; the strain is named in the
adjacent `[31168, 31205)`. The claim sentence is `[31168, 31325)` and should be one span.

**P4 ILV6.** *"The ilv6Δ strain (SHy52) shows 2.2- and 2.1-fold increases in isobutanol titer as
compared to the wild type strain (SHy23) with or without valine in the media, respectively"*. Two
evidence items, one per valine condition, both `increases`, both `group:avalos-princeton` — so
`n_direct` = 2 and `n_direct_groups` = 1 and the level is L1, which is the right answer and is worth
seeing demonstrated. **Caveat, and it is real:** later in the same paper *"Deletion of ILV6 (SHy54)
partially suppresses the increase in isobutanol production observed in the bat1Δ strain (SHy24) in
the absence of valine"*. ILV6's sign inverts on a `bat1Δ` background. This assertion is the
wild-type-background comparison and nothing else. With `condition_context` empty there is nowhere to
say so on the row, and the day someone asserts the `bat1Δ`-background result the atlas will hold two
contradicting statements with nothing distinguishing them. See §7 D4.

#### P5 and P6 — two more backgrounds on `YAA:ASSERT:893939228cea1ef4`

Both are `attach_evidence`, not `build_assertion`: `plan_assertion` returns
`already = YAA:ASSERT:893939228cea1ef4` and `"exists; would add 1 evidence item(s)"`.

| | P5 | P6 |
|---|---|---|
| evidence id | `YAA:EV:b69e96d3b0fffb54` | `YAA:EV:7ddf456c6aaf324b` |
| strain / control | `SHy104` (bat1Δ, BY4741) / `SHy99` (wild type) | `YZy173` (bat1Δ) / `YZy165` (parent) |
| measurement | `YAA:MEAS:d33a41cb54d11bf7` — 8.8 `fold_increase` | `YAA:MEAS:bdbaf9647d56291e` — 358 mg/L titer |
| span | `YAA:SPAN:a6773db939f44975b6b8dbe80faf4b6a` `[48310, 48355)` | `YAA:SPAN:9966d4fa2c214ce68f3881f1c332b507` `[16009, 16180)` |
| publication | `doi:10.1016/j.ymben.2017.10.001` | `doi:10.1186/s13068-019-1560-2` |
| group | `group:avalos-princeton` | `group:avalos-princeton` |

P5 is `L2_BATCH.md`'s optional E3, offered again now that the assertion exists. P6 is new and is the
stronger of the two: *"We found that deleting BAT1 in YZy165 results in a strain (YZy173, Table )
that produces 358 ± 13 mg/L isobutanol (from 15% xylose in 72 h high cell-density fermentations)"*,
with the genotype table saying `YZy173 | δ-IbOH pathway, bat1Δ | YZy165 bat1Δ::hphMX`. Isogenic by
construction, and it is the **only `bat1Δ` result in the corpus on a carbon source other than
glucose**.

Neither adds a group. The rehearsal confirms the level after both:

```
n_evidence=4  n_direct=4  n_direct_groups=2  level=L2  direct_evidence_replicated
```

What they add is J.3's first axis: the assertion goes from two backgrounds to **four** (CEN.PK2-1C,
BY4741, the xylose-utilising BF264-15Dau derivative, and the Thai industrial isolate) and from one
carbon source to two.

### 4.2 Modification subjects — P7, P8

| | P7 | P8 |
|---|---|---|
| assertion id | `YAA:ASSERT:05f3751605dfdcbd` | `YAA:ASSERT:15a8bd300d887a9d` |
| subject | `YAA:MOD:8003a204b05640ff` (CRISPR `bat1Δ`, IbOH-1) | `YAA:MOD:cc361f36d38986e4` (`gpd1Δ gpd2Δ`, JWY19) |
| direction | `increases` (the modification's own sign) | `increases` |
| strain / control | `iboh-1bat1` / `iboh-1` | `jwy19` / `jwy18` |
| measurement | `YAA:MEAS:e02f80aee1c3706c` 0.866 g/L | `YAA:MEAS:f661cca85c3e05e3` 1.32 g/L |
| span | `YAA:SPAN:3d8e0f0e20774354aea1f0562f2741a8` | `YAA:SPAN:2dd368f3cfee45858b29e4a6b42913a6` |
| group | `group:koonthongkaew-chulalongkorn` | `group:boles-goethe-frankfurt` |
| level from the view | **L1** `direct_evidence` | **L1** `direct_evidence` |

**P7** is `FIRST_BATCH.md` R1, re-drafted because `L2_BATCH.md` §2 answered its refusal: IbOH-1 was
run beside IbOH-1bat1Δ in Fig. 4 and reported N.D., so an isogenic control *strain* exists even
though no control *measurement* is curated — and `evidence_item` requires a stated control, not a
second number. `L2_BATCH.md` §7 item 3 asked for exactly this; here it is, planned and rehearsed.
It is not redundant with the L2: `YAA:ASSERT:05f3751605dfdcbd` is the per-paper perturbation record,
and the L2 is the species-level claim.

**P8** is `FIRST_BATCH.md` A5, unchanged and still carrying its caveat: JWY18 already has `gpd2Δ`, so
what this demonstrates is the `gpd1Δ` increment on a `gpd2Δ` background, not the double deletion
against an intact one. The fully isogenic control is JWY16, whose titer is still uncurated. Re-offered
rather than re-argued, because the owner held it and has not decided.

### 4.3 Strain subjects — P9 to P13

`from_measurement` defaults `subject_type` to `strain`, which is the module's own endorsement of this
shape. It is used here only where it is the **only** honest shape: none of GLN3 (YER040W) or LPD1
(YFL018C) has a `gene_group` row, and neither perturbation has a `modification` row, so a gene-level
or modification-level subject would dangle. Each entry names the row that would upgrade it.

| | P9 | P10 | P11 | P12 | P13 |
|---|---|---|---|---|---|
| assertion id | `YAA:ASSERT:c0ed4d595855c26b` | `YAA:ASSERT:c6712f97da98efdc` | `YAA:ASSERT:8df99ab6c79c851b` | `YAA:ASSERT:3ea66cc622705693` | `YAA:ASSERT:8ff7580c7a25d2da` |
| subject | `gln3d-gln3d-…-by4743-strain` | `gln3d` | `gln3d` | `bsw205` | `bsw206` |
| predicate | `affects_production_of` | `affects_tolerance_to` | `affects_tolerance_to` | `affects_production_of` | `affects_production_of` |
| object | isobutanol | isobutanol | **2-methyl-1-butanol** | isobutanol | isobutanol |
| direction | `increases` | `increases` | `increases` | `increases` | `increases` |
| control | `by4743` | `by4741` | `by4741` | `bsw192` | `bsw191` |
| measurement | `ee731ff3215707d7` 306 mg/L | `bb5d0854e64600ba` 2.7 % v/v | `54ffe26d3254889d` 11.4× OD | `88f336916a59cf77` 230 mg/L | `ac063b79945c2646` 221 mg/L |
| group | `avalos-princeton` | `avalos-princeton` | `avalos-princeton` | `kondo-kobe` | `kondo-kobe` |
| level | **L1** | **L1** | **L1** | **L1** | **L1** |

**P9 — GLN3 and production.** *"enhances isobutanol production 4.9-fold relative to BY4743 harboring
the same plasmid (pJA184) … from 63 ± 7 mg/L in the wild type to 306 ± 4 mg/L"*. Both arms carry
pJA184; they differ by the homozygous `gln3Δ`. Span `YAA:SPAN:bbe5e30ace9744e28cde2c50d8cccc70`
`[36394, 36443)`, chosen over the alternative `YAA:SPAN:7ab5735111d3447a905534a07d3d8359` because the
latter starts mid-number (*"7 mg/L in the wild type to 306 ± 4 mg/L"*). **Data note, identical in
kind to `FIRST_BATCH.md` A1's:** `YAA:STRAIN:by4743` records nothing about pJA184, so a reader
following the strain row alone will conclude the control is a bare wild type. The strain row, not
this assertion, is where that belongs.

**P10 — GLN3 and isobutanol tolerance.** *"The gln3D strain can grow on SC agar medium containing
2.7% isobutanol"*, against BY4741's promoted 2.4% v/v row, whose own `quantity_kind` is *"isobutanol
concentration on agar at which growth is still observable but noticeably inhibited"*. **The two
quantity kinds are not the same measurement** — one is the highest concentration permitting growth,
the other the concentration at which growth is visibly inhibited — so they must not be subtracted.
The direction is not taken from them: it is taken from the authors, *"deletion of GLN3 confers the
highest tolerance to isobutanol in liquid and solid medium, with OD600 values more than three times
those of the wild-type strain"*. This is the same discipline P1 applies, in the opposite direction.

**P11 — GLN3 and 2-methyl-1-butanol tolerance.** The atlas's first assertion about a product other
than isobutanol. *"Compared to the wild-type strain, the gln3D strain has dramatically enhanced
tolerance to branched-chain alcohols … with an OD600 as much as 11.4-fold higher in the presence of
0.55% 2-methyl-1-butanol"*. The fold-change is defined relative to wild type in the sentence, so no
control measurement is needed and `control_strain_id = YAA:STRAIN:by4741` is the stated control.
**Blocking-adjacent span defect, and the owner should fix it before writing:**
`YAA:SPAN:49f79b0e99804447a23ca599cc736990` is `[23543, 23595)` = *"as much as 11.4-fold higher in
the presence of 0.55%"* — **it stops one word before naming the alcohol.** A reader following the
span cannot tell which alcohol the 11.4-fold refers to, and the object of this assertion is exactly
that. The span should be **widened to `[23543, 23614)`**, which is
*"as much as 11.4-fold higher in the presence of 0.55%\n2-methyl-1-butanol"*. The planner cannot see
this (§1, finding 2). P11 is drafted because the claim is true and the fix is a widening, not a
re-reading — but it is the one proposal here that should not be written before its span is widened.

**P12 and P13 — LPD1.** *"The additional disruption of the LPD1 gene in the BSW192 and BSW191 strains
further activated isobutanol biosynthesis. The isobutanol titer of the BSW205 and BSW206 strains
reached 230 ± 13 and 221 ± 27 mg/L, respectively"*, all four in the same 48-h fermentation. The
curated genotype spans make the pairing exact:

```
BSW192  BY4741        /pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1     94 mg/L
BSW205  BY4741 lpd1Δ  /pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1    230 mg/L
BSW191  BY4741        /pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM     83 mg/L
BSW206  BY4741 lpd1Δ  /pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM    221 mg/L
```

Two isogenic pairs differing by `lpd1Δ` and nothing else — the cleanest controlled contrast in the
Kobe paper, and `FIRST_BATCH.md` R2 missed it because it was looking at the (since-removed) `lpd1Δ`
modification row rather than at the genotype table. **They are two assertions and not one**, because
the subject is a strain and the two strains are two rows. That is the cost of a strain subject stated
plainly: one `gene_group` row for LPD1 (YFL018C) would collapse P12 and P13 into a single assertion
with two evidence items. It would still be L1 — one group — but it would be L2-capable, and P12/P13
never can be.

### 4.4 Bottleneck subjects — P14, P15 — and the atlas's first L5s

Both are `from_bottleneck`, which also fills `bottleneck.assertion_id` on write — the one
already-curated column `assertions.py` touches, and what makes a bottleneck "an assertion with a
required shape" (PLAN.md G.8) rather than a parallel opinion.

| | P14 | P15 |
|---|---|---|
| assertion id | `YAA:ASSERT:1b0e9383315e2273` | `YAA:ASSERT:d09b990aa629e87e` |
| bottleneck | `YAA:BNK:0f91f3dea55fee47` | `YAA:BNK:fd51186dbd051805` |
| subject | `gene_group YAA:GG:yhr208w` (BAT1) | `metabolite YAA:MET:pyruvate` |
| predicate | `is_bottleneck_for` | `is_bottleneck_for` |
| object | `product YAA:PRODUCT:isobutanol` | `product YAA:PRODUCT:isobutanol` |
| direction | **NULL** | **NULL** |
| evidence type | `literature_assertion` | `literature_assertion` |
| span | `YAA:SPAN:869e0b276ad14a5bb04c450fb1be9da1` | `YAA:SPAN:9967130d42d74a318bd85d08b1ccf9af` |
| publication | `doi:10.1016/j.btre.2026.e00959` | `doi:10.1186/1475-2859-12-119` |
| level from the view | **L5** `hypothesis_or_insufficient_support` | **L5** `hypothesis_or_insufficient_support` |

**Why `literature_assertion` and not `direct_perturbation`.** `L2_BATCH.md` §4 declined
`is_bottleneck_for` for the production assertion with a sentence that is also the reason it is used
here: *"the evidence offered is two titer comparisons, which measure how much isobutanol, not where
the flux is limited; `is_bottleneck_for` is a claim the atlas's `bottleneck` table should carry with
its own evidence."* This is that follow-through. Both `bottleneck` rows have
`observation_type = 'inferred'` and `support as reported: stated_by_authors` — they record what the
authors concluded, not a flux measurement, and `literature_assertion` is the type for that. The cost
is stated openly: `literature_assertion` counts toward `n_weak` and toward nothing else, so these
grade **L5** and would still grade L5 with ten such items. Re-typing them `direct_perturbation` and
re-citing the BAT1 titers would badge them L1 and then L2 — which is the laundering route
`assertions.py`'s module docstring is written against, and is refused.

**`direction` is NULL on both**, which is the other half of why `is_bottleneck_for` is the right
term here: "is a bottleneck" has no sign to get wrong, so the assertion sidesteps §7 D1 entirely.

**P15's subject is a curator judgement and an owner decision.** `from_bottleneck`'s docstring warns
that `bottleneck.node` is free text and that *"mapping them to the nearest reaction is the guess
CONVENTIONS.md forbids"*. The node here is `'pyruvate node'` and the span is *"pyruvate supply for
isobutanol biosynthesis is competing with acetyl-CoA biosynthesis in mitochondria"*. Mapping that to
`YAA:MET:pyruvate` is naming the metabolite the node is named after, not choosing the nearest
reaction from sixteen — but it is still a judgement, it is the first of its kind, and it is §7 D5.
`competes_with` with subject `YAA:MET:pyruvate` and object `YAA:MET:acetyl-coa` was considered and is
arguably a closer fit to that one sentence; it was not chosen because the row is a `bottleneck` row
and `is_bottleneck_for` is the predicate the `bottleneck` table exists to speak.

### 4.5 The rehearsal, and what the view actually said

`build_assertion` (or `attach_evidence` where the assertion already exists) ran in a `:memory:` copy
as curator `kangkon`, kind `human`. Levels read out of `assertion_level`.

| proposal | action | `n_ev` | `n_direct` | `n_direct_groups` | level | basis |
|---|---|---|---|---|---|---|
| P1 ECM31 | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P2 ALD6 | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P3 BAT2 | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P4 ILV6 | build | 2 | 2 | 1 | **L1** | `direct_evidence` |
| P5 BAT1 +SHy104 | attach | 3 | 3 | 2 | **L2** | `direct_evidence_replicated` |
| P6 BAT1 +YZy173 | attach | 4 | 4 | 2 | **L2** | `direct_evidence_replicated` |
| P7 mod `bat1Δ` IbOH-1 | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P8 mod `gpd1Δ gpd2Δ` | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P9 gln3Δ/gln3Δ production | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P10 gln3Δ tolerance, isobutanol | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P11 gln3Δ tolerance, 2-MbOH | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P12 BSW205 `lpd1Δ` | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P13 BSW206 `lpd1Δ` | build | 1 | 1 | 1 | **L1** | `direct_evidence` |
| P14 BAT1 `is_bottleneck_for` | build | 1 | 0 | 0 | **L5** | `hypothesis_or_insufficient_support` |
| P15 pyruvate `is_bottleneck_for` | build | 1 | 0 | 0 | **L5** | `hypothesis_or_insufficient_support` |
| P17 *(see §5.1)* | build | 1 | 0 | 0 | **L5** | `hypothesis_or_insufficient_support` |

**Twelve L1, two L2 attachments onto one existing assertion, two L5. No L3 and no L4** — §5.3 says
why L3 is unreachable and there is not one `computational_model` evidence item in the corpus for L4.

PLAN.md J.5's walk over the whole rehearsal atlas:

```json
{"n_walked": 20, "n_closed": 20, "n_broken": 0, "breaks_by_kind": {}, "gaps_by_kind": {}}
exit_code: 0
```

Narrowed to this batch's assertions:

```json
{"n_walked": 15, "n_closed": 15, "n_broken": 0, "breaks_by_kind": {}, "gaps_by_kind": {}}
exit_code: 0
```

Every item closes the literature arm through `span → publication`; the analysis arm is not involved,
so the known `dataset_unreachable` gap never arises. The live atlas was re-counted afterwards:
`assertion` = 6, `evidence_item` = 7. **Unchanged.**

---

## 5. What was refused, and what would unblock each one

### 5.1 The Boles contrary BAT1 observation — P16 — *no span covers the sentence*

```
P16  ready=False
  missing: evidence[0].span_id: the exact sentence, so the claim resolves to text a reader can check
```

The claim is real (§1) and the assertion id it would take is **`YAA:ASSERT:017a897a1a9054c2`** — the
id `L2_BATCH.md` §4 drafted and the owner declined when they settled the sign convention. It is
blocked on one missing row: a `span` over `[17687, 17874)` of
`doi:10.1186/s13068-019-1486-8`, *"However, even slight reductions of the valine synthesis by
deleting only BAT1 (JWY05) or BAT2 (JWY06) had negative effects on growth in media without valine and
on isobutanol production, in contrast to other work"*.

**P17 is the same proposal with a stand-in span, and it is the warning.** Citing
`YAA:SPAN:6c4ab8fe017445d3b62abba5e2439b33` — the JWY05 genotype table row — the planner returns
`ready = True` and the rehearsal builds it at **L5**. That is a correctly-resolving citation to a
sentence that does not contain the claim, which `traceability.py` calls worse than one that does not
resolve at all. **P17 is listed to be refused, not approved.** It is here because it is the only way
to show that `ready = True` does not mean "the span says this".

If the span is curated, P16 becomes writable and the right shape is: **the assertion, plus a
`conflict` row of kind `direction` between `YAA:ASSERT:017a897a1a9054c2` and
`YAA:ASSERT:893939228cea1ef4`** (PLAN.md J.4). Note what that costs: an **open** direction conflict
makes `assertion_level` return `NULL` / `direct_evidence_discordant` for *both*, which is the
schema's deliberate "the atlas does not yet know". Whether Boles' background-specific observation
warrants withdrawing the L2 is a curator decision and emphatically not mine. See §7 D3.

### 5.2 Every `direct_biochemical` claim, corpus-wide

```
P19  ready=False
  missing: evidence[0].assay_method: which assay produced the number -- enzyme assay, isotope
           tracing, flux
```

**97 of 97 `measurement` rows have `assay_method` NULL.** `from_measurement` copies the column off
the row, so every `direct_biochemical` request in the atlas fails on the same field. Supplying the
string myself would be inventing the method. This also re-confirms `FIRST_BATCH.md` R1's finding that
a whole-strain titer is not a biochemical assay of an enzyme in any case.

**Unblock:** curate `assay_method` (GC-FID, GC-MS, HPLC) on the measurement rows, which unlocks
nothing on its own — a titer stays a titer — and then curate an *enzyme activity* measurement. The
only paper in the corpus that measured one is `doi:10.1016/j.meteno.2016.03.004` (specific activity
of BCKAD and ACD, cytosolic vs matrix), and it has **zero** promoted measurements.

### 5.3 Every `correlative_omics` claim, and with it L3

```
P20  ready=False
  missing: evidence[0].effect_size: an association with no effect size states nothing quantitative
           evidence[0].p_adjusted: multiple-testing corrected, in [0, 1]
```

All 8 `analysis_result` rows are Salmon output — raw TPM and count matrices plus a manifest and a QC
table, Zone H. There is **no `contrast` table in this schema** and no differential-expression result
anywhere, so there is no effect size and no adjusted p-value to cite. L3 additionally needs
`n_assoc_pubs >= 3`; the corpus has zero.

**Unblock:** a differential-expression run producing per-gene effect sizes and adjusted p-values,
written as `analysis_result` rows. That is a `processing_run`, not a curation task.

### 5.4 Every claim from the four `pathway_configuration` rows — *no predicate fits*

```
P22  ready=False
  missing: subject_type: 'pathway_configuration' is not one of ['compartment', 'gene',
           'gene_group', 'metabolite', 'modification', 'part', 'pathway', 'pathway_route',
           'product', 'reaction', 'strain']
```

Two failures, and the second is the one that matters.

1. `pathway_configuration` is not a `subject_type`. That alone is recoverable — the subject could be
   the `pathway` row, or one of the 600 `pathway_route` rows.
2. **No term in the 17 says what these rows are for.** The claim each configuration supports is
   *"compartmentalising the Ehrlich pathway in mitochondria outproduces the same enzymes in their
   native compartments"* — two of the four `bottleneck` rows say it too. `is_localized_to` states
   where something sits; used here it would assert that an engineered pathway is in the matrix, which
   is a restatement of the `pathway_configuration` row and adds nothing. `affects_production_of`
   needs a subject, and the subject of this claim is a **localisation strategy**, which no
   `subject_type` names. **Per the brief: none fits, and this moves on.**

**Unblock:** either a vocabulary change (a versioned addition under PLAN.md J.2, not a coercion), or
a `pathway_route` subject — the atlas has 600 of them and a mitochondrial route and a cytosolic route
to the same product are two different rows, which is precisely the distinction the claim needs.
Choosing the two routes is a curation decision with real content and is not a mapping.

### 5.5 Every claim about a `part`

All 18 `part` rows are **Zone I**, sixteen at `confidence = 'unverified'`. None carries a `span_id` or
a `publication_id`, so `literature_assertion` — the only type a part claim could take — has nothing
to cite and cannot close a J.5 arm. `ai_inference` would technically fit the zone and is refused for
a different reason: it requires `model`, `model_version`, `prompt_version` and `review_state`, and an
agent writing an AI-inference assertion about rows an agent wrote is a closed loop with a badge on it.

**Unblock:** the part rows' `evidence` prose already quotes real papers at length (see
`YAA:PART:adh3-native`, which quotes four). Turning those quotes into `span` rows with offsets would
make `catalyzes`, `is_localized_to` and the cofactor claims writable at L5 immediately.

### 5.6 Gene-level claims from the three double deletions

`BDH1/BDH2` (`YAA:MOD:510bd21a2c8e8ad8`), `LEU4/LEU9` (`YAA:MOD:a5b8b1111f6c42af`) and `GPD1/GPD2`
(`YAA:MOD:cc361f36d38986e4`) each have `gene_group` rows for **both** genes
(`yal060w`/`yal061w`, `ynl104c`/`yor108w`, `ydl022w` and — note — **no `gene_group` for GPD2**). The
experiment deleted both members at once. Asserting `LEU4 decreases isobutanol` from a `leu4Δ leu9Δ`
strain attributes the joint effect to one paralog, and `plan_assertion` would return `ready = True`
because nothing in the schema knows the modification touched two loci.

**Refused.** The modification-subject assertions for all three are the honest record and two are
already written.

**Unblock:** single-deletion titers, which the Boles paper does not report; or a `gene_group` row
whose membership is the paralog pair — `gene_group.membership_method` has values other than `anchor`,
and a two-member group anchored on one systematic name is exactly what `scope` and
`membership_method` are for.

### 5.7 A gene-level claim for ILV2 — *the sign inverts between papers*

`ilv2Δ` raised isobutanol 22-fold in Boles (JWY0), and Matsuda **overexpressed** ILV2 to raise it
(`BSW100`, *"Three genes required for isobutanol biosynthesis, including ILV2, kivd, and ADH6, were
introduced"*). Both are true, and they are not in conflict: Boles deleted the **mitochondrial** Ilv2
while expressing the **cytosolic** isoform from plasmid IsoV100 — *"a low isobutanol titer of 0.01
g/L … for the wt strain CEN.PK113-7D expressing the cytosolic isoforms of Ilv2, Ilv5, and Ilv3"*.

A species-scope `gene_group ILV2` assertion has no compartment on it, so it would have to pick one of
the two signs and would be wrong about the other half of the corpus. **Refused.** (The
modification-subject `YAA:ASSERT:80b93f76dadaa25c` is already written and is correct, because a
modification carries `compartment: mitochondrial_matrix` in its `details`.)

**Unblock:** `compartment` is a `subject_type` and `is_localized_to` is a predicate, so the
compartment-specific claim is expressible — but not as a property of the gene group. The clean shape
is a `pathway_route` subject, as in §5.4.

### 5.8 The `meteno.2016` modifications, and the `kivd` insertion

* `YAA:MOD:a89fb362fc39d454` (bacterial valine catabolism genes) and `YAA:MOD:549819c3e9e779f7`
  (Su9 leader peptide) both have **`strain_id = NULL`**, and `direct_perturbation` requires
  `strain_id`. The paper has **zero promoted measurements**. Nothing about them is assertable today.
  **Unblock:** the paper's enzyme-activity numbers (§5.2) plus a strain on each modification.
* `YAA:MOD:dd058febc2a55035` (`kivd` insertion, BSW191) — `FIRST_BATCH.md` R3's refusal stands and
  gains a second reason. R3 said BSW100 also carries *kivd*; the genotype spans now show BSW191 and
  BSW100 differ by **two** things, the `pATP423-PMsM` shunt plasmid *and* `pILV532cytM`. It is not an
  isogenic pair on any reading. **Unblock:** the transhydrogenase-shunt modification row R3 asked
  for, and a control that differs by it alone — which in this paper is BSW192 vs BSW205's series, not
  BSW100.

### 5.9 Two of the four bottlenecks — *the node is not an identifier*

```
P23  ready=False
  missing: subject_id: the statement names no subject, so it is about nothing
```

* `YAA:BNK:431c48b1e633a585` — node `'mitochondrial protein import'`. There is no transport reaction,
  no `part` and no gene group that is mitochondrial protein import. Mapping it to one of the sixteen
  `reaction` rows is the guess `from_bottleneck`'s docstring forbids.
* `YAA:BNK:e86745216bd648b4` — node `'compartment choice for the Ehrlich pathway'`. Not an entity at
  all; it is the §5.4 claim in a different table. Mapping it to
  `YAA:PWY:isobutanol-valine-ehrlich` would assert about the pathway what the row says about the
  *choice of where to put it*.

**Unblock:** for the first, a `reaction` or `pathway_route_step` row for the TOM/TIM translocation
step. For the second, §5.4's `pathway_route` pair.

### 5.10 Every condition contrast, corpus-wide — *`condition_context` holds 0 rows*

```
P21  ready=False
  missing: evidence[0].control_strain_id|control_condition_id: L1 requires a stated control. An
           isogenic control strain or the control condition -- either satisfies the schema, and
           neither can be inferred from the measurement
```

The corpus is full of real, controlled, same-strain condition contrasts and **not one is assertable**:

* valine feeding vs valine-free in SHy16, SHy24, SHy54, SHy55, SHy62 (five promoted
  `titer_decrease_percent` / `percent_decrease…` rows);
* xylose vs glucose in YZy197 (2.05 vs 1.07 g/L isobutanol, 0.91 vs 0.68 g/L 2-MbOH);
* YPD vs YNB and 100 vs 150 g/L glucose in IbOH-1bat1Δ;
* every medium comparison in `doi:10.1016/j.jbiotec.2022.09.012` (§5.11).

A same-strain contrast cannot name a control *strain*, so `control_condition_id` is the only route,
and `condition_context` is **empty**. Putting the test strain in `control_strain_id` would make the
row claim the strain is its own isogenic control, which is false and resolves cleanly — the worst
combination.

**Unblock:** `condition_context` rows, and they are the single highest-leverage curation this sweep
found after §1. They also fix `assertion.context_id`, which is NULL on all fifteen proposals above
for the same reason, and they are what would let P4's `bat1Δ`-background caveat and §5.7's
compartment problem be *stated on the row* instead of in a document.

### 5.11 The entire E. coli paper, `doi:10.1016/j.jbiotec.2022.09.012`

Four candidate perturbation pairs (HJ03 vs HM501, HJ04 vs HJ03, HJ05 vs HJ03, HJ02 vs HM501), 12
promoted measurements, and **none is assertable**, for two independent reasons.

1. **Every direction inverts between media.** `ptsG` deletion: *"Isobutanol content decreased from
   5.18 g/L to 1.26 g/L in the 1:0 medium; however, it increased from 1.76 g/L to 2.79 g/L in the 1:1
   medium."* `glf`/`glk` overexpression: *"HJ04 showed a lower isobutanol titer than the control in
   0:1 and 1:1 media. However, HJ04 … showed increased isobutanol production in the 1:0 medium."* A
   direction is only meaningful with the medium attached, and §5.10 says there is nowhere to attach
   it. Picking one medium would state a fact and imply a falsehood.
2. **The strain rows are at two granularities and one pair is duplicated.** The paper's controls are
   the empty-vector strains `HJ03::pRSFDuet-1` and `HM501::pRSFDuet-1`, and both have `strain` rows —
   but the 1.26 g/L and other control titers are curated onto the bare `YAA:STRAIN:hj03`. Worse,
   **`YAA:STRAIN:hm501-prsfdeut-1` and `YAA:STRAIN:hm501-prsfduet-1` are two rows for one strain**,
   differing by the paper's own typo ("Deut" for "Duet"), with measurements curated onto both (2.5
   g/L on the first; 1.98, 5.18 and 1.76 g/L on the second). **This is a `data/` bug and it is
   reported, not touched.**

**Unblock:** `condition_context` rows for the four media, and a merge of the two HM501 strain rows
with a `strain_alias` — the table exists.

### 5.12 Three more, briefly

* **JWY04 / `ilv1Δ`** — 0.56 vs JWY03's 0.52 g/L. The span says only *"Maximum isobutanol titers of
  0.56 g/L were reached with strain JWY04 after interrupting the isoleucine biosynthesis pathway by
  deletion of ILV1"*, with **no statistic**, on a series where the immediately preceding 0.02 g/L step
  was explicitly declared *not* significant. There is also no `modification` row for `ilv1Δ` and no
  `gene_group` for ILV1. Reading `increases` off 0.52 → 0.56 is inventing a direction. **Refused.**
* **BAT1 *overexpression* (SHy18, SHy30, SHy21)** — *"To enhance the ValC-dependent pathway, we
  overexpressed BAT1 … BAT1 (SHy18) leads to a 3-fold increase in isobutanol production"*. This is the
  same paper as the L2's E1, and the gene-level sign is the **opposite**: overexpressing BAT1 raises
  isobutanol via the valine route, deleting it raises isobutanol far more via the KIV route. The
  authors treat these as two pathway configurations, not a contradiction. With `context_id` NULL
  (§5.10) an `increases` assertion would be a bare contradiction of the atlas's only L2, from the same
  group and the same figure. **Refused**, and this is the strongest argument in the batch for
  curating `condition_context`.
* **SHy84, the BAT1 complementation** — *"complementing the bat1Δ strain (SHy24) with a single copy of
  BAT1 … resulted in a strain (SHy84) with isobutanol titers that decreased back to wild type
  levels"*. This is the textbook control for the entire BAT1 claim and it is **not curatable as
  evidence**: SHy84's titer is in Supplementary Fig. 2 and has no `measurement` row. **Unblock:** one
  measurement. It is the second-highest-value curation this sweep found.

---

## 6. Curation tasks this turned up, in priority order, none of them mine to do

1. **Curate a `span` over `[17687, 17874)` of `doi:10.1186/s13068-019-1486-8`** — the Boles
   BAT1/BAT2 sentence. Unblocks P16 and, with it, the atlas's first honest `conflict`. **Do not**
   curate a JWY05 or JWY06 titer: the paper reports none, and §1 shows what happens if one is
   invented.
2. **Widen `YAA:SPAN:49f79b0e99804447a23ca599cc736990` from `[23543, 23595)` to `[23543, 23614)`** so
   it names 2-methyl-1-butanol. P11 should not be written before this.
3. **Curate `condition_context` rows.** §5.10. It unblocks more claims than anything else on this
   list and it is what lets P4, §5.7 and §5.12's caveats live on the rows instead of in prose.
4. **Curate SHy84's titer** from Supplementary Fig. 2 of `doi:10.1016/j.ymben.2017.10.001`. §5.12.
5. **Merge `YAA:STRAIN:hm501-prsfdeut-1` into `YAA:STRAIN:hm501-prsfduet-1`** with a `strain_alias`.
   §5.11.
6. **Add a `gene_group` row for LPD1 (YFL018C)** — collapses P12 and P13 into one L2-capable
   assertion — **and for GLN3 (YER040W)** and **GPD2 (YOL059W)**, each of which would upgrade a
   strain-subject proposal to a gene-level one.
7. **Curate `YAA:STRAIN:iboh-1`'s non-detect** — still open from `L2_BATCH.md` §7 item 1, still not
   blocking anything, still the right thing to do.
8. **Curate a single-gene deletion series** or paralog-pair `gene_group` rows for BDH1/2, LEU4/9 and
   GPD1/2. §5.6.

---

## 7. What is the owner's, not mine

**D1 — the sign convention is settled and was applied.** Gene and gene_group subjects take the gene's
own sign (P2, P4 `decreases`; P5/P6 inherit the existing `decreases`); modification subjects take the
modification's (P7, P8 `increases`). `no_effect` (P1, P3) and NULL (P14, P15) have no sign to get
wrong. Recorded here only because the batch is the first to apply it to new rows, and because it is
why P2 reads `ALD6 decreases isobutanol` while the already-written
`YAA:ASSERT:65a970e162e06e63` reads `ald6Δ increases isobutanol` — two correct statements about two
different subjects.

**D2 — `doi:10.1016/j.cels.2019.10.006`'s group.** §3. `group:avalos-princeton` is proposed on
conservative grounds; `group:kuroda-kyoto` reads better for the first author and would allow a future
double-count. Whichever is chosen becomes a permanent key.

**D3 — what to do about Boles and BAT1.** Three options, in ascending cost: record nothing and leave
the disagreement in this document (status quo); curate the span and write P16 as a separate L5
assertion with no `conflict` row (the atlas holds both statements, both correctly levelled, and a
reader sees them side by side); or curate the span, write P16 **and** open a `conflict` of kind
`direction`, which makes `assertion_level` return **NULL** for both and withdraws the L2 badge until
someone resolves it. The middle option is the one I would argue for — the disagreement is real but
its cause is visible (Boles' background is `Δilv2 Δilv1`, so `bat1Δ` removes the last valine route
and the cells cannot grow without valine), which is a context difference rather than a contradiction.
But withdrawing an L2 badge is a curator act with a name attached.

**D4 — whether `is_bottleneck_for` at L5 is worth having.** P14 and P15 are the atlas's first L5s and
its first use of `literature_assertion`. They will never rise above L5 on this evidence, and
`bottleneck.assertion_id` is filled in on write, which is not reversible without superseding. The
alternative is to leave the four `bottleneck` rows unlinked, as they are today.

**D5 — P15's subject.** `metabolite YAA:MET:pyruvate` for the node `'pyruvate node'`. The first time
a free-text `bottleneck.node` has been mapped to a typed row in this atlas, and the precedent for the
other three.

**D6 — whether strain-subject assertions belong in the atlas at all.** P9–P13 are five of the
fifteen. `from_measurement` defaults to this shape, so the module endorses it, but a strain subject
has the same ceiling as a modification subject: it is paper-specific and can never reach L2. They are
proposed because they are the only honest shape for GLN3 and LPD1 today, and item 6 of §6 is the
route out.

---

## 8. If the owner approves

`build_assertion` refuses an agent, by design, and `assertion_level` does not read `zone` — so the
write is the owner's. It is **thirteen `build_assertion` calls and two `attach_evidence` calls**, in
the shape recorded in `docs/drafts/assertions/second_batch.yaml`, which is the machine-readable half
of this document and is deliberately not self-justifying.

Suggested order, because two of them change an existing row's grade and should be seen doing it:

1. **P5, then P6** — `attach_evidence` onto `YAA:ASSERT:893939228cea1ef4`. The level stays `L2`
   throughout and `n_direct_groups` stays 2; what moves is the background count, 2 → 4.
2. **P1–P4, P7, P8** — the six gene-group and modification L1s.
3. **P9, P10, P12, P13** — the strain-subject L1s. **P11 after its span is widened** (§6 item 2).
4. **P14, P15** — the two L5s, last, because they write `bottleneck.assertion_id` as a side effect.

**P11 is the one proposal in this batch that should not be written as it stands**, and **P17 is
listed to be refused.** Everything else in §4 is ready.
