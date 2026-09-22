# The model excludes beverage papers its own rubric calls ADJACENT

**Status:** verified finding. Nothing re-screened, nothing installed.
**Date:** 2026-09-22

## Not the same failure as the mtDNA one

The mtDNA finding was a **scope mismatch**: fermlit's rubric asks "is this about making alcohol
with a microorganism", a biolistic transformation protocol honestly is not, and the model answered
its own question correctly. The fix there was a second rubric, because the first one was never
pointed at that literature.

This is different, and worse. Here the rubric **explicitly covers these papers and places them in
the middle band**:

> ADJACENT (middle score) if the paper is enabling rather than about production itself:
> … Fermented beverage or food microbiology where ethanol is formed but the paper is about
> flavour, contamination or sensory quality rather than alcohol production.

ADJACENT is the 40–69 score band, which settles as `borderline` — the pile you skim. The model
restates that clause almost verbatim in its reason and then assigns `exclude` anyway.

## Measured, on both halves of the corpus

Titles matched on a beverage/flavour vocabulary (wine, beer, sake, cider, huangjiu, baijiu,
vinegar, distillation, grape, olive, cheese, sourdough, aroma, flavour, sensory, terroir …):

| corpus | beverage titles | include | borderline | exclude | excluded | settled on title alone |
|---|---:|---:|---:|---:|---:|---:|
| original 3,856 | 216 | 40 | 87 | **89** | **41.2%** | 54 |
| newly screened 1,308 | 125 | 16 | 46 | **63** | **50.4%** | 54 |

**341 papers, 152 excluded, 108 of them decided on the title without the abstract ever being
fetched.**

And the scores show it directly. The rubric assigns these the 40–69 band; where they actually
landed:

| band | n |
|---|---:|
| 0–14 certainly irrelevant | **104** |
| 15–39 probably irrelevant | **58** |
| 40–69 ADJACENT (where the rubric puts them) | 123 |
| 70+ relevant | 56 |

**162 of 341 scored below the band their own rubric assigns them.**

## Why it matters here

This is not a neutral slice. Wine, beer, sake, cider and industrial distillation are *ethanol
fermentation by yeast with real strains, real conditions and real titers* — which is phase 2's
subject. The ethanol reference layer has open slots for "industrial strain under VHG" and "genetic
basis of industrial performance", and `ethanol_scerevisiae_prod_ferm_tol` is the family carrying
most of these. The layer is currently 40 of 150 records with E2 (industrial strain) the one
criterion measurably short — 7 admitted against its own estimate of 12–15 available.

PLAN.md H.3 — *an excluded paper is a decision, not an absence* — means these are decided against
permanently, and 108 of them on a title.

## What I am not claiming

That all 152 should be included. Many genuinely are sensory or contamination studies with no
usable strain or number, and the rubric is right that they are adjacent rather than central.
`borderline` is the correct verdict for most, which is exactly the point: **borderline is a pile
somebody skims, exclude is a pile nobody opens again.**

Nor is this a bug in the model. It is the model weighting "rather than alcohol production" more
heavily than the clause's placement in ADJACENT — a reading the rubric text invites, since the
sentence ends on the disqualifying half.

## The cheap fix, and why it was not applied

Raise `--low` for this slice — the screening agent suggests 40 against the current 25 — so a
beverage title cannot be excluded on its score alone and is forced into the abstract pass. That
converts the 108 title-only exclusions into read decisions without changing the rubric at all.

Not applied here because it re-decides 341 papers, 152 of them already recorded as exclusions, and
that is a curator's call. It is also cheap: ~341 abstract-pass calls.

The sharper alternative is to fix the rubric sentence so the ADJACENT clause does not end on its
own disqualifier — but that changes the question mid-corpus and makes the halves incomparable,
which is the mistake the mtDNA rescue was careful to avoid.
