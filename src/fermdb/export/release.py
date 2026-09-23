"""Builds the T.5 release bundle: data, schema, provenance graph, versions, licence terms.

**Why JSONL and not CSV.** The bundle's fact tables are newline-delimited JSON, one object per
row. CSV was the obvious alternative and was rejected on one ground: CSV cannot tell an empty
cell from the string `'NA'` from the string `'unknown'` without a quoting convention that every
reader has to be told about and that half of them will not implement. `CONVENTIONS.md` "Missing
values" makes those three *different facts* -- "the source never recorded it", "recorded as not
applicable", "recorded but unresolvable" -- and PLAN.md P.4 exists because collapsing them is the
failure this atlas is built to prevent. JSON distinguishes `null` from `"NA"` from `"unknown"`
natively, and every row additionally carries an `_absence` map naming which of the three each
missing column is in, so a reader that ignores the subtlety still cannot accidentally conflate
them. JSONL keeps the streaming property CSV was wanted for: one row per line, readable with
`for line in file`, no parser state, greppable.

**What the underscore keys are.** Every emitted row carries a small set of keys prefixed with
`_`, injected by this module and never present in `schema.sql`:

    _table, _zone, _zone_label, _is_inference, _may_support_a_conclusion, _absence, _level

The prefix is a reserved namespace and the export refuses to run if a real column ever takes it
(:func:`_check_key_namespace`), because a silent collision would overwrite a fact with a label.
The alternative -- a sidecar file mapping row ids to zones -- was rejected for the reason T.5
gives in its own sentence: a label that lives anywhere but on the row can be separated from the
row, and then Zone I is indistinguishable from Zone R to anyone holding only the data.

**What is reported rather than smoothed.** Three kinds of thing get written down rather than
fixed up, following `query/pathways.py` and `query/traceability.py`:

* an *anomaly* is a stored row the export could not read cleanly -- a `<col>_state` companion
  that disagrees with its number, a `zone` outside R/H/I, an unparseable `tool_versions` JSON.
  It is exported as-is, counted in `manifest.json`, and named. An export that quietly repaired
  it would be publishing a correction nobody reviewed.
* a row whose `zone` is not one of R/H/I is treated as **inference** (`_is_inference` true) and
  filed separately, not as reported. The conservative direction is the only safe one here: the
  cost of mislabelling a reported fact as inferred is a curator's afternoon, and the cost of the
  converse is the thing this atlas exists to prevent.
* the bundle's own licence is stated as whatever the repository actually declares. Where it
  declares nothing, the crate says so rather than inventing a permissive default.

Read-only throughout: every statement here is a SELECT, and the connection may be `mode=ro`.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sqlite3
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .. import __version__ as FERMDB_VERSION
from ..db import SCHEMA_VERSION, schema_sql, schema_version
from ..query.traceability import walk_assertions
from ..query.values import (
    NOT_APPLICABLE_LITERAL,
    UNKNOWN_LITERAL,
    Absence,
    EvidenceLevel,
    QueryValueError,
    Zone,
)
from .crate import CRATE_SPEC_IMPLEMENTED, CRATE_SPEC_NOT_IMPLEMENTED, build_crate

__all__ = [
    "BUNDLE_FORMAT",
    "META_PREFIX",
    "UNRECOGNISED_ZONE_DIRECTORY",
    "UNZONED_DIRECTORY",
    "ZONE_DIRECTORIES",
    "Anomaly",
    "Bundle",
    "ExportError",
    "FileRecord",
    "TableExport",
    "build_release",
]


#: Stamped into `manifest.json`. Bumped when the bundle's layout changes in a way that would
#: break a reader written against the previous one -- the same discipline `meta.schema_version`
#: applies to the database (PLAN.md T.4: five things version independently, and conflating them
#: is the failure mode).
BUNDLE_FORMAT: Final[str] = "fermdb-release/1"

#: The reserved key namespace for labels this module injects onto a row. See the module header.
META_PREFIX: Final[str] = "_"

#: Zone R, H and I each get their own directory, and no file ever holds two zones. This is T.5's
#: "Zone I content exports separately" as a property of the filesystem; the `_zone` field on each
#: row is the authoritative copy, because a directory can be lost and a field travels with the row.
ZONE_DIRECTORIES: Final[Mapping[str, str]] = {
    "R": "data/reported",
    "H": "data/harmonized",
    "I": "data/inferred",
}

#: Tables with no `zone` column at all: vocabularies (`predicate`, `step_role`), pure join tables,
#: and `processing_run`, whose own schema comment explains the omission -- "a processing_run is a
#: record of a computation having happened, not a claim about biology". They are not facts about
#: the world and are filed apart from the ones that are.
UNZONED_DIRECTORY: Final[str] = "data/unzoned"

#: A `zone` value outside R/H/I. A CHECK constraint forbids it, so a row here means the constraint
#: was bypassed; it is filed on its own and labelled as inference, never as reported.
UNRECOGNISED_ZONE_DIRECTORY: Final[str] = "data/zone-unrecognised"

#: The bucket key used in `manifest.json` for a table that carries no zone.
NOT_ZONED: Final[str] = "not_zoned"

_JSONL_MEDIA_TYPE: Final[str] = "application/jsonl"
_JSON_MEDIA_TYPE: Final[str] = "application/json"


class ExportError(RuntimeError):
    """The bundle could not be written, or would have been written wrong."""


# --------------------------------------------------------------------------- what comes back


@dataclass(frozen=True)
class Anomaly:
    """A stored row the export could not read cleanly. Exported anyway, and named."""

    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"

    def as_json(self) -> dict[str, Any]:
        return {"where": self.where, "detail": self.detail}


@dataclass(frozen=True)
class FileRecord:
    """One file in the bundle, with the hash that makes "this exact state" citable (T.2)."""

    path: str
    sha256: str
    size_bytes: int
    media_type: str
    description: str

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "description": self.description,
        }


@dataclass(frozen=True)
class TableExport:
    """One table, split by zone. `by_zone` carries the zeros too, so an absent file is explained.

    A missing `data/inferred/<table>.jsonl` means "this table holds no Zone I rows", and the only
    way a reader can tell that from "Zone I was not exported" is a manifest that lists the zero.
    """

    table: str
    zoned: bool
    rows: int
    by_zone: Mapping[str, int]
    files: Mapping[str, str]

    def as_json(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "zoned": self.zoned,
            "rows": self.rows,
            "by_zone": dict(self.by_zone),
            "files": dict(self.files),
        }


@dataclass(frozen=True)
class Bundle:
    """What was written, where, and under which digest."""

    root: Path
    tables: tuple[TableExport, ...]
    files: tuple[FileRecord, ...]
    anomalies: tuple[Anomaly, ...]
    #: sha256 over the per-file hashes: one string that names this exact state of the atlas.
    digest: str
    generated_at: str
    release: str | None

    @property
    def n_rows(self) -> int:
        return sum(table.rows for table in self.tables)

    @property
    def n_inferred_rows(self) -> int:
        return sum(table.by_zone.get(Zone.INFERRED.value, 0) for table in self.tables)

    def file(self, path: str) -> FileRecord:
        for record in self.files:
            if record.path == path:
                return record
        raise KeyError(path)

    def summary(self) -> str:
        lines = [
            f"wrote {len(self.files)} file(s) to {self.root}",
            f"  {self.n_rows} row(s) over {len(self.tables)} table(s)",
            f"  {self.n_inferred_rows} Zone I row(s), in {ZONE_DIRECTORIES['I']}/ and labelled "
            "_is_inference: true",
            f"  bundle digest sha256:{self.digest}",
        ]
        if self.anomalies:
            lines.append(f"  {len(self.anomalies)} anomaly/anomalies, named in manifest.json:")
            lines.extend(f"    {anomaly}" for anomaly in self.anomalies[:10])
            if len(self.anomalies) > 10:
                lines.append(f"    ... and {len(self.anomalies) - 10} more")
        return "\n".join(lines)


# ------------------------------------------------------------------------------- the writer


class _Writer:
    """Writes a file, hashes it, and remembers what it was for.

    Newlines are forced to ``\\n`` and the encoding to UTF-8 on every write. On Windows the
    default would be CRLF, which changes the sha256 of a byte-identical bundle depending on which
    machine produced it -- and a content hash that depends on the operating system is not a
    content hash (PLAN.md T.2).
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: list[FileRecord] = []

    def _write(self, path: str, text: str, media_type: str, description: str) -> FileRecord:
        target = self.root.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        with target.open("wb") as handle:
            handle.write(data)
        record = FileRecord(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            media_type=media_type,
            description=description,
        )
        self.records.append(record)
        return record

    def text(self, path: str, text: str, *, media_type: str, description: str) -> FileRecord:
        return self._write(path, text, media_type, description)

    def json_file(self, path: str, payload: Any, *, description: str) -> FileRecord:
        body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        return self._write(path, body, _JSON_MEDIA_TYPE, description)

    def jsonl(
        self, path: str, rows: Iterable[Mapping[str, Any]], *, description: str
    ) -> FileRecord:
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return self._write(path, body, _JSONL_MEDIA_TYPE, description)


# ------------------------------------------------------------------- reading the schema shape


@dataclass(frozen=True)
class _TableShape:
    name: str
    columns: tuple[str, ...]
    types: Mapping[str, str]
    primary_key: tuple[str, ...]
    #: column -> its `<col>_state` companion, for the three-state numerics `schema.sql` defines.
    state_companions: Mapping[str, str]

    @property
    def zoned(self) -> bool:
        return "zone" in self.columns


def _table_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _table_shape(conn: sqlite3.Connection, table: str) -> _TableShape:
    # `table` is never caller-supplied: it comes from sqlite_master. Same reasoning as
    # `query/traceability._exists`.
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = tuple(str(row["name"]) for row in info)
    types = {str(row["name"]): str(row["type"] or "") for row in info}
    # `pk` is 1-based position within the primary key, 0 for a column outside it, so the sort
    # reproduces the declared key order for a composite key rather than the column order.
    key_columns = [row for row in info if int(row["pk"]) > 0]
    primary_key = tuple(
        str(row["name"]) for row in sorted(key_columns, key=lambda row: int(row["pk"]))
    )
    companions = {column: f"{column}_state" for column in columns if f"{column}_state" in columns}
    return _TableShape(
        name=table,
        columns=columns,
        types=types,
        primary_key=primary_key,
        state_companions=companions,
    )


def _check_key_namespace(shapes: Sequence[_TableShape]) -> None:
    """Refuse to export if a real column would collide with an injected label.

    Nothing in `schema.sql` starts a column with an underscore today. If that ever changes, the
    export would silently overwrite a stored fact with a zone label, which is a data corruption
    the reader has no way to detect -- so it is a hard failure here instead.
    """
    for shape in shapes:
        for column in shape.columns:
            if column.startswith(META_PREFIX):
                raise ExportError(
                    f"{shape.name}.{column} starts with {META_PREFIX!r}, which this export "
                    "reserves for the zone, absence and level labels it injects onto every row. "
                    "Rename the column or change META_PREFIX; do not let them collide."
                )


# ------------------------------------------------------------------------- the row labelling


def _absence_of(value: Any, *, state: Any, has_state: bool) -> tuple[str | None, str | None]:
    """Which of CONVENTIONS.md's three absences a cell is in, or None if it holds a value.

    Deliberately not a call into `query.values.from_state_column`, although the rule is that
    function's rule: it *raises* on a mismatched pair, which is right for a reader serving one
    record and wrong for an export, where one bad row must not stop the bundle. The disagreement
    is returned as an anomaly instead, named in `manifest.json`, and the row is exported as
    stored.
    """
    if has_state:
        if state is None:
            if value is not None:
                return (
                    Absence.NOT_RECORDED.value,
                    "the state companion is NULL but the value is not; the pair is mismatched",
                )
            return Absence.NOT_RECORDED.value, None
        if state == "recorded":
            if value is None:
                return (
                    Absence.NOT_RECORDED.value,
                    "the state companion says 'recorded' but the value is NULL",
                )
            return None, None
        if state == Absence.NOT_APPLICABLE.value:
            return Absence.NOT_APPLICABLE.value, None
        if state == UNKNOWN_LITERAL:
            return Absence.UNKNOWN.value, None
        return Absence.UNKNOWN.value, f"unrecognised state companion value {state!r}"

    if value is None:
        return Absence.NOT_RECORDED.value, None
    if value == NOT_APPLICABLE_LITERAL:
        return Absence.NOT_APPLICABLE.value, None
    if value == UNKNOWN_LITERAL:
        return Absence.UNKNOWN.value, None
    return None, None


def _zone_fields(shape: _TableShape, raw: Any) -> tuple[dict[str, Any], str | None]:
    """The zone label carried on the row itself, and an anomaly if the stored zone is not one.

    An unzoned table gets `_zone: null` with `_zone_label: "not_zoned"` and **no**
    `_may_support_a_conclusion` key -- the question is malformed for a vocabulary row or a
    processing run, and answering it with `null` would put a fourth meaning on a key whose whole
    job is to be unambiguous.
    """
    if not shape.zoned:
        return (
            {"_zone": None, "_zone_label": NOT_ZONED, "_is_inference": False},
            None,
        )
    try:
        zone = Zone(str(raw))
    except ValueError:
        return (
            {
                "_zone": raw,
                "_zone_label": "unrecognised",
                # Conservative on purpose: a row whose zone cannot be read has not been shown to
                # be reported, and treating it as inference costs a curator an afternoon while
                # the converse is the exact mistake T.5 exists to prevent.
                "_is_inference": True,
                "_may_support_a_conclusion": False,
            },
            f"zone is {raw!r}, which is not one of R/H/I; exported as inference",
        )
    return (
        {
            "_zone": zone.value,
            "_zone_label": zone.display,
            "_is_inference": zone is Zone.INFERRED,
            "_may_support_a_conclusion": zone.may_support_a_conclusion,
        },
        None,
    )


def _level_fields(row: sqlite3.Row) -> tuple[dict[str, Any], str | None]:
    """L1-L5 for one `assertion_level` row, with the basis that produced it.

    The basis travels because the view returns NULL for two opposite reasons -- nothing known,
    and direct evidence in open conflict -- and `EvidenceLevel` is the repo's existing refusal to
    let those arrive as the same absence. Reused rather than re-derived, so the export cannot
    drift from what the API serves.
    """
    basis = str(row["derived_reason"])
    level = None if row["level"] is None else str(row["level"])
    try:
        evidence_level = EvidenceLevel(
            level=level,
            basis=basis,
            is_overridden=bool(row["is_overridden"]),
            override_reason=None if row["override_reason"] is None else str(row["override_reason"]),
        )
    except QueryValueError as exc:
        return (
            {
                "level": level,
                "basis": basis,
                "display": level or basis,
                "is_conflicted": False,
                "is_overridden": bool(row["is_overridden"]),
            },
            f"assertion_level row will not construct an EvidenceLevel: {exc}",
        )
    return evidence_level.as_json(), None


# -------------------------------------------------------------------------- the data section


def _order_by(shape: _TableShape) -> str:
    """A stable row order, so two exports of one database are byte-identical."""
    if shape.primary_key:
        return ", ".join(f'"{column}"' for column in shape.primary_key)
    return "rowid"


def _zone_bucket(fields: Mapping[str, Any], shape: _TableShape) -> str:
    if not shape.zoned:
        return NOT_ZONED
    label = fields["_zone_label"]
    return str(fields["_zone"]) if label != "unrecognised" else f"unrecognised:{fields['_zone']}"


def _bucket_path(bucket: str, shape: _TableShape) -> str:
    """Where one table's rows for one bucket go. One file per table per bucket, never shared.

    The unrecognised case earns its own suffix rather than sharing `<table>.jsonl`: two different
    bad zone values in one table would otherwise write to the same path and the second would
    overwrite the first, losing rows in the one situation where the atlas is already known to be
    in a state it should not be in. The raw value is slugified because it reached here precisely
    by escaping the constraint that says what it may contain, and an unsanitised one would be a
    path.
    """
    if not shape.zoned:
        return f"{UNZONED_DIRECTORY}/{shape.name}.jsonl"
    if bucket in ZONE_DIRECTORIES:
        return f"{ZONE_DIRECTORIES[bucket]}/{shape.name}.jsonl"
    raw = bucket.split(":", 1)[1] if ":" in bucket else bucket
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:40] or "blank"
    return f"{UNRECOGNISED_ZONE_DIRECTORY}/{shape.name}.zone-{slug}.jsonl"


def _file_description(table: str, bucket: str, rows: int) -> str:
    if bucket == NOT_ZONED:
        return (
            f"{rows} row(s) of `{table}`, a table with no zone column: a vocabulary, a join "
            "table, or a record of a computation rather than a claim about biology."
        )
    if bucket == Zone.INFERRED.value:
        return (
            f"{rows} INFERRED row(s) of `{table}` (Zone I): statistical, model or LLM output. "
            "Every row carries `_is_inference: true` and `_may_support_a_conclusion: false`. "
            'CONVENTIONS.md "Data zones": Zone I may not support a conclusion until a curator '
            "promotes it."
        )
    if bucket == Zone.REPORTED.value:
        return f"{rows} REPORTED row(s) of `{table}` (Zone R): exactly as the source stated it."
    if bucket == Zone.HARMONIZED.value:
        return (
            f"{rows} HARMONIZED row(s) of `{table}` (Zone H): derived from Zone R by recorded "
            "code, and reconstructible from it."
        )
    return (
        f"{rows} row(s) of `{table}` whose stored zone is not one of R/H/I. Exported as "
        "inference, never as reported, and counted as an anomaly in manifest.json."
    )


def _export_table(
    conn: sqlite3.Connection,
    writer: _Writer,
    shape: _TableShape,
    levels: Mapping[str, dict[str, Any]],
    anomalies: list[Anomaly],
) -> TableExport:
    rows = conn.execute(
        f'SELECT * FROM "{shape.name}" ORDER BY {_order_by(shape)}'  # noqa: S608 - see _table_shape
    ).fetchall()

    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        keys = row.keys()
        values = {column: row[column] for column in keys}
        row_id = str(values.get("id", "(no id column)"))
        where = f"{shape.name} {row_id}"

        zone_fields, zone_anomaly = _zone_fields(shape, values.get("zone"))
        if zone_anomaly is not None:
            anomalies.append(Anomaly(where, zone_anomaly))

        absence: dict[str, str] = {}
        # A `<col>_state` companion is skipped: its value is a state token, not a datum. The
        # literal 'unknown' in `g_per_g_state` means "g_per_g was recorded but unresolvable",
        # and reporting it as "g_per_g_state is unknown" would be a second, false absence sitting
        # on top of the real one it is there to express.
        companions = set(shape.state_companions.values())
        for column in shape.columns:
            if column in companions:
                continue
            companion = shape.state_companions.get(column)
            state, detail = _absence_of(
                values[column],
                state=values[companion] if companion else None,
                has_state=companion is not None,
            )
            if detail is not None:
                anomalies.append(Anomaly(f"{where}.{column}", detail))
            if state is not None:
                absence[column] = state

        payload: dict[str, Any] = {"_table": shape.name, **zone_fields}
        if absence:
            payload["_absence"] = absence
        if shape.name == "assertion" and row_id in levels:
            payload["_level"] = levels[row_id]
        payload.update(values)

        buckets.setdefault(_zone_bucket(zone_fields, shape), []).append(payload)

    by_zone: dict[str, int] = (
        {zone: 0 for zone in ZONE_DIRECTORIES} if shape.zoned else {NOT_ZONED: 0}
    )
    files: dict[str, str] = {}
    for bucket, bucket_rows in sorted(buckets.items()):
        by_zone[bucket] = len(bucket_rows)
        path = _bucket_path(bucket, shape)
        writer.jsonl(
            path,
            bucket_rows,
            description=_file_description(shape.name, bucket, len(bucket_rows)),
        )
        files[bucket] = path

    return TableExport(
        table=shape.name,
        zoned=shape.zoned,
        rows=len(rows),
        by_zone=by_zone,
        files=files,
    )


def _assertion_levels(
    conn: sqlite3.Connection, anomalies: list[Anomaly]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The `assertion_level` view, once: as a per-assertion label and as a provenance file."""
    labels: dict[str, dict[str, Any]] = {}
    full: list[dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM assertion_level ORDER BY assertion_id").fetchall():
        assertion_id = str(row["assertion_id"])
        fields, detail = _level_fields(row)
        if detail is not None:
            anomalies.append(Anomaly(f"assertion_level {assertion_id}", detail))
        labels[assertion_id] = fields
        full.append(
            {
                "_table": "assertion_level",
                "_view": True,
                "_level": fields,
                # `.keys()` is load-bearing and not the dict idiom ruff reads it as:
                # iterating a sqlite3.Row yields its VALUES, so dropping it would build a
                # mapping of value -> cell and silently corrupt the file.
                **{column: row[column] for column in row.keys()},  # noqa: SIM118
            }
        )
    return labels, full


# -------------------------------------------------------------------- the provenance section


def _processing_run_recipes(
    conn: sqlite3.Connection, anomalies: list[Anomaly]
) -> list[dict[str, Any]]:
    """PLAN.md T.1's recipes, joined to what they produced.

    `processing_run` also ships verbatim in `data/unzoned/`. This file is the *graph*: the run,
    its parsed tool versions, and every `analysis_result` that names it, down to the dataset
    accession J.5's analysis arm ends at. A reader reconstructing "which code produced this
    number" should not have to join four JSONL files by hand to do it.
    """
    recipes: list[dict[str, Any]] = []
    for run in conn.execute("SELECT * FROM processing_run ORDER BY id").fetchall():
        run_id = str(run["id"])
        raw_versions = run["tool_versions"]
        tool_versions: Any = None
        if raw_versions is not None:
            try:
                tool_versions = json.loads(str(raw_versions))
            except json.JSONDecodeError as exc:
                anomalies.append(
                    Anomaly(
                        f"processing_run {run_id}.tool_versions",
                        f"is not valid JSON ({exc.msg}); exported verbatim as a string",
                    )
                )
                tool_versions = {"_unparsed": str(raw_versions)}

        results = conn.execute(
            "SELECT r.id, r.kind, r.payload_ref, r.zone, r.dataset_id, "
            "       d.accession, d.repository, d.license "
            "FROM analysis_result r LEFT JOIN dataset d ON d.id = r.dataset_id "
            "WHERE r.processing_run_id = ? ORDER BY r.id",
            (run_id,),
        ).fetchall()
        recipes.append(
            {
                # See the note on `.keys()` in `_assertion_levels`: a sqlite3.Row iterates
                # its values, not its column names.
                "processing_run": {
                    column: run[column]
                    for column in run.keys()  # noqa: SIM118
                },
                "tool_versions": tool_versions,
                "analysis_results": [
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "payload_ref": row["payload_ref"],
                        "zone": row["zone"],
                        "_is_inference": str(row["zone"]) == Zone.INFERRED.value,
                        "dataset": (
                            None
                            if row["dataset_id"] is None
                            else {
                                "id": row["dataset_id"],
                                "accession": row["accession"],
                                "repository": row["repository"],
                                "license": row["license"],
                            }
                        ),
                    }
                    for row in results
                ],
            }
        )
    return recipes


def _traceability(conn: sqlite3.Connection) -> dict[str, Any]:
    """PLAN.md J.5's chain, walked by `query.traceability` rather than re-derived here.

    Reused deliberately: a second implementation of the walk would be a second opinion about what
    a complete chain is, and the value of shipping the graph is that it is the *same* graph the
    CI gate checks. `breaks` and `gaps` travel with it -- an export that shipped only the chains
    that closed would be claiming a completeness the atlas does not have.
    """
    walk = walk_assertions(conn)
    return {
        "walk": walk.as_json(),
        "note": (
            "Produced by fermdb.query.traceability.walk_assertions over every ACTIVE assertion. "
            "A 'break' is a chain that does not close and is a bug of the same severity as a "
            "failing unit test (PLAN.md J.5). A 'gap' is a hop J.5 names that the schema cannot "
            "traverse; it is reported, never silently skipped, and is not a failure. "
            "`vacuous: true` means there were no active assertions to walk -- not that everything "
            "passed."
        ),
    }


def _versions(conn: sqlite3.Connection) -> dict[str, Any]:
    """T.5's "pipeline versions", and the versions of everything that produced the bundle."""
    pipelines = [
        {"pipeline": row["pipeline"], "version": row["version"], "runs": row["runs"]}
        for row in conn.execute(
            "SELECT pipeline, version, COUNT(*) AS runs FROM processing_run "
            "GROUP BY pipeline, version ORDER BY pipeline, version"
        ).fetchall()
    ]
    containers = [
        {"pipeline": row["pipeline"], "version": row["version"], "digest": row["container_digest"]}
        for row in conn.execute(
            "SELECT DISTINCT pipeline, version, container_digest FROM processing_run "
            "WHERE container_digest IS NOT NULL ORDER BY pipeline, version, container_digest"
        ).fetchall()
    ]
    found = schema_version(conn)
    return {
        "bundle_format": BUNDLE_FORMAT,
        "fermdb": FERMDB_VERSION,
        "schema": {
            "database_version": found,
            "build_understands": SCHEMA_VERSION,
            "note": (
                "PLAN.md T.4: the schema version is an integer with migrations, and is a "
                "different thing from the pipeline versions below and from the release id. "
                "`schema/schema.sql` is the DDL at `database_version`."
            ),
        },
        "pipelines": pipelines,
        "container_digests": containers,
        "runtime": {
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "note": (
                "The interpreter that wrote the bundle, not a requirement for reading it. The "
                "data files are plain UTF-8 JSONL and need nothing from this list."
            ),
        },
        "pipeline_versions_note": (
            "Per-run recipes -- container digest, parameter hash, input hashes, seed, exit "
            "status -- are in provenance/processing_runs.jsonl (PLAN.md T.1). An empty "
            "`pipelines` list means the atlas holds no processing_run rows, so no computed "
            "result in this bundle can name its recipe."
        ),
    }


def _licence_groups(conn: sqlite3.Connection, table: str, column: str) -> list[dict[str, Any]]:
    """Licence values held in one column, with NULL kept distinct from 'unknown'.

    The point of the split: NULL means no licence information ever reached us, `'unknown'` means
    somebody looked and could not resolve it (`schema.sql`, fulltext_asset). A `GROUP BY` that
    rendered both as an empty cell would erase a curator's work.
    """
    rows = conn.execute(
        f'SELECT "{column}" AS value, COUNT(*) AS rows FROM "{table}" '  # noqa: S608
        f'GROUP BY "{column}" ORDER BY rows DESC, value'
    ).fetchall()
    groups: list[dict[str, Any]] = []
    for row in rows:
        absence, _ = _absence_of(row["value"], state=None, has_state=False)
        entry: dict[str, Any] = {"value": row["value"], "rows": int(row["rows"])}
        if absence is not None:
            entry["absent"] = absence
            entry["absent_because"] = Absence(absence).explanation
        groups.append(entry)
    return groups


def _licences(
    conn: sqlite3.Connection,
    *,
    annotation_sources_file: Path | None,
    repo_licence: Mapping[str, Any],
) -> dict[str, Any]:
    """T.5's "licence terms", per source, read from where each one is actually recorded."""
    external: dict[str, Any]
    if annotation_sources_file is None:
        external = {
            "read": False,
            "why": (
                "no annotation sources file was supplied to the export. "
                "data/annotation/annotation_sources.yaml carries the per-database licence and "
                "redistributability terms; without it this bundle states no terms for the "
                "external annotation sources."
            ),
            "sources": [],
        }
    elif not annotation_sources_file.is_file():
        external = {
            "read": False,
            "why": f"{annotation_sources_file} does not exist",
            "sources": [],
        }
    else:
        # Imported here rather than at module scope: `annotate.sources` reads YAML and belongs to
        # the annotation package, and the export must not fail to load because that package
        # changed. The failure mode this guards against is an export that cannot run at all.
        from ..annotate.sources import AnnotationSourcesError, load_annotation_sources

        try:
            sources = load_annotation_sources(annotation_sources_file)
        except AnnotationSourcesError as exc:
            external = {"read": False, "why": str(exc), "sources": []}
        else:
            external = {
                "read": True,
                "file": annotation_sources_file.name,
                "sources": [
                    {
                        "id": source.id,
                        "name": source.name,
                        "covers": source.covers,
                        "url_pattern": source.url_pattern,
                        "license": source.license,
                        "redistributable": source.redistributable,
                        "confidence": source.confidence,
                        "evidence": source.evidence,
                    }
                    for source in sources
                ],
            }

    return {
        "bundle": repo_licence,
        "external_annotation_sources": external,
        "publications": {
            "note": (
                "Per-publication access terms as recorded in `publication.license`. PLAN.md H.4 "
                "is binding on what this project stores: full text is kept only where the "
                "licence permits it, and `fulltext_asset.storage_state` says which side of that "
                "line each paper fell on."
            ),
            "by_license": _licence_groups(conn, "publication", "license"),
        },
        "datasets": {
            "note": "Per-deposit terms as recorded in `dataset.license`.",
            "by_license": _licence_groups(conn, "dataset", "license"),
        },
        "fulltext_assets": {
            "note": (
                "`text_mining_allowed` is three-state on purpose: 'yes'/'no' is a resolved claim, "
                "'unknown' is recorded-but-unresolved, and NULL is no licence information at all."
            ),
            "by_license": _licence_groups(conn, "fulltext_asset", "license"),
            "by_text_mining_allowed": _licence_groups(
                conn, "fulltext_asset", "text_mining_allowed"
            ),
            "by_storage_state": _licence_groups(conn, "fulltext_asset", "storage_state"),
        },
        "quoted_text_warning": (
            "`span.quoted_text` holds verbatim sentences from the cited publications, and "
            "`extraction` holds model output about them. Redistribution of this bundle is "
            "therefore governed by the terms of the publications listed above as well as by the "
            "bundle's own terms. This export does NOT redact quotations per publication licence; "
            "it states the terms and leaves the decision to whoever publishes the bundle."
        ),
    }


def _repo_licence(repo_root: Path | None) -> dict[str, Any]:
    """Whatever the repository actually declares. Nothing is invented where nothing is declared."""
    if repo_root is None:
        return {
            "declared": False,
            "why": "no repository root was supplied to the export, so none was looked for",
        }
    for name in ("LICENSE", "LICENCE", "LICENSE.md", "LICENCE.md", "COPYING"):
        candidate = repo_root / name
        if candidate.is_file():
            return {
                "declared": True,
                "file": name,
                "text": candidate.read_text(encoding="utf-8"),
            }
    return {
        "declared": False,
        "why": (
            f"no LICENSE/LICENCE/COPYING file exists at {repo_root}. The atlas declares no terms "
            "of its own, and this export will not invent permissive ones on its behalf. Whoever "
            "publishes this bundle must state its terms; the per-source terms it is built on are "
            "listed beside this note."
        ),
    }


# ------------------------------------------------------------------------------ the assembly


def _schema_tables_json(shapes: Sequence[_TableShape], views: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "note": (
            "The column shape of every exported table, so a reader can rebuild the database "
            "without parsing schema/schema.sql. `state_companions` names the `<col>_state` "
            "columns that carry CONVENTIONS.md's three-state absence for a numeric column."
        ),
        "views": list(views),
        "tables": [
            {
                "table": shape.name,
                "zoned": shape.zoned,
                "primary_key": list(shape.primary_key),
                "columns": [
                    {"name": column, "type": shape.types.get(column, "")}
                    for column in shape.columns
                ],
                "state_companions": dict(shape.state_companions),
            }
            for shape in shapes
        ],
    }


def _conventions_block() -> dict[str, Any]:
    """The reading rules, as data rather than as a paragraph in a README nobody has to open."""
    return {
        "zones": {
            zone.value: {
                "label": zone.display,
                "directory": ZONE_DIRECTORIES[zone.value],
                "may_support_a_conclusion": zone.may_support_a_conclusion,
            }
            for zone in Zone
        },
        "zone_note": (
            "Zone I is inference -- statistical, model or LLM output -- and may not support a "
            "conclusion until a curator promotes it. It is exported in its own files AND every "
            "one of its rows carries `_is_inference: true`. The field is authoritative; the "
            "directory is convenience."
        ),
        "not_zoned": {
            "label": NOT_ZONED,
            "directory": UNZONED_DIRECTORY,
            "note": (
                "Tables with no `zone` column: vocabularies, join tables, and `processing_run`, "
                "which records that a computation happened rather than making a claim about "
                "biology. Rows here carry no `_may_support_a_conclusion` key, because the "
                "question does not apply to them."
            ),
        },
        "unrecognised_zone": {
            "directory": UNRECOGNISED_ZONE_DIRECTORY,
            "note": (
                "A stored `zone` outside R/H/I, which a CHECK constraint should have prevented. "
                "Exported as inference, never as reported, and named in `anomalies`."
            ),
        },
        "missing_values": {
            absence.value: {
                "meaning": absence.explanation,
                "display": absence.display,
                "stored_as": {
                    Absence.NOT_RECORDED.value: "SQL NULL",
                    Absence.NOT_APPLICABLE.value: f"the literal string {NOT_APPLICABLE_LITERAL!r}",
                    Absence.UNKNOWN.value: f"the literal string {UNKNOWN_LITERAL!r}",
                }[absence.value],
            }
            for absence in Absence
        },
        "missing_values_note": (
            "Three distinct states, never collapsed into one another and never into zero "
            "(docs/reference/CONVENTIONS.md). Each row's `_absence` map names the state of every "
            "column that holds no value, including the ones whose state is carried by a "
            "`<col>_state` companion. `unknown` rows are excluded from analyses rather than "
            "defaulted."
        ),
        "evidence_levels": {
            "field": "_level",
            "carried_on": "every row of the `assertion` table, in whichever zone file it lands",
            "note": (
                "L1-L5 derived by the `assertion_level` view (PLAN.md J.3), never stored: a "
                "stored level becomes a lie the first time a new paper lands. `level` is null "
                "for TWO opposite reasons and `basis` is the only thing that separates them -- "
                "'no_evidence' (the atlas knows nothing) and 'direct_evidence_discordant' "
                "(direct evidence on both sides, unresolved). An override is applied on top and "
                "always reported as `is_overridden`."
            ),
        },
        "injected_keys": {
            "prefix": META_PREFIX,
            "keys": [
                "_table",
                "_zone",
                "_zone_label",
                "_is_inference",
                "_may_support_a_conclusion",
                "_absence",
                "_level",
            ],
            "note": (
                "Added by the export, never columns in schema.sql. Every other key in a row is a "
                "column name and its value is what the database holds, verbatim."
            ),
        },
    }


def _readme(bundle_digest: str, generated_at: str, release: str | None) -> str:
    """Human-facing, and explicitly not the place the rules live."""
    release_line = (
        f"release: {release}"
        if release
        else "release: none given. This is a snapshot, not a citable release (PLAN.md T.4 dates "
        "releases vYYYY.N). Cite the bundle digest below instead."
    )
    return f"""# fermdb release export

An export of the isobutanol strain-engineering atlas (PLAN.md T.5).

    generated_at: {generated_at}
    {release_line}
    bundle digest: sha256:{bundle_digest}

**This README is not authoritative.** Every rule below is carried as data in `manifest.json` and
as fields on the rows themselves, because a label that lives only in documentation can be
separated from the data it describes.

## Layout

    ro-crate-metadata.json   RO-Crate metadata descriptor (see manifest.json for what of the
                             specification is and is not implemented)
    manifest.json            file hashes, row counts per table per zone, the reading rules,
                             and every anomaly found while exporting
    README.md                this file
    schema/schema.sql        the DDL, at the schema version recorded in manifest.json
    schema/tables.json       column shapes, primary keys, three-state companions
    data/reported/           Zone R -- exactly as the source stated it
    data/harmonized/         Zone H -- derived from Zone R by recorded code
    data/inferred/           Zone I -- INFERENCE. Model, statistical or LLM output
    data/unzoned/            tables that carry no zone (vocabularies, joins, processing runs)
    provenance/              the J.5 evidence chains, T.1 run recipes, versions, licence terms

One JSONL file per table per zone: one JSON object per line, UTF-8, LF.

## The two rules that matter

**Zone I is inference.** It is in its own files, and every row in them carries
`"_is_inference": true` and `"_may_support_a_conclusion": false`. Nothing in `data/inferred/` may
support a conclusion until a curator has promoted it. A reader that loads only `data/reported/`
and `data/harmonized/` has loaded only content the atlas stands behind.

**There are three ways for a value to be missing, and they are different facts.** `null` means
the source never recorded it; `"NA"` means it was recorded as not applicable; `"unknown"` means
it was recorded but could not be resolved to a controlled value. Every row carries an `_absence`
map naming which state each empty column is in. Do not coerce any of the three into another, and
do not coerce any of them into zero.
"""


def build_release(
    conn: sqlite3.Connection,
    out_dir: Path,
    *,
    release: str | None = None,
    repo_root: Path | None = None,
    annotation_sources_file: Path | None = None,
    generated_at: datetime | None = None,
    force: bool = False,
) -> Bundle:
    """Write the T.5 release bundle into `out_dir` and return what was written.

    Args:
        conn: A connection to the atlas. Read-only is sufficient and nothing here writes.
        out_dir: Where the bundle goes. Refused if it exists and is non-empty, unless `force`:
            a half-overwritten bundle whose manifest describes files from two different exports
            is worse than no bundle, and the digest would silently describe neither.
        release: The release id (PLAN.md T.4's `vYYYY.N`). Optional, and its absence is recorded
            as such rather than filled in with a date -- an invented release id is a citation to
            something that does not exist.
        repo_root: Where to look for the repository's own licence file. None means "do not look",
            and the bundle says so rather than claiming no licence was declared.
        annotation_sources_file: `data/annotation/annotation_sources.yaml`, for the per-database
            licence and redistributability terms.
        generated_at: Injectable so a test can produce a byte-identical bundle twice. Defaults to
            now, in UTC.
        force: Write into a non-empty directory.

    Raises:
        ExportError: The output directory is unusable, or a column would collide with the
            reserved `_` label namespace.
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        if not out_dir.is_dir():
            raise ExportError(f"{out_dir} exists and is not a directory")
        if any(out_dir.iterdir()) and not force:
            raise ExportError(
                f"{out_dir} is not empty. Pass --force to write into it anyway; a bundle mixed "
                "with the remains of an earlier one has a manifest that describes neither."
            )
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    writer = _Writer(out_dir)
    anomalies: list[Anomaly] = []

    shapes = [_table_shape(conn, table) for table in _table_names(conn)]
    _check_key_namespace(shapes)
    views = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
        ).fetchall()
    )

    # 1. The schema, and the version it was taken at.
    writer.text(
        "schema/schema.sql",
        schema_sql(),
        media_type="application/sql",
        description=(
            "The DDL this export was taken at. Its CHECK constraints are the enforcement the "
            "flat files cannot carry; read them before treating a column as free-form."
        ),
    )
    writer.json_file(
        "schema/tables.json",
        _schema_tables_json(shapes, views),
        description="Column shapes, primary keys and three-state `<col>_state` companions.",
    )

    # 2. The data, split by zone. Zone I lands in files of its own (PLAN.md T.5).
    levels, level_rows = _assertion_levels(conn, anomalies)
    tables = [_export_table(conn, writer, shape, levels, anomalies) for shape in shapes]

    # 3. The provenance graph.
    writer.json_file(
        "provenance/traceability.json",
        _traceability(conn),
        description=(
            "PLAN.md J.5's evidence chains: every active assertion walked through its evidence "
            "items to the measurement, publication or processing run it rests on, with every "
            "break and every unwalkable hop named."
        ),
    )
    writer.jsonl(
        "provenance/processing_runs.jsonl",
        _processing_run_recipes(conn, anomalies),
        description=(
            "PLAN.md T.1's recipes: each processing run with its parsed tool versions and every "
            "analysis_result that names it, down to the dataset accession."
        ),
    )
    writer.jsonl(
        "provenance/evidence_levels.jsonl",
        level_rows,
        description=(
            "The `assertion_level` view in full: L1-L5 per assertion with the basis it was "
            "derived from and any curator override. Also carried as `_level` on each assertion "
            "row in the data files."
        ),
    )
    writer.json_file(
        "provenance/versions.json",
        _versions(conn),
        description="Schema version, pipeline and container versions, and the build runtime.",
    )
    writer.json_file(
        "provenance/licences.json",
        _licences(
            conn,
            annotation_sources_file=annotation_sources_file,
            repo_licence=_repo_licence(repo_root),
        ),
        description=(
            "Licence terms per source: the bundle's own terms, each external annotation "
            "database's, and the access terms recorded per publication and per deposit."
        ),
    )

    # 4. The digest, over everything written so far. The manifest cannot contain its own hash, so
    #    it is written afterwards and the digest names the payload rather than the description of
    #    the payload -- which is the thing a third party is citing (PLAN.md T.2, T.5).
    payload_records = sorted(writer.records, key=lambda record: record.path)
    digest = hashlib.sha256(
        "".join(f"{record.sha256}  {record.path}\n" for record in payload_records).encode("utf-8")
    ).hexdigest()

    writer.text(
        "README.md",
        _readme(digest, stamp, release),
        media_type="text/markdown",
        description="Human-readable orientation. Not authoritative; the rules are in the data.",
    )

    writer.json_file(
        "manifest.json",
        {
            "bundle_format": BUNDLE_FORMAT,
            "generated_at": stamp,
            "release": (
                {"id": release}
                if release
                else {
                    "id": None,
                    "why": (
                        "no release id was given. PLAN.md T.4 dates atlas releases vYYYY.N and "
                        "makes them immutable and citable; this bundle is a snapshot. Cite "
                        "`bundle_digest` to name this exact state."
                    ),
                }
            ),
            "bundle_digest": f"sha256:{digest}",
            "bundle_digest_covers": [record.path for record in payload_records],
            "bundle_digest_note": (
                "sha256 over the lines '<sha256>  <path>' of every file listed in "
                "`bundle_digest_covers`, sorted by path. README.md, manifest.json and "
                "ro-crate-metadata.json are written after it and are not covered: they describe "
                "the payload rather than being it."
            ),
            "schema_version": schema_version(conn),
            "conventions": _conventions_block(),
            "tables": [table.as_json() for table in tables],
            "row_totals": {
                "rows": sum(table.rows for table in tables),
                "by_zone": {
                    bucket: sum(table.by_zone.get(bucket, 0) for table in tables)
                    for bucket in (*ZONE_DIRECTORIES, NOT_ZONED)
                },
            },
            "anomalies": [anomaly.as_json() for anomaly in anomalies],
            "anomalies_note": (
                "Rows this export could not read cleanly: a `<col>_state` companion disagreeing "
                "with its number, a `zone` outside R/H/I, an unparseable `tool_versions`. Each "
                "is exported as stored and named here. Nothing was repaired."
            ),
            "ro_crate": {
                "descriptor": "ro-crate-metadata.json",
                "implemented": list(CRATE_SPEC_IMPLEMENTED),
                "not_implemented": list(CRATE_SPEC_NOT_IMPLEMENTED),
            },
            "files": [record.as_json() for record in payload_records],
        },
        description="Hashes, counts per zone, the reading rules, and every anomaly found.",
    )

    crate = build_crate(
        records=writer.records,
        generated_at=stamp,
        release=release,
        digest=digest,
        n_inferred=sum(table.by_zone.get(Zone.INFERRED.value, 0) for table in tables),
    )
    writer.json_file(
        "ro-crate-metadata.json",
        crate,
        description="RO-Crate metadata descriptor.",
    )

    return Bundle(
        root=out_dir,
        tables=tuple(tables),
        files=tuple(writer.records),
        anomalies=tuple(anomalies),
        digest=digest,
        generated_at=stamp,
        release=release,
    )
