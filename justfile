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
