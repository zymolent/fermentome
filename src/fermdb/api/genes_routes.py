"""The gene browser's endpoints: a list, its facets, its karyotype, and one gene.

A separate module from `routes.py` for one reason that is about people rather than code -- the
gene browser was built while another agent held `routes.py`, and a router that can be registered
with a single `include_router` line is a change that cannot conflict with theirs. The handlers
are the same three lines as everything in `routes.py`: take the read-only connection, call one
query-layer reader, return its `as_json()`.

Every method is GET. `tests/test_api.py` walks every route object on the app and fails the build
on anything else, which is how PLAN.md D.3's "no write path exists" is a property of the code
rather than a line in a README. Nothing here reshapes a payload: `Value.as_json()` omits the
`value` key on an absence, and re-serialising it is precisely how that distinction is lost.

`/genes/{gene_id}` returns `genes.read_gene` **merged with** the positional read rather than
replacing it. The existing payload carries `absent_sections` -- the P.2 sections the atlas cannot
fill and the reason for each -- and that block is the gene page's most load-bearing feature. A
browser that traded it for a coordinate would have made the page look more complete and say less.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from fermdb.api.deps import Conn
from fermdb.query import genes as genes_reader
from fermdb.query import genome_browser

router = APIRouter(prefix="/genes", tags=["genes"])


@router.get("")
def list_genes(
    conn: Conn,
    q: str | None = Query(None, description="substring over name, locus tag and description"),
    assembly: str | None = None,
    seqid: str | None = Query(None, description="sequence accession, or chrIV / IV"),
    biotype: str | None = None,
    strand: str | None = Query(None, description="+, -, or 0"),
    has_coordinates: bool | None = None,
    annotated_by: str | None = Query(None, description="an annotation source, e.g. uniprot_goa"),
    order_by: str = Query("position", description="position | name | length | annotations"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """One page of genes, with a real `total_matching` beside it.

    An unrecognised `order_by` or `strand` is a 422 carrying the accepted values, not a silent
    fallback: a page that quietly ignores the sort it was asked for looks sorted and is not.
    """
    try:
        return genome_browser.list_genes(
            conn,
            q=q,
            assembly=assembly,
            seqid=seqid,
            biotype=biotype,
            strand=strand,
            has_coordinates=has_coordinates,
            annotated_by=annotated_by,
            order_by=order_by,
            limit=limit,
            offset=offset,
        ).as_json()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/facets")
def gene_facets(
    conn: Conn,
    q: str | None = None,
    assembly: str | None = None,
    seqid: str | None = None,
    biotype: str | None = None,
    strand: str | None = None,
    has_coordinates: bool | None = None,
    annotated_by: str | None = None,
) -> dict[str, Any]:
    """Every filter option the live schema can offer, with counts and blocked-facet reasons.

    The same filters the list endpoint takes, because a count of "442 genes on chromosome II" is
    misleading beside a result set already narrowed to tRNAs. Each facet's counts leave out its
    *own* filter, so the rail can switch a selection rather than only clear it.
    """
    try:
        return genome_browser.facets(
            conn,
            q=q,
            assembly=assembly,
            seqid=seqid,
            biotype=biotype,
            strand=strand,
            has_coordinates=has_coordinates,
            annotated_by=annotated_by,
        ).as_json()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/karyotype")
def gene_karyotype(
    conn: Conn,
    q: str | None = None,
    assembly: str | None = None,
    biotype: str | None = None,
    strand: str | None = None,
    annotated_by: str | None = None,
    bin_width: int = Query(genome_browser.BIN_WIDTH_DEFAULT, ge=500, le=200_000),
) -> dict[str, Any]:
    """Gene density along all 17 reference sequences, under every filter except the chromosome.

    There is no `seqid` parameter on purpose. This view is how a chromosome gets chosen, so
    filtering it by the chosen chromosome would leave one track and no way back.
    """
    try:
        return genome_browser.karyotype(
            conn,
            q=q,
            assembly=assembly,
            biotype=biotype,
            strand=strand,
            annotated_by=annotated_by,
            bin_width=bin_width,
        ).as_json()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{gene_id:path}")
def read_gene(conn: Conn, gene_id: str) -> dict[str, Any]:
    """One gene: the existing rich payload, plus where it sits and what sits beside it.

    Resolvable by internal id, systematic name or standard name — all three are how a person
    refers to a gene, and accepting only one makes the page usable only by someone who already
    knows the atlas's identifiers.
    """
    read = genes_reader.read_gene(conn, gene_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no gene {gene_id!r}")
    payload = read.as_json()
    position = genome_browser.read_position(conn, gene_id)
    payload["position"] = position.as_json() if position is not None else None
    return payload
