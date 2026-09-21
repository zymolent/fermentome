"""The corroboration gate, tested against the rows that made it necessary.

Every quote below is real -- taken from the pending queue or from the three rows corrected on
2026-09-22 -- because a gate tested only on invented strings proves nothing about the failure it
was built to stop.
"""

from __future__ import annotations

import pytest

from fermdb.curate.corroborate import (
    ACCEPT,
    REVIEW,
    corroborate_payload,
)


def payload(quote: str, **fields: object) -> dict[str, object]:
    return {**fields, "span": {"quote": quote, "section": "results", "char_start": 0}}


# --------------------------------------------------------------------------------------------
# The three rows of 2026-09-22. All had valid spans; all were wrong; none named their subject.
# --------------------------------------------------------------------------------------------


def test_rejects_the_retracted_lpd1_modification() -> None:
    """The row that was retracted: lpd1delta filed against BSW191 from an abstract sentence.

    `verify_span` passed this. The quote is genuinely in the paper at those offsets. What it is
    not, is about BSW191 -- and that is the whole distinction this module exists to draw.
    """
    report = corroborate_payload(
        "T1",
        "modifications",
        payload(
            "The integration of a single gene deletion lpd1Δ and the activation of the "
            "transhydrogenase-like shunt further increased isobutanol levels",
            strain_name_as_reported="BSW191",
            target_as_reported="LPD1",
        ),
    )
    assert report.verdict == REVIEW
    assert report.absent == ("strain_name_as_reported",)
    # The target *is* corroborated; only the subject was inferred. Saying so is the point -- it
    # tells the reviewer which half of the row to check.
    assert [c.found for c in report.checks] == [False, True]


def test_rejects_a_modification_whose_subject_is_only_in_an_adjacent_sentence() -> None:
    report = corroborate_payload(
        "T2",
        "modifications",
        payload(
            "Three genes required for isobutanol biosynthesis, including ILV2, kivd, and ADH6, "
            "were introduced",
            strain_name_as_reported="BSW191",
            target_as_reported="kivd",
        ),
    )
    assert report.verdict == REVIEW
    assert "strain_name_as_reported" in report.absent


def test_rejects_a_measurement_whose_subject_is_a_back_reference() -> None:
    """The first pending measurement in the queue: value and unit corroborate, subject does not.

    "whose" points at a strain named in the previous sentence. The number and unit are right
    there in the quote, so a rule checking only those would clear it -- and the attribution, the
    part that decides which strain the row lands on, would never have been checked.
    """
    report = corroborate_payload(
        "T3",
        "measurements",
        payload(
            "whose isobutanol production level was 22 ± 1 mg/L (Figure b)",
            strain_name_as_reported="BSW100",
            value=22,
            unit="mg/L",
        ),
    )
    assert report.verdict == REVIEW
    assert report.absent == ("strain_name_as_reported",)


# --------------------------------------------------------------------------------------------
# What it must let through, or it is worthless
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "strain", "value", "unit"),
    [
        (
            "the control strain BSW13 (23 ± 3 mg/L, YPH499/pATP426-kivd-ADH6/pATP425)",
            "BSW13",
            23,
            "mg/L",
        ),
        (
            "Mdh2p and Pyc2p in the BSW10 strain, and the isobutanol titer reached "
            "83 ± 2 mg/L (Figure a)",
            "BSW10",
            83,
            "mg/L",
        ),
        (
            "The isobutanol yields of BSW17 and BSW18 strains were 0.006 ± 0.0003 and "
            "0.007 ± 0.0002 g/g glucose consumed, respectively",
            "BSW17",
            0.006,
            "g/g",
        ),
    ],
)
def test_accepts_measurements_that_name_their_own_subject(
    quote: str, strain: str, value: float, unit: str
) -> None:
    report = corroborate_payload(
        "T", "measurements", payload(quote, strain_name_as_reported=strain, value=value, unit=unit)
    )
    assert report.verdict == ACCEPT, report.note


def test_accepts_a_strain_row_from_the_strain_table() -> None:
    report = corroborate_payload(
        "T",
        "strains",
        payload(
            "BSW100 pdc6Δ | BY4741 pdc6Δ/pGK423-kivd/pGK425-ILV2/pGK426-ADH6",
            name_as_reported="BSW100 pdc6Δ",
        ),
    )
    assert report.verdict == ACCEPT


# --------------------------------------------------------------------------------------------
# The multi-subject rule: containment passes, and the row is still unusable
# --------------------------------------------------------------------------------------------


def test_rejects_a_range_spread_across_four_strains() -> None:
    """Found by eye in the first accepted batch, which is why the rule exists.

    The quote contains the subject string verbatim -- all four strains of it -- so every
    containment check passes. The row is nonetheless unpromotable: 138 is the bottom of a range
    over four strains and nothing says which one it belongs to.
    """
    subject = "BSW100 pda1Δ, BSW100 pdb1Δ, BSW100 lpd1Δ, and BSW100 lat1Δ"
    quote = (
        "isobutanol production was remarkably increased to 138–159 mg/L in "
        + subject
        + " strains (Figure b)"
    )
    assert subject in quote  # containment alone would clear this
    report = corroborate_payload(
        "T",
        "measurements",
        payload(quote, strain_name_as_reported=subject, value=138, unit="mg/L"),
    )
    assert report.verdict == REVIEW
    assert "names several things" in report.note


# --------------------------------------------------------------------------------------------
# Every ambiguity resolves toward review
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("measurements", {"strain_name_as_reported": "BSW10", "value": 83}),  # no unit
        ("measurements", {"strain_name_as_reported": "BSW10", "unit": "mg/L"}),  # no value
        ("modifications", {"target_as_reported": "LPD1"}),  # no subject at all
    ],
)
def test_a_missing_identifying_field_is_never_treated_as_corroborated(
    kind: str, body: dict[str, object]
) -> None:
    report = corroborate_payload("T", kind, payload("BSW10 reached 83 mg/L", **body))
    assert report.verdict == REVIEW


def test_an_unknown_record_kind_goes_to_review_rather_than_through() -> None:
    """A kind nobody has defined fields for must not be cleared by the absence of a rule."""
    report = corroborate_payload("T", "something_new", payload("anything at all"))
    assert report.verdict == REVIEW
    assert report.checks == ()


def test_a_proposal_with_no_quote_cannot_be_corroborated() -> None:
    report = corroborate_payload("T", "strains", {"name_as_reported": "BSW13"})
    assert report.verdict == REVIEW


def test_pathway_configurations_have_no_subject_to_corroborate() -> None:
    """Deliberate: the extraction schema carries no host, so these always go to a reader.

    Mirrors `curate.promote._plan_configuration`, which refuses to guess the host rather than
    inventing one. If a host field is ever added there, it belongs in `IDENTIFYING_FIELDS` too.
    """
    report = corroborate_payload(
        "T", "pathway_configurations", payload("a cytosolic Ehrlich pathway was assembled")
    )
    assert report.verdict == REVIEW


# --------------------------------------------------------------------------------------------
# Normalisation: it may only ever make a match easier, never admit a different subject
# --------------------------------------------------------------------------------------------


def test_unit_written_as_a_negative_exponent_still_corroborates() -> None:
    """`g L-1` and `g/L` are the same unit; treating them as different would cost reviews."""
    report = corroborate_payload(
        "T",
        "measurements",
        payload(
            "the BSW205 strain produced 1.62 g L-1 isobutanol",
            strain_name_as_reported="BSW205",
            value=1.62,
            unit="g/L",
        ),
    )
    assert report.verdict == ACCEPT, report.note


def test_a_typographic_dash_in_a_strain_name_still_matches() -> None:
    report = corroborate_payload(
        "T",
        "strains",
        payload("the YPH499–derived strain", name_as_reported="YPH499-derived"),
    )
    assert report.verdict == ACCEPT


def test_a_two_character_subject_is_not_evidence_of_anything() -> None:
    """A short token matches almost any sentence, so it is treated as absent, not as a match."""
    report = corroborate_payload(
        "T", "strains", payload("the strain was grown", name_as_reported="B1")
    )
    assert report.verdict == REVIEW


def test_a_different_number_does_not_corroborate() -> None:
    report = corroborate_payload(
        "T",
        "measurements",
        payload(
            "BSW10 reached 83 ± 2 mg/L",
            strain_name_as_reported="BSW10",
            value=138,
            unit="mg/L",
        ),
    )
    assert report.verdict == REVIEW
    assert "value" in report.absent


def test_an_integer_valued_float_matches_the_way_a_paper_prints_it() -> None:
    report = corroborate_payload(
        "T",
        "measurements",
        payload("BSW10 reached 83 mg/L", strain_name_as_reported="BSW10", value=83.0, unit="mg/L"),
    )
    assert report.verdict == ACCEPT, report.note
