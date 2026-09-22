"""Which pending proposals describe a measurement the atlas already holds?

`proposal_hash` is a hash of the whole record, quote included, and `queue._strip_offsets` says
plainly why: *"a different quote is a different piece of evidence and therefore a different
proposal"*. That is right for rejection -- a curator who rejected a claim rejected the claim, and
re-deriving the offsets a character differently must not resurrect it.

It has a consequence at the other end. `_measurement_id` derives the row id from that hash, so two
proposals about the **same number in the same sentence of the same paper** get different ids
whenever their quotes differ by a word, and promoting both writes two rows. Nothing in the
promotion path notices, because its "already present" check is on the id.

That is not hypothetical here. The 2026-09-22 re-extraction, run after the section-splitter fix,
re-proposed papers that had already been extracted and promoted: **107 pending proposals describe
a measurement the atlas already holds**, keyed on (strain, quantity, value, unit, publication).

**And they are not junk.** Compared field by field, the new proposals are *better* than the rows
they duplicate -- they carry `basis` and a specific `source_locator` ("figure 5" rather than
"text") where the promoted rows hold NULL, because the fixed sectioner gave the model the Results
section instead of the abstract. So the honest name for them is not "duplicates" but
**supersessions**, and what to do about each is a curator's decision under PLAN.md J.1 and L.5:
keep both, or retract the thinner row and promote the richer one. Retraction is a human act and
this module does not perform it.

What this module does is make them visible before a bulk promote writes 107 second copies of rows
that already exist. It reads; it never writes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["DuplicateReport", "find_duplicates"]

#: The fields that decide whether two measurements are the same measurement. Deliberately not the
#: whole record: `time_h`, `basis` and `source_locator` are exactly what differs between a thin
#: row and the richer proposal superseding it, so including them would hide every case this
#: module exists to surface.
IDENTITY: Final[tuple[str, ...]] = ("strain", "quantity_kind", "value", "unit", "publication_id")

_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def _strain_id(name: str) -> str:
    """Mirror of `promote._strain_id`, so the key matches what promotion would actually write."""
    return "YAA:STRAIN:" + _SLUG_RE.sub("-", str(name).strip().lower()).strip("-")


@dataclass(frozen=True)
class DuplicateReport:
    """One pending proposal and the promoted row it would duplicate."""

    task_id: str
    measurement_id: str
    strain_id: str
    value: Any
    unit: str
    publication_id: str
    #: Fields the proposal carries and the promoted row leaves NULL. Non-empty means the proposal
    #: is richer, which is the supersession case rather than a plain repeat.
    adds: tuple[str, ...]

    @property
    def supersedes(self) -> bool:
        return bool(self.adds)

    def line(self) -> str:
        verdict = f"richer (adds {', '.join(self.adds)})" if self.adds else "no new fields"
        return (
            f"{self.task_id}  ->  {self.measurement_id}  "
            f"{self.strain_id} {self.value} {self.unit}  [{verdict}]"
        )


#: Proposal payload key -> promoted column, for the fields a supersession typically adds.
#:
#: `time_h` is NOT here, and finding out why was worth the detour: `measurement` has no time
#: column. Time lives on `condition_context` (schema.sql), `promote.py` never mentions `time_h` at
#: all, and `condition_context` holds zero rows. So the extractor collects "at 24 h" per
#: measurement -- `schemas.py` asks for it explicitly -- and promotion drops it on the floor.
#:
#: That is a real loss rather than a tidy-up: in a fermentation atlas 1.62 g/L at 24 h and the
#: same titer at 72 h are different claims, and the 2026-09-22 batch carries both. Comparing on it
#: here would have reported a richness the atlas cannot actually store, so it is left out and
#: written down instead.
_RICHER_FIELDS: Final[Mapping[str, str]] = {
    "basis": "basis",
    "source_locator": "source_locator",
}


def find_duplicates(
    conn: sqlite3.Connection, *, statuses: Sequence[str] = ("pending", "accepted", "edited")
) -> tuple[DuplicateReport, ...]:
    """Proposals whose measurement the atlas already holds under a different id. Read-only."""
    promoted: dict[tuple[Any, ...], sqlite3.Row] = {}
    for row in conn.execute("SELECT * FROM measurement"):
        key = (
            row["strain_id"],
            row["quantity_kind"],
            row["value_as_reported"],
            row["unit_as_reported"],
            row["publication_id"],
        )
        promoted.setdefault(key, row)

    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        "SELECT id, publication_id, payload, edited_payload FROM curation_task "  # noqa: S608
        f"WHERE record_kind = 'measurements' AND status IN ({placeholders}) ORDER BY id",
        tuple(statuses),
    ).fetchall()

    found: list[DuplicateReport] = []
    for row in rows:
        try:
            payload = json.loads(str(row["edited_payload"] or row["payload"]))
        except json.JSONDecodeError:
            continue
        name = payload.get("strain_name_as_reported")
        if not name:
            continue
        key = (
            _strain_id(str(name)),
            payload.get("quantity_kind"),
            payload.get("value"),
            payload.get("unit"),
            row["publication_id"],
        )
        existing = promoted.get(key)
        if existing is None:
            continue
        adds = tuple(
            field
            for field, column in _RICHER_FIELDS.items()
            if payload.get(field) not in (None, "") and existing[column] in (None, "")
        )
        found.append(
            DuplicateReport(
                task_id=str(row["id"]),
                measurement_id=str(existing["id"]),
                strain_id=key[0],
                value=payload.get("value"),
                unit=str(payload.get("unit")),
                publication_id=str(row["publication_id"]),
                adds=adds,
            )
        )
    return tuple(found)
