"""Tests for the read-only interface layer — `fermdb.api` and the readers it serves.

The properties under test are the ones a redesign is most likely to break, and each one is a
rule from PLAN.md rather than a preference:

* **No write path exists** (D.3). Not "no write path is documented" — every route object is
  inspected and any non-GET method fails the test, so adding a POST handler breaks the build
  rather than quietly shipping.
* **An absence never serializes as a value** (P.4). `Value.as_json()` omits the `value` key on
  an absence, which is what lets a client tell "not recorded" from "recorded as zero". A
  refactor that emitted `"value": null` would render identically in the UI and be invisible in
  review; here it fails.
* **A never-computed score is not zero** (the route ranking). `score_toxicity` is NULL in every
  row, and the payload must say so rather than sorting on an implied 0.0.
* **Counts are over distinct publications, not rows.** A paper carries one screening record per
  family, so counting rows would report a corpus several times larger than the real one.

These run against an in-memory fixture rather than the live atlas, so they test the readers'
logic and not whatever happens to be curated this week.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import genomes as genomes_reader
from fermdb.query import literature, networks, records, search, transcripts


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """A small atlas with one of everything the new readers touch.

    `zone` is passed only where the schema has no default for it, which is most tables but not
    all — `screening_record` defaults to H, `screening_decision`, `fulltext_asset` and `sra_run`
    to R. Where it is passed it is the zone that table's CHECK allows: `pathway_route` permits
    only H or I, because an enumerated route is derived and can never be something a source
    reported.
    """
    conn = open_db(IN_MEMORY)

    conn.execute(
        "INSERT INTO organism (id, name, ncbi_taxid, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 559292, 'R', 'ncbi', 'high')"
    )

    # Two publications; only one is readable, and one carries two screening families so that a
    # row count and a distinct-publication count disagree.
    for pid, title, year in (
        ("pub:a", "Isobutanol production in yeast", 2024),
        ("pub:b", "Something else entirely", 2020),
    ):
        conn.execute(
            "INSERT INTO publication (id, title, year, zone, evidence, confidence) "
            "VALUES (?, ?, ?, 'R', 'crossref', 'high')",
            (pid, title, year),
        )
    conn.execute(
        "INSERT INTO search_run (id, family, db, term, started_at, query_families_version) "
        "VALUES ('run:1', 'isobutanol_all', 'pubmed', 'isobutanol', '2026-01-01', 'v1')"
    )
    for family in ("isobutanol_all", "isobutanol_yeast"):
        conn.execute(
            "INSERT INTO screening_record (id, publication_id, family, first_seen_run_id, "
            "last_seen_run_id, triage_state, product_tier, default_disposition) "
            "VALUES (?, 'pub:a', ?, 'run:1', 'run:1', 'included', 'isobutanol', "
            "'include_unless_excluded')",
            (f"scr:{family}", family),
        )
    conn.execute(
        "INSERT INTO screening_record (id, publication_id, family, first_seen_run_id, "
        "last_seen_run_id, triage_state, product_tier, default_disposition) "
        "VALUES ('scr:b', 'pub:b', 'isobutanol_all', 'run:1', 'run:1', 'needs_full_text', "
        "'isobutanol', 'include_unless_excluded')"
    )
    conn.execute(
        "INSERT INTO screening_decision (publication_id, decision, reason, source, decided_by, "
        "decided_by_kind, decided_at, evidence, confidence) VALUES "
        "('pub:a', 'include', 'in scope', 'run-1', 'curator', 'human', '2026-01-02', "
        "'read', 'high')"
    )
    conn.execute(
        # `storage_state = 'stored_fulltext'` is a claim that the bytes are ours, and the schema
        # holds it to that: path, checksum, media type, source and retrieval time are all
        # required. An asset row that says "stored" without saying where is not storage.
        "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
        "storage_state, content_path, checksum_sha256, media_type, source_url, retrieved_at) "
        "VALUES ('fa:a', 'pub:a', '10.1/a', 'gold', 'unpaywall', 'stored_fulltext', "
        "'fulltext/pub-a.xml', 'deadbeef', 'application/xml', 'https://example.org/a', "
        "'2026-01-01')"
    )

    # Nothing is inserted for genomes. `encoding_genome`, `compartment` and the many-to-many
    # between them are seeded by `schema.sql` itself, because which genetic code a compartment
    # reads is a fact about yeast rather than something a curator decides per atlas. The test
    # below therefore asserts against the seeded truth, and would catch a migration that
    # silently dropped the mitochondrial arm of that mapping.

    # Transcripts: one study, two runs, only one of which is RNA-Seq.
    conn.execute(
        "INSERT INTO dataset (id, accession, repository, omics_type, zone, evidence, "
        "confidence) VALUES ('ds:1', 'SRP1', 'SRA', 'transcriptomics', 'R', 'sra', 'high')"
    )
    for run, strategy in (("SRR1", "RNA-Seq"), ("SRR2", "AMPLICON")):
        conn.execute(
            "INSERT INTO sra_run (id, run_accession, study_accession, library_strategy, "
            "acquisition_status, retrieved_at, evidence, confidence) "
            "VALUES (?, ?, 'SRP1', ?, 'discovered', '2026-01-01', 'sra', 'high')",
            (f"run:{run}", run, strategy),
        )

    # A route whose toxicity score was never computed.
    conn.execute(
        "INSERT INTO pathway_route (id, cofactor_strategy, balance_status, score_balance, "
        "score_evidence, score_feasibility, score_transport, zone) "
        "VALUES ('YAA:ROUTE:x', 'A_native_split', 'fail', 0.5, 0.8, 0.3, 1.0, 'I')"
    )

    # A measurement with no sample, which is the state that blocks comparability.
    conn.execute(
        "INSERT INTO product (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:isobutanol', 'isobutanol', 'R', 'chebi', 'high')"
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:s1', 'YAA:ORG:sc', 'CEN.PK', 'R', 'paper', 'high')"
    )
    conn.execute(
        "INSERT INTO measurement (id, quantity_kind, product_id, strain_id, publication_id, "
        "value_as_reported, unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES ('m:1', 'titer', 'YAA:PRODUCT:isobutanol', 'YAA:STRAIN:s1', 'pub:a', 2.09, "
        "'g/L', 'Table 1', 'R', 'table 1', 'high')"
    )
    conn.commit()
    return conn


# ------------------------------------------------------------------ the layering rule


def test_no_endpoint_accepts_a_write() -> None:
    """PLAN.md D.3: the interface may not write to the domain. Enforced, not documented.

    A browser click must never promote a proposal, because the audit log records a *named human*
    as the actor for every promotion.

    **Read via the OpenAPI schema, not by walking `app.routes`.** The first version of this test
    walked `app.routes` and was vacuous: FastAPI represents each `include_router` as one lazy
    `_IncludedRouter` object carrying no `.path` and no `.methods`, so the walk saw six
    routes -- four docs pages, `/api/health`, and the SPA fallback -- and none of the 34 real API
    paths. It passed by inspecting nothing that mattered, which is the worst way for a safety
    test to fail. `app.openapi()["paths"]` is the flattened, fully-resolved routing table, so it
    cannot go quietly blind the same way.

    `test_the_guard_can_actually_see_the_endpoints` below is the guard on the guard.
    """
    pytest.importorskip("fastapi")
    from fermdb.api.app import create_app

    paths = create_app().openapi()["paths"]
    offenders = sorted(
        (path, method.upper())
        for path, operations in paths.items()
        for method in operations
        if method.lower() not in {"get", "head", "options", "parameters"}
    )
    assert offenders == [], f"non-GET endpoints exist: {offenders}"


def test_the_guard_can_actually_see_the_endpoints() -> None:
    """The write guard must be looking at the real surface, not at an empty list.

    Without this, deleting every route would make the test above pass. It asserts the schema
    contains the endpoints the interface is actually built from, so a future refactor that hides
    them from introspection fails here rather than silently disarming the guard.
    """
    pytest.importorskip("fastapi")
    from fermdb.api.app import create_app

    paths = create_app().openapi()["paths"]

    assert len(paths) >= 20, f"only {len(paths)} paths visible; the guard has gone blind"
    for expected in (
        "/api/atlas/coverage",
        "/api/literature/overview",
        "/api/genomes/overview",
        "/api/networks/routes",
        "/api/data/measurements",
        "/api/curation/queue",
    ):
        assert expected in paths, f"{expected} is missing from the schema the guard reads"


def test_select_builder_cannot_emit_a_write() -> None:
    """The query layer's `Select` has no method that emits anything but SELECT."""
    from fermdb.query.builder import Select

    sql, _ = Select("publication").columns("id").sql(limit=1)
    assert sql.strip().upper().startswith("SELECT")


# ------------------------------------------------------------------ absence vs zero


def test_absence_omits_the_value_key_entirely() -> None:
    """A `null` and a missing key render identically in JS; only one is honest.

    This is the whole reason `Value.as_json()` is shaped the way it is: a consumer reaching for
    `.value` on an absence gets `undefined` and a visible bug, not `null` and a silent one.
    """
    from fermdb.query.values import Absence, Value, Zone

    known = Value.known(3, zone=Zone.REPORTED).as_json()
    absent = Value.absent(Absence.NOT_RECORDED).as_json()

    assert known["value"] == 3
    assert "value" not in absent
    assert absent["absent"] == "not_recorded"
    assert absent["display"] == "not recorded"

    # The three absences must stay distinguishable on the wire.
    kinds = {
        Value.absent(a).as_json()["absent"]
        for a in (Absence.NOT_RECORDED, Absence.NOT_APPLICABLE, Absence.UNKNOWN)
    }
    assert kinds == {"not_recorded", "not_applicable", "unknown"}


def test_unscored_route_axis_is_absent_not_zero(conn: sqlite3.Connection) -> None:
    """`score_toxicity` was never computed. Reporting it as 0.0 would rank on a fiction."""
    route = networks.read_route(conn, "YAA:ROUTE:x")
    assert route is not None
    payload = route.as_json()

    assert "value" not in payload["scores"]["score_toxicity"]
    assert payload["unscored_axes"] == ["score_toxicity"]
    assert "score_toxicity" in payload["ranking_caveat"]
    assert payload["is_viable"] is False, "balance_status='fail' must not read as viable"


def test_rank_routes_refuses_an_unknown_axis(conn: sqlite3.Connection) -> None:
    """Ranking happens on a named axis; there is no composite to fall back to."""
    with pytest.raises(ValueError, match="not a scoring axis"):
        networks.rank_routes(conn, order_by="score_vibes")


# ------------------------------------------------------------------ counting


def test_corpus_counts_distinct_publications_not_rows(conn: sqlite3.Connection) -> None:
    """One paper with two screening families is one paper, not two."""
    overview = literature.read_overview(conn).as_json()

    assert overview["publications"] == 2
    assert overview["screened"] == 2, "pub:a has two screening rows but is one publication"
    by_family = overview["by_family"]
    assert by_family["isobutanol_all"] == 2
    assert by_family["isobutanol_yeast"] == 1


def test_funnel_names_the_remedy_for_each_loss(conn: sqlite3.Connection) -> None:
    """A count of exclusions is trivia; a count with its remedy is a piece of work."""
    stages = {s["key"]: s for s in literature.read_overview(conn).as_json()["stages"]}

    assert stages["readable"]["count"] == 1
    assert stages["included"]["count"] == 1
    # pub:a is included and readable, so nothing is included-but-unreadable.
    assert stages["included_unreadable"]["count"] == 0
    assert "re-screening" in stages["excluded"]["remedy"]
    assert "acquire" in stages["needs_full_text"]["remedy"]


def test_study_rollup_separates_rnaseq_from_the_rest(conn: sqlite3.Connection) -> None:
    """Amplicon runs arrive with the same BioProjects and cannot support expression."""
    overview = transcripts.read_overview(conn).as_json()

    assert overview["runs"] == 2
    assert overview["expression_runs"] == 1
    study = overview["studies"][0]
    assert study["runs"] == 2
    assert study["expression_runs"] == 1
    # No matrices dir in this fixture, so nothing is quantified, and the note says so in those
    # terms. It must not say "none downloaded": `acquisition_status` has no value meaning
    # downloaded, so a count of it is always zero and would report a quantified corpus as empty.
    assert "none of them quantified" in study["usable_note"]
    assert study["quantified"] == 0


def test_quantification_is_never_read_from_acquisition_status(
    conn: sqlite3.Connection,
) -> None:
    """A regression test for a real bug: the status column cannot express "quantified".

    `sra_run.acquisition_status` is CHECK-constrained to {discovered, condition_annotated,
    queued, excluded}. An earlier version counted rows equal to `'downloaded'` -- a value the
    constraint forbids -- so the count was structurally always zero and the Transcripts page
    reported "none downloaded" for a corpus with 99 quantified samples on disk.
    """
    from fermdb.query.builder import Select
    from fermdb.query.expression import ACQUISITION_STATES, QUANTIFICATION_STATES

    stored = {
        str(row["k"])
        for row in Select("sra_run")
        .columns("acquisition_status AS k", "COUNT(*) AS n")
        .group_by("acquisition_status")
        .page(conn)
    }
    assert stored <= ACQUISITION_STATES, "a status outside the documented CHECK vocabulary"
    assert "downloaded" not in ACQUISITION_STATES
    # Empty today. If a migration ever adds a real quantification state, this fails and points
    # at the two places that then need updating.
    assert frozenset() == QUANTIFICATION_STATES


def test_study_with_no_rnaseq_says_so(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sra_run WHERE library_strategy = 'RNA-Seq'")
    study = transcripts.read_study(conn, "SRP1")
    assert study is not None
    assert "cannot support an expression statement" in study.usable_note


# ------------------------------------------------------------------ genomes


def test_dual_coded_compartment_is_flagged(conn: sqlite3.Connection) -> None:
    """A sequence filed against the matrix is ambiguous until it names its code table.

    Asserted against the schema's own seed, so this also guards the mapping: exactly the two
    compartments that host mtDNA-encoded proteins are dual-coded, and a migration that dropped
    the mitochondrial arm would leave both reading as nuclear-only and fail here.
    """
    overview = genomes_reader.read_overview(conn).as_json()

    assert overview["dual_coded_compartments"] == [
        "mitochondrial_inner_membrane",
        "mitochondrial_matrix",
    ]
    matrix = next(c for c in overview["compartments"] if c["id"] == "mitochondrial_matrix")
    assert matrix["is_dual_coded"] is True
    assert sorted(matrix["encoding_genomes"]) == ["mitochondrial", "nuclear"]
    assert "ambiguous" in matrix["warning"]

    cytosol = next(c for c in overview["compartments"] if c["id"] == "cytosol")
    assert cytosol["is_dual_coded"] is False
    assert "warning" not in cytosol

    # Table 3 applies in exactly the dual-coded compartments and nowhere else.
    mito_code = next(g for g in overview["encoding_genomes"] if g["genetic_code_table"] == 3)
    assert mito_code["compartments"] == [
        "mitochondrial_inner_membrane",
        "mitochondrial_matrix",
    ]


# ------------------------------------------------------------------ comparability


def test_measurement_without_a_sample_carries_the_warning(conn: sqlite3.Connection) -> None:
    """No sample means no condition context means no comparability class (K.4)."""
    reads, _ = records.list_measurements(conn)
    assert len(reads) == 1
    warnings = reads[0].as_json()["comparability_warnings"]
    assert any("no sample" in w for w in warnings)

    overview = records.read_overview(conn).as_json()
    assert overview["measurements_with_sample"] == 0


def test_reported_and_harmonized_forms_both_travel(conn: sqlite3.Connection) -> None:
    """ "2.09 g/L as written" and "2.09 g/L after conversion" are different claims."""
    reads, _ = records.list_measurements(conn)
    quantity = reads[0].as_json()["quantity"]

    assert quantity["reported"]["value"] == 2.09
    assert quantity["reported"]["zone"] == "R"
    # value_si was never computed for this row, so it must read as absent rather than as 0.
    assert "value" not in quantity["si"]


# ------------------------------------------------------------------ search


def test_search_groups_by_kind_and_never_merges(conn: sqlite3.Connection) -> None:
    """Nothing here can rank a paper against a strain, so nothing tries."""
    hits = search.search(conn, "isobutanol").as_json()

    kinds = {group["kind"] for group in hits["groups"]}
    assert "publication" in kinds
    assert "product" in kinds
    assert "recall_caveat" in hits
    assert hits["technique"].startswith("substring")


def test_blank_search_returns_nothing(conn: sqlite3.Connection) -> None:
    """An empty box is not a request for the whole atlas."""
    assert search.search(conn, "   ").as_json()["total"] == 0


def test_search_survives_a_column_the_schema_lacks(conn: sqlite3.Connection) -> None:
    """One kind naming a missing column must not take the whole search box down."""
    conn.execute("DROP TABLE gene")
    hits = search.search(conn, "isobutanol").as_json()
    assert hits["total"] > 0


# ------------------------------------------------------------------ the API surface


def _client() -> Any:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app

    return TestClient(create_app())


def test_health_reports_which_atlas_is_served() -> None:
    """The commonest confusion when running this is reading a copy as the live file."""
    response = _client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "atlas" in body
    assert body["writable_endpoints"] == 0


def test_missing_row_is_a_404_not_an_empty_object(tmp_path: Any, monkeypatch: Any) -> None:
    """A temp atlas, because otherwise this asks the developer's machine rather than the code.

    `api/deps.py` raises 503 from the `connection` dependency when nothing exists at the resolved
    path, before any route function runs. Pointed at the ambient atlas this test therefore asserted
    one of two different things depending on who ran it: a real 404 on a machine that happens to
    have an atlas at the default location, and `503 == 404` on one that does not -- which is how it
    passed here for months and went red the first time CI got far enough to run it.

    An empty database at the current schema is the right fixture for the question: 404 is a claim
    about a row that is absent, and every row is absent here, so nothing but the handler's
    not-found path can produce it.
    """
    atlas = tmp_path / "atlas.sqlite3"
    open_db(atlas).close()
    monkeypatch.setenv("FERMDB_DB_FILE", str(atlas))

    client = _client()
    assert client.get("/api/annotations/genes/NO-SUCH-GENE").status_code == 404
    assert client.get("/api/networks/routes?order_by=nonsense").status_code == 422


def test_health_fails_on_a_schema_mismatch(tmp_path: Any, monkeypatch: Any) -> None:
    """A health check that only stats the file cannot fail for the reason health checks exist.

    This is a regression test for a real incident: the code moved to schema v17 while the atlas on
    disk was still v16, every data endpoint raised `SchemaVersionError`, and `/api/health` kept
    returning `ok: true` because it only asked whether the file was present. The UI therefore
    rendered as healthy and empty. Presence is not usability, and only usability is worth asking.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app
    from fermdb.db import SCHEMA_VERSION

    stale = tmp_path / "stale.sqlite3"
    conn = open_db(stale)
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION - 1),)
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("FERMDB_DB_FILE", str(stale))
    body = TestClient(create_app()).get("/api/health").json()

    assert body["ok"] is False
    assert body["schema_version"] == SCHEMA_VERSION - 1
    assert body["expected_schema_version"] == SCHEMA_VERSION
    # The message has to carry the way out, not just the diagnosis.
    assert "fermdb db migrate" in body["error"]


def test_health_is_ok_on_a_current_database(tmp_path: Any, monkeypatch: Any) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app
    from fermdb.db import SCHEMA_VERSION

    fresh = tmp_path / "fresh.sqlite3"
    open_db(fresh).close()

    monkeypatch.setenv("FERMDB_DB_FILE", str(fresh))
    body = TestClient(create_app()).get("/api/health").json()

    assert body["ok"] is True
    assert body["schema_version"] == SCHEMA_VERSION
    assert "error" not in body
