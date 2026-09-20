"""Tests for `fermdb.db.vocabularies`.

The gap these close was not cosmetic. `measurement.product_id` is a foreign key onto `product`,
and `product` was empty, so no measurement could be stored at all -- perfect extraction would have
had nowhere to put its numbers, and the failure would have surfaced as a foreign-key error inside
a curation run rather than as the missing loader it was.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.db.vocabularies import (
    PRODUCTS_FILE,
    VocabularyError,
    load_vocabularies,
    read_tsv,
)

PATHS_FILE = Path(__file__).resolve().parents[1] / "env" / "paths.yaml"


@pytest.fixture
def settings() -> Settings:
    return Settings.load(paths_file=PATHS_FILE, env={})


@pytest.fixture
def conn() -> sqlite3.Connection:
    return open_db(IN_MEMORY)


def test_comment_lines_are_stripped_before_the_header(settings: Settings) -> None:
    """products.tsv opens with 43 comment lines. A reader that took line 1 as the header would
    parse the whole file into one nonsense column and load nothing."""
    rows = list(read_tsv(Path(settings.path("vocabularies_dir")) / PRODUCTS_FILE))
    assert rows
    assert all("id" in row and "name" in row for row in rows)


def test_a_missing_file_raises_rather_than_loading_nothing(tmp_path: Path) -> None:
    with pytest.raises(VocabularyError, match="source of truth"):
        list(read_tsv(tmp_path / "absent.tsv"))


def test_every_product_in_the_file_reaches_the_table(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    expected = len(list(read_tsv(Path(settings.path("vocabularies_dir")) / PRODUCTS_FILE)))
    counts = load_vocabularies(conn, settings)
    assert counts["product"] == expected
    assert conn.execute("SELECT COUNT(*) FROM product").fetchone()[0] == expected


def test_loading_is_idempotent(conn: sqlite3.Connection, settings: Settings) -> None:
    first = load_vocabularies(conn, settings)
    second = load_vocabularies(conn, settings)
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM product").fetchone()[0] == first["product"]


def test_the_yield_state_survives_the_load(conn: sqlite3.Connection, settings: Settings) -> None:
    """A yield can be known, not applicable, or sought-and-unsettled. validate.py refuses to
    enforce a ceiling whose state is not known, so flattening the state here would turn an open
    question into a number the validator would then police."""
    load_vocabularies(conn, settings)
    states = {
        row[0]
        for row in conn.execute("SELECT DISTINCT g_per_g_state FROM product_theoretical_yield")
    }
    assert states, "every yield row must carry a state"
    assert states <= {"recorded", "unknown", "NA"}


def test_the_isobutanol_ceiling_is_the_one_the_plan_names(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """PLAN.md's phase-1 acceptance names the 0.411 g/g bound explicitly. If this drifts, every
    yield check drifts with it."""
    load_vocabularies(conn, settings)
    row = conn.execute(
        "SELECT g_per_g, g_per_g_state FROM product_theoretical_yield "
        "WHERE product_id = 'YAA:PRODUCT:isobutanol' AND substrate = 'glucose'"
    ).fetchone()
    assert row is not None
    assert row["g_per_g"] == pytest.approx(0.411)
    assert row["g_per_g_state"] == "recorded"


def test_a_measurement_can_be_stored_once_the_vocabulary_exists(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The point of the whole module. Before it, this insert failed on the product foreign key."""
    load_vocabularies(conn, settings)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc','S. cerevisiae','R','t','high')"
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:x','YAA:ORG:sc','IBA-7','I','t','unverified')"
    )
    conn.execute(
        "INSERT INTO measurement (id, strain_id, quantity_kind, product_id, value_as_reported, "
        "unit_as_reported, is_fraction, is_below_lod, is_upper_bound, is_digitized, "
        "source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:M:t','YAA:STRAIN:x','titer','YAA:PRODUCT:isobutanol','22.6','g/L',"
        "0,0,0,0,'text','I','t','unverified')"
    )
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 1


def test_a_measurement_naming_an_unknown_product_is_still_refused(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Loading the vocabulary opens the door for real products only; the foreign key still holds."""
    load_vocabularies(conn, settings)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc','S. cerevisiae','R','t','high')"
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:x','YAA:ORG:sc','IBA-7','I','t','unverified')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO measurement (id, strain_id, quantity_kind, product_id, "
            "value_as_reported, unit_as_reported, is_fraction, is_below_lod, is_upper_bound, "
            "is_digitized, source_locator, zone, evidence, confidence) "
            "VALUES ('YAA:M:u','YAA:STRAIN:x','titer','YAA:PRODUCT:unobtainium','1','g/L',"
            "0,0,0,0,'text','I','t','unverified')"
        )
