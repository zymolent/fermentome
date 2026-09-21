# The ⚠ audit — what the design documents got wrong

2026-09-21, Wave 3. Two agents against the 51 marked claims in `ISOBUTANOL_PROGRAM.md` (26),
`MITOCHONDRIAL_PROGRAM.md` (22) and `DUET_TARGET.md` (3).

**⚠ has always meant "written from memory, never checked."** `MITOCHONDRIAL_PROGRAM.md`'s own
header carries the instruction — *"Verify every ⚠ ... before building anything"* — and it had never
been executed. Drafts in `docs/drafts/warnings/`. 104 quotes, **0 absent, 0 spliced**; the two
most consequential I re-read in the source myself.

| | confirmed | incomplete | overstated | **wrong** | not in corpus | already covered |
|---|---|---|---|---|---|---|
| ISOBUTANOL_PROGRAM | 7 | 13 | 1 | **4** | 1 | — |
| MITOCHONDRIAL + DUET | 7 | 2 | 3 | **1** | 3 | 9 |

**Half the marked claims were not simply right or wrong — they were incomplete.** That is the
useful outcome: 15 claims that are directionally sound and would mislead anyone acting on them
literally.

---

## 1. The claim that would have cost a build cycle

**`ISOBUTANOL_PROGRAM.md` L272 — *ECM31* is marked "(attenuate)" because deleting it is
"plausibly essential".** It is not. `ecm31Δ` is viable and is an ordinary published deletion in
isobutanol strains — including the 2.09 g/L strain — because yeast imports pantothenate through
Fen2.

Acting on the document as written, the atlas would order a promoter-swap or degron build plus an
essentiality control **for a gene four published strains simply delete**, while 2-KIV keeps
leaking to pantothenate throughout. The same line names *LEU4* alone where the corpus strains
delete *leu4Δ leu9Δ* — leaving Leu9 draining the node, and the failure would be blamed on the
route rather than on the deletion set.

## 2. The number strategy E is partly sold on

**`MITOCHONDRIAL_PROGRAM.md` §1: "mtDNA is present at roughly 50–200 copies per cell ⚠."**

The corpus splits cleanly, and I read both sides directly:

* **Every direct measurement lands 14–32.** The population survey: *"a median of 18 mitochondrial
  genomes for each haploid nuclear genome. The variation is however particularly high across the
  population, reaching over 80 copies."* Mutation-accumulation lines give 14; qPCR of wild type on
  YPD gives 18.
* **Every 50–200-style figure is a review sentence citing something else** — *"Its copy number per
  cell ranges from 50 to 200 ()"*, with the citation marker stripped by extraction.

So **50–200 is the top of a secondary range that no primary measurement in this corpus reaches.**
A ranker fed 50–200 rewards strategy E on dosage by roughly three- to ten-fold more than the
evidence supports.

**But the same paper hands over the argument §1 never makes:** *"the mtDNA copy number scales up
with ploidy in a linear way, with diploid strains having around double number of mitochondrial
genomes and triploid having three times the number."* DUET's chassis is an industrial polyploid,
so it genuinely carries proportionally more. **That — not "50–200" — is the defensible form of the
gene-dosage case for E**, and it ties the argument to a chassis property the atlas already tracks.

Two riders worth keeping: copy number is **not** expression (nothing measures protein per copy),
and it moves 1.6–3× with single nuclear mutations and with carbon source. It is a regulated
variable, not a chassis constant.

## 3. Pos5 is not the only matrix NADH → NADPH route, and this corrects us twice

`DUET_TARGET.md` §7 calls Pos5 *"the only named route from matrix NADH to matrix NADPH"* and
therefore *"a single point of failure."*

An earlier report this session (`2026-09-21-pos5-matrix-nadph.md`) already knocked down the broad
version — matrix NADPH has at least five sources — but **preserved the narrow one**: *"Pos5 may
well be the only route from matrix **NADH** to matrix NADPH."* That hedge is also wrong, and I
verified the passage in the source:

> "redox cofactors have been balanced for isobutanol production by overexpressing pyruvate
> carboxylase (PYC2), malate dehydrogenase (MDH2), and malic enzyme (MAE1) in the cytosol (in a
> decompartmentalized pathway) **or in its native mitochondrial location to produce NADPH**"
>
> "results in a strain that produces **221 ± 27 mg/L of isobutanol, a near 5-fold increase** in
> titers in comparison to sole upregulation of BCAA biosynthesis"

The Pyc2/Mdh2/Mae1 shunt runs pyruvate → oxaloacetate → malate (consuming NADH) → pyruvate
(producing NADPH). It is a second matrix route from NADH to NADPH, it has been built, and it
produced a near-five-fold isobutanol increase.

**It is not in DUET's gene set at all.** That is an actionable design gap rather than a
documentation fix: §7's `knowledge_gap` rows should be three, not two, and the third is "is the
Pyc2/Mdh2/Mae1 shunt a better matrix NADPH supply than Pos5 for this architecture?" A third option
removes the question entirely — an NADH-preferring KARI, which drops the NADPH requirement.

*(Note the Pyc2 step consumes ATP to carboxylate, so this shunt is not free either. Pos5 consumes
ATP too. Neither is a free lunch; the point is that there are two doors, not one.)*

## 4. The redox error that would stamp routes as balanced when they are not

**L45 — "the ADH step typically takes NADH"** is true for Adh1/Adh2/AdhA and false for
Adh6/Adh7/YqhD. **The published yeast route is kivd + ADH6, which is NADPH at both steps** — two
NADPH per isobutanol, not one NADPH and one NADH.

**L122 compounds it**: the 100%-of-theoretical anaerobic *E. coli* result needed **two** engineered
swaps — IlvC6E6 *and* AdhA-RE1 — not the KARI alone. (The benchmark audit reached the same
conclusion independently from BM-COF-004.)

Together these are a two-reducing-equivalent error, and §5 says the route card computes its redox
verdict. A wrong cofactor per part means the card stamps `redox ✓` on routes that do not balance.
**Cofactor belongs on the part, never on the generic step role.**

## 5. Where the audit confirmed something, and it matters that it did

**KDC "typically homotetrameric" and ADH "often Zn-dependent, oligomeric" — both confirmed.**
KivD's crystal structure is a tetramer, corroborated by gel filtration; KDC is TPP-dependent with
homotetrameric active forms; yeast Adh1 is named among tetrameric ADHs.

So the `never_attempted` gap this session opened is **correctly placed** — and the agent sharpened
it further than I had: the risk is **specifically the KDC**, because Fe-containing ADHs exist and
are a real non-Zn hedge, while **there is no equivalent hedge for thiamine**. One contradiction
recorded rather than smoothed: a 2026 figure legend calls KivD a dimer.

## 6. Two corrections to claims about the atlas's own competence

* **`MITOCHONDRIAL_PROGRAM.md` L9 is wrong about its own document.** It says *"Verify every ⚠ in
  section 3"* — but §3 contains exactly **one** mark, and it is a corpus-*size* estimate. Every
  construct-relevant mark is in §1 and §2. A reader obeying the instruction literally verifies the
  budget table and builds on unchecked biology. → "sections 1 and 2".
* **L170 — "guide RNA import is the unsolved step"** is true in mammalian cells and wrong for
  yeast: MTS-Cas9 with an ordinary SNR52-driven gRNA significantly raises ρ⁰ formation, so some
  gRNA reaches the matrix by an intrinsic mechanism. In yeast the blocking step is **donor-DNA
  delivery**. The claim needs the organism split.

## 7. Seeded knowledge gaps that are themselves defective

**L230 — two of five seeded gaps are wrong**, and §5 says the gap list is *computed*, so a wrong
gap is ranked rather than caught:

* **Gap 5 (NADH-KARI in yeast) is answered negatively in the corpus** by three papers — the
  variants underperformed the wild-type NADPH enzyme on specific activity. Seeding it `open` sends
  a team to redo an experiment the literature has already lost twice.
* **Gap 2 is aimed at the wrong molecule.** Isobutanol crosses the plasma membrane by passive
  diffusion; the unsolved export is of **acetolactate / DHIV / KIV**. As written it funds a
  transporter screen for a carrier that does not exist, while the real intermediate leak stays
  uncounted.

## 8. Smaller, but worth the curator's minute

* **L93 — zero peroxisomal isobutanol builds** across 366 readable isobutanol papers. Strategy D
  should be labelled Zone I, not presented as a fourth published family.
* **L91 — over-truncating Ilv3 past ΔN19 kills activity.** A concrete bench trap; worth recording
  as parts: Ilv2ΔN54 / Ilv5ΔN48 / Ilv3ΔN19.
* **L111 — *PDC1/5/6* appear as `[competing]` in the diagram and as KDC parts in the catalog.** A
  deletion proposal taken from the diagram alone reproduces the corpus's own decarboxylase-negative
  control strain: the ethanol sink and the product step deleted in one construct.
* **Strategy C's precedent is real but its *benefit* is contested in the same corpus** — "obscured
  by conflicting reports", both localizations reaching similar titers, and cytosolic argued
  preferable at **high glucose and anaerobic growth**, which are DUET's conditions. That lands on
  §5 question 1 and on DUET architectural claim 3.
* **A successful strategy C does not shrink E's folding risk.** C demonstrates that *imported*
  enzymes work in the matrix; it says nothing about matrix-*synthesised* ones.

---

## What I have not done

**Not one design document has been edited.** Every finding above is a proposal in
`docs/drafts/warnings/`, with the claim, the verdict, verbatim evidence, concrete replacement
wording, and a `consequence_if_wrong` field. Editing `ISOBUTANOL_PROGRAM.md`, `DUET_TARGET.md` or
`MITOCHONDRIAL_PROGRAM.md` changes what the programme believes, and that is the owner's.

The three I would apply first, on `consequence_if_wrong` alone: **ECM31** (§1, wastes a build
cycle), **the ADH cofactor** (§4, silently mis-balances routes), and **the two defective seeded
gaps** (§7, they are computed into the ranking).
