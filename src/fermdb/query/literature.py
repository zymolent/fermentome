"""The Literature read: how a corpus of 5,164 papers narrowed, and where it stalled.

`publications.py` answers "what is in this paper". This module answers the question one level
up -- *which* papers, and why the others were dropped -- because that is the shape a reader
needs before any single paper is worth opening.

The corpus is a funnel with three genuinely different kinds of loss, and a UI that draws them
as one bar is lying about all three:

* **Not screened.** Never had a verdict passed on it. The corpus grew past the classifier.
* **Excluded.** Screened and rejected, with a reason that is a controlled string. Recoverable
  by changing the rubric -- and this corpus has had three such rescues already.
* **Admitted but unreadable.** Passed screening, and the full text is not held. The most
  expensive loss, because the decision to want it has already been paid for.

Each is a different remedy (screen more, re-screen, acquire), so each is a separate number.

**Nothing here writes.** Every read goes through `builder.Select`, which cannot emit anything
but a SELECT, so the layering rule of PLAN.md D.3 is enforced by the type rather than by
convention.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Select

__all__ = [
    "AcquisitionState",
    "FunnelStage",
    "LiteratureOverview",
    "read_overview",
    "screening_families",
]


#: Storage states of `fulltext_asset` that mean the text can actually be read. Everything else
#: -- a resolved URL, a failed fetch, a queued download -- is a paper we know *about*.
READABLE_STATES: frozenset[str] = frozenset({"stored_fulltext"})


@dataclass(frozen=True)
class FunnelStage:
    """One narrowing of the corpus, with what it would take to widen it again.

    ``remedy`` is the field that makes this worth rendering. A count of exclusions is trivia;
    a count of exclusions next to "re-screening reverses this" is a piece of work someone can
    pick up.
    """

    key: str
    label: str
    count: int
    note: str
    remedy: str | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "count": self.count,
            "note": self.note,
        }
        if self.remedy is not None:
            payload["remedy"] = self.remedy
        return payload


@dataclass(frozen=True)
class AcquisitionState:
    """Where full text stands: held, attempted and failed, or waiting on a human.

    `manual_download_queue` is separated from a fetch error on purpose. A failed fetch is a
    retry; a queued manual download is a publisher that will not serve a robot, and no amount
    of retrying changes it.
    """

    readable: int
    by_storage_state: dict[str, int]
    manual_queue: int
    fetch_errors: int

    def as_json(self) -> dict[str, Any]:
        return {
            "readable": self.readable,
            "by_storage_state": self.by_storage_state,
            "manual_queue": self.manual_queue,
            "fetch_errors": self.fetch_errors,
            "note": (
                "a manual queue entry is not a retry -- it is a publisher that will not serve "
                "an automated fetch, and it clears only by hand"
            ),
        }


@dataclass(frozen=True)
class LiteratureOverview:
    """The whole Literature landing payload, in one read."""

    publications: int
    screened: int
    stages: tuple[FunnelStage, ...]
    by_family: dict[str, int]
    by_triage_state: dict[str, int]
    by_decision: dict[str, int]
    by_decider_kind: dict[str, int]
    by_source: tuple[tuple[str, int], ...]
    by_year: tuple[tuple[int, int], ...]
    acquisition: AcquisitionState
    search_runs: int

    def as_json(self) -> dict[str, Any]:
        return {
            "publications": self.publications,
            "screened": self.screened,
            "stages": [stage.as_json() for stage in self.stages],
            "by_family": self.by_family,
            "by_triage_state": self.by_triage_state,
            "by_decision": self.by_decision,
            "by_decider_kind": self.by_decider_kind,
            "by_source": [{"source": source, "count": count} for source, count in self.by_source],
            "decider_note": (
                "a model verdict and a curator's verdict are both stored here and are not "
                "interchangeable -- `decided_by_kind` is the only thing that separates them"
            ),
            "by_year": [{"year": year, "count": count} for year, count in self.by_year],
            "acquisition": self.acquisition.as_json(),
            "search_runs": self.search_runs,
        }


def _counts(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    *,
    distinct_on: str | None = None,
    where: tuple[str, Any] | None = None,
) -> dict[str, int]:
    """``{value: count}`` for one column, skipping NULL, which is not a category."""
    counter = f"COUNT(DISTINCT {distinct_on}) AS n" if distinct_on else "COUNT(*) AS n"
    select = Select(table).columns(f"{column} AS k", counter).group_by(column)
    if where is not None:
        select = select.where(*where)
    return {str(row["k"]): int(row["n"]) for row in select.page(conn) if row["k"] is not None}


def _scalar_int(conn: sqlite3.Connection, select: Select) -> int:
    return int(select.scalar(conn) or 0)


def screening_families(conn: sqlite3.Connection) -> tuple[str, ...]:
    """The screening families present, for a filter control that offers only real options."""
    return tuple(
        str(row["family"])
        for row in Select("screening_record")
        .distinct()
        .columns("family")
        .order_by("family")
        .page(conn)
        if row["family"] is not None
    )


def read_overview(conn: sqlite3.Connection) -> LiteratureOverview:
    """The corpus funnel in one pass.

    Counts are over *distinct publications*, not over rows. A paper can carry several screening
    records (one per family) and several full-text assets (one per resolution attempt), and
    counting rows would report a corpus several times larger than the one that exists.
    """
    publications = _scalar_int(conn, Select("publication").columns("COUNT(*) AS n"))
    screened = _scalar_int(
        conn, Select("screening_record").columns("COUNT(DISTINCT publication_id) AS n")
    )
    readable = _scalar_int(
        conn,
        Select("fulltext_asset")
        .columns("COUNT(DISTINCT publication_id) AS n")
        .where("storage_state = ?", "stored_fulltext"),
    )
    decided = _scalar_int(
        conn, Select("screening_decision").columns("COUNT(DISTINCT publication_id) AS n")
    )
    included = _scalar_int(
        conn,
        Select("screening_decision")
        .columns("COUNT(DISTINCT publication_id) AS n")
        .where("decision = ?", "include"),
    )
    excluded = _scalar_int(
        conn,
        Select("screening_decision")
        .columns("COUNT(DISTINCT publication_id) AS n")
        .where("decision = ?", "exclude"),
    )
    included_readable = _scalar_int(
        conn,
        Select("screening_decision", alias="d")
        .columns("COUNT(DISTINCT d.publication_id) AS n")
        .join("fulltext_asset", "d.publication_id = f.publication_id", alias="f", kind="INNER")
        .where("d.decision = ?", "include")
        .where("f.storage_state = ?", "stored_fulltext"),
    )
    needs_full_text = _scalar_int(
        conn,
        Select("screening_record")
        .columns("COUNT(DISTINCT publication_id) AS n")
        .where("triage_state = ?", "needs_full_text"),
    )

    stages = (
        FunnelStage(
            key="known",
            label="Known to the atlas",
            count=publications,
            note="a row in `publication`: at minimum a title and an identifier",
        ),
        FunnelStage(
            key="screened",
            label="Screened",
            count=screened,
            note="a verdict has been passed, in at least one family",
            remedy=(
                None
                if screened >= publications
                else (
                    f"{publications - screened} never screened -- "
                    "the corpus grew past the classifier"
                )
            ),
        ),
        FunnelStage(
            key="decided",
            label="Verdict recorded",
            count=decided,
            note="a row in `screening_decision`: include, exclude or borderline",
            remedy=(
                None
                if decided >= screened
                else f"{screened - decided} screened with no verdict yet -- a classifier run away"
            ),
        ),
        FunnelStage(
            key="included",
            label="Included",
            count=included,
            note="judged in scope on the evidence seen",
        ),
        FunnelStage(
            key="excluded",
            label="Excluded",
            count=excluded,
            note="judged out of scope, with a recorded reason",
            remedy="re-screening under a corrected rubric reverses this without new acquisition",
        ),
        FunnelStage(
            key="needs_full_text",
            label="Undecidable from the abstract",
            count=needs_full_text,
            note="triaged `needs_full_text`: the abstract does not carry enough to judge",
            remedy="acquire the text, then re-screen -- not a rubric problem",
        ),
        FunnelStage(
            key="readable",
            label="Full text held",
            count=readable,
            note="the text is on disk and can be extracted from",
        ),
        FunnelStage(
            key="included_unreadable",
            label="Included but unreadable",
            count=max(0, included - included_readable),
            note="wanted, and the text is not held -- the most expensive gap in the corpus",
            remedy="acquisition: open-access resolution, then the manual queue",
        ),
    )

    # Not `screening_record.exclusion_reason`: the column exists and is empty in every row, and
    # the reason a paper was dropped is free text on the decision rather than a controlled value.
    # Free text does not make a category, so what gets faceted is the run that made the call.
    by_source = tuple(
        sorted(
            _counts(conn, "screening_decision", "source").items(),
            key=lambda item: -item[1],
        )
    )
    by_year = tuple(
        (int(row["k"]), int(row["n"]))
        for row in Select("publication")
        .columns("year AS k", "COUNT(*) AS n")
        .group_by("year")
        .order_by("year")
        .page(conn)
        if row["k"] is not None
    )

    return LiteratureOverview(
        publications=publications,
        screened=screened,
        stages=stages,
        by_family=_counts(conn, "screening_record", "family", distinct_on="publication_id"),
        by_triage_state=_counts(
            conn, "screening_record", "triage_state", distinct_on="publication_id"
        ),
        by_decision=_counts(conn, "screening_decision", "decision", distinct_on="publication_id"),
        by_decider_kind=_counts(conn, "screening_decision", "decided_by_kind"),
        by_source=by_source,
        by_year=by_year,
        acquisition=AcquisitionState(
            readable=readable,
            by_storage_state=_counts(
                conn, "fulltext_asset", "storage_state", distinct_on="publication_id"
            ),
            manual_queue=_scalar_int(
                conn, Select("manual_download_queue").columns("COUNT(*) AS n")
            ),
            fetch_errors=_scalar_int(
                conn,
                Select("fulltext_asset")
                .columns("COUNT(DISTINCT publication_id) AS n")
                .where("fetch_error IS NOT NULL"),
            ),
        ),
        search_runs=_scalar_int(conn, Select("search_run").columns("COUNT(*) AS n")),
    )
