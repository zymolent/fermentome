"""LLM extraction: one paper's methods and results in, one proposed Zone I extraction out.

Read :mod:`fermdb.extract.harness` for the mechanism and :mod:`fermdb.extract.schemas` for the
shape of what comes out. The three things worth knowing before using either:

**Only methods and results are sent.** PLAN.md V.4 makes extraction the dominant cost of the whole
project and identifies the fix as a smaller prompt rather than a cheaper model — roughly thirteen
times cheaper across the corpus. :data:`~fermdb.extract.harness.DEFAULT_EXTRACTION_SECTIONS` is
that decision, in one place.

**Every value carries a span, and every span is checked twice.** Once against the excerpt the
model was shown, at the offsets it reported, by
:func:`fermdb.llm.validate.verify_span` — exact comparison, no whitespace normalization, no fuzzy
match. Then again against the whole document after the offsets are translated. Only document
offsets are stored. A record whose span does not resolve is not stored, not flagged: the whole run
fails, once, with the validator's complaints fed back to the model, and then fails for good.

**Nothing here is canonical.** Everything written is Zone I with ``review_state='proposed'``,
``confidence='unverified'`` forced onto every record whatever the model claimed about itself. The
harness refuses to run at all if there is no ``publication`` row, rather than creating one: that
row is Zone R and PLAN.md L.5 forbids an agent from writing there. Promotion is
:mod:`fermdb.curate.queue`'s business, and a human's.

Typical use::

    from fermdb.config import Settings
    from fermdb.db import open_db
    from fermdb.extract import extract_publication, load_source_text
    from fermdb.llm import LlmConfig, build_provider

    settings = Settings.load()
    config = LlmConfig.load(settings)          # 'mock' unless FERMDB_LLM_PROVIDER says otherwise
    conn = open_db(settings.db_file)
    text, _ = load_source_text(conn, settings, publication_id="pmid:12345678")
    outcome = extract_publication(
        conn,
        publication_id="pmid:12345678",
        source_text=text,
        provider=build_provider(config),
        config=config,
        settings=settings,
    )
    print(outcome.summary())
"""

from __future__ import annotations

from .harness import (
    DEFAULT_EXTRACTION_SECTIONS,
    EXTRACTOR,
    EXTRACTOR_VERSION,
    SECTION_NAMES,
    TRIAGE_SCHEMA,
    UNSECTIONED,
    Excerpt,
    ExcerptPiece,
    ExtractionError,
    ExtractionOutcome,
    PromptError,
    PromptFile,
    RecordNote,
    Section,
    SectioningError,
    SourceTextError,
    TriageVerdict,
    build_excerpt,
    extract_publication,
    find_publication,
    load_prompt,
    load_source_text,
    split_sections,
    triage_publication,
    write_extraction,
)
from .schemas import (
    MISSING_CHOICES,
    RECORD_KINDS,
    SPAN_SCHEMA,
    BottleneckRecord,
    ConditionRecord,
    ExtractedSpan,
    FieldSpec,
    MeasurementRecord,
    ModificationRecord,
    PathwayConfigurationRecord,
    PayloadVocabulary,
    SchemaBuildError,
    SectionSpec,
    StrainRecord,
    iter_payload_records,
    load_vocabulary,
    payload_schema,
    payload_sections,
    record_path,
    section_for,
)

__all__ = [
    "DEFAULT_EXTRACTION_SECTIONS",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "MISSING_CHOICES",
    "RECORD_KINDS",
    "SECTION_NAMES",
    "SPAN_SCHEMA",
    "TRIAGE_SCHEMA",
    "UNSECTIONED",
    "BottleneckRecord",
    "ConditionRecord",
    "Excerpt",
    "ExcerptPiece",
    "ExtractedSpan",
    "ExtractionError",
    "ExtractionOutcome",
    "FieldSpec",
    "MeasurementRecord",
    "ModificationRecord",
    "PathwayConfigurationRecord",
    "PayloadVocabulary",
    "PromptError",
    "PromptFile",
    "RecordNote",
    "SchemaBuildError",
    "Section",
    "SectionSpec",
    "SectioningError",
    "SourceTextError",
    "StrainRecord",
    "TriageVerdict",
    "build_excerpt",
    "extract_publication",
    "find_publication",
    "iter_payload_records",
    "load_prompt",
    "load_source_text",
    "load_vocabulary",
    "payload_schema",
    "payload_sections",
    "record_path",
    "section_for",
    "split_sections",
    "triage_publication",
    "write_extraction",
]
