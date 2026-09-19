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
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings
from .genetic_code import AMBIGUOUS_CODONS, TABLE_1, TABLE_3
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    # ValueError covers AmbiguousCompartmentError: naming a both-genome compartment without an
    # encoding genome is a user error with a useful message, not a traceback.
    except (RecodeError, ValueError, KeyError, FileNotFoundError, PathsConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
