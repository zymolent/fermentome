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
