# The iron-limited bottleneck in Gambacorta et al. 2022 — extracted in full

**Source.** Gambacorta FV, Wagner ER, Jacobson TB, Tremaine M, Muehlbauer LK, McGee MA, Baerwald JJ,
Wrobel RL, Wolters JF, Place M, Dietrich JJ, Xie D, Serate J, Gajbhiye S, Liu L, Vang-Smith M,
Coon JJ, Zhang Y, Gasch AP, Amador-Noguez D, Hittinger CT, Sato TK, Pfleger BF (2022).
*Comparative functional genomics identifies an iron-limited bottleneck
in a Saccharomyces cerevisiae strain with a cytosolic-localized isobutanol pathway.*
**Synth Syst Biotechnol 7(2):738–749.** doi:10.1016/j.synbio.2022.02.007, PMID 35387233.

Extracted from the stored JATS XML at
`C:\Users\kangk\fermdb-data\fulltext\d8\d8d020d4b464e6435511697cd80cdda411bdab16f985dca58471ace96cac9555.xml`.
**No database was written.** Companion measurements file:
`docs\drafts\extraction\2026-09-22-gambacorta-measurements.tsv` (56 rows).

**Scope caveat that governs everything below.** The paper's own quantitative RNA/protein tables are
Tables S1–S5 and Files S1–S5, which are not in hand. Every numeric claim here comes from the main
text or a figure caption in the stored XML. Where the paper puts a number only in a supplement or
only in an unlabelled figure, that is stated rather than estimated.

---

## 0. Strain map used throughout

| paper name | atlas id | pathway | KARI | in SRP342112? |
|---|---|---|---|---|
| WT (CEN.PK113-5D *URA3*+) | `YAA:STRAIN:y795` | none | – | yes (parent) |
| mIBA<sup>ILV5</sup> | `YAA:STRAIN:y797` | mitochondrial (Cox4p MLS on *ARO10*, *adhA29C8*) | ScIlv5p, NADPH | yes |
| cIBA<sup>IlvC6E6</sup> | `YAA:STRAIN:y799` | cytosolic (MLS removed) | *E. coli* IlvC6E6, NADH | yes |
| cIBA<sup>ILV5</sup> | `YAA:STRAIN:y812` | cytosolic (MLS removed) | ScIlv5pΔ2-48, NADPH | yes |
| mIBA<sup>IlvC6E6</sup> | — (not in atlas) | mitochondrial | IlvC6E6, NADH | **no — dropped** |
| cIBA<sup>ILV5</sup> *fra2Δ* | — (not in atlas) | cytosolic | ScIlv5pΔ2-48 | **no — built later, Fig. 6 only** |

A fifth engineered strain exists and was discarded before any omics:

> "When constructing the mIBA<sup>IlvC6E6</sup> strain we uncovered an unexpected petite phenotype.
> The frequency at which the petite colonies arose in the mIBA<sup>IlvC6E6</sup> strain was 166-fold
> that of the wild-type (WT) strain (Table S2). … The mIBA<sup>IlvC6E6</sup> strain was not included
> in further studies due to this irreversible fitness defect." — §3.1

---

## 1. Which strains the iron limitation applies to, and which it does not

**It applies to the two CYTOSOLIC strains — cIBA<sup>ILV5</sup> (Y812) and cIBA<sup>IlvC6E6</sup>
(Y799). It explicitly does NOT apply to the mitochondrial strain mIBA<sup>ILV5</sup> (Y797), nor to
the WT parent.**

> "We hypothesize that the insufficient availability of cytosolic Fe–S clusters causes the Ilv3p to
> be the bottleneck in the cIBA<sup>IlvC6E6</sup> and cIBA<sup>ILV5</sup> strains." — §3.5

> "In contrast to the cIBA<sup>IlvC6E6</sup> and cIBA<sup>ILV5</sup> strains, intracellular levels of
> DHIV in the mIBA<sup>ILV5</sup> strain were at lower levels compared to the WT strain; specifically,
> the level of DHIV was 2.8-fold (P < 5E-4), 4.5-fold (P < 0.005), and 3.2-fold (P < 0.005) lower when
> compared to WT at 4, 10, and 26 h respectively, **which indicates mitochondrial-localized Ilv3p is
> not a bottleneck**." — §3.4

Note the asymmetry between the title and the abstract. The **title** says "a … strain" (singular);
the **abstract** and results attribute it to **both** cytosolic strains. The limitation tracks
**localization**, not the KARI choice:

> "Functional genomic analyses suggested that the poor performances of the cytosolic pathway strains
> were in part due to a shortage in cytosolic Fe–S clusters, which are required cofactors for the
> dihydroxyacid dehydratase enzyme." — Abstract

---

## 2. The evidence the authors give

Four independent lines. None is an enzyme activity assay — **there is no Ilv3p/DHAD specific-activity
measurement anywhere in this paper.**

### 2a. Metabolomics — substrate pile-up at the Ilv3p step (the primary evidence)

> "At 4 h, the cIBA<sup>ILV5</sup> strain had a 23-fold (P < 5.0E-4), 16-fold (P < 5.0E-5), and
> 4.1-fold (P < 0.005) increase in intracellular AL, DHIV, and KIV, respectively when compared to WT.
> Similarly, at 4 h, the cIBA<sup>IlvC6E6</sup> strain had a 22-fold (P < 5e-6), 8.6-fold (P < 0.0005),
> and 2.5-fold (P < 5E-4) increase in intracellular AL, DHIV, and KIV, respectively when compared to
> WT (Fig. 5). … **The significant accumulation of AL and DHIV in these strains indicates that ILV3 is
> a rate-limiting step.**" — §3.4

DHIV is the direct substrate of Ilv3p/DHAD. It is 8.6–16-fold **up** in the cytosolic strains and
2.8–4.5-fold **down** in the mitochondrial strain. That contrast is the whole argument.

### 2b. Proteomics — Atm1p and the Yap5p iron-sensing regulon

> "The protein levels of enzymes in the ISC and CIA machinery between the engineered strains and WT
> were relatively unchanged, with the exception of Atm1p, the mitochondrial X–S intermediate
> transporter (Table S5). **Atm1p was upregulated approximately 2.0-fold in the cIBA<sup>IlvC6E6</sup>
> and cIBA<sup>ILV5</sup> strains at all time points** when compared to WT (Fig. 5b)." — §3.5

> "Indeed, protein levels of Ccc1p, Tyw1p, and Grx4p were elevated in the cIBA<sup>IlvC6E6</sup> and
> cIBA<sup>ILV5</sup> strains for at least one of the time points with **Tyw1p having the highest fold
> change of 1.7 at 10 h** when compared to WT (Fig. 5b)." — §3.5

The sensing transcription factor named here is **Yap5p**, not Aft1/Aft2:

> "In the cytosol, excess Fe–S clusters are sensed by the iron responsive transcription factor, Yap5p.
> Yap5p can stably bind to 2Fe–2S clusters, inducing a conformational change that activates the
> transcription of genes to help regulate iron storage including CCC1, TWY1, GRX4, and CUP1 (Fig. 5a)."
> — §3.5

**Aft1/Aft2 appears only in §3.6, as the target of the intervention, not as an observed signature.**
The paper never reports an Aft1/Aft2 regulon signature in the transcriptome of Y799/Y812. If the atlas
wants an "iron regulon induction" claim from this study, it does not exist — what exists is a *Yap5p*
**protein-level** response.

### 2c. Proteomics — sulfur metabolism, via the cysteine sulfur donor

> "Proteins at a higher abundance compared to WT were enriched (P < 5E-5) for sulfur-related pathways
> (methionine biosynthesis [GO:0009086], cysteine biosynthesis [GO:0019344], and sulfate assimilation
> [GO:0000103]) (File S5). … This response was largely due to the depletion of intracellular cysteine
> since MET gene expression is induced by Met4p under cysteine-limited conditions; in fact, the
> intracellular cysteine levels were depleted in all engineered strains but more significantly in the
> cIBA<sup>IlvC6E6</sup> and cIBA<sup>ILV5</sup> strains (Fig. 5c). **Cysteine is used as the sulfur
> donor for synthesizing Fe–S clusters**, and we hypothesized the altered sulfur metabolism was related
> to the 2Fe–2S cluster requirement of the rate-limiting enzyme, Ilv3p." — §3.5

### 2d. Genetic control — the cytosolic Ilv3p is catalytically competent

> "To confirm that our cytosolic-localized Ilv3p was functional, we deleted the endogenous
> mitochondrial-localized ILV3 in the cIBA<sup>IlvC6E6</sup> strain and performed a growth
> complementation assay … indeed, the strain harboring only the cytosolic-localized Ilv3p grew on
> synthetic complete medium minus valine plates indicating **it was functional in its non-native
> subcellular compartment** (Fig. S5)." — §3.4

This rules out "the truncated enzyme is dead" and leaves cofactor supply as the explanation.

### 2e. What the evidence explicitly is NOT

> "Overall, **neither the mRNA counts nor the protein abundance data yielded an explanation** for the
> differences in isobutanol production we observed between the engineered strains." — §3.4

The bottleneck was **not** found in the transcriptome. It was found in the metabolome, corroborated by
the proteome. This matters for the atlas: SRP342112 alone would not have produced this conclusion.

---

## 3. Which pathway step, and the cluster type — a correction

**The step is Ilv3p / dihydroxyacid dehydratase (DHAD), converting DHIV → KIV.**

**The cofactor the authors invoke is a 2Fe–2S cluster, not a 4Fe–4S cluster.** The paper says 2Fe–2S
consistently, five times, from the introduction onward. Quoting rather than assuming, as instructed:

> "…a 2Fe–2S cluster-requiring dihydroxyacid dehydratase (DHAD, encoded by ILV3)" — §1

> "We hypothesized that the mitochondrial-localized Ilv3p is not a rate-limiting step in the
> mIBA<sup>ILV5</sup> strain because **the required cofactor for the enzyme, a 2Fe–2S cluster**, is more
> accessible in the mitochondria where its biogenesis begins. This is not the case for the
> cIBA<sup>IlvC6E6</sup> and cIBA<sup>ILV5</sup> strains since the synthesis and delivery of the required
> 2Fe–2S cluster into the cytosolic-localized Ilv3p requires Fe–S cluster biogenesis machinery that spans
> multiple compartments (both the mitochondria and cytosol)." — §3.4

> "…the mitochondrial iron sulfur cluster (ISC) machinery is responsible for generating the
> sulfur-containing intermediate (X–S), which is then exported to the cytosol via the ABC transporter
> Atm1p. In the cytosol, the X–S intermediate is matured into a cluster and loaded onto the
> cytosolic-localized apoprotein by the cytosolic iron sulfur cluster assembly (CIA) machinery (Fig. 5a).
> **We hypothesized that the Ilv3p step is rate-limiting in the cIBA<sup>IlvC6E6</sup> and
> cIBA<sup>ILV5</sup> strains due to this added complexity of the cross-compartmental assembly of the
> required cofactor.**" — §3.4

*(Yeast Ilv3p is reported in the wider literature as carrying a 2Fe–2S cluster, unlike the 4Fe–4S
bacterial DHADs such as* E. coli *IlvD. Whatever the correct biochemistry, the atlas should record what
**this** paper argues: 2Fe–2S. Do not enter 4Fe–4S against this citation.)*

**Why the cytosol is worse is a logistics argument, not a chemistry argument:** cluster biogenesis
*starts* in the mitochondrion (ISC), the intermediate must be exported (Atm1p) and matured in the
cytosol (CIA). A mitochondrially-localized Ilv3p sits where the clusters are made; a cytosolic one is
at the end of a three-compartment supply chain.

---

## 4. The intervention tested, and its outcome

**Intervention: deletion of *FRA2* (a.k.a. *BOL2*), the transcriptional repressor of the iron-regulon
activator Aft1/Aft2p. Not iron supplementation of the medium, and not ISC/CIA overexpression.**

> "This can be accomplished by increasing the availability of iron in the cell through deregulation of
> the iron regulon genes. To test our hypothesis, we disrupted iron homeostasis by deleting the
> transcriptional repressor Fra2p (also referred as its standard name Bol2p) of the iron regulon
> transcriptional activator, Aft1/2p, in the cIBA<sup>ILV5</sup> and mIBA<sup>ILV5</sup> strains
> (Fig. 6a)." — §3.6

**Things the atlas might expect and that were NOT done:** no FeSO₄ / iron-supplementation growth
rescue; no ISC or CIA overexpression construct; no *AFT1* overexpression; no DHAD activity assay; and
*fra2Δ* was **not** built in the cIBA<sup>IlvC6E6</sup> (Y799) background — only in cIBA<sup>ILV5</sup>
(Y812) and mIBA<sup>ILV5</sup> (Y797). Precedent is cited from a different enzyme:

> "This strategy was successful in increasing the activity of a different cytosolic-localized Fe–S
> cluster requiring enzyme, xylonate dehydratase, in S. cerevisiae [55,56]." — §3.6

### Outcome, with numbers

> "We observed that the deletion of FRA2 **significantly altered the isobutanol titer in the
> cIBA<sup>ILV5</sup> background strain, but not in the mIBA<sup>ILV5</sup> strain**; the
> cIBA<sup>ILV5</sup> *fra2Δ* strain produced **190 mg/L isobutanol at 48 h which is 2.4-fold more than
> the cIBA<sup>ILV5</sup> strain (P < 5E-5)** (Fig. 6b). Furthermore, the titer achieved by the
> cIBA<sup>ILV5</sup> *fra2Δ* strain **surpassed the isobutanol titer in our previous best producer,
> mIBA<sup>ILV5</sup>, by 1.3-fold (P < 5E-5)** indicating a high titer with a cytosolic isobutanol
> pathway localization can be achieved." — §3.6

Mechanistic confirmation at the metabolite level:

> "the normalized peak area (peak area/OD600) of DHIV was **1.7-fold (P < 0.05) and 2.9-fold
> (P < 0.005) lower in cIBA<sup>ILV5</sup> *fra2Δ* compared to cIBA<sup>ILV5</sup> at 10 and 26 h**,
> respectively." — §3.6

And the one result that does **not** fit, reported honestly by the authors:

> "The KIV level was also measured, but **we did not observe an increased level of KIV in the
> cIBA<sup>ILV5</sup> *fra2Δ* strain compared to the cIBA<sup>ILV5</sup> strain as one might expect from
> relieving the bottleneck at Ilv3p.** Instead, the KIV level between the engineered strains was not
> significantly altered, except at 26 h where the cIBA<sup>ILV5</sup> strain had a 3.5-fold increase in
> KIV compared to the cIBA<sup>ILV5</sup> *fra2Δ* strain (P < 0.05). We suspect an accumulation of KIV
> was not seen because KIV is readily consumed in the subsequent step." — §3.6

Note the authors' own hedging in the closing sentence of §3.6 — "**potentially** by partially
overcoming the 2Fe–2S cluster cofactor limitation" — and in the abstract, "**may be** partially
recovered". The iron mechanism is presented as a supported hypothesis, not a demonstrated cause. Iron
content of the cells was never measured; the abstract's "thereby increasing cellular iron levels" is
an inference from the *fra2Δ* genotype, not a measurement reported in this paper.

### An arithmetic tension worth recording

The Fig. 6 experiment is a **separate fermentation** from Fig. 2, and the two do not reconcile
numerically. 190 ÷ 1.3 = **146 mg/L** implied for mIBA<sup>ILV5</sup> in the Fig. 6 run, against
**170 mg/L** reported at 38 h in Fig. 2. 190 ÷ 2.4 = **79 mg/L** implied for cIBA<sup>ILV5</sup>,
against **46 mg/L** at 38 h in Fig. 2. Different timepoints (48 h vs 38 h) and different runs, so this
is not a contradiction — but any atlas record that ranks the *fra2Δ* strain against the 170 mg/L
headline is making a **cross-experiment** comparison. Flagged in the TSV as confidence=low, derived.

---

## 5. Why the mitochondrial strain escapes

Two statements, both hypotheses, both quoted:

> "We hypothesized that the mitochondrial-localized Ilv3p is not a rate-limiting step in the
> mIBA<sup>ILV5</sup> strain because the required cofactor for the enzyme, a 2Fe–2S cluster, **is more
> accessible in the mitochondria where its biogenesis begins.**" — §3.4

> "**We hypothesize the fra2 deletion had no effect on isobutanol titer in the mIBA<sup>ILV5</sup>
> strain because the cofactor availability for the mitochondrial-localized Ilv3p was not limited.**"
> — §3.6

The second is the stronger form of the argument: the *fra2Δ* null result in Y797 is a negative control
that behaves as the iron hypothesis predicts. It is the cleanest piece of evidence in the paper that
the limitation is specific to the cytosolic localization.

The authors are also careful that the general strategy is not universal:

> "…however, this strategy may not be effective for all Fe–S cluster requiring enzymes as this strategy
> had no effect on 6-phosphogluconate dehydratase activity [55,58]." — §4

---

## 6. What this implies for route ranking — strictly inside what the paper says

1. **Localization dominates cofactor balance.** Mitochondrial beats cytosolic 3.8-fold on titer
   (170 vs 46 mg/L, P < 5E-6); NADH-balancing *loses* to NADPH 1.5-fold within the cytosolic pair
   (46 vs 31 mg/L, P < 5E-5). A route-ranking feature for "compartment" is supported by this paper;
   a feature for "redox-balanced KARI" is, on this evidence, **negatively** signed at low flux.

2. **A cytosolic route carries a cofactor-supply penalty that is not visible in expression data.**
   The authors state plainly that transcript and protein levels did **not** explain the performance
   differences (§3.4). Any route score built only on expression evidence will mis-rank these four
   strains.

3. **The penalty attaches specifically to the DHAD/Ilv3p step, and only when that step is cytosolic.**
   Evidence: DHIV 8.6–16-fold up in cytosolic strains, 2.8–4.5-fold down in the mitochondrial strain.

4. **The penalty is partially removable by a host-side iron intervention, not a pathway-side one.**
   *fra2Δ* raises the cytosolic strain 2.4-fold and takes it past the mitochondrial strain by 1.3-fold.
   So "cytosolic is worse" is conditional on host iron status, not an intrinsic property of the route.
   The paper's own conclusion: "demonstrating that both localizations can support flux to isobutanol"
   (Abstract).

5. **The caveats the paper attaches, which must ride with any ranking derived from it.**
   (a) The iron mechanism is a hypothesis — "potentially", "may be" — with no cellular iron measurement
   and no DHAD activity assay. (b) The KIV metabolite result did not move as predicted. (c) The whole
   comparison is at *very* low flux: ethanol reached 45–47 g/L at >90% of theoretical in **every**
   strain while isobutanol never exceeded 190 mg/L. The authors say so: "These metrics indicate that
   ethanol remains the dominant fermentation product and that pathway localization and cofactor-balance
   alone were not the limiting factor in isobutanol fermentation" (§3.2), and "we hypothesize that the
   cofactor imbalance will have to be resolved for the capacity of the isobutanol pathway to be
   enhanced… Future functional genomics studies with engineered strains disabled for ethanol production
   should uncover new genetic targets" (§4). **Any rank order taken from this paper is a rank order at
   <0.2% of theoretical isobutanol yield, in a strain set with ethanol fermentation fully intact.**

6. **Out of scope for ranking on this citation:** no specific productivity, no % of theoretical for
   isobutanol, no isopentanol or 2-methyl-1-butanol, and no reported glycerol/acetate/lactate numbers.
   Flux-leak ratios to the other fusel alcohols **cannot** be computed from this publication.

---

## 7. Cross-check: the atlas's transcript result against the paper

The atlas requantified all 33 SRP342112 runs against the deposited cassette (GenBank **MZ541859.1**)
plus wild-type *E. coli* `ilvC` — see `docs/reports/2026-09-22-transgene-requantification.md`. Verdict
per claim:

| atlas claim | paper's position | verdict |
|---|---|---|
| All four cassette constructs 13–17 log2 above parent | states all synthetic ORFs detected; no fold-change vs parent given | **agrees in direction, silent on magnitude** |
| `adhA` ~11,600 TPM in every producer, 0.5 in parent | states `MLS-adhA29C8`/`adhA29C8` detected in engineered strains; no value in main text | **agrees qualitatively, silent on value** |
| `ilvC` 1,426 TPM in Y799, exactly 0.0 elsewhere | `ilvC6E6` listed among detected transcripts; genotype makes exclusivity necessary | **agrees** |
| Native `ARO10` silent, 0.9–1.7 TPM in every strain | native gene mRNA "not statistically significantly altered in any of the engineered strains" | **agrees on invariance, silent on the absolute level** |
| Native `ILV3` ~110–385 TPM after spillover removal | same "not statistically significantly altered" statement | **possible disagreement — see 7b** |
| **Cassette expression rank order** | paper asserts a specific ordering | **DISAGREES — see 7a** |

### 7a. The real disagreement: the cassette expression rank order

The paper's claim, verbatim:

> "Normalized counts (RPKM) for all synthetic codon-optimized isobutanol genes (ILV2, ILV2Δ2-54, ILV5,
> ILV5Δ2-48, ilvC6E6, ILV3, ILV3Δ2-19, MLS-adhA29C8, adhA29C8, MLS-ARO10, and ARO10) were successfully
> detected in the transcriptomes of the engineered strains (Table S4). **In general, the amount of RNA
> detected for each transcript correlated with the predicted promoter strengths of each gene
> (P<sub>TDH3</sub>-ARO10 > P<sub>PGK1</sub>-ILV3 > P<sub>TEF1</sub>-ILV5/ilvC6E6 >
> P<sub>TEF2</sub>-adhA29C8 > P<sub>ADH1</sub>-ILV2)** (Table S4)." — §3.4

The atlas's measured medians, from the same runs:

| rank | paper's asserted order | atlas, cassette+ILV5 (Y797/Y812, n=15) | atlas, cassette+ilvC (Y799, n=9) |
|---|---|---|---|
| 1 | **ARO10** (P<sub>TDH3</sub>) | **ILV3 — 16,950 TPM** | **adhA — 18,918 TPM** |
| 2 | ILV3 (P<sub>PGK1</sub>) | **adhA — 10,524** | ILV3 — 15,607 |
| 3 | ILV5 / ilvC6E6 (P<sub>TEF1</sub>) | ARO10 — 7,251 | ARO10 — 6,381 |
| 4 | **adhA29C8** (P<sub>TEF2</sub>) | ILV5 — 4,273 | **ilvC — 1,426** |
| 5 | ILV2 (P<sub>ADH1</sub>) | ILV2 — 602 | ILV2 — 829 |

**Three of the five positions disagree, and the two extremes of the disagreement are the two genes the
atlas cares most about.**

- **`adhA` is the paper's second-weakest element and the atlas's strongest-or-second-strongest.** The
  paper places P<sub>TEF2</sub>-*adhA29C8* below P<sub>TEF1</sub>-*ILV5*/*ilvC6E6*. The atlas measures
  adhA at 10,524 TPM against ILV5's 4,273 (2.5× the other way) and, in Y799, adhA 18,918 against ilvC
  1,426 — **13-fold the other way.** To reconcile the atlas's Y799 numbers with the paper's stated
  ordering, `ilvC` would have to exceed `adhA`; it is 13-fold below it.
- **`ARO10` is the paper's strongest element and the atlas's third.** ILV3 and adhA both outrank it.
- Only the bottom rank agrees: *ILV2* under P<sub>ADH1</sub> is weakest in both, in both strain groups.

**How much weight this bears.** The paper's sentence is hedged ("in general … correlated with the
**predicted** promoter strengths") and its actual per-gene RPKM values live in **Table S4, which is not
in hand** — so what is being contradicted is a stated ordering, not a published table of numbers. The
two measurements also differ methodologically (RPKM on a Bowtie2/HTSeq pipeline against S288C + added
foreign sequences, vs the atlas's TPM against S288C + the MZ541859.1 CDS set). Recommended atlas
record: **flag as a conflict, resolvable only by obtaining Table S4**, and do not treat the paper's
promoter-strength ordering as evidence about `adhA` or `ilvC` abundance.

### 7b. The softer tension: native *ILV3*

The paper:

> "The transcript levels of the native ILV2, ILV5, ILV3, and ARO10 genes were also investigated, and as
> expected, **the mRNA abundances of the native genes were not statistically significantly altered in
> any of the engineered strains compared to the WT strain** (File S1)." — §3.4

The atlas, after removing 88% cassette spillover from the native *ILV3* row: Y795 110.1, Y797 134.1,
Y799 384.3, Y812 370.5 TPM. That is a **~3.5-fold spread**, with **both cytosolic strains** elevated
over the parent and the mitochondrial strain essentially flat.

Two readings, and the atlas should not pick one without more work:

1. **A genuine disagreement.** If native *ILV3* really is 3.4× up in Y799/Y812, the paper's blanket
   "not statistically significantly altered" is wrong for that gene — and it would be an interesting
   result, since an induced native *ILV3* is exactly what a cell short of DHAD flux might do.
2. **Residual spillover, and the more likely reading.** The cassette *ILV3* row in the atlas index is
   the **full-length** codon-optimized ORF from MZ541859.1 (the mIBA plasmid), but Y799 and Y812 carry
   **ILV3Δ2-19**, which lacks the first 57 nt. The cytosolic strains' reads therefore map to a slightly
   imperfect reference, which would push *more* residual onto the native row **in exactly the two
   strains that show the elevation**. With the cassette row at ~15,600–16,950 TPM, a residual leak of
   only 1.5–2% fully accounts for the 110 → 370 gap. That the two flat strains are the parent (no
   cassette) and Y797 (exact reference match) fits this reading precisely.

**Recommended action:** before recording any native-*ILV3* induction from SRP342112, rebuild the index
with a separate `cassette_ILV3_d2-19` row for the cytosolic strains. Until then, treat the paper as
the better authority here and record native *ILV3* as unchanged.

### 7c. Three further notes for the atlas

- **The paper cannot corroborate the absolute levels at all.** Every number the atlas wants a second
  opinion on — 11,605 TPM adhA, 1,426 TPM ilvC, 0.9–1.7 TPM native ARO10 — is in Table S4 or File S1,
  neither of which is in hand. On absolute abundance the paper is **silent**, not agreeing.
- **The "exactly 0.0 elsewhere" claim for `ilvC` is genotype-grouped, not label-grouped.** The atlas's
  own requantification report groups runs "by the genotype each run's own transcriptome shows, not by
  its label", and flags four mislabelled T14 runs (SRR16481343, …346, …349, …352). Under the *submitted
  labels*, `ilvC` is non-zero in runs declared Y795 and Y812. The paper says nothing about sample
  labelling and cannot arbitrate this.
- **The paper independently supports the atlas's "the engineered steps are not transcriptionally
  limited" conclusion**, and by a stronger route than expression: "Overall, neither the mRNA counts nor
  the protein abundance data yielded an explanation for the differences in isobutanol production we
  observed between the engineered strains" (§3.4). The atlas and the authors reach the same place —
  expression is not the discriminator; cofactor supply is.

---

## 8. Provenance

- Full text: stored JATS XML, oa_status green, `application/xml`, sha256
  `d8d020d4b464e6435511697cd80cdda411bdab16f985dca58471ace96cac9555`.
- Atlas transcript figures quoted in §7 are from
  `D:\project\yeast-alcohol-db\docs\reports\2026-09-22-transgene-requantification.md`.
- **Not in hand and required to close the open items:** Table S1 (strains), Table S2 (petite
  frequencies), Table S3 (DE counts), **Table S4 (per-gene synthetic RPKM — needed for §7a)**, Table S5
  (ISC/CIA proteins), Files S1–S5 (full RNA/protein/metabolite matrices — needed for §7b and for the
  glycerol/acetate/lactate titers). Intracellular metabolomics is on GitHub at
  `AmadorNoguezLab/compartmentalized-isobutanol-pathways-in-S.-cerevisiae`; proteomics at MassIVE
  `MSV000088169`.
- **No database write was performed.**
