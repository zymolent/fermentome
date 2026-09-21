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
from pathlib import Path
from typing import Any, Final

from ..config import Settings

__all__ = [
    "ADMISSIONS_FILE",
    "CRITERION_BUDGET",
    "GAP_KINDS",
    "GAP_STATUSES",
    "MEASUREMENT_STUDY_CAP",
    "MAX_CURATED_CONFIDENCE",
    "PLAN_ACCEPTANCE_DISAGREES",
    "PUBLICATION_CAP",
    "SLOTS",
    "AdmissionProblem",
    "AdmittedRecord",
    "AdmissionsFileError",
    "BudgetLine",
    "EthanolAdmissionError",
    "InstallReport",
    "LayerGap",
    "QuotedSpan",
    "Slot",
    "SpanCheck",
    "admit",
    "budget_status",
    "install_admissions",
    "load_admissions",
    "load_layer_gaps",
    "unspent_report",
    "validate_admission",
    "verify_record_spans",
    "write_layer_gaps",
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

    # `AND product_tier = 'ethanol'` is load-bearing, and its absence was a real defect. A
    # publication carries one screening row per query family it matched, and 103 of them carry
    # BOTH tiers; `validate_admission` was fixed for that case and this writer was not. The
    # unfiltered UPDATE tried to set `admitted_criterion` on the isobutanol rows too and died on
    # the schema's own CHECK -- `admitted_criterion IS NULL OR product_tier = 'ethanol'` -- so
    # every dual-tier paper was unadmittable, with a sqlite3.IntegrityError rather than an
    # AdmissionProblem to explain it. Four of the 23 phase-2 admissions are dual-tier. The filter
    # is also right on its own terms: an ethanol admission is not a verdict on an isobutanol row's
    # triage, and flipping that row to 'included' would overwrite a judgement this call never made.
    conn.execute(
        "UPDATE screening_record SET review_state = 'accepted', triage_state = 'included', "
        "admitted_criterion = ?, updated_at = datetime('now') "
        "WHERE publication_id = ? AND product_tier = 'ethanol'",
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


# ---------------------------------------------------------------------------------------------
# The curated layer: data/literature/ethanol_admissions.yaml
#
# The database holds exactly ONE fact per admitted record -- `screening_record.admitted_criterion`
# -- and that column is where the criterion is enforced, by the two CHECK constraints the schema
# puts on it. Everything else an admission consists of has no column anywhere: the verbatim quote
# and its offsets, why this criterion and not another, what the study lacks, B.3.4's required
# `transfer_rationale` and the `evidence_ceiling` that goes with it.
#
# So the layer lives in two places on purpose, and the split follows the tiers CONVENTIONS.md
# already draws. The committed YAML is repo tier: curated, reviewable in a diff, and the source of
# truth. The database is derived tier and rebuildable, so a criterion that lived only there would
# not survive a rebuild -- which is the whole reason this file exists rather than a one-off script
# that UPDATEs 23 rows.
# ---------------------------------------------------------------------------------------------

#: The curated admission set, under `settings.literature_dir`.
ADMISSIONS_FILE: Final[str] = "ethanol_admissions.yaml"

#: The `knowledge_gap` vocabularies, mirrored from the schema's CHECK constraints. A curated gap
#: naming anything else is a typo, and a typo that reaches the INSERT is an IntegrityError with no
#: line number in it.
GAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        "transport_carrier_unknown",
        "enzyme_unidentified",
        "mechanism_unknown",
        "quantitative_value_missing",
        "never_attempted",
    }
)
GAP_STATUSES: Final[frozenset[str]] = frozenset({"open", "candidate_proposed", "resolved"})

#: What a curated-but-unverified row may claim. 'high' is never writable from memory
#: (CONVENTIONS.md, Curation), and promoting an admission past this is a curator act under
#: PLAN.md L.5 -- so the loader refuses it rather than trusting the file.
MAX_CURATED_CONFIDENCE: Final[frozenset[str]] = frozenset({"unverified", "low", "medium"})


class AdmissionsFileError(RuntimeError):
    """`ethanol_admissions.yaml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class QuotedSpan:
    """A verbatim quote and where it sits in the stored full text.

    0-based half-open ``[char_start, char_end)``, the same convention as the ``span`` table and
    `fermdb.llm.validate.Span`, which is what re-resolves it.
    """

    quote: str
    char_start: int
    char_end: int
    occurrences_in_source: int


@dataclass(frozen=True)
class AdmittedRecord:
    """One publication admitted under one criterion, with what justifies it."""

    publication_id: str
    criterion: str
    slots: tuple[int, ...]
    slot_label: str
    title: str
    measurement_bearing: bool
    verified: bool
    confidence: str
    transfer_rationale: str | None
    evidence_ceiling: str | None
    spans: tuple[QuotedSpan, ...]


@dataclass(frozen=True)
class LayerGap:
    """A `knowledge_gap` the ethanol layer establishes by finding nothing.

    Not a property of a proposed route -- `metabolic.routes` emits those -- but a property of the
    field, reached by reading the corpus. So it carries no ``route_id``, and it is Zone I because
    it is inferred from an absence.
    """

    id: str
    kind: str
    compartment_id: str | None
    description: str
    why_it_matters: str
    status: str
    evidence: str
    confidence: str


@dataclass(frozen=True)
class SpanCheck:
    """One span re-resolved against the stored full text, or the reason it could not be."""

    publication_id: str
    index: int
    ok: bool
    code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class InstallReport:
    """What an install actually did. Never a bare count: the refusals are the useful part."""

    admitted: tuple[str, ...]
    refused: tuple[tuple[str, AdmissionProblem], ...]
    spans_checked: int
    span_failures: tuple[SpanCheck, ...]
    gaps_written: int


def _admissions_path(settings: Settings, path: Path | None) -> Path:
    source = settings.literature_dir / ADMISSIONS_FILE if path is None else path
    if not source.is_file():
        raise AdmissionsFileError(
            f"no admission set at {source}; it is curated and committed, not generated."
        )
    return source


def _read_yaml(source: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise AdmissionsFileError("PyYAML is required to read the admission set") from exc
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdmissionsFileError(f"{source}: the top level is not a mapping")
    return document


def _require_str(source: Path, where: str, value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdmissionsFileError(f"{source}: {where} has no '{field}'")
    return value


def _slots_from(source: Path, where: str, value: object, criterion: str) -> tuple[int, ...]:
    """Slot numbers out of ``2``, ``'3 and 4'`` or ``'slot 1'``, cross-checked against E1-E6.

    One record legitimately fills two slots -- `doi:10.1186/s13068-024-02503-7` serves acute shock
    and adapted growth -- so this is a tuple and not an int.
    """
    label = str(value)
    numbers = tuple(int(match) for match in re.findall(r"\d+", label))
    if not numbers:
        raise AdmissionsFileError(f"{source}: {where} names no slot")
    carried = {slot.number for slot in _slots_for(criterion)}
    wrong = sorted(number for number in numbers if number not in carried)
    if wrong:
        raise AdmissionsFileError(
            f"{source}: {where} is admitted under {criterion} but names slot(s) {wrong}; "
            f"{criterion} covers {sorted(carried)}."
        )
    return numbers


def _spans_from(source: Path, where: str, rows: object) -> tuple[QuotedSpan, ...]:
    if not isinstance(rows, list) or not rows:
        raise AdmissionsFileError(
            f"{source}: {where} carries no 'evidence'. An admission with no quote is an opinion "
            f"about a paper, and the layer records judgements that can be re-read."
        )
    spans: list[QuotedSpan] = []
    for index, row in enumerate(rows):
        at = f"{where} evidence[{index}]"
        if not isinstance(row, dict):
            raise AdmissionsFileError(f"{source}: {at} is not a mapping")
        quote = _require_str(source, at, row.get("quote"), "quote")
        start, end = row.get("char_start"), row.get("char_end")
        if not isinstance(start, int) or isinstance(start, bool):
            raise AdmissionsFileError(f"{source}: {at} char_start is not an integer")
        if not isinstance(end, int) or isinstance(end, bool):
            raise AdmissionsFileError(f"{source}: {at} char_end is not an integer")
        if start < 0 or end <= start:
            raise AdmissionsFileError(
                f"{source}: {at} has offsets [{start}, {end}), which is not a non-empty half-open "
                f"interval"
            )
        if end - start != len(quote):
            raise AdmissionsFileError(
                f"{source}: {at} spans {end - start} characters but its quote is {len(quote)}. "
                f"The offsets and the quote disagree before any source has been consulted."
            )
        occurrences = row.get("occurrences_in_source", 1)
        if not isinstance(occurrences, int) or isinstance(occurrences, bool) or occurrences < 1:
            raise AdmissionsFileError(f"{source}: {at} occurrences_in_source is not a count")
        spans.append(QuotedSpan(quote, start, end, occurrences))
    return tuple(spans)


def load_admissions(settings: Settings, *, path: Path | None = None) -> tuple[AdmittedRecord, ...]:
    """The curated admission set, validated against everything that can be checked offline.

    What it refuses, and why each one is a refusal rather than a warning:

    * **A record with no criterion, or one outside E1-E6.** PLAN.md phase 2's acceptance is
      "no admitted record lacks a criterion", and the schema's CHECK says which six.
    * **A slot that does not carry the record's criterion.** Admitting an E2 paper "into slot 6"
      is a curator slip, and the file is where it would go unnoticed.
    * **`verified: true`, or a confidence above `medium`.** Promotion is a curator act (PLAN.md
      L.5, decision D2); a file that could promote by being edited is not a safe place to put 23
      records.
    * **An E4 record with no `transfer_rationale`.** B.3.4 admits a mechanism *only* with a stated
      argument for transfer to a C4 alcohol. Without the field the criterion is decoration.
    * **A criterion over its sub-budget, or the set over either cap.** The budget is enforced per
      admission by `validate_admission`; checking it here as well means the file cannot be
      *committed* in an over-spent state, which is the state a reviewer would have to catch by eye.
    """
    source = _admissions_path(settings, path)
    document = _read_yaml(source)
    rows = document.get("records")
    if not isinstance(rows, list) or not rows:
        raise AdmissionsFileError(f"{source}: 'records' must be a non-empty list")

    records: list[AdmittedRecord] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"records[{index}]"
        if not isinstance(row, dict):
            raise AdmissionsFileError(f"{source}: {where} is not a mapping")
        publication_id = _require_str(source, where, row.get("publication_id"), "publication_id")
        where = f"{publication_id}"
        if publication_id in seen:
            raise AdmissionsFileError(
                f"{source}: {publication_id} appears twice. One paper, one admission -- a second "
                f"row would charge its criterion twice against the sub-budget."
            )
        seen.add(publication_id)

        raw_criterion = row.get("admitted_criterion")
        if not isinstance(raw_criterion, str) or raw_criterion not in CRITERION_BUDGET:
            raise AdmissionsFileError(
                f"{source}: {where} has admitted_criterion={raw_criterion!r}, not one of "
                f"{sorted(CRITERION_BUDGET)}. PLAN.md phase 2: no admitted record lacks a "
                f"criterion."
            )
        criterion: str = raw_criterion
        slots = _slots_from(source, where, row.get("slot"), criterion)

        verified = row.get("verified")
        if verified is not False:
            raise AdmissionsFileError(
                f"{source}: {where} has verified={verified!r}. This file holds a curation "
                f"proposal; flipping the bit is a curator act (PLAN.md L.5) and is not done by "
                f"editing YAML."
            )
        confidence = _require_str(source, where, row.get("confidence"), "confidence")
        if confidence not in MAX_CURATED_CONFIDENCE:
            raise AdmissionsFileError(
                f"{source}: {where} has confidence={confidence!r}; while verified is false it may "
                f"be one of {sorted(MAX_CURATED_CONFIDENCE)}."
            )

        transfer_rationale = row.get("transfer_rationale")
        if criterion == "E4" and not isinstance(transfer_rationale, str):
            raise AdmissionsFileError(
                f"{source}: {where} is admitted under E4 with no transfer_rationale. B.3.4 admits "
                f"a mechanism only with a stated argument for transfer to a C4 alcohol."
            )

        records.append(
            AdmittedRecord(
                publication_id=publication_id,
                criterion=criterion,
                slots=slots,
                slot_label=str(row.get("slot")),
                title=str(row.get("title") or publication_id),
                measurement_bearing=bool(row.get("measurement_bearing")),
                verified=False,
                confidence=confidence,
                transfer_rationale=(
                    transfer_rationale if isinstance(transfer_rationale, str) else None
                ),
                evidence_ceiling=(
                    row.get("evidence_ceiling")
                    if isinstance(row.get("evidence_ceiling"), str)
                    else None
                ),
                spans=_spans_from(source, where, row.get("evidence")),
            )
        )

    _check_caps(source, records)
    return tuple(records)


def _check_caps(source: Path, records: Sequence[AdmittedRecord]) -> None:
    if len(records) > PUBLICATION_CAP:
        raise AdmissionsFileError(
            f"{source}: {len(records)} records against a {PUBLICATION_CAP}-publication cap"
        )
    measuring = sum(1 for record in records if record.measurement_bearing)
    if measuring > MEASUREMENT_STUDY_CAP:
        raise AdmissionsFileError(
            f"{source}: {measuring} measurement-bearing records against a "
            f"{MEASUREMENT_STUDY_CAP}-study cap"
        )
    for criterion, budget in CRITERION_BUDGET.items():
        spent = sum(1 for record in records if record.criterion == criterion)
        if spent > budget:
            raise AdmissionsFileError(
                f"{source}: {criterion} carries {spent} records against a budget of {budget}. "
                f"The budget is a ceiling, and an unspent share elsewhere is reported rather than "
                f"reallocated."
            )


def verify_record_spans(
    conn: sqlite3.Connection,
    settings: Settings,
    records: Sequence[AdmittedRecord],
) -> tuple[SpanCheck, ...]:
    """Re-resolve every quote against the ``fulltext_asset`` store, exactly.

    **Which text.** `load_source_text` reads the stored asset -- not the corpus cache. They are
    not the same text for every publication and they do not share offsets, and that is not a
    theoretical distinction: the shortlist drafts this set was built from were verified against the
    cache, and two of their quotes do not occur in their paper at all. A quote verified in one
    store is not thereby verified in the other.
    """
    from ..extract.harness import SourceTextError, load_source_text
    from ..llm.validate import Span, verify_span

    checks: list[SpanCheck] = []
    cache: dict[str, str | None] = {}
    for record in records:
        if record.publication_id not in cache:
            try:
                loaded, _ = load_source_text(conn, settings, publication_id=record.publication_id)
            except SourceTextError:
                cache[record.publication_id] = None
            else:
                cache[record.publication_id] = loaded
        text = cache[record.publication_id]
        for index, span in enumerate(record.spans):
            if text is None:
                checks.append(
                    SpanCheck(
                        record.publication_id,
                        index,
                        False,
                        "source_text_unreadable",
                        "no stored full text, so the quote cannot be re-resolved at all",
                    )
                )
                continue
            verdict = verify_span(
                text, Span(quote=span.quote, char_start=span.char_start, char_end=span.char_end)
            )
            checks.append(
                SpanCheck(
                    record.publication_id,
                    index,
                    verdict.ok,
                    None if verdict.ok else verdict.reason,
                    None if verdict.ok else verdict.detail,
                )
            )
    return tuple(checks)


def install_admissions(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    path: Path | None = None,
    verify_spans: bool = True,
) -> InstallReport:
    """Install the curated admission set into a database, refusing anything that does not hold.

    Two gates, and a record has to pass both.

    **Its spans must re-resolve.** A record whose quote no longer occurs at its recorded offsets
    is not installed, and the check is against the ``fulltext_asset`` store rather than any cache.
    Installing it anyway would put a criterion in the database backed by a quote that cannot be
    re-read, which is the failure the offsets exist to make impossible.

    **`validate_admission` must return nothing**, which is where the tier rule, the sub-budget and
    the layer cap are actually enforced. Problems are collected per record rather than raised, so
    one bad record does not hide the other twenty-two.
    """
    records = load_admissions(settings, path=path)

    failures: tuple[SpanCheck, ...] = ()
    checked = 0
    if verify_spans:
        checks = verify_record_spans(conn, settings, records)
        checked = len(checks)
        failures = tuple(check for check in checks if not check.ok)
    blocked = {check.publication_id for check in failures}

    admitted: list[str] = []
    refused: list[tuple[str, AdmissionProblem]] = []
    for record in records:
        if record.publication_id in blocked:
            refused.append(
                (
                    record.publication_id,
                    AdmissionProblem(
                        "span_did_not_re_resolve",
                        "at least one quote did not re-resolve against the stored full text, so "
                        "the admission is not installed. Repair the quote against the source "
                        "rather than loosening the check.",
                    ),
                )
            )
            continue
        problems = admit(
            conn,
            settings,
            publication_id=record.publication_id,
            criterion=record.criterion,
            slot=record.slots[0],
        )
        if problems:
            refused.extend((record.publication_id, problem) for problem in problems)
        else:
            admitted.append(record.publication_id)

    gaps = load_layer_gaps(settings, path=path)
    written = write_layer_gaps(conn, gaps)

    return InstallReport(
        admitted=tuple(admitted),
        refused=tuple(refused),
        spans_checked=checked,
        span_failures=failures,
        gaps_written=written,
    )


def load_layer_gaps(settings: Settings, *, path: Path | None = None) -> tuple[LayerGap, ...]:
    """The `open_gaps` of the admission set, as `knowledge_gap` rows.

    The slots document asks for this in as many words -- gaps are to be recorded "as
    ``knowledge_gap`` rows rather than leaving silence" -- and PLAN.md §2.3 says the atlas records
    a never-attempted experiment as a gap of exactly this shape. The gap belongs beside the
    admissions because it is the *same pass*: it is what the layer found by reading the corpus and
    finding nothing, and separating the finding from the evidence for it is how a gap turns back
    into folklore.
    """
    source = _admissions_path(settings, path)
    document = _read_yaml(source)
    rows = document.get("open_gaps")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise AdmissionsFileError(f"{source}: 'open_gaps' must be a list")

    gaps: list[LayerGap] = []
    for index, row in enumerate(rows):
        where = f"open_gaps[{index}]"
        if not isinstance(row, dict):
            raise AdmissionsFileError(f"{source}: {where} is not a mapping")
        description = _require_str(source, where, row.get("gap"), "gap")
        kind = row.get("kind")
        if kind not in GAP_KINDS:
            raise AdmissionsFileError(
                f"{source}: '{description}' has kind={kind!r}, not one of {sorted(GAP_KINDS)}. "
                f"'kind' is what the gap IS; 'status' is how far it has got."
            )
        status = row.get("status") or "open"
        if status not in GAP_STATUSES:
            raise AdmissionsFileError(
                f"{source}: '{description}' has status={status!r}, not one of "
                f"{sorted(GAP_STATUSES)}"
            )
        confidence = row.get("confidence") or "unverified"
        if confidence not in MAX_CURATED_CONFIDENCE:
            raise AdmissionsFileError(
                f"{source}: '{description}' has confidence={confidence!r}; a gap inferred from an "
                f"absence may claim at most {sorted(MAX_CURATED_CONFIDENCE)}."
            )
        evidence = _require_str(source, where, row.get("evidence"), "evidence")
        slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:40]
        gaps.append(
            LayerGap(
                id=f"YAA:GAP:ethanol-{index}-{slug}",
                kind=str(kind),
                compartment_id=(
                    str(row["compartment"]) if isinstance(row.get("compartment"), str) else None
                ),
                description=description,
                why_it_matters=str(row.get("note") or description),
                status=str(status),
                evidence=evidence,
                confidence=str(confidence),
            )
        )
    return tuple(gaps)


def write_layer_gaps(conn: sqlite3.Connection, gaps: Sequence[LayerGap]) -> int:
    """Store the layer's gaps. Idempotent on id. Zone I: every one is inferred from an absence."""
    for gap in gaps:
        conn.execute(
            "INSERT INTO knowledge_gap (id, kind, compartment_id, description, why_it_matters, "
            "status, zone, evidence, confidence) VALUES (?,?,?,?,?,?,'I',?,?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, description=excluded.description, "
            "why_it_matters=excluded.why_it_matters, status=excluded.status, "
            "evidence=excluded.evidence, confidence=excluded.confidence",
            (
                gap.id,
                gap.kind,
                gap.compartment_id,
                gap.description,
                gap.why_it_matters,
                gap.status,
                gap.evidence,
                gap.confidence,
            ),
        )
    conn.commit()
    return len(gaps)
