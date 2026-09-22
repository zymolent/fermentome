# The atlas holds two BSW205 titers, sevenfold apart, with nothing to tell them apart

**Status:** a measured finding and a recommendation. Nothing changed.
**Date:** 2026-09-22

## The two rows, live right now

```
YAA:MEAS:88f336916a59cf77   YAA:STRAIN:bsw205   titer   230.0 mg/L   basis=None   loc=text
YAA:MEAS:f7a49e8797f74431   YAA:STRAIN:bsw205   titer   1.62  g/L    basis=None   loc=text
```

Both promoted, same strain, same quantity, same publication, same `source_locator`. A query asking
what titer BSW205 reached gets two answers a factor of seven apart and no way to choose between
them.

They are not contradictory. One is **24 h** and the other is **48 h**, and the drop is real —
isobutanol is volatile and the paper is measuring a culture that has been stripping it off for a
day. The paper is consistent. The atlas lost the one fact that makes it so.

The same pattern sits under BSW206 (221 mg/L at 48 h against 1.61 g/L at 24 h) and under both
strains' yields (0.016 g/g at 24 h, 0.012 and 0.011 at 48 h).

## Where the timepoint went

`extract/schemas.py` asks the model for `time_h` on every measurement. The phase-1 batch returns
it: **78 of 182 measurement proposals (43%) carry one** — 37 already accepted, 40 pending, 1
edited. `curate/promote.py` does not mention `time_h` anywhere. It is read, transported, and
dropped at the last step.

This is not a missing column. The schema already models it correctly, and the model it uses is
the right one:

```sql
CREATE TABLE sample (
    ...
    strain_id            TEXT REFERENCES strain(id),
    condition_context_id TEXT REFERENCES condition_context(id),
    time_h               REAL,
    growth_phase         TEXT,
```

Time lives on `sample`, not on `condition_context` and not on `measurement`. That is right: a
timepoint is a property of **the sample drawn**, not of the condition the culture was grown under.
Two samples at 24 h and 48 h share one condition context and differ in when somebody took the
reading. `measurement.sample_id` exists and is the intended link.

**The gap is that no literature measurement has a sample.** All 172 `sample` rows are SRA runs
from omics datasets, every one with `strain_id` and `condition_context_id` NULL. Not one belongs to
any of the eleven extracted papers. So a literature measurement carries `sample_id = NULL` and its
timepoint has nowhere to go.

## Scale

* **4 time series** in the queue today — same paper, strain and quantity at more than one timepoint
  — covering **8 measurements**. Small, and every one of them is a pair the atlas cannot currently
  distinguish.
* **78 measurements carry a timepoint** that is discarded on promotion. The other 70 are single
  readings where losing the time costs comparability rather than identity.
* Of the 4 series, **all 4 are already promoted or pending promotion**, so this is live data rather
  than a future risk.

Worth being plain about the size: this is 8 rows, not 800. It is recorded because the failure is
silent, is already in the atlas, and grows linearly with every fermentation paper extracted — and
because a titer with no timepoint is not a weaker claim, it is a different one.

## Why `proposal_hash` does not save it

Ids are hashed over the payload, and the payloads differ (different value, different quote), so the
two rows get different ids and both persist. Nothing collides, nothing warns. The duplicate
detector added today reports proposals matching an already-promoted `(strain, quantity, value,
unit, publication)` — these differ in `value`, so it correctly does not flag them. They are not
duplicates. They are distinct measurements missing the field that distinguishes them.

## The recommendation

**Do not add `time_h` to `measurement`.** It would duplicate `sample.time_h`, give the schema two
homes for one fact, and they would drift.

Instead, let promotion create a `sample` when a measurement carries a timepoint:

* one `sample` per `(publication, strain, time_h)`, `zone='R'`, `condition_context_id` left NULL
  until a context is approved — nullable already, and CONVENTIONS' "no sample enters a contrast
  without an approved condition context" governs **contrasts**, not the sample's existence;
* `measurement.sample_id` set to it;
* `time_h` never inferred — only written where the paper stated it, which is the 43% that carry one.

This is a change to what promotion *writes*, so it is a curator's decision rather than mine, and it
should be taken before the 552 corroborated proposals are promoted. Promoting first and
back-filling later means re-deriving timepoints from spans for rows that already look finished.

## Checked and not the problem

`condition_context` is the wrong lever here even though it is empty. Its 0 rows block phase 4's
contrast clause, but a literature measurement would still have no sample to hang a context on, and
the timepoint would still be dropped. Filling `condition_context` does not fix this; creating
samples does.
