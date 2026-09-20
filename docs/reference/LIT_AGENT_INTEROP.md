# lit-agent interop — decision and prerequisites

`D:\Agentic\Literature-analysis` ("lit-agent") is a mature literature-extraction pipeline:
~11,000 lines, 176 papers processed, with an OCR escalation ladder, Docling figure/table
extraction, VLM figure description, patents, Milvus semantic search and a gold-set eval harness.
It independently arrived at the same local-first design fermdb specifies — same models
(`qwen2.5:7b-instruct`, `qwen3.6:27b`, `qwen2.5vl:7b`), explicit weak-gates, a deferred escalation
queue, resumable per-stage artifacts.

## Decision, 2026-09-20: keep the two separate; do not adopt lit-agent yet

**fermdb continues to use its own extraction path.** lit-agent is a capability to adopt later,
for the things fermdb genuinely lacks, not a dependency to take on now.

Four reasons, in order of weight:

1. **lit-agent has a live `ANTHROPIC_API_KEY` in `.env` and calls the metered API directly**
   (`claude_client.py:53-58`, `anthropic.Anthropic(api_key=...)`). The project owner has a Claude
   subscription and has directed that no API spend occur. Running lit-agent today *would* spend.
   This is a blocker, not a preference.
2. **It has four uncommitted files** (`cli.py`, `escalation.py`, `vlm.py` modified,
   `figure_diff.py` untracked). Editing a working system on top of someone's work in progress is
   how two people's changes get lost. The corrections below should be made deliberately, not
   mid-flight.
3. **fermdb's own extraction path already works**, validated end to end on `avalos2013.pdf` with
   span verification and a rejected fabricated control. There is no capability gap forcing the
   adoption today.
4. **Dependency weight.** lit-agent needs Docling, Milvus, BGE-M3. fermdb is deliberately
   installable on a bare interpreter; that property is worth keeping until something needs
   breaking it.

## What lit-agent has that fermdb will eventually want

Adopt when the corpus demands it, not before:

| capability | when fermdb will need it |
|---|---|
| OCR escalation ladder (`parse.py`, `ocr.py`) | The first scanned PDF. All nine DUET papers extracted as text, so not yet |
| Docling figure/table extraction | When table-only measurements start being missed |
| VLM figure description | Figure digitisation — open question Q10 |
| `patents.py` (809 lines) | The FTO layer (Gevo/Butamax/DuPont), currently an unstarted gap |
| Milvus + BGE-M3 | Semantic search, deferred to phase 6 |
| `eval.py` + `eval/gold.json` | The phase-1 gold standard and recall measurement |

## Prerequisites before lit-agent can be used here

### 1. Remove the API path (blocking)

`claude_client.py::_ensure()` constructs `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`.

Add a `claude.provider` setting — `api` | `subscription` | `none` — **defaulting to `api` so the
existing cellulase pipeline is unchanged**, and have `_ensure()` honour it:

* `none` → raise `BudgetExceeded`. This is not a hack: lit-agent's own architecture (§9) states
  *"Nothing is ever lost or fails a paper because Claude was down"* — every stage keeps its local
  result and enqueues the hard item to `escalation_queue.jsonl`. Setting `none` uses the designed
  degradation path, and fermdb then drains that queue over the subscription.
* `subscription` → route through the Claude Agent SDK with `CLAUDE_CODE_OAUTH_TOKEN`, the pattern
  `genome-db/env/paths.yaml` uses and fermdb already implements. Note `claude_agent_sdk` is **not
  currently installed** in either environment, and `CLAUDE_CODE_OAUTH_TOKEN` is not set.
  **Vision escalation may not map onto the Agent SDK** — verify before relying on it; the text
  path is the one that matters first.

The `CostLedger` budget gate is priced in dollars per million tokens. Under a subscription there
is no per-token cost, so that gate changes meaning — it becomes a usage/rate limit, not a spend
cap. Do not leave a dollar figure in place implying it still measures money.

### 2. Keep the isobutanol corpus separate from the cellulase corpus (owner's instruction)

`get_config()` is hardcoded to `config.yaml` at the repo root, with `data_dir: "data"` and
`output_dir: "output"` — so a second corpus would land on top of the first. The existing 176
papers are entirely cellulase/*Trichoderma* work (measured: 31 cellulase, 16 trichoderma,
15 patent, 12 thesis filenames; **zero** isobutanol or butanol).

Add a `LIT_AGENT_CONFIG` environment override to `config.py::project_root()`/`get_config()`, then
run the isobutanol corpus under its own `config.isobutanol.yaml` with distinct `data_dir`,
`output_dir`, `manifest` and Milvus collection prefix. Additive, backwards-compatible, and it
keeps the two corpora from ever sharing an artifact directory or a vector collection.

## The integration shape, when it happens

```
fermdb discovery (5,164 pubs) → fermdb acquisition + manual queue → PDFs on disk
                                                                        ↓
                                                     lit-agent (own config, own data dir)
                                                     parse → OCR → figures → categorize
                                                                        ↓
                             bridge: add character offsets, Zone I, confidence = unverified
                                                                        ↓
                                                                  fermdb atlas
```

The two compose cleanly because **lit-agent reads local PDFs only** — it has no OA resolution or
fetching — which is precisely the half fermdb built. They do not overlap.

**The one real gap is offsets.** lit-agent keeps `value_raw` and `raw` verbatim (schemas.py:293,
471, 630) but records no character positions. fermdb will not store a value whose quote does not
re-resolve at stated offsets. Since the verbatim string is retained, the bridge can locate it —
use `fermdb.llm.validate.canonical_source_text()` first, because PDF extraction breaks sentences
across lines and exact matching fails against raw text.
