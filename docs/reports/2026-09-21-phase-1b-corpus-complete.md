# The phase-1b corpus, finished — and what it says about strategy E

2026-09-21, Wave 2 of the unattended plan. Five agents, one per remaining content type in
`MITOCHONDRIAL_PROGRAM.md` §3. With the activator map and precedents table done earlier the same
day, **all eight of §3's content types now exist.**

Drafts are in `docs/drafts/mitochondria/`. **230 quotes re-resolved exact in their real sources,
0 fabricated, 0 spliced.** Nothing has been promoted to `data/` except two corrections to files
already there (§6).

**The headline is not what the programme expected.** Strategy E was conceived as the escalation
path for when strategy C proves import-limited. The corpus now says C is *unlikely to be
import-limited*, and that E has a stability problem nobody has measured. Those are two independent
findings from two different agents, and they point the same way.

---

## 1. Strategy C is probably not import-limited — the first evidence against needing E

`MITOCHONDRIAL_PROGRAM.md` §1 sets the trigger precisely:

> "E becomes justified precisely when **C works but is import-limited** — which is a measurable
> condition, not a guess."

The allotopic table is the mirror image of that question: 16 relocation attempts, and **every
import failure in the corpus is a failure to translocate a transmembrane helix.** The ordering is
monotone in hydrophobicity:

| protein | TM helices | outcome |
|---|---|---|
| **Var1** | 0 — soluble matrix | **full rescue**, codon change + COX4 presequence, nothing else |
| bI4 | 0 — soluble maturase | full rescue |
| Atp8 | 1 | full rescue |
| Cox2 | 2 | partial, and only with hydrophobicity-lowering substitutions |
| Atp9 | 2 (proteolipid) | fails outright; stalls at the inner membrane, degraded by i-AAA |
| cytochrome b | 8 | "entirely unsuccessful", in any organism |

The decisive manipulation is a chimera: replacing **one** transmembrane helix with a less
hydrophobic one converted an undetectable, IMS-degraded protein into a processed one. That turns
a correlation into a causal handle.

**DUET's KDC and ADH are soluble matrix enzymes with no transmembrane helices.** Var1 — the only
soluble mtDNA-encoded product — relocated to full function with nothing but recoding and the COX4
presequence, which is specifically the MTS that *fails* for hydrophobic cargo. Every mechanism
invoked for the failures (i-AAA degradation in the IMS, stop-transfer versus conservative sorting,
precursor held by PAM/Hsp70) requires a helix to stall on.

So the trigger condition for escalating to E is unlikely to fire. **This is a prediction, not a
measurement** — and it should be tested by the strategy-C instrumentation `ISOBUTANOL_PROGRAM.md`
already mandates. It is exactly the kind of answer the atlas was built to produce.

Import proxies, for when a number is wanted: 6%→12% of WT Cox2p for the original allotopic
construct, rising to **85%** after two residue changes. Expression tuning bought ~40%; changing
two residues bought ~7-fold. *If C ever is import-limited, screen enzyme variants, not promoters.*

One honest counterweight: where mitochondrially-made and allotopic Cox2 competed in one cell, the
assembled enzyme was built overwhelmingly from the mitochondrially-made copy. Internal synthesis
beats import in direct competition — but only for cargo whose assembly machinery co-evolved with
mitochondrial synthesis, which a heterologous decarboxylase is not.

## 2. Strategy E's insert has never been shown to stay

§5's question 5 — *"Does the insert stay?"* — has a worse answer than "unknown":

* **Zero papers have ever followed a heterologous mtDNA ORF over generations.** Not sfGFPm, not
  mtnLuc, not GFPβ1-10, under selection or without.
* **Both neutral-site precedents do not measure retention at all.** "Stable" appears in them only
  about nanoluciferase's denaturation and sfGFP's folding. They are not weak stability evidence;
  they are not stability evidence. (This upgrades a note in `heterologous_orf_precedents.yaml`
  from inference to checked fact.)
* The CRISPR-inserted element is **undetectable within ~30–40 generations** without selection,
  homoplasmy never reached. Production is non-selective and 30–40 generations is a seed train.
* Background **ρ⁻ formation runs 0.1–1% per generation on glucose**, independent of any insert —
  compounding over a seed train into the loss of precisely the copy-number advantage §1 sells.
* A cider strain in wort for **150 generations** lost the whole mitochondrial genome in one clone
  of three, and cut 82 kb to 5 kb in two others.

### The strongest argument yet for the intergenic site

One paper, one cargo, one medium, one variable:

* at a **neutral site**, ARG8 is *not* counter-selected;
* **displacing an OXPHOS gene**, it is purged — >80% of fifth-generation colonies carry WT mtDNA
  only, **on glucose, where respiration is dispensable**.

So `respiration_retained: false` is a **stability** field, not only a metabolic cost. That is a
second and independent argument for `intergenic_upstream_COX2` which `activator_map.yaml` does not
currently make.

### Two design rules that did not exist this morning

* **96 bp direct repeats delete ~160× faster in mtDNA than the same geometry in the nucleus** —
  and homology arms *are* direct repeats. The §2.2 recoder should report internal repeats shared
  with an insert's flanks. One observed insert deleted through a 44-nt sequence it shared with a
  flank ~600 nt away.
* A second neutral site exists 3′ of *VAR1*, but its duplicated ATP9 promoter produced **~60%
  ρ⁻/ρ⁰ cells**. Duplication is itself a cost — which puts pPT24's duplicated *COX2* 5′ UTR under
  the same question. **Nobody has reported a ρ⁻ fraction for a pPT24 strain.** Cheap, specific,
  and worth doing before committing to that site.

## 3. The ρ⁰ finding that reframes M3

M3's answer treats respiration as the thing at stake. The corpus says the causal variable is
**membrane potential**, not respiration, and the two come apart:

* ρ⁰ cells hold only a residual ΔΨ, by *hydrolysing* glycolytic ATP through a reversed
  F1-ATPase — a permanent yield tax nobody in the corpus costs.
* Matrix protein import depends on ΔΨ, and **Fe-S cluster biogenesis depends on import.**
* The controls are unusually clean: *CAT5*/*RIP1*/*COX4* deletions abolish respiration with mtDNA
  intact and cause **no** comparable defect; a ρ⁰ strain carrying *ATP1-111* (higher ΔΨ, still
  non-respiring) shows no crisis.

**Why this matters to the isobutanol pathway specifically:** Ilv3 (DHAD) is an Fe-S enzyme in the
matrix — the same compartment as the lesion. So "we ferment anaerobically, so respiration is free"
answers the wrong half of the question. Neither `MITOCHONDRIAL_PROGRAM.md` nor OPEN_QUESTIONS M3
currently draws the ΔΨ/respiration distinction.

**But Ilv3 in a ρ⁰ strain has never been measured.** Every ρ⁰ Fe-S result in the corpus scores
*cytosolic* clients, because the assay was chromosome instability. Mechanistically strong,
empirically open, and settleable by one cheap experiment: a DHAD assay, or a DHIV/2-KIV ratio, in
a ρ⁰ versus isogenic ρ⁺ pair. If ΔΨ is the variable, *ATP1-111* is an already-published mitigation
nobody has tested on matrix clients.

### An unasked-for finding that may matter as much

**Ilv5 — the KARI of the same valine branch — is an mtDNA nucleoid packaging protein.** One paper
replaced matrix Ilv5 with a mitochondrially-targeted bacterial KARI and got a **166-fold petite
frequency** against a 1–5% baseline, then abandoned the strain as an "irreversible fitness
defect". The cytosolic version of the same swap did not do it. A second isobutanol paper looked
for the effect and did not find it; both are recorded, neither resolved.

**Recommendation: make petite frequency a standard readout on every matrix-targeted DUET
construct.** It is a plate assay, and here it caught a fatal defect that titre alone would not
have.

## 4. The industrial polyploid: ρ⁰ is precedented, the mating is not

OPEN_QUESTIONS M2 carries "in a polyploid industrial isolate it is not routine ⚠". The corpus
splits that claim:

* **Making the ρ⁰ derivative is precedented** — industrial allopolyploid *lager* strains were made
  ρ⁰ by ethidium bromide and used as *kar1-1* cytoduction recipients. That is the strategy-E
  architecture, executed on an industrial polyploid.
* **The undocumented cost is the MAT locus.** Lager yeasts carry both *MATa* and *MATα*, so they
  do not mate — and cytoduction *is* a mating. The locus had to be homozygosed first, with a
  mating-type-switching plasmid. This stacks with the Fox protocol's requirement that the acceptor
  be ρ⁰ *and* mating type A. **A MAT-heterozygous industrial polyploid needs its nuclear genome
  engineered before any mitochondrial work begins**, and M2 does not price that.
* EtBr is a nuclear mutagen, and the published answer is **three independent ρ⁰ isolates**, checked
  to behave alike. For a strain whose value *is* its nuclear genome, that is a minimum. The same
  study found significantly more variance among polyploid ρ⁰ replicates than haploid ones.

A non-mutagenic alternative exists and is the only one in the corpus: matrix-targeted Cas9 with a
gRNA against *ATP8*. Described as an increased *rate* of mtDNA-depleted cells rather than a clean
conversion — a lead, not a protocol, but the right lead for a strain that cannot absorb random
nuclear mutation.

## 5. Corrections to the programme's own documents

| document | claim | what the corpus says |
|---|---|---|
| §2.4 | markers are one field | **Two tiers.** A *nuclear* marker (*LEU2*) selects the bombardment; the mitochondrial event is **screened**, never selected. §2.4 omits the reagent without which nothing grows. Schema wants `nuclear_selection_marker` + `mitochondrial_screen`. |
| §2.4 | "the classical *COX2*/*COX3* approach" | **COX2-only** in this corpus. Every worked marker-rescue example is COX2; COX3 appears only as an ARG8ᵐ replacement target, the opposite configuration. Keep the ⚠. |
| §2.4 | homoplasmy is a screening problem | It is **waited out**: "about a dozen mitotic divisions", "20–40 generations", "two passages" — three independent labs. |
| §3 | transformation records ~30–60 papers | **15.** The rest of the 43 keyword hits are plant/algal chloroplast work or reviews. Not fillable from this corpus, and probably not at all — the technique is practised by a handful of groups. |
| §1 | "~50–200 mtDNA copies per cell ⚠" | Two independent challenges: 50–100 per *diploid*, and a population survey with a median of **18** per haploid nuclear genome. Worth reconciling; the copy-number argument for E rests on it. |
| §2.3 | Arg8ᵐ is the one precedent | Seven now, including **Cox6 and the [2Fe-2S] Rieske protein Rip1** — see §6. |

**The transformation efficiency number, since the programme wanted one:** exactly one exists in
1,309 papers — ~0.1% of tested colonies, and it is a *screening yield*, not a transformation
frequency. 14 of 15 papers report no efficiency at all. Throughput is a handful of constructs,
as §2.4 assumed, but the corpus cannot tell you how small a handful.

## 6. Two corrections to data already committed

Both found by running the draft gate against `data/` itself, which had not been done before.

* **`activator_map.yaml` carried a spliced quote.** v1 wrote the COX1 evidence with " ... "
  standing in for "the largest subunit of the cytochrome c oxidase complex,". An elided quote
  cannot be re-resolved at an offset, so it is not evidence — the same rule that rejected an
  agent's spliced quote earlier today, applied to this file's own. Desplied and verified.
* **`heterologous_orf_precedents.yaml` contained a paraphrase inside quotation marks, written by
  me yesterday.** The row read `recoded "for the mitochondrial genetic code"`; the source says
  **"compatible with"**. It survived the first pass because only the longer neighbouring span was
  submitted to `verify_span` — the short fragment was never checked. *Verify every fragment, not
  every record.*
* **Two precedents were missing**, and the reason is instructive: their paper is titled *"Allotopic
  expression of COX6"*, and allotopic normally means the opposite direction. A search for
  strategy-E precedents skips it on the title. The abstract's first line is the correction:
  *"Relocation of COX6 from nuclear to the mitochondrial genome"*. **Title-level filtering is how
  this corpus hides things.**

That second addition matters beyond bookkeeping: **Rip1 carries a [2Fe-2S] cluster and was made
from mtDNA.** This file's own headline gap — "can the matrix load a cofactor into a protein its
own ribosomes just made" — is therefore half answered, and answered in the direction that helps,
since Ilv3 is itself an Fe-S enzyme. What remains genuinely unprecedented is narrower: a
**thiamine**-dependent catalyst and an obligate **homotetramer**. DUET's KDC is both.

## 7. Where this leaves strategy E

Not excluded — better characterised, and the characterisation is unflattering:

* its **trigger condition is unlikely to fire** (§1);
* its **central unknown is now stability, not folding** (§2), and stability is unmeasured for any
  heterologous ORF;
* its **chassis route costs a nuclear MAT edit** before any mitochondrial work (§4);
* its **cofactor risk narrowed** from "any cofactor" to TPP-and-oligomerisation (§6).

`MITOCHONDRIAL_PROGRAM.md` §5 anticipated exactly this outcome and called it a win:

> "A defensible conclusion at the end of phase 3 could equally be *'strategy C first, E held in
> reserve pending an import measurement'* ... Both are wins."

The corpus now supports that first conclusion on evidence rather than on caution. **The decision
remains the owner's**, and three cheap experiments would settle most of it: a DHAD assay in a
ρ⁰/ρ⁺ pair, petite frequency on every matrix-targeted construct, and passaging an *existing*
published sfGFPm or mtnLuc strain in glucose without selection to get the first retention curve
for a heterologous mtDNA ORF that anyone has ever measured.

---

## What has not been done

The five drafts are **drafts**. Under D2 they stay in `docs/drafts/` until their quotes are
verified — which they now are — and until a human sets a `confidence` on each record, which L.5
reserves and I have not touched. Promoting them into `data/mitochondria/` is a curation act and
it is yours.
