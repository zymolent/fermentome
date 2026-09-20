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
    PayloadVocabulary,
    PromptError,
    SchemaBuildError,
    SectioningError,
    build_excerpt,
    extract_publication,
    find_publication,
    load_prompt,
    load_source_text,
    load_vocabulary,
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
            compartments=("cytosol",),
            compartment_strategies=("A_native_split",),
            condition_facets=("temperature_c",),
        )


def test_section_specs_and_record_kinds_stay_in_step(vocabulary: PayloadVocabulary) -> None:
    assert tuple(section.key for section in payload_sections(vocabulary)) == RECORD_KINDS


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
    like validated output once it is in the same table."""
    excerpt = excerpt_of()
    payload = truthful_payload(excerpt)
    payload["bottlenecks"][0]["span"]["char_start"] += 3  # offsets no longer match the quote
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


def test_load_source_text_refuses_a_pdf(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """No PDF text extractor is a dependency, and decoding one anyway produces quotable garbage."""
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
    assert "PDF" in str(excinfo.value)


def test_load_source_text_says_what_to_do_when_there_is_none(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        load_source_text(conn, settings, publication_id=PUBLICATION_ID)
    assert "manual-queue" in str(excinfo.value)


def test_find_publication_matches_by_pmid_and_by_doi(conn: sqlite3.Connection) -> None:
    assert find_publication(conn, pmid="11112222")["id"] == PUBLICATION_ID
    assert find_publication(conn, pmid="404") is None


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
