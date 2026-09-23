"""The Transcripts read: which sequencing runs exist, and which of them can be used.

A study inventory is easy to render and easy to mislead with. 172 runs across 15 studies sounds
like a transcriptome atlas; it is not one, and the columns that say so are the ones this module
puts first:

* **`acquisition_status` cannot say a run was quantified.** Its CHECK admits only `discovered`,
  `condition_annotated`, `queued` and `excluded` -- none of which means "the reads were fetched
  and counted". An earlier version of this module counted rows equal to `'downloaded'`, a value
  the constraint forbids, so it reported "none downloaded" for a corpus with 99 quantified
  samples sitting on disk. Quantification is recorded in the matrix header and nowhere else, so
  `quantified_runs` is passed in from `fermdb.query.expression` and the status column is reported
  as the triage state it actually is.
* **`library_strategy`** -- 117 of these are RNA-Seq. The rest are amplicon, Tn-Seq and WGS runs
  that arrived with the same BioProjects, and averaging across them is a category error.
* **`reference_match_quality`** -- `species_exact` means the reads were quantified against a
  *different strain's* assembly. For an engineered strain carrying a heterologous cassette, that
  is the difference between a measured transgene and an absent one.
* **`relevance_uncertain`** -- carried from triage. A run nobody has confirmed is relevant is
  not evidence, and it should not silently join a contrast.

Everything is counted per run and per study, and a study's runs are never collapsed into one
number, because a study with 33 runs of which 4 are usable is not "a study".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fermdb.config import Settings
from fermdb.query.builder import Page, Select
from fermdb.query.values import Absence, Value, Zone

__all__ = [
    "StudyRead",
    "TranscriptOverview",
    "list_runs",
    "read_overview",
    "read_study",
]

#: Library strategies whose runs can support an expression statement. Everything else is held
#: for provenance and must never be counted as transcriptome depth.
EXPRESSION_STRATEGIES: frozenset[str] = frozenset({"RNA-Seq"})


def _text(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value.absent(Absence.NOT_RECORDED)
    return Value.known(str(raw), zone=zone)


@dataclass(frozen=True)
class StudyRead:
    """One study, with its runs split by what they can and cannot support."""

    study_accession: str
    dataset_id: Value[str]
    bioproject: Value[str]
    organism: Value[str]
    title: Value[str]
    runs: int
    expression_runs: int
    #: Runs of this study that appear as a column in a quantified matrix. Passed in rather than
    #: derived from `acquisition_status`, which has no value that can express it.
    quantified: int
    excluded: int
    relevance_uncertain: int
    strain_matched: int
    by_strategy: dict[str, int]

    @property
    def usable_note(self) -> str:
        """One sentence a reader can act on, rather than four numbers to combine themselves."""
        if self.expression_runs == 0:
            return "no RNA-Seq runs -- this study cannot support an expression statement"
        if self.quantified == 0:
            return (
                f"{self.expression_runs} RNA-Seq run(s), none of them quantified -- accessions only"
            )
        if self.strain_matched == 0:
            return (
                f"{self.expression_runs} RNA-Seq run(s), quantified against another strain's "
                "assembly -- a heterologous cassette would read as absent"
            )
        return f"{self.expression_runs} RNA-Seq run(s), {self.strain_matched} strain-matched"

    def as_json(self) -> dict[str, Any]:
        return {
            "study_accession": self.study_accession,
            "dataset_id": self.dataset_id.as_json(),
            "bioproject": self.bioproject.as_json(),
            "organism": self.organism.as_json(),
            "title": self.title.as_json(),
            "runs": self.runs,
            "expression_runs": self.expression_runs,
            "quantified": self.quantified,
            "excluded": self.excluded,
            "relevance_uncertain": self.relevance_uncertain,
            "strain_matched": self.strain_matched,
            "by_strategy": self.by_strategy,
            "usable_note": self.usable_note,
        }


@dataclass(frozen=True)
class TranscriptOverview:
    """The Transcripts landing payload."""

    datasets: int
    runs: int
    samples: int
    samples_with_context: int
    studies: tuple[StudyRead, ...]
    #: Runs appearing as a column in a quantified matrix. Counted from the filesystem, because
    #: `acquisition_status` has no value that can express it.
    quantified_runs: int
    by_strategy: dict[str, int]
    by_acquisition_status: dict[str, int]
    by_reference_match: dict[str, int]
    by_repository: dict[str, int]
    analyses: dict[str, int]

    @property
    def expression_runs(self) -> int:
        return sum(
            count
            for strategy, count in self.by_strategy.items()
            if strategy in EXPRESSION_STRATEGIES
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "datasets": self.datasets,
            "runs": self.runs,
            "expression_runs": self.expression_runs,
            "samples": self.samples,
            "samples_with_context": self.samples_with_context,
            "quantified_runs": self.quantified_runs,
            "quantification_note": (
                "quantified runs are counted from the matrix headers, not from "
                "`acquisition_status` -- that column's CHECK has no value meaning the reads were "
                "fetched and counted, so it reads `discovered` even for a run with 99 columns of "
                "TPMs behind it"
            ),
            "samples_without_context": max(0, self.samples - self.samples_with_context),
            "context_note": (
                "a sample with no condition context cannot enter a contrast: there is nothing "
                "to say what it was contrasted against"
            ),
            "studies": [s.as_json() for s in self.studies],
            "by_strategy": self.by_strategy,
            "by_acquisition_status": self.by_acquisition_status,
            "by_reference_match": self.by_reference_match,
            "by_repository": self.by_repository,
            "analyses": self.analyses,
        }


def _counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        (str(row["k"]) if row["k"] is not None else "unrecorded"): int(row["n"])
        for row in Select(table)
        .columns(f"{column} AS k", "COUNT(*) AS n")
        .group_by(column)
        .page(conn)
    }


def _scalar_int(conn: sqlite3.Connection, select: Select) -> int:
    return int(select.scalar(conn) or 0)


def list_runs(
    conn: sqlite3.Connection,
    *,
    study: str | None = None,
    strategy: str | None = None,
    acquisition_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Page:
    """Runs matching the given facets, newest study first."""
    select = Select("sra_run").columns(
        "id",
        "run_accession",
        "study_accession",
        "bioproject",
        "organism",
        "library_strategy",
        "library_layout",
        "platform",
        "instrument_model",
        "spots",
        "bases",
        "size_mb",
        "acquisition_status",
        "reference_assembly",
        "reference_match_quality",
        "relevance_uncertain",
    )
    if study:
        select = select.where("study_accession = ?", study)
    if strategy:
        select = select.where("library_strategy = ?", strategy)
    if acquisition_status:
        select = select.where("acquisition_status = ?", acquisition_status)
    return select.order_by("study_accession", "run_accession").page(
        conn, limit=limit, offset=offset
    )


def _studies(
    conn: sqlite3.Connection, quantified_runs: frozenset[str] = frozenset()
) -> tuple[StudyRead, ...]:
    """Per-study rollups, built from the run rows rather than from a GROUP BY per metric.

    One pass over the runs and the counting happens here. Six correlated subqueries would be the
    obvious SQL and would also be six chances for the filters to drift apart.

    ``quantified_runs`` comes from the matrix headers, because the database has no column that
    can hold it. Defaulting to empty is safe in the honest direction: a caller that does not
    supply it sees "none quantified", which understates rather than invents.
    """
    datasets = {
        str(row["accession"]): row
        for row in Select("dataset")
        .columns("id", "accession", "bioproject", "organism", "title", "repository")
        .page(conn)
        if row["accession"] is not None
    }

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in (
        Select("sra_run")
        .columns(
            "run_accession",
            "study_accession",
            "library_strategy",
            "acquisition_status",
            "reference_match_quality",
            "relevance_uncertain",
        )
        .page(conn)
    ):
        key = str(row["study_accession"]) if row["study_accession"] is not None else "unassigned"
        grouped.setdefault(key, []).append(row)

    studies: list[StudyRead] = []
    for accession, rows in sorted(grouped.items()):
        meta = datasets.get(accession)
        by_strategy: dict[str, int] = {}
        for row in rows:
            key = (
                str(row["library_strategy"])
                if row["library_strategy"] is not None
                else "unrecorded"
            )
            by_strategy[key] = by_strategy.get(key, 0) + 1
        studies.append(
            StudyRead(
                study_accession=accession,
                dataset_id=_text(meta["id"] if meta else None),
                bioproject=_text(meta["bioproject"] if meta else None),
                organism=_text(meta["organism"] if meta else None),
                title=_text(meta["title"] if meta else None),
                runs=len(rows),
                expression_runs=sum(
                    1 for r in rows if str(r["library_strategy"]) in EXPRESSION_STRATEGIES
                ),
                quantified=sum(1 for r in rows if str(r["run_accession"]) in quantified_runs),
                excluded=sum(1 for r in rows if str(r["acquisition_status"]) == "excluded"),
                relevance_uncertain=sum(1 for r in rows if r["relevance_uncertain"]),
                strain_matched=sum(
                    1 for r in rows if str(r["reference_match_quality"]) == "strain_matched"
                ),
                by_strategy=by_strategy,
            )
        )
    return tuple(studies)


def quantified_runs(settings: Settings | None = None) -> frozenset[str]:
    """Every run accession that appears as a column in some quantified matrix.

    Read from the matrix headers because there is nowhere else it is written down:
    `sra_run.acquisition_status` has no value meaning "quantified" (see the module docstring), so
    a run's quantification state is a fact about the filesystem, not about a table.

    A missing matrices directory yields the empty set rather than raising. This is a read for a
    page that must still render when quantification has never been run.
    """
    from fermdb.query.expression import MATRIX_FILES, matrix_samples

    settings = settings or Settings.load()
    found: set[str] = set()
    for filename in MATRIX_FILES.values():
        path = Path(settings.matrices_dir) / filename
        if path.exists():
            found.update(matrix_samples(path))
    return frozenset(found)


def read_study(
    conn: sqlite3.Connection,
    study_accession: str,
    *,
    settings: Settings | None = None,
) -> StudyRead | None:
    """One study's rollup, or None if no run carries that accession."""
    for study in _studies(conn, quantified_runs(settings)):
        if study.study_accession == study_accession:
            return study
    return None


def read_overview(
    conn: sqlite3.Connection, *, settings: Settings | None = None
) -> TranscriptOverview:
    """The Transcripts page payload."""
    quantified = quantified_runs(settings)
    return TranscriptOverview(
        datasets=_scalar_int(conn, Select("dataset").columns("COUNT(*) AS n")),
        runs=_scalar_int(conn, Select("sra_run").columns("COUNT(*) AS n")),
        samples=_scalar_int(conn, Select("sample").columns("COUNT(*) AS n")),
        samples_with_context=_scalar_int(
            conn,
            Select("sample").columns("COUNT(*) AS n").where("condition_context_id IS NOT NULL"),
        ),
        studies=_studies(conn, quantified),
        quantified_runs=len(quantified),
        by_strategy=_counts(conn, "sra_run", "library_strategy"),
        by_acquisition_status=_counts(conn, "sra_run", "acquisition_status"),
        by_reference_match=_counts(conn, "sra_run", "reference_match_quality"),
        by_repository=_counts(conn, "dataset", "repository"),
        analyses=_counts(conn, "analysis_result", "kind"),
    )
