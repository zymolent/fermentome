"""Tests for `fermdb.curate.contexts` — proposing condition contexts without grouping them.

This module exists because `curate.promote` refuses to promote `conditions`, and the refusal is
right: turning N facet records into one context is a curation decision, and a wrong grouping
produces a context that never existed and that measurements are then pooled across. So the tests
that matter here are the ones that would catch this module quietly becoming the grouper it
replaces — no writer, no decided candidate, no default bucket, and an approval that stays refused
until a person has supplied the two things only a person can supply.

The other half is `context_hash`, where the whole risk is the opposite kind of silence. A hash
that folded `'NA'` into `NULL`, or `30` into `'30'`, or `"YPD"` into `"ypd"`, would merge two
contexts that are not the same and nothing downstream would ever notice. Every one of those is
pinned below, and the digest itself is pinned too — "stable across releases" is not a property a
test can assert by recomputing the thing it is testing.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from fermdb.curate import contexts as C
from fermdb.curate.promote import PROMOTERS
from fermdb.db import IN_MEMORY, open_db

REPO_ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = REPO_ROOT / "data" / "vocabularies"

#: The digest of a fixed three-facet context. Pinned, not recomputed: `context_hash` promises
#: that identical contexts across papers converge on one `condition_context` row, and a hash that
#: changed between releases would silently split every stored context from every new one.
PINNED = "ba65a5021fa635b1c8d7db63d8baf408c3105f421d0ae519362bff09221d6991"


def _three() -> list[C.Facet]:
    return [
        C.Facet("aeration_class", "recorded", "aerobic"),
        C.Facet("temperature_c", "recorded", 30.0),
        C.Facet("ph", "unknown"),
    ]


# ---------------------------------------------------------------------------- the hash itself


def test_the_hash_of_a_known_context_does_not_move() -> None:
    """The dedup promise in one line: two papers describing the same conditions must reach the
    same row, and a release that rehashed would split old rows from new ones invisibly."""
    assert C.context_hash(_three()) == PINNED


def test_facet_order_does_not_change_the_hash() -> None:
    """A context is a set of facets. If the order a curator happened to enter them in changed the
    hash, deduplication would fail for exactly the papers that describe the same conditions."""
    assert C.context_hash(list(reversed(_three()))) == PINNED


def test_thirty_and_thirty_point_zero_are_the_same_temperature() -> None:
    """One paper writes 30, another 30.0, a third stores Decimal('30.00'). Same vessel."""
    facets = [
        C.Facet("aeration_class", "recorded", "aerobic"),
        C.Facet("temperature_c", "recorded", Decimal("30.00")),
        C.Facet("ph", "unknown"),
    ]
    assert C.context_hash(facets) == PINNED


def test_surrounding_and_repeated_whitespace_is_not_a_difference() -> None:
    """A medium typed twice: `YPD  medium ` and `YPD medium` are one medium."""
    assert C.context_hash([C.Facet("medium_name", "recorded", " YPD  medium ")]) == C.context_hash(
        [C.Facet("medium_name", "recorded", "YPD medium")]
    )


def test_case_is_deliberately_not_folded() -> None:
    """Whether "YPD" and "ypd" name the same medium is a synonymy question. Answering it inside
    the hash would merge two contexts on a guess, which is the failure this package exists to
    refuse — so they hash apart and a curator normalises the value if they mean the same."""
    assert C.context_hash([C.Facet("medium_name", "recorded", "YPD")]) != C.context_hash(
        [C.Facet("medium_name", "recorded", "ypd")]
    )


def test_a_boolean_true_does_not_collide_with_the_string_true() -> None:
    """Without the type tag in the canonical form, `ph_controlled=True` and a free-text facet
    reading "true" would be the same recorded value."""
    assert C.context_hash([C.Facet("ph_controlled", "recorded", True)]) != C.context_hash(
        [C.Facet("ph_controlled", "recorded", "true")]
    )


# ------------------------------------------------- PLAN.md C.5: NULL vs 'NA' vs 'unknown'


def test_not_applicable_unknown_and_never_recorded_are_three_different_contexts() -> None:
    """PLAN.md C.5's rule, which is the whole reason the hash takes a (value, state) pair.

    "the source never recorded it" (the facet is simply absent), "recorded as not applicable" and
    "recorded but not resolvable" are three different facts about the same paper. Collapsing any
    two of them would let a context that states pH is irrelevant deduplicate onto one that never
    mentioned pH, and every measurement under both would then be pooled.
    """
    base = [C.Facet("aeration_class", "recorded", "aerobic")]
    absent = C.context_hash(base)
    not_applicable = C.context_hash([*base, C.Facet("ph", "not_applicable")])
    unknown = C.context_hash([*base, C.Facet("ph", "unknown")])
    assert len({absent, not_applicable, unknown}) == 3


def test_the_string_na_cannot_be_passed_as_a_value() -> None:
    """The coercion arriving through the front door: storing 'NA' as a medium name makes the
    not-applicable fact into text, and the text then hashes as though the paper wrote it."""
    with pytest.raises(ValueError, match="That is a state, not a value"):
        C.Facet("medium_class", "recorded", "NA")


def test_the_string_unknown_cannot_be_passed_as_a_value_either() -> None:
    """Same coercion, the other sentinel. `state='unknown'` is where this belongs."""
    with pytest.raises(ValueError, match="That is a state, not a value"):
        C.Facet("aeration_class", "recorded", "unknown")


def test_an_empty_string_is_not_a_recorded_value() -> None:
    """A blank is the most common way a missing value is smuggled past a state column."""
    with pytest.raises(ValueError, match="That is a state, not a value"):
        C.Facet("medium_name", "recorded", "   ")


# ----------------------------------------------------------------- what the hash refuses


def test_a_context_with_no_recorded_facets_is_refused() -> None:
    """Every unknown-conditions sample would otherwise hash to one shared context and be pooled.
    PLAN.md C.7 keeps such a sample at `condition_context = NULL`; an empty context is that NULL
    wearing an id."""
    with pytest.raises(ValueError, match="no recorded facets"):
        C.context_hash([])


def test_one_facet_recorded_twice_is_refused_rather_than_resolved() -> None:
    """Two values for one facet are two contexts, and which one a measurement belongs to is the
    curator's call. Picking the first, the last or the longest would be the guess."""
    with pytest.raises(ValueError, match="appears twice"):
        C.context_hash(
            [
                C.Facet("medium_name", "recorded", "YPD"),
                C.Facet("medium_name", "recorded", "SC-Ura"),
            ]
        )


def test_a_recorded_facet_with_no_value_is_refused() -> None:
    """`schema.sql` refuses that row in both directions; a hash over it would claim a value the
    source does not have."""
    with pytest.raises(ValueError, match="'recorded' with no value"):
        C.Facet("ph", "recorded")


def test_a_not_recorded_facet_carrying_a_value_is_refused() -> None:
    """Unknown, and it was 7.2 -- two contradictory claims about the same fact."""
    with pytest.raises(ValueError, match="contradictory claims"):
        C.Facet("ph", "unknown", 7.2)


def test_a_state_outside_the_three_is_refused() -> None:
    """The state vocabulary is closed in `schema.sql`; a fourth value here would hash into a row
    the database then rejects."""
    with pytest.raises(ValueError, match="must be one of"):
        C.Facet("ph", "missing")


def test_a_facet_carries_no_as_reported_shadow_so_it_cannot_reach_the_hash() -> None:
    """Two papers writing "30 C" and "30 +/- 1 C" for the same parsed 30.0 are one context. The
    shadows live on the `condition_context` row for provenance; a field for one here would
    eventually be hashed and would split the two."""
    assert tuple(C.Facet.__dataclass_fields__) == ("name", "state", "value")


# ------------------------------------------------------------------- the proposal mechanism


def _task(
    conn: sqlite3.Connection,
    task_id: str,
    facet: str,
    value: str,
    *,
    strain: str | None = None,
    start: int = 100,
    end: int = 140,
    status: str = "accepted",
    publication: str = "doi:10.1/a",
) -> None:
    payload = {
        "facet": facet,
        "value_as_reported": value,
        "strain_name_as_reported": strain,
        "confidence": "unverified",
        "zone": "I",
        "span": {
            "quote": f"grown in {value}",
            "char_start": start,
            "char_end": end,
            "section": "methods",
        },
    }
    resolved = status not in {"pending", "in_progress"}
    conn.execute(
        "INSERT INTO curation_task (id, extraction_id, publication_id, record_path, record_kind, "
        "payload, status, proposal_hash, created_at, curator, curator_kind, resolved_at, "
        "resolution_reason) "
        "VALUES (?, 'YAA:EXTR:1', ?, ?, 'conditions', ?, ?, ?, '2026-09-21T00:00:00+00:00', "
        "?, ?, ?, ?)",
        (
            task_id,
            publication,
            f"conditions[{task_id}]",
            json.dumps(payload),
            status,
            task_id,
            "k.saikia" if resolved else None,
            "human" if resolved else None,
            "2026-09-21T00:00:00+00:00" if resolved else None,
            "checked against the methods section" if resolved else None,
        ),
    )


@pytest.fixture
def atlas() -> sqlite3.Connection:
    """One publication with an extraction, ready for `conditions` tasks to be added per test."""
    conn = open_db(IN_MEMORY)
    conn.executescript(
        """
        INSERT INTO publication (id, title, zone, evidence, confidence)
            VALUES ('doi:10.1/a', 'A paper', 'R', 'test', 'high');
        INSERT INTO extraction (id, publication_id, section, extractor, extractor_version,
                                model, prompt_version, zone)
            VALUES ('YAA:EXTR:1', 'doi:10.1/a', 'methods', 'harness', '1', 'm', 'p', 'I');
        """
    )
    conn.commit()
    return conn


def test_facets_read_from_one_sentence_are_offered_as_one_candidate(
    atlas: sqlite3.Connection,
) -> None:
    """The strongest basis available: the source reported them in the same words. Still a
    candidate, because co-occurrence in a sentence is not a statement that the facets describe
    one vessel."""
    _task(atlas, "t1", "medium_name", "YPD", start=10, end=50)
    _task(atlas, "t2", "temperature_c", "30 C", start=10, end=50)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].basis is C.Basis.SAME_SPAN
    assert set(proposal.candidates[0].facet_names) == {"medium_name", "temperature_c"}


def test_facets_sharing_only_a_strain_name_are_labelled_as_an_unrecorded_grouping(
    atlas: sqlite3.Connection,
) -> None:
    """The guess `promote.PROMOTERS` refuses to make. It is offered, and it is offered *labelled*
    — one strain routinely spans several contexts in one paper, which is usually the experiment
    itself, so a curator who accepts this whole is doing so knowingly."""
    _task(atlas, "t1", "medium_name", "YPD", strain="BSW191", start=10, end=50)
    _task(atlas, "t2", "temperature_c", "30 C", strain="BSW191", start=80, end=120)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert len(proposal.candidates) == 1
    candidate = proposal.candidates[0]
    assert candidate.basis is C.Basis.SAME_STRAIN_AS_REPORTED
    assert "grouping_not_recorded" in {note.code for note in candidate.notes}


def test_a_facet_with_no_strain_and_no_shared_span_is_shown_alone(
    atlas: sqlite3.Connection,
) -> None:
    """There is no default bucket, and that is the design. A bucket eventually gets treated as a
    context, and everything in it gets compared."""
    _task(atlas, "t1", "carbon_sources", "2% glucose", start=10, end=50)
    _task(atlas, "t2", "temperature_c", "30 C", start=80, end=120)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert len(proposal.candidates) == 2
    assert {c.basis for c in proposal.candidates} == {C.Basis.UNATTRIBUTED}
    assert all(len(c.facets) == 1 for c in proposal.candidates)


def test_a_facet_is_never_offered_in_two_candidates_at_once(atlas: sqlite3.Connection) -> None:
    """A record placed by its span must not also appear under its strain. Seeing one facet twice
    would make the curator decide which copy is real before deciding anything useful."""
    _task(atlas, "t1", "medium_name", "YPD", strain="BSW191", start=10, end=50)
    _task(atlas, "t2", "temperature_c", "30 C", strain="BSW191", start=10, end=50)
    _task(atlas, "t3", "ph", "5.0", strain="BSW191", start=90, end=120)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    seen = [record.task_id for candidate in proposal.candidates for record in candidate.facets]
    assert sorted(seen) == ["t1", "t2", "t3"]


def test_a_candidate_holding_one_facet_twice_says_it_cannot_be_accepted_whole(
    atlas: sqlite3.Connection,
) -> None:
    """The real case in the atlas today: one paper reports `medium_name` twice against one
    strain. A `condition_context` holds one value per facet, so that candidate is at least two
    contexts and the split is the decision — which is exactly what must not be guessed."""
    _task(atlas, "t1", "medium_name", "YPD + 100 g/L glucose", strain="IbOH", start=10, end=50)
    _task(atlas, "t2", "medium_name", "YPD", strain="IbOH", start=80, end=120)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    codes = {note.code for note in proposal.candidates[0].notes}
    assert "facet_recorded_twice" in codes


def test_a_candidate_missing_a_class_defining_facet_says_so(atlas: sqlite3.Connection) -> None:
    """PLAN.md C.5's 2026-09-20 amendment: `carbon_regime` and `in_situ_product_removal` join
    `aeration_class` as class-defining, and a measurement that does not state them cannot enter
    an aggregate with one that does. Saying it here costs a minute; discovering it at aggregation
    time costs the aggregate."""
    _task(atlas, "t1", "medium_name", "YPD", start=10, end=50)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    notes = {note.code: note.message for note in proposal.candidates[0].notes}
    assert "class_defining_facet_absent" in notes
    assert "carbon_regime" in notes["class_defining_facet_absent"]


def test_a_facet_name_the_vocabulary_does_not_know_is_flagged(atlas: sqlite3.Connection) -> None:
    """A facet name the atlas does not recognise changes `context_hash` without changing any
    recorded fact, so two spellings of one facet would stop deduplicating — silently."""
    _task(atlas, "t1", "temperature_celsius", "30 C", start=10, end=50)
    known = C.load_condition_facets(VOCABULARIES)
    proposal = C.context_proposal(atlas, "doi:10.1/a", known_facets=known)
    assert proposal.unknown_facets == ("temperature_celsius",)
    assert "facet_not_in_vocabulary" in {n.code for n in proposal.candidates[0].notes}


def test_a_pending_proposal_is_not_grouped_into_anything(atlas: sqlite3.Connection) -> None:
    """Grouping facets a curator has not yet agreed are true puts the expensive decision before
    the cheap one, and quietly lends a pending claim the authority of an accepted grouping."""
    _task(atlas, "t1", "medium_name", "YPD", status="pending", start=10, end=50)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert proposal.candidates == ()
    assert "no_accepted_conditions" in {note.code for note in proposal.notes}


def test_no_candidate_is_ever_decided(atlas: sqlite3.Connection) -> None:
    """`decided` has no code path that sets it True, and the assertion exists so that adding one
    breaks a test rather than shipping. A decided candidate is a grouping made automatically."""
    _task(atlas, "t1", "medium_name", "YPD", strain="BSW191", start=10, end=50)
    _task(atlas, "t2", "temperature_c", "30 C", strain="BSW191", start=10, end=50)
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert proposal.candidates
    assert not any(candidate.decided for candidate in proposal.candidates)
    assert all(c.as_json()["decided"] is False for c in proposal.candidates)


def test_proposing_writes_nothing_and_condition_context_stays_empty(
    atlas: sqlite3.Connection,
) -> None:
    """The one property that makes every other refusal in this module enforceable."""
    _task(atlas, "t1", "medium_name", "YPD", strain="BSW191", start=10, end=50)
    before = atlas.total_changes
    C.context_proposal(atlas, "doi:10.1/a")
    C.context_proposals(atlas)
    C.build_context_page(atlas)
    assert atlas.total_changes == before
    assert atlas.execute("SELECT COUNT(*) FROM condition_context").fetchone()[0] == 0
    assert atlas.execute("SELECT COUNT(*) FROM condition_context_facet").fetchone()[0] == 0


def test_conditions_still_have_no_promoter(atlas: sqlite3.Connection) -> None:
    """This module is the alternative to a `conditions` promoter, not a step towards one. If a
    promoter appears, the grouping decision has been moved back into a mapping."""
    assert "conditions" not in PROMOTERS


def test_a_publication_with_no_accepted_conditions_gets_a_stated_reason(
    atlas: sqlite3.Connection,
) -> None:
    """An empty proposal and a proposal nobody built look the same to a caller unless one says
    why it is empty."""
    proposal = C.context_proposal(atlas, "doi:10.1/a")
    assert proposal.facet_count == 0
    assert "condition_context = NULL" in proposal.notes[0].message


# -------------------------------------------------------------------------- the page and JSON


def test_the_page_carries_every_facet_with_its_quoted_span(atlas: sqlite3.Connection) -> None:
    """The quote is the point. Without the sentence beside the facet, grouping is guesswork done
    by a person instead of by a mapping, which is not an improvement."""
    _task(atlas, "t1", "medium_name", "YPD", strain="BSW191", start=10, end=50)
    page = C.build_context_page(atlas)
    assert "grown in YPD" in page
    assert "medium_name" in page
    assert "BSW191" in page


def test_the_page_states_that_it_writes_nothing(atlas: sqlite3.Connection) -> None:
    """The review page it is modelled on makes the same promise in the same place, because a
    curator has to be able to see it without reading the source."""
    _task(atlas, "t1", "medium_name", "YPD", start=10, end=50)
    assert "No condition_context row is" in C.build_context_page(atlas)


def test_the_page_payload_carries_no_parsed_value_and_no_state(
    atlas: sqlite3.Connection,
) -> None:
    """The page shows the paper's own string and nothing more. A parsed value in the payload
    would be this module deciding what "micro-aerobic (0.2 vvm)" means, which is the curator's
    reading, and a state would be it deciding whether a blank is 'NA' or never-recorded."""
    _task(atlas, "t1", "aeration_class", "micro-aerobic (0.2 vvm)", start=10, end=50)
    rows = C.page_payload(C.context_proposals(atlas))
    assert rows and all("value" not in row and "state" not in row for row in rows)
    assert rows[0]["value_as_reported"] == "micro-aerobic (0.2 vvm)"


# ----------------------------------------------------------------------------- the approval


def test_an_approval_skeleton_with_no_state_is_refused() -> None:
    """What the page emits, and where the mechanism deliberately stops. Deciding whether a blank
    facet is 'recorded as not applicable' or 'never recorded' is the curation decision; defaulting
    it would be PLAN.md C.5's forbidden coercion performed by a convenience."""
    document = {
        "publication_id": "doi:10.1/a",
        "contexts": [
            {
                "label": "candidate 1",
                "facets": [
                    {"name": "medium_name", "state": None, "value": None, "as_reported": "YPD"}
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="has no state"):
        C.load_approval(document)


def test_an_approval_a_curator_completed_hashes_each_context() -> None:
    """The mechanism's end: a grouping a person made, turned into the stable identity PLAN.md C.5
    asks for — and returned, not written."""
    document = {
        "publication_id": "doi:10.1/a",
        "contexts": [
            {
                "label": "aerobic flask",
                "facets": [
                    {"name": "aeration_class", "state": "recorded", "value": "aerobic"},
                    {"name": "temperature_c", "state": "recorded", "value": 30},
                    {"name": "ph", "state": "unknown"},
                ],
            }
        ],
    }
    approved = C.load_approval(document)
    assert [label for label, _, _ in approved] == ["aerobic flask"]
    assert approved[0][1] == PINNED


def test_two_approved_contexts_that_hash_alike_are_refused_as_one_context_entered_twice() -> None:
    """`condition_context.context_hash` is UNIQUE, so the second would fail at insert time with a
    constraint error that says nothing. Here it says what actually happened, and names the two
    ways out — merge them, or record what actually differs."""
    facets = [{"name": "aeration_class", "state": "recorded", "value": "aerobic"}]
    document = {
        "contexts": [
            {"label": "flask A", "facets": facets},
            {"label": "flask B", "facets": facets},
        ]
    }
    with pytest.raises(ValueError, match="same context recorded twice"):
        C.load_approval(document)


def test_an_approval_with_no_contexts_is_refused() -> None:
    """An empty approval reads as "the curator approved nothing", which is indistinguishable from
    a document that lost its contents on the way here."""
    with pytest.raises(ValueError, match="non-empty 'contexts'"):
        C.load_approval({"publication_id": "doi:10.1/a", "contexts": []})


# ------------------------------------------------------------------ the gap this cannot close


def test_two_class_defining_facets_have_nowhere_to_be_stored_yet() -> None:
    """Not a test of this module: a test that records why it stops where it does.

    PLAN.md C.5's 2026-09-20 amendment makes `carbon_regime` and `in_situ_product_removal`
    class-defining and required in `context_hash`. Neither has a `condition_context` column and
    neither is in `data/vocabularies/condition_facets.tsv`, so a writer built today would drop
    both — out of the row and out of the hash — and two contexts differing only by whether the
    product was being stripped would deduplicate onto each other. That is the migration this
    work reports rather than performs; when it lands, this test is the one that should fail.
    """
    known = C.load_condition_facets(VOCABULARIES)
    conn = open_db(IN_MEMORY)
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(condition_context)").fetchall()
    }
    for facet in ("carbon_regime", "in_situ_product_removal"):
        assert facet not in known
        assert facet not in columns
    assert "aeration_class" in known
    assert "aeration_class" in columns
