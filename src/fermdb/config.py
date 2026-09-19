"""The `Settings` object: a friendly wrapper over `fermdb.paths` for the rest of the codebase.

Nothing in this module hardcodes a path. Every value comes from `paths.load_paths`, which reads
`env/paths.yaml`, `env/paths.local.yaml` and the environment (see that module's docstring for the
precedence rules and the three tiers).

`Settings` also owns the **non-path settings** — today the `FERMDB_LLM_*` family. They cannot live
in `env/paths.yaml`, because every key in that file is resolved into a `pathlib.Path`, and a
provider name or a model id is not a path. They still belong to configuration rather than to a
call site, for the reason CONVENTIONS.md gives for paths: one authority per fact, reportable by
`fermdb config`. So the defaults and the environment-variable names live here, in `LLM_SETTINGS`,
resolved once by `resolve_settings` and read through `Settings.setting`. A review found
`fermdb.llm.providers` reading `os.environ` directly, outside `Settings`; this module is the fix,
and `providers.py` now parses what it is handed rather than going to the environment itself.

**Credentials are never settings.** No key here holds a token. The escalation provider reads
`CLAUDE_CODE_OAUTH_TOKEN` from the process environment (put it in `env/secrets.local.env`, which
is gitignored), exactly as the sibling genome-db project does.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .paths import ENV_PREFIX, PathEntry, load_paths

# ------------------------------------------------------------------------------- LLM settings

#: Every LLM setting's environment variable starts here: ``FERMDB_LLM_PROVIDER`` and friends.
LLM_ENV_PREFIX: Final[str] = ENV_PREFIX + "LLM_"

#: Default when nothing is configured: offline, deterministic, incapable of spending anything.
DEFAULT_LLM_PROVIDER: Final[str] = "mock"

#: Where a local Ollama daemon listens unless configured otherwise.
DEFAULT_LLM_BASE_URL: Final[str] = "http://localhost:11434"

#: Generous by design. A 27B model answering a long extraction prompt on one RTX 4090 is not
#: fast, and a timeout that fires mid-generation looks exactly like a daemon that is down.
DEFAULT_LLM_TIMEOUT_S: Final[float] = 900.0

#: The documented default local model per role (MODEL_ROUTING.md §4 and §7): high-volume triage
#: gets the cheap model, extraction a larger one *and* the full validator, vision the figures and
#: scanned pages. The tier is a cost decision, never a safety one.
#:
#: This mapping is the one place a model name is written down. Everything else asks
#: ``LlmConfig.model_for(role)``; ``tests/test_llm.py`` fails the day a literal appears elsewhere.
DEFAULT_LLM_MODELS: Final[Mapping[str, str]] = {
    "triage": "qwen2.5:7b-instruct",
    "extraction": "qwen3.6:27b",
    "vision": "qwen2.5vl:7b",
}

#: Roles in a stable order, for reporting and for the ``FERMDB_LLM_MODEL_<ROLE>`` overrides.
DEFAULT_LLM_MODEL_ROLES: Final[tuple[str, ...]] = tuple(DEFAULT_LLM_MODELS)

#: Sampling defaults. Greedy and seeded: an extraction that cannot be reproduced cannot be
#: audited, and `temperature: 0` costs nothing here.
DEFAULT_LLM_OPTIONS: Final[Mapping[str, Any]] = {
    "temperature": 0.0,
    "seed": 0,
    "num_ctx": 8192,
}

#: Which runtime the escalation tier uses (MODEL_ROUTING.md §7a). ``agent-sdk`` is the Claude
#: Agent SDK, which authenticates the way the Claude Code CLI does — ``CLAUDE_CODE_OAUTH_TOKEN``
#: from ``claude setup-token``, a subscription login. ``mock`` is the deterministic offline
#: baseline used by every test. ``api`` (the metered Anthropic API client) is deliberately not
#: implemented; see ``fermdb.llm.providers.ApiProvider``.
#:
#: This mirrors ``claude_provider`` in D:/project/genome-db/env/paths.yaml, which solved the same
#: problem first. The default names the intended production path, but nothing escalates on its
#: own: escalation happens only where a caller has explicitly built an
#: :class:`~fermdb.llm.escalation.EscalationRunner` and handed it a provider.
DEFAULT_ESCALATION_PROVIDER: Final[str] = "agent-sdk"

#: The escalation model, as a **full model id, never an alias** — an alias moves under a run and
#: makes it unreproducible. Same id the sibling project pins for its judgement-carrying agents.
DEFAULT_ESCALATION_MODEL: Final[str] = "claude-opus-5"

#: How many documents one run may escalate before the budget is exhausted. Past it, documents are
#: marked ``escalation_pending`` rather than silently keeping the local result (§7a).
DEFAULT_ESCALATION_MAX_DOCUMENTS: Final[str] = "200"


@dataclass(frozen=True)
class SettingSpec:
    """One non-path setting: its key, its documented default, and what it is for."""

    key: str
    default: str
    doc: str

    @property
    def env_var(self) -> str:
        """The environment variable that overrides this key, e.g. ``FERMDB_LLM_PROVIDER``."""
        return ENV_PREFIX + self.key.upper()


@dataclass(frozen=True)
class SettingItem:
    """One resolved non-path setting, with where its value came from."""

    key: str
    env_var: str
    value: str
    origin: str  # "default" or "env"
    doc: str


#: Every LLM setting, with its default. Values are kept as strings here and parsed by the module
#: that uses them (`fermdb.llm.providers`), which is also the module that knows what a bad value
#: means and can say so in its own error type. An empty default means "unset".
LLM_SETTINGS: Final[tuple[SettingSpec, ...]] = (
    SettingSpec(
        "llm_provider",
        DEFAULT_LLM_PROVIDER,
        "local inference backend: ollama | mock | agent-sdk | api",
    ),
    SettingSpec("llm_base_url", DEFAULT_LLM_BASE_URL, "where the Ollama daemon listens"),
    SettingSpec("llm_timeout_s", str(DEFAULT_LLM_TIMEOUT_S), "seconds allowed for one call"),
    *(
        SettingSpec(
            f"llm_model_{role}",
            DEFAULT_LLM_MODELS[role],
            f"model for the {role} role, as a full id",
        )
        for role in DEFAULT_LLM_MODEL_ROLES
    ),
    SettingSpec(
        "llm_temperature",
        str(DEFAULT_LLM_OPTIONS["temperature"]),
        "sampling temperature; 0 keeps a run reproducible",
    ),
    SettingSpec("llm_seed", str(DEFAULT_LLM_OPTIONS["seed"]), "sampling seed"),
    SettingSpec("llm_num_ctx", str(DEFAULT_LLM_OPTIONS["num_ctx"]), "context window, in tokens"),
    SettingSpec("llm_num_predict", "", "cap on generated tokens; empty means the backend default"),
    SettingSpec("llm_cache", "true", "cache validated results on disk"),
    SettingSpec("llm_cache_dir", "", "override the derived-tier cache directory"),
    SettingSpec(
        "llm_escalation_provider",
        DEFAULT_ESCALATION_PROVIDER,
        "runtime for the escalation tier: agent-sdk | mock | api",
    ),
    SettingSpec(
        "llm_escalation_model",
        DEFAULT_ESCALATION_MODEL,
        "escalation model, as a full id (never an alias)",
    ),
    SettingSpec(
        "llm_escalation_max_documents",
        DEFAULT_ESCALATION_MAX_DOCUMENTS,
        "documents one run may escalate before the budget is exhausted",
    ),
    SettingSpec(
        "llm_escalation_max_tokens",
        "",
        "token budget for escalation; empty means documents are the only cap",
    ),
    SettingSpec(
        "llm_claude_cli_path",
        "",
        "Claude Code CLI to drive; empty uses the one bundled with the Agent SDK",
    ),
)

_LLM_SETTINGS_BY_KEY: Final[Mapping[str, SettingSpec]] = {spec.key: spec for spec in LLM_SETTINGS}


def resolve_settings(env: Mapping[str, str] | None = None) -> dict[str, SettingItem]:
    """Resolve every non-path setting from the environment over its documented default.

    The one place `FERMDB_LLM_*` is read. A variable that is unset, empty or whitespace counts as
    unset, so `FERMDB_LLM_MODEL_EXTRACTION=""` means "use the default" rather than "use the model
    named empty string".
    """
    active: Mapping[str, str] = os.environ if env is None else env
    resolved: dict[str, SettingItem] = {}
    for spec in LLM_SETTINGS:
        raw = active.get(spec.env_var)
        if raw is not None and raw.strip():
            resolved[spec.key] = SettingItem(spec.key, spec.env_var, raw.strip(), "env", spec.doc)
        else:
            resolved[spec.key] = SettingItem(
                spec.key, spec.env_var, spec.default, "default", spec.doc
            )
    return resolved


@dataclass(frozen=True)
class CheckItem:
    """The result of checking, or ensuring, one configured path."""

    key: str
    tier: str
    ok: bool
    detail: str
    value: Path


@dataclass(frozen=True)
class CheckReport:
    """The result of `Settings.check()`: one item per configured key."""

    items: tuple[CheckItem, ...]

    @property
    def ok(self) -> bool:
        """False if any repo- or source-tier path that should already exist does not."""
        return all(item.ok for item in self.items)


class Settings:
    """Resolved fermdb configuration: every path, its tier, origin and value — plus the
    non-path settings (`FERMDB_LLM_*`), so one object answers "how is this run configured".

    Access a path either by name (`settings.data_dir`, `settings.db_file`, ...) or by key
    (`settings.path("db_file")`). Both return the same resolved, absolute `pathlib.Path`.
    Non-path settings are strings, read with `settings.setting("llm_provider")`, and are parsed
    by whichever module owns their meaning.
    """

    def __init__(
        self, entries: Mapping[str, PathEntry], *, env: Mapping[str, str] | None = None
    ) -> None:
        self._entries: dict[str, PathEntry] = dict(entries)
        self._settings: dict[str, SettingItem] = resolve_settings(env)

    @classmethod
    def load(
        cls,
        *,
        paths_file: Path | None = None,
        local_paths_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Settings:
        """Resolve settings the normal way: discover env/paths.yaml, apply overrides and env vars.

        Arguments mirror `fermdb.paths.load_paths`; tests pin exact files, everyday callers pass
        nothing and let discovery find the repo's `env/paths.yaml`. `env` isolates both halves —
        the paths and the `FERMDB_LLM_*` settings — from the real process environment.
        """
        return cls(
            load_paths(paths_file=paths_file, local_paths_file=local_paths_file, env=env),
            env=env,
        )

    def setting(self, key: str) -> str:
        """The resolved string value for a non-path setting, or raise if `key` is not configured."""
        return self.setting_item(key).value

    def setting_item(self, key: str) -> SettingItem:
        """The full `SettingItem` (value, environment variable, origin, doc) for `key`."""
        try:
            return self._settings[key]
        except KeyError as exc:
            known = ", ".join(sorted(_LLM_SETTINGS_BY_KEY))
            raise KeyError(f"unknown setting key: {key!r} (configured: {known})") from exc

    def setting_items(self) -> Mapping[str, SettingItem]:
        """Every resolved non-path setting, keyed by name. What `LlmConfig.load` reads."""
        return dict(self._settings)

    def describe_settings(self) -> list[SettingItem]:
        """Every non-path setting, sorted, for `fermdb config` to print beside the paths."""
        return sorted(self._settings.values(), key=lambda item: item.key)

    def path(self, key: str) -> Path:
        """Return the resolved path for `key`, or raise if `key` is not configured."""
        try:
            return self._entries[key].value
        except KeyError as exc:
            raise KeyError(f"unknown path configuration key: {key!r}") from exc

    def entry(self, key: str) -> PathEntry:
        """Return the full `PathEntry` (tier, kind, origin, raw template) for `key`."""
        try:
            return self._entries[key]
        except KeyError as exc:
            raise KeyError(f"unknown path configuration key: {key!r}") from exc

    def __getattr__(self, name: str) -> Path:
        # Only reached when normal attribute lookup fails, so this never shadows _entries etc.
        entries = self.__dict__.get("_entries", {})
        if name in entries:
            entry: PathEntry = entries[name]
            return entry.value
        raise AttributeError(f"{type(self).__name__!r} has no path {name!r}")

    def describe(self) -> list[PathEntry]:
        """Every configured key, sorted for stable, readable reporting."""
        return sorted(self._entries.values(), key=lambda e: (e.tier, e.key))

    def ensure_derived(self) -> None:
        """Create every derived-tier directory (and, for a file key, its parent directory).

        The only tier fermdb ever creates on its own; repo and source paths are never touched.
        """
        for entry in self._entries.values():
            if entry.tier != "derived":
                continue
            target = entry.value.parent if entry.kind == "file" else entry.value
            target.mkdir(parents=True, exist_ok=True)

    def check(self, *, create_derived: bool = True) -> CheckReport:
        """Verify repo- and source-tier paths exist, and (by default) create derived-tier ones.

        A repo- or source-tier path is never auto-created, so a missing one is reported as not
        `ok`. A derived-tier path is created on the spot (unless `create_derived` is False) and is
        always reported `ok`, because it is rebuildable by definition.
        """
        if create_derived:
            self.ensure_derived()

        items = []
        for entry in self.describe():
            if entry.tier == "derived":
                exists = (
                    entry.value.exists() if entry.kind == "dir" else entry.value.parent.exists()
                )
                detail = "ready" if exists else "not yet created"
                items.append(CheckItem(entry.key, entry.tier, exists, detail, entry.value))
            else:
                exists = entry.value.exists()
                detail = "exists" if exists else "missing"
                items.append(CheckItem(entry.key, entry.tier, exists, detail, entry.value))
        return CheckReport(tuple(items))
