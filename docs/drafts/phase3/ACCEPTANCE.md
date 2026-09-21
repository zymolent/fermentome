# Phase 3 acceptance — what passes, what fails, what cannot yet be evaluated

**Status as of 2026-09-21.** Phase 3 was built and had never been run against its acceptance
criteria, because the first clause had no data to run against. It does now — barely — and this is
what each clause actually does.

PLAN.md Q, phase 3:

> *Acceptance:* the enumerator re-discovers every published configuration (recall test against
> phase 1); routes violating **per-compartment** redox balance are excluded with the imbalance
> named; at least one enumerated-but-never-built route survives inspection as scientifically
> defensible; every rank is explainable term by term; strategy E routes are ranked as *reachable
> but costly* rather than either dropped or flattered, and each names its locus, leader, displaced
> gene and recoding requirement.

Five clauses. **Four pass, one is not a software test at all.** C1 was the one that did not, and
the thing that unblocked it was a matching-rule ruling rather than a curation edit — see below.

**Updated 2026-09-22 — C2.** C2 was failing because the gate was never built and could not be
built without decision **D1**. The owner settled D1 on 2026-09-22 — *flag, don't exclude* — and
the per-compartment balance is now computed, flagged and named, with nothing excluded for a redox
reason. See the C2 section and the D1 entry.

**Updated 2026-09-22 — C2, a second time.** The owner ruled that the enumerator gains an
**optional `cofactor_cycle` step role**, so `POS5`, `ADH3` and `GPD` can be parts a route carries.
The tally is now **0 balanced / 4,800 unbalanced / 1,600 unknown** over 6,400 routes. Nothing
balances, for a new and sharper reason, and **240 routes close the mitochondrial matrix
completely** — the first compartment the atlas has ever reported as closing, and it is DUET. See
"the optional `cofactor_cycle` role" and "What the run says" in C2.

**Updated 2026-09-22 — C1.** The owner settled **D5** the same day: a role name *qualified by a
source organism* is a real enzyme identification where the catalog holds exactly one part for that
`(step_role, source_organism)` pair, and an ambiguous refusal where it holds more. Recall is now
**100% on the judgeable set, 2/2, coverage 50%** — and **both matches rest on that weaker
identification**, which the report says on its own line rather than leaving to be inferred.

| # | Clause | Verdict | What it needs |
|---|---|---|---|
| C1 | Recall against phase 1 | **PASSES, as of 2026-09-22 — 100%, 2/2 judgeable, coverage 50%.** Both matches are *resolved-by-source-organism*, the weaker of the two identifications the rule allows, and are counted apart | Nothing in code. More rows: a denominator of 2 is not a trend, and `coverage` is 50% |
| C2 | Per-compartment redox balance, imbalance named | **PASSES**, as of 2026-09-22, under the owner's amended clause. Tally over 6,400 routes: **0 balanced / 4,800 unbalanced / 1,600 unknown**, with the matrix closing on 240 of them | Nothing in code for the clause. PLAN.md's wording still says *excluded*; the proposed amendment is at the foot of this section and is the owner's to apply. To reach a *balanced* route: either curated stoichiometric multiplicity (a part used more than once) or a cytosolic NADH-regenerating part — both curation, not code |
| C3 | ≥1 enumerated-but-never-built route is scientifically defensible | **NOT A TEST** | A human reads a route card and says so. Effectively blocked behind C1: "never built" is the complement of the matched configurations, and that complement is currently all 600 routes |
| C4 | Every rank explainable term by term | **PASSES**, as of this change | Nothing. It did not pass before: `rank`'s fourth key was invisible to `explain` |
| C5 | Strategy E reachable-but-costly, naming locus / leader / displaced gene / recoding | **PASSES** | Nothing |

---

## C1 — recall. Ran for the first time today, failed twice, and now passes

**This section was written as "cannot be evaluated" and had to be rewritten mid-session.** When
this work started `pathway_configuration` held **0 rows**, and the honest answer was that the
clause had no denominator — not 0% (which would say the enumerator failed) and not 100% (which
would say it succeeded). `RecallReport.recall` still returns `None` in that state, for exactly the
reason `score_evidence` is NULL on all 600 routes: absence is not zero.

Then the first four configurations were promoted. The clause is now answerable, and the answer is
**0%**:

```
$ fermdb atlas recall
4 published configuration(s) against 600 enumerated routes

  recall                0%   0/2 of the configurations that CAN be judged
  coverage             50%   2/4 could be judged at all
  partial              50%   every NAMED step agreed — NOT recall, and never to be quoted as it

MISSED — the enumerator cannot express these builds:
  YAA:PCFG:6e7102e064ead4e7  C_mitochondrial_ehrlich ... doi:10.1016/j.cels.2019.10.006
      [catalog_gap] unfilled: KDC, ADH; no part carries: 'ADH7'
  YAA:PCFG:fbe93c86372bc5bb  A_native_split ... doi:10.1016/j.cels.2019.10.006
      [catalog_gap] unfilled: KDC, ADH; no part carries: 'ADH7'

not evaluable — neither a hit nor a miss, and named rather than dropped:
  YAA:PCFG:13a7bd4eac19633f  ... [under_specified] unfilled: AHAS, KARI, DHAD
  YAA:PCFG:5f5ffbe5f654332e  ... [under_specified] unfilled: AHAS, KARI, DHAD;
                                  named only by role: 'ILV genes'

enzymes named by published builds that no part in the catalog carries:
  'ADH7'
```

**The whole of the failure is one missing part.** Both misses are the same paper's build, and both
fail for the same reason: it used **Adh7**, and `parts_catalog.yaml` carries Adh1, Adh6 and the
Lactococcus AdhA but not Adh7. The clause will not pass until the catalog contains the enzymes
the literature used, and this is the shortest possible statement of what to do about it.

> **AMENDED 2026-09-22.** That diagnosis was tested by acting on it, and it was **not the whole of
> the failure** — it was the first half. `adh7_native` is now in the catalog, read from the stored
> full text of the same paper rather than from background knowledge. The `ADH7` worklist line is
> gone and both configurations stopped being misses. Neither became a match. See below.

Two caveats on reading 0%, both of them in the direction of "it is early", not "it is worse than
it looks":

* the denominator is **2**. Four configurations, two judgeable. One figure is not a trend.
* the other two are under-specified, not wrong. Both are the same paper naming `"ARO10"` and
  `"LlAdhA RE1"` and leaving the upstream ILV enzymes as `"ILV genes"`. `partial` is 50% because
  every step those records *did* name matched an enumerated route. That number is real and it is
  not recall.

### 2026-09-22 — the Adh7 part was curated, and the blocker moved rather than cleared

`adh7_native` is now in `data/pathways/parts_catalog.yaml`, written by loading the stored full
text of `doi:10.1016/j.cels.2019.10.006` and quoting it. It is the first entry in that file that
cites a source, so it carries `confidence: medium` where everything around it is `unverified`, and
the two fields the paper is silent about — `cofactor_preference`, `oxygen_sensitivity` — are
`unknown` rather than completed from background knowledge.

What that bought, exactly:

```
$ fermdb atlas recall
4 published configuration(s) against 800 enumerated routes

  recall    not measurable   0/0 of the configurations that CAN be judged
  coverage              0%   0/4 could be judged at all
  partial             100%   every NAMED step agreed — NOT recall, and never to be quoted as it

not evaluable:
  YAA:PCFG:6e7102e064ead4e7  ... [under_specified] unfilled: KDC;
      named only by role: '2-ketoacid decarboxylase (KDC) from Lactococcus lactis'
  YAA:PCFG:fbe93c86372bc5bb  ... [under_specified] unfilled: KDC;  (same)
```

**The ADH7 line is gone from the worklist and no enzyme has replaced it.** Both cels-2019
configurations moved `catalog_gap → under_specified`, which is `missed → not evaluable`. Read the
three numbers together rather than the first one: recall went from `0%` to `not measurable`, which
is not a regression but the loss of a denominator — the two configurations that were judgeable were
judgeable only because they were *wrong*. `partial` went 50% → 100%: every step those four records
name now agrees with an enumerated route.

**The remaining blocker is not a catalog gap, and this is the actionable part.** Both records name
their decarboxylase as `"2-ketoacid decarboxylase (KDC) from Lactococcus lactis"` — a role name,
which the rule correctly refuses to treat as an enzyme identification. But the paper's Methods name
the protein: *"an a-ketoacid decarboxylase (KDC) from Lactococcus lactis (**LlKivD**)"*. The
extraction took the Results phrasing; the Methods phrasing is already resolvable, because
`ENZYME_ALIASES` maps `llkivd → kivD` and `kivd_lactococcus` is in the catalog. Verified by
classifying the same two configurations with `LlKivD` substituted into the enzyme list:

```
A_native_split           -> matched   (1 route agrees)
C_mitochondrial_ehrlich  -> matched   (1 route agrees)
```

So C1 reaches **2/2 = 100% recall on the judgeable set, coverage 50%** the moment a curator
corrects those two `pathway_configuration` descriptions. That is a curation act on Zone R rows and
is the owner's, not an agent's — it is recorded here rather than done.

> **SUPERSEDED 2026-09-22.** The owner did not take that option. The Zone R descriptions stay as
> the papers were reported, and the **rule** changed instead — see the next section. The
> substitution above survives as what it always was: an independent check, run before the rule
> changed, of where the harness ought to land. It landed there, on the same part
> (`kivd_lactococcus`) and the same two route ids, by a different route.

The general lesson is worth keeping, because it will recur: *"the enumerator cannot express this
build"* and *"the record does not say what the build was"* are different failures that a single
recall percentage cannot tell apart. Only the first is a catalog gap. The first run's worklist had
one line and it looked like the whole story; it was one of two, and the second was invisible until
the first was fixed.

### 2026-09-22 — the owner's ruling on `ROLE from ORGANISM`, and C1 passing

> **A role name qualified by a source organism is a real identification, not a wildcard — but
> only when it is unambiguous.**
>
> Resolve `ROLE from ORGANISM` to a catalog part **when the catalog holds exactly one part for
> that `(step_role, source_organism)` pair.** Flag the match as **resolved-by-organism**, distinct
> from resolved-by-gene-symbol. If two or more parts share that pair, **refuse as ambiguous** — do
> not pick one.
>
> — the owner, 2026-09-22, settling **D5**

The blocker was never that the atlas lacked the enzyme. `kivd_lactococcus` has been in the catalog
all along; what the rule refused was the *phrase*, because `"KDC"` on its own is a step and not a
protein. The ruling says what the organism adds: `"2-ketoacid decarboxylase (KDC) from Lactococcus
lactis"` identifies a protein by where it was cloned from, the way the paper's own Methods do, and
the catalog can say which one — **as long as it can say which one**.

**The figure, before and after.** Same 800 routes, same four configurations, nothing in `data/`
touched and no `pathway_configuration` row edited:

```
                    before              after
  recall      not measurable   0/0     100%   2/2      <- of the configurations that CAN be judged
  coverage                0%   0/4      50%   2/4
  partial               100%            100%
  of which                 —            0 matched by gene symbol,
                                        2 by a role name plus a source organism (weaker)
```

```
$ fermdb atlas recall
matched:
  YAA:PCFG:6e7102e064ead4e7  C_mitochondrial_ehrlich ... doi:10.1016/j.cels.2019.10.006
      resolved BY SOURCE ORGANISM at KDC — a role name plus a source organism, uniquely in the
      catalog, not a gene symbol; 1 route agrees
      first route: C_mitochondrial_ehrlich:ilv2_ilv6_native+ilv5_native+ilv3_native+
                   kivd_lactococcus+adh7_native
  YAA:PCFG:fbe93c86372bc5bb  A_native_split ... (same, 1 route agrees)
```

**Read the second line of that breakdown before the first.** 100% here is *two* configurations,
and **both** of them rest on the weaker identification — the figure would be `0/2` by gene symbol
alone. That is why the match kind is on the headline block and on every matched line, and why
`RecallReport` exposes `matched_by_gene_symbol` and `matched_by_source_organism` as data rather
than only as prose: a caller that counts matches can count the two kinds apart, and a reader of
100% cannot miss what it is made of.

**Verified independently of the claim it supports.** The previous pass established, by
substituting `LlKivD` into the enzyme lists, that both configurations *ought* to reach 2/2. The new
rule arrives at the same place by a different road, and the check is that they agree on more than
the number: same clause (`matched`), same resolved part (`kivd_lactococcus`), same single route id
each. No discrepancy to report.

**The safeguard, which is the whole of why this is allowed.** Uniqueness is a fact about the
catalog *as it is now*, so it is recomputed from the parts passed in on every call and never
cached. Curate a second *Lactococcus lactis* KDC tomorrow and today's two matches become
`source_organism_ambiguous` refusals by themselves — `not_evaluable`, with both colliding part ids
named, because choosing between them is a curation claim about which enzyme the paper used and a
matcher is the last place that claim should be made silently.
`test_a_second_part_for_the_same_role_and_organism_turns_the_match_into_a_refusal` inserts exactly
that part and asserts exactly that flip, including that the refusal does not reappear as a match
through `recall_report`.

**What the ruling deliberately does not reach**, each falling through to the old
`under_specified`:

* a **bare** role name — `"KDC"`, `"ADH"`. No organism, so nothing for uniqueness to bite on; it
  would resolve to every KDC part, which is the wildcard that returns 100% on an empty record.
  This is the defence the change was most at risk of eroding and it is unchanged;
* a **gene family named as a block, even with an organism** — `"ILV genes from Saccharomyces
  cerevisiae"`. Three roles at once, each with exactly one native yeast part, so a role-by-role
  reading would fill all three off a record that named no protein. One role per phrase, or nothing;
* an organism that parses but matches **no** part of that role — `"KDC from Escherichia coli"`.
  Not resolved, and **not** asserted as a catalog gap either: a miss claimed on a parse is the
  wrong direction of error for a harness whose bias is pessimistic by design;
* anything the parser is **not sure of**. It accepts `Genus species`, the abbreviated `G. species`
  and either with a subspecies or strain suffix (`Lactococcus lactis subsp. lactis IFPL730`); a
  phrase with fewer than two words, or whose species epithet is not alphabetic, is not a binomial.
  The abbreviation `L. lactis` is genuinely weaker than the full genus — it is also *Leuconostoc
  lactis* — and that weakness is not patched over in the parser: it lands on the uniqueness test,
  which counts matching **parts**, so an abbreviation spanning two catalog genera produces two
  candidates and is refused.

**A gene symbol still wins.** The organism path is only reached by an entry that no gene symbol
recognised, so `"kivD"` resolves as it always did and is reported `gene_symbol`. A role that ends
up resolved both ways carries both kinds.

### What was built, so the clause stays answerable as the table fills

* `src/fermdb/metabolic/recall.py` — the harness, and `MATCHING_RULE`, which is the rule written
  down as data rather than buried in a comparison function. `fermdb atlas recall --rule` prints
  it clause by clause.
* `fermdb atlas recall` — the recall figure, the matched pairs, the unmatched configurations, and
  the list of enzymes published builds used that no part in the catalog carries.
* `tests/test_recall.py` — one test per rule clause plus the strictness properties. Every
  configuration in them is copied from a **real** `pathway_configurations` extraction payload
  sitting in `curation_task`, so the harness is tested against the vocabulary it actually meets,
  not against a tidy invention. `ADH7` was the catalog-gap exemplar in those tests until it became
  a catalog part; the slot now holds `ADH2`, the next real yeast alcohol dehydrogenase the catalog
  does not carry, and a new assertion checks that `ADH7` itself resolves exactly. The exemplar
  moves as the catalog fills, because the property under test is the *shape* — a name ending in a
  symbol the catalog has — and a filling catalog is precisely when a substring rule would start
  finding false matches.

### The matching rule, and why it is drawn where it is

A configuration and a route are written in different vocabularies. A configuration says
`"LlAdhA RE1"`, `"ILV genes"`, `"2-ketoacid decarboxylase (KDC) from Lactococcus lactis"`; a route
says `adha_lactococcus`. The rule has to bridge that without bridging too far.

Three axes, and only two of them are usable:

1. **Strategy** — exact id equality. `pathway_configuration.compartment_strategy_id` and
   `Route.strategy` draw on the same seeded `compartment_strategy` vocabulary, so this axis needs
   no interpretation at all.
2. **Enzyme set** — parsed out of `description`, which is where `curate/promote.py` puts it, and
   resolved to part ids by **exact, case-folded gene-symbol token equality** against `part.genes`,
   plus a small curated `ENZYME_ALIASES` table of named exceptions — or, since the 2026-09-22
   ruling, by a **role name qualified with a source organism**, where the catalog holds exactly
   one part for that `(step_role, source_organism)` pair. The two kinds are counted apart.
3. **Host** — `host_strain_id` resolves to an organism, but **`enumerate_routes` has no host axis**
   (see D2). So the host is used only to decide scope, never to match.

**Eight** clauses, applied in order, first one wins — seven until 2026-09-22.
`fermdb atlas recall --rule` prints the full text of each; the short version:

| clause | outcome | in one line |
|---|---|---|
| `strategy_not_enumerable` | not evaluable | strategy is NULL, `unknown` or `NA` — no route to compare against |
| `host_not_recorded` | not evaluable | no host, so the configuration cannot be placed in or out of scope |
| `host_outside_enumeration` | not evaluable | an *E. coli* build against a yeast-only enumeration |
| `no_enzyme_set_recorded` | not evaluable | the description has no `enzymes as reported:` segment |
| `matched` | **hit** | all five roles resolved — by gene symbol or by role-plus-organism, and it says which — and some route of that strategy agrees at all five |
| `catalog_gap` | **miss** | a role is unfilled *and* an enzyme was named that no part carries |
| `source_organism_ambiguous` | not evaluable | `ROLE from ORGANISM`, and the catalog holds two or more parts for that pair — refused, both named |
| `under_specified` | not evaluable | a role is unfilled and every named enzyme was recognised |

### Four decisions inside that rule that could each have gone the other way

**The prose beside the enzymes is never read.** `description` is
`"enzymes as reported: X, Y; localization as reported: <prose>"`. The harness reads only the first
segment. The prose is where the interesting failure lives: a real payload in this atlas says a
build works *by circumventing* Bat1p and Bat2p, and another names Cox4, a targeting leader and not
a pathway enzyme. A rule that scanned the whole description would credit builds with enzymes they
deliberately removed. Tested by
`test_the_localization_prose_is_never_mined_for_enzyme_names`.

**A bare role name is not an enzyme identification.** Real payloads name `"KDC"`, `"ADH"` and
`"ILV genes"`. Treating `"KDC"` as "any KDC part" is a wildcard, and a configuration naming
nothing would then match every route of its strategy and return 100% recall on an empty record.
Role names are recorded separately (`role_named_only`) and leave the role **unfilled**. Gene
families named as a block — `"ILV genes"`, the Ehrlich pathway — are in the same category and are
listed in `_ROLE_SYNONYMS`. Without that list, `"ILV genes"` is reported as a *catalog gap*, which
would put a non-existent part called "ILV genes" on the curation worklist; the worklist is only
worth reading if every line on it is actionable, and today it has no lines at all.

*Amended 2026-09-22, and the word that carries the amendment is **bare**.* A role name **plus a
source organism** is an identification, because the organism is what lets the catalog name one
protein — and it is allowed only while the catalog can name exactly one. Everything above stays
true of a role name on its own; see the ruling section for the three things the amendment
deliberately does not reach.

**Three of five is not re-discovery.** A route is five choices. A configuration that names three
of them and matches on all three has had two steps agreed and two never checked. That is reported
as `partial`, a number with its own name printed beside recall, and it is never called recall.
This is the single largest source of inflation available and it is closed by
`test_a_build_naming_three_of_five_enzymes_is_not_recall`.

**Never substring, never fuzzy.** `ADH7` is a real yeast alcohol dehydrogenase the catalog does
not carry; a substring rule would resolve it to Adh1 or Adh6 because both contain `ADH`.
`LlAdhA` is handled by a **named alias with its reason attached**, not by a "strip a genus prefix"
rule — a prefix rule is a substring match wearing a hat, and its first false positive would be
invisible. An unknown spelling stays unrecognised and surfaces in the report, where a curator can
see it.

### What the recall test actually measures, which is not what its name suggests

Enumeration is the **full cross product** of the parts catalog with the five strategies. An
enumerator that emits every combination cannot fail to emit a combination it can express. So C1 is
not a test of a search. It is a test of two coverage questions: does the parts catalog contain the
enzymes published builds used, and does `compartment_strategy` contain the arrangements they used.
Every miss the harness can report is one of those two, and it names which and quotes the enzyme.

That makes the output a curation worklist rather than a score, and that is the more useful thing
for it to be. The first real run bore this out exactly: recall 0%, and the entire explanation is
one line of worklist (`ADH7`). Expect that list to grow as the table fills — `yqhD`, the bacterial
BCKAD/ACD set — and expect most of it to be right.

### The bias is deliberately pessimistic

Where the record is ambiguous the harness reports a miss or refuses to judge, never a match. A
recall figure that is too high would license the claim "the atlas re-discovers the literature" on
evidence that does not support it. A figure that is too low costs a curator an afternoon.

One case is knowingly harsh: an unrecognised entry that is only a variant spelling of a role
already filled (`ILV6V90D/L91F` beside `ILV2`) is counted as a catalog gap. The verdict prints the
entry verbatim so a reader sees immediately that it is spelling and not substance.

### Ambiguity is reported, not resolved

Four KARI parts carry the gene symbol `ilvC` — `ilvc_ecoli`, `ilvc_nadh_variant`,
`ilvc6e6_ecoli`, `ilvc_p2d1a1_ecoli` — and they differ by **exactly the NADPH/NADH question the
whole atlas exists for**. Gene-symbol resolution cannot separate them. A match through `ilvC` is
therefore reported as *ambiguous at KARI*, and the harness does not pick. See D3.

### Running it, once the rows exist

```
fermdb atlas recall          # the figure, the matched pairs, the named misses
fermdb atlas recall --rule   # the matching rule, clause by clause — read this first
```

Read-only: it opens the database with `create=False` and writes nothing. It enumerates **without**
a chassis on purpose — a chassis gate excludes routes for *this* chassis, which is not a statement
about whether the enumerator can express somebody else's published build.

The figure in this document is a snapshot of a table that is actively filling. Re-run the command
rather than quoting the number here.

---

## C2 — per-compartment redox balance, imbalance named. **Passes**, as of 2026-09-22

### The ruling this was blocked on

> **Flag, don't exclude.** A route whose per-compartment redox balance does not close is
> **marked, with the imbalance named**, and **stays in the enumeration and in the ranking**.
> Nothing is dropped on an unchecked premise.
>
> — the owner, 2026-09-22, settling **D1**

PLAN.md's clause and G.7's gate table both said *excluded*; `routes.py` argued in the module
against excluding on `COFACTOR_POOLS`, which is unverified. Both had a point. The ruling takes the
module's conclusion (do not drop) and PLAN's requirement (name the imbalance) and keeps both. The
wording change PLAN.md needs is drafted at the end of this section — **not applied**, because that
file is the owner's.

### What is computed

`redox_balance(steps, pathway)` in `src/fermdb/metabolic/routes.py` sums the route's cofactor
stoichiometry **separately for each compartment** — PLAN.md B.6.4: a route split across membranes
must balance in each compartment separately, because the inner membrane does not pass NAD(P)(H).
Three pieces, from three places, and it matters which comes from where:

* the **magnitude and sign** come from the curated reaction: `reaction_participant.coefficient`
  and `metabolite.redox`/`metabolite.pair`. Nothing is invented. Only the *reduced* member of each
  couple is counted — every curated reaction already conserves its carriers (`check_balance`
  refuses to load one that does not), so counting NAD⁺ as well would make every reaction sum to
  zero and the check would be vacuous;
* the **compartment** comes from the route, not from the reaction. Relocalizing a step is the
  whole point of a compartment strategy, so `reaction.compartment_id` — where the enzyme natively
  sits — is deliberately not used;
* the **pool** comes from the part. This is the one inference the calculation makes and it is
  recorded by name, never applied silently. A curated reaction is written for one representative
  enzyme (`kari` for Ilv5, on NADPH; `adh_isobutanol` for the Adh1 type, on NADH) while the
  catalog carries NADH-preferring KARI variants and the NADPH-preferring Adh6 — which is exactly
  the variation the atlas exists to reason about. Where part and reaction disagree on the pool the
  coefficient is kept and the pool is taken from the part, and `RedoxBalance.substitutions` says
  so in words. **4,480 of 6,400 routes carry such a note**; a reader can see where every number
  came from.

### 2026-09-22, second amendment — the optional `cofactor_cycle` role

The tally below used to read **0 balanced / 600 unbalanced / 200 unknown**, and the reason nothing
balanced was named in this section as a *structural* one: the five roles in `STEP_ORDER` all
consume reducing power, none regenerates it, and there was no slot for a step that could. That is
also exactly what DUET is (`DUET_TARGET.md` §3): **Adh3** oxidises matrix ethanol to matrix NADH
and **Pos5** phosphorylates it to the matrix NADPH Ilv5 requires. So the atlas could not express
the redox closure the whole programme depends on.

The owner ruled on 2026-09-22: **add a `cofactor_cycle` step role, and make it optional.** It is
built.

**How optionality is expressed: a power set whose empty member is first and is a real value.**
`cofactor_cycle_sets(parts)` returns every subset of the cofactor-cycle parts, `()` first, and
`enumerate_routes` multiplies the five-step product by it. A route with no cofactor cycle is the
empty member — it goes through the same gates, the same ranking and the same storage as every
other route, and its id is unchanged because an empty set appends nothing. The 800 routes that
existed before are all still enumerated, with their ids, their gates and their relative order.

*Why a set and not a single nullable slot.* DUET is two genes in series. A one-part slot holds
Adh3 or Pos5 but not both, and would have left the exact gap this change exists to close.

**The alternative rejected: putting `cofactor_cycle` into `STEP_ORDER`.** That is the obvious
place for it and it would have broken C1. `metabolic/recall.py` reads `STEP_ORDER` as *the roles a
published configuration must fill before it can be called re-discovered* — `resolve_roles` seeds
one bucket per member and `classify` demands `not unfilled`. No paper's enzyme list names POS5; it
is a host gene, not a pathway enzyme. The role would therefore have been permanently unfilled and
**every published configuration would have become unmatchable**. Not hypothetical: the two
cels-2019 configurations match today, and both would have dropped to `under_specified`. The
optional role lives in a second tuple, `ROUTE_STEP_ROLES`, so the contract with the literature and
the contract with the enumerator stay separate. Verified: `fermdb atlas recall` classifies all
four configurations exactly as it did before (2 matched, 2 `under_specified`, recall 100% on 2/2,
coverage 50%), and the first route reported for each match is still the cycle-free one, because
`()` comes first.

**How the balance accounts for the new step.** A cofactor-cycle step contributes with **the sign
its curated reaction is written in** — no branch says "this one produces". `adh3_matrix` has NADH
as a product, so `+1` matrix NADH. `gpd_glycerol3p` has NADH as a *substrate*, so `-1` cytosolic
NADH: what Gpd regenerates is the *oxidised* member, which a sum over reducing equivalents does
not count, so a cofactor-cycle part is **not assumed to be a source**. Which of the three curated
reactions a step refers to is decided by exact gene-symbol match against the part; if the genes do
not narrow it to one, the step is `unknown`.

**Pos5 is different in kind from every other step in the model.** It consumes matrix NADH and
produces matrix NADPH: one compartment, two pools. It moves reducing power *between pools within a
compartment* rather than into or out of the route, so both terms are placed in the step's own
compartment. The code keys on `Reaction.transfers_redox_pool`, which `curated.py` already declares
for that one reaction, rather than inferring a transfer from "two pools appeared". And a declared
transfer must **conserve**: its terms are required to sum to zero and a transfer that does not is
reported `unknown` with the sum named. Without that check a mistyped coefficient would manufacture
reducing power from ATP and could produce a `balanced` route — the one verdict nobody re-derives.

The three parts are curated in `data/pathways/parts_catalog.yaml` to the `adh7_native` standard:
read from the stored corpus and quoted, `confidence: medium`, DOIs in the evidence, and every
field the corpus does not support left `unknown` (all three now say `oxygen_sensitivity: unknown`,
where two of them previously asserted `insensitive` from memory).

### Where the flag lives, and why

On `Route`, as a `RedoxBalance` record — not a boolean, not a string, not a companion table.

*Not a boolean.* `unbalanced: true` is not something anybody can act on. "NADPH short by 2 in the
mitochondrial matrix" names a compartment, a pool and a magnitude, which is a design instruction:
overexpress Pos5, switch the KARI, or move the step.

*Not a companion map keyed by route id.* Every other gate output a route carries —
`transport_gaps`, `cofactor_risks`, `chassis_gates`, `construction_requirements` — is a field on
`Route`. A sixth delivered as a side table would have to be threaded through `rank`, `explain`,
`write_routes`, the CLI and the recall harness by hand, and the first caller to forget it gets a
route with no balance and **no way to tell that from a balanced one** — the absence-is-not-zero
failure this module refuses everywhere else.

`Route.balance_status` is now a **property** derived from the record rather than a stored string,
so the word written to `pathway_route.balance_status` cannot disagree with the record it came
from. The three states map onto that column's existing CHECK without touching the schema:
`balanced → 'pass'`, `unbalanced → 'fail'`, `unknown → 'not_evaluated'`. **A stored `'fail'` on a
route that is still offered is the ruling expressed in the existing vocabulary**: the column says
whether the balance closes, `excluded_because` says whether the route is dropped. Those were the
same question until today and they are not any more.

### What the run says

**6,400 routes** — 800 five-step combinations × 8 cofactor-cycle subsets. (It was 600 before
`adh7_native` was curated, 800 after, and 6,400 once the optional role landed.)

| verdict | routes | of which cycle-free | stored as |
|---|---|---|---|
| balanced | **0** | 0 | `pass` |
| unbalanced | **4,800** | 600 | `fail` |
| unknown | **1,600** | 200 | `not_evaluated` |

**Nothing is excluded.** All 6,400 are viable, all 6,400 are in the ranked list, and the flag is
not a sort key. The cycle-free column is the check that the optional role added routes rather than
moving any: those 800 are the previous population, verdict for verdict.

*Why no route is balanced — and why the reason is now a sharper finding than the one it replaces.*
It used to be structural: nothing could regenerate a cofactor, so closure was unreachable. It is
reachable now, and still unreached, for an **arithmetic** reason the slot exposed rather than
caused. A route spends **two** reducing equivalents — the KARI and the ADH — and the only curated
cofactor-cycle reaction that *supplies* one is Adh3, which supplies **one**. Pos5 moves a debt
between pools rather than paying it, and Gpd deepens it. So the best any route reaches is a single
open bucket: **472 routes are one equivalent short**, against a previous floor of two.

*What the cofactor cycle does buy, and it is the result the change exists for.* **240 routes now
close the mitochondrial matrix completely** — both matrix buckets at zero, the first compartment
the atlas has ever reported as closing. They are the Adh3 + Pos5 routes with a matrix-side Ilv5,
which is to say they are DUET. Worked by hand on the native split with Adh1:

```
AHAS  ilv2_ilv6_native  matrix   ahas              no redox participant    0
KARI  ilv5_native       matrix   kari              NADPH a substrate      -1 matrix NADPH
DHAD  ilv3_native       matrix   dhad              no redox participant    0
KDC   aro10_native      cytosol  kdc               no redox participant    0
ADH   adh1_native       cytosol  adh_isobutanol    NADH a substrate       -1 cytosol NADH
cycle adh3_native       matrix   adh3_matrix       NADH a PRODUCT         +1 matrix NADH
cycle pos5_native       matrix   pos5_nadh_kinase  declared transfer      -1 matrix NADH,
                                                                          +1 matrix NADPH

matrix NADPH  -1 +1 = 0      matrix NADH  +1 -1 = 0      cytosol NADH  -1
```

The route is still reported `unbalanced`, and correctly: the one open bucket is the cytosolic
ADH's NADH. Glycolysis plainly supplies cytosolic NADH, but `COFACTOR_POOLS` records *which*
cofactors a compartment holds and never *how much* — so "glycolysis will cover it" is a supply
claim the atlas cannot make, and the same argument that forbids exclusion forbids calling this
closed. Note also what the sum does not carry: **Pos5 spends ATP**, and an adenylate balance is
not part of this calculation. `test_the_duet_pair_closes_the_mitochondrial_matrix_for_the_first_time`
pins the whole derivation, and also that neither gene alone does it — which is why the axis holds
a set rather than one slot.

*The content of the flag is still where and how much, and there is more of it.* **81 distinct
named imbalance signatures** across the 4,800, against 13 before — from
`NADPH short by 2 in mitochondrial_matrix` (strategy C on Ilv5 + Adh6, the published build, and
the number that contradicts `ISOBUTANOL_PROGRAM.md`'s prose) through
`NADH short by 1 in cytosol; NADPH short by 1 in mitochondrial_matrix` (the native split, one
shortfall on each side of the inner membrane) to
`NADH short by 2 in mitochondrial_matrix; NADH short by 1 in cytosol; NADPH in surplus by 1 in mitochondrial_matrix`
— a Pos5 route making matrix NADPH nothing in that route consumes. A **surplus** is a real
verdict and is named as one. A global sum would collapse all three and lose the only thing about
them worth knowing.

*Why 1,600 are unknown, and why that is the right answer.* `adh7_native` was read out of
10.1016/j.cels.2019.10.006 and the paper does not state the enzyme's cofactor, so the catalog
records `cofactor_preference: unknown` rather than filling it in from background knowledge. The
balance calculation does the same thing: the 1,600 routes carrying that part (a quarter of the
enumeration, the same fraction as before) report **`unknown`, with the reason named**, and they
still print the NADPH shortfall the KARI step *does* produce. An `unknown` correctly reported is
the honest state; a fabricated balance would be the worst outcome available. `unknown` is never
rounded to `balanced` — `enumerate_routes(parts)` with no curated pathway supplied flags all
routes `unknown` and says why.

### Whether the flag affects rank: **it does not**, and that is a decision

`RedoxBalance` is printed by `explain` and stored in `knowledge_gap`. It is **not** one of
`rank`'s keys. Three reasons, in order of weight:

1. *Any scalar built from it is a weighted total in disguise.* Ordering "NADPH short by 2 in the
   matrix" against "NADPH short by 1 in the matrix **and** NADH short by 1 in the cytosol" needs
   an exchange rate between a matrix NADPH and a cytosolic NADH. The atlas has no such rate, and
   the reason it has none is that the pools are not freely interconvertible — the claim the whole
   DUET argument rests on. `pathway_route` has five score columns and no total precisely to stop
   a number like that being invented.
2. *Demand alone does not say which is worse.* `COFACTOR_POOLS` says which cofactors a compartment
   has and never how much, and it is unverified. A shortfall of 2 is not known to be harder to
   meet than a shortfall of 1 until a supply figure exists — D1's option (b), still uncurated.
3. *A flag that silently reorders is a gate wearing a disguise.* Excluding on an unchecked premise
   and demoting on one differ in degree, not in kind, and the demotion is harder to notice.

**The alternative rejected:** make the total shortfall — `sum(abs(v) for v in net.values())` — the
second ranking key, ahead of feasibility, and print it in `explain` as its own term. Tempting,
because it would put one-NADPH routes above two-NADPH ones inside each strategy, which is a real
design preference. Rejected on (1): that sum adds a matrix NADPH to a cytosolic NADH as though
they were the same quantity. It would also have been constant across strategies today, moving only
*within* one — a term that looks like it works while separating almost nothing. If a measured
per-compartment supply figure is ever curated, the right term is demand-against-supply **per
compartment**, not a pooled magnitude, and it should arrive with its own `explain` line.

`test_the_redox_flag_does_not_reorder_the_ranking` pins this: the ranking with the stoichiometry
supplied is identical, id for id, to the ranking without it, under both objectives.

### What `explain` prints

```
objective=easiest | strategy=A_native_split | feasibility=1.00 | programme_fit=0.50 |
transport_gaps=1 | cofactor_risks=0 | chassis_gates=0 | construction_requirements=0 |
cofactor_cycle=adh3_native, pos5_native | redox=unbalanced (NADH short by 1 in cytosol) |
evidence=unknown (nothing extracted yet) | toxicity=unknown (no tolerance measurement)
```

C4 does not regress: the flag is printed although it is *not* a ranking term, as a stated property
of the route rather than a hidden reason for its position. `fermdb atlas explain` additionally
prints each named imbalance, each `unknown` reason and each pool substitution on its own line, and
`fermdb atlas routes` prints the balanced/unbalanced/unknown tally with the ruling beside it.

`cofactor_cycle` is printed as a **name or the word `none`, never as a count**: `0` would read as
a deficiency and a route with no cofactor cycle is what nearly every published build is. It is not
a ranking term either — the cycle steps are skipped by `_cofactor_gate` and `cofactor_demand`,
both of which ask unsigned questions of a field that carries no direction on these parts, so the
optional role adds no cofactor risk and cannot silently reorder the atlas.

### Stored, not just printed

Each named imbalance becomes a `knowledge_gap` row of kind `quantitative_value_missing`, hung off
the route, **with the compartment in its own column** — so "what does not close in the matrix" is
a query and not a string search. A `'fail'` in `balance_status` with nothing beside it saying which
pool in which compartment is short would be the boolean the ruling rejects.

### The tests

| test | what it pins |
|---|---|
| `test_a_redox_imbalance_is_flagged_and_named_and_the_route_is_not_excluded` | flagged, named per compartment, and still viable. **Replaces** `test_no_route_is_excluded_for_a_redox_reason_and_that_is_unimplemented_not_clean`, which asserted the absence of the feature |
| `test_a_route_with_a_known_imbalance_survives_enumeration_and_ranking` | the KivD + Adh6 matrix route, 2 NADPH short, is in `enumerate_routes` **and** in `rank` under both objectives |
| `test_the_balance_is_summed_per_compartment_and_never_across_them` | the native split's two shortfalls stay in different compartments; a route with the same parts in one compartment is a different record |
| `test_a_missing_stoichiometry_is_unknown_and_never_balanced` | both routes to `unknown` — no pathway supplied, and `adh7_native`'s undeclared cofactor — and that the partial imbalance is still reported |
| `test_every_route_carries_one_of_exactly_three_verdicts` | no fourth state, and the stored word stays inside the column's CHECK |
| `test_a_route_of_non_redox_steps_balances_which_is_how_balanced_is_reachable` | `balanced` is reached by a measurement, not by a constant. **Rewritten 2026-09-22**: its docstring used to give the reason nothing balances as "STEP_ORDER has no slot for a cofactor_cycle part", which is no longer true; the assertion is kept and the reason restated as the arithmetic one |
| `test_the_pool_is_taken_from_the_part_and_the_substitution_is_named` | the one inference, recorded by name; nothing substituted where part and reaction agree |
| `test_the_redox_flag_does_not_reorder_the_ranking` | the flag is not a sort key |
| `test_explain_prints_the_redox_flag_and_names_the_imbalance` | C4 — the name, not just the verdict, and on an excluded route too |
| `test_the_named_imbalance_is_stored_as_a_gap_with_its_compartment` | `balance_status='fail'`, the gap row, the compartment column, and the route still present |

And for the optional role, added 2026-09-22:

| test | what it pins |
|---|---|
| `test_enumeration_is_the_full_product_of_parts_and_strategies` | **rewritten**: the product gained a `2 ** k` factor for the cofactor-cycle subsets, the five catalytic roles are counted exactly as before, and exactly the old number of routes carry no cycle |
| `test_a_route_with_no_cofactor_cycle_is_a_route_and_not_a_deficient_one` | the constraint that mattered most — the 800 still enumerate with identical ids and verdicts, are viable and ranked, print `cofactor_cycle=none`, and a catalog with no cofactor-cycle parts still enumerates |
| `test_the_optional_role_is_not_in_step_order_and_that_is_the_whole_design` | the alternative rejected, and why: `STEP_ORDER` stays the five roles a published configuration must fill, `ROUTE_STEP_ROLES` carries the optional one |
| `test_a_cofactor_cycle_step_takes_its_compartment_and_genome_from_its_own_part` | Pos5 stays in the matrix in a cytosolic route; no cycle step is ever flagged for recoding, not even in strategy E |
| `test_a_cofactor_cycle_step_is_not_counted_as_a_demand_or_a_supply_risk` | the two unsigned gates skip it, so the ranking of the pre-existing routes is untouched, while the signed balance does change |
| `test_a_cofactor_cycle_step_contributes_the_sign_its_curated_reaction_is_written_in` | Adh3 supplies, **Gpd sinks** — a cofactor-cycle part is not assumed to be a source |
| `test_pos5_moves_reducing_power_between_pools_and_never_creates_it` | both terms in one compartment, summing to zero, with the route's total debt unchanged and no pool taken from the part |
| `test_a_declared_pool_transfer_that_does_not_conserve_is_unknown_not_balanced` | a mistyped coefficient cannot manufacture a `balanced` route |
| `test_the_duet_pair_closes_the_mitochondrial_matrix_for_the_first_time` | the result, derived term by term in the docstring, and that neither gene alone achieves it |
| `test_the_curated_reaction_for_a_cycle_step_is_chosen_by_gene_and_never_guessed` | exact gene-symbol resolution among the three cofactor-cycle reactions; `unknown` when it does not narrow to one |
| `test_only_the_entries_that_cite_a_source_are_better_than_unverified` (`tests/test_curated_pathways.py`) | **rewritten**: it pinned the one DOI `adh7_native` came from and would now fail on a correctly curated entry; it asserts a DOI-shaped citation on every `medium` entry instead |

### Proposed PLAN.md wording — **NOT APPLIED.** The owner owns that file

> **AMENDMENT 2026-09-22 — owner direction. A route that does not balance is flagged, not
> excluded.**
>
> *What this replaces:* in the phase-3 acceptance criterion, "routes violating
> **per-compartment** redox balance are excluded with the imbalance named"; and, in G.7's gate
> table, the Stoichiometric row's effect, "Fails → excluded, with the imbalance named".
>
> *The replacement:* "every route's **per-compartment** redox balance is computed and **flagged
> with the imbalance named** — which cofactor is short by how much in which compartment — and a
> route that does not balance **stays in the enumeration and in the ranking**; where the curated
> stoichiometry does not determine a step's contribution the balance is reported `unknown`, never
> `balanced`".
>
> *Why:* the supply side of the comparison does not exist. `compartment_cofactor_pool` and
> `COFACTOR_POOLS` record *which* cofactors a compartment holds and never *how much*, and both are
> `unverified`. Excluding on that premise would delete around 56 routes — including the
> cofactor-switched ones the DUET question turns on — on a claim nobody has checked, which is
> exactly the option-destroying move the atlas exists to prevent. Naming the imbalance was always
> the load-bearing half of the clause; dropping the route is the half that cannot be justified
> until a measured per-compartment supply figure is curated. Exclusion stays reserved for a
> genuine stoichiometric impossibility and for a chassis disqualification. If such a supply figure
> is ever curated, the right addition is a demand-against-supply term **per compartment**, printed
> in `explain` as its own term — not a pooled shortfall magnitude, which would add a matrix NADPH
> to a cytosolic NADH as though the inner membrane passed either.

---

## C3 — an enumerated-but-never-built route that survives inspection

Not a software test. A human reads a route card and judges it. It **was** effectively blocked
behind C1: "never built" is the complement of the *matched* configurations, and while recall was
0% the complement was all 600 routes — not a claim worth inspecting, because it was true by
default rather than by discovery.

**Unblocked 2026-09-22.** C1 now matches two configurations, so the complement is a real set:
**6,384 of the 6,400 routes**, with
`C_mitochondrial_ehrlich:ilv2_ilv6_native+ilv5_native+ilv3_native+kivd_lactococcus+adh7_native`
and its `A_native_split` twin excluded as built. The candidate set is `routes − matched`, and
`fermdb atlas explain <route>` already
prints everything an inspection needs: the term-by-term rank, the construction requirements, the
transport gaps, the cofactor risks, the per-compartment redox demand, and (for strategy E) the
insertion plan.

> **A CONSEQUENCE OF THE OPTIONAL `cofactor_cycle` ROLE, FOR THE RECALL RULE'S OWNER TO WEIGH —
> 2026-09-22.** Each of those two configurations now agrees with **8** enumerated routes rather
> than 1, because `_matching_routes` compares only the roles a record *filled* and no published
> record names a cofactor-cycle gene. Seven of the eight differ from the paper's build by adding
> POS5, ADH3 or GPD. The classification is unaffected — both are still `matched`, on the same
> clause, and the route reported first is still the cycle-free one, because the empty subset is
> enumerated first — but the *count* beside a match now reads higher than the number of builds it
> describes. Whether "8 routes agree" should instead read "1 route agrees, 7 with unnamed
> cofactor-cycle additions" is a matching-rule question, not an enumeration one, and it is
> recorded here rather than decided. It also slightly loosens C3's complement: 16 route ids are
> held out as built where 2 correspond to actual builds.

---

## C4 — every rank explainable term by term. **Passes, as of this change**

It did not pass before. `rank`'s fourth key counts the non-disqualifying chassis gates a route
carries, and `explain` did not print that term. Under the selected chassis, strategy E is the only
strategy that carries gates — so two routes could be ordered by a term the explanation did not
contain. One line added to `explain`, and the clause is now true rather than nearly true:

```
objective=easiest | strategy=B_cytosolic_relocalization | feasibility=0.80 |
programme_fit=unrecorded | transport_gaps=0 | cofactor_risks=0 | chassis_gates=0 |
construction_requirements=0 | evidence=unknown (nothing extracted yet) |
toxicity=unknown (no tolerance measurement)
```

`test_every_adjacent_pair_in_the_ranking_is_separated_by_a_printed_term` is the real test of the
clause: for every consecutive pair in the ranked list it finds the first term on which they
differ, checks the order runs the right way, and requires `explain` to print that term for both.
Ties on every named term fall back to the route id purely for determinism, and that is not a claim
about the routes.

---

## C5 — strategy E reachable but costly, naming all four things. **Passes**

* *Not dropped*: all 120 E routes are viable and appear in the ranking.
* *Costly*: every one carries a construction requirement and the lowest feasibility of any
  strategy (0.10), with a stated reason.
* *Not flattered*: no E route reaches the top of the ranking. It is not last either — strategy A
  ranks below it, because a missing carrier is a harder problem than a difficult technique.
* *All four nouns, on every route, not just one*: `insertion_plan` emits one line per
  mtDNA-carried gene naming locus, leader, activator, displacement and `recode to NCBI table 3`.
  "Displaced gene" is satisfied either by naming the gene or by saying the site displaces nothing
  — the second is the stronger answer, and it has to be *said*, because silence about displacement
  reads as "no displacement" and is not the same thing.

`test_every_strategy_e_route_names_all_four_things_not_just_one_of_them` and
`test_strategy_e_is_reachable_but_costly_rather_than_dropped_or_flattered`.

---

## Decisions this harness will not take for you

These are named rather than decided, because each is a curation or design judgement, not a coding
one.

**D1 — may an unverified compartment cofactor map exclude a route? SETTLED by the owner,
2026-09-22.**

> **Flag, don't exclude.** A route whose per-compartment redox balance does not close is
> **marked, with the imbalance named**, and **stays in the enumeration and in the ranking**.
> Nothing is dropped on an unchecked premise.

The question was: `COFACTOR_POOLS` is background knowledge that has never been measured, so may it
drop a route? Three options were on the table — (a) leave exclusion for stoichiometric
impossibility only and amend PLAN.md's clause; (b) curate a measured per-compartment supply figure
and gate on demand-exceeds-supply; (c) gate on the unverified map and accept that ~56 routes
vanish on a premise nobody has checked. `routes.py` argued (a) in a comment; PLAN.md asked for
something like (b).

**The ruling is (a), with the naming requirement kept rather than dropped** — which neither
position had stated. The balance is computed and named per compartment (PLAN's half) and the route
survives (the module's half). (c) is refused outright. (b) remains the upgrade path: if a measured
per-compartment supply figure is ever curated, the right addition is a demand-against-supply term
per compartment, and even then the owner's steer stands — if it affects rank it must appear in
`explain` as its own term, because a flag that silently reorders is a gate wearing a disguise.

Implemented 2026-09-22; see C2 above for where the flag lives, whether it affects rank (it does
not) and the alternative rejected. PLAN.md's own wording still says *excluded*; the proposed
amendment is at the end of the C2 section and is the owner's to apply.

**D6 — how should an optional step role be expressed? SETTLED by the owner, 2026-09-22.**

> Add a **`cofactor_cycle` step role** so `POS5`, `ADH3` and `GPD` can exist as parts. The step
> must be **OPTIONAL**: most published builds have no cofactor-cycle step, a route without one is
> a real route rather than a deficient one, and no existing route or published configuration may
> break.

Three ways to express it were available: a nullable slot in the enumeration, a separate axis, or
parts that may simply be absent. The implementation is **a power set over the cofactor-cycle
parts, whose empty member is first and is a first-class value**, on a tuple (`ROUTE_STEP_ROLES`)
that is deliberately *not* `STEP_ORDER`. A single nullable slot was rejected because DUET is two
genes in series and one slot cannot hold both; membership of `STEP_ORDER` was rejected because
`recall.py` reads that tuple as the roles a published configuration must fill, which would have
made every published build unmatchable. Both rejections are argued in full in C2.

**WHAT IS STILL NOT DECIDED, and is curation rather than code.** No route reaches `balanced`,
because a route spends two reducing equivalents and the one curated supplying reaction (Adh3)
supplies one. The two ways out are (a) curated stoichiometric multiplicity — a route model in
which a part can carry more than one equivalent of flux — and (b) a curated cytosolic
NADH-regenerating part. (a) is a change to what a route *is* and is the owner's; (b) is a curation
act. Neither was taken here, and `balanced` remains reachable-in-principle and unreached-in-fact,
which is the state the three-value verdict exists to report honestly.

**D2 — is a non-*S. cerevisiae* configuration in the recall denominator?**
Phase 1 curates "every published microbial isobutanol production strain, **any host**". But
`enumerate_routes` has no host axis at all — G.7's product says `× host` and the implementation
does not vary one, so every enumerated route is implicitly a yeast route (matrix and peroxisomal
compartments; a strategy E that means mtDNA). The harness currently holds non-yeast
configurations out of the denominator and names them, because counting an *E. coli* build as
re-discovered by a yeast enumeration would be a false recall of the plainest kind. The
alternative is to give the enumerator a real host axis, which is a phase-3 build, not a test fix.
Until then the recall figure speaks for yeast builds only, and `coverage` says how many that was.

**D3 — does a paper's named KARI variant equal a catalog part?**
`ENZYME_ALIASES` maps reported spellings to **gene symbols**, never to part ids. So `ilvC6E6`
resolves to all four `ilvC` parts and the match is flagged ambiguous. Asserting that the paper's
`ilvC6E6` *is* `ilvc6e6_ecoli` rather than plain `ilvc_ecoli` is a claim about cofactor
specificity, and it is the claim the DUET question turns on. A curator can settle it — by adding
`variant_of` / sequence identity to the catalog so the match has something to key on — but the
harness must not settle it silently.

**D5 — is `ROLE from ORGANISM` an enzyme identification? SETTLED by the owner, 2026-09-22.**

> A role name qualified by a source organism **is** a real identification, not a wildcard — but
> only when it is unambiguous. Resolve it to a catalog part **when the catalog holds exactly one
> part for that `(step_role, source_organism)` pair**; flag the match as **resolved-by-organism**,
> distinct from resolved-by-gene-symbol; if two or more parts share that pair, **refuse as
> ambiguous** — do not pick one.

The question was raised by the two cels-2019 configurations, which name their decarboxylase as
`"2-ketoacid decarboxylase (KDC) from Lactococcus lactis"` and were held `under_specified` because
the rule refuses a bare role name. Three options: (a) leave the rule alone and have a curator
rewrite the two Zone R descriptions to the paper's Methods spelling `LlKivD`; (b) treat the role
name as a wildcard, which returns 100% on a record that named nothing and is refused outright;
(c) read the organism.

**The ruling is (c), with uniqueness as the price.** (a) was what this document recommended and it
was not taken — the descriptions stay as the papers were reported, which is the Zone R rule, and
the vocabulary problem is solved in the matcher where it belongs. The concession is that
`resolved-by-organism` is genuinely weaker evidence than a gene symbol, so it is never allowed to
vanish into the total: it is named on every verdict and counted separately in the report.
Implemented 2026-09-22; see the C1 ruling section for the before/after figure, the three things
the ruling does not reach, and the test that flips today's matches to refusals the moment a second
*Lactococcus* KDC is curated.

**D4 — should `ENZYME_ALIASES` grow, and who owns it?**
It holds six entries today, each with its reason in a comment. Every alias is a curation claim
("the paper's X is the catalog's gene Y"). The first real recall run will produce a list of
unrecognised spellings; some are aliases to add, and some are genuine catalog gaps. Telling those
two apart is curation, and it is the worklist this whole harness exists to produce.

---

## Files

| | |
|---|---|
| `src/fermdb/metabolic/recall.py` | the harness and `MATCHING_RULE` |
| `src/fermdb/metabolic/cli.py` | `fermdb atlas recall` / `--rule`; the redox tally on `atlas routes`; the named imbalance on `atlas explain` |
| `src/fermdb/metabolic/routes.py` | `RedoxBalance`, `redox_balance`, `pathway_for_routes` (C2); `explain` prints the chassis term (C4) and the redox flag; `ROUTE_STEP_ROLES`, `cofactor_cycle_sets` and the Pos5 pool-transfer branch (the optional role) |
| `data/pathways/parts_catalog.yaml` | `pos5_native`, `adh3_native` and `gpd1_gpd2_native` — the parts of the optional role, read from the corpus and quoted, `confidence: medium` |
| `data/pathways/ethanol_reference.yaml` | where the three `cofactor_cycle` reactions are curated. `pathway_for_routes` merges **only those** into the isobutanol pathway; pooling the catalytic roles across files stays refused |
| `tests/test_recall.py` | the rule, clause by clause, and the strictness properties |
| `tests/test_routes.py` | C2 (flagged, named, not excluded), C4, C5, and the optional-role contract |
| `tests/test_curated_pathways.py` | the balance checks, and that a `medium` catalog entry cites a source |
