# The atlas's first L2 — one assertion, two groups

**Status: proposal. Nothing here has been written.** The live atlas holds `assertion` = 5 and
`evidence_item` = 5, all L1, all `group:boles-goethe-frankfurt`, and it still did after every
query and rehearsal behind this document. `~/fermdb-data/fermdb.sqlite3` was opened `mode=ro`
throughout; `build_assertion` and `attach_evidence` ran only against an in-memory copy taken with
sqlite3's own backup API.

One thing *was* written, because it was the point of the task: **17 `modifications` curation tasks
for `doi:10.1016/j.ymben.2017.10.001`**, queued by `fermdb extract run --only-kind modifications`.
They are `pending`. None was accepted, rejected or promoted.

This document does the same two things `FIRST_BATCH.md` did — it does not choose a level, and it
puts no number in `effect_size` — and adds a third: **it does not accept the route it was given
without checking it.** Two parts of the stated route turned out to be wrong, and both are load-
bearing. They are §1 and §2.

---

## 1. The subject cannot be a `modification`, and that is why this is one assertion and not two

`FIRST_BATCH.md` §4 framed the L2 route as "a `bat1Δ` claim supported by `group:avalos-princeton`
and `group:koonthongkaew-chulalongkorn`", and the six L1 proposals all used
`subject_type = modification`. Carried forward literally, that route **cannot reach L2 at all.**

`assertion_id_for` hashes `identity()`, which includes `subject_id`. A `modification` row belongs
to exactly one strain in exactly one paper. Princeton's `bat1Δ` in SHy24 and Chulalongkorn's
`bat1Δ` in IbOH-1 are two different rows, so they hash to two different assertions, and two
assertions with one evidence item each are two L1s forever. Rehearsed:

```
YAA:ASSERT:05f3751605dfdcbd   <- from_modification(YAA:MOD:8003a204b05640ff)   [Chulalongkorn]
```

Putting the Princeton evidence onto *that* assertion would be worse, not better: the assertion's
subject would be a specific CRISPR deletion in a specific Thai industrial isolate, and it would
cite a Princeton experiment on CEN.PK2-1C as support for it. That is the same conflation J.3's
second axis exists to prevent, moved from the group column to the subject column.

**So the subject is the gene group.** `YAA:GG:yhr208w` — BAT1, anchored on the S288C systematic
name YHR208W, `scope = 'species'`, Zone H, confidence high. PLAN.md J.1 lists `gene_group` first
in its subject examples, and PLAN.md I's second standing query ("genes repeatedly modified…")
groups *by gene group* for exactly this reason.

`gene` was the alternative and is wrong here. `YAA:GENE:gcf-000146045-2-yhr208w` is Zone R rather
than H, which would have matched the assertion's zone more tidily — but it is bound to assembly
`GCF_000146045.2` (S288C), and `schema.sql` says on that column why that matters: *"A gene id is
meaningless without its assembly: genome-db found 520 ids shared between two assemblies while
naming different genes."* Neither experiment here is in S288C. One is CEN.PK2-1C; the other is a
UV-mutagenised derivative of an industrial isolate, G2-3-2, whose *own* BAT1 already carries an
I107T substitution. A species-scope gene group is the only anchor that honestly spans both.
CONVENTIONS.md's zone table settles the rest: Zone H "may support a conclusion — yes".

**Consequence of the change, stated plainly.** The 17 modification proposals queued for the
Princeton paper are *not* on the critical path to this L2. They are still worth having — they are
the perturbation records themselves, and a curator will want `YAA:MOD:…` rows for `bat1Δ` in
SHy24 and SHy104 — but the L2 does not block on them being accepted. The extraction was run as
instructed and is queued; this paragraph is the correction to the reason it was thought necessary.

## 2. The Chulalongkorn control exists, was measured, and `FIRST_BATCH.md` R1 missed it

R1 refused the `bat1Δ` claim in `doi:10.1016/j.btre.2026.e00959` because *"no isogenic control
exists"*, noting that the only other titer in the paper is `YAA:STRAIN:wild-type-s-cerevisiae` at
6.4 mg/L, a background sentence in the discussion. That reading is correct **about the promoted
`measurement` rows** and wrong about the paper. From the stored full text, `[22145, 22531)`:

> To investigate whether the mutation in the BAT1 gene of IbOH-1 affected Bat1 enzyme function,
> isobutanol content was compared between G2–3–2 and the IbOH-1. The results indicated that the
> isobutanol concentration in **both strains was below the quantification limit**. […] The results
> indicated that additional BAT1 gene disruption was necessary to improve isobutanol production
> from IbOH-1.

and the caption at `[22627, 22745)`:

> **Fig. 4** Isobutanol concentration (g/L) from G2–3–2, IbOH-1, and IbOH-1bat1∆ (N.D. indicates
> not-detected amount of isobutanol).

and `[25664, 25825)`:

> Overall, IbOH-1bat1∆ demonstrated a significantly greater elevation in isobutanol levels
> compared to the sub-quantified isobutanol content **observed in IbOH-1**.

IbOH-1 — the BAT1-intact parent, same mutagenesis, same background — **was run beside
IbOH-1bat1Δ and measured for isobutanol in the same figure.** It is an isogenic control in the
strict sense R1 asked for. R1's objection ("comparing with a generic wild type attributes to BAT1
an effect that includes the whole mutagenesis") was right about the wrong control and is answered
by using the right one.

Why the atlas did not see it: the control's *value* is **not detected**, and nobody curated a
measurement row for a non-detect. The schema is ready for one — `measurement.is_below_lod`,
`detection_limit`, `is_upper_bound` — so this is a curation gap, not a schema gap. It is the top
follow-up in §7.

**And it does not block this evidence item**, because `evidence_item` has no
`control_measurement_id` column at all. J.3 requires `control_strain_id` **or**
`control_condition_id` — a stated control, not a second number — and `YAA:STRAIN:iboh-1` is a row
in the atlas today. `first_batch.yaml` carried `control_measurement_id` as a draft-only field for
the reader's benefit; it was never a column, and the same convention is kept below.

---

## 3. The two groups, and the affiliation evidence for each

The atlas stores no author and no affiliation — `publication` is
`(id, doi, pmid, title, year, journal, license, zone, evidence, confidence)`. So, as on
2026-09-22, the group is a curator judgement read off PubMed author affiliations, under the
convention `group:<pi-surname>-<institution>`.

**This is the claim that makes the L2 real.** If these two labs were not independent, the second
evidence item would be a second publication from one group and the view's `COUNT(DISTINCT
independent_group)` would be doing nothing except laundering a repeat into a replication. The
evidence for independence is set out so it can be checked rather than believed.

### `group:avalos-princeton`

> Hammer SK, Avalos JL. *Uncovering the role of branched-chain amino acid transaminases in
> Saccharomyces cerevisiae isobutanol biosynthesis.* Metab Eng 2017; 44:302–312. PMID 29037781,
> [doi:10.1016/j.ymben.2017.10.001](https://doi.org/10.1016/j.ymben.2017.10.001).

Affiliations, from PubMed:

| author | affiliation |
|---|---|
| Hammer, Sarah K | Department of Chemical and Biological Engineering, **Princeton University**, Princeton, NJ 08544, USA |
| Avalos, José L | Department of Chemical and Biological Engineering; Andlinger Center for Energy and the Environment; Department of Molecular Biology, **Princeton University**. Corresponding: `javalos@princeton.edu` |

Two authors, one institution, one senior and corresponding author. **`group:avalos-princeton`.**

### `group:koonthongkaew-chulalongkorn`

> Thammapanyaphong N, Boonyanuwat M, Luengnaruemitchai A, Koonthongkaew J. *Development of
> Saccharomyces cerevisiae isobutanol production strain from osmotolerant and ethanol-producing
> industrial isolated yeast.* Biotechnol Rep 2026; 50:e00959. PMID 42088643, PMC13137203,
> [doi:10.1016/j.btre.2026.e00959](https://doi.org/10.1016/j.btre.2026.e00959).

| author | affiliation |
|---|---|
| Thammapanyaphong, Naphattarachon | Department of Microbiology, Faculty of Sciences, **Chulalongkorn University**, Bangkok |
| Boonyanuwat, Manutsanun | Department of Microbiology, Faculty of Sciences, **Chulalongkorn University**, Bangkok |
| Luengnaruemitchai, Apanee | The Petroleum and Petrochemical College; Center of Excellence on Catalysis for Bioenergy and Renewable Chemicals, **Chulalongkorn University**, Bangkok |
| Koonthongkaew, Jirasin | Department of Microbiology, Faculty of Sciences; Research Unit in Bioconversion/Bioseparation for Value-Added Chemical Production, **Chulalongkorn University**, Bangkok |

Four authors, one institution. Koonthongkaew is last author and the BCAT specialist of the group,
so the slug `FIRST_BATCH.md` R1 guessed at is confirmed: **`group:koonthongkaew-chulalongkorn`.**

### Do the two papers share an author? **No.**

`{Hammer, Avalos}` ∩ `{Thammapanyaphong, Boonyanuwat, Luengnaruemitchai, Koonthongkaew}` = ∅. No
shared institution either: Princeton, New Jersey against Chulalongkorn, Bangkok; no shared
department, centre or corresponding address. The papers are nine years apart, and the Thai group
cites the Princeton one as prior literature (*"Hammer and Avalos (2017) demonstrated that deletion
of the BAT1 gene is the most effective approach to improve isobutanol productivity"*, `[21327,
21465)`). **Citing is not collaborating** — it is the second group deliberately testing the first
group's finding in a background the first group never touched, which is the strongest form the
J.3 axis-2 count can take. Independence holds, and with it the L2.

### The near miss that would have broken it

A third paper in the corpus carries `BAT1` spans and looks, from the DOI alone, like a third
group: `doi:10.1186/s13068-019-1560-2` (PMID 31548865, *Xylose utilization stimulates
mitochondrial production of isobutanol…*). Its authors are **Zhang Y, Lane S, Chen J-M, Hammer
SK, Luttinger J, Yang L, Jin Y-S, Avalos JL** — Princeton and UIUC, senior author Avalos, with
Hammer on both papers. **It is `group:avalos-princeton`.** Counting it as a third group would
promote this assertion on a repeat rather than a replication, which is the precise failure J.3
exists to prevent. It is recorded here so that the next person to find it does not have to
rediscover it.

---

## 4. The proposal

### L2-1 — BAT1 affects isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:017a897a1a9054c2` |
| subject | `gene_group YAA:GG:yhr208w` (BAT1 / YHR208W, species scope) |
| predicate | `affects_production_of` |
| object | `product YAA:PRODUCT:isobutanol`, `product_id` the same |
| direction | `increases` — see the owner decision in §6 |
| context_id | NULL — the two experiments share no `condition_context` row, and the claim is not condition-specific |
| effect_size | NULL, and the CI/unit/n columns with it |
| zone | `R` |
| confidence | `medium` |
| expected level | **L2**, basis `direct_evidence_replicated` |

`affects_yield_of` was rejected for the same reason as in the first batch: both cited numbers are
titers or fold-changes in titer, not yields. `improves_when_modified_by` remains structurally
impossible — `assertion.object_type` has no `modification` value. `is_bottleneck_for` was
genuinely tempting, because the Chulalongkorn paper calls Bat1 *"the rate-limiting and bottleneck
enzyme that limits isobutanol productivity"* in as many words, and it would sidestep §6's sign
problem entirely by leaving `direction` NULL. It was not used because the evidence offered is two
titer comparisons, which measure *how much isobutanol*, not *where the flux is limited*;
`is_bottleneck_for` is a claim the atlas's `bottleneck` table should carry with its own evidence.
`competes_with` is the most mechanistically accurate description of Bat1 (it drains KIV to valine)
and is not supported by these two measurements either.

#### Evidence item E1 — `group:avalos-princeton`

| | |
|---|---|
| evidence id | `YAA:EV:a3092a401c302d0c` |
| evidence_type | `direct_perturbation` |
| independent_group | `group:avalos-princeton` |
| strain / control | `YAA:STRAIN:shy24` (bat1Δ, CEN.PK2-1C) / `YAA:STRAIN:shy23` (wild-type control) |
| measurement | `YAA:MEAS:1e8f45029502a6d4` — 14.2, `fold_increase_in_isobutanol_production` |
| span | `YAA:SPAN:9a52a8dc28ef4afc9dfd74dd94f410a6`, `[31365, 31429)` |
| direction | `increases` |
| publication | `doi:10.1016/j.ymben.2017.10.001` |

**Why the comparator is real.** The control is named in the sentence before, in the same figure
panel: *"When BAT2 is deleted in CEN.PK2-1C (SHy25) isobutanol production (35 ± 12 mg/L) remains
approximately the same as in the wild type control (42 ± 11 mg/L), (SHy23), (Fig. 3b). **However,
deletion of BAT1 (SHy24) results in a 14.2-fold increase in isobutanol production**"*. SHy23 is
the wild type of the same series, measured in the same 48-h high-cell-density fermentation.
SHy23's 42 mg/L is itself already a promoted row, `YAA:MEAS:dc0d5fef6b42e641`.

**Why this measurement and not SHy24's titer.** SHy24 has exactly one promoted titer, 122 mg/L
(`YAA:MEAS:e52fb6b66fa8d889`), and it is from the **valine-fed** condition — the text at `[33624,
33798)` reads *"In the presence of valine, isobutanol titers of bat1Δ strains are substantially
decreased by as much as 80% to 269 ± 16 mg/L and 122 ± 8 mg/L with (SHy16) and without (SHy24)"*.
Citing it would attach a +valine number to a claim the authors state for valine-free medium
(*"with valine removed from the media, we observe an unprecedented 14.2-fold increase in isobutanol
production in CEN.PK2-1C upon deletion of BAT1"*, `[47942, 48087)`). The 14.2-fold row is the valine-free comparison and is the number the paper's own
abstract leads with.

#### Evidence item E2 — `group:koonthongkaew-chulalongkorn`

| | |
|---|---|
| evidence id | `YAA:EV:405403e8e4094f4a` |
| evidence_type | `direct_perturbation` |
| independent_group | `group:koonthongkaew-chulalongkorn` |
| strain / control | `YAA:STRAIN:iboh-1bat1` (CRISPR bat1Δ) / `YAA:STRAIN:iboh-1` (isogenic parent) |
| measurement | `YAA:MEAS:e02f80aee1c3706c` — 0.866 g/L titer |
| span | `YAA:SPAN:3d8e0f0e20774354aea1f0562f2741a8`, `[27209, 27324)` |
| direction | `increases` |
| publication | `doi:10.1016/j.btre.2026.e00959` |

**Why the comparator is real.** §2. IbOH-1 is IbOH-1bat1Δ minus the CRISPR deletion and nothing
else, and its isobutanol was measured in the same figure as the test strain's (Fig. 4, N.D.).

**Why the 0.866 g/L row and not one of the other three.** The paper reports four promoted titers
for IbOH-1bat1Δ: 0.215 g/L (YPD, 100 g/L glucose), **0.866 g/L (YNB, 100 g/L glucose)**, 1.001
g/L (YNB, 150 g/L glucose) and 2.016 g/L (best shake flask). YNB is *"minimal YNB medium devoid of
valine"* (`[26887, 27004)`), which makes 0.866 g/L the item whose condition is closest to the
valine-free condition E1 cites. That concordance of condition is a bonus, not a requirement — the
claim is a direction, and every one of the four exceeds a non-detect.

**A caveat that does not change the direction.** IbOH-1 is a UV mutagenesis product, and its own
BAT1 already carries a C320T / I107T substitution. The authors test whether that mutation alone
suffices and report that it does not (isobutanol below quantification in both G2-3-2 and IbOH-1),
which is *why* they deleted the gene. So E2's contrast is `bat1Δ` against a *hypomorph-or-neutral*
BAT1 allele rather than against a textbook wild type. That makes E2's effect size unquantifiable
here — another reason no `effect_size` is proposed — and leaves `increases` untouched.

#### Evidence item E3 — optional, same group, second background

| | |
|---|---|
| evidence id | `YAA:EV:11d04fe1b54ece5c` |
| independent_group | `group:avalos-princeton` — **the same group as E1** |
| strain / control | `YAA:STRAIN:shy104` (bat1Δ, BY4741) / `YAA:STRAIN:shy99` (wild type) |
| measurement | `YAA:MEAS:d33a41cb54d11bf7` — 8.8, `fold_increase` |
| span | `YAA:SPAN:a6773db939f44975b6b8dbe80faf4b6a`, `[48310, 48355)` |

Offered, not urged. It adds a third genetic background (BY4741 alongside CEN.PK2-1C and the
industrial isolate) and therefore strengthens J.3's `n_organisms` / `n_condition_classes` axis —
but it adds **no group**, and the rehearsal in §5 confirms the level is L2 with or without it. It
is listed so the owner can see that adding it is safe rather than wondering.

---

## 5. The rehearsal, and what the view actually said

The live atlas was copied into a `:memory:` database with `sqlite3.Connection.backup`, so the
rehearsal walks the five existing L1s as well as the new row. `build_assertion` ran there as
curator `kangkon`, kind `human`. The level was read out of `assertion_level`, never chosen.

| # | what was built | `n_evidence` | `n_direct` | `n_direct_groups` | level from the view | `derived_reason` |
|---|---|---|---|---|---|---|
| **A** | **E1 + E2 — the proposal** | **2** | **2** | **2** | **L2** | **`direct_evidence_replicated`** |
| B1 | E1 alone (Princeton only) | 1 | 1 | 1 | L1 | `direct_evidence` |
| B2 | E2 alone (Chulalongkorn only) | 1 | 1 | 1 | L1 | `direct_evidence` |
| B4 | E1 + E2, both mislabelled `group:avalos-princeton` | 2 | 2 | **1** | **L1** | `direct_evidence` |
| B6 | E1 + E3 + E2 | 3 | 3 | 2 | **L2** | `direct_evidence_replicated` |
| B7 | E1 + E2 with E2's direction flipped to `decreases` | 2 | 2 | 2 | **L1** | `direct_evidence` |

`plan_assertion` returned `ready = True` with empty `missing`, `blockers` and `warnings` for A,
B1, B2, B4 and B6, note `ready to write assertion YAA:ASSERT:017a897a1a9054c2 with N evidence
item(s)`.

**B4 is the row that matters.** It is the *same two experiments, the same two papers, the same
two numbers* — and it grades L1, because the only thing that changed is the string in
`independent_group`. That is J.3's second axis doing the entire job, and it is the first time the
atlas has had two direct evidence items on one assertion for it to do the job on.

**B5** — E2 with `independent_group = None` — is refused before it is written:

```
plan.ready = False
  evidence[1].independent_group: PLAN.md J.3 counts independence by group, not by publication,
  because one lab publishing three times is not three independent observations. […]
```

**B3, the path this will actually take.** The owner is not obliged to write both items at once.
Built as E1 alone and then extended with `attach_evidence(E2)`:

```
after build_assertion  : level='L1'  basis='direct_evidence'
after attach_evidence  : level='L2'  basis='direct_evidence_replicated'
assertion row after    : {'direction': 'increases', 'created_by': 'kangkon', 'zone': 'R'}
```

The assertion row is byte-identical before and after. Nothing recomputed a level, because there
is nowhere a level is kept. PLAN.md J.1's "an assertion is never edited" and J.3's "the level is a
view, not a column" are the same sentence seen from two ends, and this is the first time the atlas
has demonstrated it.

### PLAN.md J.5's walk

Over the whole rehearsal atlas — the five existing L1s plus L2-1:

```json
{"n_walked": 6, "n_closed": 6, "n_broken": 0, "breaks": {}, "exit_code": 0}
```

Narrowed to the new assertion alone:

```json
{"n_walked": 1, "n_closed": 1, "n_broken": 0, "breaks": {}, "exit_code": 0}
```

Both evidence items close the literature arm through `span → publication`; the analysis arm is not
involved, so the known `dataset_unreachable` gap does not arise. `exit_code` 0, not `EXIT_VACUOUS`.

### The live atlas, re-counted afterwards

`assertion` = 5, `evidence_item` = 5. Unchanged.

---

## 6. What is the owner's, not mine

### 6.1 The sign convention on `assertion.direction` — the real decision

The five existing assertions have `subject_type = modification`, so `direction = 'increases'`
reads correctly: *the deletion increased the titer*. L2-1's subject is the **gene**, and the same
value now reads *"BAT1 increases isobutanol production"*, which is the opposite of what both
papers found. The two readings of the column are:

* **(a) "the direction the perturbation moved the product"** — `increases`. Consistent with the
  five rows already written and with `evidence_item.direction`, whose own documented meaning in
  `assertions.py` is *"the comparison against the control"*, and the comparison is test > control.
  Drafted above.
* **(b) "the direction of the subject's own effect"** — `decreases`, the standard reading when the
  subject of an `affects_*` predicate is a gene. Reads correctly in a UI. Costs a re-reading of
  the five existing rows, and changes this assertion's id to `YAA:ASSERT:893939228cea1ef4`,
  because `direction` is in `identity()`.

**Both were rehearsed, and the level is L2 either way.** `assertion_level` never reads
`assertion.direction`; it counts `COUNT(DISTINCT e.direction)` over the *evidence* rows only. So
this is a display and semantics decision, not a level decision, and it can be settled without
anything being at stake for the grade.

One finding for whoever owns `src/`: under (b) the planner emits, on **both** items,
*"the derived level will not reach L2 while both stand"* — and the view then returns **L2**. The
warning is accurate when the evidence items disagree with *each other*; it is misleading when they
all agree with each other and merely differ from the assertion's own sign. Reported, not fixed;
`src/` is not mine this session.

### 6.2 The two group slugs

`group:avalos-princeton` and `group:koonthongkaew-chulalongkorn`. The affiliation evidence is in
§3 and the independence claim is explicit there. These become permanent keys in
`COUNT(DISTINCT independent_group)`, and `group:avalos-princeton` will also have to be the slug on
`doi:10.1186/s13068-019-1560-2` when that paper is asserted on.

### 6.3 Whether E3 is included

Safe either way (§4, §5 B6).

### 6.4 Whether `subject_type = 'gene_group'` or `'gene'`

§1 argues for `gene_group` on assembly grounds. Note the zone asymmetry it creates:
`YAA:GG:yhr208w` is Zone H while `YAA:GENE:gcf-000146045-2-yhr208w` is Zone R. CONVENTIONS.md
permits a Zone H row to support a conclusion, and `assertion_level` does not read zone at all, so
nothing is at risk — but it is the first assertion in the atlas whose subject is not Zone R, and
the owner should know that before it is the precedent.

---

## 7. Curation tasks this turned up, none of them mine to do

1. **`YAA:STRAIN:iboh-1`'s non-detect is uncurated.** Fig. 4 of `doi:10.1016/j.btre.2026.e00959`
   measures it and reports N.D. `measurement` has `is_below_lod`, `detection_limit` and
   `is_upper_bound` for exactly this. Curating it would put the control's number in the atlas
   rather than only in this document, and would let a future `effect_size` be computed as a lower
   bound. It does **not** block L2-1.
2. **The 17 queued `modifications` proposals on the Princeton paper** await review. Two of them
   are the `bat1Δ` rows the atlas has never had: `modifications[6]` (SHy24, CEN.PK2-1C,
   span `[31339, 31364)` *"However, deletion of BAT1"*) and `modifications[16]` (SHy104, BY4741,
   span `[48197, 48223)` *"Deletion of BAT1 in BY4741"*). The other fifteen are the ILV
   overexpressions, the *bat2Δ*, the *ilv6Δ*, the mitochondrially-targeted ARO10/LlAdhA^RE1 pair
   and the BAT1 complementation plasmid.
3. **`FIRST_BATCH.md` R1 should be re-read**, not because it was careless but because its refusal
   is now answered (§2). If R1 is still wanted as a `modification`-subject L1 on the Chulalongkorn
   paper, it is writable today with `control_strain_id = YAA:STRAIN:iboh-1`.
4. **The `bat1Δ`/`bat2Δ` strains in `doi:10.1186/s13068-019-1486-8`** — JWY05, JWY06, JWY07 carry
   `Δbat1`, `Δbat2` and `Δbat1 Δbat2` in their curated genotype spans, with no promoted titers and
   no `modification` rows. If those titers were curated, `group:boles-goethe-frankfurt` would
   become a **third** independent group on this same assertion. The view has no L-above-L2 for
   direct evidence, so it would not change the grade — but `n_direct_groups = 3` is the number a
   reader should see.
