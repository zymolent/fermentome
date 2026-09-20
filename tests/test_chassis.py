"""Tests for `fermdb.metabolic.chassis`.

The failure this module is built against is a chassis term that looks like it works and changes
no ordering. Adding a tolerance number to every route's score would do exactly that: 360 routes,
one constant, identical ranking, and a CLI that now says "chassis-aware". So the tests below are
mostly about the gates *differing* between routes, and about absence staying absence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.metabolic import chassis as C

MATRIX = "C_mitochondrial_ehrlich"
CYTOSOL = "B_cytosolic_relocalization"
MTDNA = "E_mtdna_encoded"


def _profile(**over: object) -> C.ChassisProfile:
    base: dict[str, object] = {
        "id": "YAA:CHASSIS:test",
        "name_as_reported": "test strain",
        "evidence": "test",
    }
    base.update(over)
    return C.ChassisProfile(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------ absence stays absence


def test_unknown_rho_status_is_not_read_as_yes() -> None:
    """The whole point of the three-state discipline, applied to a strain property.

    A chassis whose rho status nobody recorded might be rho-zero. Treating silence as rho-plus
    would let the ranker recommend a matrix pathway into a strain that cannot run one.
    """
    assert _profile().can_run_a_matrix_pathway is None
    assert _profile(rho_status="unknown").can_run_a_matrix_pathway is None
    assert _profile(rho_status="rho_plus").can_run_a_matrix_pathway is True
    assert _profile(rho_status="rho_zero").can_run_a_matrix_pathway is False

    gates = C.gates_for(_profile(), strategy=MATRIX)
    assert [g.severity for g in gates] == ["unknown"]
    assert "not assumed" in gates[0].message


def test_no_chassis_selected_yields_no_gates_and_is_not_a_clean_bill() -> None:
    """Empty means "ranked against none", which the caller must report as such."""
    assert C.gates_for(None, strategy=MATRIX) == ()
    assert "no chassis selected" in next(iter(C.iter_context(None)))


def test_an_unmeasured_tolerance_says_no_ceiling_can_be_computed() -> None:
    lines = list(C.iter_context(_profile()))
    assert any("not measured" in line and "ceiling" in line for line in lines)
    measured = list(
        C.iter_context(
            _profile(isobutanol_tolerance_g_l=8.0, tolerance_endpoint="growth rate 50% of control")
        )
    )
    assert any("8 g/L" in line and "growth rate" in line for line in measured)


# ------------------------------------------------------------------ gates differ by route


def test_a_rho_zero_chassis_disqualifies_matrix_routes_only() -> None:
    """Disqualifying, not costly -- and it must not touch a cytosolic route."""
    profile = _profile(rho_status="rho_zero")
    matrix = C.gates_for(profile, strategy=MATRIX)
    assert [g.excludes for g in matrix] == [True]
    assert "impossibility" in matrix[0].message
    assert C.gates_for(profile, strategy=CYTOSOL) == ()


def test_the_gates_differ_between_strategies() -> None:
    """If every strategy got the same gates the ranking would not move, which is the bug."""
    profile = _profile(
        rho_status="rho_plus",
        respiration_policy="preferred",
        mtdna_tooling="available_after_acquisition",
    )
    counts = {s: len(C.gates_for(profile, strategy=s)) for s in (CYTOSOL, MATRIX, MTDNA)}
    assert counts[CYTOSOL] == 0
    assert counts[MTDNA] > counts[CYTOSOL]
    assert len(set(counts.values())) > 1


def test_the_m2_answer_makes_strategy_e_conditional_not_impossible() -> None:
    """ "Not available now, but will purchase if required" is a timeline, not a wall."""
    gates = C.gates_for(_profile(mtdna_tooling="available_after_acquisition"), strategy=MTDNA)
    tooling = next(g for g in gates if g.kind == "mtdna_tooling")
    assert tooling.severity == "conditional"
    assert not tooling.excludes
    assert "two different timelines" in tooling.message

    unavailable = C.gates_for(_profile(mtdna_tooling="unavailable"), strategy=MTDNA)
    assert any(g.excludes for g in unavailable)


def test_the_m3_answer_flags_rather_than_excludes() -> None:
    """ "Preferred ... unless a compelling and scalable process advantage" is conditional."""
    preferred = C.gates_for(_profile(respiration_policy="preferred"), strategy=MTDNA)
    gate = next(g for g in preferred if g.kind == "respiration")
    assert gate.severity == "conditional"
    assert "rescue strategy" in gate.message

    required = C.gates_for(_profile(respiration_policy="required"), strategy=MTDNA)
    assert next(g for g in required if g.kind == "respiration").excludes


def test_a_pdc_minus_chassis_is_flagged_against_the_duet_requirement() -> None:
    gates = C.gates_for(_profile(pdc_status="minus"), strategy=MATRIX)
    gate = next(g for g in gates if g.kind == "pdc_status")
    assert "Pdc-POSITIVE" in gate.message
    assert not gate.excludes  # a conflict with the design, not an impossibility


# ------------------------------------------------------------------ edit burden


def test_ploidy_changes_the_edit_burden_note_only_when_recorded() -> None:
    assert "not recorded" in _profile().edit_burden_note
    assert "haploid" in _profile(ploidy=1).edit_burden_note
    multiplex = _profile(ploidy=4, marker_free_multiplex=True).edit_burden_note
    assert "verification burden scales 4x" in multiplex
    without = _profile(ploidy=4, marker_free_multiplex=False).edit_burden_note
    assert "4x the edits" in without


# ------------------------------------------------------------------ the curated file


@pytest.fixture()
def settings() -> Settings:
    return Settings.load()


def test_the_real_curated_file_loads_and_selects_exactly_one(settings: Settings) -> None:
    profiles = C.load_profiles(settings)
    assert len(profiles) >= 2
    selected = C.selected_profile(profiles)
    assert selected is not None
    assert selected.id == "YAA:CHASSIS:duet-industrial-polyploid"


def test_the_selected_chassis_matches_the_concept_note(settings: Settings) -> None:
    """DUET_TARGET.md §5.3 settles the chassis and §5.1 requires Pdc-positive."""
    selected = C.selected_profile(C.load_profiles(settings))
    assert selected is not None
    assert selected.pdc_status == "intact"
    assert selected.marker_free_multiplex is True
    assert selected.respiration_policy == "preferred"  # M3
    assert selected.mtdna_tooling == "available_after_acquisition"  # M2
    assert selected.higher_alcohol_panel_state == "not_measured"  # M4
    # The properties still owed, which the ranker reports rather than guessing.
    assert selected.ploidy is None
    assert selected.rho_status is None
    assert selected.isobutanol_tolerance_g_l is None


def test_two_selected_profiles_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ranker scores against one chassis and cannot average two."""
    monkeypatch.setenv("FERMDB_STRAINS_DIR", str(tmp_path))
    (tmp_path / C.PROFILES_FILE).write_text(
        "version: 1\nchassis:\n"
        "  - {id: a, name_as_reported: A, evidence: t, is_selected: true}\n"
        "  - {id: b, name_as_reported: B, evidence: t, is_selected: true}\n",
        encoding="utf-8",
    )
    with pytest.raises(C.ChassisError, match="cannot average two"):
        C.load_profiles(Settings.load())


def test_a_missing_file_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project may not have chosen a chassis; the ranker then says so rather than failing."""
    monkeypatch.setenv("FERMDB_STRAINS_DIR", str(tmp_path))
    assert C.load_profiles(Settings.load()) == ()
    assert C.selected_profile(()) is None


def test_an_entry_without_evidence_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONVENTIONS.md: every curated row carries evidence naming its source."""
    monkeypatch.setenv("FERMDB_STRAINS_DIR", str(tmp_path))
    (tmp_path / C.PROFILES_FILE).write_text(
        "version: 1\nchassis:\n  - {id: a, name_as_reported: A}\n", encoding="utf-8"
    )
    with pytest.raises(C.ChassisError, match="evidence"):
        C.load_profiles(Settings.load())
