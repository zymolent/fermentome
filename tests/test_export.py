"""Tests for `fermdb.export` -- PLAN.md T.5's release bundle.

T.5's acceptance test is not "a directory appeared". It is one sentence: *"Zone I content
exports separately and is labelled as inference in the export itself, not only in the
documentation."* So the tests that matter here are the ones that try to break that guarantee,
and each of them is written to fail in a specific, recoverable way rather than to confirm that
the happy path happened:

* :func:`test_no_file_mixes_two_zones` and :func:`test_inferred_directory_holds_only_zone_i` --
  the separation as a property of the filesystem, asserted over *every* file in the bundle
  rather than over the one the test author remembered to look at.
* :func:`test_every_fact_row_carries_its_own_zone` -- the separation as a property of the rows.
  This is the test that survives someone concatenating the data files, which is exactly what a
  downstream consumer will eventually do.
* :func:`test_inference_is_labelled_without_reading_the_filename` -- the labelling with the
  directory deliberately thrown away, because "labelled in the export itself, not only in the
  documentation" means the row, not the path.
* :func:`test_the_three_absences_stay_three` -- CONVENTIONS.md "Missing values". The fixture
  plants one `product_theoretical_yield` row per state, and this asserts the export keeps them
  apart both as raw JSON (`null` / `"NA"` / `"unknown"`) and in the `_absence` map. Collapsing
  them is the failure PLAN.md P.4 exists to prevent and it is invisible in a row count.
* :func:`test_evidence_levels_travel_with_the_rows` -- L1-L5 *with the basis*, because the
  `assertion_level` view returns NULL for two opposite reasons.

And the ones about being citable rather than about zones: the crate's shape, the digest's
stability across two exports of one database, and the refusal to half-overwrite an existing
bundle.

Everything runs against the phase-0 fixture atlas (`tests/fixtures/mini_atlas`) loaded into an
in-memory database, the same way `tests/test_fixture.py` and `tests/test_traceability.py` build
theirs. Nothing here touches the real atlas and nothing needs a network.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, SCHEMA_VERSION, open_db, schema_sql
from fermdb.db.fixture import load_fixture
from fermdb.export import build_release
from fermdb.export.crate import CRATE_SPEC_IMPLEMENTED, CRATE_SPEC_NOT_IMPLEMENTED
from fermdb.export.release import (
    UNZONED_DIRECTORY,
    ZONE_DIRECTORIES,
    Bundle,
    ExportError,
    _absence_of,
)
from fermdb.query.traceability import walk_assertions

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mini_atlas"


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    """The phase-0 mini-atlas, in memory. Read-only as far as this module is concerned."""
    conn = open_db(IN_MEMORY)
    load_fixture(conn, FIXTURE_DIR)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def bundle(atlas: sqlite3.Connection, tmp_path: Path) -> Bundle:
    return build_release(
        atlas,
        tmp_path / "release",
        repo_root=Path(__file__).resolve().parents[1],
        annotation_sources_file=(
            Path(__file__).resolve().parents[1] / "data" / "annotation" / "annotation_sources.yaml"
        ),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    return payload


def data_files(bundle: Bundle) -> list[Path]:
    return sorted(bundle.root.glob("data/*/*.jsonl"))


# ------------------------------------------------------------------- the rule that matters most


def test_no_file_mixes_two_zones(bundle: Bundle) -> None:
    """Asserted over every data file, not over the one the test remembered to check.

    A bundle that separated Zone I from the two tables someone thought of and interleaved it
    everywhere else would pass a narrower test and fail the guarantee.
    """
    for path in data_files(bundle):
        zones = {row["_zone"] for row in read_jsonl(path)}
        assert len(zones) == 1, f"{path.relative_to(bundle.root)} holds zones {sorted(zones)}"


def test_inferred_directory_holds_only_zone_i(bundle: Bundle) -> None:
    inferred = bundle.root.joinpath(*ZONE_DIRECTORIES["I"].split("/"))
    files = sorted(inferred.glob("*.jsonl"))
    assert files, "the fixture carries Zone I rows; the export wrote no inferred files"
    for path in files:
        for row in read_jsonl(path):
            assert row["_zone"] == "I"
            assert row["zone"] == "I", "the stored column and the injected label must agree"


def test_reported_and_harmonized_files_carry_no_inference(bundle: Bundle) -> None:
    for zone in ("R", "H"):
        directory = bundle.root.joinpath(*ZONE_DIRECTORIES[zone].split("/"))
        for path in directory.glob("*.jsonl"):
            for row in read_jsonl(path):
                assert row["_is_inference"] is False
                assert row["_may_support_a_conclusion"] is True


def test_every_fact_row_carries_its_own_zone(bundle: Bundle) -> None:
    """The zone is a field, not a filename. This is the test that survives `cat *.jsonl`."""
    seen = 0
    for path in data_files(bundle):
        for row in read_jsonl(path):
            assert "_zone" in row
            assert "_zone_label" in row
            assert "_is_inference" in row
            seen += 1
    assert seen == bundle.n_rows


def test_inference_is_labelled_without_reading_the_filename(bundle: Bundle) -> None:
    """Throw the paths away, keep the rows, and Zone I must still be identifiable.

    T.5 says "labelled as inference in the export itself, not only in the documentation". A
    directory name *is* documentation as soon as the file is copied out of it.
    """
    rows = [row for path in data_files(bundle) for row in read_jsonl(path)]
    inferred = [row for row in rows if row["_is_inference"]]
    assert inferred, "the fixture carries Zone I rows and none came back labelled"
    for row in inferred:
        assert row["_zone"] == "I"
        assert row["_zone_label"] == "inferred"
        assert row["_may_support_a_conclusion"] is False
    assert len(inferred) == bundle.n_inferred_rows


def test_manifest_counts_the_zeros_too(bundle: Bundle) -> None:
    """An absent `data/inferred/<table>.jsonl` must mean "no Zone I rows", not "not exported"."""
    manifest = read_json(bundle.root / "manifest.json")
    tables = {entry["table"]: entry for entry in manifest["tables"]}
    strain = tables["strain"]
    assert strain["zoned"] is True
    assert set(strain["by_zone"]) >= {"R", "H", "I"}
    assert strain["by_zone"]["I"] == 0
    assert "I" not in strain["files"]
    assert not (bundle.root / "data" / "inferred" / "strain.jsonl").exists()


def test_unzoned_tables_are_filed_apart_and_claim_nothing(bundle: Bundle) -> None:
    """`predicate` is a vocabulary and `processing_run` is not a claim; neither gets a zone."""
    path = bundle.root.joinpath(*UNZONED_DIRECTORY.split("/")) / "predicate.jsonl"
    rows = read_jsonl(path)
    assert rows
    for row in rows:
        assert row["_zone"] is None
        assert row["_zone_label"] == "not_zoned"
        # The key is absent rather than null: "may this support a conclusion" is a malformed
        # question for a vocabulary row, and answering it with null would add a fourth meaning to
        # a field whose whole job is to have three.
        assert "_may_support_a_conclusion" not in row


# ------------------------------------------------------------------- CONVENTIONS.md's three states


def test_the_three_absences_stay_three(bundle: Bundle) -> None:
    """NULL, 'NA' and 'unknown' are three facts. The fixture plants one row in each state."""
    rows = read_jsonl(bundle.root / "data" / "reported" / "product_theoretical_yield.jsonl")
    states = {
        row["substrate"]: row.get("_absence", {}).get("mol_per_mol", "recorded") for row in rows
    }
    assert set(states.values()) == {"recorded", "not_applicable", "unknown"}, (
        "the fixture carries one theoretical-yield row per missing-value state and the export "
        f"flattened them to {sorted(set(states.values()))}"
    )

    by_state = {state: substrate for substrate, state in states.items()}
    recorded = next(row for row in rows if row["substrate"] == by_state["recorded"])
    not_applicable = next(row for row in rows if row["substrate"] == by_state["not_applicable"])
    unknown = next(row for row in rows if row["substrate"] == by_state["unknown"])

    # The numeric is NULL in two of the three, so the raw JSON alone cannot separate them --
    # which is precisely why the state companion travels and why `_absence` exists.
    assert recorded["mol_per_mol"] is not None
    assert not_applicable["mol_per_mol"] is None
    assert unknown["mol_per_mol"] is None
    assert not_applicable["mol_per_mol_state"] == "not_applicable"
    assert unknown["mol_per_mol_state"] == "unknown"


def test_the_literal_strings_survive_the_round_trip(bundle: Bundle) -> None:
    """'NA' and 'unknown' are stored as strings and must arrive as strings, not as null."""
    rows = [row for path in data_files(bundle) for row in read_jsonl(path)]
    literals = {
        value
        for row in rows
        for key, value in row.items()
        if not key.startswith("_") and value in ("NA", "unknown")
    }
    assert literals, "the fixture stores the two absence literals and none reached the export"


def test_a_state_companion_that_disagrees_is_an_anomaly_not_a_repair() -> None:
    """A mismatched pair is exported as stored and named, never quietly fixed.

    `query.values.from_state_column` raises on this, which is right for a reader serving one
    record and wrong for an export, where one bad row must not cost the other hundred thousand.
    """
    absence, detail = _absence_of(None, state="recorded", has_state=True)
    assert absence == "not_recorded"
    assert detail is not None and "recorded" in detail

    absence, detail = _absence_of(1.5, state=None, has_state=True)
    assert detail is not None and "mismatched" in detail

    assert _absence_of("NA", state=None, has_state=False) == ("not_applicable", None)
    assert _absence_of("unknown", state=None, has_state=False) == ("unknown", None)
    assert _absence_of(None, state=None, has_state=False) == ("not_recorded", None)
    assert _absence_of(0.0, state=None, has_state=False) == (None, None)


def test_zero_is_not_an_absence(bundle: Bundle) -> None:
    """The other half of the same rule: never coerce an absence into zero, or zero into one."""
    assert _absence_of(0, state=None, has_state=False) == (None, None)
    assert _absence_of(0.0, state="recorded", has_state=True) == (None, None)


# ------------------------------------------------------------------------------ evidence levels


def test_evidence_levels_travel_with_the_rows(bundle: Bundle) -> None:
    """L1-L5 on the assertion row itself, with the basis that produced it."""
    rows = [
        row
        for path in data_files(bundle)
        for row in read_jsonl(path)
        if row["_table"] == "assertion"
    ]
    assert rows
    for row in rows:
        level = row["_level"]
        assert level["basis"], "an ungraded level that cannot say why is not permitted to exist"
        if level["level"] is None:
            assert level["basis"] in {"no_evidence", "direct_evidence_discordant"}

    levels = {row["id"]: row["_level"]["level"] for row in rows}
    # The fixture's centrepiece pair: a direct_perturbation-backed assertion grades L1 and the
    # AI-only one in Zone I grades L5. If the export ever dropped the level, both become None and
    # the atlas's whole evidence story leaves the bundle silently.
    assert "L1" in levels.values()
    assert "L5" in levels.values()

    inferred = [row for row in rows if row["_is_inference"]]
    assert inferred and all(row["_level"]["level"] == "L5" for row in inferred)


def test_the_level_view_ships_in_full(bundle: Bundle) -> None:
    view_rows = read_jsonl(bundle.root / "provenance" / "evidence_levels.jsonl")
    assert view_rows
    for row in view_rows:
        assert row["_view"] is True
        assert "derived_reason" in row
        assert "n_evidence" in row


# ------------------------------------------------------------------------- the provenance graph


def test_provenance_ships_the_same_walk_the_ci_gate_runs(
    bundle: Bundle, atlas: sqlite3.Connection
) -> None:
    """Reused from `query.traceability`, not re-derived: one definition of a complete chain."""
    payload = read_json(bundle.root / "provenance" / "traceability.json")
    assert payload["walk"] == walk_assertions(atlas).as_json()
    assert payload["walk"]["n_walked"] > 0, "a vacuous walk would prove nothing here"
    assert "vacuous" in payload["walk"]
    # Breaks and gaps travel. A bundle shipping only the chains that closed would be claiming a
    # completeness the atlas does not have.
    assert "breaks_by_kind" in payload["walk"]
    assert "gaps_by_kind" in payload["walk"]


def test_processing_runs_and_versions_are_present_even_when_empty(bundle: Bundle) -> None:
    """The fixture holds no processing_run rows, and the bundle must say so rather than omit it.

    An absent file reads as "not exported"; an empty one with a note reads as "nothing to
    export", and those are different claims about the atlas.
    """
    assert (bundle.root / "provenance" / "processing_runs.jsonl").exists()
    versions = read_json(bundle.root / "provenance" / "versions.json")
    assert versions["pipelines"] == []
    assert "no processing_run rows" in versions["pipeline_versions_note"]
    assert versions["schema"]["database_version"] == SCHEMA_VERSION
    assert versions["fermdb"]


def test_schema_ships_verbatim_with_its_version(bundle: Bundle) -> None:
    ddl = (bundle.root / "schema" / "schema.sql").read_text(encoding="utf-8")
    assert ddl == schema_sql()
    manifest = read_json(bundle.root / "manifest.json")
    assert manifest["schema_version"] == SCHEMA_VERSION

    tables = read_json(bundle.root / "schema" / "tables.json")
    shapes = {entry["table"]: entry for entry in tables["tables"]}
    assert shapes["product_theoretical_yield"]["primary_key"] == ["product_id", "substrate"]
    assert shapes["product_theoretical_yield"]["state_companions"]["mol_per_mol"] == (
        "mol_per_mol_state"
    )
    assert "assertion_level" in tables["views"]


def test_licence_terms_are_per_source_and_are_not_invented(bundle: Bundle) -> None:
    licences = read_json(bundle.root / "provenance" / "licences.json")
    external = licences["external_annotation_sources"]
    assert external["read"] is True
    assert external["sources"], "data/annotation/annotation_sources.yaml holds rows"
    assert {"id", "license", "redistributable"} <= set(external["sources"][0])
    # KEGG is marked non-redistributable in that file, and the export must carry the restriction
    # rather than flattening every source to a single bundle licence.
    assert any(source["redistributable"] is False for source in external["sources"])

    # NULL and 'unknown' are different licence facts and the grouping keeps them apart.
    for group in licences["publications"]["by_license"]:
        if group["value"] is None:
            assert group["absent"] == "not_recorded"

    # The repository declares no licence file, and the bundle says exactly that rather than
    # assuming permissive terms on the project's behalf.
    assert licences["bundle"]["declared"] is False
    assert "quoted_text_warning" in licences


# --------------------------------------------------------------------------------- the RO-Crate


def test_crate_has_the_shape_ro_crate_requires(bundle: Bundle) -> None:
    crate = read_json(bundle.root / "ro-crate-metadata.json")
    assert crate["@context"] == "https://w3id.org/ro/crate/1.1/context"
    graph = {entity["@id"]: entity for entity in crate["@graph"]}

    descriptor = graph["ro-crate-metadata.json"]
    assert descriptor["@type"] == "CreativeWork"
    assert descriptor["conformsTo"] == {"@id": "https://w3id.org/ro/crate/1.1"}
    assert descriptor["about"] == {"@id": "./"}

    root = graph["./"]
    assert root["@type"] == "Dataset"
    for required in ("name", "description", "datePublished", "license"):
        assert root[required], f"RO-Crate requires {required} on the root data entity"
    assert root["identifier"] == f"urn:sha256:{bundle.digest}"


def test_crate_hasPart_reaches_every_file_and_dangles_nowhere(bundle: Bundle) -> None:
    crate = read_json(bundle.root / "ro-crate-metadata.json")
    graph = {entity["@id"]: entity for entity in crate["@graph"]}

    reached: set[str] = set()
    frontier = ["./"]
    while frontier:
        entity = graph[frontier.pop()]
        for part in entity.get("hasPart", []):
            target = part["@id"]
            assert target in graph, f"hasPart points at {target}, which is not in the graph"
            if target not in reached:
                reached.add(target)
                frontier.append(target)

    files = {record.path for record in bundle.files if record.path != "ro-crate-metadata.json"}
    assert files <= reached, f"not reachable from the root: {sorted(files - reached)}"

    for entity in crate["@graph"]:
        if entity["@type"] == "File":
            assert entity["name"] and entity["description"] and entity["encodingFormat"]


def test_the_crate_says_what_it_does_not_implement(bundle: Bundle) -> None:
    """A conformance claim nobody verified is a lie with good intentions; the bundle carries both.

    This is asserted rather than left to a reviewer because the temptation, the next time
    somebody adds an entity type, is to quietly widen the claim without widening the check.
    """
    manifest = read_json(bundle.root / "manifest.json")
    assert manifest["ro_crate"]["implemented"] == list(CRATE_SPEC_IMPLEMENTED)
    assert manifest["ro_crate"]["not_implemented"] == list(CRATE_SPEC_NOT_IMPLEMENTED)
    assert any("NOT VALIDATED" in line for line in manifest["ro_crate"]["not_implemented"])
    assert any("ro-crate-preview.html" in line for line in manifest["ro_crate"]["not_implemented"])


def test_the_inferred_directory_is_described_as_inference_in_the_crate(bundle: Bundle) -> None:
    crate = read_json(bundle.root / "ro-crate-metadata.json")
    graph = {entity["@id"]: entity for entity in crate["@graph"]}
    assert "INFERRED" in graph["data/inferred/"]["description"]
    assert "INFERRED" in graph["./"]["description"]


# ------------------------------------------------------------------- citing a state of the atlas


def test_one_database_exports_to_one_digest(atlas: sqlite3.Connection, tmp_path: Path) -> None:
    """ "Cite a specific state of the atlas" (T.5) only works if the state has one name.

    Two exports of one unchanged database must agree byte for byte, which also means the export
    may not smuggle a timestamp, a set iteration order or a path separator into the payload.
    Newlines are forced to LF for the same reason -- a digest that differs between Windows and
    Linux is not a content hash.
    """
    stamp = None
    first = build_release(atlas, tmp_path / "one", generated_at=stamp)
    second = build_release(atlas, tmp_path / "two", generated_at=stamp)
    assert first.digest == second.digest

    for record in first.files:
        if record.path in {"README.md", "manifest.json", "ro-crate-metadata.json"}:
            continue  # these carry generated_at, which is the timestamp and not the payload
        assert record.sha256 == second.file(record.path).sha256, record.path

    manifest = read_json(first.root / "manifest.json")
    assert manifest["bundle_digest"] == f"sha256:{first.digest}"
    covered = set(manifest["bundle_digest_covers"])
    assert "manifest.json" not in covered
    assert "ro-crate-metadata.json" not in covered


def test_no_release_id_is_recorded_as_such_not_invented(bundle: Bundle) -> None:
    manifest = read_json(bundle.root / "manifest.json")
    assert manifest["release"]["id"] is None
    assert "vYYYY.N" in manifest["release"]["why"]


def test_a_release_id_reaches_the_crate(atlas: sqlite3.Connection, tmp_path: Path) -> None:
    built = build_release(atlas, tmp_path / "release", release="v2026.1")
    crate = read_json(built.root / "ro-crate-metadata.json")
    root = next(entity for entity in crate["@graph"] if entity["@id"] == "./")
    assert root["version"] == "v2026.1"
    assert read_json(built.root / "manifest.json")["release"]["id"] == "v2026.1"


# ----------------------------------------------------------------------------------- refusals


def test_a_non_empty_directory_is_refused_without_force(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """Half an old bundle under a new manifest describes neither, and the digest hides it."""
    target = tmp_path / "release"
    target.mkdir()
    (target / "leftover.txt").write_text("from an earlier export", encoding="utf-8")

    with pytest.raises(ExportError, match="not empty"):
        build_release(atlas, target)

    built = build_release(atlas, target, force=True)
    assert (built.root / "manifest.json").exists()


def test_a_column_colliding_with_the_label_namespace_is_refused(tmp_path: Path) -> None:
    """The injected `_` keys are a reserved namespace, and a collision would overwrite a fact.

    Nothing in schema.sql starts a column with an underscore today. If that ever changes the
    export must stop, because a row whose `_zone` is a stored column and whose zone label was
    silently dropped is corrupt in a way no reader can detect.
    """
    conn = open_db(IN_MEMORY)
    try:
        conn.execute("CREATE TABLE odd (id TEXT PRIMARY KEY, _zone TEXT)")
        with pytest.raises(ExportError, match="reserves"):
            build_release(conn, tmp_path / "release")
    finally:
        conn.close()


def test_an_unrecognised_zone_is_exported_as_inference_and_named(tmp_path: Path) -> None:
    """A zone outside R/H/I is not reported content, and the export refuses to imply it is.

    A CHECK constraint makes this unreachable through `schema.sql`'s own tables, so the test
    builds a table without one -- which is the state that produces the row in the first place: a
    constraint that was bypassed, or a table added without it.
    """
    conn = open_db(IN_MEMORY)
    try:
        conn.execute("CREATE TABLE odd_fact (id TEXT PRIMARY KEY, zone TEXT NOT NULL)")
        conn.execute("INSERT INTO odd_fact (id, zone) VALUES ('x', 'Z'), ('y', 'Q')")
        built = build_release(conn, tmp_path / "release")
    finally:
        conn.close()

    # Two different bad values, and neither may overwrite the other: losing a row is the last
    # thing this export should do in the one case where the atlas is already known to be wrong.
    directory = built.root / "data" / "zone-unrecognised"
    assert sorted(path.name for path in directory.glob("*.jsonl")) == [
        "odd_fact.zone-Q.jsonl",
        "odd_fact.zone-Z.jsonl",
    ]
    rows = [row for path in sorted(directory.glob("*.jsonl")) for row in read_jsonl(path)]
    assert len(rows) == 2
    for row in rows:
        assert row["_is_inference"] is True
        assert row["_may_support_a_conclusion"] is False
        assert row["_zone_label"] == "unrecognised"

    assert len([a for a in built.anomalies if "not one of R/H/I" in a.detail]) == 2
    manifest = read_json(built.root / "manifest.json")
    assert manifest["anomalies"], "an anomaly must reach the manifest, not only the return value"


# ---------------------------------------------------------------------------------- the CLI


def test_the_cli_wires_export_release() -> None:
    from fermdb.cli import build_parser
    from fermdb.export.cli import cmd_export_release

    args = build_parser().parse_args(["export", "release", "--out", "somewhere"])
    assert args.func is cmd_export_release
    assert args.out == "somewhere"
    assert args.release is None
    assert args.force is False
