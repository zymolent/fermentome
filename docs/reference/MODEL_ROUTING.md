# Model routing — where Fable 5.1 is safe, and where it is not

Which agent roles in this project justify the top model tier, argued from the project's own
evidence architecture rather than from general intuitions about capability.

The short answer: **Fable belongs on structure and on adversarial review. It does not belong
anywhere that a deterministic check or a human curation gate is already doing the work — and it
must never be allowed to substitute for either.**

---

## 1. The decision rule

Three questions per agent role. Fable is justified when the answer to all three is "no".

| question | if yes | if no |
|---|---|---|
| **Contained?** Does a wrong output land in Zone I behind the curation gate? | cheaper model is safe — its errors cost curator time, not atlas integrity | error reaches the atlas |
| **Checkable?** Is there a deterministic validator — span offsets resolve, units parse, yield ≤ theoretical max, tests pass, code-table check? | cheaper model is safe — the validator is model-independent | only a human or nothing catches it |
| **Low blast radius?** Does the error affect one row rather than defining a container? | cheaper model is safe — one bad row is one correction | error propagates into every row written afterwards |

## 2. The evidence from this session

Two workflows built phase 0 (7 agents, ~982k subagent tokens, then a 4-agent repair round). They
produced a natural experiment.

**What the curation gate caught: nothing structural.** The gate reviews *facts entering the
database*. It has no opinion about the semantics of a Python module.

**What actually went wrong.** `COMPARTMENT_TABLE` mapped `mitochondrial_matrix → table 3`. That is
wrong: the genetic code follows the **encoding genome**, not the destination compartment, so a
nuclear gene targeted to the matrix by a presequence is translated under table 1 and must not be
recoded. The bug:

* was authored by the **top model tier**, in a fast low-ceremony pass;
* passed **52 tests**;
* was invisible to every curation gate, because no fact had been curated yet;
* contradicted this project's own design document, which stated the correct rule;
* would have told a bench scientist to recode a construct that must not be recoded.

It was found by a **high-effort reviewer explicitly pointed at cross-file seams**.

**The conclusion is not "use Fable to author structure".** Fable *did* author it, and got it
wrong. The conclusion is sharper and more useful:

> **The model tier that matters most is the reviewer's, not the author's.**
> Structural errors are systematically invisible to tests, so only an independent pass with
> different framing finds them. A cheaper author plus an expensive adversarial reviewer would
> likely have reached the same outcome for less.

**What cheap models got wrong, and why it did not matter.** Three Sonnet agents produced three
different confidence vocabularies, and one wrote `high` confidence citing a fermdb source file.
Both were caught immediately — the first by a schema `CHECK` that made the value unstorable, the
second by the reviewer. Contained, checkable, low blast radius: exactly the profile where a cheap
model is the right call.

## 3. The counterintuitive risk

**Capability increases the plausibility of errors.** A stronger model produces wrong facts that
survive human review *longer*, because they read better and cohere with their surroundings.

So for output destined for human review, model tier has an **ambiguous safety sign**: it lowers
the error rate and raises the cost of each surviving error. This is why the architecture does not
rely on model trust for extraction — it requires **verbatim spans with verified character
offsets** (PLAN.md H.5), which is a model-independent check. Spend on validators before spending
on tier.

## 4. Where Fable 5.1 belongs

### Building fermdb

| role | model | why it is safe there |
|---|---|---|
| Schema, evidence model, route model, comparability classes | **Fable, high effort** | Uncontained. No gate downstream. Defines the container every later row lives in |
| **Adversarial review / seam verification** | **Fable, high effort** | The highest-value slot in the project. Errors here are silent by construction |
| Compartment / genetic-code / unit semantics | **Fable** | Encodes biology in code, where the curation gate cannot see it |
| Fixture, loaders, pattern-following code | Sonnet | Tests catch it; cheap to re-run |
| Vocabularies, data entry | Sonnet | Schema `CHECK`s and tests catch shape errors; the facts are `unverified` anyway |
| Paths, config, CLI | Sonnet | Tests catch it |
| CI, tooling, formatting | Haiku | ruff and pytest catch it |
| Benchmark set drafting | Sonnet draft → **Fable review of the negative controls** | Every entry is `unverified` and curator-gated, so containment is strong. *Retrospective: I ran this at high-effort top tier and over-spent — the containment made that unnecessary, except for the negative controls, which quietly set the discrimination bar* |

### The atlas's own runtime agents (PLAN.md L.2)

| agent | model | why |
|---|---|---|
| Literature triage, dedup, classification | Haiku / Sonnet | High volume; criteria are explicit; audit sample catches drift |
| Dataset discovery | Sonnet | Contained — a human accepts before anything downloads |
| QC | Haiku | Thresholds live in code and are fixed before seeing data. The agent explains a verdict, it does not set one |
| Condition extraction | Sonnet + span validator | Offsets verified deterministically; every record human-reviewed in phase 1 |
| Measurement extraction | Sonnet + validators | Units parse, yield ≤ theoretical max, basis mandatory |
| Engineering extraction | Sonnet, **Fable for isolated-effect attribution** | Attributing an outcome among several simultaneous modifications is judgement, not extraction |
| **Pathway mapping, conflict reconciliation** | **Fable** | Reconciling databases that disagree on compartment or cofactor is structural; a wrong call propagates into every route |
| **Evidence agent (adversarial audit)** | **Fable, high effort** | The highest-value runtime slot — the only scalable defence against a plausible claim nothing supports |
| **Atlas curator (promotion proposals)** | **Fable** | Proposes only. Never auto-commits |
| **Design narration** | **Fable** | May not introduce a node the deterministic traversal did not return |

## 5. Where Fable 5.1 must NOT be used

These are safety rules, not cost rules. A better model does not relax any of them.

1. **As a substitute for the curation gate.** PLAN.md L.5: no agent may promote its own proposal.
   Model tier is irrelevant to that rule, and §3 explains why a stronger model arguably makes the
   gate *more* necessary, not less.
2. **To assign a confidence value or an evidence level.** `confidence: unverified` means "asserted
   but never checked against a source". A model recalling a fact is not a source, whatever its
   tier. **Model capability must never appear anywhere in the derivation of a confidence value.**
3. **Anywhere determinism is required.** Route enumeration and ranking, codon recoding, the
   compartment gate, `context_hash`, deduplication, evidence-level computation. PLAN.md G.7
   requires route scores shown as inspectable components; a model call there would destroy the
   property that makes the output defensible. These are **code, not agents**.
4. **Writing to Zone R or Zone H.** Agents write to Zone I only.
5. **High-volume mechanical work.** Wasteful, and the marginal accuracy does not beat a validator
   that costs nothing per call.

## 6. Mechanics

**Workflow agents:** `agent(prompt, { model: 'sonnet', effort: 'low' })`. Omit `model` to inherit
the session model. `effort: 'high'` on review and schema slots; `'low'` on mechanical ones.

**Persistent subagents:** `.claude/agents/<name>.md` with `model:` frontmatter, as `genome-db`
does — it pins `architect` and `reviewer` to Fable and routes routine work to Sonnet and Haiku.
Worth creating here for: `architect`, `reviewer`, `curator`, `extractor`, `data-ops`, `docs-keeper`.

**A rule of thumb that fell out of this session:** spend the tier on the pass that *looks for*
problems, not the pass that produces work. Review is cheap relative to rework, and structural
rework after curation has started is the most expensive thing this project can do.

## 6a. Track split, decided 2026-09-20

The project owner has scoped the two tiers by track, and the split is clean:

| track | models | rationale |
|---|---|---|
| **Literature** — discovery, triage, extraction, curation drafting | **Local (Ollama) by default**, escalating to Claude on trigger (§7a) | High volume, contained in Zone I, span-validated. Free inference buys a bigger audit sample and unlimited prompt iteration |
| **Genomic / transcriptomic** — AWS staging, quantification, genome ingest, QC | **Claude tiers throughout** | Lower volume, higher unit stakes, and much of it is structural: the gene layer is the join key for the entire atlas, and the mtDNA annotation feeds construct design |

Within the omics track, §4's rule still decides the tier: **Fable** for the genome ingest, the
protein QC gate, the mtDNA table-3 annotation and the translational-activator loci (all
structural or scientific, and uncontained); **Sonnet** for the AWS staging, the salmon wrapper and
the CLI (pattern-following, tests catch it); **Fable** for the review.

## 7. The local tier

This machine has an RTX 4090 (24 GB VRAM) running Ollama, with `qwen3.6:35b`, `qwen3.6:27b`,
`gpt-oss:20b`, `gemma4:31b`, `qwen2.5:7b-instruct`, and the vision model `qwen2.5vl:7b`. That is a
fourth tier, and it is **free at the margin**, which changes where the §1 rule lands.

| use | local model | why it is safe |
|---|---|---|
| Triage / classification of ~3,500 abstracts | `qwen2.5:7b-instruct` | Contained, audit-sampled, criteria explicit. At API prices this is ~1.4M tokens; locally it is free, so the audit sample can be *larger* for the same budget |
| First-pass extraction draft | `qwen3.6:27b` | Safe **only because span verification is model-independent** (§3). The validator, not the model, is what rejects a number that is not in the paper |
| Scanned or figure-only PDFs | `qwen2.5vl:7b` | Reads page images where text extraction fails. Anything it produces is `digitized` — a distinct evidence grade under C.6 rule 3 |
| Bulk re-runs after a prompt revision | any local | Re-running is free, so prompt iteration stops being a budget decision |
| Structure, evidence levels, conflict resolution, adversarial review | **never** | §4 and §5 apply unchanged. Free is not a safety argument |

### The inversion, and the trap underneath it

§3 argued that capability increases the plausibility of errors. Run backwards, that means a
weaker local model's errors are **more obvious**, so for span-verified extraction each surviving
error costs a reviewer less to spot. Cheap and weak is not simply worse here.

**But the risk does not disappear, it moves.** A weaker model fails more often by *omission* —
the measurement it never extracted, the modification it did not notice. False positives are
caught by the validator and by review. **False negatives are invisible: you cannot review what
was never proposed.**

So the local tier must be evaluated on **recall, not precision**. The phase-1 gold standard
exists for exactly this: run the same 20 papers through the local model and through the top tier,
and compare what each *missed*. If local recall holds, it does the bulk work for nothing. If it
does not, the top tier extracts and local does triage only.

That measurement is a phase-1 deliverable, and it should decide the routing — not the fact that
local inference happens to be free.

## 7a. Escalation from local to Claude

Local models run first on the literature track; these four triggers hand a document to Claude.

| trigger | why |
|---|---|
| **Self-consistency disagreement** — run the local model twice and escalate where the passes differ | The interesting one. Two passes are free locally, which makes this a signal that would be prohibitively expensive with a metered model. It targets the **false-negative** risk of §7 directly: a field one pass extracts and the other misses is exactly the omission that review cannot see |
| **Validator failure after one retry** — span will not resolve, schema invalid, yield exceeds the theoretical maximum | The local model has demonstrably failed on this document |
| **High-value corpus, unconditionally** — all 33 isobutanol × mitochondria papers | 33 papers is a rounding error in cost and they are the core of the strategy C versus E decision |
| **Curator flag** from the queue | A human has looked and wants it done properly |

Mechanics:

* Every extraction records `extracted_by_tier`, so the phase-1 gold standard can measure
  local-versus-Claude **recall** per field type (§7). Any field type where local recall is poor
  becomes an always-escalate rule rather than a judgement call.
* Escalation carries a **budget cap**; when it is exhausted, documents queue as
  `escalation_pending` rather than silently falling back to the local result.
* Escalation never changes a confidence value. A Claude-produced extraction is still
  `unverified` until a curator checks it — §5 rule 2 is about the derivation of confidence, and
  tier is not part of it.

## 8. Cost shape

Round 1 was 3 top-tier, 3 Sonnet, 1 Haiku across 7 agents for ~982k subagent tokens. Applying §4
retrospectively — Sonnet for the benchmark draft, keeping Fable for schema and review — would
have cut that materially with no loss of safety, because containment was already doing the work.

The one place not to economise is the reviewer. It found the only error in the round that neither
tests nor the curation gate could have caught.
