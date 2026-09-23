"""What the atlas may and may not say about attributing an improvement to one genetic change.

PLAN.md I.4 states the problem and the rule in two sentences:

    Most published strains carry several modifications at once, so attributing the improvement to
    any single one is unjustified. Combination strains store their modifications as a set, and
    effect is attributed to the **set**; only a strain differing from its control by one change
    supports a single-gene assertion.

`modification.is_isolated_effect` (schema v18) is where that answer lives. This module is the
small amount of logic that keeps the column meaning what I.4 says it means, and it is mostly a
module about refusing two inferences that both look reasonable.

**The first refusal: one modification row does not mean one modification.** It is tempting to
derive isolation -- count the rows for a strain, and call it isolated when the count is one. That
reads absence of evidence as evidence, and the numbers say how badly it would go here: the atlas
holds **10 modifications against 109 strains**, because a modification row exists only where
somebody extracted and promoted one. Nearly every strain in the atlas would come back "isolated",
including every combination strain nobody has finished curating. The derived answer would be
wrong in the direction that manufactures single-gene assertions, which is the one direction I.4
exists to guard. So :func:`describe_isolation` reports ``not_recorded`` and stops. A curator who
has read the strain table answers it; nothing else may.

**The second refusal: the atlas does not repair the claim it finds suspicious.** Where a row says
``is_isolated_effect = 1`` and the atlas separately holds two or more modifications for that
strain, the two statements cannot both be complete. :func:`isolation_conflicts` reports the pair
and names both sides. It does **not** flip the column, and it does not decide which side is
wrong -- a curator may have recorded isolation against a stated control while the atlas holds a
second modification from a later paper about the same strain, and that is a perfectly ordinary
thing for a corpus to contain. What is not ordinary is nobody noticing.

The conflict is `confounded_measurement` in `data_quality_flag`'s vocabulary -- *"measurable, but
the measurement cannot be attributed"* -- which is I.4's sentence in the words v15 already had.
It is raised against the **strain**, not the modification, because confounding is a property of
the whole modification set rather than of any one member of it, and because a flag on one of the
two rows would imply the other is the innocent one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ..omics.quality import QualityFlag, write_flags

__all__ = [
    "ISOLATION_DETECTOR",
    "IsolationConflict",
    "as_quality_flags",
    "describe_isolation",
    "isolation_conflicts",
    "persist_conflicts",
]

#: `module:rule`, matching the convention the v15 schema comment sets. It is part of the dedup
#: key, so changing it orphans every flag already raised under the old name.
ISOLATION_DETECTOR: Final[str] = "curate.modifications:isolation"

#: What :func:`describe_isolation` may answer. Three states, and the third is not a kind of "no".
RECORDED_ISOLATED: Final[str] = "recorded_isolated"
RECORDED_COMBINATION: Final[str] = "recorded_combination"
NOT_RECORDED: Final[str] = "not_recorded"


@dataclass(frozen=True, slots=True)
class IsolationConflict:
    """A row claiming an isolated effect in a strain the atlas holds several changes for."""

    modification_id: str
    strain_id: str
    #: Every modification the atlas holds for this strain, including the claiming row.
    sibling_ids: tuple[str, ...]
    #: The publications those modifications came from. One paper and several is a different
    #: situation from several papers and several, and the curator needs to see which it is.
    publication_ids: tuple[str, ...]

    @property
    def rationale(self) -> str:
        others = [m for m in self.sibling_ids if m != self.modification_id]
        papers = ", ".join(self.publication_ids) or "no publication recorded"
        return (
            f"{self.modification_id} records is_isolated_effect = 1, but the atlas holds "
            f"{len(self.sibling_ids)} modifications for strain {self.strain_id} "
            f"({', '.join(others)} besides it), from: {papers}. "
            "PLAN.md I.4: effect is attributed to the SET unless the strain differs from its "
            "control by one change, so either the isolation claim is scoped to a control this "
            "row does not name, or the set is the unit and no single-gene assertion stands on "
            "it. Neither side is assumed here and nothing was changed."
        )


def describe_isolation(conn: sqlite3.Connection, modification_id: str) -> str:
    """``recorded_isolated`` / ``recorded_combination`` / ``not_recorded`` for one modification.

    Reads the column and nothing else. The absence of other modification rows for the strain is
    **not** consulted, because it is not evidence -- see this module's docstring.
    """
    row = conn.execute(
        "SELECT is_isolated_effect FROM modification WHERE id = ?", (modification_id,)
    ).fetchone()
    if row is None or row[0] is None:
        return NOT_RECORDED
    return RECORDED_ISOLATED if int(row[0]) == 1 else RECORDED_COMBINATION


def isolation_conflicts(conn: sqlite3.Connection) -> tuple[IsolationConflict, ...]:
    """Rows claiming an isolated effect where the atlas holds more than one change for the strain.

    A modification with no `strain_id` cannot conflict with anything -- there is no set to be part
    of -- and is skipped rather than counted as clean.
    """
    conflicts: list[IsolationConflict] = []
    claiming = conn.execute(
        "SELECT id, strain_id FROM modification "
        "WHERE is_isolated_effect = 1 AND strain_id IS NOT NULL ORDER BY id"
    ).fetchall()
    for modification_id, strain_id in claiming:
        siblings = conn.execute(
            "SELECT id, COALESCE(publication_id, '') FROM modification "
            "WHERE strain_id = ? ORDER BY id",
            (str(strain_id),),
        ).fetchall()
        if len(siblings) < 2:
            continue
        conflicts.append(
            IsolationConflict(
                modification_id=str(modification_id),
                strain_id=str(strain_id),
                sibling_ids=tuple(str(row[0]) for row in siblings),
                publication_ids=tuple(sorted({str(row[1]) for row in siblings if row[1]})),
            )
        )
    return tuple(conflicts)


def as_quality_flags(conflicts: Sequence[IsolationConflict]) -> tuple[QualityFlag, ...]:
    """The conflicts, as `data_quality_flag` rows against the strain.

    ``severity`` is ``warn``, not ``quarantine``. The rows are readable, the measurements behind
    them are real, and nothing downstream should be excluded on the strength of a bookkeeping
    disagreement -- PLAN.md S.3's ``flag``: *visible, still stored*. Quarantining here would
    delete a strain's data over a question about which of two true statements is scoped wrongly.
    """
    return tuple(
        QualityFlag(
            target_type="strain",
            target_id=conflict.strain_id,
            kind="confounded_measurement",
            severity="warn",
            detector=ISOLATION_DETECTOR,
            statistic=float(len(conflict.sibling_ids)),
            threshold=1.0,
            rationale=conflict.rationale,
        )
        for conflict in conflicts
    )


def persist_conflicts(conn: sqlite3.Connection, *, raised_by: str) -> tuple[int, int]:
    """Run the check and write its flags. Returns (written, left alone because already resolved).

    ``raised_by`` is required and not defaulted, for the same reason it is everywhere else in this
    repo: a flag whose origin is "someone" is a flag nobody can follow up.
    """
    return write_flags(
        conn, as_quality_flags(isolation_conflicts(conn)), raised_by=raised_by, actor_kind="agent"
    )
