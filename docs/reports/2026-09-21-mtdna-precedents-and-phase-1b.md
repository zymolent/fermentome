# The last two activators, the precedent that was not thin, and phase 1b's verdict

2026-09-21, unattended, following the plan in `2026-09-21-handover.md`. No acquisition, no
extraction, no new proposals. Everything below was read out of the 1,310 full texts already
stored, and every quote was re-resolved in its source before it was written down.

**Phase 1b does not pass.** Both of its mitochondrial clauses now do — that is the work of this
session — but the criterion has five clauses and the first one fails outright for reasons that
have nothing to do with mitochondria. Section 4 states it plainly.

---

## 0. Method, and the one document that could not be read

Every stored full text was decoded once through `extract.harness.load_source_text` — the same
function `verify_span` reads — into a flat cache, then searched by regex. **1,309 of 1,310
decoded.** The one that did not:

```
doi:10.2323/jgam.2022.05.001 — AES-encrypted PDF; pypdf needs cryptography>=3.1
```

Every quote in this report and in the two data files was then re-resolved through
`verify_span` at the offsets the source text itself reports. **45 quotes, 45 passes** — after one
correction, which is the interesting part and is in §5.

---

## 1. ATP8 and VAR1 — the map is 8 of 8, and it was never a gap in the literature

`MITOCHONDRIAL_PROGRAM.md` §2.1 tabulates six loci and stops. The handover read that as two
missing rows. It is better than that: §2.1 was a faithful snapshot of a field that had since
moved, and **both papers that moved it were already in this corpus, unread.**

The 2017 ATP8 paper opens by stating the gap §2.1 inherited:

> "Translational activators have been identified for every mitochondrial gene product except
> Atp8p and Var1p"
> — `10.1091/mbc.e16-11-0775`

and then closes half of it. The other half closed in 2020.

| locus | activator | source | what it cost to find |
|---|---|---|---|
| **ATP8** | **Aep3** | `10.1091/mbc.e16-11-0775` (2017) | a paper whose *title* is "Aep3p-dependent translation of yeast mitochondrial ATP8" |
| **VAR1** | **Sov1** | `10.1093/nar/gkaa424` (2020) | a paper whose *title* names Sov1 "the translational activator" |

Neither required inference. The ATP8 evidence distinguishes translation from stability
experimentally — "The results of the two approaches provide strong evidence that Aep3p is required
specifically for translation of ATP8" — and Sov1 is literally named for the job: "renamed Sov1 for
Synthesis of Var1".

### ATP6 was never unverified either

v1 of the map recorded Atp22 → ATP6 as `unverified`, with the honest note that it had not been
found in the corpus. It was in the corpus, in the ATP8 paper, which is not where a search for
ATP6 would look:

> "This is supported by the finding that mutations in the ATP6 mRNA activator Atp22p prevent
> translation of Atp6p but not Atp8p"

That single sentence does two jobs: it names ATP6's activator, and it establishes that ATP6 and
ATP8 are separately activated *despite sharing a transcript* — which is what entitles ATP8 to its
own row rather than a footnote on ATP6's.

`activator_map.yaml` is now **version 2, nine rows**: all eight protein-coding loci, every one
quoted from a held paper, plus a ninth that is not a gene at all.

---

## 2. The correction that matters more than the two new rows

> **§2.1: "inserting a gene costs you the gene whose UTR you borrowed, unless the displaced gene
> is re-provided."**
>
> That is true of the ARG8ᵐ replacement route. It is not true in general, and the atlas had been
> reasoning as though it were.

The Fox lab's `pPT24` plasmid adds a recoded ORF **as an extra gene in a silent region upstream of
COX2**, borrowing COX2's leader and Pet111 without touching the authentic COX2:

> "A unique EcoRI site was engineered into the silent region upstream of the COX2 locus, into which
> the reporter gene can be integrated."
> — `10.1016/j.xpro.2022.101359`

Built independently and respiration-*measured* rather than assumed:

> "To avoid the respiratory deficiency associated with inactivation of mitochondrial genes, we
> engineered a new mitochondrial genome that coded for sfGFP as an additional ninth open reading
> frame." … "expression of sfGFPm does not alter the assembly of respiratory complexes or the
> general respiratory competence of the cells."
> — `10.15698/mic2018.03.621`

The authentic COX2 riding along on the same plasmid doubles as the **selection**: recombination
into a `cox2-62` recipient restores respiration, scored by growth on glycerol. The marker costs
nothing because the marker is the gene you did not remove.

**Why this is load-bearing here.** The owner's M3 answer makes respiration preferred for the
production strain, and `metabolic/chassis.py` gates strategy E on it. That gate was written when
every insertion site in the atlas carried `respiration_retained: false`. One of them no longer
does. **The gate should be re-read against the new row** — I have not touched it, because changing
a ranker gate is the same class of design decision as the ranker question the handover left open.

There is a caveat and it is recorded: the neutral site borrows an *OXPHOS* leader, so it is free of
displacement cost but not free of the targeting cost in §3.

---

## 3. §2.3 — the precedent is not thin

The question, in the programme's own words: *"Has any soluble heterologous enzyme of this class
been made from mtDNA?"*, with the framing *"the size of the gap is the size of the risk."* §2.3
expected one precedent, Arg8ᵐ, and warned that it is a yeast protein that natively lives in the
matrix.

**The corpus holds five, and one of them is a catalytically assayed enzyme.** Full table with
verified quotes in `data/mitochondria/heterologous_orf_precedents.yaml`.

| what | origin | soluble | heterologous | locus | respiration | readout |
|---|---|---|---|---|---|---|
| **nanoluciferase** | engineered shrimp luciferase | yes | **yes** | silent, upstream COX2 | **retained** | **catalytic activity** |
| superfolder GFP | *Aequorea* GFP variant | yes | yes | silent, upstream COX2 | retained | fluorescence |
| GFPβ1-10 | *Aequorea* GFP, 10 strands | yes | yes | ATP6 | retained, via ATP6 moved to COX2 | reconstitution |
| ARG8ᵐ | recoded yeast *ARG8* | yes | no | COX1/2/3, COB, ATP6, ATP8, VAR1 | lost | growth −Arg |
| ATP6–mNeonGreen / –mKate2 | engineered FPs | no | yes | ATP6 | unknown | fluorescence |

Nanoluciferase is the one that answers §2.3's question:

> "we integrated a recoded version of nanoluciferase (mtnLuc) into mtDNA. Expression of mtnLuc
> does not perturb mitochondrial function" … "With a readout at around 2 × 105 of relative
> luminescent units (RLU) in the strain expressing mtnLuc and around 102 of RLU in the wild type
> strain"
> — `10.1016/j.xpro.2022.101359`

A ~2,000-fold catalytic signal from an enzyme folded in the matrix, translated from a message the
matrix's own ribosomes read.

### The failure, which is worth more than the successes

> "a gene encoding fluorescence-enhanced GFP was inserted into the mitochondrial genome to replace
> the open reading frame of COX3 . The resulting strain was respiration deficient and expressed
> only weak fluorescence" … "This limitation could be explained by **poor folding of GFP expressed
> in the context of the mitochondrial translation system , which is specialized on the production
> of membrane proteins**."
> — `10.15698/mic2018.03.621`

This is §2.3's fear, observed, with a mechanism attached — and the mechanism generalises to a
ketoacid decarboxylase exactly as well as to GFP. It also says what to do: the fix was **a
fast-folding variant of the same protein** ("we employed superfolder GFP … which folds with
enhanced kinetics"). For DUET that argues for screening KDC and ADH orthologues on folding
kinetics and stability, not only on kcat. **The programme does not currently have that selection
criterion.**

### The leader decides where a soluble protein is made

The most directly useful result of the whole search, and nobody was looking for it. One paper
varies the *leader* while holding the soluble cargo constant — Arg8ᵐ behind COB, COX1, COX2 and
VAR1:

> "the loss of Dpc29 … reduced ARG8m reporter protein steady-state levels for all the
> mitochondrial-encoded genes assayed **except VAR1**" … "the OXPHOS 5′ and 3′ sequences (COB,
> COX1 and COX2) target the ARG8m mRNA to locations where hydrophobic respiratory chain proteins …
> are directed toward the mitochondrial inner membrane" … "synthesis of the soluble mitochondrial
> matrix protein Arg8 toward the inner membrane at these locations may result in steric hindrance"
> … "Var1-expressing mitoribosomes are thought to translate at distinct mitoribosome assembly
> sites that direct their products to the matrix"
> — `10.1093/nar/gkac1229`

A borrowed leader does not only license translation. **It decides where the nascent chain
emerges.** VAR1 is the only yeast mtDNA gene whose own product is soluble and whose ribosomes are
matrix-directed — which makes the VAR1 leader the mechanistically indicated choice for a soluble
heterologous enzyme, and this is knowable only because VAR1 entered the map today. It is a
hypothesis, not a settled answer: untested for a heterologous enzyme, and the VAR1 locus costs
Var1 (rescuable — allotopic VAR1 is documented in two corpus papers).

### Where the risk actually sits now

Every precedent above is **monomeric and cofactor-free**. Not one requires a diffusible cofactor
loaded or an oligomer assembled in the matrix. DUET's KDC is TPP-dependent and homotetrameric; its
ADH is typically Zn-dependent and oligomeric. Searching all 1,309 readable texts for TPP or
thiamine in a mitochondrial-matrix context returns nothing bearing on an mtDNA-encoded protein.

So the gap moved, and got sharper:

> ~~Can the matrix fold a soluble heterologous protein at all?~~ — answered, yes, repeatedly.
> **Can the matrix load a cofactor into, and oligomerise, a protein its own ribosomes just made?**

That is a cheaper question than the one §2.3 posed, and a more answerable one.

**BM-NEG-003 still holds.** Nothing in this corpus puts an isobutanol-pathway enzyme in mtDNA; the
negative control the benchmark set exists to protect is intact.

---

## 4. Phase 1b — plainly, it does not pass

PLAN.md's criterion has five clauses. Taking them in order, against the database as it stands:

| # | clause | verdict |
|---|---|---|
| 1 | the landmark *E. coli* and *S. cerevisiae* builds each reproduce their paper's titer, yield and conditions | **FAILS** |
| 2 | every configuration passes the 0.411 g/g bound check or is flagged | **vacuous** |
| 3 | every localization claim carries a verification method or `none_reported` | **vacuous** |
| 4 | the activator map covers every mtDNA locus that could host an insert, with its leader and what inserting there displaces | **PASSES** (today) |
| 5 | the precedents table for soluble heterologous enzymes from mtDNA is complete, however thin | **PASSES** (today) |

**Clause 1 fails and it is not close.** Atsumi 2008 (`nature06450`) and Avalos 2013 (`nbt.2509`)
are both stored and — since last session's pypdf fix — both readable. Neither has been extracted.
`extraction` holds 7 rows across 5 other papers. `pathway_configuration` is 0, `measurement` is 0,
`condition_context` is 0. There are no titers in this atlas at all, so nothing reproduces anything.

**Clauses 2 and 3 are vacuous, not satisfied.** Zero configurations and zero localization records
pass trivially. Worse for clause 2, the 0.411 g/g bound it would check against is itself stored
`confidence: unverified`, citing only PLAN.md — an internal document. A check that has nothing to
check, against a number that cites us.

**Clauses 4 and 5 genuinely pass, and did not this morning.** Clause 4 was 6 of 8 loci with one of
those unverified; it is now 9 rows, all quoted. Clause 5 had no table; it now has one.

One honest qualification on clause 5's word *complete*: complete against **this corpus**, not
against the literature. The precedents file records the AES-encrypted PDF, and the search was
regex over stored text, not a fresh literature sweep.

### The shape of the failure is worth naming

Phase 1b's acceptance criterion borrows phase 1's landmark-build requirement, and **phase 1 has
not started.** The handover's "nearly 1b" was measuring the mitochondrial half and calling it the
whole. The mitochondrial half is now done; phase 1b is gated on the isobutanol half, which is
gated on curation, which is gated on a human. Nothing unattended can move it.

### Two things found while checking, which are not clause failures but are wrong

* **`knowledge_gap` has no `never_attempted` rows.** 88 `quantitative_value_missing` + 120
  `transport_carrier_unknown` = 208, and that is all. §2.3 says "The atlas records this as a
  `knowledge_gap` of kind `never_attempted`, with the Arg8ᵐ precedent attached." It does not. The
  kind is legal in the schema and unused. This is the handover's "recorded and never wired up"
  failure mode, instance six.
* **BM-MIT-004 still cannot be answered by the atlas.** Its `query_shape` is a join over
  `mtdna_insertion`, which has 0 rows. The knowledge is now in the repo as curated YAML; the
  *query layer* cannot reach it, because nothing loads `activator_map.yaml` into the database —
  grep finds no reader for that file anywhere in `src/`. Clause 4 says "the activator map covers",
  and on the letter of it the map does. It is worth knowing that a curator asking the atlas would
  still get nothing.

---

## 5. The span that failed, and why the check earns its keep

Twenty-four draft quotes went into the §2.3 verification pass and twenty-three resolved. The one
that failed was a sentence about the ρ⁰ *kar1-1* recipient in `10.1016/bs.mie.2024.07.028`. Two
causes, both invisible when reading:

1. the PDF text layer wraps with one trailing space where the draft had two;
2. **the PDF renders ρ as `U+F072`** — a private-use-area glyph, not the Greek letter.

The quote was corrected to what the source actually says. The check was not loosened. A
corpus-wide sweep found PUA glyphs in **8 of 1,309 documents** — small, except that in this paper
it hits ρ specifically, which is the one symbol this programme cannot afford to mis-search. A
future search for `ρ⁰` across PDF-sourced texts will silently miss those documents.

---

## 6. What changed on disk

* `data/mitochondria/activator_map.yaml` — v1 → **v2**. ATP8 (Aep3) and VAR1 (Sov1) added; ATP6
  upgraded `unverified` → `medium`; `intergenic_upstream_COX2` added as a non-displacing site;
  header and open-questions footer rewritten.
* `data/mitochondria/heterologous_orf_precedents.yaml` — **new.** 5 precedents, 1 documented
  failure, the leader-targeting result, 3 open gaps, every quote verified.
* This report.

Nothing was written to the database. The 95 proposals are still 95, still pending, still reviewed
by nobody — and that, not the mitochondrial corpus, is what phase 1b is waiting on.

`pytest` 948 passed; `ruff` and `mypy` clean. The gate was read from `${PIPESTATUS[0]}`, not from
the tail of the pipe.

---

## 7. Still yours, unchanged

Everything the handover left open, plus one new item:

* **Re-read `metabolic/chassis.py`'s strategy-E respiration gate** against the non-displacing
  insertion site (§2). It was written when displacement looked unavoidable.
* The ranker's per-strategy feasibility constants — the handover's finding, untouched.
* The two curation decisions, the 22.4 GB of excluded `.sra` objects, ploidy.
* And the one that dominates all of them: **95 proposals, nobody has reviewed any.**
