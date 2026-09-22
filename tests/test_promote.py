"""Tests for `fermdb.curate.promote`.

Promotion is the only thing in this project that turns model output into Zone R. Everything
upstream is reversible -- a bad extraction sits in a queue, a bad accept is an audit-log row --
and everything downstream treats a `measurement` as a number a person checked. So the tests here
are mostly about what must be *refused*, and each refusal is a way the atlas could otherwise have
acquired a fact nobody verified.

The ones that matter most:

* a stale span (the offsets no longer find the quote) must block, because after promotion the row
  is indistinguishable from a verified one;
* a missing `organism_id` must block rather than defaulting, because "probably S. cerevisiae" in
  Zone R is exactly the laundering PLAN.md W.13 lists as a top risk;
* an unpromoted strain must block its measurements rather than producing a subject-less row.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.curate import promote as P
from fermdb.curate.queue import Curator, get_task
from fermdb.db import open_db

REPO_ROOT = Path(__file__).resolve().parents[1]

QUOTE = "the isobutanol titer reached 1.62 g/L at 24 h"
SOURCE = "Results. " + QUOTE + " Strain BSW191 was grown in YPD."
START = SOURCE.index(QUOTE)
END = START + len(QUOTE)

HUMAN = Curator(name="kangkon", kind="human")
AGENT = Curator(name="extractor", kind="agent")


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FERMDB_DB_FILE", str(tmp_path / "data" / "fermdb.sqlite3"))
    return Settings.load()


@pytest.fixture()
def atlas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A publication with stored full text, one strain proposal and one measurement proposal."""
    settings = _settings(tmp_path, monkeypatch)
    conn = open_db(settings.db_file)

    # `load_source_text` resolves content_path relative to data_dir and wants 'stored_fulltext'.
    relative = Path("fulltext") / "aa" / "paper.txt"
    text_file = settings.data_dir / relative
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(SOURCE, encoding="utf-8")

    conn.executescript(
        """
        INSERT INTO organism (id, name, zone, evidence, confidence)
            VALUES ('YAA:ORG:scer', 'Saccharomyces cerevisiae', 'R', 'test', 'high');
        INSERT INTO product (id, name, zone, evidence, confidence)
            VALUES ('YAA:PRODUCT:isobutanol', 'isobutanol', 'R', 'test', 'high');
        INSERT INTO publication (id, zone, evidence, confidence)
            VALUES ('YAA:PUB:test', 'R', 'test', 'high');
        INSERT INTO extraction (id, publication_id, extractor, extractor_version, model,
                                prompt_version, input_hash, review_state, zone)
            VALUES ('YAA:EXTR:test', 'YAA:PUB:test', 'test', '1', 'test-model', 'v1', 'hash',
                    'proposed', 'I');
        """
    )
    conn.execute(
        "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
        "storage_state, content_path, checksum_sha256, source_url, media_type, retrieved_at, "
        "zone) VALUES ('YAA:FTA:test', 'YAA:PUB:test', '10.1/test', 'gold', 'europepmc', "
        "'stored_fulltext', ?, 'sha', 'https://example.org/x', 'text/plain', "
        "'2026-09-20T00:00:00Z', 'R')",
        (relative.as_posix(),),
    )
    for task_id, kind, path, payload in [
        (
            "YAA:CTASK:strain",
            "strains",
            "strains[0]",
            {
                "name_as_reported": "BSW191",
                "role": "engineered",
                "zone": "I",
                "confidence": "unverified",
                "span": {
                    "quote": QUOTE,
                    "char_start": START,
                    "char_end": END,
                    "section": "results",
                },
            },
        ),
        (
            "YAA:CTASK:meas",
            "measurements",
            "measurements[0]",
            {
                "quantity_kind": "titer",
                "product_id": "YAA:PRODUCT:isobutanol",
                "strain_name_as_reported": "BSW191",
                "value": 1.62,
                "unit": "g/L",
                "source_locator": "text",
                "zone": "I",
                "confidence": "unverified",
                "span": {
                    "quote": QUOTE,
                    "char_start": START,
                    "char_end": END,
                    "section": "results",
                },
            },
        ),
    ]:
        conn.execute(
            "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, "
            "record_kind, payload, status, priority, attempt_count, proposal_hash, curator, "
            "curator_kind, resolved_at, resolution_reason, zone) "
            "VALUES (?, 'YAA:EXTR:test', 'YAA:PUB:test', ?, ?, ?, 'accepted', 1, 0, ?, "
            "'kangkon', 'human', '2026-09-20T00:00:00Z', 'checked', 'I')",
            (task_id, path, kind, json.dumps(payload), f"hash-{kind}"),
        )
    conn.commit()
    yield conn
    conn.close()


def _plan(conn: sqlite3.Connection, task_id: str, **supplied: object) -> P.PromotionPlan:
    return P.plan_promotion(conn, get_task(conn, task_id), supplied=supplied)


# ------------------------------------------------------------------------------- what refuses


def test_a_pending_task_is_not_promotable(atlas: sqlite3.Connection) -> None:
    """'pending' means nobody has looked at it. That is the whole point of the queue."""
    # A pending task must have no curator -- the schema enforces both directions.
    atlas.execute(
        "UPDATE curation_task SET status = 'pending', curator = NULL, curator_kind = NULL, "
        "resolved_at = NULL, resolution_reason = NULL WHERE id = 'YAA:CTASK:strain'"
    )
    plan = _plan(atlas, "YAA:CTASK:strain", organism_id="YAA:ORG:scer")
    assert not plan.ready
    assert "only an accepted or edited proposal" in plan.note


def test_a_missing_organism_blocks_rather_than_defaulting(atlas: sqlite3.Connection) -> None:
    """ "Probably S. cerevisiae" written into Zone R is a fact nobody checked.

    PLAN.md W.13: "the atlas launders uncertainty into fact". This is where that would happen.
    """
    plan = _plan(atlas, "YAA:CTASK:strain")
    assert not plan.ready
    assert [m.field for m in plan.missing] == ["organism_id"]
    assert "curator supplies it" in plan.missing[0].why


def test_an_organism_that_does_not_exist_is_refused(atlas: sqlite3.Connection) -> None:
    plan = _plan(atlas, "YAA:CTASK:strain", organism_id="YAA:ORG:nope")
    assert not plan.ready
    assert "no organism with id" in plan.note


def test_a_stale_span_blocks_promotion(atlas: sqlite3.Connection) -> None:
    """The offsets no longer find the quote, so nobody can say the number came from there.

    After promotion the row looks exactly like one somebody verified, so this is the last moment
    the check is cheap.
    """
    payload = json.loads(
        atlas.execute("SELECT payload FROM curation_task WHERE id = 'YAA:CTASK:strain'").fetchone()[
            "payload"
        ]
    )
    payload["span"]["char_start"] = 0
    payload["span"]["char_end"] = 5
    atlas.execute(
        "UPDATE curation_task SET payload = ? WHERE id = 'YAA:CTASK:strain'",
        (json.dumps(payload),),
    )
    plan = _plan(atlas, "YAA:CTASK:strain", organism_id="YAA:ORG:scer")
    assert not plan.ready
    assert "offsets are stale" in plan.note


def test_a_quote_absent_from_the_source_blocks_promotion(atlas: sqlite3.Connection) -> None:
    payload = json.loads(
        atlas.execute("SELECT payload FROM curation_task WHERE id = 'YAA:CTASK:strain'").fetchone()[
            "payload"
        ]
    )
    payload["span"]["quote"] = "a sentence this paper does not contain"
    atlas.execute(
        "UPDATE curation_task SET payload = ? WHERE id = 'YAA:CTASK:strain'",
        (json.dumps(payload),),
    )
    plan = _plan(atlas, "YAA:CTASK:strain", organism_id="YAA:ORG:scer")
    assert "not in the source document at all" in plan.note


def test_an_unpromoted_strain_blocks_its_measurements(atlas: sqlite3.Connection) -> None:
    """A measurement needs a subject. A NULL one would be a number belonging to nothing."""
    plan = _plan(atlas, "YAA:CTASK:meas")
    assert not plan.ready
    assert "is not promoted yet" in plan.note
    assert "YAA:STRAIN:bsw191" in plan.note


def test_an_agent_may_not_promote(atlas: sqlite3.Connection) -> None:
    """PLAN.md L.5. The schema refuses it too, but the error should name the rule."""
    with pytest.raises(P.NotPromotable, match="L.5"):
        P.promote(atlas, "YAA:CTASK:strain", curator=AGENT, reason="x")


def test_a_kind_with_no_promoter_says_so(atlas: sqlite3.Connection) -> None:
    """Some real proposals are kinds this module does not handle yet.

    Reporting them as "no promoter" rather than skipping them silently is what keeps a batch run
    from looking complete while doing less than half the work.
    """
    atlas.execute("UPDATE curation_task SET record_kind = 'conditions' WHERE id = 'YAA:CTASK:meas'")
    plan = _plan(atlas, "YAA:CTASK:meas")
    assert plan.target_table is None
    assert "no promoter" in plan.note


# --------------------------------------------------------------------------- what succeeds


def test_a_strain_promotes_into_zone_r_with_a_walkable_chain(atlas: sqlite3.Connection) -> None:
    result = P.promote(
        atlas,
        "YAA:CTASK:strain",
        curator=HUMAN,
        reason="checked against table 1",
        supplied={"organism_id": "YAA:ORG:scer"},
    )
    assert result.created
    assert result.row_id == "YAA:STRAIN:bsw191"

    row = atlas.execute("SELECT * FROM strain WHERE id = ?", (result.row_id,)).fetchone()
    assert row["zone"] == "R"
    assert row["canonical_name"] == "BSW191"
    assert row["class"] == "engineered"
    # The J.5 chain: the row names the task, the publication and who agreed.
    assert "YAA:CTASK:strain" in row["evidence"]
    assert "YAA:PUB:test" in row["evidence"]
    assert "kangkon" in row["evidence"]
    assert "re-resolved" in row["evidence"]

    event = atlas.execute(
        "SELECT * FROM curation_event WHERE target_id = ?", (result.row_id,)
    ).fetchone()
    assert event["action"] == "promote"
    assert event["actor_kind"] == "human"


def test_promoting_twice_writes_one_row(atlas: sqlite3.Connection) -> None:
    """Derived ids, not random ones, so a re-run is a no-op rather than a duplicate."""
    for _ in range(2):
        P.promote(
            atlas,
            "YAA:CTASK:strain",
            curator=HUMAN,
            reason="again",
            supplied={"organism_id": "YAA:ORG:scer"},
        )
    assert atlas.execute("SELECT COUNT(*) FROM strain").fetchone()[0] == 1


def test_a_role_outside_the_closed_set_is_null_not_unknown(atlas: sqlite3.Connection) -> None:
    """'unknown' means recorded-but-unresolvable. NULL means the paper did not say."""
    payload = json.loads(
        atlas.execute("SELECT payload FROM curation_task WHERE id = 'YAA:CTASK:strain'").fetchone()[
            "payload"
        ]
    )
    payload["role"] = "production host"
    atlas.execute(
        "UPDATE curation_task SET payload = ? WHERE id = 'YAA:CTASK:strain'",
        (json.dumps(payload),),
    )
    P.promote(
        atlas,
        "YAA:CTASK:strain",
        curator=HUMAN,
        reason="x",
        supplied={"organism_id": "YAA:ORG:scer"},
    )
    assert atlas.execute("SELECT class FROM strain").fetchone()["class"] is None


def test_the_batch_promotes_strains_before_measurements(atlas: sqlite3.Connection) -> None:
    """In one pass, and in the right order, or the measurement reports a blocker being resolved."""
    done, blocked = P.promote_ready(
        atlas, curator=HUMAN, reason="batch", supplied={"organism_id": "YAA:ORG:scer"}
    )
    assert [r.target_table for r in done] == ["strain", "measurement"]
    assert blocked == ()

    measurement = atlas.execute("SELECT * FROM measurement").fetchone()
    assert measurement["strain_id"] == "YAA:STRAIN:bsw191"
    assert measurement["value_as_reported"] == 1.62
    assert measurement["unit_as_reported"] == "g/L"
    assert measurement["zone"] == "R"
    # 'medium', not the model's 'unverified' and not 'high': a person read one sentence.
    assert measurement["confidence"] == "medium"


def test_a_promoted_measurement_carries_its_publication_as_a_column(
    atlas: sqlite3.Connection,
) -> None:
    """PLAN.md J.5's last hop, as a join rather than a sentence (schema v12).

    The task's `publication_id` is NOT NULL, so this was always available and was always dropped.
    Asserted against the task's column rather than against the evidence string, because the string
    agreeing with the column is what a prose parser would also achieve, and the point is that the
    value did not come from there.
    """
    P.promote_ready(atlas, curator=HUMAN, reason="batch", supplied={"organism_id": "YAA:ORG:scer"})
    expected = atlas.execute(
        "SELECT publication_id FROM curation_task WHERE id = 'YAA:CTASK:meas'"
    ).fetchone()["publication_id"]
    row = atlas.execute("SELECT publication_id FROM measurement").fetchone()
    assert row["publication_id"] == expected

    # And it is a real foreign key, not a string that happens to look like one.
    walked = atlas.execute(
        "SELECT p.id FROM measurement m JOIN publication p ON p.id = m.publication_id"
    ).fetchone()
    assert walked["id"] == expected


def test_a_measurement_with_no_publication_is_still_storable(atlas: sqlite3.Connection) -> None:
    """A number from a deposited dataset has no paper, and the column stays nullable for it.

    If this ever fails, the fix is not to invent a publication for such a row.
    """
    atlas.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:ds', 'YAA:ORG:scer', 'DS', 'R', 'test', 'high')"
    )
    atlas.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, value_as_reported, "
        "unit_as_reported, source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:MEAS:ds', 'YAA:STRAIN:ds', 'titer', 4.2, 'g/L', 'dataset', 'R', "
        "'from a deposited dataset, not from a paper', 'medium')"
    )
    row = atlas.execute(
        "SELECT publication_id FROM measurement WHERE id = 'YAA:MEAS:ds'"
    ).fetchone()
    assert row["publication_id"] is None


def test_nothing_is_skipped_silently(atlas: sqlite3.Connection) -> None:
    """Every task that did not promote comes back with a reason, so a partial run cannot pass
    for a complete one."""
    atlas.execute("UPDATE curation_task SET record_kind = 'conditions' WHERE id = 'YAA:CTASK:meas'")
    done, blocked = P.promote_ready(
        atlas, curator=HUMAN, reason="batch", supplied={"organism_id": "YAA:ORG:scer"}
    )
    assert len(done) == 1
    assert len(blocked) == 1
    assert "no promoter" in blocked[0].note


def test_an_edited_payload_is_what_gets_promoted(atlas: sqlite3.Connection) -> None:
    """The curator's correction is the truth; the model's original stays for prompt analysis."""
    corrected = json.loads(
        atlas.execute("SELECT payload FROM curation_task WHERE id = 'YAA:CTASK:strain'").fetchone()[
            "payload"
        ]
    )
    corrected["name_as_reported"] = "BSW191-corrected"
    atlas.execute(
        "UPDATE curation_task SET status = 'edited', edited_payload = ? WHERE id = ?",
        (json.dumps(corrected), "YAA:CTASK:strain"),
    )
    result = P.promote(
        atlas,
        "YAA:CTASK:strain",
        curator=HUMAN,
        reason="fixed the name",
        supplied={"organism_id": "YAA:ORG:scer"},
    )
    assert result.row_id == "YAA:STRAIN:bsw191-corrected"


def test_the_slug_matches_the_convention(atlas: sqlite3.Connection) -> None:
    """CONVENTIONS.md writes the example id as YAA:STRAIN:cen-pk113-7d."""
    assert P._strain_id("CEN.PK113-7D") == "YAA:STRAIN:cen-pk113-7d"


def test_a_promoted_bottleneck_carries_its_publication_too(atlas: sqlite3.Connection) -> None:
    """`bottleneck` had the same gap as `measurement` and was fixed in the same migration.

    Worth its own test rather than a parametrization: `bottleneck_fix_attempt`, two tables down in
    `schema.sql`, has carried a real `publication_id` all along, so the missing one here was an
    inconsistency inside a single section of the schema rather than an oversight about one table.
    """
    payload = {
        "node_as_reported": "pyruvate node",
        "claim": "pyruvate supply is limiting",
        "support": "stated_by_authors",
        "zone": "I",
        "confidence": "unverified",
        "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
    }
    atlas.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, "
        "record_kind, payload, status, priority, attempt_count, proposal_hash, curator, "
        "curator_kind, resolved_at, resolution_reason, zone) "
        "VALUES ('YAA:CTASK:bnk', 'YAA:EXTR:test', 'YAA:PUB:test', 'bottlenecks[0]', "
        "'bottlenecks', ?, 'accepted', 1, 0, 'hash-bnk', 'kangkon', 'human', "
        "'2026-09-20T00:00:00Z', 'checked', 'I')",
        (json.dumps(payload),),
    )
    result = P.promote(
        atlas,
        "YAA:CTASK:bnk",
        curator=HUMAN,
        reason="checked",
        supplied={"observation_type": "inferred"},
    )
    row = atlas.execute(
        "SELECT b.publication_id FROM bottleneck b JOIN publication p ON p.id = b.publication_id "
        "WHERE b.id = ?",
        (result.row_id,),
    ).fetchone()
    assert row is not None, "the bottleneck did not join to a publication"
    assert row["publication_id"] == "YAA:PUB:test"


# ------------------------------------------------- the adjacent tier and the configuration row


def _adjacent_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    substrate: str = "xylose",
    value: float = 0.91,
) -> None:
    """One `co_reported_higher_alcohols` proposal, accepted, against the shared fixture span."""
    payload = {
        "product_id": "YAA:PRODUCT:2-methyl-1-butanol",
        "product_as_reported": "2-methyl-1-butanol",
        "quantity_kind": "titer",
        "strain_name_as_reported": "BSW191",
        "value": value,
        "unit": "g/L",
        "substrate": substrate,
        "source_locator": "text",
        "zone": "I",
        "confidence": "unverified",
        "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
    }
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, "
        "record_kind, payload, status, priority, attempt_count, proposal_hash, curator, "
        "curator_kind, resolved_at, resolution_reason, zone) "
        "VALUES (?, 'YAA:EXTR:test', 'YAA:PUB:test', 'co_reported_higher_alcohols[0]', "
        "'co_reported_higher_alcohols', ?, 'accepted', 1, 0, ?, 'kangkon', 'human', "
        "'2026-09-20T00:00:00Z', 'checked', 'I')",
        (task_id, json.dumps(payload), f"hash-{task_id}"),
    )


def _seed_adjacent_product(conn: sqlite3.Connection, tier: str = "adjacent") -> None:
    conn.execute(
        "INSERT INTO product (id, name, tier, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:2-methyl-1-butanol', '2-methyl-1-butanol', ?, 'R', 'test', 'high') "
        "ON CONFLICT(id) DO UPDATE SET tier = excluded.tier",
        (tier,),
    )


def _promote_the_host(conn: sqlite3.Connection) -> P.PromotionResult:
    return P.promote(
        conn,
        "YAA:CTASK:strain",
        curator=HUMAN,
        reason="the host",
        supplied={"organism_id": "YAA:ORG:scer"},
    )


def test_a_higher_alcohol_needs_its_isobutanol_companion(atlas: sqlite3.Connection) -> None:
    """PLAN.md B.1's admission rule, enforced rather than assumed.

    The adjacent tier exists because the *ratio* to isobutanol is diagnostic of where flux leaks.
    A lone 2-methyl-1-butanol titer measures nothing, so it is refused until the companion exists.
    """
    _seed_adjacent_product(atlas)
    _adjacent_task(atlas, "YAA:CTASK:adj")
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:adj")
    assert plan.target_table == "measurement"
    assert any("no isobutanol measurement is promoted" in b for b in plan.blockers)


def test_the_companion_rule_clears_once_isobutanol_is_promoted(atlas: sqlite3.Connection) -> None:
    _seed_adjacent_product(atlas)
    _adjacent_task(atlas, "YAA:CTASK:adj")
    _promote_the_host(atlas)
    P.promote(atlas, "YAA:CTASK:meas", curator=HUMAN, reason="the companion")

    result = P.promote(atlas, "YAA:CTASK:adj", curator=HUMAN, reason="co-reported")
    row = atlas.execute(
        "SELECT product_id, value_as_reported, zone FROM measurement WHERE id = ?",
        (result.row_id,),
    ).fetchone()
    assert row["product_id"] == "YAA:PRODUCT:2-methyl-1-butanol"
    assert row["value_as_reported"] == 0.91
    assert row["zone"] == "R"


def test_the_substrate_survives_promotion(atlas: sqlite3.Connection) -> None:
    """Three siblings differ only by carbon source; dropping it makes them indistinguishable.

    `condition_context` is deliberately unpromotable, so the substrate rides in `evidence`. This
    test exists to fail if that holding position is ever quietly removed.
    """
    _seed_adjacent_product(atlas)
    _adjacent_task(atlas, "YAA:CTASK:adj", substrate="galactose", value=0.93)
    _promote_the_host(atlas)
    P.promote(atlas, "YAA:CTASK:meas", curator=HUMAN, reason="the companion")

    result = P.promote(atlas, "YAA:CTASK:adj", curator=HUMAN, reason="co-reported")
    evidence = atlas.execute(
        "SELECT evidence FROM measurement WHERE id = ?", (result.row_id,)
    ).fetchone()["evidence"]
    assert "galactose" in evidence


def test_a_primary_tier_product_is_refused_by_the_adjacent_promoter(
    atlas: sqlite3.Connection,
) -> None:
    """An isobutanol titer is an ordinary measurement; filing it here would bypass the tier."""
    _seed_adjacent_product(atlas, tier="primary")
    _adjacent_task(atlas, "YAA:CTASK:adj")
    plan = _plan(atlas, "YAA:CTASK:adj")
    assert any("primary-tier" in str(m) for m in plan.missing)


def _configuration_task(conn: sqlite3.Connection, task_id: str, strategy: str) -> None:
    payload = {
        "compartment_strategy": strategy,
        "enzymes_as_reported": ["alsS", "ilvC", "ilvD"],
        "localization_as_reported": "mitochondrial matrix via the Su9 leader peptide",
        "zone": "I",
        "confidence": "unverified",
        "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
    }
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, "
        "record_kind, payload, status, priority, attempt_count, proposal_hash, curator, "
        "curator_kind, resolved_at, resolution_reason, zone) "
        "VALUES (?, 'YAA:EXTR:test', 'YAA:PUB:test', 'pathway_configurations[0]', "
        "'pathway_configurations', ?, 'accepted', 1, 0, ?, 'kangkon', 'human', "
        "'2026-09-20T00:00:00Z', 'checked', 'I')",
        (task_id, json.dumps(payload), f"hash-{task_id}"),
    )


def test_a_configuration_refuses_to_guess_its_host_and_product(
    atlas: sqlite3.Connection,
) -> None:
    """Both are absent from the extraction schema, and both change what the row means."""
    _configuration_task(atlas, "YAA:CTASK:cfg", "C_mitochondrial_ehrlich")
    plan = _plan(atlas, "YAA:CTASK:cfg")
    assert plan.target_table == "pathway_configuration"
    fields = {m.field for m in plan.missing}
    assert "host_strain_id" in fields
    assert "product_id" in fields


def test_an_unseeded_strategy_is_refused(atlas: sqlite3.Connection) -> None:
    _configuration_task(atlas, "YAA:CTASK:cfg", "Z_invented_strategy")
    plan = _plan(atlas, "YAA:CTASK:cfg")
    assert any(m.field == "compartment_strategy_id" for m in plan.missing)


def test_a_configuration_promotes_and_keeps_the_curators_note(
    atlas: sqlite3.Connection,
) -> None:
    """The localization note is where a curator correction lands; it must reach the row."""
    # `compartment_strategy` is seeded by the schema itself -- the five strategies of
    # ISOBUTANOL_PROGRAM.md section 2 are vocabulary, not test data.
    _configuration_task(atlas, "YAA:CTASK:cfg", "C_mitochondrial_ehrlich")
    strain = _promote_the_host(atlas)

    result = P.promote(
        atlas,
        "YAA:CTASK:cfg",
        curator=HUMAN,
        reason="the published build",
        supplied={
            "host_strain_id": strain.row_id,
            "product_id": "YAA:PRODUCT:isobutanol",
        },
    )
    row = atlas.execute(
        "SELECT name, host_strain_id, compartment_strategy_id, description, zone "
        "FROM pathway_configuration WHERE id = ?",
        (result.row_id,),
    ).fetchone()
    assert row["host_strain_id"] == "YAA:STRAIN:bsw191"
    assert row["compartment_strategy_id"] == "C_mitochondrial_ehrlich"
    assert "Su9 leader peptide" in row["description"]
    assert "alsS" in row["description"]
    assert row["zone"] == "R"


# ------------------------------------------------------ the parts catalog's expression records


PART_ID = "YAA:PART:als-s-bacillus"


def _seed_part(conn: sqlite3.Connection, part_id: str = PART_ID) -> str:
    """One catalog entry. Zone I, like every row `metabolic.curated.write_parts` writes."""
    conn.execute(
        "INSERT INTO part (id, step_role_id, zone, evidence, confidence) "
        "VALUES (?, 'AHAS', 'I', 'test fixture', 'unverified') ON CONFLICT(id) DO NOTHING",
        (part_id,),
    )
    return part_id


def _expression_task(conn: sqlite3.Connection, task_id: str, **overrides: object) -> None:
    """One accepted `part_expression_records` proposal against the shared fixture span."""
    payload: dict[str, object] = {
        "part_as_reported": "alsS from Bacillus subtilis",
        "host_as_reported": "BSW191",
        "compartment": "cytosol",
        "compartment_as_reported": "expressed in the cytosol",
        "encoding_genome": "unknown",
        "codon_optimized": "unknown",
        "promoter_as_reported": "TDH3",
        "expressed_ok": "yes",
        "activity_measured": "no",
        "outcome_as_reported": "a band at the expected size",
        "zone": "I",
        "confidence": "unverified",
        "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
    }
    payload.update(overrides)
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, "
        "record_kind, payload, status, priority, attempt_count, proposal_hash, curator, "
        "curator_kind, resolved_at, resolution_reason, zone) "
        "VALUES (?, 'YAA:EXTR:test', 'YAA:PUB:test', 'part_expression_records[0]', "
        "'part_expression_records', ?, 'accepted', 1, 0, ?, 'kangkon', 'human', "
        "'2026-09-20T00:00:00Z', 'checked', 'I')",
        (task_id, json.dumps(payload), f"hash-{task_id}"),
    )


def test_a_part_expression_refuses_to_pick_a_catalog_part_for_the_curator(
    atlas: sqlite3.Connection,
) -> None:
    """The payload carries the paper's wording; `part_id` is a resolution onto a Zone I catalog.

    Guessing it is the identifier error CONVENTIONS.md forbids by name -- the catalog is 16
    unverified entries covering the isobutanol step roles, and "alsS from Bacillus subtilis"
    matching one of them is a judgement a person makes and can be wrong about.
    """
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp")
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp")
    assert plan.target_table == "part_expression_record"
    requirement = next(m for m in plan.missing if m.field == "part_id")
    assert "alsS from Bacillus subtilis" in requirement.why


def test_a_part_id_outside_the_catalog_is_refused(atlas: sqlite3.Connection) -> None:
    """A part that is not in `part` cannot be the subject of an expression record."""
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp")
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id="YAA:PART:not-in-the-catalog")
    assert any("no part with id" in m.why for m in plan.missing)


def test_an_unpromoted_host_blocks_its_expression_record(atlas: sqlite3.Connection) -> None:
    """'Works in E. coli' is only a fact once the host is a row; a NULL host merges two claims."""
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp")

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id=PART_ID)
    assert any("is not promoted as a strain yet" in b for b in plan.blockers)


def test_the_matrix_refuses_a_record_that_does_not_say_which_genome_carried_the_gene(
    atlas: sqlite3.Connection,
) -> None:
    """The compound FK's whole reason for existing, enforced at the one place data enters.

    "Expressed in the matrix" is two different experiments: a presequence-targeted nuclear
    construct that needs no recoding, and a gene placed on mtDNA that reads under NCBI table 3
    and does. Choosing the common case would put recoding advice into Zone R that nobody checked.
    """
    _seed_part(atlas)
    _expression_task(
        atlas,
        "YAA:CTASK:pexp",
        compartment="mitochondrial_matrix",
        compartment_as_reported="targeted to the matrix",
    )
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id=PART_ID)
    requirement = next(m for m in plan.missing if m.field == "encoding_genome")
    assert "both genomes" in requirement.why


def test_an_unambiguous_compartment_derives_its_genome_and_records_that_it_derived_it(
    atlas: sqlite3.Connection,
) -> None:
    """There is no mitochondrially-encoded cytosolic protein, so one value is not a choice.

    Refusing here would make a curator retype the only storable answer; filling it in silently
    would let the row read as though the paper had stated it. So it is derived from
    `compartment_encoding_genome` and the evidence string says that is where it came from.
    """
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp")
    _promote_the_host(atlas)

    result = P.promote(
        atlas,
        "YAA:CTASK:pexp",
        curator=HUMAN,
        reason="the demonstrated host",
        supplied={"part_id": PART_ID},
    )
    row = atlas.execute(
        "SELECT encoding_genome, evidence FROM part_expression_record WHERE id = ?",
        (result.row_id,),
    ).fetchone()
    assert row["encoding_genome"] == "nuclear"
    assert "derived from compartment_encoding_genome" in row["evidence"]


def test_a_compartment_and_genome_pair_that_cannot_exist_is_refused(
    atlas: sqlite3.Connection,
) -> None:
    """The pairing table is the authority, and a row it has no entry for is unstorable anyway."""
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp", encoding_genome="mitochondrial")
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id=PART_ID)
    assert any("mitochondrial genome" in m.why for m in plan.missing)


def test_codon_optimized_is_refused_without_the_code_it_was_optimized_for(
    atlas: sqlite3.Connection,
) -> None:
    """`part_expression_record`'s own comment: optimized for which code?

    Tables 1 and 3 differ at six codons, so a 1 in this column with no genome beside it is a
    claim a bench scientist cannot act on -- and it is exactly the claim they would act on.
    """
    _seed_part(atlas)
    _expression_task(
        atlas,
        "YAA:CTASK:pexp",
        compartment="unknown",
        codon_optimized="yes",
    )
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id=PART_ID)
    assert any(m.field == "encoding_genome" and "which code" in m.why for m in plan.missing)


def test_not_applicable_is_refused_rather_than_stored_as_something_else(
    atlas: sqlite3.Connection,
) -> None:
    """'NA' is a real answer the extraction schema can produce and the column cannot hold.

    NULL would say the paper never mentioned it and 'unknown' would say it did and could not be
    resolved. Both are claims the record does not make, so the promoter says the column cannot
    take the value and leaves the choice to a person.
    """
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp", expressed_ok="NA")
    _promote_the_host(atlas)

    plan = _plan(atlas, "YAA:CTASK:pexp", part_id=PART_ID)
    requirement = next(m for m in plan.missing if m.field == "expressed_ok")
    assert "CHECK accepts only" in requirement.why


def test_an_outcome_measurement_that_is_not_promoted_blocks(atlas: sqlite3.Connection) -> None:
    """A dangling outcome would point the catalog at a number that does not exist."""
    _seed_part(atlas)
    _expression_task(atlas, "YAA:CTASK:pexp")
    _promote_the_host(atlas)

    plan = _plan(
        atlas,
        "YAA:CTASK:pexp",
        part_id=PART_ID,
        outcome_measurement_id="YAA:MEAS:nothing",
    )
    assert any("is not promoted yet" in b for b in plan.blockers)


def test_a_part_expression_promotes_into_zone_r_with_the_papers_wording_kept(
    atlas: sqlite3.Connection,
) -> None:
    """The row phase 1 asks for, with the two outcomes kept apart and the targeting preserved.

    `expressed_ok='yes'` beside `activity_measured='no'` is the honest reading of a band on a gel,
    and it is the distinction the whole record kind exists to make. The presequence lives only in
    `compartment_as_reported`, so its survival into the row is checked too.
    """
    _seed_part(atlas)
    _expression_task(
        atlas,
        "YAA:CTASK:pexp",
        compartment="mitochondrial_matrix",
        compartment_as_reported="targeted to the matrix with the Su9 presequence",
        encoding_genome="nuclear",
    )
    _promote_the_host(atlas)

    result = P.promote(
        atlas,
        "YAA:CTASK:pexp",
        curator=HUMAN,
        reason="the demonstrated host",
        supplied={"part_id": PART_ID},
    )
    row = atlas.execute(
        "SELECT part_id, host_strain_id, compartment_id, encoding_genome, codon_optimized, "
        "promoter, expressed_ok, activity_measured, outcome_measurement_id, publication_id, "
        "zone, evidence, confidence FROM part_expression_record WHERE id = ?",
        (result.row_id,),
    ).fetchone()
    assert row["part_id"] == PART_ID
    assert row["host_strain_id"] == "YAA:STRAIN:bsw191"
    assert (row["compartment_id"], row["encoding_genome"]) == ("mitochondrial_matrix", "nuclear")
    # 'unknown' is not 0: the paper did not say, and a 0 would say they chose not to optimize.
    assert row["codon_optimized"] is None
    assert row["promoter"] == "TDH3"
    assert (row["expressed_ok"], row["activity_measured"]) == ("yes", "no")
    assert row["outcome_measurement_id"] is None
    assert row["publication_id"] == "YAA:PUB:test"
    assert row["zone"] == "R"
    assert "Su9 presequence" in row["evidence"]
    assert "alsS from Bacillus subtilis" in row["evidence"]


# ---------------------------------------------------------------------------------------------
# The bulk supplied-value guard (fermdb.cli._bulk_supply_spread)
# ---------------------------------------------------------------------------------------------


def _accept_strain(conn: sqlite3.Connection, task_id: str, publication_id: str) -> None:
    """An accepted `strains` proposal."""
    _accept_task(conn, task_id, publication_id, "strains")


def _accept_task(
    conn: sqlite3.Connection, task_id: str, publication_id: str, record_kind: str
) -> None:
    """A minimal accepted proposal, with the publication and extraction it hangs off.

    The audit columns are all supplied because `curation_task` CHECKs that an accepted row
    carries curator, kind, resolved_at and reason together -- the trail is not optional.
    """
    conn.execute(
        "INSERT OR IGNORE INTO publication (id, year, zone, evidence, confidence) "
        "VALUES (?, 2020, 'R', 'test fixture', 'low')",
        (publication_id,),
    )
    extraction_id = f"YAA:EXTR:{publication_id.rsplit(':', 1)[-1]}"
    conn.execute(
        "INSERT OR IGNORE INTO extraction (id, publication_id, extractor, extractor_version, "
        "model, prompt_version, input_hash, review_state, zone) "
        "VALUES (?, ?, 'test', '1', 'test-model', 'v1', ?, 'proposed', 'I')",
        (extraction_id, publication_id, f"hash-{publication_id}"),
    )
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_kind, record_path, "
        "payload, proposal_hash, status, curator, curator_kind, resolved_at, resolution_reason, "
        "zone) VALUES (?,?,?,?,?,'{}',?,'accepted','kangkon','human',"
        "'2026-09-22T00:00:00+00:00','test', 'I')",
        (
            task_id,
            extraction_id,
            publication_id,
            record_kind,
            f"{record_kind}[{task_id}]",  # UNIQUE (extraction_id, record_path)
            f"hash-{task_id}",
        ),
    )


def _accept_config(conn: sqlite3.Connection, task_id: str, publication_id: str) -> None:
    """An accepted `pathway_configurations` proposal, for the record-scoped flags."""
    _accept_task(conn, task_id, publication_id, "pathway_configurations")


def test_one_organism_is_refused_across_several_publications(atlas: sqlite3.Connection) -> None:
    """The footgun this exists for, measured on the real queue before it was built.

    `promote` builds `supplied` once and hands the same mapping to every task in the bulk path,
    so a single `--organism` reaches every accepted strain there is. On 2026-09-22 that was 222
    strains from 11 publications, at least 19 of them *E. coli* -- and it is the field that
    separates a yeast build from a bacterial one.
    """
    from fermdb.cli import _bulk_supply_spread

    _accept_strain(atlas, "YAA:CTASK:s1", "YAA:PUB:test")
    _accept_strain(atlas, "YAA:CTASK:s2", "YAA:PUB:other")
    atlas.commit()

    note = _bulk_supply_spread(atlas, {"organism_id": "YAA:ORG:scer"})
    assert note is not None
    assert "2 publication(s)" in note
    assert "YAA:PUB:test" in note and "YAA:PUB:other" in note
    # It must say what to do instead, or it is an obstacle rather than a guard.
    assert "--task" in note


def test_one_organism_is_allowed_within_a_single_publication(atlas: sqlite3.Connection) -> None:
    """A curator who has read one paper can assert its organism. Across papers they have not."""
    from fermdb.cli import _bulk_supply_spread

    _accept_strain(atlas, "YAA:CTASK:s1", "YAA:PUB:test")
    _accept_strain(atlas, "YAA:CTASK:s2", "YAA:PUB:test")
    atlas.commit()

    assert _bulk_supply_spread(atlas, {"organism_id": "YAA:ORG:scer"}) is None


def test_a_record_scoped_value_is_refused_for_two_tasks_even_in_one_paper(
    atlas: sqlite3.Connection,
) -> None:
    """`--name`, `--part` and `--outcome-measurement` name one row, not a paper's worth of them.

    The paper-scoped spread rule would wave these through inside a single publication, and that
    would still be wrong: two configurations cannot share a name, and two expression records
    naming different genes cannot share one catalog part id.
    """
    from fermdb.cli import _bulk_supply_spread

    _accept_config(atlas, "YAA:CTASK:c1", "YAA:PUB:test")
    _accept_config(atlas, "YAA:CTASK:c2", "YAA:PUB:test")
    atlas.commit()

    note = _bulk_supply_spread(atlas, {"name": "the isobutanol build"})
    assert note is not None
    assert "names one specific row" in note
    assert "--name" in note


def test_a_paper_scoped_value_is_still_allowed_for_two_tasks_in_one_paper(
    atlas: sqlite3.Connection,
) -> None:
    """The distinction has to cut both ways or it is just a blanket refusal."""
    from fermdb.cli import _bulk_supply_spread

    _accept_config(atlas, "YAA:CTASK:c1", "YAA:PUB:test")
    _accept_config(atlas, "YAA:CTASK:c2", "YAA:PUB:test")
    atlas.commit()

    assert _bulk_supply_spread(atlas, {"pathway_id": "YAA:PATH:ehrlich"}) is None


def test_promotions_that_need_no_organism_are_never_blocked(atlas: sqlite3.Connection) -> None:
    """The guard is about one flag, not about bulk promotion, which is the useful path."""
    from fermdb.cli import _bulk_supply_spread

    _accept_strain(atlas, "YAA:CTASK:s1", "YAA:PUB:test")
    _accept_strain(atlas, "YAA:CTASK:s2", "YAA:PUB:other")
    atlas.commit()

    assert _bulk_supply_spread(atlas, {}) is None
    assert _bulk_supply_spread(atlas, {"basis": "consumed"}) is None
