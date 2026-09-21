# Phase 2 — the ethanol reference layer: what was admitted, and what the budget cannot buy

> **INSTALLED 2026-09-22, on the owner's authorisation.** The 23 records below now live in
> `data/literature/ethanol_admissions.yaml` (committed, repo tier) and in `screening_record`
> (`review_state='accepted'`, `admitted_criterion` set), put there by
> `fermdb literature ethanol install`. Every span was re-resolved against the `fulltext_asset`
> store before installing — **63 of 63 exact** — and `validate_admission` returns no problems on
> all 23. `verified` is still false and `confidence` still `unverified` on every record; §5's
> re-tagging proposals beyond the admissions themselves are still unapplied, and §7 is still the
> owner's. The §3a finding is now a `never_attempted` `knowledge_gap` row
> (`YAA:GAP:ethanol-0-matrix-nad-p-h-pool-size-and-nad-p-h-nad`) rather than a paragraph.

> **AMENDED 2026-09-22 — SLOT 6 IS DECIDED, AND E5 IS NO LONGER ZERO.** The owner picked
> `10.1016/j.mec.2024.e00245` — the paper §3b named as one that "should be read in full before slot
> 6 is decided" — from the eight-candidate re-run in `slot6_E5_redox_shuttle_rerun.yaml`, where it is
> rank 1. It is admitted under **E5, slot 6**, and installed through
> `fermdb literature ethanol install` after `fermdb.db.migrations.copy_backup`. **E5 moves 0 → 1 of
> 45.** The layer is now **24 of 150** publications and **23 of 60** measurement-bearing studies; the
> file carries **60 spans, 60 of 60 re-resolved exact**, of which the 7 new ones were *sliced* from
> the `fulltext_asset` store rather than transcribed. `validate_admission` returns no problems on all
> 24. `verified` is still **false** and `confidence` still **`unverified`** on every record,
> including this one — promotion remains a curator act and was not performed. The other seven
> candidates were **not** picked and are not admitted. §3 below is superseded only on the count; its
> finding — §3a — is untouched, and the pick makes it sharper rather than softer. See §3d.
>
> **ONE TEST NOW FAILS, AND IT IS A FINDING RATHER THAN A DEFECT IN THIS CHANGE.**
> `tests/test_ethanol_admission.py::test_the_curated_admission_set_loads` asserts
> `len(records) == 23` with the message *"phase 2 admitted 23; the deliverable is the number, not
> 150"*. It pins a **literal count**, so it fails on any 24th admission whatever its merit — and
> slot 6 was always going to produce one. It is not a budget or a cap test: every budget and cap
> assertion in the same file still passes, `validate_admission` returns no problems on all 24, and
> `test_the_files_recorded_budget_position_matches_the_records_and_the_code` passes because the
> file's own `budget_position` was updated with the records. **The test was not weakened, loosened
> or edited**; `tests/` is not this pass's to change. The count needs re-pinning to 24, or
> re-expressing as the property it means (*"well under 150"*), by whoever owns that file. Otherwise:
> `ruff check`, `ruff format --check` and `mypy` are all clean — mypy at **no issues in 68 source
> files**, unchanged — and the remaining 1266 of 1268 tests pass (1 skipped).

2026-09-21. **DRAFT** (as first written; see the note above for what has since been installed).
Nothing was written to the database and nothing under `data/`. No `confidence`
value is set anywhere; no record is marked `verified`. `fermdb extract` was not run. Project rule L.5,
decision D2. The machine-readable record set is `phase2_admissions.yaml` beside this file.

The phase-2 deliverable is **not 150 records**. It is 23, with a written account of why the rest of
the budget stands unspent — which is what the slots document asks for: *"an unspent share is not
reallocated automatically — it is reported, because 'we found fewer admissible papers than expected'
is a finding about the literature, not slack to consume."*

---

## 1. The position, per criterion

| criterion | slot(s) | budget | tagged pool | **readable** | admissible (my read) | **admitted** | unspent | why unspent |
|---|---|---|---|---|---|---|---|---|
| **E5** redox shuttle | 6 | **45** | 636 | 141 | **~5–8** | **1** ✱ | **44** | Not scarcity of *papers* but scarcity of *measurements* — §3 |
| **E6** industrial performance | 7 | 25 | 279 | 148 | 6–10 | **3** | 22 | Genuinely thin once off-target organisms are removed; Ethanol Red uncharacterised |
| **E1** competing sink | 2 | 25 | 68 | **16** | ~6 | **3** | 22 | **Acquisition, not scarcity** — 52 identified papers unreadable — §4 |
| **E2** performance ceiling | 5 | 20 | 587 | 267 | 12–15 | **3** | 17 | Ceiling is established by 3; more would be padding (B.3.2: "not a survey") |
| **E3** wild-type baselines | 1 | 20 | 319 | 106 | ~5 | **3** | 17 | Chemostat/carbon-balance standard is rare; 3 is close to everything that meets it |
| **E4** transferable mechanism | 3, 4 | 15 | 23 | 11 | ~12 | **11** | 4 | The one criterion the new PDFs materially fixed — §2 |
| | | **150** | | | | **24** ✱ | **126** ✱ | |

✱ as of the 2026-09-22 slot-6 amendment above. The table was written when E5 stood at 0 and the
layer at 23; the E5 line and the totals are the only figures that moved.

Caps: **24 of 150** publications, **23 of 60** measurement-bearing studies. Both well under.

Readable pools are counted live from the database (`fulltext_asset.storage_state='stored_fulltext'`)
and are larger than the 2026-09-21 shortlist report's figures, because the 127-PDF delivery has since
been ingested. That ingest changed **E4 and nothing else**, exactly as the corpus triage predicted.

Every one of the 23 was put through `fermdb.literature.ethanol.validate_admission` read-only.
**All 23 return no problems** — correct criterion vocabulary, ethanol tier present, screened through
discovery, within budget, within cap. Re-run over the installed set after the slot-6 admission:
**all 24 return no problems.**

---

## 2. What was admitted

Full records, with quotes and offsets, in `phase2_admissions.yaml`. In brief:

**E1 (3)** — `10.1186/1475-2859-11-131` (Oud, `MTH1-ΔT` restores glucose growth to a Pdc-minus
strain) · `10.1186/s13068-019-1486-8` (**re-tagged from E3+E5**; the Pdc cost ledger measured inside
an isobutanol strain, and the one that shows C2 auxotrophy is *not* the isobutanol bottleneck) ·
`10.1093/femsyr/foaf014` (2025 review; admitted as orientation, `measurement_bearing: false`).

**E2 (3)** — `10.1186/s13068-015-0216-0` (Ethanol Red as in-batch control on 35% w/v glucose; the
calibration ceiling) · `10.1186/s13068-018-1239-0` (VHG sugarcane juice, yield stated against
0.511 g/g) · `10.1186/s40643-022-00580-w` (five industrial strains incl. Ethanol Red, corn high
solids).

**E3 (3)** — `10.1093/femsyr/fow006` (CEN.PK113-7D, aerobic ethanol-limited chemostat, closed carbon
recovery — the strongest baseline in the layer) · `10.1186/1475-2859-9-16` (anaerobic CEN.PK-derived
batch on defined mixed glucose–xylose with closed carbon balances; also a **MIXED**-regime pentose
record under the 2026-09-20 B.3.6 amendment) · `10.1186/s13068-018-1231-8` (industrial DSM strains,
defined Verduyn medium — with the defect that the strains are access-restricted and can never be
reproduced in-house).

**E4 (11)** — the criterion the new corpus actually helped. Slot 3 (acute shock):
`10.1186/s13068-024-02503-7`, `10.1128/aem.00588-21`, `10.1016/j.crmicr.2026.100653`,
`10.1016/j.bbagen.2025.130804`, `10.1016/j.jprot.2019.103377`. Slot 4 (adapted growth):
`10.1534/g3.118.200677`, `10.1016/j.jbiotec.2010.06.006`, `10.1021/acs.jproteome.1c00139`,
`10.1128/msystems.00827-25`, `10.1016/j.jbiotec.2007.05.010`, `10.1016/j.jbiosc.2017.04.012`
(`10.1186/s13068-024-02503-7` serves both slots, with the cost of doing so recorded on the record).

**E5 (1)** *(added 2026-09-22)* — `10.1016/j.mec.2024.e00245`, *"A comparative analysis of NADPH
supply strategies in S. cerevisiae"*. The owner's slot-6 pick. Admitted for a **conditional and
adverse** result, not a favourable one: cytosolic Pos5 raises xylitol titre during the glucose
phase, loses the gain past ~24 h, and is **net negative across the whole fermentation once `ZWF1*`
is present** — and the paper names the mechanism, an order-of-magnitude fall in NADH/NAD⁺ after the
diauxic shift starving Pos5 of substrate. That is a testable adverse prediction about **DUET's own
architecture**, which proposes to feed Pos5 from ethanol-derived matrix NADH in exactly that state,
and against **G.8**'s POS5-capacity bottleneck hypothesis. J.4: disputes are stored, not resolved.

  Three weaknesses are on the record's face, in `what_it_lacks` and `evidence_ceiling`, and they are
  the reason the admission is capped at **L3**:

  1. **Its Pos5 is cytosolic.** The N-terminal targeting sequence (amino acids 1–17) is deleted —
     re-verified in the **Methods** for this admission and quoted from there, not from the results
     narrative. So the pool whose collapse it reports is the **cytosolic** NADH/NAD⁺ ratio. DUET's
     Pos5 is native and matrix-resident. The warning transfers as an **L3 transfer claim** and
     refutes nothing about the matrix.
  2. **No cofactor is measured anywhere in it** — not cytosolic NADH, not matrix NADH, not NADPH,
     not ATP. The whole redox argument is read off product titre.
  3. **Its two load-bearing numbers are cited, not measured here**: the 50-fold NADH-over-NAD⁺
     preference of Pos5, and the order-of-magnitude NADH/NAD⁺ drop after the diauxic shift. Admitting
     it means admitting a paper's reading of two other papers; the primary sources must be chased
     before either number is quoted as a measurement.

  Also: xylitol via an NADPH-dependent xylose reductase, so it shares a cofactor demand with DUET and
  nothing else; Pos5 is the paper's **worst-performing** strategy and not its headline (that is
  `ZWF1`), occupying one section and one figure; and the `RNR2` promoter is deliberately weak, so the
  experiment tests *low-level* cytosolic Pos5 and says nothing about a high-capacity one.

**E6 (3)** — `10.1101/gr.131698.111` (MKT1/SWS2/APJ1 by pooled-segregant analysis; past mapping to
allele-level causality, which is what lifts it out of B.3.6's QTL exclusion) ·
`10.1186/s12864-015-1737-4` (**the only document in the corpus that sequences Ethanol Red**;
`SRR2002842` is a second, independent ER genome to cross-check `GCA_029255905.1`) ·
`10.1371/journal.pgen.1005635` (chromosome III aneuploidy as a recurrent route to high ethanol
tolerance — direct support for the slots document's own prediction that the advantage is polygenic
with CNV contribution).

### The E4 transfer cap, and the two records that break it

B.3.4 admits a mechanism **only with a stated argument for transfer to a C4 alcohol**, and caps an
ethanol-derived claim about an isobutanol phenotype at L3 without direct isobutanol evidence. Every
one of the 11 E4 records carries a written `transfer_rationale` and an explicit `evidence_ceiling`.
Nine are capped at L3. Two are not:

* **`10.1534/g3.118.200677`** — the same three strains profiled under ethanol *and* 1% isobutanol
  *and* 0.8% 1-butanol, aerobically *and* anaerobically, reads at `GSE118069`. Transfer is measured.
  The more valuable half is the **negative** list: flocculation, hexose transport, pseudohyphal
  growth and respiration-gene induction are induced by ethanol and *not* by the butanols. That names
  where an ethanol-derived expectation would have misled the programme.
* **`10.1016/j.jbiotec.2010.06.006`** — **this is the record the caller's brief named, and it lifts
  the cap in the harder direction.** The selection was run in **1% iso-butanol** — ten serial
  subcultures — and the four recovered targets (`INO1`, `DOG1`, `HAL1`, truncated `MSN2`) then
  improve tolerance to *both* iso-butanol and ethanol in the same background. The shared mechanism is
  established starting from the C4 side, which is the reverse of the ethanol→C4 inference the cap
  exists to police. The authors also state *why* they selected in iso-butanol rather than ethanol —
  ethanol evaporates from shake flasks and iso-butanol is more inhibitory at lower concentration —
  which is itself a transferable methodological fact.

  The cap still binds where it should: this paper **imposes** isobutanol, it never **produces** it,
  and tolerating exogenous isobutanol is not the same phenotype as tolerating self-produced
  isobutanol. Any claim about isobutanol titre stays L3.

---

## 3. E5 — the account of why 45 cannot be spent

**Admitted: 1 of 45** since 2026-09-22 (§3d). This section was written at 0 and is left as written,
because the reason 45 cannot be spent is unchanged by spending one of them. The flat statement "E5
has no anchor" is slightly wrong in a way that matters for the owner's next decision, so here is the
measured version.

### 3a. The core finding, reproduced independently here

I re-ran the check over **all 141 readable E5-tagged publications**, scanning the stored full text
for six core terms (`ADH3`, `POS5`, NAD(H) kinase, ethanol–acetaldehyde shuttle, matrix/mitochondrial
NADPH, matrix/mitochondrial NADH):

| core terms present | publications |
|---|---|
| 0 | **97** |
| 1 | 24 |
| 2 | 7 |
| 3 or more | 13 |

The loader's own (deliberately permissive) E5 content check passes 65 and **fails 76**. So more than
half the criterion's readable pool would be refused by the atlas's own validator today.

I then scanned the **whole readable ethanol-criterion pool — 668 publications** — for
compartment-resolved cofactor measurement. Three documents match measurement-shaped language and
**all three are narrative background, not measurement**: `10.1534/g3.118.200677` speculating about
"NADH/NAD+ rebalancing", `10.1128/aem.00362-26` stating in its introduction that Adh3 balances the
matrix NAD+/NADH ratio, and `10.1371/journal.pone.0111585` on ROS. The only compartment-targeted
live-cell redox method anywhere in the corpus is `10.1016/j.xpro.2020.100160`, a mito-roGFP protocol
that reports **glutathione redox potential — not the NAD(P)H pool**.

**Confirmed: zero papers measure a matrix NAD(P)H pool or ratio in living *S. cerevisiae* under a
named condition.** That is now four independent passes (slot-6 agent, benchmark BM-COF-005, corpus
triage, this one). It belongs in `knowledge_gap`, and it is a direct argument for commissioning the
mito-roGFP measurement the corpus protocol describes — with the caveat, from the same protocol, that
roGFP reads glutathione and a NAD(P)H sensor would have to be added.

### 3b. The correction: E5 is not zero-fillable, it is ~5–8-fillable

B.3.5's admitted list is broader than "matrix cofactor pools". It also admits `ADH3` localisation and
directionality, `pos5Δ` consequences and `POS5` overexpression phenotypes, and the respiratory /
diauxic-shift physiology of ethanol as a carbon source. Against **that** list the readable pool is
thin but not empty. Beyond slot 6's three shortlisted candidates, at least these are genuine E5
material and one of them the shortlist did not surface:

* `10.1016/j.mec.2024.e00245` — *"A comparative analysis of NADPH supply strategies in Saccharomyces
  cerevisiae"*, 15 `POS5` mentions. **Not on the slot-6 shortlist.** On its face this is the most
  directly on-target document in the pool for the `POS5`-capacity bottleneck hypothesis (G.8), and it
  should be read in full before slot 6 is decided.
  **[2026-09-22: it was read in full, and it is now ADMITTED — §3d. Two corrections to the sentence
  above, both from the re-run. (i) "Not on the slot-6 shortlist" is half right: it was not among the
  three CANDIDATES, but it was in the prior draft under `not_shortlisted_but_notable`, correctly
  described there as the wrong compartment. It was found and filed one tier too low, not missed.
  (ii) "the most directly on-target document in the pool" overstates it — its Pos5 is CYTOSOLIC. Its
  value is not that it is on target but that it is ADVERSE.]**
* `10.1371/journal.pone.0346295` — `pos5Δ` consequences, but in *S. pombe* and read out as CoQ
  biosynthesis.
* `10.1007/s00253-015-7266-x` — `ADH3` in *Dekkera bruxellensis*.
* `10.1093/femsyr/foac007` — respiratory NADH reoxidation in *Ogataea parapolymorpha*.
* `10.1186/s13068-023-02309-z` — slot-6 candidate 3; `POS5` overexpression against a matrix-targeted
  NADPH-consuming pathway in CEN.PK. The only S. cerevisiae functional test of the architecture.

**Basis:** abstract plus scripted full-text term counts, not a full read of each. They are leads for a
slot-6 decision, not proposals.

Note the pattern, which is itself the finding: **most of the genuinely E5 content in the readable
pool is in other yeasts** — *Cyberlindnera*, *Ogataea*, *Dekkera*, *S. pombe*. The compartment logic
transfers; the energetics often do not, because *S. cerevisiae* lacks the proton-pumping Complex I
those organisms use.

### 3c. Why the number is 0 and not 5

Two reasons, and neither is "the literature has nothing".

1. **Slot 6's pick is the owner's**, and the shortlist procedure has not been run to completion for
   it — and would now need re-running, because `10.1016/j.mec.2024.e00245` was not among the three
   candidates offered.
2. **Admitting 5 would not change the finding.** The E5 budget was sized at 45 because DUET's
   architecture is load-bearing on matrix redox and the outer literature bound is 642 publications.
   What the corpus supplies is roughly a seventh of a seventh of that. Reporting 45 unspent, with the
   measured reason, is more useful to phase 3.5's decision checkpoint than reporting 40 unspent.

**The honest statement:** *the atlas has no quantitative anchor for matrix redox because the
literature has none; it does have a small number of qualitative `ADH3`/`POS5` records, and the
realistic ceiling for E5 is about 5–8, not 45.*

Also relevant to phase-2 acceptance: PLAN.md's revised acceptance text makes `ADH3` and `POS5`
records **a phase-2 blocker**. On the evidence here that acceptance criterion cannot be met as
written *for a measurement-bearing record*, and the owner has to choose between amending it and
commissioning the measurement. That is flagged, not resolved.

### 3d. 2026-09-22 — the number is 1, and the amended acceptance clause is met

§3c's first reason has been discharged. The shortlist was re-run over eight ranked candidates
(`slot6_E5_redox_shuttle_rerun.yaml`), the owner picked rank 1 —
**`10.1016/j.mec.2024.e00245`** — and it is installed under **E5, slot 6**. The other seven were not
picked; they remain unadmitted candidates rather than rejections, and the ranked file is kept whole
so a later pass starts from it.

**E5: 1 of 45 admitted, 44 unspent.** §3c's *second* reason is untouched and is why the number is 1
and not 8: an unspent share is a finding about the literature, not slack to consume.

**Against PLAN.md's phase-2 acceptance as amended 2026-09-22** — which replaced the blocker with
*"at least one qualitative `ADH3`/`POS5`/shuttle record admitted under E5, against a realistic
ceiling of about 5–8"* — **that clause is now met.** One qualitative `POS5` record is admitted under
E5; it is exactly what B.3.5's "`POS5` … overexpression phenotypes" clause names; the number is
reported with its reason, as the amendment requires; and the never-attempted `knowledge_gap` the
same amendment requires is installed. The clause asks for a *qualitative* record and does not ask
for a measurement, which is the distinction the amendment was written to draw.

**What is NOT resolved by it, and must not be read as resolved:** §3a. No paper measures a matrix
NAD(P)H pool or ratio in living *S. cerevisiae* under a named condition; four passes agree, this
pick is not a fifth counterexample, and the gap row stays open. If anything the pick **sharpens**
the absence: the quantity the admitted paper's whole argument turns on — an order-of-magnitude fall
in NADH/NAD⁺ after the diauxic shift — is the **cytosolic** ratio, is **cited from another study
rather than measured here**, and the **matrix** counterpart that DUET actually depends on has never
been measured by anyone. The atlas now holds a warning about its own architecture that it cannot
check.

---

## 4. E1 — the other starved slot, for the opposite reason

**Admitted: 3 of 25.** E5's shortfall is scarcity; **E1's is acquisition**, and the numbers are exact:

| | |
|---|---|
| publications tagged E1 | **68** |
| readable (stored full text) | **16** |
| on the manual download queue, still unreadable | **52** |
| — paywalled | 25 |
| — licence forbids | 14 |
| — no PDF found | 11 |
| added by the 127-PDF delivery | **0** |

16 + 52 = 68. **Three-quarters of the criterion is identified and unreadable.** The corpus triage
searched the whole 127-PDF delivery for *PDC* deletion, attenuation, promoter-replacement or
`pdc1Δ pdc5Δ pdc6Δ` chassis work and found **none**. The nearest item — `10.1016/j.ymben.2010.11.003`,
glycerol-synthesis minimisation via the `GPD1`/`GPD2` branch B.3.1 names — is E1-adjacent context, not
an E1 record, and it is not admitted here.

So the E1 line reads: **22 unspent, unspendable by construction until the queue is worked.** That is
not a fact about the literature. It is a fact about institutional access, and it is fixable with
money rather than with search.

### The E1 record that should be admitted and cannot be

`10.1016/j.meteno.2016.01.002` — Milne's `pdc1,5,6Δ MTH1ΔT` chassis with the mass balance. The prior
shortlist named it as the E1 record the criterion most needs. It is in the corpus, its full text is
stored, and it **still cannot be admitted**: `validate_admission` refuses it with `wrong_tier`,
because it carries screening rows in the **isobutanol tier only** and the schema's CHECK forbids an
`admitted_criterion` on an isobutanol-tier row.

That is a **discovery-routing defect, not a literature finding**. Fixing it means either re-running
discovery so the paper is screened into the ethanol tier, or an explicit owner override. Neither
belongs to a curation track, and neither was done here.

---

## 5. Re-tagging — 15 E5 proposals and 8 others

Every proposal carries a verified basis quote (or points at the record where its quotes live). Full
detail with offsets in `phase2_admissions.yaml` under `retagging_E5` and `retagging_other`. Nothing
has been moved; `admitted_criterion` is untouched in the database.

### Papers tagged E5 that do not survive B.3.5

The database tags **13 of the 127 delivered PDFs E5** — the corpus triage reported 8; the live count
queried here is 13, and two of those carry a second criterion alongside E5. Two further E5-tagged
papers from the pre-existing corpus, named by the 2026-09-21 shortlist, are included below, giving
**15 proposals**.

**Not one of the 15 survives B.3.5.** They were pulled in by surface words — "respiratory-deficient",
"mitochondria", "NADH", "mitophagy":

| publication | proposed | why the E5 tag fails |
|---|---|---|
| `10.1016/j.bbagen.2025.130804` | **E4 (slot 3)** — admitted | Mitochondrial protein quality control is not a redox route |
| `10.1016/j.jprot.2019.103377` | **E4 (slot 3)** — admitted | Surface match on "mitochondria" in the conclusions |
| `10.1016/j.crmicr.2026.100653` | **E4 (slot 3)** — admitted | Morphological mitochondrial result; genuinely dual-use |
| `10.1021/acs.jproteome.1c00139` | **E4 (slot 4)** — admitted | Gut2 is a G3P-shuttle component; no cofactor measured in any compartment |
| `10.1016/j.fm.2023.104288` | E4 — *not* admitted | Ethanol tolerance, which B.3.5 excludes from E5 by name; needs a full read first |
| `10.1016/j.biortech.2018.07.150` | drop criterion (isobutanol tier) | An isobutanol paper; the CHECK already forbids a criterion here |
| `10.1016/j.ymben.2011.12.001` | pentose / C5 | `COX4` deletion *removes* respiration — opposite direction to E5 |
| `10.1016/j.biortech.2025.132921` | pentose / C5 | `NDE1`/`NDE2` replacement routes NADH *away*, to a cytosolic sink |
| `10.1016/j.biortech.2010.11.097` | exclude (B.3.6) | Sorghum stover pretreatment |
| `10.1016/j.biortech.2011.01.062` | exclude (B.3.6) | Cellobiose CBP |
| `10.1016/j.ymben.2023.06.009` | exclude (B.3.6) | *Myceliophthora* CBP; shuttles are **inhibited**, not used |
| `10.1016/j.jbiosc.2010.02.003` | exclude (B.3.6) | Two-page SSF note, *Candida glabrata* |
| `10.1016/j.jbiosc.2015.09.006` | exclude (B.3.6) | Strain-screening survey |
| `10.1016/j.fgb.2024.103914` | exclude (B.3.6) | *Scheffersomyces*, hydrolysate inhibitors |
| `10.1128/aem.02068-21` | quarantine, re-acquire | Mitophagy is not a redox route — **and** the delivered PDF is the bioRxiv preprint, whose title lacks the "significantly" the published version added in review. No full text is stored, so nothing has been quoted from the wrong text |

Beyond the delivered corpus, `10.1186/s13068-019-1486-8` is tagged **E3 + E5** and is proposed for
**E1** (admitted above): it is not a wild-type baseline and it measures no matrix cofactor, no
`ADH3`, no shuttle.

### Other re-tags

Four more are admitted here under a criterion they are not currently tagged with —
`10.1128/aem.00588-21` (E3→E4), `10.1128/msystems.00827-25` (E3→E4),
`10.1016/j.jbiotec.2007.05.010` (E2→E4), `10.1016/j.jbiosc.2017.04.012` (E2→E4) — and three are
proposed but **blocked**:

* `10.1007/s00253-020-10518-x` (Rpn4/proteasome, E3→E4). **Not admitted.** The stored PDF is the
  University of Southern Denmark repository's **accepted manuscript**, not the version of record. The
  atlas quotes verbatim with offsets; an offset into an accepted manuscript is fidelity to the wrong
  text. Re-acquire the published article. This is a fifth instance of the version hazard the corpus
  triage found in four preprints, and it was *not* on that list — so the hazard is wider than the
  preprint flag catches.
* `10.1016/j.meteno.2016.01.002` — §4 above, `wrong_tier`.
* `10.1016/j.jbiotec.2010.02.009` (Teh & Lutz, thermodynamic analysis). The corpus triage named it as
  slot 1's one genuinely good new candidate. On reading it is a **thermodynamic re-analysis of other
  laboratories' published continuous-culture data**, not a dataset. B.3.3 asks for matched wild-type
  and parental datasets; admitting it under E3 would put a derived quantity where a measurement
  belongs. Recorded as a bound on achievable yield, not admitted.

---

## 6. Span verification

**63 of 63 quotes re-resolved exact, 0 absent, 0 spliced.**

**2026-09-22, the slot-6 admission adds 7.** The installed file now carries **60 spans and
re-resolves 60 of 60 exact** (53 + 7); the 63 headline above counts the original 53 plus the 10
basis quotes that stay in the draft. Every one of the 7 was **sliced out of the `fulltext_asset`
store at its offsets** through `load_source_text` and re-checked with `verify_span` — **7 of 7
exact, none retyped, none spliced, each unique in its source**. Five are the re-run's candidate-1
quotes at their recorded offsets; two are new: the **Methods** strain-construction sentence
(char 14480), which is where the aa 1–17 deletion is established rather than narrated, and the PRY39
glucose-phase sentence (char 42606), which states the condition-dependence in the paper's own words.
One of the seven is truncated at a figure callout — contiguous, no ellipsis, the omitted tail being
stripped-citation residue — which is the same convention the existing records use.

Checked with `fermdb.llm.validate.verify_span` against the stored full text loaded through
`fermdb.extract.harness.load_source_text`. Every quote is a **contiguous** span — the two-marker
extraction used to build them cannot produce a splice — with no ellipses and no paraphrase inside
quote marks. Hyphenation across line breaks, ligatures and PDF artefacts are reproduced exactly,
because cleaning them would break the offsets. Offsets are 0-based half-open `[char_start, char_end)`
per CONVENTIONS.md. The YAML was round-tripped and every quote re-cut from its recorded offsets:
**0 round-trip failures.**

Three quotes occur more than once in their source (repeated data-availability statements in
`10.1534/g3.118.200677`, `10.1021/acs.jproteome.1c00139`, `10.1371/journal.pgen.1005635`). They are
exact but not positionally unique; `occurrences_in_source` records this and the recorded offset is
the first occurrence.

### One defect found in the existing drafts

The slot-1 draft attributes two "strain lineage" quotes to `10.1186/1475-2859-9-16` —
*"Two isogenic yeast strains were derived from the laboratory strain S. cerevisiaeCEN.PK 113-7D."* and
a companion sentence about BP10001's construction. **Neither string occurs anywhere in the stored full
text of that publication**, and neither does "isogenic" or "CEN.PK 113-7D". The quotes appear to come
from a cited companion paper. They were replaced here with two that do resolve.

The general cause is worth recording: the shortlist drafts were verified against the **corpus cache
`NNNNN.txt` files**, and this pass verified against the **`fulltext_asset` store**. Those are not the
same text for every publication. A quote verified in one is not thereby verified in the other, and
the offsets certainly are not shared.

---

## 7. What is still the owner's

* **The picks.** This is an admission *proposal*. The slots document says the agent shortlists and
  the owner chooses; 23 records is a curation proposal, not a ratified layer.
* **Every re-tag in §5.** No `admitted_criterion` has been moved.
* **Whether to commission the matrix-redox measurement** (§3a), and whether to amend PLAN.md's
  phase-2 acceptance, which currently makes `ADH3`/`POS5` records a blocker that the corpus cannot
  satisfy with a measurement.
* ~~**Whether to re-run slot 6's shortlist** now that `10.1016/j.mec.2024.e00245` is on the
  table.~~ **DONE, 2026-09-22.** Re-run over eight candidates, owner picked rank 1, admitted under
  E5. What remains the owner's here is narrower: **whether to spend a second E5 line on the runner-up
  `10.1186/s13068-023-02309-z`.** The pick spends one, so the matrix-compartment half of the
  question — what raising *native, matrix* Pos5 buys — is still unrepresented in the layer, and the
  two records contradict each other in no respect.
* **Whether to record candidate 7's licence constraint as a blocker or a footnote.**
  `10.1093/femsyr/foae037` is `cc by-nc-nd`, `text_mining_allowed: no` — unique among the eight, and
  it matters only if that candidate is ever picked.
* **The manual download queue.** 52 E1 papers and 12 remaining E4 papers need institutional access.
  E1's budget is unspendable without them.
* **PLAN.md still reads "E1–E5"** in its phase-2 acceptance while E6 carries an accepted 25-paper
  budget, the schema permits it, 279 records are tagged under it and 3 are admitted here. The loader
  prints the discrepancy rather than resolving it; so does this document.
