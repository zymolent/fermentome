# Provenance sweep — every quoted span in `docs/drafts/` (and `data/`) re-verified against `fulltext_asset`

**Date:** 2026-09-22 · **Scope:** read-only audit. Nothing was repaired, no draft was edited, no
`data/` file was touched, the database was opened `mode=ro`, and `fermdb extract` was not run.

## What this sweep did

Every quoted string in `docs/drafts/**` and `data/**` was re-resolved against the text that
`fermdb.extract.harness.load_source_text` returns for the attributed publication — the
`fulltext_asset` store, never a cache. Where a quote carries `char_start`/`char_end`, it was
checked with `fermdb.llm.validate.verify_span` at exactly those offsets, exact, no normalisation.
Where a quote carries no offsets (most of the corpus of quotes does not — see §4), it was checked
for byte-exact presence in the stored text, and `relocate_span` was used to report where it
actually sits.

Failures were then re-tried against every other publication named anywhere in the same file, so
that a quote sourced to a cited companion paper is named as such rather than merely rejected.

**Totals: 1,912 quotes swept.**

| classification | count |
|---|---|
| `exact` — offsets recorded and resolve exactly | 1,226 |
| present byte-exact, but the draft records **no offsets** (`not_a_span` by the brief's definition) | 655 |
| `offsets_wrong_quote_present` | **0** |
| `quote_absent_from_paper` | **3** |
| spliced quote (ellipsis inside the quoted string) | **1** |
| not verbatim — the quote was silently cleaned up | **7** |
| present only after whitespace folding (YAML/PDF line-break damage) | 2 |
| attribution missing or unresolvable at the record | 10 (all 10 resolve once the source is found) |
| `no_stored_text` | **0** |
| my extractor's artefacts (editorial prose caught between quote marks, not quotes) | 8 |

## 1. The headline

**The defect is real but it is small, and it is not the one that was feared.**

The phase-2 finding reproduces exactly: two quotes in `slot1_E3_baseline_physiology.yaml`
attributed to `doi:10.1186/1475-2859-9-16` do not occur in that paper's stored full text. Both
come from **cited companion papers by the same group**, and this sweep names them. One further
case of the same kind sits in `mitochondria/allotopic_expression.yaml`. That is **three**
mis-attributed quotes in 1,912.

**The offset half of the worry did not materialise.** `warnings/PLAN.yaml` records its offsets
against the numbered cache (`NNNNN.txt @a-b`) and **all 68 of its quotes re-resolve EXACT at those
same offsets against the `fulltext_asset` store**. That file's own header says the cache was
rebuilt from `fulltext_asset` rows using the repo's own `jats_to_text` and `pdf_to_text`, and this
sweep confirms it: for those publications the cache text and the stored text are character-identical.
`offsets_wrong_quote_present` came back **zero across the entire sweep**. The cache was not a
different text; the slot-1 failure was an attribution error, not an offset drift.

**The one promoted artifact that is affected is `data/pathways/parts_catalog.yaml`**, and not in
the way the brief anticipated — see §3.

## 2. Every `quote_absent_from_paper`, in full

### 2.1 `docs/drafts/ethanol/slot1_E3_baseline_physiology.yaml` — candidate C (2 quotes)

Candidate C is attributed throughout to `doi:10.1186/1475-2859-9-16` ("Fermentation of mixed
glucose-xylose substrates by engineered strains of *S. cerevisiae*…", 2010). Two of its 15
evidence quotes are not in that paper's stored text.

| entry | quote | attributed DOI | classification | actually from |
|---|---|---|---|---|
| `candidates[2].evidence[13]` | "Two isogenic yeast strains were derived from the laboratory strain S. cerevisiaeCEN.PK 113-7D." | `doi:10.1186/1475-2859-9-16` | `quote_absent_from_paper` | **`doi:10.1186/1475-2859-7-9`** — *Altering the coenzyme preference of xylose reductase…* (Microb Cell Fact, 2008). Byte-exact there. |
| `candidates[2].evidence[14]` | "Strain BP10001 was previously constructed from S. cerevisiae CEN.PK 113-5D through genomic integration of genes encoding a doubly mutated (Lys274-to-Arg; Asn276-to-Asp) variant of XR from C. tenuis and the wild-type XDH from Galactocandida mastotermitis." | `doi:10.1186/1475-2859-9-16` | `quote_absent_from_paper` | **`doi:10.1186/1754-6834-7-49`** — *Process intensification through microbial strain evolution…* (Biotechnol Biofuels, 2014). Byte-exact there. |

These are the two the phase-2 pass found. The provenance is now named: both are cited companion
papers of the same Graz/Nidetzky lineage, both are in the corpus, and the words "isogenic" and
"CEN.PK 113-7D" do indeed appear nowhere in `9-16`. The candidate's strain-background claims rest
on papers that are not the candidate.

Note also that `evidence[14]` is dated 2014 while the attributed paper is from 2010 — the quote
could not have come from it under any reading.

### 2.2 `docs/drafts/mitochondria/allotopic_expression.yaml` — VAR1 relocation record (1 quote)

| entry | quote | attributed DOI | classification | actually from |
|---|---|---|---|---|
| `relocation_attempts[0].evidence[3]` (`gene: VAR1`) | "For example, the W56R mutant of the yeast cytochrome c oxidase could be allotopically expressed using an MTS derived from the S. cerevisiae—OXA1 gene or Neurospora crassa mitochondrial ATP synthase subunit 9 gene, both of which code for hydrophobic mitochondrial proteins, but not with an MTS derived from the COX4 gene…" | `doi:10.1093/nar/gkaa424`, `doi:10.1093/nar/gkx426` | `quote_absent_from_paper` | **`doi:10.1016/j.gendis.2019.08.001`** — *Allotopic expression of mitochondrial genes: Basic strategy and progress* (a review). Byte-exact there. |

This one is benign in substance and sloppy in filing. The record's own `why_it_matters` prose names
`doi:10.1016/j.gendis.2019.08.001` as the source of exactly this fact two lines below, so the
curator knew where it came from; the quote was simply parked in a `publication:` field that names
two other papers. It is a Cox2 sentence sitting inside a Var1 record whose `publication` is the
two Var1 papers. **The file's header claim — "78 quotes, 78 passes, 0 failures" — is therefore
not accurate for this file as written**, because the check was run against the source the quote
came from rather than against the source the record names.

### 2.3 One spliced quote, in a promoted `data/` file

| file | entry | quote | attributed DOI | classification |
|---|---|---|---|---|
| `data/pathways/parts_catalog.yaml` | `parts[16]` (`id: adh3_native`) | "The D. bruxellensis ADH3 protein sequence **...** for mitochondrial-targeting motifs by pairwise alignment with S. cerevisiae ADH3 sequence" | `doi:10.1007/s00253-015-7266-x` | **spliced quote** |

The stored text reads "The D. bruxellensis ADH3 protein sequence **was searched** for
mitochondrial-targeting motifs by pairwise alignment with S. cerevisiae ADH3 sequence using EMBOSS
ClustalW2". Two words were elided and replaced with an ellipsis inside quote marks. The material
is in the attributed paper; the **span** is not, and `verify_span` rejects it. This is the failure
mode `activator_map.yaml` explicitly condemns in its own DESPLICED note of 2026-09-21 ("An elided
quote cannot be re-resolved at an offset, so it is not evidence"), reproduced a day later in a
sibling file.

## 3. `data/` — is any promoted artifact affected?

**Yes: one, and it is not either of the two the brief flagged.**

| promoted file | swept | verdict |
|---|---|---|
| `data/benchmarks/known_positives.yaml` | 78 | **CLEAN.** 78/78 re-resolve exact at their recorded offsets. The earlier spot-check's "78 of 78" is confirmed independently. |
| `data/literature/ethanol_admissions.yaml` | 53 | **CLEAN.** 53/53 exact. (The brief says "63 of 63"; the file's own `span_verification` block says `re_resolved_exact: 53` and there are 53 spans in it. The 63 figure belongs to `docs/drafts/ethanol/phase2_admissions.yaml`, which also comes back 63/63 exact. Worth reconciling the two numbers in whatever cites them.) |
| `data/mitochondria/activator_map.yaml` — promoted 2026-09-21 | 20 | **CLEAN.** Every literature quote resolves. The one "absent" hit is my extractor lifting the file's own quotation of `docs/design/MITOCHONDRIAL_PROGRAM.md` §2.1, which the prose labels correctly. |
| `data/mitochondria/heterologous_orf_precedents.yaml` — promoted 2026-09-21 | 20 | **CLEAN on provenance.** Every quote is in the paper it is attributed to. Two quotes from `doi:10.1016/bs.mie.2024.07.028` match only after whitespace folding — the stored PDF text layer carries "split -GFP" / "bi -genomic" with stray spaces that the draft normalised. Cosmetic, not provenance. |
| `data/pathways/parts_catalog.yaml` — re-grounded 2026-09-22 | 23 | **AFFECTED. 8 of 23 quotes are not verbatim spans of the paper they are attributed to.** |
| `data/pathways/isobutanol_valine_ehrlich.yaml`, `data/omics/reference_genomes.yaml` | 2 | No literature spans of substance; nothing to report. |
| `data/annotation/`, `data/strains/`, `data/vocabularies/`, `data/panels/`, `data/omics/*.json`, `data/literature/query_families.yaml`, `data/pathways/ethanol_reference.yaml` | 0 | Carry no quoted spans. |

### The `parts_catalog.yaml` failures in full

None of these is a fabrication — in every case the sentence **is** in the attributed paper. What
is wrong is that the quote was **retyped from the rendered paper rather than sliced from the
store**, so PDF/JATS artefacts were silently cleaned away and the string is no longer a span.
`verify_span` would reject all eight. The file's header asserts these three entries "have been
re-grounded against the stored corpus and quote it"; they quote the paper, but not the stored text.

| entry | attributed DOI | what the draft writes | what the store actually reads |
|---|---|---|---|
| `parts[6]` `ilvc_p2d1a1_ecoli` | `doi:10.1038/s41467-021-27852-x` | `Ec_ilvC(P2D1-A1), encoding an engineered NADH-dependent KARI from E. coli` | `Ec_ilvCP2D1-A1, encoding …` — the superscript is lost in the stored text; the parentheses were added by the curator |
| `parts[13]` `adh7_native` | `doi:10.1016/j.cels.2019.10.006` | `The 2 m plasmid introduced, pJA184 (Avalos et al., 2013), contains ILV2, ILV3, ILV5, with their gene products targeted to mitochondria; …` | `… pJA184 ( Avalos et al., 2013 ), contains ILV2, ILV3, ILV5 , with their gene products tar-\ngeted to mitochondria; …` — spacing and a line-break hyphenation were repaired |
| `parts[13]` `adh7_native` | `doi:10.1016/j.cels.2019.10.006` | `we overexpressed five genes in the isobutanol biosynthetic pathway, ILV2, ILV3, ILV5, and ADH7 from S. cerevisiae and 2-ketoacid decarboxylase (KDC) from Lactococcus lactis` | `we overexpressed ﬁve genes in the isobutanol biosynthetic\npathway, ILV2, ILV3, ILV5,a n d ADH7 from S. cerevisiae and\n2-ketoacid decarboxylase (KDC) from Lactococcus lactis` — the `ﬁ` ligature and the letter-spaced `a n d` were normalised |
| `parts[15]` `pos5_native` | `doi:10.1016/j.mec.2024.e00245` | `the kinase Pos5 - naturally a mitochondrial enzyme - is regarded as particularly suitable…` | same sentence with **en-dashes**, not hyphens |
| `parts[15]` `pos5_native` | `doi:10.1186/1475-2859-10-27` | `Required for the response to oxidative stress` | `… and it is **r**equired for the response to oxidative stress` — capitalised by the curator |
| `parts[16]` `adh3_native` | `doi:10.1128/spectrum.03519-22` | `This reaction is catalyzed by ADH3-encoded mitochondrial alcohol dehydrogenase in Saccharomyces and helps to regenerate mitochondrial NAD+ …` | `… in Saccharomyces **()** and helps …` — the empty citation marker was deleted |
| `parts[16]` `adh3_native` | `doi:10.1007/s00253-015-7266-x` | `The D. bruxellensis ADH3 protein sequence **...** for mitochondrial-targeting motifs …` | **spliced** — see §2.3 |
| `parts[17]` `gpd1_gpd2_native` | `doi:10.1016/j.synbio.2021.12.010` | `… glycerol-3-phosphate dehydrogenase (Gpd1, Gpd2, EC 1.1.1.8)` | `… (Gpd1, Gpd2, EC 1.1.1.8 **[,]**)` — the citation marker was deleted |

Contrast this with `docs/drafts/ethanol/phase2_admissions.yaml`, which quotes the **same** Cell
Systems paper and preserves the artefacts exactly (`"…Lactococcus lactis in the\ngln3D strain…"`)
and passes byte-exact. The difference is method: sliced by offset versus retyped.

## 4. Attribution gaps (the quote is genuine; the record does not say where it is from)

Ten quotes carry no usable attribution at the record. **All ten were located and all ten resolve
byte-exact** — none is a fabrication — but none of them can be re-verified from the draft as
written.

| file | entry | resolves in |
|---|---|---|
| `mitochondria/allotopic_expression.yaml` | `hydrophobicity_hypothesis.evidence[0]` | `doi:10.1371/journal.pgen.1002876` |
| " | `…evidence[1]` | `doi:10.1091/mbc.e17-09-0560` |
| " | `…evidence[2]`, `…evidence[3]` | `doi:10.1093/nar/gkq769` |
| " | `…evidence[4]`, `…evidence[5]` | `doi:10.1016/j.gendis.2019.08.001` |
| " | `scope_exclusions[0].evidence[0]` | `doi:10.26508/lsa.202301965` |
| `mitochondria/rho_zero_physiology.yaml` | `nomenclature_discipline.definitions[0]` | `doi:10.1093/femsre/fuv028` |
| `ethanol/slot7_E6_industrial_performance.yaml` | `ethanol_red_coverage.how_it_actually_appears[3].evidence[0]` | `doi:10.1186/s13068-015-0421-x` |
| `ethanol/slot7_E6_industrial_performance.yaml` | `…the_one_quantitative_claim_about_its_performance.evidence[0]` | `doi:10.1186/s13068-015-0421-x` |

The two `slot7` entries are the structurally interesting ones: their **only** source marker is
`corpus_file: 00727.txt`. The numbered scratchpad cache no longer exists on this machine, so that
attribution is dead on its own terms — I resolved them by searching the store. **This is the real
residue of the cache-versus-store problem.** It is not that the cache text was wrong; it is that
14 draft files (267 `corpus_file:` markers in total, led by `benchmarks/pathway_compartment.yaml`
at 30, `warnings/PLAN.yaml` at 29, `warnings/ISOBUTANOL_PROGRAM.yaml` at 24) record provenance
against file numbers that nothing can now dereference. Everywhere else a DOI sits beside the
`corpus_file` and the marker is redundant; in these two places it does not, and the provenance was
recoverable only by full-text search.

## 5. Offsets: what the drafts actually record

Of 1,912 quotes swept, **only 1,226 carry offsets at all**. The other 655 are verbatim strings
with no `char_start`/`char_end` anywhere — `not_a_span` in the brief's terms. They are spread
across every mitochondria draft, every ethanol slot shortlist, both non-`PLAN` warnings files and
the benchmark category drafts. Several of those files state in their headers that each quote "was
re-resolved at its own offsets with `fermdb.llm.validate.verify_span`". That may well be true of
the work; it is **not reproducible from the file**, because the file does not carry the offsets
the claim refers to. This sweep could only confirm presence, not position, for a third of the
corpus of quotes.

Two files do it right and are the model: `ethanol/phase2_admissions.yaml` and
`configurations/host_resolution.yaml` carry `quote`, `char_start`, `char_end` and `verified_exact`
per span, and both come back 100% exact.

## 6. Per-file tally

`ok` = re-resolved against the stored full text (exact at recorded offsets, or byte-exact where no
offsets are recorded).

| file | swept | ok | not ok |
|---|---|---|---|
| **`data/` (promoted)** | | | |
| `data/benchmarks/known_positives.yaml` | 78 | 78 | — |
| `data/literature/ethanol_admissions.yaml` | 53 | 53 | — |
| `data/mitochondria/activator_map.yaml` | 20 | 20 | — (1 extractor artefact) |
| `data/mitochondria/heterologous_orf_precedents.yaml` | 20 | 18 | 2 whitespace-only (+2 artefacts) |
| `data/pathways/parts_catalog.yaml` | 23 | 15 | **7 not verbatim + 1 spliced** |
| `data/pathways/isobutanol_valine_ehrlich.yaml` | 1 | 1 | — |
| `data/omics/reference_genomes.yaml` | 1 | 0 | 1 extractor artefact |
| **`docs/drafts/warnings/`** | | | |
| `warnings/PLAN.yaml` | 68 | 68 | — (all exact at their cache-derived offsets) |
| `warnings/ISOBUTANOL_PROGRAM.yaml` | 56 | 56 | — |
| `warnings/MITOCHONDRIAL_AND_DUET.yaml` | 48 | 48 | — |
| **`docs/drafts/mitochondria/`** | | | |
| `mitochondria/allotopic_expression.yaml` | 67 | 59 | **1 absent** + 7 unattributed |
| `mitochondria/transformation_methods.yaml` | 50 | 50 | — |
| `mitochondria/rho_zero_physiology.yaml` | 49 | 48 | 1 unattributed |
| `mitochondria/stability_heteroplasmy.yaml` | 39 | 39 | — |
| `mitochondria/marker_systems.yaml` | 35 | 34 | 1 extractor artefact |
| **`docs/drafts/ethanol/`** | | | |
| `ethanol/slot1_E3_baseline_physiology.yaml` | 68 | 66 | **2 absent** |
| `ethanol/phase2_admissions.yaml` | 63 | 63 | — |
| `ethanol/slots3_4_E4_ethanol_stress.yaml` | 55 | 55 | — |
| `ethanol/slot5_E2_vhg_ceiling.yaml` | 31 | 31 | — |
| `ethanol/slot7_E6_industrial_performance.yaml` | 28 | 26 | 2 cache-file-only attribution |
| `ethanol/slot6_E5_redox_shuttle.yaml` | 20 | 20 | — |
| `ethanol/slot2_E1_pdc_minus.yaml` | 19 | 19 | — |
| **`docs/drafts/benchmarks/`** | | | |
| `benchmarks/MERGED_known_positives.candidate.yaml` | 78 | 78 | — |
| `benchmarks/pathway_compartment.yaml` | 30 | 30 | — |
| `benchmarks/mitochondrial_genetics.yaml` | 8 | 8 | — |
| `benchmarks/competing_pathway.yaml` | 6 | 6 | — |
| `benchmarks/cofactor_redox.yaml` | 5 | 5 | — |
| `benchmarks/ethanol_reference.yaml` | 4 | 4 | — |
| `benchmarks/tolerance.yaml` | 3 | 3 | — |
| `benchmarks/RECONCILIATION.md` | 7 | 7 | — |
| `benchmarks/negative_control.yaml` | 0 | — | carries no spans, by design |
| **`docs/drafts/configurations/`** | | | |
| `configurations/host_resolution.yaml` | 31 | 31 | — |
| **`docs/drafts/calibration/`** | | | |
| `calibration/raw/capable/doi_10.1016_j.meteno.2016.01.002.json` | 530 | 530 | — |
| `calibration/raw/local/doi_10.1002_elsc.201900151.json` | 142 | 142 | — |
| `calibration/raw/local/doi_10.1007_s00253-014-5580-3.json` | 102 | 102 | — |
| `calibration/raw/capable/doi_10.1016_j.jbc.2026.113228.json` | 72 | 72 | — |
| `calibration/raw/local/doi_10.1016_j.jbc.2026.113228.json` | 2 | 2 | — |
| `calibration/raw/` (remaining files, `frozen20.json`, `*.md`) | 0 | — | run conditions and selection scripts; no spans |
| **`docs/drafts/corpus/`** | | | |
| `corpus/new_pdf_triage.yaml`, `*.md` | 0 | — | triage metadata; no spans |

The 848 calibration spans are raw model-run output rather than curated claims, and are reported
separately for that reason — but they all resolve, which is itself a useful datum about the
harness that produced them.

## 7. `no_stored_text`

**Zero.** The AES-encrypted PDF (`doi:10.2323/jgam.2022.05.001`) is quoted nowhere; the drafts that
mention it name it correctly as unreadable.

One near-miss is worth recording as a repair note rather than a defect:
`docs/drafts/ethanol/slots3_4_E4_ethanol_stress.yaml` writes the DOI as `10.1128/AEM.00588-21`
while the store keys it `doi:10.1128/aem.00588-21`. A case-sensitive lookup reports "no stored full
text" for a paper that is in fact stored, and all six of that candidate's quotes resolve exactly
once the id is case-folded. Any future sweep or promotion tool should fold DOI case.

## 8. What I did not reach

Nothing in the assigned scope was skipped. All YAML and JSON under `docs/drafts/` and `data/` was
parsed and swept, plus the span-bearing markdown in `docs/drafts/benchmarks/RECONCILIATION.md`.
The remaining `.md` files under `docs/drafts/` (`PHASE2_STATUS.md`, `HOST_RESOLUTION.md`,
`ACCEPTANCE.md`, `PHASE_3_5_RECOMMENDATION.md`, the calibration and corpus notes) carry no offset
markers; their block quotes restate material already verified in the sibling YAML.

Eight of the failures above are artefacts of my own extractor, which had to lift quotes out of
prose `evidence:` blocks by looking for double-quoted runs and sometimes caught editorial sentences
instead. They are listed as artefacts, not as defects, and they are: one each in
`marker_systems.yaml`, `activator_map.yaml`, `reference_genomes.yaml`, two in
`heterologous_orf_precedents.yaml`, three in `parts_catalog.yaml`.

## 9. Verdict

**Can the earlier waves' span-verification claims be trusted?** Substantially yes, with two
qualifications and one exception. The `PLAN.yaml` wave's "49 of 49 re-resolved EXACT" holds against
the real store (68 quotes checked here, 68 exact), and the benchmark and phase-2 admission claims
hold exactly as stated. The qualifications are that (a) the `allotopic_expression.yaml` header's
"78 quotes, 78 passes" is wrong by one, because one quote was verified against the paper it came
from rather than the paper the record names, and (b) 655 quotes across the drafts claim offset
verification in their headers while recording no offsets, so the claim is unfalsifiable from the
file. The exception is `data/pathways/parts_catalog.yaml`, whose three `cofactor_cycle` entries
and `ilvc_p2d1a1_ecoli` were written by retyping sentences rather than slicing spans, and where
eight of twenty-three quotes — including one ellipsis splice — would fail `verify_span`.

**A repair pass is warranted and it is small:** three re-attributions, one desplice, seven
re-slices, ten attribution fields to fill in, and a decision about whether `corpus_file:` markers
should be replaced by DOIs everywhere now that the cache they point at is gone.
