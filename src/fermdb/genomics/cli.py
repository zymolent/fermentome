"""``fermdb genomics load-gff3`` -- put a whole RefSeq annotation into `gene`.

Separate from `cli.py` the way `omics`, `atlas`, `query`, `db` and `serve` are, so the top-level
parser gains only an import and one call.

**`--dry-run` is the point of this command, not a courtesy on it.** The first real use is a
6,600-gene file against an atlas that already holds 36 hand-curated rows, and the question that
has to be answered *before* anything is written is not "did it work" but "is this the genome it
says it is, and what is it about to do to the rows I care about". So the dry run decides
everything the write would decide -- the same merge, the same conflict detection, the same ids --
and performs none of it. It takes no write lock either, so it can be pointed at an atlas another
process has open.

**Nothing is defaulted.** `--assembly-accession` and `--organism-id` are required even though this
atlas has an obvious value for both, because the obvious value is only obvious for S288C: loading
the CEN.PK annotation under `GCF_000146045.2` would stamp 6,000 genes with the wrong assembly, and
a gene id is meaningless without its assembly (CONVENTIONS.md, "Gene identity"). An argument you
have to type is cheaper than a table you have to unpick.

**The human output shows the skips and the disagreements, not just their counts.** A skipped gene
nobody sees is a gene silently missing from the atlas, and a count of "3 skipped" tells you the
number and not which three. The table truncates long lists and says so; `--json` is always
complete.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import Settings
from ..db import DatabaseError, open_db
from .gff3 import Gff3Error
from .load_genes import GeneLoadError, GeneLoadReport, load_gff3

__all__ = ["add_genomics_subcommand", "cmd_genomics_load_gff3", "format_report"]

#: How many skips and disagreements the human table prints before summarising the rest. A dry run
#: over a whole genome can produce hundreds; a screen of them is a review, a thousand is a wall.
_MAX_DETAIL = 20


def format_report(report: GeneLoadReport, *, max_detail: int = _MAX_DETAIL) -> list[str]:
    """The human rendering, as lines so a test can read it without capturing stdout."""
    lines = [
        "",
        f"{'considered':<24}{report.considered:>8}",
        f"{'  inserted':<24}{report.inserted:>8}",
        f"{'  updated':<24}{report.updated:>8}",
        f"{'  unchanged':<24}{report.unchanged:>8}",
        f"{'  skipped':<24}{len(report.skipped):>8}",
        f"{'gene_group inserted':<24}{report.gene_groups_inserted:>8}",
        f"{'gene_group left alone':<24}{report.gene_groups_left_alone:>8}",
        f"{'disagreements':<24}{len(report.disagreements):>8}",
    ]

    if report.by_seqid:
        lines += ["", "genes per sequence"]
        lines += [f"  {name:<22}{count:>8}" for name, count in report.by_seqid]
    if report.by_biotype:
        lines += ["", "genes per biotype"]
        lines += [f"  {name:<22}{count:>8}" for name, count in report.by_biotype]

    if report.skipped:
        lines += ["", "SKIPPED -- these genes are not in the atlas and will not appear in it:"]
        for reason, count in sorted(report.skipped_by_reason().items()):
            lines.append(f"  {reason:<22}{count:>8}")
        lines.append("")
        for entry in report.skipped[:max_detail]:
            lines.append(f"  {entry.gff_id}  ({entry.locus_tag or 'no locus_tag'}): {entry.reason}")
            lines.append(f"      {entry.detail}")
        if len(report.skipped) > max_detail:
            lines.append(
                f"  ... and {len(report.skipped) - max_detail} more; --json lists every one"
            )

    if report.disagreements:
        lines += [
            "",
            "DISAGREEMENTS -- the stored value was KEPT in every case. Nothing below was applied;",
            "these are for a curator to look at (CONVENTIONS.md: conflicts are recorded, never",
            "silently resolved).",
        ]
        for clash in report.disagreements[:max_detail]:
            lines.append(
                f"  {clash.gene_id}  {clash.column}: stored {clash.stored!r}, "
                f"GFF3 says {clash.from_gff3!r}"
            )
        if len(report.disagreements) > max_detail:
            lines.append(
                f"  ... and {len(report.disagreements) - max_detail} more; --json lists every one"
            )

    lines.append("")
    if report.dry_run:
        lines.append("DRY RUN -- nothing was written. Re-run without --dry-run to apply.")
    else:
        lines.append("written and committed.")
    return lines


def cmd_genomics_load_gff3(args: argparse.Namespace) -> int:
    """Parse a RefSeq GFF3 and load, or rehearse loading, its genes."""
    path = Path(args.gff3)
    if not path.is_file():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 2

    settings = Settings.load()
    try:
        # create=False: a bulk gene load into a database that did not exist a moment ago is a
        # typo in a path, not a first run.
        conn = open_db(settings.db_file, create=False)
    except DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    conn.execute("PRAGMA busy_timeout=60000")

    try:
        report = load_gff3(
            conn,
            path,
            assembly_accession=args.assembly_accession,
            organism_id=args.organism_id,
            anchor_namespace=args.anchor_namespace,
            confidence=args.confidence,
            dry_run=args.dry_run,
        )
    except (GeneLoadError, Gff3Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    if args.json:
        payload = report.as_json()
        payload["source"] = {
            "gff3": str(path),
            "assembly_accession": args.assembly_accession,
            "organism_id": args.organism_id,
            "atlas": str(settings.db_file),
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{'gff3':<12}{path}")
    print(f"{'assembly':<12}{args.assembly_accession}")
    print(f"{'organism':<12}{args.organism_id}")
    print(f"{'atlas':<12}{settings.db_file}")
    print(f"{'mode':<12}{'DRY RUN (no write)' if args.dry_run else 'WRITE'}")
    for line in format_report(report):
        print(line)
    return 0


def add_genomics_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register `fermdb genomics ...`."""
    parser = sub.add_parser(
        "genomics",
        help="genome-scale gene models: load a RefSeq GFF3 into `gene`",
    )
    genomics_sub = parser.add_subparsers(dest="genomics_command", required=True)

    p_load = genomics_sub.add_parser(
        "load-gff3",
        help="load (or rehearse loading) every gene in a RefSeq GFF3",
        description=(
            "Streams a RefSeq GFF3 (gzipped or not) into `gene` and `gene_group`. Existing rows "
            "are never overwritten: a column that already holds a value is left alone and any "
            "disagreement with the file is reported rather than applied. Run --dry-run first."
        ),
    )
    p_load.add_argument("gff3", help="path to the RefSeq GFF3 (.gff or .gff.gz)")
    p_load.add_argument(
        "--assembly-accession",
        dest="assembly_accession",
        required=True,
        help=(
            "the assembly these genes belong to, e.g. GCF_000146045.2. Required and not "
            "defaulted: a gene id is meaningless without its assembly, and the wrong one here "
            "mislabels every row in the file"
        ),
    )
    p_load.add_argument(
        "--organism-id",
        dest="organism_id",
        required=True,
        help=(
            "an existing organism row, e.g. YAA:ORG:saccharomyces-cerevisiae-s288c. It must "
            "already exist; this command will not invent one"
        ),
    )
    p_load.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="decide everything, write nothing, and print what a real run would do",
    )
    p_load.add_argument(
        "--anchor-namespace",
        dest="anchor_namespace",
        default="sgd_systematic",
        help="gene_group.anchor_namespace for groups created here (default: sgd_systematic)",
    )
    p_load.add_argument(
        "--confidence",
        default="high",
        choices=("unverified", "low", "medium", "high"),
        help=(
            "confidence for rows this run INSERTS; existing rows keep their own. Default 'high': "
            "a verbatim parse of a checksummed RefSeq file is checked against a source"
        ),
    )
    p_load.add_argument(
        "--json", action="store_true", help="emit the wire payload an API would return"
    )
    p_load.set_defaults(func=cmd_genomics_load_gff3)
