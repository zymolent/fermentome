# The measuring stick, measured

2026-09-21. Wave 1 of the unattended plan: six agents, one per category, against
`data/benchmarks/known_positives.yaml` — **41 entries, 0 previously verified, all 41 sharing one
placeholder evidence string** ("Background knowledge, no source consulted").

PLAN.md S.5 calls recovery against this set *"the headline number for whether the atlas works."*
It could not mean anything while the set itself was unchecked. Now it is checked.

**Every quote below was re-resolved in its real source at its own offsets before entering this
report — 37 of 37 pass.** Entries without a quote are negative controls, where absence is the
result. Drafts are in `docs/drafts/benchmarks/`; nothing has been written to `data/`.

## The tally

| verdict | n |
|---|---|
| supported | 17 |
| partially_supported | 16 |
| **contradicted** | **2** |
| holds (negative controls) | 5 |
| uncertain (negative control) | 1 |
| not_in_corpus | **0** |

Zero `not_in_corpus` is itself worth noting: the corpus could speak to every positive claim in the
set. The problem was never coverage.

---

## 1. The benchmark set contradicts itself

**This is the finding that matters most, because it means the set could not have been passed.**

*BM-PATH-007*: "the isobutanol route crosses the mitochondrial inner membrane **exactly once**,
between 2-ketoisovalerate production in the matrix and its decarboxylation in the cytosol", with
`expected_outcome: "Exactly one compartment transition."`

*BM-PATH-011*: "**Pyruvate reaches the mitochondrial matrix through the mitochondrial pyruvate
carrier**, so the matrix branch of the route depends on a transport step that is itself
engineerable."

Those are two different numbers for the same count. `doi:10.1038/s41598-019-40631-5` settles it in
consecutive sentences, and I read the passage directly rather than taking the agent's word:

> "In S. cerevisiae, cytosolic pyruvate is imported into the mitochondria via mitochondrial
> pyruvate carrier (MPC) complex, and then pyruvate is converted to 2-KIV by sequential catalytic
> reactions of Ilv2 (ALS), Ilv5 (KARI), and Ilv3 (DHAD) in the mitochondrial matrix. The
> mitochondrial 2-KIV is then exported to the cytosol"

Two crossings. **BM-PATH-011 is right and BM-PATH-007 is wrong** — and because BM-PATH-007's
expected outcome is an exact count, *an atlas that correctly returns both transitions scores as a
failure on it*. The measuring stick penalised correctness. That is the inverse of what S.5 wants,
and it would have been invisible until someone tried to pass the set.

**Recommended:** restate BM-PATH-007 as two transitions (pyruvate in, 2-KIV out), or make the
route's start compartment explicit in the query shape so "exactly once" has a defined scope.

## 2. The CRISPR row has gone stale

**BM-MIT-006** asserts there is no established CRISPR-Cas route for editing yeast mtDNA.
`doi:10.7717/peerj.8362` (2020) is in the corpus and reports the opposite:

> "We confirmed donor DNA insertion at the target sites facilitated by homologous recombination
> only in the presence of Cas9/gRNA activity in yeast mitochondria and Chlamydomonas chloroplasts."
>
> "This is the first demonstration of CRISPR-mediated genome editing in both mitochondria and
> chloroplasts in two distantly related organisms."

It sidesteps the guide-RNA import problem rather than solving it — Cas9 and the guides are
expressed from a plasmid delivered biolistically that then replicates inside the organelle. So the
row's *premise* (import unsolved) survives, and is restated by a 2023 review also in the corpus.
Its *headline* does not.

The row is also compound — it bundles four separable claims (no CRISPR route; gRNA import
unsolved; biolistic-into-ρ⁰; mitoTALEN/mitoZFN delete rather than insert) behind one verdict, and
only one of them is false. Its mitoTALEN leg has **no yeast support in this corpus at all**: the
only mitoTALEN paper held is about *plant* mitochondria.

**Recommended:** split per technique and date-stamp the CRISPR leg.

## 3. A correction to one of the agents — the 0.411 g/g scare

The ethanol agent reported that **0.411 g/g is a substrate mix-up** — that the corpus writes 0.41
for glucose and attaches 0.411 to *xylose*, and that the benchmark had pinned the xylose ceiling
onto glucose. Since 0.411 g/g is the phase-1b acceptance bound and sits in
`product_theoretical_yield`, I checked it rather than relaying it.

The textual observation is real. `doi:10.1093/femsyr/foae006` does say:

> "the theoretical yields of 410 mg isobutanol/g glucose (Generoso et al. ), or 411 mg/g xylose
> (Zhang et al. )"

**The inference is wrong, and the reason is worth keeping.** Run the arithmetic:

| | stoichiometry | g/g |
|---|---|---|
| isobutanol from glucose | 1 : 1 | **0.41142** |
| isobutanol from xylose | 5 : 6 | **0.41142** |

They are *the same number*, to five places, because the carbon balance per carbon is identical —
1 glucose (C6) → 1 isobutanol (C4) + 2 CO₂, and 6 xylose (C30) → 5 isobutanol (C20) + 10 CO₂.
There is no mix-up; there is a coincidence that is not a coincidence. The paper's "410" for
glucose is the rounding that is slightly off, not the "411".

**PLAN.md's 0.411 g/g is correct and the bound check stands.** Two things follow:

* The benchmark should record the substrate explicitly anyway — the agent is right that a scraper
  reading `0.51` or `0.41` without its substrate will silently pool hexose and pentose bases, and
  the corpus does apply 0.51 g/g to xylose in several papers.
* **For DUET specifically this is useful rather than neutral.** The programme's substrate
  partition is C5 → isobutanol, and the mass-yield ceiling from xylose is identical to glucose.
  Whatever the case for the xylose route is, it is not a yield penalty.

## 4. Statements that are directionally right and overstated

The most common outcome, and the most useful one — 16 of 41. The corrections worth acting on:

* **BM-COF-004** attributes anaerobic 100%-of-theoretical isobutanol in *E. coli* to the KARI
  cofactor swap alone. The corpus is unanimous that **two** enzymes were swapped — IlvC *and*
  *L. lactis* AdhA. Its further claim that this is "the single highest-leverage part choice in the
  catalog" is actively countered for yeast: NADH-KARI variants there "did not outperform" the
  wild-type NADPH enzyme owing to reduced specific activity, and one head-to-head found
  **localization** the bigger lever at 3.8-fold. The catalog is a yeast catalog. This exercises the
  benchmark's own warning that yeast rows "must not inherit the E. coli outcome" — and the outcome
  really does not transfer.
* **BM-CMP-002** — "deletion of *PDC1* reduces ethanol formation" is contradicted as a *meaningful*
  effect by two own-result measurements: 12.6 g/L against 13 g/L wild type, because *PDC5*
  derepresses.
* **BM-CMP-001** — a framing correction with real consequences: in the isobutanol context Pdc1/Pdc5
  are **not purely competing**. Deleting both stopped isobutanol production completely, because
  they also convert KIV to isobutyraldehyde. Storing *PDC1/5/6* as `role='competing'` alone would
  misrepresent the corpus. This independently corroborates DUET's Pdc-positive requirement from a
  direction the concept note did not use.
* **BM-PATH-003** — the Ilv3 cluster type is **disputed inside the corpus**: one group writes
  [4Fe-4S], another writes [2Fe-2S] for *ILV3* specifically, and a third notes every solved
  crystal structure in the family so far is [2Fe-2S]. Record the requirement without a
  stoichiometry, or record the type as disputed with both citations.
* **BM-COF-005** — the gap is real but narrower than stated. Matrix NADPH sources are known
  *qualitatively* (Pos5, Ald4/Ald5, Idp1, Mae1, with Pos5 "considered as the main source"). What
  is missing is any **number**. Quantity, not identity, is the open gap.
* **BM-ETH-003** — "wild-type anaerobic ethanol yield in the region of 90%" conflates industrial
  process figures (92%, >90%) with laboratory wild-type physiology, which the corpus puts at
  **78%** for a reference strain in anaerobic chemostat. And it is not a constant: yield approaches
  theoretical only at near-zero growth rate, so a stored row is unusable without its dilution rate.

## 5. The negative controls held — with three near-misses outside the corpus

5 hold, 1 uncertain, **0 refuted**. The agent ran ~43 corpus regexes plus a whole-corpus
document-level co-occurrence scan and 6 recorded PubMed queries.

**BM-NEG-004** (no gene established as the mitochondrial 2-KIV carrier) survives on a narrow
margin, and the three decisive papers are *not in the corpus*:

* A 1991 study **demonstrates** that the purified yeast mitochondrial pyruvate carrier transports
  2-oxoisovalerate — right membrane, but it predates MPC1/2/3 and names only two polypeptides by
  mass, so no gene is established. The control survives on that clause alone.
* A 2017 study finds the lactate transporter **Jen1 transports 2-ketoisovalerate** — a named gene,
  but plasma-membrane. *An atlas that drops the membrane qualifier will return JEN1 and be wrong.*
  This is the most likely false-positive route for this control.
* A 2008 study is an explicit negative for the obvious candidate: α-ketoisovalerate "neither
  inhibited nor [was] transported by Oac1p."

**BM-NEG-006 is untestable from literature at all** — it is a claim about the atlas's own join
behaviour. Marking it "holds" from a corpus search would be the exact category error the control
exists to catch. It needs a unit test, not a paper.

**Still outstanding:** BM-NEG-003's `source_hint` asks for a recorded PubMed *and* Google Scholar
search. PubMed was run and recorded (isobutanol × mtDNA returns 5 irrelevant records; the
biolistic/ρ⁰/heteroplasmy query returns 0). Scholar was not — no tool for it in that session.

## 6. What the corpus structurally cannot supply

Several `source_hint`s point outside these 1,309 papers, and no amount of searching will reach
them: SGD systematic names, GO evidence codes, KEGG/MetaCyc map ids, the NCBI genetic-codes page
itself (cited by three mitochondrial entries), Bakker et al. 2001, Herzig/Bricker 2012, and
Steele/Fox 1996 — the ARG8ᵐ origin paper, present only as a reference list entry.

These are not gaps in the search. They are entries whose stated evidence level is **not reachable
from this corpus**, and a curator should either acquire the source or lower the expected level.

---

## What I recommend, in order

1. **Fix BM-PATH-007.** It is the only defect that makes the set unpassable, and it would have been
   blamed on the atlas.
2. **Split the compound rows** — BM-MIT-006 above all, but BM-CMP-002, BM-PATH-006 and BM-TOL-003
   are all several claims wearing one verdict. A compound row cannot be scored.
3. **Flip `verified` on the 17 supported entries**, once you have read the quotes. That is a
   curator act and I have not touched it.
4. **Record the 16 overstatements as the weaker wording** the corpus actually supports. The drafts
   propose specific replacements for the important ones.
5. Leave BM-NEG-006 as a unit test to be written, not a row to be verified.

Nothing in `data/` has changed. The drafts carry no `confidence` value and nothing is marked
`verified`, by design — L.5 reserves both for a human.
