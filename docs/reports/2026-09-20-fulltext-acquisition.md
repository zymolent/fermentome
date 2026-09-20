# Full-text acquisition — 2026-09-20

All 5,164 discovered publications resolved. **1,308 full texts stored, 3,856 queued for manual
download.** Two export files are ready:

| file | rows | what it is |
|---|---|---|
| `exports/priority_downloads.tsv` | 134 | isobutanol, isobutanol × mitochondria and mtDNA papers only, ordered easiest-first |
| `exports/manual_download_queue.tsv` | 3,856 | everything, the full queue |

## What was stored

| | | |
|---|---|---|
| gold | 1,034 | |
| green | 268 | |
| hybrid | 6 | |
| **total** | **1,308** | 25% of the corpus |

Every one is **JATS XML from Europe PMC**, not PDF. That was a deliberate change: `fullTextXML`
is now ranked above the PDF wherever an article is in the OA subset, because JATS keeps the
section and paragraph boundaries that span verification needs, and its tables are structured
rather than a reconstruction problem.

## What is queued for you

| reason | count | what it means |
|---|---|---|
| `paywalled` | 2,489 | needs your institutional access |
| `licence_forbids` | 758 | **free to read at the link** — policy (PLAN.md H.4) blocks automated storage, not you |
| `no_pdf_found` | 534 | the link resolves to a landing page; the PDF is behind it |
| `fetch_failed` | 75 | the link looked valid but would not fetch |

All but the paywalled ones carry a direct link. The 758 `licence_forbids` rows are the cheapest
win in the queue: they are readable right now, and 26 of them are in the 134-paper priority list.

## Coverage by query family

| family | papers | stored | |
|---|---|---|---|
| isobutanol_mitochondria | 29 | 11 | 38% |
| isobutanol_production | 649 | 241 | 37% |
| isobutanol_yeast | 257 | 91 | 35% |
| ethanol_scerevisiae_prod_ferm_tol | 1,423 | 502 | 35% |
| isobutanol_all | 1,309 | 364 | 28% |
| mtdna_methods_yeast | 1,298 | 260 | 20% |
| ethanol_mitochondria_yeast | 504 | 96 | 19% |
| mtdna_engineering_yeast | 912 | 168 | 18% |

The mtDNA families are the weakest, which is expected: much of that literature is older and in
journals that never went open access. Those are the ones worth your institutional access.

## Six defects found and fixed

Every one produced plausible output or silence rather than an error, and none was caught by the
test suite as it stood. Each is now covered by a test.

1. **HTML landing pages were being stored as full text.** Three of the first four "stored" papers
   were a 2.7 kB `<meta refresh>` stub, a Nature consent page served from a URL ending `.pdf`, and
   a repository record page with only an abstract. All answered HTTP 200, so all looked acquired —
   which kept them out of your download queue and would have fed extraction a redirect stub.
   Found only because two papers returned the *same* interstitial and tripped the checksum unique
   index, which is the one thing that noticed.
2. **One URL per paper.** Every source names several locations and acquisition tried one, so a
   consent wall at the top cost us the repository copy underneath.
3. **A checksum clash aborted the record entirely**, leaving the paper with neither an asset row
   nor a queue row — invisible to both accounting paths and retried into the same failure forever.
4. **A test was writing into the live data directory.** `env={}` isolates from environment
   variables, not from paths, so `data_dir` still resolved to the real `~/fermdb-data`; a 25-byte
   fixture PDF was found sitting among genuinely acquired papers.
5. **The extractor would have been handed raw XML.** JATS italicises gene names mid-sentence, so
   the sentences carrying the measurements are exactly the ones markup cuts in half.
6. **Tables extracted as unpaired runs of numbers.** JATS permits a whole `<table-wrap>` inside
   the paragraph citing it and publishers use it, so `itertext()` inlined every cell into the
   sentence. 215 articles have tables and zero were emitting rows; 214 now do. The 215th ships its
   table as a scanned JPEG, which the text now says outright rather than leaving a bare caption.

## Extraction: now runs, one policy question left

Extraction could not run on a real paper at all when acquisition finished. It can now.

Measured on `10.1038/s41467-021-27852-x`: methods + results is a 60,087-character excerpt, and
the prompt with the schema came to 81,748 characters — about 20,400 tokens. At the default
`num_ctx` of 8,192 the model returned **English prose**, because Ollama truncates silently keeping
the *end* of the prompt and `extraction.md` ends with the excerpt — so the instructions were what
got dropped. At 32,768 it returned nothing at all after 256 seconds.

Fixed by, in order: refusing a prompt that will not fit and naming the `num_ctx` needed; sending
the schema compact (27,629 → 16,736 characters, 39% was whitespace); and chunking the excerpt into
windows that are themselves `Excerpt` objects, so offsets coming back are already document
offsets and there is no second coordinate system to get wrong.

Then the last one, which is the interesting one. **Models cannot count characters.** All 22
records came back with verbatim, genuinely-present quotes and offsets wrong by a handful of
characters — `verify_span` rejected all 22 while its own message read *"the quote does occur at
[2912]"*. Offsets are now derived from the text rather than taken from the model. This is not a
relaxation: a quote absent from the source is still rejected by the same exact check, which is
what stops a fabricated measurement. Position is simply computed from the text, which cannot be
mistaken about where it is, and every repair is recorded as a note.

**22 rejected spans became 2** — and both survivors are `quote_absent_from_source`, paraphrases
the model invented. The validator catching those is it working correctly.

### The open question, for you

The paper still stores nothing, because the harness is all-or-nothing by design: PLAN.md's
rationale is that *"storing the records that happened to pass would put half-validated output in
the same table, in the same shape, as validated output."*

With a local model inventing a quote or two per paper, all-or-nothing means nothing is ever
stored. Three options, and this is your call rather than mine because it is a decision about what
the data means:

1. **Keep it.** Escalate any paper with a rejected span to Claude, which paraphrases less.
   Cleanest semantics, highest cost.
2. **Store the records that passed**, and record the count and text of every rejection on the
   extraction row. Every record is independently span-verified and lands in Zone I as `proposed`
   for your review anyway, so a rejected record is absent rather than half-validated — but the
   payload is then no longer "everything this paper says".
3. **Tighten the prompt first** and re-measure. Both failures here were paraphrases where the
   model summarised instead of quoting; that is addressable in wording.

My recommendation is 3 then 2 — measure whether the prompt fixes it before changing what a stored
payload means.

## State

- 640 tests, ruff, ruff format, mypy all clean
- Commits: `ecde4c3` payload validation · `965e0f4` test isolation · `e453934` JATS reader ·
  `547eed8` review guard · `5793c46` provider recovery · `6a9ab3a` measurements ·
  `ca26291` chunking · `4f2a335` chunked extraction and span repair
- AWS: nothing running, nothing added today
