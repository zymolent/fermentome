# DUET, made robust — a data-backed redesign

**2026-09-22.** A companion to `DUET_TARGET.md`, not a replacement: the destination is unchanged,
and the compartment decision at its centre has since been validated. What changes is the
*architecture around it* — four structural edits that remove single points of failure, and a
staged programme in which **every risky assumption is falsified cheaply before it becomes
expensive to be wrong about.**

Every number cited is a row in this atlas or is marked ⚠ as my inference. Expression values are
median TPM in the SRP342112 parent background (cassette-aware index, quarantined runs excluded).

---

## 0. What is already settled, and therefore not up for redesign

| settled | evidence |
|---|---|
| **The pathway belongs in the matrix** | mitochondrial 170 mg/L vs cytosolic 46 / 31 (both ≤ parent); DHIV accumulates 8.6–16× in cytosol and is depleted in matrix; *fra2Δ* rescues cytosol 2.4× and does nothing in matrix (`10.1016/j.synbio.2022.02.007`). Best yeast titer in the atlas, **1,245 mg/L**, is also mitochondrial (`10.1016/j.ymben.2017.10.001`) |
| **The entry point is well chosen** | a stranded C5 stream has zero opportunity cost; the C6 train is untouched, so plant revenue is not at risk |
| **Transcription is not the limitation** | all four constructs express 13–17 log2 over parent in both topologies; the paper's own conclusion is that neither mRNA nor protein explained the titer differences |

The redesign holds all three fixed and rebuilds what sits around them.

---

## 1. Four structural changes

### 1.1 Ethanol is a **carrier pool**, not a co-product — so stop paying for it with Pdc flux

The ethanol–acetaldehyde shuttle is **catalytic in ethanol**: cytosolic acetaldehyde + NADH →
ethanol (Adh1, **2,266 TPM** — abundant), ethanol diffuses in, Adh3 oxidises it back to
acetaldehyde (**236 TPM**), acetaldehyde diffuses out. Net effect is transfer of reducing
equivalents; **ethanol is not consumed** ⚠.

DUET treats ethanol co-production as a stoichiometric design requirement, and pays for it by
retaining *PDC* — against **PDC1 at 8,737 TPM vs ILV2 at 65**, a 134-fold disadvantage at the
shared pyruvate node, in a system where ethanol already reaches >90% of theoretical while
isobutanol stays below 0.2%.

**The change:** supply the carrier as a **small ethanol feed from the adjacent C6 train** (the
plant makes 120 g/L next door) rather than by making it in the C5 vessel. What is needed is a
standing pool plus make-up for losses (Ald6 oxidation to acetate, and stripping), not stoichiometric
co-production ⚠.

Three things fall out at once:

* the argument for retaining full Pdc flux disappears, so the sink can be attenuated (§1.3);
* **the conflict between claim 1 and the recovery concept dissolves** — less ethanol made in the
  C5 vessel means the stripped condensate is less ethanol-diluted, and ethanol is the cosolvent
  that suppresses the isobutanol/water phase split the decanter depends on;
* carrier supply becomes an **operating parameter you can tune in a run**, not a genetic
  commitment you can only change by rebuilding the strain. That is the robustness gain.

### 1.2 Give the matrix **two independent NADPH sources**, not one

DUET names Pos5 as the keystone and correctly identifies it as a single point of failure. The
measurement is worse than the note assumes — **POS5 = 17.0 TPM**, against ILV5 at 566 and Pdc1 at
8,737 — and Pos5 additionally costs **1 ATP per NADPH**, on a pentose stream where ATP per carbon
is already low.

But Pos5 is not the only matrix NADPH source. **IDP1** — mitochondrial NADP-isocitrate
dehydrogenase — reads **133.8 TPM, eight-fold above POS5**, and draws on TCA isocitrate rather
than on shuttle-delivered NADH.

| matrix NADPH route | substrate | TPM (parent) | fails if… |
|---|---|--:|---|
| **Pos5** | matrix NADH (+ATP) | 17.0 | the shuttle runs the wrong way, or ATP is short |
| **Idp1** | isocitrate | 133.8 | TCA flux is repressed |

**The change:** overexpress **both**. Their failure modes are independent — one is redox-driven,
the other carbon-driven — so the architecture no longer has a single keystone. This buys the
redundancy DUET §7 sought from an NADH-preferring KARI **without** that option's liability (§2).

*The corpus already contains a paper titled "Two sources of mitochondrial NADPH in the yeast
S. cerevisiae", currently excluded by a screening rubric. Read it before finalising the ratio.*

### 1.3 Attenuate the sink **asymmetrically by vessel**, rather than retaining or deleting it

DUET's switching is one-sided: glucose-repressed promoters turn the isobutanol pathway **on** when
glucose is gone. Nothing turns *PDC* **down**, and Pdc1 is as active on xylose-derived pyruvate as
on glucose-derived pyruvate.

**The change:** put **PDC1** under a promoter that is high on glucose and low on xylose, so the
sink is strong in the C6 train (where ethanol *is* the product) and weak in the C5 vessel (where it
is the competitor). Leave **PDC5 (88 TPM)** and **PDC6 (35 TPM)** intact as a viability backstop —
they are ~100× below Pdc1 and will not compete meaningfully, but they avoid the C2-auxotrophy
phenotype that full *pdc* deletion causes, which is the cost criterion E1 exists to quantify.

This makes the partition act on **flux**, not merely on feedstock — which is the objection §5a of
the review raised and the note does not currently answer.

**State a target ratio.** The design question DUET leaves open is *what* ethanol:isobutanol ratio
the shuttle needs. Making it an explicit, measured design parameter is what converts "retain Pdc"
from an assumption into an engineering specification.

### 1.4 Relocate the Fe-S intervention to **POS5**, and make petite frequency a release criterion

Pos5-derived NADPH feeds the mitochondrial ISC machinery through ferredoxin reductase **Arh1
(23.2 TPM)** and ferredoxin **Yah1 (96.1 TPM)**, and the corpus holds a paper titled
*"Mitochondrial NADH kinase, Pos5p, is required for efficient iron-sulfur cluster biogenesis"* —
excluded, unread. So Pos5 supplies both **Ilv5's cofactor** and the machinery that matures
**Ilv3's 2Fe–2S cluster**.

**The change:** `NFS1`/`ISU1`/`YFH1` leave phase 1. The dual-purpose Fe-S intervention DUET wanted
exists — it is the same edit as the redox intervention, at *POS5*, one gene earlier than the note
looks.

**And a standing criterion:** measure **petite frequency on every matrix-targeted construct**,
before titer. Two independent reasons, both in the corpus: the fifth strain of the 2022 study —
*mitochondrial plus NADH-KARI, DUET's own compartment choice combined with DUET's own cofactor
de-risking* — was **dropped for a 166-fold elevated petite frequency**; and the corpus holds
*"Effects of a mitochondrial mutator mutation in yeast POS5 NADH kinase on mitochondrial nucleotide
pools"*, which puts POS5 perturbation itself on the mtDNA-stability axis. For a design that is
mitochondrial by construction and whose escalation path is mtDNA engineering, petite rate is a
primary readout, not a footnote.

---

## 2. Two holes in the gene set that must be closed before any build

**2.1 No xylose-to-xylulose step.** `XKS1 TAL1 TKL1 RKI1 RPE1` all sit at or below xylulose. There
is no *XYL1*/*XYL2* and no *xylA*. Note also that the background carries **GRE3 at 407 TPM** — the
endogenous NADPH-dependent aldose reductase, which reduces xylose to **xylitol** unproductively.
Without a committed xylose route, added xylose is a xylitol sink, not a substrate.

Which route the plant strain has also changes the redox argument:

| route | cofactors | consequence for DUET |
|---|---|---|
| **XR/XDH** | −NADPH, +NADH per xylose | **Synergy.** The cytosolic NADH surplus is exactly the shuttle's substrate and gives it a driving force in the right direction; the NADH that would be excreted as xylitol becomes precursor. Supplies ~60% of the matrix reducing power the pathway needs ⚠. **But** total NADPH demand rises to ~2.2 per isobutanol ⚠, and xylose enters below the oxidative PPP, so cytosolic NADPH is poorly supplied |
| **XI** | none | Redox-neutral. No xylitol problem, no extra NADPH demand — and no free driving force for the shuttle |

**If XR/XDH: do not delete ALD6.** Ald6 (**449 TPM**) oxidises the shuttle's returning acetaldehyde
with NADP⁺, regenerating the cytosolic NADPH that XR consumes. It sits in DUET's
competing/by-product deletion set by inheritance from glucose-based designs, where deleting it is
standard. On xylose with XR it may be the supply line. Decide it deliberately; the cost is acetate,
which Acs2 (**754 TPM**) recycles at ATP expense.

**2.2 No product-side ADH — and the diagram hides a futile cycle.** §7 of the note routes matrix
NADH both to Pos5 *and* to "the final ADH step", with Adh3 generating that NADH from ethanol. **If
the same enzyme does both, it oxidises ethanol and reduces isobutanal in one compartment and the
cycle is futile** ⚠. The shuttle ADH and the product ADH must be *different* enzymes with different
substrate preferences — which is what the published mitochondrial builds do (a CoxIV-targeted
bacterial AdhA for the product step, distinct from native Adh3). The gene list names `ADH3` and
`ADH2` and no product-side ADH. Add one, and target it.

Also worth noting: **ARO10 reads 1.8 TPM** — the named decarboxylase is effectively silent in a
glucose-grown background and is nitrogen-regulated. It must be replaced or driven, not merely
listed. And **MPC1/MPC3 (62/39 TPM)** — the mitochondrial pyruvate carrier — is the unexamined
gate on a matrix pathway: every carbon must cross it. The atlas holds 1,280
`transport_carrier_unknown` gaps and this is the one that matters most here.

---

## 3. The programme: five stages, each gated on a falsification

The robustness is in the ordering. Each stage tests the assumption that would invalidate the next
one, using the cheapest instrument that can do it, and each has a defined fallback.

### Stage 0 — characterise, no genetics (2–4 weeks)

| action | why | gate |
|---|---|---|
| **Flow cytometry for ploidy** | `chassis_profile` records ploidy **unknown, candidates 1–4 open**; verification burden across ~30 loci scales 1×–4× | if >2n, cut the phase-1 edit list to the §1 core or work in a sporulated derivative |
| **Establish the xylose route** (genome + growth on xylose) | §2.1; the partition premise depends on it | none → the route must be added before anything else, and the programme is 12 weeks longer |
| **Baseline petite frequency** | the reference for §1.4's release criterion | — |
| **Isobutanol tolerance curve of the real strain** | atlas holds LC50 ≈ 1.5% v/v (~12 g/L) for a lab strain only | sets the titer at which §Stage 4 turns on |
| **★ Ethanol supplementation of a mitochondrial producer** | **the decisive cheap test** | see below |

**The ethanol-supplementation test is the single highest-value experiment in this programme.** Feed
exogenous ethanol to an existing mitochondrial isobutanol build and measure isobutanol. It requires
**no strain construction**. If DUET's central claim is right — ethanol carries reducing power into
the matrix where the pathway consumes it — supplementation should raise titer. If it does not, the
redox architecture is wrong, and it has cost a week rather than a year.

*Why this matters so much:* the quantity the whole claim rests on — matrix NAD(P)H poise — **has
never been measured by anyone**, in any paper in this corpus, under any named condition. The atlas
records it as a `never_attempted` knowledge gap. Under fermentative, glucose-repressed conditions
the matrix is NADH-rich, which thermodynamically *disfavours* ethanol oxidation — the shuttle may
run backwards. The supplementation test answers functionally what the measurement would answer
rigorously, at ~1% of the cost.

**Fallback if it fails:** drop claim 1, keep the compartment. Matrix NADPH then comes from **Idp1**
(§1.2), driven by TCA isocitrate rather than by the shuttle. The design survives, because §1.2 made
it two-sourced. *This is what the redundancy is for.*

### Stage 1 — minimal matrix build + NADPH redundancy (8–12 weeks)

Note what the mitochondrial choice buys: **Ilv2, Ilv5 and Ilv3 are already in the matrix.** They
need overexpression, not relocation. Only the Ehrlich half must be targeted there.

* matrix-targeted **KDC** (not Aro10 — see §2.2) and a **distinct matrix product-ADH**
* overexpress native **ILV2 (+ILV6), ILV5, ILV3**
* overexpress **POS5** and **IDP1** (§1.2)

| gate | threshold | fallback if missed |
|---|---|---|
| titer beats the parent, and beats the atlas's best mitochondrial build | > **1,245 mg/L** | diagnose at the step level before adding edits |
| **petite frequency** | < 2× Stage-0 baseline | drop the offending construct; re-target or re-codon-optimise |
| **POS5 overexpression moves titer on its own** | measurable effect vs the same build without it | if not, the keystone claim is wrong — go Idp1-only and re-examine §1.2 |

The third gate is the one that tests DUET's own §7 hypothesis directly and cheaply.

### Stage 2 — relieve the sink (6–8 weeks)

*PDC1* promoter swap (§1.3), plus the 2-KIV drains — **ECM31 (20 TPM)**, **BAT2 (71)**, **LEU4
(205)**; LEU4 is the significant one of that set and BAT1 (241) should be treated carefully, since
the transaminases are also the route *to* valine the cell needs.

Gate: the target ethanol:isobutanol ratio is hit **and** growth rate is within an agreed fraction
of the parent. A strain that partitions beautifully and grows at half rate is not an industrial
strain.

### Stage 3 — xylose integration (8–12 weeks, in parallel where possible)

Only shaped once Stage 0 answers §2.1. If XR/XDH: revisit the *ALD6* decision, and expect the
§2.1 synergy. If XI: expect no synergy and plan carrier supply accordingly (§1.1).

Gate: xylose consumption rate, and **xylitol excretion below an agreed threshold** — xylitol is the
direct readout of the redox imbalance this design claims to exploit.

### Stage 4 — tolerance and recovery (only above ~8 g/L)

`NFS1/ISU1/YFH1`, the efflux set (`PDR5` 17, `SNQ2` 16, `YOR1` 17 TPM — all barely on), and ISPR.

**Do not start ISPR before this threshold.** At ~1 g/L and 30–35 °C, isobutanol's vapour pressure
is low and the stripped vapour is overwhelmingly water and ethanol; the condensate will not phase-
split unless it exceeds isobutanol's water solubility, **~85 g/L** ⚠ (handbook value, not an atlas
row). ISPR earns its capex near the toxicity ceiling, and the strain is currently ~10-fold below it.

`SPT15`/gTME is deliberately **not** in any stage: high variance, hard to combine with rational
edits, and worse in a polyploid.

---

## 4. Why this is more robust than the original

| single point of failure in DUET | how it is removed |
|---|---|
| Pos5 is the only matrix NADPH route | **two** routes — Pos5 and Idp1 — with independent failure modes (§1.2) |
| The shuttle's direction is assumed and unmeasured | tested functionally in **Stage 0, before any genetics**, with a defined fallback that keeps the design alive (§3) |
| Ethanol supply is welded to *PDC* retention | decoupled into an **operating parameter** — a feed rate, tunable in a run (§1.1) |
| The sink is retained at a 134× disadvantage | attenuated **asymmetrically by vessel**, so the partition acts on flux (§1.3) |
| Fe-S handled by three genes whose rationale the 2022 data removed | relocated to the gene that serves redox and Fe-S at once (§1.4) |
| mtDNA instability unmonitored in a mitochondrial design | **petite frequency as a standing release criterion** (§1.4) |
| Recovery concept fights the redox concept | resolved by §1.1; ISPR deferred to where it pays (§3, Stage 4) |

## 5. What this still does not fix

* **The yield gap is real and old.** Best yeast yield in this corpus is **0.0596 g/g** (14.5% of
  theoretical) against **0.411 g/g** in *E. coli*, and it has not closed in fifteen years. Nothing
  above claims to close it; the programme's case rests on the stranded-stream economics, not on
  matching *E. coli*.
* **Expression is not flux.** Every transcript number here says what is available to be
  transcribed, not what carries carbon. Stage 1's gates are titer gates for that reason.
* **FTO.** The three named estates are the *cytosolic* incumbents. The mitochondrial approach has
  its own originators and they are not on the list. The atlas holds **zero patent records**.
* **The atlas still cannot state the ceiling on the real substrate** — `product_theoretical_yield`
  holds glucose only. The mass yield on xylose is the same 0.411 g/g ⚠, but ATP per carbon is lower.

## 6. Immediate next actions for the atlas itself

1. **Un-exclude the 19 compartment-redox papers** (`docs/drafts/literature/POS5_REDOX_RESCUE.md`),
   which include the Pos5/Fe-S paper, the two-sources-of-matrix-NADPH paper and the POS5 mutator
   paper. All three are load-bearing for §1.2 and §1.4 and all three are currently unread.
2. **Seed the knowledge gaps** this design depends on: matrix NAD(P)H poise (exists), MPC pyruvate
   import capacity, petite frequency of matrix-targeted heterologous enzymes, and whether Adh3 can
   serve the product step (§2.2).
3. **Close DUET §5.2 and §5.4** — pentose scoping and the `in_situ_product_removal` facet. They are
   the two of four original scoping errors still open, and 5.2 blocks the actual substrate.
