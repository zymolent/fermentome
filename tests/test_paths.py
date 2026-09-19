"""Tests for path resolution (`fermdb.paths`) and the `Settings` wrapper (`fermdb.config`).

Every test that resolves paths pins them into a `tmp_path`, via an explicit `paths_file` and/or
env var overrides, rather than relying on the real `env/paths.yaml` or the developer's actual
home directory. `fermdb config check` creates directories on disk (the derived tier, by design),
so any test that reaches it must first point every root at a temp directory — never at the real
`~/fermdb-data`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fermdb import cli
from fermdb.config import Settings
from fermdb.paths import (
    _BUILTIN_DEFAULTS,
    PathsConfigError,
    _build_entries,
    _discover_paths_file,
    load_paths,
    translate_path_spelling,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PATHS_YAML = REPO_ROOT / "env" / "paths.yaml"


# ------------------------------------------------------------------------ translate_path_spelling


def test_translate_windows_drive_passes_through_on_windows() -> None:
    assert translate_path_spelling("D:/project/x", windows=True) == "D:/project/x"


def test_translate_windows_drive_to_wsl_mount() -> None:
    assert translate_path_spelling("D:/project/x", windows=False) == "/mnt/d/project/x"


def test_translate_windows_backslashes_to_wsl_mount() -> None:
    assert translate_path_spelling(r"D:\project\x", windows=False) == "/mnt/d/project/x"


def test_translate_wsl_mount_to_windows_drive() -> None:
    assert translate_path_spelling("/mnt/d/project/x", windows=True) == "D:/project/x"


def test_translate_wsl_mount_passes_through_on_posix() -> None:
    assert translate_path_spelling("/mnt/d/project/x", windows=False) == "/mnt/d/project/x"


def test_translate_leaves_relative_and_home_paths_alone() -> None:
    assert translate_path_spelling("relative/path", windows=True) == "relative/path"
    assert translate_path_spelling("~/fermdb-data", windows=False) == "~/fermdb-data"


def test_translate_drive_letter_is_case_insensitive_on_input() -> None:
    assert translate_path_spelling("d:/project/x", windows=False) == "/mnt/d/project/x"
    assert translate_path_spelling("/mnt/D/project/x", windows=True) == "D:/project/x"


# --------------------------------------------------------------------------- _build_entries


def _doc(**tiers: dict[str, object]) -> dict[str, dict[str, object]]:
    return tiers


def test_build_entries_interpolates_a_root_into_its_children() -> None:
    doc = _doc(
        repo={"repo_root": "/repo", "vocab_dir": "${repo_root}/data/vocab"},
        derived={},
        source={},
    )
    entries = _build_entries([("file", doc)], env={})
    assert entries["vocab_dir"].value == Path("/repo/data/vocab").resolve()
    assert entries["vocab_dir"].tier == "repo"
    assert entries["vocab_dir"].kind == "dir"
    assert entries["vocab_dir"].origin == "file"


def test_build_entries_expands_home_and_tilde() -> None:
    doc = _doc(
        repo={},
        derived={"data_dir": "~/fermdb-data", "cache_dir": "${HOME}/cache"},
        source={},
    )
    entries = _build_entries([("file", doc)], env={})
    assert entries["data_dir"].value == (Path.home() / "fermdb-data").resolve()
    assert entries["cache_dir"].value == (Path.home() / "cache").resolve()


def test_build_entries_file_kind_defaults_and_explicit() -> None:
    doc = _doc(
        repo={},
        derived={
            "plain_dir": "/data/plain",
            "db_file": {"path": "/data/db.sqlite3", "kind": "file"},
        },
        source={},
    )
    entries = _build_entries([("file", doc)], env={})
    assert entries["plain_dir"].kind == "dir"
    assert entries["db_file"].kind == "file"
    assert entries["db_file"].value == Path("/data/db.sqlite3").resolve()


def test_build_entries_invalid_kind_raises() -> None:
    doc = _doc(repo={}, derived={"x": {"path": "/y", "kind": "socket"}}, source={})
    with pytest.raises(PathsConfigError):
        _build_entries([("file", doc)], env={})


def test_build_entries_later_layer_overrides_earlier_key_by_key() -> None:
    base = _doc(repo={"repo_root": "/base"}, derived={"data_dir": "/base-data"}, source={})
    override = _doc(repo={"repo_root": "/override"}, derived={}, source={})
    entries = _build_entries([("default", base), ("file", override)], env={})
    assert entries["repo_root"].value == Path("/override").resolve()
    assert entries["repo_root"].origin == "file"
    # data_dir was not touched by the override layer, so it keeps the base layer's value/origin.
    assert entries["data_dir"].value == Path("/base-data").resolve()
    assert entries["data_dir"].origin == "default"


def test_build_entries_env_wins_over_file() -> None:
    doc = _doc(repo={"repo_root": "/from-file"}, derived={}, source={})
    entries = _build_entries([("file", doc)], env={"FERMDB_REPO_ROOT": "/from-env"})
    assert entries["repo_root"].value == Path("/from-env").resolve()
    assert entries["repo_root"].origin == "env"


def test_build_entries_env_override_of_a_root_propagates_to_children() -> None:
    doc = _doc(
        repo={"repo_root": "/from-file", "vocab_dir": "${repo_root}/data/vocab"},
        derived={},
        source={},
    )
    entries = _build_entries([("file", doc)], env={"FERMDB_REPO_ROOT": "/from-env"})
    assert entries["vocab_dir"].value == Path("/from-env/data/vocab").resolve()
    # vocab_dir's own template still came from the file, even though an ingredient came from env.
    assert entries["vocab_dir"].origin == "file"


def test_build_entries_empty_env_value_does_not_override() -> None:
    doc = _doc(repo={"repo_root": "/from-file"}, derived={}, source={})
    entries = _build_entries([("file", doc)], env={"FERMDB_REPO_ROOT": ""})
    assert entries["repo_root"].value == Path("/from-file").resolve()
    assert entries["repo_root"].origin == "file"


def test_build_entries_unknown_reference_raises() -> None:
    doc = _doc(repo={"x": "${no_such_key}/y"}, derived={}, source={})
    with pytest.raises(PathsConfigError, match="no_such_key"):
        _build_entries([("file", doc)], env={})


def test_build_entries_missing_path_key_raises() -> None:
    doc = _doc(repo={}, derived={"x": {"kind": "file"}}, source={})
    with pytest.raises(PathsConfigError):
        _build_entries([("file", doc)], env={})


# --------------------------------------------------------------------------- load_paths (files)


def test_load_paths_reads_a_real_file(tmp_path: Path) -> None:
    paths_yaml = tmp_path / "env" / "paths.yaml"
    paths_yaml.parent.mkdir(parents=True)
    paths_yaml.write_text(
        "repo:\n"
        "  repo_root: '.'\n"
        "  vocab_dir: '${repo_root}/data/vocab'\n"
        "derived:\n"
        "  data_dir: '.'\n"
        "source:\n"
        "  source_root: '.'\n",
        encoding="utf-8",
    )
    entries = load_paths(paths_file=paths_yaml, env={"FERMDB_REPO_ROOT": str(tmp_path)})
    assert entries["vocab_dir"].value == (tmp_path / "data" / "vocab").resolve()
    assert entries["vocab_dir"].origin == "file"


def test_load_paths_local_file_overrides_one_key(tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / "paths.yaml").write_text(
        "repo:\n  repo_root: '/shared'\n  vocab_dir: '${repo_root}/data/vocab'\n"
        "derived: {}\nsource: {}\n",
        encoding="utf-8",
    )
    (env_dir / "paths.local.yaml").write_text(
        "repo:\n  repo_root: '/mine'\nderived: {}\nsource: {}\n",
        encoding="utf-8",
    )
    entries = load_paths(paths_file=env_dir / "paths.yaml", env={})
    assert entries["repo_root"].value == Path("/mine").resolve()
    # vocab_dir's own raw template is still the shared file's; only repo_root itself was
    # overridden by the local file, and that root change should still propagate.
    assert entries["vocab_dir"].value == Path("/mine/data/vocab").resolve()


def test_load_paths_explicit_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PathsConfigError):
        load_paths(paths_file=tmp_path / "nope.yaml", env={})


def test_load_paths_explicit_missing_local_file_raises(tmp_path: Path) -> None:
    paths_yaml = tmp_path / "paths.yaml"
    paths_yaml.write_text("repo: {}\nderived: {}\nsource: {}\n", encoding="utf-8")
    with pytest.raises(PathsConfigError):
        load_paths(paths_file=paths_yaml, local_paths_file=tmp_path / "nope.local.yaml", env={})


def test_discover_paths_file_searches_upward(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "paths.yaml").write_text("repo: {}\nderived: {}\nsource: {}\n")
    found = _discover_paths_file(nested)
    assert found == (tmp_path / "env" / "paths.yaml")


# ------------------------------------------------------------------------- the real env/paths.yaml


def test_builtin_defaults_match_the_real_paths_yaml() -> None:
    """`_BUILTIN_DEFAULTS` is a hand-kept copy of `env/paths.yaml` (see that dict's comment for why
    it cannot simply be derived from the file at import time: the one case it is used in is
    exactly the case where the file cannot be found at all). This is the guard against the two
    drifting apart — the paths convention forbids two authorities for one fact, and this test is
    what makes a silent drift between them a loud, immediate test failure instead.
    """
    with REAL_PATHS_YAML.open("r", encoding="utf-8") as handle:
        real_doc = yaml.safe_load(handle)
    assert real_doc == _BUILTIN_DEFAULTS, (
        "env/paths.yaml and fermdb.paths._BUILTIN_DEFAULTS have drifted apart; the built-in "
        "fallback is a hand-kept copy of the real file and must be updated to match it exactly"
    )


def test_real_paths_yaml_has_every_required_key() -> None:
    entries = load_paths(
        paths_file=REAL_PATHS_YAML,
        env={
            "FERMDB_REPO_ROOT": "/r",
            "FERMDB_DATA_DIR": "/d",
            "FERMDB_SOURCE_ROOT": "/s",
        },
    )
    expected_repo = {
        "repo_root",
        "vocabularies_dir",
        "benchmarks_dir",
        "strains_dir",
        "pathways_dir",
        "panels_dir",
        "comparability_dir",
        "literature_dir",
    }
    expected_derived = {
        "data_dir",
        "db_file",
        "matrices_dir",
        "quant_dir",
        "genomes_dir",
        "index_dir",
        "exports_dir",
    }
    expected_source = {"source_root", "downloads_dir", "fastq_dir"}

    assert expected_repo <= entries.keys()
    assert expected_derived <= entries.keys()
    assert expected_source <= entries.keys()

    for key in expected_repo:
        assert entries[key].tier == "repo"
    for key in expected_derived:
        assert entries[key].tier == "derived"
    for key in expected_source:
        assert entries[key].tier == "source"

    assert entries["db_file"].kind == "file"
    assert entries["vocabularies_dir"].kind == "dir"

    # Every non-root key resolves under its tier's root, wherever that root was pointed.
    assert entries["vocabularies_dir"].value == Path("/r/data/vocabularies").resolve()
    assert entries["db_file"].value == Path("/d/fermdb.sqlite3").resolve()
    assert entries["downloads_dir"].value == Path("/s/downloads").resolve()


def test_real_paths_yaml_repo_root_anchors_to_the_file_not_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run from an unrelated directory: repo_root's default "." must still mean the repo that
    # env/paths.yaml belongs to, not wherever the process happens to be invoked from.
    monkeypatch.chdir(tmp_path)
    entries = load_paths(paths_file=REAL_PATHS_YAML, env={})
    assert entries["repo_root"].value == REPO_ROOT.resolve()
    assert entries["vocabularies_dir"].value == (REPO_ROOT / "data" / "vocabularies").resolve()


def test_every_real_key_has_an_env_var_form() -> None:
    entries = load_paths(paths_file=REAL_PATHS_YAML, env={})
    for key in entries:
        env_var = "FERMDB_" + key.upper()
        overridden = load_paths(paths_file=REAL_PATHS_YAML, env={env_var: "/overridden-" + key})
        assert overridden[key].value == Path("/overridden-" + key).resolve()
        assert overridden[key].origin == "env"


# --------------------------------------------------------------------------- Settings / config.py


def test_settings_attribute_and_path_access_agree(tmp_path: Path) -> None:
    settings = Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={"FERMDB_REPO_ROOT": str(tmp_path), "FERMDB_DATA_DIR": str(tmp_path / "derived")},
    )
    assert settings.repo_root == settings.path("repo_root")
    assert settings.repo_root == tmp_path.resolve()


def test_settings_unknown_key_raises() -> None:
    settings = Settings.load(paths_file=REAL_PATHS_YAML, env={})
    with pytest.raises(KeyError):
        settings.path("not_a_real_key")
    with pytest.raises(AttributeError):
        _ = settings.not_a_real_key


def test_settings_describe_reports_origin_and_is_sorted_by_tier_then_key(tmp_path: Path) -> None:
    settings = Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={"FERMDB_DB_FILE": str(tmp_path / "custom.sqlite3")},
    )
    rows = settings.describe()
    tiers_seen = [entry.tier for entry in rows]
    assert tiers_seen == sorted(tiers_seen)
    db_entry = next(e for e in rows if e.key == "db_file")
    assert db_entry.origin == "env"
    assert db_entry.value == (tmp_path / "custom.sqlite3").resolve()


def test_settings_check_fails_when_repo_and_source_tiers_are_missing(tmp_path: Path) -> None:
    missing_repo = tmp_path / "no-such-repo"
    missing_source = tmp_path / "no-such-source"
    settings = Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={
            "FERMDB_REPO_ROOT": str(missing_repo),
            "FERMDB_SOURCE_ROOT": str(missing_source),
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
        },
    )
    report = settings.check()
    assert report.ok is False
    missing_keys = {item.key for item in report.items if not item.ok}
    assert "repo_root" in missing_keys
    assert "source_root" in missing_keys
    # The derived tier is always auto-created, so it never blocks `check`.
    assert all(item.ok for item in report.items if item.tier == "derived")


def test_settings_check_creates_derived_tier_and_passes_once_repo_and_source_exist(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    source_root = tmp_path / "source"
    data_dir = tmp_path / "derived"
    for name in (
        "vocabularies",
        "benchmarks",
        "strains",
        "pathways",
        "panels",
        "comparability",
        "literature",
    ):
        (repo_root / "data" / name).mkdir(parents=True)
    for name in ("downloads", "fastq"):
        (source_root / name).mkdir(parents=True)
    settings = Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={
            "FERMDB_REPO_ROOT": str(repo_root),
            "FERMDB_SOURCE_ROOT": str(source_root),
            "FERMDB_DATA_DIR": str(data_dir),
        },
    )
    assert not data_dir.exists()
    report = settings.check()
    assert report.ok is True
    assert data_dir.exists()
    assert (data_dir / "matrices").is_dir()
    # db_file is a file key: only its parent directory is created, never the file itself.
    assert not (data_dir / "fermdb.sqlite3").exists()
    assert data_dir.is_dir()


def test_settings_check_without_create_derived_does_not_touch_disk(tmp_path: Path) -> None:
    data_dir = tmp_path / "derived-untouched"
    settings = Settings.load(
        paths_file=REAL_PATHS_YAML,
        env={
            "FERMDB_REPO_ROOT": str(tmp_path),
            "FERMDB_SOURCE_ROOT": str(tmp_path),
            "FERMDB_DATA_DIR": str(data_dir),
        },
    )
    settings.check(create_derived=False)
    assert not data_dir.exists()


# --------------------------------------------------------------------------- CLI wiring


def test_cli_config_prints_every_key(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("FERMDB_REPO_ROOT", str(tmp_path / "repo"))
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))
    monkeypatch.setenv("FERMDB_SOURCE_ROOT", str(tmp_path / "source"))

    exit_code = cli.main(["config"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "db_file" in out
    assert "vocabularies_dir" in out
    assert not (tmp_path / "derived").exists()  # plain `config` never creates anything


def test_cli_config_check_exit_codes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    repo_root = tmp_path / "repo"
    source_root = tmp_path / "source"
    monkeypatch.setenv("FERMDB_REPO_ROOT", str(repo_root))
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))
    monkeypatch.setenv("FERMDB_SOURCE_ROOT", str(source_root))

    assert cli.main(["config", "check"]) == 1  # repo_root/source_root don't exist yet

    for name in (
        "vocabularies",
        "benchmarks",
        "strains",
        "pathways",
        "panels",
        "comparability",
        "literature",
    ):
        (repo_root / "data" / name).mkdir(parents=True)
    for name in ("downloads", "fastq"):
        (source_root / name).mkdir(parents=True)
    capsys.readouterr()  # discard the first call's output
    assert cli.main(["config", "check"]) == 0
    assert (tmp_path / "derived").exists()

    out = capsys.readouterr().out
    assert "MISSING" not in out
    assert "db_file" in out
