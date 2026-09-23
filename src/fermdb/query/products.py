"""The Product read: pathways, strategies, tolerance, and measurements faceted by class.

PLAN.md P.2 names the thing this page must get right: *"The class-faceted comparison, never a
global leaderboard."* PLAN.md I.2 says why -- the atlas **refuses to produce a global "best
strain" leaderboard**, because that number would be read as meaningful and would not be.

So this module never returns a ranked list of measurements. It returns
:class:`ClassFacetedMeasurements` groups, one per comparability class, and a group offers a
"best" only when :attr:`ClassFacetedMeasurements.is_rankable` -- which requires all four of:

1. the class is ``classified`` (every class-defining facet readable, none merely provisional),
2. every row in the group shares one unit as reported,
3. the quantity kind is one of `records.CONTROLLED_KINDS`, and
4. there is more than one row, because "the best of one" is a value with a superlative attached.

Against the atlas as it stands, no group passes (1): no measurement carries a `sample_id`, so
every one of them lands in the single ``unclassified`` group with the missing join named. The
group still renders, with its rows in a stable id order and `refusal_reason` set. Ordering them
by magnitude would present an ordering as a finding.

**Tolerance is a structural gap and is reported as one.** The schema has no tolerance table. The
only stored tolerance figure is `chassis_profile.isobutanol_tolerance_g_l` -- a column named
after a single product -- so for every product but isobutanol there is nowhere to record it at
all, and for isobutanol both rows have the value unrecorded. That is returned as
:attr:`ProductRead.tolerance_note` rather than as an empty panel.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Select
from fermdb.query.conditions import ComparabilityClass, classes_for_samples, no_context_class
from fermdb.query.records import CONTROLLED_KINDS, MeasurementRead, list_measurements
from fermdb.query.values import Absence, Value, from_state_column, from_text_column

__all__ = [
    "ClassFacetedMeasurements",
    "ProductRead",
    "ProductRow",
    "facet_by_class",
    "list_products",
    "read_product",
]

#: The one product for which `chassis_profile` has a tolerance column. Named here so that the
#: gap for every other product is a stated fact rather than a silently empty panel.
TOLERANCE_COLUMN_PRODUCT = "YAA:PRODUCT:isobutanol"


@dataclass(frozen=True)
class ProductRow:
    """One product in a list, with the counts that say what is behind it."""

    id: str
    name: str
    tier: Value[str]
    canonical_unit: Value[str]
    measurements: int
    strains: int
    configurations: int
    theoretical_yields: int

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier.as_json(),
            "canonical_unit": self.canonical_unit.as_json(),
            "measurements": self.measurements,
            "strains": self.strains,
            "configurations": self.configurations,
            "theoretical_yields": self.theoretical_yields,
        }


@dataclass(frozen=True)
class ClassFacetedMeasurements:
    """One comparability class's measurements, and whether a "best" may be named inside it.

    `best` is a mapping from ``"<quantity_kind> (<unit>)"`` to the top row, and it is empty
    whenever :attr:`is_rankable` is False. It is a mapping keyed by kind *and unit* rather than
    a single number because 2.09 g/L and 3,120 mg/L are not two candidates for one superlative.
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

    @property
    def kinds(self) -> tuple[str, ...]:
        seen: list[str] = []
        for read in self.measurements:
            if read.quantity_kind not in seen:
                seen.append(read.quantity_kind)
        return tuple(seen)

    @property
    def is_rankable(self) -> bool:
        return (
            self.klass.is_classified
            and len(self.units) == 1
            and len(self.measurements) > 1
            and all(read.quantity_kind in CONTROLLED_KINDS for read in self.measurements)
        )

    @property
    def refusal_reason(self) -> str | None:
        """Why no best is named here. None when one is."""
        if self.is_rankable:
            return None
        if not self.klass.is_classified:
            if self.klass.status == "provisional":
                return (
                    "this class is provisional: "
                    + "; ".join(self.klass.blind_to)
                    + ". Two measurements can share this key and still differ on a facet the "
                    "key cannot see, so a best within it would be a comparison the atlas "
                    "cannot defend"
                )
            return (
                "these measurements have no comparability class, so no best can be named among "
                "them: " + "; ".join(self.klass.blocked_by)
            )
        if len(self.units) > 1:
            return (
                "units differ within this class ("
                + ", ".join(self.units)
                + "), and a ranking across them would be arithmetic on incommensurable numbers"
            )
        if len(self.measurements) == 1:
            return "one measurement: the best of one is that one, and the superlative adds nothing"
        return (
            "at least one row has a free-text `quantity_kind`, which cannot be grouped with "
            "another measurement"
        )

    @property
    def best(self) -> dict[str, MeasurementRead]:
        if not self.is_rankable:
            return {}
        top: dict[str, MeasurementRead] = {}
        for read in self.measurements:
            if not read.quantity.reported.is_known:
                continue
            key = f"{read.quantity_kind} ({read.quantity.unit_reported.display})"
            current = top.get(key)
            if current is None or read.quantity.reported.unwrap() > (
                current.quantity.reported.unwrap()
            ):
                top[key] = read
        return top

    def as_json(self) -> dict[str, Any]:
        return {
            "class": self.klass.as_json(),
            "measurements": [read.as_json() for read in self.measurements],
            "count": len(self.measurements),
            "units": list(self.units),
            "kinds": list(self.kinds),
            "is_rankable": self.is_rankable,
            "refusal_reason": self.refusal_reason,
            "best": {key: read.as_json() for key, read in self.best.items()},
        }


@dataclass(frozen=True)
class ProductRead:
    """Everything for one product, with every refusal it implies carried as data."""

    id: str
    name: str
    tier: Value[str]
    mw_g_mol: Value[float]
    formula: Value[str]
    inchikey: Value[str]
    chebi_id: Value[str]
    carbon_number: Value[float]
    canonical_unit: Value[str]
    zone: Value[str]
    confidence: Value[str]
    theoretical_yields: tuple[dict[str, Any], ...]
    pathways: tuple[dict[str, Any], ...]
    pathway_note: str
    configurations: tuple[dict[str, Any], ...]
    classes: tuple[ClassFacetedMeasurements, ...]
    measurements_truncated: bool
    tolerance: tuple[dict[str, Any], ...]
    tolerance_note: str
    strains: tuple[dict[str, Any], ...]
    leaderboard_refusal: str

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier.as_json(),
            "mw_g_mol": self.mw_g_mol.as_json(),
            "formula": self.formula.as_json(),
            "inchikey": self.inchikey.as_json(),
            "chebi_id": self.chebi_id.as_json(),
            "carbon_number": self.carbon_number.as_json(),
            "canonical_unit": self.canonical_unit.as_json(),
            "zone": self.zone.as_json(),
            "confidence": self.confidence.as_json(),
            "theoretical_yields": [dict(row) for row in self.theoretical_yields],
            "pathways": [dict(row) for row in self.pathways],
            "pathway_note": self.pathway_note,
            "configurations": [dict(row) for row in self.configurations],
            "classes": [group.as_json() for group in self.classes],
            "measurements_truncated": self.measurements_truncated,
            "tolerance": [dict(row) for row in self.tolerance],
            "tolerance_note": self.tolerance_note,
            "strains": [dict(row) for row in self.strains],
            "leaderboard_refusal": self.leaderboard_refusal,
        }


#: Returned on every product read. PLAN.md I.2's refusal, stated where a reader looking for a
#: ranking will actually meet it.
LEADERBOARD_REFUSAL = (
    "This page does not rank strains against each other. A titer is a statement about a strain "
    "*under conditions*, and the atlas offers a comparison only inside a comparability class "
    "(PLAN.md K.4) or with the differing facets named (PLAN.md I.2). A single ordered list "
    "across classes would be read as a finding and would not be one."
)


def list_products(conn: sqlite3.Connection) -> tuple[ProductRow, ...]:
    """Every product, with the counts that say which ones have anything behind them.

    Unpaged on purpose: `product` holds ten rows and is a controlled vocabulary of PLAN.md B.1's
    four tiers, not a growing table. Paging it would add a truncation story to a list that has
    none.
    """
    rows = list(
        Select("product")
        .columns("id", "name", "tier", "canonical_unit")
        .order_by("tier", "name")
        .page(conn)
    )

    measurements: dict[str, int] = {}
    strains: dict[str, int] = {}
    for row in (
        Select("measurement")
        .columns("product_id AS k", "COUNT(*) AS n", "COUNT(DISTINCT strain_id) AS s")
        .group_by("product_id")
        .page(conn)
    ):
        if row["k"] is None:
            continue
        measurements[str(row["k"])] = int(row["n"])
        strains[str(row["k"])] = int(row["s"])

    configurations = {
        str(row["k"]): int(row["n"])
        for row in Select("pathway_configuration")
        .columns("product_id AS k", "COUNT(*) AS n")
        .group_by("product_id")
        .page(conn)
        if row["k"] is not None
    }
    yields = {
        str(row["k"]): int(row["n"])
        for row in Select("product_theoretical_yield")
        .columns("product_id AS k", "COUNT(*) AS n")
        .group_by("product_id")
        .page(conn)
    }

    return tuple(
        ProductRow(
            id=str(row["id"]),
            name=str(row["name"]),
            tier=from_text_column(row["tier"]),
            canonical_unit=from_text_column(row["canonical_unit"]),
            measurements=measurements.get(str(row["id"]), 0),
            strains=strains.get(str(row["id"]), 0),
            configurations=configurations.get(str(row["id"]), 0),
            theoretical_yields=yields.get(str(row["id"]), 0),
        )
        for row in rows
    )


def facet_by_class(
    conn: sqlite3.Connection, reads: Sequence[MeasurementRead]
) -> tuple[ClassFacetedMeasurements, ...]:
    """Group measurements by the comparability class of the sample each one belongs to."""
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

    order = {"classified": 0, "provisional": 1, "unclassified": 2}
    return tuple(
        ClassFacetedMeasurements(klass=keyed[key], measurements=tuple(grouped[key]))
        for key in sorted(grouped, key=lambda k: (order[keyed[k].status], k))
    )


def _pathways(conn: sqlite3.Connection, product_id: str) -> tuple[tuple[dict[str, Any], ...], str]:
    """Pathways for this product, from the two places the schema records the link.

    `pathway.product_id` is the direct link and is NULL for both curated pathways;
    `pathway_configuration.product_id` names the product and is populated. Reading only the first
    would report "no pathway" for isobutanol, which has one.
    """
    direct = {
        str(row["id"]): dict(row)
        for row in Select("pathway")
        .columns("id", "name", "product_id", "zone", "confidence")
        .where("product_id = ?", product_id)
        .page(conn)
    }

    via_configuration_ids = sorted(
        {
            str(row["pathway_id"])
            for row in Select("pathway_configuration")
            .columns("pathway_id")
            .where("product_id = ?", product_id)
            .page(conn)
            if row["pathway_id"]
        }
    )
    indirect: dict[str, dict[str, Any]] = {}
    if via_configuration_ids:
        for row in (
            Select("pathway")
            .columns("id", "name", "product_id", "zone", "confidence")
            .where_in("id", via_configuration_ids)
            .page(conn)
        ):
            indirect[str(row["id"])] = dict(row)

    merged: list[dict[str, Any]] = []
    for pathway_id in sorted(set(direct) | set(indirect)):
        entry: dict[str, Any] = dict(direct.get(pathway_id) or indirect[pathway_id])
        entry["linked_directly"] = pathway_id in direct
        entry["reactions"] = int(
            Select("pathway_reaction")
            .columns("COUNT(*) AS n")
            .where("pathway_id = ?", pathway_id)
            .scalar(conn)
            or 0
        )
        merged.append(entry)

    if not merged:
        note = "no pathway in the atlas names this product, directly or through a configuration"
    elif all(not entry["linked_directly"] for entry in merged):
        note = (
            f"{len(merged)} pathway(s) reach this product only through "
            "`pathway_configuration.product_id`; `pathway.product_id` is NULL for all of them, "
            "so a query against the direct column alone would report none"
        )
    else:
        note = f"{len(merged)} pathway(s) named for this product"
    return tuple(merged), note


def _tolerance(conn: sqlite3.Connection, product_id: str) -> tuple[tuple[dict[str, Any], ...], str]:
    if product_id != TOLERANCE_COLUMN_PRODUCT:
        total = int(Select("product").columns("COUNT(*) AS n").scalar(conn) or 0)
        return (
            (),
            (
                "there is nowhere in this schema to record tolerance to this product. The only "
                "stored tolerance figure is `chassis_profile.isobutanol_tolerance_g_l`, a column "
                f"named after one of the {total} products, so tolerance is storable for exactly "
                "one of them"
            ),
        )

    rows = tuple(
        {
            "id": str(row["id"]),
            "strain_id": row["strain_id"],
            "name_as_reported": row["name_as_reported"],
            "tolerance": from_state_column(
                None
                if row["isobutanol_tolerance_g_l"] is None
                else float(row["isobutanol_tolerance_g_l"]),
                row["isobutanol_tolerance_state"],
            ).as_json(),
            "tolerance_endpoint": from_text_column(row["tolerance_endpoint"]).as_json(),
            "is_selected": bool(row["is_selected"]),
        }
        for row in Select("chassis_profile")
        .columns(
            "id",
            "strain_id",
            "name_as_reported",
            "isobutanol_tolerance_g_l",
            "isobutanol_tolerance_state",
            "tolerance_endpoint",
            "is_selected",
        )
        .order_by("is_selected DESC", "id")
        .page(conn)
    )
    recorded = sum(1 for row in rows if "value" in row["tolerance"])
    if not rows:
        return rows, "no chassis profile exists, so no tolerance figure is recorded"
    return rows, (
        f"{recorded} of {len(rows)} chassis profile(s) record a tolerance. A profile with none "
        "is a gap, not a tolerance of zero"
    )


def read_product(conn: sqlite3.Connection, product_id: str) -> ProductRead | None:
    """One product, or None if neither its id nor its name resolves."""
    row = (
        Select("product")
        .columns(
            "id",
            "name",
            "tier",
            "mw_g_mol",
            "inchikey",
            "chebi_id",
            "formula",
            "carbon_number",
            "canonical_unit",
            "zone",
            "confidence",
        )
        .where("id = ?", product_id)
        .one(conn)
    )
    if row is None:
        by_name = Select("product").columns("id").where("name = ?", product_id).page(conn, limit=1)
        if not by_name.rows:
            return None
        return read_product(conn, str(by_name.rows[0]["id"]))

    resolved = str(row["id"])
    yields = tuple(
        {
            "substrate": str(y["substrate"]),
            "g_per_g": from_state_column(
                None if y["g_per_g"] is None else float(y["g_per_g"]), y["g_per_g_state"]
            ).as_json(),
            "mol_per_mol": from_state_column(
                None if y["mol_per_mol"] is None else float(y["mol_per_mol"]),
                y["mol_per_mol_state"],
            ).as_json(),
            "stoichiometry": from_text_column(y["stoichiometry"]).as_json(),
            "zone": y["zone"],
            "confidence": y["confidence"],
        }
        for y in Select("product_theoretical_yield")
        .columns(
            "substrate",
            "g_per_g",
            "g_per_g_state",
            "mol_per_mol",
            "mol_per_mol_state",
            "stoichiometry",
            "zone",
            "confidence",
        )
        .where("product_id = ?", resolved)
        .order_by("substrate")
        .page(conn)
    )

    configurations = tuple(
        dict(config)
        for config in Select("pathway_configuration", alias="c")
        .columns(
            "c.id AS id",
            "c.name AS name",
            "c.pathway_id AS pathway_id",
            "c.compartment_strategy_id AS compartment_strategy_id",
            "c.host_strain_id AS host_strain_id",
            "c.description AS description",
            "c.zone AS zone",
            "c.confidence AS confidence",
            "s.canonical_name AS host_strain_name",
        )
        .join("strain", "s.id = c.host_strain_id", alias="s")
        .where("c.product_id = ?", resolved)
        .order_by("id")
        .page(conn)
    )

    reads, page = list_measurements(conn, product_id=resolved, limit=300)
    pathways, pathway_note = _pathways(conn, resolved)
    tolerance, tolerance_note = _tolerance(conn, resolved)

    strain_ids = sorted({read.strain_id.unwrap() for read in reads if read.strain_id.is_known})
    strains = (
        tuple(
            dict(strain)
            for strain in Select("strain")
            .columns("id", "canonical_name", "class AS strain_class")
            .where_in("id", strain_ids)
            .order_by("canonical_name")
            .page(conn, limit=500)
        )
        if strain_ids
        else ()
    )

    carbon_number = row["carbon_number"]
    mw = row["mw_g_mol"]
    return ProductRead(
        id=resolved,
        name=str(row["name"]),
        tier=from_text_column(row["tier"]),
        mw_g_mol=(Value.known(float(mw)) if mw is not None else Value.absent(Absence.NOT_RECORDED)),
        formula=from_text_column(row["formula"]),
        inchikey=from_text_column(row["inchikey"]),
        chebi_id=from_text_column(row["chebi_id"]),
        carbon_number=(
            Value.known(float(carbon_number))
            if carbon_number is not None
            else Value.absent(Absence.NOT_RECORDED)
        ),
        canonical_unit=from_text_column(row["canonical_unit"]),
        zone=from_text_column(row["zone"]),
        confidence=from_text_column(row["confidence"]),
        theoretical_yields=yields,
        pathways=pathways,
        pathway_note=pathway_note,
        configurations=configurations,
        classes=facet_by_class(conn, reads),
        measurements_truncated=page.truncated,
        tolerance=tolerance,
        tolerance_note=tolerance_note,
        strains=strains,
        leaderboard_refusal=LEADERBOARD_REFUSAL,
    )
