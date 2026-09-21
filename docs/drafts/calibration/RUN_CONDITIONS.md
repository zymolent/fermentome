# What the calibration run actually found about the machine, before any recall number

2026-09-21. Everything here was measured, not assumed. It is separated from the recall result
because most of it is a **blocker on the local tier as configured**, and that is a finding in its
own right — arguably a larger one than the recall margin.

## 1. Ollama is on the GPU. That was never the problem.

The project's standing note (start Ollama via `ollama app.exe` or it silently runs CPU-only at
~45× latency) is satisfied:

| check | result |
|---|---|
| `ollama app.exe` process | **present**, pid 9708 |
| `ollama.exe` server | pid 27504 |
| `ollama ps` PROCESSOR | **100% GPU** |
| VRAM | 18.8 GB used of 24.5 GB (RTX 4090) |
| measured throughput, `qwen3.6:27b`, `num_ctx` 8192 | 8 tokens in 0.16 s ≈ **50 tok/s** — GPU speed |
| measured throughput, `qwen2.5:7b-instruct`, `num_ctx` 20480 | 100% GPU, ~100 tok/s |

**So the answer to "is it CPU-only?" is no.** What follows is a different failure with the same
symptom, which is why it is worth writing down.

## 2. The extraction prompt cannot fit the context the local tier is configured for

The rendered extraction prompt is dominated by the **payload schema**, not the paper. Measured on
the frozen set:

| component | size |
|---|---|
| prompt + schema, excerpt excluded | **~42,000 characters ≈ 10,500 tokens** |
| reply reservation | 2,048 tokens |
| floor before a single character of paper | **≈ 12,500 tokens** |

`OllamaProvider`'s guard is correct and fires accordingly — with a 12,000-character window the
run needs **~17,400 tokens**, and with a 6,000-character window still **~16,300**. The configured
default `num_ctx` is **8,192**.

**Consequence: the local extraction tier cannot run at its own default at any window size.**
Not slowly — at all. `num_ctx` must be raised to ≥ 17,500 before a single window is legal. This
is not recorded anywhere in `MODEL_ROUTING.md`; §7c studies the *excerpt* as the limit and
concludes "the excerpt, not the window, is the real limit". On this measurement the schema alone
is a second, independent floor, and it binds first.

## 3. `qwen3.6:27b` could not be run at a legal context at all

| attempt | result |
|---|---|
| `num_ctx` 16,384, 6,000-char windows, one paper | **no return in 900 s** — provider timeout |
| `num_ctx` 16,384, trivial prompt (`num_predict` 8) | **no return in 290 s** |
| `num_ctx` 8,192, trivial prompt | **5.0 s**, 50 tok/s |

The 8,192 request is fast because an instance was *already resident at 8,192*, held by another
consumer on this workstation. A request at a different `num_ctx` requires a second instance;
16 GB of weights plus a 16k KV cache does not fit in the ~5.7 GB left on the card, and Ollama
**blocks indefinitely rather than erroring**. For most of the session `ollama ps` showed the 27B
stuck in `Stopping...` while still holding its 16 GB.

**This is the §7-family failure mode wearing new clothes.** It is not the CPU-fallback trap the
project already knows about; it is a *load* that never completes, and it is indistinguishable
from "a big model is just slow". A 60-hour corpus estimate and an infinite hang look the same
from outside.

**So the local arm was run on `qwen2.5:7b-instruct` instead**, at `num_ctx` 20,480, where the
model loads (5.9 GB, 100% GPU) and answers. `MODEL_ROUTING.md` §7c explicitly leaves this open —
*"Whether the first pass should then run on `qwen2.5:7b-instruct` rather than `qwen3.6:27b` is a
throughput question to settle by measurement"* — so this is a sanctioned substitution, but it
**must be read as such**: the local arm below is the 7B, and the configured 27B is untested
because it could not be made to run.

## 4. The capable tier was broken on a path that had never been executed

`FERMDB_LLM_PROVIDER=agent-sdk` fails on every real paper with:

```
ResultError: Claude Code returned an error result: Reached maximum number of turns (1)
```

Diagnosis: `claude_agent_sdk_runner` in `src/fermdb/llm/providers.py` pins **`max_turns: 1`**.
On a trivial prompt with a trivial schema that is fine (verified: `max_turns=1` returns
`structured_output` correctly). On the real ~42,000-character payload schema the reply does not
complete inside one turn and the SDK errors out. It reproduces at 30,000- and 12,000-character
windows alike, so it is not excerpt size.

Also required before anything ran: **`claude-agent-sdk` was not installed** (`pip install
claude-agent-sdk`, now present). The escalation tier that `MODEL_ROUTING.md` §7a specifies has
evidently never been exercised end to end.

The capable arm here was therefore run through the repo's own `extract_publication` with
`AgentSdkProvider` and a runner identical to the shipped one **except `max_turns: 8`**. Nothing
else was patched. `write=False` throughout — which is exactly what `--dry-run` sets — and
`curate.enqueue_extraction` is never called.

## 5. A schema migration landed mid-session, from another session

The live database is at schema **v9**; the working tree's `SCHEMA_VERSION` was bumped to **v10**
by a concurrent session while this run was in progress (`git status` shows
`src/fermdb/db/__init__.py`, `migrations.py`, `schema.sql`, `vocabularies.py` modified). The
first probe of the session ran fine; the next one failed with `SchemaVersionError`.

**The real database was not migrated.** A copy was taken to the scratchpad, migrated there, and
every run pointed at it with `FERMDB_DB_FILE`. `C:\Users\kangk\fermdb-data\fermdb.sqlite3` is
still at v9 and was never written to.

## 6. What was and was not touched

* Every extraction ran with `write=False` / `--dry-run --no-enqueue`. **Zero curation tasks
  created**; the queue stands where it did, at 95 against the 180 cap.
* Nothing written to `data/`, nothing written to the project database.
* No `confidence` value set, no `verified` flag flipped.
* New files: `docs/drafts/calibration/` only.
* One environment change: `pip install claude-agent-sdk` (reversible, named above).
