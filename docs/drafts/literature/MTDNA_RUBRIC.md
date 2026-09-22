# The mtDNA corpus needs a second rubric, and the numbers say why

**Status:** a finding and a proposed rubric. Nothing has been installed or re-screened.
**Date:** 2026-09-22

## What happened

`fermlit`'s classifier had already screened 3,856 papers before any of today's work, and 2,990 of
its verdicts apply to publications this atlas holds. Free, instant, and covering more than half
the corpus — so the obvious move was to install them.

A twelve-row hand sample stopped that. Two were wrong in the same direction:

| title | verdict | stated reason |
|---|---|---|
| The mitochondrial alcohol dehydrogenase **Adh3p** is involved in a redox shuttle in *S. cerevisiae* | `borderline` | "no mention of alcohol production" |
| Mutations in the Yeast **Cox12** Subunit Severely Compromise the Activity of Mitochondrial Complex IV | `exclude` | "no link to alcohol production" |

Adh3 is the first enzyme in the DUET architecture. COX loci are where this project's mtDNA
insertions go — phase 0 closed on `cox3::ARG8m`, and the route enumerator's own chassis gate warns
that "an mtDNA insert behind a COX leader displaces that gene".

## It is systematic, and it is large

Verdicts on the 2,990, grouped by the query family that found each paper:

| family | excluded | n |
|---|---:|---:|
| `mtdna_methods_yeast` | **96%** | 820 / 851 |
| `mtdna_engineering_yeast` | **93%** | 554 / 595 |
| `ethanol_mitochondria_yeast` | 54% | 174 / 325 |
| `isobutanol_all` | 71% | 482 / 677 |
| `ethanol_scerevisiae_prod_ferm_tol` | 21% | 148 / 705 |
| `isobutanol_yeast` | 18% | 21 / 115 |

Of the 1,474 mitochondrial-tier exclusions, **1,006 (68%) name a core mitochondrial or mtDNA term
in the title alone**. A random twelve of those:

> Toward a Quadruplet Codon Mitochondrial Genetic Code · Homologous gene targeting by biolistic
> transformation · Use of lycorine and DAPI staining to differentiate between rho0 and rho− cells ·
> Respiratory repression and the stability of the mitochondrial genome · Introduction of
> chloramphenicol resistance into the modified mouse mitochondrial genome · Mitochondrial genome
> maintenance: roles for nuclear non-homologous end-joining proteins · Yeast mitochondria: an
> overview of mitochondrial biology

Four of those seven are directly load-bearing here: the quadruplet-codon paper speaks to the
recoder that phase 0 just closed on, lycorine/DAPI is a `rho_status` assay for the chassis profile,
chloramphenicol-in-mouse-mtDNA is the heterologous-mtDNA-marker question ARG8m answers for yeast,
and biolistics is the only delivery route mitochondrial transformation has.

## The classifier is not broken

Its rubric, quoted from `fermlit/screen.py`:

> Is this about making ethanol, n-butanol or isobutanol with a microorganism, or about engineering
> an organism to do so?

A biolistic transformation protocol is honestly neither. The model is answering its own question
correctly; the question is simply not the one phase 1b asks. That distinction matters, because
"the classifier is wrong" invites replacing the model, and the model is fine. What is missing is a
second question.

This is the same shape as the mis-attribution the corroboration gate was built for: a mechanism
working exactly as designed, applied one step outside the scope it was designed for, producing
confident output that is wrong in a way no distributional check would catch.

## The proposed second rubric

Run **only** over papers carrying a mitochondrial or mtDNA family, in addition to the existing
pass rather than instead of it. A paper may be irrelevant to alcohol production and essential to
this project.

> Does this paper help someone **engineer the yeast mitochondrion or its genome**?
>
> Answer `include` if it reports or enables any of:
> * getting DNA into mitochondria, or out — biolistic transformation, conjugation, allotopic
>   expression, synthetic import, mitoTALEN/mitoZFN, base editing of mtDNA;
> * the mitochondrial genetic code, codon usage, or translation — the CUN/ATA reassignments, tRNA
>   complement, translational activators, mitoribosomes;
> * mtDNA state, maintenance or inheritance — rho+/rho0/rho−, petites, heteroplasmy and its
>   segregation, nucleoids, recombination, copy number, karyogamy/kar1 cytoduction;
> * mitochondrial protein import — presequences, TOM/TIM, processing peptidases, matrix targeting
>   of a heterologous enzyme;
> * assays that measure any of the above — respiratory competence, rho0 discrimination, mtDNA
>   copy number, submitochondrial localisation or fractionation;
> * mitochondrial redox or cofactor pools — NAD(P)H shuttles, transhydrogenase-like activity,
>   Adh3, Pos5, compartment-specific measurement.
>
> Answer `include` even where the organism is not *S. cerevisiae*, if the **method** transfers;
> say so in the reason. Mammalian and plant mtDNA engineering papers are frequently the only
> record of a technique.
>
> Answer `exclude` for mitochondrial **disease** or clinical genetics with no engineering method,
> for mitochondrial cell biology with no manipulable handle, and for papers where "mitochondria"
> appears only as a cell-fractionation control.
>
> `borderline` where a method is present but its transfer to yeast mtDNA is genuinely unclear.

The organism clause is the one to get right: it is deliberately opposite to the first rubric's
instinct, and it is where most of the value sits. The chloramphenicol-in-mouse-mtDNA paper is not
about yeast and not about alcohol, and it is a direct precedent for putting a selectable marker
into a mitochondrial genome.

## What to do with the 2,990 meanwhile

Split, not filtered:

* `2026-09-22-fermlit-verdicts-safe.tsv` — **1,303** verdicts on publications with no
  mitochondrial or mtDNA family. Installable as they stand; working corpus 4,762 → 4,145.
* `2026-09-22-fermlit-verdicts.tsv` — the full 2,990, including the **1,687** withheld. Kept so
  the withheld verdicts can be re-read rather than re-derived.

Both are model verdicts: `decided_by_kind = model`, confidence `unverified`, and the loader will
not let them overwrite any of the 568 the owner reached by opening the PDF.

## The same gap is about to be reproduced

The screening run now in flight over the 1,606 publications `fermlit` has never seen uses the
**same rubric**. Roughly 1,000 of those carry an mtDNA family. Its verdicts on them will need the
same treatment, and the fix is a second rubric rather than a better model.
