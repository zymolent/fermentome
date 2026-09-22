"""Connection handling for the API: read-only, per-request, and closed even on error.

Two decisions worth stating.

**The connection is opened read-only at the SQLite level**, through a `file:...?mode=ro` URI,
not merely by convention. PLAN.md D.3 forbids the interface layer from writing to the domain,
and a mode that makes a write *impossible* is a different guarantee from a policy that makes it
*disallowed*. A bug in a handler surfaces here as an exception rather than as a silent edit to
the shared atlas.

**A connection per request, not one shared.** SQLite connections are not safe to share across
threads, and FastAPI runs sync handlers in a thread pool. One connection per request is cheap
against a local file and removes the whole class of "works until two people open it at once".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException

from fermdb.config import Settings

__all__ = ["Conn", "atlas_path", "connection"]

#: Long enough to outlast a curation transaction happening in another process, short enough that
#: a genuinely stuck lock surfaces as an error rather than as a hung page.
BUSY_TIMEOUT_MS = 60_000


def atlas_path() -> Path:
    """Where the atlas lives, from the same settings the CLI reads.

    Honours `FERMDB_DB_FILE`, so pointing the UI at a copy of the atlas is an environment
    variable and not a code change -- which is how it should be run against anything other than
    the live file.
    """
    return Path(Settings.load().db_file)


def connection() -> Iterator[sqlite3.Connection]:
    """A read-only connection for one request."""
    path = atlas_path()
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"no atlas at {path}. Set FERMDB_DB_FILE to a database file, or run the "
                "ingest pipeline first."
            ),
        )
    # `uri=True` with mode=ro is what makes this read-only; `nolock=1` is deliberately NOT set,
    # because the atlas is genuinely shared with curation processes and skipping locking would
    # trade a clear error for a torn read.
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        yield conn
    finally:
        conn.close()


#: The annotated dependency handlers declare, so the read-only guarantee is one import away and
#: a handler cannot accidentally open its own writable connection without it being obvious.
Conn = Annotated[sqlite3.Connection, Depends(connection)]
