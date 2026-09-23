"""PLAN.md T.5's release export: the atlas as a bundle that outlives this code.

T.5 asks for "a release export as RO-Crate (or an equivalent structured bundle): the data, the
schema, the provenance graph, the pipeline versions and the licence terms, such that a third
party can reproduce an analysis or cite a specific state of the atlas", and then names the one
rule that the rest of the bundle exists to serve: *"Zone I content exports separately and is
labelled as inference in the export itself, not only in the documentation."*

That sentence is the whole design brief, because everything else in this atlas is already
arranged around one claim -- that inferred content never gets mistaken for reported content --
and an export is precisely where that claim is most likely to die. A SQLite file has CHECK
constraints; a directory of flat files has nothing but its own shape. So the shape does the work:

* **Zone I is a separate file.** `data/inferred/<table>.jsonl` never holds a Zone R or Zone H
  row, and no file holds two zones. A reader who loads only `data/reported/` has loaded only
  reported content, without having read a word of prose.
* **The zone is also a field on every row** (`_zone`, `_zone_label`, `_is_inference`,
  `_may_support_a_conclusion`). The directory split is convenience; the field is the authority.
  A file moved, renamed or concatenated into another loses the directory and keeps the field,
  and T.5's "labelled as inference in the export itself" is a statement about the rows, not
  about the filenames.
* **The evidence level travels the same way** -- `_level` on every assertion row, carrying L1-L5
  *and the basis it was derived from*, because `assertion_level` returns NULL for two opposite
  reasons (nothing known, versus direct evidence in open conflict) and a bare NULL conflates
  them. See `query/values.py`, whose `EvidenceLevel` this module reuses rather than re-deriving.
* **The three absences stay three.** `docs/reference/CONVENTIONS.md` "Missing values" -- NULL is
  "the source never recorded it", `'NA'` is "recorded as not applicable", `'unknown'` is
  "recorded, but could not be resolved". JSON has one absence, so every row carries an
  `_absence` map naming which of the three each missing column is in. PLAN.md P.4 is the reason
  this is not optional, and `query/values.py` is the precedent: the rule has to live in the
  shape of the value, not in a note addressed to whoever writes the reader.

`release.py` builds the bundle; `crate.py` writes the RO-Crate metadata descriptor and is honest
in its own docstring about which parts of that specification it implements and which it does
not; `cli.py` is `fermdb export release --out DIR`.

Nothing here writes to the database. Every query is a SELECT and the connection may be opened
read-only.
"""

from __future__ import annotations

from .crate import CRATE_SPEC_IMPLEMENTED, CRATE_SPEC_NOT_IMPLEMENTED, build_crate
from .release import (
    BUNDLE_FORMAT,
    META_PREFIX,
    ZONE_DIRECTORIES,
    Anomaly,
    Bundle,
    ExportError,
    TableExport,
    build_release,
)

__all__ = [
    "BUNDLE_FORMAT",
    "CRATE_SPEC_IMPLEMENTED",
    "CRATE_SPEC_NOT_IMPLEMENTED",
    "META_PREFIX",
    "ZONE_DIRECTORIES",
    "Anomaly",
    "Bundle",
    "ExportError",
    "TableExport",
    "build_crate",
    "build_release",
]
