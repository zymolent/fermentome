# The known-positive benchmark set

## Read this before using anything in this directory

**No entry in `known_positives.yaml` may be used as evidence for anything.**

Every entry in that file was written from an AI assistant's background knowledge in phase 0, before
any pipeline, any ingestion and any source document existed in this repository. Nothing in it was
read from a paper, a database or a genome annotation. Some of it is probably wrong. Several entries
name authors and years that are recalled rather than checked, and are marked as such.

Every entry already carries an `evidence` field, honestly stating what it is today: "background
knowledge, no source consulted". That is not a placeholder in the sense the schema forbids —
it is itself the true, current evidence for an unverified claim, and satisfies
`docs/reference/CONVENTIONS.md`'s "every curated row carries evidence and confidence" rule from
the row's creation, not from some later verification event. `source_hint` remains the pointer to
what a curator should go and check; `evidence` is what has actually been checked so far.

An entry becomes usable only when a human curator has:

1. found the source named in `source_hint`, or a better one;
2. checked that the `statement` is what that source actually says;
3. overwritten the entry's `evidence` field with that real source, replacing the "background
   knowledge, no source consulted" placeholder;
4. set `confidence` to `low`, `medium` or `high` according to what the source supports; and
5. set `verified: true`.

Until then the entry is a **question**, not a fact. `tests/test_benchmarks.py` enforces that every
entry in the file is still `confidence: unverified` and `verified: false`, and that test will start
failing the moment a curator begins promoting entries — at which point the test is to be relaxed
deliberately, in a reviewed diff, not silently.

The file declares `zone: I` (inferred, quarantined) for exactly this reason. Per
`docs/reference/CONVENTIONS.md`, Zone I content may not support a conclusion until a curator
promotes it. Verified entries are promoted to Zone R with their citation.

A benchmark set that was itself unverified and did not say so would be the most damaging file in
this repository: it would launder guesses into a headline accuracy number. Hence this page.

## Why the file exists, and why it was written first

`PLAN.md` S.5 requires the benchmark set to be written in phase 0, **before** the pipelines exist.
The reason is not convenience. A target written after the tool is built is a description of what
the tool happens to do. Writing it first fixes the target before anything aims at it, so that a
low recovery rate is information rather than an embarrassment to be tuned away.

Recovery rate against this set is the single most informative number about whether the atlas works.
A pipeline that cannot recover textbook biology will not discover anything new.

## How to read an entry

| field | meaning |
|---|---|
| `id` | Stable identifier, `BM-<GROUP>-<NNN>`. Never re-pointed; a retired entry keeps its id. |
| `category` | One of the seven values listed in the file's `categories` block. |
| `statement` | The fact, or — for a negative control — the non-fact. Read every one as if it ended in "(unverified)". |
| `query_shape` | How the atlas is to be asked. If a statement has no query shape, the schema is missing something; that is the test this field applies. |
| `expected_outcome` | What a passing answer looks like, including shape and failure modes. Not just "true". |
| `organism` | The organism the statement is about. Cross-host entries exist deliberately (see `BM-COF-004` and `BM-NEG-006`). |
| `product` | `isobutanol`, `ethanol`, `isoamyl_alcohol`, or the literal string `'NA'` where the statement is not about a product at all (the genetic-code entries). `'NA'` means *recorded as not applicable* and is not the same as absent. |
| `expected_evidence_level` | The level the atlas should be able to reach for this statement, L1–L5 per `PLAN.md` J.3. Negative controls carry `'NA'`: the expected outcome is that nothing is found, so there is no level to reach. |
| `source_hint` | What a curator should go and check — an author, a year, a database, a gene name, a search to run. This field is the whole point of the file being honest. |
| `evidence` | Free text naming the source actually consulted (`CONVENTIONS.md`, Curation). "Background knowledge, no source consulted" for every entry, today; a curator overwrites it with the real source at verification time. |
| `confidence` | `unverified` for every entry, today (`CONVENTIONS.md`'s closed confidence vocabulary: `unverified`, `low`, `medium`, `high`). |
| `verified` | `false` for every entry, today. |

## The negative controls are not filler

Six of the 41 entries are negative controls, and they carry as much weight as the positives. A
pipeline that recovers every positive statement in this file and *also* "recovers" the negatives is
not discriminating biology; it is matching text. Recovery rate is only meaningful when reported
next to the false-positive rate on the negative controls, and the dashboard must show both numbers
together or neither.

Two of them guard against specific, expensive errors:

* `BM-NEG-001` — mitochondrial **targeting** does not require codon recoding, because translation
  happens on cytosolic ribosomes; only sequence placed **into** mtDNA does. Conflating these is the
  most likely mistake in this domain.
* `BM-NEG-003` — no published isobutanol configuration edits the mitochondrial genome. A fabricated
  row here would point a research programme at a year of the wrong work.

`BM-NEG-002` is the housekeeping-gene control, and its gene choice is deliberate: it uses
qPCR reference genes (*ALG9*, *TAF10*, *UBC6*, *TFC1*) and deliberately **excludes** *ACT1*, *TDH3*
and *PGK1*, which are loosely called housekeeping genes but are cytoskeletal or glycolytic and could
plausibly affect flux to isobutanol (unverified). A negative control that is not actually null
teaches nothing.

Per `CONVENTIONS.md`, the reason a row is *absent* is part of the data. Comments in
`known_positives.yaml` explaining an exclusion are content, not decoration, and are preserved.

## Composition

| category | entries | what it covers |
|---|---|---|
| `pathway_compartment` | 11 | Matrix localization of the Ilv enzymes, cytosolic Ehrlich pathway, 2-ketoisovalerate as the branch point, the single membrane crossing, the unidentified carrier as a gap. |
| `cofactor_redox` | 5 | The KARI-NADPH / ADH-NADH mismatch, per-compartment balance, the engineered NADH-preferring KARI, matrix NADPH supply as a gap. |
| `competing_pathway` | 6 | Pdc as the ethanol sink, the Gpd glycerol branch, the Bat and Leu drains on 2-ketoisovalerate, decarboxylase promiscuity. |
| `mitochondrial_genetics` | 6 | Table 3 differences (UGA, CUN, AUA), the translational-activator constraint, ARG8m as the soluble-matrix-enzyme precedent, the absence of a CRISPR route. |
| `ethanol_reference` | 4 | The 0.511 g/g and 0.411 g/g ceilings, the wild-type baseline, the Crabtree effect. |
| `tolerance` | 3 | Isobutanol versus ethanol inhibition, assay-type non-interconvertibility, the L3 cap on ethanol-to-isobutanol mechanism transfer. Each names its assay type. |
| `negative_control` | 6 | Things the atlas must not find. |
| **total** | **41** | |

Three entries are paired with a negative control and must be curated together, because verifying
one verifies the other: `BM-PATH-008` with `BM-NEG-004` (the carrier gap), and `BM-COF-004` with
`BM-NEG-006` (the *E. coli* result staying in *E. coli*).

## Adding or changing an entry

* A new entry arrives as a diff to `known_positives.yaml`, reviewed as a diff, with
  `confidence: unverified` and `verified: false` like every other.
* Ids are unique and stable. If an entry turns out to be two claims, retire the id and write two
  new ones that point back to it; never re-point an existing id.
* Do not delete a disproven entry. An entry that the literature contradicts is a *better* benchmark
  once it is rewritten as a negative control, because it tests discrimination rather than recall.
* Never write `confidence: high` from memory. That rule is why this file exists in its present
  state.

## Running the checks

From the repository root:

```
python -m pytest tests/test_benchmarks.py
```

The test asserts structure and honesty, not biology: that the YAML parses, that every entry has
every required field with a value from the controlled vocabulary, that no entry claims to be
verified, that there are at least five negative controls, and that ids are unique. It cannot tell
you whether a statement is true. Only a curator can.

The benchmark file's location is resolved from the `FERMDB_BENCHMARK_FILE` environment variable if
set, and otherwise relative to the repository root; no path is written into source code.
