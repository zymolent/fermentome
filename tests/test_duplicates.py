"""Proposals that describe a measurement the atlas already holds under a different id."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

import pytest

from fermdb.curate.duplicates import find_duplicates
from fermdb.db import IN_MEMORY, open_db

PUB = "doi:10.9999/paper-a"


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    conn = open_db(IN_MEMORY)
    conn.executescript(
        f"""
        INSERT INTO organism (id, name, zone, evidence, confidence)
            VALUES ('YAA:ORG:scer', 'S. cerevisiae', 'R', 'test', 'low');
        INSERT INTO product (id, name, zone, evidence, confidence)
            VALUES ('YAA:PRODUCT:isobutanol', 'isobutanol', 'R', 'test', 'low');
        INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence)
            VALUES ('YAA:STRAIN:bsw205', 'YAA:ORG:scer', 'BSW205', 'engineered', 'R', 'x', 'low');
        INSERT INTO publication (id, zone, evidence, confidence)
            VALUES ('{PUB}', 'R', 'test', 'low');
        INSERT INTO extraction (id, publication_id, extractor, extractor_version, model,
                                prompt_version, input_hash, review_state, zone)
            VALUES ('YAA:EXTR:a', '{PUB}', 'test', '1', 'm', 'v1', 'h', 'proposed', 'I');
        INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported,
                                 unit_as_reported, source_locator, publication_id, zone,
                                 evidence, confidence)
            VALUES ('YAA:MEAS:thin', 'YAA:STRAIN:bsw205', 'titer', 'YAA:PRODUCT:isobutanol',
                    1.62, 'g/L', 'text', '{PUB}', 'R', 'promoted', 'medium');
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def _propose(conn: sqlite3.Connection, task_id: str, **payload: object) -> None:
    body = {
        "quantity_kind": "titer",
        "strain_name_as_reported": "BSW205",
        "value": 1.62,
        "unit": "g/L",
        **payload,
    }
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_kind, record_path, "
        "payload, proposal_hash, status, zone) "
        "VALUES (?, 'YAA:EXTR:a', ?, 'measurements', ?, ?, ?, 'pending', 'I')",
        (task_id, PUB, f"measurements[{task_id}]", json.dumps(body), f"hash-{task_id}"),
    )
    conn.commit()


def test_a_reextracted_proposal_is_matched_to_the_row_it_would_duplicate(
    atlas: sqlite3.Connection,
) -> None:
    """The 2026-09-22 case: re-extraction after the sectioner fix re-proposed promoted rows.

    `proposal_hash` covers the quote, so a differently-worded quote for the same number gets a
    different `YAA:MEAS:` id and promotion's own "already present" check never fires.
    """
    _propose(atlas, "YAA:CTASK:again")
    found = find_duplicates(atlas)
    assert len(found) == 1
    assert found[0].measurement_id == "YAA:MEAS:thin"
    assert found[0].supersedes is False


def test_a_proposal_carrying_basis_the_promoted_row_lacks_is_a_supersession(
    atlas: sqlite3.Connection,
) -> None:
    """Richer, not merely repeated -- and which to keep is a curator's call, not this module's.

    Note what is NOT counted: the promoted row's `source_locator` is 'text' and the proposal's is
    'figure 5', which is plainly more specific -- and this reports only NULL becoming a value.
    Ranking one non-null locator above another is a judgement about the paper, so it is left to
    the person who reads it rather than guessed at by string length.
    """
    _propose(atlas, "YAA:CTASK:richer", basis="consumed", source_locator="figure 5")
    found = find_duplicates(atlas)
    assert len(found) == 1
    assert found[0].supersedes
    assert set(found[0].adds) == {"basis"}


def test_time_is_not_counted_as_richness_because_the_atlas_cannot_store_it(
    atlas: sqlite3.Connection,
) -> None:
    """`measurement` has no time column: time lives on `condition_context`, which has no rows.

    So a proposal carrying "at 24 h" is not richer in any way that survives promotion, and
    reporting it as such would promise a precision the schema cannot keep. The loss is real and
    is recorded in the module docstring rather than disguised here.
    """
    _propose(atlas, "YAA:CTASK:timed", time_h=24)
    found = find_duplicates(atlas)
    assert len(found) == 1
    assert found[0].supersedes is False
    assert "time_h" not in found[0].adds


def test_a_different_value_is_not_a_duplicate(atlas: sqlite3.Connection) -> None:
    _propose(atlas, "YAA:CTASK:other", value=2.10)
    assert find_duplicates(atlas) == ()


def test_the_same_number_from_another_paper_is_not_a_duplicate(
    atlas: sqlite3.Connection,
) -> None:
    """Two labs reporting 1.62 g/L for one strain is replication, which the atlas wants."""
    atlas.execute(
        "INSERT INTO publication (id, zone, evidence, confidence) "
        "VALUES ('doi:10.9999/paper-b', 'R', 'test', 'low')"
    )
    atlas.execute(
        "INSERT INTO extraction (id, publication_id, extractor, extractor_version, model, "
        "prompt_version, input_hash, review_state, zone) "
        "VALUES ('YAA:EXTR:b', 'doi:10.9999/paper-b', 'test', '1', 'm', 'v1', 'h2', "
        "'proposed', 'I')"
    )
    atlas.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_kind, record_path, "
        "payload, proposal_hash, status, zone) VALUES ('YAA:CTASK:b', 'YAA:EXTR:b', "
        "'doi:10.9999/paper-b', 'measurements', 'measurements[0]', ?, 'hb', 'pending', 'I')",
        (
            json.dumps(
                {
                    "quantity_kind": "titer",
                    "strain_name_as_reported": "BSW205",
                    "value": 1.62,
                    "unit": "g/L",
                }
            ),
        ),
    )
    atlas.commit()
    assert find_duplicates(atlas) == ()


def test_a_proposal_with_no_strain_is_skipped_rather_than_guessed_at(
    atlas: sqlite3.Connection,
) -> None:
    """Without a subject there is no identity to match on, and inventing one is the whole sin."""
    _propose(atlas, "YAA:CTASK:nostrain", strain_name_as_reported=None)
    assert find_duplicates(atlas) == ()
