"""Turn stored contrasts into assertions the evidence graph can walk.

The transcript layer computed 36 contrasts and attached them to nothing. `analysis_result` held
the numbers, `evidence_item` held **zero** rows of type `correlative_omics`, and
`query traceability` — PLAN.md J.5's CI gate, which walks every active assertion to the
publication or dataset behind it — had nothing to walk. A measurement the evidence graph cannot
reach is a measurement the atlas cannot cite, however carefully it was computed.

This module closes that gap, and the shape of what it writes is the argument:

    assertion:      <part or gene> is_differentially_expressed_in <strain>
      evidence_item: correlative_omics -> analysis_result (the contrast)
                     effect_size = log2 fold change, p_adjusted = the BH-adjusted p

`schema.sql` requires `effect_size` and `p_adjusted` on a `correlative_omics` row and forbids it
from citing a `measurement`. Both constraints are exactly right here and neither is worked
around: a differential expression is a correlation, it carries its own effect and its own
adjusted p, and it must never acquire the authority of a measured titer.

## What gets an assertion, and what deliberately does not

Only a step the route model already cares about, and only where the contrast can carry a claim:

* **A cassette row, where the build carries its own copy.** This is the only honest measurement of
  an engineered step, and it is written as an assertion about the `part`, not about the host's
  native gene — they are different objects and the atlas keeps them apart.
* **Significant, by both thresholds.** A gene must clear the FDR *and* the fold-change floor. A
  change that is significant but small is not evidence that a construct is doing anything at n=3.
* **Never an underpowered null.** A contrast that resolves nothing produces no assertion of "no
  effect". `omics.contrasts` records why: at this replication a null is uninformative, and an
  assertion of `no_effect` would convert missing power into a positive claim.

## Zone and authorship

Zone H: an assertion here is derived from stored data by a documented recipe and rebuilds from it.
`created_by_kind` is `'pipeline'`, which is what this is — not `'curator'`, and not `'agent'`
either, since no model judged anything. The evidence level stays *derived* (PLAN.md J.3) rather
than asserted: correlative omics is L3 by construction, and nothing here overrides that.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

__all__ = [
    "ExpressionAssertion",
    "PREDICATE",
    "assertions_from_support",
    "write_assertions",
]

PREDICATE: Final[str] = "is_differentially_expressed_in"
PIPELINE: Final[str] = "fermdb.omics.evidence"


@dataclass(frozen=True, slots=True)
class ExpressionAssertion:
    """One "<part> is differentially expressed in <strain>" claim and its single evidence item."""

    subject_type: str
    subject_id: str
    strain_id: str
    direction: str
    log2_fold_change: float
    p_adjusted: float
    analysis_id: str
    context_id: str | None
    rationale: str
    gene: str

    @property
    def id(self) -> str:
        digest = hashlib.sha256(
            f"{self.subject_type}|{self.subject_id}|{PREDICATE}|{self.strain_id}|"
            f"{self.analysis_id}".encode()
        ).hexdigest()[:24]
        return f"YAA:ASSERT:de-{digest}"

    @property
    def evidence_id(self) -> str:
        return f"YAA:EVID:de-{self.id.rsplit('-', 1)[-1]}"


def assertions_from_support(
    supports: Sequence[object],
    *,
    contrast_strains: Mapping[str, tuple[str, str]],
    contexts: Mapping[str, str] | None = None,
) -> tuple[ExpressionAssertion, ...]:
    """Read route-step supports and emit one assertion per distinct evidenced step.

    Deduplicated on (part, strain, contrast): 6,400 routes share a few hundred step signatures,
    and writing one assertion per route would produce thousands of identical claims whose only
    difference is which enumeration happened to contain them.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[ExpressionAssertion] = []
    for support in supports:
        for step in getattr(support, "steps", ()):
            if step.status != "elevated_in_build":
                continue
            if step.contrast_id is None or step.log2_fold_change is None:
                continue
            if step.p_adjusted is None:
                # correlative_omics requires p_adjusted; without it there is no row to write and
                # no claim to make.
                continue
            strain_id = contrast_strains.get(step.contrast_id, ("", ""))[1]
            if not strain_id:
                continue
            key = (step.part_id, strain_id, step.contrast_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ExpressionAssertion(
                    subject_type="part",
                    subject_id=step.part_id,
                    strain_id=strain_id,
                    direction="increases" if step.log2_fold_change > 0 else "decreases",
                    log2_fold_change=float(step.log2_fold_change),
                    p_adjusted=float(step.p_adjusted),
                    analysis_id=step.contrast_id,
                    context_id=(contexts or {}).get(step.contrast_id),
                    rationale=step.note,
                    gene=step.genes[0] if step.genes else "",
                )
            )
    return tuple(out)


def write_assertions(
    conn: sqlite3.Connection, assertions: Sequence[ExpressionAssertion]
) -> tuple[int, int]:
    """Write each assertion and its one `correlative_omics` evidence item. Idempotent.

    Returns ``(assertions_written, evidence_items_written)``.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")
    written_assertions = 0
    written_evidence = 0
    for item in assertions:
        before = conn.total_changes
        conn.execute(
            "INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, "
            "object_id, context_id, direction, effect_size, effect_unit, status, "
            "created_by_kind, created_by, created_at, zone, evidence, confidence) "
            "VALUES (?,?,?,?, 'strain', ?, ?, ?, ?, 'log2_fold_change', 'active', "
            "'pipeline', ?, ?, 'H', ?, 'medium') ON CONFLICT(id) DO NOTHING",
            (
                item.id,
                item.subject_type,
                item.subject_id,
                PREDICATE,
                item.strain_id,
                item.context_id,
                item.direction,
                item.log2_fold_change,
                PIPELINE,
                now,
                (
                    f"derived from contrast {item.analysis_id}: {item.rationale[:300]}. "
                    "Correlative omics -- transcript abundance, not flux and not activity"
                ),
            ),
        )
        if conn.total_changes > before:
            written_assertions += 1

        before = conn.total_changes
        conn.execute(
            "INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, "
            "analysis_result_id, contrast_id, effect_size, p_adjusted, status, zone, "
            "evidence, confidence) VALUES (?,?, 'correlative_omics', ?,?,?,?,?, 'active', 'H', "
            "?, 'medium') ON CONFLICT(id) DO NOTHING",
            (
                item.evidence_id,
                item.id,
                item.direction,
                item.analysis_id,
                item.analysis_id,
                item.log2_fold_change,
                item.p_adjusted,
                (
                    f"{item.gene or item.subject_id} in {item.strain_id}: "
                    f"{item.log2_fold_change:+.2f} log2, FDR {item.p_adjusted:.3g}, from "
                    f"{item.analysis_id}"
                ),
            ),
        )
        if conn.total_changes > before:
            written_evidence += 1

        # PLAN.md J.5's gate walks assertion -> evidence -> dataset AND assertion -> who made it.
        # Without this row the chain resolves to "no curator, no date, no rationale", which the
        # gate reports as broken -- correctly, because a claim nobody and nothing owns is not
        # traceable. `action='create'` and `actor_kind='agent'` are what the table permits for a
        # non-human author, and the CHECK that reserves accept/edit/promote for a person is
        # untouched: deriving a claim from stored data is a create, not a judgement.
        conn.execute(
            "INSERT INTO curation_event (id, curator, actor_kind, action, target_type, "
            "target_id, rationale, created_at, zone) VALUES (?,?, 'agent', 'create', "
            "'assertion', ?, ?, ?, 'R') ON CONFLICT(id) DO NOTHING",
            (
                f"YAA:CEVENT:{item.id.rsplit('-', 1)[-1]}",
                PIPELINE,
                item.id,
                (
                    f"derived from contrast {item.analysis_id} by {PIPELINE}: "
                    f"{item.gene or item.subject_id} {item.log2_fold_change:+.2f} log2 in "
                    f"{item.strain_id}, FDR {item.p_adjusted:.3g}. Rebuildable from the stored "
                    "payload; no human judgement entered this row"
                ),
                now,
            ),
        )
    return written_assertions, written_evidence
