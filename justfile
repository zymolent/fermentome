# Test recipes

test:
    python -m pytest

lint:
    ruff check .

fmt:
    ruff format .

typecheck:
    mypy

check: lint fmt-check typecheck test

fmt-check:
    ruff format --check .

clean:
    rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info


# ---------------------------------------------------------------- the web interface
#
# Two ways to run it. `just ui` is one process and needs no node toolchain, but serves whatever
# was last built. `just api` + `just web` is the pair to develop against: Vite on :5173 with hot
# reload, proxying /api to the FastAPI process on :8000.
#
# Both are read-only. Accepting a proposal is `fermdb curate`, by a named human.

# Serve the API and the built client from one process.
ui:
    python -m fermdb.cli serve

# The API alone, with reload. Pair with `just web`.
api:
    python -m uvicorn fermdb.api.app:app --reload --port 8000

# The Vite dev server. Needs `just web-install` once, and `just api` running.
web:
    pnpm dev

web-install:
    pnpm install

# Build the client into apps/web/dist, which `just ui` then serves.
web-build:
    pnpm build

web-check:
    pnpm typecheck

# Point the interface at a copy rather than the shared atlas. Takes a path:
#   just ui-on /tmp/atlas-copy.sqlite3
ui-on db:
    FERMDB_DB_FILE={{db}} python -m fermdb.cli serve


# ------------------------------------------------------- Zone H rebuild as a test (PLAN.md T.3)
#
# "Drop Zone H, rebuild, diff. A non-empty diff is either non-determinism or an undeclared
# input -- both bugs." The fixture half of that runs in `just test` (tests/test_rebuild.py) and
# needs nothing; the recipes here are the periodic run against a real database.
#
# There is deliberately no CI workflow. The owner removed `.github/` on 2026-09-23 (73a130b),
# so this is a local gate: `just check` covers the fixture, `just rebuild-check` covers the
# atlas, and the second one is a thing a person runs, not a thing a robot runs nightly.
#
# The check itself never writes -- it snapshots Zone H, rebuilds, and compares, and opens the
# file `mode=ro` besides. `rebuild-check` still works on a copy, because "it cannot write" is a
# property of today's code and "it is not the shared atlas" is a property of the invocation.

# Copy the configured atlas to a scratch file and run the T.3 check against the copy.
# The copy is what makes this safe to run without reading the source first.
rebuild-check:
    #!/usr/bin/env bash
    set -euo pipefail
    src="$(python -c 'from fermdb.config import Settings; print(Settings.load().db_file)')"
    dest="${TMPDIR:-/tmp}/fermdb-rebuild-check.sqlite3"
    echo "copying ${src}"
    echo "     -> ${dest}"
    # sqlite3's own `.backup` rather than `cp`: the atlas runs in WAL mode, so copying the
    # .sqlite3 file on its own can miss committed transactions still sitting in the -wal
    # sidecar -- and a check run against a half-copied database reports diffs that are the copy's
    # fault. The source is opened mode=ro here too.
    python -c "import sqlite3,sys; s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "${src}" "${dest}"
    python -m fermdb.cli rebuild zone-h --db "${dest}"

# The same check against a database you name. Still never the shared atlas:
#   just rebuild-check-on /tmp/atlas-copy.sqlite3
rebuild-check-on db:
    python -m fermdb.cli rebuild zone-h --db {{db}}
