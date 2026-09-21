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
