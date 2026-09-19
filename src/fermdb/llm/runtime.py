"""One model call, validated, cached and accounted for.

:func:`run` is the only way the rest of fermdb should reach a model. It enforces the rule
PLAN.md L.1.3 states flatly — **a provider never returns an unvalidated dict as success** — by
never handing back anything that has not passed :mod:`fermdb.llm.validate` first. A model call
here has exactly two outcomes: a validated object, or a raised exception. There is no third
outcome where a caller receives something it has to remember to check.

The rest is bookkeeping that an extraction cannot be audited without:

* **Provenance.** Model, resolved model version, prompt version and input hash on every call.
  An extraction is not reproducible without the prompt that produced it (PLAN.md L.3), and a
  version that records only the model tag does not identify what answered after that tag was
  re-pulled.
* **Cost.** Tokens and wall-clock per attempt, summed across retries, so a budget is measurable
  rather than estimated.
* **Retry, once.** A failed validation is fed back to the model and retried a single time. Then
  it fails loudly. A retry loop that keeps going until something validates is a machine for
  finding the output that happens to slip past the checker.
* **Caching** on ``(input_hash, model, prompt_version)``, so revising a prompt re-runs only what
  the revision changed. Only validated results are ever cached.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from .providers import Completion, Provider, ProviderError
from .validate import SchemaError, check_json_schema

__all__ = [
    "CacheEntry",
    "CacheKey",
    "FileCache",
    "LlmError",
    "LlmResponseError",
    "LlmValidationError",
    "MemoryCache",
    "NullCache",
    "ResultCache",
    "RunResult",
    "RunStats",
    "input_hash",
    "run",
]

JsonObject = dict[str, Any]

#: One retry after a failed validation, then fail. See the module docstring.
DEFAULT_MAX_ATTEMPTS: Final[int] = 2

_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"```(?:json)?\s*(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE
)
_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")


class LlmError(RuntimeError):
    """A run failed. The base for everything this module raises."""


class LlmResponseError(LlmError):
    """The model's text was not a JSON object at all."""


class LlmValidationError(LlmError):
    """Every attempt produced output that failed validation. Carries what was wrong with each.

    Raised rather than returning a partial result: an unvalidated object that reached a caller
    would be indistinguishable from a validated one by the time it was written down.
    """

    def __init__(self, message: str, *, attempts: Sequence[Sequence[str]]) -> None:
        super().__init__(message)
        #: Errors per attempt, in order.
        self.attempts: tuple[tuple[str, ...], ...] = tuple(tuple(a) for a in attempts)


# ----------------------------------------------------------------------------------- provenance


@dataclass(frozen=True)
class RunStats:
    """Everything a run must record about itself to be auditable and billable."""

    provider: str
    model: str
    model_version: str
    prompt_version: str
    input_hash: str
    attempts: int
    cache_hit: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_s: float = 0.0

    @property
    def total_tokens(self) -> int | None:
        """Prompt + completion across every attempt, or None if the backend reported neither."""
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    def as_dict(self) -> JsonObject:
        """A plain mapping, for storing beside an extraction or logging."""
        document = asdict(self)
        document["total_tokens"] = self.total_tokens
        return document


@dataclass(frozen=True)
class RunResult:
    """A validated object plus how it was obtained. The only success shape :func:`run` returns."""

    value: JsonObject
    stats: RunStats
    #: Validation errors from each failed attempt, oldest first. Empty on a first-try success.
    failed_attempts: tuple[tuple[str, ...], ...] = ()


# ---------------------------------------------------------------------------------------- cache


@dataclass(frozen=True)
class CacheKey:
    """``(input_hash, model, prompt_version)`` — PLAN.md L.3's cache key, spelled out.

    The prompt version is part of the key so that revising a prompt invalidates exactly the runs
    that prompt produced, and nothing else: a prompt revision should re-run what changed, not the
    whole corpus.
    """

    input_hash: str
    model: str
    prompt_version: str

    @property
    def digest(self) -> str:
        """A stable filename-safe digest over all three parts."""
        joined = "\x1f".join((self.input_hash, self.model, self.prompt_version))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, str]:
        """The key as a mapping, stored inside each cache entry so a hit can be verified."""
        return {
            "input_hash": self.input_hash,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class CacheEntry:
    """A cached value together with the provenance of the run that produced it.

    The stats travel with the value on purpose. A cache hit still has to say which model and
    model version produced the extraction it is handing back — recording the hit itself as the
    provenance would write "cached" into a row whose whole job is to name what answered.
    """

    value: JsonObject
    stats: RunStats | None = None


class ResultCache(Protocol):
    """Where validated results are kept between runs."""

    def get(self, key: CacheKey) -> CacheEntry | None:
        """The cached entry for ``key``, or None."""

    def put(self, key: CacheKey, value: JsonObject, stats: RunStats) -> None:
        """Store a *validated* value. Invalid output is never cached."""


class NullCache:
    """Caches nothing. The default, so a caller opts into persistence deliberately."""

    def get(self, key: CacheKey) -> CacheEntry | None:
        """Always None."""
        return None

    def put(self, key: CacheKey, value: JsonObject, stats: RunStats) -> None:
        """Discards the value."""


@dataclass
class MemoryCache:
    """An in-process cache. For tests and for a single batch run."""

    entries: dict[str, CacheEntry] = field(default_factory=dict)

    def get(self, key: CacheKey) -> CacheEntry | None:
        """The cached entry, deep-copied through JSON so a caller cannot mutate the cache."""
        found = self.entries.get(key.digest)
        return None if found is None else CacheEntry(_clone(found.value), found.stats)

    def put(self, key: CacheKey, value: JsonObject, stats: RunStats) -> None:
        """Store a validated value."""
        self.entries[key.digest] = CacheEntry(_clone(value), stats)


class FileCache:
    """A JSON-file cache under a derived-tier directory.

    The directory comes from configuration (``LlmConfig.cache_dir``, which resolves through
    ``Settings``), never from a literal path. Derived tier is the only tier fermdb creates on its
    own, and a model cache is rebuildable by definition — deleting it costs time, not data.

    Laid out as ``<cache_dir>/<model>/<prompt_version>/<digest>.json`` so a human can see at a
    glance what a prompt revision invalidated, and delete one model's results without touching
    another's. Each file repeats its own key, and a file whose key does not match the one being
    looked up is treated as a miss rather than trusted.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, key: CacheKey) -> Path:
        """Where ``key`` is stored."""
        return (
            self.directory
            / _slug(key.model)
            / _slug(key.prompt_version)
            / f"{key.digest[:32]}.json"
        )

    def get(self, key: CacheKey) -> CacheEntry | None:
        """The cached entry, or None on a miss, an unreadable file or a key mismatch."""
        path = self.path_for(key)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            # A corrupt or half-written entry is a miss, not a failure: the cache is rebuildable
            # and a run that dies because of its own cache is worse than one that recomputes.
            return None
        if not isinstance(document, dict) or document.get("key") != key.as_dict():
            return None
        value = document.get("value")
        if not isinstance(value, dict):
            return None
        return CacheEntry(value, _stats_from(document.get("stats")))

    def put(self, key: CacheKey, value: JsonObject, stats: RunStats) -> None:
        """Write a validated value, atomically enough that a crash cannot leave a torn entry."""
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "key": key.as_dict(),
            "value": value,
            "stats": stats.as_dict(),
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", value).strip("_") or "unnamed"


def _stats_from(document: object) -> RunStats | None:
    """Rebuild the stored provenance, or None if the entry predates it or is malformed."""
    if not isinstance(document, dict):
        return None
    fields = {
        "provider": str,
        "model": str,
        "model_version": str,
        "prompt_version": str,
        "input_hash": str,
        "attempts": int,
    }
    values: dict[str, Any] = {}
    for name, kind in fields.items():
        found = document.get(name)
        if not isinstance(found, kind):
            return None
        values[name] = found
    return RunStats(**values)


def _clone(value: JsonObject) -> JsonObject:
    cloned: JsonObject = json.loads(json.dumps(value))
    return cloned


# ------------------------------------------------------------------------------------------ run


def input_hash(
    prompt: str,
    schema: Mapping[str, Any],
    *,
    model: str,
    prompt_version: str,
    options: Mapping[str, Any] | None = None,
) -> str:
    """A stable sha256 over everything that could change the answer.

    Sorted keys and no whitespace, so the same logical call hashes the same across processes and
    platforms. Options are included because a different temperature or context window is a
    different call, even with an identical prompt.
    """
    payload = {
        "prompt": prompt,
        "schema": schema,
        "model": model,
        "prompt_version": prompt_version,
        "options": dict(options or {}),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run(
    prompt: str,
    schema: Mapping[str, Any],
    *,
    provider: Provider,
    model: str,
    prompt_version: str,
    options: Mapping[str, Any] | None = None,
    timeout_s: float | None = None,
    cache: ResultCache | None = None,
    post_validate: Callable[[JsonObject], Sequence[str]] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> RunResult:
    """Run one prompt and return a validated object, or raise.

    Args:
        prompt: The rendered prompt. Its version is ``prompt_version``, not its text.
        schema: JSON Schema the answer must satisfy. Passed to the provider as a decoding
            constraint where supported *and* re-checked here — a provider's promise to honour a
            schema is not a validation, and only one of those two is model-independent.
        provider: Any :class:`~fermdb.llm.providers.Provider`. Tests pass the mock.
        model: The model name, obtained from ``LlmConfig.model_for(role)``. Never a literal.
        prompt_version: Stored with the output and part of the cache key.
        post_validate: Domain checks that need more than the schema — span verification against
            the source text, the theoretical-maximum check, id resolution. Returns a list of
            error strings; a non-empty list fails the attempt exactly as a schema error does.
            This is where :func:`fermdb.llm.validate.validate_records` is wired in by the caller
            that holds the source text.
        max_attempts: Total attempts including the first. 2 means "retry once, then fail".

    Returns:
        A :class:`RunResult` whose ``value`` has passed both the schema and ``post_validate``.

    Raises:
        LlmValidationError: Every attempt failed validation.
        LlmResponseError: The model returned text containing no JSON object.
        ProviderError: The backend could not be reached or did not answer usefully.
        SchemaError: The schema itself is unusable.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    digest = input_hash(prompt, schema, model=model, prompt_version=prompt_version, options=options)
    key = CacheKey(input_hash=digest, model=model, prompt_version=prompt_version)
    active_cache: ResultCache = NullCache() if cache is None else cache

    cached = active_cache.get(key)
    if cached is not None:
        # The value keeps the provenance of the run that produced it — which model version
        # actually answered is a property of the extraction, not of today's lookup. The cost
        # fields are zeroed instead, because this call spent nothing and a budget that counted
        # cache hits would report spend that never happened.
        stored = cached.stats
        return RunResult(
            value=cached.value,
            stats=RunStats(
                provider=stored.provider if stored else provider.name,
                model=stored.model if stored else model,
                model_version=stored.model_version if stored else "unrecorded",
                prompt_version=prompt_version,
                input_hash=digest,
                attempts=0,
                cache_hit=True,
                prompt_tokens=0,
                completion_tokens=0,
                duration_s=0.0,
            ),
        )

    failures: list[tuple[str, ...]] = []
    prompt_tokens = 0
    completion_tokens = 0
    reported_tokens = False
    elapsed = 0.0
    model_version = model
    current_prompt = prompt

    for attempt in range(1, max_attempts + 1):
        completion = _complete(
            provider,
            current_prompt,
            model=model,
            schema=schema,
            options=options,
            timeout_s=timeout_s,
        )
        model_version = completion.model_version
        elapsed += completion.duration_s
        if completion.prompt_tokens is not None or completion.completion_tokens is not None:
            reported_tokens = True
            prompt_tokens += completion.prompt_tokens or 0
            completion_tokens += completion.completion_tokens or 0

        errors, value = _validate_completion(completion, schema, post_validate)
        if not errors and value is not None:
            stats = RunStats(
                provider=provider.name,
                model=model,
                model_version=model_version,
                prompt_version=prompt_version,
                input_hash=digest,
                attempts=attempt,
                cache_hit=False,
                prompt_tokens=prompt_tokens if reported_tokens else None,
                completion_tokens=completion_tokens if reported_tokens else None,
                duration_s=elapsed,
            )
            # Only a validated value is ever cached. Caching a rejected one would turn a single
            # bad answer into a permanent one.
            active_cache.put(key, value, stats)
            return RunResult(value=value, stats=stats, failed_attempts=tuple(failures))

        failures.append(tuple(errors))
        if attempt < max_attempts:
            current_prompt = _repair_prompt(prompt, errors)

    raise LlmValidationError(
        f"{model} produced output that failed validation on all {max_attempts} attempt(s) "
        f"(prompt_version={prompt_version}, input_hash={digest[:12]}). "
        f"Last errors: {'; '.join(failures[-1]) if failures else 'none recorded'}",
        attempts=failures,
    )


def _complete(
    provider: Provider,
    prompt: str,
    *,
    model: str,
    schema: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    timeout_s: float | None,
) -> Completion:
    try:
        return provider.complete(
            prompt, model=model, schema=schema, options=options, timeout_s=timeout_s
        )
    except ProviderError:
        # Reaching the backend is the provider's problem and its errors already say what to do
        # about it; wrapping them here would only bury the instruction.
        raise


def _validate_completion(
    completion: Completion,
    schema: Mapping[str, Any],
    post_validate: Callable[[JsonObject], Sequence[str]] | None,
) -> tuple[list[str], JsonObject | None]:
    """Parse, schema-check, then domain-check. Returns (errors, value-or-None)."""
    try:
        value = parse_json_object(completion.text)
    except LlmResponseError as exc:
        return [str(exc)], None

    errors = check_json_schema(value, schema)
    if errors:
        return errors, None

    if post_validate is not None:
        domain_errors = list(post_validate(value))
        if domain_errors:
            return domain_errors, None
    return [], value


def parse_json_object(text: str) -> JsonObject:
    """Pull a JSON object out of a model's reply, tolerating fences and surrounding chatter.

    Tolerant about packaging, strict about content: the result must be a JSON *object*, and no
    attempt is made to repair malformed JSON. Guessing at what a truncated object meant is how a
    number nobody wrote ends up in the atlas.
    """
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.insert(0, fenced.group("body").strip())
    braced = _outermost_object(text)
    if braced is not None:
        candidates.append(braced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LlmResponseError(
        f"the model's reply contains no JSON object (first 200 characters: {text[:200]!r})"
    )


def _outermost_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else None


def _repair_prompt(prompt: str, errors: Sequence[str]) -> str:
    """The retry prompt: the original, plus exactly what was wrong with the last answer.

    Feeding the errors back is worth one attempt — a model that mislabelled a field usually
    fixes it when told. It is not worth two: past that, the loop stops testing whether the model
    can answer and starts searching for an answer the validator happens to let through.
    """
    listed = "\n".join(f"  - {error}" for error in errors) or "  - (no detail recorded)"
    return (
        f"{prompt}\n\n"
        "Your previous answer was rejected by a deterministic validator:\n"
        f"{listed}\n\n"
        "Correct every point above and reply with the JSON object only, no commentary.\n"
        "Do not invent a quote or an offset to satisfy a span check: every quote must be copied "
        "verbatim from the source text at the offsets you report. If a value is not stated in "
        "the source, omit the value rather than supplying one."
    )


def describe_schema_support() -> str:
    """One line naming the checker behind :func:`run`, for a ``--version``-style report."""
    try:
        check_json_schema({}, {"type": "object"})
    except SchemaError as exc:  # pragma: no cover - the trivial schema always checks out
        return f"hand-rolled JSON Schema subset (unavailable: {exc})"
    return "hand-rolled JSON Schema subset (pydantic is not a dependency of this project)"
