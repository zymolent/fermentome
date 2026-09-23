"""The Experiment read: design, the condition context in full, samples, omics and results.

PLAN.md P.2: *"The condition context in full, with 'not recorded' visible."* That is the whole
brief, and it is a brief about absence. Every one of the 15 `experiment` rows in the atlas was
derived from an SRA study rather than from a paper, so `objective`, `design_type` and
`publication_id` are NULL in all of them -- and the `evidence` column holds a long, careful
paragraph explaining *why* the publication link was refused. That paragraph is the most useful
thing on the page and it is returned as a first-class field, not as a debugging aid.

Two further absences are returned rather than papered over:

* **No measurement carries an `experiment_id`.** All 105 point at a strain instead. So the
  production-metrics panel reports zero with the atlas-wide count beside it, which is the
  difference between "this experiment measured nothing" and "no measurement in this atlas is
  attached to any experiment".
* **`analysis_result` reaches an experiment only through a dataset**, and the join is reported
  with its own count so a reader can see how much of the omics arm is actually wired up.

Condition contexts are read through :mod:`fermdb.query.conditions`, which returns all 19 facets
whether or not they are recorded, so "not recorded" is visible by construction rather than by
the interface remembering to render it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Page, Select
from fermdb.query.conditions import ConditionContextRead, read_contexts
from fermdb.query.records import MeasurementRead, list_measurements
from fermdb.query.values import Value, from_text_column

__all__ = [
    "ExperimentRead",
    "ExperimentRow",
    "list_experiments",
    "read_experiment",
]


@dataclass(frozen=True)
class ExperimentRow:
    """One experiment in a list, with what hangs off it."""

    id: str
    publication_id: Value[str]
    objective: Value[str]
    design_type: Value[str]
    zone: Value[str]
    confidence: Value[str]
    samples: int
    samples_with_context: int
    measurements: int

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "publication_id": self.publication_id.as_json(),
            "objective": self.objective.as_json(),
            "design_type": self.design_type.as_json(),
            "zone": self.zone.as_json(),
            "confidence": self.confidence.as_json(),
            "samples": self.samples,
            "samples_with_context": self.samples_with_context,
            "measurements": self.measurements,
        }


@dataclass(frozen=True)
class ExperimentRead:
    """One experiment: everything recorded about it, and the shape of what is not."""

    id: str
    publication_id: Value[str]
    publication_title: Value[str]
    objective: Value[str]
    design_type: Value[str]
    zone: Value[str]
    evidence: Value[str]
    confidence: Value[str]
    samples: tuple[dict[str, Any], ...]
    contexts: tuple[ConditionContextRead, ...]
    datasets: tuple[dict[str, Any], ...]
    analyses: tuple[dict[str, Any], ...]
    measurements: tuple[MeasurementRead, ...]
    measurements_truncated: bool
    measurements_in_atlas: int
    measurements_bound_to_any_experiment: int
    quality_flags: tuple[dict[str, Any], ...]

    @property
    def samples_with_context(self) -> int:
        return sum(1 for sample in self.samples if sample["condition_context_id"])

    @property
    def context_note(self) -> str:
        if not self.samples:
            return "no sample names this experiment, so there is no condition context to show"
        if not self.contexts:
            return (
                f"none of the {len(self.samples)} sample(s) carries a `condition_context_id`, so "
                "nothing is recorded about the conditions any of them was taken under. That is "
                "an absence of metadata, not an absence of conditions"
            )
        return (
            f"{self.samples_with_context} of {len(self.samples)} sample(s) reach a condition "
            f"context; {len(self.contexts)} distinct context(s) cover them"
        )

    @property
    def measurement_note(self) -> str:
        if self.measurements:
            return f"{len(self.measurements)} measurement(s) name this experiment"
        if self.measurements_bound_to_any_experiment == 0:
            return (
                f"no measurement names this experiment -- and none names any experiment: all "
                f"{self.measurements_in_atlas} measurement(s) in the atlas carry a `strain_id` "
                "and a NULL `experiment_id`. This panel is empty because of the schema's "
                "population, not because this experiment produced no numbers"
            )
        return (
            f"no measurement names this experiment, though "
            f"{self.measurements_bound_to_any_experiment} of {self.measurements_in_atlas} in the "
            "atlas name some experiment"
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "publication_id": self.publication_id.as_json(),
            "publication_title": self.publication_title.as_json(),
            "objective": self.objective.as_json(),
            "design_type": self.design_type.as_json(),
            "zone": self.zone.as_json(),
            "evidence": self.evidence.as_json(),
            "confidence": self.confidence.as_json(),
            "samples": [dict(sample) for sample in self.samples],
            "samples_with_context": self.samples_with_context,
            "contexts": [context.as_json() for context in self.contexts],
            "context_note": self.context_note,
            "datasets": [dict(dataset) for dataset in self.datasets],
            "analyses": [dict(analysis) for analysis in self.analyses],
            "measurements": [read.as_json() for read in self.measurements],
            "measurements_truncated": self.measurements_truncated,
            "measurement_note": self.measurement_note,
            "quality_flags": [dict(flag) for flag in self.quality_flags],
        }


def list_experiments(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    has_publication: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[tuple[ExperimentRow, ...], Page]:
    """A page of experiments with their sample and measurement counts."""
    select = Select("experiment").columns(
        "id", "publication_id", "objective", "design_type", "zone", "confidence"
    )
    if q:
        select = select.where("id LIKE ?", f"%{q}%")
    if has_publication is True:
        select = select.where("publication_id IS NOT NULL")
    elif has_publication is False:
        select = select.where("publication_id IS NULL")

    page = select.order_by("id").page(conn, limit=limit, offset=offset)
    ids = [str(row["id"]) for row in page]

    samples: dict[str, int] = {}
    with_context: dict[str, int] = {}
    if ids:
        for row in (
            Select("sample")
            .columns(
                "experiment_id AS k",
                "COUNT(*) AS n",
                "COUNT(condition_context_id) AS with_context",
            )
            .where_in("experiment_id", ids)
            .group_by("experiment_id")
            .page(conn)
        ):
            samples[str(row["k"])] = int(row["n"])
            with_context[str(row["k"])] = int(row["with_context"])

    measurements: dict[str, int] = {}
    if ids:
        for row in (
            Select("measurement")
            .columns("experiment_id AS k", "COUNT(*) AS n")
            .where_in("experiment_id", ids)
            .group_by("experiment_id")
            .page(conn)
        ):
            measurements[str(row["k"])] = int(row["n"])

    rows = tuple(
        ExperimentRow(
            id=str(row["id"]),
            publication_id=from_text_column(row["publication_id"]),
            objective=from_text_column(row["objective"]),
            design_type=from_text_column(row["design_type"]),
            zone=from_text_column(row["zone"]),
            confidence=from_text_column(row["confidence"]),
            samples=samples.get(str(row["id"]), 0),
            samples_with_context=with_context.get(str(row["id"]), 0),
            measurements=measurements.get(str(row["id"]), 0),
        )
        for row in page
    )
    return rows, page


def read_experiment(conn: sqlite3.Connection, experiment_id: str) -> ExperimentRead | None:
    """One experiment, or None."""
    row = (
        Select("experiment")
        .columns(
            "id", "publication_id", "objective", "design_type", "zone", "evidence", "confidence"
        )
        .where("id = ?", experiment_id)
        .one(conn)
    )
    if row is None:
        return None

    samples = tuple(
        dict(sample)
        for sample in Select("sample", alias="sa")
        .columns(
            "sa.id AS id",
            "sa.strain_id AS strain_id",
            "sa.dataset_id AS dataset_id",
            "sa.condition_context_id AS condition_context_id",
            "sa.time_h AS time_h",
            "sa.growth_phase AS growth_phase",
            "sa.zone AS zone",
            "st.canonical_name AS strain_name",
        )
        .join("strain", "st.id = sa.strain_id", alias="st")
        .where("sa.experiment_id = ?", experiment_id)
        .order_by("id")
        .page(conn, limit=500)
    )

    contexts = read_contexts(
        conn,
        [
            str(sample["condition_context_id"])
            for sample in samples
            if sample["condition_context_id"]
        ],
    )

    dataset_ids = sorted({str(sample["dataset_id"]) for sample in samples if sample["dataset_id"]})
    datasets = (
        tuple(
            dict(dataset)
            for dataset in Select("dataset")
            .columns("id", "accession", "repository", "omics_type", "platform", "license")
            .where_in("id", dataset_ids)
            .order_by("id")
            .page(conn)
        )
        if dataset_ids
        else ()
    )

    analyses = (
        tuple(
            dict(analysis)
            for analysis in Select("analysis_result")
            .columns("id", "kind", "payload_ref", "processing_run_id", "zone")
            .where_in("dataset_id", dataset_ids)
            .order_by("id")
            .page(conn, limit=100)
        )
        if dataset_ids
        else ()
    )

    mine, page = list_measurements(conn, experiment_id=experiment_id, limit=200)

    publication_title: Value[str] = from_text_column(None)
    if row["publication_id"]:
        title = (
            Select("publication")
            .columns("title")
            .where("id = ?", str(row["publication_id"]))
            .scalar(conn)
        )
        publication_title = from_text_column(title)

    sample_ids = [str(sample["id"]) for sample in samples]
    flags = (
        tuple(
            dict(flag)
            for flag in Select("data_quality_flag")
            .columns("target_id", "target_type", "kind", "severity", "rationale", "status")
            .where("target_type = ?", "sample")
            .where_in("target_id", sample_ids)
            .page(conn, limit=200)
        )
        if sample_ids
        else ()
    )

    return ExperimentRead(
        id=str(row["id"]),
        publication_id=from_text_column(row["publication_id"]),
        publication_title=publication_title,
        objective=from_text_column(row["objective"]),
        design_type=from_text_column(row["design_type"]),
        zone=from_text_column(row["zone"]),
        evidence=from_text_column(row["evidence"]),
        confidence=from_text_column(row["confidence"]),
        samples=samples,
        contexts=tuple(contexts[key] for key in sorted(contexts)),
        datasets=datasets,
        analyses=analyses,
        measurements=mine,
        measurements_truncated=page.truncated,
        measurements_in_atlas=int(Select("measurement").columns("COUNT(*) AS n").scalar(conn) or 0),
        measurements_bound_to_any_experiment=int(
            Select("measurement")
            .columns("COUNT(*) AS n")
            .where("experiment_id IS NOT NULL")
            .scalar(conn)
            or 0
        ),
        quality_flags=flags,
    )
