"""``fermdb export release --out DIR``: PLAN.md T.5's release bundle, from the command line.

Separate from `cli.py` the way `omics`, `atlas`, `query` and `genomics` are, so the top-level
parser gains one import and one call. argparse, not Typer, for the reason the top-level module
gives: no dependency means `python -m fermdb.cli` works on a bare interpreter.

The database is opened `create=False`. An export that silently created an empty atlas and then
wrote a bundle of zero rows would be the worst possible failure here -- a citable,
digest-stamped, entirely empty release -- so a missing database is an error with a message
rather than a fresh file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..annotate.sources import annotation_sources_path
from ..config import Settings
from ..db import open_db
from .release import build_release

__all__ = ["add_export_subcommand", "cmd_export_release"]


def cmd_export_release(args: argparse.Namespace) -> int:
    settings = Settings.load()
    out_dir = Path(args.out)

    conn = open_db(settings.db_file, create=False)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        bundle = build_release(
            conn,
            out_dir,
            release=args.release,
            repo_root=settings.repo_root,
            annotation_sources_file=annotation_sources_path(settings),
            force=args.force,
        )
    finally:
        conn.close()

    print(bundle.summary())
    if args.release is None:
        print(
            "\nno --release given: this bundle is a snapshot, not a citable release "
            "(PLAN.md T.4 dates releases vYYYY.N). Cite the digest above to name this state.",
            file=sys.stderr,
        )
    return 0


def add_export_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``fermdb export ...`` to an existing top-level subparsers action."""
    p_export = sub.add_parser(
        "export",
        help="release bundles a third party can read without this code (PLAN.md T.5)",
    )
    export_sub = p_export.add_subparsers(dest="export_command", required=True)

    p_release = export_sub.add_parser(
        "release",
        help="data, schema, provenance graph, versions and licence terms, as an RO-Crate bundle",
        description=(
            "Write the atlas out as a structured bundle with an RO-Crate metadata descriptor. "
            "Zone I (inferred) content lands in data/inferred/, in files of its own, and every "
            "one of its rows is labelled as inference in the data itself."
        ),
    )
    p_release.add_argument("--out", required=True, help="directory to write the bundle into")
    p_release.add_argument(
        "--release",
        help=(
            "the release id this bundle is (PLAN.md T.4: vYYYY.N). Omit for a snapshot; the "
            "bundle then records that it has no release id rather than inventing one"
        ),
    )
    p_release.add_argument(
        "--force",
        action="store_true",
        help="write into a non-empty output directory (refused by default)",
    )
    p_release.set_defaults(func=cmd_export_release)
