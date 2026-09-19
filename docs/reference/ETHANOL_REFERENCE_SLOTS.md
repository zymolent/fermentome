# The ethanol reference layer — seven slots

The ethanol layer is capped (PLAN.md B.3). Rather than let discovery fill the cap with whatever
scores highest, it is divided into **seven named slots, each answering one question the isobutanol
programme actually asks.** A study earns a slot or it is not admitted.

**Selection procedure, decided 2026-09-20 by the project owner:** once discovery has run, the
literature agent proposes **three candidates per slot**, and the owner picks one. The agent does
not choose; it shortlists. Rationale: the shortlist is cheap and better-informed than a decision
made before the corpus exists, and the pick is a scientific judgement about what the programme
needs, not a relevance score.

## The slots

| # | slot | criterion | the question it answers | why the programme needs it |
|---|---|---|---|---|
| 1 | Anaerobic vs aerobic reference physiology | E3 | What does baseline yeast physiology look like, quantitatively? | Everything else is read against it. Chemostat, defined medium, CEN.PK preferred |
| 2 | *pdc*-minus / Pdc-attenuated background | E1 | What does removing the pyruvate sink actually cost? | DUET keeps Pdc, so this is the counterfactual, not the plan — but the cost of the incumbent approach has to be on the record |
| 3 | Ethanol stress, **acute shock** | E4 | What happens on sudden exposure? | Distinct biology from slot 4 and the plan forbids merging them |
| 4 | Ethanol stress, **adapted growth** | E4 | What happens under chronic exposure? | As above, separately |
| 5 | Industrial strain under VHG | E2 | What does a high-performing fermentation look like? | The performance ceiling the programme is calibrated against. Ethanol Red or equivalent |
| 6 | **Mitochondrial redox shuttle** | **E5** | How do reducing equivalents reach the matrix? | `ADH3`, the ethanol–acetaldehyde shuttle, `POS5`. DUET's architecture runs on this and we currently have no transcriptomic anchor for matrix redox at all |
| 7 | **Genetic basis of industrial performance** | **E6** | What makes Ethanol Red hyper-producing and ethanol-tolerant compared with lab strains? | Ethanol Red is the proxy genome for the real chassis, so "what makes it good" is the most directly transferable ethanol question available |

## Slot 7 — expectations to set before the candidates arrive

Slot 7 is the owner's own question and the most likely to disappoint if framed wrongly.

* **The advantage is almost certainly polygenic**, with substantial contribution from aneuploidy
  and copy-number variation rather than a few clean causal alleles (unverified). The honest answer
  will be *a set of contributing loci with modest individual effects*, presented with effect sizes
  and evidence levels — not a gene list. Any candidate promising a single-gene explanation should
  be treated with suspicion rather than enthusiasm.
* **Ethanol Red is a Lesaffre commercial product.** Its genome is public
  (`GCA_029255905.1`, scaffold-level); its breeding history and proprietary characterisation may
  simply not be published. Expect gaps, and record them as `knowledge_gap` rows rather than
  leaving silence.
* **Part of this slot is computable, not literary.** With Ethanol Red, CEN.PK113-7D and S288C all
  in the genome set, the variants distinguishing them fall out of the comparative layer directly.
  Those are Zone H/I associations, capped at L3 unless a paper demonstrates causality by
  reconstruction — industrial and lab strains differ at very many positions and almost none are
  causal (PLAN.md W, risk 7). The literature slot exists to tell us which of those differences
  anyone has actually tested.
* **Scaffold-level assembly limits what can be claimed.** At N50 189 kb, structural variants and
  subtelomeric regions — exactly where industrial-strain adaptations are often reported
  (unverified) — are not reliably callable. Gene content and SNPs are.

## What a candidate proposal must contain

For each slot, three candidates, each with:

`pmid` · `doi` · `title` · `year` · `strain(s)` · `conditions` · `what data it actually contains`
(raw deposited? processed only? figures only?) · `accessions if any` · `why this slot` ·
`what it lacks` · `open-access status`

The last two matter most. A shortlist that only argues *for* each candidate is not a shortlist,
it is three advocacy notes — the owner is choosing between them and needs the weaknesses.

## Cap accounting — sub-budget, accepted 2026-09-20

The cap needed a sub-budget or E5 would have eaten it. E5's outer bound is **642 publications**
against a ~150 total, so without a per-criterion allocation the broadest criterion consumes the
layer and E1–E4 arrive empty. The owner accepted a sub-budget; this is the allocation, revised
from the pre-E6 proposal to give the new criterion a share:

| criterion | slot(s) | budget | why this size |
|---|---|---|---|
| **E5** redox shuttle | 6 | **45** | Load-bearing for DUET's architecture and currently unrepresented; largest share, but a seventh of its 642 outer bound |
| **E6** industrial performance | 7 | **25** | The owner's own question, and partly *computable* from the genome set rather than only read |
| **E1** competing sink | 2 | **25** | The counterfactual. Needed, but DUET keeps Pdc, so it is no longer the primary framing |
| **E2** performance ceiling | 5 | **20** | Small, authoritative set; more would be padding |
| **E3** wild-type baselines | 1 | **20** | |
| **E4** transferable mechanism | 3, 4 | **15** | Split across shock and adapted; the tightest, because ethanol-to-C4 transfer is capped at L3 anyway |
| | | **150** | |

The budget is a ceiling per criterion, not a quota to fill. An unspent share is not reallocated
automatically — it is reported, because "we found fewer admissible papers than expected" is a
finding about the literature, not slack to consume.

## Ethanol Red — accepted as the proxy, 2026-09-20

The owner accepted Ethanol Red (`GCA_029255905.1`) as the industrial proxy genome, with its
scaffold-level limitation understood. Standing consequences, to be repeated wherever a result
leans on it:

* Gene content and SNP-level comparison: usable.
* **Structural variants and subtelomeric regions: not reliably callable at N50 189 kb** — and
  those are exactly where industrial-strain adaptations are often reported (unverified). So slot 7
  will be systematically blind to one of the likelier classes of answer, and must say so rather
  than reporting absence as evidence of absence.
* Every proxy-derived conclusion is a hypothesis about the real chassis, capped at L3.
* Sequencing the owner's own strain removes the limitation entirely, and the `gene_group` layer
  means it drops in without rework. That remains the highest value-per-rupee action available.

## Cap accounting

Slots are the admission mechanism, not an addition to the cap: the ethanol layer stays at ~150
publications and ~60 measurement-bearing studies (PLAN.md B.1). Filling a slot with a second
study later means removing something, and the swap is recorded.
