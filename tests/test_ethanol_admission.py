"""Tests for `fermdb.literature.ethanol` — the capped ethanol layer's admission control.

Three properties carry the weight.

**The sub-budget is the whole point.** E5's outer bound is 642 publications against a ~150 total,
so without a per-criterion ceiling the broadest criterion eats the layer and E1–E4 arrive empty.
A budget that does not actually stop an admission is decoration.

**E6 exists.** PLAN.md's phase-2 acceptance still says "E1–E5", but the owner accepted E6 on
2026-09-20, the schema permits it, and discovery has tagged 279 records under it. A loader
enforcing E1–E5 would reject every one and make the phase unpassable.

**Unspent is reported, never reallocated.** "We found fewer admissible papers than expected" is a
finding about the literature, not slack to consume.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.literature.ethanol import (
    ADMISSIONS_FILE,
    CRITERION_BUDGET,
    MEASUREMENT_STUDY_CAP,
    PUBLICATION_CAP,
    SLOTS,
    AdmissionsFileError,
    admit,
    budget_status,
    install_admissions,
    load_admissions,
    load_layer_gaps,
    unspent_report,
    validate_admission,
    write_layer_gaps,
)

#: The repo's own path configuration, so the curated-set tests read the committed file rather than
#: whatever `env/paths.local.yaml` happens to say on one machine.
PATHS_FILE = Path(__file__).resolve().parents[1] / "env" / "paths.yaml"


def _seed(conn: sqlite3.Connection, publication_id: str, *, tier: str = "ethanol") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO publication (id, title, zone, evidence, confidence) "
        "VALUES (?, ?, 'R', 'test fixture', 'unverified')",
        (publication_id, f"title for {publication_id}"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO search_run "
        "(id, family, db, term, started_at, query_families_version) "
        "VALUES ('RUN', 'fam', 'pubmed', 'ethanol', '2026-01-01', 1)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, zone) "
        "VALUES (?, ?, 'fam', 'RUN', 'RUN', 'needs_full_text', ?, "
        "'exclude_unless_admitted', 'proposed', 'H')",
        (f"SCR:{publication_id}", publication_id, tier),
    )
    conn.commit()


def _accept(conn: sqlite3.Connection, publication_id: str, criterion: str) -> None:
    """Mark a row admitted directly, to build up a spent budget without going through `admit`."""
    conn.execute(
        "UPDATE screening_record SET review_state='accepted', triage_state='included', "
        "admitted_criterion=? WHERE publication_id=?",
        (criterion, publication_id),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    database = open_db(tmp_path / "eth.sqlite3")
    yield database
    database.close()


@pytest.fixture
def settings() -> Settings:
    return Settings.load()


# ----------------------------------------------------------------- the budget and the slots


def test_the_sub_budget_sums_to_the_publication_cap() -> None:
    """150, the number the owner accepted. If these drift apart the layer silently over- or
    under-commits and nobody notices until curation runs out of room."""
    assert sum(CRITERION_BUDGET.values()) == PUBLICATION_CAP


def test_every_slot_maps_to_a_budgeted_criterion() -> None:
    for slot in SLOTS:
        assert slot.criterion in CRITERION_BUDGET, f"slot {slot.number} has no budget"


def test_all_seven_slots_are_present_and_e4_carries_two() -> None:
    """Slots 3 and 4 share criterion E4 — acute shock and adapted growth are distinct biology and
    the plan forbids merging them, but they rest on one admission rule."""
    assert len(SLOTS) == 7
    assert [s.number for s in SLOTS] == [1, 2, 3, 4, 5, 6, 7]
    assert [s.number for s in SLOTS if s.criterion == "E4"] == [3, 4]


def test_e6_is_accepted_although_plan_md_still_says_e1_to_e5() -> None:
    """The discrepancy this module exists to survive. E6 was accepted 2026-09-20 with a
    25-publication budget and already tags 279 records; enforcing PLAN.md's stale sentence would
    reject all of them."""
    assert "E6" in CRITERION_BUDGET
    assert CRITERION_BUDGET["E6"] == 25
    assert any(slot.criterion == "E6" for slot in SLOTS)


def test_e5_holds_the_largest_share() -> None:
    """Load-bearing for DUET's architecture, and still only a seventh of its 642 outer bound."""
    assert CRITERION_BUDGET["E5"] == max(CRITERION_BUDGET.values())


# ------------------------------------------------------------------------------ validation


def test_an_unknown_criterion_is_refused(conn: sqlite3.Connection, settings: Settings) -> None:
    _seed(conn, "doi:10.1/a")
    problems = validate_admission(conn, settings, publication_id="doi:10.1/a", criterion="E9")
    assert [p.code for p in problems] == ["unknown_criterion"]


def test_an_isobutanol_tier_paper_cannot_be_admitted(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Admission criteria belong to the ethanol tier only — the schema says so too."""
    _seed(conn, "doi:10.1/iso", tier="isobutanol")
    problems = validate_admission(conn, settings, publication_id="doi:10.1/iso", criterion="E2")
    assert "wrong_tier" in {p.code for p in problems}


def test_a_paper_screened_into_both_tiers_is_still_admissible(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The regression that shipped. A publication carries one screening row per query family it
    matched, and 103 of them match both an ethanol family and an isobutanol one — a mitochondrial
    ethanol paper legitimately answers both.

    The first version of `validate_admission` took `LIMIT 1` with no ORDER BY and refused a real
    E5 candidate as 'wrong_tier' on the strength of its isobutanol row. Nothing caught it until
    the validator was pointed at the live database.
    """
    _seed(conn, "doi:10.1/dual", tier="ethanol")
    conn.execute(
        "INSERT INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, zone) "
        "VALUES ('SCR:dual-iso', 'doi:10.1/dual', 'mtdna_fam', 'RUN', 'RUN', 'included', "
        "'isobutanol', 'include_unless_excluded', 'proposed', 'H')"
    )
    conn.commit()
    problems = validate_admission(conn, settings, publication_id="doi:10.1/dual", criterion="E3")
    assert [p.code for p in problems] == [], "an ethanol row anywhere makes it ethanol-tier"


def test_an_unscreened_paper_cannot_be_admitted(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Admission has to be auditable back to a search run (PLAN.md R.2)."""
    conn.execute(
        "INSERT INTO publication (id, title, zone, evidence, confidence) "
        "VALUES ('doi:10.1/orphan', 't', 'R', 'x', 'unverified')"
    )
    conn.commit()
    problems = validate_admission(conn, settings, publication_id="doi:10.1/orphan", criterion="E2")
    assert "not_screened" in {p.code for p in problems}


def test_a_budget_that_is_full_refuses_the_next_admission(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The test that makes the sub-budget real rather than decorative."""
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")

    _seed(conn, "doi:10.4/one-too-many")
    problems = validate_admission(
        conn, settings, publication_id="doi:10.4/one-too-many", criterion="E4"
    )
    assert "budget_exhausted" in {p.code for p in problems}


def test_a_full_budget_does_not_block_a_different_criterion(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Budgets are per criterion. Exhausting E4 must not close the layer."""
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")

    _seed(conn, "doi:10.2/fine")
    problems = validate_admission(conn, settings, publication_id="doi:10.2/fine", criterion="E2")
    assert [p.code for p in problems] == []


def test_e5_without_a_stored_full_text_cannot_be_checked(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """E5 is the only criterion with a content rule, so it is the only one that needs the text.
    Refusing is right: an unchecked E5 admission is how the broadest criterion eats the layer."""
    _seed(conn, "doi:10.5/no-text")
    problems = validate_admission(conn, settings, publication_id="doi:10.5/no-text", criterion="E5")
    assert "e5_unreadable" in {p.code for p in problems}


def test_a_non_e5_criterion_needs_no_full_text(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _seed(conn, "doi:10.3/no-text")
    problems = validate_admission(conn, settings, publication_id="doi:10.3/no-text", criterion="E3")
    assert [p.code for p in problems] == []


# --------------------------------------------------------------------------------- admitting


def test_admit_writes_and_survives_reopening(tmp_path: Path, settings: Settings) -> None:
    database = tmp_path / "admit.sqlite3"
    first = open_db(database)
    try:
        _seed(first, "doi:10.2/keeper")
        assert admit(first, settings, publication_id="doi:10.2/keeper", criterion="E2") == ()
    finally:
        first.close()

    second = open_db(database, create=False)
    try:
        row = second.execute(
            "SELECT review_state, triage_state, admitted_criterion FROM screening_record "
            "WHERE publication_id = 'doi:10.2/keeper'"
        ).fetchone()
        assert row["review_state"] == "accepted"
        assert row["triage_state"] == "included"
        assert row["admitted_criterion"] == "E2"
    finally:
        second.close()


def test_a_failed_admission_writes_nothing(conn: sqlite3.Connection, settings: Settings) -> None:
    _seed(conn, "doi:10.1/iso2", tier="isobutanol")
    problems = admit(conn, settings, publication_id="doi:10.1/iso2", criterion="E2")
    assert problems
    row = conn.execute(
        "SELECT review_state FROM screening_record WHERE publication_id = 'doi:10.1/iso2'"
    ).fetchone()
    assert row["review_state"] == "proposed"


def test_a_slot_that_does_not_carry_the_criterion_is_refused(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Slot 6 is E5; admitting an E2 paper "into slot 6" is a curator slip worth catching."""
    _seed(conn, "doi:10.2/wrongslot")
    problems = admit(conn, settings, publication_id="doi:10.2/wrongslot", criterion="E2", slot=6)
    assert [p.code for p in problems] == ["slot_criterion_mismatch"]


# ---------------------------------------------------------------------------------- reporting


def test_an_empty_layer_reports_every_share_unspent(conn: sqlite3.Connection) -> None:
    lines = unspent_report(conn)
    assert len(lines) == len(CRITERION_BUDGET)
    assert all("unspent" in line for line in lines)


def test_a_filled_criterion_drops_out_of_the_unspent_report(conn: sqlite3.Connection) -> None:
    for index in range(CRITERION_BUDGET["E4"]):
        pid = f"doi:10.4/{index}"
        _seed(conn, pid)
        _accept(conn, pid, "E4")
    assert not any(line.startswith("E4") for line in unspent_report(conn))


def test_budget_status_counts_a_paper_once_even_across_families(
    conn: sqlite3.Connection,
) -> None:
    """A paper matching several query families has several screening rows. Charging its criterion
    once per row would overstate the spend and close the budget early."""
    _seed(conn, "doi:10.5/multi")
    conn.execute(
        "INSERT INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, admitted_criterion, zone) "
        "VALUES ('SCR:second', 'doi:10.5/multi', 'other_fam', 'RUN', 'RUN', 'included', "
        "'ethanol', 'exclude_unless_admitted', 'accepted', 'E5', 'H')"
    )
    _accept(conn, "doi:10.5/multi", "E5")
    line = next(entry for entry in budget_status(conn) if entry.criterion == "E5")
    assert line.admitted == 1


# --------------------------------------------------------- the writer and the dual-tier paper


def _seed_dual_tier(conn: sqlite3.Connection, publication_id: str) -> None:
    """A publication with one ethanol screening row and one isobutanol row — 103 of them exist."""
    _seed(conn, publication_id, tier="ethanol")
    conn.execute(
        "INSERT INTO screening_record "
        "(id, publication_id, family, first_seen_run_id, last_seen_run_id, triage_state, "
        " product_tier, default_disposition, review_state, zone) "
        "VALUES (?, ?, 'iso_fam', 'RUN', 'RUN', 'included', 'isobutanol', "
        "'include_unless_excluded', 'proposed', 'H')",
        (f"SCR:iso:{publication_id}", publication_id),
    )
    conn.commit()


def test_admitting_a_dual_tier_paper_does_not_die_on_the_schema_check(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The writer's half of the bug `validate_admission` already carries a comment about.

    The validator was fixed to accept a paper screened into both tiers; `admit` was not. Its
    UPDATE matched on `publication_id` alone, so it tried to write `admitted_criterion` onto the
    isobutanol rows too and died on the schema's own CHECK — `admitted_criterion IS NULL OR
    product_tier = 'ethanol'` — with a `sqlite3.IntegrityError` and no `AdmissionProblem` to
    explain it. Every dual-tier paper was unadmittable, including four of phase 2's 23.
    """
    _seed_dual_tier(conn, "doi:10.1/dual-write")
    assert admit(conn, settings, publication_id="doi:10.1/dual-write", criterion="E4") == ()


def test_admitting_leaves_the_isobutanol_rows_untouched(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """An ethanol admission is not a verdict on an isobutanol row's triage."""
    _seed_dual_tier(conn, "doi:10.1/dual-quiet")
    before = conn.execute(
        "SELECT review_state, triage_state FROM screening_record "
        "WHERE publication_id = 'doi:10.1/dual-quiet' AND product_tier = 'isobutanol'"
    ).fetchone()
    admit(conn, settings, publication_id="doi:10.1/dual-quiet", criterion="E4")
    after = conn.execute(
        "SELECT review_state, triage_state, admitted_criterion FROM screening_record "
        "WHERE publication_id = 'doi:10.1/dual-quiet' AND product_tier = 'isobutanol'"
    ).fetchone()
    assert (after["review_state"], after["triage_state"]) == (
        before["review_state"],
        before["triage_state"],
    )
    assert after["admitted_criterion"] is None
    ethanol_row = conn.execute(
        "SELECT review_state, admitted_criterion FROM screening_record "
        "WHERE publication_id = 'doi:10.1/dual-quiet' AND product_tier = 'ethanol'"
    ).fetchone()
    assert (ethanol_row["review_state"], ethanol_row["admitted_criterion"]) == ("accepted", "E4")


# ------------------------------------------------- the curated set, data/literature/*.yaml


@pytest.fixture
def repo_settings() -> Settings:
    return Settings.load(paths_file=PATHS_FILE, env={})


def test_the_curated_admission_set_loads(repo_settings: Settings) -> None:
    records = load_admissions(repo_settings)
    assert len(records) == 23, "phase 2 admitted 23; the deliverable is the number, not 150"


def test_no_admitted_record_lacks_a_criterion(repo_settings: Settings) -> None:
    """PLAN.md phase 2's acceptance, in one line. The loader refuses the file outright if any
    record is missing one, so this asserts the property the file is allowed to have."""
    records = load_admissions(repo_settings)
    assert all(record.criterion in CRITERION_BUDGET for record in records)


def test_every_record_is_still_unverified(repo_settings: Settings) -> None:
    """`verified` false and `confidence` 'unverified' on all 23. Promotion is a curator act
    (PLAN.md L.5, decision D2) and installing a layer is not one."""
    records = load_admissions(repo_settings)
    assert not any(record.verified for record in records)
    assert {record.confidence for record in records} == {"unverified"}


def test_every_e4_record_carries_a_transfer_rationale(repo_settings: Settings) -> None:
    """B.3.4 admits a mechanism only with a stated argument for transfer to a C4 alcohol."""
    e4 = [record for record in load_admissions(repo_settings) if record.criterion == "E4"]
    assert e4, "E4 is the criterion the corpus actually filled; an empty list is a regression"
    assert all(record.transfer_rationale for record in e4)
    assert all(record.evidence_ceiling for record in e4)


def test_the_curated_set_is_inside_every_budget_and_both_caps(repo_settings: Settings) -> None:
    records = load_admissions(repo_settings)
    assert len(records) <= PUBLICATION_CAP
    assert sum(1 for record in records if record.measurement_bearing) <= MEASUREMENT_STUDY_CAP
    for criterion, budget in CRITERION_BUDGET.items():
        spent = sum(1 for record in records if record.criterion == criterion)
        assert spent <= budget, f"{criterion} is over its share"


def test_the_files_recorded_budget_position_matches_the_records_and_the_code(
    repo_settings: Settings,
) -> None:
    """The file reports its own unspent share, because the slots document requires the report.
    A hand-written table that drifts from the records is worse than no table."""
    document = yaml.safe_load(
        (repo_settings.literature_dir / ADMISSIONS_FILE).read_text(encoding="utf-8")
    )
    records = load_admissions(repo_settings)
    for line in document["budget_position"]:
        criterion = line["criterion"]
        spent = sum(1 for record in records if record.criterion == criterion)
        assert line["budget"] == CRITERION_BUDGET[criterion]
        assert line["admitted_here"] == spent
        assert line["unspent"] == CRITERION_BUDGET[criterion] - spent


def test_every_span_is_as_long_as_its_quote(repo_settings: Settings) -> None:
    """Checkable without the corpus, and it catches a hand-edited offset before any source is
    opened. Re-resolving against the stored text is `verify_record_spans`, which needs the text."""
    for record in load_admissions(repo_settings):
        for span in record.spans:
            assert span.char_end - span.char_start == len(span.quote), record.publication_id


# ------------------------------------------------------- what the curated set may not contain


def _write_set(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / ADMISSIONS_FILE
    path.write_text(yaml.safe_dump({"records": [record]}), encoding="utf-8")
    return path


def _minimal_record(**overrides: object) -> dict[str, object]:
    record = {
        "publication_id": "doi:10.2/x",
        "admitted_criterion": "E2",
        "slot": 5,
        "title": "a title",
        "measurement_bearing": True,
        "verified": False,
        "confidence": "unverified",
        "evidence": [{"quote": "abcde", "char_start": 10, "char_end": 15}],
    }
    record.update(overrides)
    return record


def test_a_record_claiming_verified_is_refused(tmp_path: Path, settings: Settings) -> None:
    path = _write_set(tmp_path, _minimal_record(verified=True))
    with pytest.raises(AdmissionsFileError, match="curator act"):
        load_admissions(settings, path=path)


def test_a_record_claiming_high_confidence_is_refused(tmp_path: Path, settings: Settings) -> None:
    """'high' is never writable from memory, and nothing here has been verified against a source
    by a human yet."""
    path = _write_set(tmp_path, _minimal_record(confidence="high"))
    with pytest.raises(AdmissionsFileError, match="confidence"):
        load_admissions(settings, path=path)


def test_a_record_with_no_criterion_is_refused(tmp_path: Path, settings: Settings) -> None:
    path = _write_set(tmp_path, _minimal_record(admitted_criterion=None))
    with pytest.raises(AdmissionsFileError, match="no admitted record lacks a criterion"):
        load_admissions(settings, path=path)


def test_a_slot_that_does_not_carry_the_criterion_is_refused_in_the_file(
    tmp_path: Path, settings: Settings
) -> None:
    """Slot 6 is E5. An E2 record "in slot 6" is a curator slip, and the file is exactly where it
    would sit unnoticed."""
    path = _write_set(tmp_path, _minimal_record(slot=6))
    with pytest.raises(AdmissionsFileError, match="names slot"):
        load_admissions(settings, path=path)


def test_offsets_that_disagree_with_the_quote_are_refused(
    tmp_path: Path, settings: Settings
) -> None:
    record = _minimal_record(evidence=[{"quote": "abcde", "char_start": 10, "char_end": 99}])
    path = _write_set(tmp_path, record)
    with pytest.raises(AdmissionsFileError, match="disagree"):
        load_admissions(settings, path=path)


def test_an_e4_record_without_a_transfer_rationale_is_refused(
    tmp_path: Path, settings: Settings
) -> None:
    path = _write_set(tmp_path, _minimal_record(admitted_criterion="E4", slot=3))
    with pytest.raises(AdmissionsFileError, match="transfer to a C4 alcohol"):
        load_admissions(settings, path=path)


def test_a_criterion_over_its_share_cannot_even_be_committed(
    tmp_path: Path, settings: Settings
) -> None:
    """`validate_admission` stops the 16th E4 admission at write time. This stops the file
    arriving in that state, where a reviewer would have to catch it by counting rows."""
    records = [
        _minimal_record(
            publication_id=f"doi:10.4/{index}",
            admitted_criterion="E4",
            slot=3,
            transfer_rationale="measured against 1% isobutanol",
        )
        for index in range(CRITERION_BUDGET["E4"] + 1)
    ]
    path = tmp_path / ADMISSIONS_FILE
    path.write_text(yaml.safe_dump({"records": records}), encoding="utf-8")
    with pytest.raises(AdmissionsFileError, match="against a budget of"):
        load_admissions(settings, path=path)


def test_the_same_paper_twice_is_refused(tmp_path: Path, settings: Settings) -> None:
    """A second row would charge the criterion twice against the sub-budget."""
    path = tmp_path / ADMISSIONS_FILE
    path.write_text(
        yaml.safe_dump({"records": [_minimal_record(), _minimal_record()]}), encoding="utf-8"
    )
    with pytest.raises(AdmissionsFileError, match="appears twice"):
        load_admissions(settings, path=path)


# ------------------------------------------------------------------ installing, and the gaps


def _store_text(
    conn: sqlite3.Connection, settings: Settings, publication_id: str, text: str
) -> None:
    target = settings.data_dir / "fulltext" / "t.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    conn.execute(
        "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
        "storage_state, content_path, checksum_sha256, media_type, source_url, retrieved_at, "
        "zone) VALUES (?, ?, ?, 'gold', 'pmc', 'stored_fulltext', ?, 'deadbeef', 'text/plain', "
        "'https://example.invalid/x', '2026-01-01T00:00:00+00:00', 'R')",
        (
            f"YAA:FTA:{publication_id}",
            publication_id,
            publication_id.removeprefix("doi:"),
            str(target.relative_to(settings.data_dir)),
        ),
    )
    conn.commit()


@pytest.fixture
def isolated_settings(tmp_path: Path) -> Settings:
    """The repo's paths with the *derived* tier under tmp_path, so a fixture full text never
    lands in the developer's live `~/fermdb-data`."""
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


def test_install_writes_the_criterion_and_the_gap(
    conn: sqlite3.Connection, isolated_settings: Settings, tmp_path: Path
) -> None:
    source_text = "prefix 0123456789 the quote lives here and nowhere else."
    quote = "the quote lives here"
    start = source_text.index(quote)
    _seed(conn, "doi:10.2/installable")
    _store_text(conn, isolated_settings, "doi:10.2/installable", source_text)

    path = tmp_path / ADMISSIONS_FILE
    path.write_text(
        yaml.safe_dump(
            {
                "records": [
                    _minimal_record(
                        publication_id="doi:10.2/installable",
                        evidence=[
                            {
                                "quote": quote,
                                "char_start": start,
                                "char_end": start + len(quote),
                            }
                        ],
                    )
                ],
                "open_gaps": [
                    {
                        "gap": "matrix NAD(P)H pool in living cells",
                        "kind": "never_attempted",
                        "status": "open",
                        "compartment": "mitochondrial_matrix",
                        "confidence": "medium",
                        "note": "nobody has measured it",
                        "evidence": "four independent corpus passes",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = install_admissions(conn, isolated_settings, path=path)
    assert report.refused == ()
    assert report.span_failures == ()
    assert report.spans_checked == 1
    assert report.admitted == ("doi:10.2/installable",)
    assert report.gaps_written == 1

    row = conn.execute(
        "SELECT review_state, triage_state, admitted_criterion FROM screening_record "
        "WHERE publication_id = 'doi:10.2/installable'"
    ).fetchone()
    assert (row["review_state"], row["triage_state"], row["admitted_criterion"]) == (
        "accepted",
        "included",
        "E2",
    )

    gap = conn.execute(
        "SELECT kind, status, zone, confidence, compartment_id FROM knowledge_gap"
    ).fetchone()
    assert gap["kind"] == "never_attempted"
    assert gap["status"] == "open"
    assert gap["zone"] == "I", "a gap read off an absence is inferred, never reported"
    assert gap["confidence"] == "medium"
    assert gap["compartment_id"] == "mitochondrial_matrix"


def test_install_refuses_a_record_whose_span_does_not_re_resolve(
    conn: sqlite3.Connection, isolated_settings: Settings, tmp_path: Path
) -> None:
    """The defect this whole re-verification exists for. The shortlist drafts were checked against
    the corpus cache and this pass checks the `fulltext_asset` store; they are not the same text
    and they do not share offsets, and two quotes in one earlier draft do not occur in their paper
    at all. A record that cannot be re-read is not installed."""
    _seed(conn, "doi:10.2/adrift")
    _store_text(conn, isolated_settings, "doi:10.2/adrift", "a completely different document")

    path = _write_set(
        tmp_path,
        _minimal_record(
            publication_id="doi:10.2/adrift",
            evidence=[{"quote": "Two isogenic yeast strains", "char_start": 0, "char_end": 26}],
        ),
    )
    report = install_admissions(conn, isolated_settings, path=path)
    assert report.admitted == ()
    assert [code for _, (code) in ((p, problem.code) for p, problem in report.refused)] == [
        "span_did_not_re_resolve"
    ]
    row = conn.execute(
        "SELECT review_state, admitted_criterion FROM screening_record "
        "WHERE publication_id = 'doi:10.2/adrift'"
    ).fetchone()
    assert row["review_state"] == "proposed"
    assert row["admitted_criterion"] is None


def test_the_committed_layer_gap_is_a_never_attempted_experiment(
    repo_settings: Settings,
) -> None:
    """PLAN.md §2.3's shape: what nobody has tried, recorded rather than left as silence."""
    gaps = load_layer_gaps(repo_settings)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.kind == "never_attempted"
    assert gap.status == "open"
    assert gap.compartment_id == "mitochondrial_matrix"
    assert gap.confidence == "medium"
    # Actionable as a bench experiment: what is measured, in what background, under what condition.
    assert "NAD(P)H" in gap.description
    assert "CEN.PK113-7D" in gap.why_it_matters
    assert "chemostat" in gap.why_it_matters
    # And it cites the four passes rather than asserting the absence on its own authority.
    assert "BM-COF-005" in gap.evidence
    assert "PHASE2_STATUS" in gap.evidence


def test_writing_the_gaps_twice_writes_one_row(
    conn: sqlite3.Connection, repo_settings: Settings
) -> None:
    gaps = load_layer_gaps(repo_settings)
    write_layer_gaps(conn, gaps)
    write_layer_gaps(conn, gaps)
    assert conn.execute("SELECT COUNT(*) FROM knowledge_gap").fetchone()[0] == len(gaps)


def test_a_gap_kind_outside_the_schemas_vocabulary_is_refused(
    tmp_path: Path, settings: Settings
) -> None:
    """`kind` is what the gap IS; `status` is how far it has got. An earlier curated file wrote a
    kind into the status column, and a loader reading it literally would have written an illegal
    status."""
    path = tmp_path / ADMISSIONS_FILE
    path.write_text(
        yaml.safe_dump(
            {
                "records": [_minimal_record()],
                "open_gaps": [
                    {"gap": "g", "kind": "open", "status": "open", "evidence": "somewhere"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AdmissionsFileError, match="'kind' is what the gap IS"):
        load_layer_gaps(settings, path=path)
