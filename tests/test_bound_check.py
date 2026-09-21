"""Tests for `fermdb.metabolic.bound_check` — the 0.411 g/g ceiling, run against stored rows.

Three properties carry the weight, and all three are about *not* answering.

**A violation must be found.** The check exists because several early yeast isobutanol reports
have been questioned on carbon-balance grounds (PLAN.md B.2). A check that cannot flag is
decoration, so the flagging path is tested against a number above the ceiling.

**An unknown substrate must not become glucose.** The ceiling is keyed on (product, substrate) and
`measurement` has no substrate column. Defaulting to glucose would invent a ceiling: for a product
whose glucose figure is the only one recorded, that either launders a xylose violation or rejects
a real xylose number. So a measurement with no recoverable substrate is `not_evaluable`, and the
test asserts the verdict rather than the value.

**An unrecorded ceiling is not a missing ceiling.** `product_theoretical_yield` stores
`g_per_g_state='unknown'` for the products whose assumed pathway is not settled. Treating that as
"no bound" and treating it as "bound of zero" are both wrong; it is reported unchecked.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fermdb.db import open_db
from fermdb.metabolic.bound_check import (
    check_configurations,
    check_measurements,
    format_report,
    load_ceilings,
    resolve_substrate,
    run_bound_check,
)

ISOBUTANOL = "YAA:PRODUCT:isobutanol"
STRAIN = "YAA:STRAIN:test-host"
PUB = "doi:10.0000/test"


def _seed(conn: sqlite3.Connection) -> None:
    """The minimum a measurement needs to exist: an organism, a strain, a product, a paper."""
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:scer', 'Saccharomyces cerevisiae', 'R', 'test', 'high')"
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, zone, evidence, confidence) "
        "VALUES (?, 'YAA:ORG:scer', 'test host', 'R', 'test', 'high')",
        (STRAIN,),
    )
    conn.execute(
        "INSERT INTO product (id, name, zone, evidence, confidence) "
        "VALUES (?, 'isobutanol', 'R', 'test', 'high')",
        (ISOBUTANOL,),
    )
    conn.execute(
        "INSERT INTO publication (id, zone, evidence, confidence) VALUES (?, 'R', 'test', 'low')",
        (PUB,),
    )
    conn.execute(
        "INSERT INTO product_theoretical_yield (product_id, substrate, g_per_g, g_per_g_state, "
        "stoichiometry, zone, evidence, confidence) "
        "VALUES (?, 'glucose', 0.411, 'recorded', '1 glucose -> 1 isobutanol + 2 CO2 + H2O', "
        "'R', 'PLAN.md B.2', 'unverified')",
        (ISOBUTANOL,),
    )
    conn.commit()


def _measurement(
    conn: sqlite3.Connection,
    measurement_id: str,
    *,
    value: float,
    unit: str = "g/g",
    kind: str = "yield",
    basis: str | None = "consumed",
    evidence: str = "test",
    is_fraction: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO measurement (id, strain_id, publication_id, quantity_kind, product_id, "
        "value_as_reported, unit_as_reported, basis, is_fraction, source_locator, zone, "
        "evidence, confidence) VALUES (?,?,?,?,?,?,?,?,?,'text','R',?,'medium')",
        (
            measurement_id,
            STRAIN,
            PUB,
            kind,
            ISOBUTANOL,
            value,
            unit,
            basis,
            is_fraction,
            evidence,
        ),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = open_db(tmp_path / "bound.sqlite3")
    _seed(connection)
    return connection


# ------------------------------------------------------------------------------ the ceiling


def test_the_ceiling_is_read_from_the_table_and_not_from_code(conn: sqlite3.Connection) -> None:
    """PLAN.md B.2 stores the figure per substrate; no stoichiometric constant lives in the
    checking module. Change the row and the bound changes."""
    ceilings = load_ceilings(conn)
    assert [(c.product_id, c.substrate, c.g_per_g) for c in ceilings] == [
        (ISOBUTANOL, "glucose", 0.411)
    ]
    assert ceilings[0].is_usable


def test_a_yield_under_the_ceiling_passes(conn: sqlite3.Connection) -> None:
    _measurement(conn, "YAA:MEAS:under", value=0.35, evidence="substrate as reported: glucose")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "pass"
    assert verdict.ceiling == 0.411
    assert "85.2% of it" in verdict.reason


def test_a_yield_above_the_ceiling_is_flagged(conn: sqlite3.Connection) -> None:
    """The whole point. 0.48 g/g of isobutanol from glucose is not a measurement, it is a
    carbon-balance claim that the stoichiometry forbids."""
    _measurement(conn, "YAA:MEAS:over", value=0.48, evidence="substrate as reported: glucose")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "flag"
    assert verdict.is_violation
    assert "exceeds the theoretical maximum 0.411" in verdict.reason
    assert run_bound_check(conn).violations == (verdict,)


def test_the_ceiling_itself_passes_rather_than_flagging(conn: sqlite3.Connection) -> None:
    """Exactly at the bound is at the bound, not over it. A float comparison that got this wrong
    would flag every theoretical-yield demonstration in the literature."""
    _measurement(conn, "YAA:MEAS:at", value=0.411, evidence="substrate as reported: glucose")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "pass"


# ----------------------------------------------------------------- what cannot be evaluated


def test_a_yield_with_no_recoverable_substrate_is_not_assumed_onto_glucose(
    conn: sqlite3.Connection,
) -> None:
    """The finding this module exists to make visible: `measurement` has no substrate column and
    `condition_context` is empty, so most stored yields cannot be checked at all. Reporting that
    is the answer; assuming glucose would be inventing a ceiling."""
    _measurement(conn, "YAA:MEAS:nosub", value=0.48, evidence="no substrate anywhere in here")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "not_evaluable"
    assert verdict.substrate.route == "none"
    assert "assuming glucose would be inventing one" in verdict.reason


def test_a_substrate_with_no_recorded_ceiling_is_reported_unchecked(
    conn: sqlite3.Connection,
) -> None:
    """0.411 g/g holds for xylose too (5 xylose -> 6 isobutanol = 0.41142 g/g), but the table has
    no xylose row, and a ceiling the atlas has not recorded is not one this module may apply."""
    _measurement(conn, "YAA:MEAS:xyl", value=0.48, evidence="substrate as reported: xylose")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "not_evaluable"
    assert verdict.substrate.substrate == "xylose"
    assert "no row for" in verdict.reason


def test_an_unknown_state_ceiling_does_not_become_a_bound(conn: sqlite3.Connection) -> None:
    """`g_per_g_state='unknown'` means the assumed pathway is not settled — six of the ten stored
    rows say exactly that. It must not be read as "unbounded" or as "zero"."""
    conn.execute(
        "INSERT INTO product (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:PRODUCT:succinate', 'succinate', 'R', 'test', 'high')"
    )
    conn.execute(
        "INSERT INTO product_theoretical_yield (product_id, substrate, g_per_g_state, "
        "mol_per_mol_state, zone, evidence, confidence) VALUES "
        "('YAA:PRODUCT:succinate', 'glucose', 'unknown', 'unknown', 'R', 'test', 'medium')"
    )
    conn.execute(
        "INSERT INTO measurement (id, strain_id, publication_id, quantity_kind, product_id, "
        "value_as_reported, unit_as_reported, basis, source_locator, zone, evidence, confidence) "
        "VALUES ('YAA:MEAS:succ', ?, ?, 'yield', 'YAA:PRODUCT:succinate', 2.0, 'g/g', "
        "'consumed', 'text', 'R', 'substrate as reported: glucose', 'medium')",
        (STRAIN, PUB),
    )
    conn.commit()
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "not_evaluable"
    assert "the assumed pathway is not settled" in verdict.reason


def test_a_yield_stored_with_unit_unknown_escapes_the_check(conn: sqlite3.Connection) -> None:
    """Recorded, because it is a live hole rather than a design choice: two of the three yield
    records this corpus has were promoted with `unit='unknown'`, and a unit that is not a mass
    ratio has nothing to compare to a g/g ceiling. The check says so out loud instead of
    silently passing them."""
    _measurement(
        conn,
        "YAA:MEAS:unitless",
        value=12.45,
        unit="unknown",
        evidence="substrate as reported: glucose",
    )
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "not_evaluable"
    assert "escapes this check entirely" in verdict.reason


def test_a_titer_is_not_a_mass_yield(conn: sqlite3.Connection) -> None:
    _measurement(conn, "YAA:MEAS:titer", value=635.0, unit="mg/L", kind="titer", basis=None)
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "not_evaluable"
    assert "is not a mass yield" in verdict.reason


# -------------------------------------------------------------------- basis, and its absence


def test_a_fraction_of_the_theoretical_maximum_needs_no_substrate(
    conn: sqlite3.Connection,
) -> None:
    """basis='theoretical_max_pct' carries its own ceiling of 1, so it is the one shape of yield
    the missing substrate column does not disable."""
    _measurement(conn, "YAA:MEAS:frac", value=0.0369, unit="unknown", basis="theoretical_max_pct")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "pass"
    assert verdict.ceiling == 1.0


def test_a_fraction_above_one_is_flagged(conn: sqlite3.Connection) -> None:
    _measurement(conn, "YAA:MEAS:frac2", value=1.4, unit="unknown", basis="theoretical_max_pct")
    (verdict,) = check_measurements(conn)
    assert verdict.verdict == "flag"
    assert "more product than the substrate contains" in verdict.reason


def test_a_yield_with_no_basis_is_refused(tmp_path: Path) -> None:
    """PLAN.md's rule, stated a second time here.

    The live schema's ``CHECK (quantity_kind <> 'yield' OR basis IS NOT NULL)`` is the first
    statement of it and cannot be violated — which is exactly why this test builds a database
    *without* that constraint. A checker that relies on the constraint holding is untested against
    the only case it would ever matter: a row that arrived by some route other than this schema.
    """
    database = tmp_path / "unconstrained.sqlite3"
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE product_theoretical_yield (
            product_id TEXT, substrate TEXT, g_per_g REAL, g_per_g_state TEXT,
            stoichiometry TEXT
        );
        CREATE TABLE measurement (
            id TEXT, strain_id TEXT, publication_id TEXT, quantity_kind TEXT, product_id TEXT,
            value_as_reported REAL, unit_as_reported TEXT, basis TEXT, evidence TEXT
        );
        CREATE TABLE pathway_configuration (
            id TEXT, name TEXT, product_id TEXT, host_strain_id TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO product_theoretical_yield VALUES (?, 'glucose', 0.411, 'recorded', NULL)",
        (ISOBUTANOL,),
    )
    conn.execute(
        "INSERT INTO measurement VALUES ('YAA:MEAS:nobasis', ?, ?, 'yield', ?, 0.2, 'g/g', "
        "NULL, 'substrate as reported: glucose')",
        (STRAIN, PUB, ISOBUTANOL),
    )
    conn.commit()
    try:
        (verdict,) = check_measurements(conn)
        assert verdict.verdict == "refused"
        assert "reached the database around its CHECK constraint" in verdict.reason
    finally:
        conn.close()


# ---------------------------------------------------------------------- substrate resolution


def test_the_substrate_is_read_from_the_evidence_prose_promote_writes(
    conn: sqlite3.Connection,
) -> None:
    resolution = resolve_substrate(
        conn,
        "promoted from ...; substrate as reported: glucose (no condition_context yet; this is "
        "what distinguishes it from its siblings)",
    )
    assert resolution.route == "evidence"
    assert resolution.substrate == "glucose"


def test_the_substrate_falls_back_to_the_originating_curation_task(
    conn: sqlite3.Connection,
) -> None:
    """The second route, and the one that answers for this corpus: 97 of 97 measurements name
    their curation task in `evidence`, while only 3 carry a substrate there directly."""
    _seed_task(conn, "YAA:CTASK:aaaa0001", {"substrate": "glucose", "value": 0.016})
    resolution = resolve_substrate(conn, "promoted from curation task YAA:CTASK:aaaa0001 on x")
    assert resolution.route == "curation_task"
    assert resolution.substrate == "glucose"


def test_an_edited_payload_wins_over_the_model_s_original(conn: sqlite3.Connection) -> None:
    """What the curator accepted is the record, not what the model proposed."""
    _seed_task(
        conn,
        "YAA:CTASK:aaaa0002",
        {"substrate": "glucose"},
        edited={"substrate": "xylose"},
    )
    resolution = resolve_substrate(conn, "promoted from curation task YAA:CTASK:aaaa0002 on x")
    assert resolution.substrate == "xylose"


def test_a_mixture_naming_two_sugars_is_ambiguous(conn: sqlite3.Connection) -> None:
    _seed_task(conn, "YAA:CTASK:aaaa0003", {"substrate": "1:1 medium (glucose: xylose)"})
    resolution = resolve_substrate(conn, "promoted from curation task YAA:CTASK:aaaa0003 on x")
    assert resolution.route == "ambiguous"
    assert resolution.substrate is None
    assert set(resolution.candidates) == {"glucose", "xylose"}


def test_a_percentage_prefix_still_resolves(conn: sqlite3.Connection) -> None:
    """ "5% glucose" is glucose. One known sugar named, no other, so the bound is unambiguous."""
    _seed_task(conn, "YAA:CTASK:aaaa0004", {"substrate": "5% glucose"})
    resolution = resolve_substrate(conn, "promoted from curation task YAA:CTASK:aaaa0004 on x")
    assert resolution.substrate == "glucose"


def _seed_task(
    conn: sqlite3.Connection,
    task_id: str,
    payload: dict[str, object],
    *,
    edited: dict[str, object] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO extraction (id, publication_id, extractor, extractor_version, payload, "
        "zone) VALUES (?, ?, 'test', '0', '{}', 'I') ON CONFLICT(id) DO NOTHING",
        (f"YAA:EXTR:{task_id[-8:]}", PUB),
    )
    status = "edited" if edited is not None else "pending"
    resolved = (
        ("kangkon", "human", "2026-09-22", "test")
        if edited is not None
        else (
            None,
            None,
            None,
            None,
        )
    )
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, record_kind, "
        "payload, status, proposal_hash, edited_payload, curator, curator_kind, resolved_at, "
        "resolution_reason) VALUES (?,?,?,?,'measurements',?,?,?,?,?,?,?,?)",
        (
            task_id,
            f"YAA:EXTR:{task_id[-8:]}",
            PUB,
            f"measurements[{task_id[-1]}]",
            json.dumps(payload),
            status,
            task_id,
            None if edited is None else json.dumps(edited),
            *resolved,
        ),
    )
    conn.commit()


# ------------------------------------------------------------------------- configurations


def test_a_configuration_with_no_yield_is_not_evaluable_rather_than_passing(
    conn: sqlite3.Connection,
) -> None:
    """The phase-1b answer, and the reason clause 2 cannot be closed by counting. A configuration
    whose host strain has only titers neither passes the bound nor violates it, and calling that
    a pass would report 4/4 for a corpus that has never been checked."""
    _configuration(conn, "YAA:PCFG:noyield")
    _measurement(conn, "YAA:MEAS:t1", value=0.5, unit="g/L", kind="titer", basis=None)
    (verdict,) = check_configurations(conn)
    assert verdict.verdict == "not_evaluable"
    assert "neither passes the bound nor violates it" in verdict.reason
    assert verdict.measurements == ()


def test_a_configuration_inherits_the_verdict_of_its_host_strain_s_yields(
    conn: sqlite3.Connection,
) -> None:
    _configuration(conn, "YAA:PCFG:ok")
    _measurement(conn, "YAA:MEAS:ok", value=0.35, evidence="substrate as reported: glucose")
    (verdict,) = check_configurations(conn)
    assert verdict.verdict == "pass"
    assert [m.measurement_id for m in verdict.measurements] == ["YAA:MEAS:ok"]


def test_a_configuration_whose_host_carries_a_violation_is_flagged(
    conn: sqlite3.Connection,
) -> None:
    _configuration(conn, "YAA:PCFG:bad")
    _measurement(conn, "YAA:MEAS:bad", value=0.6, evidence="substrate as reported: glucose")
    (verdict,) = check_configurations(conn)
    assert verdict.verdict == "flag"


def test_configurations_sharing_a_host_strain_say_so(conn: sqlite3.Connection) -> None:
    """Two of this corpus's four configurations share one host strain row, so a yield attributed
    to one is attributed to both. The rollup must not hide that."""
    _configuration(conn, "YAA:PCFG:a")
    _configuration(conn, "YAA:PCFG:b")
    _measurement(conn, "YAA:MEAS:shared", value=0.35, evidence="substrate as reported: glucose")
    verdicts = check_configurations(conn)
    assert len(verdicts) == 2
    assert all("share this host strain" in v.reason for v in verdicts)


def _configuration(conn: sqlite3.Connection, configuration_id: str) -> None:
    conn.execute(
        "INSERT INTO pathway_configuration (id, name, product_id, host_strain_id, zone, "
        "evidence, confidence) VALUES (?, ?, ?, ?, 'R', 'test', 'medium')",
        (configuration_id, f"config {configuration_id}", ISOBUTANOL, STRAIN),
    )
    conn.commit()


# ------------------------------------------------------------------------------- reporting


def test_the_report_names_every_violation(conn: sqlite3.Connection) -> None:
    _configuration(conn, "YAA:PCFG:r")
    _measurement(conn, "YAA:MEAS:r1", value=0.35, evidence="substrate as reported: glucose")
    _measurement(conn, "YAA:MEAS:r2", value=0.9, evidence="substrate as reported: glucose")
    text = format_report(run_bound_check(conn))
    assert "VIOLATIONS" in text
    assert "YAA:MEAS:r2" in text
    assert "YAA:MEAS:r1" not in text.split("VIOLATIONS")[1]


def test_an_empty_database_reports_zero_rather_than_raising(tmp_path: Path) -> None:
    connection = open_db(tmp_path / "empty.sqlite3")
    try:
        report = run_bound_check(connection)
        assert report.measurements == ()
        assert report.configurations == ()
        assert report.measurement_counts["flag"] == 0
    finally:
        connection.close()
