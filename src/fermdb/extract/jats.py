"""JATS XML to plain text, for the full text Europe PMC serves.

Almost everything acquisition stores is JATS rather than PDF: `acquire` ranks Europe PMC's
`fullTextXML` endpoint above the PDF precisely because the markup keeps the section and paragraph
boundaries a PDF has to have reconstructed from glyph positions. That advantage is only real if
the extractor reads the markup instead of the raw bytes.

Handing raw XML to a model would break the thing the whole extraction path is built around.
Span verification (`fermdb.llm.validate.verify_span`) re-resolves a verbatim quote at recorded
character offsets against the source text, and JATS wraps gene and species names in `<italic>`
mid-sentence -- `<italic>ILV5</italic>` overexpression raised the titer -- so the sentences
carrying the measurements this atlas exists to collect are exactly the ones markup cuts in half.
A quote spanning a tag either fails to resolve or resolves against text nobody wrote.

What this keeps, and why:

* **Title, abstract, body sections** with their headings, so a span can be attributed to the
  section it came from.
* **Tables**, rendered cell by cell. Titers, yields and strain genotypes are usually tabular; in
  a PDF they are a reconstruction problem, and here they are simply structured.
* **Figure and table captions**, which frequently carry the fermentation conditions.

What it drops: the reference list. A bibliography is full of title text that reads like findings,
and a model quoting a paper's own references would produce spans that verify perfectly while
saying something the authors never claimed.
"""

from __future__ import annotations

from xml.etree import ElementTree

__all__ = ["JatsError", "is_jats", "jats_to_text"]

#: Block elements whose text is emitted as one paragraph. Anything not listed is descended into.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "title",
        "article-title",
        "subtitle",
        "label",
        "caption",
        "attrib",
        "disp-quote",
        "speech",
        "statement",
        "verse-group",
        "def-item",
        "list-item",
        "td",
        "th",
    }
)

#: Dropped entirely, with their subtrees. `ref-list` is the important one (see module docstring);
#: the rest are apparatus that carries no claim.
_SKIP_TAGS = frozenset(
    {
        "ref-list",
        "ref",
        "back-matter",
        "journal-meta",
        "permissions",
        "funding-group",
        "contrib-group",
        "aff",
        "author-notes",
        "pub-date",
        "history",
        "kwd-group",
        "counts",
        "custom-meta-group",
        "processing-meta",
        "xref",
        "fn-group",
    }
)


class JatsError(ValueError):
    """The bytes are not JATS that can be read as an article."""


def _tag(element: ElementTree.Element) -> str:
    """The local name, with any namespace stripped."""
    return element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""


def is_jats(data: bytes) -> bool:
    """Whether `data` parses as XML whose root is a JATS `<article>`."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return False
    return _tag(root) == "article" or root.find(".//{*}article") is not None


#: Block-level things that publishers nest *inside* a `<p>`. JATS allows it and they use it:
#: an entire `<table-wrap>` commonly sits inside the paragraph that first cites the table.
#: These must be lifted out and rendered in their own right, never flattened into the sentence.
_FLOAT_TAGS = frozenset({"table-wrap", "fig", "fig-group", "boxed-text", "list", "def-list"})


def _text_of(element: ElementTree.Element) -> str:
    """The block's own text, with inline markup flattened and nested floats left out.

    `itertext()` is what makes `<italic>ILV5</italic>` read as `ILV5` rather than splitting the
    sentence -- inline formatting disappears and the words close up, which is the whole point.
    But it is indiscriminate: applied to a paragraph containing a table it inlines every cell,
    turning a strain/titer table into an unpaired run of numbers and handing the model exactly
    the re-pairing guesswork `_walk_table` exists to prevent. So floats are skipped here (and
    walked separately), while their `tail` -- the paragraph text that continues after them -- is
    kept, because that text is the paragraph's.

    Whitespace is collapsed to single spaces so the result matches what
    `fermdb.llm.validate.canonical_source_text` produces for a quote copied out of it.
    """
    parts: list[str] = [element.text or ""]
    for child in element:
        if _tag(child) not in _FLOAT_TAGS and _tag(child) not in _SKIP_TAGS:
            parts.append(_text_of(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def _floats_within(element: ElementTree.Element) -> list[ElementTree.Element]:
    """Nested floats, in document order, so they can be emitted after their paragraph."""
    found: list[ElementTree.Element] = []
    for child in element:
        if _tag(child) in _FLOAT_TAGS:
            found.append(child)
        elif _tag(child) not in _SKIP_TAGS:
            found.extend(_floats_within(child))
    return found


def _walk(element: ElementTree.Element, blocks: list[str]) -> None:
    tag = _tag(element)
    if tag in _SKIP_TAGS:
        return
    if tag == "table-wrap":
        _walk_table(element, blocks)
        return
    if tag in _BLOCK_TAGS:
        text = _text_of(element)
        if text:
            blocks.append(text)
        # The paragraph is emitted first, then whatever floated inside it -- reading order.
        for float_element in _floats_within(element):
            _walk(float_element, blocks)
        return
    for child in element:
        _walk(child, blocks)


def _walk_table(table_wrap: ElementTree.Element, blocks: list[str]) -> None:
    """A table as caption plus one line per row, cells joined by ' | '.

    Row-wise rather than cell-wise because a measurement is only meaningful beside its row label:
    "IV-1 | 1.62 | 0.31" keeps the strain with its titer, where a flat list of cells would leave
    the model to re-pair them and invite it to guess.
    """
    for part in ("label", "caption"):
        found = table_wrap.find(f".//{{*}}{part}")
        if found is not None:
            text = _text_of(found)
            if text:
                blocks.append(text)
    emitted = 0
    for row in table_wrap.iter():
        if _tag(row) != "tr":
            continue
        cells = [_text_of(cell) for cell in row if _tag(cell) in {"td", "th"}]
        line = " | ".join(cell for cell in cells if cell)
        if line:
            blocks.append(line)
            emitted += 1

    # Some publishers ship the table as a scanned image with no <table> markup at all. Saying so
    # matters: with only a caption in the text, a model asked whether the paper reports a titer
    # can reasonably answer "no" when the number is sitting in a JPEG. This makes the absence
    # legible to the extractor and to whoever curates the result.
    if emitted == 0 and table_wrap.find(".//{*}graphic") is not None:
        blocks.append("[table not machine-readable: published as an image]")


def jats_to_text(data: bytes) -> str:
    """Render JATS `data` as plain text: title, abstract, body, tables and captions.

    Blocks are separated by blank lines, which is what makes character offsets meaningful -- a
    span's offsets index into exactly this string, so whatever verifies here verifies later.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise JatsError(f"not parseable as XML: {exc}") from exc

    if _tag(root) != "article":
        nested = root.find(".//{*}article")
        if nested is None:
            raise JatsError(f"XML root <{_tag(root)}> is not a JATS article")
        root = nested

    blocks: list[str] = []
    title = root.find(".//{*}title-group/{*}article-title")
    if title is not None:
        text = _text_of(title)
        if text:
            blocks.append(text)
    # `floats-group` is the other convention: rather than nesting a table in the citing
    # paragraph, some publishers collect every float at the end of the article. Walking both
    # covers both, and a document using neither simply contributes nothing from the missing one.
    for section in (".//{*}abstract", ".//{*}body", ".//{*}floats-group"):
        found = root.find(section)
        if found is not None:
            _walk(found, blocks)

    if not blocks:
        raise JatsError("JATS article contained no title, abstract or body text")

    # Consecutive duplicates happen when a caption is also the table label; they add nothing and
    # would give a quote two equally valid offsets.
    deduped: list[str] = []
    for block in blocks:
        if not deduped or block != deduped[-1]:
            deduped.append(block)
    return "\n\n".join(deduped)
