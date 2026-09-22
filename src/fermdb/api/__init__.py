"""The REST layer: PLAN.md D.3's INTERFACE tier, and nothing below it.

The layer map allows this package to call the query layer and forbids it from reaching past it
into the domain tables. That rule is kept structurally rather than by review:

* Every handler takes a `sqlite3.Connection` opened **read-only** by
  :func:`fermdb.api.deps.connection`, so a handler that tried to write would fail at the
  database rather than succeed quietly.
* Handlers call `fermdb.query.*` readers and serialize their `as_json()`. There is no SQL in
  this package -- the one place a table name appears is a query-layer call.
* There is no POST, PUT, PATCH or DELETE anywhere in it. Curation writes go through
  `fermdb curate` with a named human actor, which is what the audit log is for, and a browser
  is not an actor.

That last point is the same decision `query/reviewhtml.py` made for the review page, for the
same reason: nothing can be promoted by clicking.
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    """Build the FastAPI application.

    Imported lazily so that `import fermdb.api` costs nothing and, more to the point, does not
    fail on a machine that has the atlas but not the web extra installed. The CLI imports this
    module to print a helpful message; only `fermdb serve` needs FastAPI present.
    """
    from fermdb.api.app import create_app as _create_app

    return _create_app(*args, **kwargs)  # type: ignore[arg-type]
