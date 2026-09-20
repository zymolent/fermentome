"""Tests for `fermdb.curate.genotype`.

Every genotype string below is copied from a paper in the corpus, not invented. A parser tested
only against the notation its author imagined is a parser that meets real data and drops tokens.

The dominant theme is the no-silent-drop rule. A parse that handles four of five deletions and
ignores the fifth produces a strain that looks fully characterised and is missing a modification,
and nothing downstream can tell. So the tests assert on what is *kept*, including the tokens that
failed, at least as often as on what is understood.
"""

from __future__ import annotations

import pytest

from fermdb.curate.genotype import DELTA_CHARACTERS, parse_genotype

# Wess et al., 10.1186/s13068-019-1486-8, Table 3. The delta here is U+0394.
JWY23 = "Δilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1; Δadh1; Δgpd1; Δgpd2; Δald6"
JWY12 = "Δilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1; Δpdc1::MTH1; Δpdc5"
JWY13 = "Δilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1; Δpdc1; Δpdc5; Δmth1(+169; +393)"

# Wess et al., figure caption. Same table, U+2206 instead -- indistinguishable by eye.
JWY04_INCREMENT = "∆ilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1"

# Watanabe et al., 10.1186/1475-2859-12-119, strain table. A different notation entirely.
BSW205 = "BY4741 lpd1Δ/pATP426-kivd-ADH6-ILV2/pILV532cytM/pATP423-MAE1"


def test_a_full_deletion_series_parses_completely() -> None:
    parsed = parse_genotype(JWY23)
    assert parsed.fully_parsed
    assert parsed.deletions == (
        "ILV2",
        "BDH1",
        "BDH2",
        "LEU4",
        "LEU9",
        "ECM31",
        "ILV1",
        "ADH1",
        "GPD1",
        "GPD2",
        "ALD6",
    )
    assert parsed.unparsed == ()


def test_the_adh1_deletion_is_in_the_parse() -> None:
    """The specific fact a prose reading of the abstract lost.

    JWY19 and JWY23 carry Δadh1, and the abstract's wording made it look as though gpd1/2 was
    added straight to JWY04. Once the genotype is parsed the question is a set membership test
    rather than a reading of English.
    """
    assert "ADH1" in parse_genotype(JWY23).deletions
    assert "ADH1" not in parse_genotype(JWY04_INCREMENT).deletions


def test_both_delta_characters_are_handled() -> None:
    """U+0394 and U+2206 look identical and are not. Wess et al. use both, in one table."""
    assert len(set(DELTA_CHARACTERS)) == 2
    parsed = parse_genotype(JWY04_INCREMENT)
    assert parsed.fully_parsed
    assert parsed.deletions[0] == "ILV2"  # the token written with U+2206
    for delta in DELTA_CHARACTERS:
        assert parse_genotype(f"{delta}ilv2").deletions == ("ILV2",)


def test_a_deletion_with_an_integration_keeps_both_halves() -> None:
    """Δpdc1::MTH1 deletes PDC1 *and* puts MTH1 there. Recording only the deletion loses half."""
    parsed = parse_genotype(JWY12)
    assert parsed.fully_parsed
    part = next(p for p in parsed.parts if p.kind == "deletion_with_insertion")
    assert (part.target, part.inserted) == ("pdc1", "MTH1")
    assert "PDC1" in parsed.deletions


def test_a_qualifier_containing_a_semicolon_does_not_split_the_token() -> None:
    """Δmth1(+169; +393) is one modification, not two. Splitting on ';' naively gives three."""
    parsed = parse_genotype(JWY13)
    assert parsed.fully_parsed
    part = next(p for p in parsed.parts if p.detail)
    assert part.target == "mth1"
    assert part.detail == "+169; +393"
    assert len(parsed.deletions) == 10


def test_a_trailing_delta_is_the_same_as_a_leading_one() -> None:
    """Papers write both ``Δlpd1`` and ``lpd1Δ``."""
    assert parse_genotype("lpd1Δ").deletions == ("LPD1",)
    assert parse_genotype("Δlpd1").deletions == ("LPD1",)


def test_a_plasmid_genotype_is_not_forced_into_the_deletion_grammar() -> None:
    parsed = parse_genotype(BSW205)
    assert parsed.fully_parsed
    assert parsed.parts[0].kind == "background"
    assert parsed.parts[0].target == "BY4741 lpd1Δ" or "LPD1" in parsed.deletions
    assert parsed.plasmids == ("pATP426", "pILV532cytM", "pATP423")
    carried = next(p for p in parsed.parts if p.target == "pATP426")
    assert carried.carries == ("kivd", "ADH6", "ILV2")


def test_an_unrecognised_token_is_kept_not_dropped() -> None:
    """The rule the module exists for: a partial parse must not pass for a complete one."""
    parsed = parse_genotype("Δilv2; something the parser has never seen [x]; Δbdh1")
    assert not parsed.fully_parsed
    assert parsed.deletions == ("ILV2", "BDH1")
    assert [p.as_reported for p in parsed.unparsed] == ["something the parser has never seen [x]"]
    # And it survives serialization, which is where a dropped token would vanish for good.
    assert parsed.as_json()["unparsed"] == ["something the parser has never seen [x]"]
    assert parsed.as_json()["fully_parsed"] is False


def test_the_reported_string_is_never_altered() -> None:
    """Zone R. The parse is derived; the paper's string is the record."""
    for genotype in (JWY23, JWY12, JWY13, BSW205, "nonsense [[["):
        assert parse_genotype(genotype).as_reported == genotype


def test_every_token_appears_in_the_parts() -> None:
    """Counted rather than trusted: this is the invariant that makes 'no silent drop' true."""
    for genotype in (JWY23, JWY12, JWY13, BSW205, JWY04_INCREMENT):
        parsed = parse_genotype(genotype)
        for part in parsed.parts:
            assert part.as_reported in genotype
        # Semicolon-separated top-level tokens all survive.
        top_level = [t.strip() for t in genotype.split(";") if t.strip() and "(" not in t]
        kept = " ".join(p.as_reported for p in parsed.parts)
        for token in top_level:
            assert token.split("/")[0].strip() in kept


@pytest.mark.parametrize("genotype", ["", "   ", "\n"])
def test_an_empty_genotype_has_nothing_to_fail_on(genotype: str) -> None:
    parsed = parse_genotype(genotype)
    assert parsed.parts == ()
    assert parsed.fully_parsed
    assert parsed.deletions == ()


def test_parsing_never_raises_on_unfamiliar_notation() -> None:
    """A genotype the parser does not understand is a fact about the corpus, not a crash."""
    for genotype in ("???", "Δ", "::", "p", "(((", "a; ; b", "MATa; MAL2-8c; SUC2"):
        parse_genotype(genotype)  # must not raise
