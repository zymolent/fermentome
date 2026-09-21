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
| **D13** | **Do not run the lit-agent pipeline yet.** | Its Milvus standalone is `Exited (134)` — SIGABRT, `OOMKilled=false`. Both corpora share one server. Pushing 127 papers into a store that just aborted, before knowing why, risks the cellulase corpus for no urgency |

---

## 6. Decisions that are yours

| question | why it is yours | what is ready |
|---|---|---|
| **The valine-assimilation configuration** | It needs either a new `compartment_strategy` row (a vocabulary change) or a decision that enzyme-activity-only papers are not configurations. Both are scope calls | The promoter, the refusal, and the paper read |
| **Re-tag the 8 false E5 papers** | Changes what the ethanol budget is spent on | The list, from two independent passes |
| **Whether to spend slot 6's 45 records at all** | Three passes say the literature has no matrix-redox anchor. Reporting an unspent budget is the slots document's own stated preference | The counts, three ways |
| **A title/checksum gate on ingest** | 3 of 127 were the wrong paper. Cheap to add; I did not, because it changes acquisition policy | The three DOIs, quarantined |
| **`programme_fit` values per strategy** | Encodes what DUET is trying to be | The mechanism, seeded `unknown` (D1, previous session) |
| **22.4 GB of excluded `.sra` in S3** | Irreversible and outward-facing | Keys and cost (~$1.10/yr) |
| **Ploidy** | A cost question, never a gate | Candidates 1–4, each priced |

---

## 7. What I would do next, in order

1. **Extract, now that extraction is free of the cap.** Start with the five landmarks and the 12
   pentose papers. Route by whatever the calibration measurement says.
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
