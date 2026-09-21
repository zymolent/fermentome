# Which route to build first — the phase 3.5 recommendation

**Draft, 2026-09-21. Re-checked and re-seated 2026-09-22.** Written against
`MITOCHONDRIAL_PROGRAM.md` §5, which asks for five answers and a written recommendation, and whose
acceptance criterion is: *"the recommendation is one page, every claim in it opens an evidence
chain, and the alternative it rejects is stated with the reason."*

**Status of the evidence chains, stated first because it qualifies everything below.** The v1 of
this document said every claim opened onto a span-verified quote in a draft YAML rather than onto
an `assertion` row, because `assertion` read 0. It now reads **6** — five L1 and one L2 — and
`fermdb query traceability` closes all six. So the caveat has been replaced with a count.

Of the **21 substantive claims** below, audited one by one in
[`PHASE_3_5_EVIDENCE_AUDIT.md`](PHASE_3_5_EVIDENCE_AUDIT.md):

* **2 can be re-seated onto an assertion today.** Q1, and a *correction* to Q2 — both drafted, both
  rehearsed in an in-memory copy, both returning **L5** from `assertion_level` with a closed J.5
  chain. Marked **[assertable · L5]** below. Nothing has been written; `build_assertion` refuses an
  agent.
* **7 are blocked on one missing curation step** — a `span` row. The mitochondrial papers are all
  in `publication`; not one of them has a single span, and `literature_assertion` requires one.
  The quotes already exist with verified offsets. Marked **[draft — needs a span row]**.
* **7 cannot be assertions at all**, and that is a property of the model rather than a backlog.
  Marked **[draft — not assertable]** with the reason. Three kinds: a claim whose subject is *the
  corpus* rather than a row (Q1.1, Q2.2, Q4, Q5 — "nobody has measured this" cites an **absence**,
  and every one of `evidence_item`'s seven types can only cite something that exists); a claim
  about a row in a table `assertion.subject_type` cannot name (Q3 — `mtdna_locus` is not one of the
  eleven); and one claim no column can express (Q2.5 — `part` has `sequence` but no topology).
* **5 are not biological claims at all** — two properties of the ranker, two citations of other
  documents in this repo, one count of a draft file. They open a chain; it is just not a J.5 one.

**Two of twenty-one is the honest number** and it is stated rather than rounded up. Nine is the
reachable number. The remaining chains are unchanged: real, re-resolvable, and one hop short of the
form the plan specifies.

---

## The recommendation

> **Build strategy C — the matrix-targeted Ehrlich pathway — and hold strategy E in reserve
> pending a single import measurement.** Do not open an mtDNA-engineering campaign now.

This is one of the two conclusions §5 names as defensible in advance. It is reached because the
trigger condition for E is **predicted not to fire**, and because E carries an unmeasured risk that
would be discovered late and expensively.

---

## Why the atlas's own ranker says something else, and why that is not a contradiction

`fermdb atlas routes` returns **`B_cytosolic_relocalization`** in its top five. This recommendation
says **C**. Both are correct, because they answer different questions, and the difference is
recorded in the code rather than papered over:

* `rank(objective="easiest")` — the default — orders by transport gaps, then cofactor risks, then
  **feasibility**, and B beats C there on a technique-difficulty constant (0.80 against 0.60). It
  answers *what would be least trouble to build*. B genuinely is easier, and that is real
  information, not an artifact.
* This recommendation answers *what should be built for DUET*, which technique difficulty cannot
  reach.

**Three independent lines now agree on C**, which is worth stating because only one of them is new:

1. `DUET_TARGET.md` §4, written before any of this curation: *"**DUET is strategy C** — mitochondrial
   targeting of the Ehrlich pathway by nuclear-encoded, presequence-targeted enzymes."*
2. `MITOCHONDRIAL_PROGRAM.md` §1's standing advice, which recommends running C **first**, for the
   same stated reason — it avoids the cytosolic Fe-S maturation problem and has precedent.
3. The corpus evidence assembled here (Q2 below), which says C's failure mode is unlikely to fire.

So the recommendation is not the atlas overruling itself. It is the atlas being asked the question
it was built to answer, rather than the one its default sort answers.

**The reconciliation, as of 2026-09-22, re-verified live.** `rank(objective="programme")` consults
`programme_fit` before feasibility. The owner's ruling is to **favour C while retaining everything
on B**, so that B stays available as data accumulates. `programme_fit` is a **sort key and never a
filter**, so no B route is dropped, hidden or down-weighted out of view — the ordering changes and
the population does not. `--objective easiest` continues to give the unbiased view, byte for byte.

```
easiest    -> rank 1  B_cytosolic_relocalization   feasibility 0.80   programme_fit 0.70
programme  -> rank 1  C_mitochondrial_ehrlich      feasibility 0.60   programme_fit 1.00
```

> **This is not a fourth line of agreement, and it must not be read as one.**
> `PROGRAMME_FIT["C_mitochondrial_ehrlich"] = 1.00` is a constant somebody typed in to record the
> owner's ruling. The ranker returning C under `--objective programme` is *this recommendation's
> own conclusion read back out of a table it was written into*. It is a correctly implemented sort
> key and it is zero evidence for C. The three lines above remain three.

---

## The five answers

### Q1 — Is matrix co-localization beneficial at all? *Provisionally yes, and it is now testable.*

**[assertable · L5]** This is the one answer the atlas already holds a promoted Zone R row for.
`YAA:BNK:e86745216bd648b4`, node *"compartment choice for the Ehrlich pathway"*, from
`doi:10.1186/s13068-019-1560-2`, span `YAA:SPAN:f2b5b7f8…` `[9450, 9620)`:

> This so-called mitochondrial isobutanol pathway boosts the production of branched-chain alcohols,
> relative to overexpressing the same enzymes in their native compartments

Drafted as `compartment mitochondrial_matrix` — `affects_production_of` → `product isobutanol`,
`increases`; rehearsed at **L5**, `hypothesis_or_insufficient_support`, J.5 walk closed
(AUDIT §2, D1).

**It could be L1 and is not, for a stated reason.** The same claim carrying the YZy165-vs-Y58
perturbation grades **L1** and `plan_assertion` returns `ready = True` — but Y58 has no isobutanol
pathway at all, so that contrast is *pathway against no pathway*, not *matrix against cytosol*.
That is `FIRST_BATCH.md` R3's failure in a new paper, and it is refused. The cytosolic comparator
the paper actually ran is uncurated; curating it converts Q1 to L1 in one `attach_evidence` call.

**[draft]** The supporting count, corrected: `host_resolution.yaml` holds **14**
`pathway_configuration` proposals across **four** publications — 4 `promote`, 1
`promote_pending_vocabulary`, 9 `reject` — several explicitly `C_mitochondrial_ehrlich`. (v1 said
13 across three, 8 sound; `HOST_RESOLUTION.md` has a section headed *"There are 14 proposals, not
13"*.) Until they are promoted and phase 3's recall test runs, the *breadth* of this answer rests
on the literature rather than on the atlas's own ranking.

### Q2 — Is strategy C import-limited? *Predicted no. This is the load-bearing answer.*

§1 sets the trigger precisely: *"E becomes justified precisely when C works but is import-limited."*

The allotopic-expression table is the mirror of that question — 16 relocation attempts, and **every
import failure in the corpus is a failure to translocate a transmembrane helix.** The ordering is
monotone in hydrophobicity: Var1 (0 TM, soluble) fully rescued; bI4 (0 TM) fully rescued; Atp8
(1 TM) fully rescued; Cox2 (2 TM) partial, and only with hydrophobicity-lowering substitutions;
Atp9 (2 TM, proteolipid) fails outright, degraded by i-AAA; cytochrome *b* (8 TM) "entirely
unsuccessful, in any organism". A chimera replacing **one** helix with a less hydrophobic one
converted an undetectable protein into a processed one — a causal handle, not a correlation.

**DUET's KDC and ADH are soluble matrix enzymes with no transmembrane helices.** Var1 — the only
soluble mtDNA-encoded product — relocated to full function with nothing but recoding and the COX4
presequence, which is specifically the MTS that *fails* for hydrophobic cargo. Every mechanism
invoked for the failures requires a helix to stall on.

**This is a prediction, not a measurement**, and it is exactly the kind the atlas was built to
produce. **[draft — needs a span row]** for the allotopic table's rows; **[draft — not
assertable]** for *"every import failure in the corpus is a failure to translocate a helix"*, which
is a property of a 16-row table and has no subject the atlas can name. *Chain:*
`docs/drafts/mitochondria/allotopic_expression.yaml`.

> **[assertable · L5] The counter-evidence, which v1 of this document did not cite.** The atlas
> holds a promoted Zone R bottleneck, `YAA:BNK:431c48b1e633a585`, node **"mitochondrial protein
> import"**, from `doi:10.1016/j.meteno.2016.03.004` — a paper that matrix-targeted a heterologous
> enzyme in *S. cerevisiae* with the Su9 presequence. Span `YAA:SPAN:94c4772c…` `[17210, 17484)`:
>
> > this targeted expression **dramatically reduced the amount of functional protein** as
> > visualized by the reduced green fluorescence, which may be due to the high energy cost involved
> > in translocating proteins across the mitochondrial membranes and their folding within the matrix
>
> Drafted and rehearsed at **L5** (AUDIT §2, D2). **Read in context it does not overturn Q2 — it
> quantifies the toll and then confirms the prediction.** The comparator is *"constructs lacking
> the mt leader"*, i.e. the cytosolic version of the same five-gene *P. aeruginosa* cargo, and the
> same paragraph continues: *"Despite this penalty, however, mitochondrial expression well above
> background was observed for **each construct**, with fluorescence approaching roughly half that
> of the positive mitochondrial fluorescence control"* — and *"the effects of this energy penalty
> do not appear to be exclusively correlated with protein size"* (acd1, 42.6 kDa, weak; lpdV,
> 48.6 kDa, comparable in both compartments). Every soluble cargo got in. The cost is energetic
> rather than topological, size is not the variable, and the paper's own title reports that
> targeting *increased specific activity*. That is Q2's prediction with a price tag attached, and
> the price tag is the part this document was missing.
>
> It belongs in the chain rather than out of it: Q2 is the load-bearing answer, and this is the one
> curated row in the atlas that speaks to it directly.

*If C ever does prove import-limited:* import proxies rose 6%→12% of WT Cox2p for the original
construct and to **85%** after two residue changes, while expression tuning bought ~40%. **Screen
enzyme variants, not promoters.** **[draft — needs a span row]**

### Q3 — Which locus and leader, and what does it displace? *`intergenic_upstream_COX2`.*

**[draft — not assertable]**, and it is the clearest case in this document of *the row exists and
the assertion model cannot point at it.* The activator map covers all 8 protein-coding loci plus
one non-displacing intergenic site, and is **loaded as 9 Zone R `mtdna_locus` rows** — verified.
`YAA:MTLOCUS:intergenic-upstream-cox2` carries `displaced_if_used = NULL` and
`respiration_retained_if_used = 1`: it borrows COX2's 5′ leader and **displaces nothing**, the
single most consequential fact in the map, stated by a column.

`assertion.subject_type` is a closed set of eleven tables and `mtdna_locus` is not one of them.
There is no near-miss to coerce to — mapping a locus onto `gene_group YAA:GG:…cox2` would assert
about *COX2 the gene* what is true of *the silent region upstream of it*, which is the exact
distinction the row exists to record. AUDIT §3.2 sets out the two options, both the owner's.
*Chain:* `data/mitochondria/activator_map.yaml` → `mtdna_locus`, which is a **better** chain than
most of this document's: it ends in a Zone R row rather than a file.

### Q4 — Has any soluble heterologous enzyme of this class been made from mtDNA? *Barely.*

**[draft — not assertable]** Five precedents plus one documented failure. §5 predicted a thin
answer and said *"the size of the gap is the size of the risk."* The gap is large.
*Chain:* `data/mitochondria/heterologous_orf_precedents.yaml`.

A count of precedents has no subject in the atlas and no source to cite — its content is the size
of a set, not a finding of a paper. The schema's answer to this shape is `knowledge_gap` (212
rows, `kind = 'never_attempted'`), which `MITOCHONDRIAL_PROGRAM.md` §2.3 already names as where the
Arg8ᵐ precedent should hang. That is the right home for it, and it is not an assertion.

### Q5 — Does the insert stay? *Nobody has measured it. That is worse than "unknown".*

**[draft — not assertable]**, for the same reason as Q4 and more sharply. *"Zero papers have
followed a heterologous mtDNA ORF over generations"* cites an **absence**, and every one of
`evidence_item`'s seven types requires a row, a span, a run or a model output that exists. There
is no way to cite a search that returned nothing. This is a real limit of the assertion model,
recorded rather than worked around.

* **Zero papers have followed a heterologous mtDNA ORF over generations** — not sfGFPm, not
  mtnLuc, not GFPβ1-10, with or without selection.
* **Both neutral-site precedents do not measure retention at all.** "Stable" appears in them only
  about nanoluciferase denaturation and sfGFP folding. They are not weak stability evidence; they
  are not stability evidence.
* A CRISPR-inserted element is **undetectable within ~30–40 generations** without selection.
  Production is non-selective and 30–40 generations is a seed train.
* Background **ρ⁻ formation runs 0.1–1% per generation on glucose**, compounding over a seed train
  into the loss of precisely the copy-number advantage §1 sells.
* A cider strain in wort for 150 generations lost the whole mitochondrial genome in one clone of
  three, and cut 82 kb to 5 kb in two others.

*Chain:* `docs/drafts/mitochondria/stability_heteroplasmy.yaml`.

---

## The alternative, and why it is rejected

**Rejected: open the mtDNA campaign now (strategy E).** Not because it is infeasible — Q3 gives a
locus and a leader, and Q4 gives precedents. It is rejected because **Q2 says its trigger condition
is unlikely to fire and Q5 says its central risk has never been measured by anyone.** Committing a
twelve-month campaign on that footing is the precise failure §5 names: *"starting a twelve-month
mtDNA campaign because it sounded compelling, without checking whether the cheap experiment already
answers the question."*

---

## Three findings that change the build even though nothing asked for them

**All three are [draft — needs a span row].** Their papers are in `publication`; none has a `span`
row, and `literature_assertion` requires one. Two of the three already have their *subject* in the
atlas — `YAA:GG:yjr016c` (ILV3) with `ISU1`/`NFS1`/`YFH1` for the Fe-S machinery, and
`YAA:GG:ylr355c` (ILV5) — so promoting the quotes is the whole remaining distance. The third is
about a `mtdna_locus` column and is blocked structurally, like Q3.

1. **The M3 answer solves for the wrong variable.** M3 treats *respiration* as what is at stake.
   The corpus says the causal variable is **membrane potential**, and the two come apart: ρ⁰ cells
   hold a residual ΔΨ only by hydrolysing glycolytic ATP through a reversed F1-ATPase — a permanent
   yield tax nobody costs. Matrix protein import depends on ΔΨ, and Fe-S cluster biogenesis depends
   on import. **Ilv3 (DHAD) is an Fe-S enzyme in the matrix — the same compartment as the lesion.**
   So "we ferment anaerobically, so respiration is free" answers the wrong half of the question.
   The controls are clean: *CAT5*/*RIP1*/*COX4* deletions abolish respiration with mtDNA intact and
   cause no comparable defect, and a ρ⁰ strain carrying *ATP1-111* (higher ΔΨ, non-respiring) shows
   no crisis. **Ilv3 in a ρ⁰ strain has never been measured** — every ρ⁰ Fe-S result in the corpus
   scores *cytosolic* clients. One DHAD assay, or a DHIV/2-KIV ratio, in a ρ⁰ vs isogenic ρ⁺ pair
   settles it.
2. **Ilv5 is an mtDNA nucleoid packaging protein, not only a KARI.** One paper replaced matrix Ilv5
   with a mitochondrially-targeted bacterial KARI and got a **166-fold petite frequency** against a
   1–5% baseline, then abandoned the strain as an "irreversible fitness defect". The cytosolic
   version of the same swap did not do it. A second isobutanol paper looked and did not find it.
   Both recorded, neither resolved — and the NADH-preferring KARI swap is the atlas's
   highest-priority de-risking part, so this is directly on the critical path.
3. **`respiration_retained: false` is a stability field, not only a metabolic cost.** One paper,
   one cargo, one medium, one variable: at a neutral site ARG8 is not counter-selected; displacing
   an OXPHOS gene it is purged, >80% of fifth-generation colonies carrying WT mtDNA only — **on
   glucose, where respiration is dispensable.** A second, independent argument for the intergenic
   site that `activator_map.yaml` does not currently make.

---

## Re-checked against everything that has landed since — the recommendation stands

Three things arrived after this was drafted. Each was tested against it. **None flips it, one
sharpens it, and one of the three turns out not to be evidence at all.**

### 1. 320 routes close the mitochondrial matrix — *and none of them is strategy C*

Re-verified live at HEAD, independently of the acceptance doc and the commit message:

| strategy | routes | matrix-closing |
|---|---|---|
| `A_native_split` | 1280 | **320** — all carrying **Adh3**; 128 with Pos5 + a matrix NADPH-KARI, **192 with an NADH-preferring KARI and no Pos5 at all** |
| `B_cytosolic_relocalization` | 1280 | 320 |
| `C_mitochondrial_ehrlich` | 1280 | **0** |
| `D_alternative_compartment` | 1280 | 320 |
| `E_mtdna_encoded` | 1280 | **0** |

The two mechanisms in the brief are confirmed exactly. Three corrections travel with them: it is
320 of **6,400**, not of 600 (the 600 stored `pathway_route` rows are stale, still claiming
`balance_status = 'pass'` on every row while the live enumerator returns `fail` on all 6,400);
`ACCEPTANCE.md` says 240 and commit `5519874` says 480, both predating `57062ce`; and closing the
matrix does not make a route balanced — the 320 are the routes whose residual imbalance is
cytosol-only.

**The finding the brief did not name is that C never closes the matrix, in any of 1280
combinations.** C puts the KDC and the ADH in the matrix too, so the matrix ADH opens a bucket the
valine branch does not close; C comes back `matrix NADH short by 1`, `short by 2`, or short on both
carriers. The configuration that closes the matrix 320 ways is **A**, which is not what this
document says to build.

**It does not overturn the recommendation, and the reason is itself evidence.** The atlas holds a
curated Zone R measurement of a *working* strategy C strain — `YAA:STRAIN:yzy165`,
`YAA:MEAS:00c28a4e45d96802`, 162 mg/L, sevenfold over its parent, `CoxIVMLS-ARO10` and
`CoxIVMLS-LlAdhA_RE1` in the matrix. A Zone I enumerator saying C's matrix cannot balance, against
a Zone R measurement saying a C strain made isobutanol, is the enumerator being wrong about
something — most plausibly that the parts catalog holds no part for the matrix NADH a real strain
draws from ethanol oxidation and the TCA cycle. CONVENTIONS.md's zone ordering settles which one
yields.

**What it changes is the shape of the risk, and this is a genuine gain.** The enumerator names a
specific, quantified liability of C that A does not have — **matrix NADH short by one to two per
isobutanol** — and names the lever that closes it in the A routes: Adh3, matrix-side. That is a
sharper statement of C's cofactor problem than anything else in this document, and it is now the
second thing to instrument alongside import.

### 2. The slot 6 paper's adverse prediction about DUET

`doi:10.1016/j.mec.2024.e00245` (PMID 39072283) reports that Pos5 overexpression helps during the
glucose phase, **loses the gain past ~24 h**, and is net negative over the whole fermentation when
combined with `ZWF1*`. Its stated mechanism, `[59028, 59192)`, verified exact:

> A likely reason is a decrease in the NADH/NAD+ ratio by one order of magnitude after the diauxic
> shift (), which would decrease the substrate availability for Pos5.

Note the paper's own hedge — *"A likely reason"*. Two caveats travel with it and neither is
optional: its Pos5 is **cytosolic** (residues 1–17, the targeting sequence, deleted) and the
collapsing pool it reports is the *cytosolic* NADH/NAD⁺ ratio, while DUET wants Pos5 in the
matrix; and the order-of-magnitude figure is **cited from others, not measured** — no cofactor of
any kind is measured in that paper. It is capped at L3 in the admissions layer, `verified` false.
In the atlas it is a `publication` row, two `screening_record` rows and one `fulltext_asset`:
**zero spans, zero measurements**, so it is not assertable today either.

**It is adverse to Pos5, not to C — and the hedge was already enumerated.** 192 of the 320
matrix-closing routes carry **no Pos5 at all**, closing the matrix with an NADH-preferring KARI,
which is PLAN.md B.3.5's named de-risking part. The corpus produced an adverse prediction about one
component and the route enumerator had already enumerated its replacement. That is the atlas
working, and it is the strongest test this recommendation has been put to.

What it changes is priority: the NADH-KARI arm stops being an alternative and becomes **the
hedge**, and Q2's heuristic generalises — *screen the KARI, not the NADH kinase*, and certainly not
the promoter. It also adds a fourth cheap experiment.

### 3. `programme_fit` ranks C first — which is not evidence

Covered above: the constant was typed in to record the ruling this document argues for. It is a
correctly implemented sort key and it confirms nothing. Counting it would be this document citing
itself through a table.

---

## What would change this recommendation

* A direct measurement that strategy C **is** import-limited in the production chassis. That is
  Q2's trigger and it flips the conclusion.
* A retention measurement showing a heterologous mtDNA ORF holds over a seed train without
  selection. That would convert Q5 from an unmeasured risk into a costed one.
* **New:** a matrix NADH measurement showing that C's enumerated matrix deficit is real in a
  working strain rather than an artefact of the parts catalog. That would not send the programme to
  E — it would send it to A, which is a different and cheaper answer than the one this document
  rejects.

## Four cheap experiments, in priority order

1. **DHAD activity (or DHIV/2-KIV ratio) in a ρ⁰ vs isogenic ρ⁺ pair.** Settles whether the matrix
   Fe-S lesion touches the isobutanol pathway. Mechanistically strong, empirically open.
2. **ρ⁻ fraction of a pPT24 strain.** Its duplicated *COX2* 5′ UTR is under the same question that
   made the second neutral site produce ~60% ρ⁻/ρ⁰ cells, and **nobody has reported this number.**
   Cheap, specific, and it gates the site choice.
3. **Insert retention over ~40 generations without selection.** The measurement no one has made,
   and the one that decides whether strategy E is ever viable.
4. **Matrix NADH/NAD⁺ across the diauxic shift in the production chassis.** New, and it does two
   jobs for one assay: it tests whether the slot-6 prediction transfers from the cytosol to the
   matrix — the only thing standing between the 128 Pos5 routes and the 192 without — and it tests
   whether the enumerator's matrix-NADH deficit for strategy C is real.

## One design rule for the recoder, available today

**96 bp direct repeats delete ~160× faster in mtDNA than the same geometry in the nucleus** — and
homology arms *are* direct repeats. One observed insert deleted through a 44-nt sequence shared
with a flank ~600 nt away. The §2.2 recoder should report internal repeats shared with an insert's
flanks. It does not currently. **[draft — needs a span row]**

---

## Does phase 3.5 meet its acceptance criterion?

**One page** — yes; the audit is a separate document so that being precise about evidence does not
cost the page. **The alternative it rejects is stated with the reason** — yes, unchanged, and the
new evidence tested it rather than weakening it. **Every claim opens an evidence chain** — every
claim opens *a* chain, and 2 of 21 now open onto an `assertion` row.

**So: not yet, and the gap is now measured rather than conceded.** The letter of §5 asks for
chains in the form PLAN.md J.5 specifies. **Seven** claims are one curation step away — a `span`
row for a paper already in `publication`, with the quote and its offsets already verified — and
**seven** can never get there, for three structural reasons this exercise established and AUDIT
§3.1–§3.2 record.

Saying *"7 of 21 claims in the phase 3.5 recommendation cannot be assertions, and here are the
three reasons"* is a more useful output than a document that reached 21 of 21 by weakening its
citations — which AUDIT §3.3 shows is available, rehearses to prove it, and refuses.
