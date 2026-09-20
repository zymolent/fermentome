"""The LLM layer: three interchangeable providers, one validated run function, one validator.

The order of those three matters, and it is the reverse of the intuitive one.
``docs/reference/MODEL_ROUTING.md`` §3 is the argument:

    Capability increases the plausibility of errors. A stronger model produces wrong facts that
    survive human review *longer*, because they read better and cohere with their surroundings.

So the model tier is not what makes extraction safe. :mod:`fermdb.llm.validate` is — verbatim
spans re-checked at their character offsets, units parsed against the vocabulary, yields held
under the theoretical maximum for their (product, substrate) pair, entity ids resolved, and
confidence forced to ``unverified`` no matter what the model claimed. Every one of those checks
returns the same verdict regardless of which model produced the text, which is exactly the
property that makes them worth trusting. Spend on validators before spending on tier.

Everything produced here is Zone I with ``review_state='proposed'`` (CONVENTIONS.md, "Data
zones"). Nothing in this package writes to Zone R or Zone H, assigns an evidence level, resolves
a conflict, or promotes anything (PLAN.md L.5).

Typical use::

    from fermdb.config import Settings
    from fermdb.llm import LlmConfig, build_provider, run
    from fermdb.llm import load_theoretical_yields, load_units, validate_records

    settings = Settings.load()
    config = LlmConfig.load(settings)             # FERMDB_LLM_* over documented defaults
    provider = build_provider(config)             # 'mock' unless configured otherwise
    units = load_units(settings)
    yields = load_theoretical_yields(settings)

    def check(payload: dict[str, object]) -> list[str]:
        report = validate_records(
            payload["measurements"], source_text=paper_text, units=units, yields=yields
        )
        return [i.message for v in report.rejected for i in v.fatal_issues]

    result = run(
        prompt,
        schema,
        provider=provider,
        model=config.model_for("extraction"),
        prompt_version="measurement/v1",
        post_validate=check,
    )
"""

from __future__ import annotations

from .providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MODELS,
    DEFAULT_OPTIONS,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT_S,
    MODEL_ROLES,
    PROVIDER_NAMES,
    ApiProvider,
    Completion,
    HttpRequest,
    LlmConfig,
    MockProvider,
    OllamaProvider,
    Provider,
    ProviderConfigError,
    ProviderError,
    ProviderResponseError,
    ProviderUnavailableError,
    Transport,
    build_provider,
)
from .runtime import (
    CacheEntry,
    CacheKey,
    FileCache,
    LlmError,
    LlmResponseError,
    LlmValidationError,
    MemoryCache,
    NullCache,
    ResultCache,
    RunResult,
    RunStats,
    input_hash,
    run,
)
from .validate import (
    CONFIDENCE_VALUES,
    ISSUE_CODES,
    MODEL_CONFIDENCE,
    MODEL_REVIEW_STATE,
    MODEL_ZONE,
    SPAN_REJECTION_REASONS,
    EntityResolver,
    RecordIssue,
    RecordVerdict,
    SchemaError,
    Span,
    SpanFormatError,
    SpanVerdict,
    TheoreticalYield,
    TheoreticalYields,
    UnitTable,
    UnitVerdict,
    ValidationReport,
    check_json_schema,
    load_theoretical_yields,
    load_units,
    relocate_span,
    resolver_from_ids,
    validate_records,
    verify_span,
)

__all__ = [
    "CONFIDENCE_VALUES",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODELS",
    "DEFAULT_OPTIONS",
    "DEFAULT_PROVIDER",
    "DEFAULT_TIMEOUT_S",
    "ISSUE_CODES",
    "MODEL_CONFIDENCE",
    "MODEL_REVIEW_STATE",
    "MODEL_ROLES",
    "MODEL_ZONE",
    "PROVIDER_NAMES",
    "SPAN_REJECTION_REASONS",
    "ApiProvider",
    "CacheEntry",
    "CacheKey",
    "Completion",
    "EntityResolver",
    "FileCache",
    "HttpRequest",
    "LlmConfig",
    "LlmError",
    "LlmResponseError",
    "LlmValidationError",
    "MemoryCache",
    "MockProvider",
    "NullCache",
    "OllamaProvider",
    "Provider",
    "ProviderConfigError",
    "ProviderError",
    "ProviderResponseError",
    "ProviderUnavailableError",
    "RecordIssue",
    "RecordVerdict",
    "ResultCache",
    "RunResult",
    "RunStats",
    "SchemaError",
    "Span",
    "SpanFormatError",
    "SpanVerdict",
    "TheoreticalYield",
    "TheoreticalYields",
    "Transport",
    "UnitTable",
    "UnitVerdict",
    "ValidationReport",
    "build_provider",
    "check_json_schema",
    "input_hash",
    "load_theoretical_yields",
    "load_units",
    "relocate_span",
    "resolver_from_ids",
    "run",
    "validate_records",
    "verify_span",
]
