"""The condition context in full, and the comparability class computed from it.

This module exists to serve two of PLAN.md P.2's requirements at once, because they are the same
read seen from two sides:

* the Experiment page's *"the condition context in full, with 'not recorded' visible"*, and
* the Product and Compare pages' comparability class (PLAN.md K.4, I.2).

**Every facet is returned, including the ones that are absent.** A context read that omitted its
empty columns would render as a short, tidy list and would be a lie by selection: the reason a
titer cannot be compared to the one beside it is precisely the columns nobody filled in. So
:class:`ConditionContextRead` always returns all 19 facets, each as a three-state `Value`, and a
count of how many were recorded.

**There is no `comparability_class` table.** K.4 specifies one -- id, name, `required_match[]`,
`tolerance[]`, `ignored[]`, version -- and `schema.sql` has never had it. So this module cannot
look a class definition up; it computes one from K.4's own worked example and says so in the
payload (:data:`DEFINITION_SOURCE`). Presenting an ad-hoc key as though it were a curated,
versioned class would be exactly the kind of borrowed authority K.4 exists to prevent.

That leaves classification with three outcomes rather than two, and the middle one is the honest
part:

``classified``
    Every class-defining facet is known.
``provisional``
    Every class-defining facet *that has a column* is known, but at least one of PLAN.md C.5's
    2026-09-20 class-defining facets has no column in `schema.sql` and no row in
    `condition_context_facet` -- so two contexts can share this key and still differ in, say,
    whether product was removed in situ. A key that cannot see a facet cannot separate on it.
``unclassified``
    A column-backed class-defining facet is not recorded, or there is no context at all.

Only ``classified`` supports a within-class comparison. ``provisional`` warns and names the facet
it is blind to. ``unclassified`` refuses. That is the whole of the Compare page's verdict logic,
computed here rather than in the interface, so a redesign cannot lose it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fermdb.query.builder import Select
from fermdb.query.values import Absence, Value, from_state_column, from_text_column

__all__ = [
    "CONTEXT_FACETS",
    "DEFINITION_SOURCE",
    "REQUIRED_MATCH",
    "TOLERANCE_MATCH",
    "UNMIGRATED_CLASS_FACETS",
    "ComparabilityClass",
    "ConditionContextRead",
    "ContextFacet",
    "FacetDifference",
    "FacetSpec",
    "class_of",
    "classes_for_samples",
    "context_differences",
    "no_context_class",
    "read_contexts",
]

#: What the computed class is derived from. Travels in every payload, because a reader is
#: entitled to know that this key is not a curated class definition.
DEFINITION_SOURCE: Final[str] = (
    "computed from PLAN.md K.4's worked example (`required_match` = aeration_class, "
    "feedstock_class, mode). This atlas has no `comparability_class` table, so the class is "
    "unversioned and no stored definition was consulted"
)


@dataclass(frozen=True)
class FacetSpec:
    """One column of `condition_context`, and how to read it.

    ``kind`` decides which of `values.py`'s readers applies: a plain text column honours the
    'NA'/'unknown' literals, a numeric column is paired with its `<col>_state` companion, and a
    flag is a three-state boolean that must not render as 0.
    """

    column: str
    label: str
    kind: str  # "text" | "number" | "flag"
    unit: str | None = None
    #: True where `condition_context` also stores the source's verbatim string for this facet.
    has_as_reported: bool = False


#: Every facet of a condition context, in the order a bench scientist would read them. All of
#: them are returned on every read; see the module docstring for why.
CONTEXT_FACETS: Final[tuple[FacetSpec, ...]] = (
    FacetSpec("medium_name", "medium", "text", has_as_reported=True),
    FacetSpec("medium_class", "medium class", "text", has_as_reported=True),
    FacetSpec("carbon_source_main", "carbon source", "text", has_as_reported=True),
    FacetSpec("total_sugar_g_l", "total sugar", "number", unit="g/L", has_as_reported=True),
    FacetSpec("feedstock_class", "feedstock class", "text", has_as_reported=True),
    FacetSpec("nitrogen_source", "nitrogen source", "text"),
    FacetSpec("aeration_class", "aeration", "text", has_as_reported=True),
    FacetSpec("vvm", "aeration rate", "number", unit="vvm", has_as_reported=True),
    FacetSpec("dissolved_oxygen_pct", "dissolved oxygen", "number", unit="%", has_as_reported=True),
    FacetSpec("mode", "mode", "text", has_as_reported=True),
    FacetSpec("dilution_rate", "dilution rate", "number", unit="1/h"),
    FacetSpec("temperature_c", "temperature", "number", unit="°C", has_as_reported=True),
    FacetSpec("ph", "pH", "number", has_as_reported=True),
    FacetSpec("ph_controlled", "pH controlled", "flag", has_as_reported=True),
    FacetSpec("vessel_type", "vessel", "text"),
    FacetSpec("working_volume_l", "working volume", "number", unit="L"),
    FacetSpec("scale_class", "scale", "text"),
    FacetSpec("time_h", "time", "number", unit="h"),
    FacetSpec("growth_phase", "growth phase", "text"),
)

#: K.4's `required_match[]`, as its own worked example states it. Two contexts agreeing on all
#: three (and on the C.5 facets below) are in the same class.
REQUIRED_MATCH: Final[tuple[str, ...]] = ("aeration_class", "feedstock_class", "mode")

#: K.4's `tolerance[]`: facets compared numerically, within a band, rather than for equality.
#: ``("column", band, "absolute" | "relative")``.
TOLERANCE_MATCH: Final[tuple[tuple[str, float, str], ...]] = (
    ("temperature_c", 2.0, "absolute"),
    ("ph", 0.3, "absolute"),
    ("total_sugar_g_l", 0.25, "relative"),
)

#: PLAN.md C.5's 2026-09-20 amendment makes three facets class-defining. ``aeration_class`` has a
#: column; these two have neither a column in `schema.sql` nor a row in
#: `data/vocabularies/condition_facets.tsv`. They are looked for in `condition_context_facet`
#: first -- a curator may have recorded one there -- and only reported as unavailable if absent.
UNMIGRATED_CLASS_FACETS: Final[Mapping[str, str]] = {
    "carbon_regime": (
        "PLAN.md C.5's 2026-09-20 amendment makes `carbon_regime` class-defining. It has no "
        "column in schema.sql and no vocabulary row, so a class key cannot separate on it"
    ),
    "in_situ_product_removal": (
        "PLAN.md C.5's 2026-09-20 amendment makes `in_situ_product_removal` class-defining, and "
        "PLAN.md I.2 names it as one of the facets a titer comparison must hold constant. It has "
        "no column in schema.sql, so a class key cannot separate on it"
    ),
}

#: Classification outcomes. See the module docstring.
CLASSIFIED: Final[str] = "classified"
PROVISIONAL: Final[str] = "provisional"
UNCLASSIFIED: Final[str] = "unclassified"


@dataclass(frozen=True)
class ContextFacet:
    """One facet with its parsed value, the source's own words, and whether it defines the class.

    ``as_reported`` is Zone R by definition and travels beside the parse rather than instead of
    it: "0.5 vvm" and the string the paper actually printed are different claims, and a curator
    checking a parse needs both.
    """

    facet: str
    label: str
    value: Value[Any]
    as_reported: Value[str]
    unit: str | None = None
    is_class_defining: bool = False

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "facet": self.facet,
            "label": self.label,
            "value": self.value.as_json(),
            "as_reported": self.as_reported.as_json(),
            "is_class_defining": self.is_class_defining,
        }
        if self.unit is not None:
            payload["unit"] = self.unit
        return payload


def _flag(raw: Any, state: Any, *, zone: str | None) -> Value[str]:
    """A three-state boolean, rendered as words.

    Not as 0/1. `ph_controlled` is 0 for "the paper says the pH ran uncontrolled" and absent for
    "the paper never said", and a column of zeroes and blanks makes those look like the same
    fact seen twice.
    """
    number = from_state_column(None if raw is None else float(raw), state, zone=zone)
    if not number.is_known:
        return Value.absent(number.absence or Absence.NOT_RECORDED, zone=number.zone)
    return Value.known("yes" if number.unwrap() else "no", zone=number.zone)


def _facet_from_row(spec: FacetSpec, row: Mapping[str, Any], zone: str | None) -> ContextFacet:
    value: Value[Any]
    if spec.kind == "text":
        value = from_text_column(row[spec.column], zone=zone)
    elif spec.kind == "flag":
        value = _flag(row[spec.column], row[f"{spec.column}_state"], zone=zone)
    else:
        raw = row[spec.column]
        value = from_state_column(
            None if raw is None else float(raw), row[f"{spec.column}_state"], zone=zone
        )
    as_reported: Value[str] = (
        from_text_column(row[f"{spec.column}_as_reported"], zone="R")
        if spec.has_as_reported
        else Value.absent(Absence.NOT_APPLICABLE)
    )
    return ContextFacet(
        facet=spec.column,
        label=spec.label,
        value=value,
        as_reported=as_reported,
        unit=spec.unit,
        is_class_defining=spec.column in REQUIRED_MATCH,
    )


@dataclass(frozen=True)
class ConditionContextRead:
    """One condition context, every facet of it, recorded or not."""

    id: str
    zone: Value[str]
    confidence: Value[str]
    completeness_score: Value[float]
    facets: tuple[ContextFacet, ...]
    #: Rows of `condition_context_facet`: the long tail with no first-class column.
    extra_facets: tuple[ContextFacet, ...]
    #: Class-defining facets with nowhere to live in this schema, and why that matters.
    unavailable_class_facets: Mapping[str, str]

    @property
    def recorded(self) -> int:
        return sum(1 for facet in self.facets if facet.value.is_known)

    @property
    def absent_by_kind(self) -> dict[str, int]:
        """How many facets are in each of the three absent states. Never summed together."""
        counts = {"not_recorded": 0, "not_applicable": 0, "unknown": 0}
        for facet in self.facets:
            if facet.value.absence is not None:
                counts[facet.value.absence.value] += 1
        return counts

    def facet(self, name: str) -> ContextFacet | None:
        for candidate in (*self.facets, *self.extra_facets):
            if candidate.facet == name:
                return candidate
        return None

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "zone": self.zone.as_json(),
            "confidence": self.confidence.as_json(),
            "completeness_score": self.completeness_score.as_json(),
            "facets": [facet.as_json() for facet in self.facets],
            "extra_facets": [facet.as_json() for facet in self.extra_facets],
            "recorded": self.recorded,
            "total_facets": len(self.facets),
            "absent_by_kind": self.absent_by_kind,
            "unavailable_class_facets": dict(self.unavailable_class_facets),
            "comparability_class": class_of(self).as_json(),
        }


@dataclass(frozen=True)
class ComparabilityClass:
    """The class a context falls in, or the reason it falls in none.

    ``key`` is safe to group by and unsafe to read as a name: it is this module's construction,
    not a curated class. ``status`` is the field a caller must branch on before offering any
    comparison at all.
    """

    key: str
    label: str
    status: str
    context_id: Value[str]
    facets: tuple[ContextFacet, ...]
    blocked_by: tuple[str, ...]
    blind_to: tuple[str, ...] = ()

    @property
    def is_classified(self) -> bool:
        """True only for a class every class-defining facet could actually be read for."""
        return self.status == CLASSIFIED

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "is_classified": self.is_classified,
            "context_id": self.context_id.as_json(),
            "facets": [facet.as_json() for facet in self.facets],
            "blocked_by": list(self.blocked_by),
            "blind_to": list(self.blind_to),
            "definition_source": DEFINITION_SOURCE,
        }


def no_context_class(reason: str) -> ComparabilityClass:
    """The class of a measurement that never reaches a condition context.

    A distinct object rather than a None, because "this number has no comparability class" is a
    fact the interface must render, and a None renders as nothing.
    """
    return ComparabilityClass(
        key=UNCLASSIFIED,
        label="no comparability class",
        status=UNCLASSIFIED,
        context_id=Value.absent(Absence.NOT_RECORDED),
        facets=(),
        blocked_by=(reason,),
    )


def class_of(read: ConditionContextRead) -> ComparabilityClass:
    """The comparability class of one context, with the three outcomes of the module docstring.

    **The key covers the unreadable facets too**, as ``<name>=?``. Leaving them out would give a
    context that states `in_situ_product_removal` and one that does not the *same* key, and the
    two would then be grouped -- which is precisely what PLAN.md C.5's amendment forbids: "a
    measurement whose value is 'unknown' may not enter an aggregate with one that states a
    value". A `?` in the key keeps them in separate groups and marks the group provisional.
    """
    facets: list[ContextFacet] = []
    blocked: list[str] = []
    key_parts: list[str] = []
    for name in REQUIRED_MATCH:
        facet = read.facet(name)
        if facet is None:  # pragma: no cover - every REQUIRED_MATCH name has a column
            blocked.append(f"`{name}` has no column in this schema")
            continue
        facets.append(facet)
        key_parts.append(f"{name}={facet.value.display}")
        if not facet.value.is_known:
            blocked.append(
                f"`{name}` is {facet.value.display} for this context, so it cannot be matched "
                "against another"
            )

    blind_to: list[str] = []
    for name, why in UNMIGRATED_CLASS_FACETS.items():
        facet = read.facet(name)
        if facet is not None and facet.value.is_known:
            facets.append(facet)
            key_parts.append(f"{name}={facet.value.display}")
        else:
            blind_to.append(why)
            key_parts.append(f"{name}=?")

    if blocked:
        return ComparabilityClass(
            key=f"{UNCLASSIFIED}|{'|'.join(key_parts)}",
            label="no comparability class",
            status=UNCLASSIFIED,
            context_id=Value.known(read.id),
            facets=tuple(facets),
            blocked_by=tuple(blocked),
            blind_to=tuple(blind_to),
        )

    return ComparabilityClass(
        key="|".join(key_parts),
        label=", ".join(facet.value.display for facet in facets if facet.facet in REQUIRED_MATCH),
        status=PROVISIONAL if blind_to else CLASSIFIED,
        context_id=Value.known(read.id),
        facets=tuple(facets),
        blocked_by=(),
        blind_to=tuple(blind_to),
    )


def _extra_facets(conn: sqlite3.Connection, context_ids: Sequence[str]) -> dict[str, list[Any]]:
    rows: dict[str, list[Any]] = {}
    if not context_ids:
        return rows
    for row in (
        Select("condition_context_facet")
        .columns("context_id", "facet", "value", "value_state", "as_reported", "unit", "zone")
        .where_in("context_id", list(context_ids))
        .order_by("context_id", "facet")
        .page(conn)
    ):
        rows.setdefault(str(row["context_id"]), []).append(row)
    return rows


def read_contexts(
    conn: sqlite3.Connection, context_ids: Sequence[str]
) -> dict[str, ConditionContextRead]:
    """Full reads for the given contexts, keyed by id. Unknown ids are simply absent."""
    unique = sorted({cid for cid in context_ids if cid})
    if not unique:
        return {}

    extras = _extra_facets(conn, unique)
    reads: dict[str, ConditionContextRead] = {}
    for row in Select("condition_context").where_in("id", unique).page(conn):
        mapping = dict(row)
        zone = str(mapping["zone"]) if mapping["zone"] else None
        context_id = str(mapping["id"])

        extra: list[ContextFacet] = []
        recorded_extra: set[str] = set()
        for extra_row in extras.get(context_id, []):
            name = str(extra_row["facet"])
            recorded_extra.add(name)
            extra.append(
                ContextFacet(
                    facet=name,
                    label=name.replace("_", " ").replace(".", " · "),
                    value=from_text_column(
                        extra_row["value"]
                        if extra_row["value_state"] == "recorded"
                        else extra_row["value_state"],
                        zone=str(extra_row["zone"]) if extra_row["zone"] else None,
                    ),
                    as_reported=from_text_column(extra_row["as_reported"], zone="R"),
                    unit=str(extra_row["unit"]) if extra_row["unit"] else None,
                    is_class_defining=name in UNMIGRATED_CLASS_FACETS,
                )
            )

        unavailable = {
            name: why for name, why in UNMIGRATED_CLASS_FACETS.items() if name not in recorded_extra
        }

        completeness = mapping["completeness_score"]
        reads[context_id] = ConditionContextRead(
            id=context_id,
            zone=from_text_column(mapping["zone"]),
            confidence=from_text_column(mapping["confidence"]),
            completeness_score=(
                Value.known(float(completeness))
                if completeness is not None
                else Value.absent(Absence.NOT_RECORDED)
            ),
            facets=tuple(_facet_from_row(spec, mapping, zone) for spec in CONTEXT_FACETS),
            extra_facets=tuple(extra),
            unavailable_class_facets=unavailable,
        )
    return reads


def classes_for_samples(
    conn: sqlite3.Connection, sample_ids: Sequence[str]
) -> tuple[dict[str, ComparabilityClass], dict[str, ConditionContextRead]]:
    """The class of each named sample, plus the context reads the classes were built from.

    A sample with no `condition_context_id` gets :func:`no_context_class` rather than being left
    out of the mapping: the caller is rendering a row for it either way, and a missing key would
    make "no class" indistinguishable from "not asked about".
    """
    unique = sorted({sid for sid in sample_ids if sid})
    if not unique:
        return {}, {}

    context_of: dict[str, str | None] = {}
    for row in (
        Select("sample").columns("id", "condition_context_id").where_in("id", unique).page(conn)
    ):
        context_of[str(row["id"])] = (
            str(row["condition_context_id"]) if row["condition_context_id"] else None
        )

    contexts = read_contexts(conn, [cid for cid in context_of.values() if cid])
    classes: dict[str, ComparabilityClass] = {}
    for sample_id in unique:
        context_id = context_of.get(sample_id)
        if context_id is None:
            classes[sample_id] = no_context_class(
                f"sample {sample_id} has no `condition_context_id`, so nothing about the "
                "conditions it was taken under is recorded"
            )
            continue
        read = contexts.get(context_id)
        classes[sample_id] = (
            class_of(read)
            if read is not None
            else no_context_class(f"condition context {context_id} is referenced but not stored")
        )
    return classes, contexts


@dataclass(frozen=True)
class FacetDifference:
    """One facet, as each side of a comparison has it, and whether that is a difference.

    ``within_tolerance`` is only ever True for a facet in :data:`TOLERANCE_MATCH`, and it is a
    third answer rather than a second: "38 °C and 39 °C" differ and are still comparable, which
    is not the same claim as "both say 30 °C".
    """

    facet: str
    label: str
    values: tuple[str, ...]
    differs: bool
    within_tolerance: bool = False
    is_class_defining: bool = False
    tolerance: str | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "facet": self.facet,
            "label": self.label,
            "values": list(self.values),
            "differs": self.differs,
            "within_tolerance": self.within_tolerance,
            "is_class_defining": self.is_class_defining,
        }
        if self.tolerance is not None:
            payload["tolerance"] = self.tolerance
        return payload


_TOLERANCES: Final[Mapping[str, tuple[float, str]]] = {
    column: (band, mode) for column, band, mode in TOLERANCE_MATCH
}


def _within_tolerance(facet: str, values: Sequence[Value[Any]]) -> bool:
    band = _TOLERANCES.get(facet)
    if band is None or not all(value.is_known for value in values):
        return False
    numbers = [float(value.unwrap()) for value in values]
    span = max(numbers) - min(numbers)
    if band[1] == "relative":
        reference = max(abs(number) for number in numbers)
        return reference > 0 and span / reference <= band[0]
    return span <= band[0]


def context_differences(
    reads: Sequence[ConditionContextRead | None],
) -> tuple[FacetDifference, ...]:
    """Every facet on which the given contexts differ, with the class-defining ones marked.

    A `None` read -- a subject with no context at all -- participates as "no context", so it
    shows up as a difference rather than being quietly skipped. A comparison against a subject
    whose conditions are unknown is not a comparison that happens to have fewer rows.
    """
    differences: list[FacetDifference] = []
    for spec in CONTEXT_FACETS:
        facets = [None if read is None else read.facet(spec.column) for read in reads]
        values: list[Value[Any]] = [
            facet.value if facet is not None else Value.absent(Absence.NOT_RECORDED)
            for facet in facets
        ]
        displays = tuple(value.display for value in values)
        differs = len(set(displays)) > 1
        tolerated = differs and _within_tolerance(spec.column, values)
        band = _TOLERANCES.get(spec.column)
        differences.append(
            FacetDifference(
                facet=spec.column,
                label=spec.label,
                values=displays,
                differs=differs,
                within_tolerance=tolerated,
                is_class_defining=spec.column in REQUIRED_MATCH,
                tolerance=(
                    None
                    if band is None
                    else (f"± {band[0]:g}" if band[1] == "absolute" else f"within {band[0]:.0%}")
                ),
            )
        )
    return tuple(differences)
