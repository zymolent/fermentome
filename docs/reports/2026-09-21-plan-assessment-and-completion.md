# The plan, re-measured — what is finishable now, and what was finished

2026-09-21, later the same day. Measured against PLAN.md section Q's phases and their stated
acceptance criteria, against the live database, not against effort spent.

This supersedes the phase tables in `2026-09-21-plan-status-and-parallel-work.md` and
`2026-09-21-handover.md`. **Both are stale in the one way that matters**, and the staleness points
the encouraging direction: they were written while the curation queue was untouched.

---

## 0. The correction that reframes everything below

Every recent report opens on the same sentence — *"95 proposals reviewed by nobody; `measurement`,
`strain` and `modification` all read zero."* That has not been true for some time.

| | handover said | actually is |
|---|---|---|
| curation tasks **pending** | 95 | **0** |
| curation tasks accepted | 0 | **95** |
| `strain` | 0 | **37** |
| `measurement` | 0 | **32** |
| `modification` | 0 | **11** |
| `bottleneck` | 0 | **4** |
| `genotype` | 0 | **23** |
| schema | v8 | **v10** |
| stored full texts | 1,310 | **1,429** |

The queue was worked through and promoted. The atlas holds Zone R content: 37 curated strains with
23 parsed genotypes, 32 measurements, 11 modifications, 4 bottlenecks.

**The consequence nobody has drawn yet: the 180-proposal cap no longer binds.** That cap existed
because 95 *unreviewed* proposals already represented ~2.4 hours of review backlog, and more agents
would only deepen it. With the backlog at zero, the arithmetic inverts — **extraction is now the
thing that moves phase 1, and it is no longer queue-stuffing to do it.** Every plan written in the
last two days was shaped around a constraint that has been discharged.

---

## 1. Phase by phase

| phase | status | what is actually true | moved today? |
|---|---|---|---|
| **0** — Foundations + recoder | **complete** | Acceptance passes in `test_fixture.py`, against fixtures. | no |
| **1** — Isobutanol core | **~30%**, up from ~15% | 37 strains, 32 measurements, 11 modifications, 4 bottlenecks, 16 parts, 2 pathways, 16 balance-checked reactions. `pathway_configuration` 0 — **but unblocked today**. `part_expression_record` 0, no promoter. 7 extractions of ~490 now-extractable papers. | **yes** |
| **1b** — mtDNA genetics corpus | **2 of 5 clauses** | All 8 of §3's content types now drafted; activator map loaded into `mtdna_locus` (9 rows). Clause 1 still fails: the landmark builds are not curated. | no |
| **2** — Ethanol reference layer | **not started, and now better understood** | Seven slots shortlisted. The finding is under-supply, not over-supply: ~45–65 admissible against a 150 cap. **E5 has no anchor in the literature at all** — now three independent passes agree. | **yes** |
| **3** — Route enumeration | **built, still untestable — but now unblockable** | 600 routes, 3,000 steps, 6 gates, 211 knowledge gaps. Acceptance is recall against phase 1's configurations; there are 0, and until today there was no code path that could ever make one. | **yes** |
| **3.5** — Decision checkpoint | **not started** | Needs 1–3. Q3 and Q4 of `MITOCHONDRIAL_PROGRAM.md` §5 answered; Q1, Q2, Q5 need phase 1. | no |
| **4** — Omics layer | **~60%** | 172 runs quantified, matrices built, 675 annotations. `condition_context` 0 of 172, `experiment` 0. | no |

**64 tables, 47 with rows, 17 empty.** Down from 22 empty.

---

## 2. What I completed this session

### 2.1 The two promoters that did not exist — and why `pathway_configuration` read zero

`pathway_configuration` is **phase 1's headline deliverable** ("every published microbial
isobutanol production strain, any host, as a `pathway_configuration`") and **the thing phase 3's
acceptance test measures recall against.** It read 0.

Not for want of data. It had an extraction schema (`extract/schemas.py`), a coverage mapping
(`query/coverage.py`), a table, and one accepted proposal waiting. What it did not have was a
**promoter** — the function that turns an accepted proposal into a row. `PROMOTERS` handled four
record kinds; this was not one of them, so the proposal sat resolved and unwritable, permanently.

The same was true of `co_reported_higher_alcohols`: three accepted 2-methyl-1-butanol titers with
nowhere to go.

Both are now promotable, and **both refuse rather than guess**:

* An adjacent-tier alcohol is admitted only if its strain already carries an isobutanol
  measurement. That is B.1's own rule — *"only when measured in the same experiment as
  isobutanol … their ratios are diagnostic of where flux is leaking"* — and it had never been
  enforced anywhere in the codebase. The check is **strain**-scoped, which is weaker than B.1's
  "same experiment"; `experiment` has 0 rows, so that is the strongest scope available. The
  docstring says so rather than hiding it.
* A configuration refuses to invent `host_strain_id` or `product_id`. Neither is in the extraction
  schema, and defaulting the product to isobutanol would file any other build as an isobutanol one.

### 2.2 The tier that PLAN.md said was a column, and was not

Enforcing B.1's rule needed the product tier. It turned out not to exist.

B.1 opens: *"the tier is a stored property of `product` that drives the acquisition policy in code.
**It is not an informal understanding.**"* `data/vocabularies/products.tsv` honoured that — `tier`
is its **first column**. `load_products` then folded it into a prose evidence sentence and wrote no
column at all. So the sentence written to forbid an informal understanding **described one**: the
tier survived only as English inside an evidence string, nothing could filter on it, and no
admission policy could consult it.

`product_mw_g_mol` was dropped by the same INSERT. That one costs a number rather than a policy:
B.6.7's load-bearing claim is that isobutanol is more growth-inhibitory than ethanol **on a molar
basis**, and no g/L titer reaches a molar axis without a molecular weight.

Schema **v10** adds both; the loader now refuses an unrecognised tier rather than storing it. All
10 products are now tiered and weighted. **Instances seven and eight** of the failure mode the
handover names.

### 2.3 The corpus: 120 PDFs ingested, 1,310 → 1,429 stored full texts

The 127 PDFs at `D:\Agentic\bifserver-works\literatures\pdf_included` turned out to be an
**acquisition** win, not a discovery one: all 127 were already discovered, already had publication
rows, and **all 127 sat on `manual_download_queue` as pending** — 114 paywalled. None had stored
text. What arrived was the bytes.

120 ingested through `literature manual-queue ingest`, which stores content-addressed and records
`oa_status='closed'` — correct, because a file from the owner's own access is not a confirmed open
licence.

**7 held back deliberately:**

* **3 whose content is a different paper than the DOI they are filed under.** The dangerous one is
  `10.1016/s1389-1723(00)80087-0`, which is really a 1991 JBC paper on the TIP1 cold-shock gene —
  *a yeast stress paper*, so an extractor would have found plausible content under a DOI it does
  not belong to, and every span from it would have been quietly wrong. There is no title or
  checksum gate on ingest.
* **4 preprint manuscripts rather than the published article.** `10.1128/aem.02068-21` proves the
  risk: the bioRxiv title says "does not improve", the published AEM title says "Does **Not
  Significantly** Improve". The hedge was added in review, and this atlas quotes verbatim. There is
  no `version` field in which to record "this is the preprint", so storing them under the published
  DOI would launder a preprint's wording into a published citation.

### 2.4 The first by-product ratios the atlas has ever held

Three 2-methyl-1-butanol titers for YZy197, promoted with B.1's companion rule satisfied — and
each still distinguishable by carbon source (0.91 xylose / 0.68 glucose / 0.93 galactose), because
the substrate rides in `evidence`. That is a **holding position, not a home**: it belongs in
`condition_context`, which is deliberately unpromotable, and a test now fails if the holding
position is quietly removed.

---

## 3. What can be completed now, and what actually blocks each

### Finishable without the curator

| work | why it is unblocked now |
|---|---|
| **Extract the isobutanol core** | The queue is empty and the cap does not bind. ~490 papers have stored full text; the five landmarks the corpus was missing arrived today, including **Bastian 2011** (`10.1016/j.ymben.2011.02.004`), which is the source paper for the NADH-preferring KARI that B.3.5 calls *"the highest-priority de-risking part"* and seeds as a `knowledge_gap` |
| **Fill `pathway_configuration`** | The promoter exists as of today. Each row needs a curator to name host and product — by design — but the path exists where it did not |
| **Phase 3's acceptance test** | Becomes runnable the moment configurations exist. It has never been run because it never could be |
| **Pentose/C5 layer** | 12 primary papers, newly readable, and **structurally new**: pentose entered scope on 2026-09-20, *after* the ethanol layer and its shortlists were built. No slot, no budget, no prior pass |

### Blocked, and honestly so

| work | the blocker | is it real? |
|---|---|---|
| `condition_context`, and so phase 4's contrasts | Grouping N facet records into one context is a curation decision — a wrong grouping invents a context that never existed and measurements then get compared across it | **Yes. Leave it.** |
| `assertion` / `evidence_item` — both 0 | No promoter, and the J.3 evidence level is *derived* from evidence items. Phase 0's "an assertion resolves a complete J.5 chain" passes against fixtures only | Real, and the next structural gap after this session's two |
| `part_expression_record` — 0 with 16 parts | **A different gap from the two fixed today, and a deeper one.** The extraction schema has seven record kinds and this is not one of them, so there is no proposal to promote — the parts catalog can name a part but not the host × compartment it was expressed in. Phase 1 asks for *"one expression record per demonstrated host × compartment"* | Real. Needs a new extraction section and therefore a prompt change, not a promoter |
| Phase 1b clause 1 | Needs the landmark builds curated, not merely extracted | Real |
| Ethanol layer's E1 and E5 slots | **The literature does not contain them.** Zero of 127 new papers mention `POS5`, the ethanol–acetaldehyde shuttle, or matrix NADPH. Not one *PDC* paper | Real, and it is a finding, not a failure |

---

## 4. The E5 finding, because it is the most consequential thing on this page

Slot 6 exists because the atlas has *"no transcriptomic anchor for matrix redox at all"*, and it
carries the **largest single budget in the ethanol layer — 45 of 150 records.**

Three independent passes have now reached the same place:

1. the shortlist wave: across 129 readable E5 candidates, 4 mention matrix/mitochondrial NADPH, and
   about a dozen of the 18 that mention Pos5 use it as a *cytosolic* tool;
2. the benchmark wave, independently: BM-COF-005's gap is *"quantity, not identity"*;
3. today's 127-paper corpus: **0 mention `POS5`, 0 mention the ethanol–acetaldehyde shuttle, 0
   mention matrix NADPH.** Less E5-dense than what the atlas already holds.

**Zero papers measure a matrix NAD(P)H pool or ratio in living *S. cerevisiae* under a named
condition.**

This matters far beyond phase 2. DUET's redox architecture runs through Adh3 → matrix NADH → Pos5 →
matrix NADPH → Ilv5, and PLAN.md calls `POS5` capacity *"the atlas's highest-priority bottleneck
hypothesis."* The honest reading is that **the hypothesis cannot be weighed against literature,
because the measurement does not exist in it.** That is not a gap the atlas can curate its way out
of. It is an experiment, and the atlas's job is to say so precisely — which it now can, three ways.

Also worth acting on: **8 papers are tagged E5 in the database and none survives B.3.5's test.**
They were pulled in by "respiratory-deficient" / "mitochondria" / "NADH". Re-tag before spending
budget.

---

## 5. Decisions I took

Each is reversible, spends nothing, touches no bench, and promotes nothing a human did not accept.

| # | decision | why |
|---|---|---|
| **D9** | **Ingest 120 of 127 PDFs; quarantine 7.** | 3 are the wrong paper for their DOI; 4 are preprints and no `version` field exists. Storing either would put wrong provenance behind verbatim spans, which is the one thing this atlas exists not to do |
| **D10** | **Schema v10: `product.tier` + `product.mw_g_mol`.** | PLAN.md B.1 asserts the first is a column. It was not. The migration makes the plan's own sentence true |
| **D11** | **Write both missing promoters; make both refuse rather than default.** | A kind with no promoter is a proposal that can never become a row. Refusing loudly is the house pattern (`strain.organism_id`, `bottleneck.observation_type`) |
| **D12** | **Do not promote the one `pathway_configurations` proposal.** | Its paper is *"Mitochondrial targeting increases specific activity of a heterologous valine assimilation pathway"* — bacterial BCKAD/ACD targeted to the matrix, measuring **enzyme specific activity, not a titer**. The curator had already written the warning into the payload. `C_mitochondrial_ehrlich` is the wrong strategy and the vocabulary has no right one. See §6 |
| **D13** | **Diagnose the Milvus abort before running the lit-agent pipeline — done, and it is benign.** See §6.1 | Both corpora share one server, so pushing 127 papers into a store that had just aborted would have risked the cellulase corpus for no urgency |
| **D14** | **Add a content check to ingest: refuse a file whose own text does not look like the paper its filename claims.** Threshold calibrated on the labelled batch (118 good: min 71%; 2 wrong-paper: 17%, 44%), not chosen by taste. `--no-title-check` overrides | 3 of 127 were the wrong paper and nothing downstream could catch it. This is the same "report, never guess" rule ingest already applied to filenames it could not match, extended to a failure that actually happened |

---

## 3a. The calibration, finally run — and the answer is no

`OPEN_QUESTIONS.md` Q7 and `MODEL_ROUTING.md` §7 both call a 20-paper local-vs-capable recall
calibration a **phase-1 deliverable**. It had never been run. It has now
(`docs/drafts/calibration/`), and it decides the routing for the extraction that §3 says is newly
unblocked.

**The sentence: phase 1 must not route its 500–900 papers through the local tier as a first-pass
extractor.** Across the two papers both tiers completed, local recalled **1 of 301**
capable-proposed records — **0 of 84 measurements, 0 of 68 modifications, 0 of 75 condition
facets** — and **2 of the 5 papers the local tier attempted produced nothing at all**, because it
fabricated quotes the span validator rejected. §7's own rule then applies literally: local stays on
triage.

**N = 2 paired, and that is stated as N = 2.** The capable arm averages 267 s and 975 s per paper
and was stopped mid-third. It is a pilot, both papers are isobutanol-yeast, and the 20-paper set
was frozen *before* the run (it is in git as of `c7c06f6`, which is what S.2 asks). The margin is
wide enough that sampling is unlikely to explain it; the honest caveat is in §3a.3.

### 3a.1 The GPU was never the problem — three other things were

`ollama ps` reports **100% GPU**, 50 tok/s for the 27B. The memory note's CPU trap did not bite.
What did:

* **The extraction payload schema does not fit the local tier's own default context.** The schema
  alone is ~42,000 characters ≈ 10,500 tokens; with the reply reservation the floor is ~12,500
  tokens **before any paper**. Default `num_ctx` is **8,192**, so local extraction is arithmetically
  impossible at any excerpt size until the window is raised past ~17,500. `MODEL_ROUTING.md` §7c
  concludes *"the excerpt, not the window, is the real limit"* — on this measurement **the schema
  is a second, independent floor and it binds first.**
* **The configured extraction model could not be run at a legal context at all.** `qwen3.6:27b` did
  not return in 900 s at a 6,000-char window, and a *trivial* prompt at `num_ctx` 16,384 did not
  return in 290 s while the same prompt at 8,192 returned in 5 s. A resident instance held 16 GB,
  a different `num_ctx` needs a second instance, and it does not fit — **Ollama blocks
  indefinitely rather than erroring.** Same silence as the CPU trap, different mechanism.
* So the local arm ran on **`qwen2.5:7b-instruct`**, which §7c explicitly leaves open as a
  throughput question to settle by measurement. **The configured 27B therefore remains untested.**

### 3a.2 Two repo defects, both on paths no run had ever reached

1. **`claude-agent-sdk` was not installed and was not declared anywhere.** Now declared as an
   optional `escalation` extra — it was undiscoverable, which is how it stayed missing.
2. **`claude_agent_sdk_runner` pinned `max_turns: 1`, and at 1 every real paper fails** with
   "Reached maximum number of turns (1)". Reproduced at 30k, 12k and 6k excerpt windows, so it is
   not excerpt size — a trivial schema completes in one turn and the 42,000-character payload
   schema does not. **This is the tier the calibration says we must depend on, and it was broken.**
   Fixed to 8, with the reasoning at the use site: every tool is disallowed and `setting_sources`
   is empty, so an extra turn can only continue emitting the JSON object, and the docstring's trust
   argument is about tools and file access, neither of which changes with a turn count.

### 3a.3 The span validator holds — and `relocate_span` turns out to be load-bearing

**Not one non-resolving span survived into either tier's output.** §3's claim that span
verification is model-independent survives contact with real data, which is the single most
reassuring result here.

But **99–100% of proposed offsets were wrong in both tiers.** Opus 5 is no better at counting
characters than a 7B. `relocate_span` is not a convenience, it is the thing that makes structured
extraction work at all, and it should be treated as infrastructure.

The local failure mode is also **worse than §7 predicted**: not merely omission but *fabrication* —
16 quotes that are not in the paper, killing 2 of 5 papers outright. A false negative arriving by
way of a false positive. And one nuance against over-reading the 0.3%: on two papers the 7B
proposed 71 and 51 records, volumes in the capable tier's range. **It is unreliable, not weak**,
and nothing in its output says which papers it dropped.

**The caveat worth acting on before this is treated as permanent:** the 42,000-character payload
schema may be the defect rather than the model. It is what forces the context floor above, and a
narrower per-record-kind prompt is a far cheaper thing to fix than the routing.

---

## 4a. The benchmark set: S.5's headline number was unobtainable, not merely unmeasured

`data/benchmarks/known_positives.yaml` is what PLAN.md S.5 calls *"the headline number for whether
the atlas works."* The verification wave found its 41 entries had never been checked. The
reconciliation pass (`docs/drafts/benchmarks/RECONCILIATION.md` +
`MERGED_known_positives.candidate.yaml`) found something worse and more specific.

**BM-PATH-007 demanded "exactly one" compartment transition while BM-PATH-011 asserted the very
second transition it denied.** `doi:10.1038/s41598-019-40631-5` settles it in consecutive clauses
— pyruvate in via the MPC complex, 2-KIV out to the cytosol. BM-PATH-011 was right; BM-PATH-007 is
now "exactly twice", with the start compartment named so the count has a defined scope, and the
two entries cross-reference each other so the inconsistency cannot return silently.

The consequence is the part worth keeping: because one entry demanded an exact count the other
contradicted, **no atlas run could ever have satisfied both — the set had no achievable maximum
score.** S.5's headline number was not unmeasured, it was *unobtainable*, and the defect would
have surfaced as a low recovery rate blamed on the extraction pipeline.

**18 of 41 statements are proposed for change**; the other 23 keep statement and expected outcome
and gain only real evidence. **78 of 78 spans re-resolved exact, 0 absent, 0 spliced** — and three
draft quotes that failed first pass were *repaired against the source rather than accepted*, which
is the behaviour that makes the rest of the number mean anything.

Two results worth singling out:

* **BM-MIT-006 was contradicted.** "No established CRISPR-Cas route for editing yeast mtDNA" is
  outdated; and the mitoTALEN leg was **withdrawn outright rather than restated**, because the only
  mitoTALEN paper in the corpus is about *plant* mitochondria.
* **An earlier wave's claim was itself checked and refuted.** The suggestion that PLAN.md's
  0.411 g/g bound came from a xylose mix-up is wrong: the arithmetic is 1:1 from glucose and 5:6
  from xylose, **both 0.41142 g/g**. The bound is correct and the carbon-balance check stands —
  and for DUET specifically, the C5 route carries no yield penalty.

**One thing needs you before the set can serve as the measuring stick.**
`tests/test_benchmarks.py` has 17 passing and 1 failing against the candidate:
`test_unverified_entries_say_no_source_was_consulted` requires any `unverified` entry's evidence to
contain "no source consulted". The file's model has only two states — *nobody looked* and
*curator-promoted* — and **there is no state for "sources consulted, read and quoted, but not
promoted"**, which is exactly what an agent operating under L.5 must produce. The agent did not
game the test, which it could have by quoting the old string; a three-state assertion is proposed
instead. **Resolving that coupling, then flipping `verified` on the supported entries, is a curator
act.**

---

## 5a. PLAN.md's own ⚠ debt, discharged — and the proxy that does not proxy

All **58** ⚠ marks in PLAN.md are now audited (`docs/drafts/warnings/PLAN.yaml`), completing the
sweep the earlier wave began on the three design documents. **68 of 68 quotes re-resolved exact, 0
absent, 0 spliced**, re-verified programmatically from the `fulltext_asset` rows rather than from a
working cache.

| already_covered | confirmed | incomplete | not_in_corpus | overstated | **wrong** |
|---|---|---|---|---|---|
| 15 | 14 | 13 | 8 | 7 | **1** |

**Five of the 58 are the same claim marked in two or three places**, so a fix applied once leaves
the document wrong elsewhere.

### The one `wrong`, and it is load-bearing

**Ethanol Red is a diploid. B.4 chose it as the industrial proxy for its
"aneuploid/polyploid-typical architecture ⚠".** Four corpus papers call it diploid, MATa/α; none
calls it aneuploid or polyploid. The repo's own `data/omics/reference_genomes.yaml` adds that the
pinned assembly `GCA_029255905.1` **cannot resolve aneuploidy at all** — so the justifying property
is contradicted by the literature *and* unverifiable from the assembly chosen to represent it.

This reaches further than one line. DUET's real chassis is an industrial **polyploid**
(`DUET_TARGET.md` §5.3), so the proxy does not proxy the property it was selected for — and the
previous wave's ploidy-scaling argument for strategy E's mtDNA gene dosage buys roughly **2×, not
4×**, if the only industrial genome in hand is diploid.

### The four that would change a build or a decision

1. **The benchmark set is weak in the same way twice.** BM-BNK-style entries expect
   `gpd1Δ gpd2Δ` to *"impair"* anaerobic growth; the corpus says it **prevents** it, rescuable by
   acetaldehyde or acetoin. That is the identical strength-inversion wave 1 found in BM-PATH-007.
   **Two instances is a pattern**: the set needs re-reading for `expected_outcome` *strength*, not
   only for factual support — an atlas returning the literature's own wording would fail its own
   measuring stick. The same record surfaces something PLAN.md omits entirely: glycerol-negative
   mutants lose **osmotolerance**, which is disqualifying for high-gravity fermentation.
2. **BY4741/S288C has elevated spontaneous petite formation**, attributed to a HAP1-disrupting
   transposon — and the entire mitochondrial programme runs on that lineage (B.4 admits BY4741 as
   the deletion-collection tool base). **A strategy-E insert-retention experiment in BY4741 could
   report loss that is really background petite formation**, and the atlas would store it as
   evidence against the strategy. This is an experimental-design warning, not a documentation one.
3. **"Transport of alcohols" is a day-one gene group with no members and no mechanism.**
   Isobutanol crosses the plasma membrane by **passive diffusion**; FPS1 is a glycerol channel and
   belongs to the glycerol branch, not to alcohol efflux. Meanwhile the transport gap that *is*
   real — 2-KIV out of the matrix — stays uncounted.
4. **PLAN.md gives two different sizes for its own core corpus, and the measurement settling it
   has been in the repo since 2026-09-19.** B.2 says 400–800 isobutanol papers; H.2 says "low
   thousands". `DATA_VOLUME.md` measured **768** production-scoped and **1,027** unrestricted,
   against **6,072** for the comparable ethanol query — an **~8× asymmetry, not the ~25–50×** the
   scoping argument rests on. The same non-propagation sizes transient storage at **3–4 TB** for a
   corpus measured at **~48–51 GB**, in the wrong units.

### Worth a minute each

* **Zymomonas is not a yield ceiling.** The only head-to-head in the corpus is a **tie** — yeast at
  95% of theoretical, *Z. mobilis* "also" 95%, the advantage being in *specific productivity*. Its
  sole admission rationale (B.4 role 5: calibrating what a yield fraction can reach) is not served,
  and **criterion E2 is calibrated on it.**
* **"Early isobutanol reports questioned on carbon-balance grounds" is unsourceable.** Zero papers
  across 1,309 readable full texts dispute another's numbers. The bound check is justified anyway;
  this particular rationale is not, and the project has better evidence for the risk in its own
  reports.
* **The thermophilic-parts heuristic is refuted in the corpus.** TaAlDH, sourced on the
  thermostability↔solvent-tolerance correlation, shows "a significant decrease in activity" at 2%
  isobutanol. No cofactor-switched archaeal or thermophilic variant exists here at all — every one
  is an engineered mesophile.
* **A phase-0 acceptance gate depends on an artefact the project does not hold.** The criterion
  requires reproducing the published recoded ARG8m marker sequence; the rationale is quoted in the
  corpus but **no paper in it prints the sequence.** It must come from GenBank, and nothing
  schedules that.
* B.3.1's vague "glucose-tolerance evolution" has a name in the corpus — **`MTH1ΔT`** — and the
  paper carrying it is a *pdc*-minus MTH1ΔT strain with an **NADH-preferring KARI**, which is
  simultaneously E1 evidence and the closest thing the corpus holds to the G.6 parts gap.
* **2-phenylethanol is co-produced by the same promiscuous KDC and is not in the adjacent tier**,
  so one of four diagnostic ratios is discarded at admission. The ratio is also *engineerable* —
  KivD S286T shifts it — and that variant is missing from the parts catalog.

---

## 6. The literature-analysis engine

The owner's direction is to use the pipeline at `D:\Agentic\Literature-analysis` (`lit-agent`) for
literature analysis and keep its references separate. That is the right call: it is a mature
7-stage resumable pipeline — Docling layout parsing with a per-page OCR ladder, figure and table
crops, local VLM description with Claude escalation, BGE-M3 dense+sparse embeddings, Milvus — and
`fermdb` has nothing comparable for figures or tables.

**Isolation is achievable with zero edits to lit-agent, but only via a second copy of the repo
tree.** `get_config()` has no `--config` flag and no environment override, and the project root is
derived by walking up from the imported `config.py` — so whichever copy of `src/` is imported
decides the config, the `output/` store, `taxonomy.json` and `groups.json`. The full runbook is in
`docs/drafts/corpus/lit_agent_runbook.md`. The three risks worth naming:

1. `PYTHONPATH` silently not taking, so `lit` resolves to the original repo and every write lands
   on the cellulase corpus. Gate: `doctor` must print the copy's root before any write.
2. **`lit publish` and `lit reindex` default `--recreate=True`**, which drops the `lit_*`
   collections. Plain `lit run` is safe.
3. `taxonomy.json` is **written back on every categorize call**, so a misconfigured run permanently
   injects yeast aliases into the curated cellulase taxonomy — quietly, with no error.

Marginal cost is **$0** if the copy pins `providers: ["claude_code"]`; the API budget on the
original is already exhausted ($16.0056 of $16.00) and a copy would otherwise inherit a fresh
ledger and silently re-authorize the full amount.

### 6.1 The Milvus abort, diagnosed — and it is not what it looked like

`lit-milvus-standalone` is `Exited (134)`, which is SIGABRT and looked alarming. It is a **startup
race, not a data problem**:

```
07:48:40  starting running Milvus components
07:48:45  "init with etcd failed"  error="context deadline exceeded"
07:48:50  All cleanup done, handleSignals goroutine quit
          panic: failed to create etcd client: context deadline exceeded
```

Milvus came up before etcd was accepting connections and panicked on the deadline. `OOMKilled` is
**false**, `TotalMem` 33 GB against `UsedMem` 28 MB at the point of failure, and no segment or
index error appears anywhere. etcd, minio and attu have since been healthy for the better part of
an hour, so the condition that caused it is gone.

*(Aside worth knowing: `docker logs` cannot stream the whole file — it fails partway with
`invalid character '\x00'`, so the container's json log is itself damaged. The crash is only
reachable with `--tail`. That is cosmetic, but it is why a first look at the logs shows a
goroutine dump with no cause attached.)*

**This needs one command, and I was denied permission to run it** (shared-resource guardrail,
correctly). It is yours:

```powershell
docker start lit-milvus-standalone
# or, equivalently:  docker compose -f D:\Agentic\Literature-analysis\docker\docker-compose.yml up -d milvus
```

Give it the 90-second `start_period` before judging health. Take
`docker\milvus_snapshot.ps1 snapshot -WithArtifacts` before any yeast-corpus run — note the
snapshot is cold, and it is also what brings the stack back up.

---

## 7. Decisions that are yours

| question | why it is yours | what is ready |
|---|---|---|
| **The valine-assimilation configuration** | It needs either a new `compartment_strategy` row (a vocabulary change) or a decision that enzyme-activity-only papers are not configurations. Both are scope calls | The promoter, the refusal, and the paper read |
| **Re-tag the 8 false E5 papers** | Changes what the ethanol budget is spent on | The list, from two independent passes |
| **Ethanol Red's ploidy, and whether it stays the industrial proxy** | B.4 picked it for a property it does not have, and the alternative is to pick a different proxy or to state the proxy's limit explicitly | The four papers, and the assembly's own inability to resolve aneuploidy |
| **Re-read the benchmark set for `expected_outcome` strength** | Two independent waves found the same inversion; this is a set-wide re-read, not two fixes | Both instances, quoted |
| **Which background the strategy-E retention experiment runs in** | BY4741's background petite rate could be read as insert loss. Choosing a background is a bench decision | The transposon/HAP1 attribution, quoted |
| **Whether to spend slot 6's 45 records at all** | Three passes say the literature has no matrix-redox anchor. Reporting an unspent budget is the slots document's own stated preference | The counts, three ways |
| **The benchmark `evidence`/`confidence` coupling** | A test encodes a two-state model that has no room for "read and quoted but not promoted". Relaxing it, then flipping `verified`, is a curator act | The candidate file, the failing test named, and a three-state assertion proposed |
| **`programme_fit` values per strategy** | Encodes what DUET is trying to be | The mechanism, seeded `unknown` (D1, previous session) |
| **22.4 GB of excluded `.sra` in S3** | Irreversible and outward-facing | Keys and cost (~$1.10/yr) |
| **Ploidy** | A cost question, never a gate | Candidates 1–4, each priced |

---

## 7. What I would do next, in order

1. **Extract, now that extraction is free of the cap — through the capable tier.** The calibration
   has answered the routing question (§3a) and the `max_turns` defect that blocked that tier is
   fixed. Start with the five landmarks and the 12 pentose papers. Budget ~270–975 s per paper.
   Before scaling to 500–900, try the narrower per-record-kind prompt: if the 42,000-character
   schema is what defeats the local tier, that is the cheapest thing in this report to fix and it
   would change the economics of the whole phase.
2. **Add the `part_expression_records` extraction section**, then its promoter. Every one of the
   seven existing record kinds now has a promoter except `conditions`, which is withheld on
   purpose — so promotion coverage is complete and the next gap has moved upstream, into what the
   extractor is asked for in the first place. `assertion`/`evidence_item` is the larger job after
   that, because J.3's evidence level is *derived* rather than stored.
3. **Fill `pathway_configuration` from the extracted landmarks, then run phase 3's acceptance
   test** — the first time it will ever have been possible to run it.
4. **Re-tag the ethanol layer** before any of its budget is spent.
5. **Diagnose the Milvus abort**, then decide on the lit-agent corpus.

---

## 8. What is still true and worth not forgetting

`assertion` reads **0**. The atlas's central entity — the thing C.1 draws at the top of the
diagram, the unit of knowledge everything else is vocabulary for — has never held a row. Phase 0's
acceptance criterion ("an assertion resolves a complete J.5 chain") passes against a fixture.

Everything above is machinery and content beneath that line. It is real progress and it is not the
same as the atlas having said anything yet.
