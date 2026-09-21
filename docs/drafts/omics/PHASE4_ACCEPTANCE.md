# Phase 4 acceptance, clause by clause

**Status:** draft, 2026-09-22. Assessed against the atlas as it stands, not against what is
planned. PLAN.md phase 4's acceptance paragraph reads:

> *no sample enters a contrast without an approved condition context; reprocessed results
> reproduce the direction of each study's own published DE for its highlighted genes; the
> reprocessed ethanol study count is exactly six; every Tn-Seq screen is represented as
> perturbation evidence rather than folded in with expression; **the corpus's statistical limits
> are stated in writing** — with this few independent studies, cross-study meta-analysis is
> underpowered for anything but large effects, and the atlas says so rather than implying
> otherwise.*

| # | clause | verdict |
|---|---|---|
| 1 | No sample enters a contrast without an approved condition context | **Vacuously true / not yet meaningful** — being worked separately |
| 2 | Reprocessed results reproduce the direction of each study's own published DE | **Cannot yet be evaluated** |
| 3 | The reprocessed ethanol study count is exactly six | **Fail — the count is zero** |
| 4 | Every Tn-Seq screen is represented as perturbation evidence rather than folded in with expression | **Half pass.** Not folded in: **pass**, and now tested. Represented as evidence: **fail**, blocked on a schema decision |
| 5 | The corpus's statistical limits are stated in writing | **Pass** — `STATISTICAL_LIMITS.md`, with every number measured |

Reproduce the evidence behind clauses 3, 4 and 5 with `fermdb omics limits` and
`fermdb omics tnseq`.

---

## Clause 1 — no sample enters a contrast without an approved condition context

**Verdict: vacuously true, and therefore not yet the property the clause is asking for.** Being
worked by another agent; recorded here only so the acceptance record is complete.

| | |
|---|---|
| `condition_context` rows | 0 |
| `sample` rows carrying a `condition_context_id` | 0 of 172 |
| contrasts in existence | 0 |

No sample enters a contrast because no contrast exists. The rule holds structurally — `sample`'s
own schema comment states it, and `load.py` leaves `condition_context_id` NULL deliberately rather
than guessing — but nothing has yet tested it against a case where it could fail. The clause
becomes meaningful the moment the first context is approved.

One thing worth flagging into that work, from `STATISTICAL_LIMITS.md` §4: **this is the only
clause blocking every within-study contrast in the corpus, and within-study contrasts are the
corpus's genuine strength.** At the tighter end of the measured dispersion bracket, three samples
a side detects a 9% change. Nothing else in phase 4 unlocks as much.

---

## Clause 2 — DE direction reproduction

**Verdict: cannot yet be evaluated. Not "fails" — there is no comparison to make, in either
direction, and constructing one today would require fabricating both of its sides.**

The clause needs three things. None exists.

### What is missing

**(a) A published DE call to compare against.** Zero anywhere in the atlas.

| | |
|---|---|
| `span` rows quoting `log2`, "differentially expressed" or "RNA-seq" | 0 |
| `extraction` payloads mentioning log2 / differential / fold change | 0 |
| `measurement` rows carrying a gene-level fold change | 0 — the 11 `fold_increase` and 1 `fold_change` rows are **titer** fold changes from engineering papers, not expression |

**(b) A place to put one.** PLAN.md F.5 specifies `contrast(origin='published')`. **There is no
`contrast` table in `src/fermdb/db/schema.sql`, and none in any migration.**
`evidence_item.contrast_id` exists as a bare `TEXT` column with no table behind it and no foreign
key. So the reprocessed side has nowhere to live either.

**(c) A link from a quantified study to the paper that published it.** All 15 `experiment` rows
carry `publication_id IS NULL`, with a stated refusal
(`src/fermdb/omics/experiments.py:PUBLICATION_LINK_REFUSAL`): runinfo's `Study_Pubmed_id` is a
legacy link-type code reading `3` for five unrelated studies, and a full-text mention of an
accession is a citation, not a deposit. Without this link there is no way to know **whose**
published DE a reprocessed contrast should reproduce.

And underneath all three: the reprocessed side of the comparison does not exist either, because
clause 1 blocks every contrast.

### What it would take, in order

1. **Harvest `elink(dbfrom=bioproject, db=pubmed)`** for the four quantified yeast studies
   (PRJNA733673, PRJNA772701, PRJNA484406, PRJEB33652) and the two bacterial ones. This is the one
   route `experiments.py` names as evidence, and it is unharvested rather than refused. Cheap: six
   E-utilities calls. Without it, every step below has no anchor.
2. **Add the `contrast` table** per F.5, with `origin ∈ {published, reprocessed}`, its
   `condition_context` pair, its `reference_assembly` (F.4 rule 4: a contrast may not mix
   references), and the study it belongs to.
3. **Curate each study's own highlighted genes and their direction** from the paper — the genes the
   authors named in their abstract, results or figures, with a `span` per gene. This is the
   expensive step and it is literature curation, not omics: four papers, perhaps 10–40 highlighted
   genes each.
4. **Approve condition contexts** for the samples those studies' own contrasts were built from
   (clause 1), then run the reprocessed contrast against the *same* grouping the paper used.
5. **Compare directions, and record disagreements as findings.** F.5 is explicit that a
   disagreement between the published and reprocessed result is itself worth surfacing rather than
   hiding — so the acceptance test is not "they all agree", it is "every highlighted gene has both
   directions recorded and every mismatch is a `conflict` row".

### What must not be done instead

Comparing a reprocessed contrast against *another* reprocessed contrast, or against a DE list
recalled rather than read from the paper, would satisfy the words of the clause and none of its
purpose. Step 3 is irreducible.

---

## Clause 3 — exactly six reprocessed ethanol studies

**Verdict: fail. The count is zero. Six of six slots are empty.**

Every one of the 15 SRA studies in the atlas comes from the committed isobutanol runinfo export.
No dataset is an ethanol reference study; `dataset` holds 15 rows, all `repository = 'SRA'`, none
ethanol.

PLAN.md B.3.4, as amended 2026-09-20 to add the E5 slot:

| # | slot | criterion | filled? |
|---|---|---|---|
| 1 | Anaerobic vs aerobic reference physiology | E3 | **no** |
| 2 | Ethanol as carbon source / diauxic-shift respiratory reference | **E5** | **no** |
| 3 | *pdc*-minus background (the E1 counterfactual) | E1 | **no** |
| 4 | Ethanol stress, acute shock | E4 | **no** |
| 5 | Ethanol stress, adapted growth | E4 | **no** |
| 6 | Industrial-strain reference | E2 | **no** |

**Zero of six. No acquisition is proposed here** — filling the slots is a costed decision
(`DATA_VOLUME.md` §3 puts the six studies at ~60–100 runs and ~25–45 GB) and is explicitly not
this work's call.

Three observations for whoever makes that decision:

* **The machinery to keep the cap is in place and working.** The
  `sra_ethanol_saccharomyces_reference_layer` family in `data/omics/dataset_families.yaml` carries
  `guard: ethanol_reference_cap`, so `fermdb omics discover` refuses it without `--force-guarded`,
  and `discover_sra_runs`'s `max_run_ids` cap (2000) would refuse the query's ~13,000 hits even if
  called directly. The cap is not at risk; the slots are simply empty.
* **`fermdb omics status` reports this misleadingly.** For an SRA family it prints
  `SELECT COUNT(*) FROM sra_run` — the whole table — so the guarded ethanol family currently
  displays a live count of 172 against an expected 13,117, implying 172 ethanol runs where there
  are none. The fix is to count per family term; it is not made here because the fix is a decision
  about what `expected_count` means for a guarded family.
* **Six and seven are different things, and the docs invite confusion.**
  `docs/reference/ETHANOL_REFERENCE_SLOTS.md` names **seven** slots. Those govern the ~150-
  publication *literature* layer and include slot 7 (E6, the genetic basis of industrial
  performance), which is partly computable from the genome set and has no reprocessed-
  transcriptomic counterpart. B.3.4's **six** are *reprocessed studies*. The six map onto slots
  1–6; slot 7 is not among them. This clause counts the six.

---

## Clause 4 — Tn-Seq as perturbation evidence

**Verdict: half pass.** Full argument and the schema options in `TNSEQ_UNIT.md`.

| half | verdict |
|---|---|
| *rather than folded in with expression* | **Pass.** No Tn-Seq run is in `quant_plan.json` or any matrix header. Previously true by accident; now a stated invariant with a test that proves the check fires |
| *represented as perturbation evidence* | **Fail.** 0 `evidence_item` rows, and no `evidence_type` can carry a genome-wide pooled screen |

**The unit, and its defence.** A screen is not one claim — an `assertion` is one subject, one
predicate, one direction, and a screen has ~1,800 subjects. The unit that *is* one claim is **one
gene in one screen**: gene disrupted, in library *L*, selection vs control, fitness statistic and
adjusted p. That is a perturbation, which is why PLAN.md grades a screen L1/L2 rather than L3.

The schema cannot store it, and each near miss fails differently: `direct_perturbation` demands a
`strain` row and a `measurement` row per gene, which a pooled library does not have;
`correlative_omics` fits perfectly and *is* the differential-expression slot, so using it would be
the folding-in this clause forbids and would cap the screen at L3; `comparative_genomic` means
association across strains nobody perturbed. The `ELSE 0` in `evidence_item`'s CHECK makes an
unlisted type unstorable by design — so this is reported, not forced.

**Recommendation: add an `evidence_type` rather than widen one** (`TNSEQ_UNIT.md` §3.3). Owner's
call; `src/fermdb/db/schema.sql` is outside this work's ownership and nothing was migrated.

**Also found and fixed:** `load.py` wrote `priority_rank = 0` for every run, so
`sra.priority_rank_for` — the one mechanism marking a screen as different from an expression run,
cited in `DATA_VOLUME.md` §2 and in the schema comment beside the column, unit tested throughout —
never reached the database. The loader now calls it. The 172 existing rows still read 0; correcting
them is a reload, not run here.

**Corpus note:** 8 Tn-Seq runs, not the 10 `DATA_VOLUME.md` §2 reports, and *Zymomonas mobilis*
ZM4 — not yeast. Plus 6 *Z. mobilis* `OTHER` runs (SRP591874) in neither layer, reported rather
than guessed.

---

## Clause 5 — the statistical limits, in writing

**Verdict: pass.** `docs/drafts/omics/STATISTICAL_LIMITS.md`, computed by
`src/fermdb/omics/limits.py`, re-runnable as `fermdb omics limits`, unit tested against published
normal quantiles and a hand-checkable sign test.

The headline numbers it is obliged to state:

* The yeast matrix is **99 samples from four studies**, one of which is 46% of it — and four is an
  **upper** bound on independent *groups*, because all 15 `experiment` rows name no publication.
* **Unanimous direction across all four studies has p = 0.125** — not significant before any
  correction. **Six** independent studies would be needed for one pre-specified gene; **eighteen**
  for a genome-wide scan over 6,187 genes; **eleven** for a pre-registered 36-gene panel.
* Random effects are structurally unavailable, not merely weak: with *k* = 4, *Q* has 3 degrees of
  freedom and τ² is unestimable.
* Both bacterial matrices are **one study of four samples** — *k* = 1, so cross-study integration
  is undefined rather than underpowered.
* **Within-study contrasts are a different story, and the document says so.** The measured residual
  bracket is σ ∈ [0.056, 0.741] log2 units, so three samples a side detects somewhere between a 9%
  change and a 3.2-fold change depending on the study. This is where the corpus's value is.
* And separately: **zero contrasts are definable today**, because no sample carries a condition
  context.

The clause asks the atlas to *say so rather than imply otherwise*. §7 of that document is a table
of claims the atlas may and may not make, which is the operative form of saying so.

---

## What changed in the codebase for this assessment

All within `src/fermdb/omics/**`, its tests, and `docs/drafts/omics/`.

| file | change |
|---|---|
| `src/fermdb/omics/limits.py` | **new** — corpus inventory, measured dispersion bounds, power and sign-test arithmetic, standard library only |
| `src/fermdb/omics/tnseq.py` | **new** — screen inventory, the folded-into-expression invariant, and `SCREEN_UNIT_REFUSAL` |
| `src/fermdb/omics/load.py` | `priority_rank` now comes from `sra.priority_rank_for` instead of a literal `0` |
| `src/fermdb/omics/__init__.py` | `fermdb omics limits` and `fermdb omics tnseq` |
| `tests/test_omics_limits.py` | **new** — 21 tests |
| `tests/test_omics_tnseq.py` | **new** — 9 tests |
| `tests/test_omics_load.py` | the `priority_rank` regression, pinned after a real load |
| `docs/drafts/omics/` | this file, `STATISTICAL_LIMITS.md`, `TNSEQ_UNIT.md` |

Nothing was migrated, re-quantified or downloaded, and no row in the live database was written.
