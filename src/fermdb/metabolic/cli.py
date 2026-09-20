"""`fermdb atlas ...`: the metabolic layer's command line.

Separate from `cli.py` the way `omics` and `literature` are, so the top-level parser gains only an
import and one call. PLAN.md G.6 (the parts catalog), G.7 (route enumeration and ranking), plus
the annotation fetch.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from ..annotate.ontology import annotations_for, write_annotations
from ..config import Settings
from ..db import open_db
from .curated import load_parts, load_pathways, write_parts, write_pathways
from .routes import enumerate_routes, explain, rank, write_routes

__all__ = ["add_atlas_subcommand"]


def cmd_atlas_pathways(_args: argparse.Namespace) -> int:
    """Load the curated pathways and the parts catalog, balance-checking as we go."""
    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        pathways = load_pathways(settings)
        parts = load_parts(settings)
        counts = write_pathways(conn, pathways)
        counts.update(write_parts(conn, parts))
    finally:
        conn.close()

    for pathway in pathways:
        competing = sum(1 for reaction in pathway.reactions if reaction.competing)
        print(
            f"{pathway.id:32}{len(pathway.reactions):>3} reactions "
            f"({competing} competing), all balanced"
        )
    print(f"{'parts catalog':32}{len(parts):>3} parts")
    print()
    for table, count in sorted(counts.items()):
        print(f"  {table:<26}{count:>7}")
    return 0


def cmd_atlas_routes(args: argparse.Namespace) -> int:
    """Enumerate, gate, rank and optionally store every route."""
    settings = Settings.load()
    parts = load_parts(settings)
    routes = enumerate_routes(parts)
    ordered = rank(routes)
    excluded = [route for route in routes if not route.viable]

    print(f"{len(routes)} routes enumerated, {len(ordered)} viable, {len(excluded)} excluded")
    print()
    print(f"{'#':>4}  {'strategy':28}{'gaps':>5}{'risks':>7}{'feas':>7}  parts")
    for index, route in enumerate(ordered[: args.limit], start=1):
        chain = " + ".join(step.part.id for step in route.steps)
        print(
            f"{index:>4}  {route.strategy:28}{len(route.transport_gaps):>5}"
            f"{len(route.cofactor_risks):>7}{route.score_feasibility or 0:>7.2f}  {chain}"
        )
    if excluded:
        print()
        print("excluded:")
        for route in excluded[:5]:
            print(f"  {route.strategy}: {'; '.join(route.excluded_because)}")

    print()
    print("Evidence and toxicity are NULL on every route: nothing has been extracted from the")
    print("literature and no tolerance has been measured. NULL is 'not yet looked', not 0.")

    if args.write:
        conn = open_db(settings.db_file)
        conn.execute("PRAGMA busy_timeout=60000")
        try:
            counts = write_routes(conn, routes)
        finally:
            conn.close()
        print()
        for table, count in sorted(counts.items()):
            print(f"  {table:<26}{count:>7}")
    return 0


def cmd_atlas_explain(args: argparse.Namespace) -> int:
    """Explain why one route ranks where it does, by naming the dominating term."""
    settings = Settings.load()
    routes = rank(enumerate_routes(load_parts(settings)))
    matches = [route for route in routes if args.route in route.id]
    if not matches:
        print(f"no route id contains {args.route!r}", file=sys.stderr)
        return 2
    for route in matches[: args.limit]:
        print(route.id)
        print(f"   {explain(route)}")
        for requirement in route.construction_requirements:
            print(f"   construction: {requirement}")
        for gap in route.transport_gaps:
            print(f"   transport gap: {gap}")
        for risk in route.cofactor_risks:
            print(f"   cofactor risk: {risk}")
    return 0


def cmd_atlas_annotate(_args: argparse.Namespace) -> int:
    """Fetch GO/Pfam/InterPro/EC for every resolved gene. Cached, so a re-run costs no requests."""
    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        found, gaps = annotations_for(conn, settings)
        counts = write_annotations(
            conn, found, retrieved_at=datetime.now(UTC).isoformat(timespec="seconds")
        )
    finally:
        conn.close()

    total = sum(len(rows) for rows in found.values())
    print(f"{len(found)} genes queried, {total} annotations, {len(gaps)} with no reviewed entry")
    if gaps:
        print(f"  no reviewed UniProt entry: {', '.join(gaps)}")
    for table, count in counts.items():
        print(f"  {table:<26}{count:>7}")
    return 0


def add_atlas_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `fermdb atlas ...` to an existing top-level subparsers action."""
    p_atlas = sub.add_parser(
        "atlas",
        help="curated pathways, parts catalog, annotations and route enumeration (G.6-G.7)",
    )
    atlas_sub = p_atlas.add_subparsers(dest="atlas_command", required=True)

    p_pathways = atlas_sub.add_parser(
        "pathways",
        help="load the curated pathways and parts catalog (refuses an unbalanced reaction)",
    )
    p_pathways.set_defaults(func=cmd_atlas_pathways)

    p_routes = atlas_sub.add_parser("routes", help="enumerate, gate and rank every route (G.7)")
    p_routes.add_argument("--limit", type=int, default=15, help="how many ranked routes to show")
    p_routes.add_argument(
        "--write", action="store_true", help="store the routes and their knowledge gaps"
    )
    p_routes.set_defaults(func=cmd_atlas_routes)

    p_explain = atlas_sub.add_parser("explain", help="why one route ranks where it does")
    p_explain.add_argument("route", help="substring of a route id, e.g. 'E_mtdna' or 'kivd'")
    p_explain.add_argument("--limit", type=int, default=3, help="how many matches to explain")
    p_explain.set_defaults(func=cmd_atlas_explain)

    p_annotate = atlas_sub.add_parser(
        "annotate", help="fetch GO/Pfam/InterPro/EC from UniProt for every resolved gene"
    )
    p_annotate.set_defaults(func=cmd_atlas_annotate)
