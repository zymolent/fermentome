"""GEO series discovery and linkage to SRA bioprojects.

esearch(db=gds) + esummary(db=gds), parsed into `dataset` rows (`repository='GEO'`). GEO's own
esummary response for a series already names the BioProject it shares with its SRA deposit (no
elink round trip needed), which is exactly the linkage `sra.py:resolve_dataset_id` uses to point a
run at the GEO series that describes it, rather than at a bare SRA study.

Metadata only, like `sra.py`: nothing here downloads a supplementary file or an expression matrix.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import EutilsClient


@dataclass(frozen=True)
class GeoSeries:
    """One GEO series (GSE), as reported by esummary(db=gds)."""

    accession: str  # GSE...
    title: str
    taxon: str
    platform: str  # GPL...
    entrytype: str  # 'GSE' | 'GDS' | ...
    pdat: str  # release/publication date, as GEO reports it (not ISO-normalized here)
    n_samples: int
    bioproject: str | None  # PRJNA...; None when esummary reports no linked BioProject
    sample_accessions: tuple[str, ...]  # GSM...


def _series_from_summary(summary: Mapping[str, Any]) -> GeoSeries | None:
    """Build a `GeoSeries` from one esummary(db=gds) document, or `None` if it is not a series.

    esummary(db=gds) also returns `entrytype='GDS'` (curated DataSets) for some queries; this
    package only claims to discover *series*, so anything else is skipped by the caller rather
    than mis-typed here.
    """
    if summary.get("entrytype") != "GSE":
        return None
    accession = summary.get("accession")
    if not accession:
        return None
    bioproject = summary.get("bioproject") or None
    samples = summary.get("samples") or []
    sample_accessions = tuple(
        str(s["accession"]) for s in samples if isinstance(s, Mapping) and s.get("accession")
    )
    try:
        n_samples = int(summary.get("n_samples", 0))
    except (TypeError, ValueError):
        n_samples = 0
    return GeoSeries(
        accession=str(accession),
        title=str(summary.get("title", "")),
        taxon=str(summary.get("taxon", "")),
        platform=str(summary.get("gpl", "")),
        entrytype="GSE",
        pdat=str(summary.get("pdat", "")),
        n_samples=n_samples,
        bioproject=str(bioproject) if bioproject else None,
        sample_accessions=sample_accessions,
    )


def discover_geo_series(
    client: EutilsClient, term: str, *, page_size: int = 100
) -> list[GeoSeries]:
    """esearch(db=gds) then esummary(db=gds) over the matched ids, filtered to `entrytype='GSE'`.

    `term` is expected to already scope the search to series (the convention used throughout
    `data/omics/dataset_families.yaml` is to AND in `gse[EntryType]`); this function filters again
    defensively rather than trusting the caller's term to have done so.
    """
    ids = client.esearch_all_ids(db="gds", term=term, page_size=page_size)
    if not ids:
        return []
    summaries = client.esummary(db="gds", ids=ids)
    series = [_series_from_summary(s) for s in summaries]
    return [s for s in series if s is not None]


def dataset_id_for_geo_series(accession: str) -> str:
    return f"geo:{accession}"


def dataset_ids_by_bioproject(series: Sequence[GeoSeries]) -> dict[str, str]:
    """`{bioproject: dataset_id}` for every series that reports one.

    This is the map `sra.py:resolve_dataset_id` uses to point a run at its GEO series instead of a
    bare SRA study -- the GEO-series-to-SRA-bioproject linkage this task's build list calls for.
    """
    return {
        series_.bioproject: dataset_id_for_geo_series(series_.accession)
        for series_ in series
        if series_.bioproject
    }


def geo_series_row(series: GeoSeries, *, retrieved_at: str) -> dict[str, object]:
    """`series` as a `dataset` table row (`repository='GEO'`), ready for a parameterized UPSERT."""
    return {
        "id": dataset_id_for_geo_series(series.accession),
        "accession": f"geo:{series.accession}",
        "repository": "GEO",
        "omics_type": None,
        "platform": series.platform or None,
        "license": None,
        "bioproject": series.bioproject,
        "title": series.title or None,
        "organism": series.taxon or None,
        "sample_count": series.n_samples,
        "retrieved_at": retrieved_at,
        "zone": "R",
        "evidence": (
            f"NCBI GEO accession {series.accession}, esummary via eutils, fetched live on "
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
    title = excluded.title,
    organism = excluded.organism,
    sample_count = excluded.sample_count,
    retrieved_at = excluded.retrieved_at,
    evidence = excluded.evidence
"""


def write_geo_series(
    conn: sqlite3.Connection, series: Sequence[GeoSeries], *, retrieved_at: str
) -> int:
    """Upsert `series` into `dataset`, keyed by `geo:<accession>` (idempotent, like `sra.py`'s).

    Does not open or close `conn`; `fermdb.db.open_db` is the only function that does that.
    """
    written = 0
    for one in series:
        conn.execute(_UPSERT_DATASET_SQL, geo_series_row(one, retrieved_at=retrieved_at))
        written += 1
    conn.commit()
    return written


__all__ = [
    "GeoSeries",
    "dataset_id_for_geo_series",
    "dataset_ids_by_bioproject",
    "discover_geo_series",
    "geo_series_row",
    "write_geo_series",
]
