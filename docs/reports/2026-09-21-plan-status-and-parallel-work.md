# Plan status, and what can be done in parallel without a curator

2026-09-21. Measured against PLAN.md section Q's phases and their stated acceptance criteria, not
against effort spent. Row counts are from the live database. This supersedes the phase table in
`2026-09-20-plan-status.md`; the reasoning there still holds and is not repeated.

## The one-line summary

**Unchanged in the way that matters: `measurement` 0, `strain` 0, `modification` 0,
`pathway_configuration` 0, `assertion` 0. 95 proposals, reviewed by nobody.** Since yesterday the
atlas gained a complete mitochondrial activator map, a heterologous-ORF precedents table, 240 more
enumerated routes and 172 omics samples — and moved zero acceptance criteria that depend on
curated content, because all of them terminate in a human.

63 tables, **41 with rows, 22 empty**. Every empty one holds a claim about biology.

---

## 1. Phase by phase

| phase | status | what is actually true | moved today? |
|---|---|---|---|
| **0** — Foundations + recoder | **complete** | Acceptance passes in `test_fixture.py`. Against fixtures, not real data. | no |
| **1** — Isobutanol core | **~15%** | Pathway in (2 pathways, 16 balance-checked reactions), 36 genes resolved. `pathway_configuration` 0, `measurement` 0, `bottleneck` 0, `part_expression_record` 0. 5 papers extracted of 366 extractable. | no |
| **1b** — mtDNA genetics corpus | **2 of 5 clauses pass** | Activator map complete (9 loci, all quoted); precedents table complete. Clause 1 fails: landmark builds unextracted. See `2026-09-21-mtdna-precedents-and-phase-1b.md`. | **yes** |
| **2** — Ethanol reference layer | **not started** | E1–E5 defined, 1,927-record worklist exported. No record curated. | no |
| **3** — Route enumeration | **built, cannot be tested** | 600 routes, 3,000 steps, 6 gates, 208 knowledge gaps, 2 chassis profiles. Its acceptance test is recall against phase 1's configurations, of which there are none. | no |
| **3.5** — Decision checkpoint | **not started** | Needs 1–3. Two of `MITOCHONDRIAL_PROGRAM.md` §5's five questions were answered today (Q3 locus/leader, Q4 precedents); Q1, Q2, Q5 need phase 1. | partly |
| **4** — Omics layer | **~60%** | 172 runs acquired and quantified, matrices built, 675 annotations. `condition_context` 0 of 172 samples, `experiment` 0, Tn-Seq not represented as perturbation evidence. | no |

### The two structural facts behind that table

**Phase 3 was built before phase 1 and still cannot pass its own acceptance test.** Unchanged from
yesterday. The enumerator is sound; the recall measurement it needs has nothing to measure against.

**Phase 1b's criterion borrows phase 1's landmark-build requirement.** The mitochondrial half is
now done. The half that gates it is isobutanol curation.

---

## 2. The binding constraint, with the arithmetic

W.2 predicted it: *"Curation throughput, not compute, is the rate limit."* Here is what that costs
at current rates.

5 papers extracted → **95 proposals**, ~19 per paper. The handover measures the smallest paper at
7 proposals in ~10 minutes, so ≈1.5 min per proposal.

| | |
|---|---|
| proposals now queued | 95 ≈ **2.4 hours** of review |
| isobutanol papers extractable today | **366** (triage-included, full text stored) |
| proposals if all were extracted | ~6,950 ≈ **174 hours** ≈ 4.4 weeks full-time |
| handover's standing cap | **180 proposals** — ~85 left, about **4–5 more papers** |

PLAN.md budgets phase 1 at 8–10 weeks, so 4.4 weeks of pure review is *consistent with the plan* —
it is not a crisis. But it means one number decides everything downstream and **it has never been
measured**: the real per-proposal review rate, and the recall of a cheap model against a capable
one. `OPEN_QUESTIONS.md` Q7 and `MODEL_ROUTING.md` §7 both call the 20-paper calibration a phase-1
deliverable. It has not been run.

**The consequence for this question.** More agents produce more proposals. More proposals make the
binding constraint worse, not better. Any parallel plan that ends in "…and then a curator reviews
it" is not parallelisation, it is queue-stuffing. So the tracks below are chosen for the opposite
property: **work whose output does not enter the curation queue.**

---

## 3. What multiple agents can genuinely complete, without a curator

Four tracks. All read-only against the corpus, all produce verifiable artifacts, none adds to the
95.

### Track A — Verify the known-positive benchmark set — **6 agents** — highest value

`data/benchmarks/known_positives.yaml`: **41 entries, 0 verified, all 41 carrying one identical
placeholder** — *"Background knowledge, no source consulted."*

S.5 calls recovery against this set **"the headline number for whether the atlas works."** That
headline number is currently meaningless, because the measuring stick is itself unmeasured. Nothing
else in the project has this ratio of value to effort.

Slice by the file's own categories, one agent each:

| category | entries |
|---|---|
| pathway_compartment | 11 |
| competing_pathway | 6 |
| mitochondrial_genetics | 6 |
| negative_control | 6 |
| cofactor_redox | 5 |
| ethanol_reference | 4 |
| tolerance | 3 |

Each agent: search the cached corpus for a real source for each `statement`, return either a
verbatim quote with its DOI and offsets, or **"not in this corpus"** — which is a finding, not a
failure. The file's own rule keeps the last step yours: an entry becomes usable only when a human
overwrites `evidence`, raises `confidence` and flips `verified`. **Agents find the source; you flip
the bit.** Clean separation, no queue.

The six negative controls are the most interesting: an agent that "verifies" BM-NEG-003 by finding
an isobutanol enzyme in mtDNA has found either a major paper or its own hallucination, and the span
check tells you which.

### Track B — Discharge the ⚠ debt — **4 agents**

144 marks across the docs, each meaning "written from memory, never checked":

| doc | ⚠ |
|---|---|
| PLAN.md | 58 |
| ISOBUTANOL_PROGRAM.md | 28 |
| DATA_VOLUME.md | 24 |
| MITOCHONDRIAL_PROGRAM.md | 23 |
| OPEN_QUESTIONS.md | 8 |
| DUET_TARGET.md | 3 |

`MITOCHONDRIAL_PROGRAM.md`'s own header: **"Verify every ⚠ in section 3 against primary literature
before building anything."** That instruction has never been executed, and §3 is what informs
construct design.

Today's session is the worked example of the method and of why it pays: three ⚠ claims in §2.1 were
checked, **two were incomplete and one was wrong about the corpus** (Atp22 was in the corpus all
along, in the ATP8 paper). Output is corrections to documents, not rows in a queue.

Start with MITOCHONDRIAL_PROGRAM.md §3 and ISOBUTANOL_PROGRAM.md — those inform the bench.
DATA_VOLUME.md's 24 are mostly cost arithmetic and can wait.

### Track C — Finish the phase-1b corpus — **5 agents**

`MITOCHONDRIAL_PROGRAM.md` §3 tables eight content types. Two are done as of today, one was
already done. Five remain, each a self-contained search over the **398 mtDNA papers already in
hand**, each producing one curated YAML:

| content | §3 budget | status |
|---|---|---|
| mtDNA reference under table 3 | 1 genome | ✅ done (phase 0) |
| translational activator map | ~10 loci | ✅ **done today** — 9 rows |
| heterologous-ORF precedents | ~10–25 | ✅ **done today** — 5 + 1 failure |
| transformation method records | ~30–60 papers | ⬜ agent |
| marker systems, with what each costs | ~10 | ⬜ agent |
| stability and heteroplasmy data | ~10 | ⬜ agent |
| allotopic expression attempts | ~20 | ⬜ agent |
| ρ⁰/ρ⁻ physiology | ~10 | ⬜ agent |

Perfectly parallel: disjoint topics, no shared state, one file each. Several are already
half-answered by material surfaced today — DFS160, pPT24, the cox2-62 selection, `kar1-1`
cytoduction timing, allotopic *ATP8*/*VAR1*/*ATP9*/*COX2* — which is a good sign for the yield and a
reason to run them now rather than later.

### Track D — Run the 20-paper gold-standard calibration — **agents in pairs**

The measurement two documents call a phase-1 deliverable and nobody has made. Same 20 papers
through the local tier and the capable tier; compare **what each missed**, because
`MODEL_ROUTING.md` §7 is explicit that the local tier must be judged on **recall, not precision** —
*"you cannot review what was never proposed."*

`extract run` already has `--dry-run` and `--no-enqueue`, so this generates **zero curation tasks**.
Needs Ollama started via `ollama app.exe` or it silently runs CPU-only.

This is the track that converts every week-estimate in the plan from intuition into a number, and
it decides the routing for all 500–900 papers of phase 1. If local recall holds, phase 1's
extraction cost goes to roughly nothing.

---

## 4. What agents must not do here, and one honest tension

**L.5 is explicit.** No agent may write Zone R or H, assign an evidence level, resolve a conflict,
create a `gene_group` membership, set a QC threshold, delete anything, or promote its own proposal.
So: the 95 proposals, the ranker design decision, the M3 pilot-scale bar, ploidy, the 22.4 GB of
excluded `.sra` objects, and phase 3.5's recommendation are all yours and stay yours. The 3,856
manual-download queue needs institutional access, not more agents.

**The tension worth naming rather than hiding.** Tracks A–C write curated Zone R artifacts —
`activator_map.yaml`, `heterologous_orf_precedents.yaml`, benchmark evidence fields — and L.5 says
no agent writes Zone R. Today's files were written by a model too; the previous session's v1 of the
activator map was as well. The precedent exists and it was not examined when it was set.

The defensible line, and the one I would hold: **an agent returns candidate quotes; the span check
is code and runs before anything lands.** Every quote in today's two files was re-resolved at its
offsets by `verify_span` — 45 of 45, after one correction where a PDF rendered ρ as a private-use
glyph. That check does not care which model produced the quote, which is exactly why it is the
right gate. What an agent must never do is write a `confidence` value or flip `verified`.

If you want the stricter reading instead — agents draft into `docs/` and only a human moves it to
`data/` — say so, and I will run the tracks that way. **It is your call and I have not assumed it.**

---

## 5. What I would run, in order

1. **Track A** (6 agents) — the benchmark set. Nothing else makes the atlas's headline number mean
   anything, and it is a few hours of parallel work.
2. **Track D** (paired agents) — the calibration. Decides phase 1's economics before phase 1 is
   sized. Needs Ollama up.
3. **Track B** (4 agents) — the ⚠ audit, MITOCHONDRIAL_PROGRAM §3 first, because it informs
   constructs.
4. **Track C** (5 agents) — the rest of the phase-1b corpus.
5. **Only then**, and only after you have worked through some of the 95: the five named extractions
   the handover lists — Avalos 2013, Atsumi 2008, the KARI 2×2, 3-HP, Sherkhanov — **capped at 180
   proposals**, which is 4–5 papers and no more.

Tracks A–D together produce **no new curation tasks**. That is the whole reason they are the right
parallel work: they move the project forward along the axis that is not blocked on you, and they
sharpen the one measurement that will tell you how long the axis that *is* blocked on you will
actually take.

---

## 6. Loose ends found while measuring

Not phase blockers, but wrong:

* **Nothing loads `activator_map.yaml` into the database.** `grep` finds no reader anywhere in
  `src/`. BM-MIT-004's query shape is a join over `mtdna_insertion`, which has 0 rows — so a curator
  asking the atlas still gets nothing, even though the knowledge is now in the repo.
* **`knowledge_gap` has no `never_attempted` rows.** 88 `quantitative_value_missing` + 120
  `transport_carrier_unknown` = 208. §2.3 says the atlas records the mtDNA gap as `never_attempted`.
  It does not; the kind is legal and unused.
* **`experiment` is 0 with `sample` at 172**, so no sample links to a publication — which is what
  condition annotation would need first. Phase 4's F.3 pipeline (*"LLM proposes a
  `condition_context` with quoted spans → curator accepts/edits"*) is a fifth parallel track, but it
  ends in the curation queue, so I have left it out of §3 deliberately.
* **One corpus document is unreadable** — an AES-encrypted PDF, `10.2323/jgam.2022.05.001`. Every
  coverage claim in today's work says 1,309, not 1,310, because of it.
