# DUET, reviewed against the atlas — genetic engineering, and what survives contact with scale

**2026-09-22.** A reviewer's assessment of `docs/design/DUET_TARGET.md` against the evidence this
atlas now holds. Written to be argued with: every number below is either a row in the atlas or
marked as my inference, and the places where the proposal is *right* are as load-bearing as the
places where it is not.

**Summary verdict.** The compartment decision — the single choice most likely to have been wrong —
is **correct, and has since been independently validated by evidence that did not exist when the
concept note was written.** Two of the remaining three architectural claims are weaker than the
note asserts, one of them structurally. The gene set has a hole in it. And the distance to
industrial relevance is one to two orders of magnitude in titer, which is not unusual at TRL 3 but
does determine which of the proposed interventions are worth doing *first*.

---

## 1. Claim 3 (mitochondrial, not cytosolic) — validated, and it is the best call in the proposal

DUET's reasoning: run the pathway in the matrix, where 2-KIV is already made and **Ilv3 already
folds**, so the cytosolic Fe-S maturation problem never arises.

Evidence that has since arrived, from `doi:10.1016/j.synbio.2022.02.007` — which compares exactly
this choice in one background:

| strain | design | titer |
|---|---|--:|
| **mIBA^ILV5 (Y797)** | **mitochondrial** | **170 mg/L** |
| cIBA^ILV5 (Y812) | cytosolic, native NADPH KARI | 46 mg/L |
| parent (Y795) | no pathway | 37 mg/L |
| cIBA^IlvC6E6 (Y799) | cytosolic, NADH-balanced KARI | 31 mg/L |

**Both cytosolic builds sit at or below the parent.** Localization beats cofactor balance 3.8-fold
(P<5e-6). And the mechanism is the one DUET named in advance: DHIV — the Ilv3 substrate — piles up
8.6–16-fold in the cytosolic strains and is *depleted* 2.8–4.5-fold in the mitochondrial one, with
Atm1p induction alongside. Deleting the iron-regulon repressor *FRA2* rescues the cytosolic strain
2.4-fold (to 190 mg/L) and does **nothing** in the mitochondrial one.

That last result is the clean negative control: Fe-S supply limits Ilv3 **in the cytosol and not in
the matrix**. The proposal's stated rationale for claim 3 is, as far as this corpus goes, correct.

Corroborating: the highest yeast isobutanol titer in this atlas, **1,245 mg/L (SHy48,
`doi:10.1016/j.ymben.2017.10.001`, curated by the owner)**, is also a mitochondrial build.

**Reviewer's note.** This is worth stating plainly because it is unusual: the proposal made a
compartment bet before the comparative evidence existed, and the evidence went its way.

---

## 2. Claim 4 (Fe-S protection, dual-purpose) — in tension with claim 3, and should be deprioritized

The note argues one intervention serves two ends: isobutanol destroys Fe-S clusters (tolerance) and
the rate-limiting enzyme is an Fe-S enzyme (flux).

**If claim 3 is right, the flux half of claim 4 does not apply to DUET.** The 2022 data says Fe-S
supply limits Ilv3 *in the cytosol*; in the matrix, where DUET puts it, it does not. A
mitochondrial design has already bought the Fe-S benefit by construction — `NFS1`/`ISU1`/`YFH1`
overexpression is not what unlocks its flux.

The tolerance half is real but not yet binding. Measured in this atlas: isobutanol LC50 ≈ **1.5%
v/v (~12 g/L)**, with growth still observable at 2.4% v/v (`doi:10.1016/j.cels.2019.10.006`).
Against a best demonstrated mitochondrial titer of **1.245 g/L**, toxicity sits roughly **10-fold
above** anything yet achieved.

**Recommendation, corrected 2026-09-22.** Move `NFS1 ISU1 YFH1 SOD2` out of the first build —
but **do not drop the Fe-S intervention; relocate it to *POS5***. Pos5-derived NADPH feeds the
mitochondrial ISC machinery via ferredoxin reductase Arh1 (23.2 TPM) and ferredoxin Yah1
(96.1 TPM), and the corpus holds a paper titled *"Mitochondrial NADH kinase, Pos5p, is required for
efficient iron-sulfur cluster biogenesis"* — excluded and unread. So Pos5 supplies **both** Ilv5's
cofactor **and** the machinery that matures Ilv3's 2Fe–2S cluster. The dual-purpose intervention
claim 4 wanted exists; it is one gene earlier than the note looks, and it is the same edit as the
redox intervention. See `DUET_ROBUST.md` §1.4.

---

## 3. Claim 1 (ethanol as redox carrier) — coherent, unfalsified, and resting on an unmeasured quantity

The architecture in §7 of the note closes on paper: Adh3 oxidises ethanol in the matrix → matrix
NADH → the Ehrlich ADH step directly, and → Pos5 → matrix NADPH → Ilv5. Four problems, in
descending order of seriousness.

**3a. The quantity the whole argument depends on has never been measured, by anyone.** Four
independent passes over this corpus agree: **no paper measures a matrix NAD(P)H pool or ratio in
living *S. cerevisiae* under a named condition.** The atlas records it as a `never_attempted`
knowledge gap. The direction Adh3 runs *in vivo* is set by the matrix NAD⁺/NADH poise, and under
fermentative, glucose-repressed conditions the cell is NADH-rich — which is the direction that
*disfavours* ethanol oxidation. The shuttle may run backwards under exactly the conditions DUET
operates in. **This is the proposal's central unfalsified assumption, and it is also the cheapest
thing to test.**

**3b. Pos5 is not merely a single point of failure — it is a lowly expressed one.** Median TPM in
the SRP342112 background (cassette-aware index, quarantined runs excluded):

| gene | parent | Y797 (mito) | Y799 | Y812 |
|---|--:|--:|--:|--:|
| **POS5** | **17.0** | 24.1 | 28.5 | 33.0 |
| ADH3 | 235.5 | 245.9 | 204.2 | 268.8 |
| ILV5 | 566.2 | 542.1 | 1264.7 | 2285.3 |
| **PDC1** | **8736.7** | 8275.0 | 8204.4 | 7516.7 |

Pos5 runs **20–100× below the enzyme it must supply** and **~500× below Pdc1**. The note already
identifies Pos5 as the failure point; the measurement says it is worse than that. *POS5*
overexpression is not optional in this architecture — it is the architecture.

**3c. Pos5 costs ATP.** NADH kinase phosphorylates NADH at the expense of ATP. On a pentose stream,
where ATP yield per carbon is already lower than on glucose, every matrix NADPH bought this way is
an ATP not available for growth or maintenance ⚠ *(my inference from the enzyme's chemistry, not a
measured quantity in this corpus)*. The NADH-preferring KARI alternative avoids this cost as well
as the Pos5 dependency — but see §4.

**3d. Retaining Pdc means competing with a sink that is ~134× better expressed.** PDC1 8,737 TPM
against ILV2 65 TPM at the shared pyruvate node. In the same experiments, ethanol reached 45–47 g/L
at **>90% of theoretical** while isobutanol stayed below **0.2% of theoretical**. A Pdc-positive
background does not partition carbon; it sends essentially all of it to ethanol.

**Recommendation: attenuate, do not choose between retain and delete.** DUET is right that deleting
*PDC* removes the redox carrier and cripples the strain — the atlas's E1 criterion exists to
quantify exactly that cost. But "retain" as written accepts a 134-fold expression disadvantage. The
design question the note does not answer is *what ethanol:isobutanol ratio the shuttle actually
needs*, and the corresponding lever is a promoter swap on *PDC1* to a weak or titratable promoter,
not deletion. Setting that ratio as an explicit design target is, in my view, the most important
unanswered engineering question in the proposal.

---

## 4. The de-risking option DUET names has a negative result attached to it

§7 proposes an **NADH-preferring KARI variant** as the way to remove the NADPH requirement and
de-risk Pos5. Two pieces of evidence now bear on this, and both are unfavourable.

* **In the cytosol it made things worse.** Y799 — cytosolic, *Ec*IlvC 6E6, the NADH-balanced design
  — was the **worst strain in the study at 31 mg/L, below the untransformed parent**. The
  NADPH-imbalanced Y812 beat it 1.5-fold (P<5e-5). Cofactor "balance" was negatively signed.
* **In the mitochondrion it was abandoned.** A fifth strain, **mIBA^IlvC6E6 — mitochondrial *plus*
  NADH-KARI, which is precisely DUET's compartment choice combined with DUET's cofactor
  de-risking — was dropped from the study for a 166-fold elevated petite frequency.**

The second is a direct warning to this proposal, and it compounds: petite formation is loss of
mtDNA, in a design that is mitochondrial by construction and whose stated escalation path
(strategy E) is *mtDNA engineering*. A 166-fold petite rate would destroy both.

**Recommendation.** Do not treat the NADH-KARI as the de-risking default. If it is pursued, petite
frequency becomes a release criterion for every mitochondrial build carrying it, measured before
titer. The atlas should hold that as a `knowledge_gap`: *why does a bacterial KARI in the matrix
destabilise mtDNA, and is it the enzyme, the presequence, or the expression level?*

---

## 5. Claim 2 (substrate partitioning) — good industrial logic, with a hole in the gene set

The strategic case is the strongest part of the proposal commercially: a stranded C5 stream that is
currently burned has **zero opportunity cost**, the C6 train is untouched so the plant's revenue is
not at risk, and a bolt-on fermenter is brownfield capex. That is a genuinely well-chosen entry
point and it is why this is a credible TRL 3→5 programme rather than an academic one.

Three technical objections.

**5a. Partitioning the substrate does not partition the pathway.** Glucose-repressed promoters
switch the isobutanol pathway *on* when glucose is gone. They do not switch *PDC* off, and Pdc1 is
active on xylose-derived pyruvate exactly as it is on glucose-derived pyruvate. In the C5 vessel,
pyruvate still meets a 134×-better-expressed decarboxylase. The partition is real at the level of
*feedstock* and absent at the level of *flux*.

**5b. The gene set has no xylose-to-xylulose step.** `XKS1 TAL1 TKL1 RKI1 RPE1` are all at or below
xylulose. There is no *XYL1*/*XYL2* (XR/XDH) and no *xylA* (xylose isomerase) anywhere in the note.
Either the industrial strain already carries one — entirely plausible for a working 2G plant, and
the atlas records xylose utilisation as *"not recorded because it has not been supplied, not
because it is absent"* — or the proposal is missing its first committed step. **This is the single
highest-value fact to establish, because if the strain cannot consume xylose the whole partition is
moot.**

**5c. Which xylose route the strain uses changes the redox argument — possibly in DUET's favour.**
This is the one place where I think the note *understates* its own case. If the strain is
**XR/XDH**-based, the classic problem is a cofactor imbalance: XR consumes NADPH, XDH produces
NADH, leaving a cytosolic NADH surplus that normally forces xylitol excretion. DUET's architecture
consumes cytosolic reducing power by routing it through ethanol into the matrix. **The XR/XDH
imbalance and the ethanol shuttle are complementary**, and the redox architecture has a
*better* rationale on xylose than on glucose ⚠ *(my inference; nothing in this corpus tests it)*.
If the strain is **XI**-based, the route is redox-neutral and this synergy does not exist. Worth
establishing which, and if XR/XDH, worth stating explicitly in the proposal — it is a real argument
the note currently leaves on the table.

**5d. The atlas cannot yet state the ceiling on the actual substrate.** `product_theoretical_yield`
holds glucose only. The mass yield on xylose is the same **0.411 g/g** (both substrates are
(CH₂O)ₙ, and 3 xylose → 5 pyruvate → 2.5 isobutanol conserves it) ⚠ *(my calculation, not a curated
row)*, but ATP per carbon is lower. DUET §5.2's demand that pentose be scoped in is correct and
still unimplemented.

---

## 6. The gene set, audited against what is actually expressed

Every gene the note names, measured in the SRP342112 parent background. The point of this table is
that several named genes are **effectively off**, so "include *X*" is not the same as "*X* will be
available".

| named gene | parent TPM | reviewer's note |
|---|--:|---|
| **ARO10** | **1.8** | **Essentially silent.** The named KDC is not available in a glucose-grown industrial background — it is nitrogen-regulated. A strong promoter or a heterologous *kivd* is required, not inclusion |
| ADH7 | 0.0 | Not expressed at all |
| **POS5** | **17.0** | See §3b. The architecture's keystone, at 0.2% of Pdc1 |
| ATM1 | 7.9 | The Fe-S exporter, very low — and it rises to 11.8/15.1 in the cytosolic strains, consistent with the 2022 paper's Atm1p induction |
| ECM31 | 20.0 | The 2-KIV drain the note added. Low; deletion is cheap but the gain is likely small |
| XKS1 | 31.4 | And it *falls* in the producers |
| RKI1 | 19.0 | Lowest of the named PPP genes |
| PDR5 / SNQ2 / YOR1 | 17 / 16 / 17 | Efflux pumps are barely on under these conditions |
| PMA1 | 2223.7 | Very high already; further overexpression is unlikely to be the lever |
| SPT15 | 39.6 | gTME is high-variance and hard to combine with rational edits, especially in a polyploid. I would not spend phase-1 effort here |
| ILV2 | 65.0 | The committed step, 134× below Pdc1 |
| BAT1 / BAT2 | 241 / 71 | Both present; the transamination drain is real |
| LEU4 / LEU9 | 205 / 16 | LEU4 is the significant drain of the pair |

*(Caveat, from the requantification review: for genes the builds also carry on a cassette, native
rows in the engineered strains can carry residual read spillover — Y799/Y812 carry ILV3Δ2-19 while
the index row is full-length. The **parent** column is unaffected and is what the audit rests on.)*

---

## 7. Industrial scale — the honest arithmetic

| quantity | value | source |
|---|--:|---|
| Best yeast isobutanol titer in this atlas | **1,245 mg/L** | SHy48, mitochondrial, owner-curated |
| Best mitochondrial titer with matched controls | 170 mg/L | Gambacorta 2022 |
| Best yeast **yield** anywhere in the corpus | **0.0596 g/g** (14.5% of theoretical) | JWY23, cytosolic, 10 deletions |
| Best isobutanol yield in any host | **0.411 g/g** (100% of theoretical) | *E. coli*, `10.1016/j.ymben.2011.02.004` |
| Isobutanol LC50 | ~1.5% v/v (~12 g/L) | `10.1016/j.cels.2019.10.006` |
| The plant's incumbent product | 120 g/L ethanol | owner |

**The gap is one to two orders of magnitude in titer**, and the yeast/bacteria yield gap is ~7-fold
and has not closed in fifteen years of literature. That is not a reason not to proceed — it is the
reason the *entry point matters*, and DUET's entry point (a stranded stream with zero opportunity
cost) is chosen well. But three scale consequences follow directly.

**7a. In-situ product removal is premature, and it fights claim 1.** CO₂ stripping plus a decanter
is elegant, and isobutanol's heterogeneous azeotrope does self-separate — *provided the condensate
exceeds isobutanol's water solubility, ~85 g/L* ⚠ *(handbook value, not an atlas row)*. Two problems
at present titers. First, at ~1 g/L and 30–35 °C, isobutanol's vapour pressure is low and the
stripped vapour is overwhelmingly water and ethanol; the recovery is chasing a component present at
a fraction of a percent. Second, and structurally: **claim 1 deliberately co-produces ethanol in the
same vessel, and ethanol in the condensate acts as a cosolvent that suppresses the very phase split
the recovery depends on.** Claims 1 and the recovery concept are in direct tension and the note does
not acknowledge it. ISPR earns its capex somewhere above ~8 g/L, near the toxicity threshold. Until
then it is a solution to a problem the strain does not yet have.

**7b. TRL 5 at 5,000 L validates the biology, not the economics.** At 1 g/L a 5,000 L run yields
~5 kg. That is a legitimate demonstration of strain and process integration, and it is not a
dataset from which recovery economics can be projected. Worth being explicit about in the funding
narrative so that the milestone is not later read as an economic claim it cannot support.

**7c. Polyploidy multiplies every editing decision.** `chassis_profile` records the DUET strain's
ploidy as **unknown with candidates 1–4 open**, and the verification burden across DUET's loci
therefore spans 1× to 4×. With ~30 named genes, the difference between diploid and tetraploid is
the difference between a feasible and an infeasible phase-1 edit list. **Flow cytometry on the
strain is the single cheapest de-risking action available in this entire proposal**, and it gates
the edit plan rather than merely informing it.

---

## 8. Freedom to operate — the named estates may be the wrong ones

§6 commits to an FTO opinion against **Gevo, Butamax and DuPont**. Those are the estates around the
*cytosolic* isobutanol pathway, and the claim that a mitochondrial design "sits outside the
incumbent patent space" is plausible precisely because of that.

But the mitochondrial approach has its own originators: the compartmentalisation strategy and its
highest-titer demonstrations come from Avalos and co-workers
(`doi:10.1016/j.ymben.2017.10.001`, and the 2013 work). **Their institution may hold corresponding
claims, and they are not on the FTO list.** This atlas holds **zero patent records**, so I cannot
check it here — but an FTO scope that covers the three cytosolic incumbents and omits the
mitochondrial originator has a hole in exactly the direction DUET is heading. Worth adding before
the six-month commitment is priced.

---

## 9. What I would do first, and why

In order, cheapest-and-most-gating first:

1. **Flow-cytometer the strain.** Ploidy gates the entire edit plan (§7c). Hours, not weeks.
2. **Establish the xylose route — XR/XDH, XI, or neither** (§5b). If neither, the partition premise
   fails and everything downstream changes. If XR/XDH, §5c gives the redox architecture a stronger
   rationale that the proposal should be making explicitly.
3. **Test the redox architecture functionally before measuring it.** The matrix NAD(P)H measurement
   (§3a) is the rigorous experiment and it has never been done by anyone. The *cheap* version is a
   flux test: does *POS5* overexpression raise isobutanol in a mitochondrial build? If Pos5 is the
   keystone, that single edit should move the titer; if it does not, the architecture's central
   claim is wrong and everything after it is misdirected.
4. **Replace ARO10 and overexpress POS5** (§6, §3b) — the two named genes that are effectively off.
5. **Decide the ethanol:isobutanol ratio explicitly, and attenuate *PDC1* to hit it** (§3d).
6. **Defer** Fe-S protection (§2), gTME/`SPT15` (§6), and ISPR (§7a) out of phase 1.
7. **Add the mitochondrial estate to the FTO scope** (§8), and add petite frequency as a release
   criterion for any matrix-targeted bacterial enzyme (§4).

## 10. Where the atlas is still wrong about DUET

The note's §5 listed four scoping errors. Their status today:

| DUET §5 | status |
|---|---|
| 5.1 Ethanol as mechanism, not enemy (criterion E5) | **Done.** E5 exists with a 45-publication budget; 5 records admitted, and the finding is that the literature supports only ~5–8 qualitative records and **zero** quantitative matrix-redox measurements |
| 5.2 Pentose scoped in | **Not done.** No xylose theoretical yield, no XR/XDH/XI parts, `condition_context` still one carbon source per context |
| 5.3 Chassis is the industrial polyploid | **Partly.** `chassis_profile` holds it, CEN.PK is a comparator — but ploidy is `unknown` |
| 5.4 `in_situ_product_removal` facet | **Not done.** ISPR and non-ISPR titers can still be silently compared |

Two of four remain open, and 5.2 is the one that blocks the actual substrate.
