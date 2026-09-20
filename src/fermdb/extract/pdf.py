"""Text out of a PDF, or a refusal that says why.

`pyproject.toml` has carried `pypdf>=4` with the comment *"text from the PDFs the owner supplies
via the manual download queue"* since the dependency list was written, and nothing imported it.
So a paper the owner supplied through that queue was stored and then unreadable — which is how
Atsumi 2008 and Avalos 2013 sat in the atlas as bytes while phase 1's acceptance criterion, *"the
landmark E. coli and S. cerevisiae builds each reproduce their paper's titer"*, named those two
papers and could not run.

`harness._decode_text` refused PDFs, and its reason was the right one:

    a PDF read as text produces plausible garbage, and a model will happily quote from it

That reasoning does not go away now that there is an extractor; it moves. **A PDF with no text
layer still produces plausible garbage**, and pypdf returns it without complaint — an empty
string for a clean scan, or a scatter of glyph noise for a bad one. So this module extracts and
then *checks*, and a document that fails the check is refused with the same force as before.

Two checks, both cheap and both catching a different failure:

* **Characters per page.** A scanned page yields almost nothing. A real article page yields
  hundreds. The threshold is deliberately low — some legitimate pages are mostly figure — and it
  is applied to the document, not per page, so a paper with plates does not trip it.
* **Alphabetic ratio.** Glyph-mapping failures produce text that is long enough to pass the first
  check and is mostly punctuation and control characters. Prose is overwhelmingly letters and
  spaces.

**Extraction must be deterministic**, because every span in this atlas is a character offset into
whatever this function returns. The same bytes must give the same string on every call, or a
quote verified today fails to resolve tomorrow for no reason anyone can see. Pages are joined
with a single form feed so page boundaries stay visible and stay stable, and nothing here
reflows, de-hyphenates or repairs ligatures: each of those would be a second, lossy normalisation
applied inconsistently to different papers, and the atlas would rather quote awkward text that
resolves than tidy text that does not.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "MIN_ALPHA_RATIO",
    "MIN_CHARS_PER_PAGE",
    "PAGE_SEPARATOR",
    "PdfError",
    "is_pdf",
    "pdf_to_text",
]

#: Joins pages. A form feed is the conventional page break and, unlike a blank line, cannot be
#: confused with a paragraph break already in the text.
PAGE_SEPARATOR: Final[str] = "\f"

#: Below this, the document has no usable text layer -- almost certainly a scan.
MIN_CHARS_PER_PAGE: Final[int] = 120

#: Below this, what came out is not prose. Letters and spaces dominate real text by a wide margin.
MIN_ALPHA_RATIO: Final[float] = 0.55


class PdfError(RuntimeError):
    """The PDF could not be read, or its text layer is absent or unusable."""


def is_pdf(data: bytes) -> bool:
    """Magic bytes, not the file extension or the Content-Type header."""
    return data[:5] == b"%PDF-"


def _alpha_ratio(text: str) -> float:
    """Share of non-space characters that are letters or digits."""
    meaningful = [c for c in text if not c.isspace()]
    if not meaningful:
        return 0.0
    return sum(1 for c in meaningful if c.isalnum()) / len(meaningful)


def pdf_to_text(data: bytes, *, source: str = "<pdf>") -> str:
    """Extract a PDF's text layer, or raise :class:`PdfError`.

    Args:
        data: The whole file.
        source: Named in any error, so a failure says which paper failed.

    Raises:
        PdfError: Not a PDF, unparseable, encrypted, or carrying no usable text layer.
    """
    if not is_pdf(data):
        raise PdfError(f"{source}: not a PDF (magic bytes are {data[:5]!r})")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise PdfError(
            f"{source}: pypdf is not installed, though pyproject declares it for exactly this"
        ) from exc

    import io

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise PdfError(f"{source}: pypdf could not open this file ({exc})") from exc

    if getattr(reader, "is_encrypted", False):
        # Some publisher PDFs carry an empty owner password; pypdf can open those.
        try:
            reader.decrypt("")
        except Exception as exc:
            raise PdfError(f"{source}: the PDF is encrypted and could not be opened") from exc

    pages: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:
            raise PdfError(f"{source}: page {index + 1} could not be extracted ({exc})") from exc

    if not pages:
        raise PdfError(f"{source}: the PDF has no pages")

    text = PAGE_SEPARATOR.join(pages)
    stripped = text.strip()

    per_page = len(stripped) / len(pages)
    if per_page < MIN_CHARS_PER_PAGE:
        raise PdfError(
            f"{source}: {len(stripped)} characters across {len(pages)} page(s) "
            f"({per_page:.0f} per page) is below {MIN_CHARS_PER_PAGE}. This PDF has no usable "
            f"text layer -- almost certainly a scan. It needs OCR, and quoting from what pypdf "
            f"returned would be quoting from nothing."
        )

    ratio = _alpha_ratio(stripped)
    if ratio < MIN_ALPHA_RATIO:
        raise PdfError(
            f"{source}: only {ratio:.0%} of the extracted characters are letters or digits, "
            f"below {MIN_ALPHA_RATIO:.0%}. The text layer decoded to symbol noise rather than "
            f"prose, which is what a broken glyph mapping produces -- and it is long enough to "
            f"look like a successful extraction."
        )
    return text
