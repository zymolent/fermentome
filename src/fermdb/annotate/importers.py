"""Importers: external functional-annotation sources -> `gene_annotation` rows.

Pattern, the same one `fermdb.literature.acquire` and `fermdb.omics` already use: a `parse_*`
function does no I/O at all and turns one source's own response shape into `GeneAnnotationRow`
values; a `fetch_*` function calls a pluggable `Transport` and hands the result to the matching
`parse_*`. Every test in `tests/test_annotate.py` exercises only the `parse_*` functions against
recorded fixtures under `tests/fixtures/annotate/`, and a `FakeTransport` for the handful of tests
that exercise `fetch_*` too -- this module's own `UrllibTransport` is the only thing that opens a
socket, and no test may reach it (the harness's binding rule: "tests must never touch the
network").

THE KEY DESIGN POINT (see `fermdb.annotate`'s package docstring for the full statement): every
function below IMPORTS what a source already curated. Nothing here recomputes a GO term, a KEGG
pathway membership, a Pfam domain hit, a cofactor, or a subcellular location from sequence --
`fermdb.annotate.predict_mitochondrial_presequence`/`annotate_fe_s_cluster` are the two,
deliberately-stubbed exceptions, because no source below provides either systematically.

Redistribution discipline: `kegg`, `tcdb` and `yeastract` are marked
`redistributable: false` in `data/annotation/annotation_sources.yaml`. Their parsers below store
the external identifier, a short label and a resolvable link -- never a copied-out reaction list,
pathway map, or bulk export. This is enforced by what each parser chooses to keep from a response,
not by a runtime check, because "redistributable" describes what fermdb does with the data, not a
property the response itself carries.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .sources import AnnotationSource, recommended_confidence_for_go_evidence, resolve_source_url

__all__ = [
    "AnnotationImportError",
    "AnnotationTransportError",
    "GeneAnnotationRow",
    "Transport",
    "UrllibTransport",
    "fetch_generic_term_list",
    "fetch_kegg_entry",
    "fetch_sgd_go",
    "fetch_uniprot_entry",
    "fetch_uniprot_goa",
    "find_gene_annotation",
    "parse_generic_term_list",
    "parse_kegg_flat_entry",
    "parse_sgd_go_response",
    "parse_uniprot_entry",
    "parse_uniprot_goa_response",
    "utcnow_iso",
    "write_gene_annotation",
    "write_gene_annotations",
]

_DEFAULT_USER_AGENT = "fermdb-annotate/0.1"
_KEGG_FIELD_WIDTH = 12
_EC_IN_BRACKETS_RE = re.compile(r"\[EC:([0-9.\-\s]+)\]")


class AnnotationImportError(RuntimeError):
    """A source's response could not be parsed into `GeneAnnotationRow`s."""


class AnnotationTransportError(RuntimeError):
    """A network call to an annotation source failed, timed out, or returned something unusable.

    Mirrors `fermdb.literature.acquire.TransportError`: never treated as a confident negative
    result by a caller, only as "could not check this time".
    """


class Transport(Protocol):
    """Everything an importer needs from the network, injectable so tests stay offline."""

    def get_json(self, url: str) -> Any:
        """Fetch `url` and return its parsed JSON body."""
        ...

    def get_text(self, url: str) -> str:
        """Fetch `url` and return its raw body as text (KEGG's flat-file format is not JSON)."""
        ...


class UrllibTransport:
    """The real `Transport`: nothing beyond `urllib.request` (CONVENTIONS.md prefers the stdlib).

    Tests must never reach this class -- inject a fake `Transport` instead.
    """

    def __init__(self, *, timeout: float = 20.0, user_agent: str = _DEFAULT_USER_AGENT) -> None:
        self._timeout = timeout
        self._user_agent = user_agent

    def get_json(self, url: str) -> Any:
        text = self.get_text(url)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnnotationTransportError(f"invalid JSON from {url}: {exc}") from exc

    def get_text(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self._user_agent, "Accept": "application/json, text/plain, */*"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                charset = response.headers.get_content_charset() or "utf-8"
                return str(response.read().decode(charset))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AnnotationTransportError(f"request to {url} failed: {exc}") from exc


def utcnow_iso() -> str:
    """The one place this package reads the wall clock, so a caller/test can hold it fixed."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class GeneAnnotationRow:
    """One `gene_annotation` row (src/fermdb/db/schema.sql, "functional annotation"), ready for a
    parameterized INSERT/UPDATE via `write_gene_annotation`.

    `evidence_code` is GO-only and `None` for every other source (the schema's own CHECK enforces
    this structurally). `reaction_id`/`pathway_id` are set only when `term_id` resolves to a row
    this atlas already curates internally in `reaction`/`pathway` -- left `None` for the
    overwhelming majority of rows, which point at the external source only.
    """

    gene_group_id: str
    source: str
    term_id: str
    term_label: str | None
    term_namespace: str | None
    evidence_code: str | None
    reaction_id: str | None
    pathway_id: str | None
    source_url: str | None
    source_version: str | None
    retrieved_at: str | None
    zone: str
    evidence: str
    confidence: str


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(entry: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if value:
            return str(value)
    return None


# ---------------------------------------------------------------------------------------------
# GO: sgd_go (yeast) and uniprot_goa (bacteria) -- same term/evidence-code model, different
# curator and response shape. See data/annotation/annotation_sources.yaml for both sources' field
# names, which are this session's unverified, background-knowledge reading of each API.
# ---------------------------------------------------------------------------------------------


def parse_sgd_go_response(
    payload: Any, *, gene_group_id: str, source: AnnotationSource, retrieved_at: str
) -> list[GeneAnnotationRow]:
    """Parse SGD's `go_details` response (a JSON list of annotation objects) into rows.

    Unknown or renamed fields are skipped defensively rather than guessed -- this session did not
    verify SGD's exact current field names against a live response (see the source registry's
    notes for `sgd_go`).
    """
    if not isinstance(payload, list):
        raise AnnotationImportError("SGD go_details response must be a JSON list")
    rows: list[GeneAnnotationRow] = []
    for raw_entry in payload:
        entry = _as_dict(raw_entry)
        go_id = _first_present(entry, "goid", "go_id")
        if go_id is None:
            continue
        evidence_code = _first_present(entry, "annotation_type", "evidence_code")
        evidence_code = evidence_code.upper() if evidence_code else None
        confidence = (
            recommended_confidence_for_go_evidence(evidence_code) if evidence_code else "unverified"
        )
        code_note = f" (evidence code {evidence_code})" if evidence_code else ""
        rows.append(
            GeneAnnotationRow(
                gene_group_id=gene_group_id,
                source=source.id,
                term_id=go_id,
                term_label=_first_present(entry, "go_term", "term"),
                term_namespace=_first_present(entry, "go_aspect", "aspect"),
                evidence_code=evidence_code,
                reaction_id=None,
                pathway_id=None,
                source_url=_first_present(entry, "locus_url", "url"),
                source_version=None,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, GO term {go_id} for gene_group {gene_group_id}{code_note}, "
                    f"fetched via {source.url_pattern} on {retrieved_at}"
                ),
                confidence=confidence,
            )
        )
    return rows


def fetch_sgd_go(
    transport: Transport, source: AnnotationSource, *, gene_group_id: str, systematic_name: str
) -> list[GeneAnnotationRow]:
    url = resolve_source_url(source, systematic_name=systematic_name)
    payload = transport.get_json(url)
    return parse_sgd_go_response(
        payload, gene_group_id=gene_group_id, source=source, retrieved_at=utcnow_iso()
    )


def parse_uniprot_goa_response(
    payload: Any, *, gene_group_id: str, source: AnnotationSource, retrieved_at: str
) -> list[GeneAnnotationRow]:
    """Parse a QuickGO `annotation/search` response (`{"results": [...]}`) into rows.

    Same evidence-code carry-through as `parse_sgd_go_response`; field names
    (`goId`/`goName`/`goAspect`/`evidenceCode`) are QuickGO's documented camelCase style, read
    from background knowledge and not re-verified against a live response (unverified).
    """
    document = _as_dict(payload)
    results = document.get("results")
    if not isinstance(results, list):
        raise AnnotationImportError("QuickGO annotation response missing a 'results' list")
    rows: list[GeneAnnotationRow] = []
    for raw_entry in results:
        entry = _as_dict(raw_entry)
        go_id = entry.get("goId")
        if not go_id:
            continue
        evidence_code_raw = entry.get("evidenceCode")
        evidence_code = str(evidence_code_raw).upper() if evidence_code_raw else None
        confidence = (
            recommended_confidence_for_go_evidence(evidence_code) if evidence_code else "unverified"
        )
        code_note = f" (evidence code {evidence_code})" if evidence_code else ""
        rows.append(
            GeneAnnotationRow(
                gene_group_id=gene_group_id,
                source=source.id,
                term_id=str(go_id),
                term_label=entry.get("goName"),
                term_namespace=entry.get("goAspect"),
                evidence_code=evidence_code,
                reaction_id=None,
                pathway_id=None,
                source_url=None,
                source_version=None,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, GO term {go_id} for gene_group {gene_group_id}{code_note}, "
                    f"fetched via QuickGO on {retrieved_at}"
                ),
                confidence=confidence,
            )
        )
    return rows


def fetch_uniprot_goa(
    transport: Transport, source: AnnotationSource, *, gene_group_id: str, uniprot_accession: str
) -> list[GeneAnnotationRow]:
    url = resolve_source_url(source, uniprot_accession=uniprot_accession)
    payload = transport.get_json(url)
    return parse_uniprot_goa_response(
        payload, gene_group_id=gene_group_id, source=source, retrieved_at=utcnow_iso()
    )


# ---------------------------------------------------------------------------------------------
# KEGG: pathway/KO/EC. Flat-file text, not JSON -- and redistributable: false, so this parser
# keeps only identifiers, a short label and a link (see the module and yaml docstrings).
# ---------------------------------------------------------------------------------------------


def parse_kegg_flat_entry(
    text: str, *, gene_group_id: str, source: AnnotationSource, retrieved_at: str
) -> list[GeneAnnotationRow]:
    """Parse one KEGG `get` flat-file entry (terminated by a bare `///` line) into rows.

    One row for the KO/gene entry itself, one per EC number named in its DEFINITION, and one per
    PATHWAY line. `data/annotation/annotation_sources.yaml`'s `kegg` entry explains why this
    parser never keeps more than that (identifiers and links only, never a reaction list or
    pathway map). This session's reading of KEGG's flat-file layout is unverified against a live
    response; `tests/fixtures/annotate/kegg_k01687.txt` is a hand-built fixture, not a captured one.
    """
    fields: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        if raw_line.strip() == "///":
            break
        if not raw_line.strip():
            continue
        prefix = raw_line[:_KEGG_FIELD_WIDTH]
        rest = raw_line[_KEGG_FIELD_WIDTH:].strip()
        if prefix.strip():
            current_key = prefix.strip()
            fields.setdefault(current_key, []).append(rest)
        elif current_key is not None:
            fields[current_key].append(rest)
        else:
            raise AnnotationImportError(
                f"KEGG flat entry: continuation line before any field: {raw_line!r}"
            )

    entry_lines = fields.get("ENTRY")
    if not entry_lines or not entry_lines[0].split():
        raise AnnotationImportError("KEGG flat entry has no usable ENTRY field")
    kegg_id = entry_lines[0].split()[0]
    entry_url = resolve_source_url(source, kegg_id=kegg_id)

    rows: list[GeneAnnotationRow] = []

    name_lines = fields.get("NAME")
    name_label = name_lines[0].rstrip(",").strip() if name_lines else None
    rows.append(
        GeneAnnotationRow(
            gene_group_id=gene_group_id,
            source=source.id,
            term_id=kegg_id,
            term_label=name_label,
            term_namespace="ko",
            evidence_code=None,
            reaction_id=None,
            pathway_id=None,
            source_url=entry_url,
            source_version=None,
            retrieved_at=retrieved_at,
            zone="R",
            evidence=(
                f"{source.name}, KEGG entry {kegg_id}, fetched via {source.url_pattern} on "
                f"{retrieved_at}"
            ),
            confidence="high",
        )
    )

    definition_text = " ".join(fields.get("DEFINITION", []))
    for match in _EC_IN_BRACKETS_RE.finditer(definition_text):
        for ec in match.group(1).split():
            rows.append(
                GeneAnnotationRow(
                    gene_group_id=gene_group_id,
                    source=source.id,
                    term_id=f"EC:{ec}",
                    term_label=None,
                    term_namespace="ec",
                    evidence_code=None,
                    reaction_id=None,
                    pathway_id=None,
                    source_url=entry_url,
                    source_version=None,
                    retrieved_at=retrieved_at,
                    zone="R",
                    evidence=(
                        f"{source.name}, EC {ec} named in KEGG entry {kegg_id}'s DEFINITION, "
                        f"fetched on {retrieved_at}"
                    ),
                    confidence="high",
                )
            )

    for pathway_line in fields.get("PATHWAY", []):
        parts = pathway_line.split(None, 1)
        if not parts:
            continue
        pathway_kegg_id = parts[0]
        pathway_label = parts[1] if len(parts) > 1 else None
        rows.append(
            GeneAnnotationRow(
                gene_group_id=gene_group_id,
                source=source.id,
                term_id=pathway_kegg_id,
                term_label=pathway_label,
                term_namespace="pathway",
                evidence_code=None,
                reaction_id=None,
                pathway_id=None,
                source_url=f"https://www.kegg.jp/pathway/{pathway_kegg_id}",
                source_version=None,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, pathway {pathway_kegg_id} named in KEGG entry {kegg_id}'s "
                    f"PATHWAY field, fetched on {retrieved_at}"
                ),
                confidence="high",
            )
        )
    return rows


def fetch_kegg_entry(
    transport: Transport, source: AnnotationSource, *, gene_group_id: str, kegg_id: str
) -> list[GeneAnnotationRow]:
    url = resolve_source_url(source, kegg_id=kegg_id)
    text = transport.get_text(url)
    return parse_kegg_flat_entry(
        text, gene_group_id=gene_group_id, source=source, retrieved_at=utcnow_iso()
    )


# ---------------------------------------------------------------------------------------------
# UniProt: cofactor specificity and subcellular location (docs/design/DUET_TARGET.md sections 2
# and 7: the Ilv5-NADPH / Ehrlich-ADH-NADH cofactor mismatch, and where a product already sits).
# ---------------------------------------------------------------------------------------------


def parse_uniprot_entry(
    payload: Any, *, gene_group_id: str, source: AnnotationSource, retrieved_at: str
) -> list[GeneAnnotationRow]:
    """Parse a UniProtKB entry's `comments` array for `COFACTOR` and `SUBCELLULAR LOCATION`.

    Field names (`commentType`, `cofactors[].name`/`cofactorCrossReference`,
    `subcellularLocations[].location.value`) are this session's unverified reading of UniProt's
    current REST JSON shape (see the source registry's notes for `uniprot`).
    """
    document = _as_dict(payload)
    rows: list[GeneAnnotationRow] = []
    for raw_comment in _as_list(document.get("comments")):
        comment = _as_dict(raw_comment)
        comment_type = comment.get("commentType")

        if comment_type == "COFACTOR":
            for raw_cofactor in _as_list(comment.get("cofactors")):
                cofactor = _as_dict(raw_cofactor)
                name = cofactor.get("name")
                xref = _as_dict(cofactor.get("cofactorCrossReference"))
                term_id = xref.get("id") or name
                if not term_id:
                    continue
                rows.append(
                    GeneAnnotationRow(
                        gene_group_id=gene_group_id,
                        source=source.id,
                        term_id=str(term_id),
                        term_label=str(name) if name else None,
                        term_namespace="cofactor",
                        evidence_code=None,
                        reaction_id=None,
                        pathway_id=None,
                        source_url=None,
                        source_version=None,
                        retrieved_at=retrieved_at,
                        zone="R",
                        evidence=(
                            f"{source.name}, cofactor {name!r} for gene_group {gene_group_id}, "
                            f"fetched on {retrieved_at}"
                        ),
                        confidence="high",
                    )
                )

        elif comment_type == "SUBCELLULAR LOCATION":
            for raw_location in _as_list(comment.get("subcellularLocations")):
                location_entry = _as_dict(raw_location)
                location = _as_dict(location_entry.get("location"))
                value = location.get("value")
                if not value:
                    continue
                rows.append(
                    GeneAnnotationRow(
                        gene_group_id=gene_group_id,
                        source=source.id,
                        term_id=str(value),
                        term_label=str(value),
                        term_namespace="subcellular_location",
                        evidence_code=None,
                        reaction_id=None,
                        pathway_id=None,
                        source_url=None,
                        source_version=None,
                        retrieved_at=retrieved_at,
                        zone="R",
                        evidence=(
                            f"{source.name}, subcellular location {value!r} for gene_group "
                            f"{gene_group_id}, fetched on {retrieved_at}"
                        ),
                        confidence="high",
                    )
                )
    return rows


def fetch_uniprot_entry(
    transport: Transport, source: AnnotationSource, *, gene_group_id: str, uniprot_accession: str
) -> list[GeneAnnotationRow]:
    url = resolve_source_url(source, uniprot_accession=uniprot_accession)
    payload = transport.get_json(url)
    return parse_uniprot_entry(
        payload, gene_group_id=gene_group_id, source=source, retrieved_at=utcnow_iso()
    )


# ---------------------------------------------------------------------------------------------
# Generic (id, label) term list -- pfam, interpro, tcdb, complex_portal, sgd_phenotype and
# yeastract all reduce to this shape for this build (see each source's notes in
# data/annotation/annotation_sources.yaml for why, and for the caveat that a production
# integration should confirm each one's exact field names against a live response first).
# ---------------------------------------------------------------------------------------------


def parse_generic_term_list(
    payload: Any,
    *,
    gene_group_id: str,
    source: AnnotationSource,
    retrieved_at: str,
    id_key: str = "id",
    label_key: str = "label",
    namespace: str | None = None,
) -> list[GeneAnnotationRow]:
    """Parse a bare JSON list of `{id_key: ..., label_key: ...}` objects, or an object with a
    top-level `results` list of the same shape, into rows."""
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    else:
        results = _as_dict(payload).get("results")
        if not isinstance(results, list):
            raise AnnotationImportError(
                f"{source.id} response must be a JSON list, or an object with a 'results' list"
            )
        items = results

    rows: list[GeneAnnotationRow] = []
    for raw_entry in items:
        entry = _as_dict(raw_entry)
        term_id = entry.get(id_key)
        if not term_id:
            continue
        term_label = entry.get(label_key)
        rows.append(
            GeneAnnotationRow(
                gene_group_id=gene_group_id,
                source=source.id,
                term_id=str(term_id),
                term_label=str(term_label) if term_label else None,
                term_namespace=namespace,
                evidence_code=None,
                reaction_id=None,
                pathway_id=None,
                source_url=None,
                source_version=None,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, term {term_id} for gene_group {gene_group_id}, fetched on "
                    f"{retrieved_at}"
                ),
                confidence="high",
            )
        )
    return rows


def fetch_generic_term_list(
    transport: Transport,
    source: AnnotationSource,
    *,
    gene_group_id: str,
    url_fields: Mapping[str, str],
    id_key: str = "id",
    label_key: str = "label",
    namespace: str | None = None,
) -> list[GeneAnnotationRow]:
    url = resolve_source_url(source, **dict(url_fields))
    payload = transport.get_json(url)
    return parse_generic_term_list(
        payload,
        gene_group_id=gene_group_id,
        source=source,
        retrieved_at=utcnow_iso(),
        id_key=id_key,
        label_key=label_key,
        namespace=namespace,
    )


# ---------------------------------------------------------------------------------------------
# Database: idempotent find-or-write, the same shape as
# fermdb.literature.acquire.find_fulltext_asset / write_fulltext_asset.
# ---------------------------------------------------------------------------------------------

_GENE_ANNOTATION_COLUMNS: tuple[str, ...] = (
    "gene_group_id",
    "source",
    "term_id",
    "term_label",
    "term_namespace",
    "evidence_code",
    "reaction_id",
    "pathway_id",
    "source_url",
    "source_version",
    "retrieved_at",
    "zone",
    "evidence",
    "confidence",
)


def find_gene_annotation(
    conn: sqlite3.Connection,
    *,
    gene_group_id: str,
    source: str,
    term_id: str,
    evidence_code: str | None,
) -> sqlite3.Row | None:
    """The existing `gene_annotation` row for this natural key, if any.

    `evidence_code IS ?` (not `=`) so that two GO-less sources both naming `evidence_code = NULL`
    are correctly matched as the same row -- SQLite's `IS` is the NULL-safe comparison operator,
    where `=` would never match a NULL against a NULL.
    """
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM gene_annotation WHERE gene_group_id = ? AND source = ? AND term_id = ? "
        "AND evidence_code IS ?",
        (gene_group_id, source, term_id, evidence_code),
    ).fetchone()
    return row


def write_gene_annotation(conn: sqlite3.Connection, row: GeneAnnotationRow) -> str:
    """Insert a new `gene_annotation` row, or update the existing one in place. Returns its id.

    Idempotent on `(gene_group_id, source, term_id, evidence_code)`
    (docs/reference/CONVENTIONS.md "Pipelines and provenance": every pipeline is idempotent on a
    declared key) -- re-running an importer refreshes the row rather than duplicating it. Does not
    commit or close `conn`; `write_gene_annotations` below commits once for a whole batch.
    """
    existing = find_gene_annotation(
        conn,
        gene_group_id=row.gene_group_id,
        source=row.source,
        term_id=row.term_id,
        evidence_code=row.evidence_code,
    )
    values: dict[str, Any] = {column: getattr(row, column) for column in _GENE_ANNOTATION_COLUMNS}

    if existing is not None:
        assignments = ", ".join(f"{column} = :{column}" for column in _GENE_ANNOTATION_COLUMNS)
        conn.execute(
            f"UPDATE gene_annotation SET {assignments} WHERE id = :id",
            {**values, "id": existing["id"]},
        )
        return str(existing["id"])

    new_id = f"YAA:ANNOT:{uuid.uuid4().hex}"
    columns = ("id", *_GENE_ANNOTATION_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in columns)
    conn.execute(
        f"INSERT INTO gene_annotation ({', '.join(columns)}) VALUES ({placeholders})",
        {**values, "id": new_id},
    )
    return new_id


def write_gene_annotations(conn: sqlite3.Connection, rows: Sequence[GeneAnnotationRow]) -> int:
    """`write_gene_annotation` for every row in `rows`, committing once at the end."""
    for row in rows:
        write_gene_annotation(conn, row)
    conn.commit()
    return len(rows)
