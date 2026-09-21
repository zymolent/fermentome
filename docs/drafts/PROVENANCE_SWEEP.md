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

---

# REPAIRS APPLIED — 2026-09-22

Everything below was done after the audit above, by a separate pass, against the same store opened
`mode=ro`. `fermdb extract` was not run, the database was not modified, and nothing under `src/`,
`tests/`, `PLAN.md` or `data/` was edited. **`data/pathways/parts_catalog.yaml` was deliberately
not touched** — its eight bad quotes were being re-sliced concurrently by another agent, and that
repair is theirs.

**Every relocation below was re-verified by this pass rather than taken from the audit**, through
`fermdb.extract.harness.load_source_text` and `fermdb.llm.validate.verify_span`. No quote string
was edited anywhere in the repair: each is the same contiguous slice it was, re-resolved at its own
offsets in its real source. Where a repair restructured a list to carry per-quote attribution, the
set of quote strings before and after was diffed and confirmed identical.

## 10. The re-attributions — four, not three

The audit found three. A fourth was found by re-sweeping `allotopic_expression.yaml` in full: the
audit's extractor reached 67 of that file's 78 quotes, and the fourth defect was among the 11 it
did not reach. All four are the same failure mode — **a quote from a cited companion paper appended
to an `evidence:` list whose attribution is a single record-level field, which cannot carry a
second source.** None is a fabrication; every one is a real sentence in a real paper in the corpus.

| # | entry | was attributed to | actually in | verify_span |
|---|---|---|---|---|
| 1 | `ethanol/slot1…yaml` `candidates[2].evidence[13]` | `doi:10.1186/1475-2859-9-16` | **`doi:10.1186/1475-2859-7-9`** | EXACT `[7090, 7184)`, 1 occurrence; absent from 9-16 |
| 2 | `ethanol/slot1…yaml` `candidates[2].evidence[14]` | `doi:10.1186/1475-2859-9-16` | **`doi:10.1186/1754-6834-7-49`** | EXACT `[36111, 36365)`, 1 occurrence; absent from 9-16 |
| 3 | `mitochondria/allotopic_expression.yaml` `relocation_attempts[0].evidence[3]` (VAR1) | `doi:10.1093/nar/gkaa424`, `doi:10.1093/nar/gkx426` | **`doi:10.1016/j.gendis.2019.08.001`** | EXACT `[15656, 16057)`, 1 occurrence; absent from both named papers |
| 4 | `mitochondria/allotopic_expression.yaml` `relocation_attempts[2].evidence_expression_sensitivity[3]` (ATP8) — **NEW, not in the audit** | `doi:10.1091/mbc.e16-11-0775`, `doi:10.1016/j.gendis.2019.08.001` | **`doi:10.1093/nar/gkaa424`** | EXACT `[28552, 28806)`, 1 occurrence; absent from both named papers |

Each is repaired **in place with an `attribution_corrected` block** recording the date, the previous
attribution, the new one, and how it was checked. The DOI was not silently swapped: the correction
is itself evidence about how the wave worked, and is written down as such.

**Two things the repair recorded that the audit did not.**

* **A date check would have caught #2 for free.** The quote is dated 2014 and the paper it was
  charged to is from 2010. That attribution was impossible on its face, without reading either
  text. This is now written into the entry as `the_tell`, and it is the cheapest available screen
  for the next wave.
* **The Cox2-in-a-Var1-record question was answered, not assumed.** The brief asked whether the
  record's *claim* was affected and not merely its citation. It is not, and the check is recorded
  on the record: every field of the VAR1 entry — COX4 presequence, full function restored, no
  sequence changes, fractionation readout — rests on `evidence[0..2]`, and those three re-resolve
  EXACT against the two papers the record names (`[0]` and `[2]` in `gkaa424`, `[1]` in `gkx426`),
  as do both `evidence_caveats`. The misfiled sentence supports only the COX4 contrast drawn in
  `why_it_matters`, which already named `gendis` as its source. Same for the ATP8 record: its
  fields rest on `evidence[0..4]`, all EXACT against the papers it names. **What was wrong was the
  filing, not either finding.**

## 11. Header corrections

| file | claim | verdict | action |
|---|---|---|---|
| `mitochondria/allotopic_expression.yaml` | "78 quotes, 78 passes, 0 failures" | **wrong by two, not one** | corrected, and made true again by the repair |
| `ethanol/phase2_admissions.yaml` | `spans_checked: 63` | **correct** | left; a `what_the_63_is_made_of` note added so the number cannot be conflated again |
| `data/literature/ethanol_admissions.yaml` | `re_resolved_exact: 53` | **correct** | **not edited — it is under `data/`. It needs no change.** |

The `allotopic_expression.yaml` count of **78 is itself right** — this pass found exactly 78 quotes,
matching the header. What was wrong was "78 passes": two quotes passed against the paper they came
from rather than the paper their record names, and eleven more named no paper at all, so they could
not be checked from the file in either direction. After the repair the claim holds as written:
**78 quotes, 78 resolve byte-exact against the publication the record itself names, 0 absent,
0 unattributed.** The header now also states plainly that the file records no `char_start`/
`char_end`, so "extracted by offset" describes how the work was done and is not reproducible from
the file — the §5 finding, applied to the one file whose header this pass rewrote.

## 12. Attribution gaps filled — fourteen, not ten

All ten the audit listed, plus four more of the same kind found while re-sweeping. All fourteen
resolve byte-exact; none was a fabrication.

| file | entries | resolved to |
|---|---|---|
| `mitochondria/allotopic_expression.yaml` | `hydrophobicity_hypothesis.evidence[0..5]` | `pgen.1002876`, `mbc.e17-09-0560`, `nar/gkq769` ×2, `gendis.2019.08.001` ×2 |
| " | `…evidence_natural[0..1]` — **not in the audit's ten** | `nar/gkq769`, `mbc.e17-09-0560` |
| " | `…evidence_caveats[0..1]` — **not in the audit's ten** | `mbc.e17-09-0560`, `genetics/iyaf037` |
| " | `scope_exclusions[0].evidence[0]` | `doi:10.26508/lsa.202301965` |
| `mitochondria/rho_zero_physiology.yaml` | `nomenclature_discipline.definitions[0]` | `doi:10.1093/femsre/fuv028` |
| `ethanol/slot7_E6_industrial_performance.yaml` | the two Ethanol Red quotes | `doi:10.1186/s13068-015-0421-x` (verified independently — see §13) |

Two of these are worth separating out, because they are different defects wearing the same label.

* **The `hydrophobicity_hypothesis` block was never a one-paper record.** Its six quotes come from
  four different papers — which is exactly what its own `status` field claims — so a record-level
  `publication:` could never have carried them. The list shape was changed to `{publication, quote}`
  pairs, and a `the_four_papers` field now names the four so the "stated explicitly in four papers"
  claim can be checked rather than taken. The four are `pgen.1002876`, `mbc.e17-09-0560`,
  `nar/gkq769` and `gendis.2019.08.001`. **The claim checks out.**
* **`rho_zero_physiology.yaml` was never missing its attribution at all.** It wrote
  `definition_source: doi:10.1093/femsre/fuv028` — the right DOI, under a key name used nowhere
  else in the repo, so no tool reading attribution by key could see it. The source was never wrong,
  only unreadable. It now carries `publication:` as well.

## 13. The dead `corpus_file:` markers — replaced, and the count was wrong

**Decision: replaced, per the owner's steer, and the two exceptions fixed specifically.** The
markers pointed at a numbered scratchpad cache (`NNNNN.txt`); this pass confirmed no such cache
exists anywhere on the machine — no `scratchpad/` directory, no `E3.json`, no `00727.txt` under the
data directory. The pointers were dereferenceable by nobody.

**The audit's count is wrong.** It reports "267 `corpus_file:` markers across 14 draft files". The
actual figure is **191 markers across 15 files**. The audit's own per-file leaders are right and
match this pass exactly (`pathway_compartment` 30, `PLAN` 29, `ISOBUTANOL_PROGRAM` 24) — it is the
total and the file count that are off, so this looks like a summing error rather than a different
definition. The 15 files are the 14 it names plus `benchmarks/ethanol_reference.yaml`.

| action | count | rule |
|---|---|---|
| removed as redundant | **173** | a `doi:` or `publication:` sat beside the marker in the same record and already carried the provenance |
| replaced by a DOI resolved from an adjacent `pmid:` | **16** | all in `slots3_4_E4_ethanol_stress.yaml`; a PMID is a live id, so the dead pointer became a live one rather than vanishing |
| resolved by hand from the store | **2** | the `slot7` Ethanol Red pair — the two exceptions, below |
| **total** | **191** | |

**Checked before removing anything:** across all 15 files the **101 distinct cache numbers each map
to exactly one DOI** — zero numbers map to two papers. The markers were internally consistent and
carried no information the adjacent DOI does not, which is what makes dropping them safe. Every
file that lost markers carries a header note recording how many went and why. All 15 still parse.

**The two exceptions**, whose only source marker was `corpus_file: 00727.txt`, were verified by this
pass rather than taken from the audit. Both are in **`doi:10.1186/s13068-015-0421-x`**:

* `ethanol_red_coverage.how_it_actually_appears[3].evidence[0]` — EXACT `[8423, 8581)`, 1 occurrence
* `…the_one_quantitative_claim_about_its_performance.evidence[0]` — EXACT `[7836, 7887)`, 1 occurrence

Each now carries the DOI plus an `attribution_recovered` block naming the dead marker it replaced.
Recording the 18% ethanol titre's source also makes visible what it is: a sentence in that paper's
**introduction**, which is why it carries no conditions.

**One thing the markers were hiding.** The same file's prose named "corpus files 00727, 00494,
00495, 00473" as a Thevelein-group polygenic series. Three were identified from the store by trait
and by searching for `Ethanol Red` / `ER18` / `ER7A`: `doi:10.1186/s13068-015-0421-x` (= 00727),
`doi:10.1128/aem.00814-22` and `doi:10.1128/mbio.01279-18`. **The fourth could not be identified and
is recorded as unresolved rather than guessed at** — the obvious candidate,
`doi:10.1186/s13068-020-01761-5`, does not mention Ethanol Red at all, and no paper in the store was
found using `ER18A` as a parent, so the file's claim that ER18A appears as a parent is now flagged
as unsupported.

**A residue that was left alone, deliberately.** `MITOCHONDRIAL_AND_DUET.yaml` and `PLAN.yaml`
carry cache numbers inside YAML *comments* (`# doi:10.1093/nar/gkad849  [00391.txt]`), and
`ISOBUTANOL_PROGRAM.yaml` carries them inside `also_in:` strings. These are not `corpus_file:` keys,
they were not in either count, and in every case a DOI sits beside the number in the same string —
so they are harmless. See §16.

## 14. DOI case — the draft was right, the lookup is the trap

**The audit read this backwards.** It reports that `slots3_4_E4_ethanol_stress.yaml` "writes the DOI
as `10.1128/AEM.00588-21` while the store keys `doi:10.1128/aem.00588-21`", and treats the draft as
the defect. Checked against the store:

```
publication.id  = doi:10.1128/aem.00588-21
publication.doi = 10.1128/AEM.00588-21      <- the publisher's canonical casing
```

The draft's `doi:` value **was correct all along** and matches `publication.doi` byte for byte. What
it lacked was the *store key*. The draft now carries both, the way `phase2_admissions.yaml` and
`data/literature/ethanol_admissions.yaml` already do: `doi:` is the publisher's form,
`publication_id:` is the store's key. All six of that candidate's quotes re-resolve under it.

### Should the lookup case-fold? Yes. Reported, not changed — `src/` is owned elsewhere.

Measured over the store, publication ids are **already case-normalised and DOIs are not**:

| measurement | value |
|---|---|
| publications total | 5,164 |
| DOI-keyed | 4,864 |
| `publication.id` containing any uppercase | **0** |
| `publication.doi` that is not already lowercase | **625 (12.9% of DOI-keyed)** |
| rows where `id` differs from `'doi:' + doi` | **625** |
| rows where `id` differs from `'doi:' + lower(doi)` | **0** |

So the invariant is exact and undocumented: **`publication.id` equals `'doi:'` concatenated with
`lower(publication.doi)`, for all 4,864.** `canonical_publication_id` in
`src/fermdb/literature/discovery.py:74` lowercases when minting, which is why no id has uppercase;
nothing on the read side does the same.

**Where it bites.** `load_source_text` (`src/fermdb/extract/harness.py:1247`) matches
`fulltext_asset.publication_id` with a bare `=`. No column in `schema.sql` is declared
`COLLATE NOCASE`, so that comparison is binary. Demonstrated live:

```
load_source_text(publication_id="doi:10.1128/AEM.00588-21") -> SourceTextError:
    "no stored full text for … Either it is not open access … or it was never fetched."
load_source_text(publication_id="doi:10.1128/aem.00588-21") -> 75,310 characters
```

**The message is the real danger.** It names two plausible causes — not open access, never fetched —
and the actual cause, a case-mismatched key, is not among them. A caller who trusts it records
"no stored full text" for a paper that is sitting in the store. That is how a 12.9% slice of the
corpus can be silently reported as unavailable.

**Reachable from the CLI.** `_resolve_publication_id` (`src/fermdb/cli.py:436`) passes
`--publication-id` through verbatim, so `fermdb extract run --publication-id doi:10.1128/AEM.00588-21`
hits exactly this. `--doi` is partly protected: `find_publication` (`harness.py:1229`) matches
`doi = ? OR id = ?`, which covers the canonical and the lowercase spellings but not a third casing —
`find_publication(doi="10.1128/Aem.00588-21")` returns `None`.

**Recommendation for whoever owns `src/`:** fold case on the read side, at the point an id is
matched rather than at every call site — `lower(publication_id) = lower(?)`, or `COLLATE NOCASE` on
the id columns. Failing that, `SourceTextError` should at least say "no row matched this id
exactly; a case-insensitive match does exist" when one does, so the trap announces itself. **Nothing
under `src/` was changed by this pass.**

## 15. The count reconciliation — 53 and 63 are both right

**Neither header is wrong, and neither needed correcting.** Both documents were re-counted by
walking them for objects carrying `quote` + `char_start` + `char_end`:

| file | spans found | where they sit | header says | verdict |
|---|---|---|---|---|
| `data/literature/ethanol_admissions.yaml` | **53** | all under `records` | `spans_in_this_file: 53`, `re_resolved_exact: 53` | **correct — no change, and none made** |
| `docs/drafts/ethanol/phase2_admissions.yaml` | **63** | 53 under `records` + 10 under `retagging_E5` | `spans_checked: 63`, `re_resolved_exact: 63` | **correct** |

**63 = 53 + 10.** The installed `data/` layer carries the admissions only, so it holds 53; the draft
additionally carries the 10 basis quotes on the re-tagging proposals, which stay in the draft
because installing the admissions re-tags nothing. `retagging_other` holds 8 entries and no spans,
which is why it adds to neither total. The `data/` file's own `span_verification.note` already
explained this precisely; the error was never in either file but in reporting that cited "63 of 63"
against the `data/` file. A `what_the_63_is_made_of` field was added to the **draft** to stop the
conflation recurring. **The `data/` file was read and not edited.**

## 16. Post-repair verification

Every file this pass touched, re-swept the same way the audit swept: each quote resolved against the
publication its own record names, through `load_source_text`, checked with `verify_span` — at the
recorded offsets where the file carries them, at the quote's own located offsets where it does not.

| file | quotes | exact at recorded offsets | byte-exact, no offsets recorded | absent | unattributed |
|---|---|---|---|---|---|
| `benchmarks/cofactor_redox.yaml` | 5 | — | 5 | 0 | 0 |
| `benchmarks/competing_pathway.yaml` | 6 | — | 6 | 0 | 0 |
| `benchmarks/ethanol_reference.yaml` | 4 | — | 4 | 0 | 0 |
| `benchmarks/mitochondrial_genetics.yaml` | 5 | — | 5 | 0 | 0 |
| `benchmarks/pathway_compartment.yaml` | 30 | — | 30 | 0 | 0 |
| `benchmarks/tolerance.yaml` | 3 | — | 3 | 0 | 0 |
| `ethanol/phase2_admissions.yaml` | 63 | **63** | — | 0 | 0 |
| `ethanol/slot1_E3_baseline_physiology.yaml` | 68 | — | 68 | 0 | 0 |
| `ethanol/slot2_E1_pdc_minus.yaml` | 19 | — | 19 | 0 | 0 |
| `ethanol/slot5_E2_vhg_ceiling.yaml` | 31 | — | 31 | 0 | 0 |
| `ethanol/slot6_E5_redox_shuttle.yaml` | 20 | — | 20 | 0 | 0 |
| `ethanol/slot7_E6_industrial_performance.yaml` | 28 | — | 28 | 0 | 0 |
| `ethanol/slots3_4_E4_ethanol_stress.yaml` | 55 | — | 55 | 0 | 0 |
| `mitochondria/allotopic_expression.yaml` | 78 | — | 78 | 0 | 0 |
| `mitochondria/rho_zero_physiology.yaml` | 9 | — | 9 | 0 | 0 |
| `warnings/ISOBUTANOL_PROGRAM.yaml` | 56 | — | 56 | 0 | 0 |
| `warnings/MITOCHONDRIAL_AND_DUET.yaml` | 48 | — | 48 (see below) | 0 | 0 |
| `warnings/PLAN.yaml` | 58 | — | 58 (see below) | 0 | 0 |
| **TOTAL** | **586** | **63** | **523** | **0** | **0** |

`slot1` reads 68 and `slots3_4` reads 55, matching the audit's per-file tally exactly. The audit
records `PLAN.yaml` at 68 quotes; this pass finds 58 — a difference in what each extractor counts as
a quote, not a disagreement about any quote, since all 58 resolve and none of the audit's 68 was
reported failing.

**A finding that only appeared during this verification: 34 quotes carry attribution that no parser
can read.** Swept strictly — resolving each quote against the publication its record names as a
*field* — 552 of the 586 pass and 34 do not, all in `MITOCHONDRIAL_AND_DUET.yaml` (33) and
`PLAN.yaml` (1). **None is mis-attributed.** Those files attribute each quote in a YAML **comment
directly above it**:

```yaml
  evidence:
    # doi:10.1093/nar/gkad849  [00391.txt]
    - "This analysis revealed a consistent ~1.6-fold increase of mtDNA CN in cim1-null cells …"
```

Every one of these commented attributions was extracted and checked against the store:
**`MITOCHONDRIAL_AND_DUET.yaml` 48 of 48 correct, `PLAN.yaml` 58 of 58 correct, zero wrong.** The
curator's attribution is exact; it is simply invisible to every tool, because a comment is not data.
This is the same defect as `rho_zero_physiology.yaml`'s `definition_source` — a correct source that
no machine can read — and it is why the audit, whose fallback retried failures against every paper
named anywhere in the same file, scored both files clean without noticing.

**It was left unrepaired, deliberately.** Converting 106 commented attributions into fields is a
larger and more mechanical change than this pass was asked for, it touches two files whose quotes
are all correct, and it should be done as its own pass with its own verification. It is recorded
here as the next repair rather than half-done now.

## 17. What this repair did not do

* **`data/pathways/parts_catalog.yaml` — untouched.** Its one splice and seven retyped quotes are
  another agent's concurrent work. Nothing here overlaps it.
* **`data/literature/ethanol_admissions.yaml` — read, not edited.** Its header is correct (§15).
* **No `src/`, `tests/`, `PLAN.md` or `data/` file was modified.** The case-folding fix §14 argues
  for is reported for the owner of `src/`, not applied.
* **The 655 offset-less quotes of §5 remain offset-less.** Recording real offsets means re-slicing
  every quote against the store, which is a re-extraction, not a repair. The one header that
  claimed offsets it does not carry now says so.
* **The database was not modified**; every connection was opened `mode=ro`. `fermdb extract` was
  not run.
