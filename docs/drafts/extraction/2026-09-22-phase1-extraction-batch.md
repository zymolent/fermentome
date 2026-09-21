# Phase 1 extraction batch — 2026-09-22

Running note. Written as the batch proceeds so that an interrupted run leaves an unambiguous
record of what was done. **Nothing here is a curation verdict**: every run queues proposals and
stops. No task was accepted, rejected or promoted.

Invocation, identical for every run below except the DOI and the `--only-kind` set:

```
PYTHONPATH=src FERMDB_LLM_PROVIDER=agent-sdk FERMDB_LLM_MODEL_EXTRACTION=claude-opus-5 \
  python -m fermdb.cli extract run --doi <DOI> --max-excerpt-chars 12000 \
  --run-id 2026-09-22-phase1 --only-kind <KIND> ...
```

Real runs, no `--dry-run`. Sequential, one process at a time (one SQLite file).

## Before-state (captured 2026-09-22, ahead of the batch)

| | |
|---|---|
| `extraction` rows | 11 |
| `pathway_configuration` rows | 4 |
| `part_expression_record` rows | 0 |
| curation tasks, all kinds | 5 bottleneck / 3 co-reported / 6 condition / 106 measurement / 29 modification / 14 pathway_configuration / 104 strain |
| pending tasks | 17 (`modifications`) |

## Run log

### Run 1 — re-extraction after the structured-abstract sectioner fix (`ad27c35`)

| DOI | kinds | proposed | tokens | extraction id |
|---|---|---|---|---|
| `10.1186/1475-2859-12-119` | strains, modifications, measurements | **117** (strains 44, modifications 47, measurements 26) | 37,649 | `YAA:EXTR:6a4eff5f…` |
| `10.1186/s13068-019-1486-8` | strains, modifications, measurements | **327** (strains 19, modifications 261, measurements 47) | 76,390 | see run log |

`1475-2859-12-119`: 3 attempts, no cache hit, sent 23,345 / 33,240 chars (70% of the document),
131 notes — all of them `span_offsets_repaired`, none a validation failure.
`s13068-019-1486-8`: 4 attempts, no cache hit, sent 34,693 / 49,601 chars (70%), 349 notes, again
all span repairs. **261 modification proposals from one paper is an outlier** and is flagged for
the curator, not resolved here.

### Run 2 — `part_expression_records`, the record kind with no data

All five ran clean, `rc=0`, no validation failure, no failed attempt beyond the retry loop.

| DOI | proposed | tokens | attempts | excerpt sent |
|---|---|---|---|---|
| `10.1016/j.ymben.2017.10.001` | 36 | 23,436 | 4 | 34,199 / 72,303 (47%) |
| `10.1016/j.cels.2019.10.006` | 31 | 21,769 | 3 | 28,199 / 95,333 (30%) |
| `10.1016/j.ymben.2011.02.004` | 32 | 24,952 | 3 | 20,282 / 49,176 (41%) |
| `10.1016/j.jbiotec.2022.09.012` | 7 | 4,376 | 2 | 15,290 / 41,741 (37%) |
| `10.1016/j.meteno.2016.03.004` | 38 | 28,097 | 2 | 19,935 / 26,422 (75%) |
| **total** | **144** | **102,630** | | |

`meteno.2016.03.004` — the valine-assimilation paper that measures enzyme activity per
compartment — is the richest of the five per character of text, which is what the kind was
picked for. `jbiotec.2022.09.012` is the thinnest: it is a catabolite-repression paper, and
7 records for 37% of the document is consistent with it simply having little
compartment-resolved expression evidence to give.

### Run 3 — `strains` + `pathway_configurations` over the extract-first set

(in progress)
