# The unattended work plan — decisions taken, and the order of work

2026-09-21. Written because the owner asked for maximum unattended progress and explicitly
delegated the calls that can be delegated. Everything in §1 is **decided and being acted on**;
everything in §2 is held for the owner because acting on it alone would be wrong, not because it
is hard.

The governing constraint has not changed and this plan is shaped entirely around it: **curation is
the rate limit, and no agent may curate** (PLAN.md L.5). So every wave below is chosen for one
property — *it does not add to the 95-proposal queue*. The single exception is Wave 6, which is
capped and comes last.

---

## 1. Decisions I am taking, and how to reverse each

Each of these is reversible, recorded, spends no money, touches no bench, and promotes no data.
That is the test I applied. Where a document already stated a default, I am adopting the stated
default rather than inventing one.

| # | question | **my call** | why | to reverse |
|---|---|---|---|---|
| **D1** | The ranker — B beats C on a hardcoded 0.80 vs 0.60 (handover's open finding) | **Keep `feasibility` exactly as it is. Add a separate `programme_fit` term from a curated file, and give `rank()` an explicit `objective`: `easiest` (default, unchanged) or `programme`.** `explain()` states which question was asked. | Option "make feasibility chassis-aware" was on the table and is **wrong**: `MITOCHONDRIAL_PROGRAM.md` §4 deliberately separates *is this technique possible at all* from *is it possible for you*, and folding programme fit into feasibility destroys that distinction. The real defect is that the ranker answers "easiest" while being read as "best" — so name the objective instead of silently changing it. | Delete the term; default behaviour is byte-identical today |
| **D2** | Agents writing Zone R (the L.5 tension I raised) | **Strict reading. Agents draft to `docs/drafts/` only. I run `verify_span` on every quote. Only I move a file into `data/`, at `confidence: medium` maximum. No agent ever writes a `confidence` or flips `verified`.** | L.5 is unambiguous and the cost of obeying it is one file move. The precedent set by v1 of the activator map was never examined; I am not extending it. | Loosen later if the drafts prove clean |
| **D3** | Q10 — digitize figures? | **Adopt the document's own stated default**: endpoint values only (titer, yield, productivity), marked `digitized`; never a time course in phase 1. Add a counter so the revisit has a real number. | The default was already written and is sound; leaving it "open" was costing decisions downstream. | One line in OPEN_QUESTIONS.md |
| **D4** | Q12 — rename the project? | **No. Close it.** The package is already `fermdb`, which is product-neutral. The directory name is cosmetic. | Renaming churns `paths.yaml`, every doc path and the git remote for zero functional gain. "Costs nothing to change before the package exists" — the package exists. | `git mv`, any time |
| **D5** | Q4 — licensing | **Adopt the stated default**: store locally, `redistributable = false` on licence-constrained rows, export path refuses them. I will record per-source terms as I encounter them rather than booking a half-day review up front. | The default already protects the only irreversible thing (publishing something we may not). | Unchanged; the review still happens before any export |
| **D6** | Extraction volume | **Hold the handover's 180-proposal cap.** | It is a standing instruction and the arithmetic behind it is right: 95 proposals ≈ 2.4 h of review already unreviewed. | Owner raises it |
| **D7** | Wiring debt found yesterday | **Fix it**: a loader for `activator_map.yaml` → `mtdna_insertion`, and the `never_attempted` `knowledge_gap` rows §2.3 claims exist. | Both are the documents' own stated intent, unimplemented. This is the "recorded and never wired up" failure mode the handover names; it is now at instance six. | Ordinary revert |
| **D8** | Which 20 papers for the gold-standard calibration | **I choose them**, stratified: 8 isobutanol-yeast, 4 isobutanol-other-host, 4 mtDNA-engineering, 4 ethanol-reference, all with stored full text, none already extracted. | The set has to be fixed *before* the models see it (S.2: thresholds fixed before the data). Someone has to pick; the stratification is the defensible part, not the identity of any one paper. | Swap papers before the run, not after |

**A note on D1 that matters.** The *values* of `programme_fit` are not mine to set — they encode
what DUET is trying to be. I am building the mechanism and seeding it with `unknown` for every
strategy, which leaves rankings untouched. Filling it in is §2's first item.

---

## 2. Decisions held for the owner

Not deferred out of caution — these genuinely require information or authority I do not have.

| question | why it is yours | what I will have ready |
|---|---|---|
| **22.4 GB of excluded `.sra` in S3** — delete or keep | Irreversible and outward-facing | The exact keys and the cost of keeping (~$1.10/yr under Intelligent-Tiering) |
| **`programme_fit` values per strategy** | Encodes the programme's intent | The mechanism, seeded `unknown`, plus my recommendation with reasons |
| **Ploidy, isobutanol tolerance, xylose use, transformation efficiency** | Bench facts about a strain only you hold | The `chassis_profile` fields waiting, and what each unlocks in the ranker |
| **Monthly extraction ceiling (Q7)** | Money | The recall measurement that should decide it (Wave 4) |
| **The M3 pilot-scale bar** | Your process knowledge; the handover flags it as possibly wrong | It stays as written until you amend it |
| **The GC higher-alcohol panel half-day** | Bench time | The argument for doing it before the first build, already in OPEN_QUESTIONS M4 |
| **The 95 proposals** | L.5. Agents propose; they never promote | `review.html`, regenerated, smallest paper first |

---

## 3. The waves

Each wave is fully parallel internally. Waves 1–5 add **zero** curation tasks.

### Wave 1 — Verify the benchmark set · 6 agents · **running now**

`known_positives.yaml`: 41 entries, **0 verified**, all sharing one placeholder evidence string.
S.5 calls recovery against this set *"the headline number for whether the atlas works"* — so the
measuring stick is currently unmeasured. Nothing else has this value-to-effort ratio.

One agent per category: `pathway_compartment` (11), `competing_pathway` (6),
`mitochondrial_genetics` (6), `negative_control` (6), `cofactor_redox` (5), `ethanol_reference` (4),
`tolerance` (3).

Each returns, per entry: a verbatim quote + DOI + offsets, **or** `not_in_corpus` — which is a
finding, not a failure. Drafts land in `docs/drafts/benchmarks/`. I span-verify every quote; the
owner flips `verified`.

The six negative controls are the sharpest test in the set: an agent that "confirms" BM-NEG-003 by
finding an isobutanol enzyme in mtDNA has found either a major paper or its own hallucination, and
the span check says which.

### Wave 2 — Finish the phase-1b corpus · 5 agents

`MITOCHONDRIAL_PROGRAM.md` §3 lists eight content types; three are done. The five left are disjoint
searches over the **398 mtDNA papers already stored**, one YAML draft each:

transformation method records (~30–60) · marker systems and what each costs (~10) · stability and
heteroplasmy (~10) · allotopic expression attempts (~20) · ρ⁰/ρ⁻ physiology (~10)

OPEN_QUESTIONS M2 already counted the keyword hits: 43 / 34 / 61 / 35 / 30. Several are
half-answered by material that surfaced yesterday (DFS160, pPT24, cox2-62 selection, `kar1-1`
cytoduction timing, allotopic *ATP8*/*VAR1*/*ATP9*).

### Wave 3 — Discharge the ⚠ debt · 4 agents

144 marks across the docs. `MITOCHONDRIAL_PROGRAM.md`'s own header orders it — *"Verify every ⚠ in
section 3 against primary literature before building anything"* — and it has never been run.
Priority: MITOCHONDRIAL_PROGRAM §3 (23), ISOBUTANOL_PROGRAM (28), then PLAN.md's scientific ⚠
(58, many are cost arithmetic and can wait), DUET_TARGET (3).

Yesterday was the worked example: of three §2.1 claims checked, **two were incomplete and one was
wrong about the corpus**.

### Wave 4 — The gold-standard recall calibration · paired runs

The measurement two documents call a phase-1 deliverable and nobody has made. Same 20 papers (D8)
through the local tier and the capable tier; compare **what each missed**, because
`MODEL_ROUTING.md` §7 judges the local tier on **recall, not precision** — *"you cannot review what
was never proposed."*

`extract run --dry-run --no-enqueue` ⇒ zero curation tasks. Needs Ollama started via
`ollama app.exe`, or it silently runs CPU-only at 45× the latency.

**This is the wave that converts every week-estimate in the plan into a number**, and it decides
the routing for all 500–900 phase-1 papers. If local recall holds, phase 1's extraction cost goes
to roughly nothing.

### Wave 5 — Code, by me, not agents

1. **D1**: `programme_fit` term + `rank(objective=...)` + `explain()` naming the objective. Default
   behaviour byte-identical; a regression test asserts that.
2. **D7a**: loader `activator_map.yaml` → `mtdna_insertion`, so BM-MIT-004's query shape resolves.
   Today the knowledge is in the repo and the atlas still answers nothing.
3. **D7b**: the `never_attempted` `knowledge_gap` rows, with the precedents attached.
4. **M3 enforcement**: a `respiration_retained` route property and a flagging penalty — written
   down on 2026-09-20 and never wired.
5. Re-read the strategy-E respiration gate against the non-displacing insertion site found
   yesterday (`intergenic_upstream_COX2`, `respiration_retained: true`), which the gate predates.

### Wave 6 — The capped extractions · 5 agents · **needs the owner first**

Avalos 2013, Atsumi 2008, the KARI 2×2, 3-HP, Sherkhanov. One agent per paper, each returning a
payload JSON; the harness span-checks every quote deterministically, so a subagent cannot get past
the gate that a 7B model cannot get past either.

**Gated on the owner working through some of the 95** — 85 proposals of headroom under the cap is
4–5 papers, and spending it before any of the existing queue is reviewed would be exactly the
queue-stuffing this plan exists to avoid.

---

## 4. What this leaves on the owner's desk, in order

1. **Review proposals.** Start with `10.1016/j.meteno.2016.03.004`, 7 proposals, ~10 minutes,
   and it produces the first Zone R row the atlas has ever held.
2. **Flip `verified`** on whatever Wave 1 finds a real source for.
3. **`programme_fit` values** — after I show the mechanism and my recommendation.
4. **The S3 deletion**, one word either way.
5. **Ploidy**, when convenient. A cost question, never a gate.

Everything else runs without you.
