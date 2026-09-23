"""The Strain read: lineage, genotype, modifications, and phenotype faceted by condition class.

PLAN.md P.2 names two things this page must get right -- *"the lineage DAG and the condition-class
faceting of phenotype"* -- and the atlas currently holds nothing for the first and cannot compute
the second. Both facts are returned as data rather than left for the interface to discover:

* **`strain_lineage` has zero rows.** So :class:`LineageRead` carries ``is_recorded: False`` and a
  sentence saying what that does and does not mean. "No lineage is recorded in this atlas" and
  "this strain has no parents" are opposite claims about an engineered strain -- JWY03 is a
  derivative of JWY0 by construction -- and an empty graph rendered without that sentence asserts
  the second one.
* **No measurement reaches a condition context** (`sample_id` is NULL in all 105 rows), so every
  phenotype group comes back in the single ``unclassified`` class with the join that is missing
  named on it. The faceting is still done by :mod:`fermdb.query.conditions`, so the day a curator
  attaches a measurement to a sample the page starts faceting without a code change.

Tolerance is the other place where the honest answer is structural. There is no tolerance table:
the only recorded tolerance figure in `schema.sql` is `chassis_profile.isobutanol_tolerance_g_l`,
a column named after one product, and no `chassis_profile` row is bound to a `strain`. So the
tolerance profile is read from there, reports zero rows for every strain, and says which of those
two reasons it is.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Page, Select
from fermdb.query.conditions import ComparabilityClass, classes_for_samples, no_context_class
from fermdb.query.records import MeasurementRead, list_measurements
from fermdb.query.values import Absence, Value, from_text_column

__all__ = [
    "LineageRead",
    "ModificationRead",
    "PhenotypeGroup",
    "StrainRead",
    "StrainRow",
    "list_strains",
    "read_strain",
]

#: How many measurements one strain page will fetch. Generous against a 105-row table, and a
#: ceiling rather than a promise -- the payload reports its own truncation either way.
MEASUREMENT_LIMIT = 200


@dataclass(frozen=True)
class StrainRow:
    """One strain in a list, with the counts that say whether opening it is worth it."""

    id: str
    canonical_name: str
    organism_id: Value[str]
    organism_name: Value[str]
    strain_class: Value[str]
    confidence: Value[str]
    zone: Value[str]
    measurements: int
    modifications: int
    samples: int
    has_genotype: bool
    has_lineage: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "organism_id": self.organism_id.as_json(),
            "organism_name": self.organism_name.as_json(),
            "strain_class": self.strain_class.as_json(),
            "confidence": self.confidence.as_json(),
            "zone": self.zone.as_json(),
            "measurements": self.measurements,
            "modifications": self.modifications,
            "samples": self.samples,
            "has_genotype": self.has_genotype,
            "has_lineage": self.has_lineage,
        }


@dataclass(frozen=True)
class LineageRead:
    """The lineage DAG around one strain, or a statement that none is recorded.

    ``is_recorded`` is the field that matters. It is False for every strain in the atlas today,
    and the note beside it exists so no interface can render an empty box that reads as "this
    strain has no parents".
    """

    parents: tuple[dict[str, Any], ...]
    children: tuple[dict[str, Any], ...]
    rows_in_atlas: int

    @property
    def is_recorded(self) -> bool:
        return bool(self.parents or self.children)

    @property
    def note(self) -> str:
        if self.is_recorded:
            return (
                f"{len(self.parents)} parent(s) and {len(self.children)} child(ren) recorded as "
                "`strain_lineage` edges"
            )
        if self.rows_in_atlas == 0:
            return (
                "no lineage is recorded anywhere in this atlas -- `strain_lineage` has 0 rows. "
                "That is a statement about the atlas, not about the strain: an engineered strain "
                "has a parent by construction, and nobody has curated the edge"
            )
        return (
            f"no lineage edge names this strain, though `strain_lineage` holds "
            f"{self.rows_in_atlas} edge(s) for other strains"
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "parents": [dict(parent) for parent in self.parents],
            "children": [dict(child) for child in self.children],
            "is_recorded": self.is_recorded,
            "rows_in_atlas": self.rows_in_atlas,
            "note": self.note,
        }


@dataclass(frozen=True)
class ModificationRead:
    """One engineering step, with its subtype fields where the subtype tables carry any.

    `modification_localization_change.verification_method` is surfaced unconditionally because
    its schema default is 'none_reported' and a relocalization nobody verified is the failure
    mode the column exists to make visible -- a blank there reads as "fine".
    """

    id: str
    type: str
    target_locus: Value[str]
    target_gene_group_id: Value[str]
    source_organism_id: Value[str]
    details: Value[str]
    publication_id: Value[str]
    zone: Value[str]
    confidence: Value[str]
    subtype: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "target_locus": self.target_locus.as_json(),
            "target_gene_group_id": self.target_gene_group_id.as_json(),
            "source_organism_id": self.source_organism_id.as_json(),
            "details": self.details.as_json(),
            "publication_id": self.publication_id.as_json(),
            "zone": self.zone.as_json(),
            "confidence": self.confidence.as_json(),
            "subtype": self.subtype,
        }


@dataclass(frozen=True)
class PhenotypeGroup:
    """The measurements of one strain that fall in one comparability class.

    Nothing here is ranked. Ordering rows inside a group that is not `classified` would present
    an ordering as a finding, and PLAN.md I.2 is explicit that a titer alone means nothing.
    """

    klass: ComparabilityClass
    measurements: tuple[MeasurementRead, ...]

    @property
    def units(self) -> tuple[str, ...]:
        seen: list[str] = []
        for read in self.measurements:
            unit = read.quantity.unit_reported.display
            if unit not in seen:
                seen.append(unit)
        return tuple(seen)

    def as_json(self) -> dict[str, Any]:
        return {
            "class": self.klass.as_json(),
            "measurements": [read.as_json() for read in self.measurements],
            "count": len(self.measurements),
            "units": list(self.units),
            "is_rankable": self.klass.is_classified and len(self.units) == 1,
        }


@dataclass(frozen=True)
class StrainRead:
    """Everything the atlas holds about one strain, including the parts it does not hold."""

    id: str
    canonical_name: str
    organism_id: Value[str]
    organism_name: Value[str]
    strain_class: Value[str]
    zone: Value[str]
    evidence: Value[str]
    confidence: Value[str]
    aliases: tuple[dict[str, Any], ...]
    genotype: tuple[dict[str, Any], ...]
    lineage: LineageRead
    modifications: tuple[ModificationRead, ...]
    phenotype: tuple[PhenotypeGroup, ...]
    phenotype_truncated: bool
    tolerance: tuple[dict[str, Any], ...]
    tolerance_note: str
    samples: tuple[dict[str, Any], ...]
    transcriptome_note: str
    publications: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "organism_id": self.organism_id.as_json(),
            "organism_name": self.organism_name.as_json(),
            "strain_class": self.strain_class.as_json(),
            "zone": self.zone.as_json(),
            "evidence": self.evidence.as_json(),
            "confidence": self.confidence.as_json(),
            "aliases": [dict(alias) for alias in self.aliases],
            "genotype": [dict(row) for row in self.genotype],
            "lineage": self.lineage.as_json(),
            "modifications": [mod.as_json() for mod in self.modifications],
            "phenotype": [group.as_json() for group in self.phenotype],
            "phenotype_truncated": self.phenotype_truncated,
            "tolerance": [dict(row) for row in self.tolerance],
            "tolerance_note": self.tolerance_note,
            "samples": [dict(sample) for sample in self.samples],
            "transcriptome_note": self.transcriptome_note,
            "publications": list(self.publications),
        }


def _counts(
    conn: sqlite3.Connection, table: str, column: str, ids: Sequence[str]
) -> dict[str, int]:
    if not ids:
        return {}
    return {
        str(row["k"]): int(row["n"])
        for row in Select(table)
        .columns(f"{column} AS k", "COUNT(*) AS n")
        .where_in(column, list(ids))
        .group_by(column)
        .page(conn)
    }


def list_strains(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    strain_class: str | None = None,
    organism_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[tuple[StrainRow, ...], Page, dict[str, int]]:
    """A page of strains, their per-strain counts, and the class histogram over the whole atlas.

    The histogram is deliberately *not* narrowed by the filters: it is the denominator the page
    is a slice of, and narrowing it would make every filtered view look like the whole atlas.
    """
    select = Select("strain", alias="s").columns(
        "s.id AS id",
        "s.canonical_name AS canonical_name",
        "s.organism_id AS organism_id",
        "s.class AS strain_class",
        "s.zone AS zone",
        "s.confidence AS confidence",
        "o.name AS organism_name",
    )
    select = select.join("organism", "o.id = s.organism_id", alias="o")
    if q:
        select = select.where("s.canonical_name LIKE ?", f"%{q}%")
    if strain_class:
        select = select.where("s.class = ?", strain_class)
    if organism_id:
        select = select.where("s.organism_id = ?", organism_id)

    page = select.order_by("canonical_name", "id").page(conn, limit=limit, offset=offset)
    ids = [str(row["id"]) for row in page]

    measurements = _counts(conn, "measurement", "strain_id", ids)
    modifications = _counts(conn, "modification", "strain_id", ids)
    samples = _counts(conn, "sample", "strain_id", ids)
    genotypes = _counts(conn, "genotype", "strain_id", ids)
    parents = _counts(conn, "strain_lineage", "child_strain_id", ids)
    children = _counts(conn, "strain_lineage", "parent_strain_id", ids)

    rows = tuple(
        StrainRow(
            id=str(row["id"]),
            canonical_name=str(row["canonical_name"]),
            organism_id=from_text_column(row["organism_id"]),
            organism_name=from_text_column(row["organism_name"]),
            strain_class=from_text_column(row["strain_class"]),
            confidence=from_text_column(row["confidence"]),
            zone=from_text_column(row["zone"]),
            measurements=measurements.get(str(row["id"]), 0),
            modifications=modifications.get(str(row["id"]), 0),
            samples=samples.get(str(row["id"]), 0),
            has_genotype=genotypes.get(str(row["id"]), 0) > 0,
            has_lineage=(parents.get(str(row["id"]), 0) + children.get(str(row["id"]), 0)) > 0,
        )
        for row in page
    )

    by_class = {
        (str(row["k"]) if row["k"] is not None else "not recorded"): int(row["n"])
        for row in Select("strain")
        .columns("class AS k", "COUNT(*) AS n")
        .group_by("class")
        .page(conn)
    }
    return rows, page, by_class


def _resolve(conn: sqlite3.Connection, strain_id: str) -> str | None:
    """Accept an internal id, a canonical name or an alias.

    All three are how a person refers to a strain -- a paper says "CEN.PK113-7D", the atlas says
    `YAA:STRAIN:cen-pk113-7d` -- and a page reachable only by the third is reachable only by
    someone who already knows the atlas's identifiers.
    """
    for select in (
        Select("strain").columns("id").where("id = ?", strain_id),
        Select("strain").columns("id").where("canonical_name = ?", strain_id),
        Select("strain_alias").columns("strain_id AS id").where("alias = ?", strain_id),
    ):
        page = select.page(conn, limit=1)
        if page.rows:
            return str(page.rows[0]["id"])
    return None


def _lineage(conn: sqlite3.Connection, strain_id: str) -> LineageRead:
    def edges(column: str, other: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "strain_id": str(row[other]),
                "canonical_name": row["canonical_name"],
                "step_type": row["step_type"],
                "publication_id": row["publication_id"],
                "zone": row["zone"],
                "confidence": row["confidence"],
            }
            for row in Select("strain_lineage", alias="l")
            .columns(
                f"l.{other} AS {other}",
                "l.step_type AS step_type",
                "l.publication_id AS publication_id",
                "l.zone AS zone",
                "l.confidence AS confidence",
                "s.canonical_name AS canonical_name",
            )
            .join("strain", f"s.id = l.{other}", alias="s")
            .where(f"l.{column} = ?", strain_id)
            .page(conn)
        )

    total = int(
        Select("strain_lineage").columns("COUNT(*) AS n").scalar(conn) or 0,
    )
    return LineageRead(
        parents=edges("child_strain_id", "parent_strain_id"),
        children=edges("parent_strain_id", "child_strain_id"),
        rows_in_atlas=total,
    )


def _modifications(conn: sqlite3.Connection, strain_id: str) -> tuple[ModificationRead, ...]:
    rows = list(
        Select("modification")
        .columns(
            "id",
            "type",
            "target_locus",
            "target_gene_group_id",
            "source_organism_id",
            "details",
            "publication_id",
            "zone",
            "confidence",
        )
        .where("strain_id = ?", strain_id)
        .order_by("type", "id")
        .page(conn)
    )
    ids = [str(row["id"]) for row in rows]
    subtypes: dict[str, dict[str, Any]] = {}
    for table in ("modification_localization_change", "modification_mtdna_edit"):
        if not ids:
            break
        for row in Select(table).where_in("modification_id", ids).page(conn):
            subtypes[str(row["modification_id"])] = dict(row)

    return tuple(
        ModificationRead(
            id=str(row["id"]),
            type=str(row["type"]),
            target_locus=from_text_column(row["target_locus"]),
            target_gene_group_id=from_text_column(row["target_gene_group_id"]),
            source_organism_id=from_text_column(row["source_organism_id"]),
            details=from_text_column(row["details"]),
            publication_id=from_text_column(row["publication_id"]),
            zone=from_text_column(row["zone"]),
            confidence=from_text_column(row["confidence"]),
            subtype=subtypes.get(str(row["id"]), {}),
        )
        for row in rows
    )


def group_by_class(
    conn: sqlite3.Connection, reads: Sequence[MeasurementRead]
) -> tuple[PhenotypeGroup, ...]:
    """Measurements grouped by the comparability class of the sample each belongs to.

    A measurement with no sample gets its own group, not a silent place in someone else's: that
    is the whole of PLAN.md K.4's rule, and it is why this returns groups rather than a sorted
    list.
    """
    sample_ids = [read.sample_id.unwrap() for read in reads if read.sample_id.is_known]
    classes, _ = classes_for_samples(conn, sample_ids)
    orphan = no_context_class(
        "this measurement has no `sample_id`, so it cannot reach a condition context and has no "
        "comparability class (PLAN.md K.4)"
    )

    grouped: dict[str, list[MeasurementRead]] = {}
    keyed: dict[str, ComparabilityClass] = {}
    for read in reads:
        klass = classes.get(read.sample_id.unwrap(), orphan) if read.sample_id.is_known else orphan
        grouped.setdefault(klass.key, []).append(read)
        keyed.setdefault(klass.key, klass)

    # Classified groups first: they are the only ones inside which a comparison is defensible,
    # and burying them under a long unclassified list would hide the usable part of the answer.
    order = {"classified": 0, "provisional": 1, "unclassified": 2}
    return tuple(
        PhenotypeGroup(klass=keyed[key], measurements=tuple(grouped[key]))
        for key in sorted(grouped, key=lambda k: (order[keyed[k].status], k))
    )


def _tolerance(conn: sqlite3.Connection, strain_id: str) -> tuple[tuple[dict[str, Any], ...], str]:
    rows = tuple(
        dict(row)
        for row in Select("chassis_profile")
        .columns(
            "id",
            "name_as_reported",
            "isobutanol_tolerance_g_l",
            "isobutanol_tolerance_state",
            "tolerance_endpoint",
            "rho_status",
            "pdc_status",
            "is_selected",
        )
        .where("strain_id = ?", strain_id)
        .page(conn)
    )
    if rows:
        return rows, "tolerance as recorded on this strain's chassis profile"

    total = int(Select("chassis_profile").columns("COUNT(*) AS n").scalar(conn) or 0)
    return (
        (),
        (
            "no tolerance is recorded for this strain. There is no tolerance table in this "
            f"schema: the only stored tolerance figure is `chassis_profile."
            f"isobutanol_tolerance_g_l`, a column named after one product, and none of the "
            f"{total} chassis profile(s) in the atlas is bound to a `strain` row"
        ),
    )


def read_strain(conn: sqlite3.Connection, strain_id: str) -> StrainRead | None:
    """One strain, or None if no id, canonical name or alias resolves to one."""
    resolved = _resolve(conn, strain_id)
    if resolved is None:
        return None
    row = (
        Select("strain", alias="s")
        .columns(
            "s.id AS id",
            "s.canonical_name AS canonical_name",
            "s.organism_id AS organism_id",
            "s.class AS strain_class",
            "s.zone AS zone",
            "s.evidence AS evidence",
            "s.confidence AS confidence",
            "o.name AS organism_name",
        )
        .join("organism", "o.id = s.organism_id", alias="o")
        .where("s.id = ?", resolved)
        .one(conn)
    )
    if row is None:  # pragma: no cover - _resolve only returns ids that exist
        return None

    aliases = tuple(
        dict(alias)
        for alias in Select("strain_alias")
        .columns("alias", "source", "zone", "confidence")
        .where("strain_id = ?", resolved)
        .order_by("alias")
        .page(conn)
    )

    genotype: list[dict[str, Any]] = []
    for gene_row in (
        Select("genotype")
        .columns("id", "as_reported", "parsed_json", "zone", "confidence")
        .where("strain_id = ?", resolved)
        .page(conn)
    ):
        parsed: Any = None
        if gene_row["parsed_json"]:
            try:
                parsed = json.loads(str(gene_row["parsed_json"]))
            except json.JSONDecodeError:
                # A genotype whose parse is unreadable is still a genotype. Dropping the row
                # would hide the verbatim string, which is the part that is Zone R.
                parsed = None
        genotype.append(
            {
                "id": str(gene_row["id"]),
                "as_reported": str(gene_row["as_reported"]),
                "parsed": parsed,
                "zone": gene_row["zone"],
                "confidence": gene_row["confidence"],
            }
        )

    reads, page = list_measurements(conn, strain_id=resolved, limit=MEASUREMENT_LIMIT)
    modifications = _modifications(conn, resolved)
    tolerance, tolerance_note = _tolerance(conn, resolved)

    samples = tuple(
        dict(sample)
        for sample in Select("sample")
        .columns("id", "experiment_id", "dataset_id", "condition_context_id", "growth_phase")
        .where("strain_id = ?", resolved)
        .order_by("id")
        .page(conn, limit=200)
    )
    with_context = sum(1 for sample in samples if sample["condition_context_id"])
    transcriptome_note = (
        "no sample in the atlas names this strain, so nothing links it to a sequencing run"
        if not samples
        else (
            f"{len(samples)} sample(s) name this strain; {with_context} carry a condition "
            "context. Expression matrices are keyed by run, not by strain, so a per-strain "
            "expression profile is not yet a read this atlas can serve"
        )
    )

    publications = sorted(
        {read.publication_id.unwrap() for read in reads if read.publication_id.is_known}
        | {mod.publication_id.unwrap() for mod in modifications if mod.publication_id.is_known}
    )

    return StrainRead(
        id=str(row["id"]),
        canonical_name=str(row["canonical_name"]),
        organism_id=from_text_column(row["organism_id"]),
        organism_name=from_text_column(row["organism_name"]),
        strain_class=from_text_column(row["strain_class"]),
        zone=from_text_column(row["zone"]),
        evidence=(
            from_text_column(row["evidence"])
            if row["evidence"]
            else Value.absent(Absence.NOT_RECORDED)
        ),
        confidence=from_text_column(row["confidence"]),
        aliases=aliases,
        genotype=tuple(genotype),
        lineage=_lineage(conn, resolved),
        modifications=modifications,
        phenotype=group_by_class(conn, reads),
        phenotype_truncated=page.truncated,
        tolerance=tolerance,
        tolerance_note=tolerance_note,
        samples=samples,
        transcriptome_note=transcriptome_note,
        publications=tuple(publications),
    )
