"""Three interchangeable LLM providers behind one interface (PLAN.md L.3).

    ollama  HTTP to a local Ollama daemon. The machine this atlas is built on has one, and
            local models are the intended production path for extraction.
    mock    deterministic, offline, no daemon, no network. The DEFAULT everywhere.
    api     a deliberate stub. Remote calls are out of scope for this task.

Two rules this module exists to make structural, both from
``docs/reference/MODEL_ROUTING.md`` §3 and §5:

* **The provider is not a safety boundary.** Nothing here decides whether an output is
  trustworthy; :mod:`fermdb.llm.validate` does, by checks that are the same whatever produced
  the text. "Capability increases the plausibility of errors" — a bigger model buys a
  better-reading wrong answer, not a safer one, so no code path may branch on model tier.
* **No model name is written in code.** Models come from configuration. The documented defaults
  live in :data:`DEFAULT_MODELS` — one constant, resolved through :meth:`LlmConfig.model_for`,
  which is the only way a caller should ever learn a model name.

``mock`` is the default provider on purpose. An unconfigured caller then produces a loud local
failure rather than quietly reaching a daemon (or, once ``api`` exists, the network and a bill).
Real runs opt in with ``FERMDB_LLM_PROVIDER=ollama``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from ..config import Settings

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODELS",
    "DEFAULT_OPTIONS",
    "DEFAULT_PROVIDER",
    "DEFAULT_TIMEOUT_S",
    "MODEL_ROLES",
    "PROVIDER_NAMES",
    "ApiProvider",
    "Completion",
    "HttpRequest",
    "LlmConfig",
    "MockProvider",
    "OllamaProvider",
    "Provider",
    "ProviderConfigError",
    "ProviderError",
    "ProviderResponseError",
    "ProviderUnavailableError",
    "Transport",
    "build_provider",
]

JsonObject = dict[str, Any]

#: Every provider this module knows how to build.
PROVIDER_NAMES: Final[tuple[str, ...]] = ("ollama", "mock", "api")

#: Default when nothing is configured: offline, deterministic, incapable of spending money.
DEFAULT_PROVIDER: Final[str] = "mock"

#: Where a local Ollama daemon listens unless configured otherwise.
DEFAULT_BASE_URL: Final[str] = "http://localhost:11434"

#: Generous by design. A 27B model answering a long extraction prompt on one RTX 4090 is not
#: fast, and a timeout that fires mid-generation looks exactly like a daemon that is down.
DEFAULT_TIMEOUT_S: Final[float] = 900.0

#: The documented default model per role. Overridden by ``FERMDB_LLM_MODEL_<ROLE>``.
#:
#: Roles follow MODEL_ROUTING.md §4: high-volume triage gets the cheap model, extraction gets a
#: larger one *and* the full validator, vision handles figures and scanned pages. The tier is a
#: cost decision, never a safety one.
DEFAULT_MODELS: Final[Mapping[str, str]] = {
    "triage": "qwen2.5:7b-instruct",
    "extraction": "qwen3.6:27b",
    "vision": "qwen2.5vl:7b",
}

#: Roles in a stable order, for reporting.
MODEL_ROLES: Final[tuple[str, ...]] = tuple(DEFAULT_MODELS)

#: Sampling defaults. Greedy and seeded: an extraction that cannot be reproduced cannot be
#: audited, and `temperature: 0` costs nothing here.
DEFAULT_OPTIONS: Final[Mapping[str, Any]] = {
    "temperature": 0.0,
    "seed": 0,
    "num_ctx": 8192,
}

ENV_PREFIX: Final[str] = "FERMDB_LLM_"
_JSON_HEADERS: Final[Mapping[str, str]] = {"Content-Type": "application/json"}


# --------------------------------------------------------------------------------------- errors


class ProviderError(RuntimeError):
    """A model call failed. Never raised for a merely *wrong* answer — that is the validator's."""


class ProviderUnavailableError(ProviderError):
    """The backend could not be reached: daemon down, wrong port, model not pulled."""


class ProviderResponseError(ProviderError):
    """The backend answered, but not with something this module can read."""


class ProviderConfigError(ProviderError):
    """Configuration names a provider or role that does not exist."""


# ---------------------------------------------------------------------------------- the results


@dataclass(frozen=True)
class Completion:
    """One provider call's raw result. Unvalidated text plus the provenance a run must record.

    ``model_version`` is what actually answered, resolved as precisely as the backend allows
    (for Ollama, the tag plus a content digest when one is reported). ``model`` is what was
    asked for. They differ the moment a tag is re-pulled, which is exactly when an unreproducible
    extraction would otherwise go unnoticed.
    """

    text: str
    provider: str
    model: str
    model_version: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_s: float = 0.0
    finish_reason: str | None = None

    @property
    def total_tokens(self) -> int | None:
        """Prompt + completion, or None if the backend reported neither."""
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class Provider(Protocol):
    """What every provider offers. Deliberately one method: text in, text plus provenance out.

    ``schema`` is a hint, not a guarantee: a backend that supports constrained decoding is asked
    to honour it, and one that does not simply ignores it. Either way the caller re-checks the
    result, because a provider promise is not a validation.
    """

    @property
    def name(self) -> str:
        """Provider id, one of :data:`PROVIDER_NAMES`."""

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """Run one non-streaming completion."""


# ------------------------------------------------------------------------------------- transport


@dataclass(frozen=True)
class HttpRequest:
    """One POST, as handed to a :data:`Transport`."""

    url: str
    body: bytes
    headers: Mapping[str, str]
    timeout_s: float


#: Injection seam for :class:`OllamaProvider`. Tests pass a function over recorded bytes; nothing
#: in the test suite may reach a socket (PLAN.md L.3: the pipeline is testable without network).
Transport = Callable[[HttpRequest], bytes]


def urllib_transport(request: HttpRequest) -> bytes:
    """The real transport: one urllib POST, with backend failures translated to ProviderError."""
    req = urllib.request.Request(  # noqa: S310 - http(s) URL from configuration, not user input
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=request.timeout_s) as response:  # noqa: S310
            payload: bytes = response.read()
            return payload
    except urllib.error.HTTPError as exc:
        detail = _safe_http_body(exc)
        if exc.code == 404:
            raise ProviderUnavailableError(
                f"{request.url} returned 404: the daemon is running but does not have that "
                f"model. Pull it first (`ollama pull <model>`) or set the right "
                f"{ENV_PREFIX}MODEL_<ROLE>. Server said: {detail}"
            ) from exc
        raise ProviderResponseError(f"{request.url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderUnavailableError(
            f"cannot reach {request.url} ({exc.reason}). Is the Ollama daemon running? "
            f"Start it with `ollama serve`, check `ollama list`, or point "
            f"{ENV_PREFIX}BASE_URL somewhere else."
        ) from exc
    except TimeoutError as exc:
        raise ProviderUnavailableError(
            f"{request.url} did not answer within {request.timeout_s:g}s. A large local model "
            f"can legitimately need longer — raise {ENV_PREFIX}TIMEOUT_S before assuming a hang."
        ) from exc
    except OSError as exc:
        raise ProviderUnavailableError(f"cannot reach {request.url}: {exc}") from exc


def _safe_http_body(exc: urllib.error.HTTPError, *, limit: int = 400) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return "<unreadable body>"
    body = body.strip().replace("\n", " ")
    return body[:limit] if body else "<empty body>"


# ------------------------------------------------------------------------------------ the config


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ProviderConfigError(f"{key}={raw!r} is not a number") from exc


def _env_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ProviderConfigError(f"{key}={raw!r} is not an integer") from exc


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ProviderConfigError(f"{key}={raw!r} is not a boolean (use true/false)")


@dataclass(frozen=True)
class LlmConfig:
    """Resolved LLM configuration: provider, endpoint, models per role, options, cache location.

    Every field comes from the environment over a documented default; no model name, endpoint or
    directory is written at a call site. Built with :meth:`load`, which reads ``FERMDB_LLM_*``
    and takes the cache directory from :class:`~fermdb.config.Settings` so it lands in the
    derived (rebuildable) tier like every other generated artefact.
    """

    provider: str = DEFAULT_PROVIDER
    base_url: str = DEFAULT_BASE_URL
    models: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    options: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_OPTIONS))
    timeout_s: float = DEFAULT_TIMEOUT_S
    cache_dir: Path | None = None
    cache_enabled: bool = True

    @classmethod
    def load(
        cls,
        settings: Settings | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> LlmConfig:
        """Resolve configuration from ``FERMDB_LLM_*`` plus documented defaults.

        Recognised keys (all optional)::

            FERMDB_LLM_PROVIDER        ollama | mock | api           (default: mock)
            FERMDB_LLM_BASE_URL        Ollama endpoint               (default: localhost:11434)
            FERMDB_LLM_TIMEOUT_S       seconds per call              (default: 900)
            FERMDB_LLM_MODEL_TRIAGE    model for the triage role     (see DEFAULT_MODELS)
            FERMDB_LLM_MODEL_EXTRACTION
            FERMDB_LLM_MODEL_VISION
            FERMDB_LLM_TEMPERATURE / _SEED / _NUM_CTX / _NUM_PREDICT  sampling options
            FERMDB_LLM_CACHE           true | false                  (default: true)
            FERMDB_LLM_CACHE_DIR       overrides the derived-tier default
        """
        active: Mapping[str, str] = os.environ if env is None else env

        provider = (active.get(ENV_PREFIX + "PROVIDER") or DEFAULT_PROVIDER).strip().lower()
        if provider not in PROVIDER_NAMES:
            raise ProviderConfigError(
                f"{ENV_PREFIX}PROVIDER={provider!r} is not one of {PROVIDER_NAMES}"
            )

        base_url = (active.get(ENV_PREFIX + "BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")

        models = dict(DEFAULT_MODELS)
        for role in MODEL_ROLES:
            override = active.get(f"{ENV_PREFIX}MODEL_{role.upper()}")
            if override and override.strip():
                models[role] = override.strip()

        options = dict(DEFAULT_OPTIONS)
        options["temperature"] = _env_float(
            active, ENV_PREFIX + "TEMPERATURE", float(DEFAULT_OPTIONS["temperature"])
        )
        for option_key, env_key in (("seed", "SEED"), ("num_ctx", "NUM_CTX")):
            value = _env_int(active, ENV_PREFIX + env_key)
            if value is not None:
                options[option_key] = value
        num_predict = _env_int(active, ENV_PREFIX + "NUM_PREDICT")
        if num_predict is not None:
            options["num_predict"] = num_predict

        return cls(
            provider=provider,
            base_url=base_url,
            models=models,
            options=options,
            timeout_s=_env_float(active, ENV_PREFIX + "TIMEOUT_S", DEFAULT_TIMEOUT_S),
            cache_dir=cls._cache_dir(settings, active),
            cache_enabled=_env_bool(active, ENV_PREFIX + "CACHE", True),
        )

    @staticmethod
    def _cache_dir(settings: Settings | None, env: Mapping[str, str]) -> Path | None:
        """Where cached results live: an explicit override, else the derived tier, else nowhere.

        ``llm_cache_dir`` is honoured if a future ``env/paths.yaml`` defines it; until then the
        cache sits under the configured ``data_dir``, which is derived-tier and therefore the one
        tier fermdb may create on its own (CONVENTIONS.md, "Paths and configuration").
        """
        override = env.get(ENV_PREFIX + "CACHE_DIR")
        if override and override.strip():
            return Path(override.strip())
        if settings is None:
            return None
        try:
            return settings.path("llm_cache_dir")
        except KeyError:
            return settings.path("data_dir") / "llm-cache"

    def model_for(self, role: str) -> str:
        """The configured model for ``role``. The only supported way to obtain a model name."""
        try:
            return self.models[role]
        except KeyError as exc:
            raise ProviderConfigError(
                f"unknown model role {role!r}; configured roles are {tuple(self.models)}"
            ) from exc


# --------------------------------------------------------------------------------------- ollama


class OllamaProvider:
    """A local Ollama daemon over HTTP, non-streaming, JSON-schema-constrained where supported.

    No torch and no transformers on this machine, so the HTTP API is the whole integration
    surface. Streaming is off: a run either has a complete answer to validate or it has nothing,
    and partial JSON is not a useful intermediate state for a validator.
    """

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        options: Mapping[str, Any] | None = None,
        transport: Transport | None = None,
        constrain_with_schema: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._options: dict[str, Any] = dict(DEFAULT_OPTIONS if options is None else options)
        self._transport: Transport = urllib_transport if transport is None else transport
        self._constrain_with_schema = constrain_with_schema
        self._versions: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        """The configured endpoint, for reporting."""
        return self._base_url

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """POST ``/api/generate`` once and return the text with its usage statistics."""
        merged: dict[str, Any] = dict(self._options)
        if options:
            merged.update(options)
        payload: JsonObject = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": merged,
        }
        if schema is not None and self._constrain_with_schema:
            # Ollama accepts a JSON Schema in `format` and constrains decoding to it. When the
            # running daemon is too old to understand it the field is ignored, the answer is
            # ordinary text, and the validator catches the difference. The constraint is a
            # convenience, never the reason a result is trusted.
            payload["format"] = dict(schema)

        effective_timeout = self._timeout_s if timeout_s is None else timeout_s
        started = time.monotonic()
        document = self._post("/api/generate", payload, effective_timeout)
        elapsed = time.monotonic() - started

        text = document.get("response")
        if not isinstance(text, str):
            raise ProviderResponseError(
                f"{self._base_url}/api/generate returned no 'response' string "
                f"(keys: {sorted(document)})"
            )
        reported_model = document.get("model")
        served_model = reported_model if isinstance(reported_model, str) else model
        return Completion(
            text=text,
            provider=self.name,
            model=model,
            model_version=self._model_version(served_model, effective_timeout),
            prompt_tokens=_as_int(document.get("prompt_eval_count")),
            completion_tokens=_as_int(document.get("eval_count")),
            duration_s=elapsed,
            finish_reason=_as_str(document.get("done_reason")),
        )

    def _post(self, route: str, payload: JsonObject, timeout_s: float) -> JsonObject:
        request = HttpRequest(
            url=f"{self._base_url}{route}",
            body=json.dumps(payload).encode("utf-8"),
            headers=_JSON_HEADERS,
            timeout_s=timeout_s,
        )
        try:
            raw = self._transport(request)
        except ProviderError:
            raise
        except OSError as exc:  # a custom transport that did not translate its own failure
            raise ProviderUnavailableError(f"cannot reach {request.url}: {exc}") from exc
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError(f"{request.url} did not return JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ProviderResponseError(
                f"{request.url} returned {type(document).__name__}, expected a JSON object"
            )
        return document

    def _model_version(self, model: str, timeout_s: float) -> str:
        """``tag@digest`` when the daemon reports a digest, else the tag alone.

        Best-effort and cached per tag: a missing digest degrades the precision of provenance,
        which is worth one extra call to avoid but not worth failing a run over.
        """
        cached = self._versions.get(model)
        if cached is not None:
            return cached
        version = model
        try:
            document = self._post("/api/show", {"name": model}, timeout_s)
        except ProviderError:
            document = {}
        digest = _as_str(document.get("digest"))
        if digest is None:
            details = document.get("details")
            if isinstance(details, dict):
                digest = _as_str(details.get("digest"))
        if digest:
            version = f"{model}@{digest[:12]}"
        self._versions[model] = version
        return version


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# ----------------------------------------------------------------------------------------- mock


class MockProvider:
    """Deterministic, offline, no daemon. The provider every test uses.

    Configure it one of three ways, and it will never invent an answer on its own:

    * ``responses=[...]`` — a queue consumed in order, which is how a retry path is tested
      (first response invalid, second one good);
    * ``responses={prompt: text}`` — exact-prompt lookup, with ``default_response`` as fallback;
    * ``handler=fn`` — ``fn(prompt, model, schema) -> str`` for anything shaped.

    With none of them, :meth:`complete` raises. A silent canned answer would let a test pass
    while asserting nothing about what the model was asked.
    """

    name = "mock"

    def __init__(
        self,
        *,
        responses: Sequence[str] | Mapping[str, str] | None = None,
        handler: Callable[[str, str, Mapping[str, Any] | None], str] | None = None,
        default_response: str | None = None,
        model_version: str = "mock-1",
        prompt_tokens: int | None = 0,
        completion_tokens: int | None = 0,
        duration_s: float = 0.0,
    ) -> None:
        self._queue: list[str] | None = None
        self._table: dict[str, str] | None = None
        if isinstance(responses, Mapping):
            self._table = dict(responses)
        elif responses is not None:
            self._queue = list(responses)
        self._handler = handler
        self._default = default_response
        self._model_version = model_version
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._duration_s = duration_s
        #: Every call made, in order: (prompt, model, schema). Assert against it.
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """Return the next configured response. Never touches a socket."""
        self.calls.append((prompt, model, schema))
        return Completion(
            text=self._next_text(prompt, model, schema),
            provider=self.name,
            model=model,
            model_version=self._model_version,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            duration_s=self._duration_s,
            finish_reason="stop",
        )

    def _next_text(self, prompt: str, model: str, schema: Mapping[str, Any] | None) -> str:
        if self._handler is not None:
            return self._handler(prompt, model, schema)
        if self._queue is not None:
            if not self._queue:
                if self._default is not None:
                    return self._default
                raise ProviderError(
                    f"MockProvider ran out of queued responses on call {len(self.calls)}; "
                    "queue another one or pass default_response="
                )
            return self._queue.pop(0)
        if self._table is not None:
            found = self._table.get(prompt)
            if found is not None:
                return found
            if self._default is not None:
                return self._default
            raise ProviderError(
                "MockProvider has no response for this prompt and no default_response. "
                f"Prompt began: {prompt[:120]!r}"
            )
        if self._default is not None:
            return self._default
        raise ProviderError(
            "MockProvider was constructed with no responses, handler or default_response, so it "
            "has nothing to return. Configure it explicitly rather than relying on a canned "
            "answer that asserts nothing."
        )


# ------------------------------------------------------------------------------------------ api


#: Raised by :class:`ApiProvider`. Kept as a constant so the pointer stays in one place.
API_PROVIDER_POINTER: Final[str] = (
    "the 'api' provider is a deliberate stub: this build calls local models only. "
    "Use FERMDB_LLM_PROVIDER=ollama for a real run, or 'mock' in tests. To add a remote "
    "backend, implement complete() here on the same Provider interface as OllamaProvider, and "
    "read docs/reference/MODEL_ROUTING.md first - §4 says which roles may use a stronger model "
    "and §5 says which may never, whatever the provider."
)


class ApiProvider:
    """Placeholder for a remote API backend. Construction is fine; calling it is not.

    Construction deliberately succeeds so that configuration can be inspected, listed and
    reported without exploding; the failure lands on the one operation that would have made a
    network call.
    """

    name = "api"

    def __init__(self, *, config: LlmConfig | None = None) -> None:
        self.config = config

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """Always raises :class:`NotImplementedError`."""
        raise NotImplementedError(API_PROVIDER_POINTER)


# -------------------------------------------------------------------------------------- factory


def build_provider(
    config: LlmConfig | None = None,
    *,
    transport: Transport | None = None,
    mock: MockProvider | None = None,
) -> Provider:
    """Build the configured provider.

    ``transport`` overrides Ollama's HTTP layer and ``mock`` supplies a pre-loaded mock; both
    exist so a test can exercise the same factory the CLI uses without reaching a socket.
    """
    active = LlmConfig() if config is None else config
    if active.provider == "mock":
        return mock if mock is not None else MockProvider()
    if active.provider == "ollama":
        return OllamaProvider(
            base_url=active.base_url,
            timeout_s=active.timeout_s,
            options=active.options,
            transport=transport,
        )
    if active.provider == "api":
        return ApiProvider(config=active)
    raise ProviderConfigError(
        f"unknown provider {active.provider!r}; expected one of {PROVIDER_NAMES}"
    )
