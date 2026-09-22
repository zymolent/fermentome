"""Every read endpoint, grouped by the page it serves.

One module rather than eleven, because each handler is three lines: take the read-only
connection, call one query-layer reader, return its `as_json()`. Splitting that across eleven
files would hide the single most useful property of this layer -- that it adds nothing. Where a
handler looks longer than three lines it is doing pagination or a 404, never business logic.

The serialization contract comes entirely from the query layer. `Value.as_json()` omits the
`value` key on an absence rather than sending `null`, so the client can tell "not recorded" from
"recorded as zero" by asking whether the key exists. Nothing here reshapes that, because
reshaping it is exactly how that distinction gets lost.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from fermdb.api.deps import Conn
from fermdb.config import Settings
from fermdb.query import (
    coverage,
    genes,
    genomes,
    literature,
    networks,
    pathways,
    publications,
    records,
    review,
    traceability,
    transcripts,
)
from fermdb.query import (
    search as search_query,
)

router = APIRouter()


# ---------------------------------------------------------------- dashboard / atlas


@router.get("/atlas/coverage", tags=["atlas"])
def atlas_coverage(conn: Conn) -> dict[str, Any]:
    """Row counts with the reason each empty table is empty."""
    return coverage.read_coverage(conn).as_json()


@router.get("/atlas/pages", tags=["atlas"])
def atlas_pages(conn: Conn) -> list[dict[str, Any]]:
    """Which PLAN.md P.2 pages have content, and what blocks the rest."""
    return [page.as_json() for page in coverage.page_readiness(conn)]


@router.get("/search", tags=["atlas"])
def cross_search(
    conn: Conn,
    q: str = Query("", description="substring to look for"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Search several entity kinds at once, grouped by kind and never ranked across kinds."""
    return search_query.search(conn, q, limit=limit).as_json()


# ---------------------------------------------------------------- literature


@router.get("/literature/overview", tags=["literature"])
def literature_overview(conn: Conn) -> dict[str, Any]:
    """The corpus funnel: known, screened, decided, readable, and each loss in between."""
    return literature.read_overview(conn).as_json()


@router.get("/literature/families", tags=["literature"])
def literature_families(conn: Conn) -> list[str]:
    """Screening families present, so a filter offers only real options."""
    return list(literature.screening_families(conn))


@router.get("/literature/publications", tags=["literature"])
def literature_publications(
    conn: Conn,
    q: str | None = None,
    year: int | None = None,
    family: str | None = None,
    triage_state: str | None = None,
    readable_only: bool = False,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Publications matching the given facets, as a page that reports its own truncation."""
    return publications.search_publications(
        conn,
        query=q,
        year=year,
        family=family,
        triage_state=triage_state,
        readable_only=readable_only,
        limit=limit,
        offset=offset,
    ).as_json()


@router.get("/literature/corpus-shape", tags=["literature"])
def literature_corpus_shape(conn: Conn) -> dict[str, int]:
    """Publications by how much of each the atlas actually holds."""
    return publications.corpus_shape(conn)


@router.get("/literature/publications/{publication_id:path}", tags=["literature"])
def literature_publication(
    conn: Conn,
    publication_id: str,
    finding_limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """One paper with every extracted finding and the sentence it came from."""
    read = publications.read_publication(
        conn, publication_id, settings=Settings.load(), finding_limit=finding_limit
    )
    if read is None:
        raise HTTPException(status_code=404, detail=f"no publication {publication_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- genomes


@router.get("/genomes/overview", tags=["genomes"])
def genomes_overview(conn: Conn) -> dict[str, Any]:
    """References on disk, the genetic code each compartment reads, and the mtDNA loci."""
    return genomes.read_overview(conn).as_json()


# ---------------------------------------------------------------- annotations / genes


@router.get("/annotations/genes", tags=["annotations"])
def annotations_genes(conn: Conn, limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, str]]:
    """Every gene the atlas holds, as id and display name."""
    return [{"id": gene_id, "name": name} for gene_id, name in genes.list_genes(conn, limit=limit)]


@router.get("/annotations/genes/{gene_id:path}", tags=["annotations"])
def annotations_gene(conn: Conn, gene_id: str) -> dict[str, Any]:
    """One gene: function, pathway roles, and what the atlas cannot fill in."""
    read = genes.read_gene(conn, gene_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no gene {gene_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- transcripts


@router.get("/transcripts/overview", tags=["transcripts"])
def transcripts_overview(conn: Conn) -> dict[str, Any]:
    """Studies and runs, split by what each can actually support."""
    return transcripts.read_overview(conn).as_json()


@router.get("/transcripts/runs", tags=["transcripts"])
def transcripts_runs(
    conn: Conn,
    study: str | None = None,
    strategy: str | None = None,
    acquisition_status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Sequencing runs matching the given facets."""
    return transcripts.list_runs(
        conn,
        study=study,
        strategy=strategy,
        acquisition_status=acquisition_status,
        limit=limit,
        offset=offset,
    ).as_json()


@router.get("/transcripts/studies/{study_accession}", tags=["transcripts"])
def transcripts_study(conn: Conn, study_accession: str) -> dict[str, Any]:
    """One study's rollup."""
    read = transcripts.read_study(conn, study_accession)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no study {study_accession!r}")
    return read.as_json()


# ---------------------------------------------------------------- networks / pathways


@router.get("/networks/overview", tags=["networks"])
def networks_overview(conn: Conn) -> dict[str, Any]:
    """The reaction graph and route space in summary, including how many routes are viable."""
    return networks.read_overview(conn).as_json()


@router.get("/networks/graph", tags=["networks"])
def networks_graph(conn: Conn, pathway: str | None = None) -> dict[str, Any]:
    """The reaction graph as nodes and edges, optionally narrowed to one pathway."""
    return networks.read_reaction_graph(conn, pathway_id=pathway).as_json()


@router.get("/networks/routes", tags=["networks"])
def networks_routes(
    conn: Conn,
    cofactor_strategy: str | None = None,
    balance_status: str | None = None,
    order_by: str = Query("score_evidence"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Routes ordered by one *named* scoring axis. No composite score is invented here."""
    try:
        page = networks.rank_routes(
            conn,
            cofactor_strategy=cofactor_strategy,
            balance_status=balance_status,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    payload = page.as_json()
    payload["ordered_by"] = order_by
    return payload


@router.get("/networks/routes/{route_id:path}", tags=["networks"])
def networks_route(conn: Conn, route_id: str) -> dict[str, Any]:
    """One route with its steps and every score it does and does not have."""
    read = networks.read_route(conn, route_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no route {route_id!r}")
    return read.as_json()


@router.get("/pathways", tags=["networks"])
def pathway_list(conn: Conn) -> list[dict[str, str]]:
    """The curated pathways."""
    return [{"id": pid, "name": name} for pid, name in pathways.list_pathways(conn)]


@router.get("/pathways/gaps", tags=["networks"])
def pathway_gaps(conn: Conn) -> dict[str, list[str]]:
    """Per pathway, what a diagram of it could not honestly show."""
    return {key: list(value) for key, value in pathways.pathway_gaps(conn).items()}


@router.get("/pathways/{pathway_id:path}", tags=["networks"])
def pathway_detail(conn: Conn, pathway_id: str) -> dict[str, Any]:
    """One pathway's reaction graph, with compartments and cofactors."""
    read = pathways.read_pathway(conn, pathway_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no pathway {pathway_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- data / measurements


@router.get("/data/overview", tags=["data"])
def data_overview(conn: Conn) -> dict[str, Any]:
    """Measurements, experiments, strains and products, with the quality caveats attached."""
    return records.read_overview(conn).as_json()


@router.get("/data/measurements", tags=["data"])
def data_measurements(
    conn: Conn,
    product_id: str | None = None,
    strain_id: str | None = None,
    quantity_kind: str | None = None,
    publication_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Measurements with their comparability warnings, which travel with every row."""
    reads, page = records.list_measurements(
        conn,
        product_id=product_id,
        strain_id=strain_id,
        quantity_kind=quantity_kind,
        publication_id=publication_id,
        limit=limit,
        offset=offset,
    )
    return {
        "rows": [read.as_json() for read in reads],
        "count": len(reads),
        "truncated": page.truncated,
        "limit": page.limit,
        "offset": page.offset,
    }


# ---------------------------------------------------------------- evidence


@router.get("/evidence/assertions", tags=["evidence"])
def evidence_assertions(conn: Conn) -> dict[str, Any]:
    """Every active assertion, with where its J.5 chain breaks."""
    return traceability.walk_assertions(conn).as_json()


@router.get("/evidence/assertions/{assertion_id:path}", tags=["evidence"])
def evidence_assertion(conn: Conn, assertion_id: str) -> dict[str, Any]:
    """One assertion's chain, rendered as a chain."""
    walk = traceability.walk_assertions(conn, assertion_ids=[assertion_id])
    if not walk.chains:
        raise HTTPException(status_code=404, detail=f"no active assertion {assertion_id!r}")
    return walk.chains[0].as_json()


# ---------------------------------------------------------------- curation queue


@router.get("/curation/queue", tags=["curation"])
def curation_queue(
    conn: Conn,
    limit: int = Query(10, ge=1, le=100),
    kinds: str | None = Query(None, description="comma-separated record kinds"),
) -> list[dict[str, Any]]:
    """The next proposals a curator would see.

    Read-only, and it takes no lease: looking at the queue is not starting work on it. Accepting
    a proposal is `fermdb curate`, by a named human -- there is no endpoint for it here.
    """
    kind_list = tuple(k.strip() for k in kinds.split(",") if k.strip()) if kinds else None
    packets = review.review_queue(conn, limit=limit, kinds=kind_list, settings=Settings.load())
    return [packet.as_json() for packet in packets]
