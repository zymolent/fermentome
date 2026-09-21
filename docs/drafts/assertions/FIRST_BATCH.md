# The atlas's first assertions — a batch of proposals

**Status: proposal. Nothing here has been written.** The live atlas still holds `assertion` = 0 and
`evidence_item` = 0. Every query behind this document ran against
`~/fermdb-data/fermdb.sqlite3` opened `mode=ro`; `build_assertion` and `attach_evidence` were run
only against a throwaway in-memory database built from copies of the rows each proposal cites.

The owner approved the **`direct_perturbation`** set: strains carrying *both* a promoted
`measurement` and a promoted `modification`, where a comparator exists. PLAN.md J.3 grades those
L1, and L2 once a second independent group reproduces them.

Two things this document deliberately does not do:

* **It does not choose a level.** `schema.sql` has no `level` column and `assertions.py` writes
  none. Every "expected level" below is a prediction of what `assertion_level` will report, with
  the rule it follows; the rehearsal in §5 checks the prediction by building the batch in a
  scratch database and reading the view.
* **It does not put a number in `effect_size`.** Every measurement here is a titer. A titer of
  1.32 g/L is not an effect of 1.32, and the difference from the control is a number this atlas
  would have computed rather than one the paper reported. `effect_size`, `effect_unit`,
  `effect_ci_*` and `effect_n` are left NULL on all six, which is the honest state and is
  recoverable later from the two measurement rows the evidence already cites.

---

## 1. What the search found

The query joined `strain`, `modification` and `measurement` on `strain_id`:

| | count |
|---|---|
| (strain, modification, measurement) triples | **17** |
| distinct (strain, modification) pairs — candidate perturbation claims | **9** |
| distinct strains | **8** |
| pairs with a comparator that isolates the recorded modification | **6** |
| pairs drafted below | **6** |
| pairs refused | **3** |

"Comparator" is doing real work in that table. Fourteen of the seventeen triples have *some* other
strain in the same publication measured for the same `quantity_kind` and `product_id` — that is a
cheap SQL fact and it is not what a perturbation claim needs. What it needs is a control that
differs from the test strain **by the recorded modification and by nothing else**. Deciding that
means reading the genotypes, and the genotypes live in `span.quoted_text` and in the stored full
text, not in a column: `strain_lineage` exists in the schema and holds **0 rows**, so the atlas
records no parent-of relation at all today. Every comparator below is therefore a reading, and
each one says what it was read from.

All six drafted proposals come from one publication:

> Wess J, Brinek M, Boles E. *Improving isobutanol production with the yeast Saccharomyces
> cerevisiae by successively blocking competing metabolic pathways as well as ethanol and glycerol
> formation.* Biotechnol Biofuels 2019; 12:173. PMID 31303893,
> [doi:10.1186/s13068-019-1486-8](https://doi.org/10.1186/s13068-019-1486-8). *(metadata retrieved
> from PubMed)*

That is not a coincidence and it is not a weakness: it is the only paper in the atlas that curated
a stepwise deletion series *and* the titer of every step, which is exactly the shape a
perturbation claim needs.

### The `independent_group`, and how it was decided

PLAN.md J.3 counts independence **by group, not by publication**, and `assertions.py` refuses to
default the group to the publication id because that would read one lab's three papers as three
groups and promote to L2 by the very conflation J.3 exists to prevent.

The atlas stores no author or affiliation — `publication` is `(id, doi, pmid, title, year,
journal, license, zone, evidence, confidence)`. So the group was decided from the author
affiliations on PubMed, not from anything in the database and not from the DOI:

> Wess, Brinek and Boles are all *Institute of Molecular Biosciences, Goethe University Frankfurt*.
> One institute, one senior author. **`group:boles-goethe-frankfurt`.**

All six proposals carry that same group. The consequence is deliberate and should be read as a
feature: **the batch cannot reach L2.** Six L1 assertions from one lab are six L1 assertions. The
day a second group reproduces any of them, `attach_evidence` adds a row with a different
`independent_group` and the view reports L2 for an assertion nothing rewrote.

*Owner decision required:* the group slug itself. If the atlas already has a convention for group
identifiers, these should use it; if it does not, this batch is the moment to pick one, because
the strings will be compared by `COUNT(DISTINCT independent_group)` forever.

---

## 2. The six proposals

All six share a shape, so it is stated once:

* **subject** `modification` — the deletion *is* the thing the statement is about, and
  `assertion.subject_type` has a `modification` value. Built with `from_modification`, which now
  reads `modification.publication_id` off the row.
* **predicate** `affects_production_of` — from the 17-term vocabulary, checked against
  `predicate` rather than matched to. It is the right term rather than the nearest one: the claim
  is about how much isobutanol the strain makes. `affects_yield_of` was considered and rejected —
  every cited measurement is a **titer** (g/L), not a yield, and the two are different numbers.
  `improves_when_modified_by` was considered and is structurally impossible here:
  `assertion.object_type` has no `modification` value, so a modification cannot be the object.
* **object** `product` `YAA:PRODUCT:isobutanol`, with `product_id` set to the same.
* **evidence type** `direct_perturbation`, and the reason is the same in all six: a gene was
  deleted, the product was measured, and a control strain differing by that deletion was measured
  the same way in the same experiment. That is J.3's definition verbatim.
* **zone** `R` on both the assertion and the evidence, matching the Zone R rows they cite.
* **confidence** `medium`, carried from the `measurement` and `modification` rows.
* **expected level** `L1`, basis `direct_evidence` — one direct evidence item, one group, one
  direction, no conflict. Not L2, because `n_direct_groups` is 1.

### A1 — `ilv2Δ` increases isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:80b93f76dadaa25c` |
| evidence id | `YAA:EV:c2ae5342200612e3` |
| subject | `modification YAA:MOD:219464d2528382f9` (deletion of ILV2, strain JWY0) |
| direction | `increases` |
| strain / control | `YAA:STRAIN:jwy0` (0.22 g/L) / `YAA:STRAIN:cen-pk113-7d` (0.01 g/L) |
| measurement | `YAA:MEAS:847c6e027ad9b73b` |
| control measurement | `YAA:MEAS:387df4102862207b` |
| span | `YAA:SPAN:7823495e6115441a9101152a1837d1dd` |
| publication | `doi:10.1186/s13068-019-1486-8` |

**Why the comparator is real.** This is the one that looked confounded and is not. The abstract
credits the 22-fold rise to the cytosolic overexpression *and* the deletion together, which would
make CEN.PK113-7D the wrong control. The results section settles it: the 0.01 g/L number is *"for
the wt strain CEN.PK113-7D **expressing the cytosolic isoforms of Ilv2, Ilv5, and Ilv3**"*. Both
arms carry the cytosolic pathway; they differ by `ilv2Δ`. The control is isogenic for the claim.

**Data note for the owner (not a blocker).** The curated span stops at *"for the wt strain
CEN.PK113-7D"* and drops the clause that makes the control valid, and the `strain` row is
`CEN.PK113-7D / laboratory` with no record of the IsoV100 plasmid. A reader who checks this
assertion by following the span alone will reasonably conclude the control is a bare wild type.
The strain row, not this assertion, is where that should be fixed.

### A2 — `bdh1Δ bdh2Δ` increases isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:9fb20030a088b251` |
| evidence id | `YAA:EV:bab411ee80a4e072` |
| subject | `modification YAA:MOD:510bd21a2c8e8ad8` (deletion of BDH1/BDH2, strain JWY01) |
| direction | `increases` |
| strain / control | `YAA:STRAIN:jwy01` (0.28 g/L) / `YAA:STRAIN:jwy0` (0.22 g/L) |
| measurement | `YAA:MEAS:19c6160b30e66eeb` |
| control measurement | `YAA:MEAS:847c6e027ad9b73b` |
| span | `YAA:SPAN:25032f244565461181afc4071bb55143` |

**Why the comparator is real.** JWY01 is JWY0 plus `bdh1Δ bdh2Δ`; the abstract says the series was
built by *successively* deleting, and the span says *"deletion of BDH1/2 (strain JWY01) **further
increased** isobutanol production"*. The word "further" is the authors naming JWY0 as the
baseline. Isogenic by construction.

### A3 — `leu4Δ leu9Δ` increases isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:de97fba6db568868` |
| evidence id | `YAA:EV:de07578a268e6b36` |
| subject | `modification YAA:MOD:a5b8b1111f6c42af` (deletion of LEU4/LEU9, strain JWY02) |
| direction | `increases` |
| strain / control | `YAA:STRAIN:jwy02` (0.50 g/L) / `YAA:STRAIN:jwy01` (0.28 g/L) |
| measurement | `YAA:MEAS:84f9fa99523b400b` |
| control measurement | `YAA:MEAS:19c6160b30e66eeb` |
| span | `YAA:SPAN:878de66dfdbf4404892f7ecfa0e49884` |

**Why the comparator is real.** Next step of the same series: *"Further suppression of leucine
biosynthesis by deletion of LEU4/9 (strain JWY02) had an additional large effect ... and resulted
in a titer of 0.50 g/L"*. JWY02 = JWY01 + `leu4Δ leu9Δ`.

### A4 — `ecm31Δ` has no effect on isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:f75570bed59e4456` |
| evidence id | `YAA:EV:1d70c7089712a5d1` |
| subject | `modification YAA:MOD:4471c21875d88f81` (deletion of ECM31, strain JWY03) |
| direction | **`no_effect`** |
| strain / control | `YAA:STRAIN:jwy03` (0.52 g/L) / `YAA:STRAIN:jwy02` (0.50 g/L) |
| measurement | `YAA:MEAS:6f685ea5b4b553f7` |
| control measurement | `YAA:MEAS:84f9fa99523b400b` |
| span | `YAA:SPAN:d221c3ccc6834044a8d37a644a05fd42` |

**Why this one matters more than the others.** It is the only negative result in the batch, and it
is a *tested* negative rather than an absence: the authors say *"deletion of ECM31 (strain JWY03)
had **no statistically significant effect** on isobutanol production (0.52 g/L)"*. 0.52 > 0.50, so
reading a direction off the two numbers alone would have produced `increases`. The direction comes
from the authors' stated statistical result, which is precisely why `assertions.py` refuses to
derive a direction from a measurement.

A no-effect L1 is worth as much as a positive one to the ranker: it is how the atlas can say
"pantothenate is not the branch to block" with a citation instead of with silence.

**Related row, deliberately not touched.** There is an unpromoted bottleneck candidate span at the
same offsets (`record_path bottlenecks[0]`, `[17099, 17227)`) in this publication. It has no
`bottleneck` row, and drafting one is not in the approved set.

### A5 — `gpd1Δ gpd2Δ` increases isobutanol production *(approve with the caveat, or hold)*

| | |
|---|---|
| assertion id | `YAA:ASSERT:15a8bd300d887a9d` |
| evidence id | `YAA:EV:c811e0ec5667cada` |
| subject | `modification YAA:MOD:cc361f36d38986e4` (deletion of GPD1/GPD2, strain JWY19) |
| direction | `increases` |
| strain / control | `YAA:STRAIN:jwy19` (1.32 g/L) / `YAA:STRAIN:jwy18` (1.02 g/L) |
| measurement | `YAA:MEAS:f661cca85c3e05e3` |
| control measurement | `YAA:MEAS:a1c350fceb0a2631` |
| span | `YAA:SPAN:2dd368f3cfee45858b29e4a6b42913a6` |

**The caveat, stated first.** The modification row records `GPD1/GPD2` — both genes. The only
comparator with a promoted titer is **JWY18, which already carries `gpd2Δ`**:

```
JWY16  Δilv2 Δbdh1 Δbdh2 Δleu4 Δleu9 Δecm31 Δilv1 Δadh1                 -- no promoted titer
JWY17  ... Δadh1 Δgpd1                                                  -- no promoted titer (0.43 g/L in Fig. 7b)
JWY18  ... Δadh1 Δgpd2                                 1.02 g/L         -- the control used here
JWY19  ... Δadh1 Δgpd1 Δgpd2                           1.32 g/L
```

So what this evidence item demonstrates is the `gpd1Δ` increment on a `gpd2Δ` background, not the
double deletion against an intact one. The fully isogenic control is JWY16, whose titer has not
been curated.

**Why it is still proposed rather than refused.** The assertion carries no `effect_size`, so it
claims only the *direction*, and the direction holds on both readings: JWY19 > JWY18 in the
results, and the abstract states independently that *"deletion of glycerol-3-phosphate
dehydrogenase genes GPD1 and GPD2 prevented formation of glycerol and increased isobutanol
production up to 1.32 g/L"*. If the owner wants the control to be exact rather than the direction
to be right, the clean move is to hold this one until JWY16's 0.43 g/L and JWY17's titer are
promoted, then re-draft with JWY16 as the control.

### A6 — `ald6Δ` increases isobutanol production

| | |
|---|---|
| assertion id | `YAA:ASSERT:65a970e162e06e63` |
| evidence id | `YAA:EV:af60e8d044efa999` |
| subject | `modification YAA:MOD:5ad5ac8c1f7d0d2c` (deletion of ALD6, strain JWY23) |
| direction | `increases` |
| strain / control | `YAA:STRAIN:jwy23` (2.09 g/L) / `YAA:STRAIN:jwy19` (1.32 g/L) |
| measurement | `YAA:MEAS:a4cb6381273139ff` |
| control measurement | `YAA:MEAS:f661cca85c3e05e3` |
| span | `YAA:SPAN:2e43a10d665b48fe8f4caa3b50cd2699` |

**Why the comparator is real.** The text names the parent explicitly: *"the ALD6 gene ... was
additionally deleted **in strain JWY19, resulting in strain JWY23**"*, and Fig. 7's caption lists
JWY23 as JWY19's genotype plus `Δald6`. The cleanest pair in the batch, and the largest step
(1.32 → 2.09 g/L).

**One honest wrinkle, recorded and not acted on.** The authors themselves note that JWY19 *"had
obviously not reached maximal isobutanol titers even after 120 h"* while JWY23 peaked at 96 h, so
part of the gap may be timing rather than flux. That weakens a future `effect_size`; it does not
weaken `increases`, which is why no effect size is proposed.

---

## 3. What was refused, and why

Three of the nine candidate (strain, modification) pairs are **not** drafted. In each case
`plan_assertion` would have returned `ready = True` — which is the finding, not an oversight. The
planner checks that every cited row exists, that the per-type fields are present and that a J.5
arm closes. It cannot check whether the control isolates the modification, because nothing in the
schema says what a strain's genotype is. **That judgement is the curation, and it is not
automatable today.**

### R1 — `bat1Δ` in IbOH-1bat1Δ — *no isogenic control exists*

`YAA:MOD:8003a204b05640ff`, deletion of BAT1 by CRISPR/Cas9, strain `YAA:STRAIN:iboh-1bat1`,
from [doi:10.1016/j.btre.2026.e00959](https://doi.org/10.1016/j.btre.2026.e00959) (PMID 42088643;
Thammapanyaphong et al., Chulalongkorn University — group would be
`group:koonthongkaew-chulalongkorn`). Four promoted titers (0.215, 0.866, 1.001, 2.016 g/L) plus a
yield.

The only other strain in that paper with a titer is `YAA:STRAIN:wild-type-s-cerevisiae`, 6.4 mg/L,
and its span is *"the wild-type strain of this yeast can produce isobutanol in small amounts (not
exceeding 6.4 mg/L)"* — a background statement in the discussion, not a measured control run
beside IbOH-1bat1Δ. Worse, IbOH-1bat1Δ is IbOH-1 — a mutagenised, isobutanol-tolerant industrial
isolate — plus `bat1Δ`. Comparing it with a generic wild type attributes to BAT1 an effect that
includes the whole mutagenesis. **That is inventing a direction, and it is refused.**

The isogenic control exists as a row: `YAA:STRAIN:iboh-1` is in the atlas. It has **no promoted
measurement**. Curating IbOH-1's titer unblocks this one immediately, and it is the single highest-
value curation task this exercise turned up — BAT1 is the atlas's headline bottleneck.

`direct_biochemical` was tried as the honest alternative and is also wrong here. The planner's own
answer:

```
R1b-BAT1 as direct_biochemical -> ready=False
  needs evidence[0].assay_method: which assay produced the number --
        enzyme assay, isotope tracing, flux
```

Every `measurement.assay_method` in the atlas is NULL, and in any case a whole-strain titer is not
a biochemical assay of Bat1. Forcing a type that needs no control onto a claim that needs one is
how an L1 badge gets onto an uncontrolled number, which is the exact failure `assertions.py`'s
module docstring is written against.

### R2 — `lpd1Δ` on BSW191 — *the modification is on the wrong strain*

`YAA:MOD:a7c8f9da22ee16e0` records a deletion of LPD1 with `strain_id = YAA:STRAIN:bsw191`, from
[doi:10.1186/1475-2859-12-119](https://doi.org/10.1186/1475-2859-12-119) (PMID 24305546; Matsuda,
Ishii, Kondo T, Ida, Tezuka, Kondo A — Kobe University / RIKEN CSRS). The genotype table in that
same paper, curated as spans, says otherwise:

```
BSW191  BY4741/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM          <- no lpd1Δ
BSW192  BY4741/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1          <- no lpd1Δ
BSW205  BY4741 lpd1Δ/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1
BSW206  BY4741 lpd1Δ/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM
```

The modification was promoted from an **abstract** sentence (*"The integration of a single gene
deletion lpd1Δ and the activation of the transhydrogenase-like shunt further increased isobutanol
levels"*, `[1414, 1551)`) that names no strain. `lpd1Δ` belongs to BSW205/BSW206.

Asserting on it would produce a cleanly-resolving, L1-badged statement about the wrong strain,
which `traceability.py` explicitly calls worse than one that fails to resolve.

**Two rows for the owner to look at, neither of them mine to change:**

1. `YAA:MOD:a7c8f9da22ee16e0.strain_id` — should probably be `YAA:STRAIN:bsw206` (PMsM, matching
   the modification's own text) rather than `bsw191`.
2. `YAA:MEAS:f7a49e8797f74431` — BSW191, 1.62 g/L, promoted from `[1656, 1760)`, the abstract
   sentence *immediately following* the `lpd1Δ` one (*"the isobutanol titer reached 1.62 ± 0.11
   g/L and 1.61 ± 0.03 g/L"*). Those are the **two integrated strains**, i.e. the `lpd1Δ` +shunt
   pair. Attributing 1.62 g/L to BSW191 — whose in-text titer is 83 mg/L — looks like the same
   mis-attribution. Worth a second pair of eyes before anything asserts on it.

### R3 — `kivd` insertion on BSW191 — *the control carries the modification too*

`YAA:MOD:dd058febc2a55035`, heterologous insertion of *kivd*, strain BSW191. The only comparator
with a matching titer is BSW100 at 22 mg/L — and BSW100 is *"the strain into which three genes
required for isobutanol biosynthesis, including ILV2, **kivd**, and ADH6, were introduced"*. Both
arms carry *kivd*. The difference between BSW191 (83 mg/L) and BSW100 (22 mg/L) is the
transhydrogenase-like shunt plasmid `pATP423-PMsM`, which has **no `modification` row** in the
atlas — the span at `[21543, 21804)` says so in as many words.

So the number is real, the contrast is real, and the modification the atlas can name is not the
one that caused it. Drafting it would attribute the shunt's effect to *kivd*. Refused.

The fix is a curation task, not an assertion: promote the transhydrogenase-shunt modification, and
this becomes a clean L1 with BSW100 as the control.

---

## 4. Near misses — real perturbations the approved set cannot reach

Neither of these is in the `direct_perturbation` set, because the set is defined by a promoted
`modification` and neither has one. Both are listed because the measurement side is already
curated, so the gap is small and specific.

**GLN3 / isobutanol tolerance and titer** —
[doi:10.1016/j.cels.2019.10.006](https://doi.org/10.1016/j.cels.2019.10.006) (PMID 31734159). The
atlas holds `gln3D/gln3D homozygous diploid BY4743` at 306 mg/L, `BY4743` at 63 mg/L, a
`fold_change` of 4.9 between them, and tolerance numbers for `gln3D` vs `BY4741`. That is a
textbook perturbation with its own control — and there is **no `modification` row for `gln3Δ`**,
so `assertion.subject_id` has nothing to point at. One promoted modification turns this into two
L1 assertions (one `affects_production_of`, one `affects_tolerance_to`).

**BAT1 / BAT2 across two backgrounds** —
[doi:10.1016/j.ymben.2017.10.001](https://doi.org/10.1016/j.ymben.2017.10.001) (PMID 29037781;
Hammer & Avalos, Princeton — a genuinely *different* group from all of the above). Twenty-four
promoted measurements including a 14.2-fold increase from `bat1Δ`, and again **no `modification`
rows**. This is the one that would take an assertion to **L2**: a `bat1Δ` claim supported by
`group:avalos-princeton` and `group:koonthongkaew-chulalongkorn` would be two independent groups,
concordant in direction. Getting there needs modification rows in this paper *and* the IbOH-1
control titer from R1.

---

## 5. The rehearsal, and what the view actually said

Each proposal was planned against the live atlas (`mode=ro`) and then built in a **throwaway
in-memory database** loaded with copies of the organism, product, publication, extraction, span,
strain, measurement and modification rows it cites. `build_assertion` ran there as a human curator,
and the level was read back out of `assertion_level`:

| proposal | `.ready` | `.missing` | `.blockers` | `.warnings` | level from the view |
|---|---|---|---|---|---|
| A1 ILV2 | `True` | — | — | — | **L1** / `direct_evidence` |
| A2 BDH1/BDH2 | `True` | — | — | — | **L1** / `direct_evidence` |
| A3 LEU4/LEU9 | `True` | — | — | — | **L1** / `direct_evidence` |
| A4 ECM31 | `True` | — | — | — | **L1** / `direct_evidence` |
| A5 GPD1/GPD2 | `True` | — | — | — | **L1** / `direct_evidence` |
| A6 ALD6 | `True` | — | — | — | **L1** / `direct_evidence` |

`.note` on all six: `ready to write assertion <id> with 1 evidence item(s)`.

PLAN.md J.5's walk was then run over the rehearsal database:

```json
{"n_walked": 6, "n_closed": 6, "n_broken": 0, "breaks": {}, "gaps": {}, "exit_code": 0}
```

Six chains, six closed, no breaks and no gaps — the literature arm closes through
`span -> publication` for every one, and the analysis arm is not involved, so the known
`dataset_unreachable` gap never arises. `exit_code` 0 rather than `EXIT_VACUOUS` 3, which is the
first time that gate has had anything to walk.

The live atlas was re-counted afterwards: `assertion` = 0, `evidence_item` = 0. Nothing moved.

---

## 6. If the owner approves

`build_assertion` refuses an agent, by design and for the reason `assertions.py` gives:
`assertion_level` does not look at `zone`, so an agent-written Zone I assertion carrying direct
evidence would be graded L1 by the view and badged L1 in the UI. So the write is the owner's, and
it is six calls of the shape in `docs/drafts/assertions/first_batch.yaml`.

Before writing, three decisions are the owner's and not mine:

1. **The `independent_group` string.** `group:boles-goethe-frankfurt` is a proposal. Whatever is
   chosen becomes a permanent key in `COUNT(DISTINCT independent_group)`.
2. **A5 (GPD1/GPD2).** Approve with the stated caveat, or hold it until JWY16's titer is curated
   and re-draft with an exact control.
3. **The two suspect rows in R2** — `YAA:MOD:a7c8f9da22ee16e0.strain_id` and
   `YAA:MEAS:f7a49e8797f74431`. These belong to whoever owns `data/` and promotion; they are
   reported here because this exercise is what surfaced them.
