"""Command line for the recoder.

Deliberately argparse rather than Typer for now: no dependency means `python -m fermdb.cli`
works on a bare interpreter, including on the download instance. Typer arrives when the CLI
grows past this.

    python -m fermdb.cli recode  --seq ATGCTTCTGTGA --mode dual_safe
    python -m fermdb.cli check   --seq ATGCTTCTGTGA --compartment cytosol
    python -m fermdb.cli check   --seq ATGCTTCTGTGA --compartment mitochondrial_matrix \
                                 --encoding-genome mitochondrial
    python -m fermdb.cli tables
    python -m fermdb.cli config
    python -m fermdb.cli config check
    python -m fermdb.cli literature discover
    python -m fermdb.cli literature discover --family isobutanol_mitochondria
    python -m fermdb.cli literature discover --dry-run
    python -m fermdb.cli literature status
    python -m fermdb.cli literature rescreen --criterion E1
    python -m fermdb.cli literature manual-queue export --out queue.tsv
    python -m fermdb.cli literature manual-queue ingest --dir <folder>
    python -m fermdb.cli omics discover
    python -m fermdb.cli omics references fetch
    python -m fermdb.cli omics status
    python -m fermdb.cli omics load
    python -m fermdb.cli omics genes
    python -m fermdb.cli omics baseline --limit 15
    python -m fermdb.cli genomics load-gff3 <file.gff.gz> --dry-run \
        --assembly-accession GCF_000146045.2 \
        --organism-id YAA:ORG:saccharomyces-cerevisiae-s288c
    python -m fermdb.cli genomics load-gff3 <file.gff.gz> \
        --assembly-accession GCF_000146045.2 \
        --organism-id YAA:ORG:saccharomyces-cerevisiae-s288c
    python -m fermdb.cli atlas pathways
    python -m fermdb.cli atlas routes --limit 10 --write
    python -m fermdb.cli atlas explain E_mtdna
    python -m fermdb.cli atlas annotate
    python -m fermdb.cli extract run --pmid 12345678
    python -m fermdb.cli extract run --pmid 12345678 --dry-run
    python -m fermdb.cli curate next
    python -m fermdb.cli curate accept --task YAA:CTASK:... --curator me --reason "checked"
    python -m fermdb.cli curate reject --task YAA:CTASK:... --curator me --reason "not in paper"
    python -m fermdb.cli curate stats
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from . import curate
from .api.cli import add_serve_subcommand
from .config import Settings
from .curate.queue import CurationError, Curator
from .db import open_db
from .db.cli import add_db_subcommand
from .extract import (
    DEFAULT_EXTRACTION_SECTIONS,
    RECORD_KINDS,
    ExtractionError,
    ExtractionOutcome,
    SchemaBuildError,
    extract_publication,
    find_publication,
    load_source_text,
)
from .genetic_code import AMBIGUOUS_CODONS, TABLE_1, TABLE_3
from .genomics.cli import add_genomics_subcommand
from .literature.discovery import FamilyRunResult, run_family
from .literature.ethanol import (
    ADMISSIONS_FILE,
    CRITERION_BUDGET,
    PLAN_ACCEPTANCE_DISAGREES,
    PUBLICATION_CAP,
    SLOTS,
    AdmissionsFileError,
    admit,
    budget_status,
    install_admissions,
    load_admissions,
    load_layer_gaps,
    readable_candidates,
    unspent_report,
    verify_record_spans,
)
from .literature.eutils import EutilsClient, EutilsError
from .literature.manual_queue import IngestReport, export_queue, ingest_directory
from .literature.queries import (
    QueryFamiliesError,
    QueryFamily,
    family_status,
    load_query_families,
)
from .literature.rescreen import (
    PATTERNS_FILE as RESCREEN_PATTERNS_FILE,
)
from .literature.rescreen import (
    SCHEMA_CHANGE_REQUIRED,
    RescreenError,
    criterion_names,
    load_rescreen_patterns,
    rescreen,
    summary_lines,
    write_proposals,
)
from .literature.screening import corpus_counts
from .llm import (
    FileCache,
    LlmConfig,
    LlmError,
    Provider,
    ProviderError,
    ResultCache,
    build_provider,
)
from .metabolic.cli import add_atlas_subcommand
from .omics import add_omics_subcommand
from .paths import PathsConfigError
from .query.cli import add_query_subcommand
from .recode import RecodeError, check_compartment_safety, recode


def _read_sequence(args: argparse.Namespace) -> str:
    if args.seq:
        return str(args.seq)
    text = Path(args.fasta).read_text(encoding="utf-8")
    return "".join(line.strip() for line in text.splitlines() if not line.startswith(">"))


def _wrap(seq: str, width: int = 60) -> str:
    return "\n".join(seq[i : i + width] for i in range(0, len(seq), width))


def cmd_recode(args: argparse.Namespace) -> int:
    result = recode(_read_sequence(args), source_table=args.source_table, mode=args.mode)
    print(result.summary(), file=sys.stderr)
    print(f">recoded_{args.mode}")
    print(_wrap(result.sequence))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = check_compartment_safety(
        _read_sequence(args),
        args.compartment,
        encoding_genome=args.encoding_genome,
    )
    print(report.summary())
    return 0 if report.accepted else 1


def cmd_tables(_: argparse.Namespace) -> int:
    print("Codons that differ between table 1 (standard) and table 3 (yeast mitochondrial):\n")
    print(f"  {'codon':<8}{'table 1':<10}{'table 3'}")
    for codon in AMBIGUOUS_CODONS:
        print(f"  {codon:<8}{TABLE_1.codon_to_aa[codon]:<10}{TABLE_3.codon_to_aa[codon]}")
    print(
        "\nThe CUN block is the dangerous one: a leucine-rich nuclear gene moved into mtDNA "
        "\nmistranslates extensively while still looking like a sensible gene."
    )
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    settings = Settings.load()

    if args.config_action == "check":
        report = settings.check()
        for item in report.items:
            status = "ok" if item.ok else "MISSING"
            print(f"{item.tier:<8}{item.key:<20}{status:<14}{item.value}")
        return 0 if report.ok else 1

    print(f"{'tier':<8}{'key':<20}{'origin':<8}{'exists':<8}value")
    for entry in settings.describe():
        exists = "yes" if entry.value.exists() else "no"
        print(f"{entry.tier:<8}{entry.key:<20}{entry.origin:<8}{exists:<8}{entry.value}")
    return 0


def _literature_client() -> EutilsClient:
    """Build the E-utilities client from the environment (`FERMDB_NCBI_API_KEY`/`_EMAIL`).

    A factory function rather than a call inlined into `cmd_literature_discover`, purely so a test
    can monkeypatch it to return a client wired to a fake transport -- the CLI itself must never be
    the thing standing between a test and the real network.
    """
    return EutilsClient.from_env()


def cmd_literature_discover(args: argparse.Namespace) -> int:
    settings = Settings.load()
    families = load_query_families(settings.literature_dir / "query_families.yaml")

    if args.family is not None:
        try:
            selected: tuple[QueryFamily, ...] = (families[args.family],)
        except KeyError:
            print(
                f"error: unknown family {args.family!r}; known families: "
                f"{', '.join(families.names())}",
                file=sys.stderr,
            )
            return 2
    else:
        selected = families.families

    client = _literature_client()
    conn = open_db(settings.db_file)
    try:
        for family in selected:
            result = run_family(
                conn,
                client,
                family,
                query_families_version=families.version,
                max_records=args.max_records,
                dry_run=args.dry_run,
            )
            _print_discover_result(result, family.expected_count)
    finally:
        conn.close()
    return 0


def _print_discover_result(result: FamilyRunResult, expected_count: int) -> None:
    mode = " [dry-run: esearch only, nothing written]" if result.dry_run else ""
    print(
        f"{result.family}{mode}\n"
        f"  hit_count={result.hit_count} (expected_count={expected_count}) "
        f"retrieved={result.retrieved_count}\n"
        f"  included={result.included} needs_full_text={result.needs_full_text} "
        f"excluded={result.excluded}"
    )


def cmd_literature_status(args: argparse.Namespace) -> int:
    settings = Settings.load()
    families = load_query_families(settings.literature_dir / "query_families.yaml")
    conn = open_db(settings.db_file)
    try:
        statuses = family_status(conn, families)
    finally:
        conn.close()

    print(
        f"{'family':<34}{'tier':<11}{'expected':>9}{'last_hit':>9}{'drift':>7}"
        f"{'incl':>6}{'need_ft':>8}{'excl':>6}"
    )
    for status in statuses:
        last_hit = "-" if status.last_hit_count is None else str(status.last_hit_count)
        drift = "-" if status.drift is None else f"{status.drift:+d}"
        print(
            f"{status.family:<34}{status.product_tier:<11}{status.expected_count:>9}"
            f"{last_hit:>9}{drift:>7}{status.included:>6}{status.needs_full_text:>8}"
            f"{status.excluded:>6}"
        )

    # The counts above are DISCOVERY: what the queries returned and how discovery.py triaged it.
    # They are not a reading list, and every figure quoted off `publication` was read as one until
    # the owner's own screening was loaded on 2026-09-22. Printed here so the two are never again
    # confused by someone glancing at this command.
    conn = open_db(settings.db_file)
    try:
        counts = corpus_counts(conn)
    finally:
        conn.close()
    print()
    print(
        f"corpus: {counts['discovered']} discovered, {counts['excluded']} rejected by a curator, "
        f"{counts['working']} in the working set"
    )
    print(
        f"  of the working set: {counts['included']} affirmatively included, "
        f"{counts['borderline']} borderline, {counts['undecided']} never screened"
    )
    print(
        "  'never screened' is not 'rejected'. Discovery found these; nobody has read them yet, "
        "and\n  they stay in scope until somebody does."
    )
    return 0


def cmd_literature_rescreen(args: argparse.Namespace) -> int:
    """Screen stored full text for one criterion's evidence and propose candidates.

    Reads the database and writes nothing to it. That is the design, not a limitation of this
    command: a row a full-text screen produces has no `search_run` to point at, and
    `screening_record` requires one. `rescreen.SCHEMA_CHANGE_REQUIRED` spells out the migration
    that would give these rows a home; it is deliberately not applied here.
    """
    settings = Settings.load()
    try:
        patterns = load_rescreen_patterns(settings.literature_dir / RESCREEN_PATTERNS_FILE)
    except RescreenError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.criterion not in patterns.criteria_names():
        available = ", ".join(f"{c} ({label})" for c, label in criterion_names(patterns).items())
        print(
            f"error: no pattern set for criterion {args.criterion!r}; available: {available}.\n"
            f"A criterion belongs in {RESCREEN_PATTERNS_FILE} only with a measurement behind it "
            f"showing its evidence does not live in abstracts -- E1 is there because its "
            f"admission test is a genotype, which is a methods fact.",
            file=sys.stderr,
        )
        return 2

    conn = open_db(settings.db_file)
    try:
        result = rescreen(conn, settings, criterion=args.criterion, patterns=patterns)
    finally:
        conn.close()

    for line in summary_lines(result):
        print(line)

    if args.no_write:
        print("\n--no-write: no proposal document written")
    else:
        out = (
            Path(args.out)
            if args.out
            else settings.exports_dir / "rescreen" / f"{result.criterion}.yaml"
        )
        written = write_proposals(result, out, sectioned_only=not args.all_matches)
        print(f"\nproposals written to {written}")

    print(f"\nNOT STORED AS screening_record ROWS. {SCHEMA_CHANGE_REQUIRED}")
    return 0


def cmd_literature_ethanol_status(_args: argparse.Namespace) -> int:
    """The ethanol layer's seven slots, their budgets, and what is spent against each."""
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        lines = budget_status(conn)
        readable = {c: len(readable_candidates(conn, c)) for c in CRITERION_BUDGET}
        unspent = unspent_report(conn)
    finally:
        conn.close()

    print(f"{'slot':<5}{'name':<42}{'crit':<6}{'budget':>7}{'admitted':>9}{'readable':>10}")
    for slot in SLOTS:
        line = next(entry for entry in lines if entry.criterion == slot.criterion)
        print(
            f"{slot.number:<5}{slot.name:<42}{slot.criterion:<6}{line.budget:>7}"
            f"{line.admitted:>9}{readable[slot.criterion]:>10}"
        )
    total_budget = sum(CRITERION_BUDGET.values())
    total_admitted = sum(entry.admitted for entry in lines)
    print()
    print(
        f"layer: {total_admitted}/{PUBLICATION_CAP} publications admitted "
        f"({total_budget} allocated across criteria)"
    )

    # A criterion whose readable pool is smaller than its budget cannot fill it from what is
    # held, and that is a finding about acquisition, not a reason to quietly reallocate.
    short = [c for c, n in readable.items() if n < CRITERION_BUDGET[c]]
    if short:
        print()
        for criterion in sorted(short, key=lambda c: CRITERION_BUDGET[c] - readable[c]):
            print(
                f"  SHORT  {criterion}: {readable[criterion]} readable against a budget of "
                f"{CRITERION_BUDGET[criterion]} -- the rest need acquiring, not reallocating"
            )
    if unspent:
        print()
        print("unspent (reported, never reallocated automatically):")
        for line_text in unspent:
            print(f"  {line_text}")
    print()
    print(f"NOTE: {PLAN_ACCEPTANCE_DISAGREES}")
    return 0


def cmd_literature_ethanol_admit(args: argparse.Namespace) -> int:
    """Admit one publication under one criterion, or say exactly why it cannot be."""
    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        problems = admit(
            conn,
            settings,
            publication_id=args.publication_id,
            criterion=args.criterion,
            slot=args.slot,
        )
    finally:
        conn.close()

    if not problems:
        print(f"admitted {args.publication_id} under {args.criterion}")
        return 0
    print(f"NOT admitted: {args.publication_id} under {args.criterion}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem.code}: {problem.detail}", file=sys.stderr)
    return 1


def cmd_literature_ethanol_install(args: argparse.Namespace) -> int:
    """Install `data/literature/ethanol_admissions.yaml` — the curated layer — into the database.

    `--dry-run` loads the file, re-resolves every quote against the stored full text and prints
    what would happen, without writing. It is the form to run first: the offsets are into the
    `fulltext_asset` store, and a derived tier rebuilt without re-acquiring will fail the check
    rather than install a criterion backed by a quote nobody can re-read.
    """
    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        try:
            records = load_admissions(settings)
            gaps = load_layer_gaps(settings)
        except AdmissionsFileError as exc:
            print(f"{ADMISSIONS_FILE}: {exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            checks = verify_record_spans(conn, settings, records)
            failed = [check for check in checks if not check.ok]
            print(f"{len(records)} records, {len(gaps)} gap(s)")
            print(f"spans: {len(checks) - len(failed)} of {len(checks)} re-resolved exact")
            for check in failed:
                print(
                    f"  FAIL {check.publication_id} evidence[{check.index}] {check.code}: "
                    f"{check.detail}",
                    file=sys.stderr,
                )
            return 1 if failed else 0

        report = install_admissions(conn, settings)
    finally:
        conn.close()

    print(
        f"spans: {report.spans_checked - len(report.span_failures)} of {report.spans_checked} "
        f"re-resolved exact"
    )
    print(f"admitted: {len(report.admitted)} of {len(records)}")
    print(f"knowledge_gap rows written: {report.gaps_written}")
    for check in report.span_failures:
        print(
            f"  SPAN {check.publication_id} evidence[{check.index}] {check.code}: {check.detail}",
            file=sys.stderr,
        )
    for publication_id, problem in report.refused:
        print(
            f"  NOT admitted {publication_id} — {problem.code}: {problem.detail}", file=sys.stderr
        )
    return 1 if report.refused else 0


def cmd_literature_manual_queue_export(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        count = export_queue(conn, Path(args.out))
    finally:
        conn.close()
    print(f"wrote {count} row(s) to {args.out}", file=sys.stderr)
    return 0


def cmd_literature_manual_queue_ingest(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        report = ingest_directory(
            conn, Path(args.dir), settings=settings, check_titles=not args.no_title_check
        )
    finally:
        conn.close()
    _print_ingest_report(report)
    return 0 if not (report.unmatched or report.title_mismatched) else 1


def _print_ingest_report(report: IngestReport) -> None:
    for match in report.matched:
        print(f"provided: {match.path.name} -> {match.queue_id}")
    for path in report.already_provided:
        print(f"already provided, skipped: {path.name}")
    for path in report.unmatched:
        print(f"could not match: {path.name}", file=sys.stderr)
    for mismatch in report.title_mismatched:
        print(
            f"NOT STORED, content does not match the DOI it is filed under: "
            f"{mismatch.path.name} ({mismatch.overlap:.0%} title overlap)\n"
            f"    expected: {mismatch.expected_title}\n"
            f"    re-check the file; --no-title-check stores it anyway",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------------------------


def _extract_provider(config: LlmConfig) -> Provider:
    """Build the configured LLM provider.

    A function rather than an inline call for the same reason `_literature_client` above is one: a
    test monkeypatches it to hand back a mock, so the CLI is never what stands between the test
    suite and a real model call. The default provider is `mock`, so an unconfigured run fails
    locally and loudly instead of quietly reaching a daemon.
    """
    return build_provider(config)


def _extract_cache(config: LlmConfig) -> ResultCache | None:
    """The on-disk result cache, if configuration enables one.

    PLAN.md L.3/V.4: caching on (input_hash, model, prompt_version) is what makes a prompt
    revision re-run only what the revision changed, which on a 3000-paper corpus is the difference
    between an afternoon and a week.
    """
    if not config.cache_enabled or config.cache_dir is None:
        return None
    return FileCache(config.cache_dir)


def _resolve_publication_id(conn: object, args: argparse.Namespace) -> str:
    """Turn --pmid / --doi / --publication-id into the id of an existing publication row."""
    if args.publication_id:
        return str(args.publication_id)
    row = find_publication(conn, pmid=args.pmid, doi=args.doi)  # type: ignore[arg-type]
    if row is None:
        wanted = args.pmid or args.doi
        raise ExtractionError(
            f"no publication row for {wanted!r}. Extraction will not create one: a publication "
            f"record is Zone R and no agent may write there (PLAN.md L.5). Run "
            f"`fermdb literature discover` first."
        )
    return str(row["id"])


def cmd_extract_brief(args: argparse.Namespace) -> int:
    """Print only the passages of one paper that could support a record."""
    from .extract.brief import build_brief

    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        publication_id = _resolve_publication_id(conn, args)
        excerpt, sections = build_brief(conn, settings, publication_id=publication_id)
    finally:
        conn.close()
    print(f"{publication_id}  [{len(excerpt):,} characters of methods and results]")
    for section in sections:
        print()
        print(f"===== {section.title} =====")
        if not section.passages:
            print("  (nothing matched)")
        for passage in section.passages:
            print(f"  - {passage[: args.width]}")
    return 0


def cmd_extract_run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        publication_id = _resolve_publication_id(conn, args)
        if args.text_file:
            source_text = Path(args.text_file).read_text(encoding="utf-8")
            origin = str(args.text_file)
        else:
            source_text, origin = load_source_text(conn, settings, publication_id=publication_id)

        config = LlmConfig.load(settings)
        sections = (
            tuple(part.strip() for part in args.sections.split(",") if part.strip())
            if args.sections
            else DEFAULT_EXTRACTION_SECTIONS
        )
        kinds = tuple(args.only_kinds) if args.only_kinds else None
        if kinds is not None:
            unknown = [k for k in kinds if k not in RECORD_KINDS]
            if unknown:
                print(
                    f"unknown record kind(s) {unknown}; known kinds are {list(RECORD_KINDS)}",
                    file=sys.stderr,
                )
                return 2
        print(
            f"{publication_id}: provider={config.provider} "
            f"model={config.model_for('extraction')} sections={','.join(sections)} "
            f"kinds={','.join(kinds) if kinds else 'all'} "
            f"source={origin}",
            file=sys.stderr,
        )

        outcome = extract_publication(
            conn,
            publication_id=publication_id,
            source_text=source_text,
            provider=_extract_provider(config),
            config=config,
            settings=settings,
            sections=sections,
            cache=_extract_cache(config),
            run_id=args.run_id,
            write=not args.dry_run,
            max_excerpt_chars=args.max_excerpt_chars,
            kinds=kinds,
        )
        _print_extraction_outcome(outcome, dry_run=args.dry_run)

        if args.dry_run or outcome.extraction_id is None or args.no_enqueue:
            return 0
        created = curate.enqueue_extraction(conn, outcome.extraction_id)
        print(f"queued {len(created)} curation task(s)")
    finally:
        conn.close()
    return 0


def _print_extraction_outcome(outcome: ExtractionOutcome, *, dry_run: bool) -> None:
    print(outcome.summary())
    print(
        f"  prompt_version={outcome.prompt_version} model={outcome.stats.model_version} "
        f"attempts={outcome.stats.attempts} cache_hit={outcome.stats.cache_hit} "
        f"tokens={outcome.stats.total_tokens}"
    )
    for attempt, errors in enumerate(outcome.failed_attempts, start=1):
        for error in errors:
            print(f"  attempt {attempt} rejected: {error}", file=sys.stderr)
    for note in outcome.notes:
        print(f"  note {note.record_path} [{note.code}] {note.message}", file=sys.stderr)
    if dry_run:
        print("  dry run: nothing written", file=sys.stderr)
    else:
        print(f"  extraction_id={outcome.extraction_id} review_state=proposed zone=I")


# ---------------------------------------------------------------------------------------------
# curate
# ---------------------------------------------------------------------------------------------


def cmd_curate_scan(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        created = curate.enqueue_pending_extractions(conn, limit=args.limit)
    finally:
        conn.close()
    print(f"queued {len(created)} curation task(s)")
    return 0


def cmd_curate_next(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        kinds = (
            tuple(part.strip() for part in args.kind.split(",") if part.strip())
            if args.kind
            else None
        )
        tasks = curate.peek(conn, limit=args.limit, kinds=kinds)
        for task in tasks:
            print(task.summary())
            if args.show_record:
                print(json.dumps(task.record, indent=2, sort_keys=True))
    finally:
        conn.close()
    if not tasks:
        print("nothing pending", file=sys.stderr)
    return 0


def _curate_resolve(args: argparse.Namespace, action: str) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        # Always 'human': this path exists because a person typed the command. An automated
        # worker uses the Python API with kind='agent', where accept/edit/reject are refused
        # (PLAN.md L.5).
        curator = Curator(name=args.curator, kind="human")
        if action == "accept":
            task = curate.accept(conn, args.task, curator=curator, reason=args.reason)
        else:
            task = curate.reject(conn, args.task, curator=curator, reason=args.reason)
    finally:
        conn.close()
    print(f"{task.id} -> {task.status} by {task.curator} at {task.resolved_at}")
    return 0


def cmd_curate_accept(args: argparse.Namespace) -> int:
    return _curate_resolve(args, "accept")


def cmd_curate_reject(args: argparse.Namespace) -> int:
    return _curate_resolve(args, "reject")


def cmd_curate_corroborate(args: argparse.Namespace) -> int:
    """Split the pending queue by whether each proposal's own quote supports it.

    Reports by default and writes nothing. `--accept` is what turns the report into verdicts, and
    it takes a curator for the same reason `accept` does: a person is deciding that a quote naming
    its own subject is good enough to admit without reading the paper. That decision is theirs,
    the gate only sorts.
    """
    from .curate.corroborate import ACCEPT, corroborate_queue

    if args.accept and not args.curator:
        print("--accept needs --curator: the verdict is recorded against a person", file=sys.stderr)
        return 2

    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        reports = corroborate_queue(conn)
        if args.kind:
            wanted = {part.strip() for part in args.kind.split(",") if part.strip()}
            reports = tuple(r for r in reports if r.record_kind in wanted)

        corroborated = [r for r in reports if r.verdict == ACCEPT]
        needs_review = [r for r in reports if r.verdict != ACCEPT]

        print(
            f"{len(reports)} pending; {len(corroborated)} corroborated, "
            f"{len(needs_review)} need a reader"
        )
        by_kind: dict[str, list[int]] = {}
        for report in reports:
            counts = by_kind.setdefault(report.record_kind, [0, 0])
            counts[0 if report.verdict == ACCEPT else 1] += 1
        for kind, (ok, review) in sorted(by_kind.items()):
            print(f"  {kind:<28} {ok:>4} corroborated  {review:>4} review")

        if args.show_absent:
            print("\nwhat the quote does not carry:")
            missing_counts: dict[str, int] = {}
            for report in needs_review:
                for field in report.absent:
                    missing_counts[f"{report.record_kind}.{field}"] = (
                        missing_counts.get(f"{report.record_kind}.{field}", 0) + 1
                    )
            for field, count in sorted(missing_counts.items(), key=lambda kv: -kv[1]):
                print(f"  {field:<48} {count:>4}")

        if not args.accept:
            print("\nreport only; nothing written. Re-run with --accept --curator NAME to apply.")
            return 0

        curator = Curator(name=args.curator, kind="human")
        applied = 0
        for report in corroborated:
            evidenced = ", ".join(f"{c.field}={c.claimed!r}" for c in report.checks)
            reason = (
                "corroboration gate: the cited quote itself contains " + evidenced + ". "
                "Accepted in bulk without a reader opening the paper, on the grounds that the "
                "subject was read from the span rather than inferred from surrounding text. "
                "This attests to attribution, not to truth."
            )
            curate.accept(conn, report.task_id, curator=curator, reason=reason)
            applied += 1
    finally:
        conn.close()
    print(f"\naccepted {applied} corroborated proposal(s); {len(needs_review)} left for review")
    return 0


#: Supplied fields that are a property of ONE PAPER, and the record kinds each one reaches.
#:
#: A curator who has read a paper can assert these for that paper. Across papers they are a guess
#: about papers nobody opened for this run -- and `_plan_configuration` already refuses to make
#: exactly this guess for `host_strain_id`, so making it through a CLI flag instead is the same
#: error wearing a different hat.
_PAPER_SCOPED: Final[Mapping[str, tuple[str, ...]]] = {
    "organism_id": ("strains",),
    "basis": ("measurements", "co_reported_higher_alcohols"),
    "product_id": ("measurements", "co_reported_higher_alcohols", "pathway_configurations"),
    "host_strain_id": ("pathway_configurations", "part_expression_records"),
    "pathway_id": ("pathway_configurations",),
}

#: Supplied fields that name ONE SPECIFIC ROW. These are wrong for more than one task at all,
#: within a paper as much as across papers: two configurations cannot share `--name`, and two
#: expression records naming different genes cannot share one `--part` catalog id.
_RECORD_SCOPED: Final[Mapping[str, tuple[str, ...]]] = {
    "name": ("pathway_configurations",),
    "part_id": ("part_expression_records",),
    "outcome_measurement_id": ("part_expression_records",),
    # Both are record-scoped, and `is_isolated_effect` is the one that would do real damage in
    # bulk. Two modifications in the SAME paper routinely differ -- a strain carrying a deletion
    # and an overexpression has neither made alone -- so one --isolated-effect stamped across a
    # promote run would assert single-gene attribution for a whole combination strain. That is
    # precisely the misattribution PLAN.md I.4 introduced the column to prevent, arriving through
    # the column itself.
    "is_isolated_effect": ("modifications",),
    "intent": ("modifications",),
}

_FLAG_FOR: Final[Mapping[str, str]] = {
    "organism_id": "--organism",
    "basis": "--basis",
    "product_id": "--product",
    "host_strain_id": "--host-strain",
    "pathway_id": "--pathway",
    "name": "--name",
    "part_id": "--part",
    "outcome_measurement_id": "--outcome-measurement",
    "is_isolated_effect": "--isolated-effect",
    "intent": "--intent",
}


def cmd_curate_duplicates(args: argparse.Namespace) -> int:
    """Proposals describing a measurement the atlas already holds. Reports; writes nothing."""
    from .curate.duplicates import find_duplicates

    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        found = find_duplicates(conn)
    finally:
        conn.close()

    if not found:
        print("no pending proposal duplicates a promoted measurement")
        return 0

    richer = [d for d in found if d.supersedes]
    print(
        f"{len(found)} proposal(s) describe a measurement already in the atlas; "
        f"{len(richer)} of them carry fields the promoted row does not"
    )
    if args.verbose:
        for item in found:
            print(f"  {item.line()}")
    print(
        "\nThese get different ids, because proposal_hash covers the quote and these quotes "
        "differ. So promoting them writes SECOND rows rather than updating the first, and the "
        "id-level 'already present' check will not catch it.\n"
        "The richer ones are supersessions, not repeats -- keeping both, or retracting the "
        "thinner row, is a curator's decision under PLAN.md J.1 and L.5. Nothing here does it."
    )
    return 0


def _bulk_supply_spread(conn: sqlite3.Connection, supplied: Mapping[str, Any]) -> str | None:
    """Refuse a `--flag` value stamped across rows it cannot be true of. None means proceed.

    `cmd_curate_promote` builds `supplied` once and hands the same mapping to every task in the
    bulk path, so any of these flags used without `--task` reaches every accepted record of the
    kinds it applies to. Measured on the queue of 2026-09-22: `--organism` would have written one
    organism onto 222 strains from 11 publications, at least 19 of them *E. coli* -- and the
    yeast ones are not one organism either, since BY4741 and CEN.PK2-1C have separate `organism`
    rows here.

    The two classes fail differently and so are refused differently. A **paper-scoped** value is
    defensible for one publication and a guess across several, so it is refused only on a spread.
    A **record-scoped** value names one row, so it is wrong for any two tasks at all -- the
    clearest case being `--product`, which `_plan_configuration` refuses to default precisely
    because filing a 3-HP build as an isobutanol one is what that would do.

    The message names the spread and the fix, and says which promotions are unaffected: a guard
    that blocks the useful path alongside the dangerous one is an obstacle, not a guard.
    """
    for field_name, kinds in {**_PAPER_SCOPED, **_RECORD_SCOPED}.items():
        value = supplied.get(field_name)
        if not value:
            continue
        placeholders = ", ".join("?" for _ in kinds)
        rows = conn.execute(
            "SELECT publication_id, COUNT(*) n FROM curation_task "  # noqa: S608
            f"WHERE status IN ('accepted','edited') AND record_kind IN ({placeholders}) "
            "GROUP BY publication_id ORDER BY n DESC",
            kinds,
        ).fetchall()
        total = sum(int(r["n"]) for r in rows)
        record_scoped = field_name in _RECORD_SCOPED
        if total <= 1 or (not record_scoped and len(rows) <= 1):
            continue

        flag = _FLAG_FOR[field_name]
        listing = "\n".join(f"    {r['n']:>4}  {r['publication_id']}" for r in rows)
        why = (
            f"{flag} names one specific row, so it cannot be true of {total} of them."
            if record_scoped
            else (
                f"One {flag} value across {len(rows)} papers is a guess about papers nobody read "
                "for this run."
            )
        )
        return (
            f"refusing {flag} {value!r} for a bulk promotion: it would be written onto {total} "
            f"accepted {'/'.join(kinds)} proposal(s) from {len(rows)} publication(s).\n"
            f"{listing}\n"
            f"{why}\n"
            "Promote one task at a time instead:\n"
            f"    fermdb curate promote --task <id> {flag} <value> --curator NAME --reason ...\n"
            f"Promotions that need no {flag} are unaffected -- rerun without it to write those "
            "first."
        )
    return None


def cmd_curate_promote(args: argparse.Namespace) -> int:
    """Write the rows that accepted proposals describe, or say precisely why each cannot."""
    from .curate.promote import NotPromotable, plan_promotion, promote, promote_ready

    settings = Settings.load()
    conn = open_db(settings.db_file)
    supplied = {
        k: v
        for k, v in (
            ("organism_id", args.organism),
            ("basis", args.basis),
            ("host_strain_id", args.host_strain_id),
            ("product_id", args.product_id),
            ("pathway_id", args.pathway_id),
            ("name", args.name),
            ("part_id", args.part_id),
            ("outcome_measurement_id", args.outcome_measurement_id),
            ("is_isolated_effect", args.is_isolated_effect),
            ("intent", args.intent),
        )
        if v
    }
    curator = Curator(name=args.curator, kind="human")
    try:
        if not args.task:
            spread = _bulk_supply_spread(conn, supplied)
            if spread is not None:
                print(spread, file=sys.stderr)
                return 2

        if args.task:
            task = curate.get_task(conn, args.task)
            if args.dry_run:
                print(plan_promotion(conn, task, settings=settings, supplied=supplied).note)
                return 0
            try:
                result = promote(
                    conn,
                    args.task,
                    curator=curator,
                    reason=args.reason,
                    settings=settings,
                    supplied=supplied,
                )
            except NotPromotable as exc:
                print(str(exc), file=sys.stderr)
                return 1
            verb = "wrote" if result.created else "already present:"
            print(f"{verb} {result.target_table} {result.row_id}")
            return 0

        if args.dry_run:
            rows = conn.execute(
                "SELECT id FROM curation_task WHERE status IN ('accepted','edited') ORDER BY id"
            ).fetchall()
            ready = 0
            for row in rows:
                plan = plan_promotion(
                    conn,
                    curate.get_task(conn, str(row["id"])),
                    settings=settings,
                    supplied=supplied,
                )
                ready += plan.ready
                print(
                    f"  {'READY ' if plan.ready else 'blocked'} {plan.record_kind:<24}{plan.note}"
                )
            print()
            print(f"{ready} of {len(rows)} resolved task(s) would promote")
            return 0

        done, blocked = promote_ready(
            conn,
            curator=curator,
            reason=args.reason,
            settings=settings,
            supplied=supplied,
        )
    finally:
        conn.close()

    for result in done:
        print(f"  wrote {result.target_table:<16}{result.row_id}")
    if blocked:
        print()
        print(f"{len(blocked)} not promoted:")
        for plan in blocked:
            print(f"  {plan.record_kind:<24}{plan.note}")
    print()
    print(f"{len(done)} promoted, {len(blocked)} not")
    return 0


def cmd_curate_stats(args: argparse.Namespace) -> int:
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        stats = curate.queue_stats(conn)
        repeats = curate.repeat_offenders(conn)
    finally:
        conn.close()
    print(stats.summary())
    if repeats:
        print("\nproposals a curator rejected and the model made again:")
        for signal in repeats:
            print(
                f"  {signal.record_kind:<28} {signal.publication_id:<24} "
                f"proposed={signal.times_proposed} rejected={signal.times_rejected} "
                f"model={signal.model or '-'}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fermdb", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_seq_args(p: argparse.ArgumentParser) -> None:
        src = p.add_mutually_exclusive_group(required=True)
        src.add_argument("--seq", help="nucleotide sequence")
        src.add_argument("--fasta", help="path to a FASTA file")

    p_recode = sub.add_parser("recode", help="recode a coding sequence")
    add_seq_args(p_recode)
    p_recode.add_argument(
        "--mode", default="dual_safe", choices=["dual_safe", "to_table3", "to_table1"]
    )
    p_recode.add_argument(
        "--source-table", dest="source_table", type=int, default=1, choices=[1, 3]
    )
    p_recode.set_defaults(func=cmd_recode)

    p_check = sub.add_parser("check", help="check a sequence against a compartment")
    add_seq_args(p_check)
    p_check.add_argument("--compartment", required=True)
    # D1: the code follows the encoding genome, not the compartment. Required in practice for a
    # compartment served by both genomes; omitting it there is an error, not a default to table 3.
    p_check.add_argument(
        "--encoding-genome",
        dest="encoding_genome",
        choices=["nuclear", "mitochondrial"],
        default=None,
        help="genome that carries the gene; required for mitochondrial_matrix and "
        "mitochondrial_inner_membrane, which hold proteins from both",
    )
    p_check.set_defaults(func=cmd_check)

    p_tables = sub.add_parser("tables", help="show the codons that differ between the tables")
    p_tables.set_defaults(func=cmd_tables)

    p_config = sub.add_parser("config", help="show or check the resolved path configuration")
    p_config.add_argument(
        "config_action",
        nargs="?",
        choices=["check"],
        default=None,
        help="omit to print every key; 'check' to verify paths and create derived directories",
    )
    p_config.set_defaults(func=cmd_config)

    p_literature = sub.add_parser(
        "literature", help="literature discovery: NCBI E-utilities corpus search and triage"
    )
    lit_sub = p_literature.add_subparsers(dest="literature_command", required=True)

    p_lit_discover = lit_sub.add_parser(
        "discover", help="run one or every query family in data/literature/query_families.yaml"
    )
    p_lit_discover.add_argument(
        "--family", default=None, help="run only this family (default: every family)"
    )
    p_lit_discover.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="report esearch hit counts only; fetch nothing and write nothing to the database",
    )
    p_lit_discover.add_argument(
        "--max-records",
        dest="max_records",
        type=int,
        default=None,
        help="cap ids retrieved per family (or per B.3 sub-query); default: no cap",
    )
    p_lit_discover.set_defaults(func=cmd_literature_discover)

    p_lit_status = lit_sub.add_parser(
        "status", help="corpus counts per family against query_families.yaml's expected_count"
    )
    p_lit_status.set_defaults(func=cmd_literature_status)

    p_lit_rescreen = lit_sub.add_parser(
        "rescreen",
        help="re-screen stored full text for a criterion whose evidence is not in abstracts",
        description=(
            "Screen stored full text for one B.3 criterion's evidence and propose candidates. "
            "Reads the database, writes no rows to it, and admits nothing: every proposal is "
            f"review_state='proposed'. Patterns come from data/literature/{RESCREEN_PATTERNS_FILE}."
        ),
    )
    p_lit_rescreen.add_argument(
        "--criterion",
        required=True,
        help="which B.3 criterion to screen for; only criteria defined in "
        f"{RESCREEN_PATTERNS_FILE} are available (today: E1)",
    )
    p_lit_rescreen.add_argument(
        "--out",
        default=None,
        help="where to write the proposal document (default: "
        "<exports_dir>/rescreen/<criterion>.yaml)",
    )
    p_lit_rescreen.add_argument(
        "--all-matches",
        dest="all_matches",
        action="store_true",
        help="include candidates whose genotype match landed outside Methods/Results. Reproduces "
        "the looser measurement; expect passing Discussion citations in the extra rows",
    )
    p_lit_rescreen.add_argument(
        "--no-write",
        dest="no_write",
        action="store_true",
        help="report only; do not write the proposal document",
    )
    p_lit_rescreen.set_defaults(func=cmd_literature_rescreen)

    p_lit_ethanol = lit_sub.add_parser(
        "ethanol", help="the capped ethanol reference layer: slots, budgets and admission"
    )
    eth_sub = p_lit_ethanol.add_subparsers(dest="ethanol_command", required=True)

    p_eth_status = eth_sub.add_parser("status", help="slots, budgets, and what is spent")
    p_eth_status.set_defaults(func=cmd_literature_ethanol_status)

    p_eth_admit = eth_sub.add_parser("admit", help="admit one publication under one criterion")
    p_eth_admit.add_argument("--publication-id", required=True)
    p_eth_admit.add_argument("--criterion", required=True, choices=sorted(CRITERION_BUDGET))
    p_eth_admit.add_argument("--slot", type=int, default=None, help="cross-check the slot")
    p_eth_admit.set_defaults(func=cmd_literature_ethanol_admit)

    p_eth_install = eth_sub.add_parser(
        "install",
        help=f"install the curated layer from data/literature/{ADMISSIONS_FILE}",
    )
    p_eth_install.add_argument(
        "--dry-run",
        action="store_true",
        help="re-resolve every quote and report, without writing anything",
    )
    p_eth_install.set_defaults(func=cmd_literature_ethanol_install)

    p_lit_manual_queue = lit_sub.add_parser(
        "manual-queue", help="the manual full-text download queue (export / ingest)"
    )
    mq_sub = p_lit_manual_queue.add_subparsers(dest="manual_queue_command", required=True)

    p_mq_export = mq_sub.add_parser(
        "export", help="write pending rows out as a priority-sorted TSV worklist"
    )
    p_mq_export.add_argument("--out", required=True, help="output TSV path")
    p_mq_export.set_defaults(func=cmd_literature_manual_queue_export)

    p_mq_ingest = mq_sub.add_parser(
        "ingest", help="match files dropped into a folder back to queue rows by PMID or DOI"
    )
    p_mq_ingest.add_argument(
        "--dir", required=True, dest="dir", help="folder of PDFs named by PMID or DOI"
    )
    p_mq_ingest.add_argument(
        "--no-title-check",
        action="store_true",
        help="store a file even when its own text does not look like the paper its filename "
        "claims. Use only after looking at the file: the check exists because 3 of 127 "
        "owner-supplied PDFs were a different paper than their DOI",
    )
    p_mq_ingest.set_defaults(func=cmd_literature_manual_queue_ingest)

    add_omics_subcommand(sub)
    add_genomics_subcommand(sub)
    add_atlas_subcommand(sub)
    add_query_subcommand(sub)
    add_db_subcommand(sub)
    add_serve_subcommand(sub)

    p_extract = sub.add_parser(
        "extract", help="LLM extraction of one publication into a proposed Zone I row"
    )
    ex_sub = p_extract.add_subparsers(dest="extract_command", required=True)

    p_ex_brief = ex_sub.add_parser(
        "brief", help="print only the passages that could support a record, for reading"
    )
    brief_target = p_ex_brief.add_mutually_exclusive_group(required=True)
    brief_target.add_argument("--pmid", default=None)
    brief_target.add_argument("--doi", default=None)
    brief_target.add_argument("--publication-id", dest="publication_id", default=None)
    p_ex_brief.add_argument("--width", type=int, default=300, help="characters per passage")
    p_ex_brief.set_defaults(func=cmd_extract_brief)

    p_ex_run = ex_sub.add_parser(
        "run", help="extract one publication's methods and results (PLAN.md H.5, V.4)"
    )
    target = p_ex_run.add_mutually_exclusive_group(required=True)
    target.add_argument("--pmid", default=None, help="PubMed id of an existing publication row")
    target.add_argument("--doi", default=None, help="DOI of an existing publication row")
    target.add_argument(
        "--publication-id",
        dest="publication_id",
        default=None,
        help="the publication row's own id (pmid:... or doi:...)",
    )
    p_ex_run.add_argument(
        "--text-file",
        dest="text_file",
        default=None,
        help="read the full text from this UTF-8 file instead of the stored fulltext_asset",
    )
    p_ex_run.add_argument(
        "--sections",
        default=None,
        help=(
            "comma-separated sections to send; default "
            f"{','.join(DEFAULT_EXTRACTION_SECTIONS)} (PLAN.md V.4: whole text costs ~13x more)"
        ),
    )
    p_ex_run.add_argument(
        "--max-excerpt-chars",
        type=int,
        default=None,
        help=(
            "split the excerpt into overlapping windows of at most this many characters and "
            "extract from each, merging the results. A real paper's methods and results run to "
            "~60,000 characters, which a local model answers in minutes or not at all "
            "(MODEL_ROUTING.md 7c). Offsets stay document-absolute either way"
        ),
    )
    p_ex_run.add_argument(
        "--run-id", dest="run_id", default=None, help="tag this extraction with a batch run id"
    )
    p_ex_run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="extract and validate, print the result, write nothing",
    )
    p_ex_run.add_argument(
        "--no-enqueue",
        dest="no_enqueue",
        action="store_true",
        help="write the extraction but do not create curation tasks for it",
    )
    p_ex_run.add_argument(
        "--only-kind",
        dest="only_kinds",
        action="append",
        metavar="KIND",
        help="ask for this record kind only; repeatable. Narrows the payload schema, which is "
        "most of the fixed per-call cost. A narrowed run makes NO claim about the kinds it did "
        f"not ask for, so its prompt version records the subset. Kinds: {', '.join(RECORD_KINDS)}",
    )
    p_ex_run.set_defaults(func=cmd_extract_run)

    p_curate = sub.add_parser(
        "curate", help="the curation queue: review what extraction proposed (Zone I -> reviewed)"
    )
    cu_sub = p_curate.add_subparsers(dest="curate_command", required=True)

    p_cu_scan = cu_sub.add_parser(
        "scan", help="create curation tasks for proposed extractions that have none yet"
    )
    p_cu_scan.add_argument("--limit", type=int, default=None, help="cap extractions scanned")
    p_cu_scan.set_defaults(func=cmd_curate_scan)

    p_cu_next = cu_sub.add_parser(
        "next", help="show the next tasks awaiting a verdict (does not claim them)"
    )
    p_cu_next.add_argument("--limit", type=int, default=10)
    p_cu_next.add_argument(
        "--kind", default=None, help="comma-separated record kinds, e.g. measurements"
    )
    p_cu_next.add_argument(
        "--show-record",
        dest="show_record",
        action="store_true",
        help="print each proposed record as JSON",
    )
    p_cu_next.set_defaults(func=cmd_curate_next)

    def add_verdict_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--task", required=True, help="curation task id")
        p.add_argument("--curator", required=True, help="who is deciding; recorded on the event")
        # Required, not optional: a verdict with no reason cannot be reviewed later, and the
        # reason is the only part of it the next curator can use.
        p.add_argument("--reason", required=True, help="why; stored on the task and the event")

    p_cu_accept = cu_sub.add_parser("accept", help="accept a proposed record as it stands")
    add_verdict_args(p_cu_accept)
    p_cu_accept.set_defaults(func=cmd_curate_accept)

    p_cu_reject = cu_sub.add_parser(
        "reject", help="reject a proposed record; the row is kept, never deleted"
    )
    add_verdict_args(p_cu_reject)
    p_cu_reject.set_defaults(func=cmd_curate_reject)

    p_cu_corroborate = cu_sub.add_parser(
        "corroborate",
        help="split the queue by whether each proposal's own quote names what it claims",
    )
    p_cu_corroborate.add_argument(
        "--kind", default=None, help="comma-separated record kinds, e.g. measurements,strains"
    )
    p_cu_corroborate.add_argument(
        "--show-absent",
        dest="show_absent",
        action="store_true",
        help="tally which identifying fields are missing from their quotes",
    )
    # Accepting is opt-in and needs a named curator, because the default must stay a report: a
    # flag that both measures and writes gets run for the measurement and writes by accident.
    p_cu_corroborate.add_argument(
        "--accept", action="store_true", help="accept the corroborated proposals in bulk"
    )
    p_cu_corroborate.add_argument(
        "--curator", default=None, help="who is deciding; required with --accept"
    )
    p_cu_corroborate.set_defaults(func=cmd_curate_corroborate)

    p_cu_duplicates = cu_sub.add_parser(
        "duplicates",
        help="proposals describing a measurement the atlas already holds under another id",
    )
    p_cu_duplicates.add_argument(
        "--verbose", action="store_true", help="list each proposal and the row it duplicates"
    )
    p_cu_duplicates.set_defaults(func=cmd_curate_duplicates)

    p_cu_promote = cu_sub.add_parser(
        "promote",
        help="write the rows accepted proposals describe (the step after accept)",
    )
    p_cu_promote.add_argument("--task", help="one task id; omit to promote every ready task")
    p_cu_promote.add_argument("--curator", required=True, help="who is promoting")
    p_cu_promote.add_argument(
        "--reason", default="reviewed and promoted", help="why, for the audit log"
    )
    p_cu_promote.add_argument(
        "--organism", help="organism id for strains; the extraction schema has no organism field"
    )
    p_cu_promote.add_argument("--basis", help="'consumed' or 'supplied', for a yield")
    # A `pathway_configuration` needs both, and the extraction schema carries neither. They are
    # refused rather than guessed (see `curate.promote._plan_configuration`), so these flags are
    # how a curator answers.
    # `--host-strain` serves a part expression record too, and deliberately shares the flag: a
    # configuration's host and an expression record's host are the same question about the same
    # table, and two flags would invite a curator to answer it twice, differently. The expression
    # promoter resolves the host from the paper's own wording where it can, so this flag is the
    # override rather than the usual path.
    p_cu_promote.add_argument(
        "--host-strain",
        dest="host_strain_id",
        help="host strain id for a pathway configuration or a part expression record; the "
        "extraction schema has no host field",
    )
    p_cu_promote.add_argument(
        "--product",
        dest="product_id",
        help="product id for a pathway configuration; a route is a route *to* something",
    )
    p_cu_promote.add_argument(
        "--pathway", dest="pathway_id", help="pathway id for a pathway configuration (optional)"
    )
    p_cu_promote.add_argument(
        "--name", dest="name", help="override the derived name of a pathway configuration"
    )
    # A part expression record's two curator-supplied columns. `--part` is not optional in
    # practice: `part_expression_record.part_id` is NOT NULL and the extraction schema has no
    # catalog id, on purpose (see `extract.schemas._part_expression_fields`).
    p_cu_promote.add_argument(
        "--part",
        dest="part_id",
        help="part id for a part expression record, from data/pathways/parts_catalog.yaml; the "
        "extraction schema carries the paper's wording, not a catalog id",
    )
    p_cu_promote.add_argument(
        "--outcome-measurement",
        dest="outcome_measurement_id",
        help="measurement id an expression record's outcome is recorded as (optional; a part can "
        "be demonstrated with no number behind it)",
    )
    # PLAN.md I.4's two curator-only columns on `modification`. Neither is in the extraction
    # schema, and neither is guessed: `is_isolated_effect` is a claim about what the strain was
    # compared against, which lives in the paper's strain table rather than in the sentence the
    # modification was extracted from. Left unsaid, the column stays NULL -- "not recorded" --
    # and `yes`/`no` rather than a store_true flag is what makes that third state expressible.
    p_cu_promote.add_argument(
        "--isolated-effect",
        dest="is_isolated_effect",
        choices=("yes", "no"),
        help="was this modification the only change from its stated control? Omit when the "
        "paper does not say -- NULL is 'not recorded' and is not the same as 'no'",
    )
    p_cu_promote.add_argument(
        "--intent",
        dest="intent",
        choices=(
            "increase_flux",
            "remove_competition",
            "improve_cofactor_balance",
            "improve_tolerance",
            "improve_transport",
            "reduce_byproduct",
            "other",
        ),
        help="what the change was made to achieve, as the paper frames it (optional)",
    )
    p_cu_promote.add_argument(
        "--dry-run", action="store_true", help="show what would be written and change nothing"
    )
    p_cu_promote.set_defaults(func=cmd_curate_promote)

    p_cu_stats = cu_sub.add_parser(
        "stats", help="queue health, plus proposals a curator rejected and the model repeated"
    )
    p_cu_stats.set_defaults(func=cmd_curate_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    # ValueError also catches AmbiguousCompartmentError; QueryFamiliesError is named explicitly
    # even though it subclasses ValueError, so a malformed query_families.yaml is clearly a
    # user/data error here rather than relying on the reader to know that ancestry.
    except (
        RecodeError,
        ValueError,
        QueryFamiliesError,
        KeyError,
        FileNotFoundError,
        PathsConfigError,
        EutilsError,
        # Extraction and curation. LlmError covers a model whose output never validated;
        # ProviderError covers a daemon that is down or a model that was never pulled, and both
        # already carry the instruction for what to do about them.
        ExtractionError,
        SchemaBuildError,
        CurationError,
        LlmError,
        ProviderError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
