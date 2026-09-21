"""Admission control for the ethanol reference layer — PLAN.md B.3 and phase 2.

The ethanol literature is enormous and the isobutanol programme needs a *reference layer*, not a
survey. So the layer is capped, and admission is by named criterion: a study earns a slot or it is
not admitted. This module is what enforces that, because until now the criteria were prose and the
budget was a table in a document.

**The seven slots** (``docs/reference/ETHANOL_REFERENCE_SLOTS.md``) each answer one question the
isobutanol programme actually asks, and each maps to one criterion E1-E6. Slots 3 and 4 share
criterion E4 because acute shock and adapted growth are *"distinct biology and the plan forbids
merging them"* while resting on the same admission rule.

**The sub-budget is the load-bearing part**, accepted by the owner on 2026-09-20. E5's outer bound
is 642 publications against a ~150 total, so without a per-criterion allocation the broadest
criterion consumes the whole layer and E1-E4 arrive empty. An unspent share is **reported, not
reallocated** -- "we found fewer admissible papers than expected" is a finding about the
literature, not slack to consume.

**Why E6 is here and not in PLAN.md.** PLAN.md's phase-2 acceptance text still reads *"the
criterion set the loader accepts is E1-E5"*. That predates criterion E6 (slot 7, the genetic basis
of industrial performance), which the owner accepted on 2026-09-20 with a 25-publication budget,
which the schema's CHECK constraint already permits, and under which discovery has already tagged
279 records. Enforcing E1-E5 here would reject all of them and make phase 2 unpassable. This
module implements E1-E6 and :data:`PLAN_ACCEPTANCE_DISAGREES` records the discrepancy so it is
visible rather than silently resolved -- amending PLAN.md's acceptance criterion is the owner's
call, not this module's.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ..config import Settings

__all__ = [
    "CRITERION_BUDGET",
    "MEASUREMENT_STUDY_CAP",
    "PLAN_ACCEPTANCE_DISAGREES",
    "PUBLICATION_CAP",
    "SLOTS",
    "AdmissionProblem",
    "BudgetLine",
    "EthanolAdmissionError",
    "Slot",
    "admit",
    "budget_status",
    "validate_admission",
]

#: PLAN.md phase 2 says E1-E5; the schema, the slots document and the owner's accepted budget all
#: say E1-E6. Surfaced rather than silently reconciled.
PLAN_ACCEPTANCE_DISAGREES: Final[str] = (
    "PLAN.md phase-2 acceptance reads 'the criterion set the loader accepts is E1-E5'. E6 was "
    "accepted 2026-09-20 (ETHANOL_REFERENCE_SLOTS.md, slot 7) with a 25-publication budget, is "
    "permitted by the screening_record CHECK constraint, and already tags 279 records. This "
    "module accepts E1-E6; PLAN.md's sentence needs amending by the owner."
)

#: The layer's hard caps (PLAN.md B.1). Slots are the admission mechanism, not an addition to it.
PUBLICATION_CAP: Final[int] = 150
MEASUREMENT_STUDY_CAP: Final[int] = 60


@dataclass(frozen=True)
class Slot:
    """One named question the ethanol layer exists to answer."""

    number: int
    name: str
    criterion: str
    question: str


SLOTS: Final[tuple[Slot, ...]] = (
    Slot(
        1,
        "Anaerobic vs aerobic reference physiology",
        "E3",
        "What does baseline yeast physiology look like, quantitatively?",
    ),
    Slot(
        2,
        "pdc-minus / Pdc-attenuated background",
        "E1",
        "What does removing the pyruvate sink actually cost? (the counterfactual, not the plan)",
    ),
    Slot(3, "Ethanol stress, acute shock", "E4", "What happens on sudden exposure?"),
    Slot(4, "Ethanol stress, adapted growth", "E4", "What happens under chronic exposure?"),
    Slot(
        5,
        "Industrial strain under VHG",
        "E2",
        "What does a high-performing fermentation look like?",
    ),
    Slot(6, "Mitochondrial redox shuttle", "E5", "How do reducing equivalents reach the matrix?"),
    Slot(
        7,
        "Genetic basis of industrial performance",
        "E6",
        "What makes an industrial strain hyper-producing and ethanol-tolerant?",
    ),
)

#: The allocation accepted 2026-09-20. A ceiling per criterion, never a quota to fill.
CRITERION_BUDGET: Final[Mapping[str, int]] = {
    "E5": 45,  # load-bearing for DUET's architecture, and a seventh of its 642 outer bound
    "E6": 25,  # the owner's own question, and partly computable from the genome set
    "E1": 25,  # the counterfactual; needed, but DUET keeps Pdc
    "E2": 20,  # small authoritative set; more would be padding
    "E3": 20,
    "E4": 15,  # split across shock and adapted; ethanol-to-C4 transfer is capped at L3 anyway
}

#: What an E5 record has to actually be about. PLAN.md's phase-2 acceptance singles this criterion
#: out -- "a record admitted under E5 with no ADH3/POS5/shuttle/matrix-cofactor content fails
#: validation" -- because E5 is the broadest criterion and the one most able to swallow the layer.
#: The check is deliberately a content test against the stored full text, not a metadata test: a
#: paper is admitted for what it says, and discovery's keyword tag is a candidate, not a verdict.
_E5_REQUIRED_CONTENT: Final[tuple[tuple[str, str], ...]] = (
    (r"\bADH3\b|\bAdh3p?\b", "ADH3 / Adh3"),
    (r"\bPOS5\b|\bPos5p?\b", "POS5 / Pos5"),
    (r"shuttle", "a redox shuttle"),
    (
        r"(mitochondrial|matrix)[^.]{0,80}NAD(?:\(?P\)?)?H"
        r"|NAD(?:\(?P\)?)?H[^.]{0,80}(mitochondrial|matrix)",
        "matrix NAD(P)H",
    ),
)


class EthanolAdmissionError(RuntimeError):
    """An admission could not be evaluated at all -- a missing row, an unreadable source."""


@dataclass(frozen=True)
class AdmissionProblem:
    """One reason a proposed admission fails. Never a bare bool: the reason is the useful part."""

    code: str
    detail: str


@dataclass(frozen=True)
class BudgetLine:
    """One criterion's share, and what has been spent against it."""

    criterion: str
    budget: int
    admitted: int

    @property
    def remaining(self) -> int:
        return self.budget - self.admitted

    @property
    def overspent(self) -> bool:
        return self.admitted > self.budget


def _slots_for(criterion: str) -> tuple[Slot, ...]:
    return tuple(slot for slot in SLOTS if slot.criterion == criterion)


def _admitted_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Publications admitted per criterion. Admission is ``review_state='accepted'``.

    Counted over DISTINCT publications, not screening rows: one paper can match several families
    and would otherwise be charged to its criterion more than once.
    """
    rows = conn.execute(
        "SELECT admitted_criterion AS c, COUNT(DISTINCT publication_id) AS n "
        "FROM screening_record WHERE review_state = 'accepted' AND admitted_criterion IS NOT NULL "
        "GROUP BY admitted_criterion"
    ).fetchall()
    return {row["c"]: row["n"] for row in rows}


def budget_status(conn: sqlite3.Connection) -> tuple[BudgetLine, ...]:
    """Every criterion's share and what has been spent, largest budget first."""
    spent = _admitted_counts(conn)
    return tuple(
        BudgetLine(criterion=criterion, budget=budget, admitted=spent.get(criterion, 0))
        for criterion, budget in sorted(
            CRITERION_BUDGET.items(), key=lambda item: (-item[1], item[0])
        )
    )


def _e5_content_problems(text: str) -> list[AdmissionProblem]:
    missing = [
        label for pattern, label in _E5_REQUIRED_CONTENT if not re.search(pattern, text, re.I)
    ]
    if len(missing) < len(_E5_REQUIRED_CONTENT):
        return []
    return [
        AdmissionProblem(
            "e5_without_shuttle_content",
            "admitted under E5 but the full text mentions none of "
            + ", ".join(label for _, label in _E5_REQUIRED_CONTENT)
            + ". E5 is the broadest criterion and the one most able to swallow the layer, so "
            "PLAN.md phase 2 singles it out for a content check.",
        )
    ]


def validate_admission(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    publication_id: str,
    criterion: str,
) -> tuple[AdmissionProblem, ...]:
    """Every reason this admission would be wrong, or an empty tuple.

    Returns problems rather than raising, because a curator reviewing a shortlist wants all of
    them at once rather than one per attempt.
    """
    problems: list[AdmissionProblem] = []

    if criterion not in CRITERION_BUDGET:
        problems.append(
            AdmissionProblem(
                "unknown_criterion",
                f"{criterion!r} is not one of {sorted(CRITERION_BUDGET)}. "
                f"Every admitted record names a criterion (PLAN.md phase 2).",
            )
        )
        return tuple(problems)

    row = conn.execute("SELECT 1 FROM publication WHERE id = ?", (publication_id,)).fetchone()
    if row is None:
        raise EthanolAdmissionError(f"no publication row for {publication_id}")

    # A publication can carry several screening rows -- one per query family it matched -- and
    # 103 of them carry BOTH tiers, because a mitochondrial-ethanol paper legitimately answers an
    # isobutanol family too. So the question is whether ANY row puts it in the ethanol tier, not
    # what an arbitrarily chosen row says. An earlier version of this function took `LIMIT 1` with
    # no ORDER BY and refused a genuine E5 candidate as 'wrong_tier' on the strength of its
    # isobutanol row; the bug was invisible until the validator was pointed at real data.
    tiers = {
        row["product_tier"]
        for row in conn.execute(
            "SELECT DISTINCT product_tier FROM screening_record WHERE publication_id = ?",
            (publication_id,),
        ).fetchall()
    }
    if not tiers:
        problems.append(
            AdmissionProblem(
                "not_screened",
                "no screening_record: the paper never came through discovery, so its admission "
                "would not be auditable back to a search run (PLAN.md R.2).",
            )
        )
    elif "ethanol" not in tiers:
        problems.append(
            AdmissionProblem(
                "wrong_tier",
                f"screened only into {sorted(tiers)}; admission criteria belong to the ethanol "
                f"tier only.",
            )
        )

    line = {entry.criterion: entry for entry in budget_status(conn)}[criterion]
    if line.remaining <= 0:
        slots = ", ".join(f"slot {s.number} ({s.name})" for s in _slots_for(criterion))
        problems.append(
            AdmissionProblem(
                "budget_exhausted",
                f"{criterion} is at {line.admitted}/{line.budget} for {slots}. The budget is a "
                f"ceiling, and an unspent share elsewhere is reported rather than reallocated.",
            )
        )

    total = conn.execute(
        "SELECT COUNT(DISTINCT publication_id) AS n FROM screening_record "
        "WHERE review_state = 'accepted' AND admitted_criterion IS NOT NULL"
    ).fetchone()["n"]
    if total >= PUBLICATION_CAP:
        problems.append(
            AdmissionProblem(
                "layer_cap_reached",
                f"the ethanol layer is at {total}/{PUBLICATION_CAP} publications. Filling a slot "
                f"with another study now means removing one, and the swap is recorded.",
            )
        )

    if criterion == "E5":
        # Imported here rather than at module scope: `extract.harness` imports from `literature`,
        # and a top-level import would close the cycle.
        from ..extract.harness import SourceTextError, load_source_text

        try:
            text, _ = load_source_text(conn, settings, publication_id=publication_id)
        except SourceTextError:
            problems.append(
                AdmissionProblem(
                    "e5_unreadable",
                    "E5 requires a content check and no full text is stored, so the check cannot "
                    "run. Acquire the text before admitting under E5.",
                )
            )
        else:
            problems.extend(_e5_content_problems(text))

    return tuple(problems)


def admit(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    publication_id: str,
    criterion: str,
    slot: int | None = None,
) -> tuple[AdmissionProblem, ...]:
    """Admit one publication under one criterion, or return why it cannot be admitted.

    Writes nothing when there are problems. Admission sets ``review_state='accepted'``, which is
    what stops a later discovery run from overwriting the judgement (see the upsert in
    `discovery.py`, which only refreshes triage while `review_state` is still 'proposed').
    """
    problems = validate_admission(
        conn, settings, publication_id=publication_id, criterion=criterion
    )
    if problems:
        return problems

    if slot is not None and slot not in {s.number for s in _slots_for(criterion)}:
        return (
            AdmissionProblem(
                "slot_criterion_mismatch",
                f"slot {slot} does not carry criterion {criterion}; "
                f"{criterion} covers {[s.number for s in _slots_for(criterion)]}.",
            ),
        )

    conn.execute(
        "UPDATE screening_record SET review_state = 'accepted', triage_state = 'included', "
        "admitted_criterion = ?, updated_at = datetime('now') WHERE publication_id = ?",
        (criterion, publication_id),
    )
    conn.commit()
    return ()


def unspent_report(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Lines naming every criterion that did not fill its share.

    Its own function because the slots document requires it: an unspent share "is reported,
    because 'we found fewer admissible papers than expected' is a finding about the literature,
    not slack to consume."
    """
    lines: list[str] = []
    for entry in budget_status(conn):
        if entry.remaining > 0:
            slots = ", ".join(str(s.number) for s in _slots_for(entry.criterion))
            lines.append(
                f"{entry.criterion} (slot {slots}): {entry.admitted}/{entry.budget} admitted, "
                f"{entry.remaining} unspent"
            )
    return tuple(lines)


def readable_candidates(conn: sqlite3.Connection, criterion: str) -> Sequence[sqlite3.Row]:
    """Candidates for a criterion whose full text is actually stored.

    A candidate we cannot read is a candidate we cannot extract, so a shortlist drawn from the
    full tagged pool overstates what is available.
    """
    return conn.execute(
        "SELECT DISTINCT p.id, p.doi, p.title, p.year, p.journal FROM publication p "
        "JOIN screening_record s ON s.publication_id = p.id "
        "JOIN fulltext_asset f ON f.publication_id = p.id "
        "AND f.storage_state = 'stored_fulltext' "
        "WHERE s.admitted_criterion = ? ORDER BY p.year DESC",
        (criterion,),
    ).fetchall()
