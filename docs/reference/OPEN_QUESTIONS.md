# Open questions

Updated 2026-09-19 after the scoping decisions. Four questions are now **resolved**, one
**changed its answer** because the scope changed, and the mitochondrial goal adds four new ones.

## Decisions taken

| # | question | answer | consequence |
|---|---|---|---|
| D1 | Deliverable | **Route answers first** — phases 0–3 plus a decision checkpoint, ~4.5–5.5 months | No UI, no agents, no knowledge graph, no omics. PLAN.md Q.5 lists the deferrals and what each costs to add |
| D2 | mtDNA engineering | **A research goal**, not just modelled | `docs/design/MITOCHONDRIAL_PROGRAM.md`; the mitochondrial genetics corpus enters the critical path as phase 1b |
| D3 | Lab capability | Full yeast toolkit **plus** mitochondrial capability | Strategy E is rated `frontier` but `available_here: true` — reachable, still correctly costed |
| D4 | Curation | Solo, full-time | Phase 1 at 8–10 weeks is tight but achievable; full cross-host coverage retained |

---

## Q2 — PostgreSQL or SQLite? *(answer changed)*

The original recommendation was PostgreSQL. **With the route-first scope, that recommendation no
longer follows from its own reasoning**, and the honest move is to say so rather than defend it.

The Postgres case rested on five premises. The scope cut removed four of them:

| premise | still true? |
|---|---|
| Concurrent writers — pipelines, agents and a curator at once | **No.** Solo, and agents are deferred |
| `pgvector` co-located with filterable metadata | **No.** Semantic search is deferred |
| Materialized views for derived evidence levels | **Weakly.** At this data size a plain SQLite view recomputes fast enough |
| JSONB for as-reported payloads | **No.** SQLite's JSON1 covers it |
| Partial and expression indexes for the per-evidence-type constraints | **No.** SQLite has both |

**Revised recommendation: SQLite, accessed through SQLAlchemy Core from the first line of code.**

The reason Postgres was chosen up front was that the engine is expensive to change later —
`genome-db` priced its own escape at 646 call sites. But that cost came from **raw SQL scattered
across the codebase**, not from SQLite itself. Routing every query through a query-builder layer
from day zero makes the engine a configuration detail, which dissolves the dilemma instead of
paying for it in advance.

Revisit at the phase 3.5 checkpoint. The trigger to switch is a second concurrent user, a web UI,
or semantic search — any one of them, and the migration is a connection-string change plus the
dialect-specific bits, not a rewrite.

---

## Q4 — Licensing *(mostly resolved, one task remains)*

Single-user and not redistributed means KEGG, MetaCyc, BRENDA and YEASTRACT content can be stored
locally for personal research use under most terms ⚠. The half-day licence review is still a
phase-0 task — it is cheap and it constrains the export path — but it is no longer a blocker.

**Default:** store locally, mark `redistributable = false` on anything licence-constrained, and
let the export path refuse those rows. That keeps a future decision to publish from becoming a
retroactive problem.

---

## Q7 — Model tier and extraction budget *(open, needed for phase 1)*

Phase 1 is ~500–900 papers of extraction. Cheap model for triage, capable model for extraction and
evidence audit, everything cached by `(input_hash, model, prompt_version)`.

**Needed:** a monthly ceiling. Measure precision and recall of a cheap versus a capable model on
the first 20 papers and let that decide, rather than intuition — that measurement is a phase-1
deliverable in its own right.

---

## Q10 — Are figures digitized? *(open, and now more pressing)*

More relevant than before: isobutanol papers frequently report time courses only as figures, and
the corpus is small enough that losing those values matters proportionally more.

**Default:** digitize endpoint values only (final titer, yield, productivity), mark them
`digitized`, never digitize a time course in phase 1. Count the affected papers during phase 1 and
revisit with a real number.

---

## Q12 — Naming *(open, trivial, decide in phase 0)*

The directory is `yeast-alcohol-db`; the project is now isobutanol-first and multi-host. A
product-neutral name ages better. Costs nothing to change before the package exists.

---

# New questions from the mitochondrial programme

None of these block phase 0. All four should be answered **before phase 1b ends**, because they
determine what strategy E's ranking actually means.

## M1 — Which chassis strain, concretely? *(STALE — superseded by DUET_TARGET.md §5.3)*

**This question is answered and the answer is not the one below.** `docs/design/DUET_TARGET.md`
§5.3 records that the chassis is **an industrial polyploid the owner already holds, ~120 g/L
ethanol, marker-free multiplex editing**, and states in terms that the earlier CEN.PK113-7D
recommendation was wrong. CEN.PK113-7D is a **comparator for quantitative physiology**, not the
chassis. This section was never updated to match, and a reader taking it at face value would
re-open a settled decision.

*Superseded text, kept because the trade it describes is still the right trade for choosing a
comparator:* CEN.PK113-7D has the best quantitative physiology and is the metabolic-engineering
standard ⚠; BY4741 has the tool ecosystem and the deletion collection; an industrial background
has the robustness. They are not interchangeable, and published isobutanol comparators cluster in
particular backgrounds.

### What actually remains open

Not *which* strain, but *what its properties are*. `ISOBUTANOL_PROGRAM.md` §6 defines
`chassis_profile` and every field of it is empty, so the 360 enumerated routes are ranked against
no chassis at all — a generic answer to a specific question. Needed, in rough order of value:

| field | why the ranker needs it |
|---|---|
| **ploidy** | DUET names ~15 loci. That is 15 edits in a haploid and 15 x ploidy otherwise, unless editing is genuinely marker-free and multiplex. This single number converts the build into an estimate. |
| ρ⁺/ρ⁰ status | DUET is a matrix pathway; a ρ⁰ chassis would be disqualifying, not inconvenient |
| Pdc status | DUET requires Pdc-**positive** (DUET_TARGET §5.1); confirming it closes the largest determinant of pyruvate availability |
| existing deletions | how much of the competing set is already gone |
| measured isobutanol tolerance | caps the useful titre; without it every route's ceiling line reads "toxicity-limited ~X g/L" |
| xylose utilisation today | DUET's whole substrate partition is C5 → isobutanol; whether the strain already ferments xylose is a large fork |
| transformation efficiency, markers | whether a 15-edit campaign is weeks or quarters |

## M2 — ρ⁰ derivatives and *kar1-1* partners: in hand, or to be made?

Strategy E needs a ρ⁰ recipient for biolistic transformation and a karyogamy-deficient mating
partner for cytoduction ⚠. Whether these exist in your strain background, or must be constructed
in it, is the difference between weeks and months — and it changes strategy E's feasibility rating
from `available_here` to `available_after_strain_construction`.

## M3 — Does the production chassis need to respire? *(ANSWERED 2026-09-20)*

**The owner's answer, verbatim:**

> Respiration is not an absolute biological requirement for pathway discovery, but functional
> respiration is the preferred requirement for the final industrial production strain unless a
> respiration-deficient strain demonstrates a compelling and scalable process advantage.

A conditional default with an explicit escape clause, and it separates two phases the atlas was
treating as one. **Discovery may use respiration-deficient backgrounds freely. Production defaults
to respiring.** Neither is a prohibition.

### Making the escape clause checkable

"A compelling and scalable process advantage" has to be testable or every route author will claim
it. The atlas requires all four of these before a respiration-deficient chassis may be proposed
for production:

1. **A paired comparison.** Same route, same parent background, respiring versus deficient. Not
   "the respiration-deficient route beat a different route" — that is exactly the counterfactual
   error PLAN.md B.3.1 already names for *PDC* deletion.
2. **A named metric**, recorded with its `condition_context`: titre, yield, or volumetric
   productivity. "Better" without a metric does not count.
3. **Evidence at scale.** The programme targets TRL 5 at 5,000 L. A shake-flask advantage is a
   discovery result, not a scalable one, and does not clear the bar alone.
4. **Survival of the process conditions.** DUET recovers by CO2 stripping, and an advantage
   measured in a sealed vessel may not survive continuous stripping ⚠. The comparison must run
   under ISPR, or be flagged explicitly as untested under it.

What does **not** clear the bar: an unpaired comparison, a flask-only result, or an advantage in a
metric the 5,000 L process does not preserve.

### What this settles, and what it opens

* **Strategy E is not excluded.** Displacing *COX2*/*COX3* to host an mtDNA insert stays available
  for discovery. `mtdna_insertion.respiration_retained = false` becomes a route property carrying a
  conditional burden, not a disqualification. `MITOCHONDRIAL_PROGRAM.md` §2.1's `rescue_strategy`
  field is how a route discharges that burden.
* **Two questions become live**, and neither is the owner's to answer:
  - Does the matrix NADH that Adh3 generates actually reach Pos5, or is it competed for by the
    respiratory chain? The corpus can probably answer this — 24 stored full texts mention POS5 or
    mitochondrial NADH kinase, 29 mention *NDI1* or internal NADH dehydrogenase.
  - Does a presequence-targeted matrix pathway still import, and does Ilv3 still acquire its
    [4Fe-4S] cluster, under the chosen regime? No precedent found so far; expect this to be a real
    gap and possibly a bench measurement.
* **A cost correction.** `doi:10.1093/femsyr/foae006` states that Pos5 converts NADH to NADPH *by
  consuming ATP*. The redox loop is not free, which makes the NADH-preferring KARI alternative
  (removing the NADPH requirement entirely) more attractive than the DUET note's §7 sketch implies,
  not less.

### Not yet enforced in code

Recorded here, and **nothing reads it yet**. The route ranker has no respiration term and
`chassis_profile` has no loader, so this policy cannot currently change a ranking. To enforce it:
a `respiration_retained` property on the route model, a penalty term that flags rather than
excludes, and the paired-comparison test above as a gate on promoting such a route to production
candidate. Flagged so this does not become another curated fact that was written down and never
wired up.

## M4 — Analytical capability for the higher-alcohol panel

The adjacent-product tier (PLAN.md B.1) treats the isobutanol : isoamyl alcohol :
2-methyl-1-butanol ratio as diagnostic of decarboxylase specificity and of which ketoacid pool is
draining. That only pays off if your GC method resolves and quantifies all three.

**If it does not**, say so early: the atlas will still record co-reported ratios from the
literature, but your own strains will not contribute to that axis, and route diagnosis loses one
of its better signals.
