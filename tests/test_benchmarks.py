"""Structural and honesty checks on the known-positive benchmark set.

These tests assert nothing about biology. They assert that the file parses, that every entry is
complete and drawn from the declared vocabularies, and - most importantly - that no entry claims
to be verified when no curator has verified it. PLAN.md S.5 requires the set to exist in phase 0,
before the pipelines; the risk that creates is that an unverified file written from memory gets
quoted as a source. The `unverified` and `verified: false` assertions below are the guard against
exactly that, and they are meant to fail loudly on the day curation starts, so the relaxation is a
reviewed diff rather than a silent drift.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

# ------------------------------------------------------------------------------- locating the file

_ENV_KEY = "FERMDB_BENCHMARK_FILE"
_REPO_RELATIVE = ("data", "benchmarks", "known_positives.yaml")


def _benchmark_path() -> Path:
    """Resolve the benchmark file without writing a path into source (CONVENTIONS.md, Paths)."""
    override = os.environ.get(_ENV_KEY)
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root.joinpath(*_REPO_RELATIVE)


# ----------------------------------------------------------------------------- expected structure

REQUIRED_FIELDS = (
    "id",
    "category",
    "statement",
    "query_shape",
    "expected_outcome",
    "organism",
    "product",
    "expected_evidence_level",
    "source_hint",
    "evidence",
    "confidence",
    "verified",
)

# CONVENTIONS.md's closed confidence vocabulary (D2): 'unverified' is a real, common state — an
# assertion never checked against a source — distinct from 'low' (checked, weak).
EXPECTED_CONFIDENCE_VALUES = frozenset({"unverified", "low", "medium", "high"})

# Every entry in this file is, today, written from memory with no source consulted. `evidence`
# must say that plainly rather than leaving the honesty work to `confidence` alone (this is the
# one curated file the evidence+confidence convention originally missed).
_UNCONSULTED_EVIDENCE_MARKER = "no source consulted"

# Categories the task fixes for this set. The file also declares them; both must agree, so that
# neither the file nor the test can quietly widen the vocabulary alone.
EXPECTED_CATEGORIES = frozenset(
    {
        "pathway_compartment",
        "cofactor_redox",
        "competing_pathway",
        "mitochondrial_genetics",
        "ethanol_reference",
        "tolerance",
        "negative_control",
    }
)

EXPECTED_EVIDENCE_LEVELS = frozenset({"L1", "L2", "L3", "L4", "L5", "NA"})

MIN_ENTRIES = 35
MAX_ENTRIES = 45
MIN_NEGATIVE_CONTROLS = 5

ID_PATTERN = re.compile(r"^BM-[A-Z]{3,6}-\d{3}$")

# 'NA' means recorded as not applicable and 'unknown' means recorded but unresolved. Neither is a
# stand-in for an unwritten field, so they may not appear in free-text fields that must say
# something (CONVENTIONS.md, Missing values).
_PLACEHOLDERS = frozenset({"", "na", "n/a", "none", "null", "tbd", "todo", "unknown"})


# --------------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    path = _benchmark_path()
    assert path.is_file(), f"benchmark file not found at {path} (override with ${_ENV_KEY})"
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), "the benchmark file must parse to a mapping at the top level"
    return loaded


@pytest.fixture(scope="module")
def entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("entries")
    assert isinstance(raw, list), "the benchmark file must carry a list under 'entries'"
    for index, entry in enumerate(raw):
        assert isinstance(entry, dict), f"entry {index} is not a mapping"
    return list(raw)


# ------------------------------------------------------------------------------ file-level checks


def test_file_declares_its_zone_and_unusability(document: dict[str, Any]) -> None:
    """The set is written from memory, so it is Zone I and may not support a conclusion."""
    assert document.get("zone") == "I", (
        "an unverified benchmark set written from background knowledge is Zone I (inferred, "
        "quarantined); promote it to R only when its entries carry citations"
    )
    assert document.get("usable_as_evidence") is False
    assert document.get("written_in_phase") == 0, "PLAN.md S.5 requires this set in phase 0"


def test_file_declares_the_same_vocabularies_the_tests_use(document: dict[str, Any]) -> None:
    assert set(document.get("categories", [])) == EXPECTED_CATEGORIES
    assert set(document.get("evidence_levels", [])) == EXPECTED_EVIDENCE_LEVELS
    assert "unverified" in set(document.get("confidence_values", []))


def test_readme_states_the_prohibition() -> None:
    """The README must say plainly, near the top, that nothing here is evidence yet."""
    readme = _benchmark_path().with_name("README.md")
    assert readme.is_file(), f"expected a README beside the benchmark file at {readme}"
    head = readme.read_text(encoding="utf-8")[:2000].lower()
    assert "may be used as evidence" in head or "used as evidence" in head
    assert "verified" in head


# ----------------------------------------------------------------------------- entry-level checks


def test_entry_count_is_in_range(entries: list[dict[str, Any]]) -> None:
    assert MIN_ENTRIES <= len(entries) <= MAX_ENTRIES, f"got {len(entries)} entries"


def test_every_entry_has_every_required_field(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        assert not missing, f"{entry.get('id', '<no id>')} is missing {missing}"


def test_ids_are_unique_and_well_formed(entries: list[dict[str, Any]]) -> None:
    ids = [entry["id"] for entry in entries]
    duplicates = [value for value, count in Counter(ids).items() if count > 1]
    assert not duplicates, f"duplicate ids: {duplicates}"
    malformed = [value for value in ids if not ID_PATTERN.match(str(value))]
    assert not malformed, f"ids must match BM-<GROUP>-<NNN>: {malformed}"


def test_every_entry_is_unverified(entries: list[dict[str, Any]]) -> None:
    """The honesty check. See this module's docstring before relaxing it."""
    not_unverified = [e["id"] for e in entries if e["confidence"] != "unverified"]
    assert not not_unverified, (
        "every entry in this set was written from background knowledge and must carry "
        f"confidence: unverified until a curator checks it; offenders: {not_unverified}"
    )


def test_confidence_is_from_the_closed_vocabulary(entries: list[dict[str, Any]]) -> None:
    """CONVENTIONS.md/D2: confidence is exactly {'unverified', 'low', 'medium', 'high'}."""
    bad = {
        e["id"]: e["confidence"]
        for e in entries
        if e["confidence"] not in EXPECTED_CONFIDENCE_VALUES
    }
    assert not bad, f"confidence must be one of {sorted(EXPECTED_CONFIDENCE_VALUES)}: {bad}"


def test_unverified_entries_say_no_source_was_consulted(entries: list[dict[str, Any]]) -> None:
    """An unverified entry's `evidence` must say so plainly (the evidence+confidence convention).

    `confidence: unverified` alone must not carry the honesty by itself; `evidence` should read as
    the actual (if minimal) evidence for an unverified claim - "nobody has looked yet" is itself
    something a curator recorded, not an empty field waiting to be filled in later.
    """
    dishonest = [
        e["id"]
        for e in entries
        if e["confidence"] == "unverified"
        and _UNCONSULTED_EVIDENCE_MARKER not in str(e["evidence"]).lower()
    ]
    assert not dishonest, (
        "an entry with confidence: unverified must have an evidence value that says no source "
        f"was consulted yet; offenders: {dishonest}"
    )


def test_no_entry_claims_to_be_verified(entries: list[dict[str, Any]]) -> None:
    claimed = [e["id"] for e in entries if e["verified"] is not False]
    assert not claimed, (
        "'verified' must be the boolean false for every entry; flipping it to true requires a "
        f"curator and a recorded source; offenders: {claimed}"
    )


def test_categories_are_from_the_controlled_vocabulary(entries: list[dict[str, Any]]) -> None:
    unknown = sorted({str(e["category"]) for e in entries} - EXPECTED_CATEGORIES)
    assert not unknown, f"unknown categories: {unknown}"


def test_every_category_is_represented(entries: list[dict[str, Any]]) -> None:
    present = {str(e["category"]) for e in entries}
    missing = sorted(EXPECTED_CATEGORIES - present)
    assert not missing, f"no entries in categories: {missing}"


def test_there_are_enough_negative_controls(entries: list[dict[str, Any]]) -> None:
    negatives = [e for e in entries if e["category"] == "negative_control"]
    assert len(negatives) >= MIN_NEGATIVE_CONTROLS, (
        "a pipeline that recovers everything is not discriminating; this set needs at least "
        f"{MIN_NEGATIVE_CONTROLS} negative controls, found {len(negatives)}"
    )


def test_evidence_levels_are_from_the_controlled_vocabulary(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        level = entry["expected_evidence_level"]
        assert level in EXPECTED_EVIDENCE_LEVELS, f"{entry['id']} has level {level!r}"


def test_negative_controls_expect_no_evidence_level(entries: list[dict[str, Any]]) -> None:
    """Nothing is expected to be found, so there is no level to reach: the literal string 'NA'."""
    for entry in entries:
        if entry["category"] == "negative_control":
            assert entry["expected_evidence_level"] == "NA", (
                f"{entry['id']} is a negative control and must record 'NA', not a level"
            )


def test_text_fields_say_something(entries: list[dict[str, Any]]) -> None:
    text_fields = ("statement", "query_shape", "expected_outcome", "source_hint", "evidence")
    for entry in entries:
        for field in text_fields:
            value = entry[field]
            assert isinstance(value, str), f"{entry['id']}.{field} must be a string"
            stripped = value.strip()
            assert stripped.lower() not in _PLACEHOLDERS, f"{entry['id']}.{field} is a placeholder"
            assert len(stripped) >= 30, f"{entry['id']}.{field} is too short to be actionable"


def test_organism_and_product_are_recorded(entries: list[dict[str, Any]]) -> None:
    """'NA' is permitted for product and means recorded as not applicable, never absent."""
    for entry in entries:
        organism = entry["organism"]
        assert isinstance(organism, str) and organism.strip().lower() not in _PLACEHOLDERS, (
            f"{entry['id']}.organism must name an organism"
        )
        product = entry["product"]
        assert isinstance(product, str) and product.strip() != "", (
            f"{entry['id']}.product must be a product name or the literal string 'NA'"
        )


def test_source_hint_points_a_curator_somewhere(entries: list[dict[str, Any]]) -> None:
    """A source hint that names nothing checkable defeats the purpose of the whole file."""
    for entry in entries:
        hint = str(entry["source_hint"])
        has_year = re.search(r"\b(19|20)\d{2}\b", hint) is not None
        has_proper_noun = re.search(r"\b[A-Z][A-Za-z0-9]{2,}\b", hint) is not None
        assert has_year or has_proper_noun, (
            f"{entry['id']}.source_hint must name something a curator can look up "
            "(an author, a year, a database, a gene)"
        )
