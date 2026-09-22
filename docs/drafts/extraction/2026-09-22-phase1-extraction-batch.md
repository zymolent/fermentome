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

### What the sectioner bug cost — old proposals vs new

Both papers had **two** v1 extractions: one automated (`82f…`, `541…`) and one hand-built from
the tables (`660…`, `93e…`). Only the automated one is a fair comparison; the hand-built one was
a human working around the bug, and it is listed separately below.

#### `10.1186/1475-2859-12-119`

| | v1 automated (`82f…`) | v1 hand-built (`660…`) | **v2 (`6a4…`)** |
|---|---|---|---|
| records | 9 | 6 | **117** |
| spans by section | results 9 | results 6 | results 114, **methods 3** |
| distinct strain names | 3 | 3 | **44** |
| distinct measurements | 4 | 3 | **26** |
| modifications | 2 | 0 | **47** |

**The bug did not only cost recall — it mis-assigned strains to numbers.** The paper's headline
sentence reports two titers at once. v1 put both on one strain; v2 splits them:

| quote as captured | v1 attributed to | v2 attributes to |
|---|---|---|
| *"the isobutanol titer reached 1.62 ± 0.11 **g/L** and 1.61 ± 0.03 g/L at 24 h…"* | **BSW191**, 1.62 g/L | — |
| *"the isobutanol titer reached 1.62 ± 0.11 and 1.61 ± 0.03 g/L at 24 h…"* | — | **BSW205** 1.62 g/L, **BSW206** 1.61 g/L |

Note the quotes are *not the same string*: v1's carries a `g/L` after the first value that v2's
does not. They are two different printings of the same sentence — the structured abstract and the
Results section — which is the sectioner bug caught red-handed. Two further re-assignments follow
the same pattern: **94 mg/L** moved BSW192 → **BSW191**, and **83 mg/L** moved BSW191 →
**BSW192**.

v1 also missed the paper's entire subject. The title is *"…by eliminating competing pathways"*,
and v1 proposed **no deletion strain at all**. v2 proposes the whole series — `pda1Δ`, `pdb1Δ`,
`lpd1Δ`, `lat1Δ`, `pdc5Δ`, `pdc6Δ`, `pyc1Δ`, `pyc2Δ`, `mae1Δ`, `thi3Δ`, `dld1Δ`, `irc15Δ` on both
the BSW100 and BSW101 backgrounds — plus the BSW4–BSW20 construction series.

#### `10.1186/s13068-019-1486-8`

| | v1 automated (`541…`) | v1 hand-built (`93e…`) | **v2 (`cf6…`)** |
|---|---|---|---|
| records | 20 | 15 | **327** |
| spans by section | r&d 16, results 4 | **methods 12**, r&d 3 | r&d 179, **methods 148** |
| distinct strain names | 6 | 12 | **19** |
| distinct measurements | 8 | 3 | **47** |
| modifications | 6 | 0 | **261** |

The mis-assignment here is milder but the same shape: v1 recorded two "strains" that are not
strain names at all — **`JWY04 + gpd1/2`** (1.32 g/L) and **`JWY04 + gpd1/2 + ald6`** (2.09 g/L),
which are the abstract's prose descriptions of a build. v2 files the same two numbers under the
real strain names **JWY19** and **JWY23**. The hand-built `93e…` run had already reached the same
answer, which is independent confirmation that v2 is the correct reading and v1 the polluted one.

**Two things a curator should look at before accepting this batch**, both visible only at v2's
volume and neither a sectioner problem:

1. **261 modification proposals from one paper.** The histogram is flat per gene —
   `ilv2` × 27, `bdh1` × 25, `bdh2` × 25, `leu4` × 24, `leu9` × 24, `ecm31` × 23, `ilv1` × 22 —
   against 19 strains. So it is roughly *one modification record per strain × target*, which is
   the schema working as designed rather than duplication, but it is ~14 targets restated for
   every strain in the series and it will dominate the queue.
2. **`mg/g glucose` does not canonicalize.** 13 yield records carry `unit: "unknown"` with a
   numeric value taken straight from a parenthetical — `JWY23` yield `59.55` from
   *"a yield of 59.55 mg/g glucose"*. The value is right and the span is right; the unit was not
   recognised. Accepting these as-is would put unitless yields in the atlas.

### Run 3 — `strains` + `pathway_configurations` over the extract-first set

Ordered by the triage doc's own ranking, so the highest-value papers were reached first.

| # | DOI | cfg | strains | total | tokens | excerpt sent |
|---|---|---|---|---|---|---|
| 1 | `10.1016/j.ymben.2011.02.004` | 5 | 7 | 12 | 12,649 | 41% |
| 2 | `10.1016/j.jbiotec.2022.09.012` | 2 | 14 | 16 | 11,244 | 37% |
| 3 | `10.1016/j.ymben.2017.10.001` | 8 | 23 | 31 | 37,185 | 47% |
| 4 | `10.1016/j.cels.2019.10.006` | 3 | 28 | 31 | 13,060 | 30% |
| 5 | `10.1016/j.biortech.2018.07.150` | 4 | 16 | 20 | 23,173 | 50% |
| 6 | `10.1016/j.ymben.2012.11.008` | 6 | 43 | 49 | 34,082 | 47% |
| 7 | `10.1016/j.jbiosc.2017.04.005` | 4 | 19 | 23 | 15,914 | 59% |
| 8 | `10.1016/j.jbiotec.2012.01.022` | 8 | 17 | 25 | 13,800 | 58% |
| 9 | `10.1016/j.ymben.2011.12.001` | 3 | 9 | 12 | 16,139 | 38% |
| 10 | `10.1016/j.biortech.2011.06.058` | 4 | 7 | 11 | 12,853 | 65% |
| 11 | `10.1016/j.jbiotec.2011.06.005` | 4 | 11 | 15 | 14,081 | 49% |
| 12 | `10.1016/j.jbiotec.2007.04.019` | — | — | **FAILED** | 0 | — |
| 13 | `10.1016/j.biortech.2025.132921` | 9 | 13 | 22 | 22,785 | 62% |
| 14 | `10.1016/j.jbiotec.2020.06.017` | 2 | 14 | 16 | 11,754 | 38% |
| 15 | `10.1016/j.biortech.2017.05.197` | 1 | 5 | 6 | 11,216 | 23% |
| | **total, 14 succeeded** | **63** | **226** | **289** | **249,935** | |

## Failures

**`10.1016/j.jbiotec.2007.04.019` — refused, `rc=2`.** The stored full text sections to
`['abstract', 'acknowledgements', 'front_matter', 'introduction', 'references']`, so the guard
classified it as a review and refused rather than falling back to `unsectioned`. **It is not a
review** — it is *"Ethanol production from xylose by recombinant S. cerevisiae expressing a
protein-engineered NADP⁺-dependent xylitol dehydrogenase"*, a research report, and one of the
triage doc's five highest-value pentose papers because it records a cofactor-preference change.
**The stored text is a fragment: methods and results are simply not in it.** This is an
acquisition defect, not an extraction one, and it is invisible from the corpus tables because the
paper has a `fulltext_asset` row like every other. Re-acquisition is the fix; forcing
`--sections unsectioned` is not, because there is no methods or results text present to send.

**`10.1016/j.ymben.2020.04.002` — refused, `rc=2`**, sections `['unsectioned']`. This one was
attempted only because the triage doc says of `ymben.2017.10.001` and its corrigendum "extract
both or neither". **The rule turns out not to bite here.** The corrigendum reads in full: *"the
chemical structures of valine, 2-acetolactate, and 2,3-dihydroxyisovalerate in Figure 2 of the
original manuscript were incorrect."* It corrects figure chemistry and nothing else — no strain,
no titer, no pathway claim. Extracting `ymben.2017.10.001` without it is safe, and that is now
checked rather than assumed.

## Two normalization findings a curator will hit

**1. `compartment` is left `unknown` where the prose says otherwise.** Run 2 was aimed at
host × compartment evidence. Only `meteno.2016.03.004` produced compartment-resolved records:

| paper | `cytosol` | `mitochondrial_matrix` | `unknown` / null |
|---|---|---|---|
| `meteno.2016.03.004` | 18 | 12 | 8 |
| `ymben.2017.10.001` | 0 | 0 | 36 |
| `cels.2019.10.006` | 0 | 0 | 31 |
| `ymben.2011.02.004` | 0 | 0 | 32 |
| `jbiotec.2022.09.012` | 0 | 0 | 7 |

That looks like a recall failure and is not one. **The evidence is in the records; it just did
not reach the controlled field.** 9 of `ymben.2017.10.001`'s 36 carry
`compartment_as_reported` = *"in the mitochondria"*, *"localized to mitochondria"*, *"both
targeted to mitochondria"* — with `compartment: "unknown"` beside it. 25 of
`cels.2019.10.006`'s 31 do the same (*"in their native locations (mitochondria…)"*, *"targeted
exclusively to the mi…"*). A query for "demonstrated host × compartment" would today find only
`meteno`'s 30 and miss 34 records that say the compartment in words. Whoever owns
`src/fermdb/extract/` should decide whether that is a prompt fix or a post-hoc normalizer; it is
not something to fix by accepting the proposals as they stand.

**2. 63 configurations, 38 judgeable by gene symbol.** Phase 3's recall test cannot score a
configuration that names only roles. Of the 63:

* **38** name at least one enzyme by gene symbol in `enzymes_as_reported`
  (`Ll_kivd1`, `Ec_ilvD_coEc`, `Bs_alsS1`, `pntAB`, `IlvC6E6-his6`, `AdhA`, `YqhD`…).
* **25** name only roles — *"Acetolactate synthase (ALS), ketol-acid reductoisomerase (KARI),
  dihydroxy-acid dehydratase (DHAD)…"*. Several of those spans are **figure legends**, which is
  where role-only naming lives.
* **43 of 63** carry a `strain_name_as_reported`; **20 do not**, and the configuration promoter
  refuses to invent `host_strain_id`, so those 20 cannot be promoted as they stand even if
  accepted.

`compartment_strategy` spread across the 63: `NA` 19, `unknown` 18,
`F_single_compartment_host` 13, `C_mitochondrial_ehrlich` 6, `A_native_split` 5,
`B_cytosolic_relocalization` 2.

## Batch totals

| | |
|---|---|
| runs attempted | 22 |
| runs succeeded | 20 |
| runs failed | 2 (both refusals by the section guard, both correct refusals) |
| `extraction` rows | 11 → **32** |
| **curation tasks queued** | **877** |
| queued by kind | modifications 308, strains 289, part_expression_records 144, measurements 73, pathway_configurations 63 |
| tokens | **466,604** |
| pending queue, all kinds | 17 → **894** |

Nothing was accepted, rejected, edited or promoted. `pathway_configuration` and
`part_expression_record` still hold 4 and 0 rows respectively; the proposals are in Zone I
awaiting a curator.

