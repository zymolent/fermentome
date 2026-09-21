# The measuring stick, reconciled

2026-09-21. Seven per-category drafts in this directory, produced by a six-agent verification
wave, merged into **one** proposed update to `data/benchmarks/known_positives.yaml`.

The merged candidate is **`docs/drafts/benchmarks/MERGED_known_positives.candidate.yaml`**.
**Nothing has been written to `data/`.** Project rule L.5 and decision D2
(`docs/reports/2026-09-21-unattended-work-plan.md` §1) reserve that move for a human.

## What this pass did not do, and could not do

**No `confidence` value was set. No `verified` flag was flipped.** Every entry in the candidate
still reads `confidence: unverified` and `verified: false`, byte for byte as in the current data
file. The whole of this pass's assessment lives in the `evidence` field, plus the `statement` and
`expected_outcome` corrections listed below. A machine check in the build asserts this for all 41
entries and it passes.

That is not modesty. `data/benchmarks/README.md` lists five things a curator must do before an
entry is usable, and steps 4 and 5 are exactly "set `confidence`" and "set `verified: true`". This
pass did steps 1 to 3 — found the source, checked the statement against it, and overwrote the
placeholder `evidence` with the real source and a re-resolved quote. Steps 4 and 5 are a person's.

## Span verification

**78 of 78 re-resolved exact, 0 absent, 0 spliced.**

(78 span placements across the 41 entries, drawn from 76 distinct quotes — one span, the
matrix-localization sentence in `doi:10.1038/s41598-019-40631-5`, is cited by three entries and
was re-resolved for each.)

Every quote that appears in the candidate file or in this report was located in the **real stored
document** — the text `fermdb.extract.harness.load_source_text` returns for that publication,
which is what the extraction pipeline itself shows a model — and then re-checked at its own
offsets with `fermdb.llm.validate.verify_span` (exact comparison, no whitespace normalisation, no
fuzzy match). Offsets are 0-based half-open `[char_start, char_end)` and are recorded beside every
quote in the candidate's `evidence` fields.

Three quotes as the drafts gave them did **not** resolve on the first pass, and all three were
repaired against the source rather than accepted:

| draft quote | what was wrong | resolution |
|---|---|---|
| BM-MIT-004, BM-MIT-005 (`doi:10.1093/nar/gkx127`, `gkx426`) | the prime in `5′-UTR` was transcribed as U+0374 GREEK NUMERAL SIGN; the stored text has U+0384 GREEK TONOS | re-copied from the source, then resolved exact |
| BM-NEG-002's reference-gene quote | attributed to a corpus file whose DOI the draft did not record | **dropped.** A negative control's result is an absence; it needs no quote, and a quote that cannot be re-resolved is not evidence |

Three further quotes were **widened** before entering the output because the drafts gave them as
mid-sentence fragments (`COF-004.yeastfail`, `MIT-006.import2023`, `ETH-003.lab`); each was
extended to a complete, contiguous sentence or table row and re-resolved.

**On splicing.** `mitochondrial_genetics.yaml` records that the agent originally submitted
BM-MIT-006's evidence as one quote joined by a literal `[...]`, and that a curator split it. That
split is honoured here: the three passages from `doi:10.7717/peerj.8362` enter the candidate as
three separately-resolved spans with three sets of offsets, never as one quote. The same is true
of BM-ETH-003, where `ethanol_reference.yaml` gave a two-paragraph quote spanning a paragraph
break; only the first, contiguous paragraph is used.

**On the blockquotes in this report.** Quotes shown below as Markdown blockquotes are soft-wrapped
for reading; the byte-exact form of every one, with its PDF-extraction line breaks intact, is in
the candidate file's `evidence` fields, and the offsets given here index the stored text, not this
page.

**On material outside the corpus.** BM-NEG-004's three decisive papers are not in the 1,309-text
corpus; the verification wave found them by live PubMed search. Their content is **summarised in
prose and deliberately not quoted** anywhere in the candidate, because a quote that cannot be
re-resolved in a stored document is not evidence in this project. The same rule was applied to
every figure the drafts flagged as paraphrased (the Greek-delta strain names in `00438.txt` and
`00662.txt`); those appear as prose, never inside quote marks.

---

## 1. The self-contradiction — resolved

**This is the finding that matters most, because it is the one that made the set unpassable.**

`BM-PATH-007` asserted the isobutanol route crosses the mitochondrial inner membrane *exactly
once*, with `expected_outcome: "Exactly one compartment transition."` `BM-PATH-011` asserts that
pyruvate itself enters the matrix through the mitochondrial pyruvate carrier — a second
transition. Two entries in one file, two different numbers for one count.

`doi:10.1038/s41598-019-40631-5` settles it in consecutive clauses. Re-resolved at
**chars [3268, 3689)** of the stored full text, exact:

> In S. cerevisiae, cytosolic pyruvate is imported into the mitochondria via mitochondrial
> pyruvate carrier (MPC) complex, and then pyruvate is converted to 2-KIV by sequential catalytic
> reactions of Ilv2 (ALS), Ilv5 (KARI), and Ilv3 (DHAD) in the mitochondrial matrix. The
> mitochondrial 2-KIV is then exported to the cytosol, and finally converted to isobutanol through
> Ehrlich pathway, involving endogenous KDCs and ADHs.

Two crossings: pyruvate in, 2-ketoisovalerate out. A second source, `doi:10.1080/21655979.2021.1978189`
at **chars [22483, 22604)**, independently starts the route at glycolytic pyruvate in the cytosol —

> Pyruvate produced through glycolysis are transferred into the mitochondria through the
> mitochondrial pyruvate complex [].

— so no consulted source draws the route boundary at matrix pyruvate, which is the only reading
under which "exactly once" would be true.

**BM-PATH-011 was right and BM-PATH-007 was wrong.** Both are corrected in the candidate, and
their `expected_outcome`s now reference each other so the inconsistency cannot silently return.

### Why it matters

Because BM-PATH-007's expected outcome was an *exact count*, an atlas that correctly returned both
transitions scored as a **failure** on it. The measuring stick penalised correctness. And because
BM-PATH-011 asserted the very transition BM-PATH-007 denied, no atlas could satisfy both: a run
that passed one necessarily failed the other. PLAN.md S.5 calls recovery against this set "the
headline number for whether the atlas works" — and that number was not merely unmeasured, it was
**unobtainable**. A set that contradicts itself has no achievable maximum score, so there was no
denominator. Worse, the defect would have surfaced as a low recovery rate and been blamed on the
pipeline, which is the failure mode the whole phase-0-first design of this file exists to prevent.

### The corrected pair

**BM-PATH-007 — `statement`**

> In the native (unengineered) configuration the isobutanol route crosses the mitochondrial inner
> membrane exactly twice: cytosolic pyruvate is imported into the matrix through the mitochondrial
> pyruvate carrier, and the 2-ketoisovalerate made there is exported back to the cytosol for
> decarboxylation. Counted from cytosolic pyruvate the route is cytosol -> matrix -> cytosol.

**BM-PATH-007 — `expected_outcome`**

> Exactly two compartment transitions along a route whose start compartment is cytosolic pyruvate
> - pyruvate in at the carrier step, 2-ketoisovalerate out at the branch-point step - returned as
> two distinct transport steps rather than one. A route returned with one transition has dropped
> the pyruvate import step, which is the error this entry was rewritten to catch; a route returned
> with zero transitions means compartment is being dropped somewhere in the join. The count
> returned here must agree with BM-PATH-011, which names the first of the two transitions.

**BM-PATH-011 — `statement`**

> Cytosolic pyruvate reaches the mitochondrial matrix through the mitochondrial pyruvate carrier
> (MPC) complex, encoded by MPC1, MPC2 and MPC3 with MPC1 required for function. This is the first
> of the two inner-membrane crossings the native route makes (BM-PATH-007), and it is itself
> engineerable: overexpressing mpc1 together with mpc3 is reported to improve isobutanol
> production.

**BM-PATH-011 — `expected_outcome`**

> A named carrier complex returned, resolving to the MPC1/MPC2/MPC3 gene group, distinguishing it
> clearly from the unidentified 2-ketoisovalerate carrier of BM-PATH-008. The contrast between
> these two entries is the point: the atlas must return a name for one and a gap for the other.
> This transition must also be counted by BM-PATH-007; an atlas that names the carrier here and
> reports one transition there is internally inconsistent and fails both. The sources consulted
> say pyruvate is imported 'into the mitochondria' and do not name the inner membrane, so a row
> asserting the specific membrane needs a source beyond those in evidence.

Note the second correction folded into BM-PATH-011: the entry said "mitochondrial inner membrane",
and a targeted search returned **zero** corpus texts pairing MPC with "inner membrane". The
statement now says the matrix, and the expected outcome names the membrane as a claim still
needing a source. Separately, Herzig et al. and Bricker et al. (Science 2012) are in the corpus
only as citations, so this entry's `expected_evidence_level: L2` is **not reachable from the
corpus alone** — flagged, not changed, because evidence levels are a curator's call.

---

## 2. The two `contradicted` entries

### BM-PATH-007 — corrected, not removed

Handled in full above. Not removed: `data/benchmarks/README.md` is explicit that a disproven entry
is a *better* benchmark once rewritten, because it tests discrimination rather than recall. Here
the rewrite is stronger still — the corrected entry now catches the specific error of dropping the
pyruvate import step from a compartment count.

### BM-MIT-006 — corrected, and one leg withdrawn

The entry asserted "There is no established CRISPR-Cas route for editing yeast mtDNA". The corpus
holds `doi:10.7717/peerj.8362` (2020) reporting the opposite. Three separately re-resolved spans:

**chars [176, 360)** — the premise the row rests on, which survives:

> Organelles have been considered off-limits to CRISPR due to their impermeability to most RNA and
> DNA. This has prevented applications of Cas9/gRNA-mediated genome editing in organelles

**chars [1464, 1653)** — the contradiction:

> We confirmed donor DNA insertion at the target sites facilitated by homologous recombination
> only in the presence of Cas9/gRNA activity in yeast mitochondria and Chlamydomonas chloroplasts.

**chars [2178, 2317)**:

> This is the first demonstration of CRISPR-mediated genome editing in both mitochondria and
> chloroplasts in two distantly related organisms.

**Proposal: corrected statement, not removal — and the mitoTALEN leg withdrawn outright.**

Four things are true at once and the old row flattened them into one false headline:

1. A CRISPR route **is** demonstrated (2020), and it **inserts** rather than deletes.
2. It **sidesteps** the import problem rather than solving it: Cas9 and the guides are expressed
   from a plasmid delivered biolistically that then replicates inside the organelle. So the row's
   *premise* survives, and is restated by a 2023 review in the corpus
   (`doi:10.3390/microorganisms11041040`, chars [31491, 31704) and [41358, 41490)) which says
   mtDNA editing with CRISPR-Cas9 "remains highly challenging because of the difficulties in
   transporting gRNA and donor DNA into the mitochondria" and that the successful example "remains
   insufficient in editing efficiency".
3. The biolistic-into-rho-zero route is well attested — at least five corpus papers.
4. **The mitoTALEN/mitoZFN leg has no yeast support in this corpus at all.** The only mitoTALEN
   paper held is about *plant* mitochondria; DdCBE and TALED are tabulated for mammalian cells
   only. That leg is therefore **withdrawn from the statement rather than restated**, because
   asserting it would be a fabrication in the opposite direction.

The corrected statement is date-stamped ("as of 2020", "as of a 2023 review") so the row's staleness
is visible rather than implicit, which is what its own `source_hint` asked for.

**Remaining curator action.** This row is *compound* — four separable claims behind one verdict —
and a compound row cannot be scored. Splitting it per technique is the right move, but per
`data/benchmarks/README.md` that means **retiring the id and writing new ones that point back to
it**. Minting ids is a curation act, so this reconciliation does not do it; the corrected single
row is the safe interim, and the split is recommended.

---

## 3. The 16 `partially_supported` entries

Each row: what the corpus supports, what it does not, and the narrowed statement now in the
candidate. The full new wording of every one is in
`MERGED_known_positives.candidate.yaml`; the table in §6 gives old → new verbatim.

| id | supported | **not** supported | narrowing |
|---|---|---|---|
| **BM-PATH-003** | matrix localization; an Fe-S cluster requirement; the reaction | the **[4Fe-4S]** stoichiometry — disputed *inside* the corpus: one source assigns 4Fe-4S to the DHAD family, another 2Fe-2S to yeast ILV3 specifically, a third records every solved ilvD/EDD structure as [2Fe-2S] | requirement recorded **without a stoichiometry**; oxygen lability removed (asserted for the family, never for yeast Ilv3) |
| **BM-PATH-006** | cytosolic compartment; more than one ADH candidate | the roster: "Adh1-Adh7 **and Adh6**" names Adh6 twice, and the source gives **ADH1-5**, not Adh1-Adh7. Cofactor is disputed (NADH for ADH1-5 vs NADPH for the step vs NADPH for Adh7) | roster restated as ADH1-ADH5 plus ADH6 and ADH7 separately; cofactor made an explicit per-candidate requirement |
| **BM-PATH-011** | MPC import; MPC1/2/3 composition; engineerability | **"mitochondrial inner membrane"** — zero corpus texts pair MPC with "inner membrane" | says "matrix"; membrane flagged as needing an outside source; now counted by BM-PATH-007 |
| **BM-COF-004** | an engineered NADH-preferring IlvC exists; 13.4 g/L at 100% theoretical anaerobically in *E. coli* | that the KARI swap was **"the change"** — the strain carried **both** IlvC6E6 *and* AdhA-RE1; and "the single highest-leverage part choice in the catalog", which is countered for yeast | attribution corrected to two enzymes; the leverage clause **dropped**, not softened, and replaced with the yeast counter-result (NADH-KARI variants did not outperform wild-type; localization was the 3.8-fold lever) |
| **BM-COF-005** | that no matrix NADPH **quantity** exists in 1,309 texts | that supply is *unknown* — it is known qualitatively: Pos5, Ald4/Ald5, Idp1, Mae1, Pos5 the main source | "quantity, not identity, is the open gap"; gap kind pinned to `quantitative_value_missing` |
| **BM-CMP-002** | abolition by the pdc1 pdc5 double deletion (0.01 g/L); the C2 requirement | that **PDC1 deletion reduces ethanol** meaningfully — 12.6 g/L against 13 g/L wild type, "only minor effects" in the authors' own words, because PDC5 derepresses. Also "all three" is more than needed: PDC1+PDC5 sufficed | single deletion restated as *minor*, with the derepression mechanism; double deletion named as the one that abolishes |
| **BM-CMP-004** | Bat1: mitochondrial, converts KIV to valine, deletion raised isobutanol 2.5-fold | **the Bat2 half** — no own-result localization or deletion contrast anywhere; the compartment split is background only, tracing to a PMID not in the corpus | records the split as background-grade; adds that the BAT1 deletion's **sign is background-dependent** (raised isobutanol in one strain, harmful in another) |
| **BM-MIT-002** | CUN → threonine in *S. cerevisiae*, via the 8-nt-anticodon-loop tRNA-Thr | the enumeration CUU/CUC/CUA/CUG (nothing lists all four); the phrase "translation table 3"; and the "most dangerous difference" clause, which is editorial and not testable by the query shape | keeps the mistranslation consequence but marks it an **inference**; expected outcome now states that the four-codon demand tests the recoder against the NCBI table, not the corpus |
| **BM-MIT-003** | that table 3 is the yeast code and that **AUA is reassigned** in it | **what AUA is reassigned to.** No corpus document anywhere states AUA = Met | keeps AUA = Met but sources it to the NCBI page, not a paper; adds the corpus's own caveat that the AUA reassignment is unsupported in many Saccharomycetales |
| **BM-MIT-005** | ARG8m recoded, matrix-localized, expressed from mtDNA under the replaced gene's UTRs | the **locus restriction** to COX3/COX2 — ARG8m is used at COX1, COX2, COX3, COB, VAR1, ATP6, ATP9 | locus clause **widened**; the respiration cost added (ATP9::ARG8m grows on glucose without arginine, not on glycerol) |
| **BM-ETH-001** | 0.511 g/g with substrate, organism and basis named; the arithmetic | that every atlas yield is expressible as a fraction of it — a property of the atlas, not a literature claim | adds the two hazards: 0.511 is the minority spelling (4 files vs 17 rounding to 0.51), and many papers apply 0.51 g/g to **xylose** |
| **BM-ETH-002** | the stoichiometry and the mass ratio | the third decimal: no corpus file writes 0.411 for glucose | keeps **0.411**, with the arithmetic, and records why the apparent xylose mix-up is not one (see below) |
| **BM-ETH-003** | that 92% is reported — for **industrial** Brazilian sugar-cane ethanol | that this is **wild-type laboratory physiology.** The lab reference strain gives 1.56 mol/mol = **78%**, not 90% | restated as two numbers with their contexts, plus the growth-rate dependence that makes any single number unusable |
| **BM-TOL-001** | the isobutanol half, molar, with a growth endpoint (~190 mM) | the **comparison** — the ethanol figure is a different paper, strain, medium and protocol, and is in g/L | direction stated as supported, matched pair declared `not_in_corpus`; adds the w/v vs v/v inconsistency *inside* the isobutanol source (189 mM vs 151 mM, a 25% spread) |
| **BM-TOL-002** | five assay types, and non-interconvertibility **demonstrated** (two assays invert the strain ranking) | that the five are the five named — **IC50 and MIC are not attested for isobutanol in yeast** anywhere in the corpus; MIC appears only in a bacterial paper | the five replaced with the five that exist; the IC50/MIC emptiness recorded as a finding about the literature |
| **BM-TOL-003** | the *principle*, and an in-corpus instance of it | the rule itself — the L3 cap is project policy, and the best justification is a **bacterial** paper | keeps the cap, names it as policy, and adds the counterexample that makes the "unless" clause load-bearing: a tryptophan/membrane mechanism reasoned from ethanol and then **demonstrated directly for isobutanol** in yeast, which a blanket cap would under-rate |

### The 0.411 g/g scare, settled

The ethanol draft reported that 0.411 g/g is a substrate mix-up — that `doi:10.1093/femsyr/foae006`
writes 410 mg/g for glucose and 411 mg/g for **xylose**, and that the benchmark pinned the xylose
ceiling onto glucose. Since 0.411 g/g is PLAN.md's phase-1b acceptance bound and sits in
`product_theoretical_yield`, the arithmetic was run rather than the claim relayed.

The textual observation is real. `doi:10.1093/femsyr/foae006`, **chars [5152, 5261)**, exact:

> the theoretical yields of 410 mg isobutanol/g glucose (Generoso et al. ), or 411 mg/g xylose
> (Zhang et al. ).

**The inference is wrong.** Isobutanol from glucose is 1 : 1 and from xylose is 5 : 6, and both
come to **0.41142 g/g** — the same number to five places, because the carbon balance per carbon is
identical (1 C6 → 1 C4 + 2 CO₂; 6 C5 → 5 C4 + 10 CO₂). The paper's "410" for glucose is the
rounding that is slightly off, not the "411". **PLAN.md's 0.411 g/g is correct and the bound check
stands.** Two consequences are carried into the candidate: the substrate must still be recorded
explicitly (a scraper reading `0.51` or `0.41` without its substrate will silently pool hexose and
pentose bases), and for DUET the result is useful rather than neutral — the programme's substrate
partition is C5 → isobutanol, and the mass-yield ceiling from xylose is identical to glucose, so
whatever the case for the xylose route is, it is not a yield penalty.

---

## 4. The negative controls

**5 hold, 1 uncertain, 0 refuted.** No negative-control `statement` is changed: they held, so
there is nothing to correct. Their `evidence` fields now carry the searches, the traps and the
outstanding work.

| id | verdict | the thing to carry forward |
|---|---|---|
| BM-NEG-001 | holds | **Trap:** the corpus is full of "codon-optimized" pathway genes unrelated to table 3 — one paper codon-optimizes Ilv2/Ilv5/Ilv3 in a strain where the MTS was *removed*. A pipeline keying on "codon" + "mitochondrial targeting" in one sentence manufactures exactly the error this control guards against. Still needs its textbook citation. |
| BM-NEG-002 | holds | The four genes × "isobutanol" in one window: **zero** documents. **Trap:** one wine-fermentation paper tabulates all four genes *and* names isobutanol in its introduction — document-level co-occurrence joins them, window-level does not. **Still owed:** nobody has confirmed the four are condition-insensitive under fermentative conditions. |
| BM-NEG-003 | holds | Four converging lines including a whole-corpus document-level scan and a recorded PubMed search (strings and date preserved). **Still outstanding:** `source_hint` asks for PubMed **and Google Scholar**; Scholar was never run — no tool in that session — so this control is not fully curated even though it holds on everything that was. |
| BM-NEG-004 | holds, narrowly | **The three decisive papers are not in the corpus.** A 1991 study demonstrates the purified yeast mitochondrial pyruvate carrier transports 2-oxoisovalerate — right membrane, no gene, and the control survives on the "specific gene has been established" clause *alone*. A 2017 study finds **Jen1** transports 2-ketoisovalerate — named gene, plasma membrane: **an atlas that drops the membrane qualifier will return JEN1 and be wrong.** A 2008 study is an explicit negative for Oac1p. This control cannot be curated from the corpus. |
| BM-NEG-005 | holds | Clean. **Trap:** two documents use an "A and B from X and Y" construction that inverts if read as adjacency, yielding "isobutanol … from leucine". |
| **BM-NEG-006** | **uncertain** | see below |

### BM-NEG-006 — what would settle it, exactly

The uncertainty is about **testability**, not about evidence found against the claim. No corpus
document could constitute a counterexample, because BM-NEG-006 is not a claim about the literature
at all — its own `source_hint` says so. What it forbids is the atlas emitting a part as
yeast-demonstrated when that part's only `expression_record` has `host=E. coli`. Only the atlas's
own query output can bear on that. Marking it "holds" from a corpus search would be the exact
category error the control exists to catch.

**It is settled by three steps, in this order:**

1. Curate **BM-COF-004** first, so the parts catalog holds the *E. coli* expression records for
   IlvC6E6 and AdhA-RE1 (the pair is now explicit in BM-COF-004's corrected statement).
2. Run the part ranking for `host=S. cerevisiae` directly against the parts catalog.
3. Assert that **every part whose only `expression_record` is `host=E. coli` comes back flagged
   untested-in-target-host rather than ranked as demonstrated.**

That is a unit test over the atlas's join and it belongs next to the join, in `tests/`, not as a
row to be verified in this file. **One thing to watch when BM-COF-004 is curated:** `adhA` is
exactly the part where host matters, because the yeast literature uses engineered *variants* of
it. If the catalog stores the *E. coli* parent and the yeast variant under one part id, the join
will look correct while being wrong.

---

## 5. What the merged candidate does to the test suite — read this

`python -m pytest tests/test_benchmarks.py` against the candidate: **17 passed, 1 failed.**

The failure is not a defect in the candidate. It is a **real design decision this pass cannot
make**, and it is the single thing a curator must settle before the candidate can be adopted:

```
FAILED tests/test_benchmarks.py::test_unverified_entries_say_no_source_was_consulted
```

That test asserts that any entry with `confidence: unverified` must have an `evidence` value
containing the marker string `"no source consulted"`. The file's model has exactly two states:

* `confidence: unverified` **and** evidence saying nobody has looked; or
* curator-promoted, with a real source and `confidence` raised.

**There is no state for "sources have now been consulted, read and quoted, but no curator has
promoted the row."** That third state is precisely what this reconciliation produces, and it is
what the hard rules of this task require — evidence updated, `confidence` and `verified`
untouched.

**This was deliberately not gamed.** The marker string could have been smuggled into the evidence
text as a quotation of the old value, and the test would have gone green while the file said
something false. A test passing on a technicality is worse than a failing test that names a real
gap.

`data/benchmarks/README.md` already anticipates this: *"that test will start failing the moment a
curator begins promoting entries — at which point the test is to be relaxed deliberately, in a
reviewed diff, not silently."* This is that moment, arriving one step earlier than expected.

**Recommended relaxation, for the curator to make in a reviewed diff:** replace the two-state
assertion with a three-state one — an `unverified` entry must *either* say no source was consulted
*or* carry a re-resolvable source span — so the honesty the test protects survives while the
"checked but not promoted" state becomes expressible. Do not simply delete the test.

*(A second failure, `test_readme_states_the_prohibition`, appears only when `FERMDB_BENCHMARK_FILE`
points into `docs/drafts/benchmarks/`, because that test looks for a `README.md` beside the
benchmark file. With `data/benchmarks/README.md` placed beside the candidate it passes. It is an
artefact of the draft location and will disappear the moment the candidate lands in `data/`.)*

Other machine checks run on the candidate, all passing:

* top-level keys, their order and their values identical to the current file;
* 41 entries, same ids, same order;
* per-entry **key order identical** for all 41 — the file is a clean field-level diff;
* every field other than `statement`, `expected_outcome` and `evidence` byte-identical;
* `confidence == 'unverified'` and `verified is False` on all 41;
* every one of the 76 quotes survives the YAML round trip **byte for byte** (this is why `evidence`
  uses a literal `|-` block rather than the folded `>-` the other fields use: folding would
  silently convert the PDF-extraction line breaks inside quotes from `doi:10.1038/nbt.2509` into
  spaces, which would make them no longer verbatim. No other scalar style was changed).

---

## 6. Every `statement` change, old → new

18 entries. `expected_outcome` changed on the same 18 and nowhere else. The other 23 entries — the
17 `supported` and the 6 negative controls — keep their `statement` and `expected_outcome` exactly
as they are today; only their `evidence` is rewritten.

<!-- generated from the two files, not retyped -->

### BM-PATH-003

**old** > Dihydroxyacid dehydratase Ilv3 is localized to the mitochondrial matrix, carries a [4Fe-4S] cluster, and converts 2,3-dihydroxyisovalerate to 2-ketoisovalerate.

**new** > Dihydroxyacid dehydratase Ilv3 is localized to the mitochondrial matrix, requires an iron-sulfur cluster, and converts 2,3-dihydroxyisovalerate to 2-ketoisovalerate. The cluster type is disputed inside the consulted literature - one source assigns [4Fe-4S] to dihydroxyacid dehydratases as a family, another assigns 2Fe-2S to yeast ILV3 specifically, and a third records that every solved crystal structure in the ilvD/EDD family so far carries [2Fe-2S] - so the requirement is recorded without a stoichiometry.

### BM-PATH-006

**old** > The final reduction of isobutyraldehyde to isobutanol is catalysed in the cytosol by alcohol dehydrogenases, with Adh1-Adh7 and Adh6 among the candidates.

**new** > The final reduction of isobutyraldehyde to isobutanol is catalysed in the cytosol by alcohol dehydrogenases, of which more than one is a candidate: the sources consulted name ADH1-ADH5 as a group for this step, and ADH6 and ADH7 separately. Cofactor preference is not uniform across the candidates and is disputed in the literature for this step, so it must be recorded per candidate and never on a merged 'ADH' row.

### BM-PATH-007

**old** > In the native (unengineered) configuration the isobutanol route crosses the mitochondrial inner membrane exactly once, between 2-ketoisovalerate production in the matrix and its decarboxylation in the cytosol.

**new** > In the native (unengineered) configuration the isobutanol route crosses the mitochondrial inner membrane exactly twice: cytosolic pyruvate is imported into the matrix through the mitochondrial pyruvate carrier, and the 2-ketoisovalerate made there is exported back to the cytosol for decarboxylation. Counted from cytosolic pyruvate the route is cytosol -> matrix -> cytosol.

### BM-PATH-011

**old** > Pyruvate reaches the mitochondrial matrix through the mitochondrial pyruvate carrier, so the matrix branch of the route depends on a transport step that is itself engineerable.

**new** > Cytosolic pyruvate reaches the mitochondrial matrix through the mitochondrial pyruvate carrier (MPC) complex, encoded by MPC1, MPC2 and MPC3 with MPC1 required for function. This is the first of the two inner-membrane crossings the native route makes (BM-PATH-007), and it is itself engineerable: overexpressing mpc1 together with mpc3 is reported to improve isobutanol production.

### BM-COF-004

**old** > Engineering an NADH-preferring KARI variant was the change that enabled near-theoretical anaerobic isobutanol production in Escherichia coli, which makes cofactor preference the single highest-leverage part choice in the catalog.

**new** > Switching ketol-acid reductoisomerase cofactor preference from NADPH to NADH, TOGETHER WITH an NADH-dependent alcohol dehydrogenase (L. lactis AdhA-RE1), enabled anaerobic isobutanol production at 100 percent of theoretical maximum yield (13.4 g/L) in Escherichia coli. Two enzymes were cofactor-swapped in that build, not one. The outcome does not transfer to yeast: NADH-preferring KARI variants in S. cerevisiae did not outperform the wild-type NADPH-dependent enzyme, and in a head-to-head comparison the larger lever was pathway localization.

### BM-COF-005

**old** > Matrix NADPH supply under production conditions is not quantified, and is an open gap for any configuration that runs the KARI step in the mitochondrial matrix.

**new** > The enzymes supplying mitochondrial-matrix NADPH in S. cerevisiae are qualitatively known - Pos5, Ald4/Ald5, Idp1 and Mae1, with Pos5 regarded as the main source - but no compartment-resolved matrix NADPH concentration, NADPH/NADP+ ratio or supply flux under fermentative or production conditions is recorded anywhere in the consulted corpus. The quantity, not the identity of the sources, is the open gap, and it is an open gap for any configuration that runs the KARI step in the mitochondrial matrix.

### BM-CMP-002

**old** > Deletion of PDC1 reduces ethanol formation, and deletion of all three PDC isozymes abolishes fermentative ethanol production and produces a strain that cannot grow on glucose as sole carbon source without a C2 supplement.

**new** > Deletion of PDC1 alone has only a minor effect on ethanol formation, because PDC5 is derepressed in its absence - 12.6 g/L against 13 g/L for the wild type in one own-result measurement. Deleting PDC1 together with PDC5 is what abolishes fermentative ethanol production (0.01 g/L), PDC6 not normally being expressed on glucose. Pdc-negative strains cannot grow on high glucose concentrations and require a C2 compound - ethanol or acetate - for growth at low glucose.

### BM-CMP-004

**old** > The branched-chain aminotransferases Bat1 and Bat2 drain 2-ketoisovalerate to valine, and they differ in compartment - Bat1 mitochondrial, Bat2 cytosolic - so deleting one is not equivalent to deleting the other.

**new** > The branched-chain aminotransferases Bat1 and Bat2 catalyse the reaction between 2-ketoisovalerate and valine and differ in compartment - Bat1 in the mitochondrial matrix, Bat2 in the cytosol - so deleting one is not equivalent to deleting the other. The compartment difference is attested in the consulted corpus only as background statement, never as anyone's own localization experiment. The measured deletion consequence is known for BAT1 and is background-dependent: deleting BAT1 raised isobutanol 2.5-fold in one strain and was reported harmful in another.

### BM-MIT-002

**old** > In translation table 3 the entire CUN codon family reads as threonine rather than leucine, which is the most dangerous difference for anyone moving a gene into mtDNA because a leucine-rich sequence mistranslates extensively while still looking like a sensible gene.

**new** > In the S. cerevisiae mitochondrial genetic code (NCBI translation table 3) the CUN codon family reads as threonine rather than leucine, decoded by an abnormal tRNA-Thr with an 8-nucleotide anticodon loop that S. cerevisiae carries and some other yeasts lack. A leucine-rich sequence moved into mtDNA therefore mistranslates extensively while still reading as a sensible gene - that consequence is an inference from the reassignment, not a statement any consulted source makes.

### BM-MIT-003

**old** > In translation table 3 the codon AUA reads as methionine rather than isoleucine.

**new** > In the S. cerevisiae mitochondrial genetic code (NCBI translation table 3) the codon AUA reads as methionine rather than isoleucine. The consulted corpus establishes that table 3 is the yeast mitochondrial code, originally based on S. cerevisiae, and that AUA is one of the two codons it reassigns relative to the fungal code (table 4) - but no consulted source states the destination amino acid, so the methionine assignment is reachable only from the NCBI genetic-codes page named in source_hint. The same source notes that in many Saccharomycetales the AUA reassignment is not supported and the tRNA required for it is absent, which makes this the shakiest leg of table 3.

### BM-MIT-005

**old** > The recoded ARG8m marker, inserted at the COX3 or COX2 locus and driven by that gene's 5' leader, is the established precedent for expressing a soluble matrix enzyme from mtDNA in yeast, and it is therefore the correct feasibility anchor for any proposal to encode a pathway enzyme in the mitochondrial genome.

**new** > The recoded ARG8m marker, inserted in place of a resident mitochondrial ORF and translated under that gene's untranslated regions, is the established precedent for expressing a soluble matrix enzyme from mtDNA in yeast, and is therefore the correct feasibility anchor for any proposal to encode a pathway enzyme in the mitochondrial genome. The locus is not restricted to COX3 or COX2: ARG8m has been used at COX1, COX2, COX3, COB, VAR1, ATP6 and ATP9. Displacing the resident gene carries a respiration cost - a strain with ATP9 replaced by ARG8m grows on glucose without arginine but not on glycerol.

### BM-MIT-006

**old** > There is no established CRISPR-Cas route for editing yeast mtDNA, because import of guide RNA into the matrix is unsolved; the established routes are biolistic transformation into a rho-zero recipient, and nuclease-based heteroplasmy shifting, which deletes rather than inserts.

**new** > As of 2020 a CRISPR-Cas route for editing yeast mtDNA has been demonstrated: donor DNA was inserted at Cas9/gRNA-induced target sites in S. cerevisiae mitochondria, with Cas9 and the guides expressed from a plasmid delivered biolistically into the organelle rather than imported across the inner membrane. Import of guide RNA and donor DNA into the matrix remains unsolved and editing efficiency remains insufficient as of a 2023 review, so the route is demonstrated but not routine. The long-established insertion route is biolistic transformation into a rho-zero recipient. No yeast mitoTALEN or mitoZFN result is held in this corpus - the only mitoTALEN source is about plant mitochondria - so this entry asserts nothing about what those techniques do in S. cerevisiae.

### BM-ETH-001

**old** > The theoretical mass yield of ethanol from glucose is 0.511 g/g, and every reported ethanol yield in the atlas is expressible as a fraction of it.

**new** > The theoretical mass yield of ethanol from glucose is 0.511 g/g (2 x 46.07 / 180.156 = 0.51142) and the substrate must be stored with it. Most of the consulted literature rounds to 0.51 g/g, and a substantial number of papers apply that same 0.51 g/g figure to XYLOSE rather than glucose, so the number alone does not identify the substrate. That every reported ethanol yield in the atlas is expressible as a fraction of this ceiling is a property of the atlas's own unit handling, not a claim any paper makes, and is tested against stored rows rather than looked up.

### BM-ETH-002

**old** > The theoretical mass yield of isobutanol from glucose is 0.411 g/g, materially lower than the ethanol ceiling, so isobutanol and ethanol yields are never comparable as raw g/g.

**new** > The theoretical mass yield of isobutanol from glucose is 0.411 g/g (74.12 / 180.156 = 0.41142), materially lower than the ethanol ceiling of 0.511 g/g, so isobutanol and ethanol yields are never comparable as raw g/g. The consulted literature almost always rounds this to 0.41 g/g; the one source giving three significant figures writes 410 mg/g for glucose and 411 mg/g for xylose, which is a rounding difference and NOT a substrate difference - the isobutanol mass yield from xylose (5 isobutanol per 6 xylose) is 0.41142 g/g, the same number to five places, because the carbon balance per carbon is identical.

### BM-ETH-003

**old** > Wild-type S. cerevisiae under anaerobic glucose fermentation reaches ethanol yields in the region of 90 percent of theoretical, with the remainder going substantially to biomass, glycerol and CO2 - a baseline against which any isobutanol yield should be read.

**new** > Wild-type S. cerevisiae anaerobic ethanol yield is not one number and is not a constant. Industrial first-generation processes are reported above 90 percent of theoretical - 92 percent for Brazilian sugar-cane ethanol against a 0.51 g/g hexose basis - while a laboratory reference strain in anaerobic sugar-limited chemostat at D = 0.05 h-1 gives 1.56 mol ethanol per mol sugar, which is 78 percent of the 2 mol/mol ceiling. The yield rises as specific growth rate falls and approaches theoretical only at near-zero growth rate, so a stored row is unusable without its dilution rate or specific growth rate alongside its basis. The remainder goes to biomass, CO2 and by-products, glycerol taking up to 4 percent of the substrate in industrial processes.

### BM-TOL-001

**old** > Isobutanol is substantially more growth-inhibitory than ethanol on a molar basis.

**new** > Isobutanol is substantially more growth-inhibitory than ethanol on a molar basis - isobutanol inhibits S. cerevisiae growth above roughly 190 mM, against roughly 40 g/L (roughly 870 mM) of ethanol for 50 percent growth inhibition. The DIRECTION is supported; the matched comparison is not. No consulted source measures both alcohols in one strain background under one assay, so those two figures come from different papers, strains, media and protocols - and by this entry's own expected outcome such a pairing is what the atlas must refuse rather than return.

### BM-TOL-002

**old** > Isobutanol tolerance is reported through at least five non-interconvertible assay types - maximum specific growth rate at a stated concentration, viability after acute shock, IC50 or MIC, lag-phase extension, and long-term adapted growth - and values from different assay types may not be aggregated.

**new** > Isobutanol tolerance is reported through several non-interconvertible assay types and values from different assay types may not be aggregated. Five are attested for S. cerevisiae in the consulted corpus: growth or OD600 at a stated concentration, viability or survival after exposure, colony size on solid medium, recovery or lag-phase extension, and long-term adapted growth after laboratory evolution. IC50 and MIC are NOT attested for isobutanol in S. cerevisiae there - MIC appears only in a bacterial paper - and that emptiness is a finding about the literature, not a gap in the search. Non-interconvertibility is demonstrated rather than asserted: in one paper two assay types invert the strain ranking.

### BM-TOL-003

**old** > A tolerance mechanism demonstrated for ethanol is, for isobutanol, a hypothesis and not a finding, and must be capped at evidence level L3 unless directly demonstrated for isobutanol.

**new** > A tolerance mechanism demonstrated for ethanol is, for isobutanol, a hypothesis and not a finding, and must be capped at evidence level L3 unless directly demonstrated for isobutanol. The cap is project policy, not a literature finding. What the literature supplies is the reason for it - longer-chain alcohol cytotoxicity is reported to be unlike ethanol cytotoxicity - and a case in which the 'unless' clause is load-bearing: a tryptophan/membrane mechanism reasoned from the ethanol literature and then demonstrated directly for isobutanol in S. cerevisiae, which an automatic cap keyed on 'the origin was ethanol' would under-rate. transfer_rationale must therefore record whether a direct isobutanol demonstration was sought and found, not merely that the mechanism originated in the ethanol literature.

---

## 7. What a curator still owes this file

In the order that unblocks the most:

1. **Decide the `evidence` / `confidence` coupling** (§5). Nothing else can land until the
   three-state question is answered, because the candidate fails the current test by design.
2. **Read the 17 `supported` entries' quotes and flip `verified`.** Every one carries its DOI and
   its offsets; re-resolution is mechanical.
3. **Split the compound rows.** BM-MIT-006 above all, but BM-CMP-002, BM-PATH-006 and BM-TOL-003
   were each several claims wearing one verdict. The narrowed statements make the seams visible;
   splitting them means retiring ids and minting new ones, which only a curator may do.
4. **Write the BM-NEG-006 unit test** (§4). It is not a row to be verified.
5. **Acquire the sources the corpus structurally cannot supply**, or lower the expected level:
   SGD systematic names and GO evidence codes, KEGG/MetaCyc map ids, the NCBI genetic-codes page
   (cited by three mitochondrial entries and load-bearing for BM-MIT-003), Bakker et al. 2001,
   Herzig/Bricker 2012 (load-bearing for BM-PATH-011's L2), Steele/Fox 1996, Hazelwood 2008, and
   the three BM-NEG-004 papers. These are not gaps in the search; they are entries whose stated
   evidence level is not reachable from these 1,309 papers.
6. **Run the Google Scholar half of BM-NEG-003's recorded search.**
