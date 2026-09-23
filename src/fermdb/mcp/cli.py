"""`fermdb mcp` -- serve the atlas to an agent over stdio.

Registered the same way `fermdb serve` is, and argparse for the same stated reason: no
dependency means this runs on a bare interpreter. Unlike `serve`, there is no optional extra to
check for and no install hint to print, because this server imports nothing that is not in the
standard library or already in `fermdb`.

**Everything this command prints goes to stderr.** stdout is the protocol stream: one JSON-RPC
message per line and nothing else. A banner on stdout would be read by the client as a malformed
message, and the resulting error would name JSON rather than the banner -- so the banner is on
stderr, where a person running this by hand still sees it and the client never does.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import Settings
from .budget import DEFAULT_BUDGET_CHARS
from .server import SERVER_VERSION, serve_stdio
from .tools import TOOLS

__all__ = ["add_mcp_subcommand"]


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve one stdio session until the client closes stdin."""
    settings = Settings.load()
    atlas = Path(args.atlas) if args.atlas else Path(settings.db_file)

    print(f"fermdb mcp {SERVER_VERSION}", file=sys.stderr)
    print(f"atlas    {atlas}{'' if atlas.exists() else '   (MISSING)'}", file=sys.stderr)
    print(f"tools    {len(TOOLS)}, all read-only", file=sys.stderr)
    print(f"budget   {args.budget_chars} characters per result", file=sys.stderr)
    print("stdio    waiting for `initialize`", file=sys.stderr)

    return serve_stdio(atlas=atlas, budget_chars=args.budget_chars, settings=settings)


def add_mcp_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register `fermdb mcp`."""
    parser = sub.add_parser(
        "mcp",
        help="serve the read-only atlas to an agent over stdio (PLAN.md L.4)",
        description=(
            "Speaks MCP (JSON-RPC 2.0 over newline-delimited JSON on stdin/stdout) so Claude "
            "Code and other agents can query the atlas. Every tool is a read: the connection is "
            "opened mode=ro and no tool writes. Register it with:\n"
            "    claude mcp add fermdb -- python -m fermdb.cli mcp"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--atlas",
        default=None,
        help="database file to serve; defaults to the configured atlas (FERMDB_DB_FILE)",
    )
    parser.add_argument(
        "--budget-chars",
        dest="budget_chars",
        type=int,
        default=DEFAULT_BUDGET_CHARS,
        help=(
            "character budget per result; larger lists are trimmed first and the response "
            f"reports every cut (default: {DEFAULT_BUDGET_CHARS})"
        ),
    )
    parser.set_defaults(func=cmd_mcp)
