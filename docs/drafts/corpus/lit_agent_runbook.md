# Running lit-agent over the yeast/ethanol corpus in an isolated scope

**Status:** plan only — nothing in this document has been executed.
**Written:** 2026-09-21
**Reference engine:** `D:\Agentic\Literature-analysis` (lit-agent). Read-only. Not modified.
**Target corpus:** `D:\Agentic\bifserver-works\literatures\pdf_included` — **127 PDFs** (the
directory holds 128 entries; the 128th is `_manifest.csv`, which lit-agent ignores because `.csv`
is not in the accepted extension set, `state.py:272`). 196 MB.

---

## 0. Verdict up front

**Full isolation IS achievable with zero edits to the lit-agent source** — but *not* by
overriding config in place. It requires **a second copy of the repo tree**, because:

- `get_config()` has **no `--config` flag, no env-var override, and is `lru_cache`d**
  (`config.py:54-59`). The config file is found by `project_root()`, which walks up from
  `src/lit_agent/config.py` looking for `config.yaml` (`config.py:16-23`). *Which copy of the
  source you import decides which config, which `output/`, which `taxonomy.json` and which
  `groups.json` you get.* There is no other lever.
- `discover_papers()` calls `p.relative_to(cfg.root)` (`state.py:279`). **A `data_dir` outside the
  project root raises `ValueError` on the first file.** So the PDFs must live under the root of
  whichever copy is running.
- `groups.json` is hardcoded to `cfg.root / "groups.json"` (`grouping.py:84`) and is **written**
  if absent (`grouping.py:96`). `units.json` / `substrate_equivalence.json` are likewise
  `get_config().root`-relative (`normalize.py:33,43`). `eval/gold.json` too (`eval.py:165,325`).
  None of these are configurable; all of them follow `cfg.root`, so the copy isolates them.

With a copy in place, **Milvus needs no code change either**: collection names are fully
config-driven (`config.yaml:197-209` → `milvus_store.py:296-316`, `load.py:52-62`). Giving the
yeast run its own collection names isolates it inside the same Milvus server.

**The one thing that is genuinely not configurable is the Milvus `db_name`.** See §5.3.

---

## 1. Answers to the seven questions

### Q1 — Corpus input path

Config key, not a CLI flag. `paths.data_dir` (`config.yaml:8`, default `"data"`), resolved by
`Config.path()` (`config.py:45-51`) relative to the project root. Consumed once, in
`discover_papers()` (`state.py:270`), which `rglob`s it for `{.pdf,.docx,.txt,.jpeg,.jpg,.png,.zip}`
(`state.py:272-275`). `lit run` takes only `--limit` and `--force` (`cli.py:146-152`) — there is
**no `--data-dir`**.

**Can it be pointed elsewhere?** An absolute path outside the repo root **will fail**:
`state.py:279` does `p.relative_to(cfg.root)`, which raises `ValueError` for any file not under
the root. So `data_dir` must resolve to something *inside* `cfg.root`.

Verified workaround (tested, works): a **Windows directory junction** inside the copy's root
pointing at the real PDF folder. `Path.rglob` descends it and `relative_to(root)` succeeds —
I confirmed this against the actual 127 PDFs: `rglob found 127`,
`relative_to → data\10.1006_mben.1999.0140.pdf`. The source folder is only ever **read**
(`parse.py:75`, `figures.py:196` open it with PyMuPDF; nothing writes to `src_path`).

### Q2 — Artifact store, and paper_id collision

`paths.output_dir` (`config.yaml:9`) and `paths.manifest` (`config.yaml:10`) are both configurable
and both root-relative. Everything derived lives under `output_dir`:
`output/<paper_id>/` (`state.py:286`), `manifest.jsonl` (`state.py:206`),
`cost_ledger.json` (`state.py:106`), `escalation_queue.jsonl` (`escalation.py:37`,
`figure_diff.py:60`).

**`paper_id` is content-hashed**: `sha256(file bytes)[:16]` (`state.py:48-54`). Not sequential,
not filename-derived. Consequences:

- Two corpora **cannot** collide on an ID unless the byte-identical PDF is in both — in which
  case collapsing them is the *intended* dedup behaviour (`state.py:280-282`).
- But if two corpora shared one `output_dir`, the same PDF present in both would get **one**
  artifact dir whose `source_paths` and `04_categorize.json` are overwritten by whichever ran
  last, and `manifest.jsonl` would interleave both corpora's rows. `Manifest._save()`
  (`state.py:219-223`) rewrites the *whole* file from its in-memory dict, so a concurrent second
  process would silently drop the other's rows.

→ **Give the yeast run its own `output_dir`.** The copy does this automatically.

### Q3 — Milvus collections

**Configurable.** `milvus.collections.{chunks,papers,figures,tables,measurements,references,
methods,variants,sequences,constructs}` (`config.yaml:199-209`). Ten collections, not four —
the README's "4 collections" is stale; `ACTION_PLAN_v3.md:20-32` documents all ten with live
counts. They are read by name in `ensure_collections()` (`milvus_store.py:296-316`) and again in
`load_paper()` (`load.py:52-62`). **No name is hardcoded anywhere in the write path.**

Renaming them in the copy's `config.yaml` is sufficient and needs **no code change**.

Two caveats:
- `smoke_test()` hardcodes the collection name `"lit_smoke"` and **drops it**
  (`milvus_store.py:369-370, 390`). Harmless — it is not one of the ten — but `lit milvus-smoke`
  is still a write to the shared server. Skip it.
- **`db_name` is NOT supported.** `connect()` does
  `connections.connect(alias="default", uri=uri)` (`milvus_store.py:33-37`) — `uri` is the only
  config key (`config.yaml:198`). pymilvus accepts `db_name=` but it is never passed. To use a
  separate Milvus *database* you would have to edit
  **`milvus_store.py` → `connect()`**, one line:
  `connections.connect(alias="default", uri=uri, db_name=cfg.get("milvus","db_name",default="default"))`.
  *This is not necessary* if you use distinct collection names, which is the recommended route.
  A separate Milvus *instance* (second compose stack on another port) is also possible but costs
  ~1.5 GB of volumes and a second container set for no benefit over renamed collections.

### Q4 — Taxonomy / grouping

| file | path source | configurable? |
|---|---|---|
| `taxonomy.json` | `cfg.path("paths","taxonomy")` (`categorize_norm.py:82,99`) | **yes** — `config.yaml:11` |
| `groups.json` | `cfg.root / "groups.json"` (`grouping.py:84`) | **no** — root-relative only |
| `units.json`, `substrate_equivalence.json` | `get_config().root` (`normalize.py:33,43`) | **no** |

Both non-configurable files still follow `cfg.root`, so the **copy isolates them**. That matters,
because these files are **written back**, not just read:

- `_save_taxonomy()` (`categorize_norm.py:99`) **persists newly learned aliases on every
  categorize call**. Running a yeast corpus against the shared `taxonomy.json` would permanently
  inject yeast aliases into the 74 KB cellulase taxonomy.
- `_load_rules()` (`grouping.py:96`) **writes `groups.json`** from defaults if it is missing.

**What a yeast-alcohol corpus needs instead.** The current rules (`grouping.py:31-73`,
`groups.json`) are cellulase-shaped: `enzyme_group` = Cellulases / Hemicellulases /
Auxiliary-enzymes / Starch-enzymes / Proteases; `organism_group` = Filamentous-fungi / Bacteria /
Yeast (one bucket for all yeast — useless here). Proposed replacement for the copy's
`groups.json` (edit the copy, never the original):

- **`enzyme_group`** (feeds from `enzyme_family`, `grouping.py:76-80`) →
  `Ehrlich-pathway` (alpha-ketoacid decarboxylase, Aro10, Kdc, Pdc1/5/6, alcohol dehydrogenase,
  Adh1-7, Sfa1) · `Valine-biosynthesis` (acetolactate synthase, Ilv2, ketol-acid reductoisomerase,
  Ilv5, dihydroxyacid dehydratase, Ilv3) · `Ethanol-fermentation` (pyruvate decarboxylase,
  alcohol dehydrogenase, hexokinase, Pdc1) · `Redox-cofactor` (transhydrogenase, NADPH,
  glucose-6-phosphate dehydrogenase, Zwf1) · `Stress-tolerance` (Hsp, trehalose synthase, Tps1).
- **`organism_group`** → split the single `Yeast` bucket into
  `Saccharomyces` (S. cerevisiae, S. uvarum, S. paradoxus) · `Non-conventional-yeast`
  (Kluyveromyces, Pichia, Komagataella, Yarrowia, Candida, Scheffersomyces, Ogataea,
  Zygosaccharomyces, Brettanomyces) · `Bacteria` (Escherichia, Corynebacterium, Zymomonas,
  Lactobacillus, Clostridium) · `Filamentous-fungi` (keep, for comparison papers).
- **`theme_group`** → `Strain-Engineering` (keep + crispr, knockout, overexpression, promoter) ·
  `Pathway-Engineering` (flux, cofactor balancing, compartmentalization, mitochondrial targeting) ·
  `Fermentation` (batch, fed-batch, titre, yield, productivity, in-situ product removal) ·
  `Tolerance-Physiology` (isobutanol toxicity, ethanol tolerance, membrane, viability) ·
  `Omics-Systems` (transcriptomics, proteomics, flux balance analysis, GEM).
- **`doc_role`** — no change needed (`grouping.py:68-73` is domain-neutral).

`taxonomy.json` should start **empty (`{}`)** in the copy — it is a *grown* alias map, and the
seed aliases in `categorize_norm.py:23` are cellulase-specific but additive, so a fresh file is
the clean start. `lit retag` ($0, `cli.py:269-277`) re-applies taxonomy + grouping to cached
records, so grouping rules can be tuned after the run without re-extracting.

**One code-level bias to be aware of** (optional to fix): the categorize prompt hardcodes
cellulase few-shot examples — `categorize.py:80-81` says
`"enzyme_family": [...] e.g. beta-glucosidase / cellobiohydrolase / LPMO / xylanase` and
`"organism": ... e.g. "Trichoderma reesei"`. The *field* is generic ("enzymes STUDIED"), so it
will still capture Adh1/Ilv5, but the examples bias the local Qwen extractor. Swapping those two
example strings in the **copy's** `categorize.py` is a 2-line improvement. Not required for a
first run.

### Q5 — State / resumability

Three independent mechanisms, all under `output_dir`:

1. **Per-stage artifact existence.** `Paper.stage_done()` = "does the artifact file exist"
   (`state.py:84-88`), against the `STAGE_ARTIFACTS` map (`state.py:30-42`:
   `01_parse.json`, `02_figures/figures.json`, `03_vlm.json`, `04_categorize.json`,
   `05_chunks.jsonl`, `06_loaded.flag`, `07_patent.json`, `07_translation_en.json`).
   Each stage function early-returns when its artifact exists and `force` is False
   (e.g. `embed.py:205-207`).
2. **`manifest.jsonl`** — per-paper per-stage status/timestamp/error, rewritten atomically
   (`state.py:197-258`). Reporting, not gating.
3. **The load stage double-checks Milvus** — `06_loaded.flag` is not trusted on its own; it
   queries `papers_c` for the `paper_id` and re-loads if absent (`load.py:68-75`). Loads are
   idempotent: delete-then-flush-then-insert by `paper_id` (`load.py:86-93`).

**Would a second corpus confuse it?** Only if it shared `output_dir`. With a separate
`output_dir` there is no shared state at all — including the cost ledger (§Q6). Note that the
Milvus-presence check at `load.py:71` queries whatever `milvus.collections.papers` names, so a
mismatched config (separate `output/`, shared collection names) would produce the worst of both:
the yeast run would see cellulase rows and skip work, or overwrite rows on ID collision.
Rename the collections **and** the output dir, together.

### Q6 — Cost and budget gates

- `budget.claude_budget_usd: 16.00` (`config.yaml:225`), `on_limit: "ask"`,
  `auto_continue_local: true` (`config.yaml:226-228`).
- The gate reads `CostLedger.would_exceed()` (`state.py:181-187`), which **only counts API
  spend** — `in_usd`. Subscription work is tallied separately in `sub_usd`/`sub_calls`
  (`state.py:167-179`) and **never gates anything**, by design.
- Ladder: `claude.providers: ["claude_code", "api"]` (`config.yaml:152`). `ClaudeRouter._dispatch`
  (`claude_router.py:72-96`) tries `claude_code` (the `claude` CLI on the Max subscription) first
  and latches a backend down on `ClaudeUnavailable` or `BudgetExceeded`, handing the *same call*
  to the next. When all are down it raises `BudgetExceeded`, which `pipeline.py:98-102` turns into
  "pause Claude, keep local results, keep processing the rest of the corpus".
  `claude_code.ignore_api_key: true` (`config.yaml:168`) strips `ANTHROPIC_API_KEY` from the CLI
  env so a subscription call can never bill credits.

**Current live state (from `lit claude-status --no-probe`, run read-only):**

```
1  claude_code    configured   C:\Users\kangk\.local\bin\claude.EXE
2  api (credits)  no key       key MISSING; $16.0056 / $16.00 used
Subscription so far: 9 calls, 37,998 in / 3,133 out, $0.2699 of API spend avoided.
API credits so far : $16.0056 / $16.00 (786 calls).
```

The **API budget in the original repo is exhausted and there is no key set**. `ACTION_PLAN_v3.md:34-38`
confirms: *"Budget — EXHAUSTED … Claude escalation is gated off."*

**Cost projection for 127 papers.** README reports ~$8.50 for 150 papers in hybrid mode
(`README.md:152-155`) ≈ $0.057/paper ⇒ **127 papers ≈ $7.20** *if it ran on the API*. That figure
is Sonnet at `$3/$15 per Mtok` (`config.yaml:181`) for the weak-result fallback only; yeast papers
are mostly born-digital journal PDFs (fewer OCR/vision escalations than the cellulase corpus's
theses and patents), so the real number is likely **$4–7**.

**But you should plan for $0.** The copy gets a **fresh `cost_ledger.json`** (it lives at
`output_dir/cost_ledger.json`, `state.py:106`) so the gate resets — which is exactly why you must
set the budget deliberately rather than inherit `16.00`. Recommended for the copy:

```yaml
claude:
  providers: ["claude_code"]      # forbid credit spend entirely (README.md:63)
budget:
  claude_budget_usd: 2.00         # ceiling that only bites if you re-add "api"
```

With `providers: ["claude_code"]`, marginal cost is **$0** — the Max subscription absorbs it, and
`record_subscription()` (`state.py:167`) books it to `sub_usd`, outside the gate. Local stages
(parse, figures, VLM-local, embed, load) are free regardless.

### Q7 — Preconditions

**Milvus is DOWN right now, and it did not stop cleanly.**

```
lit-milvus-attu          running   Up 30 minutes
lit-milvus-etcd          running   Up 30 minutes (healthy)
lit-milvus-minio         running   Up 30 minutes (healthy)
lit-milvus-standalone    exited    Exited (134) 30 minutes ago     <-- SIGABRT
```

`lit doctor` confirms: `Milvus NOT reachable: Fail connecting to server on localhost:19530`.
Exit code **134 = SIGABRT** — an abort, typically `std::bad_alloc` / OOM inside Milvus, not a
clean `docker stop`. **Investigate the crash before loading 127 more papers into it.**

What must be started (`docker/docker-compose.yml`, stack name `lit-agent`, line 11):

```powershell
docker compose -f D:\Agentic\Literature-analysis\docker\docker-compose.yml up -d milvus
# or the whole stack (etcd/minio/attu are already up, so this is a no-op for them):
docker compose -f D:\Agentic\Literature-analysis\docker\docker-compose.yml up -d
```

The `milvus` service (`docker-compose.yml:49-71`) is the only missing piece: image
`milvusdb/milvus:v2.5.4`, ports `19530` (SDK) and `9091` (health), volume `./volumes/milvus`,
`depends_on: [etcd, minio]`. Healthcheck `curl -f http://localhost:9091/healthz`,
`start_period: 90s` — give it **~2 minutes** before trusting a connection failure.
*Per the hard rules I did not start it.*

**What `lit doctor` checks** (`cli.py:24-40`): prints project root, resolved `data_dir`,
resolved `output_dir`, `budget.claude_budget_usd`, the `claude.providers` ladder; then imports
`milvus_store` and calls `connect(cfg)`, reporting reachable / not. **Fully read-only** — no
files written, no collections touched. It is the single best "am I pointed at the right repo"
check, because it prints the resolved root and paths.

**What `lit claude-status` checks** (`cli.py:43-101`): builds a `CostLedger` (read-only load,
`state.py:119-129`) and walks `claude.providers`. For `claude_code` it resolves the CLI binary;
**with `--probe` (the default!) it calls `ClaudeCodeClient.probe()`** (`claude_code_client.py:370-399`),
which runs `claude --version` **and makes a real one-token Claude call** — that call goes through
`_run()` and **writes `output/cost_ledger.json`**. For `api` it just checks
`ANTHROPIC_API_KEY` and prints ledger totals. **Always pass `--no-probe` against the original
repo** — that is what I did.

---

## 2. Recommended layout

```
D:\Agentic\lit-agent-yeast\          <-- the isolated copy (NOT inside either git repo)
  config.yaml                        <-- edited: collections, output, taxonomy, budget
  groups.json                        <-- yeast/alcohol rules
  taxonomy.json                      <-- {}
  units.json, substrate_equivalence.json
  src\lit_agent\...                  <-- copy of the source
  data\                              <-- junction -> D:\Agentic\bifserver-works\literatures\pdf_included
  output\                            <-- yeast artifacts only
```

Why **not** under `D:\project\yeast-alcohol-db`: `output/` will reach several GB (the cellulase
`output/` is 2.3 GB for 176 docs) and `fermdb` treats `data/` and `env/` as *committed curation
layers* — a multi-GB generated artifact store does not belong in that git tree. Keep the engine
beside the reference implementation and let fermdb reference it by path. Disk available on D:
is 527 GB; budget ~3 GB for artifacts and ~1 GB of Milvus growth.

---

## 3. Step-by-step runbook

> Nothing below has been run. Steps marked **[WRITES]** modify something.

### Step 0 — **[WRITES]** Back up first. Yes, take the snapshot.

```powershell
cd D:\Agentic\Literature-analysis
docker\milvus_snapshot.ps1 snapshot -WithArtifacts
docker\milvus_snapshot.ps1 list
```

**Why it is required, even though the plan is isolated:** the yeast run shares one Milvus
*server* with the cellulase corpus. Everything in that server lives in three coupled volume
directories (`docker/volumes/{etcd,minio,milvus}`) — schemas, segment binlogs, WAL. A bad
`ensure_collections(drop=True)`, a typo that leaves a collection name at `lit_papers`, or another
Milvus abort like the `Exited (134)` above can damage the *catalog*, not just one collection.
`ARCHITECTURE.md` §13 states the rule directly: *"Backup before schema/destructive ops: cold
Milvus snapshot + `output/` archive + git tag, captured together (resume ties `output/` to the
DB)"*, and *"Never run `ensure_collections(drop=True)` against the live corpus except as a
deliberate, backed-up migration."* `-WithArtifacts` additionally archives `output/` — the one
that actually matters, since **Milvus is fully derivable from the artifacts** via
`lit reprocess` → `lit publish` (`README.md:126-129`).

Two things to know about the script:
- It is a **COLD** snapshot: it stops the stack, tars the volumes, and **restarts it**
  (`milvus_snapshot.ps1` .DESCRIPTION). Since `lit-milvus-standalone` is already exited, this
  will also be the thing that brings Milvus back up. Verify it comes up healthy before Step 1.
- **`restore` wipes the entire server** — after the yeast run exists, restoring a pre-yeast
  snapshot destroys the yeast collections too. Snapshot again once the yeast run is done.

### Step 1 — **[WRITES]** Create the isolated copy

```powershell
$SRC = "D:\Agentic\Literature-analysis"
$DST = "D:\Agentic\lit-agent-yeast"
New-Item -ItemType Directory -Force $DST | Out-Null

# source tree + the root-relative data files the engine reads
robocopy $SRC\src $DST\src /E /XD __pycache__ | Out-Null
Copy-Item $SRC\config.yaml, $SRC\pyproject.toml, $SRC\groups.json, `
          $SRC\units.json, $SRC\substrate_equivalence.json $DST

# fresh, empty alias map — do NOT copy the 74 KB cellulase taxonomy
'{}' | Out-File -Encoding utf8 $DST\taxonomy.json

# PDFs must live under the copy's root (state.py:279). Junction = zero copy, read-only source.
cmd /c mklink /J "$DST\data" "D:\Agentic\bifserver-works\literatures\pdf_included"
```

Do **not** copy `output\`, `docker\`, `eval\`, `.venv\`, or `.git\`.

### Step 2 — **[WRITES]** Edit `D:\Agentic\lit-agent-yeast\config.yaml`

Exactly these keys change. Everything else stays as-is.

```yaml
paths:
  data_dir: "data"                   # the junction; unchanged value, new meaning
  output_dir: "output"               # now D:\Agentic\lit-agent-yeast\output
  manifest: "output/manifest.jsonl"
  taxonomy: "taxonomy.json"          # now the copy's empty one

claude:
  providers: ["claude_code"]         # subscription only; forbids all credit spend

budget:
  claude_budget_usd: 2.00            # only bites if "api" is ever re-added

milvus:
  uri: "http://localhost:19530"      # SAME server — isolation is by collection name
  collections:
    chunks:       "yeast_chunks"
    papers:       "yeast_papers"
    figures:      "yeast_figures"
    tables:       "yeast_tables"
    measurements: "yeast_measurements"
    references:   "yeast_references"
    methods:      "yeast_methods"
    variants:     "yeast_variants"
    sequences:    "yeast_sequences"
    constructs:   "yeast_constructs"
```

Then replace `groups.json` with the yeast/alcohol axes from §Q4. (Optional, recommended:
swap the two cellulase example strings in `$DST\src\lit_agent\categorize.py:80-81` for
`alcohol dehydrogenase / pyruvate decarboxylase / ketol-acid reductoisomerase` and
`"Saccharomyces cerevisiae"`.)

### Step 3 — Reuse the existing venv, safely

The heavy ML stack (torch+CUDA, docling, FlagEmbedding/BGE-M3) is ~10 GB; do not reinstall it.
The existing venv has lit-agent installed **editable**, and
`.venv\Lib\site-packages\_editable_impl_lit_agent.pth` contains
`D:\Agentic\Literature-analysis\src` — so its `lit` command **always resolves to the original
repo**. `PYTHONPATH` takes precedence over `.pth` entries; I verified this:

```
PYTHONPATH=<other>\src  python -c "import lit_agent; print(lit_agent.__file__)"
  -> ...\<other>\src\lit_agent\__init__.py
```

So define this once per shell and **never call the bare `lit` command for yeast work**:

```powershell
$env:PYTHONUTF8   = "1"
$env:PYTHONPATH   = "D:\Agentic\lit-agent-yeast\src"
$PY = "D:\Agentic\Literature-analysis\.venv\Scripts\python.exe"
Set-Location D:\Agentic\lit-agent-yeast
function ylit { & $PY -m lit_agent.cli @args }
```

### Step 4 — **THE GATE.** Verify you are pointed at the copy.

```powershell
ylit doctor
```

Must print **exactly**:

```
project root: D:\Agentic\lit-agent-yeast
data dir   : D:\Agentic\lit-agent-yeast\data
output dir : D:\Agentic\lit-agent-yeast\output
budget USD : 2.0
claude via  : claude_code
Milvus reachable at http://localhost:19530
```

**If `project root` says `D:\Agentic\Literature-analysis`, STOP.** `PYTHONPATH` did not take;
every subsequent command would write to the cellulase corpus. Do not proceed on any other output.

Then confirm the corpus is seen (read-only; `discover_papers` only hashes files):

```powershell
ylit discover        # expect: 127 unique papers from 127 source files
```

### Step 5 — **[WRITES to Milvus]** Create the yeast collections

```powershell
ylit milvus-init     # NOT --drop. ensure_collections(drop=False) creates only what's missing.
```

`milvus_store.py:320-322` only drops when `drop=True`; `cli.py:117` defaults it to `False`.
Leave it that way. Verify in Attu (http://localhost:8400) that ten new `yeast_*` collections
exist **and** that the ten `lit_*` collections are untouched with their documented counts
(`lit_papers` 176, `lit_chunks` 7,531, `lit_figures` 2,070, `lit_tables` 926 —
`ACTION_PLAN_v3.md:20-32`).

Do **not** run `ylit milvus-smoke`: it creates and drops a `lit_smoke` collection on the shared
server (`milvus_store.py:369-390`).

### Step 6 — **[WRITES]** Smoke-run one paper

```powershell
ylit run --limit 1
```

Then check that the artifact landed in the copy, not the original:

```powershell
Get-ChildItem D:\Agentic\lit-agent-yeast\output       # should now hold 1 <paper_id> dir + manifest.jsonl
Get-ChildItem D:\Agentic\Literature-analysis\output | Measure-Object   # count must be UNCHANGED
```

Also confirm Ollama is on the **GPU** before the full run — per the project memory note, starting
Ollama the wrong way silently runs CPU-only at ~45x latency, which would turn a several-hour run
into days. Start it via `ollama app.exe`.

### Step 7 — **[WRITES]** Full run

```powershell
ylit run
```

Resumable: re-running skips every stage whose artifact exists (`state.py:87`). A failing paper is
recorded and skipped, not fatal (`pipeline.py:103-107`). Expect several hours (127 PDFs × local
Docling + Qwen2.5-VL per figure + BGE-M3 embed).

### Step 8 — Tune grouping ($0) and query

```powershell
ylit browse-groups --axis enzyme_group      # see how the yeast rules landed
# edit D:\Agentic\lit-agent-yeast\groups.json, then:
ylit retag --no-reembed                     # re-apply taxonomy+grouping, no LLM, no re-embed
ylit ask "Which ketol-acid reductoisomerase variants raise isobutanol titre in S. cerevisiae?"
ylit analyze "Compare cytosolic vs mitochondrial isobutanol pathway strategies"
```

### Step 9 — **[WRITES]** Snapshot again

```powershell
cd D:\Agentic\Literature-analysis
docker\milvus_snapshot.ps1 snapshot -WithArtifacts
```

This now captures **both** corpora's collections (they share the volumes). Separately archive
`D:\Agentic\lit-agent-yeast\output` — the script's `-WithArtifacts` only knows about the
original repo's `output/`.

---

## 4. Blast radius — what could contaminate the cellulase corpus, and why each is blocked

| # | Contamination vector | Mechanism | Prevented by |
|---|---|---|---|
| 1 | **Wrong `lit` resolves to the original repo** | `get_config()` root comes from the imported module's location (`config.py:16-23`); the venv's editable `.pth` points at `Literature-analysis\src` | `PYTHONPATH` override (verified to win) + **the Step 4 `doctor` gate**. Never invoke the bare `lit` binary for yeast work. |
| 2 | **`output/` shared** → `manifest.jsonl` rewritten, artifacts overwritten on a shared paper_id | `Manifest._save()` rewrites the whole file from memory (`state.py:219-223`); `paper_id` is content-hashed so an identical PDF in both corpora maps to one dir (`state.py:48`) | Separate `paths.output_dir` in the copy's config; verified by `doctor` and by the Step 6 file count check. |
| 3 | **Milvus collections shared** → 127 yeast papers injected into `lit_papers`/`lit_chunks` | `load_paper()` writes to whatever `milvus.collections.*` names (`load.py:52-62`) | Ten renamed `yeast_*` collections in the copy's config. Cross-checked in Attu at Step 5. |
| 4 | **`ensure_collections(drop=True)` on `lit_*`** — instant total loss of the cellulase index | `milvus_store.py:320-322`; reachable via `lit milvus-init --drop`, and via **`lit publish`/`lit reindex`, whose `--recreate` defaults to `True`** (`cli.py:594`, `cli.py:610`) | Never run `publish`/`reindex` for the yeast corpus without first confirming `doctor` shows the copy's root. Snapshot at Step 0. The plain `lit run` path only calls `ensure_collections(cfg)` with `drop` defaulted to `False` (`pipeline.py:47`). |
| 5 | **`taxonomy.json` mutated** — yeast aliases permanently written into the 74 KB cellulase taxonomy | `_save_taxonomy()` writes on every categorize (`categorize_norm.py:99`) | `paths.taxonomy` points at the copy's fresh `{}` file. |
| 6 | **`groups.json` overwritten** | `_load_rules()` writes defaults if absent (`grouping.py:96`), path hardcoded `cfg.root / "groups.json"` (`grouping.py:84`) | Isolated by `cfg.root` differing. This is **only** true because we copied the repo — a config-only override cannot move this file. |
| 7 | **Budget/ledger cross-talk** — yeast spend counted against the cellulase gate (or vice versa) | `CostLedger` path is `output_dir/cost_ledger.json` (`state.py:106`) | Separate `output_dir`. Note the flip side: the copy starts at **$0 spent**, so an inherited `claude_budget_usd: 16.00` would silently authorize a fresh $16 — hence `2.00` + `providers: ["claude_code"]`. |
| 8 | **Source PDFs written to** | — | Nothing writes to `paper.src_path`; `parse.py:75` and `figures.py:196` only open it for reading. The junction target stays read-only. |
| 9 | **Escalation queue / eval gold mixed** | `escalation_queue.jsonl` under `output_dir` (`escalation.py:37`); `eval/gold.json` at `cfg.root` (`eval.py:165`) | Both follow the copy. |
| 10 | **Reverse direction: `milvus_snapshot.ps1 restore` wipes the yeast collections** | Restore wipes all three shared volumes | Take a fresh snapshot after the yeast run (Step 9); treat any pre-yeast restore as destroying yeast data. |
| 11 | **Milvus server instability** — it is currently `Exited (134)` / SIGABRT | shared server, shared volumes, shared failure | Diagnose the abort before adding 127 papers. Step 0 snapshot is the rollback. |

---

## 5. Minimal code changes, if you want them

None are required for the plan above. Listed for completeness:

1. **Separate Milvus database** (not needed if collections are renamed) —
   `src/lit_agent/milvus_store.py`, function **`connect()`** (lines 33-37): pass
   `db_name=cfg.get("milvus", "db_name", default="default")` to `connections.connect()`, and add
   `milvus.db_name` to `config.yaml`. One line + one config key.
2. **Corpus directory outside the project root** (not needed if you use the junction) —
   `src/lit_agent/state.py`, function **`discover_papers()`** (line 279): replace
   `rel = str(p.relative_to(cfg.root))` with a try/except falling back to `str(p)`.
   This would make `paths.data_dir` accept any absolute path.
3. **A `--config` / `LIT_CONFIG` override**, which is the real missing affordance —
   `src/lit_agent/config.py`, function **`get_config()`** (lines 54-59): honour an env var for
   the config path and drop/parameterize the `lru_cache`. This would remove the need to copy the
   repo at all. It is the change worth upstreaming into the reference engine, but it touches the
   precious repo, so it is **out of scope here**.

Note that (1) and (2) are edits to **the copy**, not to `D:\Agentic\Literature-analysis`. Keeping
the copy's `src/` byte-identical to the original (except the optional `categorize.py` prompt
tweak) makes it trivial to re-sync when the reference engine improves — a periodic
`robocopy /MIR` of `src\` plus re-applying the prompt tweak.
