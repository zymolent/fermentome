"""The FastAPI application: routes, CORS for the dev server, and the built UI in production.

Two modes, one app.

**Development.** Vite serves the client on :5173 with hot reload and proxies `/api` here. The
CORS allowance exists for that and is narrow -- localhost origins only. It is not a deployment
posture; it is the dev server talking to the dev API on the same machine.

**Built.** `apps/web/dist` is mounted at the root if it exists, so `fermdb serve` alone gives
the whole interface from one process with no node toolchain present. The SPA fallback returns
`index.html` for any unmatched non-`/api` path, because client-side routes are real URLs that
must survive a reload -- a bookmarked strain page that 404s is a broken interface.

The mount is conditional and its absence is not an error: an API-only run is a legitimate way to
use this, and refusing to start because a frontend was never built would make that impossible.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fermdb.api.deps import atlas_path
from fermdb.api.entity_routes import router as entity_router
from fermdb.api.genes_routes import router as genes_router
from fermdb.api.routes import router
from fermdb.db import SCHEMA_VERSION, schema_version

__all__ = ["create_app", "web_dist"]

#: Origins the Vite dev server can appear on. Both spellings, because "localhost" and
#: "127.0.0.1" are different origins to a browser and hitting the wrong one is a confusing
#: five minutes of CORS errors that look like the API being down.
DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def web_dist() -> Path:
    """Where `pnpm build` puts the client, relative to the installed package."""
    return Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"


def create_app(*, dev_cors: bool = True) -> FastAPI:
    """Build the application."""
    app = FastAPI(
        title="Fermentome",
        version="0.0.1",
        summary="Biochemical Atlas & Fermentation Products Database -- read-only interface",
        description=(
            "Every endpoint is a GET. Curation writes go through `fermdb curate` with a named "
            "human actor; there is deliberately no write path here (PLAN.md D.3)."
        ),
    )

    if dev_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(DEV_ORIGINS),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.include_router(router, prefix="/api")
    app.include_router(genes_router, prefix="/api")
    app.include_router(entity_router, prefix="/api")

    @app.get("/api/health", tags=["atlas"])
    def health() -> dict[str, Any]:
        """Whether the atlas is actually readable, and which one is being served.

        Reports the path because the commonest confusion when running this is pointing at a copy
        and reading it as the live atlas, or the reverse.

        **It opens the database.** An earlier version only called `path.exists()`, and that is a
        health check that cannot fail for the reason a health check exists: when the code expected
        schema v17 and the file on disk was v16, every real endpoint raised `SchemaVersionError`
        while this one cheerfully returned `ok: true`. A file being present is not the same claim
        as a file being usable, and only the second one is worth asking. So the connection is
        opened, the schema version read, and a mismatch reported as `ok: false` with the command
        that fixes it.
        """
        path = atlas_path()
        payload: dict[str, Any] = {
            "ok": False,
            "atlas": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
            "writable_endpoints": 0,
        }
        if not path.exists():
            payload["error"] = f"no atlas at {path}"
            return payload

        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                version = schema_version(conn)
            finally:
                conn.close()
        except sqlite3.Error as error:
            payload["error"] = f"cannot open the atlas: {error}"
            return payload

        payload["schema_version"] = version
        payload["expected_schema_version"] = SCHEMA_VERSION
        if version != SCHEMA_VERSION:
            payload["error"] = (
                f"atlas is at schema v{version}, this build expects v{SCHEMA_VERSION}. "
                f"Migrate it with `fermdb db migrate` (it backs up first), or point "
                f"FERMDB_DB_FILE at a database that is already at v{SCHEMA_VERSION}."
            )
            return payload

        payload["ok"] = True
        return payload

    dist = web_dist()
    if dist.is_dir():
        # `html=True` serves index.html for directory requests; the explicit fallback below
        # covers deep client routes such as /literature/publications/YAA:PUB:...
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> Any:
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


#: Module-level app so `uvicorn fermdb.api.app:app` works without a factory flag.
app = create_app()
