"""Tests for `fermdb.metabolic.mtdna_loci` — the activator map, made queryable.

Two properties carry the weight.

**Absence is not emptiness.** `activators = None` means "not recorded"; an empty list would assert
that no activator is required, which is a claim about biology this atlas has no source for at any
locus. BM-MIT-004 exists to catch an insertion design whose activator requirement is NULL, and it
can only catch it if the two are stored differently — so the loader refuses an empty list outright
rather than quietly normalising it.

**One row is not a gene.** `intergenic_upstream_COX2` displaces nothing and keeps respiration.
It is the counterexample to MITOCHONDRIAL_PROGRAM.md §2.1's "inserting a gene costs you the gene
whose UTR you borrowed", and the reason `displaced_if_used` is nullable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.metabolic.mtdna_loci import (
    MtdnaLocusError,
    load_activator_map,
    load_programme_gaps,
    loci_without_activator,
    non_displacing_loci,
    write_loci,
    write_programme_gaps,
)


@pytest.fixture
def loci() -> tuple:
    return load_activator_map(Settings.load())


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------------------- the real curated map


def test_the_curated_map_covers_every_protein_coding_locus(loci: tuple) -> None:
    """All eight of them. S. cerevisiae mtDNA encodes seven OXPHOS subunits plus Var1, and a map
    that stops short of one of them offers a designer a site it cannot describe."""
    names = {locus.locus for locus in loci}
    assert {"COX1", "COX2", "COX3", "COB", "ATP6", "ATP8", "ATP9", "VAR1"} <= names


def test_every_offered_locus_names_its_activator(loci: tuple) -> None:
    """BM-MIT-004's stated failure mode: "An insertion design returned with activator_required
    NULL is the failure mode this entry exists to catch." Today none is NULL."""
    assert loci_without_activator(loci) == ()


def test_every_locus_carries_evidence_and_a_confidence(loci: tuple) -> None:
    """CONVENTIONS.md requires both on every curated row, and a placeholder is not an exemption."""
    for locus in loci:
        assert locus.evidence.strip()
        assert locus.confidence in {"unverified", "low", "medium", "high"}


def test_exactly_one_locus_displaces_nothing(loci: tuple) -> None:
    """The pPT24 silent region upstream of COX2. If this ever returns empty, strategy E's cost
    model changes shape — every insert would then carry a respiration burden."""
    free = non_displacing_loci(loci)
    assert [locus.locus for locus in free] == ["intergenic_upstream_COX2"]
    assert free[0].utr_source == "COX2", "it borrows COX2's leader; it has none of its own"
    assert free[0].displaced_if_used is None


def test_a_gene_locus_defaults_to_driving_an_insert_with_its_own_leader(loci: tuple) -> None:
    by_name = {locus.locus: locus for locus in loci}
    assert by_name["VAR1"].utr_source == "VAR1"
    assert by_name["ATP8"].utr_source == "ATP8"


def test_taking_a_gene_locus_costs_respiration(loci: tuple) -> None:
    """Every one of the eight. That is what makes the intergenic row worth having."""
    for locus in loci:
        if locus.displaced_if_used is not None:
            assert locus.respiration_retained_if_used is False


# ----------------------------------------------------------------------- malformed input


def test_an_empty_activator_list_is_refused_rather_than_normalised(tmp_path: Path) -> None:
    """The distinction this whole module protects. `[]` would read as "no activator required",
    which is a biological claim; the loader makes you omit the key to mean "not recorded"."""
    path = _write(
        tmp_path / "map.yaml",
        "version: 1\nloci:\n  - locus: COX2\n    activators: []\n    evidence: x\n",
    )
    with pytest.raises(MtdnaLocusError, match="empty activator list"):
        load_activator_map(Settings.load(), path=path)


def test_a_missing_activator_key_means_not_recorded(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "map.yaml",
        "version: 1\nloci:\n  - locus: COX2\n    evidence: carried over, unchecked\n",
    )
    loaded = load_activator_map(Settings.load(), path=path)
    assert loaded[0].activators is None
    assert loci_without_activator(loaded) == loaded


def test_a_row_without_evidence_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "map.yaml", "version: 1\nloci:\n  - locus: COX2\n")
    with pytest.raises(MtdnaLocusError, match="no evidence"):
        load_activator_map(Settings.load(), path=path)


def test_a_duplicated_locus_is_refused(tmp_path: Path) -> None:
    """It is a catalogue. Two rows for one site would make a design lookup ambiguous."""
    path = _write(
        tmp_path / "map.yaml",
        "version: 1\nloci:\n  - locus: COX2\n    evidence: a\n  - locus: COX2\n    evidence: b\n",
    )
    with pytest.raises(MtdnaLocusError, match="appears twice"):
        load_activator_map(Settings.load(), path=path)


def test_an_unknown_rescue_strategy_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "map.yaml",
        "version: 1\nloci:\n  - locus: COX2\n    evidence: a\n    rescue_available: wishful\n",
    )
    with pytest.raises(MtdnaLocusError, match="rescue_available"):
        load_activator_map(Settings.load(), path=path)


def test_a_missing_map_raises_rather_than_returning_nothing(tmp_path: Path) -> None:
    """An empty map would make every design query answer "no constraint", which is the opposite
    of what §2.1 says is true and is more dangerous than an error."""
    with pytest.raises(MtdnaLocusError, match="no activator map"):
        load_activator_map(Settings.load(), path=tmp_path / "absent.yaml")


# ------------------------------------------------------------------------------- storage


def test_loci_round_trip_through_the_table(tmp_path: Path, loci: tuple) -> None:
    conn = open_db(tmp_path / "t.sqlite3")
    try:
        assert write_loci(conn, loci) == len(loci)
        rows = {r["locus"]: r for r in conn.execute("SELECT * FROM mtdna_locus").fetchall()}
        assert len(rows) == len(loci)
        assert json.loads(rows["ATP8"]["activators"]) == ["Aep3"]
        assert rows["intergenic_upstream_COX2"]["displaced_if_used"] is None
        assert rows["intergenic_upstream_COX2"]["respiration_retained_if_used"] == 1
        assert rows["VAR1"]["respiration_retained_if_used"] == 0
    finally:
        conn.close()


def test_written_loci_survive_closing_the_connection(tmp_path: Path, loci: tuple) -> None:
    """The regression that shipped: `write_loci` did not commit, so `atlas loci` printed nine rows
    and stored none. Every assertion in this file passed anyway, because they all read back
    through the same open connection that did the writing — which sees uncommitted rows.

    Reopening is the only version of this test that can fail.
    """
    database = tmp_path / "persist.sqlite3"
    conn = open_db(database)
    try:
        write_loci(conn, loci)
    finally:
        conn.close()

    reopened = open_db(database, create=False)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM mtdna_locus").fetchone()[0] == len(loci)
    finally:
        reopened.close()


def test_writing_twice_is_idempotent(tmp_path: Path, loci: tuple) -> None:
    conn = open_db(tmp_path / "t.sqlite3")
    try:
        write_loci(conn, loci)
        write_loci(conn, loci)
        assert conn.execute("SELECT COUNT(*) FROM mtdna_locus").fetchone()[0] == len(loci)
    finally:
        conn.close()


def test_the_design_lookup_bm_mit_004_asks_for_resolves(tmp_path: Path, loci: tuple) -> None:
    """BM-MIT-004's query_shape, run as SQL: "for a proposed insertion locus, return utr_source,
    activator_required and displaced_gene". Before `mtdna_locus` this returned nothing."""
    conn = open_db(tmp_path / "t.sqlite3")
    try:
        write_loci(conn, loci)
        row = conn.execute(
            "SELECT utr_source, activators, displaced_if_used FROM mtdna_locus WHERE locus = ?",
            ("COX2",),
        ).fetchone()
        assert row is not None
        assert row["utr_source"] == "COX2"
        assert json.loads(row["activators"]) == ["Pet111"]
        assert row["displaced_if_used"] == "COX2"
    finally:
        conn.close()


def test_the_free_site_is_findable_by_query_not_only_in_python(tmp_path: Path, loci: tuple) -> None:
    conn = open_db(tmp_path / "t.sqlite3")
    try:
        write_loci(conn, loci)
        found = conn.execute(
            "SELECT locus FROM mtdna_locus WHERE displaced_if_used IS NULL "
            "AND respiration_retained_if_used = 1"
        ).fetchall()
        assert [r["locus"] for r in found] == ["intergenic_upstream_COX2"]
    finally:
        conn.close()


# ------------------------------------------------- programme gaps, §2.3's unkept promise


@pytest.fixture
def gaps() -> tuple:
    return load_programme_gaps(Settings.load())


def test_the_precedents_file_yields_never_attempted_gaps(gaps: tuple) -> None:
    """MITOCHONDRIAL_PROGRAM.md §2.3 says the atlas "records this as a `knowledge_gap` of kind
    `never_attempted`". Before this loader, `knowledge_gap` held 208 rows and not one of that
    kind — the document described a behaviour nothing implemented."""
    assert gaps
    assert all(gap.kind == "never_attempted" for gap in gaps)


def test_a_gap_is_not_hung_off_a_route(gaps: tuple) -> None:
    """Route gaps come from gate output and describe a proposed route. These describe the field:
    they are true whether or not anyone enumerates a route, so they hang off the compartment."""
    assert all(gap.compartment_id == "mitochondrial_matrix" for gap in gaps)


def test_kind_and_status_are_kept_apart(gaps: tuple) -> None:
    """The curated file used to write `status: never_attempted`, conflating what a gap IS with how
    far it has got. A loader reading that literally would have written an illegal status."""
    assert all(gap.status == "open" for gap in gaps)


def test_a_gap_naming_an_illegal_kind_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "p.yaml",
        "open_gaps:\n  - gap: something\n    kind: vibes\n    status: open\n",
    )
    with pytest.raises(MtdnaLocusError, match="not one of"):
        load_programme_gaps(Settings.load(), path=path)


def test_a_gap_naming_an_illegal_status_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "p.yaml",
        "open_gaps:\n  - gap: x\n    kind: never_attempted\n    status: never_attempted\n",
    )
    with pytest.raises(MtdnaLocusError, match="status="):
        load_programme_gaps(Settings.load(), path=path)


def test_programme_gaps_survive_closing_the_connection(tmp_path: Path, gaps: tuple) -> None:
    database = tmp_path / "gaps.sqlite3"
    conn = open_db(database)
    try:
        assert write_programme_gaps(conn, gaps) == len(gaps)
    finally:
        conn.close()

    reopened = open_db(database, create=False)
    try:
        count = reopened.execute(
            "SELECT COUNT(*) FROM knowledge_gap WHERE kind = 'never_attempted'"
        ).fetchone()[0]
        assert count == len(gaps)
    finally:
        reopened.close()
