"""Tests for the controlled vocabularies in `data/vocabularies/`.

These files are read with the plain `csv` module rather than pandas, deliberately: pandas'
default NA-sniffing on `read_csv`/`read_table` treats the literal string ``'NA'`` as missing and
silently turns it into `NaN`, which would collapse this project's three-state
NULL / `'NA'` / `'unknown'` convention (docs/reference/CONVENTIONS.md, "Missing values") into two
states. `csv.DictReader` does no such coercion, so an empty field reads back as `""` (NULL) and a
cell holding the literal text ``NA`` or ``unknown`` reads back as exactly that string.

No path is hardcoded (docs/reference/CONVENTIONS.md, "Paths and configuration"): the vocabularies
directory is resolved relative to this test file, because there is no project-wide path-
configuration module yet for it to use instead.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fermdb.genetic_code import COMPARTMENT_ENCODING_GENOMES, ENCODING_GENOME_TABLE

REPO_ROOT = Path(__file__).resolve().parent.parent
VOCAB_DIR = REPO_ROOT / "data" / "vocabularies"
SCHEMA_PATH = REPO_ROOT / "src" / "fermdb" / "db" / "schema.sql"

VOCAB_FILES = [
    "products.tsv",
    "theoretical_yields.tsv",
    "compartments.tsv",
    "evidence_types.tsv",
    "modification_types.tsv",
    "assay_types.tsv",
    "units.tsv",
    "predicates.tsv",
    "condition_facets.tsv",
]

CONFIDENCE_VALUES = {"unverified", "low", "medium", "high"}


def read_tsv(name: str) -> list[dict[str, str]]:
    """Parse a vocabulary TSV, skipping its leading `#`-commented header block.

    Uses `csv.DictReader` rather than pandas so the literal strings `'NA'` and `'unknown'` come
    back unchanged instead of being coerced to a missing-value sentinel (see module docstring).
    """
    path = VOCAB_DIR / name
    with path.open(encoding="utf-8") as f:
        lines = [line for line in f if not line.lstrip().startswith("#") and line.strip()]
    reader = csv.DictReader(lines, delimiter="\t")
    return list(reader)


# --------------------------------------------------------------------------- files exist & parse


def test_vocab_directory_exists() -> None:
    assert VOCAB_DIR.is_dir(), f"expected {VOCAB_DIR} to exist"


@pytest.mark.parametrize("name", VOCAB_FILES)
def test_every_file_parses_with_evidence_and_confidence_columns(name: str) -> None:
    rows = read_tsv(name)
    assert rows, f"{name} has no data rows"
    fieldnames = set(rows[0].keys())
    assert "evidence" in fieldnames, f"{name} is missing an 'evidence' column"
    assert "confidence" in fieldnames, f"{name} is missing a 'confidence' column"
    # Every row must actually be that many columns wide (DictReader puts overflow in None and
    # leaves missing trailing fields as None) -- a silently ragged row is a malformed file.
    for i, row in enumerate(rows):
        assert None not in row, f"{name} row {i} has the wrong number of columns"
        assert None not in row.values(), f"{name} row {i} has the wrong number of columns"


@pytest.mark.parametrize("name", VOCAB_FILES)
def test_no_row_is_missing_evidence_or_confidence(name: str) -> None:
    for i, row in enumerate(read_tsv(name)):
        assert row["evidence"].strip(), f"{name} row {i} ({row}) has empty evidence"
        assert row["confidence"].strip(), f"{name} row {i} ({row}) has empty confidence"


@pytest.mark.parametrize("name", VOCAB_FILES)
def test_confidence_values_are_from_the_closed_set(name: str) -> None:
    # D2: the confidence vocabulary is closed and has exactly four values, everywhere:
    # ('unverified', 'low', 'medium', 'high'). 'unverified' means asserted but never checked
    # against a source -- a real and common state, distinct from 'low' (checked, weak).
    for i, row in enumerate(read_tsv(name)):
        assert row["confidence"] in CONFIDENCE_VALUES, (
            f"{name} row {i} has confidence={row['confidence']!r}, not one of {CONFIDENCE_VALUES}"
        )


def test_unverified_confidence_is_actually_used_somewhere() -> None:
    """D2: 'unverified' is a real, common state -- not merely a legal-but-unused value."""
    found_in = {
        name for name in VOCAB_FILES for row in read_tsv(name) if row["confidence"] == "unverified"
    }
    assert found_in, "expected at least one vocabulary row to use confidence='unverified'"


def test_high_confidence_never_rests_solely_on_an_internal_fermdb_citation() -> None:
    """Evidence honesty: citing another fermdb file is 'memory with an extra hop' (this is why
    compartments.tsv was rewritten -- see its header). A row may claim 'high' only when its
    evidence names something actually checked outside the repo in this session -- a web search, a
    database lookup, a named external standard. A row whose evidence is entirely fermdb-internal
    citations (PLAN.md, CONVENTIONS.md, a source module, another vocabulary TSV) must not be
    'high'.
    """
    external_markers = ("web search", "verified against", "ncbi", "chebi", "http")
    for name in VOCAB_FILES:
        for i, row in enumerate(read_tsv(name)):
            if row["confidence"] != "high":
                continue
            evidence_lower = row["evidence"].lower()
            assert any(marker in evidence_lower for marker in external_markers), (
                f"{name} row {i} claims confidence='high' but its evidence "
                f"({row['evidence']!r}) does not name anything checked outside the fermdb repo"
            )


# --------------------------------------------------------------------------- tri-state values


def test_na_and_unknown_survive_parsing_as_literal_strings() -> None:
    """Guards against the pandas NA-sniffing trap the module docstring warns about."""
    units = read_tsv("units.tsv")
    na_rows = [r for r in units if r["entry_type"] == "unit"]
    assert na_rows, "expected at least one 'unit' row in units.tsv"
    assert all(r["from_unit"] == "NA" for r in na_rows)

    unknown_rows = [r for r in units if r["code"] == "OD600 -> g/L (biomass)"]
    assert len(unknown_rows) == 1
    assert unknown_rows[0]["factor"] == "unknown"


# --------------------------------------------------------------------------- compartments.tsv


def test_compartments_tsv_agrees_exactly_with_the_genetic_code_module() -> None:
    """compartments.tsv must mirror src/fermdb/genetic_code.py::COMPARTMENT_ENCODING_GENOMES
    exactly (D1: the genetic code follows the encoding genome, not the compartment).

    Not just "consistent with" -- exact agreement, key-for-key and value-for-value, so that a
    loader can trust this file instead of importing the code module.
    """
    rows = read_tsv("compartments.tsv")
    from_file = {r["compartment"]: tuple(r["encoding_genomes"].split("|")) for r in rows}
    assert from_file == COMPARTMENT_ENCODING_GENOMES
    assert len(rows) == len(COMPARTMENT_ENCODING_GENOMES), (
        "compartments.tsv has a duplicate or extra row"
    )


def test_compartments_tsv_genetic_code_tables_match_encoding_genome_table() -> None:
    """Each row's genetic_code_tables must be exactly ENCODING_GENOME_TABLE applied to its
    encoding_genomes, in the same order -- the code table follows the genome, not the compartment.
    """
    for row in read_tsv("compartments.tsv"):
        genomes = row["encoding_genomes"].split("|")
        tables = [int(t) for t in row["genetic_code_tables"].split("|")]
        expected = [ENCODING_GENOME_TABLE[g] for g in genomes]
        assert tables == expected, f"{row['compartment']}: genetic_code_tables mismatch"


def test_mitochondrial_ims_is_nuclear_only() -> None:
    """D1: mitochondrial_ims previously (wrongly) claimed table 3 at 'high' confidence; it is
    nuclear-only (table 1)."""
    rows = {r["compartment"]: r for r in read_tsv("compartments.tsv")}
    assert rows["mitochondrial_ims"]["encoding_genomes"] == "nuclear"
    assert rows["mitochondrial_ims"]["genetic_code_tables"] == "1"


def test_mitochondrial_inner_membrane_is_present_and_dual_genome() -> None:
    rows = {r["compartment"]: r for r in read_tsv("compartments.tsv")}
    assert "mitochondrial_inner_membrane" in rows
    assert rows["mitochondrial_inner_membrane"]["encoding_genomes"] == "nuclear|mitochondrial"


def test_compartments_served_by_both_genomes_are_exactly_matrix_and_inner_membrane() -> None:
    dual = {r["compartment"] for r in read_tsv("compartments.tsv") if "|" in r["encoding_genomes"]}
    assert dual == {"mitochondrial_matrix", "mitochondrial_inner_membrane"}


# --------------------------------------------------------------------------- products.tsv


def _product_row(rows: list[dict[str, str]], product_id: str) -> dict[str, str]:
    matches = [r for r in rows if r["id"] == product_id]
    assert len(matches) == 1, f"expected exactly one row with id={product_id!r}, found {matches}"
    return matches[0]


def test_product_tiers_match_plan_b1() -> None:
    rows = read_tsv("products.tsv")
    by_tier: dict[str, set[str]] = {}
    for r in rows:
        by_tier.setdefault(r["tier"], set()).add(r["name"])

    assert by_tier["primary"] == {"isobutanol"}
    assert by_tier["reference"] == {"ethanol"}
    assert by_tier["adjacent"] == {
        "isoamyl alcohol (3-methyl-1-butanol)",
        "2-methyl-1-butanol",
        "n-butanol (1-butanol)",
        "1-propanol",
    }
    assert by_tier["reserved"] == {"2,3-butanediol", "lactate", "succinate", "itaconate"}


def test_products_tsv_no_longer_names_a_glucose_specific_column() -> None:
    """D5: glucose must stop being an unnamed assumption baked into a column name."""
    rows = read_tsv("products.tsv")
    fieldnames = set(rows[0].keys())
    assert not any("glucose" in f.lower() for f in fieldnames)
    assert "theoretical_yield_g_per_g" not in fieldnames
    assert "theoretical_yield_mol_per_mol" not in fieldnames


# --------------------------------------------------------------------------- theoretical_yields.tsv


def _yield_row(rows: list[dict[str, str]], product_id: str, substrate: str) -> dict[str, str]:
    matches = [r for r in rows if r["product_id"] == product_id and r["substrate"] == substrate]
    assert len(matches) == 1, (
        f"expected exactly one row with product_id={product_id!r}, substrate={substrate!r}, "
        f"found {matches}"
    )
    return matches[0]


def test_glucose_is_a_named_substrate_not_a_column_name() -> None:
    rows = read_tsv("theoretical_yields.tsv")
    assert rows, "theoretical_yields.tsv has no data rows"
    fieldnames = set(rows[0].keys())
    assert not any("glucose" in f.lower() for f in fieldnames), (
        f"glucose must be a value in a 'substrate' column, not part of a column name: {fieldnames}"
    )
    assert {r["substrate"] for r in rows} == {"glucose"}


def test_theoretical_yields_keyed_uniquely_by_product_and_substrate() -> None:
    rows = read_tsv("theoretical_yields.tsv")
    keys = [(r["product_id"], r["substrate"]) for r in rows]
    assert len(keys) == len(set(keys)), (
        "duplicate (product_id, substrate) key in theoretical_yields.tsv"
    )
    # Every product in products.tsv has a corresponding glucose yield row.
    product_ids = {r["id"] for r in read_tsv("products.tsv")}
    yield_ids = {r["product_id"] for r in rows}
    assert product_ids == yield_ids


def test_ethanol_and_isobutanol_theoretical_yields_are_exact() -> None:
    yields = read_tsv("theoretical_yields.tsv")

    ethanol = _yield_row(yields, "YAA:PRODUCT:ethanol", "glucose")
    isobutanol = _yield_row(yields, "YAA:PRODUCT:isobutanol", "glucose")

    assert ethanol["state"] == "recorded"
    assert isobutanol["state"] == "recorded"
    assert round(float(ethanol["g_per_g"]), 3) == 0.511
    assert round(float(isobutanol["g_per_g"]), 3) == 0.411

    # The stored yield must actually follow from the stored MWs and stoichiometry -- a curated
    # number that silently drifts from its own inputs is worse than an admittedly 'unknown' one.
    substrate_mw = float(ethanol["substrate_mw_g_mol"])
    assert substrate_mw == float(isobutanol["substrate_mw_g_mol"])
    ethanol_recomputed = (
        float(ethanol["mol_per_mol"]) * float(ethanol["product_mw_g_mol"])
    ) / substrate_mw
    isobutanol_recomputed = (
        float(isobutanol["mol_per_mol"]) * float(isobutanol["product_mw_g_mol"])
    ) / substrate_mw
    assert round(ethanol_recomputed, 3) == 0.511
    assert round(isobutanol_recomputed, 3) == 0.411


def test_unresolved_theoretical_yields_have_null_numerics_and_state_unknown() -> None:
    """D3 applied to theoretical yields: the numeric fields are NULL unless state='recorded';
    'unknown' is recorded-as-attempted, never coerced to blank-with-no-explanation or to zero."""
    products = read_tsv("products.tsv")
    yields = read_tsv("theoretical_yields.tsv")
    unresolved_slugs = [
        "YAA:PRODUCT:3-methyl-1-butanol",
        "YAA:PRODUCT:2-methyl-1-butanol",
        "YAA:PRODUCT:1-propanol",
        "YAA:PRODUCT:succinate",
        "YAA:PRODUCT:itaconate",
    ]
    assert len(unresolved_slugs) == 5
    for pid in unresolved_slugs:
        _product_row(products, pid)  # sanity: the product itself exists
        row = _yield_row(yields, pid, "glucose")
        assert row["state"] == "unknown"
        assert row["g_per_g"] == "", f"{pid}: g_per_g must be NULL (blank) when state='unknown'"
        assert row["mol_per_mol"] == "", f"{pid}: mol_per_mol must be NULL when state='unknown'"
        assert row["stoichiometry"] == "unknown"
        assert row["stoichiometry"] != "0"

    # And every other product's yield is 'recorded', never silently left in a third state.
    resolved = {r["product_id"] for r in yields if r["state"] == "recorded"}
    assert resolved == {r["id"] for r in products} - set(unresolved_slugs)


def test_theoretical_yields_state_is_two_valued() -> None:
    allowed = {"recorded", "unknown"}
    for row in read_tsv("theoretical_yields.tsv"):
        assert row["state"] in allowed, f"unexpected state {row['state']!r}"


# --------------------------------------------------------------------------- assay_types.tsv


def test_required_assay_types_are_present_and_flagged_non_interconvertible() -> None:
    required = {
        "growth_rate_in_x_percent",
        "viability_after_shock",
        "IC50",
        "MIC",
        "lag_extension",
        "spot_dilution",
        "adapted_growth",
    }
    rows = {r["assay_type"]: r for r in read_tsv("assay_types.tsv")}
    missing = required - rows.keys()
    assert not missing, f"assay_types.tsv is missing required assay types: {missing}"
    for name in required:
        assert "NOT interconvertible" in rows[name]["note"], (
            f"{name} does not state it is non-interconvertible with the other assay types"
        )


# --------------------------------------------------------------------------- predicates.tsv


def test_predicates_match_plan_j2_closed_set() -> None:
    expected = {
        "affects_production_of",
        "affects_tolerance_to",
        "affects_yield_of",
        "catalyzes",
        "transports",
        "regulates",
        "is_expressed_under",
        "is_differentially_expressed_in",
        "co_expressed_with",
        "is_bottleneck_for",
        "competes_with",
        "is_required_for",
        "confers_resistance_to",
        "is_localized_to",
        "has_variant_associated_with",
        "improves_when_modified_by",
        "interacts_with",
    }
    found = {r["predicate"] for r in read_tsv("predicates.tsv")}
    assert found == expected


# --------------------------------------------------------------------------- evidence_types.tsv


def test_ai_inference_forbids_measurement_id() -> None:
    """Mirrors the CHECK constraint PLAN.md J.3 requires at the schema layer."""
    rows = {r["evidence_type"]: r for r in read_tsv("evidence_types.tsv")}
    assert "measurement_id" in rows["ai_inference"]["forbidden_fields"]


# --------------------------------------------------------------------------- condition_facets.tsv


def _condition_context_columns() -> set[str]:
    """Column names declared on the `condition_context` table in schema.sql.

    Read directly from the schema (not from PLAN.md or memory) so condition_facets.tsv's
    `storage_location` can be checked against what the database actually does, rather than against
    another guess. This only reads schema.sql; it never writes to it.
    """
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    start = text.index("CREATE TABLE condition_context (")
    end = text.index("CREATE TABLE condition_context_facet", start)
    body = text[start:end]
    columns: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("--", "CREATE", "CHECK", ")")):
            continue
        name = line.split()[0].rstrip(",")
        if name:
            columns.add(name)
    return columns


def test_condition_facets_tsv_has_storage_location_column() -> None:
    rows = read_tsv("condition_facets.tsv")
    assert rows, "condition_facets.tsv has no data rows"
    assert "storage_location" in rows[0]
    allowed = {"condition_context", "condition_context_facet"}
    for i, row in enumerate(rows):
        assert row["storage_location"] in allowed, (
            f"condition_facets.tsv row {i} ({row['field']!r}) has storage_location="
            f"{row['storage_location']!r}, not one of {allowed}"
        )


def test_condition_facets_storage_location_matches_schema() -> None:
    """A facet claiming storage_location='condition_context' must name a column that actually
    exists on that table in schema.sql -- this is exactly the drift ("two loaders would otherwise
    guess differently and break context_hash dedup") this column exists to prevent.
    """
    columns = _condition_context_columns()
    assert columns, "expected to find condition_context's column list in schema.sql"
    for row in read_tsv("condition_facets.tsv"):
        if row["storage_location"] != "condition_context":
            continue
        base = row["field"].replace(".", "_")
        assert base in columns, (
            f"condition_facets.tsv field {row['field']!r} claims storage_location="
            "'condition_context' but schema.sql has no such column on condition_context"
        )


def test_struct_and_reference_facets_are_overflow() -> None:
    """A struct (array-valued) or reference facet has no single scalar column to live in, so it
    must be stored in the condition_context_facet overflow table."""
    for row in read_tsv("condition_facets.tsv"):
        if row["type"] in {"struct", "reference"}:
            assert row["storage_location"] == "condition_context_facet", (
                f"{row['field']!r} is type={row['type']!r} but claims a first-class column"
            )
