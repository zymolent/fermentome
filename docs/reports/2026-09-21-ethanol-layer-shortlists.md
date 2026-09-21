# The ethanol layer's seven slots, shortlisted — and the budget that cannot be spent

2026-09-21. Six agents, one per slot (slots 3 and 4 share an agent because they share criterion
E4). Drafts in `docs/drafts/ethanol/`. **203 quotes re-resolved exact in their sources, 0 absent,
0 spliced.**

Every slot now has its three candidates, with what each one *lacks* stated as plainly as what it
offers — the slots document is emphatic that a shortlist arguing only in favour is "three advocacy
notes". Two slots deliberately propose fewer than three rather than pad.

**Two findings dominate, and neither is about any individual paper.**

---

## 1. The layer is about a third fillable

The 150-publication cap was set as a *ceiling*, to stop the broadest criterion eating the layer.
The actual constraint turns out to be the opposite — under-supply, in every slot:

| criterion | slot | budget | readable pool | realistic admissible |
|---|---|---|---|---|
| E5 redox shuttle | 6 | 45 | 129 | **15–25**, under 10 compartment-resolved |
| E6 industrial performance | 7 | 25 | 143 | **6–10**, of which 2–3 test causality for ethanol |
| E1 pdc-minus | 2 | 25 | 16 | **~6** load-bearing |
| E2 performance ceiling | 5 | 20 | 209 | **12–15** with internally consistent records |
| E3 baseline physiology | 1 | 20 | 91 | **~5** at bioreactor/carbon-balance standard |
| E4 stress | 3+4 | 15 | 8 | **2** from the pool |
| | | **150** | 597 | **≈45–65** |

The slots doc already says what to do with that: *"an unspent share is not reallocated
automatically — it is reported, because 'we found fewer admissible papers than expected' is a
finding about the literature, not slack to consume."* Every agent independently recommended
reporting rather than padding. **The honest phase-2 deliverable is a half-filled layer with a
written account of why**, not 150 records.

### The sharpest instance

Slot 6 exists because *"we currently have no transcriptomic anchor for matrix redox at all."*
Across 129 readable E5 candidates: 43 mention one core matrix-redox term, 18 mention two, only 4
say "mitochondrial/matrix NADPH", and about a dozen of the 18 use Pos5 as a *cytosolic* tool.

**Zero papers measure a matrix NAD(P)H pool or ratio in living *S. cerevisiae* under a named
condition.** The benchmark pass reached the same place independently — BM-COF-005's gap is
*"quantity, not identity"*. Two agents, different tasks, same conclusion.

So the atlas has no anchor for matrix redox because **the literature has none**. That belongs in
`knowledge_gap`, not in an unspent budget line, and it is a direct argument for the mito-roGFP
measurement one corpus protocol describes.

---

## 2. The criterion tagging is misrouting the best papers

Every slot found it, independently, and I confirmed the specific cases against the database:

| paper | tagged | should be |
|---|---|---|
| four Delft anaerobic glucose-limited chemostat studies | **E2** | E3 — one runs D = 0.05/0.1/0.25 h⁻¹ *with transcriptome data* |
| `10.1186/s13068-019-1486-8` — the full E1 cost ledger inside an isobutanol strain | **E3+E5** | E1 |
| `10.1016/j.meteno.2016.01.002` — Milne's *pdc1,5,6Δ MTH1ΔT* chassis with the mass balance | **none** | E1 |
| three ethanol-stress mechanism papers | E3, E5, E5 | E4 |

This inverts the slot-1 verdict. "Is 20 fillable at chemostat standard? No — the pool has exactly
one chemostat study, aerobic, on ethanol." But **the papers the slot wants are in the corpus**,
filed under E2. Slot 3+4 puts it plainly: a corpus sweep found 41 ethanol-stress documents with
the best mechanism papers under E2/E3/E5/E6 — *"that's routing, not literature."*

There is off-target contamination too. The slot-7 agent judged **47 of 143 E6 candidates not
substantially about *S. cerevisiae*** — the tag pulled in *Pichia*, *Yarrowia*, and several plant
genomics papers (hemp BES1, maize ZmICE1, a sugarcane CMS study). My own cruder check — fewer than
three mentions of *S. cerevisiae* anywhere in the text — puts a floor of 13% on E6 and 10–25%
across the other pools. The two measures disagree because they measure different things; the
stricter read is the one a curator would apply.

**Recommendation: re-tag before spending any budget.** A shortlist drawn from a mis-routed pool
is a careful choice among the wrong candidates, and five of the six agents hit this.

---

## 3. Ethanol Red — the proxy — is essentially uncharacterised here

Slot 7 rests on Ethanol Red standing in for the owner's real chassis. The corpus:

* **57 of 1,311 documents** name Ethanol Red / Lesaffre / Fermentis; **9** are in the E6 pool
* **1** sequences it — and usefully: reads `SRR2002842`, assembly `JWJK00000000`, a *second
  independent* ER genome to cross-check `GCA_029255905.1`
* **0** test why it is ethanol-tolerant or high-yielding

The only quantitative performance claim in the whole corpus is a passing *"able to produce ethanol
titers of up to 18 %"* in an introduction, with no conditions. And the same paper uses Ethanol Red
as the **inferior** parent, because its acetic-acid tolerance is low — a direct caution against
treating the proxy as a general robustness reference. No breeding history, pedigree, ploidy or
karyotype appears anywhere; no matched ER-versus-CEN.PK ethanol comparison exists.

That is not a reason to drop the proxy. It is a reason to hold slot 7's expectations exactly where
the slots doc put them — *"a set of contributing loci with modest individual effects, not a gene
list"* — and to note that **sequencing the owner's own strain removes the limitation entirely**.

---

## 4. Things worth acting on regardless of which candidates you pick

**One paper breaks the L3 transfer cap on its own terms.** PMID 30301737 — RNA-seq of ethanol
*and isobutanol* and 1-butanol, three strains, aerobic *and* anaerobic, raw reads at `GSE118069`.
E4 exists to capture mechanisms that might transfer from ethanol to C4, and transfer is capped at
L3 unless demonstrated for isobutanol. This paper demonstrates it. It is the single most valuable
candidate surfaced across all six slots.

**Two extraction hazards to wire in before curation opens:**
* **% v/v and % w/v are misused in abstracts whose bodies use the other** — including two of the
  three slot-5 candidates. Extraction must key on body tables, not abstracts.
* At least one paper reports an isobutanol tolerance result with a duration (24 h) and **no stated
  concentration**, so it cannot be entered as a measurement at all.

**Acute shock is structurally rarer than adapted growth.** One true acute-shock design in the E4
pool, two more in the whole corpus; the field studies tolerance as growth or evolution. The plan
forbids merging slots 3 and 4, and that rule is what made the asymmetry visible.

**The ceiling number for calibration:** Ethanol Red at **149.7 ± 2.94 g/L, 0.49 g/g, 0.90 g/L/h**,
as an in-batch triplicate control on 35% w/v glucose; best in pool is 158.1 g/L from a hybrid in
the same batch. The owner's ~120 g/L chassis sits below the published ceiling.

**The Pdc dual role, confirmed from two directions.** Phenotype: *pdc1Δ pdc5Δ* "stopped isobutanol
biosynthesis completely". Enzyme assay: a *pdc1Δ pdc5Δ pdc6Δ* triple retains only 8.66 ± 0.41
mU/mg KIV-decarboxylase activity against 38.73 ± 6.24 in wild type — ~78% lost — and *ARO10*
overexpression restores it **without** restoring pyruvate decarboxylation, so the two activities
are separable in principle. Caveat: both from the same lab lineage, and nobody separates the Pdc1
from the Pdc5 contribution.

---

## 5. What the loader now enforces

`fermdb literature ethanol status` reports the slots against the accepted budget, names any
criterion whose readable pool is smaller than its share, and prints the unspent report. `admit`
refuses an admission that names no criterion, a paper outside the ethanol tier, one that never
came through discovery, a criterion at its ceiling, or the layer at its cap — and for E5 applies
the content check PLAN.md singles out.

**It was tested against this shortlist and refused one of its own candidates.** The CEN.PK
mitochondrial-proteome paper mentions none of ADH3, Pos5, a shuttle or matrix NAD(P)H anywhere in
its full text, so it cannot be admitted under E5 — independently confirming the agent's own flag
on it. That is the validator doing its job on real data the day it was written.

It also found a bug in itself: an earlier version refused that paper as `wrong_tier`, because 103
publications carry screening rows in **both** tiers and the query took `LIMIT 1` with no ordering.
Fixed, with a regression test built from the real dual-tier case.

---

## 6. Still the owner's

* **The picks.** Three candidates per slot, seven slots. The agents shortlist; they do not choose.
* **Re-tagging** — §2. I have not moved any `admitted_criterion`; that changes which pool a future
  shortlist draws from, which is a curation decision.
* **PLAN.md's phase-2 acceptance still reads "E1–E5"** while E6 carries a 25-paper budget you
  accepted, the schema permits it, and 279 records are tagged under it. The module implements
  E1–E6 and prints the discrepancy on every status run rather than resolving it silently.
* **The manual download queue** — 52 more E1 and 15 more E4 papers need institutional access.
  Without them those two budgets are unspendable by construction.
