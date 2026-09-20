# POS5 and matrix NADPH — what the corpus already knew

2026-09-21. Read from the stored full texts, unattended. No new acquisition; all four papers were
already in the 1,308 held locally.

`DUET_TARGET.md` §7 names POS5 capacity as **"the atlas's highest-priority bottleneck
hypothesis"**, on this reasoning:

> Ilv5 needs NADPH and the Ehrlich ADH step needs NADH; ethanol oxidation by Adh3 supplies NADH
> directly, and `POS5` is the only named route from matrix NADH to matrix NADPH ⚠. That makes the
> architecture coherent — and it makes **`POS5` a single point of failure**.

Twenty-four stored papers mention POS5 or mitochondrial NADH kinase. Four of them speak to this
directly. The hypothesis survives in part, is **too strong** in part, and has a published
architectural precedent nobody in this project had noticed.

---

## 1. The claim that does not survive: "single point of failure"

`10.1186/s13068-023-02309-z` states the matrix NADPH supply plainly:

> "the mitochondrial NADPH is relying on the reactions catalyzed by NAD+/NADH kinase Pos5 and
> NADP+ dependent enzymes, including acetaldehyde dehydrogenases **Ald4 and Ald5**, isocitrate
> dehydrogenase **Idp1**, and malic enzyme **Mae1**"

So matrix NADPH has **at least five sources**, not one. The distinction worth keeping is narrow
but real:

* **Pos5 may well be the only route from matrix _NADH_ to matrix NADPH.** DUET's sentence, read
  literally, is not contradicted.
* **But matrix NADPH itself is not Pos5-dependent.** Ald4, Ald5, Idp1 and Mae1 generate it from
  other substrates entirely, bypassing NADH.

The consequence for the architecture: if Pos5 flux is insufficient, **Ilv5 does not necessarily
stall** — it may be supplied from the other four, just not by the ethanol-derived reducing power
DUET's design intends. The failure mode is therefore *"the redox loop does not close as designed"*
rather than *"the pathway stops"*. Those are different risks and they call for different
experiments. "Single point of failure" should be softened to **"the only route that closes the
ethanol→NADH→NADPH loop"**, which is what the architecture actually rests on.

## 2. The claims that do survive, and are now sourced rather than assumed

| DUET premise | corpus |
|---|---|
| Pos5 is the main matrix NADPH supply | *"Pos5 is considered as the main source of mitochondrial NADPH"* — `10.1186/s13068-023-02309-z` |
| Pos5 suits the NADH pool Adh3 makes | *"possesses higher NADH kinase activity than NAD kinase activity"* (ibid.); *"it strongly prefers NADH over NAD+"* — `10.1016/j.mec.2024.e00245` |
| NADH and ATP are available in the matrix | *"active NADPH synthesis from NADH with ATP consumed, both of which are abundant in the mitochondriona"* (ibid.) |

The NADH preference is the happiest finding here: the enzyme DUET depends on is the one that
prefers the substrate DUET supplies. Two independent papers say so.

## 3. The cost DUET's §7 sketch omits — and it bears on M3

Pos5 consumes ATP per turn. That was already noted from `10.1093/femsyr/foae006`. The comparative
NADPH-strategies paper adds the measured consequence:

> "A recurrent observation was a negative effect on cell growth, which is obviously a consequence
> of energy dissipation, since the kinase consumes ATP **and decreases the amount of NADH
> available for respiration**."

**That last clause answers the question M3 left open.** I had hypothesised — marked unverified —
that matrix NADH would be contested between Pos5 and the respiratory chain. It is, and it is
documented rather than inferred. Pos5 activity measurably reduces NADH available for respiration.

Set against the owner's M3 answer — *functional respiration is the preferred requirement for the
final industrial production strain* — this is a real trade, not a hypothetical one:

* Overexpressing Pos5 to serve Ilv5 **draws NADH away from respiration** and dissipates ATP.
* A respiring production strain therefore pays twice for the redox loop: once in ATP, once in
  respiratory capacity.
* The observed penalty is on **growth**, which in an industrial process is a yield and
  productivity question rather than a viability one.

This does not overturn the M3 answer. It prices it.

## 4. The finding nobody was looking for: DUET's architecture has a precedent

`10.1186/s13068-023-02309-z` — *"Engineering yeast mitochondrial metabolism for
3-hydroxypropionate production"* — is the same architecture as DUET in a different product: a
heterologous pathway relocated into the yeast matrix, with matrix NADPH supply then optimised.

Its reported progression:

| step | titre |
|---|---|
| MCR in the **cytosol** | 0.09 g/L |
| MCR targeted to the **mitochondria** | **0.27 g/L** — 3× from compartmentalisation alone |
| dissected MCR enzymes | 4.42 g/L |
| **+ POS5 and IDP1 overexpression** | **5.11 g/L** — +15.6% from matrix NADPH supply |
| + mitochondrial ACC1 mutant | 6.16 g/L (shake flask) |
| fed-batch | 71.09 g/L |

And its conclusion, reached independently of this project:

> "Metabolic modeling suggested that the mitochondrion serves as a **more suitable compartment**
> for 3-HP synthesis via the malonyl-CoA pathway than the cytosol, due to the opportunity to
> obtain a higher maximum yield and a lower oxygen consumption."

> "Taking together, the yeast mitochondrion seems to be a suitable subcellular compartment for
> 3-HP production."

**Why this matters to DUET.** Its §2 claim *"Mitochondrial, not cytosolic"* has been arguing from
first principles — 2-KIV is already made in the matrix, Ilv3 already folds there. This paper is an
independent, quantified demonstration that the same reasoning pays off for a different
malonyl-CoA-derived product, **and** that overexpressing POS5 on top of it adds a further
measurable increment. It is the nearest published analogue to DUET's architecture found so far,
and it is a supporting precedent rather than a competing claim, because the product is different.

It is also directly useful to phase 3: a strategy-C route currently has `score_evidence = NULL`
because nothing has been extracted. This is a candidate for the first non-isobutanol comparator —
admitted under a transferable-mechanism criterion rather than as an isobutanol measurement.

## 5. What changes

**In the design docs.** `DUET_TARGET.md` §7's "single point of failure" is too strong and should
read "the only route that closes the ethanol→NADH→NADPH loop". Flagged; not edited, because that
file is the owner's own concept note and the correction is theirs to accept.

**In the knowledge gaps.** The seeded gap *"is matrix NADH available to Pos5, or contested"* is
**answered: contested, with respiration, and documented.** It should move from `open` to
`resolved` with these citations once the route enumerator is re-run.

**In the parts question.** §7 names an NADH-preferring KARI as the alternative that de-risks the
Pos5 dependency. That case is now **stronger**, not weaker: the ATP cost is confirmed, the growth
penalty is observed, and the respiration competition is documented. Five stored papers mention an
NADH-dependent or NADH-preferring KARI and none has been read yet. That is the obvious next
unattended task.

**Not changed.** No measurement was extracted and no row was written. This is a reading of four
papers, reported so the owner can decide what to curate from it.

---

### Sources

| DOI | title | role here |
|---|---|---|
| `10.1186/s13068-023-02309-z` | Engineering yeast mitochondrial metabolism for 3-hydroxypropionate production | the architectural precedent, and the matrix NADPH inventory |
| `10.1016/j.mec.2024.e00245` | A comparative analysis of NADPH supply strategies in *S. cerevisiae* (Metab Eng Commun, 2024) | Pos5's NADH preference, ATP cost, growth penalty, respiration competition |
| `10.1093/femsyr/foae006` | Increased production of isobutanol from xylose … overexpressing Znf1 | the ATP cost, and isobutanol-from-xylose (DUET's substrate claim) |
| `10.1371/journal.pone.0346295` | Mitochondrial NAD kinase Pos5 is required for CoQ biosynthesis in yeasts (PLoS One, 2026) | 305 mentions of Pos5; not yet read — the deepest single source available |
