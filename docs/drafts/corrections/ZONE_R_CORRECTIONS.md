# Zone R corrections — `doi:10.1186/1475-2859-12-119` (Matsuda et al. 2013)

**Status: proposal. Nothing here has been applied.** Every query behind this document ran against
`~/fermdb-data/fermdb.sqlite3` opened `mode=ro`. No row was written, no curation task was accepted,
rejected or promoted, and `fermdb extract` was not run. The SQL in §6 is written to be applied
verbatim by the owner *after* he has read §§2–4.

The paper:

> Matsuda F, Ishii J, Kondo T, Ida K, Tezuka H, Kondo A. *Increased isobutanol production in
> Saccharomyces cerevisiae by eliminating competing pathways and resolving cofactor imbalance.*
> Microb Cell Fact 2013; 12:119. PMID 24305546,
> [doi:10.1186/1475-2859-12-119](https://doi.org/10.1186/1475-2859-12-119).

Full text loaded with `fermdb.extract.harness.load_source_text`, which resolved to
`C:\Users\kangk\fermdb-data\fulltext\82\82b906abd3f576dfa8147da420a79d7d88323e79179126062bfbf531dcf48014.xml`
(JATS, 33 240 characters after `jats_to_text`). Every offset below is a document offset into that
text.

---

## 1. The spans, re-verified

Fifteen spans were re-read at their own offsets with `fermdb.llm.validate.verify_span` — exact
comparison, no normalization, no fuzzy matching. **15 of 15 exact.** Four of them are the spans the
suspect rows were promoted from; the other eleven are the evidence for what the paper actually says.

| | offsets | section | quote |
|---|---|---|---|
| **S1** | `[1414, 1551)` | abstract/Results | `The integration of a single gene deletion lpd1Δ and the activation of the transhydrogenase-like shunt further increased isobutanol levels` |
| **S2** | `[1656, 1760)` | abstract/Results | `the isobutanol titer reached 1.62 ± 0.11 g/L and 1.61 ± 0.03 g/L at 24 h after the start of fermentation` |
| **S3** | `[1768, 1830)` | abstract/Results | `corresponds to the yield at 0.016 ± 0.001 g/g glucose consumed` |
| **S4** | `[1131, 1232)` | abstract/Results | `pyruvate supply for isobutanol biosynthesis is competing with acetyl-CoA biosynthesis in mitochondria` |
| **S5** | `[9369, 9432)` | Table 1 | `BSW191 \| BY4741/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM` |
| **S6** | `[9499, 9568)` | Table 1 | `BSW205 \| BY4741 lpd1Δ/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1` |
| **S7** | `[9570, 9639)` | Table 1 | `BSW206 \| BY4741 lpd1Δ/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM` |
| **S8** | `[21744, 21804)` | Results | `The isobutanol titer was increased to 94 ± 5 and 83 ± 2 mg/L` |
| **S9** | `[21995, 22113)` | Results | `The additional disruption of the LPD1 gene in the BSW192 and BSW191 strains further activated isobutanol biosynthesis.` |
| **S10** | `[22114, 22202)` | Results | `The isobutanol titer of the BSW205 and BSW206 strains reached 230 ± 13 and 221 ± 27 mg/L` |
| **S11** | `[22429, 22573)` | Results | `The fermentation profile of the BSW205 and BSW206 strains was determined by batch fermentation at a 50-mL scale under semi-anaerobic conditions.` |
| **S12** | `[22677, 22911)` | Results | `the isobutanol titer reached 1.62 ± 0.11 and 1.61 ± 0.03 g/L at 24 h after the start of fermentation, which corresponded to isobutanol yields of 0.016 ± 0.001 g/g glucose consumed and 0.016 ± 0.0003 g/g glucose consumed, respectively.` |
| **S13** | `[23392, 23466)` | Figure 6 legend | `Closed and open symbols represent data of BSW205 and BSW206, respectively.` |
| **S14** | `[26525, 26647)` | Discussion | `The integration of PDH suppression by lpd1Δ and activation of the transhydrogenase-like shunt in BSW205 and BSW206 strains` |
| **S15** | `[22227, 22334)` | Results | `that correspond to isobutanol yields at 0.012 ± 0.0007 and 0.011 ± 0.001 g/g glucose consumed, respectively` |

Four negative checks, run the same way and reported because an absence is the load-bearing fact in
two of the three dispositions:

* `BSW191` does **not** occur anywhere in `[1414, 1551)` — S1 names no strain.
* No strain name (`BSW100`, `BSW191`, `BSW192`, `BSW205`, `BSW206`) occurs anywhere in
  `[1656, 1760)` or in `[1768, 1830)` — S2 and S3 name no strain either.
* `lpd1` does **not** occur in BSW191's genotype at `[9369, 9432)`. It does occur in BSW205's at
  `[9499, 9568)` and in BSW206's at `[9570, 9639)`.

---

## 2. Row 1 — `YAA:MOD:a7c8f9da22ee16e0` (`lpd1Δ`, `strain_id = YAA:STRAIN:bsw191`)

### The suspicion is confirmed. The row is false as it stands.

S5 is BSW191's genotype as the paper's own Table 1 prints it, and it carries no `lpd1Δ`. The atlas
does not even hold this as a genotype row — `genotype` has rows for `bsw192`, `bsw205` and `bsw206`
and none for `bsw191` — so BSW191's genotype lives only in the span, which is why the contradiction
survived promotion.

### But the disposition is retraction, not a corrected `strain_id`.

`docs/drafts/assertions/FIRST_BATCH.md` R2 suggests `strain_id` "should probably be
`YAA:STRAIN:bsw206`". That is the right *lineage* and the wrong *fix*, and the difference matters.

The row's own span, S1, names no strain. Its in-text counterpart does, and names **two**:

* **S14** (Discussion) is the same claim restated — `The integration of PDH suppression by lpd1Δ
  and activation of the transhydrogenase-like shunt in BSW205 and BSW206 strains`. S1's subject is
  the pair.
* **S9** (Results) gives the construction — LPD1 was disrupted in *both* BSW192 and BSW191. S6 and
  S7 fix which is which: BSW192 (`pATP423-MAE1`) + `lpd1Δ` → **BSW205** (`MAE1`), BSW191
  (`pATP423-PMsM`) + `lpd1Δ` → **BSW206** (`PMsM`).

So `bsw206` is genuinely the `lpd1Δ` descendant of `bsw191`, which is almost certainly how the
extractor's `strain_name_as_reported` came to say "BSW191" — but the sentence the row was promoted
from asserts the deletion of *one* gene in *two* strains, and there is no "respectively" to split
it, because it is the **same deletion in both**. One `modification` row cannot carry two subjects.
Patching `strain_id` to `bsw206` would produce one true row, silently drop BSW205, and leave a
Zone R row whose `evidence` string points at a span that names neither strain — a row a reader
following its own provenance could not confirm.

### What the row should actually say

Nothing. The fact it was trying to record is two facts:

* BSW205 carries `lpd1Δ` — evidenced by **S6**, which contains `lpd1Δ` verbatim beside the strain name;
* BSW206 carries `lpd1Δ` — evidenced by **S7**, likewise.

Neither of those needs this row. Both are already half-recorded in the atlas:
`YAA:GENOTYPE:bsw205.parsed_json` and `YAA:GENOTYPE:bsw206.parsed_json` both parse
`"deletions": ["LPD1"]`, from those same two spans. **Retracting loses nothing the atlas does not
already hold; it only removes a claim that is false.**

Promoting the two replacement `modification` rows is a curation act, not a SQL patch, and is
explicitly *not* proposed here — see §5.

### Blast radius

`assertion` = 5 and `evidence_item` = 5 as of this reading; all ten rows belong to
`doi:10.1186/s13068-019-1486-8` (the Wess/Boles paper) and **none cites this modification**.
`modification_localization_change` and `modification_mtdna_edit` hold 0 rows for it. The delete is
free-standing.

---

## 3. Row 2 — `YAA:MEAS:f7a49e8797f74431` (BSW191, 1.62 g/L titer)

### The suspicion is confirmed. The subject is wrong; the number is not.

BSW191's own isobutanol titer is **83 ± 2 mg/L**. S8 gives the number and the sentence immediately
before it (part of `[21543, 21804)`, the span the atlas already cites) gives the order —
`BSW192 and BSW191 strains possessing pATP423-MAE1 and pATP423-PMsM plasmids, respectively` — so
94 mg/L is BSW192 and 83 mg/L is BSW191. The atlas already holds both correctly:
`YAA:MEAS:086a34c189b69ed1` (bsw192, 94 mg/L) and `YAA:MEAS:1368a0dfec89ff16` (bsw191, 83 mg/L).

1.62 g/L is a different experiment entirely. S11 names its subject — **the BSW205 and BSW206
strains**, batch fermentation at 50-mL scale from 100 g/L glucose — and S12 reports it. S12's
`respectively` resolves against S11's ordering, and S13 (the Figure 6 legend) independently fixes
the same order, so:

* **1.62 ± 0.11 g/L → BSW205**
* **1.61 ± 0.03 g/L → BSW206**

### Disposition: correct `strain_id`, and move the span off the abstract

This is the "right number, wrong strain" case rather than the conflation case, and the difference
from Row 1 is precise: the row holds **one** number, and the paper assigns that number to **one**
strain. It is not carrying two subjects; it was given the wrong one.

The honest correction is two fields, not one. The assignment of 1.62 to BSW205 is **not readable
from the row's own span** — S2 says only "the two integrated strains" and gives no order at all. So
the `evidence` must move to `[22677, 22911)` (S12), where the subject is recoverable, or the
corrected row inherits the same unverifiable provenance the original had.

`value_as_reported` and `unit_as_reported` are untouched, which is both correct and mandatory:
`measurement_reported_value_is_immutable` would abort the update.

### What the row should actually say

> BSW205 (`YAA:STRAIN:bsw205`), isobutanol titer 1.62 g/L, 24 h, 50-mL batch from 100 g/L glucose,
> evidenced at `[22677, 22911)`.

### Owner decision, stated plainly

If you would rather not rest a Zone R subject on a `respectively` whose antecedent sits in the
*previous* sentence, the conservative alternative is to retract this row exactly as Row 1 is
retracted and re-curate two rows (BSW205 1.62 ± 0.11 g/L, BSW206 1.61 ± 0.03 g/L) from S11 + S12,
which would also pick up the standard deviations and the second strain's number. §6 gives the
correction; §6.4 gives the retraction variant. **The correction is what I recommend**, because the
number is real, the attribution is recoverable from the paper, and S13 corroborates it from a
second place.

### Gap this exposes (not a defect)

BSW206's **1.61 ± 0.03 g/L** has no row. So does BSW206's 50-mL yield of 0.016 ± 0.0003 g/g. Both
are curation tasks, listed in §5.

---

## 4. Siblings — the same provenance shape in the same paper

### The sweep

Every table in the schema carrying an `evidence` column was scanned for rows naming this
publication, and the `quote re-resolved at [a, b)` offsets were pulled out of each `evidence`
string. The paper's abstract runs `[128, 2243)` (`Abstract` heading at 128, body `Background` at
2243). **Four promoted rows cite offsets inside it.**

| row | offsets | span names a strain? | subject inferred? | verdict |
|---|---|---|---|---|
| `YAA:MOD:a7c8f9da22ee16e0` | `[1414, 1551)` | no | **yes** — `bsw191` | **retract** (§2) |
| `YAA:MEAS:f7a49e8797f74431` | `[1656, 1760)` | no | **yes** — `bsw191` | **correct** → `bsw205` (§3) |
| `YAA:MEAS:ab2a9e7b553b112c` | `[1768, 1830)` | no | **yes** — `bsw191` | **correct** → `bsw205` (below) |
| `YAA:BNK:fd51186dbd051805` | `[1131, 1232)` | n/a | no | **clean — leave it** |

So: **three** rows share the abstract-inferred-subject shape, of which the first batch had found
two. The third is new.

### The new one — `YAA:MEAS:ab2a9e7b553b112c` (BSW191, yield 0.016 g/g consumed)

Promoted from S3, `[1768, 1830)` — the clause of the *same* abstract sentence that follows S2 and
reports the *first* of the two 50-mL yields. It has the same defect, the same cause and the same
fix as Row 2, and it is arguably less ambiguous than Row 2: the abstract quotes `0.016 ± 0.001`,
and S12 shows `0.016 ± 0.001` is BSW205's while BSW206's is `0.016 ± 0.0003`. The standard
deviation disambiguates it on its own.

It is also definitely the 50-mL number and not the small-scale one: S15 gives BSW205's and BSW206's
small-scale yields as **0.012 ± 0.0007** and **0.011 ± 0.001** g/g. `→ YAA:STRAIN:bsw205`.

(The row's `uncertainty_sd` is NULL, so the ±0.001 that settles it is not stored. Worth filling in
at the same time; §6.3 does.)

### The one that is fine — `YAA:BNK:fd51186dbd051805`

Abstract-sited at S4, but **the suspicion does not apply**. `bottleneck` has no strain subject at
all, its `node` is `pyruvate node`, and the abstract sentence states that claim directly rather
than leaving it to be inferred. Its `observation_type` is `inferred`, which is the honest record of
a claim the authors reasoned to rather than measured. Nothing to change. I am listing it only
because it is the fourth abstract-sourced row and the sweep would otherwise look incomplete.

### Root cause — a bug in `split_sections`, reported and deliberately not fixed

This is not three independent mistakes. `fermdb.extract.harness.split_sections` returns **two**
sections named `results` for this paper:

```
abstract          [128, 138)
introduction      [138, 807)      <- the abstract's "Background"
results           [807, 1887)     <- the abstract's "Results"        *** this one ***
conclusion        [1887, 2243)    <- the abstract's "Conclusions"
introduction      [2243, 4882)    <- the body's "Background"
results           [4882, 23662)   <- the body's Results
discussion        [23662, 27072)
...
```

BMC's structured abstract has its own `Background` / `Results` / `Conclusions` sub-headings, and
`_HEADING_KEYWORDS` matches `^results?$` on the first of them. `build_excerpt` then includes
*every* section named `results`, so the excerpt sent to the model had three pieces —
`results`, `results`, `methods` — the first of which is the abstract. All four abstract-sited spans
lie in `[807, 1887)`, and every one of them is stored with `span.section = 'results'`, which is why
nothing downstream could tell they were abstract sentences.

The abstract is exactly the place where a paper compresses several strains into one sentence and
drops the subject, so feeding it to the extractor under the label "results" is precisely the input
that produces an inferred subject. PLAN.md V.4's cost argument for sending results-only is also an
*accuracy* argument, and it is being defeated here.

**`src/` is another agent's right now and this document does not touch it.** Flagging only. The
three rows above should be corrected regardless, because they are wrong today; the sectioning fix
is what stops it recurring in the next paper with a structured abstract.

### How the wrong subject got in

For the record, it was not invented at promotion time. All three curation-task payloads carry
`"strain_name_as_reported": "BSW191"` from the extractor itself, and
`fermdb.curate.promote` resolved that name to `YAA:STRAIN:bsw191` faithfully. All three were
resolved by the same bulk accept:

> `owner reviewed all 95 proposals in review.html on 2026-09-21 and judged them accurate, with
> differences he assessed as negligible; accepted in bulk on his instruction`

---

## 5. What is *not* proposed here, and why

Three things this document deliberately leaves alone, each of which is a curation act:

1. **The two replacement `modification` rows** (`lpd1Δ` on `bsw205` from S6, `lpd1Δ` on `bsw206`
   from S7). A promoted row's id is derived, not random: `fermdb/curate/promote.py` builds it as
   `YAA:MOD:` / `YAA:MEAS:` / `YAA:BNK:` + the first 16 hex of its task's `proposal_hash`.
   Hand-writing INSERTs would mint ids that hash nothing, so these belong in the queue, not in
   this file's SQL.
2. **BSW206's missing 50-mL numbers** — 1.61 ± 0.03 g/L titer and 0.016 ± 0.0003 g/g yield, both at
   S12. No rows exist.
3. **Re-promotion as a repair path.** It is not one. `promote` is idempotent by design: when a plan
   finds `already`, it writes nothing (`promote.py`, "re-promoting writes nothing new"), and
   `proposal_hash` is computed once at enqueue and never recomputed on edit. So editing a task's
   payload and re-promoting will *not* update an already-promoted row. That is why §6 updates the
   task *and* the row: otherwise the two disagree, which is how this started.

---

## 6. The change, as SQL

Read §§2–4 first. Take a backup — the repo's own convention is
`fermdb.sqlite3.pre-<label>.<UTC>.bak`. Then, against the **read-write** database:

```sql
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
```

### 6.1 Retract `YAA:MOD:a7c8f9da22ee16e0`

```sql
-- The claim is false: BSW191's genotype at [9369, 9432) carries no lpd1-delta, and the abstract
-- sentence at [1414, 1551) the row was promoted from is about BSW205 and BSW206 together
-- ([26525, 26647)), which one modification row cannot carry.
DELETE FROM modification WHERE id = 'YAA:MOD:a7c8f9da22ee16e0';

INSERT INTO curation_event
    (id, curator, actor_kind, action, target_type, target_id, rationale, zone)
VALUES
    ('YAA:CUEV:27d453dc97914d0092d6e25a04a8cfa3', 'kangkon', 'human', 'reject',
     'modification', 'YAA:MOD:a7c8f9da22ee16e0',
     'retracted 2026-09-22. The row recorded lpd1-delta on BSW191; Table 1 at [9369, 9432) gives '
     || 'BSW191 as BY4741/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-PMsM, with no lpd1-delta. '
     || 'The span it was promoted from, [1414, 1551), is an abstract sentence naming no strain; '
     || 'its in-text counterpart at [26525, 26647) names BSW205 and BSW206 together, and '
     || '[21995, 22113) gives the construction (LPD1 disrupted in BSW192 -> BSW205 and in '
     || 'BSW191 -> BSW206). One modification row cannot carry two subjects, so this is retracted '
     || 'rather than re-pointed. Replacements to be curated from [9499, 9568) and [9570, 9639). '
     || 'See docs/drafts/corrections/ZONE_R_CORRECTIONS.md section 2.',
     'R');

UPDATE curation_task
   SET status            = 'rejected',
       curator           = 'kangkon',
       curator_kind      = 'human',
       resolved_at       = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
       resolution_reason = 'reopened and rejected 2026-09-22: the record names BSW191, which has '
                           || 'no lpd1-delta; the quoted abstract sentence is about BSW205 and '
                           || 'BSW206 together. See '
                           || 'docs/drafts/corrections/ZONE_R_CORRECTIONS.md.',
       edited_payload    = NULL
 WHERE id = 'YAA:CTASK:e38704398c844715bd18cd89698e6cac';
```

> **Note on the SQL style.** SQLite does *not* concatenate adjacent string literals — `'a' 'b'`
> parses as `'a' AS b` and silently loses the second half. Every multi-line string below therefore
> uses an explicit `||`. Do not "tidy" those away.

### 6.2 Correct `YAA:MEAS:f7a49e8797f74431` — 1.62 g/L is BSW205's

```sql
UPDATE measurement
   SET strain_id = 'YAA:STRAIN:bsw205',
       evidence  = 'promoted from curation task YAA:CTASK:e0ccb26becca45019dd3e14767d26c83 on '
                   || 'doi:10.1186/1475-2859-12-119 (measurements[0]); quote re-resolved at '
                   || '[22677, 22911); curator kangkon; strain_id corrected from '
                   || 'YAA:STRAIN:bsw191 to YAA:STRAIN:bsw205 and the span moved off the abstract '
                   || 'on 2026-09-22 -- see '
                   || 'docs/drafts/corrections/ZONE_R_CORRECTIONS.md section 3'
 WHERE id = 'YAA:MEAS:f7a49e8797f74431';

INSERT INTO curation_event
    (id, curator, actor_kind, action, target_type, target_id, rationale, zone)
VALUES
    ('YAA:CUEV:ae519d1d8dd24b96a4a1ae4578ed72f1', 'kangkon', 'human', 'edit',
     'measurement', 'YAA:MEAS:f7a49e8797f74431',
     'strain_id corrected bsw191 -> bsw205 on 2026-09-22. 1.62 g/L is the 50-mL batch titer of '
     || 'the two integrated strains: [22429, 22573) names them (BSW205 and BSW206) and '
     || '[22677, 22911) reports 1.62 +/- 0.11 and 1.61 +/- 0.03 g/L respectively; the Figure 6 '
     || 'legend at [23392, 23466) fixes the same order. BSW191''s own titer is 83 +/- 2 mg/L at '
     || '[21744, 21804), already held as YAA:MEAS:1368a0dfec89ff16. The span was moved from the '
     || 'abstract at [1656, 1760), which says only "the two integrated strains" and gives no '
     || 'order, to [22677, 22911). value_as_reported and unit_as_reported are unchanged.',
     'R');

UPDATE curation_task
   SET status            = 'edited',
       curator           = 'kangkon',
       curator_kind      = 'human',
       resolved_at       = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
       resolution_reason = 'corrected 2026-09-22: the model wrote strain_name_as_reported '
                           || '"BSW191" against an abstract sentence naming no strain; 1.62 g/L '
                           || 'is BSW205''s. See '
                           || 'docs/drafts/corrections/ZONE_R_CORRECTIONS.md.',
       edited_payload    = json('{"confidence":"unverified","product_as_reported":"isobutanol","product_id":"YAA:PRODUCT:isobutanol","quantity_kind":"titer","review_state":"proposed","source_locator":"text","span":{"char_end":22911,"char_start":22677,"quote":"the isobutanol titer reached 1.62 ± 0.11 and 1.61 ± 0.03 g/L at 24 h after the start of fermentation, which corresponded to isobutanol yields of 0.016 ± 0.001 g/g glucose consumed and 0.016 ± 0.0003 g/g glucose consumed, respectively.","section":"results"},"strain_name_as_reported":"BSW205","time_h":24,"unit":"g/L","unit_canonical":"g/L","unit_state":"recorded","value":1.62,"zone":"I"}')
 WHERE id = 'YAA:CTASK:e0ccb26becca45019dd3e14767d26c83';
```

### 6.3 Correct `YAA:MEAS:ab2a9e7b553b112c` — 0.016 g/g is BSW205's (the sibling)

```sql
UPDATE measurement
   SET strain_id     = 'YAA:STRAIN:bsw205',
       uncertainty_sd = 0.001,
       evidence      = 'promoted from curation task YAA:CTASK:3e89f705f24b4a2497feca8d56612c33 on '
                       || 'doi:10.1186/1475-2859-12-119 (measurements[1]); quote re-resolved at '
                       || '[22677, 22911); curator kangkon; strain_id corrected from '
                       || 'YAA:STRAIN:bsw191 to YAA:STRAIN:bsw205 and the span moved off the '
                       || 'abstract on 2026-09-22 -- see '
                       || 'docs/drafts/corrections/ZONE_R_CORRECTIONS.md section 4'
 WHERE id = 'YAA:MEAS:ab2a9e7b553b112c';

INSERT INTO curation_event
    (id, curator, actor_kind, action, target_type, target_id, rationale, zone)
VALUES
    ('YAA:CUEV:1542c49cc8e4438b8ddbecb568a15545', 'kangkon', 'human', 'edit',
     'measurement', 'YAA:MEAS:ab2a9e7b553b112c',
     'strain_id corrected bsw191 -> bsw205 on 2026-09-22, same defect and same cause as '
     || 'YAA:MEAS:f7a49e8797f74431: promoted from the continuation of the same abstract '
     || 'sentence, [1768, 1830), which names no strain. 0.016 +/- 0.001 g/g is BSW205''s 50-mL '
     || 'yield and 0.016 +/- 0.0003 g/g is BSW206''s, per [22677, 22911); the small-scale yields '
     || 'at [22227, 22334) are 0.012 and 0.011 g/g, so this is unambiguously the 50-mL number. '
     || 'uncertainty_sd filled in from the same quote. value_as_reported and unit_as_reported '
     || 'are unchanged.',
     'R');

UPDATE curation_task
   SET status            = 'edited',
       curator           = 'kangkon',
       curator_kind      = 'human',
       resolved_at       = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
       resolution_reason = 'corrected 2026-09-22: same abstract sentence, same invented subject; '
                           || '0.016 +/- 0.001 g/g is BSW205''s. See '
                           || 'docs/drafts/corrections/ZONE_R_CORRECTIONS.md.',
       edited_payload    = json('{"basis":"consumed","confidence":"unverified","product_as_reported":"isobutanol","product_id":"YAA:PRODUCT:isobutanol","quantity_kind":"yield","review_state":"proposed","source_locator":"text","span":{"char_end":22911,"char_start":22677,"quote":"the isobutanol titer reached 1.62 ± 0.11 and 1.61 ± 0.03 g/L at 24 h after the start of fermentation, which corresponded to isobutanol yields of 0.016 ± 0.001 g/g glucose consumed and 0.016 ± 0.0003 g/g glucose consumed, respectively.","section":"results"},"strain_name_as_reported":"BSW205","substrate":"glucose","unit":"g/g","unit_canonical":"g/g","unit_state":"recorded","value":0.016,"zone":"I"}')
 WHERE id = 'YAA:CTASK:3e89f705f24b4a2497feca8d56612c33';
```

```sql
COMMIT;
```

### 6.4 Variant — retract the two measurements instead

If §3's owner decision goes the conservative way, replace 6.2 and 6.3 with deletes in the shape of
6.1 (`action = 'reject'`, `status = 'rejected'`, `edited_payload = NULL`), and add four curation
tasks against `[22429, 22573)` + `[22677, 22911)`: BSW205 titer 1.62 ± 0.11 g/L, BSW206 titer
1.61 ± 0.03 g/L, BSW205 yield 0.016 ± 0.001 g/g consumed, BSW206 yield 0.016 ± 0.0003 g/g
consumed. That is strictly more complete than the correction; it is also four curation decisions
rather than zero, which is the trade.

### 6.5 Verification after applying

```sql
-- 0 rows expected
SELECT id FROM modification WHERE id = 'YAA:MOD:a7c8f9da22ee16e0';

-- bsw205 twice, 1.62 g/L and 0.016 g/g
SELECT id, strain_id, quantity_kind, value_as_reported, unit_as_reported
  FROM measurement
 WHERE id IN ('YAA:MEAS:f7a49e8797f74431', 'YAA:MEAS:ab2a9e7b553b112c');

-- bsw191 should keep exactly one row, the 83 mg/L titer
SELECT id, quantity_kind, value_as_reported, unit_as_reported
  FROM measurement
 WHERE strain_id = 'YAA:STRAIN:bsw191';

-- no promoted row from this paper should still cite an offset inside [128, 2243) with an
-- inferred strain subject; only YAA:BNK:fd51186dbd051805 (no strain subject) should remain
SELECT 'measurement' AS t, id, strain_id, evidence FROM measurement
 WHERE publication_id = 'doi:10.1186/1475-2859-12-119'
UNION ALL
SELECT 'modification', id, strain_id, evidence FROM modification
 WHERE publication_id = 'doi:10.1186/1475-2859-12-119';
```

### 6.6 The rehearsal

§§6.1–6.5 were not written and left untested. The three SQL blocks were extracted from *this file*
and applied to a **throwaway in-memory database** built from `src/fermdb/db/schema.sql` and loaded
with copies of the rows they touch (this publication's `extraction`, `span`, `curation_task`,
`measurement` and `modification` rows, plus `organism`, `product`, `publication` and `strain`), with
`PRAGMA foreign_keys = ON`. Applied as one transaction, in the order written, they ran clean and
left exactly this:

```
modification WHERE id = 'YAA:MOD:a7c8f9da22ee16e0'        -> 0 rows
YAA:MEAS:f7a49e8797f74431   bsw205  titer  1.62   g/L
YAA:MEAS:ab2a9e7b553b112c   bsw205  yield  0.016  g/g   sd 0.001  basis consumed
measurement WHERE strain_id = 'YAA:STRAIN:bsw191'         -> 1 row, the 83 mg/L titer
curation_task  e387043...  rejected  human  edited_payload NULL
curation_task  e0ccb26...  edited    human  strain_name_as_reported BSW205, span 22677, value 1.62
curation_task  3e89f70...  edited    human  strain_name_as_reported BSW205, span 22677, value 0.016
curation_event 3 rows written (1 reject, 2 edit)
PRAGMA foreign_key_check                                   -> clean
```

The `measurement_reported_value_is_immutable` trigger did not fire, because no reported value or
unit is touched. **The live database was not opened for writing at any point.**

---

## 7. Summary

| row | suspicion | disposition | becomes |
|---|---|---|---|
| `YAA:MOD:a7c8f9da22ee16e0` | **confirmed** | **retract** — the source sentence is about two strains | *(nothing; replaced by two curation tasks)* |
| `YAA:MEAS:f7a49e8797f74431` | **confirmed** | **correct** `strain_id` + move span | BSW205, 1.62 g/L titer, 50-mL batch |
| `YAA:MEAS:ab2a9e7b553b112c` *(new sibling)* | n/a — found by the sweep | **correct** `strain_id` + move span | BSW205, 0.016 g/g yield, consumed basis |
| `YAA:BNK:fd51186dbd051805` | checked | **none** — abstract-sited but no inferred subject | unchanged |

Neither suspicion was unfounded. Both flagged rows are wrong, and the sweep found a third that is
wrong the same way and had not been flagged. The one abstract-sited row the sweep cleared is
cleared explicitly rather than by silence.

---

## 8. Root cause — fixed (appended 2026-09-22)

§4's `split_sections` bug is fixed in `src/fermdb/extract/harness.py`. A leading **structured
abstract** — the run of `Background` / `Results` / `Conclusions` sub-headings BMC and its
imitators print inside the abstract — is now collapsed into one `abstract` section by
`_fold_structured_abstract`, so the paper's own Results is the only thing named `results`. The
fix is in the sectioner, not in `build_excerpt`: `build_excerpt` could have been taught to take
only the largest `results`, but `span.section` would then still have said `results` for a
sentence in the abstract, and that is the half that made this invisible. `EXTRACTOR_VERSION` is
bumped `1` → `2`, so a version-1 row is identifiable as one that may carry this defect.

**Reach, measured over the 1,429 stored full texts.** 209 produce more than one section with a
name in `DEFAULT_EXTRACTION_SECTIONS` (`results` duplicated in 187, `methods` in 44). Counting
duplicates *understates* it: 293 papers have an abstract sub-heading reaching the model as body
text, because a paper whose body is `Results and discussion` gets an abstract `results` that
duplicates nothing. 301,243 characters of abstract stop being sent. This is a house style, not a
paper.

**Nothing real was dropped.** Before/after across all 1,429: zero body sections moved, resized or
vanished; every range the fix removes lies wholly inside the new `abstract`. The three
publications' body sections are byte-identical — this paper's Results stays `[4882, 23662)`. The
18 remaining duplicated `methods` are genuine Elsevier/MDPI bodies that announce Methods twice,
deliberately left alone: both halves are still sent, and a test pins that.

**A second paper, not covered above.** Of the 11 extractions performed, **5** were affected,
across **3** publications — `doi:10.1186/1475-2859-12-119` (this one), `doi:10.1186/s13068-019-1560-2`
(no span landed in its abstract) and **`doi:10.1186/s13068-019-1486-8`**, which §2 treats only as
the blast-radius neighbour. That paper has 5 abstract-sited spans stored `section = 'results'`,
and **two promoted `modification` rows** among them:

| row | offsets | span names a strain? | `strain_id` |
|---|---|---|---|
| `YAA:MOD:cc361f36d38986e4` | `[2157, 2306)` | **no** | `YAA:STRAIN:jwy19` |
| `YAA:MOD:5ad5ac8c1f7d0d2c` | `[2434, 2524)` | **no** | `YAA:STRAIN:jwy23` |

No strain token occurs anywhere in that paper's abstract, `[1213, 2601)`. Both rows therefore
have the same inferred-subject shape as §2's, and neither has been checked against its in-text
counterpart. **Not proposed here** — that is the same curation act §5 declines to take, and it
needs the body read the way §§1–4 read this one.

**Re-extraction is the owner's call and has not been run.** It is worth it for
`doi:10.1186/1475-2859-12-119` and `doi:10.1186/s13068-019-1486-8`, whose spans sit in the
abstract; `doi:10.1186/s13068-019-1560-2` was extracted from a polluted excerpt but no span
landed in the abstract, so re-extraction there buys only cost. Note that re-extraction produces
*new* proposals, not corrections: §5.3's point stands, so the rows above still need §6-style SQL
whatever is re-run.
