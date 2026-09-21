# The phase 3.5 recommendation, claim by claim — what an assertion can and cannot carry

**Draft, 2026-09-22. Nothing here has been written.** The live atlas was opened `mode=ro`
throughout and re-counted afterwards: **`assertion` = 6, `evidence_item` = 7 — unchanged.** Every
`build_assertion` below ran against a `:memory:` copy taken with `sqlite3.Connection.backup`. No
row in `data/` was touched, no level was chosen, and `fermdb extract` was not run.

Other sessions were writing to the same atlas while this ran; `span` went from 267 to 384 and
`curation_event` from 520 to 521 between the first and last query here. Where that could have
changed a conclusion — §3.3 — it was re-checked at the end. It did not.

This document exists because `PHASE_3_5_RECOMMENDATION.md`'s acceptance criterion is
*"every claim in it opens an evidence chain"*, and the recommendation's own opening paragraph
conceded that its chains stop at a span-verified quote in a draft YAML rather than at an
`assertion` row — honest when written, because `assertion` read 0. It now reads **6**: five L1
and one L2, and `fermdb query traceability` closes all six.

So the question is no longer "can the atlas make an assertion at all". It is: **which of the
recommendation's own claims can be re-seated onto one, today.**

The answer is **two of twenty-one**, and this document says which two, what the other nineteen are
blocked on, and — for six of them — why the blockage is a real property of the assertion model
rather than a curation backlog.

---

## 1. The audit

`chain today` is what the claim actually resolves to as of 2026-09-22. `assertable?` is whether
`plan_assertion` returns `ready = True` for a statement that carries it, **without inventing a
row, a span, a group or a comparator.**

### Which of the four sourcing states each claim is in

* **R-row** — resolves to a promoted Zone R row in the live atlas.
* **draft** — resolves to a span-verified quote in a draft YAML under `docs/drafts/`. Real,
  re-resolvable, and *not* a row.
* **software** — a property of the code, reproducible by running it. Not a biological claim and
  not a thing `assertion` models.
* **doc** — a citation of another document in this repository. CONVENTIONS.md calls that citing
  memory with an extra hop.

| # | claim | chain today | assertable? |
|---|---|---|---|
| **R1** | `atlas routes --objective easiest` puts `B_cytosolic_relocalization` at the top; B beats C on feasibility 0.80 vs 0.60 | software — **re-verified live 2026-09-22, holds** | no — `assertion` has no subject for "the ranker's first row" |
| **R2** | `--objective programme` consults `programme_fit` before feasibility; it is a sort key and never a filter | software — **re-verified live, holds**; `PROGRAMME_FIT` is now filled and C ranks 1 | no — and see §4.1, this is not evidence |
| **R3** | Three independent lines agree on C | doc + doc + corpus | partly — only the third line is evidence at all |
| **Q1.1** | Matrix targeting is the strategy essentially all published mitochondrial isobutanol work uses | draft | no — a synthesis across papers, see §3.1 |
| **Q1.2** | "13 `pathway_configuration` proposals across three landmark papers, 8 of them sound" | draft — **stale and wrong, see §4.4** | n/a |
| **Q1.3** | **Matrix co-localization of the Ehrlich pathway raises branched-chain alcohol output** | **R-row**: `YAA:BNK:e86745216bd648b4` + span `YAA:SPAN:f2b5b7f8…` | **YES — D1, rehearsed L5** |
| **Q2.1** | §1 sets E's trigger: "E becomes justified precisely when C works but is import-limited" | doc | no — a statement about the plan, not about the world |
| **Q2.2** | 16 relocation attempts; every import failure in the corpus is a failure to translocate a transmembrane helix | draft | **no — §3.1, the claim is the shape of a table** |
| **Q2.3** | The ordering is monotone in hydrophobicity (Var1, bI4, Atp8 → Cox2 → Atp9 → cyt *b*) | draft | no — §3.1 and §3.3 |
| **Q2.4** | A chimera replacing one helix turned an undetectable protein into a processed one | draft | no — §3.3, no span row for that paper |
| **Q2.5** | DUET's KDC and ADH are soluble matrix enzymes with no transmembrane helices | background | no — no row asserts a part's TM count; `part` has `sequence` but no topology column |
| **Q2.6** | **Predicted: strategy C is not import-limited** | inference over Q2.2–Q2.5 | **an inference cannot be asserted — but its counter-evidence can. D2, rehearsed L5** |
| **Q2.7** | Import proxies rose 6%→12%→85% on two residue changes while expression tuning bought ~40%; so screen enzyme variants, not promoters | draft | no — §3.3 |
| **Q3.1** | The activator map covers all 8 protein-coding loci plus one non-displacing intergenic site | **R-row — 9 `mtdna_locus` rows, verified** | **no — §3.2, `mtdna_locus` is not a subject type** |
| **Q3.2** | `intergenic_upstream_COX2` borrows COX2's leader and displaces nothing | **R-row — `displaced_if_used` NULL, `respiration_retained_if_used` = 1** | **no — §3.2** |
| **Q4** | Five precedents plus one documented failure for a soluble heterologous ORF from mtDNA | `data/mitochondria/heterologous_orf_precedents.yaml` | no — §3.1 and §3.3 |
| **Q5** | Nobody has measured whether the insert stays (five sub-claims: zero papers follow an ORF over generations; both neutral-site precedents measure no retention; CRISPR inserts vanish in ~30–40 generations; ρ⁻ runs 0.1–1%/generation; the cider strain lost 82 kb) | draft | no — §3.1 and §3.3. **This is the load-bearing "absence" claim and §3.1 explains why the model has no way to state it at all** |
| **F1** | M3 solves for the wrong variable: the causal quantity is ΔΨ, not respiration; Ilv3 is an Fe-S matrix enzyme and Ilv3-in-ρ⁰ has never been measured | draft | no — §3.1, §3.3. The *subject* exists (`YAA:GG:yjr016c` ILV3, and ISU1/NFS1/YFH1 for the Fe-S machinery); the evidence does not |
| **F2** | Ilv5 is an mtDNA nucleoid packaging protein; a matrix bacterial-KARI swap gave 166-fold petite frequency and was abandoned | draft | no — §3.3. Subject `YAA:GG:ylr355c` (ILV5) exists and is the right one |
| **F3** | `respiration_retained: false` is a stability field: ARG8 at a neutral site is not counter-selected, ARG8 displacing an OXPHOS gene is purged on glucose | draft | no — §3.2 and §3.3 |
| **G** | 96 bp direct repeats delete ~160× faster in mtDNA than in the nucleus; the §2.2 recoder should report internal repeats shared with an insert's flanks | draft | no — a design rule for code, not a claim about a row |

### The tally, partitioned so the 19 do not all look alike

| bucket | n | claims | what would fix it |
|---|---|---|---|
| **Assertable today** | **2** | Q1.3, Q2.6's counter-evidence | nothing — drafted and rehearsed in §2; the write is the owner's |
| **Blocked on a `span` row, and nothing else** | **7** | Q2.3, Q2.4, Q2.7, F1, F2, F3, G | promote the already-offset-verified draft quotes to `span` rows (§3.3). The papers are in `publication` |
| **Not assertions in principle** | **7** | Q1.1, Q2.2, Q4, Q5 (subject is *the corpus*, §3.1); Q3.1, Q3.2 (`mtdna_locus` is not a subject type, §3.2); Q2.5 (no column expresses protein topology) | a schema/vocabulary change, or `knowledge_gap` — which for Q4 and Q5 is the right home |
| **Not biological claims at all** | **5** | R1, R2 (software), R3, Q2.1 (document citations), Q1.2 (a count of a draft file) | nothing. They open a chain — run the code, open the file — just not a J.5 one |

**2 + 7 + 7 + 5 = 21.** The number to quote is **2 of 21 assertion-backed, 9 reachable** (the 2
plus the 7 a span row would unblock).

---

## 2. The two that can be re-seated, and what the view said

Both were planned against the live atlas and then built in a throwaway `:memory:` copy.
`build_assertion` ran as curator `kangkon`, kind `human`. **The level was read out of
`assertion_level`, never chosen** — as `FIRST_BATCH.md` and `L2_BATCH.md` both do.

| draft | statement | evidence offered | `.ready` | level from the view | `derived_reason` |
|---|---|---|---|---|---|
| **D1** | `compartment mitochondrial_matrix` — `affects_production_of` → `product isobutanol`, `increases` | 1 × `literature_assertion` | `True` | **L5** | `hypothesis_or_insufficient_support` |
| **D1b** | *the same statement*, different evidence | 1 × `direct_perturbation` | `True` | **L1** | `direct_evidence` |
| **D2** | `compartment mitochondrial_matrix` — `is_bottleneck_for` → literal | 1 × `literature_assertion` | `True` | **L5** | `hypothesis_or_insufficient_support` |
| **D3** | `modification YAA:MOD:549819c3e9e779f7` — `is_localized_to` → `compartment mitochondrial_matrix` | 1 × `literature_assertion` | `True` | **L5** | `hypothesis_or_insufficient_support` |

`.missing`, `.blockers` and `.warnings` were empty on all four. J.5's walk, narrowed to each new
assertion: `n_walked=1, n_closed=1, n_broken=0, breaks={}, gaps={}, exit_code=0`. The literature
arm closes through `span → publication` every time; the analysis arm is not involved, so the known
`dataset_unreachable` gap never arises.

### D1 — Q1, and the only claim in the recommendation that a curated row already carries

| | |
|---|---|
| assertion id | `YAA:ASSERT:c1f3ece5e9162d8d` |
| evidence id | `YAA:EV:b217e0235661d756` |
| subject | `compartment mitochondrial_matrix` |
| predicate | `affects_production_of` |
| object | `product YAA:PRODUCT:isobutanol`, `product_id` the same |
| direction | `increases` |
| evidence type | `literature_assertion` |
| publication | `doi:10.1186/s13068-019-1560-2` (Zhang, Lane, Chen, Hammer, Luttinger, Yang, Jin, Avalos — *Xylose utilization stimulates mitochondrial production of isobutanol*) |
| span | `YAA:SPAN:f2b5b7f8711b46d49d709994c5fdaabc`, `[9450, 9620)` |
| bottleneck | `YAA:BNK:e86745216bd648b4` (node *"compartment choice for the Ehrlich pathway"*) |
| zone / confidence | `R` / `medium` |
| expected level | **L5**, basis `hypothesis_or_insufficient_support` |

The span, in full:

> This so-called mitochondrial isobutanol pathway boosts the production of branched-chain alcohols,
> relative to overexpressing the same enzymes in their native compartments

That sentence **is Q1**. It is the only place in the whole recommendation where the atlas already
holds a promoted Zone R row that states the claim the document makes.

**Why `compartment` is the subject.** The claim is about where the pathway is put. `assertion.
subject_type` has a `compartment` value and `mitochondrial_matrix` is a row. `pathway
YAA:PWY:isobutanol-valine-ehrlich` was the alternative and is wrong: the pathway row is the
curated stoichiometry with its native compartment assignment, so asserting *about* it that it is
localised somewhere else would contradict the row it points at. `reaction` was the third option
and is worse still — the claim is about the Ehrlich half as a unit, and picking one of
`…-ehrlich-kdc` or `…-ehrlich-adh-isobutanol` would state a third of it.

**Why `affects_production_of` and not `is_localized_to`.** `is_localized_to` states where
something is; the paper's sentence states what happens to output when you put it there. The
direction carries that, and `is_localized_to` has no room for it.

**The direction is `increases`, under the convention the owner has already settled.** The live
L2 (`YAA:ASSERT:893939228cea1ef4`, subject `gene_group YAA:GG:yhr208w`) carries `decreases` — so
the owner took `L2_BATCH.md` §6.1's reading **(b)**, *"the direction of the subject's own
effect"*. Under (b), the matrix's own effect on isobutanol is `increases`. This draft follows the
precedent rather than re-opening it.

**`independent_group` is not set, and that is correct.** `assertions.py` requires it for the two
direct types only; `literature_assertion` neither requires nor benefits from it, because
`assertion_level` counts groups only over direct evidence. It becomes an owner decision the moment
D1b below is wanted — and the group is already named in `L2_BATCH.md` §3: this paper is
**`group:avalos-princeton`** (Hammer and Avalos are both on it, which is exactly why L2_BATCH
flagged it as the near miss that would have broken the L2 if counted as a third group).

#### D1b — the same statement at L1, and why it is drafted but **not** proposed

`assertion_id_for` hashes subject, predicate, object, context, product and direction. D1 and D1b
hash to **the same id**, `YAA:ASSERT:c1f3ece5e9162d8d`, because they are the same statement. So
D1b is not a second assertion; it is a second evidence item on the first, and it takes the level
from L5 to **L1**:

| | |
|---|---|
| evidence id | `YAA:EV:df5f8bf153851f9f` |
| evidence type | `direct_perturbation`, `group:avalos-princeton` |
| strain / control | `YAA:STRAIN:yzy165` / `YAA:STRAIN:y58` |
| measurement | `YAA:MEAS:00c28a4e45d96802` — 162 mg/L |
| control measurement | `YAA:MEAS:36f73f0c537ec6d8` — 24 mg/L |
| span | `YAA:SPAN:bbed43a56a184b9781b19dc0997d07f3` |
| `plan_assertion` | `ready = True`, no missing, no blockers, no warnings |
| level from the view | **L1**, `direct_evidence` |

**And it should be refused, for the reason `FIRST_BATCH.md` §3 gives three times.** The planner
returns `ready = True` — that is the finding, not an oversight. It checks that every cited row
exists, that the per-type fields are present and that a J.5 arm closes. It cannot check whether
the control isolates the variable, because nothing in the schema says what a strain is.

Here it does not. From the curated genotype spans:

```
Y58     Xylose-utilizing strain, H145E10-XYLA3-1, evolved      <- no isobutanol pathway at all
YZy165  Y58 + delta-integration ILV2, ILV5, ILV3,
        CoxIVMLS-ARO10, CoxIVMLS-LlAdhA_RE1                    <- whole pathway AND matrix targeting
```

The contrast is **pathway against no pathway**, not **matrix against cytosol**. Attributing the
sevenfold rise to compartment choice would attribute to matrix targeting an effect that includes
introducing the entire pathway. That is FIRST_BATCH R3 — *"the number is real, the contrast is
real, and the modification the atlas can name is not the one that caused it"* — in a new paper.

The isogenic control the claim needs is the cytosolic version of YZy165, which the paper ran (the
D1 span says so in as many words: *"relative to overexpressing the same enzymes in their native
compartments"*) and which **is not curated**: no strain row, no measurement row, no span. Curating
it is the single highest-value task this audit turned up, and it converts Q1 from L5 to L1 in one
`attach_evidence` call against an assertion nobody rewrites.

So D1 is proposed at L5. D1b is drafted, rehearsed, reported, and held.

### D2 — Q2's counter-evidence, which the recommendation does not cite and should

| | |
|---|---|
| assertion id | `YAA:ASSERT:d12a5326f6e9a040` |
| evidence id | `YAA:EV:dffba8170cc341c8` |
| subject | `compartment mitochondrial_matrix` |
| predicate | `is_bottleneck_for` |
| object | `literal` — *"expression of a heterologous matrix-targeted enzyme (functional protein yield)"* |
| direction | NULL |
| evidence type | `literature_assertion` |
| publication | `doi:10.1016/j.meteno.2016.03.004` — *Mitochondrial targeting increases specific activity of a heterologous valine assimilation pathway in S. cerevisiae* |
| span | `YAA:SPAN:94c4772c8e394671ac0c7f29a197d8b1`, `[17210, 17484)` |
| bottleneck | `YAA:BNK:431c48b1e633a585` (node *"mitochondrial protein import"*) |
| expected level | **L5**, basis `hypothesis_or_insufficient_support` |

The span, in full:

> this targeted expression dramatically reduced the amount of functional protein as visualized by
> the reduced green fluorescence, which may be due to the high energy cost involved in
> translocating proteins across the mitochondrial membranes and their folding within the matrix

**This matters more than its level suggests.** Q2 is the recommendation's load-bearing answer and
it predicts *no* import limitation, from a draft table of allotopic-expression attempts. The atlas
holds a **promoted Zone R bottleneck row, node "mitochondrial protein import"**, from a paper that
matrix-targeted a heterologous enzyme in *S. cerevisiae* and reports that doing so sharply reduced
functional protein. The v1 recommendation cites neither the row nor the paper.

**Read in its own paragraph it confirms Q2 rather than contradicting it, and that reading is why
it must be cited rather than quietly omitted.** The comparator is *"constructs lacking the mt
leader"* — the cytosolic version of the same five-gene *P. aeruginosa* cargo — and the text
continues:

> Despite this penalty, however, mitochondrial expression well above background was observed for
> each construct with fluorescence approaching roughly half that of the positive mitochondrial
> fluorescence control. […] The effects of this energy penalty do not appear to be exclusively
> correlated with protein size. For instance acd1, encoding a 42.6 kDa protein, expresses very
> strongly in the cytoplasm but weakly in the mitochondria while the slightly larger lpdV
> (48.6 kDa), expresses at comparable levels in both

Every soluble cargo got in; the toll is energetic rather than topological; size is not the
variable; and the paper's title is *"Mitochondrial targeting **increases** specific activity"*.
So the honest summary is **Q2's prediction with a price tag**, and the price tag is what the
recommendation was missing. A document whose acceptance criterion is that every claim opens an
evidence chain cannot leave out the one curated row that speaks directly to its load-bearing
answer, in either direction.

**`is_bottleneck_for` with a `literal` object is the honest shape and it is not a comfortable
one.** The subject the bottleneck row actually names is *"mitochondrial protein import"* — the
TOM/TIM23 translocase — and no row in any of the eleven subject tables means that.
`bottleneck.transport_step` is NULL, so `from_bottleneck` cannot supply it either.
`compartment mitochondrial_matrix` is the nearest anchor and it is broader than the claim: it
names the destination, not the translocase. The `literal` object is what keeps the statement from
silently widening to "the matrix is a bottleneck for isobutanol", which this evidence does not
support — the paper is about valine *catabolism*, not isobutanol production, and asserting it
against `pathway YAA:PWY:isobutanol-valine-ehrlich` would be the cleanly-resolving-onto-the-wrong-
thing failure `traceability.py` calls worse than a break.

### D3 — a supporting assertion, offered not urged

| | |
|---|---|
| assertion id | `YAA:ASSERT:390861b699defc56` |
| evidence id | `YAA:EV:4aa52ce3ff5640cb` |
| subject | `modification YAA:MOD:549819c3e9e779f7` (Su9 mitochondrial leader peptide, `localization_change`) |
| predicate | `is_localized_to` |
| object | `compartment mitochondrial_matrix` |
| publication / span | `doi:10.1016/j.meteno.2016.03.004` / `YAA:SPAN:24ad34f759b44a7db582177fd0e5c7a5` |
| expected level | **L5** |

> the mt leader peptide appeared to direct expression towards the mitochondria of the cell

This backs a *premise* of Q2 rather than one of its numbered claims — that a nuclear-encoded
presequence does in fact deliver heterologous cargo to the matrix in this organism. It is the
positive half of the same paper whose negative half is D2, and writing one without the other would
be selective. It is counted in neither the 2 nor the 19, because it is not a claim the
recommendation makes.

---

## 3. What cannot be asserted, and the three different reasons

### 3.1 The synthesis-across-papers limit — and it is a real limit of the model, not a backlog

**This is the finding worth recording.**

Q2.2, Q4 and all five sub-claims of Q5 have the same shape, and it is not the shape an assertion
has. Take Q5's first bullet:

> Zero papers have followed a heterologous mtDNA ORF over generations.

An `assertion` is `(subject, predicate, object)` where the subject is a row and the evidence closes
a J.5 arm to a source. That sentence has **no subject in the atlas** — its subject is *the corpus*
— and **no source**, because its evidence is the absence of one. `evidence_item` has no way to
cite a search that returned nothing: every one of the seven evidence types requires a row, a span,
a run or a model output that *exists*. The same is true of Q2.2 (*"every import failure in the
corpus is a failure to translocate a transmembrane helix"* — a property of a 16-row table, not of
any one of its rows), of Q4 (*"five precedents plus one failure"* — a count), and of Q1.1
(*"essentially all published work uses matrix targeting"*).

The honest statement is that **the atlas can assert what a paper found; it cannot assert what the
literature does not contain.** A `knowledge_gap` row is the schema's answer to that shape —
`knowledge_gap` holds 212 rows and has `kind`, `why_it_matters` and `status` for exactly this —
and `MITOCHONDRIAL_PROGRAM.md` §2.3 already says the Arg8ᵐ precedent should hang off one as
*"the nearest supporting evidence"*. That is the right home for Q4 and Q5, and it is not an
assertion. Recording that, rather than forcing a subject, is the correct outcome of this exercise.

Four claims — **Q1.1, Q2.2, Q4 and Q5** — are in this class. Q2.3's *ordering* is a property of the
same table, but its individual rows are paper findings and are span-blocked rather than structural,
so it is counted in the seven.

### 3.2 The subject-table limit — `mtdna_locus` is not addressable

Q3 is the clearest case in the document of *the row exists, and the assertion model cannot point at
it.*

`mtdna_locus` holds **9 rows**, Zone R, each with its activators, `utr_source`, `displaced_if_used`
and `respiration_retained_if_used`. `YAA:MTLOCUS:intergenic-upstream-cox2` carries
`displaced_if_used = NULL` and `respiration_retained_if_used = 1` — Q3.2, stated by a column.

`assertion.subject_type` is a closed set of eleven values and `mtdna_locus` is not one of them.
Rehearsed:

```
D4  Q3 intergenic_upstream_COX2 displaces nothing
  ready     : False
  MISSING   : subject_type: 'mtdna_locus' is not one of ['compartment', 'gene', 'gene_group',
              'metabolite', 'modification', 'part', 'pathway', 'pathway_route', 'product',
              'reaction', 'strain']
```

There is no near-miss to coerce to. `part` is the closest table in spirit and means a *sequence
playing a step role*, not a genomic insertion site. Mapping a locus to a `gene_group` would assert
about *COX2 the gene* something that is true of *the silent region upstream of COX2* — which is
precisely the distinction the row was created to record. F3 is in the same class: it is a claim
about `respiration_retained_if_used`, a column on a table nothing can be asserted about.

**Two options, both an owner's and neither mine:** add `mtdna_locus` to `SUBJECT_TABLES` and to
`assertion.subject_type`'s CHECK (a schema and vocabulary change, PLAN.md J.2's versioned kind), or
accept that the activator map is a curated table the assertion layer reads and never speaks about.
Until then Q3.1 and Q3.2 stay draft-backed — with the mitigating fact that their chain is *better*
than most of the document's, because it terminates in a Zone R row rather than in a YAML file.

### 3.3 The span-row gap — thirteen claims, blocked on curation and nothing else

The mitochondrial papers **are** in `publication`. All eight I checked resolve:
`doi:10.1093/nar/gkx127`, `doi:10.1016/j.xpro.2022.101359`, `doi:10.15698/mic2018.03.621`,
`doi:10.1093/nar/gkaa424`, `doi:10.1091/mbc.e16-11-0775`, `doi:10.1091/mbc.e17-09-0560`,
`doi:10.1093/nar/gkaf634`, `doi:10.1093/nar/gkac1229`.

**None of them has a single `span` row.** Every span in the atlas belongs to one of eight
isobutanol/ethanol papers, and only two of those eight are mitochondrial in subject —
`doi:10.1186/s13068-019-1560-2` and `doi:10.1016/j.meteno.2016.03.004`, which is exactly why D1,
D2 and D3 are the only drafts in §2.

*(The total moved during this audit — 267 spans when it began, **384** when it ended, another
session loading `doi:10.1186/1475-2859-12-119` from 17 to 134. The **distribution did not move**:
the same eight publications, and still zero on every mitochondrial paper. Re-checked, and the
conclusion below is unchanged. `doi:10.1016/j.mec.2024.e00245`, the slot-6 paper of §4.3, is also
at zero.)*

`literature_assertion` requires `publication_id` **and** `span_id`, and `_check_evidence_references`
refuses a span that does not exist or that belongs to another paper. Rehearsed on Q5:

```
D5  Q5 insert retention (literature_assertion, no span row)
  ready     : False
  MISSING   : evidence[0].span_id: the exact sentence, so the claim resolves to text a reader
              can check
```

This is a curation gap, not a schema gap, and it is a *small* one: the draft YAMLs already carry
the quotes with character offsets, sliced from the stored full text and re-checked with
`fermdb.llm.validate.verify_span`. `~/fermdb-data/fulltext/` holds 254 shards. **Promoting those
quotes to `span` rows is the single change that would move the largest number of the
recommendation's claims from draft-backed to assertion-backed** — **seven**: Q2.3, Q2.4, Q2.7,
F1, F2, F3 and G. Q4 and Q5 would still fail, on §3.1: a span does not give a claim a subject.

#### The loophole, rehearsed so it can be refused with a number

`ai_inference` does **not** require a span — only `model`, `model_version`, `prompt_version`,
`review_state`, zone `I`, and any one of the four chain columns, of which `publication_id` alone
suffices. So Q5 *can* be made to pass:

```
D5b Q5 via ai_inference (the loophole)
  ready     : True
  LEVEL     : L5  basis=hypothesis_or_insufficient_support
  J.5 walk  : n_walked=1 n_closed=1 n_broken=0 exit=0
  arms      : ('literature',)  hops: evidence_item YAA:EV:f718637e… -> publication doi:10.15698/…
```

**It is refused, and the refusal is the point.** Every claim in this document currently rests on a
quote that was sliced out of stored text at an offset and re-verified byte for byte. Swapping that
for an AI inference whose only chain hop is a DOI would trade a stronger citation for a weaker one
*in order to make a count go up*. The level is L5 either way; the difference is entirely in whether
a reader can check the sentence. Meeting an acceptance criterion by lowering the evidence is
failing it with extra steps.

### 3.4 The routes cannot be cited either — `pathway_route` has no run

`pathway_route` **is** in `SUBJECT_TABLES`, so the matrix-closure result (§4.3) looked assertable
as a `computational_model` claim. It is not:

```
D6  a matrix-closing pathway_route (computational_model)
  ready     : False
  BLOCKER   : evidence[0].processing_run_id: no row 'YAA:PROCRUN:route-enumeration'
              in `processing_run`
```

`computational_model` requires `model_id`, `model_version` **and** `processing_run_id`, and
`processing_run` holds exactly one row — `YAA:PROCRUN:salmon-quantification`, the RNA-seq
quantification. All 600 stored `pathway_route` rows carry `processing_run_id = NULL`. Citing the
salmon run for a route-enumeration claim would produce a chain that resolves cleanly onto an
unrelated pipeline.

There is a second reason not to try. The 600 stored rows are **stale**: every one carries
`balance_status = 'pass'`, while the live enumerator at HEAD returns 6,400 routes, *all* of them
`fail` / `unbalanced`. `routes.py` says so against itself at the point where it writes them.
`fermdb atlas routes --write` has not been re-run since the cofactor-cycle work, so **no row in the
database reflects the matrix-closure finding at all.** Asserting on one of those rows would assert
on a row the code already knows to be wrong.

---

## 4. Re-checking the recommendation against what has landed since it was written

### 4.1 `programme_fit` now ranks C first — and this is **not** a fourth line of agreement

Re-verified live at HEAD:

```
easiest   -> rank 1  B_cytosolic_relocalization   feasibility 0.80   programme_fit 0.70
programme -> rank 1  C_mitochondrial_ehrlich      feasibility 0.60   programme_fit 1.00
```

The recommendation's reconciliation section is **correct and holds byte for byte**: `--objective
easiest` is unchanged, `programme_fit` is consulted before feasibility, no route is filtered, and
the population is identical under both.

But `PROGRAMME_FIT["C_mitochondrial_ehrlich"] = 1.00` is a **hand-entered constant recording the
owner's ruling**, not a measurement. The ranker returning C under `--objective programme` is the
recommendation's own conclusion read back out of a table somebody typed it into. It is a correctly
implemented sort key and it is **zero evidence for C**. The recommendation names three independent
lines; a reader who saw C appear at the top of the programme ranking could easily count a fourth,
and there is not one. The updated document says so explicitly.

Two docstrings in `src/` are now stale and would mislead a reader who trusts them —
`cli.py`'s `--objective` help still says *"programme_fit is unrecorded so both currently agree"*,
and `routes.py`'s *"WHY EVERY VALUE IS None"* paragraph sits directly above the filled-in values.
`src/` is not mine this session; reported, not fixed.

### 4.2 The 320 matrix-closing routes — **and the number that should have been in the brief**

Verified live, independently of the doc and the commit message:

| strategy | routes | matrix-closing |
|---|---|---|
| `A_native_split` | 1280 | **320** |
| `B_cytosolic_relocalization` | 1280 | 320 |
| `C_mitochondrial_ehrlich` | 1280 | **0** |
| `D_alternative_compartment` | 1280 | 320 |
| `E_mtdna_encoded` | 1280 | **0** |

All 320 of the A routes carry **Adh3**. The split is **128 with Pos5** (matrix-side NADPH-KARI:
`ilv5_native`, `ilvc_ecoli`) and **192 without Pos5** (NADH-preferring KARI:
`ilvc_nadh_variant`, `ilvc6e6_ecoli`, `ilvc_p2d1a1_ecoli`). The two mechanisms in the brief are
confirmed exactly.

**Three corrections.** (i) It is 320 of **6,400**, not of 600; the 600 is the stale
`pathway_route` table. (ii) `docs/drafts/phase3/ACCEPTANCE.md` says **240** and commit `5519874`'s
message says **480**; both predate `57062ce`, which grounded `adh7_native` as NADPH and removed the
`unknown` bucket. 320 is the number at HEAD. (iii) Closing the matrix does not make a route
balanced — all 6,400 are `unbalanced` / `fail`, and the 320 are exactly the routes whose residual
imbalance is cytosol-only.

**And the finding the brief did not name: no strategy C route closes the matrix. None of 1280.**
C puts the KDC and the ADH in the matrix as well, so the matrix ADH's demand opens a bucket the
valine branch does not close: the C routes come back `matrix NADH short by 1`, `short by 2`, or
short on both carriers. The result that closes the matrix 320 ways is **strategy A**, which is not
what the recommendation says to build.

**Does that overturn the recommendation? No, and the reason is itself evidence.** The atlas holds
a curated Zone R measurement of a working strategy C strain — `YAA:STRAIN:yzy165`,
`YAA:MEAS:00c28a4e45d96802`, 162 mg/L, sevenfold over its parent, with `CoxIVMLS-ARO10` and
`CoxIVMLS-LlAdhA_RE1` in the matrix. A Zone I enumerator saying C's matrix never balances, against
a Zone R measurement saying a C strain made isobutanol, is the enumerator being wrong about
something — most likely that the parts catalog has no part representing the matrix NADH the real
strain draws from ethanol oxidation and the TCA cycle. `CONVENTIONS.md`'s zone ordering settles
which one yields.

**What it does change is the shape of the risk.** The enumerator names a specific, quantified
liability of C that A does not have — matrix NADH short by one to two per isobutanol — and names
the lever that fixes it in the A routes: Adh3, matrix-side. That is a sharper statement of C's
cofactor problem than the recommendation currently makes anywhere, and it belongs in the document.

### 4.3 The slot 6 adverse prediction about DUET

`doi:10.1016/j.mec.2024.e00245` (PMID 39072283), admitted to slot 6 under E5 on 2026-09-22, reports
that a Pos5 overexpression raises product during the glucose phase, **loses the gain past ~24 h**,
and is net negative across the whole fermentation when combined with `ZWF1*`. Its stated mechanism:

> A likely reason is a decrease in the NADH/NAD+ ratio by one order of magnitude after the diauxic
> shift (), which would decrease the substrate availability for Pos5.

`[59028, 59192)`, one occurrence, verified exact. Note the paper's own hedge — *"A likely
reason"* — it offers this as an explanation, not a demonstration.

**Two caveats travel with it and neither is optional.** (i) The Pos5 in that paper is
**cytosolic** — its N-terminal targeting sequence (residues 1–17) was deleted — and the collapsing
pool it reports is the *cytosolic* NADH/NAD⁺ ratio. DUET wants Pos5 in the matrix. (ii) Both the
order-of-magnitude figure and the 50-fold NADH preference are **cited by that paper from others,
not measured in it**; no cofactor of any kind is measured in it. It is capped at L3 in the
admissions layer, `verified` is false and `confidence` is `unverified` on all 24 admissions.

In the atlas it exists as a `publication` row (zone R), two `screening_record` rows and one
`fulltext_asset`. **Zero spans, zero measurements.** So this prediction is not assertable today
either, for §3.3's reason.

**Does it change the recommendation? No — and §4.2 is why.** The prediction is adverse to
**Pos5**, not to **C**. 192 of the 320 matrix-closing routes carry **no Pos5 at all**: they close
the matrix with an NADH-preferring KARI, which is PLAN.md B.3.5's named de-risking part. The
corpus generated an adverse prediction about one component and the route enumerator had already
enumerated the component's replacement. That is the atlas working.

What it does change is priority. The NADH-KARI arm stops being an alternative and becomes the
hedge, and Q2.7's heuristic generalises: **screen the KARI, not the NADH kinase** — and certainly
not the promoter. It also adds a fourth cheap experiment, below.

### 4.4 One stale count in the recommendation, found while auditing it

Q1 says *"13 `pathway_configuration` proposals now exist across three landmark papers, 8 of them
sound"*. `docs/drafts/configurations/host_resolution.yaml` holds **14**, across **four**
publications (ymben 2017 ×10, cels 2019 ×2, jbiotec 2022 ×1, meteno 2016 ×1), with **4** marked
`promote`, **1** `promote_pending_vocabulary` and **9** `reject`. `HOST_RESOLUTION.md` carries a
section headed *"There are 14 proposals, not 13"* explaining the fourteenth. The recommendation was
written against the earlier expectation and its own cited chain now contradicts it. Corrected in
the updated document.

---

## 5. What the owner is being asked

1. **Write D1, D2 and D3?** Three L5 assertions, all `literature_assertion`, all closing a
   `span → publication` arm, none reaching above L5 and none pretending to. `build_assertion`
   refuses an agent, so the write is the owner's.
2. **Curate the cytosolic comparator of YZy165** (`doi:10.1186/s13068-019-1560-2`). One strain row
   and one measurement row turn Q1 from L5 into **L1** through `attach_evidence`, with the
   assertion row untouched. Highest value per unit of work in this audit.
3. **Promote the mitochondrial draft quotes to `span` rows.** The papers are already in
   `publication` and the offsets are already verified. This unblocks roughly seven more claims
   (§3.3).
4. **Decide whether `mtdna_locus` becomes a subject type** (§3.2), or whether the activator map is
   accepted as a table the assertion layer reads and never speaks about.
5. **Re-run `fermdb atlas routes --write`** so the stored 600 stop claiming `balance_status =
   'pass'` (§3.4). Not mine: `src/` and `data/` are not this session's.
6. **A fourth cheap experiment**, from §4.3: **matrix NADH/NAD⁺ across the diauxic shift in the
   production chassis.** It costs about what the ρ⁰ DHAD assay costs and it decides whether the
   slot-6 prediction transfers from the cytosol to the matrix — which is the only thing standing
   between the 128 Pos5 routes and the 192 without.
