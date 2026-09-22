"""`fermdb serve` -- run the read-only web interface.

FastAPI and uvicorn are an optional extra, so the import happens inside the handler and its
absence produces the install line rather than a traceback. A machine that has the atlas but not
the web extra is a normal state, not a broken one.
"""

from __future__ import annotations

import argparse
import sys

__all__ = ["add_serve_subcommand"]

INSTALL_HINT = (
    "the web interface needs FastAPI and uvicorn, which are an optional extra:\n"
    "    python -m pip install -e .[web]"
)


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the API, and the built client if `apps/web/dist` exists."""
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    from fermdb.api.app import create_app, web_dist
    from fermdb.api.deps import atlas_path

    path = atlas_path()
    dist = web_dist()

    print(f"atlas    {path}{'' if path.exists() else '   (MISSING)'}")
    if dist.is_dir():
        print(f"client   {dist}")
        print(f"open     http://{args.host}:{args.port}/")
    else:
        # Not an error: an API-only run is a legitimate way to use this.
        print(f"client   not built ({dist}) -- serving the API only")
        print("          build it with `pnpm install && pnpm build`, or run `pnpm dev` for")
        print("          the dev server on :5173 with hot reload")
        print(f"open     http://{args.host}:{args.port}/docs")

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    return 0


def add_serve_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register `fermdb serve`."""
    parser = sub.add_parser(
        "serve",
        help="run the read-only web interface (PLAN.md D.3 interface layer)",
        description=(
            "Serves every query-layer reader over HTTP, and the built client at the root if it "
            "exists. Every endpoint is a GET: curation writes go through `fermdb curate` with a "
            "named human actor, so there is no write path here."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        help="uvicorn log level",
    )
    parser.set_defaults(func=cmd_serve)
