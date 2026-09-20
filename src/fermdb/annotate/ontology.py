"""GO terms, Pfam domains and EC numbers for the DUET gene set, from UniProt.

The owner asked for "ontology, pathway, pfam and any other annotations relevant for isobutanol
and ethanol production" and this layer had never been started. It reads UniProt's REST API, which
needs no key and no account, and it stores what UniProt says without interpreting it.

**Everything here is Zone R.** An annotation row is what a source reported, recorded with the
source, its URL and the date it was retrieved. Nothing is inferred: a gene UniProt has no entry
for produces no rows at all rather than borrowed ones from a relative, because an annotation
transferred by homology is a different claim from an annotation recorded for this protein and the
two must not end up in the same column.

**evidence_code is NULL for everything that is not a GO term**, and that is a structural absence
rather than an unknown. Pfam has no notion of a GO evidence code; the column does not apply to
that row's source type. CONVENTIONS.md's missing-value rule governs a fact a source could have
recorded and did not, which is a different situation.

**Resumable and cached.** Each gene's UniProt response is written to ``<data_dir>/annotations/``
before anything is parsed, so an interrupted run continues rather than restarting, and a re-run
costs no requests. The cache is the evidence too: a row here can be traced to the exact bytes
UniProt returned.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from ..config import Settings

__all__ = [
    "SOURCE_NAME",
    "UNIPROT_SEARCH",
    "YEAST_TAXON",
    "Annotation",
    "AnnotationError",
    "Transport",
    "UrllibTransport",
    "annotations_dir",
    "annotations_for",
    "fetch_all",
    "parse_uniprot",
    "write_annotations",
]

UNIPROT_SEARCH: Final[str] = "https://rest.uniprot.org/uniprotkb/search"

#: S. cerevisiae S288C. Pinned so a query cannot silently return a homolog from another yeast.
YEAST_TAXON: Final[str] = "559292"

SOURCE_NAME: Final[str] = "uniprot"

#: Courtesy delay between requests. UniProt asks for reasonable use rather than a fixed rate; one
#: request every 400 ms over 36 genes is well inside anything they publish.
_DELAY_S: Final[float] = 0.4


class AnnotationError(RuntimeError):
    """A UniProt response could not be used, or a cache entry is unreadable."""


class Transport(Protocol):
    """Everything this module needs from the network, injectable so tests stay offline."""

    def get_json(self, url: str) -> Any:
        """Fetch `url` and return its parsed JSON body."""
        ...


class UrllibTransport:
    """The real transport. Tests must never reach this class -- inject a fake instead."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url, headers={"User-Agent": "fermdb-annotate/0.1", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AnnotationError(f"request to {url} failed: {exc}") from exc


@dataclass(frozen=True)
class Annotation:
    """One term a source recorded for one gene."""

    gene: str
    source: str
    term_id: str
    term_label: str | None
    term_namespace: str
    evidence_code: str | None
    source_url: str


def annotations_dir(settings: Settings) -> Path:
    return Path(settings.data_dir) / "annotations"


def _query_url(symbol: str) -> str:
    query = f"gene_exact:{symbol} AND organism_id:{YEAST_TAXON} AND reviewed:true"
    fields = "accession,id,gene_names,protein_name,go,xref_pfam,xref_interpro,ec"
    return f"{UNIPROT_SEARCH}?query={urllib.parse.quote(query)}&fields={fields}&format=json&size=1"


# ------------------------------------------------------------------------------------- parsing


def _go_terms(entry: dict[str, Any], gene: str, url: str) -> list[Annotation]:
    out: list[Annotation] = []
    for reference in entry.get("uniProtKBCrossReferences", []):
        if reference.get("database") != "GO":
            continue
        properties = {p["key"]: p["value"] for p in reference.get("properties", [])}
        term = properties.get("GoTerm", "")
        # UniProt writes "C:mitochondrion" / "F:catalytic activity" / "P:valine biosynthesis".
        aspect, _, label = term.partition(":")
        namespace = {
            "C": "cellular_component",
            "F": "molecular_function",
            "P": "biological_process",
        }.get(aspect, "unknown")
        # "IDA:SGD" -> the evidence code is the part before the colon.
        source_code = properties.get("GoEvidenceType", "")
        out.append(
            Annotation(
                gene=gene,
                source="uniprot_goa",
                term_id=str(reference.get("id", "")),
                term_label=label or None,
                term_namespace=namespace,
                evidence_code=source_code.partition(":")[0] or None,
                source_url=url,
            )
        )
    return out


def _domains(entry: dict[str, Any], gene: str, url: str) -> list[Annotation]:
    out: list[Annotation] = []
    for reference in entry.get("uniProtKBCrossReferences", []):
        database = reference.get("database")
        if database not in {"Pfam", "InterPro"}:
            continue
        properties = {p["key"]: p["value"] for p in reference.get("properties", [])}
        out.append(
            Annotation(
                gene=gene,
                source="pfam" if database == "Pfam" else "interpro",
                term_id=str(reference.get("id", "")),
                term_label=properties.get("EntryName") or properties.get("Description"),
                term_namespace="domain",
                # Structurally absent: Pfam and InterPro have no GO evidence codes.
                evidence_code=None,
                source_url=url,
            )
        )
    return out


def _ec_numbers(entry: dict[str, Any], gene: str, url: str) -> list[Annotation]:
    protein = entry.get("proteinDescription", {})
    recommended = protein.get("recommendedName", {})
    out: list[Annotation] = []
    for ec in recommended.get("ecNumbers", []):
        value = ec.get("value")
        if value:
            out.append(
                Annotation(
                    gene=gene,
                    source=SOURCE_NAME,
                    term_id=f"EC:{value}",
                    term_label=recommended.get("fullName", {}).get("value"),
                    term_namespace="ec",
                    evidence_code=None,
                    source_url=url,
                )
            )
    return out


def parse_uniprot(payload: Any, gene: str, url: str) -> list[Annotation]:
    """Every annotation in one UniProt search response. An empty result yields no rows."""
    if not isinstance(payload, dict):
        raise AnnotationError(f"{gene}: UniProt returned {type(payload).__name__}, not an object")
    results = payload.get("results") or []
    if not results:
        return []
    entry = results[0]
    return _go_terms(entry, gene, url) + _domains(entry, gene, url) + _ec_numbers(entry, gene, url)


# ------------------------------------------------------------------------------------ fetching


def fetch_all(
    genes: Sequence[str],
    settings: Settings,
    *,
    transport: Transport | None = None,
    delay_s: float = _DELAY_S,
) -> dict[str, list[Annotation]]:
    """Annotations for every gene, cached per gene and resumable.

    A gene whose cache file already exists costs no request, so an interrupted run continues from
    where it stopped. A gene UniProt has no reviewed entry for caches an empty result and is
    reported as a gap by :func:`annotations_for` -- it is not retried forever and it is not filled
    from a relative.
    """
    client = transport if transport is not None else UrllibTransport()
    directory = annotations_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)

    out: dict[str, list[Annotation]] = {}
    for index, gene in enumerate(genes):
        cache = directory / f"{gene}.json"
        url = _query_url(gene)
        if cache.is_file():
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            if index and delay_s:
                time.sleep(delay_s)
            payload = client.get_json(url)
            # Written before parsing, so the bytes a row is traced to are the bytes received.
            cache.write_text(json.dumps(payload), encoding="utf-8")
        out[gene] = parse_uniprot(payload, gene, url)
    return out


def annotations_for(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    transport: Transport | None = None,
) -> tuple[dict[str, list[Annotation]], tuple[str, ...]]:
    """Annotations for every gene already resolved into ``gene``, plus the genes with none.

    Returns ``(annotations, genes UniProt had no reviewed entry for)``. The second half is a
    finding rather than a nuisance: a DUET gene with no reviewed UniProt entry is a gap in what
    can be said about it, and it is reported instead of being quietly absent.
    """
    symbols = [
        str(row[0])
        for row in conn.execute(
            "SELECT standard_name FROM gene WHERE standard_name IS NOT NULL ORDER BY standard_name"
        )
    ]
    found = fetch_all(symbols, settings, transport=transport)
    gaps = tuple(gene for gene, rows in found.items() if not rows)
    return found, gaps


# ------------------------------------------------------------------------------------- storage


def write_annotations(
    conn: sqlite3.Connection, annotations: dict[str, list[Annotation]], *, retrieved_at: str
) -> dict[str, int]:
    """Store annotations against the gene_group each gene belongs to."""
    groups = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT standard_name, gene_group_id FROM gene WHERE standard_name IS NOT NULL"
        )
    }
    written = 0
    for gene, rows in annotations.items():
        group = groups.get(gene)
        if group is None:
            continue
        for annotation in rows:
            conn.execute(
                "INSERT INTO gene_annotation (id, gene_group_id, source, term_id, term_label, "
                "term_namespace, evidence_code, source_url, retrieved_at, zone, evidence, "
                "confidence) VALUES (?,?,?,?,?,?,?,?,?,'R',?,'high') "
                "ON CONFLICT(id) DO UPDATE SET term_label=excluded.term_label, "
                "retrieved_at=excluded.retrieved_at",
                (
                    f"YAA:ANNOT:{gene}-{annotation.source}-{annotation.term_id}".replace(":", "-"),
                    group,
                    annotation.source,
                    annotation.term_id,
                    annotation.term_label,
                    annotation.term_namespace,
                    annotation.evidence_code,
                    annotation.source_url,
                    retrieved_at,
                    f"UniProt REST, reviewed entry for {gene} in taxon {YEAST_TAXON}",
                ),
            )
            written += 1
    conn.commit()
    return {"gene_annotation": written}
