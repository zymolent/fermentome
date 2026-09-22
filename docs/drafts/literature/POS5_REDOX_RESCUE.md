# The matrix-redox papers were in the corpus all along, excluded, and are unreadable

**Status:** a finding. Nothing installed, nothing acquired.
**Date:** 2026-09-22

## What turned up

The mtDNA rescue pass was expected to recover mitochondrial *engineering* papers. It also
recovered something nobody was looking for: **19 papers about compartment-specific redox, none of
which carries a mitochondrial query family at all.** They were found by
`ethanol_scerevisiae_prod_ferm_tol` — the general ethanol query — and excluded by the first rubric
for the reason it excludes everything of this kind, "no link to alcohol production".

Among them, a **Pos5 cluster**:

| paper | year |
|---|---|
| Structural determinants of discrimination of NAD+ from NADH in yeast mitochondrial NADH kinase Pos5 | — |
| Mitochondrial NADH kinase, Pos5p, is required for efficient iron-sulfur cluster biogenesis | — |
| Effects of a mitochondrial mutator mutation in yeast POS5 NADH kinase on mitochondrial nucleotide pools | 2012 |
| Transcriptional response to mitochondrial NADH kinase deficiency in *S. cerevisiae* | 2009 |
| Role of mitochondrial NADH kinase and NADPH supply in the respiratory chain activity | 2011 |
| Localization of the NADH kinase in the inner membrane of yeast mitochondria | 1989 |
| Overexpression of ZWF1 and POS5 improves carotenoid biosynthesis in recombinant *S. cerevisiae* | 2015 |

and a measurement cluster:

| paper | year |
|---|---|
| Two sources of mitochondrial NADPH in the yeast *S. cerevisiae* | — |
| Ratiometric biosensors that measure mitochondrial redox state and ATP in living yeast cells | 2013 |
| Live cell imaging of mitochondrial redox state in mammalian cells and yeast | — |
| The redox environment in the mitochondrial intermembrane space is maintained separately from the matrix | 2008 |

**Pos5 is the second enzyme in the DUET architecture** — ethanol → Adh3 → matrix NADH → **Pos5** →
matrix NADPH → Ilv5. Seven papers on it sat in the corpus, excluded, because none of them makes
alcohol.

## Why this matters more than a rescue count

`docs/drafts/ethanol/PHASE2_STATUS.md` §3a has recorded the same finding on five consecutive
passes:

> No paper measures a matrix NAD(P)H pool or ratio in living *S. cerevisiae* under a named
> condition. The layer holds five records about matrix redox and not one number from inside the
> matrix.

That conclusion was reached honestly, over the *readable and included* corpus — which is exactly
the corpus these 19 had been excluded from. "No such paper is in the layer" was true. "No such
paper exists in the corpus" was never tested, because the papers that would test it had been
filtered out one stage earlier.

**Stated carefully, because it is easy to overclaim:** these are *candidates*, not an answer. A
ratiometric biosensor paper is a method for measuring mitochondrial redox state; whether any of
them reports a matrix NAD(P)H **ratio under a named fermentation condition** — which is what §3a
asks — can only be settled by reading them. What has changed is that there is now something to
read.

## The catch, and it is the whole practical problem

**All 19 have `readable = 0`.** Not one has stored full text. They are recovered into the corpus
and cannot be extracted today.

So this is an **acquisition** task, not an extraction one, and it does not compete with the
curation queue for attention — it competes for whatever the PDF-fetching pipeline's time is worth.
Until they are acquired, the rescue changes the corpus and nothing downstream of it.

## What to do

1. **Acquire these 19 first** among the rescued set. They are the highest-value unreadable papers
   the project has: seven on the DUET pathway's own second enzyme, four on the measurement §3a
   says is missing.
2. **Do not amend §3a yet.** Its statement is still accurate about the layer. Amend it if and when
   one of these is read and found to carry a matrix number under a named condition — and if none
   does, that is a stronger version of the same gap, now tested rather than assumed.
3. **Note the mechanism for future rubrics.** These were found by an ethanol query, excluded by an
   alcohol-production rubric and recovered by a redox clause. Three stages, each behaving
   correctly, and the paper only survives if the last one exists. The clause that caught them —
   "compartment-specific cofactor/redox measurement: NAD(P)H pools, transhydrogenase-like shunts,
   Adh3, Pos5" — was an extension beyond the mtDNA core, added on judgement. It earned its place.
