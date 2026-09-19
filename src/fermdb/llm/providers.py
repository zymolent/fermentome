"""Four interchangeable LLM providers behind one interface (PLAN.md L.3).

    ollama     HTTP to a local Ollama daemon. The machine this atlas is built on has one, and
               local models are the intended production path for extraction.
    mock       deterministic, offline, no daemon, no network. The DEFAULT everywhere.
    agent-sdk  Claude, driven through the Claude Agent SDK — the Claude Code harness as a
               library, authenticated by a **subscription login**, not a metered API key.
               This is the escalation tier of MODEL_ROUTING.md §7a.
    api        a deliberate stub that raises and points at agent-sdk, so nobody wires the
               metered path by accident.

Three rules this module exists to make structural, the first two from
``docs/reference/MODEL_ROUTING.md`` §3 and §5 and the third from the project owner:

* **The provider is not a safety boundary.** Nothing here decides whether an output is
  trustworthy; :mod:`fermdb.llm.validate` does, by checks that are the same whatever produced
  the text. "Capability increases the plausibility of errors" — a bigger model buys a
  better-reading wrong answer, not a safer one, so no code path may branch on model tier.
* **No model name is written in code.** Models come from configuration:
  :data:`fermdb.config.DEFAULT_LLM_MODELS` and :data:`fermdb.config.DEFAULT_ESCALATION_MODEL`
  are the only places a model name is written down, and :meth:`LlmConfig.model_for` is the only
  way a caller should ever learn one. Ids are full ids, never aliases — an alias moves under a
  run and takes reproducibility with it.
* **Claude is reached through the subscription, never through the API.** :class:`AgentSdkProvider`
  requires ``CLAUDE_CODE_OAUTH_TOKEN`` (from ``claude setup-token``) or an existing Claude Code
  login, refuses to run on ``ANTHROPIC_API_KEY`` alone, and blanks that variable for the child
  process so a key lying around in the environment cannot silently start a bill. No credential is
  ever read from a configuration file; put it in ``env/secrets.local.env``, which is gitignored.

``mock`` is the default local provider on purpose. An unconfigured caller then produces a loud
local failure rather than quietly reaching a daemon or the network. Real runs opt in with
``FERMDB_LLM_PROVIDER=ollama``.

Nothing here reads the environment for its own configuration. Every ``FERMDB_LLM_*`` value is
resolved once by :func:`fermdb.config.resolve_settings` and handed to :meth:`LlmConfig.load`, so
``fermdb config`` reports exactly what a run will use. The two environment reads that remain are
credentials, which are deliberately not settings.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from ..config import (
    DEFAULT_ESCALATION_MODEL,
    DEFAULT_ESCALATION_PROVIDER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL_ROLES,
    DEFAULT_LLM_MODELS,
    DEFAULT_LLM_OPTIONS,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_TIMEOUT_S,
    LLM_ENV_PREFIX,
    SettingItem,
    Settings,
    resolve_settings,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_ESCALATION_PROVIDER",
    "DEFAULT_MODELS",
    "DEFAULT_OPTIONS",
    "DEFAULT_PROVIDER",
    "DEFAULT_TIMEOUT_S",
    "ESCALATION_ROLE",
    "MODEL_ROLES",
    "PROVIDER_NAMES",
    "AgentReply",
    "AgentRequest",
    "AgentRunner",
    "AgentSdkProvider",
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
    "build_escalation_provider",
    "build_provider",
    "subscription_credential",
]

JsonObject = dict[str, Any]

#: Every provider this module knows how to build.
PROVIDER_NAMES: Final[tuple[str, ...]] = ("ollama", "mock", "agent-sdk", "api")

#: Re-exported from :mod:`fermdb.config`, which owns the defaults so that `fermdb config` can
#: report them. Named here for the callers that have always imported them from this module.
DEFAULT_PROVIDER: Final[str] = DEFAULT_LLM_PROVIDER
DEFAULT_BASE_URL: Final[str] = DEFAULT_LLM_BASE_URL
DEFAULT_TIMEOUT_S: Final[float] = DEFAULT_LLM_TIMEOUT_S
DEFAULT_MODELS: Final[Mapping[str, str]] = DEFAULT_LLM_MODELS
DEFAULT_OPTIONS: Final[Mapping[str, Any]] = DEFAULT_LLM_OPTIONS

#: The escalation model is a role like any other, so :meth:`LlmConfig.model_for` stays the single
#: way to learn a model name — but it is *not* one of the local roles, so it is kept out of
#: :data:`DEFAULT_MODELS`, where every entry is a model the Ollama daemon is expected to serve.
ESCALATION_ROLE: Final[str] = "escalation"

#: Roles in a stable order, for reporting.
MODEL_ROLES: Final[tuple[str, ...]] = (*DEFAULT_LLM_MODEL_ROLES, ESCALATION_ROLE)

ENV_PREFIX: Final[str] = LLM_ENV_PREFIX
_JSON_HEADERS: Final[Mapping[str, str]] = {"Content-Type": "application/json"}

#: The subscription credential the Agent SDK uses, and the one this project supports.
OAUTH_TOKEN_VAR: Final[str] = "CLAUDE_CODE_OAUTH_TOKEN"

#: The metered credential. Deliberately *not* used: see the module docstring, rule three.
API_KEY_VAR: Final[str] = "ANTHROPIC_API_KEY"


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


Items = Mapping[str, SettingItem]


def _item(items: Items, key: str) -> SettingItem:
    try:
        return items[key]
    except KeyError as exc:  # pragma: no cover - only a typo in this module can reach it
        raise ProviderConfigError(f"setting {key!r} is not declared in fermdb.config") from exc


def _setting_float(items: Items, key: str) -> float:
    item = _item(items, key)
    try:
        return float(item.value)
    except ValueError as exc:
        raise ProviderConfigError(f"{item.env_var}={item.value!r} is not a number") from exc


def _setting_int(items: Items, key: str) -> int | None:
    """The value as an integer, or None when it is unset — which is a real, distinct state."""
    item = _item(items, key)
    if not item.value.strip():
        return None
    try:
        return int(item.value)
    except ValueError as exc:
        raise ProviderConfigError(f"{item.env_var}={item.value!r} is not an integer") from exc


def _setting_bool(items: Items, key: str) -> bool:
    item = _item(items, key)
    lowered = item.value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ProviderConfigError(f"{item.env_var}={item.value!r} is not a boolean (use true/false)")


def _setting_provider(items: Items, key: str) -> str:
    item = _item(items, key)
    name = item.value.strip().lower()
    if name not in PROVIDER_NAMES:
        raise ProviderConfigError(f"{item.env_var}={name!r} is not one of {PROVIDER_NAMES}")
    return name


def _default_models() -> dict[str, str]:
    return {**DEFAULT_MODELS, ESCALATION_ROLE: DEFAULT_ESCALATION_MODEL}


@dataclass(frozen=True)
class LlmConfig:
    """Resolved LLM configuration: providers, endpoint, models per role, options, cache, budget.

    Every field comes from :class:`~fermdb.config.Settings` over a documented default; no model
    name, endpoint or directory is written at a call site, and this class never reads the
    environment itself. Built with :meth:`load`, which takes the cache directory from `Settings`
    so it lands in the derived (rebuildable) tier like every other generated artefact.

    ``escalation_provider`` and ``escalation_model`` describe the §7a tier and are separate from
    ``provider``/``models``: the local tier runs first on everything, and escalation is a
    different backend reached for a minority of documents. Nothing escalates because this is
    configured — see :mod:`fermdb.llm.escalation`.
    """

    provider: str = DEFAULT_PROVIDER
    base_url: str = DEFAULT_BASE_URL
    models: Mapping[str, str] = field(default_factory=_default_models)
    options: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_OPTIONS))
    timeout_s: float = DEFAULT_TIMEOUT_S
    cache_dir: Path | None = None
    cache_enabled: bool = True
    escalation_provider: str = DEFAULT_ESCALATION_PROVIDER
    escalation_max_documents: int = 0
    escalation_max_tokens: int | None = None
    claude_cli_path: Path | None = None

    @classmethod
    def load(
        cls,
        settings: Settings | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> LlmConfig:
        """Resolve configuration through :class:`~fermdb.config.Settings`.

        `env` wins when given (tests pass ``env={}`` for a documented-defaults run); otherwise
        the values come from `settings`, and failing that from a fresh resolution over the
        process environment. Whichever path is taken, `fermdb.config.LLM_SETTINGS` is the list of
        recognised keys and their defaults, and `fermdb config` prints them.
        """
        if env is not None:
            items: Items = resolve_settings(env)
        elif settings is not None:
            items = settings.setting_items()
        else:
            items = resolve_settings(None)

        models = _default_models()
        for role in MODEL_ROLES:
            key = "llm_escalation_model" if role == ESCALATION_ROLE else f"llm_model_{role}"
            models[role] = _item(items, key).value

        options = dict(DEFAULT_OPTIONS)
        options["temperature"] = _setting_float(items, "llm_temperature")
        for option_key, setting_key in (("seed", "llm_seed"), ("num_ctx", "llm_num_ctx")):
            value = _setting_int(items, setting_key)
            if value is not None:
                options[option_key] = value
        num_predict = _setting_int(items, "llm_num_predict")
        if num_predict is not None:
            options["num_predict"] = num_predict

        max_documents = _setting_int(items, "llm_escalation_max_documents")
        cli_path = _item(items, "llm_claude_cli_path").value

        return cls(
            provider=_setting_provider(items, "llm_provider"),
            base_url=_item(items, "llm_base_url").value.rstrip("/"),
            models=models,
            options=options,
            timeout_s=_setting_float(items, "llm_timeout_s"),
            cache_dir=cls._cache_dir(settings, items),
            cache_enabled=_setting_bool(items, "llm_cache"),
            escalation_provider=_setting_provider(items, "llm_escalation_provider"),
            escalation_max_documents=0 if max_documents is None else max_documents,
            escalation_max_tokens=_setting_int(items, "llm_escalation_max_tokens"),
            claude_cli_path=Path(cli_path) if cli_path else None,
        )

    @staticmethod
    def _cache_dir(settings: Settings | None, items: Items) -> Path | None:
        """Where cached results live: an explicit override, else the derived tier, else nowhere.

        ``llm_cache_dir`` is honoured if a future ``env/paths.yaml`` defines it; until then the
        cache sits under the configured ``data_dir``, which is derived-tier and therefore the one
        tier fermdb may create on its own (CONVENTIONS.md, "Paths and configuration").
        """
        override = _item(items, "llm_cache_dir").value
        if override:
            return Path(override)
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


# ------------------------------------------------------------------------------------ agent-sdk


@dataclass(frozen=True)
class AgentRequest:
    """One escalation call, as handed to an :data:`AgentRunner`."""

    prompt: str
    model: str
    schema: Mapping[str, Any] | None
    timeout_s: float
    cli_path: Path | None


@dataclass(frozen=True)
class AgentReply:
    """What an :data:`AgentRunner` returns: the text, plus whatever the run reported about cost."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    model_version: str | None = None


#: Injection seam for :class:`AgentSdkProvider`, exactly as :data:`Transport` is for Ollama.
#: Tests pass a function over recorded replies; nothing in the test suite may start a CLI or
#: reach a socket.
AgentRunner = Callable[[AgentRequest], AgentReply]


def subscription_credential(
    env: Mapping[str, str] | None = None, *, home: Path | None = None
) -> str:
    """Name the subscription credential the Agent SDK will use, or raise saying how to get one.

    Two accepted sources, both a Claude Code login rather than a metered key:

    * ``CLAUDE_CODE_OAUTH_TOKEN`` in the environment, from ``claude setup-token``;
    * an existing ``~/.claude/.credentials.json`` written by an interactive ``claude`` login.

    ``ANTHROPIC_API_KEY`` is deliberately **not** accepted. The owner's instruction is that
    escalation runs on the subscription, and falling back to a key that happens to be exported
    would turn a configuration accident into a bill. The error says so rather than failing
    mysteriously later, inside a subprocess.
    """
    active: Mapping[str, str] = os.environ if env is None else env
    token = active.get(OAUTH_TOKEN_VAR)
    if token and token.strip():
        return OAUTH_TOKEN_VAR
    credentials = (Path.home() if home is None else home) / ".claude" / ".credentials.json"
    if credentials.exists():
        return str(credentials)
    extra = (
        f" {API_KEY_VAR} is set, but it is not used: escalation runs on the Claude Code "
        "subscription, not the metered API."
        if active.get(API_KEY_VAR)
        else ""
    )
    raise ProviderConfigError(
        f"no subscription credential for the 'agent-sdk' provider. Run `claude setup-token` and "
        f"put {OAUTH_TOKEN_VAR}=... in env/secrets.local.env (gitignored), or log in with "
        f"`claude` so {credentials} exists.{extra}"
    )


def claude_agent_sdk_runner(request: AgentRequest) -> AgentReply:
    """The real runner: one non-interactive Claude Agent SDK query, tools off, JSON out.

    The credential is checked *before* the SDK is imported, so a misconfigured run fails with an
    actionable message instead of an ImportError or a subprocess that quietly picks up whatever
    credential it can find. ``ANTHROPIC_API_KEY`` is blanked for the child process for the same
    reason (best effort: it stops the SDK's own key lookup, which is where the metered path would
    otherwise start).

    Every built-in tool is disallowed. This provider exists to turn a prompt into JSON, and an
    escalation that could read or write files would be a different, much larger, trust question.
    """
    source = subscription_credential()
    try:
        import claude_agent_sdk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProviderUnavailableError(
            "the 'agent-sdk' provider needs the claude-agent-sdk package "
            "(pip install claude-agent-sdk). It is not a dependency of fermdb yet; see the "
            f"escalation notes in docs/reference/MODEL_ROUTING.md §7a. Credential found: {source}"
        ) from exc

    options_kwargs: dict[str, Any] = {
        "system_prompt": (
            "You are an extraction backend. Reply with a single JSON object and nothing else."
        ),
        "allowed_tools": [],
        "disallowed_tools": [
            "Bash",
            "Read",
            "Write",
            "Edit",
            "NotebookEdit",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Agent",
            "Task",
            "Skill",
            "TodoWrite",
        ],
        "permission_mode": "dontAsk",
        "model": request.model,
        "max_turns": 1,
        "setting_sources": [],
        "env": {API_KEY_VAR: "", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "0"},
    }
    if request.schema is not None:
        options_kwargs["output_format"] = {"type": "json_schema", "schema": dict(request.schema)}
    if request.cli_path is not None:
        options_kwargs["cli_path"] = str(request.cli_path)

    async def _collect() -> AgentReply:
        texts: list[str] = []
        structured: Any = None
        result_text = ""
        usage: Any = None
        finish: str | None = None
        options = claude_agent_sdk.ClaudeAgentOptions(**options_kwargs)
        async for message in claude_agent_sdk.query(prompt=request.prompt, options=options):
            if isinstance(message, claude_agent_sdk.AssistantMessage):
                for block in message.content:
                    if isinstance(block, claude_agent_sdk.TextBlock):
                        texts.append(str(block.text))
            elif isinstance(message, claude_agent_sdk.ResultMessage):
                finish = str(message.subtype)
                structured = getattr(message, "structured_output", None)
                raw = message.result
                result_text = raw if isinstance(raw, str) else json.dumps(raw)
                usage = getattr(message, "usage", None)
        if isinstance(structured, dict):
            text = json.dumps(structured)
        else:
            text = result_text or "\n".join(texts)
        return AgentReply(
            text=text,
            input_tokens=_usage_count(usage, "input_tokens"),
            output_tokens=_usage_count(usage, "output_tokens"),
            finish_reason=finish,
            model_version=request.model,
        )

    try:
        reply: AgentReply = asyncio.run(asyncio.wait_for(_collect(), request.timeout_s))
    except TimeoutError as exc:
        raise ProviderUnavailableError(
            f"the Claude Agent SDK did not finish within {request.timeout_s:g}s"
        ) from exc
    except ProviderError:
        raise
    except Exception as exc:  # the SDK raises its own family; none of it is importable here
        raise ProviderUnavailableError(
            f"the Claude Agent SDK failed: {type(exc).__name__}: {exc}"
        ) from exc
    return reply


def _usage_count(usage: object, key: str) -> int | None:
    if isinstance(usage, Mapping):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return None


class AgentSdkProvider:
    """Claude through the Claude Agent SDK, on a subscription login. The §7a escalation tier.

    Same one-method contract as every other provider, so :func:`fermdb.llm.runtime.run` validates
    an escalated answer with the same checks it applies to a local one. That is the point: the
    escalation tier buys recall, not trust — a Claude extraction is still Zone I, still
    span-verified, still ``unverified`` until a curator says otherwise.
    """

    name = "agent-sdk"

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cli_path: Path | None = None,
        runner: AgentRunner | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._cli_path = cli_path
        self._runner: AgentRunner = claude_agent_sdk_runner if runner is None else runner

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """Run one query. ``options`` is accepted and ignored: sampling is not exposed here."""
        started = time.monotonic()
        reply = self._runner(
            AgentRequest(
                prompt=prompt,
                model=model,
                schema=schema,
                timeout_s=self._timeout_s if timeout_s is None else timeout_s,
                cli_path=self._cli_path,
            )
        )
        if not reply.text.strip():
            raise ProviderResponseError(
                f"{self.name} returned an empty reply for model {model!r} "
                f"(finish_reason={reply.finish_reason!r})"
            )
        return Completion(
            text=reply.text,
            provider=self.name,
            model=model,
            model_version=reply.model_version or model,
            prompt_tokens=reply.input_tokens,
            completion_tokens=reply.output_tokens,
            duration_s=time.monotonic() - started,
            finish_reason=reply.finish_reason,
        )


# ------------------------------------------------------------------------------------------ api


#: Raised by :class:`ApiProvider`. Kept as a constant so the pointer stays in one place.
API_PROVIDER_POINTER: Final[str] = (
    "the 'api' provider is a deliberate stub: this build never calls the metered Anthropic API. "
    "Claude is reached through 'agent-sdk', which authenticates with a Claude Code subscription "
    f"login ({OAUTH_TOKEN_VAR} from `claude setup-token`) - set "
    "FERMDB_LLM_ESCALATION_PROVIDER=agent-sdk. Use FERMDB_LLM_PROVIDER=ollama for local runs, or "
    "'mock' in tests. Wiring a metered client here is a cost decision, not a code change: read "
    "docs/reference/MODEL_ROUTING.md first - §4 says which roles may use a stronger model and §5 "
    "says which may never, whatever the provider."
)


class ApiProvider:
    """Placeholder for the metered Anthropic API client. Construction is fine; calling it is not.

    Kept deliberately, rather than deleted: a named stub that raises is what stops somebody
    adding a metered path by reflex when the subscription one is inconvenient. Construction
    succeeds so configuration can be inspected, listed and reported without exploding; the
    failure lands on the one operation that would have spent money.
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


def _build(
    name: str,
    config: LlmConfig,
    *,
    transport: Transport | None,
    mock: MockProvider | None,
    runner: AgentRunner | None,
) -> Provider:
    if name == "mock":
        return mock if mock is not None else MockProvider()
    if name == "ollama":
        return OllamaProvider(
            base_url=config.base_url,
            timeout_s=config.timeout_s,
            options=config.options,
            transport=transport,
        )
    if name == "agent-sdk":
        return AgentSdkProvider(
            timeout_s=config.timeout_s,
            cli_path=config.claude_cli_path,
            runner=runner,
        )
    if name == "api":
        return ApiProvider(config=config)
    raise ProviderConfigError(f"unknown provider {name!r}; expected one of {PROVIDER_NAMES}")


def build_provider(
    config: LlmConfig | None = None,
    *,
    transport: Transport | None = None,
    mock: MockProvider | None = None,
    runner: AgentRunner | None = None,
) -> Provider:
    """Build the configured **local** provider — the one that runs first on everything.

    ``transport`` overrides Ollama's HTTP layer, ``mock`` supplies a pre-loaded mock and
    ``runner`` overrides the Agent SDK's; all three exist so a test can exercise the same factory
    the CLI uses without reaching a socket.
    """
    active = LlmConfig() if config is None else config
    return _build(active.provider, active, transport=transport, mock=mock, runner=runner)


def build_escalation_provider(
    config: LlmConfig | None = None,
    *,
    transport: Transport | None = None,
    mock: MockProvider | None = None,
    runner: AgentRunner | None = None,
) -> Provider:
    """Build the configured **escalation** provider (MODEL_ROUTING.md §7a).

    Separate from :func:`build_provider` because the two tiers are different backends and a run
    holds both at once. Building one costs nothing and reaches nothing; the credential check and
    the subprocess happen on the first :meth:`complete`.
    """
    active = LlmConfig() if config is None else config
    return _build(active.escalation_provider, active, transport=transport, mock=mock, runner=runner)
