"""Tests for `fermdb.query.review`.

The packet's whole value is that it tells a curator something they would otherwise find out too
late, or not at all. So the tests are about the warnings and about the span being *re-resolved*
rather than echoed -- a stored quote proves only that a model once emitted that string.

One test here is not about behaviour but about layering: the review packet lives in the query
package, which is read-only, and it calls into `curate.promote` to plan a promotion. Planning
writes nothing, but "writes nothing" is the kind of property that quietly stops being true, so it
is asserted rather than assumed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.query import review as R

QUOTE = "the isobutanol titer reached 1.62 g/L at 24 h"
PREFIX = "Results and discussion. Cells were grown to stationary phase. "
SUFFIX = " Strain BSW191 was grown in YPD at 30 C with shaking at 200 rpm."
SOURCE = PREFIX + QUOTE + SUFFIX
START = SOURCE.index(QUOTE)
END = START + len(QUOTE)


def _measurement(strain: str = "BSW191", **over: object) -> dict[str, object]:
    record: dict[str, object] = {
        "quantity_kind": "titer",
        "product_id": "YAA:PRODUCT:isobutanol",
        "strain_name_as_reported": strain,
        "value": 1.62,
        "unit": "g/L",
        "source_locator": "text",
        "assay_method": None,
        "zone": "I",
        "confidence": "unverified",
        "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
    }
    record.update(over)
    return record


@pytest.fixture()
def atlas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A publication with stored full text, one strain proposal and one measurement proposal."""
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FERMDB_DB_FILE", str(tmp_path / "data" / "fermdb.sqlite3"))
    settings = Settings.load()
    conn = open_db(settings.db_file)

    relative = Path("fulltext") / "aa" / "paper.txt"
    (settings.data_dir / relative).parent.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / relative).write_text(SOURCE, encoding="utf-8")

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
            VALUES ('YAA:EXTR:test', 'YAA:PUB:test', 'test', '1', 'test-model', 'v1', 'h',
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
    _add_task(
        conn,
        "YAA:CTASK:strain",
        "strains",
        "strains[0]",
        {
            "name_as_reported": "BSW191",
            "role": "engineered",
            "zone": "I",
            "confidence": "unverified",
            "span": {"quote": QUOTE, "char_start": START, "char_end": END, "section": "results"},
        },
    )
    _add_task(conn, "YAA:CTASK:meas", "measurements", "measurements[0]", _measurement())
    conn.commit()
    yield conn
    conn.close()


def _add_task(
    conn: sqlite3.Connection,
    task_id: str,
    kind: str,
    path: str,
    payload: dict[str, object],
    *,
    status: str = "pending",
    digest: str | None = None,
    extraction_id: str = "YAA:EXTR:test",
) -> None:
    resolved = status in {"accepted", "edited", "rejected"}
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, record_kind, "
        "payload, status, priority, attempt_count, proposal_hash, curator, curator_kind, "
        "resolved_at, resolution_reason, zone) "
        "VALUES (?, ?, 'YAA:PUB:test', ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, 'I')",
        (
            task_id,
            extraction_id,
            path,
            kind,
            json.dumps(payload),
            status,
            digest or f"hash-{task_id}",
            "kangkon" if resolved else None,
            "human" if resolved else None,
            "2026-09-20T00:00:00Z" if resolved else None,
            "test" if resolved else None,
        ),
    )


# ------------------------------------------------------------------------------- the span


def test_the_quote_comes_back_from_the_source_not_the_payload(atlas: sqlite3.Connection) -> None:
    """A stored quote proves only that a model once emitted that string.

    The packet shows the document's own text at the recorded offsets, so a curator reading the
    packet is reading the paper, not the extraction's account of it.
    """
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assert packet.span.resolves
    assert packet.span.status == "verified"
    assert packet.span.quote_in_source == QUOTE
    # Surrounding sentences travel too, which is what makes a misread row visible.
    assert "stationary phase" in packet.span.before
    assert "YPD" in packet.span.after
    assert ">>>" in packet.span.context and "<<<" in packet.span.context


def test_a_moved_span_is_flagged_and_still_shows_where_it_actually_is(
    atlas: sqlite3.Connection,
) -> None:
    """Stale offsets are a warning, not a dead end -- the curator can still see the sentence."""
    record = _measurement()
    span = record["span"]
    assert isinstance(span, dict)
    span["char_start"] = 0
    span["char_end"] = len(QUOTE)
    atlas.execute(
        "UPDATE curation_task SET payload = ? WHERE id = 'YAA:CTASK:meas'", (json.dumps(record),)
    )
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assert packet.span.status == "moved"
    assert not packet.span.resolves
    assert packet.span.verdict.found_at == START
    assert packet.span.quote_in_source == QUOTE  # shown at the place it really is
    assert any(w.code == "span_unverified" for w in packet.warnings)


def test_a_quote_absent_from_the_source_is_reported_as_such(atlas: sqlite3.Connection) -> None:
    record = _measurement()
    span = record["span"]
    assert isinstance(span, dict)
    span["quote"] = "a sentence this paper does not contain"
    atlas.execute(
        "UPDATE curation_task SET payload = ? WHERE id = 'YAA:CTASK:meas'", (json.dumps(record),)
    )
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assert packet.span.status == "absent"
    assert packet.span.context == ""  # nothing honest to show
    assert any(w.code == "span_unverified" for w in packet.warnings)


# ------------------------------------------------------------------------------- the warnings


def test_a_measurement_whose_strain_was_never_proposed_is_flagged(
    atlas: sqlite3.Connection,
) -> None:
    """The real case: the Wess series proposed 6 strains and its measurements referenced 8.

    Promotion blocks this too, but by then the curator has already accepted it. The fact is the
    same; delivering it during review is what makes it actionable.
    """
    _add_task(
        atlas,
        "YAA:CTASK:orphan",
        "measurements",
        "measurements[1]",
        _measurement(strain="JWY04 + gpd1/2", value=1.32),
    )
    packet = R.review_packet(atlas, "YAA:CTASK:orphan")
    warning = next(w for w in packet.warnings if w.code == "strain_never_proposed")
    assert "JWY04 + gpd1/2" in warning.message
    assert "reviewing cannot create one" in warning.message

    # The strain that *was* proposed draws no warning.
    assert not any(
        w.code == "strain_never_proposed" for w in R.review_packet(atlas, "YAA:CTASK:meas").warnings
    )


def test_a_proposal_a_curator_already_rejected_is_flagged(atlas: sqlite3.Connection) -> None:
    """Accepting it now silently reverses a decision somebody made deliberately.

    The repeat comes from a second extraction, because (extraction_id, record_path) is unique --
    which is how it happens for real: the paper is extracted again and the model proposes the
    same thing.
    """
    for suffix, version in (("first", "v0"), ("rerun", "v2")):
        atlas.execute(
            "INSERT INTO extraction (id, publication_id, extractor, extractor_version, model, "
            "prompt_version, input_hash, review_state, zone) VALUES (?, 'YAA:PUB:test', 'test', "
            "'1', 'test-model', ?, ?, 'proposed', 'I')",
            (f"YAA:EXTR:{suffix}", version, f"h-{suffix}"),
        )
    _add_task(
        atlas,
        "YAA:CTASK:old",
        "measurements",
        "measurements[0]",
        _measurement(),
        status="rejected",
        digest="shared-hash",
        extraction_id="YAA:EXTR:first",
    )
    _add_task(
        atlas,
        "YAA:CTASK:again",
        "measurements",
        "measurements[0]",
        _measurement(),
        digest="shared-hash",
        extraction_id="YAA:EXTR:rerun",
    )
    packet = R.review_packet(atlas, "YAA:CTASK:again")
    assert packet.times_proposed == 2
    assert packet.times_rejected == 1
    warning = next(w for w in packet.warnings if w.code == "previously_rejected")
    assert "reverses that decision" in warning.message


def test_a_kind_nothing_can_promote_is_flagged_once_accepted(atlas: sqlite3.Connection) -> None:
    """Accepting a condition today leaves it in the queue. Better to know while deciding."""
    _add_task(
        atlas,
        "YAA:CTASK:bn",
        "conditions",
        "conditions[0]",
        {
            "zone": "I",
            "confidence": "unverified",
            "span": {"quote": QUOTE, "char_start": START, "char_end": END},
        },
        status="accepted",
    )
    packet = R.review_packet(atlas, "YAA:CTASK:bn")
    assert any(w.code == "no_promoter" for w in packet.warnings)


def test_a_clean_proposal_carries_no_warnings(atlas: sqlite3.Connection) -> None:
    """The warnings have to mean something, so they must not fire on a good record."""
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assert packet.warnings == ()
    assert packet.needs_attention is False


# --------------------------------------------------------------------------------- the fields


def test_a_field_the_model_left_null_is_absent_not_missing(atlas: sqlite3.Connection) -> None:
    """ "The model looked and found nothing" is not "this key is not part of this record kind"."""
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assay = next(f for f in packet.fields if f.name == "assay_method")
    assert assay.value.is_known is False
    assert assay.value.display == "not recorded"
    assert "value" not in assay.value.as_json()


def test_the_proposal_is_marked_zone_i_throughout(atlas: sqlite3.Connection) -> None:
    """Nothing in a packet may render as established fact: it is all model output until promoted."""
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    for proposed in packet.fields:
        assert proposed.value.as_json()["zone"] == "I"
    assert packet.model_confidence.as_json()["zone"] == "I"


def test_bookkeeping_keys_are_not_shown_as_proposed_content(atlas: sqlite3.Connection) -> None:
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    names = {f.name for f in packet.fields}
    assert not names & {"span", "zone", "review_state", "confidence"}
    assert "value" in names and "unit" in names


def test_the_citation_cannot_be_omitted(atlas: sqlite3.Connection) -> None:
    """PLAN.md O.2.1 as a type: a packet names what it cites or it does not exist."""
    packet = R.review_packet(atlas, "YAA:CTASK:meas")
    assert packet.citation.source_id == "YAA:PUB:test"
    assert packet.citation.source_kind == "publication"


# ------------------------------------------------------------------- what accepting leads to


def test_the_packet_says_what_accepting_would_write(atlas: sqlite3.Connection) -> None:
    """So a curator sees the organism requirement while deciding, not at promotion time."""
    strain = R.review_packet(atlas, "YAA:CTASK:strain")
    assert "only an accepted or edited proposal" in strain.plan.note

    atlas.execute(
        "UPDATE curation_task SET status='accepted', curator='k', curator_kind='human', "
        "resolved_at='2026-09-20T00:00:00Z', resolution_reason='ok' WHERE id='YAA:CTASK:strain'"
    )
    accepted = R.review_packet(atlas, "YAA:CTASK:strain")
    assert [m.field for m in accepted.plan.missing] == ["organism_id"]

    supplied = R.review_packet(atlas, "YAA:CTASK:strain", supplied={"organism_id": "YAA:ORG:scer"})
    assert supplied.plan.ready
    assert supplied.plan.row["id"] == "YAA:STRAIN:bsw191"


# ------------------------------------------------------------------------------- layering


def test_building_a_packet_writes_nothing(atlas: sqlite3.Connection) -> None:
    """The query package is read-only, and it plans a promotion to build this.

    Planning writes nothing today. That is the kind of property that quietly stops being true
    when someone adds a cache or an audit row, so it is asserted rather than assumed.
    """
    before = atlas.total_changes
    R.review_queue(atlas, limit=10)
    assert atlas.total_changes == before
    assert atlas.execute("SELECT COUNT(*) FROM strain").fetchone()[0] == 0
    assert atlas.execute("SELECT COUNT(*) FROM curation_event").fetchone()[0] == 0


def test_the_queue_view_takes_no_lease(atlas: sqlite3.Connection) -> None:
    """Looking at what is waiting is not starting work on it."""
    R.review_queue(atlas, limit=10)
    claimed = atlas.execute(
        "SELECT COUNT(*) FROM curation_task WHERE claimed_by IS NOT NULL"
    ).fetchone()[0]
    assert claimed == 0


def test_the_queue_can_be_filtered_by_kind(atlas: sqlite3.Connection) -> None:
    packets = R.review_queue(atlas, limit=10, kinds=("measurements",))
    assert {p.record_kind for p in packets} == {"measurements"}


def test_an_orphan_measurement_points_at_the_better_anchored_alternative(
    atlas: sqlite3.Connection,
) -> None:
    """`strain_never_proposed` on its own leaves a curator stuck.

    The measurement cannot acquire a subject, but rejecting it might lose the number. If the same
    value is already proposed against a strain that exists, the number is safe and rejecting is
    the clean move -- which is a fact the atlas holds and nobody was asking it for.
    """
    atlas.execute(
        "INSERT INTO extraction (id, publication_id, extractor, extractor_version, model, "
        "prompt_version, input_hash, review_state, zone) VALUES ('YAA:EXTR:fix', 'YAA:PUB:test', "
        "'test', '1', 'test-model', 'v2', 'h3', 'proposed', 'I')"
    )
    # The synthesised label nothing will ever match...
    _add_task(
        atlas,
        "YAA:CTASK:synth",
        "measurements",
        "measurements[7]",
        _measurement(strain="BSW191 + gpd1/2", value=7.77),
    )
    # ...and the same number, properly attributed, from a second extraction. A distinct value, so
    # the alternative found is unambiguously this one and not the fixture's own BSW191 record.
    _add_task(
        atlas,
        "YAA:CTASK:anchored",
        "measurements",
        "measurements[7]",
        _measurement(strain="BSW191", value=7.77),
        extraction_id="YAA:EXTR:fix",
    )
    packet = R.review_packet(atlas, "YAA:CTASK:synth")
    codes = {w.code for w in packet.warnings}
    assert "strain_never_proposed" in codes
    alt = next(w for w in packet.warnings if w.code == "alternative_with_known_strain")
    assert "YAA:CTASK:anchored" in alt.message
    assert "not lost if this record is rejected" in alt.message

    # The well-formed one draws neither warning.
    assert R.review_packet(atlas, "YAA:CTASK:anchored").warnings == ()


def test_a_different_number_is_not_offered_as_an_alternative(
    atlas: sqlite3.Connection,
) -> None:
    """The match is on the value, so an unrelated measurement is not proposed as a replacement."""
    atlas.execute(
        "INSERT INTO extraction (id, publication_id, extractor, extractor_version, model, "
        "prompt_version, input_hash, review_state, zone) VALUES ('YAA:EXTR:other', "
        "'YAA:PUB:test', 'test', '1', 'test-model', 'v2', 'h4', 'proposed', 'I')"
    )
    _add_task(
        atlas,
        "YAA:CTASK:synth2",
        "measurements",
        "measurements[8]",
        _measurement(strain="BSW191 + gpd1/2", value=8.88),
    )
    _add_task(
        atlas,
        "YAA:CTASK:different",
        "measurements",
        "measurements[8]",
        _measurement(strain="BSW191", value=9.99),
        extraction_id="YAA:EXTR:other",
    )
    codes = {w.code for w in R.review_packet(atlas, "YAA:CTASK:synth2").warnings}
    assert "alternative_with_known_strain" not in codes
