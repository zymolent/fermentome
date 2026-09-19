"""Deterministic, model-independent checks on model output. The safety layer of this project.

``docs/reference/MODEL_ROUTING.md`` §3 states the premise this module is built on:
**capability increases the plausibility of errors.** A stronger model does not produce fewer
wrong facts so much as wrong facts that survive human review longer, because they read better.
So nothing here asks what produced a value, and nothing here may ever be relaxed because a
better model is in use. Every check below would return the same verdict for output from a 7B
model, a frontier model, or a person typing at random.

Four checks, in the order they matter:

1. **Span verification.** Every extracted value carries a verbatim quote plus 0-based half-open
   character offsets, and :func:`verify_span` re-reads the source at those offsets. A value whose
   span does not resolve is rejected, not stored, not "flagged for review". This is the single
   check that kills the failure mode PLAN.md §2345 calls the most damaging one: a plausible
   number that is not in the paper. It is also the check that a smarter model makes *more*
   necessary, not less.
2. **Units parse**, against ``data/vocabularies/units.tsv``, and yields do not exceed the
   theoretical maximum for their (product, substrate) pair, read from
   ``data/vocabularies/theoretical_yields.tsv``. No stoichiometric constant appears in this file.
   Where the vocabulary records ``state='unknown'`` — the yield was sought and not settled — the
   check reports *not checkable* and never substitutes a number of its own.
3. **Referenced entity ids resolve**, through a resolver the caller injects. An id that does not
   resolve is reported in the ``UNRESOLVED:<as-written>`` form CONVENTIONS.md requires, never
   mapped to the nearest plausible match.
4. **Confidence is forced to 'unverified'**, whatever the model claimed, and the claim is kept
   beside it as an audit trail. MODEL_ROUTING.md §5.2: model capability must never appear
   anywhere in the derivation of a confidence value. A model may not set its own confidence,
   its own zone, or its own review state.

Everything that survives is Zone I with ``review_state='proposed'`` (CONVENTIONS.md, "Data
zones"). Nothing here promotes anything.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from ..config import Settings

__all__ = [
    "CONFIDENCE_VALUES",
    "ISSUE_CODES",
    "MODEL_CONFIDENCE",
    "MODEL_REVIEW_STATE",
    "MODEL_ZONE",
    "MISSING_STATES",
    "SPAN_REJECTION_REASONS",
    "EntityResolver",
    "RecordIssue",
    "RecordVerdict",
    "SchemaError",
    "Span",
    "SpanFormatError",
    "SpanVerdict",
    "TheoreticalYield",
    "TheoreticalYields",
    "UnitTable",
    "UnitVerdict",
    "ValidationReport",
    "check_json_schema",
    "load_theoretical_yields",
    "load_units",
    "resolver_from_ids",
    "validate_records",
    "verify_span",
]

JsonObject = dict[str, Any]

#: The closed confidence set (CONVENTIONS.md, "Curation"). Nothing may widen it.
CONFIDENCE_VALUES: Final[frozenset[str]] = frozenset(("unverified", "low", "medium", "high"))

#: What model output is always worth, whatever it claimed about itself.
MODEL_CONFIDENCE: Final[str] = "unverified"

#: Model output is Zone I, always (CONVENTIONS.md, "Data zones"; MODEL_ROUTING.md §5.4).
MODEL_ZONE: Final[str] = "I"

#: And it arrives proposed. Promotion is a curator action (PLAN.md L.1, L.5).
MODEL_REVIEW_STATE: Final[str] = "proposed"

#: The three distinct missing states, never collapsed into one another (CONVENTIONS.md).
MISSING_STATES: Final[frozenset[str]] = frozenset(("NA", "unknown"))

_CURIE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]*:[^\s].*$")
_YIELD_UNITS: Final[Mapping[str, str]] = {"g/g": "g_per_g", "mol/mol": "mol_per_mol"}

#: Yields are stored as fractions in [0, 1], never percentages (CONVENTIONS.md, "Units").
_FRACTION_BASES: Final[frozenset[str]] = frozenset(("theoretical_max_pct",))

# Floating-point slack on the theoretical-maximum comparison. Relative, tiny, and deliberately
# not a tolerance for real overshoot: a ceiling exceeded in the ninth decimal place is arithmetic
# noise, a ceiling exceeded in the second is a rejection.
_YIELD_EPSILON: Final[float] = 1e-9


# ------------------------------------------------------------------------------- JSON Schema


class SchemaError(ValueError):
    """The schema itself is unusable — malformed, or using a keyword this checker cannot honour."""


# Keywords that carry no constraint. Present in real schemas; safe to ignore.
_ANNOTATION_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "$comment",
        "$id",
        "$schema",
        "default",
        "definitions",
        "deprecated",
        "description",
        "examples",
        "readOnly",
        "title",
        "writeOnly",
    }
)

# Keywords this checker enforces. Anything outside both sets raises, because silently ignoring
# a constraint is under-validation wearing the costume of validation.
_SUPPORTED_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "not",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
    }
)

_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)


def check_json_schema(value: object, schema: Mapping[str, Any], *, path: str = "$") -> list[str]:
    """Validate ``value`` against a JSON Schema subset. Returns human-readable errors, [] if ok.

    Pydantic is not available here and a full JSON Schema implementation is not needed, so this
    is a hand-rolled checker over the keywords in :data:`_SUPPORTED_KEYWORDS`. It is strict in
    one direction on purpose: an unknown keyword raises :class:`SchemaError` rather than being
    skipped. ``$ref`` in particular is unsupported — a checker that quietly ignored a ``$ref``
    would report every document valid, which is worse than having no checker at all.
    """
    _assert_supported(schema, path)
    errors: list[str] = []
    _check(value, schema, path, errors)
    return errors


def _assert_supported(schema: Mapping[str, Any], path: str) -> None:
    for keyword in schema:
        if keyword in _SUPPORTED_KEYWORDS or keyword in _ANNOTATION_KEYWORDS:
            continue
        raise SchemaError(
            f"{path}: schema keyword {keyword!r} is not supported by this checker. Supported: "
            f"{sorted(_SUPPORTED_KEYWORDS)}. ($ref is deliberately unsupported: silently "
            f"ignoring one would validate everything.)"
        )


def _check(value: object, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    if "type" in schema:
        expected = schema["type"]
        names = [expected] if isinstance(expected, str) else list(expected)
        for name in names:
            if name not in _TYPE_NAMES:
                raise SchemaError(f"{path}: unknown JSON Schema type {name!r}")
        if not any(_is_type(value, name) for name in names):
            errors.append(f"{path}: expected type {'|'.join(names)}, got {_type_of(value)}")
            return

    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, list):
            raise SchemaError(f"{path}: 'enum' must be a list")
        if not any(_json_equal(value, option) for option in allowed):
            errors.append(f"{path}: {value!r} is not one of {allowed!r}")

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: expected the constant {schema['const']!r}, got {value!r}")

    _check_composites(value, schema, path, errors)

    if isinstance(value, str):
        _check_string(value, schema, path, errors)
    elif isinstance(value, bool):
        pass  # A JSON boolean is not a number, whatever Python thinks of bool.
    elif isinstance(value, (int, float)):
        _check_number(value, schema, path, errors)
    if isinstance(value, Mapping):
        _check_object(value, schema, path, errors)
    elif isinstance(value, list):
        _check_array(value, schema, path, errors)


def _check_composites(
    value: object, schema: Mapping[str, Any], path: str, errors: list[str]
) -> None:
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        branches = schema[keyword]
        if not isinstance(branches, list) or not branches:
            raise SchemaError(f"{path}: {keyword!r} must be a non-empty list of schemas")
        results: list[list[str]] = []
        for index, branch in enumerate(branches):
            sub = _as_schema(branch, f"{path}.{keyword}[{index}]")
            _assert_supported(sub, f"{path}.{keyword}[{index}]")
            collected: list[str] = []
            _check(value, sub, path, collected)
            results.append(collected)
        passed = sum(1 for result in results if not result)
        if keyword == "allOf":
            for result in results:
                errors.extend(result)
        elif keyword == "anyOf" and passed == 0:
            errors.append(f"{path}: matched none of the {len(branches)} anyOf branches")
        elif keyword == "oneOf" and passed != 1:
            errors.append(f"{path}: matched {passed} oneOf branches, expected exactly 1")

    if "not" in schema:
        sub = _as_schema(schema["not"], f"{path}.not")
        _assert_supported(sub, f"{path}.not")
        collected = []
        _check(value, sub, path, collected)
        if not collected:
            errors.append(f"{path}: matched a 'not' schema it must not match")


def _check_string(value: str, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    minimum = schema.get("minLength")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: string shorter than minLength {minimum}")
    maximum = schema.get("maxLength")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: string longer than maxLength {maximum}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise SchemaError(f"{path}: invalid 'pattern' {pattern!r}: {exc}") from exc
        if compiled.search(value) is None:
            errors.append(f"{path}: {value!r} does not match pattern {pattern!r}")


def _check_number(value: float, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        errors.append(f"{path}: {value} is below minimum {minimum}")
    maximum = schema.get("maximum")
    if isinstance(maximum, (int, float)) and value > maximum:
        errors.append(f"{path}: {value} is above maximum {maximum}")
    exclusive_min = schema.get("exclusiveMinimum")
    if isinstance(exclusive_min, (int, float)) and value <= exclusive_min:
        errors.append(f"{path}: {value} is not above exclusiveMinimum {exclusive_min}")
    exclusive_max = schema.get("exclusiveMaximum")
    if isinstance(exclusive_max, (int, float)) and value >= exclusive_max:
        errors.append(f"{path}: {value} is not below exclusiveMaximum {exclusive_max}")
    multiple = schema.get("multipleOf")
    if isinstance(multiple, (int, float)) and multiple > 0:
        quotient = value / multiple
        if abs(quotient - round(quotient)) > 1e-9:
            errors.append(f"{path}: {value} is not a multiple of {multiple}")


def _check_object(
    value: Mapping[str, Any], schema: Mapping[str, Any], path: str, errors: list[str]
) -> None:
    required = schema.get("required", [])
    if not isinstance(required, list):
        raise SchemaError(f"{path}: 'required' must be a list")
    for name in required:
        if name not in value:
            errors.append(f"{path}: missing required property {name!r}")

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise SchemaError(f"{path}: 'properties' must be an object")
    for name, subschema in properties.items():
        if name in value:
            sub = _as_schema(subschema, f"{path}.{name}")
            _assert_supported(sub, f"{path}.{name}")
            _check(value[name], sub, f"{path}.{name}", errors)

    extra = schema.get("additionalProperties")
    if extra is False:
        unexpected = sorted(set(value) - set(properties))
        if unexpected:
            errors.append(f"{path}: unexpected properties {unexpected}")
    elif isinstance(extra, Mapping):
        _assert_supported(extra, f"{path}.additionalProperties")
        for name in sorted(set(value) - set(properties)):
            _check(value[name], extra, f"{path}.{name}", errors)


def _check_array(value: list[Any], schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: {len(value)} items, minItems is {minimum}")
    maximum = schema.get("maxItems")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: {len(value)} items, maxItems is {maximum}")
    if schema.get("uniqueItems") is True:
        seen: list[Any] = []
        for item in value:
            if any(_json_equal(item, other) for other in seen):
                errors.append(f"{path}: duplicate item {item!r} with uniqueItems set")
                break
            seen.append(item)
    if "items" in schema:
        sub = _as_schema(schema["items"], f"{path}.items")
        _assert_supported(sub, f"{path}.items")
        for index, item in enumerate(value):
            _check(item, sub, f"{path}[{index}]", errors)


def _as_schema(value: object, path: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise SchemaError(f"{path}: expected a schema object, got {_type_of(value)}")


def _is_type(value: object, name: str) -> bool:
    if name == "object":
        return isinstance(value, Mapping)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _type_of(value: object) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is_type(value, name):
            return name
    return type(value).__name__


def _json_equal(left: object, right: object) -> bool:
    """JSON equality: True and 1 are different values, unlike in Python."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return bool(left == right)


# ---------------------------------------------------------------------------- span verification

#: The closed set of reasons a span can fail. A value may be rejected for exactly one of these.
SPAN_REJECTION_REASONS: Final[tuple[str, ...]] = (
    "empty_quote",
    "offsets_malformed",
    "offsets_out_of_range",
    "offsets_do_not_match_quote",
    "quote_absent_from_source",
)


class SpanFormatError(ValueError):
    """A span mapping is missing its quote or its offsets, or they are not the right types."""


@dataclass(frozen=True)
class Span:
    """A verbatim quote and where it sits in the source text.

    0-based half-open ``[char_start, char_end)``, matching CONVENTIONS.md "Coordinates and
    sequence" and the ``span`` table's columns. Length is always ``char_end - char_start``.
    """

    quote: str
    char_start: int
    char_end: int
    section: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Span:
        """Build from a model's JSON. Accepts ``quote`` or the column name ``quoted_text``."""
        quote = data.get("quote", data.get("quoted_text"))
        if not isinstance(quote, str):
            raise SpanFormatError(f"span has no string quote: {dict(data)!r}")
        start = data.get("char_start")
        end = data.get("char_end")
        if not isinstance(start, int) or isinstance(start, bool):
            raise SpanFormatError(f"span char_start is not an integer: {start!r}")
        if not isinstance(end, int) or isinstance(end, bool):
            raise SpanFormatError(f"span char_end is not an integer: {end!r}")
        section = data.get("section")
        return cls(
            quote=quote,
            char_start=start,
            char_end=end,
            section=section if isinstance(section, str) else None,
        )

    def as_dict(self) -> JsonObject:
        """The normalized form stored alongside an accepted value."""
        return {
            "quote": self.quote,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "section": self.section,
        }


@dataclass(frozen=True)
class SpanVerdict:
    """The result of re-reading the source at a span's offsets."""

    ok: bool
    reason: str | None = None
    detail: str = ""
    #: Offsets where the quote *does* occur, when it occurs somewhere other than where claimed.
    found_at: tuple[int, ...] = ()

    @property
    def quote_exists_elsewhere(self) -> bool:
        """True when the text is really in the paper but the offsets point somewhere else.

        Worth distinguishing from an absent quote — one is a bookkeeping error an offset-repair
        pass could fix, the other is fabrication — but both reject the value either way.
        """
        return bool(self.found_at)


def verify_span(source_text: str, span: Span, *, max_alternatives: int = 3) -> SpanVerdict:
    """Re-check that ``span.quote`` occurs in ``source_text`` at exactly ``[start, end)``.

    Exact comparison, with no whitespace normalization and no fuzzy matching. That strictness is
    the entire value of the check: a validator that accepts an approximate match accepts a quote
    the model adjusted, and a quote the model adjusted is not evidence of anything.
    """
    if not span.quote:
        return SpanVerdict(False, "empty_quote", "the span carries no quoted text")
    if span.char_start < 0 or span.char_end <= span.char_start:
        return SpanVerdict(
            False,
            "offsets_malformed",
            f"[{span.char_start}, {span.char_end}) is not a non-empty half-open interval",
        )
    if span.char_end > len(source_text):
        return SpanVerdict(
            False,
            "offsets_out_of_range",
            f"[{span.char_start}, {span.char_end}) runs past the {len(source_text)}-character "
            "source text",
        )

    actual = source_text[span.char_start : span.char_end]
    if actual == span.quote:
        return SpanVerdict(True)

    found = tuple(_find_all(source_text, span.quote, limit=max_alternatives))
    if found:
        return SpanVerdict(
            False,
            "offsets_do_not_match_quote",
            f"the source reads {actual!r} at [{span.char_start}, {span.char_end}); the quote "
            f"does occur at {list(found)}",
            found,
        )
    return SpanVerdict(
        False,
        "quote_absent_from_source",
        f"the quoted text does not occur anywhere in the source; [{span.char_start}, "
        f"{span.char_end}) reads {actual!r}",
    )


def _find_all(haystack: str, needle: str, *, limit: int) -> Iterator[int]:
    start = 0
    for _ in range(limit):
        index = haystack.find(needle, start)
        if index < 0:
            return
        yield index
        start = index + 1


# -------------------------------------------------------------------------------- vocabularies


def _vocabularies_dir(source: Settings | Path) -> Path:
    return source if isinstance(source, Path) else source.path("vocabularies_dir")


def _read_tsv(path: Path) -> list[dict[str, str]]:
    """Parse a vocabulary TSV, skipping its `#` header block.

    The plain `csv` module rather than pandas, for the reason tests/test_vocabularies.py gives:
    pandas would read the literal string ``'NA'`` as a missing value and collapse this project's
    three distinct missing states into two.
    """
    with path.open(encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#") and line.strip()]
    return list(csv.DictReader(lines, delimiter="\t"))


@lru_cache(maxsize=8)
def _read_tsv_cached(path_str: str, mtime_ns: int) -> tuple[dict[str, str], ...]:
    return tuple(_read_tsv(Path(path_str)))


def _rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.is_file():
        raise FileNotFoundError(f"vocabulary file not found: {path}")
    return _read_tsv_cached(str(path), path.stat().st_mtime_ns)


def _as_float(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# -- units -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitVerdict:
    """Whether a reported unit parses, and what it is."""

    ok: bool
    #: 'recorded' | 'null' | 'NA' | 'unknown' | 'unparsable' — the three missing states kept apart.
    state: str
    canonical: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class UnitTable:
    """The unit and basis vocabulary, loaded from ``units.tsv``. No unit is written in code."""

    units: frozenset[str]
    bases: frozenset[str]
    _canonical: Mapping[str, str] = field(default_factory=dict, repr=False)

    def parse(self, unit: object) -> UnitVerdict:
        """Resolve a reported unit to a vocabulary entry, keeping the three missing states apart.

        ``None`` means the source never recorded a unit; the literal ``'NA'`` and ``'unknown'``
        are their own states and are never coerced into NULL or into each other
        (CONVENTIONS.md, "Missing values"). Anything else must be in the vocabulary.
        """
        if unit is None:
            return UnitVerdict(True, "null", None, "no unit recorded")
        if not isinstance(unit, str):
            return UnitVerdict(False, "unparsable", None, f"unit is {_type_of(unit)}, not a string")
        stripped = unit.strip()
        if stripped in MISSING_STATES:
            return UnitVerdict(True, stripped, None, f"unit recorded as {stripped!r}")
        if not stripped:
            return UnitVerdict(False, "unparsable", None, "unit is an empty string")
        canonical = self._canonical.get(_normalize_unit(stripped))
        if canonical is None:
            return UnitVerdict(
                False,
                "unparsable",
                None,
                f"{unit!r} is not in units.tsv (known: {sorted(self.units)})",
            )
        return UnitVerdict(True, "recorded", canonical)

    def is_basis(self, basis: str) -> bool:
        """True if ``basis`` is in the ``basis`` vocabulary."""
        return basis in self.bases


def _normalize_unit(unit: str) -> str:
    """Fold whitespace only. ``'% v/v'``, ``'%v/v'`` and ``'% v / v'`` are one unit; nothing else
    is folded, because a unit's scale is never inferred (CONVENTIONS.md, "Units and quantities")."""
    return "".join(unit.split())


def load_units(source: Settings | Path) -> UnitTable:
    """Load ``units.tsv`` from the configured vocabularies directory (or a directory directly)."""
    rows = _rows(_vocabularies_dir(source) / "units.tsv")
    units = {row["code"].strip() for row in rows if row.get("entry_type") == "unit"}
    bases = {row["code"].strip() for row in rows if row.get("entry_type") == "basis"}
    return UnitTable(
        units=frozenset(units),
        bases=frozenset(bases),
        _canonical={_normalize_unit(code): code for code in units},
    )


# -- theoretical yields ------------------------------------------------------------------------


@dataclass(frozen=True)
class TheoreticalYield:
    """One row of ``theoretical_yields.tsv``: a maximum for one (product, substrate) pair."""

    product_id: str
    substrate: str
    mol_per_mol: float | None
    g_per_g: float | None
    #: 'recorded' | 'unknown'. 'unknown' means a yield was sought and the pathway is not settled.
    state: str

    def maximum_for(self, unit: str) -> float | None:
        """The ceiling in ``unit``, or None when this row cannot answer for that unit."""
        if self.state != "recorded":
            return None
        column = _YIELD_UNITS.get(unit)
        if column is None:
            return None
        return self.g_per_g if column == "g_per_g" else self.mol_per_mol


@dataclass(frozen=True)
class TheoreticalYields:
    """Every theoretical maximum, keyed by (product_id, substrate).

    Read from the vocabulary, never hardcoded. No stoichiometric constant appears in this module,
    and a test asserts that it stays that way: a yield is a property of a *pair* under an assumed
    stoichiometry, and the file that records one also records which assumption it rests on and
    how well checked that assumption is. A constant copied into code loses all of that.
    """

    rows: Mapping[tuple[str, str], TheoreticalYield]

    def lookup(self, product_id: str, substrate: str) -> TheoreticalYield | None:
        """The row for a pair, or None if the atlas tracks no yield for it."""
        return self.rows.get((product_id, substrate.strip().lower()))

    def maximum(self, product_id: str, substrate: str, unit: str) -> float | None:
        """The ceiling for a pair in ``unit``, or None when the check cannot be made.

        None means *not checkable* — no row, or the row's ``state`` is ``'unknown'`` because the
        pathway's redox/ATP closure is unsettled. It never means "no limit", and the caller must
        report it as unchecked rather than treat the value as verified.
        """
        row = self.lookup(product_id, substrate)
        return None if row is None else row.maximum_for(unit)


def load_theoretical_yields(source: Settings | Path) -> TheoreticalYields:
    """Load ``theoretical_yields.tsv`` from the configured vocabularies directory."""
    rows = _rows(_vocabularies_dir(source) / "theoretical_yields.tsv")
    table: dict[tuple[str, str], TheoreticalYield] = {}
    for row in rows:
        product_id = (row.get("product_id") or "").strip()
        substrate = (row.get("substrate") or "").strip().lower()
        if not product_id or not substrate:
            continue
        table[(product_id, substrate)] = TheoreticalYield(
            product_id=product_id,
            substrate=substrate,
            mol_per_mol=_as_float(row.get("mol_per_mol")),
            g_per_g=_as_float(row.get("g_per_g")),
            state=(row.get("state") or "unknown").strip(),
        )
    return TheoreticalYields(rows=table)


# ------------------------------------------------------------------------------ entity resolution

#: ``resolve(id) -> True`` when the id names something that exists. Injected, so the validator
#: needs neither a database nor a network to run (and so tests need neither either).
EntityResolver = Callable[[str], bool]


def resolver_from_ids(known: Iterable[str]) -> EntityResolver:
    """A resolver over a fixed set of ids — for tests, and for a caller holding an id snapshot."""
    ids = frozenset(known)
    return lambda candidate: candidate in ids


# ---------------------------------------------------------------------------- record validation

#: The closed set of issue codes. Fatal ones reject the record; the rest annotate it.
ISSUE_CODES: Final[tuple[str, ...]] = (
    "span_missing",
    "span_malformed",
    "span_unresolved",
    "unit_unparsable",
    "yield_exceeds_theoretical_max",
    "yield_not_checkable",
    "fraction_out_of_range",
    "value_not_numeric",
    "entity_unresolved",
    "entity_ids_unchecked",
    "basis_defaulted_to_unknown",
    "basis_not_in_vocabulary",
    "confidence_overridden",
)


@dataclass(frozen=True)
class RecordIssue:
    """One finding about one record. ``fatal`` decides whether the record is stored at all."""

    code: str
    message: str
    fatal: bool = True

    def __post_init__(self) -> None:
        if self.code not in ISSUE_CODES:
            raise ValueError(f"unknown issue code {self.code!r}; expected one of {ISSUE_CODES}")


@dataclass(frozen=True)
class RecordVerdict:
    """What became of one extracted record."""

    index: int
    accepted: bool
    #: The record as it may be stored — Zone I, confidence forced — or None if rejected.
    record: JsonObject | None
    issues: tuple[RecordIssue, ...] = ()

    @property
    def fatal_issues(self) -> tuple[RecordIssue, ...]:
        """Only the issues that caused, or would cause, rejection."""
        return tuple(issue for issue in self.issues if issue.fatal)


@dataclass(frozen=True)
class ValidationReport:
    """The verdict on a whole extraction payload."""

    verdicts: tuple[RecordVerdict, ...]

    @property
    def accepted(self) -> tuple[JsonObject, ...]:
        """Records that may be written to Zone I."""
        return tuple(v.record for v in self.verdicts if v.accepted and v.record is not None)

    @property
    def rejected(self) -> tuple[RecordVerdict, ...]:
        """Records that must not be stored, each with the reason."""
        return tuple(v for v in self.verdicts if not v.accepted)

    @property
    def ok(self) -> bool:
        """True when nothing was rejected."""
        return not self.rejected

    def summary(self) -> str:
        """One line for a log or a CLI, naming what was dropped and why."""
        if self.ok:
            return f"{len(self.verdicts)} record(s) validated, none rejected"
        reasons = sorted({issue.code for v in self.rejected for issue in v.fatal_issues})
        return (
            f"{len(self.accepted)}/{len(self.verdicts)} record(s) accepted; "
            f"{len(self.rejected)} rejected ({', '.join(reasons)})"
        )


def validate_records(
    records: Sequence[Mapping[str, Any]],
    *,
    source_text: str,
    units: UnitTable,
    yields: TheoreticalYields,
    resolve_entity: EntityResolver | None = None,
    require_span: bool = True,
) -> ValidationReport:
    """Run every deterministic check over a list of extracted records.

    A record is a mapping. The fields this looks at, all optional except ``span``::

        span         {quote | quoted_text, char_start, char_end, section?}   verbatim + offsets
        value        the number or string extracted
        unit         as reported; checked against units.tsv, never rewritten in place
        basis        yield basis; defaulted to 'unknown' (not NULL) when absent
        product_id   YAA:PRODUCT:... , for the theoretical-maximum check
        substrate    e.g. 'glucose', the other half of the yield pair
        entity_ids   explicit ids to resolve; any '*_id'/'*_ids' field is checked too
        confidence   whatever the model claimed. Overwritten. Kept as 'claimed_confidence'

    An accepted record comes back as a *new* mapping with ``confidence='unverified'``,
    ``zone='I'`` and ``review_state='proposed'`` forced, ``unit_canonical`` added beside the
    untouched reported unit, and its span normalized. Nothing reported is overwritten in place
    (CONVENTIONS.md: ``value_as_reported`` and ``unit_as_reported`` are Zone R).
    """
    verdicts: list[RecordVerdict] = []
    for index, record in enumerate(records):
        issues: list[RecordIssue] = []
        checked = _validate_record(
            record,
            source_text=source_text,
            units=units,
            yields=yields,
            resolve_entity=resolve_entity,
            require_span=require_span,
            issues=issues,
        )
        fatal = any(issue.fatal for issue in issues)
        verdicts.append(
            RecordVerdict(
                index=index,
                accepted=not fatal,
                record=None if fatal else checked,
                issues=tuple(issues),
            )
        )
    return ValidationReport(tuple(verdicts))


def _validate_record(
    record: Mapping[str, Any],
    *,
    source_text: str,
    units: UnitTable,
    yields: TheoreticalYields,
    resolve_entity: EntityResolver | None,
    require_span: bool,
    issues: list[RecordIssue],
) -> JsonObject:
    checked: JsonObject = dict(record)

    span = _check_span(record, source_text, require_span=require_span, issues=issues)
    if span is not None:
        checked["span"] = span.as_dict()

    unit_verdict = units.parse(record.get("unit"))
    if not unit_verdict.ok:
        issues.append(RecordIssue("unit_unparsable", unit_verdict.detail))
    checked["unit_state"] = unit_verdict.state
    if unit_verdict.canonical is not None:
        # Added alongside, never over: the reported unit is Zone R and is not rewritten.
        checked["unit_canonical"] = unit_verdict.canonical

    _check_basis(record, units, checked, issues)
    _check_yield(record, unit_verdict, yields, issues)
    _check_entities(record, resolve_entity, checked, issues)
    _force_provenance(record, checked, issues)
    return checked


def _check_span(
    record: Mapping[str, Any],
    source_text: str,
    *,
    require_span: bool,
    issues: list[RecordIssue],
) -> Span | None:
    raw = record.get("span")
    if raw is None:
        if require_span:
            issues.append(
                RecordIssue(
                    "span_missing",
                    "no span: an extracted value is not storable without a verbatim quote and "
                    "its offsets (PLAN.md H.5)",
                )
            )
        return None
    if not isinstance(raw, Mapping):
        issues.append(RecordIssue("span_malformed", f"span is {_type_of(raw)}, expected an object"))
        return None
    try:
        span = Span.from_mapping(raw)
    except SpanFormatError as exc:
        issues.append(RecordIssue("span_malformed", str(exc)))
        return None

    verdict = verify_span(source_text, span)
    if not verdict.ok:
        issues.append(
            RecordIssue(
                "span_unresolved",
                f"span does not resolve ({verdict.reason}): {verdict.detail}",
            )
        )
        return None
    return span


def _check_basis(
    record: Mapping[str, Any],
    units: UnitTable,
    checked: JsonObject,
    issues: list[RecordIssue],
) -> None:
    """`basis` is mandatory on a yield; absent means 'unknown', never NULL (CONVENTIONS.md)."""
    if not _looks_like_yield(record):
        return
    basis = record.get("basis")
    if basis is None or (isinstance(basis, str) and not basis.strip()):
        checked["basis"] = "unknown"
        issues.append(
            RecordIssue(
                "basis_defaulted_to_unknown",
                "no basis reported for a yield; recorded as 'unknown' (not NULL) and not usable "
                "for cross-study comparison",
                fatal=False,
            )
        )
        return
    if isinstance(basis, str) and basis not in MISSING_STATES and not units.is_basis(basis):
        issues.append(
            RecordIssue(
                "basis_not_in_vocabulary",
                f"basis {basis!r} is not in the units.tsv basis vocabulary "
                f"(known: {sorted(units.bases)})",
            )
        )


def _looks_like_yield(record: Mapping[str, Any]) -> bool:
    unit = record.get("unit")
    if isinstance(unit, str) and _normalize_unit(unit) in _YIELD_UNITS:
        return True
    basis = record.get("basis")
    return isinstance(basis, str) and basis in _FRACTION_BASES


def _check_yield(
    record: Mapping[str, Any],
    unit_verdict: UnitVerdict,
    yields: TheoreticalYields,
    issues: list[RecordIssue],
) -> None:
    """Reject a yield above the theoretical maximum for its (product, substrate) pair.

    The maximum is read from theoretical_yields.tsv. Where that file records ``state='unknown'``
    — the pathway's redox/ATP closure is not settled — this reports the value as *unchecked*
    rather than inventing a ceiling, because a wrong ceiling rejects real data.
    """
    basis = record.get("basis")
    is_fraction_basis = isinstance(basis, str) and basis in _FRACTION_BASES
    if not is_fraction_basis and unit_verdict.canonical not in _YIELD_UNITS:
        return

    value = record.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(
            RecordIssue("value_not_numeric", f"a yield's value must be a number, got {value!r}")
        )
        return

    if is_fraction_basis:
        # Fractions in [0, 1], never percentages (CONVENTIONS.md, "Units and quantities").
        if value < 0 or value > 1 + _YIELD_EPSILON:
            issues.append(
                RecordIssue(
                    "fraction_out_of_range",
                    f"basis {basis!r} means a fraction of the theoretical maximum, so {value} is "
                    "out of [0, 1] — a value above 1 claims more product than the substrate "
                    "contains",
                )
            )
        return

    product_id = record.get("product_id")
    substrate = record.get("substrate")
    unit = unit_verdict.canonical or ""
    if not isinstance(product_id, str) or not isinstance(substrate, str):
        issues.append(
            RecordIssue(
                "yield_not_checkable",
                f"a {unit} yield without both product_id and substrate cannot be checked against "
                "a theoretical maximum",
                fatal=False,
            )
        )
        return

    maximum = yields.maximum(product_id, substrate, unit)
    if maximum is None:
        row = yields.lookup(product_id, substrate)
        reason = (
            f"theoretical_yields.tsv has no row for ({product_id}, {substrate})"
            if row is None
            else f"theoretical_yields.tsv records state={row.state!r} for "
            f"({product_id}, {substrate}): the assumed pathway is not settled"
        )
        issues.append(
            RecordIssue("yield_not_checkable", f"{reason}; no ceiling applied", fatal=False)
        )
        return

    if value > maximum * (1 + _YIELD_EPSILON):
        issues.append(
            RecordIssue(
                "yield_exceeds_theoretical_max",
                f"{value} {unit} exceeds the theoretical maximum {maximum} {unit} for "
                f"{product_id} from {substrate} (theoretical_yields.tsv). A yield above the "
                "stoichiometric ceiling is not a measurement",
            )
        )


def _check_entities(
    record: Mapping[str, Any],
    resolve_entity: EntityResolver | None,
    checked: JsonObject,
    issues: list[RecordIssue],
) -> None:
    """Every referenced id must resolve; an unresolvable one is recorded, never remapped."""
    referenced = sorted(_referenced_ids(record))
    if not referenced:
        return
    if resolve_entity is None:
        issues.append(
            RecordIssue(
                "entity_ids_unchecked",
                f"no resolver supplied, so {referenced} were not checked",
                fatal=False,
            )
        )
        return
    unresolved = [name for name in referenced if not resolve_entity(name)]
    if unresolved:
        # CONVENTIONS.md, "Identifiers": an identifier that cannot be resolved is recorded as
        # UNRESOLVED:<as-written>, never mapped to the nearest plausible match.
        checked["unresolved_ids"] = [f"UNRESOLVED:{name}" for name in unresolved]
        issues.append(
            RecordIssue(
                "entity_unresolved",
                f"these ids do not resolve: {unresolved}; recorded as "
                f"{checked['unresolved_ids']} rather than matched to anything similar",
            )
        )


def _referenced_ids(record: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()
    for key, value in record.items():
        if key == "entity_ids" or key.endswith("_ids"):
            if isinstance(value, (list, tuple)):
                found.update(item for item in value if _is_curie(item))
        elif key.endswith("_id") and _is_curie(value):
            found.add(str(value))
    return found


def _is_curie(value: object) -> bool:
    return isinstance(value, str) and bool(_CURIE_RE.match(value))


def _force_provenance(
    record: Mapping[str, Any], checked: JsonObject, issues: list[RecordIssue]
) -> None:
    """Overwrite confidence, zone and review_state. A model may not set any of the three.

    MODEL_ROUTING.md §5.2: model capability must never appear anywhere in the derivation of a
    confidence value. `unverified` means "asserted but never checked against a source", which is
    exactly what model output is, whatever the model wrote about itself.
    """
    claimed = record.get("confidence")
    if isinstance(claimed, str) and claimed != MODEL_CONFIDENCE:
        checked["claimed_confidence"] = claimed
        issues.append(
            RecordIssue(
                "confidence_overridden",
                f"the model claimed confidence {claimed!r}; forced to {MODEL_CONFIDENCE!r} "
                "(a model may not set its own confidence)",
                fatal=False,
            )
        )
    checked["confidence"] = MODEL_CONFIDENCE
    checked["zone"] = MODEL_ZONE
    checked["review_state"] = MODEL_REVIEW_STATE
