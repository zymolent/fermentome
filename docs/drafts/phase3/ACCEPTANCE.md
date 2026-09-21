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

Five clauses. **Two pass, two fail, one is not a software test at all.** Neither failure is a bug
in the ranker: C1 fails because the parts catalog is missing an enzyme the literature used, and C2
fails because the gate was never built and cannot be built without a decision only the owner can
take.

| # | Clause | Verdict | What it needs |
|---|---|---|---|
| C1 | Recall against phase 1 | **FAILS — 0%**, on the first 2 judgeable configurations | Parts for the enzymes published builds actually used, starting with **Adh7**. Until this session it read CANNOT BE EVALUATED |
| C2 | Per-compartment redox exclusion, imbalance named | **FAILS** | The gate is not implemented. Implementing it needs decision **D1**, which is the owner's |
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

Two caveats on reading 0%, both of them in the direction of "it is early", not "it is worse than
it looks":

* the denominator is **2**. Four configurations, two judgeable. One figure is not a trend.
* the other two are under-specified, not wrong. Both are the same paper naming `"ARO10"` and
  `"LlAdhA RE1"` and leaving the upstream ILV enzymes as `"ILV genes"`. `partial` is 50% because
  every step those records *did* name matched an enumerated route. That number is real and it is
  not recall.

### What was built, so the clause stays answerable as the table fills

* `src/fermdb/metabolic/recall.py` — the harness, and `MATCHING_RULE`, which is the rule written
  down as data rather than buried in a comparison function. `fermdb atlas recall --rule` prints
  it clause by clause.
* `fermdb atlas recall` — the recall figure, the matched pairs, the unmatched configurations, and
  the list of enzymes published builds used that no part in the catalog carries.
* `tests/test_recall.py` — one test per rule clause plus the strictness properties. Every
  configuration in them is copied from a **real** `pathway_configurations` extraction payload
  sitting in `curation_task`, so the harness is tested against the vocabulary it actually meets,
  not against a tidy invention. `ADH7` is in those tests because it is in the literature, and it
  is now the one thing standing between this clause and a non-zero figure.

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

## C2 — per-compartment redox exclusion. **Fails.** The gate is not implemented

G.7's gate table says:

> | Stoichiometric | Carbon, redox and ATP balance, **per compartment** | Fails → excluded, with the imbalance named |

Nothing in `routes.py` excludes a route for a redox reason. `Route.balance_status` is the literal
string `"pass"` on all 600 rows, and the only exclusions reachable today come from
`chassis.gates_for`. Half the machinery exists: `cofactor_demand` tallies demand per
`(compartment, cofactor)` — that is what found that the published KivD + Adh6 route wants **2
NADPH in the matrix**, contradicting `ISOBUTANOL_PROGRAM.md`'s prose. What is missing is a supply
figure to test that demand against. `COFACTOR_POOLS` says *which* cofactors a compartment has,
never *how much*, and it is marked unverified.

`routes.py` argues, at length and in the module, that excluding 56 routes on an unverified premise
would delete exactly the options the atlas exists to surface. That argument is good and this
harness does not overrule it. But it means the clause as written does not pass, and saying "it
passes because we decided not to exclude anything" would be dressing a gap as a policy.

Pinned by `test_no_route_is_excluded_for_a_redox_reason_and_that_is_unimplemented_not_clean`,
which is written as an assertion so it fails the day the gate arrives and this note goes stale.

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

**D1 — may an unverified compartment cofactor map exclude a route?**
C2 cannot be implemented without an answer. `COFACTOR_POOLS` is background knowledge that has
never been measured. Three options: (a) leave exclusion for stoichiometric impossibility only and
**amend PLAN.md's clause** to say so — the honest option if the map stays unverified; (b) curate a
measured per-compartment supply figure and gate on demand-exceeds-supply; (c) gate on the
unverified map and accept that ~56 routes vanish on a premise nobody has checked. `routes.py`
currently argues for (a) in a comment; PLAN.md asks for something like (b). They disagree, and
only the owner can settle which document is wrong.

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
| `src/fermdb/metabolic/cli.py` | `fermdb atlas recall` / `--rule` |
| `src/fermdb/metabolic/routes.py` | `explain` now prints the chassis term (C4) |
| `tests/test_recall.py` | the rule, clause by clause, and the strictness properties |
| `tests/test_routes.py` | C2 (pinned as failing), C4, C5 |
