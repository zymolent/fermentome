# SRA study inventory — condition metadata for the 172 runs in `sra_run`

Fetched 2026-09-22 from NCBI E-utilities (`efetch db=sra` experiment packages for all
172 run accessions, plus `efetch db=biosample` for all 122 distinct BioSamples).
Raw XML: `C:\Users\kangk\AppData\Local\Temp\claude\d--project-yeast-alcohol-db\978b41f1-b5be-464e-8302-a6e1c3e1ae8b\scratchpad\sra_xml\`
Per-run table: `2026-09-22-run-attributes.tsv` (172 rows, 51 columns).

All 172 runs resolved to an SRA EXPERIMENT_PACKAGE; none were missing.

**Reading rule used throughout.** "Declared" means the value is present in a
`SAMPLE_ATTRIBUTE` / BioSample `Attribute` element, or in the submitter-written
SAMPLE/EXPERIMENT title. "Inferred" means I read it out of a free-text string and
it is marked as such. Where a submitter did not state something, this file says
"not stated in the metadata" and does not fill the gap from the study abstract or
from the associated publication.

---

## Coverage at a glance

| | runs |
|---|---|
| total | 172 |
| carry a literal `genotype` attribute | 95 |
| carry `genotype` **or** `strain`/`substrain`/`isolate` with a non-placeholder value | 135 |
| carry a treatment-type attribute (`treatment`, `agent`, `compound`, `growth_condition`, `*_addition`) | 81 |
| carry neither `genotype` nor a treatment-type attribute | 50 |
| carry a time attribute (`time_point`, `timepoint`, `experiment_day`, `age`) | 44 |
| have an empty SAMPLE title | 37 |

29 runs (all of SRP272487) carry the literal string `strain: missing`, which the
submitter wrote — it is a declared non-value, not an absence, and it is counted as
absent above.

---

## Per-study assessment

### SRP321884 — n=46 runs / 24 BioSamples — *Saccharomyces cerevisiae* S288C — RNA-Seq (cDNA, SINGLE)
**"Tryptophan plays a central role in yeast's tolerance to isobutanol"** (PRJNA733673)

Declared attributes on every run: `source_name`, `genotype`, `tryptophan_addition`,
`isobutanol_addition`, `replicate`.

**Usable for (i) engineered-vs-parent and (ii) isobutanol-vs-untreated — this is the
strongest study in the set.** It is a full 2×2×2 factorial, and every factor is
declared as its own attribute rather than buried in a title.

- genotype: `"WT"` (24 runs) vs `"Tryptophan synthase (TRP5) defective"` (22 runs);
  `source_name` repeats it as `"Wild type"` vs `"TRP5 defected strain"`.
- treatment: `isobutanol_addition` = `"Yes"` (24) / `"No"` (22), and independently
  `tryptophan_addition` = `"Yes"` (23) / `"No"` (23).

Eight groups, **3 biological replicates (BioSamples) each**, `replicate` declared as
`"1"`/`"2"`/`"3"`:

| genotype | Trp | isobutanol | BioSamples | runs |
|---|---|---|---|---|
| WT | No | No | 3 | 6 |
| WT | Yes | No | 3 | 6 |
| WT | No | Yes | 3 | 6 |
| WT | Yes | Yes | 3 | 6 |
| TRP5 defective | No | No | 3 | 5 |
| TRP5 defective | Yes | No | 3 | 5 |
| TRP5 defective | No | Yes | 3 | 6 |
| TRP5 defective | Yes | Yes | 3 | 6 |

Note the run count exceeds the BioSample count: most GSM samples were sequenced in two
runs (e.g. SRR14687189 and SRR14687190 are both `GSM5348134`, `"1. WT"`). Two samples
(`"15. Sc12"`, `"16. Sc12+Trp"`) have a single run. **Runs must be collapsed to
BioSample before any replicate-level statistics**, or the technical duplicates will be
counted as biological replicates.

(iii) time course: not stated in the metadata.

This is a tolerance study, not a production study — the "engineered" strain is a TRP5
knockout, so the producer-vs-parent axis here is *tolerance mutant vs wild type*, not
*isobutanol producer vs non-producer*.

### SRP342112 — n=33 runs / 33 BioSamples — *S. cerevisiae* — RNA-Seq (cDNA, PAIRED)
**"RNAseq of engineered S. cerevisiae strains for isobutanol production"** (PRJNA772701)

Declared attributes on every run: `source_name` (`"frozen stock"`, constant),
`genotype`, `timepoint`/`time_point` (duplicate keys, identical values), `replicate`.

**Usable for (i) producer-vs-parent and (iii) time course. Not usable for (ii)** — no
chemical treatment factor is declared; every run is `source_name: frozen stock`.

Four declared genotypes, one of which is the unengineered parent:

| sample prefix | declared `genotype` | role |
|---|---|---|
| Y795 | `CEN.PK113-5D URA3+` | **parent / control** (no isobutanol cassette in the declared genotype string) |
| Y797 | `Y795 with HO::pADH1-ScILV2-tCYC1 _pPGK1-ScILV3-tTEF2_pTEF2CoxIV-LlAdhA29C8_tTDH3_pTDH3CovIV-ScARO10-tTEF1_pTEF1-ScILV5-tTUB1` | producer |
| Y799 | `Y795 with HO::pADH1-ScILV2N54-tCYC1 _pPGK1-ScILV3N19-tTEF2_pTEF2-LlAdhA29C8tTDH3_pTDH3-ScARO10-tTEF1_pTEF1-EcIlvC6E6-tTUB1` | producer |
| Y812 | `Y795 with HO::pADH1-ScILV2N54-tCYC1 _pPGK1-ScILV3N19-tTEF2_pTEF2-LlAdhA29C8tTDH3_pTDH3-ScARO10-tTEF1_pTEF1-ScILV5N48-tTUB1` | producer |

The parent relationship is **declared, not inferred**: three genotype strings literally
begin `"Y795 with ..."`, and Y795's own genotype is the bare `CEN.PK113-5D URA3+`.

Three declared timepoints, `"T3 - hour 4"`, `"T6 - hour 10"`, `"T14 - hour 26"`, with
**n per genotype×timepoint group**:

| genotype | T3 (h4) | T6 (h10) | T14 (h26) |
|---|---|---|---|
| Y795 (parent) | 3 | 3 | 3 |
| Y797 | 3 | 3 | 3 |
| Y799 | 2 | 3 | 3 |
| Y812 | 3 | 2 | 2 |

Totals: Y795 n=9, Y797 n=9, Y799 n=8, Y812 n=7. The missing runs are simply absent from
the submission; no reason is stated in the metadata.

**Inferred, flagged as such:** the abstract distinguishes mitochondrial from cytosolic
pathway localisation and NADPH- from NADH-dependent KARI. The `CoxIV` targeting
sequences in Y797's genotype string and their absence from Y799/Y812, and the `EcIlvC6E6`
vs `ScILV5N48` reductoisomerase, are consistent with that — but **no attribute names
localisation or cofactor**, so any localisation/cofactor grouping is my reading of the
genotype string, not the submitter's declaration.

### SRP272487 — n=29 runs / 29 BioSamples — *Escherichia coli* — AMPLICON (PCR, PAIRED)
**"Engineering regulatory networks for complex phenotypes in E. coli"** (PRJNA644061)

Declared attributes: `strain: "missing"` (all 29 — the submitter wrote the literal word),
`sample_type: "mixed culture"`, `isolation_source`, `collection_date`,
`geo_loc_name`, `biosamplemodel`. SAMPLE titles are **empty on all 29 runs**; the
experiment titles carry the labels.

**Usable for (ii) a before/after selection contrast only. Not usable for (i) — no
genotype or strain is declared at all.**

Declared `isolation_source` values, which line up exactly with `collection_date` and the
EXPERIMENT titles:

| `isolation_source` | experiment title | collection date | n |
|---|---|---|---|
| `"before isobutanol sensor condition"` | `Sensor_preselection` | 2019-10-24 | 10 |
| `"after isobutanol sensor condition"` | `Sensor_postselection` | 2019-10-25 | 10 |
| `"before isobutanol condition"` | `IBA_preselection` | 2019-09-12→ listed 2019-09-07 | 2 |
| `"after isobutanol condition"` | `IBA_postselection` | 2019-09-12 | 7 |

This is a pooled-library selection experiment (`sample_type: mixed culture`), so the
before/after pairs are library states, not replicate cultures. The **2 vs 7 imbalance in
the IBA arm is what the submitter declared** — no explanation is stated in the metadata.
What the 10 "Sensor" amplicons and the 9 "IBA" amplicons are libraries *of* is not
stated in the metadata; `strain: missing` blocks any genotype annotation.

### SRP156315 — n=12 runs / 12 BioSamples — *S. cerevisiae* — RNA-Seq (cDNA, SINGLE)
**"Genotype-by-environment-by-environment interactions in the Saccharomyces cerevisiae
transcriptomic response to alcohols and anaerobiosis"** (PRJNA484406)

Declared attributes: `strain`, `agent: "Isobutanol"` (all 12), `compound: "Isobutanol"`
(all 12), `source_name: "Gasch Lab/ GLBRC"`.

**Usable for a three-way strain contrast. NOT usable for (ii)** — every run in this
subset is isobutanol-treated; there is no untreated control among these 12 runs. (The
parent BioProject may hold untreated runs; they are not in `sra_run`.)

- `strain` = `"NCY3290"` (n=4), `"IL01"` (n=4), `"Y7568"` (n=4).

These are three different yeast backgrounds, **not a producer and its parent** — no
attribute declares an engineering relationship between them, so this does not satisfy (i)
as a producer-vs-parent contrast.

**Declared in the SAMPLE title but not in any attribute:** an aerobic/anaerobic split,
e.g. `"Isobutanol_NCY3290_ANAE_R1 [RNA-Seq_3strains]"` vs
`"Isobutanol_NCY3290_AER_R1 [RNA-Seq_3strains]"`, giving 2 aerobic + 2 anaerobic per
strain (R1/R2 replicates). Using it means parsing the title string; **no
`growth_condition` or oxygen attribute exists on these samples.**

### SRP588897 — n=8 runs / 8 BioSamples — *Zymomonas mobilis* ZM4 — Tn-Seq (PCR, SINGLE)
**"Tn-seq chemical genomics in Zymomonas mobilis"** (PRJNA1270032)

Declared attributes: `genotype: "WT conjugated with pRL27"` (constant, all 8),
`strain: "PK15455"`, `temp: "30C"`, `sample_type: "DNA"`, `sample_replicate_id`,
`library_id`.

**Not usable for (i)** — the genotype is constant. **Not usable for (ii) as
treated-vs-untreated** — there is no 0% / no-isobutanol control among these 8 runs.

The only varying declared fields are `sample_replicate_id` and the SAMPLE title, which
encode an **isobutanol dose series**: `"Isobutanol.1.25%_Rep_A"`/`"_Rep_B"`,
`"Isobutanol.5%_Rep_A"`/`"_Rep_B"`, `"Isobutanol.7.5%_Rep_A"`/`"_Rep_B"`,
`"Isobutanol.10%_Rep_A"`/`"_Rep_B"` — **4 doses × 2 replicates**. The dose is declared
(in the title and replicate id), but as free text; there is no `dose` or `concentration`
attribute. Usable as a **dose-response series without an untreated reference**.

### ERP116462 — n=8 runs / 8 BioSamples — *S. cerevisiae* — RNA-Seq (RANDOM, PAIRED)
**"Transcriptional responses to isobutanol in Saccharomyces cerevisiae wild type and
gln3 deletion strains"** (PRJEB33652)

Declared attributes: `genotype`, `growth_condition`, `age: "12"` (constant),
plus ENA checklist boilerplate (`cell_line`, `tissue`, `organism_part`, `common_name`).

**Usable for both (i) and (ii), as a clean 2×2 — the smallest fully-crossed design here.**

- genotype: `"gln3 deletion"` (n=4) vs `"wild type genotype"` (n=4)
- treatment: `"SC medium with 1.3% (v/v) isobutanol"` (n=4) vs
  `"SC medium without isobutanol"` (n=4)

| group | n | run accessions |
|---|---|---|
| wild type, no isobutanol | 2 | ERR3450098, ERR3450099 |
| wild type, 1.3% isobutanol | 2 | ERR3450100, ERR3450101 |
| gln3∆, no isobutanol | 2 | ERR3450094, ERR3450095 |
| gln3∆, 1.3% isobutanol | 2 | ERR3450096, ERR3450097 |

**2 replicates per group.** The SAMPLE titles agree (`WT(0)_rep1`, `WT(i-BuOH)_rep1`,
`gln3(0)_rep1`, `gln3(i-BuOH)_rep1`). `age: "12"` is declared with no unit — whether it
means 12 hours is not stated in the metadata. As with SRP321884 this is a deletion mutant
vs wild type (tolerance), not a producer vs its parent.

### ERP109305 — n=8 runs / 8 BioSamples — *Fusarium graminearum* — RNA-Seq (cDNA, PAIRED)
**"RNA-seq of Fusarium graminearum under predation by the springtail Folsomia candida
against untreated controls"** (PRJEB27245)

Declared attributes: `growth_condition`, `replicate`, plus ENA boilerplate.

**Structurally a clean treated-vs-control design — but it is off-topic for this atlas.**
The treatment is `"with Folsomia candida"` (n=4: ERR2624984–87, titled `TreatedA`–`D`)
vs `"without Folsomia candida"` (n=4: ERR2624980–83, `controlA`–`D`), 4 replicates per
group. The organism is a filamentous fungus and the treatment is springtail predation.
**Nothing in this study's declared metadata mentions isobutanol, ethanol or any alcohol.**
No genotype is declared. Flagging it for the curator: these 8 runs look like a
false-positive carry-over from the SRA Run Selector export and should be reviewed for
removal from `sra_run` rather than annotated.

### SRP591874 — n=6 runs / 6 BioSamples — *Zymomonas mobilis* ZM4 — OTHER (PCR, PAIRED)
**"CRISPRi chemical genomics in Zymomonas mobilis"** (PRJNA1276497)

Declared attributes: `isolate: "sJMP2618, sJMP2619 & sJMP2620 libraries"` (constant),
`strain: "ZM4"`, `sample_type: "CRISPRi library"`, `temp: "30C"`, `sample_replicate_id`,
`isolation_source`. No `genotype` attribute at all.

**Not usable for (i)** — one pooled library, constant across all 6 runs. **Not usable for
(ii) as treated-vs-untreated** — no no-isobutanol control among these 6.

Same shape as SRP588897: a dose series declared only in the SAMPLE title —
`"CRISPRi in Zymomonas mobilis ZM4: Isobutanol 1.25% rep 1"`/`"rep 2"`, and the same for
`5%` and `7.5%`. **3 doses × 2 replicates.** The `sample_replicate_id` values
(`P16.2_A4_B`, `P35.2_B4_B`, …) are plate coordinates and do not by themselves decode the
dose. Companion study to SRP588897 (same lab, same doses, CRISPRi instead of Tn-seq), but
nothing in either record declares that link.

### SRP518086 — n=6 runs / 6 BioSamples — *E. coli* K-12 MG1655 — RNA-Seq (cDNA, PAIRED)
**"Altering the sigma D factor of RNA polymerase and thereby improving the tolerance of
E. coli strains to isobutanol."** (PRJNA1132130)

Declared attributes: `strain: "K12 MG1655"`, `substrain: "MG1655"` (both constant),
`sample_type: "cell culture"`, and `isolate`, which is the only informative field.
SAMPLE titles are **empty on all 6**; EXPERIMENT titles are informative.

**Usable for both (i) and (ii) at n=2 per group**, but only by reading the free-text
`isolate` string — there is no `genotype` and no `treatment` attribute.

| `isolate` (declared, verbatim) | experiment title | runs | n |
|---|---|---|---|
| `"MG1655 grew in the LB media, replicate 1/2"` | `RNA-Seq of E. coli MG1655 in LB media` | SRR29711605, SRR29711606 | 2 |
| `"MG1655 grew in the condition of solvent stress, replicate 1/2"` | `RNA-Seq of E. coli MG1655 in solvent stress medium` | SRR29711603, SRR29711604 | 2 |
| `"MG1655 with rpoD-33 grew in the condition of solvent stress, replicate 1/2"` | `RNA-Seq of E. coli MG1655 with D-33 in solvent stress medium` | SRR29711607, SRR29711608 | 2 |

Two contrasts are available: **parent MG1655 vs engineered MG1655+rpoD-33, both under
solvent stress** (2 vs 2), and **MG1655 in LB vs MG1655 under solvent stress** (2 vs 2).
There is no rpoD-33-in-LB arm, so the design is incomplete — the genotype and treatment
effects cannot be separated from their interaction.

**What "solvent stress" consists of is not stated in the metadata** — no concentration,
no named solvent. The study title says isobutanol; the attributes do not.

### SRP368097 — n=4 runs / 1 BioSample — *E. coli* K-12 MG1655 — OTHER (PAIRED)
**"Deep sequencing and fitness calculation for plasmids carrying the CREATE cassette from
the enriched tolerant strains under different pressures by using Illumina protocol"**
(PRJNA824516)

Declared attributes: `strain: "K-12"`, `substrain: "MG1655"`, `type: "plasmids"`,
`treatment: "PCR"`, `source_name: "Escherichia coli"`. SAMPLE title `"Isobutanol"`.

**(iv) nothing at all — ungroupable.** All 4 runs are the *same BioSample*
(one GSM, `GSM6033850`), with identical attributes. The `treatment` attribute exists but
its value is `"PCR"` — a library-prep step, not an experimental treatment. No genotype,
no dose, no control arm, no time point. The study title promises "different pressures";
**no pressure or condition is declared on any of these 4 runs**. These are 4 technical
runs of one plasmid amplicon pool and cannot be split into groups from their own metadata.

### SRP126584 — n=4 runs / 4 BioSamples — *Lactococcus cremoris* — RNA-Seq (cDNA, PAIRED)
**"Designing of Lactococcus lactis platform for isobutanol production using multiple
rounds of adaptive laboratory evolution"** (PRJNA422127)

Declared attributes: `strain`, `culture: "late log phase"` (constant),
`source_name: "bacterial cell"`.

**Usable for (i) evolved-vs-parent at n=2 vs n=2. Not usable for (ii)** — no treatment
attribute; all four are `culture: late log phase` with no isobutanol exposure declared.

- `strain: "wild type"` (n=2) — SRR6370305 (`WT/rep1`), SRR6370306 (`WTD/WT rep2`)
- `strain: "4% isobutanol tolerant"` (n=2) — SRR6370307 (`4B0 rep1`), SRR6903496 (`4B4 rep1`)

Caveat the curator should see: the two "tolerant" runs have **different sample titles,
`4B0` and `4B4`**, which look like two different evolved isolates rather than two
replicates of one. The `strain` attribute gives them the same value. Whether 4B0 and 4B4
are the same strain is **not stated in the metadata**. Treating them as n=2 replicates
assumes they are; treating them as n=1 each leaves no replication.

### SRP343868 — n=3 runs / 3 BioSamples — *S. cerevisiae* — OTHER (SINGLE)
**"Comparative chemical-genomic profiling of plant-based hydrolysate toxins enables
predictive assessment of responses to complex mixtures"** (PRJNA776529)

Declared attributes: `strain: "3DeltaAlpha"` (constant), `treatment:
"0.75% Isobutanol (IBA)"` (constant, all 3), `base_media: "1x SynBase"`,
`experiment_day` (`ChemGen003/004/005`), `control_1`, `control_2`, `source_name`.

**Not usable for (i)** — one pooled deletion-collection strain. **Not usable for (ii) as
it stands**, because all 3 runs are treated: `source_name` reads
`"3DeltaAlpha strains pool, 0.75% IBA, replicate 1/2/3"`.

However — and this is the one place where the submitter declared a pointer to controls —
each run names its own controls in `control_1`/`control_2`:

| run | `experiment_day` | `control_1` | `control_2` |
|---|---|---|---|
| SRR16642822 | `ChemGen003` | `Control2_CG003` | `Control3_CG003` |
| SRR16642820 | `ChemGen004` | `Control2_CG004` | `Control3_CG004` |
| SRR16642818 | `ChemGen005` | `Control1_CG005` | `Control3_CG005` |

**Those named control samples are not among the 172 runs in `sra_run`.** So the treatment
contrast is declared but the control arm would have to be fetched from the rest of
PRJNA776529 before it can be used. `experiment_day` is a batch variable, not a time
course — the 3 runs are 3 replicates run on 3 different days, not 3 timepoints.

### SRP140506 — n=2 runs / 2 BioSamples — *E. coli* — AMPLICON (PCR, PAIRED)
**"CRISPRi pooled screening based functional genomics method in bacteria"** (PRJNA450392)

Declared attributes: `strain: "K12 MG1655"`, `sample_type: "mixed culture"`,
`isolation_source: "lab culture"`, `roles_in_the_project`. SAMPLE titles empty.

**(iv) nothing at all as a contrast.** Both runs are the same condition:
`roles_in_the_project` = `"Genome-wide library screen in MOPS + 4 g/L isobutanol,
replicate 1"` and `"... replicate 2"`. So: **1 group, n=2 replicates, isobutanol dose
declared (4 g/L) but no untreated control and no genotype variation** — the CRISPRi
library composition is not declared as a genotype. Ungroupable on its own.

### SRP003312 — n=2 runs / 2 BioSamples — *E. coli* K-12 MG1655 — WGS (RANDOM, PAIRED)
**"Whole genome sequencing of isobutanol high tolerance Escherichia coli strain"**
(no BioProject recorded in `sra_run`)

Declared attributes: `strain: "K-12"` on both — identical, so the attributes alone do not
separate the runs.

**Usable for (i) mutant-vs-parent at n=1 vs n=1, from the SAMPLE titles only:**

- SRR064642 — `"Isobutanol production host JCL260 (wild-type)"`
- SRR064643 — `"Isobutanol tolerance mutant SA481"`

The parent/mutant relationship is declared in the titles (`(wild-type)` vs
`tolerance mutant`), not in an attribute. **n=1 per group, WGS** — this is a variant-calling
pair, not an expression comparison. No treatment and no time point are stated in the
metadata.

### SRP162375 — n=1 run / 1 BioSample — *Lactococcus cremoris* — WGS (PCR, PAIRED)
**"Genome sequencing of 4B0 Lactococcus lactis strain (4% isobutanol tolerant srain grown
in absence of isobutanol)."** (PRJNA492719)

Declared attributes: `strain: "4B0"`, `isolation_source: "4% isobutanol tolerant sttrain
was obtained after evolution ..."`, plus MIGS environmental boilerplate in `attr_other`
(`env_biome: "Plants and animal habitats"`, `env_feature: "Laboratory isolate"`, etc.).

**(iv) nothing at all — a single run cannot form a contrast.** It is the genome of the
same `4B0` isolate that appears in SRP126584's RNA-Seq. Usable only as a reference
genome for that study, and **that cross-study link is my inference from the shared strain
label `4B0`; neither record declares the other.**

---

## Summary tables

### Studies usable for a producer/engineered-vs-parent contrast (i)

| study | engineered group (n runs) | parent/WT group (n runs) | basis |
|---|---|---|---|
| SRP342112 | Y797 n=9, Y799 n=8, Y812 n=7 | Y795 `CEN.PK113-5D URA3+` n=9 | `genotype` attribute; producers declared as `"Y795 with ..."` |
| SRP321884 | TRP5-defective n=22 runs / 12 BioSamples | WT n=24 runs / 12 BioSamples | `genotype` attribute |
| ERP116462 | `gln3 deletion` n=4 | `wild type genotype` n=4 | `genotype` attribute |
| SRP518086 | `MG1655 with rpoD-33` n=2 | `MG1655` n=2 (both solvent-stressed) | free-text `isolate` attribute |
| SRP126584 | `4% isobutanol tolerant` n=2 | `wild type` n=2 | `strain` attribute; see 4B0/4B4 caveat |
| SRP003312 | `SA481` n=1 | `JCL260 (wild-type)` n=1 | SAMPLE title only; WGS |

Only **SRP342112** is a genuine *isobutanol-producer vs non-producing parent* contrast.
SRP321884, ERP116462, SRP126584 and SRP003312 are *tolerance* mutants vs wild type;
SRP518086 is a *tolerance* engineering (sigma factor) contrast.

### Studies usable for a treatment-vs-control contrast (ii)

| study | treated (n) | control (n) | basis |
|---|---|---|---|
| SRP321884 | `isobutanol_addition: Yes` n=24 | `isobutanol_addition: No` n=22 | dedicated attribute; crossed with genotype and Trp |
| ERP116462 | `SC medium with 1.3% (v/v) isobutanol` n=4 | `SC medium without isobutanol` n=4 | `growth_condition` attribute |
| SRP518086 | `solvent stress` n=4 (2 parent + 2 rpoD-33) | `LB media` n=2 (parent only) | free-text `isolate`; solvent unnamed |
| SRP272487 | `after isobutanol (sensor) condition` n=17 | `before isobutanol (sensor) condition` n=12 | `isolation_source`; pooled libraries, before/after not replicates |
| ERP109305 | `with Folsomia candida` n=4 | `without Folsomia candida` n=4 | `growth_condition`; **not an alcohol study — off-topic** |

### Dose series with no untreated reference

SRP588897 (4 doses × 2, Tn-Seq), SRP591874 (3 doses × 2, CRISPRi) — dose declared in the
SAMPLE title only. SRP140506 (1 dose, n=2).

### Ungroupable from their own declared metadata

SRP368097 (4 technical runs of one BioSample; `treatment: "PCR"`), SRP162375 (n=1),
SRP343868 (controls named but not in this run set), SRP140506 (single condition),
SRP591874 and SRP588897 (no untreated arm), SRP156315 (no untreated arm).
