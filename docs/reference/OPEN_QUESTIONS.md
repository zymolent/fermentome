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

## M1 — Which chassis strain, concretely?

CEN.PK113-7D has the best quantitative physiology and is the metabolic-engineering standard ⚠;
BY4741 has the tool ecosystem and the deletion collection; an industrial background has the
robustness. They are not interchangeable, and published isobutanol comparators cluster in
particular backgrounds.

**Why it matters now:** the route ranker scores against a chassis profile (`ISOBUTANOL_PROGRAM.md`
§6). Ranking without one produces a generic answer.

## M2 — ρ⁰ derivatives and *kar1-1* partners: in hand, or to be made?

Strategy E needs a ρ⁰ recipient for biolistic transformation and a karyogamy-deficient mating
partner for cytoduction ⚠. Whether these exist in your strain background, or must be constructed
in it, is the difference between weeks and months — and it changes strategy E's feasibility rating
from `available_here` to `available_after_strain_construction`.

## M3 — Does the production chassis need to respire?

The sharp one, and it is a genuine design fork.

Inserting into *COX2* or *COX3* displaces that gene and costs respiration unless it is rescued
(`MITOCHONDRIAL_PROGRAM.md` §2.1). Whether that is acceptable depends on the process:

* Under **anaerobic or strongly fermentative** production, losing respiration may cost little
  directly — but note that mitochondrial protein **import requires an inner-membrane potential**,
  which respiration-deficient cells maintain by other means ⚠, and that **Ilv3 is an
  [Fe-S] enzyme** whose cluster assembly depends on mitochondrial Fe-S biogenesis ⚠. A
  respiration-deficient matrix is not automatically a functional one for this route.
* Under **aerobic or respiro-fermentative** production, displacing a *COX* gene is likely
  disqualifying without rescue.

**This question should be answered before any locus is chosen**, because it determines which loci
are available and therefore which leaders and activators are in play.

## M4 — Analytical capability for the higher-alcohol panel

The adjacent-product tier (PLAN.md B.1) treats the isobutanol : isoamyl alcohol :
2-methyl-1-butanol ratio as diagnostic of decarboxylase specificity and of which ketoacid pool is
draining. That only pays off if your GC method resolves and quantifies all three.

**If it does not**, say so early: the atlas will still record co-reported ratios from the
literature, but your own strains will not contribute to that axis, and route diagnosis loses one
of its better signals.
