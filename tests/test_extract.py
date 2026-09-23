"""Tests for `fermdb.extract` — sectioning, prompts, the payload schema, and the harness.

Three properties this file exists to hold down.

**No test touches the network.** An autouse fixture makes `urllib.request.urlopen` raise, and
every run goes through `MockProvider`. A test that needs the internet is a broken test.

**The span check survives the excerpt.** The model is shown methods + results, not the paper, so
its offsets are into a stitched-together excerpt that exists only for the duration of the call.
The tests below pin both halves of the translation: a truthful quote must come back with offsets
that resolve *in the document*, and a quote that is fabricated, misplaced, or sitting across a
section boundary must take its record down with it. That is the check PLAN.md calls the one that
matters most, and the excerpt is where it would quietly stop working.

**Nothing reaches the database unreviewed.** The stored row is `zone='I'`,
`review_state='proposed'`, every record `confidence='unverified'` whatever the model claimed — and
when validation fails, nothing is stored at all rather than the subset that happened to pass.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.extract import (
    DEFAULT_EXTRACTION_SECTIONS,
    RECORD_KINDS,
    UNSECTIONED,
    Excerpt,
    ExtractionError,
    MeasurementRecord,
    NotPrimaryResearchError,
    PayloadVocabulary,
    PromptError,
    SchemaBuildError,
    Section,
    SectioningError,
    SourceTextError,
    build_excerpt,
    extract_publication,
    find_publication,
    load_prompt,
    load_source_text,
    load_vocabulary,
    looks_like_review,
    payload_schema,
    payload_sections,
    record_path,
    split_sections,
)
from fermdb.llm import LlmConfig, LlmValidationError, MemoryCache, MockProvider, check_json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"
PROMPT_DIR = REPO_ROOT / "src" / "fermdb" / "extract" / "prompts"

PUBLICATION_ID = "pmid:11112222"

DOCUMENT = """Mitochondrial isobutanol production in Saccharomyces cerevisiae
A. Author, B. Author

Abstract
We relocalized the Ehrlich pathway and measured isobutanol.

1. Introduction
Isobutanol is a drop-in fuel. Earlier work reported 0.63 g/L in a cytosolic strain.

2. Materials and Methods
Strains were derived from CEN.PK113-7D. ILV2 was overexpressed from the TDH3 promoter.
Cultures were grown at 30 C in minimal medium with 20 g/L glucose.

3. Results
The engineered strain IBA-7 produced 22.6 g/L isobutanol after 72 h, corresponding to a
yield of 0.31 g/g glucose consumed. The parent strain reached 1.2 g/L. Isoamyl alcohol
accumulated to 0.9 g/L in the same cultures. 2-Ketoisovalerate supply remained limiting.

4. Discussion
The titer is the highest reported for this configuration.

References
1. Someone et al., 2019.
"""


# ------------------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any real HTTP call fail loudly here rather than pass on a machine with a daemon."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pinned to the repo's own env/paths.yaml, with the *derived tier* under tmp_path.

    `env={}` alone isolates from environment variables, not from the paths themselves -- it still
    resolves `data_dir` to the developer's real `~/fermdb-data`, so
    `test_load_source_text_refuses_a_pdf` was writing its fixture PDF into live data (it was found
    there, as `fulltext/aa/aa.pdf`, sitting beside genuinely acquired papers). Same isolation as
    `tests/test_acquire.py::settings`.
    """
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """An in-memory atlas with one publication row to hang an extraction off."""
    connection = open_db(IN_MEMORY)
    connection.execute(
        "INSERT INTO publication (id, pmid, title, year, zone, evidence, confidence) "
        "VALUES (?, '11112222', 'Test paper', 2024, 'R', 'test fixture', 'unverified')",
        (PUBLICATION_ID,),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def vocabulary(settings: Settings, conn: sqlite3.Connection) -> PayloadVocabulary:
    return load_vocabulary(settings, conn)


@pytest.fixture
def config() -> LlmConfig:
    """Default LLM configuration: the mock provider, no cache directory."""
    return LlmConfig.load(env={})


def excerpt_of(document: str = DOCUMENT) -> Excerpt:
    """The excerpt the harness would build for the default sections."""
    return build_excerpt(document, split_sections(document), DEFAULT_EXTRACTION_SECTIONS)


def span_in(excerpt: Excerpt, quote: str) -> dict[str, Any]:
    """A truthful span: the quote and the offsets where it really occurs in the excerpt."""
    start = excerpt.text.index(quote)
    return {"quote": quote, "char_start": start, "char_end": start + len(quote)}


def empty_payload(self_confidence: str = "medium") -> dict[str, Any]:
    """A schema-valid payload that reports nothing — the honest answer for an empty paper."""
    payload: dict[str, Any] = {kind: [] for kind in RECORD_KINDS}
    payload["self_confidence"] = self_confidence
    return payload


def truthful_payload(excerpt: Excerpt) -> dict[str, Any]:
    """A payload whose every span really occurs where it says it does."""
    payload = empty_payload()
    payload["strains"] = [
        {
            "name_as_reported": "IBA-7",
            "role": "engineered",
            "span": span_in(excerpt, "The engineered strain IBA-7"),
        }
    ]
    payload["modifications"] = [
        {
            "target_as_reported": "ILV2",
            "modification_type": "overexpression",
            "encoding_genome": "nuclear",
            "span": span_in(excerpt, "ILV2 was overexpressed from the TDH3 promoter"),
        }
    ]
    payload["measurements"] = [
        {
            "product_id": "YAA:PRODUCT:isobutanol",
            "product_as_reported": "isobutanol",
            "quantity_kind": "titer",
            "value": 22.6,
            "unit": "g/L",
            "source_locator": "text",
            "span": span_in(excerpt, "22.6 g/L isobutanol after 72 h"),
        },
        {
            "product_id": "YAA:PRODUCT:isobutanol",
            "product_as_reported": "isobutanol",
            "quantity_kind": "yield",
            "value": 0.31,
            "unit": "g/g",
            "basis": "consumed",
            "substrate": "glucose",
            "source_locator": "text",
            "span": span_in(excerpt, "0.31 g/g glucose consumed"),
        },
    ]
    payload["conditions"] = [
        {
            "facet": "temperature_c",
            "value_as_reported": "30 C",
            "span": span_in(excerpt, "grown at 30 C in minimal medium"),
        }
    ]
    payload["co_reported_higher_alcohols"] = [
        {
            "product_id": "YAA:PRODUCT:3-methyl-1-butanol",
            "product_as_reported": "Isoamyl alcohol",
            "quantity_kind": "titer",
            "value": 0.9,
            "unit": "g/L",
            "source_locator": "text",
            "span": span_in(excerpt, "Isoamyl alcohol\naccumulated to 0.9 g/L"),
        }
    ]
    payload["bottlenecks"] = [
        {
            "node_as_reported": "2-Ketoisovalerate supply",
            "claim": "2-ketoisovalerate supply limits isobutanol production",
            "support": "stated_by_authors",
            "span": span_in(excerpt, "2-Ketoisovalerate supply remained limiting"),
        }
    ]
    return payload


def provider_returning(*payloads: Mapping[str, Any]) -> MockProvider:
    """A mock that answers with these payloads in order, then repeats the last one."""
    texts = [json.dumps(payload) for payload in payloads]
    return MockProvider(responses=texts, default_response=texts[-1])


def extract(
    conn: sqlite3.Connection,
    settings: Settings,
    config: LlmConfig,
    provider: MockProvider,
    **kwargs: Any,
) -> Any:
    return extract_publication(
        conn,
        publication_id=PUBLICATION_ID,
        source_text=DOCUMENT,
        provider=provider,
        config=config,
        settings=settings,
        **kwargs,
    )


# ------------------------------------------------------------------------------------ sectioning


def test_sections_tile_the_document_exactly() -> None:
    """Every character belongs to exactly one section, which is what makes offsets translatable."""
    sections = split_sections(DOCUMENT)
    assert sections[0].char_start == 0
    assert sections[-1].char_end == len(DOCUMENT)
    for earlier, later in zip(sections, sections[1:], strict=False):
        assert earlier.char_end == later.char_start


def test_the_usual_headings_are_recognized() -> None:
    names = [section.name for section in split_sections(DOCUMENT)]
    assert names == [
        "front_matter",
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
    ]


def test_results_and_discussion_is_not_split_into_results() -> None:
    """A combined section matched as 'results' would silently drop half the paper."""
    text = "Results and Discussion\nWe found things.\n"
    assert [section.name for section in split_sections(text)] == ["results_and_discussion"]


def test_a_paragraph_starting_with_results_is_not_a_heading() -> None:
    text = "Methods\nResults were obtained by HPLC over a long sentence that keeps going here.\n"
    assert [section.name for section in split_sections(text)] == ["methods"]


def test_a_document_with_no_headings_is_one_unsectioned_block() -> None:
    sections = split_sections("just some text with no headings at all in it")
    assert [section.name for section in sections] == [UNSECTIONED]


def test_build_excerpt_refuses_a_document_with_no_methods_or_results() -> None:
    """Loud failure, with the sections that *are* present named, rather than a whole-text run."""
    document = "Abstract\nWe did things.\n\nIntroduction\nBackground.\n"
    with pytest.raises(SectioningError) as excinfo:
        build_excerpt(document, split_sections(document), DEFAULT_EXTRACTION_SECTIONS)
    assert "abstract" in str(excinfo.value)
    assert "introduction" in str(excinfo.value)


def test_the_excerpt_is_much_smaller_than_the_document() -> None:
    """PLAN.md V.4's whole argument, measured on one paper."""
    excerpt = excerpt_of()
    assert excerpt.chars < excerpt.document_chars
    assert excerpt.section_names == ("methods", "results")


def test_excerpt_offsets_translate_back_to_the_document() -> None:
    excerpt = excerpt_of()
    quote = "22.6 g/L isobutanol"
    start = excerpt.text.index(quote)
    mapped = excerpt.to_document(start, start + len(quote))
    assert mapped is not None
    assert DOCUMENT[mapped[0] : mapped[1]] == quote


def test_a_span_across_a_section_marker_does_not_translate() -> None:
    """Clamping it would resolve to *some* text, which is exactly what must not happen."""
    excerpt = excerpt_of()
    marker_at = excerpt.text.index("[[section: results]]")
    assert excerpt.to_document(marker_at - 5, marker_at + 25) is None


def test_section_at_returns_none_on_a_marker() -> None:
    excerpt = excerpt_of()
    assert excerpt.section_at(excerpt.text.index("[[section: results]]")) is None


# ---------------------------------------------------------------------------------------------
# Structured abstracts.
#
# BMC and its imitators print `Background` / `Results` / `Conclusions` *inside* the abstract, in
# the same heading shape the body uses. Until `_fold_structured_abstract`, `split_sections`
# returned two sections named `results` for such a paper -- the abstract's and the body's -- and
# `build_excerpt` sent both. The abstract is the one passage in a paper where several strains are
# compressed into one subject-less clause, so it is the worst possible thing to hand an extractor
# under the label "results"; three Zone R rows on doi:10.1186/1475-2859-12-119 attribute an
# abstract claim to a strain the sentence never named because of it, and every one of those spans
# is stored with `section = 'results'`, which is why nothing downstream could tell.
#
# 209 of the 1,429 stored full texts produce a duplicated wanted section name, and 270 have an
# abstract sub-heading reaching the model as body text. This is a house style, not a paper.
# ---------------------------------------------------------------------------------------------

#: The real shape of doi:10.1186/1475-2859-12-119 (Matsuda et al. 2013), quoted from the stored
#: JATS: an `Abstract` heading, three sub-headings under it, then the body restarting at
#: `Background`. The abstract's Results and the body's Results are both present and say different
#: things about the same strains, which is the whole hazard in one fixture.
BMC_STRUCTURED = """Increased isobutanol production in Saccharomyces cerevisiae
F. Matsuda, J. Ishii, A. Kondo

Abstract

Background

Isobutanol is an important target for biorefinery research as a next-generation biofuel.

Results

The integration of a single gene deletion lpd1D and the activation of the transhydrogenase-like
shunt further increased isobutanol levels. In a batch fermentation test at the 50-mL scale using
the two integrated strains, the isobutanol titer reached 1.62 g/L at 24 h.

Conclusions

Downregulation of competing pathways is a promising strategy.

Keywords: Isobutanol, Ehrlich pathway, Saccharomyces cerevisiae

Background

There is increasing interest in the production of branched higher alcohols from renewable
biomass to be used as a next-generation biofuel.

Results

Disruption of genes related to pyruvate metabolism and valine biosynthesis

The isobutanol titer of the BSW205 and BSW206 strains reached 230 and 221 mg/L.

Discussion

The integration of PDH suppression by lpd1D in BSW205 and BSW206 strains.

Methods

Strains were derived from BY4741.

References
1. Matsuda et al., 2013.
"""


def test_a_structured_abstract_does_not_contribute_a_results_section() -> None:
    """The abstract's `Results` sub-heading is not the paper's Results, and must not be named one.

    This is the bug itself, pinned at its source: before the fix `split_sections` returned two
    sections called `results` for this shape, and `build_excerpt` includes every section matching
    a wanted name, so the excerpt began with the abstract.
    """
    names = [section.name for section in split_sections(BMC_STRUCTURED)]
    assert names.count("results") == 1
    assert names == [
        "front_matter",
        "abstract",
        "introduction",
        "results",
        "discussion",
        "methods",
        "references",
    ]


def test_the_folded_abstract_covers_every_one_of_its_sub_headings() -> None:
    """One `abstract` section spanning the lot, not four sections that happen to be adjacent.

    Sections must still tile the document exactly -- that is what makes an excerpt offset
    translatable back -- so folding replaces the run rather than dropping or overlapping it.
    """
    sections = split_sections(BMC_STRUCTURED)
    assert sections[0].char_start == 0
    assert sections[-1].char_end == len(BMC_STRUCTURED)
    for earlier, later in zip(sections, sections[1:], strict=False):
        assert earlier.char_end == later.char_start

    abstract = sections[1]
    assert abstract.name == "abstract"
    body = abstract.text_of(BMC_STRUCTURED)
    # Every sub-heading, and the abstract's own claims, are inside the one section.
    assert "Conclusions" in body
    assert "the isobutanol titer reached 1.62 g/L" in body


def test_the_bodys_results_is_still_found_and_still_whole() -> None:
    """Fixing the abstract must not cost a single character of the section that was wanted."""
    sections = split_sections(BMC_STRUCTURED)
    results = [section for section in sections if section.name == "results"]
    assert len(results) == 1
    text = results[0].text_of(BMC_STRUCTURED)
    assert text.startswith("Results")
    assert "BSW205 and BSW206 strains reached 230 and 221 mg/L" in text
    # It ends where Discussion begins, so nothing of it was handed to the abstract.
    assert text.rstrip().endswith("230 and 221 mg/L.")
    assert "1.62 g/L" not in text


def test_a_structured_abstract_with_no_abstract_heading_is_still_an_abstract() -> None:
    """85 of the 209 affected papers have no `Abstract` heading for a rule to key on.

    `jats_to_text` emits the sub-headings bare, straight after the title block, so the abstract
    begins at `Background` and looks exactly like an introduction. What identifies it is that the
    body restarts with that same `Background` further down -- never that the word "abstract"
    appears anywhere.
    """
    document = BMC_STRUCTURED.replace("Abstract\n\n", "", 1)
    names = [section.name for section in split_sections(document)]
    assert names.count("results") == 1
    assert names[:3] == ["front_matter", "abstract", "introduction"]


def test_no_part_of_the_abstract_reaches_the_model_or_can_be_labelled_results() -> None:
    """The guarantee that had to hold: a span in the abstract is never labelled `results`.

    Both halves are checked, because only one of them was ever visible. The excerpt must not
    contain the abstract's sentence (cost, and the wrong subject), *and* no offset inside the
    abstract may resolve to the name `results` (provenance -- the half that let three wrong rows
    through a bulk accept looking like Results quotes).
    """
    sections = split_sections(BMC_STRUCTURED)
    excerpt = build_excerpt(BMC_STRUCTURED, sections, DEFAULT_EXTRACTION_SECTIONS)
    assert excerpt.section_names == ("results", "methods")
    assert "the isobutanol titer reached 1.62 g/L" not in excerpt.text

    abstract = next(section for section in sections if section.name == "abstract")
    for piece in excerpt.pieces:
        overlaps = piece.doc_start < abstract.char_end and abstract.char_start < piece.doc_end
        assert not overlaps, f"{piece.name} piece overlaps the abstract"
    for section in sections:
        if section.char_start >= abstract.char_start and section.char_end <= abstract.char_end:
            assert section.name == "abstract"


def test_a_body_that_announces_methods_twice_keeps_both_halves() -> None:
    """ "The abstract has a Results sub-heading" and "the body's Methods is discontinuous" differ.

    Elsevier and MDPI papers really do print two matching `Methods` headings in the body, and 13
    of the stored full texts are that shape. Such a body re-opens a name, so a naive "a name
    repeats later, so the first one was the abstract" rule folds it and silently drops the real
    Introduction and the real first Methods. What separates them is that a body never re-opens
    its *Introduction*: the paper only starts once.
    """
    document = (
        "A paper\n\nAbstract\nWe did things.\n\n"
        "Introduction\nBackground to the work.\n\n"
        "Materials and Methods\nStrains were derived from CEN.PK113-7D.\n\n"
        "Experimental procedures\nIsobutanol was quantified by HPLC.\n\n"
        "Results\nThe strain produced 22.6 g/L.\n\n"
        "Discussion\nGood.\n"
    )
    names = [section.name for section in split_sections(document)]
    assert names.count("methods") == 2
    assert "introduction" in names, "the real Introduction was folded away"

    excerpt = build_excerpt(document, split_sections(document), DEFAULT_EXTRACTION_SECTIONS)
    assert excerpt.section_names == ("methods", "methods", "results")
    assert "Strains were derived from CEN.PK113-7D." in excerpt.text
    assert "Isobutanol was quantified by HPLC." in excerpt.text


def test_a_discontinuous_body_results_is_sent_in_both_halves() -> None:
    """A Results split in two by an intervening heading is still Results, twice over.

    The fix must not be "there can only be one Results". A paper that reports findings, breaks
    for a methods aside and resumes has two genuine Results blocks, and dropping either would
    lose measurements exactly as quietly as sending the abstract added false ones.
    """
    document = (
        "A paper\n\nAbstract\nWe did things.\n\n"
        "Introduction\nBackground to the work.\n\n"
        "Methods\nStrains were derived from CEN.PK113-7D.\n\n"
        "Results\nThe strain produced 22.6 g/L.\n\n"
        "Experimental procedures\nIsobutanol was quantified by HPLC.\n\n"
        "Results\nThe parent strain reached 1.2 g/L.\n\n"
        "Discussion\nGood.\n"
    )
    sections = split_sections(document)
    assert [section.name for section in sections].count("results") == 2

    excerpt = build_excerpt(document, sections, DEFAULT_EXTRACTION_SECTIONS)
    assert excerpt.section_names == ("methods", "results", "methods", "results")
    assert "The strain produced 22.6 g/L." in excerpt.text
    assert "The parent strain reached 1.2 g/L." in excerpt.text


def test_an_ordinary_abstract_is_left_exactly_as_it_was() -> None:
    """The common paper has one unstructured abstract and must pass through untouched.

    `abstract` is not a body-opening name, so a run consisting only of it is never confirmed --
    which is what keeps this rule from having an opinion about the 1,136 papers it has no
    business touching.
    """
    names = [section.name for section in split_sections(DOCUMENT)]
    assert names == [
        "front_matter",
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
    ]
    assert split_sections(DOCUMENT)[1].text_of(DOCUMENT).startswith("Abstract")


def test_a_long_leading_section_is_a_body_not_an_abstract() -> None:
    """An abstract is short because a journal caps it; a body Introduction is not.

    The second, dimensional guard. A paper whose body somehow did re-open its Introduction would
    still not be folded, because folding it would swallow thousands of characters of real text.
    The two guards are independent on purpose: over the 1,429 stored full texts each one alone
    selects exactly the same 293 runs, so neither is carrying the result by itself.
    """
    filler = "This is a real body paragraph that runs on at length. " * 60
    document = (
        f"A paper\n\nIntroduction\n{filler}\n\n"
        f"Results\n{filler}\n\n"
        f"Introduction\nA second introduction heading, improbably.\n\n"
        f"Results\nThe strain produced 22.6 g/L.\n\n"
        f"Discussion\nGood.\n"
    )
    names = [section.name for section in split_sections(document)]
    assert names.count("introduction") == 2, "a long body Introduction was folded into an abstract"
    assert names.count("results") == 2
    assert (
        filler.strip()
        in build_excerpt(document, split_sections(document), DEFAULT_EXTRACTION_SECTIONS).text
    )


# --------------------------------------------------------------------------------------- prompts


def test_the_prompt_version_carries_a_content_digest() -> None:
    """An edited prompt is a different prompt even if nobody bumped its declared version."""
    prompt = load_prompt("extraction")
    assert prompt.version.startswith("extraction/v1+")
    assert prompt.sha256[:12] in prompt.version


def test_editing_a_prompt_changes_its_version(tmp_path: Path) -> None:
    source = (PROMPT_DIR / "extraction.md").read_text(encoding="utf-8")
    (tmp_path / "extraction.md").write_text(source, encoding="utf-8")
    before = load_prompt("extraction", directory=tmp_path)
    (tmp_path / "extraction.md").write_text(source + "\nOne more instruction.\n", encoding="utf-8")
    after = load_prompt("extraction", directory=tmp_path)
    assert before.declared_version == after.declared_version
    assert before.version != after.version


def test_rendering_refuses_a_placeholder_mismatch() -> None:
    prompt = load_prompt("triage")
    with pytest.raises(PromptError) as excinfo:
        prompt.render({"publication_id": "x"})
    assert "missing" in str(excinfo.value)


def test_a_prompt_without_front_matter_is_refused(tmp_path: Path) -> None:
    (tmp_path / "broken.md").write_text("Just a prompt with no version.\n", encoding="utf-8")
    with pytest.raises(PromptError) as excinfo:
        load_prompt("broken", directory=tmp_path)
    assert "version" in str(excinfo.value)


def test_a_prompt_whose_front_matter_names_another_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "mine.md").write_text(
        "---\nname: theirs\nversion: v1\n---\nBody.\n", encoding="utf-8"
    )
    with pytest.raises(PromptError):
        load_prompt("mine", directory=tmp_path)


def test_every_shipped_prompt_loads_and_declares_a_version() -> None:
    for path in sorted(PROMPT_DIR.glob("*.md")):
        prompt = load_prompt(path.stem)
        assert prompt.declared_version
        assert prompt.template.strip()


def test_no_prompt_text_is_inlined_in_the_harness() -> None:
    """PLAN.md L.3: prompts are versioned files on disk, never inline strings."""
    source = (REPO_ROOT / "src" / "fermdb" / "extract" / "harness.py").read_text(encoding="utf-8")
    for giveaway in ("You are extracting", "Reply with a single JSON object"):
        assert giveaway not in source


# ---------------------------------------------------------------------------------------- schema


def test_the_payload_schema_requires_every_section(vocabulary: PayloadVocabulary) -> None:
    """An omitted key is ambiguous between 'none' and 'I did not look'."""
    schema = payload_schema(vocabulary)
    assert check_json_schema(empty_payload(), schema) == []
    incomplete = empty_payload()
    del incomplete["bottlenecks"]
    assert check_json_schema(incomplete, schema)


def test_a_narrowed_schema_asks_for_only_the_kinds_named(
    vocabulary: PayloadVocabulary,
) -> None:
    """One record kind at a time, so the schema stops being most of the prompt.

    The whole schema is ~18,000 compact characters against a ~4,800-character prompt template, and
    that overhead is repeated in every window of every paper. Narrowing cuts it by ~60%, which is
    the difference between a local model having negative room for the excerpt at its default
    context and having ~12,000 characters of it.
    """
    schema = payload_schema(vocabulary, kinds=["measurements"])
    assert set(schema["properties"]) == {"measurements", "self_confidence"}
    assert schema["required"] == ["measurements", "self_confidence"]
    assert check_json_schema({"measurements": [], "self_confidence": "low"}, schema) == []


def test_a_narrowed_schema_keeps_record_kinds_order_not_the_callers(
    vocabulary: PayloadVocabulary,
) -> None:
    """The prompt is part of the cache key, so it must not vary with argument order."""
    forwards = payload_schema(vocabulary, kinds=["strains", "measurements"])
    backwards = payload_schema(vocabulary, kinds=["measurements", "strains"])
    assert forwards == backwards
    assert list(forwards["properties"]) == ["strains", "measurements", "self_confidence"]


def test_a_narrowed_schema_rejects_an_unknown_or_empty_kind(
    vocabulary: PayloadVocabulary,
) -> None:
    with pytest.raises(SchemaBuildError, match="unknown record kind"):
        payload_schema(vocabulary, kinds=["measurments"])  # codespell:ignore
    with pytest.raises(SchemaBuildError, match="asks nothing"):
        payload_schema(vocabulary, kinds=[])


def test_the_full_schema_is_unchanged_when_no_kinds_are_given(
    vocabulary: PayloadVocabulary,
) -> None:
    """The narrowing is opt-in: every existing caller must get byte-identical output."""
    assert payload_schema(vocabulary) == payload_schema(vocabulary, kinds=None)
    assert list(payload_schema(vocabulary)["properties"])[:-1] == list(RECORD_KINDS)


def test_the_payload_schema_refuses_an_invented_product_id(
    vocabulary: PayloadVocabulary,
) -> None:
    """PLAN.md L.1.2: the model selects from an enumeration, it does not mint an identifier."""
    payload = empty_payload()
    payload["measurements"] = [
        {
            "product_id": "YAA:PRODUCT:isobutanol-but-better",
            "product_as_reported": "isobutanol",
            "quantity_kind": "titer",
            "value": 1.0,
            "unit": "g/L",
            "source_locator": "text",
            "span": {"quote": "x", "char_start": 0, "char_end": 1},
        }
    ]
    assert check_json_schema(payload, payload_schema(vocabulary))


def test_the_payload_schema_requires_a_span_on_every_record(
    vocabulary: PayloadVocabulary,
) -> None:
    payload = empty_payload()
    payload["strains"] = [{"name_as_reported": "IBA-7", "role": "engineered"}]
    errors = check_json_schema(payload, payload_schema(vocabulary))
    assert any("span" in error for error in errors)


def test_no_vocabulary_value_is_written_in_the_schema_module() -> None:
    """Adding a product must not mean editing code (CONVENTIONS.md, 'Code')."""
    source = (REPO_ROOT / "src" / "fermdb" / "extract" / "schemas.py").read_text(encoding="utf-8")
    assert "YAA:PRODUCT:" not in source
    assert "A_native_split" not in source


def test_an_empty_vocabulary_is_refused_rather_than_widened() -> None:
    with pytest.raises(SchemaBuildError):
        PayloadVocabulary(
            product_ids=(),
            units=("g/L",),
            bases=("consumed",),
            modification_types=("knockout",),
            quantity_kinds=("titer",),
            compartments=("cytosol",),
            compartment_strategies=("A_native_split",),
            condition_facets=("temperature_c",),
        )


def test_section_specs_and_record_kinds_stay_in_step(vocabulary: PayloadVocabulary) -> None:
    assert tuple(section.key for section in payload_sections(vocabulary)) == RECORD_KINDS


def _section(vocabulary: PayloadVocabulary, key: str) -> Any:
    return {section.key: section for section in payload_sections(vocabulary)}[key]


def _expression_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "part_as_reported": "alsS from Bacillus subtilis",
        "host_as_reported": "E. coli BL21(DE3)",
        "expressed_ok": "yes",
        "activity_measured": "no",
        "span": {"quote": "x", "char_start": 0, "char_end": 1},
    }
    record.update(overrides)
    return record


def test_a_part_expression_record_must_name_its_part_its_host_and_both_outcomes(
    vocabulary: PayloadVocabulary,
) -> None:
    """PLAN.md G.6 is one row per demonstrated host/compartment, and these four fields are the row.

    Each omission is a different claim rather than a weaker one. Without a host the record says
    only that somebody expressed something somewhere, which is the merge G.6 exists to refuse;
    without `activity_measured` a Western blot stands in for an assay.
    """
    section = _section(vocabulary, "part_expression_records")
    assert set(section.record_schema()["required"]) == {
        "part_as_reported",
        "host_as_reported",
        "expressed_ok",
        "activity_measured",
        "span",
    }
    payload = empty_payload()
    payload["part_expression_records"] = [_expression_record()]
    assert check_json_schema(payload, payload_schema(vocabulary)) == []

    payload["part_expression_records"] = [
        {k: v for k, v in _expression_record().items() if k != "host_as_reported"}
    ]
    assert check_json_schema(payload, payload_schema(vocabulary))


def test_a_band_on_a_gel_cannot_be_reported_as_partial_activity(
    vocabulary: PayloadVocabulary,
) -> None:
    """`expressed_ok` and `activity_measured` take different answers because they are different
    questions.

    A protein can be truncated, insoluble or partly processed, so expression has a 'partial'.
    "Did you assay what it does" has no half-way, and `part_expression_record`'s CHECK agrees --
    so a model offered 'partial' for activity would be offered a value the table cannot store.
    """
    fields = {
        field.name: field.schema for field in _section(vocabulary, "part_expression_records").fields
    }
    assert "partial" in fields["expressed_ok"]["enum"]
    assert "partial" not in fields["activity_measured"]["enum"]

    payload = empty_payload()
    payload["part_expression_records"] = [_expression_record(activity_measured="partial")]
    assert check_json_schema(payload, payload_schema(vocabulary))


def test_the_part_expression_section_never_asks_the_model_for_a_catalog_id(
    vocabulary: PayloadVocabulary,
) -> None:
    """The model reports the paper's words; resolving them onto a `part` row is a curator's act.

    PLAN.md L.1.2 has the model select wherever the atlas can enumerate, and this is the case
    where it must not: `part` is curated data that grows and is empty until `fermdb atlas
    pathways` runs, and every identity claim in it is Zone I and 'unverified'. An enum over it
    would make the schema unbuildable on a database that can otherwise extract perfectly well,
    and would invite the closest-looking match for a paper about a seventeenth enzyme.
    """
    names = _section(vocabulary, "part_expression_records").field_names
    assert "part_id" not in names
    assert "outcome_measurement_id" not in names
    assert "part_as_reported" in names


def test_record_path_is_the_address_used_everywhere() -> None:
    assert record_path("measurements", 3) == "measurements[3]"
    with pytest.raises(KeyError):
        record_path("not_a_kind", 0)


def test_the_typed_record_reads_a_validated_payload_record() -> None:
    excerpt = excerpt_of()
    record = MeasurementRecord.from_mapping(truthful_payload(excerpt)["measurements"][0])
    assert record.value == 22.6
    assert record.unit == "g/L"
    assert record.span.quote.startswith("22.6")


# -------------------------------------------------------------------------------- the happy path


def test_a_truthful_extraction_is_stored_as_a_proposal(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    outcome = extract(conn, settings, config, provider_returning(truthful_payload(excerpt)))

    assert outcome.extraction_id is not None
    assert outcome.record_count == 7
    assert outcome.counts_by_kind["measurements"] == 2

    row = conn.execute("SELECT * FROM extraction WHERE id = ?", (outcome.extraction_id,)).fetchone()
    assert row["zone"] == "I"
    assert row["review_state"] == "proposed"
    assert row["curator"] is None
    assert row["section"] == "methods,results"
    assert row["prompt_version"].startswith("extraction/v1+")
    assert row["extractor"] == "fermdb.extract.harness"
    assert row["input_hash"]


def test_a_record_cannot_claim_its_own_confidence(vocabulary: PayloadVocabulary) -> None:
    """MODEL_ROUTING.md 5.2, made unrepresentable rather than merely overridden.

    The validator would force `unverified` anyway. The schema goes further and gives the model
    nowhere to put the claim, so a per-record confidence never exists even transiently.
    """
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["measurements"][0]["confidence"] = "high"
    errors = check_json_schema(payload, payload_schema(vocabulary))
    assert any("confidence" in error for error in errors)


def test_every_stored_value_carries_confidence_unverified(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """Zone, review state and confidence are written by the validator, never by the model."""
    excerpt = excerpt_of()
    outcome = extract(conn, settings, config, provider_returning(truthful_payload(excerpt)))

    stored = json.loads(
        conn.execute(
            "SELECT payload FROM extraction WHERE id = ?", (outcome.extraction_id,)
        ).fetchone()["payload"]
    )
    seen = 0
    for kind in RECORD_KINDS:
        for record in stored[kind]:
            assert record["confidence"] == "unverified"
            assert record["zone"] == "I"
            assert record["review_state"] == "proposed"
            seen += 1
    assert seen == outcome.record_count


def test_stored_spans_use_document_offsets_that_really_resolve(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """The offsets the model gave were into the excerpt. What is stored must index the paper."""
    excerpt = excerpt_of()
    outcome = extract(conn, settings, config, provider_returning(truthful_payload(excerpt)))

    rows = conn.execute(
        "SELECT * FROM span WHERE extraction_id = ? ORDER BY record_path",
        (outcome.extraction_id,),
    ).fetchall()
    assert len(rows) == outcome.record_count
    for row in rows:
        assert DOCUMENT[row["char_start"] : row["char_end"]] == row["quoted_text"]
        assert row["section"] in ("methods", "results")
        assert row["zone"] == "I"
        assert row["record_path"]


def test_the_stored_payload_holds_document_offsets_not_excerpt_offsets(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    proposed = truthful_payload(excerpt)
    outcome = extract(conn, settings, config, provider_returning(proposed))
    stored = json.loads(
        conn.execute(
            "SELECT payload FROM extraction WHERE id = ?", (outcome.extraction_id,)
        ).fetchone()["payload"]
    )
    sent = proposed["measurements"][0]["span"]
    kept = stored["measurements"][0]["span"]
    assert kept["char_start"] != sent["char_start"]
    assert DOCUMENT[kept["char_start"] : kept["char_end"]] == kept["quote"]


def test_only_methods_and_results_reach_the_model(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """PLAN.md V.4. The discussion's own numbers must not be in the prompt at all."""
    excerpt = excerpt_of()
    provider = provider_returning(truthful_payload(excerpt))
    extract(conn, settings, config, provider)
    prompt = provider.calls[0][0]
    assert "The engineered strain IBA-7 produced" in prompt
    assert "0.63 g/L in a cytosolic strain" not in prompt  # introduction
    assert "highest reported for this configuration" not in prompt  # discussion


# ------------------------------------------------------------------------------- the failure path


def test_a_hallucinated_quote_takes_the_whole_extraction_down(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """The single check PLAN.md calls the most valuable one, through the whole harness."""
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["measurements"][0]["span"] = {
        "quote": "the strain produced 48.0 g/L isobutanol",
        "char_start": 10,
        "char_end": 49,
    }
    with pytest.raises(LlmValidationError):
        extract(conn, settings, config, provider_returning(payload))
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM span").fetchone()[0] == 0


def test_a_yield_above_the_theoretical_maximum_is_rejected(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["measurements"][1]["value"] = 0.95  # isobutanol from glucose maxes at 0.411 g/g
    with pytest.raises(LlmValidationError) as excinfo:
        extract(conn, settings, config, provider_returning(payload))
    assert "theoretical maximum" in str(excinfo.value)
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 0


def test_a_quote_that_exists_only_outside_the_excerpt_is_rejected(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """A real sentence from the discussion is still not evidence the model was shown."""
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    quote = "The titer is the highest reported"
    payload["strains"][0]["span"] = {
        "quote": quote,
        "char_start": DOCUMENT.index(quote),
        "char_end": DOCUMENT.index(quote) + len(quote),
    }
    with pytest.raises(LlmValidationError):
        extract(conn, settings, config, provider_returning(payload))


def test_nothing_partial_is_stored_when_one_record_fails(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """Six good records and one bad one store nothing. Half-validated output must not look
    like validated output once it is in the same table.

    The bad record fabricates its quote. A merely *misplaced* quote no longer fails -- offsets are
    recomputed from the text now, because models cannot count characters -- so the failure this
    test needs is the one that still matters: text that is not in the paper at all.
    """
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["bottlenecks"][0]["span"]["quote"] = "a sentence the authors never wrote"
    with pytest.raises(LlmValidationError):
        extract(conn, settings, config, provider_returning(payload))
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 0


def test_the_model_gets_exactly_one_retry_with_the_errors_fed_back(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    bad = truthful_payload(excerpt)
    bad["measurements"][0]["span"] = {"quote": "not in the paper", "char_start": 0, "char_end": 16}
    provider = provider_returning(bad, truthful_payload(excerpt))

    outcome = extract(conn, settings, config, provider)
    assert outcome.stats.attempts == 2
    assert len(provider.calls) == 2
    assert "rejected by a deterministic validator" in provider.calls[1][0]
    assert outcome.failed_attempts and outcome.failed_attempts[0]

    validation = json.loads(
        conn.execute(
            "SELECT validation FROM extraction WHERE id = ?", (outcome.extraction_id,)
        ).fetchone()["validation"]
    )
    assert validation["attempts"] == 2
    assert validation["failed_attempts"]


def test_extraction_refuses_to_invent_a_publication_row(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """A publication row is Zone R, and PLAN.md L.5 forbids an agent from writing there."""
    excerpt = excerpt_of()
    with pytest.raises(ExtractionError) as excinfo:
        extract_publication(
            conn,
            publication_id="pmid:99999999",
            source_text=DOCUMENT,
            provider=provider_returning(truthful_payload(excerpt)),
            config=config,
            settings=settings,
        )
    assert "L.5" in str(excinfo.value)
    assert conn.execute("SELECT COUNT(*) FROM publication").fetchone()[0] == 1


def test_a_dry_run_validates_and_writes_nothing(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    outcome = extract(
        conn, settings, config, provider_returning(truthful_payload(excerpt)), write=False
    )
    assert outcome.extraction_id is None
    assert outcome.record_count == 7
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 0


# ----------------------------------------------------------------------------------------- cache


def test_a_cached_result_is_revalidated_before_it_is_stored(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """A cache hit skips post_validate inside `run`, so the harness checks it again itself."""
    excerpt = excerpt_of()
    cache = MemoryCache()
    provider = provider_returning(truthful_payload(excerpt))

    first = extract(conn, settings, config, provider, cache=cache)
    second = extract(conn, settings, config, provider, cache=cache)

    assert len(provider.calls) == 1  # the second run never reached the model
    assert second.stats.cache_hit is True
    assert second.record_count == first.record_count
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 2


# -------------------------------------------------------------------------------- source text


def test_load_source_text_refuses_an_unreadable_pdf(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """Rewritten 2026-09-21: PDFs are now read, but an unreadable one is still refused.

    This test used to assert that every PDF was refused, because no extractor was wired in.
    `extract.pdf` changed that -- so the assertion it encoded is now the wrong behaviour, and the
    failure was correct. What survives is the reason the old refusal existed: a PDF whose bytes
    do not yield prose must never be decoded anyway, because the result is quotable garbage.
    """
    relative = Path("fulltext") / "aa" / "aa.pdf"
    target = settings.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.7\nnot really a pdf")
    conn.execute(
        "INSERT INTO fulltext_asset (id, publication_id, pmid, oa_status, resolved_via, "
        "storage_state, content_path, checksum_sha256, media_type, source_url, retrieved_at, "
        "zone) VALUES ('YAA:FTA:t', ?, '11112222', 'gold', 'pmc', 'stored_fulltext', ?, "
        "'deadbeef', 'application/pdf', 'https://example.invalid/x', '2026-01-01T00:00:00+00:00',"
        " 'R')",
        (PUBLICATION_ID, str(relative)),
    )
    conn.commit()
    with pytest.raises(ExtractionError) as excinfo:
        load_source_text(conn, settings, publication_id=PUBLICATION_ID)
    # The message names the publication, so a batch failure is actionable.
    assert PUBLICATION_ID in str(excinfo.value)


def test_load_source_text_says_what_to_do_when_there_is_none(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        load_source_text(conn, settings, publication_id=PUBLICATION_ID)
    assert "manual-queue" in str(excinfo.value)


def test_find_publication_matches_by_pmid_and_by_doi(conn: sqlite3.Connection) -> None:
    assert find_publication(conn, pmid="11112222")["id"] == PUBLICATION_ID
    assert find_publication(conn, pmid="404") is None


# ------------------------------------------------------- the case trap on the read side
#
# `publication.id` is stored as 'doi:' || lower(doi); `publication.doi` keeps the publisher's
# own casing. Measured on the live atlas 2026-09-22: 0 of 5,164 ids are non-lowercase, while
# 625 of the 4,864 DOI-keyed rows (12.9%) have a non-lowercase `doi`. Minting folded; reading
# did not, so one DOI in eight, typed off the paper it came from, resolved to nothing — and
# said so by blaming a cause ("not open access / never fetched") that was not among the
# options.

AEM_DOI = "10.1128/AEM.00588-21"  # a real, publisher-cased DOI from this atlas
AEM_ID = "doi:10.1128/aem.00588-21"


def _publisher_cased_publication(conn: sqlite3.Connection, *, with_fulltext: Path | None) -> None:
    """One publication stored the way the atlas stores them: lowercased id, publisher-cased doi."""
    conn.execute(
        "INSERT INTO publication (id, doi, title, year, zone, evidence, confidence) "
        "VALUES (?, ?, 'Publisher-cased paper', 2021, 'R', 'test fixture', 'unverified')",
        (AEM_ID, AEM_DOI),
    )
    if with_fulltext is not None:
        conn.execute(
            "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
            "storage_state, content_path, checksum_sha256, media_type, source_url, retrieved_at, "
            "zone) VALUES ('YAA:FTA:aem', ?, ?, 'gold', 'pmc', 'stored_fulltext', ?, 'cafe', "
            "'text/plain', 'https://example.invalid/aem', '2026-01-01T00:00:00+00:00', 'R')",
            (AEM_ID, AEM_DOI, str(with_fulltext)),
        )
    conn.commit()


def test_a_publisher_cased_doi_resolves_to_its_stored_full_text(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The headline fix. `10.1128/AEM.00588-21` is how this DOI is printed on the paper and how a
    caller types it into `--publication-id`; `doi:10.1128/aem.00588-21` is how the atlas stores
    it. Before the fold, that one keystroke difference was reported as the paper not being open
    access."""
    relative = Path("fulltext") / "aem" / "aem.txt"
    target = settings.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, not write_text: the latter translates newlines on Windows and the assertion
    # below is an exact round-trip of the stored bytes.
    target.write_bytes(DOCUMENT.encode("utf-8"))
    _publisher_cased_publication(conn, with_fulltext=relative)

    text, origin = load_source_text(conn, settings, publication_id=f"doi:{AEM_DOI}")
    assert text == DOCUMENT
    assert origin.endswith("aem.txt")


def test_the_fold_reaches_the_same_row_from_either_casing(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Both spellings are the same publication, so both must reach the same asset — otherwise the
    fold has merely moved which casing is the broken one."""
    relative = Path("fulltext") / "aem" / "aem.txt"
    target = settings.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, not write_text: the latter translates newlines on Windows and the assertion
    # below is an exact round-trip of the stored bytes.
    target.write_bytes(DOCUMENT.encode("utf-8"))
    _publisher_cased_publication(conn, with_fulltext=relative)

    upper = load_source_text(conn, settings, publication_id=f"DOI:{AEM_DOI}")
    lower = load_source_text(conn, settings, publication_id=AEM_ID)
    assert upper == lower


def test_an_unknown_publication_is_not_blamed_on_open_access(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Case one of three. Nothing in the atlas has this id in any casing, so the remedy is
    discovery, not the manual download queue — and extraction must not create the row itself."""
    with pytest.raises(SourceTextError) as excinfo:
        load_source_text(conn, settings, publication_id="doi:10.9999/nobody.1")
    message = str(excinfo.value)
    assert "no publication row" in message
    assert "literature discover" in message
    assert "manual-queue" not in message


def test_a_known_publication_with_no_asset_says_the_row_exists(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Case two of three, and the only one the old message was ever right about. It now says the
    publication row exists, so the reader knows the gap is acquisition and not discovery."""
    with pytest.raises(SourceTextError) as excinfo:
        load_source_text(conn, settings, publication_id=PUBLICATION_ID)
    message = str(excinfo.value)
    assert "manual-queue" in message
    assert "publication row exists" in message


def test_a_mis_cased_id_that_still_has_no_full_text_says_the_casing_was_not_the_problem(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Case three of three, and the one that keeps the fix honest. The caller's id was mis-cased
    *and* there is no stored text. Reporting only the acquisition gap would leave them wondering
    whether their casing was the real fault; reporting only the casing would send them chasing a
    spelling that had already been resolved."""
    _publisher_cased_publication(conn, with_fulltext=None)
    with pytest.raises(SourceTextError) as excinfo:
        load_source_text(conn, settings, publication_id=f"doi:{AEM_DOI}")
    message = str(excinfo.value)
    assert AEM_ID in message
    assert "case-folded" in message
    assert "manual-queue" in message


def test_find_publication_matches_a_doi_in_the_other_casing(conn: sqlite3.Connection) -> None:
    """`--doi` reaches `find_publication`, which built its id term by pasting the caller's string
    after 'doi:'. For a row whose stored `doi` is publisher-cased, a caller passing the lowercase
    form matched neither column."""
    _publisher_cased_publication(conn, with_fulltext=None)
    assert find_publication(conn, doi=AEM_DOI)["id"] == AEM_ID
    assert find_publication(conn, doi=AEM_DOI.lower())["id"] == AEM_ID
    assert find_publication(conn, doi="10.9999/nobody.1") is None


# ------------------------------------------------------------------------------------------- cli


def test_the_cli_exposes_extract_run_and_the_curate_verbs() -> None:
    from fermdb.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["extract", "run", "--pmid", "123", "--dry-run"])
    assert args.pmid == "123" and args.dry_run is True
    for verb in ("next", "stats"):
        assert parser.parse_args(["curate", verb]) is not None
    verdict = parser.parse_args(
        ["curate", "accept", "--task", "t", "--curator", "me", "--reason", "checked"]
    )
    assert verdict.curator == "me" and verdict.reason == "checked"


def test_the_cli_requires_a_reason_for_a_verdict() -> None:
    """A verdict with no reason cannot be reviewed later, so argparse refuses it."""
    from fermdb.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["curate", "reject", "--task", "t", "--curator", "me"])


# ---------------------------------------------------------------------------------------------
# Reviews.
#
# 21 of the 279 open-access articles acquisition fetched (7.5%) are reviews: the discovery
# queries match them on topic exactly as well as they match primary papers. A review has no
# methods and no results, so it already failed sectioning -- but it failed with advice to resend
# it whole, which is the one thing that must not happen to a review.
# ---------------------------------------------------------------------------------------------


def _sections_named(*names: str) -> list[Section]:
    """Sections with the given names over a throwaway document."""
    return [
        Section(name=name, char_start=index * 10, char_end=index * 10 + 10)
        for index, name in enumerate(names)
    ]


def test_looks_like_review_needs_narrative_sections_and_no_findings() -> None:
    assert looks_like_review(_sections_named("abstract", "introduction", "conclusion")) is True
    # A research paper is not a review, even when only some of its findings sections parsed.
    assert looks_like_review(_sections_named("abstract", "introduction", "results")) is False
    # Neither is a fragment: no narrative sections either, so the remedy is re-reading it.
    assert looks_like_review(_sections_named("front_matter", "references")) is False


def test_build_excerpt_refuses_a_review_without_offering_a_way_round() -> None:
    """The generic failure suggests resending the whole text; for a review that is the hazard.

    The message still names `unsectioned` -- an operator who knows the flag exists will reach for
    it, so saying "deliberately not offering it" pre-empts that, where silence would not.
    """
    sections = _sections_named("front_matter", "abstract", "introduction", "conclusion")
    with pytest.raises(NotPrimaryResearchError) as raised:
        build_excerpt("x" * 100, sections, DEFAULT_EXTRACTION_SECTIONS)

    message = str(raised.value)
    assert "review" in message
    assert f"not offering '{UNSECTIONED}'" in message
    # Why it is refused, not just that it is: the span would verify and still be false.
    assert "cites" in message


def test_build_excerpt_still_suggests_unsectioned_for_a_genuine_fragment() -> None:
    """A document whose headings were lost has the opposite remedy, and keeps the old advice."""
    with pytest.raises(SectioningError) as raised:
        build_excerpt("x" * 100, _sections_named("front_matter"), DEFAULT_EXTRACTION_SECTIONS)
    assert not isinstance(raised.value, NotPrimaryResearchError)
    assert UNSECTIONED in str(raised.value)


# ---------------------------------------------------------------------------------------------
# Chunking.
#
# One real paper's methods and results come to 60,000 characters, about 20,000 tokens with the
# schema (MODEL_ROUTING.md 7c). A 27B model answers that in four minutes or not at all. The
# property that makes chunking safe is that a window is itself an Excerpt, so offsets coming back
# from one are already document offsets -- there is no second coordinate system.
# ---------------------------------------------------------------------------------------------


def test_split_returns_the_excerpt_itself_when_it_already_fits() -> None:
    excerpt = excerpt_of()
    assert excerpt.split(100_000) == (excerpt,)


def test_every_window_translates_its_own_offsets_back_to_the_document() -> None:
    """The load-bearing property: a quote found in a window resolves in the document."""
    excerpt = excerpt_of()
    windows = excerpt.split(400, overlap=100)
    assert len(windows) > 1

    checked = 0
    for window in windows:
        for piece in window.pieces:
            # Take a real substring of this window and translate it.
            quote = window.text[piece.exc_start : piece.exc_end][:40]
            if len(quote) < 10:
                continue
            start = window.text.index(quote)
            translated = window.to_document(start, start + len(quote))
            assert translated is not None
            doc_start, doc_end = translated
            assert DOCUMENT[doc_start:doc_end] == quote
            checked += 1
    assert checked, "no window yielded a checkable span"


def test_windows_cover_the_whole_excerpt() -> None:
    """Nothing may fall between two windows -- a lost paragraph is a silent false negative."""
    excerpt = excerpt_of()
    windows = excerpt.split(300, overlap=80)
    rebuilt = windows[0].text
    for window in windows[1:]:
        # Each window overlaps the previous, so its text must continue from somewhere inside it.
        assert window.text[:20] in rebuilt[-200:] or rebuilt.endswith(window.text[:20])
        overlap_at = rebuilt.rfind(window.text[:40])
        rebuilt = rebuilt[:overlap_at] + window.text if overlap_at != -1 else rebuilt + window.text
    assert rebuilt == excerpt.text


def test_windows_overlap_so_a_boundary_sentence_survives() -> None:
    excerpt = excerpt_of()
    windows = excerpt.split(300, overlap=150)
    assert len(windows) > 1
    first, second = windows[0], windows[1]
    # The tail of one window reappears at the head of the next, so a measurement sentence
    # straddling the cut is seen whole at least once.
    assert first.text[-100:] in second.text


def test_a_window_keeps_only_the_sections_it_contains() -> None:
    excerpt = excerpt_of()
    windows = excerpt.split(300, overlap=0)
    for window in windows:
        assert window.pieces, "a window with no pieces can produce no translatable span"
        for piece in window.pieces:
            assert 0 <= piece.exc_start < piece.exc_end <= len(window.text)
            assert piece.doc_end - piece.doc_start == piece.exc_end - piece.exc_start


def test_split_rejects_nonsense_bounds() -> None:
    excerpt = excerpt_of()
    with pytest.raises(ValueError, match="max_chars must be positive"):
        excerpt.split(0)
    with pytest.raises(ValueError, match="overlap must be in"):
        excerpt.split(100, overlap=100)


def test_a_long_document_is_extracted_window_by_window_and_merged(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """Every window's records land in one payload, renumbered against it.

    The provider answers each window with whatever truthful records that window can support, so
    this also pins the property that matters: a record found in window 3 carries *document*
    offsets, indistinguishable from one found in window 1.
    """
    excerpt = excerpt_of()
    windows = excerpt.split(200, overlap=60)
    assert len(windows) >= 3

    quote = "The engineered strain IBA-7"

    def reply(prompt: str, _model: str, _schema: Mapping[str, Any] | None) -> str:
        # Offsets must be into the window the model was shown, so identify it by its own text.
        payload = empty_payload()
        shown = next((w.text for w in windows if w.text and w.text in prompt), None)
        if shown is not None and quote in shown:
            start = shown.index(quote)
            payload["strains"] = [
                {
                    "name_as_reported": "IBA-7",
                    "role": "engineered",
                    "span": {"quote": quote, "char_start": start, "char_end": start + len(quote)},
                }
            ]
        return json.dumps(payload)

    outcome = extract_publication(
        conn,
        publication_id=PUBLICATION_ID,
        source_text=DOCUMENT,
        provider=MockProvider(handler=reply),
        config=config,
        settings=settings,
        max_excerpt_chars=200,
        window_overlap=60,
        write=False,
    )

    strains = outcome.payload["strains"]
    # Seen twice through the overlap, stored once.
    assert len(strains) == 1
    span = strains[0]["span"]
    assert DOCUMENT[span["char_start"] : span["char_end"]] == "The engineered strain IBA-7"
    # One RunStats covering every window, not just the last.
    assert outcome.stats.attempts >= len(windows)


def test_one_strain_quoted_differently_in_two_windows_is_still_one_strain(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """The duplicate the whole-record key could not see.

    The test above has the model return the *same* quote in both windows, so the records serialise
    identically and any key catches them. Real models do not do that: asked about the overlap they
    quote whichever sentence is in front of them, so the span differs, the JSON differs, and the
    duplicate survives into the curation queue as a second task for the same strain.

    Measured on `doi:10.1016/j.ymben.2012.11.008`: 85 strain proposals for 53 distinct strains.
    """
    excerpt = excerpt_of()
    windows = excerpt.split(200, overlap=60)
    assert len(windows) >= 3

    # Two different true sentences about the same strain, each in a different window.
    quotes = ("The engineered strain IBA-7", "strain IBA-7")

    def reply(prompt: str, _model: str, _schema: Mapping[str, Any] | None) -> str:
        payload = empty_payload()
        shown = next((w.text for w in windows if w.text and w.text in prompt), None)
        if shown is None:
            return json.dumps(payload)
        for quote in quotes:
            if quote in shown:
                start = shown.index(quote)
                payload["strains"] = [
                    {
                        "name_as_reported": "IBA-7",
                        "role": "engineered",
                        "span": {
                            "quote": quote,
                            "char_start": start,
                            "char_end": start + len(quote),
                        },
                    }
                ]
                break
        return json.dumps(payload)

    outcome = extract_publication(
        conn,
        publication_id=PUBLICATION_ID,
        source_text=DOCUMENT,
        provider=MockProvider(handler=reply),
        config=config,
        settings=settings,
        max_excerpt_chars=200,
        window_overlap=60,
        write=False,
    )
    assert [s["name_as_reported"] for s in outcome.payload["strains"]] == ["IBA-7"]


def test_a_blank_identity_field_does_not_collapse_unrelated_records() -> None:
    """A strain the model failed to name cannot identify anything, so it must not act as a key."""
    from fermdb.extract.harness import _identity_of

    first = {"name_as_reported": "", "role": "engineered", "span": {"quote": "a"}}
    second = {"name_as_reported": "", "role": "parent", "span": {"quote": "b"}}
    assert _identity_of("strains", first) != _identity_of("strains", second)
    # And a named one is identified by its name alone, whatever else differs.
    named_a = {"name_as_reported": "CEN.PK113-7D", "span": {"quote": "a"}}
    named_b = {"name_as_reported": "cen.pk113-7d ", "span": {"quote": "b"}}
    assert _identity_of("strains", named_a) == _identity_of("strains", named_b)


def test_measurements_keep_the_whole_record_identity() -> None:
    """Two measurements with the same number may be different measurements. Deliberate."""
    from fermdb.extract.harness import _identity_of

    one = {"strain_name_as_reported": "X", "value": 1.0, "span": {"quote": "a"}}
    two = {"strain_name_as_reported": "X", "value": 1.0, "span": {"quote": "b"}}
    assert _identity_of("measurements", one) != _identity_of("measurements", two)


def test_merged_records_are_renumbered_against_the_merged_payload() -> None:
    """record_path must mean the same thing on the span row, the task and the payload."""
    from fermdb.extract.harness import _normalized_payload

    records = [("strains", 0, {"a": 1}), ("strains", 1, {"a": 2}), ("measurements", 0, {"b": 3})]
    payload = _normalized_payload({"self_confidence": "low"}, records)
    assert [r["a"] for r in payload["strains"]] == [1, 2]
    assert len(payload["measurements"]) == 1


def test_a_papers_confidence_is_its_least_confident_window() -> None:
    """A paper is extracted as well as its worst window, not its best."""
    from fermdb.extract.harness import _least_confident

    class _R:
        def __init__(self, value: str | None) -> None:
            self.value = {"self_confidence": value} if value else {}

    assert _least_confident([_R("high"), _R("low"), _R("medium")]) == "low"
    assert _least_confident([_R("high"), _R("high")]) == "high"
    assert _least_confident([_R(None)]) is None
    # An unrecognized value is not evidence of confidence.
    assert _least_confident([_R("high"), _R("certain")]) == "certain"


# ---------------------------------------------------------------------------------------------
# Span repair.
#
# Measured on a real paper with a 7B local model: all 22 records came back with verbatim,
# genuinely-present quotes and offsets wrong by a handful of characters. verify_span rejected
# every one while its own message read "the quote does occur at [2912]". The extraction was
# correct; only the arithmetic was not.
# ---------------------------------------------------------------------------------------------


def test_a_misplaced_but_real_quote_is_relocated_and_stored(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["measurements"][0]["span"]["char_start"] += 7
    payload["measurements"][0]["span"]["char_end"] += 7

    outcome = extract(conn, settings, config, provider_returning(payload))

    span = outcome.payload["measurements"][0]["span"]
    assert DOCUMENT[span["char_start"] : span["char_end"]] == "22.6 g/L isobutanol after 72 h"
    # The repair is recorded, not silent: a curator must see the position was computed.
    codes = [note.code for note in outcome.notes]
    assert "span_offsets_repaired" in codes


def test_a_fabricated_quote_is_still_rejected(
    conn: sqlite3.Connection, settings: Settings, config: LlmConfig
) -> None:
    """The check that stops an invented measurement is untouched by the repair."""
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["measurements"][0]["span"] = {
        "quote": "produced 999 g/L isobutanol",
        "char_start": 100,
        "char_end": 127,
    }
    with pytest.raises(LlmValidationError, match="does not occur"):
        extract(conn, settings, config, provider_returning(payload))
    assert conn.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 0


def test_relocate_span_prefers_the_occurrence_nearest_the_claim() -> None:
    from fermdb.llm import relocate_span
    from fermdb.llm.validate import Span

    text = "the titer rose. the titer rose. the titer rose."
    moved = relocate_span(text, Span(quote="the titer rose", char_start=30, char_end=44))
    assert moved is not None
    span, note = moved
    assert span.char_start == 32  # the third occurrence, nearest to the claimed 30
    assert text[span.char_start : span.char_end] == "the titer rose"
    assert "occurs 3 times" in note


def test_relocate_span_reports_an_unambiguous_move() -> None:
    from fermdb.llm import relocate_span
    from fermdb.llm.validate import Span

    text = "the strain produced 22.6 g/L isobutanol"
    moved = relocate_span(text, Span(quote="22.6 g/L", char_start=0, char_end=8))
    assert moved is not None
    span, note = moved
    assert text[span.char_start : span.char_end] == "22.6 g/L"
    assert "exactly once" in note


def test_relocate_span_refuses_a_quote_that_is_not_there() -> None:
    from fermdb.llm import relocate_span
    from fermdb.llm.validate import Span

    assert relocate_span("real text", Span(quote="invented", char_start=0, char_end=8)) is None
