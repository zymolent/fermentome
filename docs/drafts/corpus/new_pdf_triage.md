# The 128 new PDFs: what they actually add

2026-09-21. Triage of `D:/Agentic/bifserver-works/literatures/pdf_included` against PLAN.md
B.1–B.3.6 and the seven ethanol slots.

**DRAFT.** Nothing accepted, verified or enqueued. Nothing written under `data/` or to the
database; the database was opened read-only with `mode=ro`. Source directory treated as
read-only throughout. Per-DOI calls in `new_pdf_triage.yaml`.

---

## 0. Three corrections before the findings

**There are 127 papers, not 128.** The directory holds 127 PDFs and `_manifest.csv` holds 127
data rows — 128 *lines*, including the header. There is no 128th paper.

**Three of the 127 PDFs are the wrong document.** Not a wrong version — a different paper
entirely. Each was opened and read:

| DOI the file claims | what the file actually contains |
|---|---|
| `10.1006/mben.1999.0140` (Metab Eng, ammonium assimilation) | *Fuel* 312 (2022) 122848, magnesium thermophotovoltaic combustor flammability limits |
| `10.1007/s11274-018-2463-2` (World J Microbiol Biotechnol) | a 2009 IATP policy report, "Fueling Resistance? Antibiotics in Ethanol Production" |
| `10.1016/s1389-1723(00)80087-0` (sake-yeast ethanol tolerance) | *J Biol Chem* 266:17537–17544 (1991), Kondo & Inouye on the TIP1 cold-shock gene |

Detected by scripted title-token matching across all 127, then confirmed by reading. A 2.4%
mis-filing rate. These would extract silently into the wrong `publication_id`, and the third is
the most dangerous of the three because it *is* a yeast stress paper — an extractor would find
plausible-looking content under a DOI it does not belong to.

**Four PDFs are preprint manuscripts, not the published article**: `10.1007/s00253-021-11278-y`,
`10.1007/s00438-024-02196-5`, `10.1128/aem.00268-21`, `10.1128/aem.02068-21`. The last one makes
the risk concrete — the bioRxiv title reads "Blocking mitophagy does not improve fuel ethanol
production", the published AEM title reads "**Does Not Significantly Improve**". The hedge was
added in review. Quote-level fidelity against a stored preprint is fidelity to the wrong text.

So: **120 clean, usable, correctly-filed published PDFs.**

---

## 1. The headline nobody expected: zero new papers, 124 newly *readable* ones

| question | answer |
|---|---|
| Already in the corpus? | **127 of 127.** Every DOI already has a `publication` row and a `screening_record`. |
| Genuinely new publications? | **0.** |
| Already had stored full text? | **0.** Not one has a `fulltext_asset` with `storage_state='stored_fulltext'`. |
| Already on the manual download queue? | **127 of 127** — 114 `paywalled`, 7 `licence_forbids`, 6 `no_pdf_found`. |

This corpus adds **no discovery value whatsoever** and a large amount of **acquisition value**.
Discovery had already found every one of these papers and filed each as wanted-but-unavailable.
What arrived is the bytes.

That reframes the deliverable. The question is not "what new literature is this" but "which of
the atlas's already-identified, already-blocked papers does this unblock" — and the answer is
124 of them (127 minus the 3 mis-filed).

The 2026-09-21 shortlist report closed on exactly this constraint: *"The manual download queue —
52 more E1 and 15 more E4 papers need institutional access. Without them those two budgets are
unspendable by construction."* Section 3 below reports against that sentence directly.

---

## 2. Per-slot count table

My own call against B.1–B.3.6, not the database's existing tag.

| # | slot | criterion | budget | pool before | **this corpus adds** | strong |
|---|---|---|---|---|---|---|
| 1 | Anaerobic vs aerobic reference physiology | E3 | 20 | 91 readable, ~5 admissible | **1** | 1 |
| 2 | *pdc*-minus / Pdc-attenuated background | E1 | 25 | 16 readable, ~6 load-bearing | **0** | 0 |
| 3 | Ethanol stress, **acute shock** | E4 | 15 (with 4) | 8 readable total, 2 admissible | **2** | 2 |
| 4 | Ethanol stress, **adapted growth** | E4 | (shared) | (shared pool of 8) | **4** | 2 |
| 5 | Industrial strain under VHG | E2 | 20 | 209 readable, 12–15 consistent | **4** | 0 |
| 6 | **Mitochondrial redox shuttle** | **E5** | 45 | 129 readable, 15–25 admissible | **0** | 0 |
| 7 | Genetic basis of industrial performance | E6 | 25 | 143 readable, 6–10 admissible | **3** | 0 |

Full admission tally across all 127, including the categories that are not ethanol slots:

| admission | n |
|---|---|
| `out_of_scope` (B.3.6) | **52** |
| `isobutanol_primary` | **30** |
| `E4` | 18 — of which **6** are slot-3/4 alcohol-stress mechanisms, 6 are further redox/stress-engineering records (glycerol branch, SAGA, stress circuits), and 6 are marginal because the stressor is a hydrolysate inhibitor, acetate or oxidative rather than an alcohol |
| `pentose_C5` | **12** (+5 more as secondary) |
| `E6` | 7 |
| `E2` | 5 |
| `E3` | 2 |
| `adjacent_higher_alcohol` | 1 |
| `E1` | **0** |
| `E5` | **0** |

**52 of 127 are excluded outright by B.3.6** — SSF, CBP, hydrolysate and pretreatment
optimisation, feedstock demonstrations, strain-screening surveys, process economics,
immobilisation and separation. That is 41% of the corpus, and it is concentrated almost entirely
in the *Bioresource Technology* block, which supplies 60 of the corpus's papers and is where the
database's E2 tag has been accumulating them.

---

## 3. Does this relieve the ethanol layer's under-supply?

### Slot 6 (E5 matrix redox shuttle) — **No. It adds exactly nothing.**

This is the firm answer, and it is evidence-based rather than title-based. Every one of the 127
PDFs was scanned in full text for the E5 core vocabulary B.3.5 defines and the loader's own
admission check enforces — `ADH3`, `POS5`, "ethanol–acetaldehyde shuttle", "matrix/mitochondrial
NADPH", "matrix/mitochondrial NADH", "NADH kinase":

* **0 papers mention `POS5`.**
* **0 papers mention an ethanol–acetaldehyde shuttle.**
* **0 papers mention matrix or mitochondrial NADPH.**
* **0 papers carry two or more core terms.**
* 4 papers carry exactly one — and all four fail on inspection:
  * `10.1016/j.jbiotec.2012.01.022` — its sole `ADH3` mention states that Adh3 was **excluded**
    from the Ehrlich-pathway ADH candidate screen. A recorded negative on the E5 enzyme, which
    is worth keeping, but it is not an E5 record.
  * `10.1016/j.ymben.2005.09.007` — "NADH kinase" appears as a reaction row in an *in silico*
    stoichiometric strategy table. No measurement.
  * `10.1016/j.ymben.2023.06.009` — "mitochondrial NADH shuttle" knockouts made to **block** the
    shuttle, in *Myceliophthora thermophila*. Wrong organism, opposite direction, and CBP is
    B.3.6-excluded. A useful contrast case, not a slot filler.
  * `10.1128/aem.00268-21` — a passing citation to Aßkamp on Nde1. Also a preprint.

For scale: the existing E5 pool of 129 readable candidates had 43 papers with at least one core
term, 18 with two, and 4 naming matrix NADPH. This corpus of 127 has 4, 0 and 0. **It is
markedly less E5-dense than the pool the atlas already holds.** (Term sets are mine and not
byte-identical to the earlier pass's, so treat the comparison as indicative of magnitude — but
the zeros are zeros.)

The shortlist's conclusion therefore stands untouched and is now corroborated from a second,
independent corpus: *"the atlas has no anchor for matrix redox because the literature has
none."* Three passes — the slot-6 agent, the benchmark pass on BM-COF-005, and now this — have
reached it independently. That belongs in `knowledge_gap`, and it strengthens rather than
weakens the argument for the mito-roGFP measurement.

One caveat worth recording: 8 of the corpus's papers are tagged **E5 in the database** and not
one of them survives B.3.5. They were pulled in by surface words — "respiratory-deficient",
"mitochondria", "NADH" — including a two-page SSF note on *Candida glabrata* and a cellobiose
CBP paper. This is the same misrouting the shortlist report's §2 found, reproduced exactly.

### Slot 3 + 4 (E4 ethanol stress) — **Yes, materially. This is the corpus's one real ethanol win.**

The pool was 8 readable papers yielding 2 admissible, the thinnest in the layer. This corpus
adds **6 genuine alcohol-stress mechanism papers, 4 of them strong**, and roughly **doubles the
readable E4 pool from 8 to 14**:

**Slot 3, acute shock** — structurally the rarest design in the field (one true shock design in
the entire prior pool):

* `10.1016/j.bbagen.2025.130804` — 10% v/v severe ethanol with 6% v/v mild pretreatment;
  DUMPs/Aco1 aggregation, `hsp78Δ` and `mdj1Δ`, ROS, and respiration-deficient mutant frequency.
  A true shock design *with* a named mitochondrial mechanism and a deletion series. **Abstract
  read.**
* `10.1016/j.jprot.2019.103377` — 4 h at 10% v/v, RNA-seq **and** iTRAQ, 937 DEGs and 457 DEPs.
  Paired transcriptome and proteome on a short exposure. Database has it as E5; it is E4.
  **Abstract read.**

**Slot 4, adapted growth:**

* `10.1016/j.jbiotec.2010.06.006` — **the most valuable ethanol-tier paper in the corpus.**
  Inverse metabolic engineering, transformants enriched by serial subculture in **1%
  iso-butanol**; `INO1`, `DOG1`, `HAL1` and a truncated `MSN2` improve tolerance to **both
  iso-butanol and ethanol**, with INO1 giving higher titers and a threefold growth-rate gain
  under 10% glucose and 5% ethanol. E4 exists to hold mechanisms that *might* transfer to C4,
  capped at L3 unless demonstrated — **this paper measures the transfer rather than arguing
  it.** **Abstract read.**
* `10.1016/j.jbiotec.2007.05.010` — DNA microarray on a laboratory *and* a sake strain at 5%
  v/v, with knockout validation; tryptophan biosynthesis and tryptophan permease confer
  tolerance. **Abstract read.** Note it converges with the Sc131 proteomics paper above, which
  independently lands on tryptophan — two different labs, two decades apart, same node.
* `10.1007/s00253-020-10518-x` — Rpn4/proteasome-mediated resistance including autophagy.
* `10.1016/j.jbiosc.2017.04.012` — evolutionary engineering under ethanol triggers
  diploidization; a ploidy mechanism, which connects to the atlas's open ploidy question.

Plus `10.1016/j.ymben.2020.06.003`, a designed stress-sensing feedback circuit (glutathione and
acetate pathways under transcriptome-derived stress promoters) in a xylose-fermenting strain —
which B.3.6's amendment now treats as program literature rather than background. Database has it
as E2.

### Slot 2 (E1 *pdc*-minus) — **No. Zero.**

Not one *PDC* deletion, attenuation, promoter-replacement or `pdc1Δ pdc5Δ pdc6Δ` chassis paper.
The 52 queued E1 papers the shortlist flagged as needing institutional access are **not in this
delivery**. That budget remains unspendable by construction.

The nearest thing is `10.1016/j.ymben.2010.11.003`, minimisation of glycerol synthesis in
industrial ethanol yeast — the `GPD1`/`GPD2` compensating NADH sink that B.3.1 names explicitly.
It is E1-adjacent context, not an E1 record.

### Slots 1, 5, 7 — marginal.

Slot 1 gains one genuinely good candidate: `10.1016/j.jbiotec.2010.02.009`, thermodynamic
analysis of fermentation and anaerobic growth of baker's yeast, which is at the energy- and
carbon-balance standard the slot demands. Slot 5 gains 4, none of them a clean defined-medium
VHG ceiling record — the best, `10.1016/j.biortech.2023.129993`, clears 100 g/L but on
hydrolysate. Slot 7 gains 3, of which the IRA2 QTL paper is the only one naming a causal gene,
and B.3.6 excludes bare tolerance QTL mapping. **No Ethanol Red characterisation arrived**, so
§3 of the shortlist report is unchanged.

### Verdict

**The ethanol layer's under-supply is not relieved. One slot of seven is materially helped.**

Slot 3+4 roughly doubles and gains two papers that a curator would actually pick. Slot 6 — the
sharpest gap, with the largest budget at 45 — gains nothing, and the corpus is *less* E5-dense
than what the atlas already had. Slot 2 gains nothing. The honest phase-2 deliverable is still a
half-filled layer with a written account of why.

---

## 4. Where the real value is: phase-1 isobutanol and pentose

The ethanol framing undersells this corpus. Its centre of mass is elsewhere.

### Landmarks the plan names

**`10.1016/j.ymben.2011.02.004` — extract this first.** "Engineered ketol-acid reductoisomerase
and alcohol dehydrogenase enable anaerobic 2-methylpropan-1-ol production at theoretical yield in
*Escherichia coli*." PLAN.md B.3.5 names **"an NADH-preferring KARI variant as the
highest-priority de-risking part (G.6)"** and seeds it as a `knowledge_gap` before curation
starts. This is that variant's source paper. The plan names no landmark by author and year
anywhere, but it names this *part*, and this is it.

**`10.1016/j.ymben.2012.11.008`** — "Activating transhydrogenase and NAD kinase in combination
for improving isobutanol production." NAD kinase is the enzyme class `POS5` belongs to, tested
here as an NADPH-supply lever for an isobutanol pathway. It is bacterial and cytosolic, so it
cannot close the G.8 matrix bottleneck — but it is the closest analogue in the corpus to the
atlas's highest-priority bottleneck hypothesis, and it is a real perturbation with a titer
readout.

**`10.1016/j.ymben.2017.10.001`** — BCAA transaminases in yeast isobutanol biosynthesis. Bat1
and Bat2 are the mitochondrial/cytosolic pair, so this is compartment-resolved. **Its corrigendum
`10.1016/j.ymben.2020.04.002` is also in the corpus** — extract both or neither.

**`10.1016/j.cels.2019.10.006`** — Kuroda et al., PPP and GLN3 in **isobutanol-specific**
tolerance. Direct C4 tolerance evidence, which is what lifts E4's L3 cap, and it runs through the
pentose phosphate pathway. **Its evaluation commentary `10.1016/j.cels.2020.01.005` is also
here.**

**`10.1016/j.jbiotec.2022.09.012`** — isobutanol from glucose **and xylose** by overexpressing
the xylose regulator to control catabolite repression. B.3.6's amendment says the C6→C5 handover
"is a designed component and its literature is program literature, not background". This is a
paper that builds it. For DUET's substrate partition it is the single most on-target item in the
corpus.

### Extract-first list

Isobutanol-primary, ranked by what the plan says it needs:

1. `10.1016/j.ymben.2011.02.004` — NADH-preferring KARI, the named G.6 part
2. `10.1016/j.jbiotec.2022.09.012` — isobutanol on glucose + xylose, the C6/C5 handover
3. `10.1016/j.ymben.2017.10.001` + `10.1016/j.ymben.2020.04.002` — BAT1/BAT2, compartment
4. `10.1016/j.cels.2019.10.006` + `10.1016/j.cels.2020.01.005` — isobutanol-specific tolerance
5. `10.1016/j.biortech.2018.07.150` — mitochondrial Val/Ile pathway elimination in yeast
6. `10.1016/j.ymben.2012.11.008` — transhydrogenase + NAD kinase, the Pos5 analogue
7. `10.1016/j.jbiosc.2017.04.005` — PEPC + Entner–Doudoroff in yeast
8. `10.1016/j.biochi.2014.10.024` — a second KARI part, thermo/solvent-stable
9. `10.1016/j.jbiotec.2012.01.022` — Ehrlich pathway flux in yeast (and the Adh3 negative)
10. `10.1016/j.jbiotec.2020.06.017`, `10.1016/j.biortech.2017.05.197` — cofactor-engineering builds

Then the bacterial and non-yeast builds (`ymben.2011.08.004`, `ymben.2014.03.006`,
`ymben.2017.07.003`, `ymben.2020.01.004`, `enzmictec.2026.110838`, `jbiotec.2023.03.012`,
`jbiotec.2024.07.014`, `biortech.2018.03.081`, `biortech.2019.122104`, `jbiosc.2012.02.029`), the
reviews (`s00253-023-12821-9`, `cbpa.2013.03.036`, `copbio.2014.09.004`, `ymben.2014.07.007`,
`biortech.2012.09.104`), and the biosensor part (`ymben.2019.08.015`).

Two corpus hygiene notes: `10.1016/j.jbiosc.2017.01.010` is a **corrigendum whose original
article is not in this corpus**, and `10.1016/j.cels.2020.01.005` is a one-page commentary. Both
are near-worthless alone.

### Pentose / C5 — 12 primary, 17 touching

This is the **largest genuinely new contribution**, and it is new for a structural reason:
pentose utilisation was admitted to scope only on **2026-09-20** by the B.3.6 amendment, after
the ethanol layer and its shortlists were built. There is no pentose slot, no pentose budget, and
no prior shortlist pass over this material. The corpus supplies a substantial starting set.

Highest value, because each records a **cofactor-preference change** — which B.3.6 says must be
captured "because it is a redox claim and therefore interacts with E5":

* `10.1016/j.biortech.2011.06.058` — XR coenzyme preference altered
* `10.1016/j.jbiotec.2007.04.019` — protein-engineered NADP⁺-dependent XDH
* `10.1016/j.jbiotec.2011.06.005` — NADH-preferring XR
* `10.1016/j.ymben.2011.12.001` — non-oxidative PPP overproduction **plus** `COX4` deletion
  removing respiration, then evolution with an NADP⁺-preferring XDH. The one paper here that
  puts the pentose route and respiratory redox in the same experiment. **Abstract read.**
* `10.1016/j.biortech.2025.132921` — four-substrate co-fermentation (glycerol, xylose, acetate,
  glucose) with `NDE1`/`NDE2` replaced by an acetylating acetaldehyde dehydrogenase. Explicit
  mitochondrial NADH-routing surgery. **Abstract read.**

MIXED-regime co-fermentation records, which C.5 was amended to hold and currently models badly:
`10.1016/j.biortech.2010.03.129`, `10.1016/j.biortech.2013.09.082`.

Glucose repression and carbon-programmed switching — B.3.6's named area, and DUET's automatic
inducer-free handover: `10.1016/j.jbiotec.2022.09.012` (also isobutanol),
`10.1016/j.jbiosc.2012.02.029` (also isobutanol), `10.1007/s10482-006-9085-7` (review covering
`MIG1`/`HXK2`).

Route surveys and XI-route records: `10.1007/10_2007_057`, `10.1016/j.jbiosc.2015.10.013`,
`10.1016/j.biortech.2008.11.047`, `10.1016/s1567-1356(03)00146-6`.

---

## 5. Things to fix before any of this is curated

1. **Quarantine the 3 content-mismatched PDFs** and re-acquire. Do not let an extractor near
   them. A checksum-and-title gate on ingest would have caught all three; there is no such gate.
2. **Flag the 4 preprint PDFs** as `version: preprint`. The mitophagy title change proves the
   text differs from the record of record, and the atlas quotes verbatim.
3. **Re-tag before spending budget.** 8 papers are E5 in the database and none is admissible
   under B.3.5; 2 are isobutanol-tier and are an SSF tequila paper and a 2-butanol paper. The
   shortlist report already recommended re-tagging and explicitly left it as the owner's
   decision — this corpus is further evidence for it, not a new argument.
4. **52 of 127 are B.3.6-excluded.** If they are extracted because the bytes are now available,
   the ethanol layer floods with precisely the material the cap exists to keep out. The bytes
   arriving does not change the admission test.

---

## 6. Still the owner's

* Every call in `new_pdf_triage.yaml` is a proposal. No `admitted_criterion` was moved, no
  screening row touched, no curation proposal enqueued, no extraction run.
* 15 of 127 PDFs were opened and their abstracts read; the `basis` field records `title`,
  `title+fulltext_term_scan` or `abstract_read` for every paper, and no claim here rests on
  content that was not actually read or scripted.
* The E5 zero-count is the load-bearing finding and the one most worth re-checking
  independently, because it decides whether slot 6's 45-record budget stays unspent.
