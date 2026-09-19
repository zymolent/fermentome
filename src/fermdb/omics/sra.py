"""SRA run discovery: esearch + efetch(rettype=runinfo), parsed into `sra_run` rows.

METADATA ONLY (docs/reference/DATA_VOLUME.md section 6). This module fetches SRA's own runinfo
report -- accession, organism, library strategy, spot/base counts, and a `location_url` recording
*where* a run's bytes can be found -- and nothing else. There is deliberately no function here that
downloads a read: `download_run_bytes` below is a tripwire, not an unfinished stub, so that a
bulk-download entry point cannot be added to this module later by accident (51 GB must never move
without the explicit, costed step DATA_VOLUME.md section 6 describes).

Every row is Zone R (docs/reference/CONVENTIONS.md "Data zones"): exactly what SRA's runinfo
reported, never a curator's or a model's reading of it. PLAN.md F.3 is the reason
`acquisition_status` only ever comes out of this module as `'discovered'` -- a run whose
conditions are unknown cannot enter any comparison, so condition annotation and queuing are later,
human-gated steps this module does not perform.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import ESearchResult, EutilsClient, OmicsFetchError

#: DATA_VOLUME.md section 2: Tn-Seq runs are perturbation evidence (L1/L2 under PLAN.md J.3)
#: rather than correlation (L3), so per run they are the most informative rows in the corpus and
#: are surfaced first by `ORDER BY priority_rank`. Everything not named here sorts last, together.
_PRIORITY_BY_STRATEGY: Mapping[str, int] = {
    "Tn-Seq": 1,
    "WGS": 20,
    "RNA-Seq": 50,
    "AMPLICON": 80,
    "OTHER": 90,
}
_DEFAULT_PRIORITY = 100

#: A defense-in-depth cap independent of the CLI's `guard` mechanism (`omics.DatasetFamily`): even
#: a caller that builds an `EutilsClient` directly and points `discover_sra_runs` at an unguarded,
#: unexpectedly huge term (e.g. the uncapped ethanol query) cannot pull more than this many run
#: ids in one call without asking for it explicitly.
DEFAULT_MAX_RUN_IDS = 2000


@dataclass(frozen=True)
class SraRun:
    """One row of SRA's runinfo report, typed and with blank fields turned into `None`.

    Field names mirror the runinfo CSV columns fermdb actually uses (docs/reference/DATA_VOLUME.md
    section 2's build list), not the full ~45-column report -- `raw` keeps everything else for
    anyone who needs a column this dataclass does not surface.
    """

    run_accession: str
    experiment_accession: str
    study_accession: str
    bioproject: str
    biosample: str
    organism: str
    taxid: int | None
    library_strategy: str
    library_layout: str
    platform: str
    instrument_model: str
    spots: int | None
    bases: int | None
    size_mb: float | None
    location_url: str
    raw: Mapping[str, str]


class RuninfoParseError(OmicsFetchError):
    """`efetch(rettype=runinfo)` returned something that does not parse as SRA's runinfo CSV."""


_REQUIRED_RUNINFO_COLUMNS = ("Run",)


def _int_or_none(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _float_or_none(value: str) -> float | None:
    value = value.strip()
    return float(value) if value else None


def parse_runinfo_csv(text: str) -> list[SraRun]:
    """Parse SRA's runinfo CSV (the exact text `efetch(rettype=runinfo)` returns) into `SraRun`s.

    A blank numeric field becomes `None`, never `0` -- SRA reporting a run with 0 spots is a
    different fact than SRA reporting nothing (docs/reference/CONVENTIONS.md "Missing values").
    """
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not set(_REQUIRED_RUNINFO_COLUMNS) <= set(reader.fieldnames):
        raise RuninfoParseError(
            f"runinfo text does not have the expected header; got fieldnames={reader.fieldnames!r}"
        )
    runs: list[SraRun] = []
    for row in reader:
        if not row.get("Run"):
            continue  # a trailing blank line, not a run
        try:
            runs.append(
                SraRun(
                    run_accession=row["Run"],
                    experiment_accession=row.get("Experiment", ""),
                    study_accession=row.get("SRAStudy", ""),
                    bioproject=row.get("BioProject", ""),
                    biosample=row.get("BioSample", ""),
                    organism=row.get("ScientificName", ""),
                    taxid=_int_or_none(row.get("TaxID", "")),
                    library_strategy=row.get("LibraryStrategy", ""),
                    library_layout=row.get("LibraryLayout", "") or "unknown",
                    platform=row.get("Platform", ""),
                    instrument_model=row.get("Model", ""),
                    spots=_int_or_none(row.get("spots", "")),
                    bases=_int_or_none(row.get("bases", "")),
                    size_mb=_float_or_none(row.get("size_MB", "")),
                    location_url=row.get("download_path", ""),
                    raw=dict(row),
                )
            )
        except ValueError as exc:
            raise RuninfoParseError(f"run {row.get('Run')!r}: {exc}") from exc
    return runs


def priority_rank_for(library_strategy: str) -> int:
    """Lower sorts first. See `_PRIORITY_BY_STRATEGY` for the rule this implements."""
    return _PRIORITY_BY_STRATEGY.get(library_strategy, _DEFAULT_PRIORITY)


def count_by_library_strategy(runs: Sequence[SraRun]) -> dict[str, int]:
    return dict(Counter(run.library_strategy or "(none)" for run in runs))


def discover_sra_runs(
    client: EutilsClient,
    term: str,
    *,
    page_size: int = 200,
    max_run_ids: int = DEFAULT_MAX_RUN_IDS,
) -> tuple[ESearchResult, list[SraRun]]:
    """esearch(db=sra) then efetch(rettype=runinfo) over the matched ids.

    Returns the esearch result (mainly for its `count`, to compare against a family's
    `expected_count`) alongside the parsed runs. Raises `OmicsFetchError` rather than silently
    truncating if the search matches more than `max_run_ids` ids -- pass a larger cap explicitly
    if a query is genuinely meant to be this big (the ethanol reference query is not: it is capped
    by project decision to six hand-picked studies, never bulk-discovered; see
    `data/omics/dataset_families.yaml`'s `guard` field and `add_omics_subcommand` in
    `omics/__init__.py`).
    """
    first_page = client.esearch(db="sra", term=term, retmax=page_size)
    if first_page.count == 0:
        return first_page, []
    if first_page.count > max_run_ids:
        raise OmicsFetchError(
            f"esearch db=sra term={term!r} matched {first_page.count} records, over the "
            f"max_run_ids={max_run_ids} safety cap; pass a larger max_run_ids explicitly if this "
            "query is genuinely meant to be this big"
        )
    ids = client.esearch_all_ids(db="sra", term=term, page_size=page_size)
    csv_text = client.efetch(db="sra", ids=ids, rettype="runinfo", retmode="text")
    return first_page, parse_runinfo_csv(csv_text)


def dataset_id_for_sra_study(study_accession: str) -> str:
    """The `dataset` row id for an SRA study with no linked GEO series."""
    return f"insdc.sra:{study_accession}"


def resolve_dataset_id(run: SraRun, geo_dataset_ids_by_bioproject: Mapping[str, str]) -> str | None:
    """The dataset a run belongs to: its GEO series if one shares its bioproject, else its SRA
    study, else `None` -- an unresolved link is not an absent run.

    This is the GEO-series-to-SRA-bioproject linkage this task's build list and
    docs/reference/DATA_VOLUME.md section 2 both call for: `geo.py` discovers series and their
    bioprojects independently of any SRA query, and this function is where the two meet.
    """
    if run.bioproject and run.bioproject in geo_dataset_ids_by_bioproject:
        return geo_dataset_ids_by_bioproject[run.bioproject]
    if run.study_accession:
        return dataset_id_for_sra_study(run.study_accession)
    return None


def sra_study_dataset_row(run: SraRun, *, retrieved_at: str) -> dict[str, object] | None:
    """A minimal `dataset` row for `run`'s SRA study, for when no GEO series claims its bioproject.

    Returns `None` when `run` has no study accession to key a row on.
    """
    if not run.study_accession:
        return None
    return {
        "id": dataset_id_for_sra_study(run.study_accession),
        "accession": f"insdc.sra:{run.study_accession}",
        "repository": "SRA",
        "omics_type": run.library_strategy or None,
        "platform": run.platform or None,
        "license": None,
        "bioproject": run.bioproject or None,
        "title": None,
        "organism": run.organism or None,
        "sample_count": None,
        "retrieved_at": retrieved_at,
        "zone": "R",
        "evidence": (
            f"NCBI SRA study {run.study_accession}, discovered via a run's own runinfo "
            f"(insdc.sra:{run.run_accession}), fetched live via eutils on {retrieved_at}"
        ),
        "confidence": "high",
    }


def sra_run_row(
    run: SraRun,
    *,
    dataset_id: str | None,
    retrieved_at: str,
) -> dict[str, object]:
    """`run` as a `sra_run` table row, ready for a parameterized INSERT/UPSERT."""
    return {
        "id": f"insdc.sra:{run.run_accession}",
        "run_accession": run.run_accession,
        "dataset_id": dataset_id,
        "experiment_accession": run.experiment_accession or None,
        "study_accession": run.study_accession or None,
        "bioproject": run.bioproject or None,
        "biosample": run.biosample or None,
        "organism": run.organism or None,
        "taxid": run.taxid,
        "library_strategy": run.library_strategy or None,
        "library_layout": run.library_layout,
        "platform": run.platform or None,
        "instrument_model": run.instrument_model or None,
        "spots": run.spots,
        "bases": run.bases,
        "size_mb": run.size_mb,
        "location_url": run.location_url or None,
        "priority_rank": priority_rank_for(run.library_strategy),
        "retrieved_at": retrieved_at,
        "evidence": (
            f"NCBI SRA runinfo for {run.run_accession}, fetched live via eutils efetch on "
            f"{retrieved_at}"
        ),
        "confidence": "high",
    }


_UPSERT_DATASET_SQL = """
INSERT INTO dataset (id, accession, repository, omics_type, platform, license, bioproject, title,
                      organism, sample_count, retrieved_at, zone, evidence, confidence)
VALUES (:id, :accession, :repository, :omics_type, :platform, :license, :bioproject, :title,
        :organism, :sample_count, :retrieved_at, :zone, :evidence, :confidence)
ON CONFLICT(id) DO UPDATE SET
    bioproject = excluded.bioproject,
    organism = excluded.organism,
    retrieved_at = excluded.retrieved_at,
    evidence = excluded.evidence
"""

_UPSERT_SRA_RUN_SQL = """
INSERT INTO sra_run (id, run_accession, dataset_id, experiment_accession, study_accession,
                      bioproject, biosample, organism, taxid, library_strategy, library_layout,
                      platform, instrument_model, spots, bases, size_mb, location_url,
                      priority_rank, retrieved_at, evidence, confidence)
VALUES (:id, :run_accession, :dataset_id, :experiment_accession, :study_accession, :bioproject,
        :biosample, :organism, :taxid, :library_strategy, :library_layout, :platform,
        :instrument_model, :spots, :bases, :size_mb, :location_url, :priority_rank, :retrieved_at,
        :evidence, :confidence)
ON CONFLICT(run_accession) DO UPDATE SET
    dataset_id = excluded.dataset_id,
    spots = excluded.spots,
    bases = excluded.bases,
    size_mb = excluded.size_mb,
    location_url = excluded.location_url,
    retrieved_at = excluded.retrieved_at,
    evidence = excluded.evidence
"""


def write_sra_runs(
    conn: sqlite3.Connection,
    runs: Sequence[SraRun],
    *,
    geo_dataset_ids_by_bioproject: Mapping[str, str],
    retrieved_at: str,
) -> int:
    """Upsert `runs` into `sra_run`, writing an SRA-study `dataset` row first where one is needed.

    Idempotent on `run_accession` (docs/reference/CONVENTIONS.md "Pipelines and provenance": every
    pipeline is idempotent on a declared key) -- re-running discovery updates the existing row
    rather than erroring or duplicating it. Does not open or close `conn`; `fermdb.db.open_db` is
    the only function that does that.
    """
    written = 0
    seen_dataset_ids: set[str] = set()
    for run in runs:
        dataset_id = resolve_dataset_id(run, geo_dataset_ids_by_bioproject)
        if (
            dataset_id is not None
            and dataset_id not in geo_dataset_ids_by_bioproject.values()
            and dataset_id not in seen_dataset_ids
        ):
            study_row = sra_study_dataset_row(run, retrieved_at=retrieved_at)
            if study_row is not None:
                conn.execute(_UPSERT_DATASET_SQL, study_row)
                seen_dataset_ids.add(dataset_id)
        row = sra_run_row(run, dataset_id=dataset_id, retrieved_at=retrieved_at)
        conn.execute(_UPSERT_SRA_RUN_SQL, row)
        written += 1
    conn.commit()
    return written


def download_run_bytes(*_args: object, **_kwargs: object) -> None:
    """Refuse. Bulk download is a separate, explicitly costed step.

    This function exists only as a tripwire: if something later tries to call a "download the
    reads" entry point in this module by name, it fails loudly instead of silently degrading into
    a partial implementation that moves gigabytes by accident. See
    docs/reference/DATA_VOLUME.md section 6 for the actual, costed download plan (server-side
    `aws s3 cp`, staged in `us-east-1`, run only as a deliberate, separate step).
    """
    raise NotImplementedError(
        "fermdb.omics.sra deliberately implements no bulk download path. "
        "See docs/reference/DATA_VOLUME.md section 6 for the costed download plan."
    )


__all__ = [
    "DEFAULT_MAX_RUN_IDS",
    "RuninfoParseError",
    "SraRun",
    "count_by_library_strategy",
    "dataset_id_for_sra_study",
    "discover_sra_runs",
    "download_run_bytes",
    "parse_runinfo_csv",
    "priority_rank_for",
    "resolve_dataset_id",
    "sra_run_row",
    "sra_study_dataset_row",
    "write_sra_runs",
]
