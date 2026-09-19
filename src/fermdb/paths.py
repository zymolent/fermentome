"""Path resolution: env/paths.yaml + env/paths.local.yaml + environment variables.

Every location fermdb touches is a key in ``env/paths.yaml``, organised into the three tiers
described in ``docs/reference/CONVENTIONS.md`` ("Paths and configuration") and PLAN.md N.2:

    repo    committed, curated, small    — never auto-created
    derived rebuildable                   — the ONLY tier fermdb ever creates on its own
    source  read-only, never written to   — never auto-created

Resolution order for a key's value, highest precedence first:

    1. the environment variable ``FERMDB_<KEY>`` (upper-cased)
    2. ``env/paths.local.yaml`` (gitignored, machine-specific overrides)
    3. ``env/paths.yaml`` (the shared, portable defaults, committed to the repo)
    4. a built-in fallback baked into this module, used only if no paths.yaml can be found at all

A value may interpolate another key with ``${other_key}``, plus ``${HOME}`` and a leading ``~``
for the user's home directory. Interpolation runs to a fixed point, so a key may reference a key
that itself still needs expanding.

Windows (``D:/x``) and POSIX/WSL (``/mnt/d/x``) drive spellings are both accepted; exactly one
function (:func:`translate_path_spelling`) translates between them, applied once per value after
interpolation, so this project can move from Windows to Linux/WSL without touching paths.yaml.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TIERS: tuple[str, str, str] = ("repo", "derived", "source")
ENV_PREFIX = "FERMDB_"
PATHS_FILENAME = "paths.yaml"
LOCAL_PATHS_FILENAME = "paths.local.yaml"

# A tier's raw document, as loaded from YAML: {"repo": {"repo_root": ".", ...}, "derived": {...}}.
TierDoc = Mapping[str, Mapping[str, Any]]

_IS_WINDOWS = os.name == "nt"
_MAX_INTERPOLATION_PASSES = 10

_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_WSL_MOUNT_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Built-in fallback, used only when no env/paths.yaml can be found on disk at all (for example a
# stray invocation outside the repo, with the installed package itself missing its data files).
#
# This cannot be *derived* from env/paths.yaml at import time: the only case where it is actually
# used is exactly the case where `_discover_paths_file` (below) already failed to find that file
# either by searching upward from the working directory or next to the installed package - so by
# the time this dict would matter, there is no on-disk copy left to read it from. Reading the
# packaged file here would either duplicate the same upward/package-relative search for no benefit
# (the normal case, where it always finds the file `_discover_paths_file` already found, making
# this dict dead code) or fail for the same reason discovery just failed (the fallback case this
# dict exists for). So env/paths.yaml is content-identical to this dict by hand, and
# `tests/test_paths.py::test_builtin_defaults_match_the_real_paths_yaml` is the guard against the
# two drifting apart; that test fails the day this dict stops matching env/paths.yaml.
_BUILTIN_DEFAULTS: TierDoc = {
    "repo": {
        "repo_root": ".",
        "vocabularies_dir": "${repo_root}/data/vocabularies",
        "benchmarks_dir": "${repo_root}/data/benchmarks",
        "strains_dir": "${repo_root}/data/strains",
        "pathways_dir": "${repo_root}/data/pathways",
        "panels_dir": "${repo_root}/data/panels",
        "comparability_dir": "${repo_root}/data/comparability",
        "literature_dir": "${repo_root}/data/literature",
    },
    "derived": {
        "data_dir": "~/fermdb-data",
        "db_file": {"path": "${data_dir}/fermdb.sqlite3", "kind": "file"},
        "matrices_dir": "${data_dir}/matrices",
        "quant_dir": "${data_dir}/quant",
        "genomes_dir": "${data_dir}/genomes",
        "index_dir": "${data_dir}/index",
        "exports_dir": "${data_dir}/exports",
    },
    "source": {
        "source_root": "~/fermdb-source",
        "downloads_dir": "${source_root}/downloads",
        "fastq_dir": "${source_root}/fastq",
    },
}


class PathsConfigError(Exception):
    """env/paths.yaml (or an override) is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class PathEntry:
    """One resolved configuration key."""

    key: str
    tier: str
    kind: str  # "dir" or "file"
    value: Path
    raw: str
    origin: str  # "default", "file", or "env"


def translate_path_spelling(value: str, *, windows: bool = _IS_WINDOWS) -> str:
    """Translate between Windows (``D:/x``) and WSL/POSIX (``/mnt/d/x``) drive spellings.

    This is the one place fermdb converts between the two spellings, so paths.yaml can be written
    once and read correctly on either platform. Anything else — a relative path, a plain POSIX
    path with no drive, a home-relative ``~/...``, a UNC path — passes through unchanged.
    """
    if windows:
        match = _WSL_MOUNT_RE.match(value)
        if match:
            drive, rest = match.group(1).upper(), match.group(2) or ""
            return f"{drive}:/{rest}"
        return value
    match = _WINDOWS_DRIVE_RE.match(value)
    if match:
        drive, rest = match.group(1).lower(), match.group(2).replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return value


def _normalize_spec(key: str, spec: object) -> tuple[str, str]:
    """Return (raw_path, kind) for one entry, accepting a bare string or a {path, kind} mapping."""
    if isinstance(spec, str):
        return spec, "dir"
    if isinstance(spec, Mapping):
        if "path" not in spec:
            raise PathsConfigError(f"path entry '{key}' is missing 'path': {spec!r}")
        kind = str(spec.get("kind", "dir"))
        if kind not in ("dir", "file"):
            raise PathsConfigError(
                f"path entry '{key}' has invalid kind {kind!r}; use 'dir' or 'file'"
            )
        return str(spec["path"]), kind
    raise PathsConfigError(
        f"path entry '{key}' must be a string or a {{path, kind}} mapping, got {spec!r}"
    )


def _interpolate(raw: dict[str, str]) -> dict[str, str]:
    """Expand ${other_key}, ${HOME} and a leading ~ in every value, to a fixed point."""
    values = dict(raw)
    for _ in range(_MAX_INTERPOLATION_PASSES):
        changed = False
        for key, template in values.items():

            def _substitute(match: re.Match[str], _key: str = key) -> str:
                name = match.group(1)
                if name == "HOME":
                    return str(Path.home())
                if name not in values:
                    raise PathsConfigError(f"'{_key}' references unknown key '${{{name}}}'")
                return values[name]

            expanded = os.path.expanduser(_VAR_RE.sub(_substitute, template))
            if expanded != values[key]:
                values[key] = expanded
                changed = True
        if not changed:
            return values
    raise PathsConfigError("circular ${...} reference in path configuration")


def _build_entries(
    layers: Sequence[tuple[str, TierDoc]],
    *,
    env: Mapping[str, str],
    anchor: Path | None = None,
) -> dict[str, PathEntry]:
    """Merge layered docs (lowest precedence first) and environment variables into PathEntries.

    Each layer is (origin_label, doc). A later layer overrides an earlier one key-by-key, not
    tier-by-tier, so ``env/paths.local.yaml`` can override a single key and leave the rest of
    ``env/paths.yaml`` alone. The environment is applied last and wins over every layer.

    ``anchor`` is where a still-relative value (typically ``repo_root: "."``) resolves from. It
    defaults to the current working directory, but `load_paths` passes the directory containing
    the ``env/paths.yaml`` actually used, so `repo_root` means the repo regardless of where fermdb
    was invoked from.
    """
    anchor = Path.cwd() if anchor is None else anchor
    raw_of: dict[str, str] = {}
    kind_of: dict[str, str] = {}
    tier_of: dict[str, str] = {}
    origin_of: dict[str, str] = {}

    for origin_label, doc in layers:
        for tier in TIERS:
            for key, spec in doc.get(tier, {}).items():
                path_str, kind = _normalize_spec(key, spec)
                raw_of[key] = path_str
                kind_of[key] = kind
                tier_of[key] = tier
                origin_of[key] = origin_label

    for key in list(raw_of):
        env_var = ENV_PREFIX + key.upper()
        env_value = env.get(env_var)
        if env_value:
            raw_of[key] = env_value
            origin_of[key] = "env"

    resolved = _interpolate(raw_of)

    entries: dict[str, PathEntry] = {}
    for key, value_str in resolved.items():
        translated = translate_path_spelling(value_str)
        candidate = Path(translated)
        # pathlib.PureWindowsPath treats a driveless root like "/mine" as NOT absolute, even
        # though it plainly is not relative either; a leading slash always means "do not join
        # with anchor", on every platform.
        rooted = candidate.is_absolute() or translated.startswith(("/", "\\"))
        value = candidate if rooted else anchor / candidate
        entries[key] = PathEntry(
            key=key,
            tier=tier_of[key],
            kind=kind_of[key],
            value=value.resolve(),
            raw=raw_of[key],
            origin=origin_of[key],
        )
    return entries


def _read_yaml(path: Path) -> TierDoc:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without the dependency
        raise PathsConfigError(
            "PyYAML is required to read path configuration (add 'pyyaml' as a dependency)"
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    if not isinstance(doc, dict):
        raise PathsConfigError(f"{path}: expected a mapping at the top level")
    return doc


def _discover_paths_file(start: Path) -> Path | None:
    """Search ``start`` and its parents for ``env/paths.yaml``, falling back to a path relative
    to this installed package so fermdb still finds its config when run from elsewhere."""
    for directory in (start, *start.parents):
        candidate = directory / "env" / PATHS_FILENAME
        if candidate.is_file():
            return candidate
    package_fallback = Path(__file__).resolve().parents[2] / "env" / PATHS_FILENAME
    return package_fallback if package_fallback.is_file() else None


def load_paths(
    *,
    paths_file: Path | None = None,
    local_paths_file: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, PathEntry]:
    """Resolve every configured path key into a :class:`PathEntry`.

    ``paths_file`` / ``local_paths_file`` let a caller (tests, mainly) pin an exact file instead
    of the normal upward search from the current directory. Passing ``env`` isolates a caller from
    the real process environment.
    """
    active_env = os.environ if env is None else env
    layers: list[tuple[str, TierDoc]] = [("default", _BUILTIN_DEFAULTS)]
    anchor = Path.cwd()

    if paths_file is not None and not paths_file.is_file():
        raise PathsConfigError(f"paths file not found: {paths_file}")
    resolved_main = paths_file if paths_file is not None else _discover_paths_file(Path.cwd())

    if resolved_main is not None:
        layers.append(("file", _read_yaml(resolved_main)))

        # By convention paths.yaml lives at <repo_root>/env/paths.yaml, so a still-relative value
        # such as the default repo_root: "." should mean "the repo this file belongs to", not
        # "wherever fermdb happened to be invoked from". Fall back to the file's own directory for
        # a paths_file that does not follow that convention (chiefly a test fixture).
        main_dir = resolved_main.resolve().parent
        anchor = main_dir.parent if main_dir.name == "env" else main_dir

        if local_paths_file is not None:
            if not local_paths_file.is_file():
                raise PathsConfigError(f"local paths file not found: {local_paths_file}")
            resolved_local: Path | None = local_paths_file
        else:
            candidate = resolved_main.with_name(LOCAL_PATHS_FILENAME)
            resolved_local = candidate if candidate.is_file() else None

        if resolved_local is not None:
            layers.append(("file", _read_yaml(resolved_local)))

    return _build_entries(layers, env=active_env, anchor=anchor)
