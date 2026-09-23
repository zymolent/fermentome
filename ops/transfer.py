"""Move the out-of-tree tiers between machines as one verifiable archive.

    python ops/transfer.py export                      # -> <repo>/exports/transfer/<stamp>/
    python ops/transfer.py import --archive <zip>      # reports; writes nothing
    python ops/transfer.py import --archive <zip> --apply

`git clone` brings the repository. It does not bring `data_dir` (the atlas, the stored full
texts, the genomes, the quantification matrices), `source_root` (downloads, FASTQ) or
`env/secrets.local.env`. This script packs those into one zip with a manifest, and unpacks it on
the other machine against *that* machine's resolved paths -- so `FERMDB_DATA_DIR` or
`env/paths.local.yaml` decides where it lands, and nothing here hardcodes a location.

Three things it does that a plain `zip -r` cannot:

* **SQLite is snapshotted, not copied.** The atlas runs in WAL mode, so copying the `.sqlite3`
  file alone can miss committed transactions still sitting in the `-wal` sidecar, and an archive
  made that way restores a database that is quietly behind. Every SQLite file is read through
  `sqlite3.Connection.backup` from a `mode=ro` connection, exactly as `just rebuild-check` does,
  and the `-wal`/`-shm` sidecars are then redundant and skipped.
* **Every member carries its sha256**, recorded in the manifest at export and re-checked at
  import. A transfer that corrupts a file says so instead of producing an atlas that reads.
* **Already-compressed payloads are stored, not deflated.** `fulltext/` and `genomes/` are mostly
  `.gz`, `.pdf` and `.xml.gz`; re-compressing them costs minutes and saves nothing, while the
  databases deflate to a fraction of their size.

Import is refuse-by-default in two ways. It writes nothing without `--apply`, and even with it,
a file that already exists is left alone unless `--overwrite` is passed -- restoring over a
populated `data_dir` would otherwise replace a curated atlas with an older one silently.
`env/secrets.local.env` is never written over an existing file at all.

Secrets are excluded unless `--include-secrets` is passed. The file holds the NCBI key; an
archive that carries it should not be uploaded anywhere shared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fermdb.config import Settings  # noqa: E402

FORMAT = "fermdb-transfer/1"
SQLITE_MAGIC = b"SQLite format 3\x00"

#: Written by SQLite beside a database in WAL mode. Redundant once the database itself has been
#: snapshotted through the backup API, and actively misleading if restored beside a newer file.
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

#: Compressing these again costs CPU and saves ~nothing: the bulk of `fulltext/` and `genomes/`.
STORED_SUFFIXES = frozenset(
    {".gz", ".zip", ".xz", ".bz2", ".zst", ".pdf", ".png", ".jpg", ".jpeg", ".7z", ".xlsx"}
)

#: Archive-relative prefixes, one per tier. Import maps each back to the *local* resolved path.
DATA_PREFIX = "data"
SOURCE_PREFIX = "source"
SECRETS_MEMBER = "secrets/secrets.local.env"


# ------------------------------------------------------------------------------------- helpers


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sqlite(path: Path) -> bool:
    """True if `path` starts with the SQLite header.

    Checked by content rather than by suffix on purpose: the derived tier holds ~40 `.bak`
    snapshots that are databases, and a `.bak` that is not one still has to be archivable.
    """
    try:
        with path.open("rb") as handle:
            return handle.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _compression(path: Path) -> int:
    return zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED


def _repo_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size):,} B"
        size /= 1024
    return f"{size:,.1f} TB"


def _walk(root: Path, *, skip: set[Path], include_backups: bool) -> Iterator[Path]:
    """Every regular file under `root`, minus sidecars, minus `skip`, sorted for reproducibility."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(path.name.endswith(suffix) for suffix in SIDECAR_SUFFIXES):
            continue
        if any(skipped == path or skipped in path.parents for skipped in skip):
            continue
        if not include_backups and ".bak" in path.name:
            continue
        yield path


def _snapshot_sqlite(src: Path, dest: Path) -> bool:
    """Copy `src` to `dest` through the backup API. False if it is not a usable database."""
    source = destination = None
    try:
        source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(str(dest))
        source.backup(destination)
        return True
    except sqlite3.Error:
        return False
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


# -------------------------------------------------------------------------------------- export


def cmd_export(args: argparse.Namespace) -> int:
    settings = Settings.load()
    data_dir = settings.path("data_dir")
    source_root = settings.path("source_root")

    if not data_dir.is_dir():
        print(f"data_dir does not exist: {data_dir}", file=sys.stderr)
        print("Nothing to export. `fermdb config` shows how it resolved.", file=sys.stderr)
        return 1

    stamp = _stamp()
    # Repo-local, not `<data_dir>/exports`, at the owner's direction. A transfer archive is a
    # thing a person picks up and carries, and it is easier to find beside the code than under a
    # derived tier that is routinely on another drive. It is emphatically not repo content:
    # `/exports/` is gitignored, and this is the one derived artifact that lives in the tree.
    default_root = REPO / "exports" / "transfer"
    out_root = Path(args.out).expanduser() if args.out else default_root
    out_dir = out_root / stamp
    archive_path = out_dir / f"fermdb-transfer-{stamp}.zip"

    # Never pack an archive into an archive. The first entry covers wherever this run is writing,
    # including an `--out` pointed inside data_dir; the second covers archives left by earlier
    # runs, which defaulted to `<data_dir>/exports/transfer` before this one.
    skip = {out_root, settings.path("exports_dir") / "transfer"}

    plan: list[tuple[Path, str, Path]] = []  # (source, archive member, tier root)
    for path in _walk(data_dir, skip=skip, include_backups=args.include_backups):
        plan.append((path, f"{DATA_PREFIX}/{path.relative_to(data_dir).as_posix()}", data_dir))
    if source_root.is_dir():
        for path in _walk(source_root, skip=set(), include_backups=args.include_backups):
            member = f"{SOURCE_PREFIX}/{path.relative_to(source_root).as_posix()}"
            plan.append((path, member, source_root))

    secrets = REPO / "env" / "secrets.local.env"
    if args.include_secrets and secrets.is_file():
        plan.append((secrets, SECRETS_MEMBER, secrets.parent))
    elif args.include_secrets:
        print(f"warning: --include-secrets given but {secrets} does not exist", file=sys.stderr)

    on_disk = sum(path.stat().st_size for path, _, _ in plan)
    print(f"{len(plan):,} files, {_human(on_disk)} on disk")
    if not args.include_backups:
        print("  .bak snapshots excluded (pass --include-backups to carry them)")
    if not args.include_secrets:
        print("  env/secrets.local.env excluded (pass --include-secrets to carry it)")

    if args.dry_run:
        print(f"\ndry run -- would write {archive_path}")
        for _, member, _ in plan[:20]:
            print(f"  {member}")
        if len(plan) > 20:
            print(f"  ... and {len(plan) - 20:,} more")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    members: list[dict[str, object]] = []
    scratch = Path(tempfile.mkdtemp(prefix="fermdb-transfer-"))
    written = 0
    try:
        with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
            for index, (path, member, _) in enumerate(plan, start=1):
                staged, how = path, "copy"
                if _is_sqlite(path):
                    candidate = scratch / f"{index}-{path.name}"
                    if _snapshot_sqlite(path, candidate):
                        staged, how = candidate, "sqlite-backup"
                    else:
                        how = "copy (not a readable database)"
                archive.write(staged, member, compress_type=_compression(path))
                members.append(
                    {
                        "path": member,
                        "bytes": staged.stat().st_size,
                        "sha256": _sha256(staged),
                        "source": how,
                        "modified": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    }
                )
                written += int(members[-1]["bytes"])  # type: ignore[arg-type]
                if staged is not path:
                    staged.unlink(missing_ok=True)
                if index % 200 == 0 or index == len(plan):
                    print(f"  {index:,}/{len(plan):,} packed", file=sys.stderr)

            manifest = {
                "format": FORMAT,
                "created_at": datetime.now(UTC).isoformat(),
                "created_on": {
                    "host": socket.gethostname(),
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                },
                "repo_commit": _repo_commit(),
                "source_paths": {
                    "data_dir": str(data_dir),
                    "source_root": str(source_root) if source_root.is_dir() else None,
                },
                "options": {
                    "include_backups": bool(args.include_backups),
                    "include_secrets": bool(args.include_secrets),
                },
                "totals": {"files": len(members), "bytes": written},
                "members": members,
            }
            body = json.dumps(manifest, indent=2, sort_keys=False)
            archive.writestr("MANIFEST.json", body, compress_type=zipfile.ZIP_DEFLATED)
            (out_dir / "MANIFEST.json").write_text(body, encoding="utf-8")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(f"\nwrote {archive_path}")
    print(f"  {len(members):,} files, {_human(archive_path.stat().st_size)} compressed")
    print(f"  manifest beside it: {out_dir / 'MANIFEST.json'}")
    print("\nOn the other machine:")
    print(f"  python ops/transfer.py import --archive {archive_path.name} --apply")
    return 0


# -------------------------------------------------------------------------------------- import


def cmd_import(args: argparse.Namespace) -> int:
    archive_path = Path(args.archive).expanduser()
    if not archive_path.is_file():
        print(f"no archive at {archive_path}", file=sys.stderr)
        return 1

    settings = Settings.load()
    targets = {
        DATA_PREFIX: Path(args.into).expanduser() if args.into else settings.path("data_dir"),
        SOURCE_PREFIX: settings.path("source_root"),
    }

    with zipfile.ZipFile(archive_path) as archive:
        try:
            manifest = json.loads(archive.read("MANIFEST.json"))
        except KeyError:
            print("archive has no MANIFEST.json -- not a fermdb transfer archive", file=sys.stderr)
            return 1
        if manifest.get("format") != FORMAT:
            print(f"unsupported archive format {manifest.get('format')!r}", file=sys.stderr)
            return 1

        print(f"archive   {archive_path}")
        print(f"created   {manifest['created_at']} on {manifest['created_on']['host']}")
        print(f"commit    {manifest.get('repo_commit') or 'unknown'}")
        print(
            f"contents  {manifest['totals']['files']:,} files, "
            f"{_human(manifest['totals']['bytes'])} uncompressed"
        )
        print(f"was       {manifest['source_paths']['data_dir']}")
        print(f"will be   {targets[DATA_PREFIX]}")

        expected = {str(m["path"]): m for m in manifest["members"]}
        # `--into` redirects the data tier only; say where the other two are going rather than
        # letting a reader assume one flag moved everything.
        if any(member.startswith(f"{SOURCE_PREFIX}/") for member in expected):
            print(f"source    {targets[SOURCE_PREFIX]}")
        if SECRETS_MEMBER in expected:
            print(f"secrets   {REPO / 'env' / 'secrets.local.env'} (never overwritten)")

        conflicts: list[str] = []
        for member in expected:
            local = _local_path(member, targets)
            if local is not None and local.exists():
                conflicts.append(member)

        if conflicts:
            print(f"\n{len(conflicts):,} of {len(expected):,} files already exist at the target:")
            for member in conflicts[:10]:
                print(f"  {member}")
            if len(conflicts) > 10:
                print(f"  ... and {len(conflicts) - 10:,} more")
            if not args.overwrite:
                print("  these will be LEFT ALONE (pass --overwrite to replace them)")

        if not args.apply:
            print("\nreport only -- nothing written. Re-run with --apply.")
            return 0

        restored = skipped = 0
        failures: list[str] = []
        for index, (member, record) in enumerate(expected.items(), start=1):
            local = _local_path(member, targets)
            if local is None:
                continue
            if local.exists() and not args.overwrite:
                skipped += 1
                continue
            if member == SECRETS_MEMBER and local.exists():
                skipped += 1  # never clobbered, --overwrite or not
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, local.open("wb") as dest:
                shutil.copyfileobj(src, dest, 1 << 20)
            actual = _sha256(local)
            if actual != record["sha256"]:
                failures.append(f"{member}: sha256 {actual[:12]} != {str(record['sha256'])[:12]}")
            restored += 1
            if index % 200 == 0 or index == len(expected):
                print(f"  {index:,}/{len(expected):,} processed", file=sys.stderr)

    print(f"\nrestored {restored:,}, left alone {skipped:,}")
    if failures:
        print(f"\n{len(failures)} CHECKSUM FAILURES -- the archive or the disk is corrupt:")
        for line in failures[:20]:
            print(f"  {line}")
        return 1
    print("every restored file matched its recorded sha256.")
    print("\nNext: python -m fermdb.cli config     # confirm the paths, and the exists column")
    return 0


def _local_path(member: str, targets: dict[str, Path]) -> Path | None:
    """Map an archive member to where it belongs on *this* machine, or None to ignore it."""
    if member == SECRETS_MEMBER:
        return REPO / "env" / "secrets.local.env"
    prefix, _, rest = member.partition("/")
    root = targets.get(prefix)
    if root is None or not rest:
        return None
    candidate = (root / rest).resolve()
    # Refuse a member that would escape its tier root -- a zip-slip guard, cheap and absolute.
    if root.resolve() not in candidate.parents and candidate != root.resolve():
        return None
    return candidate


# ----------------------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ops/transfer.py",
        description="Pack and unpack the out-of-tree tiers (data_dir, source_root, secrets).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="write a timestamped archive of the local tiers")
    p_export.add_argument(
        "--out",
        help="directory to create the timestamped export folder in "
        "(default: <repo>/exports/transfer, which is gitignored)",
    )
    p_export.add_argument(
        "--include-backups",
        action="store_true",
        help="carry the .bak database snapshots too (roughly +1 GB)",
    )
    p_export.add_argument(
        "--include-secrets",
        action="store_true",
        help="carry env/secrets.local.env. It holds the NCBI key -- do not upload the result",
    )
    p_export.add_argument("--dry-run", action="store_true", help="list what would be packed")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="restore an archive onto this machine")
    p_import.add_argument("--archive", required=True, help="the .zip written by `export`")
    p_import.add_argument(
        "--into", help="restore the data tier here instead of the resolved data_dir"
    )
    p_import.add_argument(
        "--overwrite",
        action="store_true",
        help="replace files that already exist (env/secrets.local.env never is)",
    )
    p_import.add_argument("--apply", action="store_true", help="actually write; off by default")
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
