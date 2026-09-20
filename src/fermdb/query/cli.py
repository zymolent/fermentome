"""``fermdb query ...``: the read layer's command line, and its first consumer.

Separate from `cli.py` the way `omics`, `atlas` and `extract` are, so the top-level parser gains
only an import and one call.

``--json`` on every command emits the exact payload an HTTP handler would return. That is not a
convenience flag: it is how the wire format gets exercised before anything depends on it. A
serialization bug in `values.py` -- a three-state absence flattened to null, an ungraded evidence
level with no basis -- is invisible in a formatted table and obvious in the JSON, and it is much
cheaper to find now than through a frontend that has already been written against it.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..config import Settings
from ..db import open_db
from .coverage import page_readiness, read_coverage
from .pathways import list_pathways, read_pathway

__all__ = ["add_query_subcommand"]


def cmd_query_coverage(args: argparse.Namespace) -> int:
    """What the atlas holds, and why each empty table is empty."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        report = read_coverage(conn)
    finally:
        conn.close()

    if args.json:
        json.dump(report.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{'entity':<26}{'rows':>8}{'queued':>8}  state")
    for entity in report.entities:
        queued = str(entity.pending) if entity.pending else "-"
        print(f"{entity.label:<26}{entity.count:>8}{queued:>8}  {entity.state}")

    actionable = [entity for entity in report.entities if entity.is_actionable]
    if actionable:
        print()
        print("Empty, but proposals are queued -- these are waiting on a curator, not on data:")
        for entity in actionable:
            print(f"  {entity.label:<24}{entity.pending:>4} proposal(s)")

    never = report.by_state("never_populated")
    if never:
        print()
        print("Empty with nothing proposed -- never looked:")
        print("  " + ", ".join(entity.label for entity in never))

    print()
    print(f"{report.pending_total} proposal(s) pending, by kind:")
    for kind, count in sorted(report.pending_by_kind.items(), key=lambda item: -item[1]):
        if count:
            print(f"  {kind:<32}{count:>5}")
    return 0


def cmd_query_pages(args: argparse.Namespace) -> int:
    """Which PLAN.md P.2 pages have content today, and what blocks the rest."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        pages = page_readiness(conn)
    finally:
        conn.close()

    if args.json:
        json.dump([page.as_json() for page in pages], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    ready = sum(1 for page in pages if page.renderable)
    print(f"{ready} of {len(pages)} pages have content")
    print()
    for page in pages:
        mark = "ok  " if page.renderable else "    "
        print(f"{mark}{page.page:<14}{page.note}")
    return 0


def cmd_query_pathway(args: argparse.Namespace) -> int:
    """One pathway's reaction graph, and what a diagram of it could not honestly show."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        if args.pathway is None:
            for pathway_id, name in list_pathways(conn):
                print(f"{pathway_id:<40}{name}")
            return 0
        read = read_pathway(conn, args.pathway)
    finally:
        conn.close()

    if read is None:
        print(f"no pathway with id {args.pathway!r}", file=sys.stderr)
        return 2

    if args.json:
        json.dump(read.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{read.name}  [{read.id}]  zone {read.zone.value if read.zone else '?'}")
    print()
    for reaction in read.reactions:
        competing = reaction.competing.display
        print(
            f"{reaction.step_order:>3}. {reaction.step_role.display:<16}"
            f"{reaction.name.display:<42}competing: {competing}"
        )
        print(f"     {reaction.equation.display}")
        print(f"     compartment {reaction.compartment.display}")
    if read.gaps:
        print()
        print("This page cannot be rendered as PLAN.md P.2 specifies it:")
        for gap in read.gaps:
            print(f"  - {gap}")
    return 0


def add_query_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``fermdb query ...`` to an existing top-level subparsers action."""
    p_query = sub.add_parser(
        "query",
        help="the read layer an interface sits on: coverage, page readiness (D.3, P.2)",
    )
    query_sub = p_query.add_subparsers(dest="query_command", required=True)

    p_coverage = query_sub.add_parser(
        "coverage",
        help="row counts with the reason each empty table is empty",
    )
    p_coverage.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_coverage.set_defaults(func=cmd_query_coverage)

    p_pages = query_sub.add_parser(
        "pages",
        help="which PLAN.md P.2 pages have content, and what blocks the rest",
    )
    p_pages.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_pages.set_defaults(func=cmd_query_pages)

    p_pathway = query_sub.add_parser(
        "pathway",
        help="one pathway's reaction graph, with what a diagram of it could not honestly show",
    )
    p_pathway.add_argument(
        "pathway", nargs="?", help="pathway id; omit to list the curated pathways"
    )
    p_pathway.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_pathway.set_defaults(func=cmd_query_pathway)
