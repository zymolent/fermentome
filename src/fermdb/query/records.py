"""The Data read: measurements, experiments, strains and products, with their quality flags.

The numbers a strain engineer actually wants are here, and so is the reason most of them cannot
yet be compared to each other. Four facts about the current measurement table shape everything
this module returns, and each one is surfaced rather than smoothed:

* **`quantity_kind` is not yet a controlled vocabulary.** 21 distinct values over 105 rows, of
  which `titer` (64) and `yield` (6) are the only ones used more than a handful of times. The
  rest are sentences -- "isobutanol concentration on SC agar permitting growth". Grouping by
  this column produces a chart with a long tail of n=1 categories, so the reader is told how
  many kinds are singletons instead of being shown them as if they were classes.
* **Units are mixed within a kind.** g/L, mg/L, % v/v, g/g and `unknown` all appear. A "best
  titer" ranking across them is arithmetic on incommensurable numbers.
* **No measurement is attached to a sample.** `sample_id` is NULL in all 105 rows, so no
  measurement can currently be joined to a condition context. That is precisely the join that
  comparability classes (PLAN.md K.4) are built on, so the atlas cannot yet say whether two
  numbers are comparable.
* **`derived_by` is NULL everywhere.** PLAN.md O.2 requires a reported yield to be
  distinguishable from one the atlas computed. Today nothing distinguishes them, so every yield
  is reported as ungraded on that axis rather than assumed to be primary.

`comparability_warnings` exists to carry these to the UI as data, so P.4's rendering rules have
something to render and the warnings cannot be lost by a redesign.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Page, Select
from fermdb.query.values import Absence, Quantity, Value, Zone

__all__ = [
    "DataOverview",
    "MeasurementRead",
    "list_measurements",
    "read_overview",
]

#: `quantity_kind` values used often enough to behave as classes. Everything else is a singleton
#: or near-singleton and is reported as "uncontrolled" rather than charted as a category.
CONTROLLED_KINDS: frozenset[str] = frozenset({"titer", "yield", "fold_increase"})


def _text(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value.absent(Absence.NOT_RECORDED)
    text = str(raw)
    if text == "NA":
        return Value.absent(Absence.NOT_APPLICABLE)
    if text == "unknown":
        return Value.absent(Absence.UNKNOWN)
    return Value.known(text, zone=zone)


def _float(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[float]:
    if raw is None:
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(float(raw), zone=zone)


@dataclass(frozen=True)
class MeasurementRead:
    """One measurement, carrying both the reported and the harmonized form.

    The `Quantity` keeps `value_as_reported` beside `value_si`: "2.09 g/L as the paper wrote it"
    and "2.09 g/L after our conversion" are different claims in different zones, and a view that
    shows only the second has dropped the source's own words.
    """

    id: str
    quantity_kind: str
    quantity: Quantity
    product_id: Value[str]
    strain_id: Value[str]
    experiment_id: Value[str]
    publication_id: Value[str]
    sample_id: Value[str]
    basis: Value[str]
    derived_by: Value[str]
    assay_method: Value[str]
    n_replicates: Value[float]
    source_locator: Value[str]
    flags: tuple[dict[str, Any], ...]

    @property
    def comparability_warnings(self) -> tuple[str, ...]:
        """Why this number may not be comparable to the one next to it."""
        warnings: list[str] = []
        if not self.sample_id.is_known:
            warnings.append(
                "no sample: this measurement is not attached to a condition context, so its "
                "comparability class cannot be computed"
            )
        if not self.derived_by.is_known and self.quantity_kind == "yield":
            warnings.append(
                "`derived_by` is not recorded, so a reported yield cannot be told apart from "
                "one the atlas computed from titer and substrate"
            )
        if self.quantity_kind not in CONTROLLED_KINDS:
            warnings.append(
                f"`{self.quantity_kind}` is free text, not a controlled quantity kind -- it "
                "cannot be grouped with other measurements"
            )
        for flag in self.flags:
            if flag.get("severity") == "quarantine":
                warnings.append(
                    f"quarantined: {flag.get('kind')} -- "
                    f"{flag.get('rationale') or 'no rationale recorded'}"
                )
        return tuple(warnings)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "quantity_kind": self.quantity_kind,
            "is_controlled_kind": self.quantity_kind in CONTROLLED_KINDS,
            "quantity": self.quantity.as_json(),
            "product_id": self.product_id.as_json(),
            "strain_id": self.strain_id.as_json(),
            "experiment_id": self.experiment_id.as_json(),
            "publication_id": self.publication_id.as_json(),
            "sample_id": self.sample_id.as_json(),
            "basis": self.basis.as_json(),
            "derived_by": self.derived_by.as_json(),
            "assay_method": self.assay_method.as_json(),
            "n_replicates": self.n_replicates.as_json(),
            "source_locator": self.source_locator.as_json(),
            "flags": list(self.flags),
            "comparability_warnings": list(self.comparability_warnings),
        }


@dataclass(frozen=True)
class DataOverview:
    """The Data landing payload."""

    measurements: int
    experiments: int
    strains: int
    products: int
    condition_contexts: int
    by_quantity_kind: dict[str, int]
    singleton_kinds: int
    by_unit: dict[str, int]
    by_product: dict[str, int]
    measurements_with_sample: int
    measurements_with_publication: int
    quality_flags: dict[str, int]
    quality_severity: dict[str, int]
    products_by_tier: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        controlled = {
            kind: count for kind, count in self.by_quantity_kind.items() if kind in CONTROLLED_KINDS
        }
        return {
            "measurements": self.measurements,
            "experiments": self.experiments,
            "strains": self.strains,
            "products": self.products,
            "condition_contexts": self.condition_contexts,
            "by_quantity_kind": controlled,
            "uncontrolled_kinds": len(self.by_quantity_kind) - len(controlled),
            "singleton_kinds": self.singleton_kinds,
            "quantity_kind_note": (
                f"{len(self.by_quantity_kind)} distinct values of `quantity_kind`, "
                f"{self.singleton_kinds} of them used exactly once -- this column is not yet a "
                "controlled vocabulary, so only the recurring kinds are charted"
            ),
            "by_unit": self.by_unit,
            "unit_note": (
                "units are mixed within a kind; a ranking across them would be arithmetic on "
                "incommensurable numbers"
            ),
            "by_product": self.by_product,
            "measurements_with_sample": self.measurements_with_sample,
            "measurements_with_publication": self.measurements_with_publication,
            "join_note": (
                "a measurement with no sample cannot reach a condition context, and so has no "
                "comparability class (PLAN.md K.4)"
            ),
            "quality_flags": self.quality_flags,
            "quality_severity": self.quality_severity,
            "products_by_tier": self.products_by_tier,
        }


def _counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        (str(row["k"]) if row["k"] is not None else "unrecorded"): int(row["n"])
        for row in Select(table)
        .columns(f"{column} AS k", "COUNT(*) AS n")
        .group_by(column)
        .page(conn)
    }


def _scalar_int(conn: sqlite3.Connection, select: Select) -> int:
    return int(select.scalar(conn) or 0)


def _flags_for(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Quality flags keyed by measurement id, fetched for a whole page at once."""
    if not ids:
        return {}
    flags: dict[str, list[dict[str, Any]]] = {}
    for row in (
        Select("data_quality_flag")
        .columns("target_id", "kind", "severity", "rationale", "status", "detector")
        .where("target_type = ?", "measurement")
        .where_in("target_id", ids)
        .page(conn)
    ):
        flags.setdefault(str(row["target_id"]), []).append(
            {
                "kind": row["kind"],
                "severity": row["severity"],
                "rationale": row["rationale"],
                "status": row["status"],
                "detector": row["detector"],
            }
        )
    return flags


def list_measurements(
    conn: sqlite3.Connection,
    *,
    product_id: str | None = None,
    strain_id: str | None = None,
    quantity_kind: str | None = None,
    publication_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[tuple[MeasurementRead, ...], Page]:
    """Measurements matching the given facets, with their quality flags attached.

    Returns the reads *and* the `Page`, so a caller can render the rows and still report whether
    it is looking at a page or a total.
    """
    select = Select("measurement").columns(
        "id",
        "quantity_kind",
        "product_id",
        "strain_id",
        "experiment_id",
        "publication_id",
        "sample_id",
        "value_as_reported",
        "unit_as_reported",
        "value_si",
        "unit_si",
        "is_below_lod",
        "is_upper_bound",
        "basis",
        "derived_by",
        "assay_method",
        "n_replicates",
        "source_locator",
    )
    if product_id:
        select = select.where("product_id = ?", product_id)
    if strain_id:
        select = select.where("strain_id = ?", strain_id)
    if quantity_kind:
        select = select.where("quantity_kind = ?", quantity_kind)
    if publication_id:
        select = select.where("publication_id = ?", publication_id)

    page = select.order_by("quantity_kind", "id").page(conn, limit=limit, offset=offset)
    flags = _flags_for(conn, [str(row["id"]) for row in page])

    reads = tuple(
        MeasurementRead(
            id=str(row["id"]),
            quantity_kind=str(row["quantity_kind"]),
            quantity=Quantity(
                reported=_float(row["value_as_reported"]),
                unit_reported=_text(row["unit_as_reported"]),
                si=_float(row["value_si"], zone=Zone.HARMONIZED),
                unit_si=_text(row["unit_si"], zone=Zone.HARMONIZED),
                is_below_lod=bool(row["is_below_lod"]),
                is_upper_bound=bool(row["is_upper_bound"]),
            ),
            product_id=_text(row["product_id"]),
            strain_id=_text(row["strain_id"]),
            experiment_id=_text(row["experiment_id"]),
            publication_id=_text(row["publication_id"]),
            sample_id=_text(row["sample_id"]),
            basis=_text(row["basis"]),
            derived_by=_text(row["derived_by"]),
            assay_method=_text(row["assay_method"]),
            n_replicates=_float(row["n_replicates"]),
            source_locator=_text(row["source_locator"]),
            flags=tuple(flags.get(str(row["id"]), ())),
        )
        for row in page
    )
    return reads, page


def read_overview(conn: sqlite3.Connection) -> DataOverview:
    """The Data page payload."""
    by_kind = _counts(conn, "measurement", "quantity_kind")
    return DataOverview(
        measurements=_scalar_int(conn, Select("measurement").columns("COUNT(*) AS n")),
        experiments=_scalar_int(conn, Select("experiment").columns("COUNT(*) AS n")),
        strains=_scalar_int(conn, Select("strain").columns("COUNT(*) AS n")),
        products=_scalar_int(conn, Select("product").columns("COUNT(*) AS n")),
        condition_contexts=_scalar_int(conn, Select("condition_context").columns("COUNT(*) AS n")),
        by_quantity_kind=by_kind,
        singleton_kinds=sum(1 for count in by_kind.values() if count == 1),
        by_unit=_counts(conn, "measurement", "unit_as_reported"),
        by_product=_counts(conn, "measurement", "product_id"),
        measurements_with_sample=_scalar_int(
            conn,
            Select("measurement").columns("COUNT(*) AS n").where("sample_id IS NOT NULL"),
        ),
        measurements_with_publication=_scalar_int(
            conn,
            Select("measurement").columns("COUNT(*) AS n").where("publication_id IS NOT NULL"),
        ),
        quality_flags=_counts(conn, "data_quality_flag", "kind"),
        quality_severity=_counts(conn, "data_quality_flag", "severity"),
        products_by_tier=_counts(conn, "product", "tier"),
    )
