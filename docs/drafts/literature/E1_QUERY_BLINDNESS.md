# E1 query blindness: what PubMed swallows, how much it actually costs, and whether `[tiab]` is the right instrument

**DRAFT, 2026-09-22.** Nothing was written to `data/`, `src/`, `tests/` or `PLAN.md`, and nothing
to the database (opened `mode=ro` throughout). **`fermdb literature discover` was not run at all —
not even `--dry-run`.** All network activity was read-only E-utilities traffic issued directly
through `EutilsClient`: ~75 requests, all of them `esearch` count/id reads or `efetch` abstract
reads, throttled at the unauthenticated 3 req/s (no `api_key` passed; `FERMDB_NCBI_API_KEY` is
still not loaded by anything, as `E1_TIER_ROUTING_DEFECT.md` §5.2 reported). No `search_run` row
exists as a result of this pass. The proposed YAML edits below are **proposed, not applied**.

---

## 1. The answer, first

Three things, in descending order of how much they change what anyone should do:

1. **The mechanism is not "Δ binds into the token". PubMed transliterates Greek letters into
   their spelled-out Latin names, at both index time and query time, and glues the result to the
   adjacent token.** `pdc1Δ` is indexed as the single term **`pdc1delta`**. So the notation is not
   unreachable — it is reachable, under a spelling nobody would guess. `pdc1`, `pdc1delta` and
   `deltapdc1` are three **disjoint** index terms with no stemming between them.

2. **The blindness is real and its reach is small and now exactly known.** A notation-aware E1
   plus a one-phrase E6 fix would newly match **exactly 2 of the atlas's 5,164 publications** —
   `26628917` and `34727964`, two of the six stuck papers — and would newly admit **43
   publications that are not in the atlas at all.** It rescues **2 of 6**. It cannot rescue the
   other four, because their abstracts contain no E1 gene token in *any* notation.

3. **The notation fix is not the interesting finding; the ratio behind it is.** Across the 710
   iso-only publications with stored JATS full text, **5** carry Pdc evidence in title+abstract and
   **56** carry it in the body. **51 of those 56 are invisible to every `[tiab]` query that could
   ever be written**, notation-aware or not. Abstract screening sees roughly **9%** of the
   E1-relevant material in the readable corpus. That is the defect; the Δ is a symptom of it.

**Correction to `E1_TIER_ROUTING_DEFECT.md`.** That document's §6(a) minimal fix — "add the
genotype spellings" — **does not rescue the paper it was written for.** Adding `pdc1delta` to E1's
gene clause leaves `26628917` stuck at the *third* clause, whose abstract contains none of
`deletion`, `knockout`, `pdc-negative`, `pdc minus`, `C2 auxotroph` or `glucose-tolerant`. Two
other corrections are in §6.

---

## 2. The notation matrix

### 2.1 What PubMed actually holds

`efetch` on PMID 26628917 returns the abstract with the genotype intact, as
`pdc1&#x394; pdc5&#x394; pdc6&#x394; aro10&#x394;` — U+0394 GREEK CAPITAL LETTER DELTA, appended
with no separator. So the character survives into NCBI's record. What happens next is a
*normalisation*, and `esearch`'s `querytranslation` field reports it in the clear.

### 2.2 The matrix — PDC1, every notation the literature uses

Probes are `<term>[tiab]`, run live 2026-09-22. "Translated to" is the verbatim
`querytranslation` NCBI returned.

| written as | translated to | PubMed-wide `[tiab]` count | retrievable? |
|---|---|---|---|
| `PDC1` (prose) | `"pdc1"[Title/Abstract]` | **261** | yes |
| `pdc1Δ` (U+0394, unquoted) | `"pdc1delta"[Title/Abstract]` | **6** | yes — as `pdc1delta` |
| `"pdc1Δ"` (U+0394, quoted) | `"pdc1delta"[Title/Abstract]` | **6** | identical to unquoted |
| `pdc1delta` (ASCII) | `"pdc1delta"[Title/Abstract]` | **6** | identical — same index term |
| `Δpdc1` (prefix) | `"deltapdc1"[Title/Abstract]` | **4** | yes — as `deltapdc1` |
| `pdc1-delta` | *(untranslated — no such term)* | **0** | **no** |
| `"pdc1 delta"` (phrase) | *(untranslated)* | **0** | **no** |
| `pdc1::loxP` | *(untranslated)* | **0** | **no** |
| `pdc1loxp` (glued hypothesis) | *(untranslated)* | **0** | **no** |
| `"pdc1 loxP"` (split hypothesis) | *(untranslated)* | **0** | **no** |
| `pdc1D` / `pdc1d` (ASCII capital-D convention) | *(untranslated)* | **0** | **no** |
| `pdcΔ` (locus-level) | `"pdcdelta"[Title/Abstract]` | **1** | yes |

Three conclusions:

* **`Δ` is survivable. `::` is not.** The `gene::marker` genotype — `pdc1::loxP`, which is how the
  Delft CEN.PK lineage writes its strains and which appears 10 times in the stored bodies — is
  invisible in every form tested: not as a phrase, not split into adjacent tokens, not glued. There
  is no `[tiab]` spelling that reaches it. This is a harder wall than the delta, and
  `E1_TIER_ROUTING_DEFECT.md` did not identify it.
* **Bare and delta forms are disjoint.** `pdc1[tiab]` (261) does not retrieve any of the 6
  `pdc1delta` records, and vice versa. There is no truncation or stemming that bridges them. A
  query must name both spellings explicitly.
* **PubMed silently drops dead terms from a query.** `deltapdc5`, `deltapdc6`, `ilv3delta`,
  `deltailv3` and `deltailv5` all vanished from the returned `querytranslation` rather than
  returning zero — the index has no such term, so NCBI removes it. **A query can therefore contain
  terms that do nothing, and nothing in the response says so.** That is the same class of silent
  failure as the stable hit count: it looks healthy because nothing reports it.

### 2.3 The same test for the ILV / BAT / ALD / ADH / ARO genes

| gene | bare `[tiab]` | `geneΔ` + `Δgene` (i.e. `genedelta` + `deltagene`) |
|---|---|---|
| PDC1 | 261 | 6 + 4 |
| PDC5 / PDC6 | — | 5 (union; `deltapdc5`/`deltapdc6` do not exist) |
| ILV2 | — | 3 |
| ILV3 | — | **0** (neither spelling exists in the index) |
| ILV5 | 43 | 2 |
| BAT1 | 160 | 4 |
| BAT2 | — | 8 |
| ALD6 | 85 | 4 |
| ALD4 / ALD5 | — | 4 |
| ADH1 | — | 13 |
| ADH3 / POS5 | — | 11 |
| ARO10 | — | (inside the union below) |

**Union of every Δ-notation form across the whole gene set: 48 records in all of PubMed. PDC-only:
13.** That is the entire ceiling on what any notation-aware widening can ever retrieve. It is a
small number and it should be stated plainly before anyone widens six queries.

### 2.4 The phrases are bigger than the notation

The genotype notation is rare in abstracts precisely because authors who state a genotype in an
abstract usually also describe it in words. Those words are far more retrievable:

| phrase | PubMed-wide `[tiab]` | with the E1 organism clause |
|---|---|---|
| `"decarboxylase-negative"` | **69** | **19** |
| `"pdc-deficient"` ∪ `"pyruvate decarboxylase negative"` | **49** | — |
| `"pdc-negative"` | 8 | — |
| `"pdc-minus"` / `"pdc minus"` | **0** | **0** |
| `"C2 auxotroph"` | **0** | **0** |
| `"glucose tolerant"` (auto-maps to `"glucose-tolerant"`) | 1,225 | — |

**Two terms currently in E1's third clause are dead: `"pdc minus"[tiab]` and `"C2 auxotroph"[tiab]`
each return 0 records in all of PubMed.** They have never contributed a hit and never will.
`"glucose tolerant"` and `"glucose-tolerant"` are the same term after normalisation, so listing
both is redundant rather than wrong.

And `26628917`'s abstract says **`'decarboxylase-negative'`**, verbatim, in quotes. The single
most valuable term the query is missing is a phrase, not a notation.

---

## 3. The reach, measured rather than estimated

### 3.1 What is exactly measurable, and is

The notation question is about title+abstract, and PubMed holds every atlas publication's abstract.
So this is a **census, not an estimate**: the id set of the current query and the id set of the
proposed query were both retrieved in full and diffed against the atlas locally.

| | E1 | E6 |
|---|---|---|
| current sub-query hit count | 68 | 362 |
| proposed sub-query hit count | **101** | **383** |
| records **lost** by the change | **0** | **0** |
| records added | 33 | 21 |
| — already ethanol-tier (no change) | 6 | 2 |
| — already both-tier (no change) | 1 | 0 |
| — **iso-only atlas publications rescued** | **1** (`26628917`) | **1** (`34727964`) |
| — not in the atlas at all (newly admitted) | **25** | **18** |

**So: of the atlas's 5,164 publications, a notation-aware query newly matches exactly 2.** Both are
among the six stuck papers. In addition, **43 publications enter the corpus that were never in it.**

### 3.2 What cannot be measured, and why it is the real ceiling

* **The 2,552 iso-only publications with no stored bytes.** Their abstracts *are* testable (§3.1
  covers them — they are inside the PubMed census), but **their full text is not.** Since §4 shows
  that ~91% of E1-relevant material lives below the abstract line, the number of E1 records hiding
  in those 2,552 is unknowable by any method available here. It is bounded above only by 2,552 and
  below by 0. Scaling the readable rate (9 substantive per 710 readable ≈ 1.3%) onto 2,552 would
  suggest ~30 more — **but that scaling is not defensible**, because the readable 710 are
  open-access and the unreadable 2,552 are not, and Pdc-minus chassis work is concentrated in
  exactly the OA metabolic-engineering journals that are already readable. The honest statement is:
  **unknown, with a plausible order of tens, and the acquisition wall is what would have to move.**
* **152 of the 1,429 stored full texts are PDFs** with no machine-readable abstract/body boundary,
  so they can only be scanned as whole documents (§4.2). Their abstract-visibility is not separable.
* **Precision on the 43 new records** was assessed from titles only (§5.3), not from reading.

---

## 4. The instrument question: abstracts vs. stored full text

### 4.1 The measurement

Over the **1,277 stored JATS full texts**, the title+abstract and the body were separated
programmatically and tested for Pdc evidence — bare `pdcN` token, Δ/`::`/`delta` genotype token,
the phrase `pyruvate decarboxylase`, or a `decarboxylase-negative`/`pdc-negative`/`pdc-deficient`
phrase.

| | all 1,277 stored | the 710 that are **iso-only** |
|---|---|---|
| Pdc evidence in **title+abstract** (what any `[tiab]` query can reach) | 28 | **5** |
| Pdc evidence **anywhere in the body** | 166 | **56** |
| **body-only — unreachable by any abstract query** | **138** | **51** |
| genotype token (`Δ` / `::` / `delta`) in the body | 28 | 10 |
| **substantive** (body genotype token **and** ≥3 `pdcN` mentions) | 26 | **9** |
| — of those, abstract-invisible | 14 | **8 of 9** |

**Abstract screening reaches 5 of the 56 iso-only publications that carry Pdc evidence — about
9%. Full-text screening reaches all 56.** That is an 11× difference, and no rewrite of a `[tiab]`
query can close it, because the missing 51 contain no Pdc token in their abstracts in any notation.

The 9 substantive iso-only candidates, with abstract-visibility:

| DOI | PMID | abstract-visible? |
|---|---|---|
| `10.1186/s13068-015-0374-0` | 26628917 | **Y** (the one the notation fix rescues) |
| `10.1016/j.meteno.2016.01.002` | 29142820 | N |
| `10.1186/1754-6834-6-68` | 23642236 | N |
| `10.1038/s41467-021-27852-x` | 35022416 | N |
| `10.3389/fbioe.2022.1080024` | 36532572 | N |
| `10.1186/1475-2859-12-119` | 24305546 | N — **not named by the previous pass** |
| `10.1186/s12934-016-0449-z` | 26971319 | N — **not named by the previous pass** |
| `10.3389/fmicb.2025.1753983` | 41809199 | N — **not named by the previous pass** |
| `10.18632/oncotarget.7174` | 26862728 | N — likely a false positive on reading |

### 4.2 The PDFs

All 152 stored PDFs were extracted with `pypdf` (59 s, 0 failures). 10 mention `pdcN`; **3** carry
a genotype or negative-phenotype token: `10.1016/j.cbpa.2013.03.036` (23628723),
`10.1007/s00253-023-12821-9` (38175234), `10.1016/j.copbio.2014.09.004` (25286420). Two of the
three are *Current Opinion* reviews and are probably not primary records. So the PDF layer adds
roughly one more real candidate, and closes that gap in the sizing.

### 4.3 What a full-text screen would cost

* **Compute: negligible.** The whole XML pass is seconds; the PDF pass was 59 s. No network, no
  LLM, no acquisition. A full re-screen of the 1,429 stored texts is **under two minutes**, and it
  is re-runnable whenever the pattern file changes.
* **It needs a `search_run` it did not search for.** `screening_record` requires `family NOT NULL`
  and `first_seen_run_id`/`last_seen_run_id` → `REFERENCES search_run(id)`. A full-text screen
  produces rows that came from no E-utilities query. It therefore needs either a pseudo-family with
  a synthetic run row (which makes `search_run` mean two different things and would quietly corrupt
  `fermdb literature status`'s drift arithmetic), or a new provenance path. **This is the real cost
  and it is a schema/provenance decision, not a coding one.**
* **Zone and evidence hold up.** A regex over stored bytes driven by a committed pattern file is
  reconstructible from a recorded input, so `zone='H'` is correct and `CONVENTIONS.md` is satisfied.
  The `CHECK (admitted_criterion IS NULL OR product_tier='ethanol')` is satisfied by writing a new
  ethanol-tier row alongside the existing isobutanol ones — the "both" state that 103 publications
  already occupy. No schema change is needed for the row itself.

### 4.4 What it would break

* **It introduces an open-access bias into the ethanol layer, silently.** Only 1,429 of 5,164
  publications (28%) have stored bytes, and they skew heavily OA. A full-text screen can only ever
  admit from that 28%. The ethanol reference layer would therefore acquire a systematic bias
  towards open-access publishers — and because the admission would be recorded as an ordinary
  `admitted_criterion='E1'`, **nothing downstream would record that the selection was conditioned
  on licence.** If this is built, the screening row must carry that the evidence came from stored
  full text, or `B.3`'s "admitted against a stated criterion" becomes "admitted against a stated
  criterion, if we happened to be allowed to read it."
* **It cannot replace discovery.** A full-text screen only re-reads what is already in the corpus.
  It would have found **0** of the 43 publications §3.1's query edits newly admit. The two
  mechanisms are complementary and neither subsumes the other.
* **Precision collapses without a gate.** The previous pass's own funnel — 247 loose matches → 28
  substantive → 6 genuine — is the warning. A regex over a whole paper hits every passing
  Discussion citation ("unlike Pdc-minus strains…"). §4.1's substantive gate (genotype token **and**
  ≥3 mentions) cuts 56 → 9, and even that leaves at least one clear false positive
  (`10.18632/oncotarget.7174`). A production screen needs a section restriction (Methods/Results,
  which `extraction.section` already models) or an LLM triage pass, and then it stops being free.

### 4.5 Recommendation

**Do both, and choose the instrument per criterion rather than per corpus.**

Ship the query edits in §5 — they are cheap, lose nothing, and 43 of their 54 added hits are
publications the atlas has never seen. But do **not** expect them to fix E1, because they fix
1 paper in 6.

Then build the full-text re-screen, and scope it to **E1 only**, at least at first. The reason is
not that full text is better in general — it is that **the criteria differ in where their defining
evidence structurally lives**:

| criterion | its defining evidence | where that lives | right instrument |
|---|---|---|---|
| **E1** competing sink | a `pdc1Δ pdc5Δ pdc6Δ` genotype | **a strain table in Methods** | **full text** |
| E2 performance ceiling | titer, yield, productivity | the abstract — it is the result | `[tiab]` |
| E3 wild-type baseline | a named parental strain and a regime | usually the abstract | `[tiab]` |
| E4 transferable mechanism | a tolerance measurement | the abstract | `[tiab]` |
| E5 redox shuttle | `ADH3`/`POS5`/shuttle terms | the abstract — distinctive enough that the previous pass found **no** E5 routing defect | `[tiab]` |
| E6 industrial basis | a named industrial strain | the abstract | `[tiab]` |

E1 is the outlier, and it is the outlier for a structural reason: **it is the only criterion whose
admission test is a genotype.** A genotype is a methods fact. It is in the abstract only when the
paper is *about* the genotype, and the entire class of papers this defect loses are papers that use
a Pdc-minus chassis to study something else. That is not a vocabulary problem and it will not be
fixed by vocabulary.

The cheapest honest version of this: a `fermdb literature rescreen --criterion E1` that runs the
§4.1 substantive gate over stored full text, writes `review_state='proposed'`,
`triage_state='needs_full_text'` ethanol-tier rows carrying a provenance marker distinguishing them
from search-derived rows, and reports the OA-coverage denominator (1,429 / 5,164) in its own
output so the bias is visible at the point of use. On today's corpus it would surface **9
candidates**, 8 of which no query can reach.

**And close the reporting gap regardless of which option is chosen.** Nothing here was detectable
from `fermdb literature status`, because that compares `hit_count` against `expected_count` and a
systematically blind query has a perfectly stable count. Two checks would have caught it: (a) a
per-sub-query count, so a clause contributing 0 (as `"pdc minus"` and `"C2 auxotroph"` do) is
visible; and (b) a check that flags publications holding screening rows in one tier only while
their stored full text matches another tier's criterion terms.

---

## 5. Proposed changes to `data/literature/query_families.yaml` — **NOT APPLIED**

Three variants of the E1 change were measured before choosing. The comparison is the argument:

| variant | hit count | Δ vs 68 | rescues 26628917 | of the 8 PubMed Δ-papers not in the atlas |
|---|---|---|---|---|
| current | 68 | — | no | **0** |
| **A** flat: add Δ tokens to clause 2, add `"decarboxylase-negative"` to clause 3 | 77 | +9 (+13%) | yes | **1** |
| **B (recommended)** Δ tokens + `"decarboxylase-negative"` made **self-sufficient** | **101** | **+33 (+49%)** | yes | **6** |
| C: B, plus `deleted`/`disruption`/`disrupted` verbs and `pdc-deficient` self-sufficient | 130 | +62 (+91%) | yes | 6 |

**The structural finding is the gap between A and B.** A Δ genotype token *already asserts the
deletion* — `pdc1Δ` means "PDC1 is deleted". Gating it on a second deletion verb re-loses the very
papers it was added for: variant A retrieves 1 of the 8, variant B retrieves 6. **The fix is not
only new terms, it is moving them out from under the AND.** Variant C buys nothing further over B
(same 6) for another 29 hits, so it is rejected.

### 5.1 E1 — `ethanol_scerevisiae_prod_ferm_tol`, criterion E1

```diff
       - criterion: E1
         label: competing_sink
         term: >-
           (yeast[tiab] OR "Saccharomyces cerevisiae"[tiab]) AND
-          (PDC1[tiab] OR PDC5[tiab] OR PDC6[tiab] OR "pyruvate decarboxylase"[tiab]) AND
-          (deletion[tiab] OR knockout[tiab] OR "pdc-negative"[tiab] OR "pdc minus"[tiab] OR
-           "C2 auxotroph"[tiab] OR "glucose tolerant"[tiab] OR "glucose-tolerant"[tiab])
+          (
+           (pdc1delta[tiab] OR pdc5delta[tiab] OR pdc6delta[tiab] OR deltapdc1[tiab] OR
+            pdcdelta[tiab] OR "decarboxylase-negative"[tiab])
+           OR
+           ((PDC1[tiab] OR PDC5[tiab] OR PDC6[tiab] OR "pyruvate decarboxylase"[tiab]) AND
+            (deletion[tiab] OR knockout[tiab] OR deleted[tiab] OR "pdc-negative"[tiab] OR
+             "pdc-deficient"[tiab] OR "C2 auxotroph"[tiab] OR "glucose-tolerant"[tiab]))
+          )
```

Notes the edit needs beside it in the file:

* `pdc1delta` etc. are **not** misspellings. PubMed transliterates `Δ` to `delta` and glues it to
  the preceding token, so `pdc1delta` *is* the index term for `pdc1Δ`. Verified via
  `querytranslation` 2026-09-22 (§2.2).
* The first branch is deliberately **not** gated on a deletion verb: a Δ-genotype token and the
  phrase `decarboxylase-negative` each already state the deletion. Gating them costs 5 of 6
  recoverable papers (§5).
* `"pdc minus"[tiab]` is **removed as dead** — 0 records in all of PubMed. `"C2 auxotroph"[tiab]`
  is also 0 but is **retained deliberately**, because B.3.1 names C2 auxotrophy as the thing E1
  exists to characterise and the term should be there if the literature ever adopts it. It should
  be commented as knowingly-zero so it is not mistaken for a working clause.
* `"glucose tolerant"[tiab]` is removed as a duplicate: PubMed auto-maps it to `"glucose-tolerant"`.
* `deltapdc5`, `deltapdc6` are **not** added: PubMed has no such index terms and silently drops
  them, which would put invisible dead weight back into the query.

**Rescues:** `10.1186/s13068-015-0374-0` (PMID 26628917, Milne 2015) — the stuck-score-219 paper,
the worst-affected case. **Rescues none of the other five.** Also newly admits 25 publications not
currently in the atlas, and loses nothing.

**Does it widen dangerously?** +33 hits on a sub-query of 68 is +49%, but it is +33 on a *family*
of 1,586 and on an E1 review queue of 70 rows. Titles of the 25 new records were checked: roughly
11–14 are squarely B.3.1 material — `9292991` "Metabolic responses of pyruvate
decarboxylase-negative *S. cerevisiae* to glucose excess" (the C2/glucose-excess physiology B.3.1
names explicitly), `9546164` "Pyruvate decarboxylase catalyzes decarboxylation of branched-chain
2-oxo acids" (the direct E1↔isobutanol crossover), `25852051` Ach1 cytosolic C2 provision,
`22904058` substrate specificity of TPP-dependent 2-oxo-acid decarboxylases, `26588105` /
`27528190` / `27990176` Pdc-negative and Pdc-deficient chassis. Most of the remainder are
Pdc-minus chassis used for a non-ethanol product (lactate, 2,3-BDO, vanillin, aromatics) — which
B.3.1 **wants**, since it states E1 is what the atlas needs "in order to read the Gevo/Butamax-
lineage literature, essentially all of which is Pdc-attenuated". Clear noise is ~3–4 records
(a *Candida* polyamine transporter, an ornithine-decarboxylase clone, a catalase paper, a
*Penicillium* pathway paper), mostly false friends on `"decarboxylase-negative"`. **Precision is
roughly 50–80% depending on how generously B.3.1 is read — this is not a query that doubles noise
along with recall.**

### 5.2 E6 — `ethanol_scerevisiae_prod_ferm_tol`, criterion E6

```diff
       - criterion: E6
         label: industrial_performance_basis
         term: >-
           ("Saccharomyces cerevisiae"[tiab] OR yeast[tiab]) AND
           (industrial[tiab] OR bioethanol[tiab] OR "Ethanol Red"[tiab] OR "PE-2"[tiab] OR
            JAY270[tiab] OR CAT-1[tiab]) AND
           (genome[tiab] OR "comparative genomics"[tiab] OR QTL[tiab] OR aneuploidy[tiab] OR
            "copy number"[tiab] OR polymorphism[tiab] OR "reverse engineering"[tiab]) AND
           (tolerance[tiab] OR robustness[tiab] OR "high gravity"[tiab] OR productivity[tiab] OR
-           yield[tiab])
+           yield[tiab] OR "stress resistance"[tiab] OR "stress resistant"[tiab] OR
+           "stress tolerance"[tiab] OR "fermentation performance"[tiab])
```

**Rescues:** `10.1186/s13068-021-02059-w` (PMID 34727964) — the E6 stuck paper, whose title says
"stress resistance" and which failed on this clause and this clause only. Verified: it matches the
amended term.

**Does it widen dangerously?** 362 → 383, **+21 (+6%)**, 0 lost, 18 of the 21 not previously in the
atlas. This is the cheapest of the proposals per paper rescued and carries essentially no risk:
"stress resistance" and "stress tolerance" are near-synonyms of the `tolerance` term already in the
clause, gated behind three other ANDs.

### 5.3 Family bookkeeping the edits require

`discovery.run_family` computes `hit_count` as the **sum** of the sub-query counts, so
`expected_count` must move with the terms or `fermdb literature status` reports permanent false
drift.

```diff
   - name: ethanol_scerevisiae_prod_ferm_tol
     db: pubmed
     product_tier: ethanol
     default_disposition: exclude_unless_admitted
-    expected_count: 1586
+    expected_count: 1640
```

```diff
-version: 1
-measured_on: "2026-09-19/2026-09-20"
+version: 2
+measured_on: "2026-09-19/2026-09-20; E1 and E6 re-measured 2026-09-22"
```

**Side-finding that resolves a standing caveat in this file.** The header warns that the query
strings are "THIS implementation's construction" and "have NOT been re-run against the live NCBI
service… to confirm they reproduce the recorded count exactly (unverified)." They were run, one at
a time, on 2026-09-22: E1 68, E2 591, E3 381, E4 32, E5 152, E6 362 — **sum exactly 1,586, the
recorded `expected_count`.** The caveat can be lifted for this family. With the proposed edits the
sum is **1,640**, which is where the number above comes from.

### 5.4 No change proposed for E2, E3, E4, E5 or `ethanol_mitochondria_yeast`

E5 was re-checked: `adh3delta`/`deltaadh3`/`pos5delta`/`deltapos5` together are 11 records
PubMed-wide, and the previous pass found no E5 routing defect on reading (four candidates, four
false positives). E5's terms are distinctive enough that its recall problem, if any, is not a
notation problem. E2/E3/E4 are outcome criteria whose evidence is in abstracts by construction
(§4.5). **Widening all six queries because one is broken would be the wrong lesson from this
document.**

---

## 6. Corrections to `E1_TIER_ROUTING_DEFECT.md`

1. **§4 failure class (c) has no member.** That document assigns `10.1186/1754-6834-6-68`
   (PMID 23642236) to class (c) — "the abstract says 'pyruvate decarboxylase' and passes the gene
   clause, then fails on the second clause" — and marks it *"Verified: matches the gene clause"*.
   It does not. Live probe, 2026-09-22:
   `23642236[uid] AND (PDC1[tiab] OR PDC5[tiab] OR PDC6[tiab] OR "pyruvate decarboxylase"[tiab])`
   returns **0**, and the abstract (fetched in full) contains no `pdc` substring anywhere. It is a
   glycine/fusel-alcohol pathway paper; its Pdc-minus content (RWB837) is entirely in the full
   text. **It is class (a), not class (c).** So there are three failure classes, not four, and
   **class (a) — no gene token in the abstract at all — accounts for four of the six stuck
   papers**, which strengthens rather than weakens that document's conclusion.
2. **§6(a)'s minimal fix does not work.** Adding genotype spellings to the gene clause alone
   leaves `26628917` failing at the third clause (measured: variant A above needs
   `"decarboxylase-negative"` in clause 3 as well, and even then recovers only 1 of the 8 other
   Δ-notation papers). The genotype token has to be lifted out from under the AND (§5).
3. **§3's mechanism is half right.** "The delta binds into the token" is the correct consequence;
   the cause is transliteration to `delta`, which matters because it means the token **is**
   reachable. The document's implication that `pdc1Δ` is simply unreachable would have led to the
   wrong fix. By contrast `pdc1::loxP` genuinely is unreachable (§2.2), and that case is not in
   that document at all.

---

## 7. Exactly what was run

| | |
|---|---|
| `fermdb literature discover` | **not run**, in any mode, including `--dry-run` |
| `fermdb extract` | not run |
| database | opened `mode=ro` only; 0 writes |
| files written | this one |
| NCBI traffic | ~75 read-only requests: `esearch` (counts + id lists) and 2 `efetch` abstract reads, unauthenticated, throttled at 3 req/s by `EutilsClient`, identifying `tool=fermdb-diagnostic` and a contact email |
| local compute | JATS parse of 1,277 stored XML full texts; `pypdf` extraction of 152 stored PDFs (59 s, 0 failures) |

The `esearch` id-list retrievals in §3.1 paged through 68, 101, 362 and 383 ids respectively. That
is the same traffic a `--dry-run` would generate and less than a tenth of a real discovery run, and
it wrote nothing anywhere.
