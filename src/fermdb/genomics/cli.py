"""``fermdb genomics load-gff3`` and ``fermdb genomics protein-qc``.

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

**`protein-qc` exits non-zero when it refuses, and has no flag that can talk it round.** It is the
gate of PLAN.md E.3, which is worded as an action -- *"refuse the ingest below a threshold"* -- and
a gate that prints a warning and exits 0 is a warning, not a gate. So the exit codes are three
distinct things a script can branch on: `0` the corpus passed, `1` the corpus was read and
**refused**, `2` the run never happened (a missing file, an unparsable GFF3, a bad `--genetic-code`
spelling). Conflating 1 and 2 would let a typo in a path read as a clean genome.

There is deliberately **no `--threshold`**. PLAN.md S.2 puts QC constants in one module, fixed
before the data is seen and reviewed as a diff; a flag that relaxes one for a single run is the
same rationalization S.2 names, with an audit trail no shorter than a shell history. The number
lives in `protein_qc.MIN_PROTEIN_IDENTITY` and moving it is a reviewed change the owner signs off.
`--json` still emits every count and every failure on a refused run, so a below-threshold corpus
is completely inspectable without the gate having been softened to look at it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import Settings
from ..db import DatabaseError, open_db
from ..genetic_code import TABLES
from .gff3 import Gff3Error
from .load_genes import GeneLoadError, GeneLoadReport, load_gff3
from .protein_qc import MIN_PROTEIN_IDENTITY, run_protein_qc
from .protein_qc import format_report as format_protein_qc_report

__all__ = [
    "add_genomics_subcommand",
    "cmd_genomics_load_gff3",
    "cmd_genomics_protein_qc",
    "format_report",
    "parse_genetic_code_options",
]

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


def parse_genetic_code_options(options: list[str] | None) -> dict[str, int]:
    """`["NC_001224.1=3"]` -> `{"NC_001224.1": 3}`.

    Raises `ValueError` on anything it cannot read, including a table `fermdb.genetic_code` does
    not implement. A mistyped seqid would otherwise resolve nothing and be indistinguishable in
    the output from a sequence the annotation happened to cover on its own.
    """
    declared: dict[str, int] = {}
    for option in options or []:
        seqid, separator, table = option.partition("=")
        if not separator or not seqid.strip():
            raise ValueError(f"--genetic-code {option!r} is not SEQID=TABLE")
        try:
            table_id = int(table)
        except ValueError as exc:
            raise ValueError(f"--genetic-code {option!r}: {table!r} is not an integer") from exc
        if table_id not in TABLES:
            known = ", ".join(str(t) for t in sorted(TABLES))
            raise ValueError(
                f"--genetic-code {option!r}: fermdb.genetic_code implements tables {known}. "
                "Adding another is a change to that module, not a flag on this one."
            )
        declared[seqid.strip()] = table_id
    return declared


def cmd_genomics_protein_qc(args: argparse.Namespace) -> int:
    """Re-splice, translate and verify every CDS. Exit 1 if the corpus is refused."""
    paths = {"gff3": Path(args.gff3), "genome": Path(args.genome), "proteins": Path(args.proteins)}
    for label, path in paths.items():
        if not path.is_file():
            print(f"error: no such {label} file: {path}", file=sys.stderr)
            return 2

    try:
        declared = parse_genetic_code_options(args.genetic_code)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        report = run_protein_qc(
            paths["gff3"],
            paths["genome"],
            paths["proteins"],
            declared_tables=declared,
        )
    except (Gff3Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = report.as_json()
        payload["source"] = {
            "gff3": str(paths["gff3"]),
            "genome": str(paths["genome"]),
            "proteins": str(paths["proteins"]),
            "declared_genetic_codes": declared,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        # Still non-zero. `--json` chooses the output format, not the verdict; a caller that
        # wanted the numbers and got exit 0 would have been told the corpus was fine.
        return 0 if report.passed else 1

    print(f"{'gff3':<12}{paths['gff3']}")
    print(f"{'genome':<12}{paths['genome']}")
    print(f"{'proteins':<12}{paths['proteins']}")
    for line in format_protein_qc_report(report):
        print(line)
    return 0 if report.passed else 1


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

    p_qc = genomics_sub.add_parser(
        "protein-qc",
        help="re-splice and translate every CDS; refuse the annotation below the identity gate",
        description=(
            "The protein QC gate of PLAN.md E.3. Re-splices every CDS in a GFF3 out of the "
            f"genome FASTA, translates it under the genetic code resolved for its own sequence, "
            f"and compares it to the protein FASTA. Exits 1 when fewer than "
            f"{MIN_PROTEIN_IDENTITY:.1%} of CDS reproduce their protein record exactly. That "
            "threshold is a reviewed constant in fermdb.genomics.protein_qc and there is no "
            "flag for it (PLAN.md S.2). Reads three files and no database; writes nothing."
        ),
    )
    p_qc.add_argument("--gff3", required=True, help="the annotation (.gff or .gff.gz)")
    p_qc.add_argument("--genome", required=True, help="the genomic FASTA (.fna or .fna.gz)")
    p_qc.add_argument("--proteins", required=True, help="the protein FASTA (.faa or .faa.gz)")
    p_qc.add_argument(
        "--genetic-code",
        dest="genetic_code",
        action="append",
        metavar="SEQID=TABLE",
        help=(
            "state the NCBI table for one sequence, e.g. NC_001224.1=3. Repeatable. Used only "
            "where the annotation states nothing itself; where it does, a disagreement is "
            "reported and the annotation wins. Without this, a sequence the annotation says "
            "nothing about is REFUSED rather than read under table 1"
        ),
    )
    p_qc.add_argument(
        "--json", action="store_true", help="emit every count and every failure, untruncated"
    )
    p_qc.set_defaults(func=cmd_genomics_protein_qc)
