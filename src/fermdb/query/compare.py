"""Compare: two or more strains or experiments side by side, or a stated refusal to.

PLAN.md P.2 gives this page one job -- *"Refuses or warns when the comparability class
differs"* -- and PLAN.md I.2 makes refusal a feature rather than a failure: *"Refusal is a valid
answer here."*

The verdict is computed here, not in the interface, and there are three of them:

``comparable``
    Every subject resolves to the same ``classified`` comparability class. The aligned metric
    table is built.
``warn``
    The subjects are comparable in principle but something the reader must see is different: the
    classes differ, a class is only ``provisional`` (a class-defining facet has no column, so the
    key is blind to it), or a subject spans more than one context and therefore has no single
    class. The differing facets are named, and the aligned table is built with the warning
    attached.
``refuse``
    No aligned table is produced at all. Either fewer than two subjects resolved, or no subject
    has any comparability class -- which is the atlas's current state, because no measurement
    carries a `sample_id`.

A refusal is **not** a blank page. The subjects' non-contextual attributes -- organism, strain
class, genotype, modification count, design type -- are compared regardless, because those are
properties of the subject rather than of the conditions it was measured under, and comparing
them does not require a comparability class. What a refusal withholds is the one thing that
would be misread: the side-by-side numbers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from fermdb.query.builder import Select
from fermdb.query.conditions import (
    ComparabilityClass,
    ConditionContextRead,
    FacetDifference,
    context_differences,
)
from fermdb.query.experiments import read_experiment
from fermdb.query.records import MeasurementRead
from fermdb.query.strains import read_strain
from fermdb.query.values import Absence, Value, from_text_column

__all__ = [
    "COMPARABLE",
    "KINDS",
    "REFUSE",
    "WARN",
    "Comparison",
    "Metric",
    "Subject",
    "compare",
]

COMPARABLE: Final[str] = "comparable"
WARN: Final[str] = "warn"
REFUSE: Final[str] = "refuse"

#: What may be compared. Two kinds, never mixed in one comparison: a strain and an experiment
#: are not two of a thing, and a table with one of each has no row labels that mean anything.
KINDS: Final[tuple[str, ...]] = ("strain", "experiment")

#: The most subjects one comparison will take. Past this the table stops being readable and
#: starts being a list, and a list is what the Strains page already is.
MAX_SUBJECTS: Final[int] = 6


@dataclass(frozen=True)
class Subject:
    """One side of a comparison."""

    kind: str
    id: str
    label: str
    attributes: tuple[tuple[str, Value[Any]], ...]
    classes: tuple[ComparabilityClass, ...]
    context: ConditionContextRead | None
    context_note: str
    measurements: tuple[MeasurementRead, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "attributes": [
                {"label": label, "value": value.as_json()} for label, value in self.attributes
            ],
            "classes": [klass.as_json() for klass in self.classes],
            "context": None if self.context is None else self.context.as_json(),
            "context_note": self.context_note,
            "measurements": [read.as_json() for read in self.measurements],
        }


@dataclass(frozen=True)
class Metric:
    """One quantity kind and unit, with each subject's value for it.

    Built only when the verdict is not ``refuse``. ``values`` is positional against
    :attr:`Comparison.subjects`, and a subject with no such measurement carries an absence rather
    than a gap in the list -- a shorter row would silently realign the columns.
    """

    quantity_kind: str
    unit: str
    values: tuple[dict[str, Any] | None, ...]
    is_controlled_kind: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "quantity_kind": self.quantity_kind,
            "unit": self.unit,
            "values": list(self.values),
            "is_controlled_kind": self.is_controlled_kind,
        }


@dataclass(frozen=True)
class Comparison:
    """The comparison, or the reason there is not one."""

    kind: str
    requested: tuple[str, ...]
    subjects: tuple[Subject, ...]
    missing: tuple[str, ...]
    verdict: str
    reason: str
    warnings: tuple[str, ...]
    differences: tuple[FacetDifference, ...]
    metrics: tuple[Metric, ...]

    @property
    def differing_facets(self) -> tuple[str, ...]:
        return tuple(
            difference.label
            for difference in self.differences
            if difference.differs and not difference.within_tolerance
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requested": list(self.requested),
            "subjects": [subject.as_json() for subject in self.subjects],
            "missing": list(self.missing),
            "verdict": self.verdict,
            "reason": self.reason,
            "warnings": list(self.warnings),
            "differences": [difference.as_json() for difference in self.differences],
            "differing_facets": list(self.differing_facets),
            "metrics": [metric.as_json() for metric in self.metrics],
        }


def _refusal(
    kind: str, requested: Sequence[str], missing: Sequence[str], reason: str
) -> Comparison:
    return Comparison(
        kind=kind,
        requested=tuple(requested),
        subjects=(),
        missing=tuple(missing),
        verdict=REFUSE,
        reason=reason,
        warnings=(),
        differences=(),
        metrics=(),
    )


def _strain_subject(conn: sqlite3.Connection, strain_id: str) -> Subject | None:
    read = read_strain(conn, strain_id)
    if read is None:
        return None
    measurements = tuple(
        measurement for group in read.phenotype for measurement in group.measurements
    )
    genotype = (
        Value.known(str(read.genotype[0]["as_reported"]))
        if read.genotype
        else Value.absent(Absence.NOT_RECORDED)
    )
    modifications = ", ".join(
        f"{mod.type}:{mod.target_locus.display}" for mod in read.modifications
    )
    return Subject(
        kind="strain",
        id=read.id,
        label=read.canonical_name,
        attributes=(
            ("organism", read.organism_name),
            ("strain class", read.strain_class),
            ("genotype as reported", genotype),
            (
                "modifications",
                Value.known(modifications) if modifications else Value.absent(Absence.NOT_RECORDED),
            ),
            (
                "lineage",
                Value.known(f"{len(read.lineage.parents)} parent(s)")
                if read.lineage.is_recorded
                else Value.absent(Absence.NOT_RECORDED),
            ),
            ("measurements", Value.known(str(len(measurements)))),
            ("samples", Value.known(str(len(read.samples)))),
            ("confidence", read.confidence),
        ),
        classes=tuple(group.klass for group in read.phenotype),
        context=None,
        context_note=(
            "a strain has no condition context of its own; its class comes from the samples its "
            "measurements belong to"
        ),
        measurements=measurements,
    )


def _experiment_subject(conn: sqlite3.Connection, experiment_id: str) -> Subject | None:
    read = read_experiment(conn, experiment_id)
    if read is None:
        return None
    strains = sorted(
        {str(sample["strain_name"]) for sample in read.samples if sample["strain_name"]}
    )
    context = read.contexts[0] if len(read.contexts) == 1 else None
    if len(read.contexts) > 1:
        note = (
            f"this experiment spans {len(read.contexts)} condition contexts, so it has no single "
            "comparability class; comparing it as one thing would average over conditions the "
            "atlas has taken the trouble to keep apart"
        )
    elif context is None:
        note = read.context_note
    else:
        note = f"one condition context: {context.recorded} of {len(context.facets)} facets recorded"
    return Subject(
        kind="experiment",
        id=read.id,
        label=read.id.replace("YAA:EXPERIMENT:", ""),
        attributes=(
            ("publication", read.publication_id),
            ("objective", read.objective),
            ("design type", read.design_type),
            ("samples", Value.known(str(len(read.samples)))),
            ("samples with a context", Value.known(str(read.samples_with_context))),
            (
                "strains",
                Value.known(", ".join(strains)) if strains else Value.absent(Absence.NOT_RECORDED),
            ),
            ("datasets", Value.known(str(len(read.datasets)))),
            ("measurements", Value.known(str(len(read.measurements)))),
        ),
        classes=(),
        context=context,
        context_note=note,
        measurements=read.measurements,
    )


def _metrics(subjects: Sequence[Subject]) -> tuple[Metric, ...]:
    """One row per (quantity kind, unit), with a cell per subject.

    Keyed by unit as well as kind so that a row never puts g/L beside mg/L under one heading.
    That pairing is the commonest way a side-by-side table lies.
    """
    keys: list[tuple[str, str]] = []
    controlled: dict[tuple[str, str], bool] = {}
    per_subject: list[dict[tuple[str, str], MeasurementRead]] = []
    for subject in subjects:
        found: dict[tuple[str, str], MeasurementRead] = {}
        for read in subject.measurements:
            key = (read.quantity_kind, read.quantity.unit_reported.display)
            if key not in keys:
                keys.append(key)
            controlled[key] = read.as_json()["is_controlled_kind"]
            # Several rows can share a kind for one subject; the first in id order is taken and
            # the rest stay visible in that subject's own measurement list. Picking the largest
            # here would be the leaderboard by another name.
            found.setdefault(key, read)
        per_subject.append(found)

    return tuple(
        Metric(
            quantity_kind=kind,
            unit=unit,
            values=tuple(
                None if (kind, unit) not in found else found[(kind, unit)].as_json()
                for found in per_subject
            ),
            is_controlled_kind=controlled[(kind, unit)],
        )
        for kind, unit in keys
    )


def compare(conn: sqlite3.Connection, *, kind: str, ids: Sequence[str]) -> Comparison:
    """Compare subjects of one kind, or refuse with a reason."""
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {KINDS}")

    requested = tuple(dict.fromkeys(i for i in ids if i.strip()))
    if len(requested) < 2:
        return _refusal(
            kind,
            requested,
            (),
            f"a comparison needs at least two subjects; {len(requested)} distinct id(s) were given",
        )
    if len(requested) > MAX_SUBJECTS:
        return _refusal(
            kind,
            requested,
            (),
            f"{len(requested)} subjects were asked for and at most {MAX_SUBJECTS} are compared "
            "side by side; past that a table stops being a comparison and becomes a list",
        )

    build = _strain_subject if kind == "strain" else _experiment_subject
    subjects: list[Subject] = []
    missing: list[str] = []
    for subject_id in requested:
        subject = build(conn, subject_id)
        if subject is None:
            missing.append(subject_id)
        else:
            subjects.append(subject)

    if len(subjects) < 2:
        return _refusal(
            kind,
            requested,
            missing,
            f"only {len(subjects)} of {len(requested)} requested {kind}(s) exist in the atlas, "
            "so there is nothing to compare them with",
        )

    differences = context_differences([subject.context for subject in subjects])
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"{len(missing)} requested id(s) do not exist in the atlas and are left out: "
            + ", ".join(missing)
        )

    classified = [
        klass
        for subject in subjects
        for klass in subject.classes
        if klass.status in {"classified", "provisional"}
    ]
    contexts = [subject.context for subject in subjects]

    # The refusal case: nothing in this comparison has a comparability class at all, from either
    # arm -- no subject-level context, and no classified class under any subject's measurements.
    if not classified and not any(context is not None for context in contexts):
        reasons = sorted(
            {
                reason
                for subject in subjects
                for klass in subject.classes
                for reason in klass.blocked_by
            }
        ) or [subject.context_note for subject in subjects[:1]]
        return Comparison(
            kind=kind,
            requested=requested,
            subjects=tuple(subjects),
            missing=tuple(missing),
            verdict=REFUSE,
            reason=(
                "no subject in this comparison has a comparability class, so the numbers are not "
                "put side by side: " + "; ".join(reasons)
            ),
            warnings=tuple(warnings),
            differences=differences,
            metrics=(),
        )

    keys = {klass.key for klass in classified} | {
        context.id for context in contexts if context is not None
    }
    differing = [
        difference.label
        for difference in differences
        if difference.differs and not difference.within_tolerance
    ]
    provisional = sorted({blind for klass in classified for blind in klass.blind_to})

    verdict = COMPARABLE
    reason = "every subject falls in the same comparability class"
    if len(keys) > 1 or differing:
        verdict = WARN
        reason = (
            "the subjects are not in the same comparability class. They are shown side by side "
            "with the facets that differ named: " + ", ".join(differing or sorted(keys))
        )
    if provisional:
        verdict = WARN if verdict == COMPARABLE else verdict
        warnings.extend(provisional)
    for subject in subjects:
        if subject.kind == "experiment" and subject.context is None:
            verdict = WARN
            warnings.append(f"{subject.label}: {subject.context_note}")

    return Comparison(
        kind=kind,
        requested=requested,
        subjects=tuple(subjects),
        missing=tuple(missing),
        verdict=verdict,
        reason=reason,
        warnings=tuple(warnings),
        differences=differences,
        metrics=_metrics(subjects),
    )


def suggest(conn: sqlite3.Connection, *, kind: str) -> tuple[dict[str, Any], ...]:
    """Candidate subjects for a comparison, most-populated first.

    Offered so the page opens with something to compare rather than an empty form. Ordered by
    how much is recorded about each, which is a statement about the atlas, not about the
    science.
    """
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {KINDS}")

    if kind == "strain":
        counts = {
            str(row["k"]): int(row["n"])
            for row in Select("measurement")
            .columns("strain_id AS k", "COUNT(*) AS n")
            .group_by("strain_id")
            .page(conn)
            if row["k"] is not None
        }
        rows = [
            {
                "id": str(row["id"]),
                "label": str(row["canonical_name"]),
                "detail": from_text_column(row["strain_class"]).as_json(),
                "weight": counts.get(str(row["id"]), 0),
            }
            for row in Select("strain")
            .columns("id", "canonical_name", "class AS strain_class")
            .where_in("id", sorted(counts) or [""])
            .page(conn, limit=200)
        ]
    else:
        counts = {
            str(row["k"]): int(row["n"])
            for row in Select("sample")
            .columns("experiment_id AS k", "COUNT(*) AS n")
            .group_by("experiment_id")
            .page(conn)
            if row["k"] is not None
        }
        rows = [
            {
                "id": str(row["id"]),
                "label": str(row["id"]).replace("YAA:EXPERIMENT:", ""),
                "detail": from_text_column(row["design_type"]).as_json(),
                "weight": counts.get(str(row["id"]), 0),
            }
            for row in Select("experiment").columns("id", "design_type").page(conn, limit=200)
        ]

    return tuple(sorted(rows, key=lambda row: (-int(row["weight"]), str(row["label"]))))
