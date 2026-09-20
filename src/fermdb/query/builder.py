"""A small read-only query builder, and the reason it exists at all.

`docs/reference/OPEN_QUESTIONS.md` Q2 revised the storage decision to *"SQLite, accessed through
SQLAlchemy Core from the first line of code"*, on this argument:

    The reason Postgres was chosen up front was that the engine is expensive to change later --
    `genome-db` priced its own escape at 646 call sites. But that cost came from **raw SQL
    scattered across the codebase**, not from SQLite itself.

That advice was not followed. There are ~106 raw ``execute(`` call sites in `src/fermdb/`, and no
SQLAlchemy. Q2 also names the trigger to revisit the engine -- *"a second concurrent user, a web
UI, or semantic search"* -- so building a UI is precisely the event the mitigation was meant to
make cheap, arriving with the mitigation unbuilt.

This module is the narrow, honest version of that fix, and its limits are worth stating plainly:

* **It covers reads only.** The ~106 sites skew heavily to writers in the ingest pipelines
  (`curate/queue.py` 19, `omics/load.py` 11, `literature/acquire.py` 9). Those are not ported and
  do not need to be for an interface layer; porting them is a separate decision with its own cost.
* **It is not SQLAlchemy.** Adding a dependency of that size to a project whose entire runtime
  requirement list is `pyyaml` and `pypdf` is a real trade, and the read surface needed here --
  select, join, filter, group, order, page -- is a few hundred lines of stdlib. If the engine
  does move to PostgreSQL, what changes is this file, not every reader above it, which is the
  property Q2 actually asked for.

Two rules it enforces that a raw string cannot:

1. **Values are never interpolated.** Identifiers are matched against a strict pattern; everything
   else becomes a placeholder parameter. A builder that formats a value into SQL is a builder that
   eventually formats a curator's free-text note into SQL.
2. **Truncation is reported.** CONVENTIONS.md, "API": *"Results trimmed for size say what was cut.
   A silent truncation causes a consumer to report a count that is really a limit."* So
   :meth:`Select.page` fetches ``limit + 1`` rows and returns a :class:`Page` that knows whether
   more existed. A caller cannot get a truncated list that looks complete, because the list is not
   what it gets.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = ["MAX_ROWS", "Page", "QueryError", "Select", "count_of"]

#: A bare identifier, or a dotted/aliased one: ``strain``, ``s.name``, ``COUNT(*)`` is not one.
_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_*][A-Za-z0-9_]*)?$"
)

#: Expressions allowed in a projection beyond a plain identifier. Deliberately a closed list.
_PROJECTION: Final[re.Pattern[str]] = re.compile(
    r"^(COUNT|SUM|MIN|MAX|AVG|GROUP_CONCAT)\(\s*(DISTINCT\s+)?"
    r"(\*|[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\)"
    r"(\s+AS\s+[A-Za-z_][A-Za-z0-9_]*)?$",
    re.IGNORECASE,
)

#: Hard ceiling on a single page, so a caller that forgets to pass one cannot stream the atlas.
MAX_ROWS: Final[int] = 5000

_JOIN_KINDS: Final[frozenset[str]] = frozenset({"INNER", "LEFT", "CROSS"})


class QueryError(RuntimeError):
    """A query could not be built: a bad identifier, an unsupported shape, or a write attempt."""


def _check_identifier(name: str, *, what: str) -> str:
    stripped = name.strip()
    if not _IDENTIFIER.match(stripped):
        raise QueryError(f"{what} {name!r} is not a plain identifier")
    return stripped


def _check_projection(expr: str) -> str:
    stripped = expr.strip()
    if _IDENTIFIER.match(stripped) or _PROJECTION.match(stripped):
        return stripped
    # An aliased plain column: "s.name AS strain_name".
    parts = re.split(r"\s+AS\s+", stripped, flags=re.IGNORECASE)
    if len(parts) == 2 and _IDENTIFIER.match(parts[0].strip()):
        _check_identifier(parts[1], what="alias")
        return stripped
    raise QueryError(f"projection {expr!r} is not a column, an alias or an allowed aggregate")


@dataclass(frozen=True)
class Page:
    """Rows, plus whether there were more of them.

    ``truncated`` is not a convenience. It is the difference between "the atlas holds 20 strains"
    and "you asked for 20 strains", and those render identically unless something carries the
    distinction across the wire.
    """

    rows: tuple[sqlite3.Row, ...]
    limit: int | None
    truncated: bool
    offset: int = 0

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self.rows)

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows]

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rows": self.dicts(),
            "count": len(self.rows),
            "truncated": self.truncated,
        }
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.offset:
            payload["offset"] = self.offset
        if self.truncated:
            payload["note"] = (
                f"more rows matched than the limit of {self.limit}; this is a page, not a total"
            )
        return payload


@dataclass
class Select:
    """A SELECT under construction. Every method returns a new instance; nothing mutates in place.

    Read-only by construction: there is no method that emits anything but SELECT, so this type
    cannot be the route by which a UI writes to the atlas (PLAN.md D.3's layering rule).
    """

    table: str
    alias: str | None = None
    _columns: tuple[str, ...] = ()
    _joins: tuple[tuple[str, str, str, str | None], ...] = ()
    _wheres: tuple[str, ...] = ()
    _params: tuple[Any, ...] = ()
    _group_by: tuple[str, ...] = ()
    _order_by: tuple[str, ...] = ()
    _distinct: bool = field(default=False)

    def __post_init__(self) -> None:
        self.table = _check_identifier(self.table, what="table")
        if self.alias is not None:
            self.alias = _check_identifier(self.alias, what="alias")

    def _replace(self, **changes: Any) -> Select:
        merged: dict[str, Any] = {
            "table": self.table,
            "alias": self.alias,
            "_columns": self._columns,
            "_joins": self._joins,
            "_wheres": self._wheres,
            "_params": self._params,
            "_group_by": self._group_by,
            "_order_by": self._order_by,
            "_distinct": self._distinct,
        }
        merged.update(changes)
        return Select(**merged)

    def columns(self, *names: str) -> Select:
        return self._replace(_columns=self._columns + tuple(_check_projection(n) for n in names))

    def distinct(self) -> Select:
        return self._replace(_distinct=True)

    def join(
        self,
        table: str,
        on: str | Sequence[str],
        *,
        alias: str | None = None,
        kind: str = "LEFT",
    ) -> Select:
        """Join ``table`` on one or more equalities between plain identifiers.

        ``on`` is checked as ``left = right`` with both sides plain identifiers, and a sequence
        of those is ANDed. That is narrow on purpose: a join condition is the natural place for
        an injected predicate to hide, and every join the read layer needs is an equality between
        columns.

        Multiple conditions are not a convenience. `span` and `curation_task` share
        ``record_path``, which is unique only *within* an extraction -- joining on it alone
        cross-joins every extraction of a publication against every other, and the result is a
        finding count several times the real one that looks entirely plausible.
        """
        kind_upper = kind.upper()
        if kind_upper not in _JOIN_KINDS:
            raise QueryError(f"join kind {kind!r} is not one of {sorted(_JOIN_KINDS)}")
        conditions = [on] if isinstance(on, str) else list(on)
        if not conditions:
            raise QueryError("a join needs at least one condition")
        rendered: list[str] = []
        for condition in conditions:
            sides = condition.split("=")
            if len(sides) != 2:
                raise QueryError(f"join condition {condition!r} must be 'left = right'")
            left = _check_identifier(sides[0], what="join column")
            right = _check_identifier(sides[1], what="join column")
            rendered.append(f"{left} = {right}")
        table_checked = _check_identifier(table, what="table")
        alias_checked = _check_identifier(alias, what="alias") if alias else None
        return self._replace(
            _joins=self._joins
            + ((kind_upper, table_checked, " AND ".join(rendered), alias_checked),)
        )

    def where(self, expression: str, *params: Any) -> Select:
        """Add a conjunct. ``expression`` carries ``?`` placeholders; values go in ``params``.

        The placeholder count is checked against the parameter count, because a mismatch is
        otherwise a runtime sqlite3 error thrown far from the call site that caused it.
        """
        expected = expression.count("?")
        if expected != len(params):
            raise QueryError(
                f"{expression!r} has {expected} placeholder(s) but {len(params)} parameter(s)"
            )
        return self._replace(
            _wheres=self._wheres + (f"({expression})",), _params=self._params + params
        )

    def where_in(self, column: str, values: Sequence[Any]) -> Select:
        """``column IN (...)`` with one placeholder per value, or a guaranteed-empty predicate.

        An empty sequence becomes ``0 = 1`` rather than an ``IN ()`` syntax error or, worse, a
        silently dropped filter. "Filter by nothing" means "match nothing", not "match all".
        """
        checked = _check_identifier(column, what="column")
        if not values:
            return self._replace(_wheres=self._wheres + ("(0 = 1)",))
        holes = ", ".join("?" for _ in values)
        return self._replace(
            _wheres=self._wheres + (f"({checked} IN ({holes}))",),
            _params=self._params + tuple(values),
        )

    def group_by(self, *names: str) -> Select:
        return self._replace(
            _group_by=self._group_by + tuple(_check_identifier(n, what="column") for n in names)
        )

    def order_by(self, *names: str) -> Select:
        """Order by column, optionally with a trailing ASC/DESC."""
        checked: list[str] = []
        for name in names:
            parts = name.strip().split()
            column = _check_identifier(parts[0], what="column")
            if len(parts) == 1:
                checked.append(column)
            elif len(parts) == 2 and parts[1].upper() in {"ASC", "DESC"}:
                checked.append(f"{column} {parts[1].upper()}")
            else:
                raise QueryError(f"order term {name!r} is not 'column [ASC|DESC]'")
        return self._replace(_order_by=self._order_by + tuple(checked))

    def sql(self, *, limit: int | None = None, offset: int = 0) -> tuple[str, tuple[Any, ...]]:
        """The statement and its parameters. Pure -- builds nothing and touches no connection."""
        source = f"{self.table} AS {self.alias}" if self.alias else self.table
        projection = ", ".join(self._columns) if self._columns else "*"
        clauses = [f"SELECT {'DISTINCT ' if self._distinct else ''}{projection}", f"FROM {source}"]
        for kind, table, condition, alias in self._joins:
            target = f"{table} AS {alias}" if alias else table
            clauses.append(f"{kind} JOIN {target} ON {condition}")
        if self._wheres:
            clauses.append("WHERE " + " AND ".join(self._wheres))
        if self._group_by:
            clauses.append("GROUP BY " + ", ".join(self._group_by))
        if self._order_by:
            clauses.append("ORDER BY " + ", ".join(self._order_by))
        params = self._params
        if limit is not None:
            clauses.append("LIMIT ?")
            params = params + (limit,)
            if offset:
                clauses.append("OFFSET ?")
                params = params + (offset,)
        elif offset:
            raise QueryError("offset without limit is meaningless; pass a limit")
        return "\n".join(clauses), params

    def page(self, conn: sqlite3.Connection, *, limit: int | None = None, offset: int = 0) -> Page:
        """Execute and return a :class:`Page` that knows whether it was truncated.

        ``limit + 1`` rows are requested and the extra is discarded. One wasted row is the price
        of never handing a caller a short list that looks like a complete one.
        """
        effective = MAX_ROWS if limit is None else min(limit, MAX_ROWS)
        statement, params = self.sql(limit=effective + 1, offset=offset)
        rows = conn.execute(statement, params).fetchall()
        truncated = len(rows) > effective
        return Page(
            rows=tuple(rows[:effective]),
            limit=effective,
            truncated=truncated,
            offset=offset,
        )

    def one(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        """The single matching row, None if there is none, or raise if there is more than one.

        Raising on a second row is the point. A reader that says "the strain" and silently takes
        the first of two has made a claim the data does not support.
        """
        page = self.page(conn, limit=2)
        if not page.rows:
            return None
        if len(page.rows) > 1:
            raise QueryError(f"expected at most one row from {self.table}, got more than one")
        return page.rows[0]

    def scalar(self, conn: sqlite3.Connection) -> Any:
        row = self.one(conn)
        return None if row is None else row[0]


def count_of(table: str, *, where: str | None = None, params: Sequence[Any] = ()) -> Select:
    """``SELECT COUNT(*) AS n FROM table [WHERE ...]`` -- the shape every coverage read needs."""
    query = Select(table).columns("COUNT(*) AS n")
    if where is not None:
        query = query.where(where, *params)
    return query
