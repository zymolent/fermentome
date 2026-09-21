"""PLAN.md J.5's traceability walk: every active assertion, hop by hop, or where it breaks.

J.5 draws the chain and then states its own acceptance test in one sentence: *"a script walks
every active assertion and fails if any one of them cannot produce a complete chain. It runs in
CI. An assertion without a chain is a bug of the same severity as a failing unit test."* The
script did not exist. `curate/assertions.py` checks a subset of the same conditions at write
time and says so in its own report -- *"the J.5 CI walk still does not exist ... my per-write
checks are the cheap half, not a substitute"* -- and it is right about why: a write-time check
sees only rows written through it. It cannot see a fixture loaded straight into the tables, a
row written by an earlier build, a publication deleted after the evidence cited it, or an
assertion whose curation event was never logged. This module is the other half, and it reads
what is actually stored.

**The chain, as this module resolves it.** J.5 writes it as a union::

    assertion -> evidence_item -> { analysis_result -> processing_run -> dataset -> accession }
                                u { extraction -> span -> publication }
                                u { curation_event -> curator -> date -> rationale }

Read literally the union says "at least one arm". Read as the acceptance test it is, it says two
different things about two different kinds of arm, and this module separates them:

* **the source arms** -- the analysis arm and the literature arm. An evidence item must close at
  least one. Which one depends on what kind of evidence it is, and requiring both would make
  every literature assertion a failure.
* **the provenance arm** -- `curation_event`. This is not an alternative to a source; it is the
  answer to *who said this row means that claim, when, and why*. An assertion that resolves to a
  paper but to nobody is exactly the statement PLAN.md L.5 exists to prevent, so it is required
  of every assertion rather than offered as a substitute for a citation.

**What breaks are, and what gaps are.** A *break* is a chain that does not close, and it fails
the walk. A *gap* is a hop J.5 names that the schema has no column to traverse -- there is one,
and it is real: `analysis_result` reaches `processing_run` and stops. Neither `analysis_result`
nor `processing_run` carries a `dataset_id`, so `-> dataset -> accession` cannot be walked at
all today. Failing on that would fail every omics-backed assertion for a schema gap rather than
a curation bug, and staying silent about it would let this check claim to have verified a hop it
never looked at. So it is reported, named, counted, and does not set the exit code. This follows
`query/pathways.py`, which returns the `gaps` a pathway diagram "could not honestly show"
alongside what it can.

**Every break is named and located.** "FAIL" tells a curator nothing; "breaks at evidence_item
YAA:EV:3f: names no publication, analysis_result, processing_run or extraction, so no J.5 source
arm closes" tells them what to go and fix. :data:`BREAK_KINDS` is the closed list, and
:data:`WHY_IT_MATTERS` carries the one-line reason each kind is a bug rather than an untidiness.

**The vacuous walk.** The atlas holds zero assertions today, so a walk that simply reported
success would be a green tick asserting nothing -- and, wired into CI, a green tick that people
learn to trust. :meth:`Walk.is_vacuous` makes that state a distinguishable outcome with its own
exit code (:data:`EXIT_VACUOUS`, 3) rather than folding it into success, and turning it back into
a pass takes an explicit `--allow-empty`. See :func:`exit_code` for the argument in full.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..curate.assertions import OBJECT_TABLES, SUBJECT_TABLES

__all__ = [
    "BREAK_KINDS",
    "CITED_COLUMNS",
    "EXIT_BROKEN",
    "EXIT_OK",
    "EXIT_VACUOUS",
    "GAP_KINDS",
    "WHY_IT_MATTERS",
    "AssertionChain",
    "Break",
    "EvidenceChain",
    "Gap",
    "Walk",
    "exit_code",
    "walk_assertions",
]


#: Exit status: every active assertion resolved a complete chain, and there was at least one.
EXIT_OK: Final[int] = 0
#: Exit status: at least one active assertion could not produce a complete chain.
EXIT_BROKEN: Final[int] = 1
#: Exit status: the walk found nothing to walk. Deliberately not 0; see :func:`exit_code`.
EXIT_VACUOUS: Final[int] = 3


#: Every way a chain can fail to close, as a closed set. Closed on purpose: a break kind is the
#: thing a curator greps for and a dashboard groups by, and a walk that invented a new string per
#: failure would make both useless.
BREAK_KINDS: Final[tuple[str, ...]] = (
    "no_evidence",
    "dangling_subject",
    "dangling_object",
    "evidence_cites_nothing",
    "dangling_citation",
    "span_publication_mismatch",
    "extraction_publication_mismatch",
    "no_curation_event",
    "curation_event_unnamed",
)

#: Hops J.5 names that the current schema cannot traverse. Reported, counted, and never fatal.
GAP_KINDS: Final[tuple[str, ...]] = ("dataset_unreachable",)

#: Why each kind is a bug, in the terms PLAN.md J.5 and L.5 give. Printed next to the count, so
#: a report that lands in a CI log carries its own argument instead of a code to look up.
WHY_IT_MATTERS: Final[Mapping[str, str]] = {
    "no_evidence": (
        "an assertion with no active evidence item is a claim nothing supports. "
        "`assertion_level` grades it NULL with basis 'no_evidence' and the atlas would show a "
        "statement with no badge and no source"
    ),
    "dangling_subject": (
        "`assertion.subject_id` is polymorphic and carries no foreign key -- schema.sql says "
        "SQLite cannot express 'FK into one of eleven tables' -- so a subject that points at "
        "nothing is stored happily and is found only by this walk"
    ),
    "dangling_object": (
        "`assertion.object_id` is polymorphic in the same way as the subject, and a statement "
        "about a row that does not exist is about nothing"
    ),
    "evidence_cites_nothing": (
        "the evidence names no publication, analysis_result, processing_run or extraction, so no "
        "J.5 source arm closes and the claim resolves to no source at all"
    ),
    "dangling_citation": (
        "the evidence cites a row that is not there. Foreign keys are per-connection in SQLite "
        "and a row written on a connection that forgot the pragma, or a source deleted "
        "afterwards, leaves a citation pointing into space"
    ),
    "span_publication_mismatch": (
        "the span resolves to a different paper than the evidence names. A chain that closes "
        "cleanly onto the wrong sentence is worse than one that fails to close, because nothing "
        "about it looks broken"
    ),
    "extraction_publication_mismatch": (
        "the extraction is of a different paper than the evidence names, so the model output "
        "being cited is about something else"
    ),
    "no_curation_event": (
        "no `curation_event` targets this assertion, so J.5's third arm -- curator, date, "
        "rationale -- resolves to nobody. `assertion.created_by` is a string the writer chose; "
        "an event is the logged act, with the reason attached (PLAN.md L.5)"
    ),
    "curation_event_unnamed": (
        "the curation event exists but names no curator, which is a judgement made by nobody"
    ),
    "dataset_unreachable": (
        "J.5's analysis arm continues `-> dataset -> accession` and the schema has no column to "
        "follow: neither `analysis_result` nor `processing_run` carries a dataset id. The walk "
        "verifies the arm as far as it goes and says where it stopped rather than claiming a hop "
        "it did not check"
    ),
}


#: Every column of `evidence_item` that points at another row, and the table it points into.
#: Checked one by one rather than left to the foreign keys, because `PRAGMA foreign_keys` is
#: per-connection (see `fermdb.db`) and a row written without it is exactly what this walk is for.
CITED_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("publication_id", "publication"),
    ("span_id", "span"),
    ("extraction_id", "extraction"),
    ("measurement_id", "measurement"),
    ("analysis_result_id", "analysis_result"),
    ("processing_run_id", "processing_run"),
    ("strain_id", "strain"),
    ("control_strain_id", "strain"),
    ("control_condition_id", "condition_context"),
)

#: The four columns by which an evidence item can reach a source at all (the same four
#: `curate.assertions` requires at write time). If none is set, no source arm can close.
_CHAIN_COLUMNS: Final[tuple[str, ...]] = (
    "publication_id",
    "analysis_result_id",
    "processing_run_id",
    "extraction_id",
)


# ------------------------------------------------------------------------------- what comes back


@dataclass(frozen=True)
class Break:
    """One reason a chain does not close, located at the row it is about."""

    kind: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"breaks at {self.where}: {self.detail}"

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "where": self.where,
            "detail": self.detail,
            "why": WHY_IT_MATTERS.get(self.kind, ""),
        }


@dataclass(frozen=True)
class Gap:
    """A hop J.5 names that the schema cannot traverse. Not a break, and never fatal."""

    kind: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "where": self.where,
            "detail": self.detail,
            "why": WHY_IT_MATTERS.get(self.kind, ""),
        }


@dataclass(frozen=True)
class EvidenceChain:
    """One `evidence_item` and the source arms it does or does not close."""

    evidence_id: str
    evidence_type: str
    #: The hops that resolved, in the order they were followed, e.g.
    #: ``("span YAA:SPAN:a", "publication doi:10.9999/paper-a")``.
    hops: tuple[str, ...] = ()
    #: Which J.5 source arms closed: 'literature', 'analysis'.
    arms: tuple[str, ...] = ()
    breaks: tuple[Break, ...] = ()
    gaps: tuple[Gap, ...] = ()

    @property
    def closes(self) -> bool:
        return not self.breaks and bool(self.arms)

    def as_json(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "closes": self.closes,
            "arms": list(self.arms),
            "hops": list(self.hops),
            "breaks": [b.as_json() for b in self.breaks],
            "gaps": [g.as_json() for g in self.gaps],
        }


@dataclass(frozen=True)
class AssertionChain:
    """One active assertion, walked end to end."""

    assertion_id: str
    predicate: str
    subject_type: str
    subject_id: str
    object_type: str
    object_id: str | None
    zone: str
    evidence: tuple[EvidenceChain, ...] = ()
    #: ``(event_id, curator, created_at)`` for every curation event targeting this assertion.
    curation: tuple[tuple[str, str, str], ...] = ()
    breaks: tuple[Break, ...] = ()
    gaps: tuple[Gap, ...] = ()

    @property
    def closes(self) -> bool:
        """True when nothing on this assertion, or on any of its evidence, is broken."""
        return not self.breaks and all(item.closes for item in self.evidence)

    @property
    def all_breaks(self) -> tuple[Break, ...]:
        return (*self.breaks, *(b for item in self.evidence for b in item.breaks))

    @property
    def all_gaps(self) -> tuple[Gap, ...]:
        return (*self.gaps, *(g for item in self.evidence for g in item.gaps))

    @property
    def subject(self) -> str:
        return f"{self.subject_type} {self.subject_id}"

    @property
    def object(self) -> str:
        return f"{self.object_type} {self.object_id or '(literal)'}"

    def as_json(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "predicate": self.predicate,
            "subject": self.subject,
            "object": self.object,
            "zone": self.zone,
            "closes": self.closes,
            "evidence": [item.as_json() for item in self.evidence],
            "curation_events": [
                {"id": event, "curator": curator, "created_at": at}
                for event, curator, at in self.curation
            ],
            "breaks": [b.as_json() for b in self.all_breaks],
            "gaps": [g.as_json() for g in self.all_gaps],
        }


@dataclass(frozen=True)
class Walk:
    """The whole walk: what was looked at, what closed, and what did not."""

    chains: tuple[AssertionChain, ...]

    @property
    def n_walked(self) -> int:
        return len(self.chains)

    @property
    def broken(self) -> tuple[AssertionChain, ...]:
        return tuple(chain for chain in self.chains if not chain.closes)

    @property
    def n_closed(self) -> int:
        return self.n_walked - len(self.broken)

    @property
    def is_vacuous(self) -> bool:
        """Nothing was walked.

        A distinct state from "everything walked closed", and the whole reason this class reports
        `n_walked` at all. See :func:`exit_code`.
        """
        return self.n_walked == 0

    def breaks_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chain in self.chains:
            for item in chain.all_breaks:
                counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def gaps_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chain in self.chains:
            for gap in chain.all_gaps:
                counts[gap.kind] = counts.get(gap.kind, 0) + 1
        return counts

    def as_json(self) -> dict[str, Any]:
        return {
            "n_walked": self.n_walked,
            "n_closed": self.n_closed,
            "n_broken": len(self.broken),
            "vacuous": self.is_vacuous,
            "breaks_by_kind": self.breaks_by_kind(),
            "gaps_by_kind": self.gaps_by_kind(),
            "assertions": [chain.as_json() for chain in self.chains],
        }


def exit_code(walk: Walk, *, allow_empty: bool = False) -> int:
    """The status a CI gate reads. Three outcomes, not two.

    A walk of nothing is **not** a pass by default, and the argument is the one PLAN.md J.5 makes
    for the check existing at all. J.5 calls a broken chain "a bug of the same severity as a
    failing unit test"; the severity comes from the check being believed. A check that reports
    success because it found nothing to check is believed in exactly the same way and has
    verified nothing, and the atlas holds zero assertions today -- the failure mode is not
    hypothetical, it is the present state. Reporting it as green would mean the first assertion
    ever written enters an atlas whose traceability gate has never once run against a row.

    So the vacuous walk gets its own status, :data:`EXIT_VACUOUS`, and `allow_empty` is what turns
    it back into a pass. That keeps the exemption where it can be seen: it lives as a visible flag
    in `.github/workflows/ci.yml` with a comment saying to delete it, rather than as a silent
    branch in this function. The day the atlas holds assertions, the flag stops mattering and
    removing it changes nothing -- which is the point at which it should go.
    """
    if walk.broken:
        return EXIT_BROKEN
    if walk.is_vacuous:
        return EXIT_OK if allow_empty else EXIT_VACUOUS
    return EXIT_OK


# ----------------------------------------------------------------------------------- the walking


def _exists(conn: sqlite3.Connection, table: str, row_id: str) -> bool:
    # `table` is never caller-supplied: every value comes from CITED_COLUMNS, SUBJECT_TABLES or
    # OBJECT_TABLES, or is a literal in this module.
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone() is not None


def _publication_of(conn: sqlite3.Connection, table: str, row_id: str) -> str | None:
    row = conn.execute(f"SELECT publication_id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return None if row is None or row["publication_id"] is None else str(row["publication_id"])


def _check_subject_and_object(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> tuple[list[Break], list[Gap]]:
    """Hop 0: the statement is about rows that exist.

    `subject_id` and `object_id` are polymorphic and carry no foreign key, so this is the only
    place either is ever checked against the table it claims to point into once the row is
    stored.
    """
    breaks: list[Break] = []
    where = f"assertion {row['id']}"

    subject_table = SUBJECT_TABLES.get(str(row["subject_type"]))
    if subject_table is None:
        breaks.append(
            Break(
                "dangling_subject",
                where,
                f"subject_type {row['subject_type']!r} names no table; it is not one of "
                f"{sorted(SUBJECT_TABLES)}",
            )
        )
    elif not _exists(conn, subject_table, str(row["subject_id"])):
        breaks.append(
            Break(
                "dangling_subject",
                where,
                f"subject is {row['subject_type']} {row['subject_id']!r} and there is no such "
                f"row in `{subject_table}`",
            )
        )

    object_type = str(row["object_type"])
    if object_type != "literal":
        object_table = OBJECT_TABLES.get(object_type)
        object_id = row["object_id"]
        if object_table is None:
            breaks.append(
                Break(
                    "dangling_object",
                    where,
                    f"object_type {object_type!r} names no table; it is not one of "
                    f"{[*sorted(OBJECT_TABLES), 'literal']}",
                )
            )
        elif object_id is None or not _exists(conn, object_table, str(object_id)):
            breaks.append(
                Break(
                    "dangling_object",
                    where,
                    f"object is {object_type} {object_id!r} and there is no such row in "
                    f"`{object_table}`",
                )
            )
    return breaks, []


def _literature_arm(
    conn: sqlite3.Connection, row: sqlite3.Row, where: str, resolved: Mapping[str, bool]
) -> tuple[list[str], list[Break]]:
    """J.5's second arm: extraction -> span -> publication.

    Followed from whichever end the evidence names. A span or an extraction reaches a paper of its
    own, so the arm closes through it even when `publication_id` is NULL -- and when both are
    named and disagree, that disagreement is the break, not the missing hop.
    """
    hops: list[str] = []
    breaks: list[Break] = []
    named = str(row["publication_id"]) if row["publication_id"] else None

    for column, table in (("extraction_id", "extraction"), ("span_id", "span")):
        value = row[column]
        if not value or not resolved[column]:
            continue
        hops.append(f"{table} {value}")
        owner = _publication_of(conn, table, str(value))
        if owner is None:
            breaks.append(
                Break(
                    "dangling_citation",
                    where,
                    f"{table} {value!r} names no publication, so the literature arm stops there",
                )
            )
            continue
        if not _exists(conn, "publication", owner):
            breaks.append(
                Break(
                    "dangling_citation",
                    where,
                    f"{table} {value!r} names publication {owner!r} and there is no such row in "
                    "`publication`",
                )
            )
            continue
        if named is not None and owner != named:
            breaks.append(
                Break(
                    f"{table}_publication_mismatch",
                    where,
                    f"{table} {value!r} belongs to {owner!r}, but the evidence names {named!r}. "
                    "A chain that resolves to the wrong paper is worse than one that does not "
                    "resolve",
                )
            )
            continue
        hops.append(f"publication {owner}")

    if named is not None and resolved["publication_id"] and f"publication {named}" not in hops:
        hops.append(f"publication {named}")
    return hops, breaks


def _analysis_arm(
    conn: sqlite3.Connection, row: sqlite3.Row, where: str, resolved: Mapping[str, bool]
) -> tuple[list[str], list[Break], list[Gap]]:
    """J.5's first arm: analysis_result -> processing_run -> dataset -> accession.

    It stops at `processing_run`, because that is where the schema stops. The remaining two hops
    are reported as a :class:`Gap` rather than walked or assumed.
    """
    hops: list[str] = []
    breaks: list[Break] = []
    gaps: list[Gap] = []

    result_id = row["analysis_result_id"]
    run_id = row["processing_run_id"]
    if result_id and resolved["analysis_result_id"]:
        hops.append(f"analysis_result {result_id}")
        found = conn.execute(
            "SELECT processing_run_id FROM analysis_result WHERE id = ?", (str(result_id),)
        ).fetchone()
        owner = None if found is None else found["processing_run_id"]
        if owner is None or not _exists(conn, "processing_run", str(owner)):
            breaks.append(
                Break(
                    "dangling_citation",
                    where,
                    f"analysis_result {result_id!r} names processing_run {owner!r} and there is "
                    "no such row in `processing_run`, so T.1's recipe does not resolve",
                )
            )
        else:
            hops.append(f"processing_run {owner}")
    elif run_id and resolved["processing_run_id"]:
        hops.append(f"processing_run {run_id}")

    if hops:
        gaps.append(
            Gap(
                "dataset_unreachable",
                where,
                "the analysis arm resolves as far as `processing_run` and stops: neither "
                "`analysis_result` nor `processing_run` carries a dataset id, so J.5's "
                "`-> dataset -> accession` has no column to follow",
            )
        )
    return hops, breaks, gaps


def _walk_evidence(conn: sqlite3.Connection, row: sqlite3.Row) -> EvidenceChain:
    """One evidence item: every cited row exists, and at least one source arm closes."""
    where = f"evidence_item {row['id']}"
    breaks: list[Break] = []
    resolved: dict[str, bool] = {}

    for column, table in CITED_COLUMNS:
        value = row[column]
        if not value:
            resolved[column] = False
            continue
        present = _exists(conn, table, str(value))
        resolved[column] = present
        if not present:
            breaks.append(
                Break(
                    "dangling_citation",
                    where,
                    f"{column} cites {value!r} and there is no such row in `{table}`",
                )
            )

    lit_hops, lit_breaks = _literature_arm(conn, row, where, resolved)
    run_hops, run_breaks, gaps = _analysis_arm(conn, row, where, resolved)
    breaks.extend(lit_breaks)
    breaks.extend(run_breaks)

    arms: list[str] = []
    if any(hop.startswith("publication ") for hop in lit_hops):
        arms.append("literature")
    if any(hop.startswith("processing_run ") for hop in run_hops):
        arms.append("analysis")

    hops = [f"evidence_item {row['id']}"]
    if row["measurement_id"] and resolved["measurement_id"]:
        hops.append(f"measurement {row['measurement_id']}")
    hops.extend(run_hops)
    hops.extend(lit_hops)

    # The arms are what decide it, not the column list: a `span_id` with no `publication_id`
    # still reaches a paper, and calling that "cites nothing" would be a break the atlas does not
    # have. `evidence_cites_nothing` is reserved for an item that names no source at all, and the
    # second branch for one that names a source through which no arm nevertheless closes --
    # reported only when no earlier break already explains why.
    if not arms:
        if not any(row[column] for column in (*_CHAIN_COLUMNS, "span_id")):
            breaks.append(
                Break(
                    "evidence_cites_nothing",
                    where,
                    "names no publication, analysis_result, processing_run or extraction, so no "
                    "J.5 source arm closes. A `measurement` cannot close it either -- "
                    "`measurement` has no publication column at all -- which is why a "
                    "measurement-backed item must still name its paper",
                )
            )
        elif not breaks:
            breaks.append(
                Break(
                    "evidence_cites_nothing",
                    where,
                    "cites a row, but no J.5 source arm closes through it",
                )
            )

    return EvidenceChain(
        evidence_id=str(row["id"]),
        evidence_type=str(row["evidence_type"]),
        hops=tuple(hops),
        arms=tuple(arms),
        breaks=tuple(breaks),
        gaps=tuple(gaps),
    )


def _curation(
    conn: sqlite3.Connection, assertion_id: str
) -> tuple[tuple[tuple[str, str, str], ...], list[Break]]:
    """J.5's third arm: curation_event -> curator -> date -> rationale.

    Required of every assertion rather than offered as an alternative to a citation. `rationale`
    and `created_at` are NOT NULL in the schema, so the only thing that can go missing on a row
    that exists is a curator name that is blank -- and a blank one is a judgement made by nobody.
    """
    rows = conn.execute(
        "SELECT id, curator, created_at FROM curation_event "
        "WHERE target_type = 'assertion' AND target_id = ? ORDER BY created_at, id",
        (assertion_id,),
    ).fetchall()
    where = f"assertion {assertion_id}"
    if not rows:
        return (), [
            Break(
                "no_curation_event",
                where,
                "no `curation_event` has target_type='assertion' and this id, so the chain "
                "resolves to no curator, no date and no rationale",
            )
        ]

    events = tuple(
        (str(row["id"]), str(row["curator"] or ""), str(row["created_at"] or "")) for row in rows
    )
    if not any(curator.strip() for _, curator, _ in events):
        return events, [
            Break(
                "curation_event_unnamed",
                where,
                f"{len(events)} curation event(s) target this assertion and none names a curator",
            )
        ]
    return events, []


def _walk_one(conn: sqlite3.Connection, row: sqlite3.Row) -> AssertionChain:
    breaks, gaps = _check_subject_and_object(conn, row)
    assertion_id = str(row["id"])

    evidence_rows = conn.execute(
        "SELECT * FROM evidence_item WHERE assertion_id = ? AND status = 'active' ORDER BY id",
        (assertion_id,),
    ).fetchall()
    if not evidence_rows:
        held = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_item WHERE assertion_id = ?", (assertion_id,)
        ).fetchone()["n"]
        detail = (
            "no `evidence_item` points at this assertion at all"
            if not held
            else f"all {held} evidence item(s) on this assertion are superseded or retracted, so "
            "nothing active supports it"
        )
        breaks.append(Break("no_evidence", f"assertion {assertion_id}", detail))

    events, curation_breaks = _curation(conn, assertion_id)
    breaks.extend(curation_breaks)

    return AssertionChain(
        assertion_id=assertion_id,
        predicate=str(row["predicate"]),
        subject_type=str(row["subject_type"]),
        subject_id=str(row["subject_id"]),
        object_type=str(row["object_type"]),
        object_id=None if row["object_id"] is None else str(row["object_id"]),
        zone=str(row["zone"]),
        evidence=tuple(_walk_evidence(conn, item) for item in evidence_rows),
        curation=events,
        breaks=tuple(breaks),
        gaps=tuple(gaps),
    )


def walk_assertions(
    conn: sqlite3.Connection, *, assertion_ids: Sequence[str] | None = None
) -> Walk:
    """Walk every active assertion and report, per assertion, where its chain breaks.

    ``assertion_ids`` narrows the walk to named rows, for looking at one thing. It is not a
    sampling knob: the CI gate walks everything, because J.5's acceptance test is *every* active
    assertion and a walk of a subset that reported success would be the same vacuous green tick
    in a different costume.

    Read-only. Nothing here writes, and the connection may be opened ``mode=ro``.
    """
    if assertion_ids is None:
        rows: Iterable[sqlite3.Row] = conn.execute(
            "SELECT * FROM assertion WHERE status = 'active' ORDER BY id"
        ).fetchall()
    else:
        marks = ", ".join("?" for _ in assertion_ids)
        rows = conn.execute(
            f"SELECT * FROM assertion WHERE status = 'active' AND id IN ({marks}) ORDER BY id",
            tuple(assertion_ids),
        ).fetchall()
    return Walk(chains=tuple(_walk_one(conn, row) for row in rows))
