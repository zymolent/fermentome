"""The owner's own include/exclude verdicts, and the working corpus they define.

The atlas holds 5,164 publications. That is the **discovery** layer -- what eight PubMed query
families returned, triaged by `discovery.py` and nothing else. It is not a reading list, and
nobody ever claimed it was; but every count taken off `publication` has quietly been treated as
one.

Meanwhile the owner read 582 PDFs and sorted them into two folders, rejecting 413. None of that
reached the database, because there was nowhere for it to go:

* `screening_record.triage_state` is Zone H, "a deterministic function of query_families.yaml and
  the recorded rule in discovery.py", and the schema says anything else "must never overwrite
  `triage_state` here directly". A human verdict written there is erased by the next
  `fermdb literature discover`, silently, and the papers have to be read again.
* Deleting the rows is worse, and PLAN.md H.3 says why in a sentence worth keeping: **"an excluded
  paper is a decision, not an absence."** A dropped row cannot state its reason, and the next
  discovery run re-adds it with no memory that anybody judged it.

So the verdicts live in `data/literature/screening_decisions.tsv` (the committed curation layer,
keyed by DOI so it survives a rebuild) and load into `screening_decision` (Zone R). `working_ids`
is then the only thing callers need: the publications that are actually in scope.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "DECISIONS_FILE",
    "ScreeningDecision",
    "ScreeningError",
    "corpus_counts",
    "install_decisions",
    "load_decisions",
    "working_ids",
]

DECISIONS_FILE: Final[str] = "screening_decisions.tsv"

_DECISIONS: Final[frozenset[str]] = frozenset({"include", "exclude", "borderline"})
_KINDS: Final[frozenset[str]] = frozenset({"human", "model"})


class ScreeningError(RuntimeError):
    """The decisions file cannot be read, or says something it is not allowed to say."""


@dataclass(frozen=True)
class ScreeningDecision:
    """One curator verdict on one publication."""

    publication_id: str
    decision: str
    reason: str
    source: str
    decided_by: str
    decided_at: str
    #: 'human' | 'model'. A person who opened the PDF and a classifier that scored the title are
    #: not the same grade of evidence, and `install_decisions` refuses to let the second overwrite
    #: the first. Defaults to 'human' because the first 582 verdicts were all read by hand.
    decided_by_kind: str = "human"
    #: Whether the DOI matched a publication when the file was written. Kept as recorded rather
    #: than recomputed: it is a note about the corpus at that moment, not a live fact.
    in_atlas: str = ""
    pdf_file: str = ""


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        # `#` comments carry the file's own rationale and are not data.
        yield from csv.DictReader((ln for ln in handle if not ln.startswith("#")), delimiter="\t")


def load_decisions(path: Path) -> tuple[ScreeningDecision, ...]:
    """Read and validate the committed decisions. Refuses rather than repairs."""
    if not path.exists():
        raise ScreeningError(f"no decisions file at {path}")
    out: list[ScreeningDecision] = []
    seen: set[str] = set()
    for index, row in enumerate(_rows(path), start=1):
        pub = (row.get("publication_id") or "").strip().lower()
        decision = (row.get("decision") or "").strip()
        reason = (row.get("reason") or "").strip()
        if not pub:
            raise ScreeningError(f"row {index}: no publication_id")
        if decision not in _DECISIONS:
            raise ScreeningError(f"row {index}: decision {decision!r} not in {sorted(_DECISIONS)}")
        if not reason:
            # Mirrors screening_record's CHECK: an exclusion with no reason cannot be revisited
            # when the policy changes, which is the one thing this file exists to make possible.
            raise ScreeningError(f"row {index} ({pub}): a decision with no reason is not reusable")
        if pub in seen:
            raise ScreeningError(f"row {index}: {pub} decided twice; one verdict per publication")
        seen.add(pub)
        kind = (row.get("decided_by_kind") or "human").strip() or "human"
        if kind not in _KINDS:
            raise ScreeningError(f"row {index}: decided_by_kind {kind!r} not in {sorted(_KINDS)}")
        out.append(
            ScreeningDecision(
                publication_id=pub,
                decision=decision,
                reason=reason,
                source=(row.get("source") or "").strip(),
                decided_by=(row.get("decided_by") or "").strip(),
                decided_at=(row.get("decided_at") or "").strip(),
                decided_by_kind=kind,
                in_atlas=(row.get("in_atlas") or "").strip(),
                pdf_file=(row.get("pdf_file") or "").strip(),
            )
        )
    return tuple(out)


def install_decisions(
    conn: sqlite3.Connection, decisions: Sequence[ScreeningDecision], *, now: datetime | None = None
) -> dict[str, int]:
    """Write the verdicts into `screening_decision`. Returns what was written and what was not.

    A decision whose publication the atlas does not hold is **skipped, not invented**: writing it
    would need a `publication` row, and manufacturing one from a filename would put a paper in the
    corpus on the strength of a PDF someone happened to save.

    **A model verdict never overwrites a human one.** The first version of this function upserted
    blind, which was fine while the only input was 582 PDFs somebody had read -- and became a
    defect the moment a classifier was pointed at the same table, because a run over 1,606 papers
    would have replaced those 582 without a word. A title-score and an afternoon spent reading the
    paper are not interchangeable. The reverse direction is allowed: a person correcting a
    classifier is the entire point of having a person. Same argument `curation_event.actor_kind`
    already makes by CHECK-ing that accept and promote require a human.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    known = {str(r[0]).lower() for r in conn.execute("SELECT id FROM publication")}
    human_held = {
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT publication_id FROM screening_decision WHERE decided_by_kind = 'human'"
        )
    }
    counts = {"written": 0, "no_such_publication": 0, "kept_human_verdict": 0}
    for item in decisions:
        if item.publication_id not in known:
            counts["no_such_publication"] += 1
            continue
        if item.decided_by_kind == "model" and item.publication_id in human_held:
            counts["kept_human_verdict"] += 1
            continue
        conn.execute(
            "INSERT INTO screening_decision (publication_id, decision, reason, source, "
            "decided_by, decided_by_kind, decided_at, zone, evidence, confidence) "
            "VALUES (?,?,?,?,?,?,?, 'R', ?, ?) "
            "ON CONFLICT(publication_id) DO UPDATE SET decision=excluded.decision, "
            "reason=excluded.reason, source=excluded.source, decided_by=excluded.decided_by, "
            "decided_by_kind=excluded.decided_by_kind, decided_at=excluded.decided_at, "
            "evidence=excluded.evidence, confidence=excluded.confidence",
            (
                item.publication_id,
                item.decision,
                item.reason,
                item.source,
                item.decided_by or "unknown",
                item.decided_by_kind,
                item.decided_at or stamp,
                f"curator verdict recorded from {item.source or 'the screening pass'}"
                + (f" ({item.pdf_file})" if item.pdf_file else "")
                + f"; installed from data/literature/{DECISIONS_FILE}",
                # A read paper is checked; a scored title is a proposal that happens to be stored.
                "high" if item.decided_by_kind == "human" else "unverified",
            ),
        )
        counts["written"] += 1
    conn.commit()
    return counts


def working_ids(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Publications in scope: everything the atlas holds, minus what the owner rejected.

    Deliberately *not* "only what the owner included". 413 papers were read and rejected; the
    rest were mostly never opened, and never-opened is not the same as rejected. Treating the
    unscreened as out of scope would quietly throw away the part of the corpus still to be read.
    """
    rows = conn.execute(
        "SELECT p.id FROM publication p "
        "LEFT JOIN screening_decision d ON d.publication_id = p.id "
        "WHERE d.decision IS NULL OR d.decision <> 'exclude' ORDER BY p.id"
    ).fetchall()
    return tuple(str(r[0]) for r in rows)


def corpus_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Discovered, rejected, working, and how much of the working set anybody has read."""
    total = conn.execute("SELECT count(*) FROM publication").fetchone()[0]
    by_decision = dict(
        conn.execute("SELECT decision, count(*) FROM screening_decision GROUP BY decision")
    )
    excluded = int(by_decision.get("exclude", 0))
    return {
        "discovered": int(total),
        "excluded": excluded,
        "included": int(by_decision.get("include", 0)),
        "borderline": int(by_decision.get("borderline", 0)),
        "working": int(total) - excluded,
        "undecided": int(total) - sum(int(v) for v in by_decision.values()),
    }
