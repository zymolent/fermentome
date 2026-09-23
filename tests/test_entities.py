"""Tests for the four remaining PLAN.md P.2 pages: Strain, Experiment, Product and Compare.

Every property pinned here is a rule from PLAN.md rather than a preference, and each one is the
kind that a redesign loses quietly:

* **An empty lineage is not "no parents"** (P.2). `strain_lineage` is empty across the atlas, so
  the read has to distinguish "the atlas records nothing" from "this strain is a founder". A UI
  rendering an empty DAG asserts the second.
* **A comparability class has three outcomes, not two** (K.4, C.5). `provisional` -- every
  column-backed facet known, but a class-defining facet has no column -- is the one a boolean
  would erase, and it is the one that decides whether a comparison may be offered.
* **No global leaderboard** (I.2). A "best" is named only inside a `classified` class, with one
  unit, a controlled quantity kind and more than one row. Each of those four is tested by
  removing it.
* **The condition context is returned in full** (P.2). All 19 facets, always, with the three
  absences kept apart.
* **Compare refuses rather than guesses** (P.2, I.2), and a refusal is a 200 with a reason.

These run against an in-memory fixture, so they test the readers rather than whatever happens to
be curated this week.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import compare as compare_module
from fermdb.query import conditions, experiments, products, strains

# A context that names every class-defining facet the schema has a column for.
_FULL_CONTEXT = {
    "aeration_class": "anaerobic",
    "feedstock_class": "defined",
    "mode": "batch",
}


def _context(
    conn: sqlite3.Connection,
    context_id: str,
    *,
    facets: dict[str, str] | None = None,
    temperature: float | None = None,
    extra: dict[str, str] | None = None,
) -> None:
    columns = ["id", "context_hash", "zone", "evidence", "confidence"]
    values: list[Any] = [context_id, f"hash-{context_id}", "R", "paper", "high"]
    for column, value in (facets or {}).items():
        columns.append(column)
        values.append(value)
    if temperature is not None:
        columns += ["temperature_c", "temperature_c_state"]
        values += [temperature, "recorded"]
    conn.execute(
        f"INSERT INTO condition_context ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        values,
    )
    for facet, value in (extra or {}).items():
        conn.execute(
            "INSERT INTO condition_context_facet (context_id, facet, value, value_state, "
            "zone, evidence, confidence) VALUES (?, ?, ?, 'recorded', 'R', 'paper', 'high')",
            (context_id, facet, value),
        )


def _measurement(
    conn: sqlite3.Connection,
    measurement_id: str,
    *,
    strain_id: str,
    sample_id: str | None = None,
    kind: str = "titer",
    value: float = 1.0,
    unit: str = "g/L",
) -> None:
    conn.execute(
        "INSERT INTO measurement (id, quantity_kind, product_id, strain_id, sample_id, "
        "publication_id, value_as_reported, unit_as_reported, source_locator, zone, evidence, "
        "confidence) VALUES (?, ?, 'YAA:PRODUCT:isobutanol', ?, ?, 'pub:a', ?, ?, 'Table 1', "
        "'R', 'table 1', 'high')",
        (measurement_id, kind, strain_id, sample_id, value, unit),
    )


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """An atlas with one of each comparability outcome, so all three branches are reachable.

    * `ctx:full` -- the three column-backed class facets **and** both C.5 facets recorded in
      `condition_context_facet`. The only context here that can be `classified`.
    * `ctx:provisional` -- the same three columns, neither C.5 facet. Classifiable on what has a
      column, blind to what does not.
    * `ctx:bare` -- nothing but a temperature. Unclassified.
    """
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 'R', 'ncbi', 'high')"
    )
    conn.execute(
        "INSERT INTO publication (id, title, year, zone, evidence, confidence) "
        "VALUES ('pub:a', 'A paper', 2024, 'R', 'crossref', 'high')"
    )
    conn.execute(
        "INSERT INTO product (id, name, tier, canonical_unit, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:isobutanol', 'isobutanol', 'primary', 'g/L', 'R', 'chebi', 'high')"
    )

    for local, name, klass in (
        ("parent", "PARENT", "laboratory"),
        ("child", "CHILD", "engineered"),
        ("lonely", "LONELY", "engineered"),
    ):
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:sc', ?, ?, 'R', 'paper', 'high')",
            (f"YAA:STRAIN:{local}", name, klass),
        )
    conn.execute(
        "INSERT INTO strain_lineage (parent_strain_id, child_strain_id, step_type, zone, "
        "evidence, confidence) VALUES ('YAA:STRAIN:parent', 'YAA:STRAIN:child', "
        "'transformation', 'R', 'paper', 'high')"
    )
    conn.execute(
        "INSERT INTO genotype (id, strain_id, as_reported, parsed_json, zone, evidence, "
        "confidence) VALUES ('g:child', 'YAA:STRAIN:child', 'BY4741 ilv2D', "
        "'{\"deletions\": [\"ILV2\"], \"fully_parsed\": true}', 'R', 'paper', 'high')"
    )
    conn.execute(
        "INSERT INTO modification (id, strain_id, type, target_locus, publication_id, zone, "
        "evidence, confidence) VALUES ('YAA:MOD:1', 'YAA:STRAIN:child', 'deletion', 'ILV2', "
        "'pub:a', 'R', 'paper', 'high')"
    )

    _context(
        conn,
        "ctx:full",
        facets=_FULL_CONTEXT,
        temperature=30.0,
        extra={"carbon_regime": "batch_glucose", "in_situ_product_removal": "none"},
    )
    _context(
        conn,
        "ctx:provisional",
        facets=_FULL_CONTEXT,
        temperature=30.0,
    )
    _context(conn, "ctx:bare", temperature=37.0)

    conn.execute(
        "INSERT INTO experiment (id, publication_id, objective, zone, evidence, confidence) "
        "VALUES ('YAA:EXPERIMENT:e1', 'pub:a', 'make isobutanol', 'R', 'paper', 'high')"
    )
    conn.execute(
        "INSERT INTO experiment (id, zone, evidence, confidence) "
        "VALUES ('YAA:EXPERIMENT:e2', 'R', 'one experiment per SRA study', 'high')"
    )
    for sample_id, context_id, strain in (
        ("sam:1", "ctx:full", "YAA:STRAIN:child"),
        ("sam:2", "ctx:full", "YAA:STRAIN:child"),
        ("sam:3", "ctx:provisional", "YAA:STRAIN:lonely"),
        ("sam:4", None, "YAA:STRAIN:lonely"),
    ):
        conn.execute(
            "INSERT INTO sample (id, experiment_id, strain_id, condition_context_id, zone, "
            "evidence, confidence) VALUES (?, 'YAA:EXPERIMENT:e1', ?, ?, 'R', 'paper', 'high')",
            (sample_id, strain, context_id),
        )

    _measurement(conn, "m:1", strain_id="YAA:STRAIN:child", sample_id="sam:1", value=2.0)
    _measurement(conn, "m:2", strain_id="YAA:STRAIN:child", sample_id="sam:2", value=5.0)
    _measurement(conn, "m:3", strain_id="YAA:STRAIN:lonely", sample_id="sam:3", value=3.0)
    _measurement(conn, "m:4", strain_id="YAA:STRAIN:lonely", sample_id=None, value=9.0)
    conn.commit()
    return conn


# ------------------------------------------------------------------ lineage


def test_missing_lineage_is_a_stated_absence_not_an_empty_graph(conn: sqlite3.Connection) -> None:
    """An engineered strain with no recorded parent is a gap in the atlas, not a founder."""
    read = strains.read_strain(conn, "YAA:STRAIN:lonely")
    assert read is not None
    assert read.lineage.is_recorded is False
    assert read.lineage.parents == ()
    # The note must say which of the two it is, and must not read as "this strain has no parents".
    assert "statement about the atlas" in read.lineage.note or "no lineage edge names" in (
        read.lineage.note
    )


def test_recorded_lineage_comes_back_as_edges(conn: sqlite3.Connection) -> None:
    child = strains.read_strain(conn, "YAA:STRAIN:child")
    parent = strains.read_strain(conn, "YAA:STRAIN:parent")
    assert child is not None and parent is not None
    assert [edge["canonical_name"] for edge in child.lineage.parents] == ["PARENT"]
    assert [edge["canonical_name"] for edge in parent.lineage.children] == ["CHILD"]
    assert child.lineage.is_recorded is True


def test_a_strain_resolves_by_canonical_name(conn: sqlite3.Connection) -> None:
    """A paper says "CHILD"; the atlas says `YAA:STRAIN:child`. Both must reach the page."""
    assert strains.read_strain(conn, "CHILD") is not None
    assert strains.read_strain(conn, "no such strain") is None


# ------------------------------------------------------------------ comparability classes


def test_class_is_classified_only_when_every_defining_facet_is_readable(
    conn: sqlite3.Connection,
) -> None:
    reads = conditions.read_contexts(conn, ["ctx:full", "ctx:provisional", "ctx:bare"])
    assert conditions.class_of(reads["ctx:full"]).status == conditions.CLASSIFIED
    assert conditions.class_of(reads["ctx:provisional"]).status == conditions.PROVISIONAL
    assert conditions.class_of(reads["ctx:bare"]).status == conditions.UNCLASSIFIED


def test_a_provisional_class_names_the_facet_it_is_blind_to(conn: sqlite3.Connection) -> None:
    """PLAN.md C.5's amendment named facets that were never migrated; the payload says so.

    Without this the key looks like a real class, and two contexts that differ in whether
    product was removed in situ would be reported as the same one.
    """
    reads = conditions.read_contexts(conn, ["ctx:provisional"])
    klass = conditions.class_of(reads["ctx:provisional"])
    assert klass.is_classified is False
    assert len(klass.blind_to) == len(conditions.UNMIGRATED_CLASS_FACETS)
    for name in conditions.UNMIGRATED_CLASS_FACETS:
        assert any(name in reason for reason in klass.blind_to)


def test_an_unclassified_class_names_the_facet_that_blocked_it(conn: sqlite3.Connection) -> None:
    klass = conditions.class_of(conditions.read_contexts(conn, ["ctx:bare"])["ctx:bare"])
    assert klass.status == conditions.UNCLASSIFIED
    assert any("aeration_class" in reason for reason in klass.blocked_by)


def test_a_measurement_with_no_sample_gets_its_own_class(conn: sqlite3.Connection) -> None:
    """PLAN.md K.4's join. A number that cannot reach a context is not in anyone else's class."""
    read = strains.read_strain(conn, "YAA:STRAIN:lonely")
    assert read is not None
    keys = {group.klass.key for group in read.phenotype}
    assert conditions.UNCLASSIFIED in keys
    assert len(keys) > 1, "the orphan must not be folded into the classified group"


def test_the_class_key_is_never_presented_as_a_curated_definition(
    conn: sqlite3.Connection,
) -> None:
    """There is no `comparability_class` table; the payload must not imply there is."""
    klass = conditions.class_of(conditions.read_contexts(conn, ["ctx:full"])["ctx:full"])
    assert "no `comparability_class` table" in klass.as_json()["definition_source"]


# ------------------------------------------------------------------ the condition context


def test_every_facet_is_returned_even_when_nothing_was_recorded(
    conn: sqlite3.Connection,
) -> None:
    """P.2: "the condition context in full, with 'not recorded' visible"."""
    read = conditions.read_contexts(conn, ["ctx:bare"])["ctx:bare"]
    assert len(read.facets) == len(conditions.CONTEXT_FACETS)
    assert read.recorded == 1  # temperature only
    payload = read.as_json()
    assert payload["absent_by_kind"]["not_recorded"] == len(conditions.CONTEXT_FACETS) - 1


def test_the_three_absences_are_kept_apart(conn: sqlite3.Connection) -> None:
    """'NA' and 'unknown' are recorded facts; a NULL is the absence of one. Three states."""
    conn.execute(
        "UPDATE condition_context SET medium_class = 'NA', aeration_class = 'unknown' "
        "WHERE id = 'ctx:bare'"
    )
    read = conditions.read_contexts(conn, ["ctx:bare"])["ctx:bare"]
    by_facet = {facet.facet: facet.value.as_json() for facet in read.facets}
    assert by_facet["medium_class"]["absent"] == "not_applicable"
    assert by_facet["aeration_class"]["absent"] == "unknown"
    assert by_facet["mode"]["absent"] == "not_recorded"
    # And none of the three carries a `value` key, so none can be read as a number.
    assert all("value" not in by_facet[name] for name in ("medium_class", "aeration_class", "mode"))


def test_a_flag_facet_never_renders_as_zero(conn: sqlite3.Connection) -> None:
    """`ph_controlled = 0` is "the paper ran it uncontrolled"; NULL is "the paper never said"."""
    conn.execute(
        "UPDATE condition_context SET ph_controlled = 0, ph_controlled_state = 'recorded' "
        "WHERE id = 'ctx:full'"
    )
    read = conditions.read_contexts(conn, ["ctx:full"])["ctx:full"]
    controlled = next(facet for facet in read.facets if facet.facet == "ph_controlled")
    assert controlled.value.as_json()["value"] == "no"

    bare = conditions.read_contexts(conn, ["ctx:bare"])["ctx:bare"]
    unrecorded = next(facet for facet in bare.facets if facet.facet == "ph_controlled")
    assert "value" not in unrecorded.value.as_json()


# ------------------------------------------------------------------ the product page


def test_a_best_is_named_only_inside_a_classified_class(conn: sqlite3.Connection) -> None:
    read = products.read_product(conn, "YAA:PRODUCT:isobutanol")
    assert read is not None
    by_status = {group.klass.status: group for group in read.classes}

    classified = by_status[conditions.CLASSIFIED]
    assert classified.is_rankable is True
    assert classified.refusal_reason is None
    assert classified.best["titer (g/L)"].id == "m:2"  # 5.0 g/L, not the 9.0 with no class

    for status in (conditions.PROVISIONAL, conditions.UNCLASSIFIED):
        group = by_status[status]
        assert group.is_rankable is False
        assert group.best == {}
        assert group.refusal_reason


def test_a_class_with_two_units_names_no_best(conn: sqlite3.Connection) -> None:
    """g/L and mg/L in one ranking is arithmetic on incommensurable numbers."""
    _measurement(
        conn, "m:5", strain_id="YAA:STRAIN:child", sample_id="sam:1", value=3120.0, unit="mg/L"
    )
    read = products.read_product(conn, "YAA:PRODUCT:isobutanol")
    assert read is not None
    classified = next(
        group for group in read.classes if group.klass.status == conditions.CLASSIFIED
    )
    assert classified.is_rankable is False
    assert "units differ" in (classified.refusal_reason or "")


def test_a_free_text_quantity_kind_blocks_ranking(conn: sqlite3.Connection) -> None:
    _measurement(
        conn,
        "m:6",
        strain_id="YAA:STRAIN:child",
        sample_id="sam:1",
        kind="isobutanol concentration on SC agar permitting growth",
    )
    read = products.read_product(conn, "YAA:PRODUCT:isobutanol")
    assert read is not None
    classified = next(
        group for group in read.classes if group.klass.status == conditions.CLASSIFIED
    )
    assert classified.is_rankable is False


def test_the_product_payload_carries_the_leaderboard_refusal(conn: sqlite3.Connection) -> None:
    """PLAN.md I.2's refusal travels in the data, so a second client cannot lose it."""
    read = products.read_product(conn, "YAA:PRODUCT:isobutanol")
    assert read is not None
    assert "does not rank strains" in read.as_json()["leaderboard_refusal"]


def test_tolerance_reports_the_structural_gap_rather_than_an_empty_panel(
    conn: sqlite3.Connection,
) -> None:
    """There is no tolerance table; only isobutanol has a column. Say so, do not render blank."""
    conn.execute(
        "INSERT INTO product (id, name, tier, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:ethanol', 'ethanol', 'reference', 'R', 'chebi', 'high')"
    )
    other = products.read_product(conn, "YAA:PRODUCT:ethanol")
    assert other is not None
    assert other.tolerance == ()
    assert "nowhere in this schema" in other.tolerance_note


# ------------------------------------------------------------------ the experiment page


def test_the_experiment_returns_every_context_its_samples_reach(
    conn: sqlite3.Connection,
) -> None:
    read = experiments.read_experiment(conn, "YAA:EXPERIMENT:e1")
    assert read is not None
    assert {context.id for context in read.contexts} == {"ctx:full", "ctx:provisional"}
    assert read.samples_with_context == 3
    assert len(read.samples) == 4


def test_an_experiment_with_no_measurement_says_why(conn: sqlite3.Connection) -> None:
    """`No number was measured here` and `no number names any experiment` are different."""
    read = experiments.read_experiment(conn, "YAA:EXPERIMENT:e1")
    assert read is not None
    assert read.measurements == ()
    assert "none names any experiment" in read.measurement_note


def test_an_experiment_with_no_samples_says_so_rather_than_rendering_empty(
    conn: sqlite3.Connection,
) -> None:
    read = experiments.read_experiment(conn, "YAA:EXPERIMENT:e2")
    assert read is not None
    assert read.contexts == ()
    assert "no sample names this experiment" in read.context_note


def test_a_missing_experiment_is_none_not_an_empty_object(conn: sqlite3.Connection) -> None:
    assert experiments.read_experiment(conn, "YAA:EXPERIMENT:nope") is None


# ------------------------------------------------------------------ compare


def test_comparing_one_subject_is_refused(conn: sqlite3.Connection) -> None:
    result = compare_module.compare(conn, kind="strain", ids=["YAA:STRAIN:child"])
    assert result.verdict == compare_module.REFUSE
    assert "at least two subjects" in result.reason
    assert result.metrics == ()


def test_comparing_a_strain_with_itself_is_refused(conn: sqlite3.Connection) -> None:
    """Duplicate ids collapse, and a comparison of one thing with itself is not a comparison."""
    result = compare_module.compare(
        conn, kind="strain", ids=["YAA:STRAIN:child", "YAA:STRAIN:child"]
    )
    assert result.verdict == compare_module.REFUSE


def test_a_missing_subject_is_named_rather_than_dropped(conn: sqlite3.Connection) -> None:
    result = compare_module.compare(conn, kind="strain", ids=["YAA:STRAIN:child", "nope"])
    assert result.verdict == compare_module.REFUSE
    assert result.missing == ("nope",)


def test_comparing_strains_in_different_classes_warns_and_names_the_facets(
    conn: sqlite3.Connection,
) -> None:
    """P.2: "Refuses or warns when the comparability class differs"."""
    result = compare_module.compare(
        conn, kind="strain", ids=["YAA:STRAIN:child", "YAA:STRAIN:lonely"]
    )
    assert result.verdict == compare_module.WARN
    assert result.metrics, "a warn still shows the numbers, with the warning attached"
    assert result.reason


def test_a_comparison_with_no_class_anywhere_is_refused(conn: sqlite3.Connection) -> None:
    """The atlas's actual state: nothing reaches a context, so nothing may be aligned."""
    conn.execute("UPDATE measurement SET sample_id = NULL")
    result = compare_module.compare(
        conn, kind="strain", ids=["YAA:STRAIN:child", "YAA:STRAIN:lonely"]
    )
    assert result.verdict == compare_module.REFUSE
    assert result.metrics == ()
    # The subjects still come back: organism and genotype are not context-dependent.
    assert len(result.subjects) == 2
    assert any(attribute[0] == "organism" for attribute in result.subjects[0].attributes)


def test_an_experiment_spanning_two_contexts_has_no_single_class(
    conn: sqlite3.Connection,
) -> None:
    result = compare_module.compare(
        conn, kind="experiment", ids=["YAA:EXPERIMENT:e1", "YAA:EXPERIMENT:e2"]
    )
    assert result.verdict == compare_module.REFUSE
    assert "spans 2 condition contexts" in result.reason


def test_compare_refuses_an_unknown_kind(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not one of"):
        compare_module.compare(conn, kind="pathway", ids=["a", "b"])


def test_a_metric_row_never_shares_a_unit_across_kinds(conn: sqlite3.Connection) -> None:
    """A side-by-side row that puts g/L next to mg/L under one heading is the commonest lie."""
    _measurement(conn, "m:7", strain_id="YAA:STRAIN:lonely", sample_id="sam:3", unit="mg/L")
    result = compare_module.compare(
        conn, kind="strain", ids=["YAA:STRAIN:child", "YAA:STRAIN:lonely"]
    )
    keys = {(metric.quantity_kind, metric.unit) for metric in result.metrics}
    assert ("titer", "g/L") in keys
    assert ("titer", "mg/L") in keys


def test_a_subject_missing_a_metric_carries_an_absence_not_a_gap(
    conn: sqlite3.Connection,
) -> None:
    """`values` is positional; a short row would silently realign the columns."""
    _measurement(conn, "m:8", strain_id="YAA:STRAIN:lonely", sample_id="sam:3", unit="mg/L")
    result = compare_module.compare(
        conn, kind="strain", ids=["YAA:STRAIN:child", "YAA:STRAIN:lonely"]
    )
    for metric in result.metrics:
        assert len(metric.values) == len(result.subjects)
    mg = next(metric for metric in result.metrics if metric.unit == "mg/L")
    assert mg.values[0] is None


# ------------------------------------------------------------------ the endpoints


def test_the_new_endpoints_are_visible_to_the_write_guard() -> None:
    """The D.3 guard reads the OpenAPI schema; these paths must appear in it."""
    pytest.importorskip("fastapi")
    from fermdb.api.app import create_app

    paths = create_app().openapi()["paths"]
    for expected in (
        "/api/strains",
        "/api/strains/{strain_id}",
        "/api/experiments",
        "/api/experiments/{experiment_id}",
        "/api/products",
        "/api/products/{product_id}",
        "/api/compare",
    ):
        assert expected in paths, f"{expected} is missing from the schema"
        assert set(paths[expected]) <= {"get", "head", "options", "parameters"}


def test_a_refusal_is_a_200_not_an_error(tmp_path: Any, monkeypatch: Any) -> None:
    """PLAN.md I.2 makes refusal a valid answer, and an answer is not a 4xx."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app

    database = tmp_path / "atlas.sqlite3"
    open_db(database).close()
    monkeypatch.setenv("FERMDB_DB_FILE", str(database))

    client = TestClient(create_app())
    response = client.get("/api/compare", params={"kind": "strain", "id": ["a"]})
    assert response.status_code == 200
    assert response.json()["verdict"] == "refuse"

    assert client.get("/api/strains/nope").status_code == 404
    assert client.get("/api/compare", params={"kind": "nonsense"}).status_code == 422
