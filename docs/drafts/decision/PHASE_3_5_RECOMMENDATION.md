# Which route to build first — the phase 3.5 recommendation

**Draft, 2026-09-21.** Written against `MITOCHONDRIAL_PROGRAM.md` §5, which asks for five answers
and a written recommendation, and whose acceptance criterion is: *"the recommendation is one page,
every claim in it opens an evidence chain, and the alternative it rejects is stated with the
reason."*

**Status of the evidence chains, stated first because it qualifies everything below.** Every claim
here opens onto a **span-verified quote in a draft YAML**, not onto an `assertion` row — the
`assertion` table still reads 0. So this meets §5's spirit and not yet its letter. The chains are
real and re-resolvable; they are one hop short of the form the plan specifies.

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

**The reconciliation, as of 2026-09-22.** `rank(objective="programme")` consults `programme_fit`
before feasibility. The owner's ruling is to **favour C while retaining everything on B**, so that
B stays available as data accumulates. `programme_fit` is a **sort key and never a filter**, so no
B route is dropped, hidden or down-weighted out of view — the ordering changes and the population
does not. `--objective easiest` continues to give the unbiased view, byte for byte.

---

## The five answers

### Q1 — Is matrix co-localization beneficial at all? *Provisionally yes, and it is now testable.*

The corpus supports matrix targeting as the strategy essentially all published mitochondrial
isobutanol work uses (PLAN.md B.6.2: relocating Ehrlich enzymes into the matrix by adding targeting
sequences). **13 `pathway_configuration` proposals now exist** across three landmark papers, 8 of
them sound, including several explicitly `C_mitochondrial_ehrlich`. Until they are promoted and
phase 3's recall test runs, this answer rests on the literature rather than on the atlas's own
ranking. *Chain:* `docs/drafts/configurations/host_resolution.yaml`.

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
produce. *Chain:* `docs/drafts/mitochondria/allotopic_expression.yaml`.

*If C ever does prove import-limited:* import proxies rose 6%→12% of WT Cox2p for the original
construct and to **85%** after two residue changes, while expression tuning bought ~40%. **Screen
enzyme variants, not promoters.**

### Q3 — Which locus and leader, and what does it displace? *`intergenic_upstream_COX2`.*

The activator map covers all 8 protein-coding loci plus one non-displacing intergenic site, and is
loaded (`mtdna_locus`, 9 rows). The intergenic site borrows COX2's 5′ leader and **displaces
nothing** — the single most consequential fact in the map. *Chain:* `data/mitochondria/activator_map.yaml`.

### Q4 — Has any soluble heterologous enzyme of this class been made from mtDNA? *Barely.*

Five precedents plus one documented failure. §5 predicted a thin answer and said *"the size of the
gap is the size of the risk."* The gap is large. *Chain:* `data/mitochondria/heterologous_orf_precedents.yaml`.

### Q5 — Does the insert stay? *Nobody has measured it. That is worse than "unknown".*

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

## What would change this recommendation

* A direct measurement that strategy C **is** import-limited in the production chassis. That is
  Q2's trigger and it flips the conclusion.
* A retention measurement showing a heterologous mtDNA ORF holds over a seed train without
  selection. That would convert Q5 from an unmeasured risk into a costed one.

## Three cheap experiments, in priority order

1. **DHAD activity (or DHIV/2-KIV ratio) in a ρ⁰ vs isogenic ρ⁺ pair.** Settles whether the matrix
   Fe-S lesion touches the isobutanol pathway. Mechanistically strong, empirically open.
2. **ρ⁻ fraction of a pPT24 strain.** Its duplicated *COX2* 5′ UTR is under the same question that
   made the second neutral site produce ~60% ρ⁻/ρ⁰ cells, and **nobody has reported this number.**
   Cheap, specific, and it gates the site choice.
3. **Insert retention over ~40 generations without selection.** The measurement no one has made,
   and the one that decides whether strategy E is ever viable.

## One design rule for the recoder, available today

**96 bp direct repeats delete ~160× faster in mtDNA than the same geometry in the nucleus** — and
homology arms *are* direct repeats. One observed insert deleted through a 44-nt sequence shared
with a flank ~600 nt away. The §2.2 recoder should report internal repeats shared with an insert's
flanks. It does not currently.
