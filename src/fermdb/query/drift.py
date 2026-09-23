"""Stored values that fall outside a closed vocabulary, reported and never repaired.

A controlled vocabulary added after rows already exist has two halves. The first is stopping new
drift, which happens where values enter: `extract.schemas` offers `quantity_kind` as a closed
choice, and `curate.promote` refuses a value outside the file on the way to a row. The second is
saying what the existing rows hold, which is this module.

**Why it reports rather than remaps.** The 17 drifted values measured on 2026-09-24 are not typos
of the 14 good ones. They are sentences:

    percent_decrease_in_isobutanol_titer_upon_valine_feeding
    isobutanol concentration on SC agar permitting growth
    LC50 (approximate, growth reduced by slightly more than half)

Each one carries something the vocabulary cannot: a control, a feeding condition, an agar plate,
a hedge about how the number was read. An automatic remap onto `percent_change` or
`inhibitory_concentration` would be right about the kind and would silently delete the rest --
and the rest is the only place it is written down, because `condition_context` is empty for every
one of these rows. So the remap is a curator's edit, made with the paper open, and what this
module produces is the worklist for it.

**The count is the point, not the list.** 21 distinct values over 105 rows means the column can
be grouped by for 70 of them (`titer` and `yield`) and is prose for the rest. Reporting that as a
number is what makes it a decision rather than a vague sense that the column is untidy.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..db.vocabularies import read_tsv

__all__ = [
    "QUANTITY_KINDS_FILE",
    "DriftReport",
    "DriftedValue",
    "format_report",
    "quantity_kind_drift",
]

QUANTITY_KINDS_FILE: Final[str] = "quantity_kinds.tsv"


@dataclass(frozen=True, slots=True)
class DriftedValue:
    """One stored value outside the vocabulary, with enough to act on it."""

    value: str
    count: int
    measurement_ids: tuple[str, ...]
    publication_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriftReport:
    vocabulary: tuple[str, ...]
    #: Values inside the vocabulary, with their counts. Reported alongside the drift because
    #: "17 values are wrong" and "17 values are wrong and they cover 23 of 105 rows" are
    #: different findings, and only the second one says how much work this is.
    conforming: tuple[tuple[str, int], ...]
    drifted: tuple[DriftedValue, ...]

    @property
    def rows_total(self) -> int:
        return self.rows_conforming + self.rows_drifted

    @property
    def rows_conforming(self) -> int:
        return sum(count for _, count in self.conforming)

    @property
    def rows_drifted(self) -> int:
        return sum(value.count for value in self.drifted)


def load_vocabulary(vocabularies_dir: Path) -> tuple[str, ...]:
    """The closed `quantity_kind` values, in file order."""
    return tuple(
        row["quantity_kind"].strip()
        for row in read_tsv(vocabularies_dir / QUANTITY_KINDS_FILE)
        if row.get("quantity_kind", "").strip()
    )


def quantity_kind_drift(conn: sqlite3.Connection, vocabularies_dir: Path) -> DriftReport:
    """Every stored `measurement.quantity_kind`, split by whether the vocabulary admits it."""
    vocabulary = load_vocabulary(vocabularies_dir)
    allowed = frozenset(vocabulary)
    conforming: list[tuple[str, int]] = []
    drifted: list[DriftedValue] = []
    for kind, count in conn.execute(
        "SELECT quantity_kind, COUNT(*) FROM measurement GROUP BY quantity_kind "
        "ORDER BY COUNT(*) DESC, quantity_kind"
    ):
        if str(kind) in allowed:
            conforming.append((str(kind), int(count)))
            continue
        rows = conn.execute(
            "SELECT id, COALESCE(publication_id, '') FROM measurement "
            "WHERE quantity_kind = ? ORDER BY id",
            (str(kind),),
        ).fetchall()
        drifted.append(
            DriftedValue(
                value=str(kind),
                count=int(count),
                measurement_ids=tuple(str(row[0]) for row in rows),
                publication_ids=tuple(sorted({str(row[1]) for row in rows if row[1]})),
            )
        )
    return DriftReport(vocabulary=vocabulary, conforming=tuple(conforming), drifted=tuple(drifted))


def format_report(report: DriftReport) -> str:
    """A worklist a curator can read top to bottom, heaviest first."""
    lines: list[str] = [
        f"measurement.quantity_kind: {report.rows_total} rows, "
        f"{len(report.conforming) + len(report.drifted)} distinct values",
        f"  in vocabulary:     {report.rows_conforming} rows over {len(report.conforming)} values",
        f"  outside it:        {report.rows_drifted} rows over {len(report.drifted)} values",
    ]
    if report.conforming:
        lines.append("")
        lines.append("conforming:")
        lines.extend(f"  {count:>4}  {kind}" for kind, count in report.conforming)
    if report.drifted:
        lines.append("")
        lines.append("outside the vocabulary — each needs a curator, not a mapping:")
        for value in report.drifted:
            papers = ", ".join(value.publication_ids) or "no publication recorded"
            lines.append(f"  {value.count:>4}  {value.value}")
            lines.append(f"        {papers}")
            lines.append(f"        {', '.join(value.measurement_ids)}")
    return "\n".join(lines)


def _main() -> int:  # pragma: no cover - a convenience entry point, not part of the API
    """``python -m fermdb.query.drift`` against the configured database. Reads only."""
    from ..config import Settings
    from ..db import open_db

    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    try:
        print(format_report(quantity_kind_drift(conn, settings.path("vocabularies_dir"))))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
