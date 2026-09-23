"""Tests for `fermdb.query.lexical` -- PLAN.md O.1's lexical modality.

Four things here are properties rather than examples, because they are the claims the module
makes about itself and an example can only fail to disprove them:

* an evidence-level difference is **never** overturned by a textual one (O.1's "an L1 result
  should outrank a textually better-matching L5 one"), checked on a fixture where the L5 has the
  strictly better text score;
* the score is never a single opaque number -- every hit carries the components that produced it,
  and they sum to it;
* the index is a derived artifact: droppable, rebuildable, byte-identical on a second build over
  an unchanged database, and absent until somebody builds it;
* it covers every kind the substring search covers, so the faster modality cannot quietly serve
  less than the one it sits beside.

Everything runs on a temporary database this file builds and indexes itself. Nothing reaches the
network and nothing touches the shared atlas.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import lexical as L
from fermdb.query import search as S


def _fixture(conn: sqlite3.Connection) -> None:
    """A small atlas with the three things this modality needs: names, aliases and evidence."""
    conn.execute(
        "INSERT INTO organism (id, name, ncbi_taxid, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 559292, 'R', 'ncbi', 'high')"
    )

    # A paper that names a gene by its STANDARD name only. Searching the systematic name must
    # still find it, which is the whole point of the query-time synonym dictionary.
    for pub_id, title, year in (
        ("pub:adh2", "ADH2 overexpression and ethanol oxidation in yeast", 2024),
        ("pub:old", "Acetolactate accumulation in brewing yeast", 1992),
    ):
        conn.execute(
            "INSERT INTO publication (id, doi, title, year, journal, zone, evidence, confidence) "
            "VALUES (?, ?, ?, ?, 'Metab Eng', 'R', 'esummary', 'high')",
            (pub_id, f"10.1000/{pub_id}", title, year),
        )

    conn.execute(
        "INSERT INTO gene_group (id, anchor_id, standard_name, scope, membership_method, zone, "
        "evidence, confidence) VALUES ('YAA:GG:ymr303c', 'YMR303C', 'ADH2', 'species', 'anchor', "
        "'H', 'fixture', 'high')"
    )
    conn.execute(
        "INSERT INTO gene (id, organism_id, assembly_accession, systematic_name, standard_name, "
        "gene_group_id, zone, evidence, confidence) VALUES ('YAA:GENE:ymr303c', 'YAA:ORG:sc', "
        "'GCF_000146045.2', 'YMR303C', 'ADH2', 'YAA:GG:ymr303c', 'R', 'fixture', 'high')"
    )

    # Two strains carrying the same query term. `long` has strictly the worse text score (the
    # term is one token among many) and is the one given L1 evidence below.
    for strain_id, name in (
        ("YAA:STRAIN:short", "acetolactate"),
        ("YAA:STRAIN:long", "acetolactate overproducing brewing strain of many words indeed"),
    ):
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:sc', ?, 'engineered', 'R', 'fixture', 'medium')",
            (strain_id, name),
        )
    # A strain findable only by a name it is not canonically called.
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:red', 'YAA:ORG:sc', 'Ethanol Red', 'industrial', 'R', 'fx', 'high')"
    )
    conn.execute(
        "INSERT INTO strain_alias (id, strain_id, alias, source, zone, evidence, confidence) "
        "VALUES ('YAA:SALIAS:1', 'YAA:STRAIN:red', 'Fermentis ER', 'vendor', 'R', 'fx', 'medium')"
    )

    conn.execute(
        "INSERT INTO product (id, name, tier, formula, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:ibut', 'isobutanol', 'primary', 'C4H10O', 'R', 'fx', 'high')"
    )

    # L1 for the textually worse strain: one direct_biochemical evidence item, which the
    # `assertion_level` view grades L1 on its own.
    conn.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, value_as_reported, "
        "unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:MEAS:1', 'YAA:STRAIN:long', 'titer', 2.1, 'g/L', 'table 2', 'R', 'fx', "
        "'high')"
    )
    conn.execute(
        "INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, object_id, "
        "created_by_kind, created_by, zone, evidence, confidence) "
        "VALUES ('YAA:ASSERT:1', 'strain', 'YAA:STRAIN:long', 'affects_production_of', 'product', "
        "'YAA:PRODUCT:ibut', 'curator', 'tester', 'R', 'fixture', 'high')"
    )
    conn.execute(
        "INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, assay_method, "
        "measurement_id, zone, evidence, confidence) VALUES ('YAA:EV:1', 'YAA:ASSERT:1', "
        "'direct_biochemical', 'increases', 'HPLC', 'YAA:MEAS:1', 'R', 'fixture', 'high')"
    )
    conn.commit()


@pytest.fixture()
def atlas() -> Iterator[sqlite3.Connection]:
    conn = open_db(IN_MEMORY)
    _fixture(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def indexed(atlas: sqlite3.Connection) -> sqlite3.Connection:
    L.build_index(atlas)
    return atlas


# --------------------------------------------------------------------------- availability


def test_fts5_availability_is_established_by_use_not_assumed() -> None:
    """The probe must answer for *this* interpreter, and must not lie either way."""
    assert L.fts5_available() is True
    # And the same answer through a live connection, which is the form the build uses.
    conn = sqlite3.connect(IN_MEMORY)
    try:
        assert L.fts5_available(conn) is True
        L.require_fts5(conn)  # does not raise
    finally:
        conn.close()


def test_without_fts5_the_build_refuses_rather_than_falling_back(
    atlas: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent fall back to `LIKE` would sell a substring scan as a full-text index."""
    monkeypatch.setattr(L, "fts5_available", lambda conn=None: False)
    with pytest.raises(L.Fts5Unavailable) as caught:
        L.build_index(atlas)
    assert "FTS5" in str(caught.value)
    # And nothing was written on the way out.
    assert L.index_status(atlas) is None


# --------------------------------------------------------------------------- the index


def test_search_before_a_build_says_so_instead_of_returning_nothing(
    atlas: sqlite3.Connection,
) -> None:
    """ "No matches" and "nobody built the index" must not render identically."""
    with pytest.raises(L.IndexNotBuilt) as caught:
        L.search_lexical(atlas, "isobutanol")
    assert L.BUILD_COMMAND in str(caught.value)


def test_the_index_is_rebuildable_and_idempotent(atlas: sqlite3.Connection) -> None:
    first = L.build_index(atlas)
    second = L.build_index(atlas)
    assert second.by_kind == first.by_kind
    assert second.documents == first.documents
    assert second.synonym_pairs == first.synonym_pairs
    # A second build leaves no duplicates behind -- the failure mode of every append-only index.
    rows = atlas.execute("SELECT COUNT(*) FROM lexical_document").fetchone()[0]
    assert rows == first.documents
    assert L.search_lexical(atlas, "isobutanol").total >= 1


def test_the_index_touches_no_table_the_core_schema_owns(indexed: sqlite3.Connection) -> None:
    """A derived artifact that edits the facts is not derived. Checked, not asserted in prose."""
    created = {
        str(row[0])
        for row in indexed.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'lexical%' AND name NOT LIKE '%_data' "
            "AND name NOT LIKE '%_idx' AND name NOT LIKE '%_content' AND name NOT LIKE '%_docsize'"
            " AND name NOT LIKE '%_config'"
        )
    }
    assert "lexical_document" in created
    assert "lexical_index" in created
    assert "lexical_synonym" in created
    # Dropping every one of them leaves a database that still opens and still searches the old
    # way, which is the property that makes `index-build` safe to re-run at any moment.
    for name in ("lexical_index", "lexical_document", "lexical_synonym", "lexical_build"):
        indexed.execute(f"DROP TABLE IF EXISTS {name}")
    assert S.search(indexed, "isobutanol").total >= 1


def test_it_covers_every_kind_the_substring_search_covers() -> None:
    """The newer modality must never quietly serve less than the placeholder beside it."""
    assert set(S._KINDS) <= set(L.KIND_LABELS)


def test_the_build_report_is_kept_so_staleness_is_answerable(indexed: sqlite3.Connection) -> None:
    report = L.index_status(indexed)
    assert report is not None
    assert report.documents == sum(report.by_kind.values())
    assert report.by_kind["publication"] == 2
    assert report.by_kind["strain"] == 3
    assert report.built_at.endswith("Z")


def test_a_builder_version_change_drops_rather_than_migrates(
    indexed: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Derived artifacts are thrown away, not migrated. `migrations.py` is for facts."""
    indexed.execute("ALTER TABLE lexical_document ADD COLUMN stale_column TEXT")
    monkeypatch.setattr(L, "BUILDER_VERSION", L.BUILDER_VERSION + 1)
    L.build_index(indexed)
    columns = {str(row[1]) for row in indexed.execute("PRAGMA table_info(lexical_document)")}
    assert "stale_column" not in columns


# --------------------------------------------------------------------------- synonyms


def test_a_strain_is_findable_by_an_alias_it_is_not_canonically_called(
    indexed: sqlite3.Connection,
) -> None:
    hits = L.search_lexical(indexed, "Fermentis ER")
    assert [hit.entity_id for hit in hits.hits][:1] == ["YAA:STRAIN:red"]


def test_a_synonym_reaches_documents_that_never_carry_the_queried_name(
    indexed: sqlite3.Connection,
) -> None:
    """The half of the dictionary that a substring scan can never do.

    `pub:adh2` says ADH2 and does not contain the string YMR303C anywhere. A `LIKE '%YMR303C%'`
    finds nothing; the dictionary, built from the gene name pair, finds the paper.
    """
    hits = L.search_lexical(indexed, "YMR303C")
    payload = hits.as_json()
    assert payload["synonyms_applied"] == {"YMR303C": ["adh2"]}
    assert "pub:adh2" in [hit.entity_id for hit in hits.hits]
    assert S.search(indexed, "YMR303C").as_json()["groups"] == [] or all(
        group["kind"] != "publication" for group in S.search(indexed, "YMR303C").as_json()["groups"]
    )


def test_the_dictionary_is_symmetric(indexed: sqlite3.Connection) -> None:
    """A reader who knows only the alias and one who knows only the canonical name are equal."""
    forward = L.search_lexical(indexed, "YMR303C").as_json()["synonyms_applied"]
    backward = L.search_lexical(indexed, "ADH2").as_json()["synonyms_applied"]
    assert forward == {"YMR303C": ["adh2"]}
    assert backward == {"ADH2": ["ymr303c"]}


def test_synonym_coverage_is_reported_per_source_including_the_empty_ones(
    atlas: sqlite3.Connection,
) -> None:
    """The honesty requirement: an empty alias table must be visible as an empty alias table.

    On the live atlas `strain_alias` holds 0 rows, so this is not a hypothetical shape -- it is
    what the report actually says there, and it must not read as a rich synonym layer.
    """
    atlas.execute("DELETE FROM strain_alias")
    report = L.build_index(atlas)
    by_source = {source.source: source for source in report.synonym_sources}
    assert by_source["strain_alias"].rows == 0
    assert by_source["strain_alias"].pairs == 0
    assert "EMPTY" in by_source["strain_alias"].note
    assert by_source["gene"].pairs == 2  # one gene, two names, both directions


# --------------------------------------------------------------------------- ranking


def _hit(hits: L.LexicalHits, entity_id: str) -> L.LexicalHit:
    return next(hit for hit in hits.hits if hit.entity_id == entity_id)


def _component(hit: L.LexicalHit, name: str) -> L.Contribution:
    return next(component for component in hit.components if component.name == name)


def test_evidence_outranks_a_better_text_match(indexed: sqlite3.Connection) -> None:
    """PLAN.md O.1, as a property: the L1 wins although the ungraded row matches better.

    This is the test that would fail if somebody "fixed" the ranking by tuning the weights until
    the results looked more intuitive.
    """
    hits = L.search_lexical(indexed, "acetolactate", kinds=("strain",))
    graded = _hit(hits, "YAA:STRAIN:long")
    ungraded = _hit(hits, "YAA:STRAIN:short")

    assert graded.evidence.level == "L1"
    assert ungraded.evidence.level is None
    # The ungraded one really is the better textual match -- otherwise this proves nothing.
    assert _component(ungraded, "text").contribution > _component(graded, "text").contribution
    assert hits.hits[0].entity_id == "YAA:STRAIN:long"


def test_no_text_difference_can_overturn_an_evidence_level(indexed: sqlite3.Connection) -> None:
    """The arithmetic behind the guarantee, stated as a test rather than only as a comment."""
    one_level = 0.2 * L._EVIDENCE_WEIGHT
    most_text_and_recency_can_swing = L._TEXT_WEIGHT + L._RECENCY_WEIGHT
    assert one_level > most_text_and_recency_can_swing


def test_the_score_is_never_one_opaque_number(indexed: sqlite3.Connection) -> None:
    hits = L.search_lexical(indexed, "acetolactate")
    payload = hits.as_json()
    for hit, wire in zip(hits.hits, payload["hits"], strict=True):
        names = [component["name"] for component in wire["ranking"]]
        assert names == ["text", "evidence", "recency"]
        assert round(sum(c["contribution"] for c in wire["ranking"]), 6) == wire["score"]
        # Each component says what it was computed from, not just what it added.
        assert all(component["note"] for component in wire["ranking"])
        assert hit.score == wire["score"]


def test_a_conflicted_entity_is_not_displayed_as_an_unevidenced_one(
    indexed: sqlite3.Connection,
) -> None:
    """Both score 0 on evidence; PLAN.md J.4 says they must not *read* alike."""
    unevidenced = L.search_lexical(indexed, "acetolactate", kinds=("strain",))
    ungraded = _hit(unevidenced, "YAA:STRAIN:short")
    assert ungraded.evidence.as_json()["display"] == "no evidence"
    assert ungraded.evidence.is_conflicted is False

    # The conflicted shape comes from `assertion_level`, whose basis vocabulary this module
    # carries through untouched rather than flattening into "ungraded".
    level = L.EvidenceLevel(level=None, basis="direct_evidence_discordant")
    assert level.display == "conflicted"
    assert L._EVIDENCE_SCORES.get(level.level or "", 0.0) == 0.0


def test_recency_is_a_named_component_with_its_bias_written_down(
    indexed: sqlite3.Connection,
) -> None:
    hits = L.search_lexical(indexed, "yeast", kinds=("publication",))
    recent = _hit(hits, "pub:adh2")
    old = _hit(hits, "pub:old")
    assert _component(recent, "recency").contribution > _component(old, "recency").contribution
    # A row with no year gets zero and says why, rather than being given an invented date.
    strains = L.search_lexical(indexed, "acetolactate", kinds=("strain",))
    undated = _component(strains.hits[0], "recency")
    assert undated.raw is None
    assert "no year" in undated.note


# --------------------------------------------------------------------------- the query


def test_a_blank_box_is_not_a_request_for_the_whole_atlas(indexed: sqlite3.Connection) -> None:
    assert L.search_lexical(indexed, "   ").total == 0
    assert L.search_lexical(indexed, "-- ;").total == 0


def test_a_punctuated_identifier_is_searched_as_the_phrase_it_was_indexed_as(
    indexed: sqlite3.Connection,
) -> None:
    """`CEN.PK113-7D` tokenizes to three tokens; querying it must match those three, adjacent."""
    assert L._tokens("CEN.PK113-7D") == ("cen", "pk113", "7d")
    expression, words, _ = L._match_expression(indexed, "CEN.PK113-7D")
    assert expression == '("cen pk113 7d")'
    assert words == ("CEN.PK113-7D",)


def test_fts5_operators_typed_into_the_box_are_data_not_syntax(
    indexed: sqlite3.Connection,
) -> None:
    """The other little language in play. Only `[A-Za-z0-9]+` tokens ever reach the expression."""
    for hostile in ('adh2" OR name:*', "adh2 NEAR/3 ethanol", "adh2*", 'x" AND "y'):
        hits = L.search_lexical(indexed, hostile)  # must not raise
        assert all(token.isalnum() for word in hits.words for token in L._tokens(word))


def test_an_unknown_kind_is_refused_rather_than_silently_dropped(
    indexed: sqlite3.Connection,
) -> None:
    with pytest.raises(L.LexicalError):
        L.search_lexical(indexed, "isobutanol", kinds=("strain", "sorcery"))


def test_the_payload_states_what_the_ranking_could_not_see(indexed: sqlite3.Connection) -> None:
    payload = L.search_lexical(indexed, "yeast").as_json()
    assert payload["ranking"]["weights"]["evidence"] == L._EVIDENCE_WEIGHT
    assert any("not comparable between queries" in caveat for caveat in payload["caveats"])
    assert any("token, not by substring" in caveat for caveat in payload["caveats"])


def test_a_saturated_pool_admits_that_it_re_ranked_only_part_of_the_match(
    indexed: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every re-ranking scheme has this hole; most do not report it."""
    monkeypatch.setattr(L, "_POOL_MINIMUM", 1)
    monkeypatch.setattr(L, "_POOL_MULTIPLE", 0)
    hits = L.search_lexical(indexed, "acetolactate", limit=1)
    assert hits.pool_saturated is True
    assert any("could not be lifted into view" in caveat for caveat in hits.as_json()["caveats"])


# --------------------------------------------------------------------------- over the wire


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, build: bool) -> Any:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app

    database = tmp_path / "atlas.sqlite3"
    conn = open_db(database)
    _fixture(conn)
    if build:
        L.build_index(conn)
    conn.close()
    monkeypatch.setenv("FERMDB_DB_FILE", str(database))
    return TestClient(create_app())


def test_the_api_says_503_rather_than_returning_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty list would mean "nothing matched", which is not what happened."""
    client = _client(tmp_path, monkeypatch, build=False)
    response = client.get("/api/search/lexical?q=isobutanol")
    assert response.status_code == 503
    assert L.BUILD_COMMAND in response.json()["detail"]

    status = client.get("/api/search/lexical/status").json()
    assert status["built"] is False
    assert status["fts5_available"] is True


def test_the_wire_payload_carries_the_ranking_and_its_caveats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, build=True)
    body = client.get("/api/search/lexical?q=acetolactate&kind=strain").json()
    assert [hit["id"] for hit in body["hits"]][0] == "YAA:STRAIN:long"
    assert body["hits"][0]["evidence"]["level"] == "L1"
    assert [c["name"] for c in body["hits"][0]["ranking"]] == ["text", "evidence", "recency"]
    assert body["caveats"]

    assert client.get("/api/search/lexical?q=x&kind=sorcery").status_code == 400
    status = client.get("/api/search/lexical/status").json()
    assert status["built"] is True
    assert status["by_kind"]["strain"] == 3
