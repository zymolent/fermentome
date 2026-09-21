# The gold-standard recall calibration — result, at the N actually run

2026-09-21. Read `FROZEN_SET.md` for the set and `RUN_CONDITIONS.md` for the machine. This file
is the measurement, and it reports **the N that was run, not the N that was planned**.

## The honest headline on sample size

| | planned | run |
|---|---|---|
| frozen set | 20 | 20, fixed before anything ran |
| **local arm attempted** | 20 | **5** (ranks 1–5: 2 IY, 1 IO, 1 MT, 1 ET — a balanced prefix by construction) |
| **capable arm completed** | 20 | **2** (ranks 1–2, both IY) |
| **papers with BOTH arms, i.e. the paired recall sample** | 20 | **2** |

Why: the capable tier averages **267 s and 975 s** on the two papers it finished and was still
working on rank 3 when the wall-clock budget expired. The local tier had to be re-pointed at a
different model before it would run at all (`RUN_CONDITIONS.md` §3). **N = 2 paired is a pilot,
not the deliverable.** It is reported as 2.

## 1. Paired recall — the 2 papers both tiers completed

"Missed" = a record the capable tier proposed for which the local tier proposed nothing of the
same kind, matched either on a normalised key field or on any character overlap of the two spans.
Both tiers saw the **identical excerpt** (same sections, same window size).

| miss kind | capable proposed | local also proposed | **MISSED** | local recall |
|---|---|---|---|---|
| measurement | 84 | 0 | **84** | **0%** |
| condition facet | 75 | 0 | **75** | **0%** |
| modification | 68 | 0 | **68** | **0%** |
| strain | 55 | 1 | **54** | **2%** |
| bottleneck | 10 | 0 | **10** | **0%** |
| pathway configuration | 8 | 0 | **8** | **0%** |
| co-reported higher alcohol | 1 | 0 | **1** | **0%** |
| **TOTAL** | **301** | **1** | **300** | **0.3%** |

Per paper:

| # | stratum | paper | capable | local | recalled | missed | capable s | local s |
|---|---|---|---|---|---|---|---|---|
| 1 | IY | `10.1016/j.jbc.2026.113228` | 36 | 1 | 1 | 35 | 267 | 15 |
| 2 | IY | `10.1016/j.meteno.2016.01.002` | 265 | **0 (hard failure)** | 0 | 265 | 975 | 132 |

**Local proposals with no capable counterpart: 0.** The local tier found nothing the capable tier
missed.

## 2. Span failures — the thing that is worse than a miss

| | local (`qwen2.5:7b-instruct`, 5 papers) | capable (`claude-opus-5`, 2 papers) |
|---|---|---|
| retained records | 123 | 301 |
| **retained spans that re-resolve exactly** (`verify_span`, raw source) | **123 / 123 (100%)** | **301 / 301 (100%)** |
| offsets wrong *as the model proposed them*, repaired by the harness | 318 repairs | 299 / 301 (99%) |
| **quotes that do not occur in the paper at all** (`quote_absent_from_source`) | **16** | **0** |
| attempts rejected outright by the validator | 2 | 0 |
| **papers lost entirely to unfixable spans** | **2 of 5 (40%)** | **0 of 2** |

Two readings matter here and they point opposite ways.

**The validator works, and that is the good news.** Not one span survived into either tier's
output that does not re-resolve character-exactly in the source. `MODEL_ROUTING.md` §3's claim —
that the architecture does not rely on model trust because span verification is
model-independent — holds up under measurement. The 16 fabricated quotes the local model produced
were all caught; none reached a proposal.

**But nearly every offset was wrong in both tiers.** 99–100% of proposed records needed
`relocate_span` to place the quote where it really is. That is not a tier difference — Opus 5 is
just as bad at counting characters as a 7B — and it means the offset-repair pass is
load-bearing infrastructure, not a nicety. If it were removed, both tiers would score near zero.

**The local failure mode is exactly the one §7 predicted, plus one it did not.** §7 warns about
omission — invisible false negatives. That showed up (0.3% recall). What also showed up is
*fabrication*: on 2 of 5 papers the 7B quoted sentences that are not in the paper, twice in a row,
and the harness correctly threw the whole extraction away. The result is a paper that yields
nothing — which is a false negative arriving by way of a false positive.

## 3. The local arm across all 5 papers it attempted

The paired table above is dominated by one catastrophic paper, so the fuller local picture is
worth stating — even though there is no capable counterpart yet for ranks 3–5.

| # | stratum | status | s | records |
|---|---|---|---|---|
| 1 | IY | ok | 15 | 1 (`strains` 1) |
| 2 | IY | **failed — 2 attempts, fabricated quotes** | 132 | 0 |
| 3 | IO | ok | 214 | 71 (`strains` 27, `modifications` 14, `pathway_configurations` 10, `measurements` 13, `conditions` 7) |
| 4 | MT | **failed — 2 attempts, fabricated quotes** | 35 | 0 |
| 5 | ET | ok | 42 | 51 (`strains` 18, `measurements` 23, `conditions` 10) |

So the 7B is *not* uniformly empty — on ranks 3 and 5 it proposed volumes in the same range the
capable tier produces. **It is unreliable rather than weak**, and unreliability of this shape
(40% of papers yielding nothing, and on rank 1 proposing 1 record where the capable tier found 36)
is worse for a corpus sweep than a uniformly lower yield would be, because there is no signal in
the output that says which papers were dropped.

## 4. Throughput, for the routing arithmetic

| tier | s / paper (measured) | 900-paper phase 1 |
|---|---|---|
| local `qwen2.5:7b-instruct` | 15 / 132 / 214 / 35 / 42 → **mean 88 s** | ~22 hours, free |
| local `qwen3.6:27b` (configured default) | **could not be loaded at a legal context** | not measurable |
| capable `claude-opus-5` | 267 / 975 → **mean 621 s** | ~155 hours of wall clock, subscription-metered |

The capable tier is not cheap in *time* even though it is not metered per token here. Whatever
routing is chosen, 900 papers through Opus at 10 minutes each is a week of continuous running.

## 5. The answer

**No.** On this evidence phase 1 must not route its 500–900 papers through the local tier as a
first-pass extractor.

The measured margin: **local recall 1 of 301 capable-proposed records (0.3%) across the 2 papers
both tiers completed, with 0 of 84 measurements, 0 of 68 modifications and 0 of 75 condition
facets recovered — and 2 of the 5 papers the local tier attempted produced nothing at all because
it fabricated quotes the span validator rejected.**

§7's own decision rule then applies literally: *"If local recall holds, it does the bulk work for
nothing. If it does not, the top tier extracts and local does triage only."* It does not hold.
**Local stays on triage.**

### What would change this answer, and should be measured before it is treated as final

1. **N = 2 paired is a pilot.** The margin is so wide (0.3% vs a useful threshold of, say, 80%)
   that it is unlikely to be a sampling artifact, but it is two papers and both are `IY`. The
   other three strata are unmeasured.
2. **The configured local model was never tested.** This is the 7B. `qwen3.6:27b` is what §7
   routes first-pass extraction to, and it could not be loaded at the ≥17.5k context the prompt
   requires. It might do better. It would also take ~4 min/paper at best, which is most of the
   capable tier's cost without the capable tier's recall.
3. **The prompt may be the defect, not the model.** 42,000 characters of payload schema is a very
   large ask of a 7B, and the schema is what forces the context floor in the first place. A
   narrower per-kind prompt (extract measurements only, then strains only) would be a cheaper
   thing to fix than the routing, and §7a's self-consistency trigger is free locally. **This is
   the experiment I would run next, before accepting the routing conclusion as permanent.**
4. **`--sections` was left at the default.** Both tiers saw 22k–40k characters of a 38k–54k
   character document, so neither tier saw the whole paper; recall is measured relative to the
   capable tier on identical input, which is the right comparison, but it is not recall against
   the paper.
