"""One publication in, one Zone I ``extraction`` row out.

PLAN.md H.5 and V.4 between them describe this module completely:

* **H.5** — per publication, emit schema-constrained JSON into Zone I, with a verbatim quote and
  character offsets for *every* extracted value, `review_state='proposed'`, and a deterministic
  validator that re-reads the source at those offsets.
* **V.4** — extraction cost is the budget line that dominates the whole project, and the way it is
  controlled is not a cheaper model but a smaller prompt: send the methods and results sections
  only, not the whole paper. PLAN.md's own arithmetic makes that roughly thirteen times cheaper
  across the corpus. :func:`split_sections` and :func:`build_excerpt` are that saving.

Sending an excerpt rather than the paper creates the one genuinely tricky problem in this file.
The model reports offsets into the text it was shown, but a span is only useful if it points into
the document. So every span is verified **twice**: once against the excerpt at the offsets the
model gave (:func:`fermdb.llm.validate.verify_span`, exact, no normalization), and again against
the whole document after :meth:`Excerpt.to_document` translates them. A quote that survives only
the first check — because it straddles the boundary between two stitched-together sections, say —
is rejected. Only document offsets are ever stored, because an offset into a temporary excerpt is
an offset into something nobody can reconstruct.

Three things this module deliberately does not do:

* **It does not write Zone R or Zone H.** If there is no ``publication`` row for the paper it
  refuses, rather than creating one: a publication record is Zone R and PLAN.md L.5 forbids an
  agent from writing there. Run literature discovery first.
* **It does not promote anything.** Everything it writes is ``review_state='proposed'``, and the
  ``extraction`` table's CHECK constraints make any other state require a named curator.
* **It does not store a partial payload.** If any record fails validation, the run fails — after
  one retry with the validator's complaints fed back to the model (see
  :func:`fermdb.llm.runtime.run`). Storing the records that happened to pass would put
  half-validated output in the same table, in the same shape, as validated output.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Final

from ..config import Settings
from ..literature.discovery import canonical_publication_id, normalize_publication_id
from ..llm import (
    LlmConfig,
    Provider,
    ResultCache,
    RunStats,
    Span,
    load_theoretical_yields,
    load_units,
    relocate_span,
    resolver_from_ids,
    run,
    validate_records,
    verify_span,
)
from ..llm.validate import EntityResolver, TheoreticalYields, UnitTable
from .jats import JatsError, is_jats, jats_to_text
from .pdf import PdfError, is_pdf, pdf_to_text
from .schemas import (
    RECORD_KINDS,
    iter_payload_records,
    load_vocabulary,
    payload_schema,
    record_path,
)

__all__ = [
    "DEFAULT_EXTRACTION_SECTIONS",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "SECTION_NAMES",
    "TRIAGE_SCHEMA",
    "UNSECTIONED",
    "Excerpt",
    "ExcerptPiece",
    "ExtractionError",
    "ExtractionOutcome",
    "NotPrimaryResearchError",
    "PromptError",
    "PromptFile",
    "RecordNote",
    "Section",
    "SectioningError",
    "SourceTextError",
    "TriageVerdict",
    "build_excerpt",
    "extract_publication",
    "find_publication",
    "load_prompt",
    "load_source_text",
    "looks_like_review",
    "split_sections",
    "triage_publication",
    "write_extraction",
]

JsonObject = dict[str, Any]
JsonSchema = dict[str, Any]

#: Who wrote the row, recorded on every extraction.
EXTRACTOR: Final[str] = "fermdb.extract.harness"

#: Bumped when this module changes what an extraction row *means* — the section selection, the
#: span translation, the validation gate. Not a release number: it is the answer to "would this
#: code produce the same row from the same paper?", which a curator reviewing an old row needs.
#:
#: ``"2"``: a structured abstract's sub-headings no longer become sections of the paper
#: (:func:`_fold_structured_abstract`). A version-1 row for a paper with a structured abstract was
#: extracted from an excerpt whose first ``results`` piece was the abstract, and its spans may be
#: labelled ``results`` while sitting in it; a version-2 row cannot be.
EXTRACTOR_VERSION: Final[str] = "2"


# ---------------------------------------------------------------------------------- exceptions


class ExtractionError(RuntimeError):
    """Extraction could not be completed. The base for everything this module raises."""


class SectioningError(ExtractionError):
    """The document could not be split into the sections extraction needs."""


class NotPrimaryResearchError(SectioningError):
    """The document is a review or commentary, so its numbers are other papers' numbers.

    Separated from a plain :class:`SectioningError` because the remedy is opposite. A document
    whose headings were lost should be re-read or sent whole; a review must not be, however it is
    sectioned -- extracting from one attributes a cited result to the authors reviewing it.
    """


class SourceTextError(ExtractionError):
    """There is no readable full text for this publication."""


class PromptError(ExtractionError):
    """A prompt file is missing, malformed, or was rendered with the wrong placeholders."""


# ------------------------------------------------------------------------------------ sections

#: Normalized section names. ``front_matter`` is whatever precedes the first recognized heading —
#: usually a title block and author list — and ``other`` is a heading that was recognized as a
#: heading but not as one of these.
SECTION_NAMES: Final[tuple[str, ...]] = (
    "front_matter",
    "abstract",
    "introduction",
    "methods",
    "results",
    "results_and_discussion",
    "discussion",
    "conclusion",
    "acknowledgements",
    "references",
    "supplementary",
    "other",
)

#: The name given to a document with no recognizable headings at all. Not in
#: :data:`DEFAULT_EXTRACTION_SECTIONS`, so such a document fails loudly by default rather than
#: quietly costing whole-paper tokens; an operator who wants that pays for it on purpose.
UNSECTIONED: Final[str] = "unsectioned"

#: What the model is shown. PLAN.md V.4's staged filter, spelled as a constant so the cost
#: decision is visible and changeable in one place.
DEFAULT_EXTRACTION_SECTIONS: Final[tuple[str, ...]] = (
    "methods",
    "results",
    "results_and_discussion",
)

# Order matters: 'results and discussion' is tried before 'results' and before 'discussion',
# because a combined section matched as either of its halves would silently drop the other half.
_HEADING_KEYWORDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("results_and_discussion", re.compile(r"^results?\s+and\s+discussions?$")),
    ("methods", re.compile(r"^(?:materials?\s+and\s+)?methods?$")),
    ("methods", re.compile(r"^methods?\s+and\s+materials?$")),
    ("methods", re.compile(r"^experimental(?:\s+(?:procedures?|section|methods?|details?))?$")),
    ("results", re.compile(r"^results?$")),
    ("discussion", re.compile(r"^discussions?$")),
    ("abstract", re.compile(r"^(?:abstract|summary)$")),
    ("introduction", re.compile(r"^(?:introduction|background)$")),
    ("conclusion", re.compile(r"^(?:conclusions?|concluding\s+remarks)$")),
    ("acknowledgements", re.compile(r"^acknowledge?ments?$")),
    ("references", re.compile(r"^(?:references?|bibliography|literature\s+cited)$")),
    ("supplementary", re.compile(r"^supplement(?:ary|al)(?:\s+\w+)*$")),
)

# A heading is a whole line, optionally numbered ('2.1 Methods'), optionally a markdown heading
# ('## Methods'), optionally emphasized ('**Methods**'), optionally followed by a colon. Short,
# because a paragraph that happens to begin with the word Results is not a heading.
_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(?:\#{1,6}[ \t]*)?(?:\d+(?:\.\d+)*[.)]?[ \t]*)?"
    r"\*{0,2}([A-Za-z][^\n]{0,60}?)\*{0,2}[ \t]*:?[ \t]*$",
    re.MULTILINE,
)

_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

#: The names a structured abstract's own sub-headings can carry. BMC, Frontiers, PeerJ, MDPI and
#: the rest of the house styles all spell an abstract as ``Background`` / ``Methods`` / ``Results``
#: / ``Conclusions``, which :data:`_HEADING_KEYWORDS` matches exactly as it matches the body's.
#: Anything outside this set — ``references``, ``supplementary``, ``acknowledgements`` — ends the
#: run, because no abstract contains one.
_ABSTRACT_PART_NAMES: Final[frozenset[str]] = frozenset(
    {
        "abstract",
        "introduction",
        "methods",
        "results",
        "results_and_discussion",
        "discussion",
        "conclusion",
    }
)

#: The names a *body* can open with. The abstract is confirmed only when the run's **first** such
#: name re-opens further down: that second ``Background`` is the paper itself starting from the
#: top, and it is the only positive evidence that what came first was a summary of the paper
#: rather than the paper.
#:
#: Insisting on the *first* one, rather than on any of them, is what tells a structured abstract
#: apart from a body that merely announces ``Methods`` twice — Elsevier and MDPI both do that, and
#: such a body re-opens ``methods`` but never re-opens its ``Introduction``. Over the 1,429 stored
#: full texts the two readings differ by exactly the 13 double-``Methods`` bodies, all of which
#: the strict one correctly declines to fold, and by no structured abstract at all.
_BODY_OPENING_NAMES: Final[frozenset[str]] = frozenset(
    {"introduction", "methods", "results", "results_and_discussion"}
)

#: How long one sub-heading of a structured abstract may be, and how long the whole of it may be.
#:
#: **A second guard, deliberately independent of the first.** The re-opening test above is
#: structural and the length test is dimensional, and they agree: over the 1,429 stored full texts
#: each one *on its own* selects exactly the same 293 runs. Neither is load-bearing alone, which
#: is the point — a paper that defeated one would have to defeat the other too, and the failure
#: this guards against is silent (a folded body loses its real Results from the excerpt).
#:
#: **Where the numbers come from.** Across those 293 runs the longest single part is 1,495
#: characters and the longest whole run 3,890. The shortest body section that must be *rejected*
#: is 2,204 (a body Introduction), and the double-``Methods`` bodies start at 3,797. So 2,000 sits
#: in the gap with room on both sides, and 6,000 is slack over an observed 3,890. A run that
#: overruns is cut at that point rather than abandoned, because the overrun *is* the body
#: beginning: in all eight corpus cases the part that broke the cap was the body's own
#: Introduction, and every abstract sub-heading was already inside the run.
_ABSTRACT_PART_MAX_CHARS: Final[int] = 2000
_ABSTRACT_MAX_CHARS: Final[int] = 6000

#: How a section is announced inside the excerpt. The model is told these count toward its
#: offsets and that a quote must not cross one; :meth:`Excerpt.to_document` enforces the second
#: half by refusing to translate a span that is not wholly inside one piece.
_MARKER_TEMPLATE: Final[str] = "[[section: {name}]]"
_PIECE_SEPARATOR: Final[str] = "\n\n"


@dataclass(frozen=True)
class Section:
    """One contiguous stretch of the document, 0-based half-open ``[char_start, char_end)``."""

    name: str
    char_start: int
    char_end: int
    heading_as_reported: str | None = None

    @property
    def length(self) -> int:
        """``char_end - char_start``. Never plus one (CONVENTIONS.md, "Coordinates")."""
        return self.char_end - self.char_start

    def text_of(self, document: str) -> str:
        """This section's own text, cut out of the document."""
        return document[self.char_start : self.char_end]


def _normalize_heading(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().strip(".").lower()


def _heading_name(text: str) -> str | None:
    normalized = _normalize_heading(text)
    if not normalized:
        return None
    for name, pattern in _HEADING_KEYWORDS:
        if pattern.match(normalized):
            return name
    return None


def _structured_abstract_run(sections: Sequence[Section]) -> tuple[int, int] | None:
    """The half-open index range of a leading structured abstract, or None if there is not one.

    A structured abstract is a run of sections at the very top of the document — after
    ``front_matter``, if there is one — that is short, whose names are abstract-plausible and
    distinct, and whose first body-opening name re-opens further down. That last clause is the
    whole test: the second ``Background`` is the paper starting from the top, so everything before
    it was a summary of the paper rather than part of it.

    Nothing here looks for the word "abstract", because in 85 of the 209 affected papers there is
    no ``Abstract`` heading to find — ``jats_to_text`` emits the sub-headings bare, straight after
    the title block, and the run begins at ``Background``.
    """
    start = 1 if sections and sections[0].name == "front_matter" else 0
    seen: list[str] = []
    stop = start
    total = 0
    for section in sections[start:]:
        if section.name not in _ABSTRACT_PART_NAMES or section.name in seen:
            break
        if section.length > _ABSTRACT_PART_MAX_CHARS:
            break
        if total + section.length > _ABSTRACT_MAX_CHARS:
            break
        seen.append(section.name)
        total += section.length
        stop += 1
    if stop == start:
        return None
    # Only a name the body could open with counts as confirmation, and only the first of them. A
    # run of nothing but `abstract` — an ordinary unstructured abstract — has no such name at all
    # and is left alone, which is why a normal paper passes through this function untouched.
    openers = [name for name in seen if name in _BODY_OPENING_NAMES]
    if not openers:
        return None
    if not any(section.name == openers[0] for section in sections[stop:]):
        return None
    return start, stop


def _fold_structured_abstract(sections: tuple[Section, ...]) -> tuple[Section, ...]:
    """Collapse a structured abstract's sub-headings into the one ``abstract`` section they are.

    The sub-headings of a structured abstract are not the paper's sections. ``Results`` inside a
    BMC abstract announces four sentences summarizing the Results section; it is not the Results
    section, and it is the single worst passage in the paper to hand an extractor, because the
    abstract is exactly where several strains get compressed into one subject-less clause —
    *"the integration of PDH suppression by lpd1Δ ... in BSW205 and BSW206 strains"*. Fed to the
    model under the label ``results``, that produced three Zone R rows attributing an abstract
    claim to a strain the sentence never named (docs/drafts/corrections/ZONE_R_CORRECTIONS.md).

    The collapse happens here, in the sectioner, rather than in :func:`build_excerpt`, and the
    difference is not cosmetic. ``build_excerpt`` could have been taught to take only the first or
    the largest ``results``, and the excerpt would then have been right while ``span.section``
    went on saying ``results`` for a sentence in the abstract — which is the half that made this
    invisible for three rows and one bulk accept. A span's section is read off the section it
    lands in, so the only place that can stop a span being *labelled* ``results`` in the abstract
    is the place that decides what is named ``results``.

    Tiling is preserved: the run becomes one section spanning exactly the characters its parts
    spanned, keeping the heading that opened it.
    """
    span = _structured_abstract_run(sections)
    if span is None:
        return sections
    start, stop = span
    folded = Section(
        "abstract",
        sections[start].char_start,
        sections[stop - 1].char_end,
        sections[start].heading_as_reported,
    )
    return (*sections[:start], folded, *sections[stop:])


def split_sections(document: str) -> tuple[Section, ...]:
    """Split a paper's plain text into named, contiguous, non-overlapping sections.

    The returned sections tile the document exactly: the first starts at 0, the last ends at
    ``len(document)``, and each begins at its own heading line. That is what makes an offset
    translatable in both directions later, and it is why the heading line belongs to the section
    it announces rather than to the one before it.

    A document with no recognizable heading comes back as a single :data:`UNSECTIONED` section
    rather than as an error: deciding what to do about that is :func:`build_excerpt`'s job, and it
    has the caller's wanted-section list to decide with.

    A leading *structured* abstract — the ``Background`` / ``Results`` / ``Conclusions``
    sub-headings BMC and its imitators print inside the abstract — is collapsed into a single
    ``abstract`` section by :func:`_fold_structured_abstract`, so that the paper's Results is the
    only thing named ``results``. Headings further down are never touched: a body whose Methods
    really is announced twice keeps both halves, and both are still sent.
    """
    boundaries: list[tuple[int, str, str]] = []
    for match in _HEADING_RE.finditer(document):
        name = _heading_name(match.group(1))
        if name is None:
            continue
        boundaries.append((match.start(), name, match.group(1).strip()))

    if not boundaries:
        return (Section(UNSECTIONED, 0, len(document)),)

    sections: list[Section] = []
    if boundaries[0][0] > 0:
        sections.append(Section("front_matter", 0, boundaries[0][0]))
    for index, (start, name, heading) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(document)
        sections.append(Section(name, start, end, heading))
    return _fold_structured_abstract(tuple(sections))


@dataclass(frozen=True)
class ExcerptPiece:
    """One document section as it appears in the excerpt, with both coordinate systems."""

    name: str
    doc_start: int
    doc_end: int
    exc_start: int
    exc_end: int


@dataclass(frozen=True)
class Excerpt:
    """The text actually sent to the model, plus the map back to the document.

    ``text`` is what the model sees and what its offsets refer to; ``pieces`` is how those offsets
    become document offsets. Nothing outside this class should do that arithmetic.
    """

    text: str
    pieces: tuple[ExcerptPiece, ...]
    document_chars: int

    @property
    def section_names(self) -> tuple[str, ...]:
        """The sections included, in document order, with repeats kept."""
        return tuple(piece.name for piece in self.pieces)

    @property
    def chars(self) -> int:
        """Characters actually sent, markers included."""
        return len(self.text)

    @property
    def fraction_of_document(self) -> float:
        """Sent characters over document characters — PLAN.md V.4's saving, measured per paper."""
        if self.document_chars <= 0:
            return 0.0
        return self.chars / self.document_chars

    def to_document(self, char_start: int, char_end: int) -> tuple[int, int] | None:
        """Translate excerpt offsets into document offsets, or None if they do not translate.

        None means the span is not wholly inside one included section: it runs across a section
        marker, or past the end of a piece into the next. Returning None rather than clamping is
        the point — a clamped span would resolve to *some* text, which is exactly the outcome the
        span check exists to prevent.
        """
        if char_end <= char_start:
            return None
        for piece in self.pieces:
            if piece.exc_start <= char_start and char_end <= piece.exc_end:
                offset = piece.doc_start - piece.exc_start
                return char_start + offset, char_end + offset
        return None

    def section_at(self, char_start: int) -> str | None:
        """Which section an excerpt offset falls in, or None if it falls on a marker."""
        for piece in self.pieces:
            if piece.exc_start <= char_start < piece.exc_end:
                return piece.name
        return None

    def split(self, max_chars: int, *, overlap: int = 2000) -> tuple[Excerpt, ...]:
        """Cut this excerpt into windows small enough to send, each a valid ``Excerpt``.

        Measured on a real paper (MODEL_ROUTING.md 7c), one article's methods and results come to
        60,000 characters — about 20,000 tokens with the schema. A 27B model on one GPU answers
        that in four minutes, or returns nothing at all; across the stored corpus that is days of
        compute for an unreliable result. The excerpt, not the context window, is the limit.

        Each window is returned as a full ``Excerpt`` with its pieces clipped and rebased, so
        every caller — and :meth:`to_document` above all — works on a window exactly as it works
        on the whole. Offsets that come back from a window are therefore already *document*
        offsets: there is no second coordinate system to get wrong, which is the only reason
        chunking is safe to do at all.

        Windows overlap by ``overlap`` characters so that a sentence carrying a measurement is not
        lost to a boundary. That makes duplicate records possible, and they are easy to remove
        precisely because both copies translate to the same document span.

        Cuts prefer a paragraph boundary within the last quarter of the window; ``jats_to_text``
        separates blocks with a blank line, so in practice that is a clean break between
        paragraphs or table rows rather than mid-sentence.
        """
        if max_chars <= 0:
            raise ValueError(f"max_chars must be positive, got {max_chars}")
        if overlap < 0 or overlap >= max_chars:
            raise ValueError(f"overlap must be in [0, max_chars), got {overlap}")
        if len(self.text) <= max_chars:
            return (self,)

        windows: list[Excerpt] = []
        start = 0
        while start < len(self.text):
            end = min(start + max_chars, len(self.text))
            if end < len(self.text):
                # Prefer a paragraph break, but only a late one -- an early break would make the
                # window far smaller than asked for and multiply the number of calls.
                floor = start + (max_chars * 3) // 4
                paragraph = self.text.rfind("\n\n", floor, end)
                if paragraph > start:
                    end = paragraph
            windows.append(self._window(start, end))
            if end >= len(self.text):
                break
            start = max(end - overlap, start + 1)
        return tuple(windows)

    def _window(self, start: int, end: int) -> Excerpt:
        """One window as an Excerpt: pieces clipped to ``[start, end)`` and rebased onto it."""
        clipped: list[ExcerptPiece] = []
        for piece in self.pieces:
            exc_start = max(piece.exc_start, start)
            exc_end = min(piece.exc_end, end)
            if exc_start >= exc_end:
                continue
            # A piece maps excerpt to document by a constant shift, so clipping one end of the
            # excerpt range shifts the same end of the document range by the same amount.
            lead = exc_start - piece.exc_start
            clipped.append(
                ExcerptPiece(
                    name=piece.name,
                    doc_start=piece.doc_start + lead,
                    doc_end=piece.doc_start + lead + (exc_end - exc_start),
                    exc_start=exc_start - start,
                    exc_end=exc_end - start,
                )
            )
        return Excerpt(
            text=self.text[start:end],
            pieces=tuple(clipped),
            document_chars=self.document_chars,
        )


#: What a primary research report has and a review does not. The discriminator is structural, so
#: it costs nothing and cannot be talked out of its answer by a persuasive abstract.
_PRIMARY_RESEARCH_SECTIONS: Final[frozenset[str]] = frozenset(
    {"methods", "results", "results_and_discussion"}
)

#: A review still has these, which is how "a review" is told apart from "a fragment".
_NARRATIVE_SECTIONS: Final[frozenset[str]] = frozenset(
    {"abstract", "introduction", "conclusion", "discussion"}
)


def looks_like_review(sections: Sequence[Section]) -> bool:
    """Whether this document reads as a review or commentary rather than a research report.

    True when it has narrative sections but no methods and no results. Measured over the acquired
    open-access corpus, 21 of 279 articles (7.5%) are this shape -- Frontiers, MDPI and Biotech
    reviews of isobutanol production, which the discovery queries match on topic exactly as well
    as primary papers do.
    """
    names = {section.name for section in sections}
    return not (names & _PRIMARY_RESEARCH_SECTIONS) and bool(names & _NARRATIVE_SECTIONS)


def build_excerpt(document: str, sections: Sequence[Section], wanted: Sequence[str]) -> Excerpt:
    """Stitch the wanted sections into the text the model will be shown.

    Each piece is announced by a ``[[section: name]]`` marker so the model knows what it is
    reading. The markers are not part of any piece's coordinate range, so a quote that includes
    one cannot be translated back and is rejected — which is the behaviour we want, because such
    a quote does not occur in the paper.
    """
    chosen = [section for section in sections if section.name in wanted]
    if not chosen:
        found = sorted({section.name for section in sections})
        if looks_like_review(sections):
            raise NotPrimaryResearchError(
                f"this document has no methods and no results ({found}): it is a review, "
                f"commentary or perspective, not a research report. Refusing to extract "
                f"measurements from it, and deliberately not offering '{UNSECTIONED}' as a way "
                f"round -- every number in a review belongs to a paper it cites, so extracting "
                f"here would attribute someone else's titer to these authors and produce a span "
                f"that verifies perfectly while asserting something false. fermdb takes those "
                f"measurements from the cited papers, which discovery finds on their own terms. "
                f"A review is still worth reading for its route claims; that is a different "
                f"record kind, not this one."
            )
        raise SectioningError(
            f"none of the wanted sections {list(wanted)} are in this document; it has {found}. "
            f"Either the full text is a fragment, or the text conversion lost the headings. "
            f"Pass --sections with a name that is actually present (or "
            f"'{UNSECTIONED}' to send the whole text and pay for it) rather than extracting "
            f"from a paper whose methods and results were never found."
        )

    parts: list[str] = []
    pieces: list[ExcerptPiece] = []
    cursor = 0
    for section in chosen:
        if parts:
            parts.append(_PIECE_SEPARATOR)
            cursor += len(_PIECE_SEPARATOR)
        marker = _MARKER_TEMPLATE.format(name=section.name) + "\n"
        parts.append(marker)
        cursor += len(marker)
        body = section.text_of(document)
        pieces.append(
            ExcerptPiece(
                name=section.name,
                doc_start=section.char_start,
                doc_end=section.char_end,
                exc_start=cursor,
                exc_end=cursor + len(body),
            )
        )
        parts.append(body)
        cursor += len(body)

    return Excerpt(text="".join(parts), pieces=tuple(pieces), document_chars=len(document))


# ------------------------------------------------------------------------------------- prompts

_PROMPT_PACKAGE: Final[str] = "fermdb.extract"
_PROMPT_DIRNAME: Final[str] = "prompts"
_PROMPT_SUFFIX: Final[str] = ".md"
_FRONT_MATTER_DELIMITER: Final[str] = "---"
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")


@dataclass(frozen=True)
class PromptFile:
    """A versioned prompt read off disk. Never an inline string.

    PLAN.md L.3: prompts are versioned files and ``prompt_version`` is stored with every output,
    because an extraction is not reproducible without the prompt that produced it. :attr:`version`
    therefore carries both the *declared* version from the file's front matter and a digest of the
    file's bytes — a prompt edited without bumping its declared version is a different prompt, and
    would otherwise reuse the old version string over new text and hit the old cache entries.
    """

    name: str
    declared_version: str
    role: str
    template: str
    sha256: str
    origin: str

    @property
    def version(self) -> str:
        """``'extraction/v1+3f2a...'`` — what is stored in ``extraction.prompt_version``."""
        return f"{self.name}/{self.declared_version}+{self.sha256[:12]}"

    @property
    def placeholders(self) -> frozenset[str]:
        """Every ``{{name}}`` the template expects."""
        return frozenset(_PLACEHOLDER_RE.findall(self.template))

    def render(self, values: Mapping[str, str]) -> str:
        """Substitute every ``{{name}}``, refusing a mismatch in either direction.

        A missing value would send the model a literal ``{{excerpt}}``; an extra one usually means
        a renamed placeholder that is now being silently ignored. Both are worth a loud failure,
        because the resulting prompt would still *look* fine in a log.
        """
        expected = self.placeholders
        supplied = frozenset(values)
        if expected != supplied:
            missing = sorted(expected - supplied)
            unexpected = sorted(supplied - expected)
            raise PromptError(
                f"{self.origin}: placeholder mismatch (missing={missing}, unexpected={unexpected})"
            )
        return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], self.template)


def _parse_front_matter(text: str, origin: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise PromptError(
            f"{origin}: a prompt file must open with a '---' front-matter block declaring at "
            f"least 'name' and 'version'; an unversioned prompt produces an unreproducible "
            f"extraction (PLAN.md L.3)"
        )
    header: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONT_MATTER_DELIMITER:
            return header, "\n".join(lines[index + 1 :]).lstrip("\n")
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise PromptError(f"{origin}: front-matter line {line!r} is not 'key: value'")
        header[key.strip().lower()] = value.strip()
    raise PromptError(f"{origin}: front-matter block is never closed with '---'")


def load_prompt(name: str, *, directory: Path | None = None) -> PromptFile:
    """Load a versioned prompt by name.

    ``directory`` overrides the packaged ``prompts/`` folder — for tests, and for a curator
    trialling a revised prompt without editing the installed package. The override is reflected in
    :attr:`PromptFile.origin` and, through the content digest, in the stored ``prompt_version``, so
    a row produced by a trial prompt can never be mistaken for one produced by the shipped prompt.
    """
    if directory is not None:
        path = directory / f"{name}{_PROMPT_SUFFIX}"
        if not path.is_file():
            raise PromptError(f"no prompt file at {path}")
        raw = path.read_text(encoding="utf-8")
        origin = str(path)
    else:
        resource = (
            resources.files(_PROMPT_PACKAGE)
            .joinpath(_PROMPT_DIRNAME)
            .joinpath(f"{name}{_PROMPT_SUFFIX}")
        )
        if not resource.is_file():
            raise PromptError(
                f"no packaged prompt named {name!r} in {_PROMPT_PACKAGE}/{_PROMPT_DIRNAME}"
            )
        raw = resource.read_text(encoding="utf-8")
        origin = f"{_PROMPT_PACKAGE}/{_PROMPT_DIRNAME}/{name}{_PROMPT_SUFFIX}"

    header, template = _parse_front_matter(raw, origin)
    declared_name = header.get("name", name)
    version = header.get("version")
    if not version:
        raise PromptError(f"{origin}: front matter has no 'version'")
    if declared_name != name:
        raise PromptError(
            f"{origin}: front matter declares name {declared_name!r} but the file is {name!r}; "
            f"the two must agree or a stored prompt_version names the wrong file"
        )
    if not template.strip():
        raise PromptError(f"{origin}: the prompt body is empty")
    return PromptFile(
        name=name,
        declared_version=version,
        role=header.get("role", "extraction"),
        template=template,
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        origin=origin,
    )


# ---------------------------------------------------------------------------------- validation


@dataclass(frozen=True)
class RecordNote:
    """A non-fatal finding about one proposed record, kept for the curator who reviews it."""

    record_path: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """The stored form, inside ``extraction.validation``."""
        return {"record_path": self.record_path, "code": self.code, "message": self.message}


def _translate_span(
    record: JsonObject, *, path: str, document: str, excerpt: Excerpt
) -> tuple[JsonObject | None, str | None]:
    """Move a validated span from excerpt coordinates into document coordinates.

    The span has already been verified against the excerpt by
    :func:`fermdb.llm.validate.validate_records`. This re-verifies it against the document, which
    is not redundant: the translation is arithmetic, and arithmetic that is wrong produces offsets
    that look perfectly plausible.
    """
    raw = record.get("span")
    if not isinstance(raw, Mapping):
        return None, f"{path}: accepted record has no span object after validation"
    quote = raw.get("quote")
    start = raw.get("char_start")
    end = raw.get("char_end")
    if not isinstance(quote, str) or not isinstance(start, int) or not isinstance(end, int):
        return None, f"{path}: span is malformed after validation: {dict(raw)!r}"

    mapped = excerpt.to_document(start, end)
    if mapped is None:
        return None, (
            f"{path}: the span [{start}, {end}) is not wholly inside one of the sections you "
            f"were given — it runs across a [[section: ...]] marker. Quote from inside a single "
            f"section."
        )
    doc_start, doc_end = mapped
    span = Span(
        quote=quote,
        char_start=doc_start,
        char_end=doc_end,
        section=excerpt.section_at(start),
    )
    verdict = verify_span(document, span)
    if not verdict.ok:
        return None, (
            f"{path}: the span verified against the excerpt but not against the document "
            f"({verdict.reason}): {verdict.detail}"
        )
    checked = dict(record)
    checked["span"] = span.as_dict()
    return checked, None


def _normalized_payload(
    raw: Mapping[str, Any], accepted: Sequence[tuple[str, int, JsonObject]]
) -> JsonObject:
    """The payload as it is stored: validated records, document offsets, forced provenance.

    Not the model's raw reply. What is stored has been through
    :func:`fermdb.llm.validate.validate_records` — ``confidence='unverified'``, ``zone='I'``,
    ``review_state='proposed'`` forced onto every record whatever the model claimed — and has had
    its spans translated from excerpt coordinates into document coordinates. Storing the raw reply
    instead would put excerpt offsets in the database, and an excerpt is not something a curator
    opening the row a year later can reconstruct.

    The raw reply is not lost: ``extraction.input_hash`` plus the model and prompt version is the
    cache key it is stored under (PLAN.md L.3), so a run with the cache enabled can produce it
    again byte for byte.

    Validation is all-or-nothing, so a record's position here is the same as its position in the
    reply, which is what makes ``record_path`` mean the same thing on the span row, the curation
    task and the stored payload.
    """
    payload: JsonObject = {kind: [] for kind in RECORD_KINDS}
    for kind, _, record in accepted:
        payload[kind].append(record)
    confidence = raw.get("self_confidence")
    if isinstance(confidence, str):
        payload["self_confidence"] = confidence
    return payload


def _repair_spans(
    records: Sequence[JsonObject], source_text: str
) -> tuple[list[JsonObject], list[str | None]]:
    """Move each record's span onto the place its quote really occurs, before validation.

    Models cannot count characters. Measured on a real paper with a 7B local model, all 22
    records came back with verbatim, genuinely-present quotes and offsets wrong by a few
    characters; `verify_span` rejected every one while its own message read "the quote does occur
    at [2912]". The extraction was right and only the arithmetic was wrong.

    So the offsets are recomputed from the text rather than taken from the model. This is not a
    relaxation: a quote that does not occur in the source is still rejected, by the same exact
    check as before, and that is the check which stops a fabricated measurement. Repairs are
    returned alongside so each one is recorded as a note against the record -- a curator can see
    that a position was computed, not reported.

    Returns ``(records to validate, one note-or-None per record, in order)``.
    """
    out: list[JsonObject] = []
    notes: list[str | None] = []
    for record in records:
        raw = record.get("span")
        if not isinstance(raw, Mapping):
            out.append(dict(record))
            notes.append(None)
            continue
        quote, start, end = raw.get("quote"), raw.get("char_start"), raw.get("char_end")
        if not isinstance(quote, str) or not isinstance(start, int) or not isinstance(end, int):
            out.append(dict(record))
            notes.append(None)
            continue
        if source_text[start:end] == quote:
            out.append(dict(record))
            notes.append(None)
            continue
        moved = relocate_span(source_text, Span(quote=quote, char_start=start, char_end=end))
        if moved is None:
            # The quote is not in the source at all. Leave it exactly as the model gave it so
            # `verify_span` reports 'quote_absent_from_source' -- the hallucination signal, which
            # must not be softened into a repair failure.
            out.append(dict(record))
            notes.append(None)
            continue
        span, note = moved
        updated = dict(record)
        updated["span"] = {**dict(raw), **span.as_dict()}
        out.append(updated)
        notes.append(note)
    return out, notes


def _validate_payload(
    payload: Mapping[str, Any],
    *,
    document: str,
    excerpt: Excerpt,
    units: UnitTable,
    yields: TheoreticalYields,
    resolve_entity: EntityResolver | None,
) -> tuple[list[str], list[RecordNote], list[tuple[str, int, JsonObject]]]:
    """Run every deterministic check over a whole payload.

    Returns ``(fatal errors, non-fatal notes, accepted records)``. The errors are what gets fed
    back to the model on a retry, so they are phrased as instructions to it rather than as a log
    line: "quote from inside a single section", not "span translation failed".
    """
    flattened = iter_payload_records(payload)
    repaired, repairs = _repair_spans([record for _, _, record in flattened], excerpt.text)
    report = validate_records(
        repaired,
        source_text=excerpt.text,
        units=units,
        yields=yields,
        resolve_entity=resolve_entity,
        require_span=True,
    )
    errors: list[str] = []
    notes: list[RecordNote] = []
    accepted: list[tuple[str, int, JsonObject]] = []

    for position, ((kind, index, _), verdict) in enumerate(
        zip(flattened, report.verdicts, strict=True)
    ):
        path = record_path(kind, index)
        if repairs[position] is not None:
            notes.append(RecordNote(path, "span_offsets_repaired", str(repairs[position])))
        for issue in verdict.issues:
            if issue.fatal:
                errors.append(f"{path}: {issue.message}")
            else:
                notes.append(RecordNote(path, issue.code, issue.message))
        if not verdict.accepted or verdict.record is None:
            continue
        translated, failure = _translate_span(
            verdict.record, path=path, document=document, excerpt=excerpt
        )
        if translated is None:
            errors.append(failure or f"{path}: the span could not be placed in the document")
            continue
        accepted.append((kind, index, translated))

    return errors, notes, accepted


#: Ordered least to most confident, so a merge can take the lowest without inventing a scale.
_CONFIDENCE_ORDER: Final[tuple[str, ...]] = ("low", "medium", "high")


#: Fields that identify a record for cross-window deduplication, per kind.
#:
#: **Why this is not just the whole record.** Windows overlap by design, so a strain named in the
#: overlap is reported twice. The original key was the whole serialised record, on the reasoning
#: that spans are in document coordinates by this point and so a repeat "serialises identically
#: both times". Measured against a real paper, that is false: the model quotes a *different
#: sentence* for the same strain in each window, so the span differs, so the JSON differs, and the
#: duplicate survives. On `doi:10.1016/j.ymben.2012.11.008` it produced **85 strain proposals for
#: 53 distinct strains** -- 32 duplicate curation tasks from one paper, each costing a curator the
#: same minute or two as a real one.
#:
#: A strain is identified by its name: that is already how promotion treats it
#: (``YAA:STRAIN:<slug>``, so two papers reporting CEN.PK113-7D converge on one row), so collapsing
#: here only moves that collapse earlier, to where the human cost actually is.
#:
#: Every other kind keeps the whole-record key, deliberately. Two measurements with the same value
#: and unit may be genuinely different measurements under different conditions, and the same paper
#: showed only 8 whole-record duplicates in 167 measurements -- so the cost of being wrong there is
#: high and the saving is small. Narrow the identity for another kind only with the same kind of
#: measurement behind it.
_IDENTITY_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "strains": ("name_as_reported",),
}


def _identity_of(kind: str, record: Mapping[str, Any]) -> str:
    """What makes two records of this kind the same record, for dedup across windows."""
    fields = _IDENTITY_FIELDS.get(kind)
    if fields is None:
        return json.dumps(record, sort_keys=True, default=str)
    values = [str(record.get(name, "")).strip().casefold() for name in fields]
    # An identity field the model left blank cannot identify anything, so such a record falls back
    # to the whole-record key rather than colliding with every other blank one.
    if not any(values):
        return json.dumps(record, sort_keys=True, default=str)
    return "\x00".join(values)


def _least_confident(results: Sequence[Any]) -> str | None:
    """The most cautious ``self_confidence`` any window reported.

    A paper is extracted as well as its worst window, not its best: if the model was unsure about
    the section holding the titers, the extraction as a whole deserves that caution. An
    unrecognized value is treated as the most cautious of all — it is not evidence of confidence.
    """
    claims = [
        value
        for value in (result.value.get("self_confidence") for result in results)
        if isinstance(value, str)
    ]
    if not claims:
        return None
    if any(claim not in _CONFIDENCE_ORDER for claim in claims):
        return min(claims)
    return min(claims, key=_CONFIDENCE_ORDER.index)


def _merge_stats(parts: Sequence[RunStats]) -> RunStats:
    """One :class:`RunStats` covering every window: tokens and seconds summed, attempts summed.

    ``cache_hit`` is true only when *every* window was served from cache, because a run that
    called the model even once was not a cache hit — reporting otherwise would understate cost.
    ``input_hash`` is taken from the first window and is no longer a key that reproduces the whole
    run; that is what makes a chunked extraction not byte-reproducible from the cache alone, and
    it is recorded here rather than papered over.
    """
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    prompt_tokens = [part.prompt_tokens for part in parts if part.prompt_tokens is not None]
    completion = [part.completion_tokens for part in parts if part.completion_tokens is not None]
    return replace(
        first,
        attempts=sum(part.attempts for part in parts),
        cache_hit=all(part.cache_hit for part in parts),
        prompt_tokens=sum(prompt_tokens) if prompt_tokens else None,
        completion_tokens=sum(completion) if completion else None,
        duration_s=sum(part.duration_s for part in parts),
    )


# ------------------------------------------------------------------------------------ the runs


@dataclass(frozen=True)
class TriageVerdict:
    """The cheap model's answer to "is this paper worth the expensive one?"."""

    recommend_extraction: bool
    has_quantitative_production_data: bool
    has_genetic_modifications: bool
    reason: str
    stats: RunStats


#: The triage answer's shape. Four fields, no spans: triage extracts nothing, so there is nothing
#: to point at. It decides whether the extractor runs, and that decision is re-made every time the
#: prompt version changes rather than stored as a fact about the paper.
TRIAGE_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "required": [
        "has_quantitative_production_data",
        "has_genetic_modifications",
        "recommend_extraction",
        "reason",
    ],
    "properties": {
        "has_quantitative_production_data": {"type": "boolean"},
        "has_genetic_modifications": {"type": "boolean"},
        "recommend_extraction": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1, "maxLength": 400},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ExtractionOutcome:
    """Everything one extraction produced, whether or not it was written."""

    publication_id: str
    extraction_id: str | None
    payload: JsonObject
    records: tuple[tuple[str, int, JsonObject], ...]
    notes: tuple[RecordNote, ...]
    excerpt: Excerpt
    stats: RunStats
    prompt_version: str
    self_confidence: str | None
    #: Validator complaints from each attempt the model got wrong, oldest first. Empty on a
    #: first-try success. Stored because "the model needed to be told twice, about this" is a
    #: measurement of the prompt, and the only place it is ever recorded.
    failed_attempts: tuple[tuple[str, ...], ...] = ()

    @property
    def record_count(self) -> int:
        """How many proposed records survived validation."""
        return len(self.records)

    @property
    def counts_by_kind(self) -> dict[str, int]:
        """Accepted records per payload section, for a one-line report."""
        counts: dict[str, int] = {}
        for kind, _, _ in self.records:
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def summary(self) -> str:
        """One line for a CLI or a log."""
        kinds = ", ".join(f"{kind}={count}" for kind, count in sorted(self.counts_by_kind.items()))
        return (
            f"{self.publication_id}: {self.record_count} proposed record(s)"
            f"{' (' + kinds + ')' if kinds else ''}; "
            f"sent {self.excerpt.chars}/{self.excerpt.document_chars} chars "
            f"({self.excerpt.fraction_of_document:.0%} of the document); "
            f"{len(self.notes)} note(s)"
        )


def triage_publication(
    *,
    publication_id: str,
    source_text: str,
    provider: Provider,
    config: LlmConfig,
    sections: Sequence[str] = DEFAULT_EXTRACTION_SECTIONS,
    prompt_directory: Path | None = None,
    cache: ResultCache | None = None,
) -> TriageVerdict:
    """Ask the cheap model whether the expensive one should read this paper.

    PLAN.md L.3's ordering, made runnable: this uses the ``triage`` model role, sees the same
    excerpt the extractor would, and extracts nothing. A caller that skips it pays full price on
    every paper; a caller that treats its "no" as final loses papers, which is why the prompt tells
    the model to be generous and why the verdict is advisory rather than stored.
    """
    excerpt = build_excerpt(source_text, split_sections(source_text), sections)
    prompt_file = load_prompt("triage", directory=prompt_directory)
    prompt = prompt_file.render(
        {
            "publication_id": publication_id,
            "section_names": ", ".join(excerpt.section_names),
            "excerpt": excerpt.text,
        }
    )
    result = run(
        prompt,
        TRIAGE_SCHEMA,
        provider=provider,
        model=config.model_for("triage"),
        prompt_version=prompt_file.version,
        options=config.options,
        timeout_s=config.timeout_s,
        cache=cache,
    )
    value = result.value
    return TriageVerdict(
        recommend_extraction=bool(value["recommend_extraction"]),
        has_quantitative_production_data=bool(value["has_quantitative_production_data"]),
        has_genetic_modifications=bool(value["has_genetic_modifications"]),
        reason=str(value["reason"]),
        stats=result.stats,
    )


def extract_publication(
    conn: sqlite3.Connection,
    *,
    publication_id: str,
    source_text: str,
    provider: Provider,
    config: LlmConfig,
    settings: Settings,
    sections: Sequence[str] = DEFAULT_EXTRACTION_SECTIONS,
    prompt_directory: Path | None = None,
    resolve_entity: EntityResolver | None = None,
    cache: ResultCache | None = None,
    run_id: str | None = None,
    write: bool = True,
    now: datetime | None = None,
    max_excerpt_chars: int | None = None,
    window_overlap: int = 1500,
    kinds: Sequence[str] | None = None,
) -> ExtractionOutcome:
    """Extract one publication into a proposed Zone I ``extraction`` row.

    Args:
        conn: An open connection. Read for the vocabulary, written only if ``write``.
        publication_id: Must already exist in ``publication``. This function will not create one:
            that row is Zone R and PLAN.md L.5 forbids an agent from writing there.
        source_text: The paper's plain text. Sectioned here; only the wanted sections are sent.
        provider: Any :class:`~fermdb.llm.providers.Provider`. Tests pass the mock.
        config: Supplies the model for the ``extraction`` role, sampling options and the timeout.
            No model name is chosen here.
        resolve_entity: Injected id resolver. Defaults to one over the product vocabulary, which
            is the only id space the payload references; pass a wider one where more ids are in
            play. Never falls back to "assume it resolves".
        write: False runs everything including validation and writes nothing — the dry run a
            curator uses to see what a prompt revision would produce.
        kinds: Ask for a subset of ``RECORD_KINDS`` instead of all seven. The payload schema is
            most of the fixed per-call cost, so narrowing it buys back context — but a narrowed
            run makes **no claim about the kinds it did not ask for**, and the resulting
            ``extraction`` row would otherwise be indistinguishable from one that looked and found
            nothing. The kinds asked for are therefore recorded in the prompt version, so two runs
            over different subsets cannot silently share a cache entry or be compared as equals.

    Returns:
        An :class:`ExtractionOutcome`. ``extraction_id`` is None when ``write`` is False.

    Raises:
        ExtractionError: No publication row, no sections, or a malformed payload.
        LlmValidationError: The model's output failed validation on every attempt. Nothing is
            stored: a payload where only some records validated is not a smaller good extraction,
            it is an extraction whose failures have been hidden.
    """
    existing = _publication_row(conn, publication_id)
    if existing is None:
        raise ExtractionError(
            f"no publication row for {publication_id!r}. Extraction will not create one: a "
            f"publication record is Zone R and no agent may write there (PLAN.md L.5). Run "
            f"`fermdb literature discover` first."
        )
    # Carry the id forward in the spelling the `publication` row actually uses, not the caller's.
    # Every `extraction`/`extraction_span` FK points at `publication(id)`, so writing a
    # publisher-cased DOI id here would fail the foreign key — or, in a build with enforcement
    # off, store a row that no join ever finds again.
    publication_id = str(existing["id"])

    document = source_text
    excerpt = build_excerpt(document, split_sections(document), sections)
    vocabulary = load_vocabulary(settings, conn)
    schema = payload_schema(vocabulary, kinds=kinds)
    units = load_units(settings)
    yields = load_theoretical_yields(settings)
    resolver = (
        resolve_entity if resolve_entity is not None else resolver_from_ids(vocabulary.product_ids)
    )

    prompt_file = load_prompt("extraction", directory=prompt_directory)
    # A narrowed run asked a different question, so it gets a different prompt version. Without
    # this, two runs over different subsets would share a cache entry keyed on (prompt, model,
    # options) -- and a stored `extraction` row would claim a coverage it never had.
    prompt_version = prompt_file.version
    if kinds is not None:
        prompt_version += "+kinds:" + ",".join(k for k in RECORD_KINDS if k in frozenset(kinds))
    windows = (
        excerpt.split(max_excerpt_chars, overlap=window_overlap)
        if max_excerpt_chars is not None
        else (excerpt,)
    )

    merged: list[tuple[str, JsonObject]] = []
    seen: set[tuple[str, str]] = set()
    notes: list[RecordNote] = []
    results: list[Any] = []

    for number, window in enumerate(windows, start=1):
        prompt = prompt_file.render(
            {
                "publication_id": publication_id,
                "section_names": ", ".join(window.section_names),
                "excerpt": window.text,
                # Compact, not indented. The schema is 27,629 characters pretty-printed and
                # 16,736 compact -- 39% of it was whitespace, ~3,100 tokens of a local model's
                # context, repeated in every window of every paper. Nothing reads this but the
                # model, and it is still valid JSON for anyone who wants to pretty-print a
                # logged prompt. `sort_keys` stays, because the prompt is part of the cache key
                # and must not change with dict ordering.
                "schema_json": json.dumps(schema, sort_keys=True, separators=(",", ":")),
            }
        )

        def check(candidate: JsonObject, _window: Excerpt = window) -> list[str]:
            errors, _, _ = _validate_payload(
                candidate,
                document=document,
                excerpt=_window,
                units=units,
                yields=yields,
                resolve_entity=resolver,
            )
            return errors

        result = run(
            prompt,
            schema,
            provider=provider,
            model=config.model_for("extraction"),
            prompt_version=prompt_version,
            options=config.options,
            timeout_s=config.timeout_s,
            cache=cache,
            post_validate=check,
        )
        results.append(result)

        # Re-validated after the run rather than reusing what `check` computed, so that a value
        # served from cache — which skips `post_validate` entirely — is still checked against this
        # source text before it is written down. The cost is a few microseconds of deterministic
        # work against a model call that has already happened.
        errors, window_notes, accepted = _validate_payload(
            result.value,
            document=document,
            excerpt=window,
            units=units,
            yields=yields,
            resolve_entity=resolver,
        )
        if errors:
            raise ExtractionError(
                f"{publication_id}: a validated result failed re-validation before storage, which "
                f"means the cached entry was produced against different source text or this code "
                f"changed under it: {'; '.join(errors[:5])}"
            )

        for kind, _, record in accepted:
            key = (kind, _identity_of(kind, record))
            if key in seen:
                continue
            seen.add(key)
            merged.append((kind, record))
        for note in window_notes:
            path = note.record_path if len(windows) == 1 else f"w{number}:{note.record_path}"
            notes.append(RecordNote(path, note.code, note.message))

    # Renumbered against the merged payload, because `record_path` has to mean the same thing on
    # the span row, the curation task and the stored payload — and after merging, a record's
    # position is its position here, not in whichever window happened to report it.
    counters: dict[str, int] = {}
    records: list[tuple[str, int, JsonObject]] = []
    for kind, record in merged:
        index = counters.get(kind, 0)
        counters[kind] = index + 1
        records.append((kind, index, record))

    stats = _merge_stats([result.stats for result in results])
    outcome = ExtractionOutcome(
        publication_id=publication_id,
        extraction_id=None,
        payload=_normalized_payload({"self_confidence": _least_confident(results)}, records),
        records=tuple(records),
        notes=tuple(notes),
        excerpt=excerpt,
        stats=stats,
        prompt_version=prompt_version,
        self_confidence=_least_confident(results),
        failed_attempts=tuple(attempt for result in results for attempt in result.failed_attempts),
    )
    if not write:
        return outcome
    extraction_id = write_extraction(conn, outcome, run_id=run_id, now=now)
    return replace(outcome, extraction_id=extraction_id)


# ------------------------------------------------------------------------------------- storage


def _utc_now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")


def _publication_row(conn: sqlite3.Connection, publication_id: str) -> sqlite3.Row | None:
    """Does a `publication` row exist for this id, in whatever casing the caller spelled it?

    Folds through :func:`normalize_publication_id` first. `publication.id` is stored lowercased
    for a DOI key while `publication.doi` keeps the publisher's casing (see that function for the
    invariant and the measurement), so a bare `=` against an id a caller typed from a paper's
    front matter misses one DOI-keyed row in eight.
    """
    row: sqlite3.Row | None = conn.execute(
        "SELECT id FROM publication WHERE id = ?", (normalize_publication_id(publication_id),)
    ).fetchone()
    return row


def find_publication(
    conn: sqlite3.Connection, *, pmid: str | None = None, doi: str | None = None
) -> sqlite3.Row | None:
    """Look a publication up by PMID or DOI, preferring the PMID when both are given.

    The `id` half of each lookup is built with :func:`canonical_publication_id`, not by pasting
    the caller's string after a scheme prefix: `publication.id` holds the *lowercased* DOI, so
    `'doi:' || <publisher-cased DOI>` matches nothing. The `doi = ?` half still compares verbatim,
    which is what finds a row whose stored `doi` carries that same publisher casing.
    """
    if pmid:
        row = conn.execute(
            "SELECT * FROM publication WHERE pmid = ? OR id = ?",
            (pmid, canonical_publication_id(doi=None, pmid=pmid)),
        ).fetchone()
        if row is not None:
            return row  # type: ignore[no-any-return]
    if doi:
        row = conn.execute(
            "SELECT * FROM publication WHERE doi = ? OR id = ?",
            (doi, canonical_publication_id(doi=doi, pmid=None)),
        ).fetchone()
        if row is not None:
            return row  # type: ignore[no-any-return]
    return None


def _no_source_text_error(
    conn: sqlite3.Connection, *, requested: str, canonical: str
) -> SourceTextError:
    """Say which of the three things actually went wrong.

    Until this function existed, all three produced the same sentence -- "not open access or never
    fetched" -- including the two cases where that sentence is false. A misleading diagnosis is
    worse than a vague one: it sends the reader to the manual download queue for a publication
    that is not in the atlas at all, or for an id they merely mis-cased.
    """
    folded = canonical != requested
    if _publication_row(conn, canonical) is None:
        also = f" (nor for {canonical!r}, its case-folded form)" if folded else ""
        return SourceTextError(
            f"no publication row for {requested!r}{also}. Extraction will not create one: a "
            f"publication record is Zone R and no agent may write there (PLAN.md L.5). Run "
            f"`fermdb literature discover` first, or pass --text-file to extract from a local "
            f"copy."
        )
    if folded:
        return SourceTextError(
            f"{requested} is stored as {canonical} (publication ids are case-folded; only the "
            f"`doi` column keeps the publisher's casing), and that publication has no stored full "
            f"text. Either it is not open access (see `fermdb literature manual-queue export`) or "
            f"it was never fetched. Pass --text-file to extract from a local copy instead."
        )
    return SourceTextError(
        f"no stored full text for {canonical}. The publication row exists, so this is an "
        f"acquisition gap: either it is not open access (see `fermdb literature manual-queue "
        f"export`) or it was never fetched. Pass --text-file to extract from a local copy instead."
    )


def load_source_text(
    conn: sqlite3.Connection, settings: Settings, *, publication_id: str
) -> tuple[str, str]:
    """The stored full text for a publication, as ``(text, origin)``.

    Reads the ``fulltext_asset`` row acquisition wrote. Refuses anything it cannot decode as text
    rather than guessing: there is no PDF text extractor in this build's dependencies, and a PDF
    decoded as UTF-8 with errors replaced would produce a document full of plausible-looking
    garbage for a model to quote from.

    The id is case-folded on the way in (:func:`normalize_publication_id`), because
    ``--publication-id`` reaches here verbatim from the CLI and a DOI copied off a paper carries
    the publisher's casing -- ``10.1128/AEM.00588-21``, say, against a stored id of
    ``doi:10.1128/aem.00588-21``.
    """
    canonical = normalize_publication_id(publication_id)
    row = conn.execute(
        "SELECT content_path, media_type FROM fulltext_asset "
        "WHERE publication_id = ? AND storage_state = 'stored_fulltext' "
        "ORDER BY retrieved_at DESC LIMIT 1",
        (canonical,),
    ).fetchone()
    if row is None:
        raise _no_source_text_error(conn, requested=publication_id, canonical=canonical)
    path = settings.data_dir / str(row["content_path"])
    if not path.is_file():
        raise SourceTextError(
            f"{canonical}: fulltext_asset points at {path}, which does not exist. The "
            f"derived tier may have been rebuilt without re-acquiring."
        )
    media_type = (row["media_type"] or "").split(";", 1)[0].strip().lower()
    return _decode_text(path, media_type, canonical), str(path)


def _decode_text(path: Path, media_type: str, publication_id: str) -> str:
    data = path.read_bytes()
    # JATS first: acquisition prefers Europe PMC's fullTextXML over the PDF, so this is the
    # common case, and the raw markup must never reach a model (see fermdb.extract.jats).
    if is_jats(data):
        try:
            return jats_to_text(data)
        except JatsError as exc:
            raise SourceTextError(
                f"{publication_id}: {path} is JATS but unreadable: {exc}"
            ) from exc
    # PDFs the owner supplied through the manual download queue. `extract.pdf` extracts the text
    # layer and refuses a document that has none -- the original reason for refusing PDFs outright
    # ("a PDF read as text produces plausible garbage") applies to a scan just as much, so the
    # check moved rather than went away.
    if media_type == "application/pdf" or is_pdf(data):
        try:
            return pdf_to_text(data, source=f"{publication_id} ({path.name})")
        except PdfError as exc:
            raise SourceTextError(str(exc)) from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceTextError(
            f"{publication_id}: {path} is not valid UTF-8 ({exc}). Not decoding with errors "
            f"replaced: a replacement character inside a quote makes a span unverifiable against "
            f"the real text."
        ) from exc


def write_extraction(
    conn: sqlite3.Connection,
    outcome: ExtractionOutcome,
    *,
    run_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """Write one proposed extraction and its spans. Returns the new extraction id.

    ``review_state`` is ``'proposed'`` and no curator column is set, which the ``extraction``
    table's CHECK constraints require of an unreviewed row. Promotion out of Zone I happens in
    :mod:`fermdb.curate.queue`, by a human.

    Span rows are written ``zone='I'``, not ``'R'``, even though ``quoted_text`` is the paper's
    own words. The zone describes the *claim*, and the claim a span makes is "this passage is the
    evidence for that value" — which is the model's, not the paper's. The quote inside it is
    verbatim by construction and verified twice; the choice of it is inference.
    """
    extraction_id = f"YAA:EXTR:{uuid.uuid4().hex}"
    timestamp = _utc_now_iso(now)
    validation = {
        "notes": [note.as_dict() for note in outcome.notes],
        "accepted_records": outcome.record_count,
        "excerpt_chars": outcome.excerpt.chars,
        "document_chars": outcome.excerpt.document_chars,
        "sections_sent": list(outcome.excerpt.section_names),
        "attempts": outcome.stats.attempts,
        "cache_hit": outcome.stats.cache_hit,
        # What the model got wrong before it got it right. A prompt whose extractions all needed
        # a retry for the same reason is a prompt with a bug in it, and this is where that shows.
        "failed_attempts": [list(attempt) for attempt in outcome.failed_attempts],
    }
    conn.execute(
        "INSERT INTO extraction (id, publication_id, section, extractor, extractor_version, "
        "model, model_version, prompt_version, run_id, input_hash, payload, self_confidence, "
        "validation, review_state, created_at, zone) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, 'I')",
        (
            extraction_id,
            outcome.publication_id,
            ",".join(outcome.excerpt.section_names),
            EXTRACTOR,
            EXTRACTOR_VERSION,
            outcome.stats.model,
            outcome.stats.model_version,
            outcome.prompt_version,
            run_id,
            outcome.stats.input_hash,
            json.dumps(outcome.payload, sort_keys=True),
            outcome.self_confidence,
            json.dumps(validation, sort_keys=True),
            timestamp,
        ),
    )

    for kind, index, record in outcome.records:
        span = record.get("span")
        if not isinstance(span, Mapping):
            continue
        conn.execute(
            "INSERT INTO span (id, publication_id, extraction_id, section, char_start, "
            "char_end, quoted_text, record_path, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'I')",
            (
                f"YAA:SPAN:{uuid.uuid4().hex}",
                outcome.publication_id,
                extraction_id,
                span.get("section"),
                span.get("char_start"),
                span.get("char_end"),
                span.get("quote"),
                record_path(kind, index),
            ),
        )
    conn.commit()
    return extraction_id
