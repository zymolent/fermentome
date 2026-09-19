"""The `Settings` object: a friendly wrapper over `fermdb.paths` for the rest of the codebase.

Nothing in this module hardcodes a path. Every value comes from `paths.load_paths`, which reads
`env/paths.yaml`, `env/paths.local.yaml` and the environment (see that module's docstring for the
precedence rules and the three tiers).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .paths import PathEntry, load_paths


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
    """Resolved fermdb configuration: every path, its tier, origin and value.

    Access a path either by name (`settings.data_dir`, `settings.db_file`, ...) or by key
    (`settings.path("db_file")`). Both return the same resolved, absolute `pathlib.Path`.
    """

    def __init__(self, entries: Mapping[str, PathEntry]) -> None:
        self._entries: dict[str, PathEntry] = dict(entries)

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
        nothing and let discovery find the repo's `env/paths.yaml`.
        """
        return cls(load_paths(paths_file=paths_file, local_paths_file=local_paths_file, env=env))

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
