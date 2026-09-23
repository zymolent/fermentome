"""The four entity pages' endpoints: Strain, Experiment, Product and Compare (PLAN.md P.2).

A separate module from `routes.py` on the same reasoning `genes_routes.py` gives: a router that
registers with one `include_router` line is a change that cannot conflict with another agent
holding `routes.py`.

Every method is GET, and `tests/test_api.py` walks the OpenAPI schema and fails the build on
anything else -- which is how PLAN.md D.3's "no write path exists" stays a property of the code.
Nothing here reshapes a payload: `Value.as_json()` omits the `value` key on an absence, and
re-serialising it is exactly how "not recorded" becomes indistinguishable from zero.

`/compare` takes its subjects as a repeated `id` query parameter rather than as a comma-joined
string, because an atlas identifier is `YAA:STRAIN:cen-pk113-7d` and splitting on a separator
that can appear in an id is a bug waiting for the first id that contains one.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from fermdb.api.deps import Conn
from fermdb.query import experiments as experiments_query
from fermdb.query import products as products_query
from fermdb.query import strains as strains_query
from fermdb.query.compare import compare as compare_subjects
from fermdb.query.compare import suggest as suggest_candidates

router = APIRouter(tags=["entities"])


# ---------------------------------------------------------------- strains


@router.get("/strains")
def list_strains(
    conn: Conn,
    q: str | None = Query(None, description="substring over the canonical name"),
    strain_class: str | None = Query(
        None, alias="class", description="laboratory | industrial | wild | engineered | evolved"
    ),
    organism_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """A page of strains, with the atlas-wide class histogram beside it.

    The histogram is not narrowed by the filters: it is the denominator this page is a slice of.
    """
    rows, page, by_class = strains_query.list_strains(
        conn,
        q=q,
        strain_class=strain_class,
        organism_id=organism_id,
        limit=limit,
        offset=offset,
    )
    return {
        "rows": [row.as_json() for row in rows],
        "count": len(rows),
        "truncated": page.truncated,
        "limit": page.limit,
        "offset": page.offset,
        "by_class": by_class,
        "total": sum(by_class.values()),
    }


@router.get("/strains/{strain_id:path}")
def read_strain(conn: Conn, strain_id: str) -> dict[str, Any]:
    """One strain: lineage, genotype, modifications, phenotype by class, tolerance, samples.

    Resolvable by internal id, canonical name or alias -- all three are how a person names a
    strain, and accepting only the first makes the page usable only by someone who already knows
    the atlas's identifiers.
    """
    read = strains_query.read_strain(conn, strain_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no strain {strain_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- experiments


@router.get("/experiments")
def list_experiments(
    conn: Conn,
    q: str | None = None,
    has_publication: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """A page of experiments with their sample and measurement counts."""
    rows, page = experiments_query.list_experiments(
        conn, q=q, has_publication=has_publication, limit=limit, offset=offset
    )
    return {
        "rows": [row.as_json() for row in rows],
        "count": len(rows),
        "truncated": page.truncated,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.get("/experiments/{experiment_id:path}")
def read_experiment(conn: Conn, experiment_id: str) -> dict[str, Any]:
    """One experiment, with every facet of its condition context whether recorded or not."""
    read = experiments_query.read_experiment(conn, experiment_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no experiment {experiment_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- products


@router.get("/products")
def list_products(conn: Conn) -> list[dict[str, Any]]:
    """Every product. Unpaged: `product` is a ten-row controlled vocabulary, not a table."""
    return [row.as_json() for row in products_query.list_products(conn)]


@router.get("/products/{product_id:path}")
def read_product(conn: Conn, product_id: str) -> dict[str, Any]:
    """One product: pathways, strategies, tolerance, and measurements faceted by class.

    Never ranked across classes. `leaderboard_refusal` travels in the payload so the refusal
    survives into any other consumer of this endpoint, not only the page.
    """
    read = products_query.read_product(conn, product_id)
    if read is None:
        raise HTTPException(status_code=404, detail=f"no product {product_id!r}")
    return read.as_json()


# ---------------------------------------------------------------- compare


@router.get("/compare")
def compare(
    conn: Conn,
    kind: str = Query("strain", description="strain | experiment"),
    id: Annotated[list[str] | None, Query(description="repeat once per subject")] = None,
) -> dict[str, Any]:
    """Subjects side by side, or a refusal with the reason named.

    A refusal is a 200 with `verdict: "refuse"`, not an error. PLAN.md I.2 makes refusal a valid
    answer, and an answer is not a 4xx.
    """
    try:
        return compare_subjects(conn, kind=kind, ids=id or []).as_json()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/compare/candidates")
def compare_candidates(
    conn: Conn, kind: str = Query("strain", description="strain | experiment")
) -> list[dict[str, Any]]:
    """Subjects worth comparing, most-populated first, so the page opens with something in it."""
    try:
        return [dict(row) for row in suggest_candidates(conn, kind=kind)]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
