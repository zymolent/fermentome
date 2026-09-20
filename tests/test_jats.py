"""Tests for `fermdb.extract.jats`.

Every case here is a shape found in the corpus acquisition actually fetched, not an invented
one -- the nested `<table-wrap>` in particular, which is what the real Europe PMC documents do
and what a first pass at this module got wrong.
"""

from __future__ import annotations

import pytest

from fermdb.extract.jats import JatsError, is_jats, jats_to_text


def _article(body: str, *, abstract: str = "", title: str = "A paper") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<article><front><article-meta><title-group>"
        f"<article-title>{title}</article-title></title-group>"
        f"{f'<abstract><p>{abstract}</p></abstract>' if abstract else ''}"
        f"</article-meta></front><body>{body}</body></article>"
    ).encode()


def test_is_jats_accepts_an_article_and_rejects_other_xml() -> None:
    assert is_jats(_article("<p>Text.</p>")) is True
    assert is_jats(b"<error>not open access</error>") is False
    assert is_jats(b"%PDF-1.4 binary") is False


def test_inline_markup_is_flattened_so_a_quote_stays_whole() -> None:
    """The reason this module exists: JATS italicises gene names mid-sentence.

    A quote spanning `<italic>ILV5</italic>` either fails to re-resolve at its recorded offsets
    or resolves against text nobody wrote -- and gene names appear in exactly the sentences that
    carry the measurements.
    """
    text = jats_to_text(
        _article("<p>Overexpression of <italic>ILV5</italic> raised the titer to 1.62 g/L.</p>")
    )
    assert "Overexpression of ILV5 raised the titer to 1.62 g/L." in text
    assert "<italic>" not in text


def test_a_table_nested_inside_a_paragraph_is_lifted_out() -> None:
    """JATS permits a whole table inside the paragraph that cites it, and publishers use it.

    Flattened with `itertext()` the cells inline into the sentence as an unpaired run of numbers
    -- "listed in Table 1. Strain Titer IV-1 1.62 IV-2 0.31" -- leaving the model to re-pair
    strain with value. Lifting the table out keeps each row intact.
    """
    body = (
        "<sec><title>Results</title>"
        "<p>Strains are listed in Table 1."
        "<table-wrap><label>Table 1</label>"
        "<caption><p>Isobutanol titers by strain</p></caption>"
        "<table><thead><tr><th>Strain</th><th>Titer (g/L)</th></tr></thead>"
        "<tbody><tr><td>IV-1</td><td>1.62</td></tr>"
        "<tr><td>IV-2</td><td>0.31</td></tr></tbody></table>"
        "</table-wrap>"
        " Growth was unaffected.</p></sec>"
    )
    text = jats_to_text(_article(body))
    lines = text.splitlines()

    # The paragraph keeps its own words, including the text that continues *after* the table.
    assert "Strains are listed in Table 1. Growth was unaffected." in lines
    # And each row survives as a row.
    assert "Strain | Titer (g/L)" in lines
    assert "IV-1 | 1.62" in lines
    assert "IV-2 | 0.31" in lines
    # The paragraph must not have swallowed the cells.
    paragraph = next(line for line in lines if line.startswith("Strains are listed"))
    assert "1.62" not in paragraph


def test_a_table_in_a_floats_group_is_also_found() -> None:
    """The other publisher convention: floats collected at the end, outside <body>."""
    xml = (
        b'<?xml version="1.0"?><article><front><article-meta><title-group>'
        b"<article-title>T</article-title></title-group></article-meta></front>"
        b"<body><p>See Table 1.</p></body>"
        b"<floats-group><table-wrap><label>Table 1</label>"
        b"<table><tbody><tr><td>CEN.PK</td><td>0.98</td></tr></tbody></table>"
        b"</table-wrap></floats-group></article>"
    )
    assert "CEN.PK | 0.98" in jats_to_text(xml).splitlines()


def test_a_table_published_as_an_image_says_so() -> None:
    """With only a caption in the text, "does this paper report a titer" answers wrongly."""
    body = (
        "<p>Results follow."
        "<table-wrap><label>Table 1</label>"
        "<caption><p>Fatty acid composition</p></caption>"
        '<graphic xlink:href="Tab1.jpg" xmlns:xlink="http://www.w3.org/1999/xlink"/>'
        "</table-wrap></p>"
    )
    text = jats_to_text(_article(body))
    assert "Fatty acid composition" in text
    assert "[table not machine-readable: published as an image]" in text


def test_the_reference_list_is_dropped() -> None:
    """A bibliography reads like findings; a span quoting one would verify and still mislead."""
    xml = (
        b'<?xml version="1.0"?><article><front><article-meta><title-group>'
        b"<article-title>T</article-title></title-group></article-meta></front>"
        b"<body><p>Our titer was 1.6 g/L.</p></body>"
        b"<back><ref-list><ref><element-citation>"
        b"<article-title>Isobutanol production at 22 g/L in yeast</article-title>"
        b"</element-citation></ref></ref-list></back></article>"
    )
    text = jats_to_text(xml)
    assert "1.6 g/L" in text
    assert "22 g/L" not in text


def test_title_and_abstract_come_first() -> None:
    text = jats_to_text(
        _article("<p>Body.</p>", abstract="We made isobutanol.", title="Isobutanol")
    )
    assert text.splitlines()[0] == "Isobutanol"
    assert "We made isobutanol." in text


def test_blocks_are_separated_so_offsets_are_meaningful() -> None:
    text = jats_to_text(_article("<p>First.</p><p>Second.</p>"))
    assert text == "A paper\n\nFirst.\n\nSecond."
    # A span's offsets index into exactly this string.
    assert text[text.index("Second.") : text.index("Second.") + 7] == "Second."


def test_unparseable_xml_is_refused_rather_than_guessed() -> None:
    with pytest.raises(JatsError, match="not parseable"):
        jats_to_text(b"<article><p>unclosed")


def test_xml_that_is_not_an_article_is_refused() -> None:
    with pytest.raises(JatsError, match="not a JATS article"):
        jats_to_text(b'<?xml version="1.0"?><error>not open access</error>')


def test_an_article_with_no_text_is_refused_rather_than_returning_empty() -> None:
    with pytest.raises(JatsError, match="no title, abstract or body"):
        jats_to_text(b'<?xml version="1.0"?><article><body/></article>')
