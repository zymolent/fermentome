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
from pathlib import Path

from ..config import Settings
from ..db import open_db
from .coverage import page_readiness, read_coverage
from .genes import list_genes, read_gene
from .lexical import (
    BUILD_COMMAND,
    KIND_LABELS,
    IndexReport,
    LexicalError,
    build_index,
    fts5_available,
    index_status,
    search_lexical,
)
from .pathways import list_pathways, read_pathway
from .publications import corpus_shape, read_publication, search_publications
from .review import ReviewPacket, review_packet, review_queue
from .reviewhtml import build_review_page
from .traceability import WHY_IT_MATTERS, Walk, exit_code, walk_assertions

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

    stuck = report.by_state("awaiting_promoter")
    if stuck:
        print()
        print("Empty, but proposals are accepted and unwritable -- these wait on a")
        print("promoter, not a curator:")
        for entity in stuck:
            print(f"  {entity.label:<24}{entity.accepted_unpromotable:>4} proposal(s)")

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


def _print_packet(p: ReviewPacket) -> None:
    """One proposal, laid out so the quote is the thing the eye lands on."""
    print(f"{p.task_id}   {p.record_kind}  {p.record_path}   [{p.status}]")
    print(
        f"  source     {p.citation.source_id}"
        + (f"  ({p.citation.locator})" if p.citation.locator else "")
    )
    print(f"  span       {p.span.status}: {p.span.verdict.detail}")
    if p.span.context:
        print()
        for line in _wrap_text(p.span.context, 94):
            print(f"      {line}")
    print()
    print("  proposed")
    for field in p.fields:
        print(f"      {field.name:<30}{field.value.display}")
    print(f"      {'(model confidence)':<30}{p.model_confidence.display}")
    print()
    print(f"  on accept  {p.plan.note}")
    if p.times_proposed > 1:
        print(f"  history    proposed {p.times_proposed}x, rejected {p.times_rejected}x")
    for warning in p.warnings:
        print(f"  ! {warning.code:<24}{warning.message}")
    print()


def _wrap_text(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def cmd_query_review(args: argparse.Namespace) -> int:
    """Everything needed to judge a proposal, in one read."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    supplied = {"organism_id": args.organism} if args.organism else None
    try:
        if args.html:
            page = build_review_page(
                conn, settings=settings, curator=args.curator, supplied=supplied
            )
            target = Path(args.html)
            target.write_text(page, encoding="utf-8")
            print(f"wrote {target}  ({len(page) / 1024:.0f} KB)")
            print("Open it in a browser. Decisions stay in that browser and come out as")
            print("`fermdb curate` commands -- the page never writes to the atlas.")
            return 0
        packets: tuple[ReviewPacket, ...]
        if args.task:
            packets = (review_packet(conn, args.task, settings=settings, supplied=supplied),)
        else:
            kinds = (
                tuple(k.strip() for k in args.kind.split(",") if k.strip()) if args.kind else None
            )
            packets = review_queue(
                conn, limit=args.limit, kinds=kinds, settings=settings, supplied=supplied
            )
    finally:
        conn.close()

    if args.json:
        json.dump([p.as_json() for p in packets], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not packets:
        print("nothing pending", file=sys.stderr)
        return 0
    for packet in packets:
        _print_packet(packet)
    flagged = sum(1 for p in packets if p.needs_attention)
    print(f"{len(packets)} proposal(s), {flagged} with warnings")
    return 0


def cmd_query_publication(args: argparse.Namespace) -> int:
    """One paper: what is held of it, and every finding with the sentence it came from."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        if args.publication is None:
            if args.shape:
                shape = corpus_shape(conn)
                for key, count in shape.items():
                    print(f"  {key:<20}{count:>6}")
                return 0
            page = search_publications(
                conn,
                query=args.query,
                year=args.year,
                readable_only=args.readable,
                limit=args.limit,
            )
            for row in page:
                print(
                    f"{str(row['year'] or '----'):<6}{row['id']:<34}{str(row['title'] or '')[:60]}"
                )
            if page.truncated:
                print()
                print(f"showing {len(page)}; more matched. This is a page, not a total.")
            return 0
        read = read_publication(conn, args.publication, settings=settings)
    finally:
        conn.close()

    if read is None:
        print(f"no publication with id {args.publication!r}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(read.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(read.title.display)
    print(f"  {read.id}   {read.year.display}   {read.journal.display}")
    print(f"  full text  {read.fulltext.display}")
    if read.fulltext.characters.is_known:
        print(
            f"             {read.fulltext.characters.display} characters, "
            f"{read.fulltext.media_type.display}, licence {read.fulltext.license.display}"
        )
    if read.screening:
        print("  found by   " + ", ".join(f"{s.family} ({s.triage_state})" for s in read.screening))
    print()
    established = sum(1 for f in read.findings if f.is_established)
    print(
        f"  {len(read.findings)} finding(s), {established} established, "
        f"{len(read.unresolved_findings)} with a span that no longer resolves"
    )
    for finding in read.findings[: args.findings]:
        mark = "ok " if finding.resolves else "!! "
        print()
        print(
            f"  {mark}{finding.record_kind.display:<26}{finding.record_path.display:<20}"
            f"[{finding.task_status.display}]"
        )
        for line in _wrap_text(finding.context or finding.quote_as_recorded.display, 92):
            print(f"      {line}")
    if read.findings_truncated:
        print()
        print("more findings matched than were read; this is a page, not a total")
    return 0


def cmd_query_gene(args: argparse.Namespace) -> int:
    """One gene: identity, function, pathway role, and the sections the atlas cannot fill."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        if args.gene is None:
            for gene_id, name in list_genes(conn, limit=args.limit):
                print(f"{name:<12}{gene_id}")
            return 0
        read = read_gene(conn, args.gene)
    finally:
        conn.close()

    if read is None:
        print(f"no gene matching {args.gene!r}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(read.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{read.standard_name.display}  ({read.systematic_name.display})")
    print(f"  group      {read.gene_group_id.display}   anchor {read.gene_group_anchor.display}")
    print(f"  assembly   {read.assembly_accession.display}")
    print()
    print(f"  {len(read.reactions)} reaction(s), {len(read.competing_reactions)} competing")
    for role in read.reactions:
        mark = "drain" if role.competing.or_none() is True else "     "
        print(f"    {mark} {role.reaction_name.display[:46]:<48}{role.compartment.display}")
    print()
    print(f"  {len(read.annotations)} functional annotation(s)")
    by_source: dict[str, int] = {}
    for ann in read.annotations:
        by_source[ann.source] = by_source.get(ann.source, 0) + 1
    for source, count in sorted(by_source.items()):
        print(f"    {source:<16}{count:>4}")
    for ann in read.annotations[: args.terms]:
        print(f"      {ann.term_id:<16}{ann.term_label.display[:56]}")
    print()
    print("  not held by this page:")
    for section, why in read.absent_sections.items():
        print(f"    {section:<26}{why}")
    return 0


def _print_walk(walk: Walk, *, verbose: bool, allow_empty: bool) -> None:
    """The walk, hop by hop for what broke and one line for what did not."""
    for chain in walk.chains:
        broken = not chain.closes
        if not broken and not verbose:
            continue
        mark = "BROKEN" if broken else "ok    "
        print(f"{mark} {chain.assertion_id}  {chain.predicate}")
        print(f"         {chain.subject}  ->  {chain.object}   zone {chain.zone}")
        for item in chain.evidence:
            arms = "+".join(item.arms) or "no arm"
            state = "ok " if item.closes else "!! "
            print(f"         {state}{item.evidence_id}  {item.evidence_type:<20}[{arms}]")
            if verbose:
                print(f"             {' -> '.join(item.hops)}")
        for event, curator, at in chain.curation[:1]:
            print(f"         curation {event} by {curator or '(unnamed)'} at {at or '?'}")
        for failure in chain.all_breaks:
            print(f"         {failure}")
        print()

    if walk.is_vacuous:
        print("0 active assertions walked.")
        print()
        print("VACUOUS. Nothing was checked, so nothing was verified. PLAN.md J.5 calls a broken")
        print("chain 'a bug of the same severity as a failing unit test', and that severity comes")
        print("from the check being believed -- a pass here would be believed in exactly the same")
        print("way while having looked at no row at all. `assertion` holds zero rows today, which")
        print("is PLAN.md C.1's gap, not a clean bill of health.")
        print()
        if allow_empty:
            print("--allow-empty was given, so this is reported as a pass (exit 0). Delete the")
            print("flag once the atlas holds assertions: from that day it changes nothing, which")
            print("is exactly when it should go.")
        else:
            print("Exit 3 -- neither a pass nor a broken chain. Pass --allow-empty to accept it")
            print("as a pass while the atlas is still empty.")
        return

    print(f"walked {walk.n_walked} active assertion(s): {walk.n_closed} closed, ", end="")
    print(f"{len(walk.broken)} broken")

    breaks = walk.breaks_by_kind()
    if breaks:
        print()
        print("breaks by kind:")
        for kind, count in sorted(breaks.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {kind:<32}{count:>4}   {WHY_IT_MATTERS.get(kind, '')[:52]}")

    gaps = walk.gaps_by_kind()
    if gaps:
        print()
        print("hops J.5 names that the schema cannot traverse (reported, not failed):")
        for kind, count in sorted(gaps.items()):
            print(f"  {kind:<32}{count:>4}   {WHY_IT_MATTERS.get(kind, '')[:52]}")


def cmd_query_traceability(args: argparse.Namespace) -> int:
    """PLAN.md J.5's acceptance test: every active assertion, or where its chain breaks."""
    settings = Settings.load()
    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        walk = walk_assertions(conn, assertion_ids=args.assertion or None)
    finally:
        conn.close()

    if args.json:
        payload = walk.as_json()
        payload["allow_empty"] = bool(args.allow_empty)
        payload["exit_code"] = exit_code(walk, allow_empty=args.allow_empty)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return int(payload["exit_code"])

    _print_walk(walk, verbose=args.verbose, allow_empty=args.allow_empty)
    return exit_code(walk, allow_empty=args.allow_empty)


def _lexical_target(args: argparse.Namespace) -> Path:
    """Which database the lexical commands touch, said out loud before anything is written.

    `index-build` is the only command in this file that writes, and what it writes is a derived
    artifact. The database is still the caller's choice and is never guessed at here: `--db`, or
    the configured `db_file` (which `FERMDB_DB_FILE` overrides). Printed rather than assumed,
    because "which atlas did that just rebuild" is not a question anyone should have to answer
    from memory.
    """
    return Path(args.db) if args.db else Settings.load().db_file


def cmd_query_index_build(args: argparse.Namespace) -> int:
    """PLAN.md M.2's `index-build` pipeline, for the lexical half of it (O.1)."""
    target = _lexical_target(args)

    if args.status:
        conn = open_db(target, create=False)
        try:
            report = index_status(conn)
        finally:
            conn.close()
        if report is None:
            print(f"{target}: no lexical index; build one with `{BUILD_COMMAND}`")
            return 3
        if args.json:
            json.dump(report.as_json(), sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        _print_index_report(report, target)
        return 0

    if not fts5_available():
        print(
            "this interpreter's sqlite3 was built without FTS5, so the lexical index cannot be "
            "created. Nothing was written, and `fermdb query` keeps working on the substring "
            "search -- which is a substring search, and is not silently substituted here.",
            file=sys.stderr,
        )
        return 4

    print(f"building the lexical index in {target}")
    conn = open_db(target, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        report = build_index(conn)
    finally:
        conn.close()

    if args.json:
        json.dump(report.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_index_report(report, target)
    return 0


def _print_index_report(report: IndexReport, target: Path) -> None:
    print(f"{report.documents} document(s) indexed in {target}, built {report.built_at}")
    for kind, count in report.by_kind.items():
        print(f"  {kind:<16}{count:>8}")
    for kind, reason in report.skipped_kinds.items():
        print(f"  {kind:<16}{'skipped':>8}  {reason}")
    print()
    print(
        f"{report.graded_documents} of {report.documents} document(s) carry an evidence level; "
        "the rest score 0 on the evidence term"
    )
    print()
    print(f"synonym dictionary: {report.synonym_pairs} pair(s)")
    for source in report.synonym_sources:
        print(f"  {source.source:<16}{source.pairs:>6} pair(s) from {source.rows} row(s)")
        print(f"                    {source.note}")
    for note in report.notes:
        print()
        print(f"note: {note}")


def cmd_query_lexical(args: argparse.Namespace) -> int:
    """The lexical modality: ranked across kinds, with every term of the score shown."""
    target = _lexical_target(args)
    conn = open_db(target, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        hits = search_lexical(
            conn,
            args.term,
            kinds=tuple(args.kind) if args.kind else None,
            limit=args.limit,
        )
    except LexicalError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    finally:
        conn.close()

    payload = hits.as_json()
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if payload["synonyms_applied"]:
        for word, expansions in payload["synonyms_applied"].items():
            print(f"{word} also searched as: {', '.join(expansions)}")
        print()

    if not hits.hits:
        print(f"nothing matched {hits.term!r}")
        for caveat in payload["caveats"]:
            print(f"  note: {caveat}")
        return 0

    print(f"{'score':>7}  {'kind':<12}{'evidence':<12}{'what':<44}contributions")
    for hit in hits.hits:
        parts = "  ".join(
            f"{component.name} {component.contribution:+.2f}" for component in hit.components
        )
        print(
            f"{hit.score:>7.3f}  {hit.kind:<12}{hit.evidence.display:<12}"
            f"{hit.label[:42]:<44}{parts}"
        )
    print()
    for caveat in payload["caveats"]:
        print(f"note: {caveat}")
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

    p_review = query_sub.add_parser(
        "review",
        help="one proposal with its re-resolved quote, what accepting writes, and what to check",
    )
    p_review.add_argument("--task", help="one task id; omit for the next in the queue")
    p_review.add_argument("--limit", type=int, default=5, help="how many to show")
    p_review.add_argument("--kind", help="comma-separated record kinds, e.g. 'measurements'")
    p_review.add_argument("--organism", help="organism id, to plan strain promotion against")
    p_review.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_review.add_argument(
        "--html", metavar="PATH", help="write a self-contained review page for the whole queue"
    )
    p_review.add_argument(
        "--curator", default="curator", help="name written into the generated commands"
    )
    p_review.set_defaults(func=cmd_query_review)

    p_pub = query_sub.add_parser(
        "publication",
        help="one paper with every finding and the sentence it came from (P.2)",
    )
    p_pub.add_argument("publication", nargs="?", help="publication id; omit to search")
    p_pub.add_argument("--query", help="substring of the title")
    p_pub.add_argument("--year", type=int, help="publication year")
    p_pub.add_argument(
        "--readable", action="store_true", help="only papers whose full text is actually held"
    )
    p_pub.add_argument("--shape", action="store_true", help="corpus totals by what is held")
    p_pub.add_argument("--limit", type=int, default=20, help="how many to list")
    p_pub.add_argument("--findings", type=int, default=8, help="how many findings to show")
    p_pub.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_pub.set_defaults(func=cmd_query_publication)

    p_gene = query_sub.add_parser(
        "gene", help="one gene: function, pathway role, and what the atlas cannot fill (P.2)"
    )
    p_gene.add_argument("gene", nargs="?", help="id, systematic name (YLR355C) or standard (ILV5)")
    p_gene.add_argument("--limit", type=int, default=50, help="how many to list")
    p_gene.add_argument("--terms", type=int, default=6, help="how many annotation terms to show")
    p_gene.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_gene.set_defaults(func=cmd_query_gene)

    p_trace = query_sub.add_parser(
        "traceability",
        help="PLAN.md J.5's CI gate: walk every active assertion and name where its chain breaks",
    )
    p_trace.add_argument(
        "assertion", nargs="*", help="assertion ids to walk; omit for every active assertion"
    )
    p_trace.add_argument(
        "--verbose",
        action="store_true",
        help="print every assertion hop by hop, not only the broken ones",
    )
    p_trace.add_argument(
        "--allow-empty",
        action="store_true",
        help="treat a walk of zero assertions as a pass. Without it that case exits 3, because a "
        "check that reports success having looked at nothing is trusted exactly as much as one "
        "that verified something",
    )
    p_trace.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_trace.set_defaults(func=cmd_query_traceability)

    # PLAN.md M.2's `index-build`, and the modality it serves. A pipeline rather than a
    # migration, because the index is derived: `schema.sql` never mentions it, and rebuilding it
    # from scratch is always available.
    p_index = query_sub.add_parser(
        "index-build",
        help="build the FTS5 lexical index and its synonym dictionary (M.2, O.1)",
    )
    p_index.add_argument(
        "--db",
        help="database to build the index in; defaults to the configured db_file, which "
        "FERMDB_DB_FILE overrides. Always printed before anything is written",
    )
    p_index.add_argument(
        "--status",
        action="store_true",
        help="report the last build instead of rebuilding; exits 3 if there is no index",
    )
    p_index.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_index.set_defaults(func=cmd_query_index_build)

    p_lexical = query_sub.add_parser(
        "lexical",
        help="lexical search: FTS5, synonyms from the alias tables, evidence-aware ranking",
    )
    p_lexical.add_argument("term", help="identifiers, gene or strain names, accessions, words")
    p_lexical.add_argument(
        "--kind",
        action="append",
        choices=sorted(KIND_LABELS),
        help="restrict to one kind; repeatable",
    )
    p_lexical.add_argument("--limit", type=int, default=10, help="how many hits to show")
    p_lexical.add_argument("--db", help="database to search; defaults to the configured db_file")
    p_lexical.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_lexical.set_defaults(func=cmd_query_lexical)
