# The two landmark builds, as rows that would have to exist — a draft

2026-09-22. **Draft only. Nothing here is promoted, and nothing here may be promoted from this
file**: every row below needs an `extraction` and a `span` behind it, which needs
`fermdb extract` to run on these two papers, which is another agent's this round.

Phase 1b's clause 1 — *"the landmark E. coli and S. cerevisiae builds each reproduce their
paper's titer, yield and conditions"* — does not name its papers. PLAN.md phase 1 names an
*E. coli* landmark and an *S. cerevisiae* landmark; the 2026-09-21 handover names **Atsumi 2008**
and **Avalos 2013**. Both are stored full text, both were read for this draft, and the figures
below are quoted from them.

**Neither is extracted.** `extraction` holds eleven rows across eight publications and neither
DOI is among them; `span` holds 267 rows across the same eight. So the corpus contains zero rows
that could reproduce either paper, and the numbers below have no `span` behind them yet.

**What the offsets are.** Each quote was resolved against the text
`fermdb.extract.harness.load_source_text` returns for that publication — the same bytes an
extraction would be given, from the same checksummed PDF. Every offset below was checked to
re-resolve exactly. They are candidate spans, not stored ones: nothing has written them to `span`.

---

## 1. Atsumi, Hanai & Liao 2008 — the *E. coli* landmark

`doi:10.1038/nature06450` · PMID 18172501 · *Nature* 451:86–89 · full text stored, checksum
`bd4300b9...`, `oa_status='closed'` (manual upload).

### What the paper reports

| quantity | value | where | span into stored text |
|---|---|---|---|
| titer | ~300 mM (22 g/L) isobutanol, 112 h | results | `[7969, 8039)` |
| yield | 0.35 g isobutanol per g glucose, 40–112 h | results | `[8318, 8392)` |
| yield, as % of max | 86% of the theoretical maximum | results | `[8417, 8456)` |
| **the ceiling itself** | "The theoretical maximum yield of isobutanol is 0.41 g g⁻¹" | Fig. 2 legend | `[16294, 16352)` |
| earlier build's yield | 0.21 g/g, 16–24 h, ~30 mM | results | `[7310, 7432)` |
| conditions | M9 + 36 g/L glucose, shake flask, 30 °C, 0.1 mM IPTG | Fig. 2 legend | `[15943, 16030)` |
| host | JCL260 = JCL88 + ΔpflB; JCL88 = JCL16 Δadh Δldh Δfrd Δfnr Δpta | methods summary | `[18456, 18497)` |

**The 0.41 figure is the paper's own.** PLAN.md B.2's 0.411 g/g is cited in
`product_theoretical_yield` only to PLAN.md — *"an internal document, not to an external pathway
reference checked in this session"*, and the row's `confidence` is `unverified` because of it.
This sentence is that external reference, in the *E. coli* landmark itself. Promoting it would
raise that row's confidence off `unverified` on evidence rather than on assertion. **That is a
curation act and is not done here.**

Independent arithmetic agrees: 0.35 / 0.41142 = 85.1%, against the paper's stated 86%.

### The draft `pathway_configuration`

```yaml
id:                      (assigned on promotion)
name:                    "F_single_compartment_host configuration from doi:10.1038/nature06450"
pathway_id:              YAA:PWY:isobutanol-valine-ehrlich
product_id:              YAA:PRODUCT:isobutanol
compartment_strategy_id: F_single_compartment_host   # E. coli has no compartment to choose
host_strain_id:          (new strain: JCL260, organism YAA:ORG:ecoli-k12-mg1655 —
                          JCL16 is BW25113-derived, so a K-12 organism row fits and the
                          substrain difference belongs in strain_lineage, not in organism)
description:             "enzymes as reported: alsS (Bacillus subtilis), ilvC, ilvD,
                          kivd (Lactococcus lactis), ADH2 (S. cerevisiae); localization as
                          reported: none stated — single-compartment host"
zone:                    R
confidence:              (a curator's, on review — not an agent's)
```

Deletions, as `modification` rows on the host strain: `adh`, `ldh`, `frd`, `fnr`, `pta`, `pflB`,
all type `deletion`.

### The draft measurements

Three, all `strain_id` = the JCL260 row, `publication_id` = `doi:10.1038/nature06450`, `zone='R'`:

| quantity_kind | value | unit | basis | source_locator |
|---|---|---|---|---|
| `titer` | 22 | `g/L` | (n/a) | text |
| `yield` | 0.35 | `g/g` | `consumed` **if the paper says consumed, else `unknown`** | text |
| `yield` | 0.86 | (fraction) | `theoretical_max_pct` | text |

**The basis is the open question and it is not answerable from the sentence.** "0.35 (g
isobutanol per g glucose) between 40 h and 112 h" does not say consumed or supplied, and the
schema forbids NULL. Under CONVENTIONS the honest value is `'unknown'`, and an `'unknown'` basis
is not comparable across studies — so *"reproduces the paper's yield"* is satisfiable and
*"reproduces it comparably"* is not, on this paper, without the supplementary data.

Titer in mM is also reported (~300 mM) and is the same number in a different unit; one Zone R row
per reported figure, not one per unit.

### What the bound check would say

0.35 g/g against the 0.411 g/g ceiling → **pass**, at 85.2% of it — *provided the substrate
resolves*. It will not resolve through `measurement`, because there is no substrate column; see
ACCEPTANCE.md clause 2.

### Conditions this build needs a `condition_context` for, and there are none

`condition_context` has **0 rows**. Every facet below is in the paper and has nowhere to go:
medium M9, carbon source glucose at 36 g/L, aeration micro-aerobic, vessel 250-ml screw-cap
conical flask, temperature 30 °C, agitation 250 r.p.m., inducer 0.1 mM IPTG, supplement 5 g/L
yeast extract, time 112 h, assay GC–MS/GC–FID. **"Reproduces the paper's conditions" is not a
statement the schema can currently hold for any paper.**

---

## 2. Avalos, Fink & Stephanopoulos 2013 — the *S. cerevisiae* landmark

`doi:10.1038/nbt.2509` · PMID 23417095 · *Nature Biotechnology* · full text stored, checksum
`38b38302...`, `oa_status='green'`.

### What the paper reports

Table 1, "Highest titers, yields and productivities achieved with JAy161", complete medium:

| quantity | value | span into stored text |
|---|---|---|
| isobutanol titer | 635 ± 23 mg/L | `[30309, 30333)` |
| isobutanol yield | 6.4 ± 0.2 mg per g glucose | `[30360, 30395)` |
| isobutanol productivity | 20.5 ± 1.2 mg l⁻¹ h⁻¹ | `[30426, 30463)` |
| isopentanol titer | 95 ± 12 mg/L | (same table block) |
| 2-methyl-1-butanol titer | 118 ± 28 mg/L | (same table block) |
| total fusel alcohols | 850 ± 60 mg/L | (same table block) |

Minimal medium, 24-h high-cell-density: 486 ± 36 mg/L (JAy153) and 491 ± 29 mg/L (JAy161),
`[11885, 12004)`. Cytoplasmic counterparts JAy166/JAy174 are the controls the compartmentalization
claim rests on and belong in the same promotion, not a later one.

Conditions, `[53154, 53354)`: minimal medium (1× YNB) with **20% glucose**, 50-ml conical tubes,
semiaerobic, 30 °C, 350 r.p.m., **24 h**; complete medium (SC minus uracil) for the Table 1
figures; parental strain JAy1 = BY4741 × Y3929, `[51758, 51851)`; alcohols by HPLC.

### The draft `pathway_configuration`

```yaml
name:                    "C_mitochondrial_ehrlich configuration from doi:10.1038/nbt.2509"
pathway_id:              YAA:PWY:isobutanol-valine-ehrlich
product_id:              YAA:PRODUCT:isobutanol
compartment_strategy_id: C_mitochondrial_ehrlich
host_strain_id:          (new strain: JAy161, parent JAy1 = BY4741 x Y3929)
description:             "enzymes as reported: ILV2, ILV3, ILV5 plus a downstream alpha-KDC
                          and ADH; localization as reported: targeted to mitochondria using
                          the N-terminal mitochondrial localization signal from subunit IV of
                          the yeast cytochrome c oxidase (CoxIV)"
```

**A gap to record rather than fill:** the main text does not name JAy161's specific α-KDC and ADH.
The candidate sets are in the Fig. 2 legend (`Ll-kivd` / `Sc-kid1` / `Sc-aro10`; `Sc-adh7` /
`Ec-fucO` / `Ll-adhA RE1`) and the per-strain assignment is in Supplementary Table 2, which is
**not in the stored asset**. A configuration that names an enzyme set JAy161 may not have is worse
than one that records the set as unresolved. The supplementary file needs acquiring first.

A cytoplasmic sibling configuration (JAy166/JAy174, `B_cytosolic_relocalization` or
`A_native_split` depending on how the ILV half is read) is the control and should be promoted with
it. The paper's claim is a *comparison*; a corpus holding only the winner cannot state it.

### The draft measurements

Per strain, `publication_id` = `doi:10.1038/nbt.2509`:

| strain | quantity_kind | value | unit | basis | note |
|---|---|---|---|---|---|
| JAy161 | `titer` | 635 | `mg/L` | — | complete medium, `uncertainty_sd` 23 |
| JAy161 | `yield` | 0.0064 | `g/g` | `unknown` | reported as 6.4 mg/g; **1.6% of the 0.411 ceiling** |
| JAy161 | `productivity` | 20.5 | `mg/L/h` | — | `uncertainty_sd` 1.2 |
| JAy161 | `titer` | 491 | `mg/L` | — | minimal medium, 24 h |
| JAy153 | `titer` | 486 | `mg/L` | — | minimal medium, 24 h |
| JAy166 | `titer` | 151 | `mg/L` | — | cytoplasmic control |
| JAy2 | `titer` | 28 | `mg/L` | — | empty-plasmid background |

Co-reported higher alcohols (phase 1's own requirement): isopentanol 95 ± 12 mg/L and
2-methyl-1-butanol 118 ± 28 mg/L on JAy161, with their own `product_id`s — both of which carry
`g_per_g_state='unknown'` in `product_theoretical_yield`, so neither is bound-checkable and both
are correctly *reported unchecked* rather than passed.

**The unit trap.** The yield is reported as *mg per g glucose*. Two of the three yield records
already in the corpus were promoted with `unit='unknown'` because the reported unit was
`mg/g`-shaped, and a yield stored with `unit='unknown'` **escapes the bound check entirely**
(ACCEPTANCE.md clause 2). Promoting 6.4 mg/g as `unit='unknown'` would put the *S. cerevisiae*
landmark outside the check the clause is about. It must be promoted as `0.0064 g/g` with the
conversion recorded in `derived_by`, or as `6.4 mg/g` with `mg/g` added to the unit vocabulary.

### Localization — the one place clause 3 is answerable

Avalos 2013 verifies its localization claim three ways, and the atlas can record exactly one of
them:

* **subcellular fractionation + western blot**, with anti-PGK (cytosol) and anti-porin
  (mitochondria) as compartment markers — `[23523, 23624)`; this is
  `verification_method='fractionation'`;
* **fluorescence microscopy**, GFP fusions against MitoFluor Red 589 — `microscopy`;
* **quantified enzyme concentration per fraction**, up to a fourfold increase for Ll-adhA RE1 —
  closest to `activity_in_fraction`.

`modification_localization_change.verification_method` accepts all three names and the table has
**0 rows**. So this paper is the test case that would take clause 3 from vacuous to real, and the
blocker is not the column — it is that nothing promotes into that table at all. See ACCEPTANCE.md
clause 3.

---

## 3. What "reproduce" has to mean, before either can be claimed

Clause 1 says the builds *reproduce their paper's titer, yield and conditions*. Two of those three
are storable today and one is not:

* **titer** — storable. `measurement` holds it with unit, uncertainty and source locator.
* **yield** — storable, with a caveat that matters: the basis is `'unknown'` for both papers
  unless the supplementary data settles it, and an `'unknown'` basis is *by this project's own
  rule* not comparable across studies.
* **conditions** — **not storable**. `condition_context` has 0 rows and no measurement in the
  corpus points at an `experiment`. Every condition facet for both landmarks would have to live in
  `evidence` prose, which is where `curate.promote` already says the substrate lives *"because it
  has nowhere else"*.

So clause 1 cannot be *fully* satisfied by extraction alone, however good the extraction is. Two
thirds of it can.
