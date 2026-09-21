"""`fermdb atlas ...`: the metabolic layer's command line.

Separate from `cli.py` the way `omics` and `literature` are, so the top-level parser gains only an
import and one call. PLAN.md G.6 (the parts catalog), G.7 (route enumeration and ranking), plus
the annotation fetch.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import UTC, datetime

from ..annotate.ontology import annotations_for, write_annotations
from ..config import Settings
from ..db import open_db
from ..db.vocabularies import load_vocabularies
from .chassis import iter_context, load_profiles, selected_profile, write_profiles
from .curated import load_parts, load_pathways, write_parts, write_pathways
from .mtdna_loci import (
    load_activator_map,
    load_programme_gaps,
    loci_without_activator,
    non_displacing_loci,
    write_loci,
    write_programme_gaps,
)
from .recall import (
    MATCHING_RULE,
    describe_report,
    load_configurations,
    recall_report,
)
from .routes import (
    OBJECTIVES,
    describe_demand,
    enumerate_routes,
    explain,
    insertion_plan,
    rank,
    write_routes,
)

#: One clause per objective, printed beside the ranking so the reader knows which question the
#: list in front of them answers. The handover's finding was that a reader takes "the top route"
#: to mean "the route to build"; naming the objective is the cheapest correction to that.
_OBJECTIVE_MEANS = {
    "easiest": "least trouble to build",
    "programme": "closest to what this programme is trying to build",
}

__all__ = ["add_atlas_subcommand"]


def cmd_atlas_vocabularies(_args: argparse.Namespace) -> int:
    """Load data/vocabularies/ into its tables. Nothing can reference a product until this runs."""
    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        counts = load_vocabularies(conn, settings)
    finally:
        conn.close()
    for table, count in sorted(counts.items()):
        print(f"  {table:<28}{count:>7}")
    return 0


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


def cmd_atlas_chassis(_args: argparse.Namespace) -> int:
    """Load the curated chassis profiles and show what is and is not recorded."""
    settings = Settings.load()
    profiles = load_profiles(settings)
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        counts = write_profiles(conn, profiles)
    finally:
        conn.close()
    for profile in profiles:
        mark = "*" if profile.is_selected else " "
        print(f"{mark} {profile.name_as_reported}")
        for line in iter_context(profile):
            print(f"      {line}")
        unknown = [
            name
            for name, value in (
                ("ploidy", profile.ploidy),
                ("rho_status", profile.rho_status),
                ("ferments_xylose", profile.ferments_xylose),
                ("isobutanol_tolerance_g_l", profile.isobutanol_tolerance_g_l),
            )
            if value is None
        ]
        if unknown:
            print(f"      not recorded: {', '.join(unknown)}")
        print()
    for table, count in counts.items():
        print(f"  {table:<26}{count:>7}")
    print()
    print("* = the chassis the route ranker scores against.")
    return 0


def cmd_atlas_loci(_args: argparse.Namespace) -> int:
    """The activator map as a design lookup: where an insert can go, and what it costs.

    This is benchmark BM-MIT-004's query shape — "for a proposed insertion locus, return
    utr_source, activator_required and displaced_gene". Until `mtdna_locus` existed the atlas
    could not answer it, although the map had been curated: the knowledge was in the repository
    and unreachable from a query.
    """
    settings = Settings.load()
    loci = load_activator_map(settings)
    gaps = load_programme_gaps(settings)
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        stored = write_loci(conn, loci)
        stored_gaps = write_programme_gaps(conn, gaps)
    finally:
        conn.close()

    print(f"{stored} mtDNA loci — where a heterologous ORF could go, and what it costs")
    print()
    print(f"{'locus':28}{'leader':10}{'displaces':12}{'resp':7}activators")
    for locus in loci:
        activators = ", ".join(locus.activators) if locus.activators else "NOT RECORDED"
        displaced = locus.displaced_if_used or "—"
        retained = {True: "kept", False: "lost", None: "?"}[locus.respiration_retained_if_used]
        print(f"{locus.locus:28}{locus.utr_source or '—':10}{displaced:12}{retained:7}{activators}")

    free = non_displacing_loci(loci)
    print()
    if free:
        names = ", ".join(locus.locus for locus in free)
        print(f"Displaces nothing and keeps respiration: {names}")
        print("  So MITOCHONDRIAL_PROGRAM.md §2.1's 'inserting costs you the gene whose UTR you")
        print("  borrowed' holds for the replacement route, and not in general.")
    else:
        print("Every locus costs a resident gene. Strategy E pays a respiration burden whatever")
        print("  it targets, and `rescue_strategy` is the only way to discharge it.")

    missing = loci_without_activator(loci)
    if missing:
        names = ", ".join(locus.locus for locus in missing)
        print()
        print(f"OFFERED AS TARGETS WITH NO ACTIVATOR RECORDED: {names}")
        print("  BM-MIT-004 exists to catch exactly this. An insert designed here has no named")
        print("  requirement, which reads as 'no requirement' and is not the same thing.")

    print()
    print(f"{stored_gaps} programme-level knowledge gaps recorded (kind='never_attempted'):")
    for gap in gaps:
        print(f"  {gap.status:6} {gap.description}")
    print("  MITOCHONDRIAL_PROGRAM.md §2.3 said the atlas recorded these. Until today it did not:")
    print("  knowledge_gap held 208 rows and none of this kind.")
    return 0


def cmd_atlas_routes(args: argparse.Namespace) -> int:
    """Enumerate, gate, rank and optionally store every route."""
    settings = Settings.load()
    parts = load_parts(settings)
    chassis = selected_profile(load_profiles(settings))
    routes = enumerate_routes(parts, chassis=chassis)
    ordered = rank(routes, objective=args.objective)
    excluded = [route for route in routes if not route.viable]

    print(f"{len(routes)} routes enumerated, {len(ordered)} viable, {len(excluded)} excluded")
    print(f"ranked by objective={args.objective} ({_OBJECTIVE_MEANS[args.objective]})")
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
    for line in iter_context(chassis):
        print(f"  {line}")
    conditional = sum(1 for r in routes for g in r.chassis_gates if not g.excludes)
    if conditional:
        print(f"  {conditional} route-gate(s) are conditional on the chassis, not disqualifying:")
        seen: set[str] = set()
        for route in routes:
            for gate in route.chassis_gates:
                if not gate.excludes and gate.message not in seen:
                    seen.add(gate.message)
                    print(f"      [{gate.kind}] {gate.message}")
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
    routes = rank(enumerate_routes(load_parts(settings)), objective=args.objective)
    loci = load_activator_map(settings)
    matches = [route for route in routes if args.route in route.id]
    if not matches:
        print(f"no route id contains {args.route!r}", file=sys.stderr)
        return 2
    for route in matches[: args.limit]:
        print(route.id)
        print(f"   {explain(route, objective=args.objective)}")
        for requirement in route.construction_requirements:
            print(f"   construction: {requirement}")
        for gap in route.transport_gaps:
            print(f"   transport gap: {gap}")
        for risk in route.cofactor_risks:
            print(f"   cofactor risk: {risk}")
        for line in describe_demand(route.redox_demand):
            print(f"   redox demand: {line}")
        # PLAN.md phase 3: a strategy-E route must name its locus, leader, displaced gene and
        # recoding requirement. Empty for every other strategy, because nothing is in the mtDNA.
        for line in insertion_plan(route.steps, loci):
            print(f"   mtDNA insertion: {line}")
    return 0


def _wrap(text: str, width: int = 92) -> list[str]:
    """Wrap a rule clause for the terminal. The clauses are the output that matters most in
    `atlas recall --rule`, so they get one obvious width rather than the terminal's."""
    return textwrap.wrap(text, width=width)


def cmd_atlas_recall(args: argparse.Namespace) -> int:
    """PLAN.md phase 3's first acceptance clause: does the enumerator re-discover the literature?

    Read-only, and deliberately so — this command reports on the atlas, it does not add to it.
    `create=False` because an absent database must be heard about: opening one would create an
    empty atlas and print "0 configurations", which reads as "phase 1 has curated nothing" when
    it means "you are pointed at the wrong file".
    """
    settings = Settings.load()
    if args.rule:
        print("THE MATCHING RULE, in the order the clauses are applied. First one wins.")
        print()
        for index, clause in enumerate(MATCHING_RULE, start=1):
            print(f"{index}. {clause.name}  ->  {clause.outcome}")
            for line in _wrap(clause.text):
                print(f"     {line}")
            print()
        return 0

    parts = load_parts(settings)
    # No chassis. A chassis gate excludes routes for THIS chassis, which is not a statement about
    # whether the enumerator can express somebody else's published build — and depressing recall
    # with it would attribute a curation question to the ranker.
    routes = enumerate_routes(parts)

    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        configurations = load_configurations(conn)
    finally:
        conn.close()

    chassis = selected_profile(load_profiles(settings))
    organism = chassis.organism_id if chassis is not None else None
    report = recall_report(configurations, parts, routes, chassis_organism_id=organism)

    for line in describe_report(report):
        print(line)
    print()
    print(f"scope: routes enumerated against no chassis; host organism {organism or 'unset'}")
    print("rule:  fermdb atlas recall --rule")
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

    p_vocab = atlas_sub.add_parser(
        "vocabularies",
        help="load data/vocabularies/ into product and product_theoretical_yield",
    )
    p_vocab.set_defaults(func=cmd_atlas_vocabularies)

    p_pathways = atlas_sub.add_parser(
        "pathways",
        help="load the curated pathways and parts catalog (refuses an unbalanced reaction)",
    )
    p_pathways.set_defaults(func=cmd_atlas_pathways)

    p_loci = atlas_sub.add_parser(
        "loci", help="the mtDNA activator map: where an insert can go and what it displaces"
    )
    p_loci.set_defaults(func=cmd_atlas_loci)

    p_routes = atlas_sub.add_parser("routes", help="enumerate, gate and rank every route (G.7)")
    p_routes.add_argument("--limit", type=int, default=15, help="how many ranked routes to show")
    p_routes.add_argument(
        "--write", action="store_true", help="store the routes and their knowledge gaps"
    )
    p_routes.add_argument(
        "--objective",
        choices=OBJECTIVES,
        default="easiest",
        help="which question to rank by: 'easiest' (least trouble to build) or 'programme' "
        "(what this programme is trying to build). They are different questions; the default "
        "answers the first, and programme_fit is unrecorded so both currently agree",
    )
    p_routes.set_defaults(func=cmd_atlas_routes)

    p_explain = atlas_sub.add_parser("explain", help="why one route ranks where it does")
    p_explain.add_argument("route", help="substring of a route id, e.g. 'E_mtdna' or 'kivd'")
    p_explain.add_argument("--limit", type=int, default=3, help="how many matches to explain")
    p_explain.add_argument("--objective", choices=OBJECTIVES, default="easiest")
    p_explain.set_defaults(func=cmd_atlas_explain)

    p_recall = atlas_sub.add_parser(
        "recall",
        help="phase 3 acceptance: does the enumerator re-discover every published configuration?",
    )
    p_recall.add_argument(
        "--rule",
        action="store_true",
        help="print the matching rule clause by clause and exit, without touching the database. "
        "The rule is the deliverable: a recall figure read without it means nothing",
    )
    p_recall.set_defaults(func=cmd_atlas_recall)

    p_chassis = atlas_sub.add_parser(
        "chassis", help="load the curated chassis profiles and show what is not recorded"
    )
    p_chassis.set_defaults(func=cmd_atlas_chassis)

    p_annotate = atlas_sub.add_parser(
        "annotate", help="fetch GO/Pfam/InterPro/EC from UniProt for every resolved gene"
    )
    p_annotate.set_defaults(func=cmd_atlas_annotate)
