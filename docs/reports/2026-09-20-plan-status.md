# Plan status — 2026-09-20

Measured against PLAN.md section Q's phases and their stated acceptance criteria, not against
effort spent. Row counts are from the live database.

## The one-line summary

**The machinery is built and proven; the atlas is nearly empty of scientific content.** 35 of 61
tables hold rows, but every table that holds a *claim about biology* — `measurement`, `strain`,
`modification`, `pathway_configuration`, `assertion`, `bottleneck`, `condition_context` — holds
zero. That is not a surprise and it is not a failure of design: W.2 predicted it in writing.
*"Curation throughput, not compute, is the rate limit."* It is now the observed state.

## By phase

| phase | status | what is actually true |
|---|---|---|
| **0 — Foundations + recoder** | **complete** | Repo, config, CI, 61-table schema, recoder, S288C nuclear + mtDNA under table 3. Every stated acceptance criterion passes in `test_fixture.py`: the fixture loads, an assertion resolves a full J.5 chain, L1/L5 derive correctly, and an unrecoded `CUN` run filed against `mitochondrial_matrix` is rejected while the same enzyme presequence-targeted is not. **Against fixtures, though — `mini_atlas`, not real data.** |
| **1 — The isobutanol core** | **~15%** | The curated pathway is in (2 pathways, 16 reactions, every one balance-checked). The genomics acceptance criterion is met: 36 DUET genes resolved by parsing and cross-checked against the matrix. Everything else is absent — `pathway_configuration` 0, `measurement` 0, `bottleneck` 0, `part_expression_record` 0. 14 parts exist as *candidates*, not as demonstrated host × compartment records. |
| **1b — mtDNA genetics corpus** | **not started** | No translational activator map, no transformation-method records, no marker systems, no heterologous-ORF precedents. `mtdna_insertion` 0. |
| **2 — Ethanol reference layer** | **not started** | E1–E6 criteria are defined and the 1,927-record admission worklist is exported and with you. No record curated. |
| **3 — Route enumeration** | **built, unvalidated** | 360 routes, six gates, component scores, 144 knowledge gaps — all working. But its acceptance test is *"the enumerator re-discovers every published configuration"*, a recall test against phase 1. Phase 1 has no configurations, so the test cannot run. See the note below. |
| **3.5 — Decision checkpoint** | **not started** | Needs 1–3. |
| **4 — Omics layer** | **~60%** | Acquisition and quantification done: 172 runs, 111.95 GB in S3, 99 runs requantified against a mitochondria-complete transcriptome, matrices built, 675 functional annotations. Missing is the half that makes it analysable — `condition_context` 0, `sample` 0, Tn-Seq not represented as perturbation evidence. |

## Two things worth stating plainly

**Phase 3 was built before phase 1, and cannot pass its own acceptance test.** The enumerator is
sound and its gates find real things — the 2-ketoisovalerate transport gap, the table-3 recoding
requirement that separates strategy C from E. But *"re-discovers every published configuration"*
is a recall measurement against curated literature, and there is none. Until phase 1 has content,
the ranking runs on feasibility and gap-counting with `score_evidence` NULL on all 360 routes —
which the CLI states on every run rather than letting the ranking look complete.

**Work was done outside the phase plan, and it was worth it.** Literature acquisition (section H)
ran far ahead: 5,164 publications resolved, 1,308 full texts stored, 3,856 queued for manual
download. That is the raw material phases 1, 1b and 2 all consume, and having it in hand is why
those phases are now throughput-limited rather than blocked.

## What actually remains, in dependency order

1. **Extraction at volume.** One paper is extracted (7 records, Zone I, awaiting your review). The
   `SessionProvider` path works and costs nothing. This is the only thing standing between the
   current state and phase 1.
2. **Curation.** Every extracted record is Zone I `proposed` and needs a human. 7 tasks are
   queued. Phase 1 explicitly requires full human review of every quantitative claim.
3. **Phase 1 content** — configurations, measurements, bottlenecks — which falls out of 1 and 2.
4. **Phase 3's recall test**, once 3 exists, which is what tells us whether the enumerator is
   trustworthy.
5. **Condition annotation** for phase 4's contrasts; F.3 blocks every contrast until then.
6. **Phase 1b and 2**, both of which are corpus curation against literature already in hand.

## Where the estimate stands

Phases 0 and most of 4's infrastructure are done, which the plan budgeted at roughly 7–9 weeks.
Phase 3's code is done ahead of schedule. Phases 1, 1b and 2 — the content — are nearly all
ahead, and the plan budgets 13–17 weeks for them, essentially all of it human curation time.

The honest read: **the project is ahead on everything a machine can do alone and has not started
the part that needs you.** The 20-paper calibration PLAN.md calls for — measuring the real
curation rate before sizing later phases — has not been run, and it is the next thing that would
turn these week estimates into something grounded.

---

# Update — later the same day

Eleven commits since the section above. **No phase acceptance criterion has moved**, and that is
the most important sentence here: `measurement` 0, `strain` 0, `pathway_configuration` 0, exactly
as before. Phase 1 is still ~15%.

What changed is not progress through the plan but the discovery that **the plan had a hole in it,
and the hole was load-bearing.**

## The hole

`accept` writes nothing into Zone R — correctly, since collapsing accept and promote would mean
accepting silently created canonical data. It defers to a separate curator action. **That action
did not exist.** Nothing in `src/` wrote `measurement`, `strain`, `modification`,
`condition_context`, `bottleneck` or `experiment`; only tests did.

So this morning's "what remains" list was wrong in its ordering. It said extraction, then
curation, then phase 1 content falls out. It does not fall out. A curator could have reviewed all
55 proposals perfectly and every one of those tables would still have read zero, with nothing
anywhere reporting that the work had not landed.

That is now built, with 69 of 76 proposals leading somewhere.

## What the machinery found on the way

Each of these was invisible until something tried to read the data back.

| found | how |
|---|---|
| `competing`, `genes`, `carrier` never reached the database | building the Pathway page; `data/pathways/*.yaml` recorded them and the INSERT named none |
| `carbons`, `redox`, `pair`, `adenylate` likewise | reading the loader properly after the first three |
| No migration path existed at all | needing one; the only route past a version bump was delete-and-rebuild |
| `strains` had no genotype field | Wess et al.'s 17 genotypes going in as 17 bare names |
| `modification_types.tsv` has 16 types, the table's CHECK accepts 9 | writing the modification promoter |
| Wess: 6 of 17 strains extracted | a measurement referencing a strain nobody proposed |
| Watanabe: 3 of 22 strains, and the best numbers missed (230/221 mg/L against 94/83) | the same check |
| My own deletion series was wrong | reading the results section instead of the abstract |

The last one is worth keeping. I reported `JWY04 + gpd1/2 → 1.32` and `+ ald6 → 2.09` as if added
straight to JWY04. Both strains carry **Δadh1**, and the paper is explicit that deleting *ADH1*
alone did not increase isobutanol — it enhanced glycerol formation, which is *why* gpd1/2
followed. I made the same error the extraction did: reading the abstract's prose as a lineage.
With genotypes now parsed, that question is a set membership test rather than a reading of
English.

## Where today's work sits in the plan

Mostly **nowhere**, which is worth being plain about:

* The query layer is a prerequisite for Q.5's deferred "Web UI", not a phase.
* Promotion is phase-0/1 infrastructure the plan assumed and never listed.
* The migration mechanism is not in the plan at all.

None of it is scope creep — each was blocking the step in front of it — but none of it advances a
phase either. The phase table above still stands.

## The revised dependency order

1. **Curation.** 76 proposals, every span verifying. Now the only thing between here and phase 1
   content, because the step after it exists.
2. **Phase 1 content**, which now genuinely does fall out of 1.
3. **Phase 3's recall test**, once there are configurations to recall.
4. Condition annotation, phase 1b, phase 2 — unchanged.

## Two decisions waiting on you

* **`modification.type`'s CHECK** accepts 9 values; the curated vocabulary defines 16. The
  curated file is the source of truth, so the table is wrong — but which nine more to model is
  curation, not mechanics. 2 of 12 queued modifications are blocked on it.
* **`conditions` → `condition_context`.** The extraction emits one record per facet;
  `condition_context` is one immutable hash-deduplicated row per whole context. Nothing in a
  payload says which facets belong together, and a wrong grouping invents a context that
  measurements would then be compared across. 6 proposals blocked.

## The estimate, unchanged and now better grounded

Still ahead on everything a machine can do alone, still not started on the part that needs a
person. The 20-paper calibration — measuring the real curation rate before sizing later phases —
has still not been run, and it is still the thing that would turn week estimates into numbers.
