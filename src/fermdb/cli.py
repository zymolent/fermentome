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
    python -m fermdb.cli literature manual-queue export --out queue.tsv
    python -m fermdb.cli literature manual-queue ingest --dir <folder>
    python -m fermdb.cli omics discover
    python -m fermdb.cli omics references fetch
    python -m fermdb.cli omics status
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
import sys
from pathlib import Path

from . import curate
from .config import Settings
from .curate.queue import CurationError, Curator
from .db import open_db
from .extract import (
    DEFAULT_EXTRACTION_SECTIONS,
    ExtractionError,
    ExtractionOutcome,
    SchemaBuildError,
    extract_publication,
    find_publication,
    load_source_text,
)
from .genetic_code import AMBIGUOUS_CODONS, TABLE_1, TABLE_3
from .literature.discovery import FamilyRunResult, run_family
from .literature.eutils import EutilsClient, EutilsError
from .literature.manual_queue import IngestReport, export_queue, ingest_directory
from .literature.queries import (
    QueryFamiliesError,
    QueryFamily,
    family_status,
    load_query_families,
)
from .llm import (
    FileCache,
    LlmConfig,
    LlmError,
    Provider,
    ProviderError,
    ResultCache,
    build_provider,
)
from .omics import add_omics_subcommand
from .paths import PathsConfigError
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
    return 0


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
        report = ingest_directory(conn, Path(args.dir), settings=settings)
    finally:
        conn.close()
    _print_ingest_report(report)
    return 0 if not report.unmatched else 1


def _print_ingest_report(report: IngestReport) -> None:
    for match in report.matched:
        print(f"provided: {match.path.name} -> {match.queue_id}")
    for path in report.already_provided:
        print(f"already provided, skipped: {path.name}")
    for path in report.unmatched:
        print(f"could not match: {path.name}", file=sys.stderr)


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
        print(
            f"{publication_id}: provider={config.provider} "
            f"model={config.model_for('extraction')} sections={','.join(sections)} "
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
    p_mq_ingest.set_defaults(func=cmd_literature_manual_queue_ingest)

    add_omics_subcommand(sub)

    p_extract = sub.add_parser(
        "extract", help="LLM extraction of one publication into a proposed Zone I row"
    )
    ex_sub = p_extract.add_subparsers(dest="extract_command", required=True)

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
