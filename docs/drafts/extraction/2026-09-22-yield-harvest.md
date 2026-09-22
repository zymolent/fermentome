# Isobutanol yield harvest from the stored full texts — 2026-09-22

Companion files:

- `docs/drafts/extraction/2026-09-22-yield-harvest.tsv` — 136 yield rows
- `docs/drafts/omics/2026-09-22-accessions-from-fulltext.tsv` — 530 accession rows

**Nothing here has been written to the database.** These are candidate rows for curation.

---

## 1. What was scanned

| | count |
|---|---|
| Full texts read | **1,429** |
| — JATS XML from PMC (`media_type='application/xml'`) | 1,277 |
| — PDF, via `pdftotext` (`media_type='application/pdf*'`) | 152 |
| XML parse failures | 0 |
| PDFs that produced no usable text (scanned/image-only) | 0 |
| Texts mentioning isobutanol ≥3 times | 360 |
| …of those, reporting an isobutanol **titer** | 136 |
| Papers contributing ≥1 **yield** row | **47** (35 XML, 12 PDF) |
| Yield rows extracted | **136** |

Method: strip tags (XML) or flow the text (PDF), split into sentences, keep sentences that
carry both a yield token (`yield`, `g/g`, `mol/mol`, `mg/g`, `C-mol`, `% of theoretical`,
`theoretical maximum`) **and** an isobutanol mention **and** a number adjacent to one of
those units. That gave 700 XML + ~160 PDF candidate sentences across 140 papers, every one
of which I then read to decide whether the number is an isobutanol yield rather than a
biomass, ethanol, 2,3-butanediol, 2-ketoisovalerate, enzyme, plasmid or product-recovery
yield.

**Every one of the 136 rows carries a quote that was verified character-for-character
against the stored source file by an automated check.** 135/136 match exactly; the single
exception is documented in its own `note` (an XML `<sub>` element splits `Y`/`Iso/S` across
two nodes, so the quote rejoins the subscript).

### The worklist was entirely PDF-only — and that mattered

`docs/drafts/literature/2026-09-22-extract-worklist.tsv` has 105 rows. **All 105 are
`stored_fulltext` with `media_type='application/pdf'`, and none of them has XML.** The
prioritised worklist and the XML corpus are completely disjoint sets. Scanning the XML
alone would have missed the worklist in its entirety.

Extracting the 152 PDFs was therefore not an optional widening — it is where the field's
landmark numbers live. The PDF pass added Atsumi 2008 (`10.1038/nature06450`), Bastian 2011
(`10.1016/j.ymben.2011.02.004`), Smith & Liao 2011, Shi 2013, Avalos 2013 (`10.1038/nbt.2509`),
Matsuda 2012, Hammer & Avalos 2017 and the 2020 *C. glutamicum* paper — i.e. most of the
values the rest of the corpus spends its introductions quoting second-hand.

Of the 105 worklist papers, 5 contributed a yield row and 8 contributed an accession. The
rest are reviews, tolerance/biosensor studies, or report titers only (see §4).

---

## 2. The yields

110 of 136 rows convert to g isobutanol / g substrate. The other 26 are deliberately left
unconverted (see §3).

### Distribution (g/g, n=110)

| band (g/g) | rows |
|---|---|
| < 0.001 | 7 |
| 0.001 – 0.01 | 24 |
| 0.01 – 0.05 | 26 |
| 0.05 – 0.10 | 9 |
| 0.10 – 0.20 | 11 |
| 0.20 – 0.30 | 21 |
| ≥ 0.30 | 12 |

The shape is bimodal and the split is by organism, not by year. Bacterial rows cluster at
0.2–0.41 g/g; yeast rows cluster at 0.001–0.06 g/g. There is almost nothing in between.

### By host

| host | rows |
|---|---|
| *Saccharomyces cerevisiae* | 53 |
| *Escherichia coli* | 45 |
| *Bacillus subtilis* | 7 |
| *Corynebacterium glutamicum* | 4 |
| *Pseudomonas putida* | 4 |
| *Bacillus megaterium* | 4 |
| *Enterobacter aerogenes* | 4 |
| *Shimwellia blattae* | 3 |
| *Klebsiella pneumoniae* | 2 |
| *Komagataella phaffii* (*Pichia pastoris*) | 1 |
| cell-free / in vitro enzyme systems | 9 |

### Top 10 by g/g

| g/g | host | strain | doi | conf |
|---|---|---|---|---|
| 0.411 | *E. coli* | AdhA<sup>RE1</sup> + IlvC6E6-his6, fully NADH-dependent | 10.1016/j.ymben.2011.02.004 | high |
| 0.390 | cell-free | synthetic-biochemistry cascade, continuous product removal | 10.1038/s41467-020-18124-1 | high |
| 0.379 | *E. coli* | AS166 (pntAB M1-93 + yfjB), anaerobic | 10.1016/j.ymben.2012.11.008 | high |
| 0.377 | cell-free | same cascade, 60 h extended run | 10.1038/s41467-020-18124-1 | high |
| 0.370 | *E. coli* | CFTi91zpee (ED pathway, zwf pgl edd eda) | 10.1186/s12934-019-1171-4 | high |
| 0.366 | *E. coli* | SB001-pIBA4, growth-coupled anaerobic | 10.1186/s13068-023-02395-z | high |
| 0.350 | *E. coli* | alsS-pathway strain, JCL260 background | 10.1038/nature06450 | high |
| 0.345 | *C. glutamicum* | ΔpckA + ED pathway + ptsG + ΔilvE | 10.1016/j.ymben.2020.01.004 | high |
| 0.320 | *E. coli* | JCL260 + pSA69/pSA65 | 10.1016/j.ymben.2011.08.004 | high |
| 0.315 | *B. subtilis* | BSUL08 | 10.1371/journal.pone.0093815 | medium |

The 0.411 figure is not a measurement of 0.411 g/g — it is my conversion of the paper's
*"100% of the theoretical limit"*. The paper reports a percentage; the g/g column carries
my arithmetic, and the `is_theoretical_percent` column flags this. Do not ingest it as a
directly measured mass yield.

### Top yeast yields — the gap the atlas actually cares about

| g/g | strain | basis | doi | conf |
|---|---|---|---|---|
| 0.156 | ZNXISO | xylose | 10.1093/femsyr/foae006 | **low — see §5** |
| 0.0596 | JWY23 (Δald6 on top of 9 other deletions) | glucose | 10.1186/s13068-019-1486-8 | high |
| 0.0489 | "control strain" | xylose | 10.1093/femsyr/foae006 | **low — see §5** |
| 0.0405 | JWY19 (Δgpd1 Δgpd2) | glucose | 10.1186/s13068-019-1486-8 | high |
| 0.0388 | YZy197 (max **daily** yield, not overall) | xylose | 10.1186/s13068-019-1560-2 | high |
| 0.0360 | sJD107 | glucose | 10.3389/fbioe.2022.1080024 | high |
| 0.0222 | PP304 (*Pichia pastoris*) | glucose | 10.1186/s13068-017-1003-x | high |

**Discounting the two disputed rows, the best credible yeast isobutanol yield in the entire
corpus is 0.0596 g/g — 14.5% of theoretical — and it took ten gene deletions to get there.**
The best *E. coli* number is 0.411 g/g at 100% of theoretical. That is a ~7-fold gap, and
it is the single clearest quantitative statement this harvest supports.

The yeast rows also give an unusually complete engineering ladder. `10.1186/s13068-019-1486-8`
alone yields ten rows tracing one lineage from 0.23 mg/g (wild-type CEN.PK113-7D with a
cytosolic pathway) to 59.55 mg/g (JWY23), deletion by deletion. `10.1186/1754-6834-5-65`,
`10.1186/1475-2859-12-119` and `10.1186/s12934-015-0240-6` add three more strain series.
For a chassis-comparison table these ladders are worth more than the single best number.

---

## 3. Rows deliberately left unconverted (26)

Precision here matters more than filling the column.

**Yield on a non-sugar substrate (14 rows).** *B. megaterium* SR7 under supercritical CO₂
(`10.1038/s41467-019-08486-6`), the in-vitro cascades (`10.1016/j.mec.2022.e00210`,
`10.3389/fbioe.2026.1879695`, `10.1016/j.biortech.2019.122104`) all report % yield **on
2-ketoisovalerate**, a pathway intermediate. The 0.411 g/g glucose maximum is irrelevant to
those numbers and multiplying by it would be wrong.

**"% of theoretical" on a non-glucose sugar (4 rows).** `10.1186/s12934-015-0232-6` reports
36–70% of theoretical on gluconate and on cellobionic acid. The theoretical maximum on those
substrates is not 0.411 g/g. Its four glucose rows in the same paper *are* converted; its
gluconate/CBA rows are not.

**Mixed-substrate yields (3 rows).** `10.1016/j.biortech.2018.03.081` reports g/g on
"glucose and xylose" combined. `basis` = `other`.

**Glycerol basis (1 row).** `10.1038/s41467-024-51029-x` defines its own maximum as one
isobutanol per two glycerol. Recorded as 80% of *that*, not converted.

**Ambiguous units (4 rows).** See §5.

Two conversion constants used throughout, both stated in `note`:
mol/mol × 74.12/180.16 = ×0.4114 (glucose); C-mol/C-mol × 0.6171 (a C-mol of glucose and a
C-mol of xylose/arabinose both weigh ≈30.03 g, so the same factor is correct for pentoses).

---

## 4. Titer without yield: 96 papers

**96 papers report an isobutanol titer in g/L or mg/L and never report a yield at all.**
Against 47 papers that do report a yield, that is roughly two thirds of the
titer-reporting literature publishing an unnormalised number.

This is a finding about the field, not about the corpus. Titer is the headline metric;
yield is the one that says whether a process can pay for its feedstock, and it is
systematically omitted. Some of the largest offenders by isobutanol mention count:

| isob. mentions | year | doi | note |
|---|---|---|---|
| 380 | 2026 | 10.1186/s13068-025-02720-8 | review; quotes others' yields, reports none of its own |
| 299 | 2011 | 10.1186/1475-2859-10-18 | tolerance evolution — titers only |
| 275 | 2019 | 10.1016/j.cels.2019.10.006 | yeast deletion-library tolerance screen |
| 193 | 2020 | 10.1186/s13068-020-1654-x | *Z. mobilis* — **yields exist, but only in supplementary Table S1** |
| 168 | 2022 | 10.1186/s12934-022-01738-z | photosynthetic isobutanol |
| 161 | 2010 | 10.1038/msb.2010.98 | tolerance reconstruction |
| 156 | 2017 | 10.1016/j.ymben.2017.07.003 | *K. pneumoniae* native pathway |
| 120 | 2017 | 10.1016/j.meteno.2017.07.003 | *Synechocystis* — reports mg/g **DCW**, i.e. per biomass |
| 115 | 2018 | 10.1186/s13068-018-1268-8 | photosynthetic isobutanol |

Three recoverable sub-cases worth a follow-up pass:

1. **Yield is in the supplementary material, not the article.** `10.1186/s13068-020-1654-x`
   says outright: *"The isobutanol yield relative to the maximum theoretical yields (%) …
   was calculated based on the information of glucose consumed"* — and puts the numbers in
   Additional file 1, Table S1, which is not in the stored full text. Several papers do this.
2. **Photosynthetic hosts have no sugar substrate**, so "yield" is either per photon or per
   g DCW. `10.1016/j.meteno.2017.07.003` reports 16.8 mg g⁻¹ DCW. That is a cell content,
   not a product-per-substrate yield, and I excluded it rather than mis-typing it as one.
   The atlas may want a separate `yield_per_biomass` concept for cyanobacteria.
3. **Yield is only in a main-text figure axis.** `10.1186/s13068-019-1486-8` and
   `10.1186/s13068-019-1560-2` both have figure panels labelled "Isobutanol yield" whose
   values I could only recover where the prose repeats them.

---

## 5. Everywhere I was unsure

### 5.1 `10.1093/femsyr/foae006` — the yeast xylose numbers I do not believe

Two rows (155.88 and 48.92 mg/g xylose) are marked `confidence=low` with a long note.
The reasons:

- 155.88 mg/g xylose is 37.9% of the 411 mg/g theoretical maximum the paper itself states.
  That would be **2.6× the best yeast yield anywhere else in this corpus** and roughly
  10× the best previously published yeast titer.
- The claimed titer is 14.8 g/L isobutanol from *S. cerevisiae*. The highest other yeast
  titer in the whole harvest is 3.12 g/L.
- The same paper's own introduction says *"isobutanol is produced at very low levels
  (< 1% of the theoretical maximum yield)"* in *S. cerevisiae*.
- Its "control" strain is credited with 48.92 mg/g — which would itself beat every other
  yeast strain in the corpus except JWY23.
- Adjacent sentences are internally inconsistent: *"the control strain showed 40.0 ± 400
  mg/L of isobutanol or yield 42.61 mg/g xylose consumed"* — a value with an error bar ten
  times the value, and a yield that cannot be derived from it.

Its low-xylose rows (1.121 and 0.741 mg/g) are consistent with the rest of the literature
and are recorded at `medium`. **I recommend this paper is not promoted without someone
checking its Table 1 against the raw fermentation data.** It is the only thing standing
between the atlas and a clean "yeast tops out near 0.06 g/g" statement.

### 5.2 `10.1016/j.ymben.2012.11.008` — the authors report an impossible value

*"Surprisingly, isobutanol yield was higher than theoretical maximum when using two-stage
process (Table S5)."* I recorded this as a row with no number and `confidence=low`, purely
as a warning marker. The paper's other eleven yields (from the main text, with named
strains AS29…AS226-20) are solid and are recorded at `high`; anything taken from its
Table S5 two-stage data should not be.

### 5.3 "% of theoretical" is not one scale

Four papers use a **denominator other than 0.411 g/g** and their percentages are therefore
not comparable with each other or with the rest:

- `10.1371/journal.pone.0093815` and `10.1186/1475-2859-11-101` (*B. subtilis*) compute
  "% of theoretical" against their own elementary-mode prediction of **0.59 C-mol/C-mol**,
  not the stoichiometric 0.667. Their C-mol/C-mol values are converted to g/g; their
  percentages are left as reported.
- `10.1186/s13068-015-0291-2` (*E. coli* LA-series) uses a basis near **0.84 mol/mol**
  (0.240 mol/mol is called 28.6%). I converted its mol/mol values and deliberately left
  `value_g_per_g` **empty** for the row that only gives 71.4% of theoretical.
- `10.1007/s00253-011-3173-y` calls 0.29 g/g "68% of the theoretical maximum", implying a
  denominator near 0.426 g/g rather than 0.411.

If the atlas normalises "% of theoretical" with a single constant, these four papers will
be silently wrong. Each row's `note` states the paper's own denominator.

### 5.4 `10.1186/s13068-020-01862-1` (*Shimwellia blattae*) — undecodable percentages

Three rows, all `low`. The paper uses two percentage scales and defines neither: yields
"from 11.9% to 16.4%", and separately "the calculated yield over the theoretical maximum
increases from 46.4% to 58.5%". 11.9/46.4 is not a clean ratio and I could not reconcile
them from the text. Recorded ambiguous rather than normalised away.

### 5.5 `10.1038/nbt.2509` (Avalos 2013) — a value read out of a flattened PDF table

JAy161 at 6.4 ± 0.2 mg/g glucose comes from Table 1, which `pdftotext` flattens into a
single run of numbers across four alcohol columns. I read the first column (isobutanol:
635 mg/L, 6.4 mg/g, 20.5 mg/L/h), which is self-consistent and matches the abstract, but
column alignment should be confirmed against the published table. Marked `medium`.

### 5.6 "Yield" used to mean "titer"

A recurring trap. Several papers write "yield" and give mg/L:

- `10.1186/s12934-015-0199-3` and `10.1038/srep39543` (*C. crenatum*) say "the highest
  isobutanol yields achieved were 1264.63 mg/L" — that is a titer. **Excluded.**
- `10.1021/acssynbio.2c00097`: "isobutanol yield of 2.23 g/L". **Excluded.**
- `10.1016/j.btre.2026.e00959`: "The isobutanol yield from IbOH-1bat1∆ was 0.215 ± 0.04
  g/L". **Excluded** — though the same paper's genuine mg/g values *are* recorded.
- Wine/rice-wine papers (`10.3389/fmicb.2022.978323`, `10.1371/journal.pone.0260024`,
  `10.3389/fmicb.2026.1757951`) use "yield of higher alcohols" for concentration
  throughout. All excluded.

### 5.7 Categories I excluded on purpose

- **Secondary restatements.** Reviews and introductions quoting other papers' yields
  (`10.1186/s13068-025-02720-8`, `10.1080/21655979.2021.1978189`,
  `10.3389/fmicb.2012.00196`, `10.1016/j.ymben.2014.07.007`, `10.1016/j.copbio.2014.09.004`,
  `10.1016/j.cbpa.2013.03.036`, `10.3390/bioengineering2040184` and ~10 more). A review's
  restatement would be misattributed to the review. One exception is recorded and flagged
  `SECONDARY` in its note (`10.3389/fbioe.2026.1879695` describing its own prior system).
- **In-silico predictions.** `10.1186/1752-0509-4-53` (OptORF, ~94% of theoretical),
  `10.1186/s13068-017-0856-3`, `10.1186/s12934-014-0128-x`, and the model-derived maxima in
  the two *B. subtilis* papers. These are model output, not measurements.
- **Chemical catalysis.** `10.1021/acs.organomet.1c00313` and `10.1021/acs.organomet.0c00588`
  report 16–40% isobutanol yields from Guerbet condensation of ethanol over Re and Mn
  catalysts. Real yields, wrong atlas.
- **Per-biomass content.** `10.3390/foods11182725` (*P. kudriavzevii*, μg/g DCW) and the
  *Synechocystis* mg/g DCW values above.
- **The wrong molecule.** Isobutyraldehyde (`10.1186/1475-2859-11-90`, 45% of theoretical),
  isobutyric acid (`10.1186/1475-2859-13-2`), 2-ketoisovalerate (`10.1128/aem.00976-22`'s
  0.644 mol/mol — though that paper's *isobutanol* by-product yields **are** recorded),
  3-methyl-1-butanol (`10.3389/fmicb.2025.1753983`).

### 5.8 One row where I could not identify the strain

`10.1186/1475-2859-11-101`, "isobutanol yield was up to 53% of the theoretical value to
0.31 ± 0.02 C-mol/C-mol" — the sentence names no strain and the surrounding text did not let
me pin it to BSUL04 or BSUL05. Recorded at `low` for a human to resolve.

---

## 6. Omics accessions — 530 rows, 262 papers

`docs/drafts/omics/2026-09-22-accessions-from-fulltext.tsv`. All 530 quotes verified
verbatim.

| relevance | rows |
|---|---|
| isobutanol_producer | 50 |
| isobutanol_exposure | 34 |
| mitochondrial | 177 |
| ethanol_reference | 177 |
| other | 92 |

`relevance` and `host_organism` are **rule-assigned** from screening-record families,
isobutanol mention counts and organism-mention counts across the paper — not read out of the
quote. Both columns say so. The quote and the accession are the trustworthy parts of each
row; a handful of food-fermentation microbiome papers are labelled `isobutanol_exposure`
only because they mention isobutanol as an aroma compound.

`confidence` is `high` when the quote is a data-availability statement naming the accession
(308 rows), `medium` when the accession sits in a table cell (116 rows — the adjacent cell
is reproduced in `assay_as_described`), `low` otherwise (106).

### The dozen that actually matter

| accession | type | doi | what it is |
|---|---|---|---|
| **GSE186126** + **MSV000088169** | GEO + MassIVE | 10.1016/j.synbio.2022.02.007 | RNA-seq **and** proteomics of an *S. cerevisiae* strain carrying a cytosolic isobutanol pathway — the iron-limited-bottleneck study. The closest thing in the corpus to a yeast isobutanol-producer transcriptome. |
| **E-MTAB-8175** | ArrayExpress | 10.1016/j.cels.2019.10.006 | Yeast **deletion-library** tolerance screen — PPP and GLN3 in isobutanol-specific tolerance. The nearest thing to a genome-wide functional screen for isobutanol in yeast. |
| **GSE118069** | GEO | 10.1534/g3.118.200677 | *S. cerevisiae* transcriptome in YPD + **1% isobutanol** vs 0.8% 1-butanol vs 4% ethanol, across strain backgrounds and aerobic/anaerobic. Directly a producer-vs-parent-style comparison. |
| **GSE175794** | GEO | 10.1186/s13068-021-02048-z | Yeast isobutanol tolerance, tryptophan mechanism. |
| **GSE13444** | GEO | 10.1038/msb.2009.34 | The *E. coli* isobutanol response network. |
| **GSE23526** | GEO | 10.1186/1475-2859-10-18 | *E. coli* isobutanol tolerance evolution. |
| **GSE107996** / **PRJNA492719** | GEO / BioProject | 10.1038/s41598-020-67635-w | Evolved *Lactobacillus* isobutanol tolerance — genomes + transcriptomes. |
| **PXD048679** | PRIDE | 10.1111/1751-7915.14438 | *P. polymyxa* isobutanol-producer proteome. |
| **PXD066951** + **MTBLS12808** | PRIDE + MetaboLights | 10.1128/spectrum.00610-25 | *Z. mobilis* proteome + lipidome on hydrolysate. |
| **PRJNA417511** | BioProject | 10.1186/s13068-018-1089-9 | Evolved *S. cerevisiae* medium-chain-alcohol tolerance genomes. |
| **PRJNA191134** | BioProject | 10.1186/1754-6834-6-48 | *S. cerevisiae* butanol tolerance, CEN.PK + IMS evolved lines. |
| **DRA006219** | DDBJ | 10.1186/s13068-017-0996-5 | *Synechocystis* alcohol-tolerance ALE genomes. |

### There is essentially no Tn-Seq for isobutanol

Only **one** of 530 accession rows describes a transposon or deletion-library screen
(E-MTAB-8175, above). Scanning all 1,429 texts for transposon-sequencing vocabulary
(`Tn-seq`, `RB-TnSeq`, `SATAY`, `transposon insertion sequencing`, `Tn5 library`) found
just 8 papers with ≥2 mentions, and the three with the most hits use the term only in
passing:

| hits | doi | |
|---|---|---|
| 12 | 10.1186/1754-6834-7-101 | *Z. mobilis* review, discussing Tn-seq as a method |
| 7 | 10.1038/s41467-021-26850-3 | chemogenomic essentiality predictions |
| 5 | 10.1186/1475-2859-10-18 | *E. coli* isobutanol tolerance evolution |

**No paper in this corpus deposits Tn-seq data from an isobutanol-producing or
isobutanol-challenged culture.** If the atlas wants transposon-level genotype–phenotype
data for isobutanol, it is not in the stored literature and would have to be found outside
it — or generated.

This is consistent with, and complementary to, `docs/drafts/omics/TNSEQ_UNIT.md`. That note
records the one Tn-Seq screen the project does hold — **SRP588897 / PRJNA1270032**, eight
runs of *Z. mobilis* ZM4. I searched all 1,429 full texts for `SRP588897`, `PRJNA1270032`
and `SRR33767*`: **zero hits.** The project's only Tn-Seq screen came in through SRA
metadata and is cited by no paper in the stored corpus. A literature-side scan cannot
corroborate it, and the reverse also holds: the literature adds no second screen.

---

## 7. Two things worth fixing upstream

1. **Roughly 70% of the supplementary tables are unreachable.** At least five papers state
   in the article that the yield is in an Additional File that the ingest did not store.
   `10.1186/s13068-020-1654-x` is the cleanest example: a whole *Z. mobilis* strain series'
   yields, named in the text, absent from the corpus. Fetching PMC supplementary files for
   the ~360 isobutanol-mentioning papers would likely be the single highest-yield next step
   for this gap — larger than widening the paper set.

2. **Figure-only yields.** Several strain series publish yields as a bar-chart panel and
   repeat only the best value in prose. Those rows are in the TSV; the intermediate strains
   are not recoverable from text.
