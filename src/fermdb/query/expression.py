"""The Expression read: a 99-sample transcriptome that lives in files, not in tables.

`query/genes.py` reports expression as an explicit absence, and says why: "the 99-run baseline is
in on-disk matrices, not a table". That was the honest thing to do while nothing could read the
matrices. This module is the reader, so the absence can become a measurement without either of
them lying about where the number came from.

Three things shape everything here.

**The matrix is the source, and it is not in the database.** `s288c.tpm.tsv.gz` holds 6,187 genes
across 99 sequencing runs. Nothing in SQLite mirrors it, so every number this module returns is
read from a file whose path and modification time travel with the payload. A reader that silently
served a stale in-process cache after someone re-ran quantification would be reporting last
week's transcriptome as this week's.

**`sra_run.acquisition_status` cannot say a run was quantified, and reading it as if it could is
a trap.** Its CHECK constraint admits exactly four values -- `discovered`, `condition_annotated`,
`queued`, `excluded` -- and none of them means "the reads were fetched and counted". So every run
in the atlas sits at `discovered` while 99 columns of real TPMs exist on disk, and a reader who
takes that column as a quantification state concludes, wrongly, that nothing was ever downloaded.
It is not a stale column; it is a column answering a different question (where a run sits in
acquisition triage). The matrix header is the only record that a run was quantified, so that is
what this module counts, and `quantified_runs_not_expressible_in_status` states the limitation
rather than dressing it up as a contradiction between two numbers.

**A mitochondrial TPM from a poly(A)-selected library is not a fact about the organelle.** Yeast
mitochondrial transcripts are not polyadenylated the way nuclear ones are, so poly(A) selection
depletes them -- measured on this corpus, a cDNA run puts 0.01% of reads on mitochondrial CDS.
`fermdb.omics.baseline` already works this out and phrases the caveat; this module carries that
object through to the wire rather than restating it, because a caveat that has to be re-derived at
each layer is a caveat that will eventually be dropped at one of them. For a mitochondrial
engineering atlas, that particular silent drop would be the most expensive one available.
"""

from __future__ import annotations

import gzip
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fermdb.config import Settings
from fermdb.omics.baseline import (
    DETECTION_TPM,
    mitochondrial_readout,
    read_matrix,
)
from fermdb.query.builder import Select
from fermdb.query.values import Absence, Value, Zone

__all__ = [
    "ContrastRead",
    "ExpressionOverview",
    "GeneExpression",
    "list_contrasts",
    "matrix_samples",
    "read_gene_expression",
    "read_overview",
]

#: The quantified matrices, by the organism slug the pipeline names them with.
MATRIX_FILES: dict[str, str] = {
    "s288c": "s288c.tpm.tsv.gz",
    "ecoli": "ecoli.tpm.tsv.gz",
    "lcremoris": "lcremoris.tpm.tsv.gz",
}

#: Systematic names on the S288C mitochondrial genome carry this prefix. Derived from the name
#: rather than looked up, so a gene present in the matrix but missing from the gene table still
#: gets the right answer -- and the mtDNA genes are exactly that case.
MITOCHONDRIAL_PREFIX = "Q"

#: The whole of `sra_run.acquisition_status`'s CHECK vocabulary, mirrored from schema.sql.
#: Duplicated here on purpose: this module's central claim is about what that vocabulary *cannot*
#: express, and a claim about a constraint should name the constraint it is about.
ACQUISITION_STATES: frozenset[str] = frozenset(
    {"discovered", "condition_annotated", "queued", "excluded"}
)

#: Those of them that would mean "the reads were fetched and counted". Empty, which is the point:
#: there is no such value, so quantification is unrepresentable in that column and the matrix
#: header is the only place it is recorded. If a migration ever adds one, put it here and the
#: warning stops firing on its own.
QUANTIFICATION_STATES: frozenset[str] = frozenset()


def _matrix_path(settings: Settings, slug: str) -> Path:
    return Path(settings.matrices_dir) / MATRIX_FILES[slug]


def _text(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value.absent(Absence.NOT_RECORDED)
    return Value.known(str(raw), zone=zone)


def matrix_samples(path: Path) -> tuple[str, ...]:
    """The run accessions naming the matrix's columns.

    Read from the header alone; the body is never touched. Callers that only need to know *which*
    runs were quantified should not pay for 6,187 rows of parsing to find out.
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
    return tuple(header[1:])


@dataclass(frozen=True)
class GeneExpression:
    """One gene's expression across every quantified sample.

    ``per_sample`` keeps the run accession beside each value, because a bare list of 99 floats
    cannot be joined back to a condition and is therefore not evidence about anything.
    """

    systematic_name: str
    slug: str
    matrix_path: str
    per_sample: tuple[tuple[str, float], ...]
    is_mitochondrial: bool
    #: Present only where library metadata was available to compute it.
    mitochondrial_caveat: str | None
    usable_samples: tuple[str, ...]

    @property
    def values(self) -> list[float]:
        return [value for _, value in self.per_sample]

    @property
    def detected_in(self) -> int:
        return sum(1 for value in self.values if value >= DETECTION_TPM)

    def as_json(self) -> dict[str, Any]:
        values = self.values
        # A gene absent from every sample has no meaningful spread, and substituting a floor
        # would put a number where an absence belongs.
        spread: Value[float] = (
            Value.known(max(values) / min(values), zone=Zone.HARMONIZED)
            if values and min(values) > 0
            else Value.absent(Absence.NOT_APPLICABLE)
        )
        payload: dict[str, Any] = {
            "systematic_name": self.systematic_name,
            "slug": self.slug,
            "matrix_path": self.matrix_path,
            "samples": len(self.per_sample),
            "per_sample": [{"run": run, "tpm": value} for run, value in self.per_sample],
            # All three go through `Value`. An empty matrix row means "never quantified", and
            # emitting 0.0 for it would be indistinguishable from "quantified, and silent" --
            # which is the exact confusion the value layer exists to prevent.
            "median_tpm": (
                Value.known(statistics.median(values), zone=Zone.HARMONIZED)
                if values
                else Value.absent(Absence.NOT_RECORDED)
            ).as_json(),
            "min_tpm": (
                Value.known(min(values), zone=Zone.HARMONIZED)
                if values
                else Value.absent(Absence.NOT_RECORDED)
            ).as_json(),
            "max_tpm": (
                Value.known(max(values), zone=Zone.HARMONIZED)
                if values
                else Value.absent(Absence.NOT_RECORDED)
            ).as_json(),
            "detected_in": self.detected_in,
            "detection_floor_tpm": DETECTION_TPM,
            "fold_spread": spread.as_json(),
            "is_mitochondrial": self.is_mitochondrial,
        }
        if self.is_mitochondrial:
            # Repeated onto the payload of every mitochondrial gene rather than left on the
            # overview, because this is the number a reader will quote out of context.
            payload["usable_samples"] = len(self.usable_samples)
            payload["caveat"] = self.mitochondrial_caveat or (
                "no library-selection metadata was available, so it is not known how many of "
                "these samples can support a mitochondrial claim"
            )
        return payload


@dataclass(frozen=True)
class ContrastRead:
    """One differential-expression result, as the pipeline recorded it."""

    id: str
    kind: str
    payload_ref: str
    dataset_id: Value[str]
    path: Path | None

    @property
    def exists_on_disk(self) -> bool:
        return self.path is not None and self.path.exists()

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload_ref": self.payload_ref,
            "dataset_id": self.dataset_id.as_json(),
            "path": str(self.path) if self.path else None,
            "exists_on_disk": self.exists_on_disk,
        }


@dataclass(frozen=True)
class ExpressionOverview:
    """What has actually been quantified, against what the run table claims."""

    matrices: tuple[dict[str, Any], ...]
    contrasts: int
    contrasts_on_disk: int
    runs_in_atlas: int
    runs_quantified: int
    acquisition_status: dict[str, int]

    @property
    def quantified_runs_not_expressible_in_status(self) -> bool:
        """True when runs are quantified but no status value can say so.

        Not a contradiction between two numbers -- a gap in one of their vocabularies. Rendering
        `discovered` beside "99 samples quantified" without this note invites the reader to
        conclude the 99 is wrong, and it is the trustworthy one of the pair.
        """
        return self.runs_quantified > 0 and not (
            set(self.acquisition_status) & QUANTIFICATION_STATES
        )

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "matrices": list(self.matrices),
            "contrasts": self.contrasts,
            "contrasts_on_disk": self.contrasts_on_disk,
            "runs_in_atlas": self.runs_in_atlas,
            "runs_quantified": self.runs_quantified,
            "acquisition_status": self.acquisition_status,
            "detection_floor_tpm": DETECTION_TPM,
        }
        if self.quantified_runs_not_expressible_in_status:
            payload["status_warning"] = (
                f"{self.runs_quantified} runs appear as columns in a quantified matrix. "
                "`sra_run.acquisition_status` does not record this and cannot: its CHECK admits "
                f"only {', '.join(sorted(ACQUISITION_STATES))}, none of which means the reads "
                "were fetched and counted. The status column tracks acquisition triage, not "
                "quantification. Read quantification from the matrix; it is the only record of it."
            )
        return payload


def _selection_by_run(conn: sqlite3.Connection) -> dict[str, str | None]:
    """``{run accession: library_selection}``, for the mitochondrial usability split.

    `sra_run` carries `library_strategy` but no `library_selection` column in this schema, so the
    strategy is what is available. It is the honest input: `RNA-Seq` via poly(A) and `RNA-Seq`
    via total RNA are indistinguishable here, which is precisely why the caveat is phrased as a
    limit on what can be claimed rather than as a correction factor.
    """
    return {
        str(row["run_accession"]): (
            str(row["library_strategy"]) if row["library_strategy"] is not None else None
        )
        for row in Select("sra_run").columns("run_accession", "library_strategy").page(conn)
    }


def read_gene_expression(
    conn: sqlite3.Connection,
    systematic_name: str,
    *,
    slug: str = "s288c",
    settings: Settings | None = None,
) -> GeneExpression | None:
    """One gene's profile across the matrix, or None when the matrix has no such row.

    None means "this gene was not quantified", which is a different statement from "this gene is
    not expressed" -- the caller must keep them apart, and returning an empty profile would make
    that impossible.
    """
    settings = settings or Settings.load()
    path = _matrix_path(settings, slug)
    if not path.exists():
        return None

    values, _, _ = read_matrix(path, {systematic_name})
    row = values.get(systematic_name)
    if row is None:
        return None

    samples = matrix_samples(path)
    is_mito = systematic_name.startswith(MITOCHONDRIAL_PREFIX)
    readout = mitochondrial_readout(samples, _selection_by_run(conn)) if is_mito else None

    return GeneExpression(
        systematic_name=systematic_name,
        slug=slug,
        matrix_path=str(path),
        per_sample=tuple(zip(samples, row, strict=False)),
        is_mitochondrial=is_mito,
        mitochondrial_caveat=readout.caveat() if readout else None,
        usable_samples=readout.usable_samples if readout else (),
    )


def list_contrasts(conn: sqlite3.Connection) -> tuple[ContrastRead, ...]:
    """Every differential-expression result the atlas recorded, with whether its file survives."""
    contrasts: list[ContrastRead] = []
    for row in (
        Select("analysis_result")
        .columns("id", "kind", "payload_ref", "dataset_id")
        .where("kind = ?", "differential_expression")
        .order_by("id")
        .page(conn)
    ):
        ref = str(row["payload_ref"] or "")
        # `payload_ref` is a path followed by a parenthesised human summary; the path is
        # everything before the first " (".
        head = ref.split(" (", 1)[0].strip()
        contrasts.append(
            ContrastRead(
                id=str(row["id"]),
                kind=str(row["kind"]),
                payload_ref=ref,
                dataset_id=_text(row["dataset_id"]),
                path=Path(head) if head else None,
            )
        )
    return tuple(contrasts)


def read_overview(
    conn: sqlite3.Connection, *, settings: Settings | None = None
) -> ExpressionOverview:
    """What is quantified, and where that disagrees with the run table."""
    settings = settings or Settings.load()

    matrices: list[dict[str, Any]] = []
    quantified: set[str] = set()
    for slug, filename in MATRIX_FILES.items():
        path = Path(settings.matrices_dir) / filename
        if not path.exists():
            matrices.append({"slug": slug, "filename": filename, "present": False})
            continue
        samples = matrix_samples(path)
        quantified.update(samples)
        matrices.append(
            {
                "slug": slug,
                "filename": filename,
                "present": True,
                "path": str(path),
                "samples": len(samples),
                "size_bytes": path.stat().st_size,
                "run_accessions": list(samples),
            }
        )

    contrasts = list_contrasts(conn)
    status = {
        (str(row["k"]) if row["k"] is not None else "unrecorded"): int(row["n"])
        for row in Select("sra_run")
        .columns("acquisition_status AS k", "COUNT(*) AS n")
        .group_by("acquisition_status")
        .page(conn)
    }
    runs_in_atlas = int(Select("sra_run").columns("COUNT(*) AS n").scalar(conn) or 0)

    return ExpressionOverview(
        matrices=tuple(matrices),
        contrasts=len(contrasts),
        contrasts_on_disk=sum(1 for c in contrasts if c.exists_on_disk),
        runs_in_atlas=runs_in_atlas,
        runs_quantified=len(quantified),
        acquisition_status=status,
    )
