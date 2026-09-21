# The frozen 20-paper gold-standard calibration set

2026-09-21. Fixed **before any model was run**, as PLAN.md S.2 requires (thresholds and sets
fixed before the data is seen). Nothing below was chosen by looking at extraction output.

Stratification is Decision **D8** (`docs/reports/2026-09-21-unattended-work-plan.md` §1):
**8 isobutanol-yeast, 4 isobutanol-other-host, 4 mtDNA-engineering, 4 ethanol-reference — all
with stored full text, none already extracted.** D8's own note applies: *"the stratification is
the defensible part, not the identity of any one paper."*

## Selection rule, stated before selection

Applied in this order. Every criterion is a property of the corpus, not of any model's answer.

1. **Stored full text, JATS XML only** (`fulltext_asset.storage_state = 'stored_fulltext'`,
   `media_type = 'application/xml'`). PDFs are excluded deliberately: `MODEL_ROUTING.md` §7c
   records that PDF text extraction breaks sentences across lines, which makes a span fail
   verification for a reason that has nothing to do with the model. Including PDFs would
   confound the span-failure count this calibration is meant to measure. 1,277 of the 1,310
   stored documents are JATS, so this costs almost nothing.
2. **No existing `extraction` row** for the publication. Five publications already extracted
   (`10.1016/j.meteno.2016.03.004`, `10.1186/1475-2859-12-119`, `10.1016/j.btre.2026.e00959`,
   `10.1186/s13068-019-1486-8`, `10.1186/s13068-019-1560-2`) are excluded.
3. **Disjoint strata, by triage family** (`screening_record.family`):
   * `IY` — in `isobutanol_yeast` or `isobutanol_mitochondria`
   * `IO` — in an isobutanol family but *not* `isobutanol_yeast`, and a non-yeast host named in
     the title
   * `MT` — in `mtdna_engineering_yeast`, not in any isobutanol family
   * `ET` — in an `ethanol_*` family, not in any isobutanol or mtDNA family
4. **Topical screen on the title.** The triage families are broad keyword families: the
   `isobutanol_all` family contains table-olive and plum-wine aroma papers, and a first pass
   ordered purely by DOI put *"A bHLH Transcription Factor Confers Salinity Stress Tolerance"*
   into the mtDNA stratum. A recall measurement on papers that contain no extractable
   engineering facts measures nothing — both tiers would return near-zero and the margin would
   be noise. So within each stratum the title must be on-topic:
   * `IY` / `IO`: the title names isobutanol
   * `MT`: the title names a mitochondrial genome / mtDNA / allotopic expression / a
     mitochondrially-encoded locus
   * `ET`: the title names ethanol *and* a yeast *and* production, yield, fermentation or
     tolerance
5. **Reviews and publisher corrections excluded** (no primary measurements to recall).
6. **Tie-break: DOI ascending, lexicographic.** Content-independent, reproducible, and not
   chosen to favour either tier.

## Run order — any prefix stays stratified

The list is interleaved `IY IY IO MT ET`, repeated four times, so a run that has to stop early
still has a balanced sample. **This matters**: `MODEL_ROUTING.md` §7c measures a 27B model at
minutes per paper, so the full 20 may not fit the wall-clock budget. If N < 20, the first N in
this order is the sample, and N is reported as N.

| # | stratum | DOI | year | title |
|---|---|---|---|---|
| 1 | IY | `10.1016/j.jbc.2026.113228` | 2026 | Leucyl-tRNA synthetase as a molecular target of isobutanol-mediated growth inhibition |
| 2 | IY | `10.1016/j.meteno.2016.01.002` | 2016 | Excessive by-product formation: a key contributor to low isobutanol yields of engineered *S. cerevisiae* |
| 3 | IO | `10.1002/elsc.201900151` | 2019 | Engineering *Pseudomonas putida* KT2440 for the production of isobutanol |
| 4 | MT | `10.1093/g3journal/jkae295` | 2024 | A high copy suppressor screen identifies factors enhancing the allotopic production of … |
| 5 | ET | `10.1007/s00253-014-5580-3` | 2014 | Physiological characterization of thermotolerant yeast for cellulosic ethanol production |
| 6 | IY | `10.1016/j.synbio.2022.02.007` | 2022 | Comparative functional genomics identifies an iron-limited bottleneck in a *Saccharomyces* … |
| 7 | IY | `10.1038/s41467-021-27852-x` | 2021 | Biosensor for branched-chain amino acid metabolism in yeast and applications in isobutanol … |
| 8 | IO | `10.1007/s00253-009-2085-6` | 2010 | Engineering the isobutanol biosynthetic pathway in *Escherichia coli* |
| 9 | MT | `10.1093/genetics/iyaf037` | 2025 | A new set of mutations in the second transmembrane helix of the Cox2p-W56R … |
| 10 | ET | `10.1007/s00253-025-13446-w` | 2025 | Engineered *S. cerevisiae* construction for high-gravity ethanol production |
| 11 | IY | `10.1038/s41598-019-40631-5` | 2019 | Development of an efficient cytosolic isobutanol production pathway in *S. cerevisiae* |
| 12 | IY | `10.1093/femsyr/foae006` | 2024 | Increased production of isobutanol from xylose through metabolic engineering of *S. cerevisiae* |
| 13 | IO | `10.1007/s00253-010-2522-6` | 2010 | Engineering *Corynebacterium glutamicum* for isobutanol production |
| 14 | MT | `10.1371/journal.pgen.1002876` | 2012 | Experimental relocation of the mitochondrial *ATP9* gene to the nucleus |
| 15 | ET | `10.1007/s00253-026-13830-0` | 2026 | Engineering natural *S. cerevisiae* isolates for enhanced one-step cellulosic ethanol … |
| 16 | IY | `10.1186/1754-6834-4-21` | 2011 | Increased isobutanol production in *S. cerevisiae* by overexpression of genes |
| 17 | IY | `10.1186/1754-6834-5-65` | 2012 | Cytosolic re-localization and optimization of valine synthesis and catabolism |
| 18 | IO | `10.1016/j.meteno.2017.07.003` | 2017 | Isobutanol production in *Synechocystis* PCC 6803 |
| 19 | MT | `10.26508/lsa.202301965` | 2023 | Allotopic expression of *COX6* elucidates Atco-driven co-assembly of cytochrome oxidase |
| 20 | ET | `10.1007/s10295-013-1311-5` | 2013 | Engineering of the glycerol decomposition pathway and cofactor regulation in an industrial … |

## Pool sizes the strata were drawn from

After criteria 1–3, before the topical screen: `IY` 84, `IO` 261, `MT` 384, `ET` 534 eligible
publications. The set is not scarce; nothing here was forced.

## What this run may and may not do

* Every `fermdb extract run` invocation carries **`--dry-run --no-enqueue`**. Zero curation
  tasks are created; the queue stays at 95 against the 180 cap (D6).
* Nothing is written to `data/` or to the database. All output lands under
  `docs/drafts/calibration/`.
* No `confidence` value is set and no `verified` flag is flipped anywhere (D2, L.5, and
  `MODEL_ROUTING.md` §5 rule 2).
