# Industrial Ethanol & Isobutanol Production Atlas — master blueprint

Status: **blueprint only**, 2026-09-19. Nothing here is implemented. This document exists to be
argued with and cut down before any schema is written.

## 0. How to read this

Sections A–X follow the requested structure. Every major component is described with the same
seven-line block:

| field | meaning |
|---|---|
| **Why** | what breaks without it |
| **Stores** | the data it owns |
| **In** | what it consumes |
| **Out** | what it produces for other components |
| **Connects** | its neighbours |
| **Automate** | what runs without a human |
| **Human** | what must not run without one |

Three conventions used throughout:

* **⚠ marks a number or claim taken from background knowledge rather than from a source read
  during this planning session.** Every one of them must be re-verified against the primary
  literature before it enters the database. This is the same rule `genome-db`'s curator agent
  operates under — *never write `high` confidence from memory* — applied to the plan itself.
* **Zone R / Zone H / Zone I** are the three data zones defined in section D. They are referred
  to constantly; read D.2 before E onwards.
* Anything written as a **decision** is a recommendation with its reasoning attached, not a
  commitment. Section X collects the ones that matter; `docs/reference/OPEN_QUESTIONS.md`
  collects the ones deliberately left open.

---

# A. Project vision

## A.1 What this is

**A decision-support system for engineering *Saccharomyces cerevisiae* to produce isobutanol.**

Not a general fermentation knowledgebase that happens to cover isobutanol. The atlas exists to
answer one operational question repeatedly and defensibly:

> Given what has actually been demonstrated, which route — enzyme set, compartment, cofactor
> strategy, host background and set of deletions — should I build next, and what is likely to
> stop it?

Everything in the design serves that. The atlas returns **ranked, evidence-backed engineering
routes** with their demonstrated outcomes, their known failure modes, the interventions that have
and have not worked on each node, and an explicit statement of what has never been tried. It
distinguishes, always and structurally, what has been measured from what is inferred.

Isobutanol is covered **comprehensively and across all host organisms** — yeast first, but the
bacterial and cyanobacterial isobutanol literature is where most of the pathway biochemistry was
established, and it is ingested at full depth as transferable parts and strategies, not as a
footnote.

Ethanol is covered **narrowly and deliberately**, as a reference layer (B.3). It is not a second
product of interest. It is in the atlas for three reasons only: it is the dominant *competing
sink* at the pyruvate node that isobutanol engineering must defeat; it defines what a
high-performing yeast fermentation looks like; and it supplies the wild-type baselines against
which engineered strains are compared.

## A.1.1 Why this re-scope did not change the architecture

The original blueprint's decision 12 states that product-specific behaviour lives in data, never
in code, and that product priority is policy rather than structure. This re-scope is the test of
that claim, and it passes: making isobutanol primary and ethanol a bounded reference layer
required changes to **scope, acquisition policy, phase order and one new subsystem** — and no
change to the core entity model, the zone model, the evidence framework, the storage architecture
or the knowledge graph. Sections C, D, J, K, L, M, N, O, T and V stand as written.

The one genuinely new subsystem is the **route, parts and compartment layer** (G.5–G.8 and
`docs/design/ISOBUTANOL_PROGRAM.md`), which is new capability rather than restructuring.

## A.2 What this is not

Naming the exclusions is load-bearing, because each one is a plausible direction that would
double the scope:

| not in scope | why |
|---|---|
| **An ethanol atlas** | Ethanol is the best-studied topic in industrial microbiology and re-curating it would consume the project. Ethanol enters only through the bounded reference layer of B.3, under a hard admission cap. |
| **Broad ethanol omics reprocessing** | Thousands of *S. cerevisiae* RNA-seq runs exist under ethanolic conditions. Ingesting them would bury the isobutanol signal in a corpus that answers a different question. A named short list only (B.3.4). |
| A general yeast knowledgebase | SGD already is one, better than this will be. This atlas is about *production*, and imports SGD rather than competing with it. |
| Lignocellulose pretreatment chemistry | A separate discipline. Hydrolysate composition enters only as fermentation *inhibitors* (furfural, HMF, acetate, phenolics) in the condition model. |
| Techno-economic modelling | Downstream of the atlas. The atlas supplies titer/yield/productivity in normalized units so a TEA tool can consume them; it does not compute cost. |
| A protocol execution or LIMS system | Protocols are stored as references and extracted method summaries, not as executable procedures. |
| Genome-scale flux simulation as a core feature | Yeast9 and the BiGG/MetaCyc ecosystem already do this. The atlas links to models and stores their outputs as Zone I evidence; it does not host an FBA engine in phase 1. |
| Protein structure prediction at scale | AlphaFold DB is referenced for specific enzymes; nothing is folded here. |
| Clinical, food-safety or regulatory data | Out of domain. |

**AMENDMENT 2026-09-20 — DUET §5.4. One carve-out from the downstream exclusion.**

*What this replaces:* the unqualified reading of the two rows above (techno-economic modelling;
and, in B.3.6, "process control, distillation and downstream separation") as excluding everything
downstream of the fermenter, including the conditions under which a titer was measured.

*Why:* DUET recovers isobutanol by stripping with waste CO₂ from the adjacent ethanol fermenter
and decanting the heterogeneous azeotrope, so **in-situ product removal is a property of DUET's
fermentation, not of a separate downstream unit**. A 2 g/L titer measured under continuous
stripping and a 2 g/L titer measured in a sealed flask are not the same measurement: the first has
had the product — and therefore the product inhibition — removed as it formed. Comparing them
silently is a comparability error of exactly the class section K.4 exists to prevent.

*The carve-out, and its limit:* `in_situ_product_removal` becomes a **`condition_context` facet**
(C.5), so ISPR and non-ISPR measurements can never be pooled without the difference being visible.
Nothing else moves in scope. Separation train design, solvent selection, distillation modelling,
energy integration and TEA all stay out; the atlas still supplies normalized numbers to a TEA tool
rather than computing cost. DUET's recovery route is also a patent-family commitment, which is
handled by the patent layer of R.1, not by a process-engineering layer.

## A.3 The five properties that define success

1. **Traceability.** Every number in the interface has a path back to a publication, an accession
   and, where the atlas computed it, a pipeline run with a recorded version. A number without a
   path is a bug.
2. **Separation of evidence.** A measured titer, a cross-study correlation and an LLM-proposed
   hypothesis are never rendered, exported or queried as if they were the same kind of thing.
3. **Comparability.** Two experiments from different labs can be placed on the same axis, or the
   atlas states why they cannot. This is the hard part; section K.4 and section F.6 are about
   nothing else.
4. **Extensibility.** Adding *n*-butanol means adding rows to `product`, a pathway, and a set of
   assays. If it means a migration of the core tables, the design failed.
5. **Honesty about ignorance.** "Not recorded" and "recorded as not applicable" are different
   facts and are stored differently. Absence of evidence is displayed as absence, never as zero.
6. **Actionability.** The atlas ranks routes, it does not only list facts. A query that returns
   forty equally-weighted genes has failed, even if all forty are correctly cited. Ranking is by
   demonstrated effect size under comparable conditions, weighted by evidence level and
   independence — and the ranking function is inspectable, not a black box.
7. **Bounded scope.** Every layer has an admission policy and, where the literature is large
   enough to swamp the project, a hard cap. Growth is a decision, never a default.

## A.4 Primary users

Reordered for the isobutanol program. The first row is the one the system is built for; the rest
are served by the same machinery.

| user | what they come for | the feature that serves them |
|---|---|---|
| **Isobutanol strain engineer (primary)** | "which route should I build next, and what will stop it" | Route ranking (G.7), parts catalog (G.6), bottleneck model (G.8), engineering history per node |
| Pathway / compartment engineer | "cytosolic relocalization or mitochondrial targeting, and what does each cost" | Compartment layer (G.5), localization records with verification method |
| Strain developer | "which background, and which deletions come with it" | Strain page, lineage DAG, modification sets, ploidy and marker-free editing history, *pdc*-minus chassis records (as a comparator, not the default — B.4) |
| Fermentation scientist | "what titer is realistic, and under what aeration" | Phenotype atlas faceted by condition class |
| Reviewer / PI | "is this claim actually supported" | Evidence page with full support and conflicts |
| An AI agent acting for any of the above | structured, cited answers | MCP server and the assertion API (section L) |

---

# B. Scientific scope

## B.1 The priority model

Three tiers, and the tier is a stored property of `product` that drives the acquisition policy in
code. It is not an informal understanding.

| tier | products | policy |
|---|---|---|
| **Primary** | isobutanol | Comprehensive across all host organisms and all data types |
| **Reference** | ethanol | Bounded, capped, admitted only against stated criteria (B.3) |
| **Adjacent** | 2-methyl-1-butanol, 3-methyl-1-butanol (isoamyl alcohol), *n*-butanol, 1-propanol | Captured **only** when measured in the same experiment as isobutanol — they are the by-products of the same promiscuous ketoacid decarboxylases and their ratios are diagnostic of where flux is leaking |
| **Reserved** | 2,3-butanediol, lactate, succinate, itaconate | Rows with no data. They prove the schema is product-generic (section U) |

The adjacent tier is new and is not a compromise. Ehrlich-pathway decarboxylases act on several
2-ketoacids ⚠, so an isobutanol strain almost always makes isoamyl alcohol and
2-methyl-1-butanol too. **The ratio between them is a measurement of decarboxylase specificity and
of which ketoacid pool is actually being drained** — which is diagnostic information for route
design, and is lost if only isobutanol is recorded. Any paper reporting an isobutanol titer is
therefore mined for the co-reported higher alcohols, at no extra curation cost.

### Admission policy by data type

| data type | isobutanol (primary) | ethanol (reference) |
|---|---|---|
| Publications | Comprehensive — target ≥95% recall of the primary production literature | Capped set, each admitted against a B.3 criterion with the criterion recorded |
| Engineering records | All interventions, all hosts, including failures and null results | Only pyruvate-node competition, redox rebalancing, and higher-alcohol-transferable tolerance |
| Measurements | All, including by-products and carbon balance | Benchmark ceilings and wild-type baselines only |
| Genomes | Host chassis plus every parts-source organism | S288C and CEN.PK plus a named industrial shortlist |
| Transcriptomics (reprocessed) | All recoverable datasets | A named short list only (B.3.4) |
| Pathway curation | Full depth: compartment, cofactor, transport, kinetics | Only to the depth needed to model competition at the pyruvate node |
| Tolerance | Full, by assay type | Only mechanisms with a stated argument for transfer to C4 alcohols |

**Caps are budgets, not targets.** The ethanol layer is capped at ~150 publications, ~60
measurement-bearing studies and ~6 reprocessed transcriptomic studies. Once a cap is reached,
adding a record requires removing one, with the swap recorded. This is the mechanism that
implements *do not flood the database*: without a hard number it will be flooded, because every
individual ethanol paper looks worth adding.

## B.2 Isobutanol: what "comprehensive" means

The isobutanol production literature is small enough to be covered nearly completely — plausibly
400–800 primary papers across all organisms ⚠, against tens of thousands for ethanol. That
asymmetry is the whole reason this scoping works: **near-total recall is achievable on the primary
product and impossible on the reference product.**

Comprehensive means:

* Every published microbial isobutanol production strain, in any host, as a
  `pathway_configuration` (G.4) with its enzyme set, compartment strategy, cofactor strategy,
  deletions, conditions and best measured outcome.
* Every enzyme variant used in those builds as a **part** (G.6), with its source organism,
  cofactor preference, kinetics where reported, and every host it has been expressed in.
* Every reported bottleneck, with the evidence for it and whether the proposed fix worked.
* Negative and null results with equal standing — for a product where most builds underperform,
  the record of what failed is more informative than the record of what succeeded.
* All recoverable transcriptomic, proteomic and fluxomic data from isobutanol-producing or
  isobutanol-stressed cultures. This corpus is small; it will not swamp anything.
* Tolerance data across assay types, since product toxicity is a binding constraint well below
  the titers the route calculations permit.

Theoretical mass yield from glucose is **0.411 g/g** (1 glucose → 1 isobutanol + 2 CO₂ + H₂O),
against **0.511 g/g** for ethanol. Both are stored per substrate and drive the automated
carbon-balance bound check of S.3 — the check that matters most here, because several early yeast
isobutanol reports have been questioned on carbon-balance grounds ⚠ and a database that ingests
them silently launders a disputed number into a fact.

## B.3 Ethanol: the reference layer

Ethanol is in the atlas because the isobutanol program needs it, and the admission test is exactly
that:

> **An ethanol record is admitted only if it answers a question the isobutanol program asks.**

Every admitted record stores which of the **five** criteria below it was admitted under. A record
that satisfies none is excluded, with the exclusion recorded and re-runnable (R.2).

**AMENDMENT 2026-09-20 — DUET §5.1. There are five criteria, not four, and E1 is no longer the
primary one.**

*What this replaces:* "four criteria" throughout B.3, and the framing — stated in B.3.1 below and
inherited by everything that cites it — that ethanol enters the atlas mainly as the competitor to
be deleted.

*Why:* DUET's first architectural claim is that **ethanol is the mechanism, not the enemy**.
Ethanol diffuses into the matrix, Adh3 oxidises it there, and the resulting matrix NADH feeds both
the final Ehrlich ADH step and — through Pos5, the mitochondrial NADH kinase — the matrix NADPH
that Ilv5 requires. That literature (mitochondrial alcohol dehydrogenase, the
ethanol–acetaldehyde shuttle as a cytosol→matrix route for reducing equivalents, matrix NADH/NADPH
pools, `POS5`) was **entirely unscoped** by E1–E4, which only asked what deleting ethanol
production costs. It is now criterion **E5** (B.3.5). The fifth criterion already exists in
`data/literature/query_families.yaml` and in the schema CHECK on the criterion column; PLAN.md was
the last document still listing four.

E1 stays, unchanged in content and unchanged in value — knowing precisely what *PDC* deletion
costs is still required, both to read the incumbent literature and to argue why DUET does not do
it. What changes is its rank: **E5 is the primary ethanol framing for this atlas, E1 is the
counterfactual.**

### B.3.1 Criterion E1 — the competing sink (the counterfactual, not the plan)

The reason ethanol cannot simply be dropped from the atlas. Pyruvate decarboxylase
sends pyruvate to acetaldehyde and then ethanol; the isobutanol route needs that same pyruvate for
acetolactate. **Ethanol is not a neighbouring product, it is the competitor.**

Admitted: *PDC* deletion and attenuation studies, `pdc1Δ pdc5Δ pdc6Δ` chassis strains and their
C2 auxotrophy, the glucose-tolerance evolution that makes Pdc-minus strains usable ⚠, Pdc
promoter-replacement and dynamic-control strategies, and the redox consequences of removing the
principal NADH sink — including the glycerol branch (*GPD1*/*GPD2*) that compensates.

**AMENDMENT 2026-09-20 — DUET §5.1. The chassis is Pdc-POSITIVE.**

*What this replaces:* the sentence that stood here, verbatim — *"This material is arguably the
highest-value content in the entire ethanol layer, because a Pdc-minus or Pdc-attenuated
background is the likely starting chassis."*

*Why:* it is false with respect to the strain this atlas exists to design. DUET deliberately
**retains and strengthens** the ethanol–acetaldehyde shuttle: deleting *PDC* cripples the yeast,
imposes the C2 auxotrophy, and removes the redox carrier the matrix pathway depends on. The
production chassis is Pdc-positive and co-produces ethanol by design (B.4).

*What E1 is for instead:* E1 records are the **counterfactual layer**. They answer "what does the
incumbent architecture cost, and what would we be giving up" — the C2 auxotrophy, the growth
defect, the redox consequences of removing the principal NADH sink, the compensating glycerol
branch, the evolved suppressors. Those are the measured consequences that make the Pdc-positive
choice arguable rather than asserted, and they are also what the atlas needs in order to read the
Gevo/Butamax-lineage literature, essentially all of which is Pdc-attenuated. E1 records may
therefore never be used to characterise the DUET chassis itself; they characterise the alternative
it rejected. An assertion about DUET derived from a Pdc-minus background is a cross-chassis
inference and is capped accordingly (J.3).

The highest-value content in the ethanol layer is now **E5** (B.3.5).

### B.3.2 Criterion E2 — the performance ceiling

A small, authoritative set answering "what does a high-performing yeast fermentation look like":
industrial and very-high-gravity fermentations with their titer, yield as a fraction of the
0.511 g/g theoretical maximum, productivity and conditions.

Purpose: the isobutanol program is reaching for numbers two to three orders of magnitude below
these, and the reference values calibrate what "good" means for a sugar-to-alcohol process in
yeast — the achievable yield fraction, the realistic productivity, the tolerable product
concentration. Target ~30–50 records, heavily curated, not a survey.

### B.3.3 Criterion E3 — wild-type baselines

Matched wild-type and parental-strain datasets that serve as the control against which engineered
strains are read. An engineered strain's number is meaningless without the baseline it was
measured against, and papers frequently report the engineered strain while citing the baseline
elsewhere.

Admitted: well-characterized wild-type fermentation profiles for the specific backgrounds the
program will use (S288C/BY4741, CEN.PK113-7D, and the named industrial strains), under stated
conditions, with by-products and carbon balance where available.

### B.3.4 Criterion E4 — transferable mechanism

Alcohol tolerance, redox balancing and stress response, admitted **only with a stated argument for
transfer to a C4 alcohol.** This filter matters: isobutanol is considerably more toxic than
ethanol on a molar basis ⚠ and acts partly through different membrane effects, so ethanol
tolerance mechanisms transfer unevenly. A mechanism admitted here carries an explicit
`transfer_rationale` field, and an assertion derived from ethanol data about an isobutanol
phenotype can never exceed evidence level L3 (J.3) without direct isobutanol evidence.

The named transcriptomic short list also lives here — at most six reprocessed studies, chosen to
cover: anaerobic versus aerobic reference physiology, the *pdc*-minus background, ethanol stress
(shock and adapted, separately), and one industrial-strain reference. Nothing else.

**AMENDMENT 2026-09-20 — DUET §5.1. The short list gains an E5 slot and loses nothing.**

*What this replaces:* a six-study list in which every slot served E1–E4, and in which the only
redox-relevant slot was the *pdc*-minus background.

*Why:* with E5 in scope, the atlas needs at least one reprocessed study of **cells respiring or
co-metabolising ethanol** — the physiological state in which Adh3 is actually carrying flux and
the matrix NADH pool is being fed. Without it the E5 criterion has literature but no expression
data behind it. The cap stays at six. The slots are now: (1) anaerobic vs aerobic reference
physiology; (2) **ethanol as carbon source / diauxic-shift respiratory reference — the E5 slot**;
(3) the *pdc*-minus background, retained as the E1 counterfactual; (4) ethanol stress, shock;
(5) ethanol stress, adapted; (6) an industrial-strain reference. Nothing else.

### B.3.5 Criterion E5 — ethanol as mitochondrial redox shuttle

**ADDED 2026-09-20 — DUET §5.1. New subsection; nothing was replaced, this criterion was simply
absent from PLAN.md while already present in `data/literature/query_families.yaml` and in the
schema CHECK constraint on the admission-criterion column. The renumbering it forces is recorded
at the end of this subsection.**

The primary ethanol framing for this atlas, and the one the destination strain depends on.

DUET's redox architecture runs *through* ethanol rather than around it:

```
ethanol (cytosol) --diffuses--> mitochondrial matrix
   --Adh3--> acetaldehyde + matrix NADH
        |
        +--> final ADH step of the matrix Ehrlich pathway      [needs NADH]
        |
        +--Pos5 (mitochondrial NADH kinase)--> matrix NADPH
                 --> Ilv5 / KARI                               [needs NADPH]
```

Ilv5 needs NADPH and the Ehrlich alcohol-dehydrogenase step needs NADH. Ethanol oxidation by Adh3
supplies the NADH directly in the right compartment, and `POS5` is the only named route from
matrix NADH to matrix NADPH ⚠. That is what makes the architecture close — and it is also why
**`POS5` capacity is the atlas's highest-priority bottleneck hypothesis** (G.8), with an
NADH-preferring KARI variant as the highest-priority de-risking part (G.6). Both are seeded as
`knowledge_gap` rows before curation starts, so the literature search is actively looking for them
rather than stumbling on them.

**Admitted under E5:**

* `ADH3` and mitochondrial alcohol dehydrogenase generally — localization, kinetics, directionality
  (matrix ethanol oxidation vs. acetaldehyde reduction), and the consequences of `adh3Δ`.
* The **ethanol–acetaldehyde shuttle** as a route for cytosol→matrix reducing equivalents: its
  stoichiometry, its measured capacity, the acetaldehyde permeability assumption it rests on, and
  the studies that dispute it. Disputes are stored, not resolved (J.4).
* **Matrix NADH and NADPH pool** measurements and the methods used to measure them per
  compartment, since a whole-cell cofactor ratio cannot answer an E5 question.
* `POS5` (mitochondrial NADH kinase) — expression level, overexpression phenotypes, `pos5Δ`
  consequences, and any measured matrix NADPH response.
* `ADH2` and the other routes by which ethanol re-enters central metabolism, where they bear on
  how much ethanol is available to the matrix.
* The respiratory / diauxic-shift physiology of ethanol as a **carbon source**, which is the
  condition under which all of the above is normally measured.

**Not admitted under E5:** ethanol tolerance (that is E4), ethanol titer records (E2/E3), and
general mitochondrial bioenergetics with no stated link to a cytosol→matrix redox route. E5 is a
redox-shuttle criterion, not a mitochondria criterion.

**Interaction with E1.** E1 and E5 point in opposite engineering directions, and that is
deliberate: E1 measures the cost of removing the ethanol sink, E5 measures the benefit of keeping
it. A record may be admitted under both, and the pair is exactly what makes the Pdc-positive
decision (B.4) reviewable. The admission criterion is stored per record, so "show me everything
that argues against retaining PDC" stays an answerable query.

**Evidence ceiling.** Most of the E5 literature was generated for reasons unrelated to branched-
chain alcohols. An assertion about DUET's matrix redox balance that rests only on E5 records is a
transfer claim and is capped at **L3** (J.3) until there is a direct measurement in an
isobutanol-producing strain — the same rule E4 already carries.

*Renumbering caused by this insertion:* the exclusions section that was **B.3.5** is now
**B.3.6**. The criterion ↔ section mapping E*n* ↔ B.3.*n* is preserved, which is what
`src/fermdb/db/schema.sql` and `src/fermdb/literature/queries.py` comment against; those comments
say "E1-E4 / B.3.1-B.3.4" and now read one criterion short. `docs/design/DUET_TARGET.md` §5.2
cites the exclusions as B.3.5 and now points one section early. Neither file is editable from
this change; both are flagged in the report rather than silently left wrong.

### B.3.6 What is explicitly excluded

*(Was B.3.5 until 2026-09-20; renumbered by the insertion of E5 above.)*

Lignocellulosic hydrolysate and pretreatment optimization; SSF and CBP process studies;
consolidated bioprocessing; strain-screening surveys; ethanol tolerance QTL mapping beyond
mechanisms admitted under E4; yeast strain biodiversity surveys; and process control, distillation
and downstream separation.

Each of these is legitimate science and none of it advances an isobutanol build. They are named
here so the exclusion is a decision on the record rather than an oversight, and so that a future
change of mind can re-run the filter over what was skipped.

**AMENDMENT 2026-09-20 — DUET §5.2. Pentose utilisation is no longer excluded.**

*What this replaces:* the phrase **"pentose utilization engineering"**, which stood second in the
exclusion list above and has been struck from it.

*Why:* it excluded the thing the destination strain is built on. DUET's entire substrate partition
is **C6 → ethanol on the existing train, C5 → isobutanol in the bolt-on fermenter**; the stranded
pentose stream is roughly a third of the fermentable sugar and is the only reason the process has
a feedstock at all. `XKS1 TAL1 TKL1 RKI1 RPE1` are core DUET genes (DUET_TARGET §3). Excluding
pentose utilisation made the plan contradict its own destination in the most direct way available.

*Now in scope, first-class:*

| area | what enters |
|---|---|
| **Xylose utilisation** | Both routes — XR/XDH (`XYL1`/`XYL2` and their cofactor imbalance) and xylose isomerase (`xylA`, fungal and bacterial sources) — with the cofactor consequence recorded, because it is a redox claim and therefore interacts with E5 |
| **Arabinose utilisation** | Bacterial and fungal L-arabinose routes, at lower depth than xylose until the feedstock analysis says otherwise |
| **Non-oxidative PPP** | `XKS1` `TAL1` `TKL1` `RKI1` `RPE1` — overexpression sets, measured flux consequences, and the deletion/attenuation partners they are normally shipped with |
| **Pentose transport** | Which transporters carry xylose and arabinose, and at what affinity, since glucose–xylose transporter competition is the usual reason a co-fermentation stalls ⚠ |
| **Glucose repression and carbon-programmed switching** | `MIG1`, `SNF1`/`HXK2`, glucose-repressed and glucose-derepressed promoters, and the kinetics of derepression. DUET makes the C6→C5 handover automatic with no inducer, so **the switch is a designed component and its literature is program literature, not background** |

*Admission depth.* This is admitted for the **isobutanol program**, not as a general pentose
atlas. The test is DUET's: a pentose record enters if it bears on making C5 into 2-ketoisovalerate
in an industrial strain, or on the C6/C5 handover. Pentose work aimed at maximising *ethanol* from
xylose enters under the ethanol layer's existing cap, as E3/E4, and does not get its own budget.

*Schema consequence — this is the part that would have broken silently.* `condition_context`
currently models one carbon source per context well and a mixture badly. DUET requires both
**MIXED** (glucose and xylose present together, as in a real hydrolysate) and **SEQUENTIAL**
(glucose consumed first, then xylose, the programmed switch) carbon regimes, and the difference
between them is the whole point of the design. C.5 is amended accordingly.

## B.4 Organisms, by their role in the isobutanol program

Organisms are organized by **what they are for**, not by taxonomy. A taxonomic tiering would put
*E. coli* far from the work, when in fact it is where most of the pathway was established and is
therefore ingested at full depth.

**Role 1 — production chassis (where we build).** *S. cerevisiae*. Laboratory backgrounds
CEN.PK113-7D (the metabolic-engineering and physiology standard, with the best-characterized
quantitative fermentation data ⚠), BY4741/S288C (the reference genome and the deletion-collection
tool base), W303. Industrial backgrounds — Ethanol Red, PE-2/JAY270, CAT-1 and comparable
distillers' lineages ⚠ — admitted for their robustness and tolerance, which matter for a real
process. Plus the *pdc*-minus and Pdc-attenuated derivatives (B.3.1), which are chassis in their
own right.

**AMENDMENT 2026-09-20 — DUET §5.3. The real chassis is an industrial polyploid with no public
genome, so the atlas runs two proxies in parallel and says so.**

*What this replaces:* the recommendation — made in the planning conversation and carried into the
paragraph above and into E.2 — that **CEN.PK113-7D is the chassis**, and the implication in B.3.1
that a Pdc-minus derivative is the likely background.

*Why:* neither is true of the destination. DUET is built in an **industrial polyploid
*S. cerevisiae* that the owner already holds**, running at ~120 g/L ethanol in an existing Indian
2G plant, engineered by **marker-free multiplex editing**, and **Pdc-positive** by design. It is
haploid in neither genotype nor behaviour, its genome is **not sequenced and not public**, and it
is not any of the strains named above.

*The resolution — two proxies and an anchor, never collapsed into one:*

| role | strain | assembly | what it is for | what it may not be used for |
|---|---|---|---|---|
| **Anchor** | S288C | RefSeq **R64** | The systematic-name namespace every `gene_group` is anchored on (C.3); the coordinate space quantification reports in (F.4) | Any physiology or robustness claim. S288C is a laboratory strain and a poor model of an industrial one ⚠ |
| **Industrial proxy** | **Ethanol Red** | **GCA_029255905.1** (Scaffold, N50 189 kb, Padova) | Standing in for the owner's strain: industrial genetic background, distillers' lineage, high-ethanol robustness, aneuploid/polyploid-typical architecture ⚠ | Gene-level coordinate work that a scaffold-level assembly cannot support; anything requiring chromosome-scale continuity |
| **Physiology comparator** | **CEN.PK113-7D** | **GCA_002571405.2** (Chromosome, N50 913 kb, Delft) | Quantitative physiology: the chemostat, carbon-balance and fermentation datasets that actually have the numbers ⚠; the chromosome-scale assembly for structural questions | Robustness, tolerance or industrial-performance claims. CEN.PK is a laboratory strain |

Both assemblies are verified present on NCBI as of 2026-09-20. They are ingested **in parallel,
not ranked** — the two proxies answer different questions and the atlas never silently substitutes
one for the other. Every strain-level conclusion records **which proxy produced it**.

*The honesty rule this forces, stated plainly.* A conclusion derived from Ethanol Red or
CEN.PK113-7D is **a hypothesis about the owner's strain, not a fact about it.** Such assertions are
**capped at L3** (J.3) and may not be promoted by accumulating more proxy evidence — only a
measurement in the actual chassis lifts the cap. The atlas renders the proxy in the assertion, so
"this was shown in Ethanol Red" is visible at the point of reading rather than buried in provenance.

*Why this costs nothing later.* The join key is `gene_group`, never a raw gene id (C.3). When the
owner's strain is sequenced, it enters as one more member of each existing group with its own
assembly and its own coordinates; the proxy-derived rows keep their strain attribution and their L3
cap, and new rows measured in the real chassis simply outrank them. **No migration, no re-keying,
no re-curation** — which is the concrete payoff of having refused to join on gene ids.

*What `chassis_profile` must therefore model:* **ploidy** (and aneuploidy, per chromosome, since an
industrial polyploid is rarely uniformly *n*), **allele dosage** (a heterozygous deletion in a
polyploid is not a deletion), **marker-free multiplex editing history** (no auxotrophic markers
available, which constrains every proposed modification), industrial robustness traits, and
`genome_available` as an explicit boolean rather than an absent row. A modification proposal that
assumes haploid single-copy editing is wrong for this chassis and the schema should be able to say
so.

*Unchanged:* the mitochondrial-genetics background of the laboratory strains stays relevant, but
only for **strategy E** (mtDNA engineering) later, under the escalation condition already recorded
in `ISOBUTANOL_PROGRAM.md` §4 — attempt E when strategy C is demonstrated to be import-limited.

**Role 2 — alternative eukaryotic chassis (the fallback comparison).** *Yarrowia lipolytica*,
*Kluyveromyces marxianus* (thermotolerance, which pairs with in-situ product removal since
isobutanol toxicity binds early), *Ogataea polymorpha*, *Komagataella (Pichia) phaffii*. Ingested
for their isobutanol records and chassis properties, not as full genomic programs. They are in the
atlas so that "is *S. cerevisiae* actually the right host" remains an answerable question rather
than an assumption.

**Role 3 — demonstration organisms (where the route was proven).** **Full depth for isobutanol.**
*E. coli* — the organism where the ketoacid route to branched-chain alcohols was first assembled
and where the highest titers and near-theoretical anaerobic yields were demonstrated ⚠;
*Corynebacterium glutamicum* — an amino-acid industrial organism with a natively strong valine
pathway, which makes its precursor-supply engineering directly relevant; *Bacillus subtilis*;
*Clostridium* spp.; *Cupriavidus/Ralstonia*; *Geobacillus* and other thermophiles;
*Synechococcus*/*Synechocystis* for the photosynthetic routes.

These are **not** comparative footnotes. The cofactor-balancing solutions, the ketoacid pool
engineering and the decarboxylase specificity work largely happened here, and it transfers as
strategy and as parts even where the host does not.

**Role 4 — parts-source organisms (where the enzymes come from).** *B. subtilis* (`alsS`
acetolactate synthase), *E. coli* (`ilvC` ketol-acid reductoisomerase and its NADH-preferring
variants, `ilvD` dihydroxyacid dehydratase, `yqhD`), *Lactococcus lactis* (`kivD` 2-ketoacid
decarboxylase, `adhA` alcohol dehydrogenase), plus thermophilic and archaeal sources of
cofactor-switched or thermostable variants ⚠. These organisms need genes, protein sequences,
enzyme properties and variant records — they do not need genome assemblies or transcriptomes.

**Role 5 — ethanol reference organisms.** *S. cerevisiae* only, under the B.3 criteria.
*Zymomonas mobilis* is admitted as a **single yield-ceiling reference** — the highest-yield
natural ethanologen, useful as a calibration point for what a sugar-to-alcohol yield fraction can
reach ⚠ — and nothing more. It gets no genome layer, no transcriptomics and no engineering
program.

*(Superseded for Z. mobilis by the amendment below: ZM4 is a role-3 bacterial isobutanol host with
Tn-Seq data in the measured SRA corpus, and it now gets a genome and annotation layer under role 3.
Its role-5 standing as an ethanol yield-ceiling reference is unchanged and unexpanded — these are
two different admissions of the same organism, recorded separately.)*

### Ingestion depth by role

| layer | R1 chassis | R2 alt. chassis | R3 demonstration | R4 parts source | R5 ethanol ref |
|---|---|---|---|---|---|
| Genome assembly + annotation | full | reference only | no | no | S. cerevisiae only |
| Mitochondrial genome | **full** (G.5) | reference | no | no | no |
| Gene / protein sequence | full | full | full | full | full |
| Enzyme + kinetics + variants | full | full | full | **full** | minimal |
| Engineering records | full | full | **full** | n/a | E1 only |
| Measurements | full | full | **full** | n/a | E2/E3 only |
| Transcriptomics | full | isobutanol only | isobutanol only | no | ≤6 studies |

**AMENDMENT 2026-09-20 — owner direction, 2026-09-20. Role-3 bacterial hosts get a genome and
annotation layer.**

*What this replaces:* the **"no"** in the *R3 demonstration* column of the
"Genome assembly + annotation" row of the table above, and the sentence in Role 5 that
*Z. mobilis* "gets no genome layer, no transcriptomics and no engineering program".

*Why:* the owner has directed that isobutanol production in the established bacterial hosts be
studied properly — genomes, transcriptomes, annotations, pathways and ontology where the data
exists — rather than treated as a source of transferable anecdotes. The original "no" was a budget
decision made on the assumption that role-3 organisms contribute parts and strategies but not
sequence context. Two things make that wrong. First, **most of the isobutanol route was established
in these organisms**, and reading an *E. coli* ketoacid-pool result without its genomic context
(operon structure, regulator, the deletions already in MG1655 derivatives) is reading a conclusion
without its premises. Second, **the SRA corpus is not what the table assumed** — the measured
breakdown (DATA_VOLUME §2) shows bacterial runs that the role-3 row said would not be ingested,
including the Tn-Seq fitness screens, which are *Zymomonas*, not yeast.

*Revised depth for role 3 — the row above is replaced by this table:*

| organism | genome + annotation | transcriptome | pathway / ontology | note |
|---|---|---|---|---|
| ***E. coli* K-12 MG1655** | **full** (reference assembly + annotation) | **yes** — 20 runs in the measured isobutanol corpus (RNA-Seq, OTHER, AMPLICON, WGS; only the RNA-Seq runs enter the expression layer) | full — EcoCyc-class pathway detail, GO | The organism the ketoacid route was assembled in; the highest titers and near-theoretical anaerobic yields ⚠ |
| ***Zymomonas mobilis* ZM4** | **full** | **yes** — 11 runs (Tn-Seq, OTHER). **The Tn-Seq runs are *Zymomonas*, not yeast** — see the correction in DATA_VOLUME §2 | full | Genome-wide fitness screens are the highest-information rows in the whole corpus, and they need a genome to be interpretable at all. Also a role-5 ethanol yield-ceiling reference; the two admissions stay separate |
| ***Lactococcus cremoris*** | **full** | **yes** — 5 runs (RNA-Seq) | annotation + pathway | Source of `kivD` and `adhA`; a parts-source organism that also has expression data, so R3 and R4 overlap here |
| ***Corynebacterium glutamicum*** | **full** | **none in the measured corpus** — genome + annotation only until paper-driven discovery finds runs | full | Natively strong valine pathway; its precursor-supply engineering is the closest industrial analogue to the 2-KIV problem |
| ***Bacillus subtilis*** | **full** | **none in the measured corpus** — genome + annotation only | full | Source of `alsS`; same R3/R4 overlap as *L. cremoris* |

*Still "no genome layer":* the remaining role-3 organisms named above — *Clostridium* spp.,
*Cupriavidus/Ralstonia*, *Geobacillus* and the cyanobacteria — and all role-4 parts sources that
are not in the five-organism list. They keep gene, protein, enzyme and variant records only. The
line is drawn at **organisms with either a measured isobutanol SRA presence or an established
industrial isobutanol program**, which is a re-runnable criterion rather than a taste judgement.
*Fusarium graminearum* has 8 RNA-Seq runs in the corpus but no isobutanol production program; it is
screened at the paper level before any genome work is committed, and is not in the table above.

*Transcriptome counts are provisional by construction.* The per-organism numbers above are from a
runinfo fetch that disagrees with an earlier one on the same query (120 runs vs ~148; DATA_VOLUME
§2 records both and neither is discarded). The ingest **pins the real count at fetch time with a
retrieval timestamp** and reconciles against these figures; it does not treat either number as
ground truth.

*What does not change:* role 3 is still not a chassis role. These organisms get sequence context so
their results can be read, not so that anything is built in them. No isobutanol *build* is planned
in a bacterium, and a bacterial result remains a transfer claim against the yeast chassis, capped
at L3 (J.3) exactly as before.

The organism hierarchy is NCBI Taxonomy, not a bespoke tree. A `Yeast / Bacteria / Fungi / Other`
grouping is a *display* tag over taxonomy, because "yeast" is a polyphyletic lifestyle and not a
clade — *S. cerevisiae*, *Y. lipolytica* and *K. phaffii* are as distantly related to each other as
some of them are to filamentous fungi ⚠. Encoding "yeast" as a structural level would bake a
scientific error into the schema.

## B.5 The design questions, made answerable

Restated as the query shape each becomes. If a question has no query shape, the schema is missing
something — that is the test this table exists to apply.

**Route design — the primary output**

| question | query shape | needs |
|---|---|---|
| Which route should I build next? | Enumerate `pathway_route`s, filter by host feasibility, rank by demonstrated outcome × evidence level × technical feasibility | Route model (G.7), parts catalog, feasibility ratings |
| Which enzyme for each step, and from where? | Parts catalog filtered by step, host-expression record, cofactor preference and measured kinetics | `part` entity with per-host expression records (G.6) |
| Cytosolic relocalization or mitochondrial targeting? | Compare configurations grouped by `compartment_strategy`, with outcome and verification method | Compartment layer (G.5) |
| Is this route redox- and ATP-balanced? | Sum cofactor stoichiometry along the route, per compartment | Cofactor stoichiometry on every reaction, compartment-aware |
| What has never been tried? | Enumerated routes with **no** supporting configuration — the complement of the evidence | Route enumeration must be generative, not a list of published builds |

**Nodes and bottlenecks**

| question | query shape | needs |
|---|---|---|
| Where does flux actually stop? | `bottleneck` assertions grouped by reaction, counted by independent study, with the fix attempted and whether it worked | Bottleneck model (G.8) |
| What competes for pyruvate, and what does removing it cost? | Competing reactions at the node with `role='competing'`, joined to the measured consequence of deleting each | Contextual `role` on `pathway_step`; the E1 ethanol layer |
| How does 2-ketoisovalerate leave the mitochondrion? | Transport reactions with substrate = 2-KIV, and the assertions about carriers | Transport model — expect this to return a **known gap** (G.5.4) |
| Which by-products indicate a leak, and where? | Co-reported higher-alcohol ratios per configuration | Adjacent-product tier (B.1) |
| Which cofactor strategy actually worked? | Configurations grouped by `cofactor_strategy` with yield as a fraction of theoretical | Carbon-balance-checked measurements |

**Chassis and tolerance**

| question | query shape | needs |
|---|---|---|
| Which background should I start from? | Strains ranked by chassis properties: existing deletions, tolerance, transformability, genome availability, prior isobutanol record | Strain layer + lineage DAG |
| What limits titer before the pathway does? | Isobutanol tolerance measurements by assay type, against route-predicted ceilings | Typed tolerance assays |
| Which tolerance mechanisms transfer from ethanol? | E4 records with a `transfer_rationale`, capped at L3 evidence unless directly demonstrated | The transfer-rationale field (B.3.4) |
| Is mitochondrial genome engineering feasible for this? | Route feasibility ratings by technique class, with the method record and who has done it | Technique maturity model (G.5.3) |

**Ethanol reference — deliberately few**

| question | query shape |
|---|---|
| What yield fraction is achievable for a sugar-to-alcohol process in yeast? | E2 benchmark records, yield as % of 0.511 g/g |
| What does the wild-type baseline look like in my background? | E3 records for the chosen strain under matched conditions |
| What happens physiologically when the Pdc sink is removed? | E1 records: growth, C2 requirement, redox, glycerol, evolved suppressors |

**AMENDMENT 2026-09-20 — DUET §5.1, §5.2 and §7. Four questions the table could not express.**

*What this replaces:* nothing is withdrawn. The table above stands. It was, however, **complete
only for the scope that preceded the DUET corrections** — it has no question whose answer depends
on matrix redox, on a pentose substrate, on product removal, or on which proxy strain produced a
result. By the table's own test ("if a question has no query shape, the schema is missing
something"), those four absences were schema gaps hiding as unasked questions.

| question | query shape | needs |
|---|---|---|
| **Can matrix NADH supply both the Ehrlich ADH step and, via Pos5, the NADPH Ilv5 needs?** *(the highest-priority bottleneck hypothesis)* | E5 records for `ADH3` and `POS5`, joined to compartment-resolved NADH/NADPH pool measurements, with the shuttle stoichiometry summed per compartment | Criterion E5 (B.3.5); compartment-aware cofactor stoichiometry; a `knowledge_gap` row seeded before curation, because this will return mostly gaps |
| **What removes the `POS5` single point of failure?** | Parts catalog filtered to NADH-preferring KARI variants, with source organism, measured cofactor preference and every host and compartment they have been expressed in | Parts catalog (G.6) — this is the highest-priority parts question and is seeded as a gap alongside the one above |
| **Which pentose route, and what does the C6→C5 handover cost?** | Configurations grouped by pentose route (XR/XDH vs. xylose isomerase) with the non-oxidative PPP set they shipped with, restricted to `carbon_regime ∈ (MIXED, SEQUENTIAL)`, reporting the redox consequence per route | B.3.6 pentose scope; the `carbon_regime` and `carbon_phase` facets (C.5) |
| **Is this titer comparable to that one?** | Any two measurements, with `in_situ_product_removal`, `carbon_regime` and `reference_assembly` compared before the numbers are, and the comparison refused with a stated reason where they differ | The C.5 facet amendments; comparability classes (K.4). **Refusal is a valid answer here** and is the feature, not a failure |
| **Which proxy produced this, and does it hold for the real chassis?** | Any strain-level assertion, rendered with its source strain (Ethanol Red / CEN.PK113-7D / S288C) and its L3 cap, plus what measurement in the owner's strain would lift it | `chassis_profile` with `genome_available`; the proxy attribution rule (B.4) |

## B.6 The biology the schema must not flatten

Seven specifics. Each is a place where a naive schema loses exactly the information the route
designer needs.

1. **Compartmentalization.** In *S. cerevisiae* the valine branch (Ilv2/Ilv6 acetolactate synthase,
   Ilv5 ketol-acid reductoisomerase, Ilv3 dihydroxyacid dehydratase) sits in the mitochondrial
   matrix, while the Ehrlich pathway that finishes isobutanol — a 2-ketoacid decarboxylase, then
   an alcohol dehydrogenase — is cytosolic ⚠. The route therefore crosses a membrane, and a large
   fraction of the engineering literature exists to resolve that. **A reaction without a
   compartment is not storable.** Compartment is mandatory and `unknown` is an explicit value,
   never a NULL.

2. **Two entirely different things are called "mitochondrial engineering", and conflating them
   would be the single most expensive modelling error in this atlas.**

   | | **(a) Compartment targeting** | **(b) Mitochondrial genome engineering** |
   |---|---|---|
   | What is changed | A *nuclear* gene, given or stripped of a mitochondrial targeting sequence, so its protein is imported into the matrix or retained in the cytosol | The *mitochondrial DNA itself* — the ~86 kb mtDNA encoding a handful of respiratory-chain subunits ⚠ |
   | Typical method | Fuse/delete an N-terminal presequence; express from a nuclear locus | Biolistic transformation into a ρ⁰ recipient with a mitochondrial marker; mitoTALEN/mitoZFN heteroplasmy shifting; DdCBE-class base editing ⚠ |
   | Maturity | Routine | **Difficult, low-throughput, practised in few laboratories; no routine CRISPR route, because guide RNA import into the matrix is not established ⚠** |
   | Used for isobutanol | Yes — this is what essentially all published "mitochondrial isobutanol" work is | Rarely or not at all for this pathway ⚠ |

   Almost all published mitochondrial isobutanol engineering is **(a)** — relocating Ehrlich-pathway
   enzymes into the matrix by adding targeting sequences, or relocating the Ilv enzymes to the
   cytosol by truncating theirs ⚠. The schema stores these as distinct `modification.type`
   values (`localization_change` versus `mtdna_edit`) with distinct feasibility ratings, so a
   route that requires true mtDNA editing is never ranked as if it were as easy as adding a
   presequence. See G.5.

3. **The mitochondrial genetic code is not the standard code, and this constrains every
   relocation.** *S. cerevisiae* mitochondria use NCBI translation table 3: `UGA` reads as
   tryptophan rather than stop, `AUA` as methionine, and the entire `CUN` family as **threonine
   rather than leucine** ⚠. Consequences the schema must carry:

   * A gene moved *into* mtDNA must be recoded, or it mistranslates — this is why mitochondrial
     reporters and markers exist in recoded form ⚠.
   * An mtDNA-encoded gene expressed allotopically *from the nucleus* must be recoded the other
     way.
   * Compartment targeting (2a) does **not** require recoding, because translation still happens
     on cytosolic ribosomes — a distinction that is easy to state and easy to get wrong.

   Therefore **`genetic_code_table` is a property of the `encoding_genome`** — nuclear or
   mitochondrial — **not of the compartment**, because translation happens where the ribosome is,
   not where the protein ends up. Every stored sequence carries the genome whose code it is
   written in, and the compartment only constrains which genomes are possible.

   The matrix and the inner membrane hold proteins from **both** genomes, so asking "what code
   does the matrix use" is a malformed question and the API raises rather than answering it.
   Getting this wrong produces a construct that looks correct and does not work — and in the
   likelier direction it tells someone to recode a presequence-targeted construct that must not
   be recoded.

   *Corrected 2026-09-19. This paragraph previously concluded that the code was a property of the
   compartment, contradicting the bullet directly above it. The implementation had inherited the
   error; see `docs/reference/CONVENTIONS.md` "Genetic code and compartment".*

4. **Cofactor mismatch.** The ketol-acid reductoisomerase step is NADPH-dependent while the
   alcohol dehydrogenase step is typically NADH-dependent ⚠, so an anaerobic, redox-balanced route
   needs a cofactor-switched enzyme variant or a transhydrogenase-like cycle. Cofactor identity
   and stoichiometry are properties of a *reaction*; cofactor engineering is a first-class
   intervention type; and **cofactor pools are compartment-specific**, so a route split across
   membranes must balance in each compartment separately, not only overall.

5. **Shared precursor, competing fates, promiscuous enzymes.** Pyruvate branches to ethanol,
   valine and the TCA cycle at once; 2-ketoisovalerate branches to isobutanol and to valine;
   2-ketoacid decarboxylases act on several ketoacids, which is why isoamyl alcohol and
   2-methyl-1-butanol appear alongside isobutanol ⚠. A reaction is therefore *competing* in one
   context and the target in another: `role` belongs to the `(reaction, product, context)` triple,
   never as a flag on the reaction.

6. **Transport is a first-class unknown, not an omission.** How 2-ketoisovalerate crosses the
   mitochondrial inner membrane in the cytosolic-Ehrlich configuration is not settled ⚠. The
   schema must be able to represent *"this step is required by the route and its carrier is
   unidentified"* as an explicit, citable gap with its own entity — because that gap is one of the
   most valuable things the atlas can hand a designer, and a schema that can only store known
   reactions would silently drop it.

7. **Tolerance is not one phenotype, and isobutanol tolerance is not ethanol tolerance.** The
   literature means at least: maximum specific growth rate in *x*%, viability after shock, IC₅₀ or
   MIC, lag extension, and long-term adapted growth. These are not interconvertible, so every
   measurement carries its **assay type** and the atlas refuses silent aggregation across types.
   And isobutanol is substantially more growth-inhibitory than ethanol on a molar basis ⚠, acting
   partly through different membrane effects — so an ethanol-derived tolerance mechanism is a
   hypothesis about isobutanol, capped at L3, never a finding.

---

# C. Core entities

## C.1 The model in one picture

```
                          ┌──────────────────────────────────────┐
                          │            ASSERTION                 │  the unit of knowledge
                          │  subject · predicate · object        │
                          │  + context  + evidence  + provenance │
                          └──────────────────────────────────────┘
                                  ▲ everything below is the vocabulary
                                  │ assertions speak about
  ┌───────────────┬───────────────┼───────────────┬────────────────┬──────────────┐
  │               │               │               │                │              │
BIOLOGICAL     GENOMIC         CHEMICAL       EXPERIMENTAL      EVIDENCE      LITERATURE
  │               │               │               │                │              │
Organism       Assembly        Product        Experiment       EvidenceItem   Publication
Strain         Annotation      Metabolite     ConditionContext  Provenance     Claim
StrainLineage  Gene            Reaction       Sample            CurationEvent  Accession
Genotype       GeneGroup ★     Pathway        Measurement ★     Conflict       Protocol
Modification   Transcript      EnzymeActivity Dataset           Benchmark
               Protein         Compartment    ProcessingRun
               Variant         Transporter    AnalysisResult
               Feature         Cofactor
```

★ marks the two entities that most determine whether the atlas works: `GeneGroup` (C.3) and
`Measurement` (C.6).

## C.2 Entity catalogue

Grouped, with the non-obvious fields only. Field names are indicative, not final.

**Biological**

| entity | key fields | notes |
|---|---|---|
| `organism` | `ncbi_taxid`, `name`, `rank`, `lifestyle_tags[]` | `lifestyle_tags` carries `yeast`, `bacterium`, `thermotolerant`, `crabtree_positive` |
| `strain` | `id`, `organism_id`, `canonical_name`, `class` (`laboratory`/`industrial`/`wild`/`engineered`/`evolved`), `collection_ids[]` | `class` is curated, evidenced, and frequently arguable |
| `strain_alias` | `strain_id`, `alias`, `source`, `evidence`, `confidence` | Direct carry-over from `genome-db`'s alias table. "Ethanol Red" and "industrial yeast" resolve here |
| `strain_lineage` | `parent_strain_id`, `child_strain_id`, `step_type`, `publication_id` | A DAG, not a tree: crosses and hybrids have two parents |
| `genotype` | `strain_id`, `as_reported`, `parsed[]` | The raw genotype string is preserved verbatim; `parsed` is Zone H |
| `modification` | `strain_id`, `target` (gene group or locus), `type`, `details`, `source_organism_id` | The engineering atlas's atom; see I.4 |

**Genomic** — section E.

**Chemical / metabolic** — section G.

**Experimental**

| entity | key fields | notes |
|---|---|---|
| `experiment` | `id`, `publication_id`, `objective`, `design_type` | One experimental design, possibly many samples |
| `condition_context` | `id`, facets (C.5), `context_hash` | Immutable and deduplicated: identical conditions across papers share one row |
| `sample` | `id`, `experiment_id`, `strain_id`, `condition_context_id`, `time`, `growth_phase` | The join point between omics and phenotype |
| `measurement` | C.6 | |
| `dataset` | `id`, `accession`, `repository`, `omics_type`, `platform`, `license` | |
| `processing_run` | `id`, `pipeline`, `version`, `container_digest`, `parameters_hash`, `inputs[]` | Section T |
| `analysis_result` | `id`, `processing_run_id`, `kind`, `payload_ref` | Points at Parquet, not at a BLOB |

**Evidence and literature** — sections H and J.

## C.3 `gene_group`: the single most important decision

The atlas must say "this gene" across a laboratory strain, an industrial strain, an engineered
derivative and a different species. Raw gene identifiers cannot carry that: `genome-db` already
found that 520 gene ids are shared between two *Trichoderma* assemblies while naming different
genes, and made every expression query scope by assembly for exactly that reason.

**Decision.** Every gene belongs to exactly one `gene_group`. All cross-study, cross-strain and
cross-species integration happens at group level; raw `gene` rows are never joined across
assemblies. A group carries:

```
gene_group
  id                  YAA:GG:...
  anchor_namespace    'sgd_systematic' for yeast
  anchor_id           e.g. YGR192C          -- the S288C systematic name, when one exists
  standard_name       e.g. TDH3
  scope               'species' | 'genus' | 'cross_species'
  membership_method   'anchor' | 'orthofinder' | 'ygob' | 'rbh' | 'curated'
  membership_evidence per-member identity/coverage, retained
```

Three consequences, all deliberate:

* The *S. cerevisiae* S288C systematic name is the anchor for yeast. It is stable, universally
  used in the literature, and already the key SGD and YEASTRACT use.
* Cross-species groups (yeast ↔ *E. coli* `ilvC`) are a **separate, weaker relation**
  (`ortholog_link` with method and score) and are never silently merged into an anchor group.
  Asserting that `ILV5` and `ilvC` are "the same gene" is a claim, not an identifier.
* A heterologous gene in an engineered strain (`kivD` from *L. lactis* in a yeast) belongs to its
  *native* organism's group and is linked to the host strain through `modification`. It does not
  become a yeast gene.

| | |
|---|---|
| **Why** | Without it, every cross-study statement is either wrong or impossible. |
| **Stores** | Group membership, anchor, method, per-member identity evidence. |
| **In** | Genome annotations, SGD/UniProt mappings, OrthoFinder/YGOB/RBH output. |
| **Out** | The join key for expression, engineering, variants, assertions. |
| **Connects** | Everything. |
| **Automate** | Group construction from anchors and orthology tools; drift detection when an annotation is updated. |
| **Human** | Every cross-species link used in an atlas conclusion; every group where members disagree; every gene family with known one-to-many structure (`ADH1–7`, `PDC1/5/6`, `HXT1–17`) — these are exactly the cases automated orthology gets wrong, and they are central to both products. |

## C.4 `product`

```
product: id, name, inchikey, chebi_id, formula, carbon_number,
         theoretical_yield_from[ {substrate, g_per_g, mol_per_mol, stoichiometry, source} ],
         default_assay_methods[], canonical_unit
```

Theoretical yields are stored **per substrate** and cited, not computed on the fly, because the
stoichiometry depends on the assumed pathway and the assumed redox/ATP closure. They drive the
QC bound in S.3.

## C.5 `condition_context`

The entity that decides whether cross-study integration is possible at all. Flat, explicit,
hashed, immutable.

| facet group | fields |
|---|---|
| Carbon | `carbon_sources[] {compound, concentration, unit}`, `total_sugar_g_l`, `feedstock_class` (`defined`/`molasses`/`hydrolysate`/`starch`/`other`), `hydrolysate_inhibitors[] {compound, concentration}` |
| Nitrogen & medium | `medium_name`, `medium_class` (`defined`/`complex`/`industrial`), `nitrogen_source`, `supplements[]` |
| Oxygen | `aeration_class` (`anaerobic`/`microaerobic`/`oxygen_limited`/`aerobic`), `vvm`, `agitation_rpm`, `dissolved_oxygen_pct`, `otr` |
| Mode | `mode` (`batch`/`fed_batch`/`continuous`/`repeated_batch`/`SSF`/`SHF`/`CBP`/`immobilized`), `dilution_rate`, `feed_profile` |
| Physical | `temperature_c`, `ph`, `ph_controlled` (bool), `osmolarity`, `pressure` |
| Scale | `vessel_type` (`shake_flask`/`serum_bottle`/`microplate`/`bioreactor`), `working_volume_l`, `scale_class` |
| Inoculum | `inoculum_od`, `inoculum_g_l`, `preculture_condition_id` |
| Stressor | `stressor {compound, concentration, exposure_type: shock|adaptation|chronic, duration}` |
| Sampling | `time_h`, `growth_phase`, `sampling_basis` |

Rules, carried from `genome-db`'s `NULL` vs `'NA'` convention and extended:

* `NULL` = the source never recorded it. `'NA'` = recorded as not applicable. **Never coerce one
  into the other.** The UI shows "not recorded" and "not applicable" distinctly.
* Every facet has an `as_reported` shadow field. The parsed value is Zone H; the string the paper
  used is Zone R.
* `context_hash` is a stable hash over the *recorded* facets only, so identical contexts
  deduplicate and a saved analysis can name the context it used.
* `completeness_score` — the fraction of the facets that matter for this product that are
  recorded. It is the primary metadata-quality signal (section S.2) and the primary reason a
  study will be excluded from a meta-analysis.

**AMENDMENT 2026-09-20 — DUET §5.2 and §5.4. Two facet changes, both of which would otherwise
produce silently wrong comparisons.**

**(a) The Carbon facet group is replaced.** *What this replaces:* the row above, which modelled
`carbon_sources[]` as a list but carried no statement of how the sources are **presented in time**.
A list of two sugars cannot distinguish a real hydrolysate co-fermentation from a programmed
glucose-then-xylose switch, and DUET is the second of those.

*Why it matters:* DUET's substrate partition is C6 → ethanol, C5 → isobutanol, made automatic by
glucose-repressed promoters. A measurement taken while glucose is still present and a measurement
taken after derepression are different physiological states of the same vessel. Pooling them is
not a rounding error, it is averaging across the switch the design is built on.

*Replacement row:*

| facet group | fields |
|---|---|
| Carbon | `carbon_sources[] {compound, concentration, unit, role}` where `role` ∈ (`primary`, `secondary`, `co_substrate`, `trace`); **`carbon_regime`** ∈ (`SINGLE`, `MIXED`, `SEQUENTIAL`, `FED`, `unknown`); **`carbon_phase`** — for `SEQUENTIAL` and `FED`, which source is being consumed at the sampling point, with its own `as_reported` shadow; `total_sugar_g_l`, `feedstock_class` (`defined`/`molasses`/`hydrolysate`/`starch`/`other`), `hydrolysate_inhibitors[] {compound, concentration}` |

`carbon_regime` is **required, and `'unknown'` is a legitimate and common value** — a paper that
lists two sugars without saying whether they were co-fed or sequential has genuinely not recorded
it, and that is different from NULL (nothing about carbon recorded at all) and different from
`'NA'`. The three states are never collapsed. Two contexts with different `carbon_regime` are
different contexts and hash differently; a comparability class (K.4) that spans regimes must say
so in its own definition.

**(b) New facet group: in-situ product removal.** *What this replaces:* nothing — this facet was
absent, and its absence was the bug. A.2 excluded downstream processing, and that exclusion was
over-read to mean the atlas need not record whether product was being removed during the
fermentation.

*Why it matters:* DUET strips isobutanol continuously with waste CO₂ from the adjacent ethanol
fermenter. A titer measured under continuous stripping has had its product inhibition removed as it
formed; the same number in a sealed flask has not. For a product whose toxicity binds well below
the stoichiometric ceiling (B.2), this is frequently the **dominant** difference between two
otherwise comparable numbers.

*New row:*

| facet group | fields |
|---|---|
| Product removal | **`in_situ_product_removal`** ∈ (`none`, `gas_stripping`, `vacuum`, `pervaporation`, `liquid_liquid_extraction`, `adsorption`, `membrane`, `other`, `unknown`); `ispr_continuous` (bool); `ispr_carrier` (e.g. the stripping gas, with `as_reported`); `ispr_rate` + unit; `product_retained_in_broth` (bool — whether the reported titer is broth concentration or a recovered total) |

`in_situ_product_removal = 'none'` is an **assertion that the vessel was sealed or vented without
recovery**, and is only written when the methods say so. Where the paper is silent the value is
`'unknown'`, never `'none'` — defaulting to `'none'` would convert "we don't know" into "we know
there was no stripping", which is the exact coercion the missing-value rule forbids.

**The comparability consequence, which is the point of both changes.** A measurement whose
`in_situ_product_removal` is `'unknown'` may not enter an aggregate with measurements that state a
value, and the same holds for `carbon_regime`. Both facets join `aeration_class` as
**class-defining** rather than merely descriptive: they participate in `context_hash`, they appear
in every comparability-class definition (K.4), and the UI surfaces them on any two numbers it puts
on the same axis. `product_retained_in_broth = false` additionally flags the titer as
non-comparable to broth titers without a stated reconciliation.

## C.6 `measurement`

Every quantitative experimental result — production and phenotype alike — is one row.

```
measurement
  sample_id | strain_id | experiment_id      -- the subject, at whatever granularity was reported
  quantity_kind        titer | yield | productivity | specific_productivity | growth_rate |
                       biomass | substrate_consumed | byproduct | tolerance | viability |
                       fermentation_time | uptake_rate | ...
  product_id                                 -- NULL for non-product quantities
  value_as_reported, unit_as_reported        -- Zone R, never touched
  value_si, unit_si                          -- Zone H, derived
  basis                consumed | supplied | theoretical_max_pct | per_biomass | per_volume
  assay_method         HPLC | GC | enzymatic | gravimetric | OD | plate | flow | inferred
  assay_details, detection_limit, is_below_lod, is_upper_bound
  uncertainty {sd, sem, ci_low, ci_high, n_replicates, replicate_type: biological|technical}
  derived_by           NULL if reported; else the rule that computed it
  source_locator       table 2, row 3 / figure 4B (digitized) / text
```

Four rules that prevent the errors this table exists to prevent:

1. **`value_as_reported` is never overwritten, never unit-converted in place.** Conversion writes
   `value_si` beside it, with the conversion rule recorded. This is `genome-db`'s rule that raw
   source data is read-only, applied to numbers.
2. **`basis` is mandatory for yield.** g/g-consumed and g/g-supplied are different numbers and
   papers report both, often without saying which. Where the paper does not say, `basis` is
   `NULL` and the value is not usable for cross-study comparison — and the atlas says so rather
   than guessing.
3. **A value read off a figure is marked as such.** Digitized values are legitimate but are a
   different evidence grade from a tabulated one.
4. **`derived_by` distinguishes a reported yield from one the atlas computed** from titer and
   sugar consumed. Both are useful; conflating them is not.

| | |
|---|---|
| **Why** | Production metrics are the atlas's primary output and the place unit errors do the most damage. |
| **Stores** | Every reported quantitative result with its assay, basis, uncertainty and locator. |
| **In** | Literature extraction, dataset metadata, computed derivations. |
| **Out** | Phenotype atlas, engineering effect sizes, the QC bounds check, ranking. |
| **Connects** | `sample` → `condition_context`, `strain`, `product`, `publication`. |
| **Automate** | Unit conversion, derivation of missing metrics where inputs exist, theoretical-yield bound checks, outlier flagging. |
| **Human** | Every `basis` inference; every digitized figure value; every measurement that fails a bound check; the first 200 extractions of each new journal/table layout. |

---

# D. Data architecture

## D.1 Principles

1. **One system of record for facts; specialized stores for bulk.** Metadata, entities and
   assertions live in one relational database. Large numeric matrices, sequences and documents
   live in files referenced from it. Nothing important exists only in a file.
2. **Derived data is disposable.** Anything in Zone H must be reconstructible from Zone R by
   running recorded code. If it cannot be, it belongs in Zone R.
3. **Append, don't overwrite.** Corrections are new revisions with a reason, not edits.
4. **Provenance is a column, not a convention.** Every table that holds a fact carries its
   source, and the schema enforces it.

## D.2 The three zones

This is the structural expression of "do not mix experimental evidence, computational prediction
and AI inference". `genome-db` does a two-value version of this already —
`experiment.source CHECK (source IN ('geo','salmon'))`, separating a published matrix from one
quantified locally. This generalizes it.

| | **Zone R — Reported** | **Zone H — Harmonized** | **Zone I — Inferred** |
|---|---|---|---|
| Contents | Exactly what the source said: reported values, original units, original identifiers, original condition text, raw accessions, publication metadata | Normalized units, mapped gene groups, parsed conditions, reprocessed omics, standardized DE results, computed derivations | Statistical inferences, cross-study meta-analyses, network predictions, LLM extractions awaiting review, generated hypotheses, recommendations |
| Mutable | Never (append-only revisions) | Freely — it is rebuilt | Freely — it is regenerated |
| Deletable | No | **Yes, entirely.** Dropping Zone H and rebuilding it is a routine operation and a test | Yes |
| Requires | A source locator | A `processing_run` | A `processing_run` **and** a model/version, and a review state |
| Enters the UI | always, labelled with its source | always, labelled derived | only with an explicit visual marker |
| Enters an export | yes | yes | only when asked for, and separately |
| Can support an atlas conclusion | yes | yes | **no, until promoted through curation** |

The promotion path is one-way and audited: a Zone I item reviewed and accepted by a curator
becomes an assertion whose evidence cites the Zone I item *and* the human review event. The
original Zone I row is retained, not consumed. Rejection is also recorded — a rejected extraction
that keeps being re-proposed by a model is a signal about the model, and throwing it away loses
that signal.

## D.3 Layer map

```
┌─────────────────────────────────────────────────────────────────────────┐
│ INTERFACE     web UI · REST API · MCP server · exports · notebooks      │
├─────────────────────────────────────────────────────────────────────────┤
│ QUERY         structured SQL · graph traversal · lexical · semantic     │
│               ─────────────── hybrid ranking, always cited ──────────── │
├─────────────────────────────────────────────────────────────────────────┤
│ KNOWLEDGE     assertions · evidence · conflicts · curation queue        │
│               materialized knowledge graph (rebuilt, not authored)      │
├─────────────────────────────────────────────────────────────────────────┤
│ DOMAIN        genomic · transcriptomic · metabolic · engineering ·      │
│               phenotype · literature vocabularies                       │
├─────────────────────────────────────────────────────────────────────────┤
│ HARMONIZATION unit conversion · gene-group mapping · condition parsing  │
│               · ID resolution · omics reprocessing        [Zone H]      │
├─────────────────────────────────────────────────────────────────────────┤
│ INGEST        source adapters · relevance ranking · extraction          │
│               · validation gates                          [→ Zone R]    │
├─────────────────────────────────────────────────────────────────────────┤
│ SOURCES       NCBI/SRA/GEO/ENA · SGD · UniProt · KEGG/MetaCyc/Rhea ·    │
│               YEASTRACT · Europe PMC · Crossref · BRENDA · TCDB         │
└─────────────────────────────────────────────────────────────────────────┘
```

Each layer may call only the layer below it. The specific violation to guard against: the UI
reaching into files directly, or an agent writing to the domain layer without passing the
validation gate.

---

# E. Genomics architecture

## E.1 Purpose

Answer "what is this gene, in this strain, and how does it differ from the reference" — and
supply the gene-group anchor that everything else joins on.

| | |
|---|---|
| **Why** | Industrial-vs-laboratory strain differences are one of the four core scientific questions, and nothing else can resolve a gene identity. |
| **Stores** | Assemblies, annotations, gene models, proteins, features, variants, comparative results. |
| **In** | RefSeq/GenBank/SGD assemblies and annotations; published VCFs; strain resequencing data. |
| **Out** | `gene_group` anchors; per-strain gene presence/absence; variant sets; promoter and regulatory regions. |
| **Connects** | Transcriptomics (quantification target), engineering (modification loci), pathway (gene→enzyme). |
| **Automate** | Assembly ingest, annotation parsing, protein QC gate, ortholog construction, variant annotation. |
| **Human** | Gene-family group assignments; any variant claimed to be causal; strain-class assignment. |

## E.2 What is ingested

| layer | source | phase |
|---|---|---|
| S288C reference genome + annotation | SGD / RefSeq (R64) | 1 |
| CEN.PK113-7D, W303 | published assemblies | 1 |
| Industrial/bioethanol assemblies (Ethanol Red, PE-2/JAY270, CAT-1 …) ⚠ | NCBI | 2 |
| Population variation across ~1,000 *S. cerevisiae* isolates ⚠ | the published 1002/1011 Yeast Genomes VCF and assemblies | 2 |
| Tier-2 yeast genomes | RefSeq | 3 |
| Tier-3 bacterial genomes | RefSeq, gene-level only | as needed |

**AMENDMENT 2026-09-20 — DUET §5.3 and owner direction. Accessions pinned; two rows re-phased.**

*What this replaces:* "published assemblies" and "NCBI" as unpinned source descriptions, the
phase-2 placement of the industrial assemblies, and the "gene-level only" depth for bacterial
genomes.

*Why:* an assembly named without its accession and version is not a reproducible input — the
project's own rule that a gene id is meaningless without its assembly applies to the plan as much
as to the data. And the two proxy strains of B.4 are not phase-2 nice-to-haves; they are how the
atlas represents a chassis whose genome does not exist publicly, so they are needed when the first
strain-level conclusion is drawn.

*Pinned, verified on NCBI 2026-09-20:*

| strain | accession | level | contig N50 | centre | phase | role (B.4) |
|---|---|---|---|---|---|---|
| S288C | RefSeq **R64** | Chromosome | — | SGD | 1 | anchor namespace |
| **CEN.PK113-7D** | **GCA_002571405.2** | Chromosome | 913 kb | Delft | **1** | physiology comparator |
| **Ethanol Red** | **GCA_029255905.1** | Scaffold | 189 kb | Padova | **1** (was 2) | industrial proxy |

The accession **with its version suffix** is stored, not the assembly name. A version bump is a new
assembly and a new set of coordinates, and the atlas treats it as such.

*The Ethanol Red caveat, recorded where it will be read.* GCA_029255905.1 is **scaffold-level with
a 189 kb N50**, against 913 kb for the chromosome-level CEN.PK assembly. That is a fourfold
difference in continuity and it constrains what the industrial proxy can be asked. Gene content,
presence/absence and sequence-level comparison are fine; **synteny, structural variation,
subtelomeric content and copy number are not**, and copy number is exactly what matters for a
polyploid chassis. Where a question needs chromosome-scale continuity, CEN.PK answers it and the
answer is labelled a laboratory-strain answer. The atlas does not paper over the gap by preferring
whichever assembly is convenient.

*Bacterial genomes are no longer gene-level only.* Per the B.4 amendment, **E. coli K-12 MG1655,
Z. mobilis ZM4, L. cremoris, C. glutamicum and B. subtilis** get full assembly + annotation from
RefSeq, phase 2. The remaining bacteria stay gene-level. Accessions are pinned at ingest with the
same rule as above and are not listed here, because unlike the two yeast proxies they have not been
verified in this session and writing them from memory would be exactly the failure this project
forbids.

**Decision: consume published variant calls rather than re-calling from reads, in phase 2.**
Re-calling ~1,000 isolate genomes is days of compute and a large storage commitment to reproduce
a published result. The atlas re-calls only where it needs something the published VCF does not
have — a specific industrial strain, or a consistent call set across a comparison.

## E.3 Components

**Assembly & annotation store.** Assembly, sequence (bgzip + faidx, random access), gene models,
transcripts, CDS with phase, proteins, UTRs, promoters and terminators as derived intervals.
Coordinates 0-based half-open internally, 1-based inclusive only at the edge — carried directly
from `genome-db`'s conventions, which document exactly how much damage the alternative causes.

**The protein QC gate.** Re-splice and translate every CDS, compare to the source protein FASTA,
refuse the ingest below a threshold. `genome-db` runs this at 99.5% and reports 99.86% achieved.
It catches phase errors, coordinate errors and off-by-ones that are otherwise invisible until a
promoter sequence is silently wrong. **Non-negotiable; it is the cheapest correctness insurance
in the whole system.**

**Comparative genomics.** SNPs, indels, CNV, structural variants, gene presence/absence,
promoter and regulatory variation, at gene-group level. Two invariants carried from `genome-db`'s
variant layer, both learned the hard way there:

* A sequence name means nothing without its assembly. Never join on `chrIV` alone.
* A lifted coordinate and an independently called one differ by the length of the repeat around
  an indel. Match variants by interval overlap with a repeat-length tolerance, **never** by exact
  lifted position.

**Strain–variant–phenotype linking.** The payoff layer: variants enriched in high-producing or
tolerant strains. This is where the correlation-versus-causation discipline is most needed —
industrial strains differ from lab strains at tens of thousands of positions ⚠ and almost none of
them are causal. Output is explicitly Zone I (an association) unless a paper demonstrates the
variant's effect by reconstruction, which makes it Zone R evidence for a causal assertion.

## E.4 Genes that must be right on day one

A named list is a test, not documentation. The atlas's genomic layer is not usable until each of
these resolves to a gene group with its standard name, systematic name, product, compartment and
reactions:

*Ethanol and central carbon:* `PDC1 PDC5 PDC6 ADH1 ADH2 ADH3 ADH4 ADH5 SFA1 GPD1 GPD2 GPP1 GPP2
ALD2 ALD3 ALD4 ALD5 ALD6 ACS1 ACS2 PYK1/CDC19 PYK2 PFK1 PFK2 HXK1 HXK2 GLK1 TDH1 TDH2 TDH3 ENO1
ENO2 PGK1 TPI1 FBA1 PDA1 PDB1 LAT1 LPD1 PYC1 PYC2 MAE1` ⚠

*Sugar transport and pentose utilization:* `HXT1–HXT17 GAL2 SUC2 MAL genes XKS1 TAL1 TKL1 RKI1
RPE1 GRE3 PHO13` ⚠

*Isobutanol and branched-chain:* `ILV1 ILV2 ILV3 ILV5 ILV6 BAT1 BAT2 LEU1 LEU2 LEU4 LEU9 ARO10
ARO8 ARO9 ADH6 ADH7 MAE1` plus heterologous `alsS` (*B. subtilis*), `ilvC ilvD` (*E. coli*),
`kivD adhA` (*L. lactis*) ⚠

*Regulation and tolerance:* `MSN2 MSN4 HSF1 HAA1 YAP1 SKN7 PDR1 PDR3 WAR1 ROX1 HAP1 MIG1 SNF1
ADR1 CAT8 TPS1 TPS2 NTH1 PMA1 INO1 OPI1 ERG3 ERG6 ERG11 SPT15 HSP12 HSP26 HSP104` ⚠

*Transport of alcohols and stress:* the relevant `PDR`/`SNQ`/`AQR`/`QDR`/`FPS1` set ⚠

Every entry is ⚠ and must be resolved against SGD during phase 1 — that resolution *is* the
phase-1 genomics acceptance criterion.

---

# F. Transcriptomics architecture

## F.1 Purpose and the central tension

Two things are wanted and they conflict: the study's **own published results** (what the authors
concluded, which is what the literature says) and a **uniformly reprocessed** version (which is
what makes studies comparable). The resolution is to store both, permanently, and never let one
overwrite the other.

| | |
|---|---|
| **Why** | Expression evidence is how "which genes are associated with X" is answered at scale. |
| **Stores** | Studies, samples, published results, reprocessed quantifications, contrasts, DE results, co-expression modules, meta-analyses. |
| **In** | SRA/ENA runs, GEO series and supplementary matrices, published DE tables. |
| **Out** | Per-gene-group expression, contrast results, conserved and context-specific response sets. |
| **Connects** | Genomics (quantification reference, gene groups), phenotype (samples with measurements), assertions. |
| **Automate** | Discovery, download, QC, quantification, normalization, DE, enrichment, co-expression. |
| **Human** | Condition annotation for every study (see F.3 — this is the bottleneck); contrast definition; any conclusion drawn across studies. |

## F.2 Data model

Adapted from `genome-db`'s expression schema, which is battle-tested, with three changes.

```
study            accession, repository, title, publication_id, design_type
sample           study_id, run_accession, strain_id, condition_context_id,
                 library {layout, strandedness, platform, selection},
                 qc {reads, mapping_rate, decoy_rate, libtype, rin},
                 metadata_completeness, condition_evidence, condition_confidence
quantification   sample_id, processing_run_id, target_assembly, matrix_ref → Parquet
expression_value gene_group_id, sample_id, counts, tpm, normalized      [Parquet, not rows]
contrast         study_id, treatment_condition, control_condition, method, origin
de_result        contrast_id, gene_group_id, log2fc, base_mean, pvalue, padj
```

The three changes from `genome-db`:

1. **`origin` on `contrast`**, generalizing its `source IN ('geo','salmon')`:
   `published` (the authors' own DE table, as published), `reprocessed` (computed here from
   reprocessed counts), `recomputed_from_published_counts` (computed here from the authors'
   count matrix). Three different provenances that get conflated constantly.
2. **Expression values in Parquet, not in the database.** `genome-db` measured its own
   `value` table at ~113 bytes/row and projected ~350 MB for 7M rows in SQLite. This atlas
   targets thousands of samples across many studies — 6,000 gene groups × 5,000 samples is
   30M values, which is 120 MB as a float32 Parquet matrix and several gigabytes as relational
   rows with worse analytical performance. The database holds sample and study metadata and a
   pointer; DuckDB reads the matrices.
3. **`condition_evidence` and `condition_confidence` on `sample`** — carried directly from
   `genome-db`'s `data/rnaseq/geo_run_conditions.tsv`, which records for every run the sentence
   the condition was derived from and whether it was stated or inferred. This is the single most
   valuable pattern in the reference project for this atlas.

## F.3 The metadata problem, stated plainly

**SRA and GEO metadata almost never contain what this atlas needs.** Aeration regime, actual
sugar concentration, fermentation mode, whether pH was controlled, the titer at the sampling
point — these live in the paper's methods section, often in prose, sometimes only in a figure.

This is the project's biggest hidden cost and the main reason the transcriptomic layer must not
be sized by how many runs exist in SRA. The pipeline is therefore:

```
discover runs → rank relevance → fetch the paper → extract conditions from the METHODS
   → LLM proposes a condition_context with quoted spans → curator accepts/edits
   → only then is the run queued for quantification
```

Quantifying a run whose conditions are unknown produces a column in a matrix that cannot be used
in any comparison.

**Amended 2026-09-20. This gate was an economic rule wearing a scientific costume, and the two
have now been separated:**

| rule | status |
|---|---|
| *No contrast, comparison or aggregate without an approved `condition_context`* | **Scientific. Stands unconditionally.** This is what protects every downstream claim |
| *Do not quantify a run whose conditions are unknown* | **Economic. Void when compute is free.** It existed to avoid spending cloud time and storage on columns nobody could use |

The isobutanol corpus is ~50 GB — roughly 36 core-hours, which is about **$9 of spot compute** on
the `c7i.16xlarge` the omics track uses. *(Amended 2026-09-20: this read "120 runs and 51 GB". Two
runinfo fetches of the same query disagree — 120 runs / 51 GB and ~148 runs / ~48 GB — and
DATA_VOLUME §2 records both rather than picking one. The arithmetic below is unaffected at this
resolution, which is the point: no decision here turns on the difference.)* Quantifying the handful of runs whose
conditions never get resolved therefore wastes single-digit dollars, against a real gain: mapping
rates and QC expose unusable runs immediately, and an exploratory matrix exists months before
condition curation finishes.

The rule was written when the corpus in view was thousands of runs, where that arithmetic
reverses.

So: **quantify everything now, define contrasts only from approved conditions.** A quantified run
with unknown conditions is a legitimate artifact carrying `condition_context = NULL`; it simply
cannot enter a contrast, and the schema enforces that rather than the pipeline order.

The rule reverts to its original form if the corpus ever expands to a scale where compute is a
real cost — the ethanol universe at 13,117 runs, for instance.

## F.4 Processing pipeline

```
run accession
  → fetch (ENA FASTQ preferred over SRA .sra for throughput ⚠)
  → fastp: adapter and quality trimming, QC report
  → salmon selective alignment against a decoy-aware index of the strain's
    (or the nearest suitable) reference transcriptome
  → per-run QC gate: mapping rate, decoy rate, library type consistency within study
  → tximport → gene-group-level counts
  → normalization (DESeq2 median-of-ratios within study; TPM for cross-sample display)
  → contrasts (DESeq2) against curator-defined condition pairs
  → enrichment (GO, KEGG, curated panels)
  → co-expression (WGCNA within study; consensus modules across studies)
  → FASTQ deleted; quant output, QC JSON and logs retained
```

**Decision: transient FASTQ.** Storage is sized for what is kept, not what passes through.
3,000 yeast RNA-seq runs are roughly 3–4 TB of compressed FASTQ ⚠ but under 10 GB of retained
quantification output. Streaming 10–20 concurrently with immediate deletion turns a 4 TB storage
problem into a 200 GB working-set problem. The cost is that re-quantification means
re-downloading, which is acceptable because the pipeline is versioned and deterministic.

**Decision: quantify against S288C R64 in phase 3, per-strain references later.** Mapping an
industrial strain's reads to S288C loses genes absent from S288C and mis-quantifies divergent
ones. The honest first step is one reference, with the loss measured (unmapped fraction per
strain) and reported, moving to per-strain or pangenome references once the loss is quantified.
Recording the target assembly on every quantification is what makes that transition possible
without invalidating earlier data.

**AMENDMENT 2026-09-20 — DUET §5.3. "One reference" becomes "one anchor plus two proxies", because
the corpus is not one strain.**

*What this replaces:* the decision immediately above, in its unqualified form — *quantify
everything against S288C R64 in phase 3, per-strain references later*. The **anchor** half of that
decision stands. The **only** half does not.

*Why: the transcriptomic corpus is not S288C.* The measured SRA isobutanol corpus (DATA_VOLUME §2)
contains **104 yeast RNA-Seq runs — 56 submitted as *S. cerevisiae* and 48 as *S. cerevisiae*
S288C**. The 56 are not S288C by declaration and are not necessarily S288C in fact: isobutanol work
is done in CEN.PK, in BY-derived laboratory strains and in industrial backgrounds, and the
submitter's organism field records what was typed, not what was sequenced. Quantifying all 104
against R64 and reporting one number per gene would silently mix strains whose gene content differs
— and gene *absence* in an industrial strain reads as "expressed at zero", which is the precise
error the missing-value rule exists to prevent.

*The rule, restated:*

1. **S288C R64 remains the anchor.** Every run is quantified against it, so there is always one
   comparable space, and `gene_group` (C.3) is what results are reported on — never a raw gene id.
2. **Runs whose submitted strain resolves to CEN.PK113-7D or to an industrial background are
   additionally quantified against their own proxy** — GCA_002571405.2 and GCA_029255905.1
   respectively. Two quantifications of the same run, each recording its target assembly. They are
   stored side by side and are never averaged.
3. **The unmapped fraction and the decoy rate per run per reference are first-class QC outputs**,
   not log lines. A run whose mapping rate against R64 is materially worse than against its proxy
   is evidence that the strain assignment matters for that study, and it is surfaced rather than
   absorbed into the QC gate.
4. **`reference_assembly` is required on every quantification row and on every contrast.** A
   contrast may not mix quantifications made against different references. This is enforced by the
   schema, not by pipeline discipline.
5. **Strain assignment is curated, not trusted.** The submitted organism field enters as Zone R
   `as_reported`; the resolved strain is Zone H with its own evidence and confidence, and
   `'unknown'` is a legitimate resolution for a run whose paper does not name a background. An
   unknown-strain run is quantified against the anchor only.

*Bacterial runs are separate and are not affected by any of this.* The 20 *E. coli* K-12 MG1655,
11 *Z. mobilis* ZM4 and 5 *L. cremoris* runs are quantified against their own species' RefSeq
annotation — now ingested per the B.4 and E.2 amendments — and never against a yeast reference.
Their results reach yeast questions through `ortholog_link` (C.3), which is a claim carrying a
method and a score, never an identity, and never a merge into a yeast `gene_group`. The Tn-Seq runs
in the corpus are *Zymomonas* fitness screens, not expression data, and do not enter the
quantification pipeline at all; they are a separate data type with a separate model.

QC gates carried from `genome-db`: mapping rate ≥ 0.50 accept / 0.35–0.50 flag / below reject ⚠,
rates stored as fractions in [0,1] with a CHECK constraint — because a percentage written where a
fraction belongs is the one silent error this column class has.

## F.5 Published results are also ingested

For every study, the authors' own DE table and conclusions are captured as
`contrast(origin='published')` plus extracted claims. Reasons: many important studies predate
usable raw deposition or have no recoverable raw data; the authors know their experiment; and
disagreement between the published result and the reprocessed one is itself a finding worth
surfacing rather than hiding.

## F.6 Cross-study integration: the binding constraint

Stated here rather than only in K.4, because it determines what the transcriptomic layer is
allowed to claim.

`genome-db` normalizes expression per experiment as gene-centred log2, and its network plan
records the consequence as an explicit constraint: **a condition difference survives only if both
conditions occur within some experiment.** Single-condition studies contribute nothing to it, and
eighteen deposited projects were consequently never imported.

For this atlas that constraint binds harder than it did there, because the ethanol and isobutanol
literature is made of *many small studies*, a large fraction of which profile one condition, one
strain, one timepoint. A design that integrates by merging normalized expression matrices across
studies would therefore (a) discard most of the corpus and (b) confound the remainder with batch
and lab effects that are perfectly aliased with the biological factor of interest.

**Decision: the unit of cross-study integration is the contrast, not the expression value.**

| level | what crosses study boundaries | what does not |
|---|---|---|
| Within study | expression values, co-expression, PCA, any direct numeric comparison | — |
| Across studies | **effect sizes and their directions** (log2FC with standard error, or ranks), combined by random-effects meta-analysis or rank aggregation | raw or normalized expression values |
| Never | — | a merged matrix presented as if one experiment |

Consequences, all deliberate:

* A study with no internal contrast contributes to condition annotation, co-expression within
  itself, and gene-level presence — but not to differential-expression meta-analysis. It is
  recorded as such rather than dropped silently.
* Batch correction (ComBat-seq, RUV, surrogate variables) is available for *within-study* designs
  and for explicitly constructed multi-study analyses, but a corrected matrix is a Zone I artifact
  with its correction recorded, never a replacement for the study's own values.
* Meta-analysis output (a gene consistently up under alcohol stress across nine studies) is a
  Zone I result that can be *promoted* to an L3 assertion under J.3, with the constituent
  contrasts as its evidence.

Two further guards, both from mistakes recorded in the reference project:

* **The declared unit is the only authority.** "The scale of an expression matrix cannot be
  inferred from its numbers" — a matrix of counts, TPM and log2 ratios all look like numbers.
  Every matrix carries its unit and every operation refuses input whose unit it cannot accept.
* **Rank correctly.** An argsort of an argsort is not a rank; ties handled that way created
  co-expression edges that did not exist. Rank aggregation uses a real ranking function with
  explicit tie handling, and the meta-analysis has a test asserting tied inputs produce tied
  ranks.

---

# G. Metabolic architecture

## G.1 Purpose

| | |
|---|---|
| **Why** | Pathways are how genes, enzymes, metabolites and interventions are related to each other; without them the atlas is a list. |
| **Stores** | Metabolites, reactions, enzymes, cofactors, compartments, transporters, pathways, pathway configurations, regulatory nodes. |
| **In** | KEGG, MetaCyc/YeastCyc, Rhea, Yeast9 GEM, BRENDA, UniProt, TCDB, curation. |
| **Out** | Pathway subgraphs, competing-reaction sets, precursor traces, auto-generated diagrams. |
| **Connects** | Genomics (gene→protein→enzyme), engineering (interventions land on reactions), transcriptomics (pathway-level expression). |
| **Automate** | Import and reconciliation of public pathway data; diagram layout; competing-branch detection by graph traversal. |
| **Human** | The two curated core pathways; every compartment assignment that differs between sources; every "competing reaction" designation. |

## G.2 Model

A reaction-centric graph, not a picture:

```
metabolite   id, name, chebi, inchikey, formula, charge
compartment  cytosol | mitochondrion | peroxisome | vacuole | ER | nucleus |
             extracellular | membrane | unknown            -- mandatory, 'unknown' explicit
reaction     id, rhea/kegg/metacyc xrefs, stoichiometry[] {metabolite, coeff, compartment},
             cofactors[] {cofactor, role, stoichiometry},  -- NADH/NADPH/ATP/CoA/TPP/Mg
             reversibility, ec_numbers[], delta_g_estimate
enzyme       id, ec, uniprot, gene_group_id, kinetics[] {km, kcat, substrate, source, conditions}
transporter  id, tcdb_class, substrate, direction, driving_force, gene_group_id
pathway      id, product_id, name, scope
pathway_step pathway_id, reaction_id, order, role: core | competing | precursor | bypass | salvage
regulatory_node  pathway_id, reaction_id, regulator (TF or metabolite), mode, evidence
```

`role` on `pathway_step` is what makes "competing pathway" contextual rather than a global flag —
the ethanol branch is the *target* in an ethanol pathway and a *competing* branch in an
isobutanol pathway, and both statements are true simultaneously.

## G.3 The two curated pathways

Public pathway databases are the starting material, not the product. Both core pathways are
hand-curated against the literature, because the details that matter — compartment, cofactor
specificity, which paralog actually carries flux under which condition — are exactly what
automated imports get wrong or omit.

**Ethanol** (*S. cerevisiae*, glucose):

```
glucose --HXT--> glucose(cyt) --HXK1/HXK2/GLK1--> G6P --> ... glycolysis ...
  --CDC19/PYK2--> pyruvate(cyt)
       ├── PDC1/PDC5/PDC6 [TPP] --> acetaldehyde --ADH1 [NADH]--> ETHANOL
       ├── ALD6 [NADP+] --> acetate --ACS1/ACS2 [ATP]--> acetyl-CoA        (competing)
       ├── PDH complex (mitochondrial) --> acetyl-CoA --> TCA              (competing)
       ├── PYC1/PYC2 --> oxaloacetate --> anaplerosis                      (competing)
       └── via DHAP: GPD1/GPD2 [NADH] --> G3P --GPP1/GPP2--> GLYCEROL      (competing, redox sink)
```

The glycerol branch is annotated as the principal anaerobic redox sink for surplus cytosolic
NADH ⚠ — which is why it is the most-deleted competing pathway in the ethanol literature and why
deleting it without providing an alternative NADH sink impairs anaerobic growth ⚠. That
relationship (intervention → consequence → compensating intervention) is stored as linked
assertions, and it is the template for how the atlas represents engineering trade-offs.

**Isobutanol** (*S. cerevisiae*, glucose):

```
2 × pyruvate(mito) --ILV2/ILV6 [TPP]--> 2-acetolactate
   --ILV5 [NADPH]--> 2,3-dihydroxyisovalerate
   --ILV3--> 2-KETOISOVALERATE  (mitochondrial)
        ├── BAT1(mito)/BAT2(cyt) --> VALINE                         (competing)
        ├── LEU4/LEU9 --> 2-isopropylmalate --> leucine             (competing)
        ├── ECM31 --> ketopantoate --> PANTOTHENATE / CoA           (competing) ⚠
        └── [transport / compartment boundary — the engineering problem]
             2-ketoisovalerate(cyt) --ARO10/PDC1/PDC5/PDC6 or kivD--> isobutyraldehyde
                --ADH1-7 / ADH6 / adhA [NADH or NADPH]--> ISOBUTANOL
```

Annotated with: the compartment boundary and the two published strategies for resolving it
(cytosolic relocalization of the Ilv enzymes; mitochondrial targeting of the Ehrlich enzymes) ⚠;
the NADPH/NADH mismatch across Ilv5 and the alcohol dehydrogenase ⚠; the promiscuity of the
2-ketoacid decarboxylases, which is why isoamyl alcohol and 2-methyl-1-butanol appear as
by-products ⚠; and pyruvate competition with Pdc-mediated ethanol formation.

**AMENDMENT 2026-09-20 — DUET §6. `ECM31` added to the 2-KIV competing-reaction set.**

*What this replaces:* the competing-reaction set at the 2-ketoisovalerate node, which listed the
valine branch (`BAT1`/`BAT2`) and the leucine branch (`LEU4`/`LEU9`) and stopped there. That set
was incomplete, not merely abbreviated.

*Why:* **`ECM31`, ketopantoate hydroxymethyltransferase, draws 2-ketoisovalerate into pantothenate
and thence CoA biosynthesis (unverified)**. It is a third drain on the precursor pool the whole
route is competing for, and it was missing from the sketch. It is named in the DUET gene set
(DUET_TARGET §3) among the competing / by-product genes, so the destination document had it and
this plan did not.

*Consequences for the model, not just the diagram:*

* `ECM31` is a member of the competing-reaction set wherever that set is enumerated — route
  enumeration (G.7), the bottleneck model (G.8), and the deletion candidates a route proposes.
* **It is not interchangeable with `BAT1`/`BAT2` or `LEU4`/`LEU9` as a deletion candidate.**
  Pantothenate is a CoA precursor and the pathway is plausibly essential (unverified); an
  `ecm31Δ` proposal must carry an essentiality check and, if essential, an attenuation rather than
  a deletion. The route ranker must be able to tell "delete" from "attenuate" for this node.
* Flux through it is likely small relative to the valine branch (unverified). Small does not mean
  ignorable when the pool is the bottleneck, and the honest state is that **the atlas has no
  measured split of 2-KIV between the three drains in any chassis**. That is a `knowledge_gap` row
  (G.8), seeded now, not a gap discovered during curation.
* Every claim in this amendment about `ECM31`'s biochemistry is **(unverified)** — asserted from
  background knowledge and never checked against a source. It enters the database at
  `confidence = 'unverified'` and must be re-verified against primary literature before any
  assertion depends on it. The same mirrored text is in `ISOBUTANOL_PROGRAM.md` §1; the two must
  be corrected together when it is checked.

Both diagrams are **generated from the database**, not drawn. If the diagram and the data can
disagree, the diagram is decoration. See section P.3.

## G.4 `pathway_configuration`

The entity that answers "which pathway configurations have been experimentally validated":

```
pathway_configuration
  id, product_id, host_organism_id, host_strain_id
  enzyme_set[]  {step, gene_group or heterologous gene, source_organism, compartment_targeted}
  cofactor_strategy   native | switched_KARI | transhydrogenase_cycle | NADPH_ADH | other
  compartment_strategy  native_split | cytosolic_relocalization | mitochondrial_targeting |
                        peroxisomal | other
  best_measurement_id → measurement
  publications[]
```

This turns a diffuse literature into a comparable table: every published isobutanol pathway build
as one row, with what it achieved and under what conditions.

## G.5 The compartment and mitochondrial layer

New in the isobutanol-first scope. Full design in `docs/design/ISOBUTANOL_PROGRAM.md`; the
contract is here.

`compartment` stops being a label and becomes an entity with properties that constrain design:

```
compartment
  id                  cytosol | mitochondrial_matrix | mitochondrial_ims |
                      mitochondrial_inner_membrane | peroxisome | ...
  encoding_genomes[]  which genomes can encode a protein found here.        -- B.6 point 3
                      cytosol, ims, peroxisome: (nuclear,)
                      matrix, inner membrane:   (nuclear, mitochondrial)    <- BOTH
  cofactor_pools[]    NADH, NADPH, ATP, CoA — pooled separately per compartment
  import_machinery    TOM/TIM for matrix; PTS1/PTS2 for peroxisome
  ph_estimate, redox_estimate

encoding_genome                                    -- this, not compartment, decides the code
  id                  nuclear | mitochondrial
  genetic_code_table  1 (standard) | 3 (yeast mitochondrial)
```

**`compartment` deliberately has no `genetic_code_table` column.** A compartment served by both
genomes has no single answer, and giving it one is the error corrected in B.6 point 3.

Two distinct modification types, never merged (B.6 point 2):

```
localization_change   -- nuclear gene, targeting sequence added/removed/swapped
  target_compartment, targeting_sequence, source_of_sequence,
  cleavage_site_predicted, n_terminal_fusion_retained,
  verification_method   microscopy | fractionation | protease_protection |
                        activity_in_fraction | none_reported
  import_efficiency_reported

mtdna_edit            -- the mitochondrial genome itself
  technique   biolistic_transformation | mitoTALEN | mitoZFN | base_editor | other
  recipient_state  rho0 | rho- | rho+ heteroplasmic
  marker, recoded_for_table_3 (bool), heteroplasmy_achieved
  feasibility_rating, labs_demonstrating
```

`verification_method` is mandatory and defaults to `none_reported`, because a claimed
relocalization with no localization evidence is a common and consequential weak point — the
construct may simply not be imported, and the paper's conclusion rests on it. The atlas shows the
verification method next to every localization claim.

`feasibility_rating` on mtDNA techniques (`routine` / `specialist` / `frontier` / `not
demonstrated in this organism`) is what stops the route ranker from proposing an mtDNA edit as
casually as a promoter swap.

## G.6 The parts catalog

The engineer's working object, and the reason role-4 organisms are ingested at all.

```
part
  id, step_role  (AHAS | KARI | DHAD | KDC | ADH | transporter | cofactor_cycle)
  source_organism_id, gene_group_id, sequence, variant_of
  cofactor_preference {NADH | NADPH | either}, engineered_switch (bool)
  kinetics[] {km, kcat, substrate, conditions, source}
  oxygen_sensitivity        -- matters for DHAD-class [Fe-S] enzymes ⚠
  expression_records[] {host, compartment, codon_optimized, promoter,
                        expressed_ok, activity_measured, outcome_measurement_id}
```

`expression_records` is the field that makes the catalog worth having: the same part behaves
differently in different hosts and compartments, and "worked in *E. coli*" is not "works in the
yeast mitochondrial matrix". One row per demonstrated host/compartment combination, each with its
evidence.

## G.7 Route enumeration and ranking

The atlas's primary output. **Enumeration is generative, not a catalogue of published builds** —
that is what allows "what has never been tried" (B.5) to be answered as the complement of the
evidence rather than as a guess.

```
pathway_route = { step → part } × compartment assignment per step
                × cofactor strategy × host × deletion set
```

Each enumerated route is then filtered and scored:

| gate | check | effect |
|---|---|---|
| Stoichiometric | Carbon, redox and ATP balance, **per compartment** | Fails → excluded, with the imbalance named |
| Code | Sequences recoded correctly for their **encoding genome's** table — mtDNA-carried genes only; presequence-targeted nuclear genes need none | Fails → flagged as a construction requirement |
| Transport | Every metabolite crossing a membrane has a carrier, or an explicit gap | Gap → route carries a named risk |
| Feasibility | Technique maturity for each required modification | Downweights mtDNA-editing routes |
| Evidence | Demonstrated outcomes for this route or its nearest neighbours | Primary ranking term |
| Toxicity | Route-predicted titer against measured tolerance | Caps the realistic ceiling |

Scores are **shown as their components, never as a single opaque number**, and a route's rank is
explainable by listing which term dominated. Routes with no supporting evidence are displayed —
that is the point — but in a separate, explicitly-labelled band (Zone I), never interleaved with
demonstrated ones.

## G.8 The bottleneck model

A bottleneck is an assertion with its own predicate and a required shape, so that it cannot be
recorded as a vague opinion:

```
bottleneck
  reaction_id | transport_step | node
  route_context      which configuration it was observed in
  evidence_type      metabolite_accumulation | flux_measurement | overexpression_relieved |
                     deletion_worsened | in_vitro_kinetics | inferred
  fix_attempted[]    intervention → outcome (worked | partial | no effect | worse)
  recurrence         independent studies observing it
```

`fix_attempted` with its outcomes is the highest-value field in the schema for the user's actual
goal: it converts "2-KIV supply is limiting" from folklore into a record of what people did about
it and whether it helped.

---

# H. Literature architecture

## H.1 Purpose

| | |
|---|---|
| **Why** | Most of what is known about industrial fermentation exists only in papers; the structured databases do not have it. |
| **Stores** | Publications, their metadata, licensing state, retrieved full text where permitted, extracted claims with spans, and the links from claims to every other entity. |
| **In** | PubMed, Europe PMC, Crossref, Unpaywall, bioRxiv, publisher OA feeds. |
| **Out** | Citations for every assertion; the corpus for semantic search; the raw material for extraction. |
| **Connects** | Everything — a publication is the terminal node of most provenance chains. |
| **Automate** | Discovery, deduplication, metadata normalization, OA full-text retrieval, section splitting, embedding, candidate extraction. |
| **Human** | Inclusion decisions at the margin; every extracted quantitative claim in phase 1; conflict adjudication. |

## H.2 Corpus construction

Query families rather than one query: product × organism × topic, run against PubMed and Europe
PMC, plus citation-graph expansion (forward and backward) from a hand-picked seed set of ~50
papers per product, plus the publications linked from every ingested dataset accession.

Expected scale ⚠: ethanol + yeast is a very large literature (tens of thousands of records);
isobutanol + microbial production is far smaller (low thousands). The ethanol side therefore
*needs* the relevance-ranking pipeline; the isobutanol side can plausibly be read in full, which
makes it the better place to start and to measure extraction quality against a human baseline.

## H.3 Relevance ranking and inclusion

The brief's instruction — *do not simply download everything* — becomes a staged filter, with the
cheap stages first:

```
candidate → deduplicate (DOI/PMID/title-normalized)
  → hard filters: organism in scope, product in scope, is primary research
  → topical classifier on title+abstract → relevance score
  → industrial-relevance score: does it report a titer, yield, productivity, a strain
    modification, or a fermentation condition? (the atlas's actual currency)
  → triage: include / full-text-needed / exclude, each with a reason
  → human review of everything near the threshold and a random audit sample of the rest
```

Every exclusion stores its reason. An excluded paper is a decision, not an absence, and a
changed inclusion policy must be re-runnable against the exclusions — which is impossible if they
were never recorded. `genome-db` does this already in a small way: its
`data/rnaseq/literature.tsv` carries a `needed_for` column saying why each paper was fetched and
a `status` column recording `fetched` versus `paywalled`.

## H.4 Legal and access constraints

Stated in the architecture because they constrain it:

* Abstracts and metadata from PubMed/Europe PMC/Crossref may be stored and indexed.
* **Full text may be stored only for open-access content under a licence that permits it.**
  Everything else is stored as a pointer plus locally derived, non-substitutive artifacts
  (extracted structured values, embeddings, short quoted spans for provenance).
* Text-mining rights for subscribed content depend on the institution's agreements. The schema
  carries `license`, `oa_status` and `text_mining_allowed` per publication and the pipeline
  honours them; it does not discover them at runtime by trying.
* Extracted *facts* (a titer, a genotype) are not copyrightable; extracted *prose* is. Extraction
  stores values plus short verbatim spans for verification, not reproduced paragraphs.

## H.5 Extraction

Per publication, an LLM-driven extractor emits schema-constrained JSON into Zone I:

```
extraction
  publication_id, section, model, model_version, prompt_version, run_id
  payload            -- typed: strains, modifications, conditions, measurements, claims
  spans[]            -- verbatim quote + character offsets for EVERY extracted value
  self_confidence
  validation         -- deterministic checks, see below
  review_state       proposed | accepted | edited | rejected   + curator + timestamp + reason
```

**No extracted value is storable without a span**, and a deterministic validator re-checks that
each quoted span actually occurs in the source text at the stated offsets. That single check
eliminates the failure mode that matters most — a plausible number that is not in the paper.
Further automatic validation: entity ids must resolve; units must parse; yields must not exceed
the theoretical maximum; a titer must be consistent with its stated units' plausible range for
that product; a strain must exist or be proposed as new with its parent.

## H.6 Protocols

A light layer, as decided in A.2: method summaries extracted per experiment (medium, inoculum,
vessel, sampling, analytics), plus links to protocols.io and to the paper's methods section.
Enough to judge comparability; not a protocol execution system.

---

# I. Experimental phenotype and engineering architecture

## I.1 Purpose

| | |
|---|---|
| **Why** | Titer, yield and productivity under stated conditions are the atlas's reason to exist; the engineering record is what makes it actionable. |
| **Stores** | Measurements (C.6), strain constructions, modifications, and the link from intervention to outcome. |
| **In** | Literature extraction, dataset metadata, supplementary tables. |
| **Out** | Phenotype comparisons, intervention effect sizes, strain rankings, bottleneck evidence. |
| **Connects** | Strains, condition contexts, products, publications, gene groups. |
| **Automate** | Unit normalization, derived metrics, bound checks, effect-size computation, aggregation. |
| **Human** | Parent-strain resolution, genotype parsing, every effect attributed to a single modification, comparability judgements. |

## I.2 The comparison problem

A titer is meaningless alone. 20 g/L ethanol from a shake flask on 50 g/L glucose and 20 g/L from
a fed-batch bioreactor on hydrolysate are not comparable, and no amount of normalization makes
them so. Therefore:

* Every measurement points at a `condition_context`.
* Comparisons are **only** offered within a comparability class (section K.4), or with an
  explicit, visible warning naming the facets that differ.
* The atlas ranks within class and refuses to produce a global "best strain" leaderboard, because
  that number would be read as meaningful and would not be.

## I.3 Phenotype coverage

Production (titer, yield, productivity, specific productivity), physiology (growth rate, biomass
yield, substrate uptake, fermentation time, oxygen requirement), by-products (glycerol, acetate,
succinate, isoamyl alcohol, 2-methyl-1-butanol, CO₂ where reported), and tolerance (to ethanol,
isobutanol, temperature, osmotic pressure, acid, and hydrolysate inhibitors).

Every tolerance measurement carries `assay_type` — growth rate in *x*%, viability after shock,
IC₅₀/MIC, lag extension, spot dilution, competition — and the atlas will not aggregate across
assay types silently (B.5, point 4).

## I.4 The engineering atlas

One `modification` row per genetic change, one `strain_construction` linking parent to child:

```
modification
  strain_id, parent_strain_id
  target_gene_group_id | target_locus | target_pathway_id
  type    knockout | knockdown | overexpression | promoter_replacement | terminator_replacement |
          heterologous_expression | copy_number_change | codon_optimization | protein_engineering |
          localization_change | cofactor_switch | crispr_edit | adaptive_evolution |
          genome_shuffling | mutagenesis | other
  details {promoter, copy_number, integration_locus, source_organism, variant, method}
  intent  increase_flux | remove_competition | improve_cofactor_balance | improve_tolerance |
          improve_transport | reduce_byproduct | other
  measured_effect[] → measurement, with the control it was measured against
  is_isolated_effect  bool   -- was this change made alone, or in combination?
```

`is_isolated_effect` is the field that keeps the engineering atlas honest. Most published strains
carry several modifications at once, so attributing the improvement to any single one is
unjustified. Combination strains store their modifications as a set, and effect is attributed to
the **set**; only a strain differing from its control by one change supports a single-gene
assertion.

This directly serves the two queries in the brief:

* *"all genetic modifications that increased isobutanol production in yeast"* — modifications
  joined to measurements with a positive effect versus their stated control, filtered by product
  and organism, each row carrying whether the effect was isolated, in which conditions, and at
  what evidence level.
* *"genes repeatedly modified in high-ethanol-producing strains"* — modifications grouped by gene
  group, counted by independent publication, with the distribution of outcomes including the
  negative and null results.

Null and negative results are stored with equal status. A gene that ten groups have overexpressed
without effect is one of the most valuable facts the atlas can hold, and it is exactly what a
literature-summary tool loses.

---

# J. Evidence architecture

## J.1 The assertion

```
assertion
  id
  subject       (typed reference: gene_group | strain | reaction | pathway | modification | ...)
  predicate     (a closed, versioned vocabulary — see J.2)
  object        (typed reference or a literal with units)
  context_id    → condition_context, or a partial context ("anaerobic, glucose")
  product_id    where applicable
  direction     increases | decreases | no_effect | required_for | not_required
  effect_size   value, unit, ci, n
  evidence[]    → evidence_item
  level         L1..L5      -- DERIVED, see J.3
  level_override, override_reason, override_curator
  status        active | superseded | disputed | retracted
  created_by    curator | pipeline | agent(model, version)
```

An assertion is never edited. A revision supersedes it and both remain, which is what makes
"what did the atlas say last March" answerable.

## J.2 Predicates

A closed vocabulary, versioned, mapped to Biolink and RO where an equivalent exists. Initial set:

`affects_production_of` · `affects_tolerance_to` · `affects_yield_of` · `catalyzes` ·
`transports` · `regulates` · `is_expressed_under` · `is_differentially_expressed_in` ·
`co_expressed_with` · `is_bottleneck_for` · `competes_with` · `is_required_for` ·
`confers_resistance_to` · `is_localized_to` · `has_variant_associated_with` ·
`improves_when_modified_by` · `interacts_with`

Closed because an open predicate vocabulary makes the knowledge graph unqueryable within a year;
versioned because it will need to grow.

## J.3 Evidence levels, derived rather than assigned

The brief's five-level hierarchy is the public face. Under it, two **orthogonal** axes, because
"repeated experimental evidence" conflates the kind of observation with how often it was made —
and conflating them means a weak assay repeated three times outranks a decisive experiment done
once.

**Axis 1 — evidence type** (what kind of observation):

| code | meaning |
|---|---|
| `direct_perturbation` | The gene/pathway was changed and the product/phenotype measured against a proper control |
| `direct_biochemical` | Enzyme assay, in vitro reconstitution, isotope tracing, flux measurement |
| `correlative_omics` | Differential expression, proteomics, co-expression |
| `comparative_genomic` | Variant or gene presence associated across strains |
| `computational_model` | FBA, kinetic model, structure or sequence prediction |
| `literature_assertion` | Stated in a paper without primary data shown (review, introduction) |
| `ai_inference` | Produced by a model in this system |

**Axis 2 — support**: `n_independent_publications`, `n_independent_groups`, `concordant`,
`discordant`, `n_organisms`, `n_condition_classes`.

**The derived level** (a stated rule, not a judgement, recomputed whenever evidence changes):

| level | rule |
|---|---|
| **L1** Direct experimental | ≥1 `direct_perturbation` or `direct_biochemical` with a stated control, no unresolved discordance |
| **L2** Repeated experimental | L1 criteria met by ≥2 independent groups, concordant in direction |
| **L3** Strong cross-study association | No direct evidence, but concordant `correlative_omics` or `comparative_genomic` support across ≥3 independent studies |
| **L4** Computational prediction | `computational_model` only |
| **L5** Hypothesis | `literature_assertion` or `ai_inference` only |

A curator may override the derived level, but must supply a reason, and the override is displayed
as an override. This is what keeps evidence grading auditable instead of a matter of taste.

**The level is a view, not a column.** `genome-db`'s GRN layer computes its derived judgements
(`grn_tier1_support` — concordant, replicated or conflicting; `perturbation_breadth`) as views
precisely so that they cannot go stale when the evidence under them changes. The same applies
here with more force: evidence accumulates continuously, and a stored level silently becomes a
lie the first time a new paper lands. `assertion.level` is therefore a materialized view over the
evidence, refreshed on evidence change, with the override applied on top.

**Constraints make a mislabelled row unstorable.** `genome-db` stores every GRN edge in one table
with per-tier `CHECK`s: a perturbation edge must carry its contrast, effect and p-value; a motif
edge must carry motif and window and must be unsigned; a literature edge must carry species and
citation, and no other tier may carry them. A row that lies about what kind of evidence it is
cannot be written. The evidence layer here adopts the same discipline, per `evidence_type`:

| evidence_type | required, enforced by constraint |
|---|---|
| `direct_perturbation` | `strain_id`, `control_strain_id` or `control_condition_id`, `measurement_id`, `direction` |
| `direct_biochemical` | `assay_method`, `measurement_id` |
| `correlative_omics` | `contrast_id` or `analysis_result_id`, `effect_size`, `p_adjusted` |
| `comparative_genomic` | `variant_or_gene_set`, `strain_set`, `statistic` |
| `computational_model` | `model_id`, `model_version`, `processing_run_id` |
| `literature_assertion` | `publication_id`, `span` |
| `ai_inference` | `model`, `model_version`, `prompt_version`, `review_state`, and **must not** carry a `measurement_id` |

The last row is the important one: an AI inference is structurally prevented from masquerading as
a measurement.

Mapping to ECO (the Evidence and Conclusion Ontology) is recorded per evidence item so the atlas
can export into the wider ecosystem, but the L1–L5 face stays, because it is what users asked for
and what fits in a UI badge.

## J.4 Conflicts are first-class

```
conflict
  assertion_ids[], kind (direction | magnitude | presence | identity),
  context_difference  -- the facets that differ between the conflicting studies
  status  open | explained_by_context | resolved | irreconcilable
  resolution_note, curator
```

Carried from `genome-db`'s curator rule: *disagreements between sources are recorded in both
places, not silently resolved.* An atlas that resolves conflicts silently is less useful than the
literature it summarizes, because the reader can no longer see the disagreement.

The most common real resolution will be `explained_by_context` — the two studies disagree because
one was aerobic and one was not — and capturing that is more valuable than declaring a winner.

## J.5 The traceability chain

Every atlas statement resolves to:

```
assertion → evidence_item → { analysis_result → processing_run → dataset → accession }
                           ∪ { extraction → span → publication }
                           ∪ { curation_event → curator → date → rationale }
```

The acceptance test for this section is mechanical: **a script walks every active assertion and
fails if any one of them cannot produce a complete chain.** It runs in CI. An assertion without a
chain is a bug of the same severity as a failing unit test.

---

# K. Knowledge graph

## K.1 Principle: derived, never authored

| | |
|---|---|
| **Why** | The interesting questions are traversals — *gene → reaction → pathway → intervention → strain → measurement* — and expressing those as ad-hoc joins across a dozen tables does not survive contact with a second query. |
| **Stores** | Nothing of its own. Nodes and edges are projections of the relational entities and assertions. |
| **In** | The relational system of record. |
| **Out** | Typed traversals, neighbourhoods, path explanations, subgraph exports. |
| **Connects** | Sits above the domain layer, below search and the UI. |
| **Automate** | Full rebuild; incremental refresh on assertion change. |
| **Human** | Nothing directly — the curation happens on the assertions the graph is built from. |

**The graph is rebuilt from the relational store and is never written to directly.** If it can be
edited independently, there are two sources of truth and they will diverge. This also makes the
graph disposable, which makes changing its shape cheap.

## K.2 Node and edge types

Nodes: `GeneGroup`, `Gene`, `Protein`, `Enzyme`, `Transporter`, `Reaction`, `Metabolite`,
`Pathway`, `PathwayConfiguration`, `Compartment`, `Organism`, `Strain`, `Modification`,
`ConditionContext`, `Experiment`, `Dataset`, `Measurement`, `Publication`, `Assertion`.

Edges carry the assertion predicates of J.2 plus structural relations (`encodes`,
`part_of_pathway`, `has_substrate`, `derived_from_strain`, `measured_in`). Every edge carries
`evidence_level`, `n_support`, `context_id` and `zone`. **An edge without an evidence level is not
storable** — which means the graph cannot be traversed in a way that loses evidence, because the
evidence is on the edge being traversed.

Node and edge types are aligned to Biolink where an equivalent exists, so the graph can be
exported into the wider bio-knowledge-graph ecosystem without a bespoke mapping written later
under time pressure.

## K.3 Traversals it must support

1. **Gene neighbourhood** — everything known about one gene group, evidence-ranked.
2. **Pathway-to-intervention** — for a product, every reaction on the route, and for each, every
   published intervention with its outcome.
3. **Bottleneck detection** — reactions where interventions cluster and where effect sizes are
   largest, weighted by independence of the studies.
4. **Strain comparison** — two strains, their differences in genotype, variants, modifications
   and measured phenotype under matched conditions.
5. **Evidence path** — for any statement, the full chain of J.5, rendered.
6. **Hypothesis scaffold** — the section-A.1 query: from a product and a host, the ranked union of
   candidate genes, regulators, bottlenecks, competing branches, tolerance mechanisms and prior
   strategies, each labelled with its level. The traversal is deterministic; only the *narration*
   of it is a language-model task, and the narration cannot introduce nodes that the traversal did
   not return.

## K.4 Comparability classes

The mechanism that makes cross-study statements defensible.

A **comparability class** is a named, versioned equivalence relation over `condition_context`,
defined by which facets must match and at what tolerance:

```
comparability_class
  id, name, product_scope
  required_match[]   e.g. aeration_class, feedstock_class, mode
  tolerance[]        e.g. temperature_c ± 2, ph ± 0.3, total_sugar_g_l within 25 %
  ignored[]          facets explicitly deemed irrelevant for this class, with a reason
  version
```

Examples: *anaerobic defined-medium glucose batch flask*; *aerobic bioreactor fed-batch*;
*hydrolysate SSF*; *alcohol shock, defined medium*.

Every cross-study comparison names the class it used. Two measurements in the same class are
directly comparable; two in different classes are shown side by side with the differing facets
named. A class is versioned because the definition will be revised, and every stored analysis
records which version it used — otherwise re-running an analysis a year later silently answers a
different question.

This is also the honest answer to *"compare experiments despite differences in strain, medium,
carbon source, temperature, pH, oxygen, stage, platform, lab, design and reference genome"*:
the differences are not dissolved, they are **declared**, and the analysis states which of them
it held constant and which it ignored.

## K.5 When a graph database becomes justified

Not yet. PostgreSQL with recursive CTEs and well-chosen indexes handles the traversals of K.3 at
the scale of section V. A dedicated graph store (Neo4j, Memgraph, or an RDF triplestore) is
justified when a *measured* query need appears that Postgres serves badly — variable-length paths
over millions of edges, or an external SPARQL consumer.

The cost of deciding this later is near zero because the graph is derived; the cost of deciding it
now is a second database to operate, keep consistent and back up from day one. `genome-db`
records the mirror-image lesson: a Postgres migration there was designed and dropped because it
had become a 646-call-site cutover — *"worth deciding before writing those call sites in a new
project."* That is exactly why section N decides the relational engine now and the graph engine
later: the one that is expensive to change is chosen up front, the one that is cheap to change is
deferred.

---

# L. AI-agent architecture

## L.1 The four rules

1. **Agents propose; they never write canonical data.** Every agent output lands in Zone I with a
   `review_state`. Promotion is a curator action or, for narrowly defined and measured classes, an
   automated rule that is itself versioned and auditable.
2. **Agents select more often than they generate.** `genome-db`'s cloning agents choose a
   `candidate_index` into a deterministic table rather than emitting a sequence, and overrides are
   applied by recomputing the deterministic baseline. Wherever the atlas can enumerate the
   possibilities, the agent picks among them and justifies the pick; free-form generation is
   reserved for cases where enumeration is impossible (prose summarization, hypothesis text).
3. **Every output is schema-validated before it is stored.** Pydantic models, JSON-schema-
   constrained decoding, and deterministic post-checks (spans resolve, ids exist, units parse,
   yields under theoretical maximum). A provider never returns an unvalidated dict as success.
4. **Failure degrades to the deterministic baseline**, loudly. An agent that fails leaves the
   pipeline's non-AI result in place with a recorded failure, never a gap and never a guess.

## L.2 The roster

Each agent gets: a narrow scope, a typed output schema, a validation gate, and a stated
promotion path. "Tier" is the model class: **heavy** for judgement-critical extraction and
review, **light** for high-volume classification.

| agent | scope | output (typed) | gate | tier |
|---|---|---|---|---|
| **Literature** | Find, deduplicate, classify and summarize publications | `PublicationRecord`, `RelevanceVerdict` with reasons | Automatic for metadata; human for inclusion near threshold | light + heavy for summaries |
| **Dataset discovery** | Find datasets in SRA/GEO/ENA/ArrayExpress matching scope; propose relevance | `DatasetCandidate` with matched criteria | Human accept before download queue | light |
| **QC** | Judge dataset and metadata quality against fixed thresholds | `QcVerdict` (accept/flag/reject + reason codes) | Thresholds are fixed in code before seeing data; the agent explains, it does not set them | light |
| **Transcriptomics** | Propose contrasts from annotated conditions; interpret results | `ContrastProposal`, `ResultInterpretation` | Human confirms every contrast before it is computed | heavy |
| **Genomics** | Summarize variant differences; propose candidate causal variants | `VariantSummary`, `CandidateVariant` (always Zone I) | Human for any causal claim | heavy |
| **Pathway** | Map genes to reactions/pathways; reconcile conflicting database assignments | `PathwayMapping` with per-source disagreement recorded | Human for the two core pathways and every conflict | heavy |
| **Network** | Build and describe co-expression and regulatory networks | `NetworkRun`, `ModuleDescription` | Automatic (Zone I); human before any assertion | light |
| **Engineering** | Extract strain constructions, modifications and intents from papers | `ModificationRecord[]` with spans | Human review of all, in phase 1; sampled thereafter | heavy |
| **Fermentation** | Extract conditions and production metrics | `ConditionContext`, `Measurement[]` with spans and units | Human review of all quantitative values in phase 1 | heavy |
| **Evidence** | Adversarially check whether an assertion's evidence supports it; find conflicts | `EvidenceAudit` (supported / overstated / unsupported / conflicted) | Runs against existing assertions; findings queue for curation | heavy |
| **Atlas curator** | Propose promotions from Zone I to assertion; propose merges and supersessions | `PromotionProposal` | **Always human.** This agent never auto-commits | heavy |
| **Research question** | Answer a user question by composing deterministic traversals and citing them | `Answer` with a citation for every clause | Answer is rejected if any clause lacks a resolvable citation | heavy |

The **Evidence agent is the most valuable and the least obvious**. Running an adversarial check
over the atlas's own assertions is the only scalable defence against the failure mode this whole
design is built to prevent: a plausible statement that nothing actually supports.

## L.3 Runtime

Three interchangeable providers behind one interface — an agent SDK path, a direct API path, and
a **mock** path — so the entire pipeline is testable without network access or spend. Tool access
is allow-listed per agent; general file and shell tools are disabled. Prompts are versioned files
on disk, and `prompt_version` is stored with every output, because an extraction is not
reproducible without the prompt that produced it.

Cost control is a design constraint, not an afterthought: cheap deterministic filters run first,
the expensive model sees only what survives, results are cached by
`(input_hash, model, prompt_version)`, and every run records its token usage against a budget.

## L.4 The MCP server

A read-only MCP server over the same API the UI uses — never a second implementation — so that
Claude Code, Claude Desktop and other agents can query the atlas directly. Two features carried
from `genome-db`'s implementation:

* Tools are annotated `READ` / `COMPUTE` / `WRITE`, and writes are off unless explicitly enabled.
* **A result budget that reports what it cut.** Large results are trimmed to a character budget,
  largest lists first, and the response says so — because a silent truncation causes the model to
  report a count that is really the budget.

## L.5 What no agent may do

Write to Zone R or Zone H. Assign an evidence level. Resolve a conflict. Create a `gene_group`
membership. Set a QC threshold. Delete anything. Promote its own proposal.

---

# M. Processing pipelines

## M.1 Orchestration

Two classes of work, two tools, on purpose:

| class | examples | tool | why |
|---|---|---|---|
| Bioinformatics batch | RNA-seq quantification, variant calling, orthology, alignment | **Nextflow** (nf-core conventions) | Container-per-process, resume, portable to a cluster unchanged, and the community modules are already validated |
| Metadata, literature, extraction, curation, derivation | everything else | **Python CLI + job table** | These are database transactions with API calls, not compute graphs. A workflow engine adds ceremony without benefit |

Both write into the same `processing_run` record, so provenance is uniform regardless of which
engine produced a result.

A single Typer CLI is the entry point for everything (`genome-db`'s `genomedb` pattern), with a
job table and Server-Sent Events for progress. Nothing that can exceed a few seconds is
synchronous in the API.

## M.2 The pipelines

| pipeline | in | out | idempotent on |
|---|---|---|---|
| `source-sync` | Public database releases | Updated reference vocabularies with version recorded | Source release version |
| `literature-discover` | Query families, citation graph | Publication candidates with relevance scores | Query + date window |
| `literature-extract` | Publication full text | Zone I extractions with spans | `(publication, prompt_version, model)` |
| `dataset-discover` | Scope criteria | Dataset candidates | Query + date window |
| `condition-annotate` | Dataset metadata + paper methods | `condition_context` proposals with evidence and confidence | `(dataset, prompt_version)` |
| `rnaseq-quantify` | Run accessions with approved conditions | Quant output, QC JSON, matrices | Run accession + index version |
| `rnaseq-contrast` | Approved contrast definitions | DE results | `(contrast, method, counts hash)` |
| `genome-ingest` | Assembly + annotation | Gene models, proteins, QC gate report | Assembly accession + annotation version |
| `ortholog-build` | Proteomes | Gene groups, ortholog links | Proteome set hash |
| `variant-annotate` | VCF | Annotated variants at gene-group level | VCF checksum + annotation version |
| `harmonize` | Zone R | Zone H (units, ids, conditions) | Zone R revision + recipe version |
| `meta-analyze` | Contrasts within a comparability class | Zone I meta-results | Contrast set + class version + method |
| `graph-build` | Relational store | Materialized graph | Assertion revision watermark |
| `index-build` | Text, entities, embeddings | Lexical + vector indexes | Content hash + model version |

Every pipeline is resumable and idempotent on the key in the last column, and writes a
per-unit marker file (`genome-db`'s `run.json` pattern) so an interrupted batch restarts where it
stopped rather than from the beginning.

## M.3 Two failure modes worth designing against now

Both are recorded in `genome-db` as things that produced *plausible* output, which is the
dangerous kind:

* **A truncated download that still parses.** Streaming a FASTQ through a pipe into a quantifier
  yields a perfectly plausible result from half a file. The fix is to check the *downloader's*
  exit status after the consumer finishes, and to verify expected read counts and checksums —
  not to trust that the consumer would have failed.
* **A silent identifier collapse.** Deduplicating transcripts by sequence can delete a gene;
  mapping ids without checking the resolved fraction can attach a matrix to the wrong genome. Both
  get an explicit floor (`--keepDuplicates`; a minimum resolved fraction below which the import is
  refused) rather than a warning.

---

# N. Storage architecture

## N.1 The recommendation, with the argument

| component | choice | why this and not the alternative |
|---|---|---|
| System of record | **PostgreSQL 17** | Multi-writer (pipelines, agents, curators concurrently), real constraint enforcement across ~60 tables, JSONB for as-reported payloads, partial and expression indexes for the per-evidence-type CHECKs of J.3, materialized views for derived levels, and `pgvector` in the same database as the metadata being filtered on. `genome-db` chose SQLite for a single-user single-organism viewer and was right; it also priced the later escape at 646 call sites. This atlas is multi-writer and cross-organism on day one. |
| Expression matrices | **Parquet + DuckDB** | 30M values is 120 MB columnar and analytically fast; the same data as relational rows is gigabytes and slower for the only access pattern that matters (slice a gene group across samples). |
| Sequences & alignments | **bgzip + faidx / CRAM on the filesystem** | Random access without loading; the standard tools expect it. |
| Documents & artifacts | **Filesystem, object-store layout** | PDFs, full text, quant output, QC reports, RO-Crates. S3/MinIO-compatible layout from the start so moving to object storage is configuration, not migration. |
| Embeddings | **pgvector in the main database** | Hybrid queries need `WHERE product = 'isobutanol' AND organism = ... ORDER BY embedding <=> query`. A separate vector database cannot filter on the metadata without a round trip and a consistency problem. |
| Lexical search | **PostgreSQL full-text first**, OpenSearch only if measured to be insufficient | One system until there is evidence for two. |
| Knowledge graph | **Materialized in Postgres**; graph DB deferred (K.5) | |
| Cache / queue | **Postgres table + `LISTEN/NOTIFY`** | A job queue for a handful of concurrent pipelines does not need Redis. |

**One database, not one per organism.** This is the deliberate departure from `genome-db`, and
its own design already points the way: `expression.sqlite` there is explicitly *not* per-assembly,
because "an experiment is not a property of an assembly — re-ingesting a genome must not destroy
months of imported measurements." Extend that reasoning to strains, products, conditions and
assertions and the per-organism boundary disappears entirely.

## N.2 Path layout

The three-way split from `genome-db`'s `env/paths.yaml`, adopted wholesale because it is the
cleanest part of that project:

```
REPO (committed, curated, small — the human-curation layer, reviewed in pull requests)
  data/strains/           strain registry, aliases, lineage, class assignments
  data/pathways/          the two curated core pathways, compartments, cofactors
  data/panels/            curated gene panels per topic (ethanol core, isobutanol core, tolerance)
  data/vocabularies/      condition facet vocabularies, assay types, unit conversions
  data/comparability/     comparability class definitions, versioned
  data/literature/        seed sets, inclusion decisions, extraction gold standard
  data/benchmarks/        the known-positive benchmark set (section S.5)

DERIVED (rebuildable, never backed up except by convenience — data_dir)
  postgres/               the database cluster
  matrices/               Parquet expression matrices
  quant/<run>/            salmon output, run.json, QC
  genomes/<assembly>/     sequence, indexes
  graph/                  materialized graph artifacts
  index/                  lexical and vector indexes
  exports/                release snapshots

SOURCE (read-only, never written to — source_root)
  downloads/              retrieved raw files, content-addressed
  fastq/                  transient; deleted after quantification
```

Rules carried over verbatim because they are correct: no path is written in source code — every
location is a key with a default, resolvable and reportable by a `config` command; every key is
also an environment variable; only the derived tier is auto-created; the source tier is never
written to.

The **repo tier is the curation interface**. A curated fact arrives as a row in a commented TSV or
YAML file, is reviewed as a diff, and is loaded into the database by a CLI command that validates
every identifier before writing. This gives human curation version control, review and blame for
free — and it is why `genome-db`'s curated files carry comments explaining *why a row is absent*,
which is information no database table holds.

## N.3 What is backed up

Only what cannot be rebuilt: the repo tier (in git), the curation events and review decisions, and
the Zone R tables. Everything else is reconstructible from those plus the pipelines. The backup
story is therefore a `pg_dump` of a defined subset plus the git repository — small enough to be
done nightly and, critically, small enough to be *restored and verified* routinely.

---

# O. Search architecture

## O.1 Four modalities, one ranking

| modality | serves | implementation |
|---|---|---|
| **Structured / faceted** | "isobutanol measurements in *S. cerevisiae*, anaerobic, defined medium, above 1 g/L" | SQL over the relational store with facet counts |
| **Lexical** | Exact identifiers, gene names, strain names, accessions | Postgres FTS with a synonym dictionary built from the alias tables |
| **Semantic** | "studies where a transporter change improved alcohol export" | pgvector over abstracts, methods paragraphs, extracted claims and gene summaries |
| **Graph** | "everything two hops from 2-ketoisovalerate that has been engineered" | Traversal from K.3 |

Hybrid ranking fuses lexical and semantic results (reciprocal-rank fusion), then re-ranks by
evidence level and recency. Evidence level participating in ranking is a deliberate scientific
choice: an L1 result should outrank a textually better-matching L5 one.

## O.2 The answer contract

Any natural-language answer the system produces obeys:

1. **Every factual clause carries a citation** that resolves to an assertion, a measurement or a
   publication. A clause that cannot be cited is removed, not softened.
2. **Evidence level is shown inline**, not buried in a footnote.
3. **Zone I content is visually and textually marked** as inference, everywhere, including in
   exports and API responses (a `zone` field, not a formatting convention).
4. **Absence is reported as absence.** "No studies in the atlas report X" is a valid and valuable
   answer, and is distinguished from "X is not the case".
5. **Conflicts are surfaced, not averaged.** If two studies disagree, the answer says so and names
   the contextual difference if one is known.

---

# P. Visualization and UI architecture

## P.1 Stack

React + TypeScript + Vite, a component library, TanStack Query/Router/Table, and a deliberately
short list of visualization libraries — one statistical charting library, one network renderer,
one pathway renderer — chosen once and enforced. `genome-db` restricts itself to ECharts and
sigma.js and is better for it; an atlas that accumulates five charting libraries becomes
unmaintainable in a year.

Server-rendered where it helps first paint; the heavy interactive views are client-side.

## P.2 Pages

| page | shows | the thing it must get right |
|---|---|---|
| **Dashboard** | Counts and coverage across organisms, strains, products, experiments, genes, pathways, publications, datasets; what changed since the last release | Coverage, not just totals — *which* conditions and products are thin is the actionable number |
| **Gene** | Function, gene group membership, expression across conditions, pathways, interactions, regulators, engineering history, variants across strains, literature, evidence summary | The engineering history table with outcomes, including null results |
| **Strain** | Genome, lineage to parents, genotype, modifications, production phenotype by condition class, tolerance profile, transcriptome, publications | The lineage DAG and the condition-class faceting of phenotype |
| **Pathway** | Reaction graph with compartments, genes, enzymes, cofactors, competing branches, regulation, interventions mapped onto reactions | Compartments drawn as compartments; cofactors on the edges |
| **Experiment** | Design, full condition context, samples, omics, production metrics, results, publication | The condition context in full, with "not recorded" visible |
| **Publication** | Metadata, extracted findings with their spans highlighted, linked datasets, genes, pathways, conditions | Extraction provenance — click a value, see the sentence |
| **Product** | Everything for one product: pathways, best measurements by class, strategies, tolerance | The class-faceted comparison, never a global leaderboard |
| **Evidence** | One assertion, its full support, its conflicts, its history | The J.5 chain rendered as a chain |
| **Compare** | Two or more strains/experiments side by side | Refuses or warns when the comparability class differs |

## P.3 Pathway diagrams are generated

Layout is computed from the reaction graph (compartments as containers, reactions as edges,
cofactors as side-nodes), not drawn by hand. Nodes carry expression overlays and intervention
badges. An SBGN-compatible or Escher-compatible export is a goal, not a dependency.

The rule from section G.3 restated as a UI rule: **if a diagram can disagree with the database,
it is decoration.** A hand-drawn pathway image is acceptable only as an explicitly-labelled
figure, never as the pathway view.

## P.4 Rendering evidence

Every number carries an evidence badge (L1–L5) and a provenance affordance that opens the chain.
Zone I content is rendered in a visually distinct style with an explicit label. "Not recorded"
and "not applicable" render differently from each other and from zero. These are not styling
preferences — they are the user-facing expression of the whole evidence architecture, and getting
them wrong discards the value of everything underneath.

---

# Q. Development phases

One developer, full-time, with AI assistance. **Scope is set to "route answers first": phases 0–3
only, then a decision checkpoint.** The infrastructure phases of the original plan — knowledge
graph, semantic search, agents, web UI, MCP server, omics reprocessing — are deferred, not
cancelled, and section Q.5 lists them with what each would cost to add later.

Every phase has acceptance criteria, and **a phase is not done until they pass.**

### Phase 0 — Foundations and the recoder (3–4 weeks)

Repository, environment, config/paths, CI. The core schema of section C, plus what the isobutanol
scope adds: `compartment` with its `encoding_genomes`, `encoding_genome` carrying the code table,
the two modification types of G.5, the
`part`, `pathway_route` and `knowledge_gap` tables, and the `mtdna_insertion` fields of
`docs/design/MITOCHONDRIAL_PROGRAM.md` §2.1.

**Reference sequences, minimal.** Because there is no UI and no omics in scope, no genome ingest
pipeline is needed — only SGD identifiers as the gene-group anchor, the S288C nuclear reference,
and **the mitochondrial genome annotated under translation table 3**. That is a few days, not the
four weeks a general genomics layer would cost.

**The codon recoder ships in this phase.** Table 1 ↔ table 3, refusing any conversion that
introduces an internal stop or an unassigned codon, reporting AT content and rare-codon profile
against mitochondrial usage. It is small, it is testable, and it is usable at the bench long
before the atlas is.

*Acceptance:* fixture loads; an assertion resolves a complete J.5 chain; Zone H rebuild is
byte-identical; **a sequence filed against `mitochondrial_matrix` carrying an unrecoded `CUN` run
is rejected**; the recoder round-trips a known mitochondrial gene and reproduces the published
recoded marker sequence for a control ⚠.

### Phase 1 — The isobutanol core (8–10 weeks)

**The phase that decides whether the project works.** Agent-drafted, fully human-reviewed:

* every published microbial isobutanol production strain, any host, as a `pathway_configuration`
  with enzyme set, compartments, cofactor strategy, deletions, conditions and outcome;
* the parts catalog (G.6), one expression record per demonstrated host × compartment;
* the curated pathway with compartments, cofactors, transport steps and explicit gaps;
* every reported bottleneck with attempted fixes and their outcomes;
* co-reported higher alcohols for every configuration.

**Phase 1b — the mitochondrial genetics corpus (3–4 weeks, overlapping).** Promoted into the
critical path because mtDNA engineering is a research goal. The bounded corpus of
`MITOCHONDRIAL_PROGRAM.md` §3: the translational activator map, transformation method records,
marker systems and what each displaces, precedents for heterologous ORFs in yeast mtDNA, and
stability data.

*Acceptance:* the landmark *E. coli* and *S. cerevisiae* builds each reproduce their paper's
titer, yield and conditions; every configuration passes the 0.411 g/g bound check or is flagged;
every localization claim carries a verification method or `none_reported`; **the activator map
covers every mtDNA locus that could host an insert, with its leader and what inserting there
displaces**; the precedents table for soluble heterologous enzymes from mtDNA is complete, however
thin it turns out to be.

### Phase 2 — The ethanol reference layer (2–3 weeks)

Short by design, and short **is** the deliverable. E1 competing-sink records, E2 ceiling
benchmarks, E3 wild-type baselines, E4 transferable mechanisms with rationales. Caps enforced in
code, not by intention.

**AMENDMENT 2026-09-20 — DUET §5.1. E5 lands in this phase, and it moves earlier within it.**

*What this replaces:* the criterion list above (E1–E4) and the acceptance test, which could pass
with no matrix-redox content at all.

*Why:* E5 — ethanol as mitochondrial redox shuttle (B.3.5) — is the primary ethanol framing and is
what the isobutanol core of phase 1 will be reaching for. Curating it after E1–E4 would mean phase
3's route ranking asks "can Pos5 supply the matrix NADPH" against an empty layer.

*Revised:* E5 is curated **first** within phase 2, not last. **`ADH3` and `POS5` records are a
phase-2 blocker**, not a nice-to-have: without them the highest-priority bottleneck hypothesis
(G.8) has no evidence to be weighed against, and phase 3.5's decision checkpoint has nothing to
decide on. The outer bound on the E5 literature is ~642 records (DATA_VOLUME §1) against a
~150-publication ethanol cap, so E5 needs its own sub-budget agreed before curation opens —
otherwise it consumes the whole cap and E1–E4 arrive empty.

*Revised acceptance:* at or under cap (≤150 publications, ≤60 measurement studies); every record
names its admission criterion; **the criterion set the loader accepts is E1–E5, and a record
admitted under E5 with no `ADH3`/`POS5`/shuttle/matrix-cofactor content fails validation**;
deleting *PDC* in the model returns its measured physiological consequences **and is rendered as
the counterfactual it is, not as the chassis**; no admitted record lacks a criterion.

**AMENDMENT 2026-09-22 — phase 2, measured. The E5 ceiling is the literature's, not the plan's,
and the quantitative anchor is an experiment.**

*What this replaces:* the 2026-09-20 amendment's "**`ADH3` and `POS5` records are a phase-2
blocker**", and the *Revised acceptance* sentence "**the criterion set the loader accepts is
E1–E5**".

*Why:* the curation pass ran and measured the pool rather than assuming it. Against B.3.5's
admitted list — `ADH3` localization and directionality, `pos5Δ` and `POS5` overexpression, and the
respiratory/diauxic-shift physiology of ethanol as a carbon source — the readable literature
supports roughly **5–8 qualitative records, not 45**. Against the narrower thing the blocker was
written to secure, a *measurement* of matrix redox, it supports **none**: four independent passes
agree that **no paper measures a matrix NAD(P)H pool or ratio in living *S. cerevisiae* under a
named condition**. The nearest compartment-targeted live-cell method in the corpus
(`10.1016/j.xpro.2020.100160`) reports glutathione redox potential, not the NAD(P)H pool. So the
blocker as written was unmeetable by reading, and **a phase cannot be gated on a paper that does
not exist.** Separately, the "E1–E5" sentence predates criterion E6, which was accepted on
2026-09-20 with a 25-publication budget and which the `screening_record` CHECK already permits;
enforcing E1–E5 would reject its records and make the phase unpassable for a second, unrelated
reason.

*Revised:* E5 is still curated **first** within phase 2. The `ADH3`/`POS5` requirement becomes what
the literature can support: **at least one qualitative `ADH3`/`POS5`/shuttle record admitted under
E5, against a realistic ceiling of about 5–8** — and the number admitted, whatever it is, is
**reported with its reason**, because an unspent share is a finding about the literature and not
slack to consume. The **quantitative** matrix-redox anchor is removed from phase 2's acceptance and
recorded instead as a `knowledge_gap` of kind `never_attempted`, naming the sensor, the backgrounds
and the conditions in enough detail to be costed and run (§2.3). Commissioning that measurement is
an owner decision at the phase 3.5 checkpoint; **it is not a phase-2 deliverable, and its absence
is not a phase-2 failure.** The E5 sub-budget of 45 stays as a ceiling and is expected to report a
large unspent share.

*Revised acceptance:* at or under cap (≤150 publications, ≤60 measurement studies); every record
names its admission criterion; **the criterion set the loader accepts is E1–E6**; **a record
admitted under E5 with no `ADH3`/`POS5`/shuttle/matrix-cofactor content fails validation**; **the
absence of a quantitative matrix-redox measurement is recorded as a `never_attempted`
`knowledge_gap` citing the passes that establish it, not left as silence and not counted as a
failure**; deleting *PDC* in the model returns its measured physiological consequences **and is
rendered as the counterfactual it is, not as the chassis**; no admitted record lacks a criterion.

### Phase 3 — Route enumeration and ranking (4–5 weeks)

The generative route model, the six gates of G.7, component-wise explainable scoring, and
strategy E carrying its real constraints (`MITOCHONDRIAL_PROGRAM.md` §4).

*Acceptance:* the enumerator re-discovers every published configuration (recall test against phase
1); routes violating **per-compartment** redox balance are excluded with the imbalance named; at
least one enumerated-but-never-built route survives inspection as scientifically defensible; every
rank is explainable term by term; strategy E routes are ranked as *reachable but costly* rather
than either dropped or flattered, and each names its locus, leader, displaced gene and recoding
requirement.

**AMENDMENT 2026-09-22 — owner direction. A route that does not balance is flagged, not excluded.**

*What this replaces:* in the phase-3 acceptance criterion above, "routes violating
**per-compartment** redox balance are **excluded** with the imbalance named"; and, in G.7's gate
table, the Stoichiometric row's effect, "Fails → excluded, with the imbalance named".

*The replacement:* "every route's **per-compartment** redox balance is computed and **flagged with
the imbalance named** — which cofactor is short by how much in which compartment — and a route that
does not balance **stays in the enumeration and in the ranking**; where the curated stoichiometry
does not determine a step's contribution the balance is reported `unknown`, never `balanced`".

*Why:* **the supply side of the comparison does not exist.** `compartment_cofactor_pool` and
`COFACTOR_POOLS` record *which* cofactors a compartment holds and never *how much*, and both are
`unverified`. Excluding on that premise would delete around 56 routes — including the
cofactor-switched ones the DUET question turns on — on a claim nobody has checked, which is exactly
the option-destroying move the atlas exists to prevent. Naming the imbalance was always the
load-bearing half of the clause; dropping the route is the half that cannot be justified until a
measured per-compartment supply figure is curated. Exclusion stays reserved for a genuine
stoichiometric impossibility and for a chassis disqualification.

*What the first run of it found, recorded because it changes what the clause means:* of 800 routes,
**0 balanced, 600 unbalanced, 200 unknown.** That is structural rather than a defect — the five
catalytic steps all consume reducing power and none regenerates it, so no route could close. The
owner's response was to add a **`cofactor_cycle` step role** so `POS5`, `ADH3` and `GPD` can exist
as parts, which is what DUET's architecture actually is (B.3.5). Until that lands, "unbalanced"
should be read as *per-compartment demand*, and the useful content is the 13 distinct named
shortfalls — `NADPH short by 2 in mitochondrial_matrix` for the published matrix build against
`NADH short by 1 in cytosol; NADPH short by 1 in mitochondrial_matrix` for the native split. A
global sum would collapse the second and lose the only thing worth knowing.

*If a measured supply figure is ever curated,* the right addition is a demand-against-supply term
**per compartment**, printed in `explain` as its own term — not a pooled shortfall magnitude, which
would add a matrix NADPH to a cytosolic NADH as though the inner membrane passed either.

### Phase 3.5 — The decision checkpoint (1 week)

Not a build phase. Produce the five answers of `MITOCHONDRIAL_PROGRAM.md` §5 and a written
recommendation: which route to build first, whether strategy C is documented as import-limited,
and whether strategy E is warranted now or held in reserve.

*Acceptance:* the recommendation is one page, every claim in it opens an evidence chain, and the
alternative it rejects is stated with the reason.

### Phase 4 — The isobutanol omics layer (4–5 weeks)

Back in scope. Measured corpus (`docs/reference/DATA_VOLUME.md` §2): the entire isobutanol SRA
holding is **120 runs / 51 GB**, of which 72 are RNA-Seq and **10 are Tn-Seq**; expect ~150–250
runs after paper-driven discovery, because SRA text search misses studies whose metadata never
says "isobutanol". Plus the six capped ethanol reference studies.

Condition annotation gates quantification (F.3) — ~47 hours of annotation for ~350 runs, and a run
whose conditions are unknown is not queued.

**Priority order**, because the corpus is thin and not all of it is equally informative:
paired producer-vs-parent yeast designs first; then the Tn-Seq fitness screens, which are
perturbation evidence (L1/L2) rather than correlation (L3) and are per-run the most informative
data in the set; then isobutanol exposure time courses; then cross-host producers; then the
ethanol six.

Processing plan (`docs/reference/DATA_VOLUME.md` §6): a `t4g.micro` in **`us-east-1`** drives a
server-side `aws s3 cp` from SRA's Open Data mirror into a `us-east-1` bucket — the bytes move
inside S3 and never traverse the instance, so it costs about three cents. **The raw `.sra`
archive is then kept permanently** under Intelligent-Tiering (~$7/year for 140 GB), because
re-quantification against per-strain references is expected and retained raw makes it free to
feed. Quantification runs on one `c7i.16xlarge` (64 vCPU) in the same region, 16 jobs × 4 threads,
~3 hours, on-demand rather than spot — streaming S3 → named pipe → salmon, with the downloader's
exit status checked *after* the quantifier finishes. FASTQ is still never materialized; ~1.4 GB of
quant output and QC comes home to the `ap-south-1` bucket.

*Acceptance:* no sample enters a contrast without an approved condition context; reprocessed
results reproduce the direction of each study's own published DE for its highlighted genes; the
reprocessed ethanol study count is exactly six; every Tn-Seq screen is represented as
perturbation evidence rather than folded in with expression; **the corpus's statistical limits are
stated in writing** — with this few independent studies, cross-study meta-analysis is
underpowered for anything but large effects, and the atlas says so rather than implying otherwise.

**Total: roughly 5.5–6.5 months** to a ranked, evidence-backed route list, an omics layer and a
build decision.

### Q.5 What is deferred, and what it would cost to add

Deferred because the architecture makes them additive — none requires reworking what phases 0–3
build. This is the payoff of keeping product scope in data rather than in code.

| deferred | cost to add later | trigger to add it |
|---|---|---|
| Proteomics / metabolomics / ¹³C-flux | ~4–6 weeks each | Flux measurement is the one that would most improve bottleneck evidence — expression is not flux |
| Lifting the ethanol cap | **~5.6 TB and 10–14 weeks** — 13,117 SRA runs, measured | Nothing foreseeable. This is the deferral the cap exists to prevent |
| Chassis genomics: industrial strains, variants | ~3–4 weeks | Moving off a laboratory background |
| Tolerance layer as a full typed system | ~2 weeks | When titers approach the toxicity ceiling |
| Knowledge graph + semantic search | ~4–5 weeks | When SQL and the CLI stop being enough |
| Web UI | ~6–8 weeks | When someone other than you needs it |
| Agents beyond curation drafting | ~4–6 weeks | When corpus maintenance outgrows manual effort |
| MCP server | ~1 week on top of an API | When you want to query the atlas from Claude |

The one deferral with a real cost is the **web UI**: without it, everything is CLI and notebook
queries. For a single full-time user that is a reasonable trade for six to eight weeks; for a
second user it is not.

---

# R. Data acquisition strategy

## R.1 Sources and what each is for

| source | provides | access | cadence |
|---|---|---|---|
| **SGD** | *S. cerevisiae* reference genome, systematic names, GO, phenotypes, alleles, literature curation | Download + API | Per release |
| **NCBI RefSeq / GenBank** | Assemblies and annotations for all organisms | E-utilities, datasets CLI | Per release |
| **SRA / ENA / DDBJ** | Raw sequencing runs and run metadata (ENA preferred for FASTQ throughput) | API, FTP | Weekly discovery |
| **GEO / ArrayExpress** | Series-level design, published matrices | E-utilities | Weekly discovery |
| **UniProt** | Proteins, functional annotation, cross-references, subcellular location | REST, proteome downloads | Per release |
| **KEGG** | Pathway maps, orthology, reactions | API — **licence review required for redistribution** | Per release |
| **MetaCyc / YeastCyc** | Curated yeast metabolism | Licensed download — **subscription required** | Per release |
| **Rhea / ChEBI** | Reaction and metabolite identity, open | Download | Per release |
| **Yeast9 (consensus GEM)** | Genome-scale model, reactions, compartments, gene associations | GitHub, open | Per release |
| **YEASTRACT+** | TF–target regulatory interactions | Web/API — **check terms** | Per release |
| **BRENDA / SABIO-RK** | Enzyme kinetics | **Licence review required** | Per release |
| **TCDB** | Transporter classification | Download | Per release |
| **PDB / AlphaFold DB** | Structures for specific enzymes | REST | On demand |
| **PubMed / Europe PMC / Crossref / Unpaywall / bioRxiv** | Literature, OA full text, licence status | REST | Daily/weekly |
| **CAZy** | Only where hydrolysis of feedstock matters (SSF/CBP) | Web | Rarely |

**Licensing is checked before ingestion, not after.** KEGG, MetaCyc, BRENDA and YEASTRACT each
have terms that constrain redistribution, and a public atlas that has mirrored them is a problem
discovered too late. The schema carries `license` and `redistributable` per source, exports honour
them, and where redistribution is not permitted the atlas stores identifiers and links rather than
content. This is an explicit phase-0 task, not a phase-7 discovery.

### R.1.1 Patent / FTO layer

**ADDED 2026-09-20 — DUET §6. New subsection; nothing replaced. The source table above lists
fifteen sources and not one of them is a patent source, which is an omission rather than a
decision.**

DUET commits to **four patent families and a freedom-to-operate opinion against the Gevo, Butamax
and DuPont estates within six months**. Two consequences for the atlas, and only two:

1. **A route's novelty is not knowable from the publication record alone.** DUET's third
   architectural claim is that the mitochondrial route sits *outside* the incumbent patent space.
   That is a claim about claim language, and the atlas cannot support or refute it with papers.
2. **"Does this route sit inside someone's claim space?" must be answerable**, at least as
   "here are the families to read", for any route the ranker proposes (G.7). A route ranked first
   on evidence and unbuildable on freedom-to-operate is a wrong answer delivered confidently.

**Minimum viable scope**, deliberately small: a `patent` source alongside publications, holding
family-level records — family id, priority date, assignee, jurisdictions, status, and the
independent claims relevant to **mitochondrial and compartment-targeted isobutanol pathways**.
Linked to `pathway_configuration` and to parts (G.6) the same way publications are, so a route
surfaces its neighbouring claims.

**Not designed here, and deliberately not.** The source (EPO OPS, Google Patents, Lens.org,
PatentsView), the ingest cadence, the claim-parsing approach and the data model are all open
questions and belong in `docs/reference/OPEN_QUESTIONS.md`. Designing a patent pipeline in this
document before anyone has looked at the licence terms of a patent API would repeat the mistake the
licensing paragraph above exists to prevent.

**Two hard boundaries, stated now so they are not negotiated later.**

* **The atlas does not produce an FTO opinion.** It holds patent *records* and links them to
  routes. An FTO opinion is a legal instrument produced by counsel, and anything the atlas emits
  that resembles one is a liability. The UI labels patent links as "claims to read", never as
  clearance.
* **Patent claims are Zone R and are never promoted.** A claim is what a document asserts, not what
  is true or enforceable; validity, scope after prosecution and jurisdictional differences are
  outside what this atlas can evaluate. No patent record may raise the evidence level of any
  scientific assertion (J.3) — a patent is evidence about the legal landscape, not about biology.

## R.2 Relevance pipeline

**The pipeline is product-tier-aware, and the tier comes from the `product` table rather than
from a hardcoded rule** (B.1) — which is what keeps the asymmetry a policy rather than a branch in
the code, and what lets a future product be promoted or demoted without a rewrite.

| | isobutanol (primary) | ethanol (reference) |
|---|---|---|
| Discovery | Broad, recall-oriented; citation-graph expansion in both directions from a seed set | Targeted queries against the four B.3 criteria only |
| Default disposition | **Include unless excluded** | **Exclude unless admitted** |
| Reviewer burden | Review the exclusions | Review the admissions |
| Stop condition | Corpus saturation — new queries return no new primary papers | The cap |

The inversion of the default disposition on that third row is the whole mechanism. For a small
literature, the cost of a false exclusion is high and the cost of a false inclusion is low, so
inclusion is the default and the exclusions get the scrutiny. For a vast literature, the costs
reverse, and so does the default. A single uniform relevance threshold across both products would
either flood the atlas with ethanol or lose isobutanol papers, and no choice of threshold avoids
both.

Discovery is generous, ingestion is selective, and the gap between them is recorded:

```
discover (broad)  →  classify against the section-4 criteria of the brief  →
score relevance + industrial relevance  →  triage: include | needs-full-text | exclude(reason)
  →  human review at the threshold and on a random audit sample
  →  queue for extraction / download
```

Each dataset is classified on the axes the brief lists — organism, strain, product, objective,
condition, carbon source, mode, aeration, temperature, pH, sampling time, genotype, modification,
production metrics, omics type, platform, design, reference genome, publication, accession,
quality, relevance — and those axes are exactly the `condition_context` facets plus dataset
metadata, so classification populates the schema rather than producing a parallel spreadsheet.

**Exclusions are stored with their reason and are re-runnable.** A policy change must be able to
ask "what did we exclude that we would now include", and that is impossible if exclusions were
never written down.

## R.3 Politeness and reliability

Rate limits and API keys per source; exponential backoff; a local content-addressed cache so a
re-run does not re-fetch; every download recorded with its URL, timestamp, checksum and the
source's stated version. `genome-db` keeps a `DOWNLOADS.md` recording where every external file
came from and why — the same, but as a table in the database, because this atlas will have
thousands of them rather than dozens.

---

# S. Quality control

## S.1 Four levels

QC that only checks data files misses everything that matters here. Four levels, each with
automated gates and a human escalation path.

**Level 1 — technical.** Reads, mapping rate, decoy rate, library type consistency, assembly
completeness (BUSCO), the protein translation QC gate, checksum verification, download
completeness. Hard thresholds, fixed in code.

**Level 2 — metadata.** Per dataset and per measurement: is the condition context complete
enough to use? `completeness_score` over the facets that matter for the product, plus required-
facet rules per analysis type. A record can be perfectly valid technically and useless
scientifically, and this level is what separates the two.

**Level 3 — semantic and physical.** The checks that need domain knowledge:

* Mass yield ≤ theoretical maximum for that product and substrate (0.511 g/g ethanol,
  0.411 g/g isobutanol from glucose). A violation is flagged and blocked from aggregation, never
  silently stored.
* Carbon balance closure where enough is reported to compute it.
* Titer plausible for its declared unit — a "g/L" isobutanol value of 400 is a unit error.
* Productivity consistent with titer and fermentation time, where both are given.
* Yield consistent with titer and substrate consumed, where both are given.
* Growth rate within physiological bounds for the organism and temperature.
* A gene said to be knocked out is not also said to be overexpressed in the same strain.

Each check has a defined action: `flag` (visible, still stored), `block_aggregation` (usable
alone, excluded from summaries), or `reject` (not stored, logged with reason).

**Level 4 — integration.** Batch-effect diagnostics, confounding detection (is the biological
factor perfectly aliased with study?), negative controls, and the benchmark of S.5.

## S.2 Thresholds are fixed before the data is seen

A rule worth stating as policy because the reference project states it as practice: QC constants
(`ACCEPT_MAPPING_RATE`, minimum resolved-identifier fraction, minimum identity and coverage for
orthology) were *"fixed before seeing data"*. A threshold chosen after looking at the results it
will filter is not a quality gate, it is a rationalization. Thresholds live in one module, are
reviewed as a diff, and changing one requires re-running what it gated.

## S.3 Never guess

Carried directly from `genome-db`'s RNA-seq rules, where guessing a condition once inverted four
timepoints in a real project:

* A field that cannot be evidenced is `unknown`, and `unknown` records are excluded from analyses
  rather than defaulted.
* An unresolvable gene name is recorded as unresolved (`UNRESOLVED:<name>`), never mapped to the
  nearest plausible match.
* `NULL` (not recorded) is never coerced to `'NA'` (not applicable) or to zero.

## S.4 Curation quality

Inter-curator agreement on a shared sample, measured and reported. Extraction precision and recall
against the phase-1 gold standard, per field type, re-measured whenever the model or prompt
changes. A random audit sample of auto-accepted records, re-checked by a human on a schedule.

## S.5 The known-positive benchmark

A set of ~50 facts that the atlas must independently recover, written down in phase 0 **before**
the pipelines exist, and stored in `data/benchmarks/`. Examples of the form:

* Deleting both *GPD1* and *GPD2* reduces glycerol and impairs anaerobic growth ⚠.
* Anaerobic conditions induce a recognizable, published set of genes relative to aerobic ⚠.
* *PDC1* deletion reduces ethanol formation ⚠.
* The valine pathway genes *ILV2*, *ILV5* and *ILV3* are annotated to the mitochondrion ⚠.
* A specified negative-control gene set shows no association with alcohol tolerance.

Each is stated as a query plus an expected outcome. Recovery rate against this set is the single
most informative number about whether the atlas works, and it is reported on the dashboard. A
pipeline that cannot recover textbook biology will not discover anything new.

---

# T. Reproducibility and versioning

## T.1 Every computed result carries its recipe

`processing_run` records pipeline name and version, container image **digest** (not tag), all
tool versions, a hash of the full parameter set, content hashes of every input, the random seed,
start/end time, and the exit status. A result that cannot name its run is not storable.

## T.2 Content addressing

Every external file is stored under a content hash with its source URL, retrieval timestamp and
the source's declared version. "The same accession" is not the same file if the repository
updated it, and content addressing is what makes that detectable rather than mysterious.

## T.3 Rebuild as a test

Zone H is regenerable by definition, so regeneration is a test, run in CI on the fixture and
periodically on the real database: drop Zone H, rebuild, diff. A non-empty diff is either
non-determinism or an undeclared input — both bugs. This is the strongest guarantee in the whole
design and it is free once the zones are separated.

## T.4 Versioning strategy

Five things version independently, and conflating them is a common failure:

| what | scheme | rule |
|---|---|---|
| **Database schema** | Integer, with migrations | A `meta.schema_version` row; the application refuses to open a newer or an un-migrated database rather than migrating implicitly inside a request. |
| **Pipelines** | SemVer per pipeline | A patch bump may not change outputs; a minor bump may add fields; a major bump requires reprocessing or explicit coexistence of results. |
| **Vocabularies and comparability classes** | Version integer per definition | Every stored analysis records the version it used. |
| **Atlas releases** | `vYYYY.N` dated snapshots | Immutable, exportable, citable. A published figure cites a release. |
| **Assertions** | Append-only revisions | Supersession, never mutation; `status` carries `active`/`superseded`/`disputed`/`retracted`. |

Public identifiers never change meaning. If an entity turns out to be two entities, the old id is
retired with a pointer to both; it is never silently re-pointed.

## T.5 Export

A release export as RO-Crate (or an equivalent structured bundle): the data, the schema, the
provenance graph, the pipeline versions and the licence terms, such that a third party can
reproduce an analysis or cite a specific state of the atlas. Zone I content exports separately
and is labelled as inference in the export itself, not only in the documentation.

---

# U. Future expansion

## U.1 Adding a product

The extensibility test of Q phase 10. Adding *n*-butanol should require:

1. A `product` row with its ChEBI id, formula and theoretical yields per substrate.
2. Pathway, reaction, enzyme and metabolite rows — largely already present, since the butanol
   routes share central carbon metabolism and, for the ketoacid routes, the same Ehrlich
   chemistry.
3. Assay types and unit conversions if the product needs any the atlas lacks.
4. A comparability class if its fermentation practice differs.
5. Literature query families.

**No schema migration, no new tables, no code branch on product identity.** Any `if product ==
'ethanol'` in the codebase is a defect; product-specific behaviour lives in data (theoretical
yields, default assays, required facets), which is why those are tables and not constants.

## U.2 Adding an organism

A taxonomy row, a genome ingest, an orthology run to attach its genes to gene groups, and a
decision about which gene-group scope applies. The one genuinely hard part is gene-group
membership for a distant organism, which is why cross-species links are a separate, weaker,
evidenced relation (C.3) rather than a merge.

## U.3 Adding an omics type

Proteomics and metabolomics are the obvious next layers, and the schema accommodates them because
`dataset`, `sample`, `processing_run` and `analysis_result` are omics-agnostic. What each needs is
its own quantification pipeline and its own identifier mapping (protein groups; metabolite
identity, which is harder than gene identity and should not be underestimated). Fluxomics
(¹³C-MFA) is the highest-value addition for this atlas specifically, because it measures the thing
pathway engineering is actually about.

## U.4 What would force a redesign

Stated honestly, since the brief asks for an architecture that does not need one:

* Moving from gene-level to isoform-level or allele-specific expression.
* Making the atlas multi-tenant with per-user private data.
* Community curation at a scale that needs full editorial workflow, moderation and rollback.
* Single-cell or spatial data.

None are in scope, and none are precluded — but each would be a substantial addition rather than a
row.

---

# V. Computational requirements and data volume

## V.1 Why this is smaller than it looks

> **Scope note.** Everything in this section is sized for the **full atlas including
> transcriptomic reprocessing**. Under the settled route-first scope (phases 0–3, no omics), the
> real figures are roughly **100× smaller** — under 4 GB on disk, no meaningful compute, and a
> laptop rather than a workstation. See **`docs/reference/DATA_VOLUME.md`**, which uses measured
> PubMed corpus counts rather than estimates. This section stays as written because it is the
> sizing that applies if the omics layer is ever restored.

Yeast is a 12.1 Mb genome with ~6,000 genes. The atlas's scale problem is *breadth of studies and
curation effort*, not compute. The numbers below are estimates for planning ⚠ and should be
re-measured after phase 3's first ten datasets.

## V.2 Data volume at steady state

| layer | retained | notes |
|---|---|---|
| PostgreSQL (entities, assertions, metadata, literature, embeddings) | **20–60 GB** | 200k publication records, ~10⁵–10⁶ assertions, ~10⁵ measurements |
| Expression matrices (Parquet) | **0.5–2 GB** | 6,000 gene groups × 5,000 samples × a few normalizations |
| Retained quantification output + QC | **10–20 GB** | ~2–4 MB per run |
| Genomes, annotations, indexes | **30–80 GB** | Incl. ~1,000 *S. cerevisiae* assemblies at ~12 MB each |
| Variant data (published VCFs) | **5–20 GB** | |
| Literature full text (OA only) + PDFs | **10–30 GB** | |
| Vector index | **2–5 GB** | ~500k chunks × 1024 dims |
| Downloads cache (content-addressed) | **50–200 GB** | Prunable |
| **Steady-state total** | **≈ 150–400 GB** | Comfortably one NVMe drive |
| FASTQ, transient | **3–6 TB transferred, ≤ 200 GB resident** | Deleted immediately after quantification |

The transient/resident distinction is the whole storage story: naively retaining FASTQ turns a
400 GB project into a 6 TB one for no analytical gain, since quantification is deterministic and
re-runnable.

## V.3 Compute

| task | cost | note |
|---|---|---|
| Salmon index (decoy-aware, yeast) | minutes, ~8–16 GB RAM | Per reference |
| Salmon quant per sample | ~1–3 min on 8 threads, ~4 GB RAM | |
| 5,000 samples end to end | **100–250 core-hours** ≈ 1–2 days on 16 cores | Compute is *not* the bottleneck |
| Downloading 5,000 runs | **5–6 TB**; days to weeks | **This is the bottleneck.** 100 Mbit/s sustained ≈ 5 days continuous; plan for retries and source throttling |
| DESeq2 per contrast | seconds | |
| WGCNA / correlation, 6,000 genes | 6,000² float64 = 288 MB per matrix | Comfortable — the reference project's memory pressure came from a 7,951-gene fungus and multiple live matrices; yeast is smaller |
| Meta-analysis across contrasts | minutes | |
| OrthoFinder over ~20 proteomes | hours | |
| Graph materialization | minutes | |
| Embedding ~500k chunks | API cost, not compute | |

## V.4 The real budget line: extraction

LLM extraction cost dominates, and controlling it is a design decision, not an optimization:

| approach | scale | relative cost |
|---|---|---|
| Naive: every candidate paper, full text | ~20k papers × ~30k tokens = **600M input tokens** | prohibitive |
| Staged: filter first, then extract methods + results sections only from included papers | ~3k papers × ~15k tokens = **45M input tokens** | ~13× cheaper |

Hence the staged filter of R.2 and the cheap-classifier-before-expensive-extractor rule of L.3.
Caching by `(input_hash, model, prompt_version)` means a prompt revision re-runs only what changed.

## V.5 Recommended hardware

**One workstation is sufficient**, which is a significant and slightly surprising conclusion worth
stating plainly: 16–32 cores, 128 GB RAM, 2 TB NVMe for the database and working set, 8–20 TB bulk
for the download cache, no GPU (embeddings and generation via API). Fast, stable internet matters
more than cores.

A caveat inherited from the reference project's measurements: put the database and working set on
a **native Linux filesystem**, not a mounted Windows drive — random reads across the WSL 9P bridge
were measured there as several times slower.

Cloud burst is optional and only worth it for the download-and-quantify phase, where running close
to the data (SRA is in cloud object storage) converts days of transfer into hours of compute.

---

# W. Risks and mitigation

Ordered by expected damage. "Early warning" is what to watch for to know the risk is materializing
before it is expensive.

| # | risk | why it bites | mitigation | early warning |
|---|---|---|---|---|
| 1 | **Fermentation metadata is not in the repositories** | Aeration, mode, actual sugar, pH control, titer at sampling live in the paper's methods, often in prose. Without them, samples cannot be compared and the atlas is a pile | Condition annotation gates quantification (F.3); `completeness_score` as a first-class metric; paper-derived conditions with evidence and confidence | In the first 20 studies, the fraction where aeration and mode can be established. If it is below ~60%, the transcriptomic plan needs rescoping |
| 2 | **Curation throughput, not compute, is the rate limit** | Every quality mechanism here routes through a human. One person can curate a few papers an hour at this depth | Phase 1 measures the real rate before phases 3–5 are sized; agents draft and humans verify rather than humans authoring; narrow gold standards make sampling defensible | Phase 1 running >50% over its estimate |
| 3 | **Gene identity errors across strains and species** | A wrong ortholog silently corrupts every downstream aggregation, and the errors cluster exactly in the expanded families that matter here (*ADH*, *PDC*, *HXT*) | Anchor on S288C systematic names; cross-species links kept separate and weaker; mandatory human review of the E.4 families; membership evidence retained per member | Disagreement between orthology methods on the *ADH*/*PDC*/*HXT* families |
| 4 | **LLM extraction produces plausible wrong numbers** | The most damaging failure, because the output looks right | Mandatory verbatim spans with offset verification; deterministic validators; full human review in phase 1; measured precision/recall per field; Zone I quarantine | Span verification failure rate; disagreement between two models on the same table |
| 5 | **Unit and basis errors in measurements** | g/L vs % v/v; yield per consumed vs supplied sugar; % of theoretical vs g/g. Silent, and it inverts conclusions | `value_as_reported` never overwritten; `basis` mandatory for yield; theoretical-maximum bound check; unit declared, never inferred | Bound-check violations clustering in one journal or extraction template |
| 6 | **Publication bias and irreproducible published values** | Negative results are rarely published; some early isobutanol claims are disputed on carbon-balance grounds ⚠ | Null and negative results stored with equal status; carbon-balance flags; conflicts first-class; disputed values shown as disputed, not excluded | Reported yields clustering suspiciously near or above theoretical maxima |
| 7 | **Correlation read as causation** | Expression correlates with everything; industrial strains differ from lab strains at tens of thousands of positions ⚠ | Evidence types kept distinct in the schema, not in the prose; L3 cannot be reached by correlation alone; the UI shows the level next to the claim | Any UI surface where a correlative association renders identically to a perturbation result |
| 8 | **Cross-study confounding** | Lab, batch and biology are often perfectly aliased; correcting for batch can remove the signal | Contrast-level meta-analysis rather than merged matrices (F.6); confounding detection in level-4 QC; corrected matrices are Zone I | A "conserved response" set that tracks study rather than condition |
| 9 | **Scope explosion** | Every section of this plan has an obvious next step; the atlas could absorb all of microbial biotechnology | The exclusions of A.2 are binding; phase 10 tests extensibility instead of adding scope; new organisms and products are data, so saying yes stays cheap and saying no stays possible | New entity types being proposed after phase 2 |
| 10 | **Licensing** | KEGG, MetaCyc, BRENDA and publisher full text each constrain redistribution; discovering this after ingestion is expensive | Licence review as a phase-0 task; `license`/`redistributable` per source; exports honour it; identifiers-and-links where redistribution is not permitted | Any ingestion whose licence field is unset |
| 11 | **Schema churn after data is loaded** | Migrating curated data is far more expensive than migrating code | Phase 1 deliberately loads real data by hand before pipelines exist, specifically to find schema gaps while they are cheap | A schema change proposed in phase 3+ that touches `measurement` or `condition_context` |
| 12 | **Tolerance assay heterogeneity** | Six incompatible definitions of "ethanol tolerance" aggregated into one number would be worse than useless | `assay_type` mandatory; no aggregation across assay types without an explicit, visible statement | Any summary that reports a single tolerance value per strain |
| 13 | **The atlas launders uncertainty into fact** | A structured database confers unearned authority; a hedged sentence in a paper becomes a row | Evidence level on every claim, everywhere, including exports and API; Zone I labelled in the data, not the CSS; the Evidence agent auditing continuously | An export or API response where `zone` and `level` are absent |
| 14 | **Single-maintainer continuity** | One person holds the model of a large system | Conventions documented before code (this plan, and `CONVENTIONS.md`); fixture-based tests; curated data in git with reviewable diffs; agent briefs self-contained | Documentation lagging more than one phase behind the code |
| 15 | **Extraction cost overrun** | 600M tokens of naive extraction is a real budget | Staged filtering (V.4); caching by prompt version; cheap classifier before expensive extractor; per-run token accounting against a budget | Token spend per accepted record trending up |

---

# X. Final recommended architecture

## X.1 One page

```
              ┌──────────────────────────────────────────────────────────┐
  Researcher →│  Web UI (React) · REST API (FastAPI) · MCP server · CLI  │
   AI agent  →└──────────────────────────────────────────────────────────┘
                                      │
              ┌───────────────────────┴──────────────────────────────────┐
              │  SEARCH: structured · lexical (PG FTS) · semantic        │
              │  (pgvector) · graph traversal → hybrid, always cited     │
              └───────────────────────┬──────────────────────────────────┘
                                      │
              ┌───────────────────────┴──────────────────────────────────┐
              │  KNOWLEDGE: assertions · evidence (levels as views) ·    │
              │  conflicts · curation queue · materialized graph         │
              └───────────────────────┬──────────────────────────────────┘
                                      │
   ┌──────────┬──────────┬────────────┴────────┬────────────┬────────────┐
   │ Genomic  │ Transcr. │ Metabolic           │ Engineering│ Phenotype  │  DOMAIN
   │          │          │                     │            │ Literature │
   └──────────┴──────────┴─────────────────────┴────────────┴────────────┘
                                      │
              ┌───────────────────────┴──────────────────────────────────┐
              │  ZONE R (reported, immutable) · ZONE H (harmonized,      │
              │  rebuildable) · ZONE I (inferred, quarantined)           │
              └───────────────────────┬──────────────────────────────────┘
                                      │
   PostgreSQL 17 (system of record + pgvector)  ·  Parquet/DuckDB (matrices)
   Filesystem/object store (sequences, documents, artifacts)  ·  git (curation)
                                      │
   Nextflow (bioinformatics)  ·  Python CLI + job table (everything else)
                                      │
   SGD · NCBI/SRA/ENA · UniProt · Rhea/ChEBI · Yeast9 · YEASTRACT · KEGG/MetaCyc*
   Europe PMC · Crossref · BRENDA*          (* licence-constrained)
```

## X.2 The decisions that matter

| # | decision | one-line reason |
|---|---|---|
| 1 | **The assertion is the unit of knowledge**; domain tables are the vocabulary it speaks about | Traceability and evidence separation become structural rather than conventional |
| 2 | **Three zones: Reported / Harmonized / Inferred**, physically separated | It is the only way "do not mix evidence with inference" survives contact with a deadline |
| 3 | **One system of record, engine kept swappable via a query-builder layer** — SQLite under the route-first scope, PostgreSQL when a second user, a UI or semantic search appears | The Postgres case rested on concurrency, pgvector, JSONB and partial indexes; the scope cut removed four of the five premises. The reference project's 646-call-site migration cost came from raw SQL everywhere, not from SQLite — so the abstraction layer, not the engine, is the decision that matters. See `docs/reference/OPEN_QUESTIONS.md` Q2 |
| 4 | **`gene_group` is the join key**; raw gene ids never cross an assembly boundary | Cross-study integration is otherwise wrong rather than merely hard |
| 5 | **`condition_context` is a first-class, hashed, structured entity** with `as_reported` shadows | Comparability lives entirely here |
| 6 | **Cross-study integration combines contrasts, not expression values** | Most of this literature is small single-condition studies; merging matrices would discard them and confound the rest |
| 7 | **Evidence level is derived by a stated rule and stored as a view** | A stored level becomes a lie the first time new evidence lands |
| 8 | **Per-evidence-type constraints make a mislabelled row unstorable** | An AI inference is structurally prevented from occupying a measurement's shape |
| 9 | **Agents propose into Zone I only**, select rather than generate, and degrade to a deterministic baseline | Automation without a curation gate would destroy the atlas's only real asset |
| 10 | **Expression matrices in Parquet, metadata in Postgres** | Right tool per access pattern, 10× smaller, faster for the only query that matters |
| 11 | **FASTQ is transient; the `.sra` archive is permanent** | FASTQ is streamed into the quantifier and never written to disk. The compact `.sra` originals are retained in S3 indefinitely (~140 GB, ~$7/year on Intelligent-Tiering) so re-quantification costs no retrieval. Permanent compact form, transient expanded form |
| 12 | **Product-specific behaviour lives in data, never in code** | The extension path to butanol and organic acids is only real if nothing branches on product identity |
| 13 | **Curated facts live in git as reviewed TSV/YAML**, loaded by a validating CLI | Version control, review and blame for human curation, free |
| 14 | **Theoretical-yield bounds as an automated QC gate** | The cheapest defence against unit errors and disputed claims |
| 15 | **The graph is materialized from the relational store, never authored** | Keeps one source of truth and makes the graph engine a deferrable decision |

## X.3 What to do first

In order, and nothing from phase 2 onward until phase 1 has been tried on real papers:

1. **Decide the open questions** in `docs/reference/OPEN_QUESTIONS.md` that block phase 0 — chiefly
   the deployment target (single-user workstation versus shared/multi-user), which determines
   several things that are expensive to change later.
2. **Run the licence review** on KEGG, MetaCyc, BRENDA and YEASTRACT. It is a half-day and it
   constrains the data model.
3. **Write the fixture and the benchmark set** (S.5) before any pipeline exists, so the target is
   fixed before the tools that aim at it.
4. **Build phase 0's schema and load twenty real papers by hand**, including at least five
   isobutanol papers with complete fermentation data and two papers that disagree with each other.
   This is the cheapest possible test of every decision in this document, and it will falsify some
   of them.

---

# Appendix 1 — Coverage of the requested planning items

| # | requested item | where |
|---|---|---|
| 1 | Overall project architecture | A, D, X |
| 2 | Scientific scope | B |
| 3 | Organism strategy | B.3 |
| 4 | Product strategy | B.1, B.2, U.1 |
| 5 | Data-source strategy | R |
| 6 | Genomic pipeline | E |
| 7 | Transcriptomic pipeline | F |
| 8 | Metabolic pathway pipeline | G |
| 9 | Literature-mining pipeline | H |
| 10 | Experimental-data extraction pipeline | H.5, I |
| 11 | Cross-study integration strategy | F.6, K.4 |
| 12 | Evidence framework | J |
| 13 | Database architecture | D, N.1 |
| 14 | Knowledge graph architecture | K |
| 15 | AI-agent architecture | L |
| 16 | Storage architecture | N |
| 17 | Processing architecture | M |
| 18 | Search architecture | O |
| 19 | Visualization architecture | P.3, P.4 |
| 20 | UI architecture | P |
| 21 | Quality-control framework | S |
| 22 | Reproducibility framework | T.1–T.3, T.5 |
| 23 | Versioning strategy | T.4 |
| 24 | Future-product extension strategy | U |
| 25 | Proposed development phases | Q |
| 26 | Estimated computational requirements | V.3, V.5 |
| 27 | Expected data volume | V.2 |
| 28 | Automation opportunities | Appendix 2 |
| 29 | Human-curation requirements | Appendix 2 |
| 30 | Major technical/scientific risks | W |

# Appendix 2 — Automation and human curation, consolidated

| activity | automated | human required | why the human |
|---|---|---|---|
| Publication discovery, dedup, metadata | fully | inclusion decisions near the threshold | The threshold is a scientific judgement |
| Full-text retrieval, licence detection | fully | licence policy | Legal exposure |
| Relevance classification | fully | audit sample | Drift detection |
| Condition extraction from methods | drafted | **every record in phase 1**, sampled later | This is where the atlas's comparability comes from |
| Measurement extraction | drafted | **every quantitative value in phase 1**, then by template | A wrong number is worse than a missing one |
| Unit conversion, derived metrics | fully | basis inference | g/g-consumed vs supplied cannot be guessed |
| Dataset discovery, download, QC | fully | rejection overrides | |
| RNA-seq quantification | fully | none | Deterministic |
| Contrast definition | proposed | **always confirmed** | A wrong contrast produces confident nonsense |
| DE, enrichment, co-expression | fully | interpretation | |
| Meta-analysis | fully | promotion to an assertion | L3 is a scientific claim |
| Genome ingest, QC gate, orthology | fully | gene-family group assignments | Automated orthology fails exactly on *ADH*/*PDC*/*HXT* |
| Variant annotation | fully | **any causal claim** | Tens of thousands of variants, almost none causal |
| Pathway import | fully | the two core pathways; every inter-source conflict | Compartment and cofactor detail is what public sources get wrong |
| Engineering extraction | drafted | **all in phase 1**; isolated-effect attribution always | Multi-modification strains cannot be attributed automatically |
| Evidence levelling | fully (derived) | overrides, with reasons | |
| Conflict detection | fully | adjudication and context explanation | |
| Assertion promotion | never | **always** | The single most important gate in the system |
| Graph, indexes, exports | fully | none | Derived |
