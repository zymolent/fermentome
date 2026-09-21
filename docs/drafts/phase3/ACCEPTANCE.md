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

Five clauses. **Three pass, one does not, one is not a software test at all.** The one that does
not is C1, and it is not a bug in the ranker — see that section for where its blocker now sits.

**Updated 2026-09-22 — C2.** C2 was failing because the gate was never built and could not be
built without decision **D1**. The owner settled D1 on 2026-09-22 — *flag, don't exclude* — and
the per-compartment balance is now computed, flagged and named, with nothing excluded for a redox
reason. See the C2 section and the D1 entry.

| # | Clause | Verdict | What it needs |
|---|---|---|---|
| C1 | Recall against phase 1 | **STILL NOT PASSING — now `not measurable`, 0/0 judgeable.** See the 2026-09-22 amendment below; the Adh7 part was curated and the blocker moved | A curator correction to the two cels-2019 configurations, naming the decarboxylase as `LlKivD` (the paper's own Methods do). Not another part |
| C2 | Per-compartment redox balance, imbalance named | **PASSES**, as of 2026-09-22, under the owner's amended clause | Nothing in code. PLAN.md's wording still says *excluded*; the proposed amendment is at the foot of this section and is the owner's to apply |
| C3 | ≥1 enumerated-but-never-built route is scientifically defensible | **NOT A TEST** | A human reads a route card and says so. Effectively blocked behind C1: "never built" is the complement of the matched configurations, and that complement is currently all 600 routes |
| C4 | Every rank explainable term by term | **PASSES**, as of this change | Nothing. It did not pass before: `rank`'s fourth key was invisible to `explain` |
| C5 | Strategy E reachable-but-costly, naming locus / leader / displaced gene / recoding | **PASSES** | Nothing |

---

## C1 — recall. Ran for the first time today, and it fails

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

The general lesson is worth keeping, because it will recur: *"the enumerator cannot express this
build"* and *"the record does not say what the build was"* are different failures that a single
recall percentage cannot tell apart. Only the first is a catalog gap. The first run's worklist had
one line and it looked like the whole story; it was one of two, and the second was invisible until
the first was fixed.

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
   plus a small curated `ENZYME_ALIASES` table of named exceptions.
3. **Host** — `host_strain_id` resolves to an organism, but **`enumerate_routes` has no host axis**
   (see D2). So the host is used only to decide scope, never to match.

Seven clauses, applied in order, first one wins. `fermdb atlas recall --rule` prints the full text
of each; the short version:

| clause | outcome | in one line |
|---|---|---|
| `strategy_not_enumerable` | not evaluable | strategy is NULL, `unknown` or `NA` — no route to compare against |
| `host_not_recorded` | not evaluable | no host, so the configuration cannot be placed in or out of scope |
| `host_outside_enumeration` | not evaluable | an *E. coli* build against a yeast-only enumeration |
| `no_enzyme_set_recorded` | not evaluable | the description has no `enzymes as reported:` segment |
| `matched` | **hit** | all five roles resolved, and some route of that strategy agrees at all five |
| `catalog_gap` | **miss** | a role is unfilled *and* an enzyme was named that no part carries |
| `under_specified` | not evaluable | a role is unfilled and every named enzyme was recognised |

### Four decisions inside that rule that could each have gone the other way

**The prose beside the enzymes is never read.** `description` is
`"enzymes as reported: X, Y; localization as reported: <prose>"`. The harness reads only the first
segment. The prose is where the interesting failure lives: a real payload in this atlas says a
build works *by circumventing* Bat1p and Bat2p, and another names Cox4, a targeting leader and not
a pathway enzyme. A rule that scanned the whole description would credit builds with enzymes they
deliberately removed. Tested by
`test_the_localization_prose_is_never_mined_for_enzyme_names`.

**A role name is not an enzyme identification.** Real payloads name `"KDC"`, `"ADH"` and
`"ILV genes"`. Treating `"KDC"` as "any KDC part" is a wildcard, and a configuration naming
nothing would then match all 120 routes of its strategy and return 100% recall on an empty record.
Role names are recorded separately (`role_named_only`) and leave the role **unfilled**. Gene
families named as a block — `"ILV genes"`, the Ehrlich pathway — are in the same category and are
listed in `_ROLE_SYNONYMS`. Without that list, `"ILV genes"` is reported as a *catalog gap*, which
would put a non-existent part called "ILV genes" on the curation worklist; the worklist is only
worth reading if every line on it is actionable, and today it has exactly one line, `ADH7`.

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
  so in words. **560 of 800 routes carry such a note**; a reader can see where every number came
  from.

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

800 routes (600 until `adh7_native` was added to the catalog on 2026-09-22):

| verdict | routes | stored as |
|---|---|---|
| balanced | **0** | `pass` |
| unbalanced | **600** | `fail` |
| unknown | **200** | `not_evaluated` |

**Nothing is excluded.** All 800 are viable, all 800 are in the ranked list, and the flag is not a
sort key.

*Why no route is balanced, and why that is a finding rather than a bug.* The five catalytic steps
consume reducing power and none of them regenerates it. Closure needs a `cofactor_cycle` part —
POS5, ADH3, GPD — and `STEP_ORDER` has no slot for one. So the content of the flag is *where* and
*how much*, and that varies: **13 distinct named imbalances** across the 600, from
`NADPH short by 2 in mitochondrial_matrix` (strategy C on Ilv5 + Adh6 — the published build, and
the number that contradicts `ISOBUTANOL_PROGRAM.md`'s prose) through
`NADH short by 1 in cytosol; NADPH short by 1 in mitochondrial_matrix` (the native split, one
shortfall on each side of the inner membrane) to `NADH short by 2 in cytosol`. A global sum would
collapse the second of those to "2 short" and lose the only thing about it worth knowing.

*Why 200 are unknown, and why that is the right answer.* `adh7_native` was read out of
10.1016/j.cels.2019.10.006 and the paper does not state the enzyme's cofactor, so the catalog
records `cofactor_preference: unknown` rather than filling it in from background knowledge. The
balance calculation does the same thing: the 200 routes carrying that part report **`unknown`,
with the reason named**, and they still print the NADPH shortfall the KARI step *does* produce.
An `unknown` correctly reported is the honest state; a fabricated balance would be the worst
outcome available. `unknown` is never rounded to `balanced` — `enumerate_routes(parts)` with no
curated pathway supplied flags all routes `unknown` and says why.

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
objective=easiest | strategy=C_mitochondrial_ehrlich | feasibility=0.60 |
programme_fit=unrecorded | transport_gaps=0 | cofactor_risks=0 | chassis_gates=0 |
construction_requirements=0 | redox=unbalanced (NADPH short by 2 in mitochondrial_matrix) |
evidence=unknown (nothing extracted yet) | toxicity=unknown (no tolerance measurement)
```

C4 does not regress: the flag is printed although it is *not* a ranking term, as a stated property
of the route rather than a hidden reason for its position. `fermdb atlas explain` additionally
prints each named imbalance, each `unknown` reason and each pool substitution on its own line, and
`fermdb atlas routes` prints the balanced/unbalanced/unknown tally with the ruling beside it.

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
| `test_a_route_of_non_redox_steps_balances_which_is_how_balanced_is_reachable` | `balanced` is reached by a measurement, not by a constant |
| `test_the_pool_is_taken_from_the_part_and_the_substitution_is_named` | the one inference, recorded by name; nothing substituted where part and reaction agree |
| `test_the_redox_flag_does_not_reorder_the_ranking` | the flag is not a sort key |
| `test_explain_prints_the_redox_flag_and_names_the_imbalance` | C4 — the name, not just the verdict, and on an excluded route too |
| `test_the_named_imbalance_is_stored_as_a_gap_with_its_compartment` | `balance_status='fail'`, the gap row, the compartment column, and the route still present |

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

Not a software test. A human reads a route card and judges it. It is also **effectively blocked
behind C1**: "never built" is the complement of the *matched* configurations, and with recall at
0% the complement is all 600 routes — which is not a claim worth inspecting, because it is true by
default rather than by discovery.

Once C1 matches anything, the candidate set is `routes − matched`, and `fermdb atlas explain <route>` already
prints everything an inspection needs: the term-by-term rank, the construction requirements, the
transport gaps, the cofactor risks, the per-compartment redox demand, and (for strategy E) the
insertion plan.

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
| `src/fermdb/metabolic/routes.py` | `RedoxBalance`, `redox_balance`, `pathway_for_routes` (C2); `explain` prints the chassis term (C4) and the redox flag |
| `tests/test_recall.py` | the rule, clause by clause, and the strictness properties |
| `tests/test_routes.py` | C2 (flagged, named, not excluded), C4, C5 |
