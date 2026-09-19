"""Tests for `fermdb.llm` — providers, the run loop, and above all the validator.

Two properties this file exists to hold down, both from docs/reference/MODEL_ROUTING.md:

* **No test touches the network.** An autouse fixture makes `urllib.request.urlopen` raise, so an
  accidental socket call fails loudly here rather than passing on a machine with a daemon running
  and failing in CI. Every provider test uses either `MockProvider` or an injected transport over
  recorded bytes.
* **The validator, not the model tier, is what makes extraction safe** (§3, §5). So the two
  tests the task names are the load-bearing ones: a deliberately hallucinated quote must be
  rejected, and a yield above the theoretical maximum must be rejected. Both are written as
  "the record does not reach `accepted`", not "a warning is emitted" — a warning is not a gate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fermdb.config import Settings
from fermdb.llm import (
    DEFAULT_MODELS,
    ISSUE_CODES,
    MODEL_CONFIDENCE,
    MODEL_REVIEW_STATE,
    MODEL_ZONE,
    ApiProvider,
    CacheKey,
    FileCache,
    HttpRequest,
    LlmConfig,
    LlmValidationError,
    MemoryCache,
    MockProvider,
    OllamaProvider,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailableError,
    RunResult,
    SchemaError,
    Span,
    build_provider,
    check_json_schema,
    input_hash,
    load_theoretical_yields,
    load_units,
    resolver_from_ids,
    run,
    validate_records,
    verify_span,
)
from fermdb.llm.providers import API_PROVIDER_POINTER, urllib_transport
from fermdb.llm.runtime import LlmResponseError, parse_json_object

REPO_ROOT = Path(__file__).resolve().parent.parent
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"
LLM_SOURCE_DIR = REPO_ROOT / "src" / "fermdb" / "llm"


# ------------------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any real HTTP call fail. A test that needs the internet is a broken test."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)


@pytest.fixture
def settings() -> Settings:
    """Settings pinned to the repo's own env/paths.yaml, isolated from the real environment."""
    return Settings.load(paths_file=PATHS_FILE, env={})


@pytest.fixture
def units(settings: Settings) -> Any:
    return load_units(settings)


@pytest.fixture
def yields(settings: Settings) -> Any:
    return load_theoretical_yields(settings)


SOURCE_TEXT = (
    "The engineered strain produced 22.6 g/L isobutanol after 72 h in minimal medium, "
    "corresponding to a yield of 0.31 g/g glucose. The parent strain reached 1.2 g/L."
)

OBJECT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["titer_g_per_l"],
    "properties": {"titer_g_per_l": {"type": "number", "minimum": 0}},
    "additionalProperties": False,
}


def span_for(text: str, quote: str) -> dict[str, Any]:
    """A truthful span: the quote and the offsets where it really occurs."""
    start = text.index(quote)
    return {"quote": quote, "char_start": start, "char_end": start + len(quote)}


# -------------------------------------------------------------------------------- configuration


def test_default_provider_is_mock_so_nothing_reaches_a_daemon_by_accident() -> None:
    config = LlmConfig.load(env={})
    assert config.provider == "mock"
    assert isinstance(build_provider(config), MockProvider)


def test_models_come_from_config_with_the_documented_defaults() -> None:
    config = LlmConfig.load(env={})
    assert config.model_for("triage") == DEFAULT_MODELS["triage"]
    assert config.model_for("extraction") == DEFAULT_MODELS["extraction"]
    assert config.model_for("vision") == DEFAULT_MODELS["vision"]


def test_environment_overrides_every_documented_key() -> None:
    config = LlmConfig.load(
        env={
            "FERMDB_LLM_PROVIDER": "ollama",
            "FERMDB_LLM_BASE_URL": "http://127.0.0.1:9999/",
            "FERMDB_LLM_MODEL_EXTRACTION": "some-other-model:70b",
            "FERMDB_LLM_TIMEOUT_S": "1234",
            "FERMDB_LLM_NUM_CTX": "32768",
            "FERMDB_LLM_CACHE": "false",
        }
    )
    assert config.provider == "ollama"
    assert config.base_url == "http://127.0.0.1:9999"
    assert config.model_for("extraction") == "some-other-model:70b"
    assert config.model_for("triage") == DEFAULT_MODELS["triage"]
    assert config.timeout_s == 1234
    assert config.options["num_ctx"] == 32768
    assert config.cache_enabled is False


def test_bad_configuration_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(ProviderConfigError):
        LlmConfig.load(env={"FERMDB_LLM_PROVIDER": "gpt"})
    with pytest.raises(ProviderConfigError):
        LlmConfig.load(env={"FERMDB_LLM_TIMEOUT_S": "soon"})
    with pytest.raises(ProviderConfigError):
        LlmConfig().model_for("summarization")


def test_cache_lives_in_the_derived_tier_via_settings(settings: Settings) -> None:
    config = LlmConfig.load(settings, env={})
    assert config.cache_dir is not None
    assert config.cache_dir.is_relative_to(settings.path("data_dir"))


def test_defaults_are_generous_enough_for_a_27b_model_on_one_gpu() -> None:
    # A 27B model answering a long extraction prompt is slow; a short timeout is indistinguishable
    # from a dead daemon, and the wrong diagnosis sends someone restarting a healthy service.
    assert LlmConfig().timeout_s >= 600


def test_no_model_name_is_written_anywhere_but_the_defaults_table() -> None:
    """MODEL_ROUTING.md: models come from config. A literal at a call site defeats that."""
    for model in DEFAULT_MODELS.values():
        for source in sorted(LLM_SOURCE_DIR.glob("*.py")):
            occurrences = source.read_text(encoding="utf-8").count(model)
            if source.name == "providers.py":
                assert occurrences == 1, f"{model} appears {occurrences}x in providers.py"
            else:
                assert occurrences == 0, f"{model} is hardcoded in {source.name}"


def test_no_theoretical_yield_constant_is_hardcoded_in_the_validator() -> None:
    """0.411 and 0.511 belong to theoretical_yields.tsv, which records what they assume."""
    text = (LLM_SOURCE_DIR / "validate.py").read_text(encoding="utf-8")
    assert "0.411" not in text
    assert "0.511" not in text


# ----------------------------------------------------------------------------------- providers


def ollama_transport(document: Mapping[str, Any], *, show: Mapping[str, Any] | None = None) -> Any:
    """A recorded-response transport. Records every request for assertion."""
    seen: list[HttpRequest] = []

    def _transport(request: HttpRequest) -> bytes:
        seen.append(request)
        if request.url.endswith("/api/show"):
            return json.dumps(show or {}).encode("utf-8")
        return json.dumps(document).encode("utf-8")

    _transport.seen = seen  # type: ignore[attr-defined]
    return _transport


def test_ollama_sends_a_non_streaming_schema_constrained_request() -> None:
    transport = ollama_transport(
        {
            "model": "configured-model:27b",
            "response": '{"titer_g_per_l": 22.6}',
            "prompt_eval_count": 1200,
            "eval_count": 40,
            "done_reason": "stop",
        },
        show={"digest": "sha256:abcdef0123456789"},
    )
    provider = OllamaProvider(
        base_url="http://localhost:11434", transport=transport, options={"temperature": 0.0}
    )
    completion = provider.complete(
        "extract the titer", model="configured-model:27b", schema=OBJECT_SCHEMA
    )

    generate = json.loads(transport.seen[0].body)
    assert transport.seen[0].url == "http://localhost:11434/api/generate"
    assert generate["stream"] is False
    assert generate["format"] == dict(OBJECT_SCHEMA)
    assert generate["options"]["temperature"] == 0.0
    assert completion.text == '{"titer_g_per_l": 22.6}'
    assert completion.prompt_tokens == 1200
    assert completion.completion_tokens == 40
    assert completion.total_tokens == 1240
    # Provenance is the tag plus the digest that actually answered, so a re-pulled tag is visible.
    assert completion.model_version == "configured-model:27b@sha256:abcde"


def test_ollama_falls_back_to_the_tag_when_no_digest_is_reported() -> None:
    transport = ollama_transport({"response": "{}"}, show={})
    provider = OllamaProvider(transport=transport)
    completion = provider.complete("hello", model="configured-model:27b")
    assert completion.model_version == "configured-model:27b"


def test_ollama_reports_a_missing_response_field_rather_than_returning_empty_text() -> None:
    provider = OllamaProvider(transport=ollama_transport({"error": "model not found"}))
    with pytest.raises(ProviderError, match="no 'response' string"):
        provider.complete("hello", model="configured-model:27b")


def test_a_down_daemon_produces_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refused(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    request = HttpRequest("http://localhost:11434/api/generate", b"{}", {}, 1.0)
    with pytest.raises(ProviderUnavailableError) as caught:
        urllib_transport(request)
    message = str(caught.value)
    assert "ollama serve" in message
    assert "localhost:11434" in message


def test_a_missing_model_says_to_pull_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def _not_found(*args: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "http://localhost:11434/api/generate",
            404,
            "Not Found",
            {},
            None,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(urllib.request, "urlopen", _not_found)
    with pytest.raises(ProviderUnavailableError, match="ollama pull"):
        urllib_transport(HttpRequest("http://localhost:11434/api/generate", b"{}", {}, 1.0))


def test_mock_provider_is_deterministic_and_records_its_calls() -> None:
    provider = MockProvider(responses={"ask": '{"a": 1}'}, default_response='{"a": 0}')
    first = provider.complete("ask", model="m")
    second = provider.complete("ask", model="m")
    assert first.text == second.text == '{"a": 1}'
    assert provider.complete("something else", model="m").text == '{"a": 0}'
    assert [call[0] for call in provider.calls] == ["ask", "ask", "something else"]


def test_mock_provider_refuses_to_invent_an_answer() -> None:
    with pytest.raises(ProviderError, match="nothing to return"):
        MockProvider().complete("hello", model="m")
    exhausted = MockProvider(responses=["{}"])
    exhausted.complete("one", model="m")
    with pytest.raises(ProviderError, match="ran out of queued responses"):
        exhausted.complete("two", model="m")


def test_api_provider_is_a_stub_with_a_pointer() -> None:
    provider = ApiProvider()
    assert provider.name == "api"
    with pytest.raises(NotImplementedError) as caught:
        provider.complete("hello", model="m")
    assert "MODEL_ROUTING" in str(caught.value)
    assert str(caught.value) == API_PROVIDER_POINTER


def test_build_provider_covers_every_declared_name() -> None:
    assert isinstance(build_provider(LlmConfig(provider="mock")), MockProvider)
    assert isinstance(build_provider(LlmConfig(provider="ollama")), OllamaProvider)
    assert isinstance(build_provider(LlmConfig(provider="api")), ApiProvider)


# ------------------------------------------------------------------------------ the JSON checker


def test_schema_checker_enforces_types_requirements_and_enums() -> None:
    schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["name", "count"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 0},
            "basis": {"enum": ["consumed", "supplied"]},
        },
        "additionalProperties": False,
    }
    assert check_json_schema({"name": "a", "count": 2, "basis": "consumed"}, schema) == []
    assert check_json_schema({"count": 2}, schema) != []
    assert check_json_schema({"name": "a", "count": -1}, schema) != []
    assert check_json_schema({"name": "a", "count": 1, "basis": "guessed"}, schema) != []
    assert check_json_schema({"name": "a", "count": 1, "extra": 1}, schema) != []


def test_a_json_boolean_is_not_a_number() -> None:
    # Python says isinstance(True, int); JSON does not. Conflating them would let `true` through
    # a numeric field.
    assert check_json_schema(True, {"type": "number"}) != []
    assert check_json_schema(True, {"type": "integer"}) != []
    assert check_json_schema(1, {"type": "boolean"}) != []
    assert check_json_schema({"v": True}, {"properties": {"v": {"enum": [1]}}}) != []


def test_nested_arrays_are_checked_item_by_item() -> None:
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "values": {"type": "array", "minItems": 1, "items": {"type": "number"}},
        },
    }
    assert check_json_schema({"values": [1, 2.5]}, schema) == []
    assert check_json_schema({"values": []}, schema) != []
    assert check_json_schema({"values": [1, "two"]}, schema) != []


def test_an_unsupported_keyword_raises_instead_of_being_ignored() -> None:
    """A checker that skips $ref reports every document valid — worse than no checker."""
    with pytest.raises(SchemaError, match=r"\$ref"):
        check_json_schema({}, {"$ref": "#/$defs/thing"})


# -------------------------------------------------------------------- span verification (core)


def test_a_truthful_span_verifies() -> None:
    span = Span.from_mapping(span_for(SOURCE_TEXT, "22.6 g/L isobutanol"))
    assert verify_span(SOURCE_TEXT, span).ok


def test_a_hallucinated_quote_is_rejected() -> None:
    """The failure mode the whole architecture exists to stop: a plausible number, not in the
    paper. The quote reads perfectly and the offsets are in range; it is simply not there."""
    span = Span(quote="41.8 g/L isobutanol", char_start=30, char_end=49)
    verdict = verify_span(SOURCE_TEXT, span)
    assert not verdict.ok
    assert verdict.reason == "quote_absent_from_source"
    assert not verdict.quote_exists_elsewhere


def test_a_real_quote_at_the_wrong_offsets_is_still_rejected() -> None:
    real = "22.6 g/L isobutanol"
    span = Span(quote=real, char_start=0, char_end=len(real))
    verdict = verify_span(SOURCE_TEXT, span)
    assert not verdict.ok
    assert verdict.reason == "offsets_do_not_match_quote"
    # Distinguished from fabrication — a repair pass could fix offsets — but rejected all the same.
    assert verdict.quote_exists_elsewhere
    assert verdict.found_at[0] == SOURCE_TEXT.index(real)


def test_spans_are_not_fuzzily_matched() -> None:
    truthful = span_for(SOURCE_TEXT, "22.6 g/L isobutanol")
    nearly = Span(
        quote="22.6  g/L isobutanol",  # one extra space
        char_start=truthful["char_start"],
        char_end=truthful["char_end"],
    )
    assert not verify_span(SOURCE_TEXT, nearly).ok


def test_malformed_and_out_of_range_spans_are_rejected() -> None:
    assert verify_span(SOURCE_TEXT, Span("", 0, 5)).reason == "empty_quote"
    assert verify_span(SOURCE_TEXT, Span("x", 5, 5)).reason == "offsets_malformed"
    assert verify_span(SOURCE_TEXT, Span("x", -1, 3)).reason == "offsets_malformed"
    assert verify_span(SOURCE_TEXT, Span("x", 10, 10_000)).reason == "offsets_out_of_range"


def test_a_record_with_a_hallucinated_span_never_reaches_accepted(units: Any, yields: Any) -> None:
    records = [
        {
            "field": "titer",
            "value": 22.6,
            "unit": "g/L",
            "span": span_for(SOURCE_TEXT, "22.6 g/L isobutanol"),
        },
        {
            "field": "titer",
            "value": 41.8,
            "unit": "g/L",
            "span": {"quote": "41.8 g/L isobutanol", "char_start": 30, "char_end": 49},
        },
    ]
    report = validate_records(records, source_text=SOURCE_TEXT, units=units, yields=yields)
    assert len(report.accepted) == 1
    assert report.accepted[0]["value"] == 22.6
    rejected = report.rejected
    assert len(rejected) == 1
    assert rejected[0].index == 1
    assert rejected[0].record is None
    assert [issue.code for issue in rejected[0].fatal_issues] == ["span_unresolved"]


def test_a_value_without_a_span_is_not_storable(units: Any, yields: Any) -> None:
    report = validate_records(
        [{"field": "titer", "value": 22.6, "unit": "g/L"}],
        source_text=SOURCE_TEXT,
        units=units,
        yields=yields,
    )
    assert report.accepted == ()
    assert report.rejected[0].fatal_issues[0].code == "span_missing"


# ----------------------------------------------------------------- theoretical maximum (core)


def test_theoretical_yields_are_read_from_the_vocabulary(yields: Any) -> None:
    ceiling = yields.maximum("YAA:PRODUCT:isobutanol", "glucose", "g/g")
    assert ceiling is not None and 0.40 < ceiling < 0.42
    assert yields.maximum("YAA:PRODUCT:ethanol", "glucose", "mol/mol") == 2.0


def test_a_yield_above_the_theoretical_maximum_is_rejected(units: Any, yields: Any) -> None:
    """0.55 g/g isobutanol from glucose is above the stoichiometric ceiling, so whatever the
    model read, it is not a measurement. The span verifies; the physics does not."""
    text = "a yield of 0.55 g/g glucose was obtained"
    report = validate_records(
        [
            {
                "field": "yield",
                "value": 0.55,
                "unit": "g/g",
                "basis": "consumed",
                "product_id": "YAA:PRODUCT:isobutanol",
                "substrate": "glucose",
                "span": span_for(text, "0.55 g/g"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.accepted == ()
    issue = report.rejected[0].fatal_issues[0]
    assert issue.code == "yield_exceeds_theoretical_max"
    assert "theoretical maximum" in issue.message


def test_a_yield_under_the_maximum_is_accepted(units: Any, yields: Any) -> None:
    report = validate_records(
        [
            {
                "field": "yield",
                "value": 0.31,
                "unit": "g/g",
                "basis": "consumed",
                "product_id": "YAA:PRODUCT:isobutanol",
                "substrate": "glucose",
                "span": span_for(SOURCE_TEXT, "0.31 g/g glucose"),
            }
        ],
        source_text=SOURCE_TEXT,
        units=units,
        yields=yields,
    )
    assert report.ok
    assert report.accepted[0]["value"] == 0.31


def test_the_ceiling_comes_from_the_file_not_from_the_code(tmp_path: Path, units: Any) -> None:
    """Point the validator at a vocabulary with a different ceiling and the verdict must follow.

    This is what proves the 0.411 is data: a value accepted against the real file is rejected
    against a file that says something else.
    """
    vocab = tmp_path / "vocabularies"
    vocab.mkdir()
    (vocab / "theoretical_yields.tsv").write_text(
        "# a deliberately different ceiling\n"
        "product_id\tsubstrate\tsubstrate_mw_g_mol\tproduct_mw_g_mol\tstoichiometry\t"
        "mol_per_mol\tg_per_g\tstate\tevidence\tconfidence\n"
        "YAA:PRODUCT:isobutanol\tglucose\t180.16\t74.12\ttest\t1.0\t0.200\trecorded\ttest\t"
        "unverified\n",
        encoding="utf-8",
    )
    text = "a yield of 0.31 g/g glucose"
    record = {
        "field": "yield",
        "value": 0.31,
        "unit": "g/g",
        "basis": "consumed",
        "product_id": "YAA:PRODUCT:isobutanol",
        "substrate": "glucose",
        "span": span_for(text, "0.31 g/g"),
    }
    report = validate_records(
        [record], source_text=text, units=units, yields=load_theoretical_yields(vocab)
    )
    assert report.accepted == ()
    assert report.rejected[0].fatal_issues[0].code == "yield_exceeds_theoretical_max"


def test_an_unsettled_theoretical_yield_is_reported_unchecked_not_invented(
    units: Any, yields: Any
) -> None:
    """theoretical_yields.tsv records state='unknown' for 3-methyl-1-butanol: the pathway's
    redox closure is not settled. Inventing a ceiling there would reject real data."""
    text = "a yield of 0.31 g/g glucose"
    report = validate_records(
        [
            {
                "field": "yield",
                "value": 0.31,
                "unit": "g/g",
                "basis": "consumed",
                "product_id": "YAA:PRODUCT:3-methyl-1-butanol",
                "substrate": "glucose",
                "span": span_for(text, "0.31 g/g"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.ok
    codes = [issue.code for issue in report.verdicts[0].issues]
    assert "yield_not_checkable" in codes


def test_a_fraction_of_theoretical_above_one_is_rejected(units: Any, yields: Any) -> None:
    text = "reaching 1.4 of the theoretical maximum"
    report = validate_records(
        [
            {
                "field": "yield",
                "value": 1.4,
                "unit": "g/g",
                "basis": "theoretical_max_pct",
                "product_id": "YAA:PRODUCT:isobutanol",
                "substrate": "glucose",
                "span": span_for(text, "1.4"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.accepted == ()
    assert report.rejected[0].fatal_issues[0].code == "fraction_out_of_range"


# ------------------------------------------------------------------------------ units and basis


def test_units_parse_against_the_vocabulary(units: Any) -> None:
    assert units.parse("g/L").canonical == "g/L"
    assert units.parse("%v/v").canonical == "% v/v"  # whitespace folded, nothing else
    assert not units.parse("gram per litre").ok
    assert not units.parse("").ok


def test_the_three_missing_states_stay_distinct(units: Any) -> None:
    assert units.parse(None).state == "null"
    assert units.parse("NA").state == "NA"
    assert units.parse("unknown").state == "unknown"
    assert len({units.parse(v).state for v in (None, "NA", "unknown")}) == 3


def test_an_unparsable_unit_rejects_the_record(units: Any, yields: Any) -> None:
    text = "produced 22.6 furlongs per fortnight"
    report = validate_records(
        [
            {
                "value": 22.6,
                "unit": "furlongs/fortnight",
                "span": span_for(text, "22.6 furlongs"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.accepted == ()
    assert report.rejected[0].fatal_issues[0].code == "unit_unparsable"


def test_a_missing_basis_becomes_unknown_never_null(units: Any, yields: Any) -> None:
    """CONVENTIONS.md: where the source does not state a basis it is 'unknown', not NULL —
    a curator who read the paper and found no basis has learned something."""
    text = "a yield of 0.31 g/g glucose"
    report = validate_records(
        [
            {
                "value": 0.31,
                "unit": "g/g",
                "product_id": "YAA:PRODUCT:isobutanol",
                "substrate": "glucose",
                "span": span_for(text, "0.31 g/g"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.ok
    assert report.accepted[0]["basis"] == "unknown"
    assert "basis_defaulted_to_unknown" in [i.code for i in report.verdicts[0].issues]


def test_the_reported_unit_is_never_overwritten(units: Any, yields: Any) -> None:
    text = "produced 22.6 %v/v ethanol"
    report = validate_records(
        [{"value": 22.6, "unit": "%v/v", "span": span_for(text, "22.6 %v/v")}],
        source_text=text,
        units=units,
        yields=yields,
    )
    record = report.accepted[0]
    assert record["unit"] == "%v/v"  # Zone R, as reported
    assert record["unit_canonical"] == "% v/v"  # the harmonized value, added alongside


# -------------------------------------------------------------------------- entity resolution


def test_an_unresolvable_id_rejects_the_record_and_is_recorded_as_unresolved(
    units: Any, yields: Any
) -> None:
    text = "strain JAY270 produced 22.6 g/L"
    resolver = resolver_from_ids({"YAA:STRAIN:cen-pk113-7d"})
    report = validate_records(
        [
            {
                "value": 22.6,
                "unit": "g/L",
                "strain_id": "YAA:STRAIN:jay270",
                "span": span_for(text, "22.6 g/L"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
        resolve_entity=resolver,
    )
    assert report.accepted == ()
    issue = report.rejected[0].fatal_issues[0]
    assert issue.code == "entity_unresolved"
    # Never mapped to the nearest plausible match (CONVENTIONS.md, "Identifiers").
    assert "UNRESOLVED:YAA:STRAIN:jay270" in issue.message


def test_ids_that_resolve_are_accepted(units: Any, yields: Any) -> None:
    text = "strain CEN.PK113-7D produced 22.6 g/L"
    report = validate_records(
        [
            {
                "value": 22.6,
                "unit": "g/L",
                "strain_id": "YAA:STRAIN:cen-pk113-7d",
                "entity_ids": ["YAA:PRODUCT:isobutanol"],
                "span": span_for(text, "22.6 g/L"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
        resolve_entity=resolver_from_ids({"YAA:STRAIN:cen-pk113-7d", "YAA:PRODUCT:isobutanol"}),
    )
    assert report.ok


def test_without_a_resolver_ids_are_reported_unchecked_not_assumed_good(
    units: Any, yields: Any
) -> None:
    text = "strain X produced 22.6 g/L"
    report = validate_records(
        [
            {
                "value": 22.6,
                "unit": "g/L",
                "strain_id": "YAA:STRAIN:whatever",
                "span": span_for(text, "22.6 g/L"),
            }
        ],
        source_text=text,
        units=units,
        yields=yields,
    )
    assert report.ok
    assert "entity_ids_unchecked" in [i.code for i in report.verdicts[0].issues]


# ------------------------------------------------------------------------------- forced zone I


def test_a_model_may_not_set_its_own_confidence(units: Any, yields: Any) -> None:
    """MODEL_ROUTING.md §5.2: model capability must never appear in the derivation of a
    confidence value. The claim is kept for audit; the stored value is 'unverified'."""
    report = validate_records(
        [
            {
                "value": 22.6,
                "unit": "g/L",
                "confidence": "high",
                "span": span_for(SOURCE_TEXT, "22.6 g/L isobutanol"),
            }
        ],
        source_text=SOURCE_TEXT,
        units=units,
        yields=yields,
    )
    record = report.accepted[0]
    assert record["confidence"] == MODEL_CONFIDENCE == "unverified"
    assert record["claimed_confidence"] == "high"
    assert record["zone"] == MODEL_ZONE == "I"
    assert record["review_state"] == MODEL_REVIEW_STATE == "proposed"
    # An overclaim is worth recording, but it is not grounds to throw the value away.
    assert "confidence_overridden" in [i.code for i in report.verdicts[0].issues]
    assert report.ok


def test_every_accepted_record_is_zone_i_proposed(units: Any, yields: Any) -> None:
    report = validate_records(
        [{"value": 22.6, "unit": "g/L", "span": span_for(SOURCE_TEXT, "22.6 g/L")}],
        source_text=SOURCE_TEXT,
        units=units,
        yields=yields,
    )
    assert all(r["zone"] == "I" and r["review_state"] == "proposed" for r in report.accepted)


def test_issue_codes_are_a_closed_set() -> None:
    from fermdb.llm.validate import RecordIssue

    assert len(set(ISSUE_CODES)) == len(ISSUE_CODES)
    with pytest.raises(ValueError, match="unknown issue code"):
        RecordIssue("looks_wrong_to_me", "invented on the spot")


def test_report_summary_names_what_was_dropped(units: Any, yields: Any) -> None:
    report = validate_records(
        [
            {"value": 22.6, "unit": "g/L", "span": span_for(SOURCE_TEXT, "22.6 g/L")},
            {"value": 99.9, "unit": "g/L"},
        ],
        source_text=SOURCE_TEXT,
        units=units,
        yields=yields,
    )
    assert "1/2" in report.summary()
    assert "span_missing" in report.summary()


# ------------------------------------------------------------------------------------ the run


def test_run_returns_a_validated_object_with_full_provenance() -> None:
    provider = MockProvider(responses=['{"titer_g_per_l": 22.6}'], model_version="mock-1")
    result = run(
        "extract",
        OBJECT_SCHEMA,
        provider=provider,
        model="configured-model:27b",
        prompt_version="measurement/v3",
    )
    assert isinstance(result, RunResult)
    assert result.value == {"titer_g_per_l": 22.6}
    assert result.stats.provider == "mock"
    assert result.stats.model == "configured-model:27b"
    assert result.stats.model_version == "mock-1"
    assert result.stats.prompt_version == "measurement/v3"
    assert result.stats.attempts == 1
    assert result.stats.cache_hit is False
    assert len(result.stats.input_hash) == 64


def test_run_records_tokens_and_duration() -> None:
    provider = MockProvider(
        responses=['{"titer_g_per_l": 1.0}'],
        prompt_tokens=1200,
        completion_tokens=35,
        duration_s=4.5,
    )
    stats = run("extract", OBJECT_SCHEMA, provider=provider, model="m", prompt_version="v1").stats
    assert stats.prompt_tokens == 1200
    assert stats.completion_tokens == 35
    assert stats.total_tokens == 1235
    assert stats.duration_s == 4.5
    assert stats.as_dict()["total_tokens"] == 1235


def test_a_schema_failure_is_retried_once_with_the_error_fed_back() -> None:
    provider = MockProvider(
        responses=['{"titer_g_per_l": "twenty-two point six"}', '{"titer_g_per_l": 22.6}']
    )
    result = run("extract", OBJECT_SCHEMA, provider=provider, model="m", prompt_version="v1")
    assert result.value == {"titer_g_per_l": 22.6}
    assert result.stats.attempts == 2
    assert len(provider.calls) == 2
    retry_prompt = provider.calls[1][0]
    assert "rejected by a deterministic validator" in retry_prompt
    assert "titer_g_per_l" in retry_prompt
    # And the retry must not invite the model to manufacture evidence to get past the check.
    assert "Do not invent a quote or an offset" in retry_prompt
    assert result.failed_attempts and result.failed_attempts[0]


def test_persistent_failure_raises_loudly_rather_than_returning_something() -> None:
    provider = MockProvider(responses=['{"titer_g_per_l": -5}', '{"titer_g_per_l": -6}'])
    with pytest.raises(LlmValidationError) as caught:
        run("extract", OBJECT_SCHEMA, provider=provider, model="m", prompt_version="v1")
    assert len(caught.value.attempts) == 2
    assert len(provider.calls) == 2


def test_run_never_retries_more_than_the_configured_number_of_attempts() -> None:
    provider = MockProvider(responses=["{}"] * 10, default_response="{}")
    with pytest.raises(LlmValidationError):
        run("extract", OBJECT_SCHEMA, provider=provider, model="m", prompt_version="v1")
    assert len(provider.calls) == 2  # the default: one retry, then fail


def test_a_domain_check_failure_fails_the_run_exactly_like_a_schema_failure() -> None:
    """post_validate is where span verification is wired in. A provider must never return an
    unvalidated dict as success (PLAN.md L.1.3), so a failing domain check raises."""
    # Schema-valid on both attempts: only the domain check stands between this and a caller.
    provider = MockProvider(responses=['{"titer_g_per_l": 22.6}'] * 2)

    def reject_everything(value: dict[str, Any]) -> list[str]:
        return ["span does not resolve (quote_absent_from_source)"]

    with pytest.raises(LlmValidationError) as caught:
        run(
            "extract",
            OBJECT_SCHEMA,
            provider=provider,
            model="m",
            prompt_version="v1",
            post_validate=reject_everything,
        )
    assert "quote_absent_from_source" in str(caught.value)


def test_non_json_output_fails_rather_than_being_repaired() -> None:
    provider = MockProvider(responses=["I could not find a titer in this paper."] * 2)
    with pytest.raises(LlmValidationError, match="no JSON object"):
        run("extract", OBJECT_SCHEMA, provider=provider, model="m", prompt_version="v1")


def test_json_is_recovered_from_fences_and_chatter() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here you go:\n{"a": 1}\nHope that helps!') == {"a": 1}
    assert parse_json_object('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}}
    with pytest.raises(LlmResponseError):
        parse_json_object("[1, 2, 3]")  # an array is not an extraction record
    with pytest.raises(LlmResponseError):
        parse_json_object("no json here")


# ---------------------------------------------------------------------------------- the cache


def test_a_cache_hit_does_not_call_the_model() -> None:
    cache = MemoryCache()
    first_provider = MockProvider(responses=['{"titer_g_per_l": 22.6}'])
    first = run(
        "extract",
        OBJECT_SCHEMA,
        provider=first_provider,
        model="m",
        prompt_version="v1",
        cache=cache,
    )
    second_provider = MockProvider()  # raises if called at all
    second = run(
        "extract",
        OBJECT_SCHEMA,
        provider=second_provider,
        model="m",
        prompt_version="v1",
        cache=cache,
    )
    assert second.value == first.value
    assert second.stats.cache_hit is True
    assert second.stats.attempts == 0
    assert second_provider.calls == []
    # The provenance is the original run's: which model answered is a property of the
    # extraction, not of today's lookup.
    assert second.stats.model_version == first.stats.model_version
    # ...but the cost is this call's, and this call cost nothing.
    assert second.stats.total_tokens == 0
    assert second.stats.duration_s == 0.0


def test_a_prompt_revision_re_runs_only_what_changed() -> None:
    cache = MemoryCache()
    run(
        "extract",
        OBJECT_SCHEMA,
        provider=MockProvider(responses=['{"titer_g_per_l": 1.0}']),
        model="m",
        prompt_version="v1",
        cache=cache,
    )
    revised = MockProvider(responses=['{"titer_g_per_l": 2.0}'])
    result = run(
        "extract",
        OBJECT_SCHEMA,
        provider=revised,
        model="m",
        prompt_version="v2",
        cache=cache,
    )
    assert result.stats.cache_hit is False
    assert result.value == {"titer_g_per_l": 2.0}
    assert len(cache.entries) == 2


def test_a_different_model_is_a_different_cache_entry() -> None:
    cache = MemoryCache()
    run(
        "extract",
        OBJECT_SCHEMA,
        provider=MockProvider(responses=['{"titer_g_per_l": 1.0}']),
        model="small-model",
        prompt_version="v1",
        cache=cache,
    )
    other = MockProvider(responses=['{"titer_g_per_l": 2.0}'])
    assert (
        run(
            "extract",
            OBJECT_SCHEMA,
            provider=other,
            model="large-model",
            prompt_version="v1",
            cache=cache,
        ).stats.cache_hit
        is False
    )


def test_invalid_output_is_never_cached() -> None:
    cache = MemoryCache()
    with pytest.raises(LlmValidationError):
        run(
            "extract",
            OBJECT_SCHEMA,
            provider=MockProvider(responses=['{"titer_g_per_l": -1}'] * 2),
            model="m",
            prompt_version="v1",
            cache=cache,
        )
    assert cache.entries == {}


def test_file_cache_round_trips_and_is_laid_out_by_model_and_prompt(tmp_path: Path) -> None:
    cache = FileCache(tmp_path / "llm-cache")
    result = run(
        "extract",
        OBJECT_SCHEMA,
        provider=MockProvider(responses=['{"titer_g_per_l": 22.6}']),
        model="configured-model:27b",
        prompt_version="measurement/v3",
        cache=cache,
    )
    key = CacheKey(result.stats.input_hash, "configured-model:27b", "measurement/v3")
    stored = cache.path_for(key)
    assert stored.is_file()
    assert "configured-model_27b" in stored.parts
    assert "measurement_v3" in stored.parts
    entry = cache.get(key)
    assert entry is not None
    assert entry.value == {"titer_g_per_l": 22.6}
    assert entry.stats is not None and entry.stats.prompt_version == "measurement/v3"
    document = json.loads(stored.read_text(encoding="utf-8"))
    assert document["key"] == key.as_dict()
    assert document["stats"]["prompt_version"] == "measurement/v3"


def test_a_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    cache = FileCache(tmp_path / "llm-cache")
    key = CacheKey("a" * 64, "m", "v1")
    path = cache.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    assert cache.get(key) is None


def test_input_hash_is_stable_and_sensitive_to_everything_that_changes_the_answer() -> None:
    base = dict(model="m", prompt_version="v1")
    first = input_hash("p", OBJECT_SCHEMA, **base)
    assert first == input_hash("p", OBJECT_SCHEMA, **base)
    assert first != input_hash("p2", OBJECT_SCHEMA, **base)
    assert first != input_hash("p", {"type": "object"}, **base)
    assert first != input_hash("p", OBJECT_SCHEMA, model="m2", prompt_version="v1")
    assert first != input_hash("p", OBJECT_SCHEMA, **base, options={"temperature": 0.7})


# --------------------------------------------------------------------- end-to-end, still offline


def test_the_whole_path_rejects_a_hallucinated_number_from_a_model(units: Any, yields: Any) -> None:
    """A model returns a schema-valid, well-written, entirely fabricated measurement. The run
    must fail rather than hand anything back — that is the point of the layer."""
    schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["measurements"],
        "properties": {
            "measurements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["value", "unit", "span"],
                    "properties": {
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        "confidence": {"type": "string"},
                        "span": {
                            "type": "object",
                            "required": ["quote", "char_start", "char_end"],
                            "properties": {
                                "quote": {"type": "string"},
                                "char_start": {"type": "integer"},
                                "char_end": {"type": "integer"},
                            },
                        },
                    },
                },
            }
        },
    }
    fabricated = json.dumps(
        {
            "measurements": [
                {
                    "value": 41.8,
                    "unit": "g/L",
                    "confidence": "high",
                    "span": {
                        "quote": "41.8 g/L isobutanol",
                        "char_start": 30,
                        "char_end": 49,
                    },
                }
            ]
        }
    )

    def check(payload: dict[str, Any]) -> list[str]:
        report = validate_records(
            payload["measurements"], source_text=SOURCE_TEXT, units=units, yields=yields
        )
        return [i.message for v in report.rejected for i in v.fatal_issues]

    with pytest.raises(LlmValidationError) as caught:
        run(
            "extract every measurement",
            schema,
            provider=MockProvider(responses=[fabricated] * 2),
            model="configured-model:27b",
            prompt_version="measurement/v3",
            post_validate=check,
        )
    assert "span does not resolve" in str(caught.value)


def test_the_whole_path_accepts_a_truthful_extraction(units: Any, yields: Any) -> None:
    quote = "22.6 g/L isobutanol"
    start = SOURCE_TEXT.index(quote)
    payload = json.dumps(
        {
            "measurements": [
                {
                    "value": 22.6,
                    "unit": "g/L",
                    "confidence": "high",
                    "span": {
                        "quote": quote,
                        "char_start": start,
                        "char_end": start + len(quote),
                    },
                }
            ]
        }
    )
    accepted: list[dict[str, Any]] = []

    def check(value: dict[str, Any]) -> list[str]:
        report = validate_records(
            value["measurements"], source_text=SOURCE_TEXT, units=units, yields=yields
        )
        accepted.extend(report.accepted)
        return [i.message for v in report.rejected for i in v.fatal_issues]

    result = run(
        "extract every measurement",
        {"type": "object"},
        provider=MockProvider(responses=[payload]),
        model="configured-model:27b",
        prompt_version="measurement/v3",
        post_validate=check,
    )
    assert result.stats.attempts == 1
    assert accepted[0]["value"] == 22.6
    assert accepted[0]["confidence"] == "unverified"  # not the 'high' the model asked for
    assert accepted[0]["zone"] == "I"
