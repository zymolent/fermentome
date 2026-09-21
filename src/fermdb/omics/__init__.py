"""Omics metadata acquisition: SRA run discovery, GEO series linkage, and the small DNA
references (the S288C nuclear genome and the mitochondrial genome) everything else depends on.

Scope, deliberately narrow (docs/reference/DATA_VOLUME.md sections 2 and 6; PLAN.md F.3):

* `sra.py` and `geo.py` harvest METADATA only -- esearch/esummary/efetch responses parsed into
  rows. Nothing here downloads a read. `sra_run.location_url` records *where* a run's bytes are,
  not that they have been fetched; bulk retrieval is a separate, explicitly costed step
  (DATA_VOLUME.md section 6) and this package refuses to perform it --
  `sra.download_run_bytes` is a deliberate tripwire, not a stub waiting to be filled in.
* `references.py` is the one place that *does* fetch bytes, because the two DNA references it
  fetches are small (~12 Mb nuclear + ~86 kb mitochondrial) and are a dependency of nearly
  everything else in the atlas (PLAN.md F.4's quantification reference).

Every row this package writes is Zone R: exactly what SRA, GEO or NCBI Nucleotide reported, never
a curator's or a model's reading of it (docs/reference/CONVENTIONS.md "Data zones") -- every table
this package's rows land in (`sra_run`, `reference_sequence`) fixes `zone = 'R'` by CHECK
constraint, so this is structural, not a convention someone has to remember. Where a value was
checked against a live source in this session, `evidence` names that source and date and
`confidence` is `'high'`; nothing here is Zone I, and nothing here is model output.

Network access is behind one seam, `FetchFn`, so every test in `tests/test_omics.py` runs offline
by injecting a fake one instead of `urllib_fetch`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import Settings
from ..db import open_db

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

#: NCBI's stated courtesy rate limit for unauthenticated E-utilities traffic (see
#: https://www.ncbi.nlm.nih.gov/books/NBK25497/ -- unverified, read from general knowledge of the
#: E-utilities documentation, not fetched in this session).
DEFAULT_MIN_INTERVAL_S = 0.34  # ~3 requests/second

#: The one seam between this package and the network. A `FetchFn` takes a fully-built URL and
#: returns the response body decoded as text. `urllib_fetch` is the only implementation that opens
#: a socket; `sra.py`, `geo.py` and `references.py` all take a `FetchFn` parameter instead of
#: calling it directly, so a test injects a fake one and never touches the network (the harness's
#: binding rule: "tests MUST NOT hit the network").
FetchFn = Callable[[str], str]


class OmicsFetchError(RuntimeError):
    """A `FetchFn` failed, or returned something this package could not parse."""


def urllib_fetch(url: str, *, timeout: float = 30.0) -> str:
    """Default network transport: GET `url` and return the body as text.

    The only function in this package that opens a socket. Everything else takes a `FetchFn`
    parameter and calls through it instead, which is what lets `tests/test_omics.py` run offline.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "fermdb/0.0 (metadata harvest)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            charset = response.headers.get_content_charset() or "utf-8"
            return str(response.read().decode(charset))
    except urllib.error.URLError as exc:
        raise OmicsFetchError(f"GET {url} failed: {exc}") from exc


def utcnow_iso() -> str:
    """The one place this package reads the wall clock, so a caller can hold it fixed in a test."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ESearchResult:
    """A parsed NCBI esearch response: enough to page results or hand ids to efetch/esummary."""

    count: int
    ids: tuple[str, ...]
    retmax: int
    retstart: int


@dataclass
class EutilsClient:
    """A thin, injectable wrapper over the three E-utilities calls this package needs.

    Not a general eutils client -- only esearch (JSON), efetch (by explicit id list) and esummary
    (by explicit id list), in the shapes `sra.py`, `geo.py` and `references.py` actually use.
    `min_interval_s` is a real `time.sleep` between requests via an injectable `sleep`, so a test
    can assert on throttling without actually waiting (pass `min_interval_s=0.0`).
    """

    fetch: FetchFn
    tool: str = "fermdb"
    email: str | None = None
    api_key: str | None = None
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)

    def _params(self, extra: Mapping[str, str]) -> dict[str, str]:
        params: dict[str, str] = {"tool": self.tool, **extra}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _get(self, endpoint: str, params: Mapping[str, str]) -> str:
        query = urllib.parse.urlencode(self._params(params))
        body = self.fetch(f"{EUTILS_BASE}/{endpoint}?{query}")
        if self.min_interval_s:
            self.sleep(self.min_interval_s)
        return body

    def esearch(self, *, db: str, term: str, retstart: int = 0, retmax: int = 200) -> ESearchResult:
        raw = self._get(
            "esearch.fcgi",
            {
                "db": db,
                "term": term,
                "retstart": str(retstart),
                "retmax": str(retmax),
                "retmode": "json",
            },
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OmicsFetchError(f"esearch db={db} term={term!r} returned invalid JSON") from exc
        result = payload.get("esearchresult") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise OmicsFetchError(
                f"esearch db={db} term={term!r} response missing 'esearchresult': {payload!r}"
            )
        try:
            count = int(result["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OmicsFetchError(
                f"esearch db={db} term={term!r} response has no usable 'count': {result!r}"
            ) from exc
        return ESearchResult(
            count=count,
            ids=tuple(str(i) for i in result.get("idlist", [])),
            retmax=int(result.get("retmax", retmax)),
            retstart=int(result.get("retstart", retstart)),
        )

    def esearch_all_ids(self, *, db: str, term: str, page_size: int = 200) -> list[str]:
        """Page through esearch until every id is collected."""
        ids: list[str] = []
        retstart = 0
        while True:
            page = self.esearch(db=db, term=term, retstart=retstart, retmax=page_size)
            if not page.ids:
                break
            ids.extend(page.ids)
            retstart += len(page.ids)
            if retstart >= page.count:
                break
        return ids

    def esummary(self, *, db: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """Return one summary dict per id, in the order NCBI reports `uids` (not input order)."""
        if not ids:
            return []
        raw = self._get("esummary.fcgi", {"db": db, "id": ",".join(ids), "retmode": "json"})
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OmicsFetchError(f"esummary db={db} returned invalid JSON") from exc
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise OmicsFetchError(f"esummary db={db} response missing 'result': {payload!r}")
        uids = result.get("uids", [])
        return [result[uid] for uid in uids if isinstance(result.get(uid), dict)]

    def efetch(self, *, db: str, ids: Sequence[str], rettype: str, retmode: str = "text") -> str:
        """Return the raw efetch payload; the caller parses it (runinfo CSV, GenBank, FASTA...)."""
        if not ids:
            return ""
        return self._get(
            "efetch.fcgi",
            {"db": db, "id": ",".join(ids), "rettype": rettype, "retmode": retmode},
        )


# --------------------------------------------------------------------------------------------
# data/omics/dataset_families.yaml: the curated queries this atlas runs, and their last-measured
# counts. Loading this file is package-level (rather than living in sra.py or geo.py) because both
# modules' discovery functions are driven by it and neither owns it more than the other.
# --------------------------------------------------------------------------------------------


class DatasetFamiliesError(ValueError):
    """`data/omics/dataset_families.yaml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class DatasetFamily:
    """One curated query this atlas runs against SRA or GEO, with its last-measured baseline.

    `expected_count` and the rest of the measured fields are a historical snapshot, not a target:
    SRA and GEO grow continuously, so a live count higher than `expected_count` is normal drift,
    not an error (`fermdb omics status` reports it as such). `guard`, when set, names a reason
    `fermdb omics discover` refuses to run this family without an explicit override -- the ethanol
    reference layer is capped at six hand-picked studies by project decision (PLAN.md, DATA_VOLUME
    section 2), not bulk-discovered like the isobutanol families.
    """

    name: str
    target: str  # 'sra' | 'geo'
    db: str  # 'sra' | 'gds'
    term: str
    expected_count: int | None
    notes: str | None
    evidence: str
    confidence: str
    guard: str | None = None


def load_dataset_families(path: str | Path) -> list[DatasetFamily]:
    """Parse `data/omics/dataset_families.yaml`'s `families` list into `DatasetFamily` rows.

    No path is hardcoded here: the caller resolves `path` from `Settings` (repo tier), per
    docs/reference/CONVENTIONS.md ("Paths and configuration").
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise DatasetFamiliesError(f"no dataset families file at {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or "families" not in document:
        raise DatasetFamiliesError(f"{file_path}: expected a mapping with a top-level 'families'")
    families = document["families"]
    if not isinstance(families, list):
        raise DatasetFamiliesError(f"{file_path}: 'families' must be a list")

    result: list[DatasetFamily] = []
    seen: set[str] = set()
    for index, row in enumerate(families):
        if not isinstance(row, dict):
            raise DatasetFamiliesError(f"{file_path}: families[{index}] must be a mapping")
        try:
            name = str(row["name"])
            target = str(row["target"])
            db = str(row["db"])
            term = str(row["term"])
            evidence = str(row["evidence"])
            confidence = str(row["confidence"])
        except KeyError as exc:
            raise DatasetFamiliesError(f"{file_path}: families[{index}] missing {exc}") from exc
        if target not in ("sra", "geo"):
            raise DatasetFamiliesError(
                f"{file_path}: families[{index}] ({name!r}) has target {target!r}; "
                "must be 'sra' or 'geo'"
            )
        if confidence not in ("unverified", "low", "medium", "high"):
            raise DatasetFamiliesError(
                f"{file_path}: families[{index}] ({name!r}) has confidence {confidence!r}; "
                "must be one of unverified/low/medium/high"
            )
        if name in seen:
            raise DatasetFamiliesError(f"{file_path}: duplicate family name {name!r}")
        seen.add(name)
        result.append(
            DatasetFamily(
                name=name,
                target=target,
                db=db,
                term=term,
                expected_count=row.get("expected_count"),
                notes=row.get("notes"),
                evidence=evidence,
                confidence=confidence,
                guard=row.get("guard"),
            )
        )
    return result


def dataset_families_path(settings: Settings) -> Path:
    """`data/omics/dataset_families.yaml`, resolved off `settings.repo_root`.

    There is no dedicated `env/paths.yaml` key for this file: adding one means keeping
    `fermdb.paths._BUILTIN_DEFAULTS` in sync with it (that module's own docstring explains why it
    cannot be derived automatically), and `paths.py`/`config.py` are outside this task's file list.
    A fixed sub-path off the already-configurable `repo_root` follows the same pattern
    `fermdb.paths` itself uses for `quant_dir/<run>/` (PLAN.md N.2): only the root is a
    configuration key, not every path beneath it.
    """
    return settings.repo_root / "data" / "omics" / "dataset_families.yaml"


def family_by_name(families: Sequence[DatasetFamily], name: str) -> DatasetFamily:
    """The one family named `name`, or raise `KeyError` naming what *is* available."""
    for family in families:
        if family.name == name:
            return family
    known = ", ".join(sorted(f.name for f in families))
    raise KeyError(f"unknown dataset family {name!r}; known families: {known}")


__all__ = [
    "DEFAULT_MIN_INTERVAL_S",
    "EUTILS_BASE",
    "DatasetFamiliesError",
    "DatasetFamily",
    "ESearchResult",
    "EutilsClient",
    "FetchFn",
    "OmicsFetchError",
    "add_omics_subcommand",
    "family_by_name",
    "load_dataset_families",
    "urllib_fetch",
    "utcnow_iso",
]


# --------------------------------------------------------------------------------------------
# CLI wiring. Deliberately all here (rather than a separate omics/cli.py) so that
# src/fermdb/cli.py's own diff stays to exactly "add the omics subcommand" -- everything the
# subcommand actually does is `sra.py`/`geo.py`/`references.py` functions this module glues
# together with `Settings` and `fermdb.db.open_db`.
# --------------------------------------------------------------------------------------------


def _client_from_args(args: argparse.Namespace) -> EutilsClient:
    """Build the real, network-touching client. The CLI's only concession to production wiring;
    every command below takes an optional `fetch` override so a test never has to go through this.
    """
    return EutilsClient(fetch=urllib_fetch, email=getattr(args, "ncbi_email", None) or None)


def cmd_omics_discover(args: argparse.Namespace, *, fetch: FetchFn | None = None) -> int:
    # Deferred: sra.py/geo.py import names from this module, so importing them back at module
    # load time would be a package import cycle. Deferring to call time sidesteps it entirely.
    from . import geo as geo_mod
    from . import sra as sra_mod

    settings = Settings.load()
    families = load_dataset_families(dataset_families_path(settings))
    client = EutilsClient(fetch=fetch) if fetch is not None else _client_from_args(args)

    if args.family is not None:
        try:
            selected = [family_by_name(families, args.family)]
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if selected[0].guard is not None and not args.force_guarded:
            print(
                f"error: family {selected[0].name!r} is guarded ({selected[0].guard}); "
                "pass --force-guarded to run it anyway. See docs/reference/DATA_VOLUME.md "
                "section 2 for why this query is not bulk-discovered.",
                file=sys.stderr,
            )
            return 2
    else:
        selected = [f for f in families if f.guard is None]

    conn = open_db(settings.db_file)
    try:
        try:
            retrieved_at = utcnow_iso()
            geo_dataset_ids: dict[str, str] = {}
            for family in selected:
                if family.target != "geo":
                    continue
                series = geo_mod.discover_geo_series(client, family.term)
                geo_mod.write_geo_series(conn, series, retrieved_at=retrieved_at)
                geo_dataset_ids.update(geo_mod.dataset_ids_by_bioproject(series))
                print(f"{family.name}: {len(series)} GEO series (expected~{family.expected_count})")

            for family in selected:
                if family.target != "sra":
                    continue
                search, runs = sra_mod.discover_sra_runs(client, family.term)
                written = sra_mod.write_sra_runs(
                    conn,
                    runs,
                    geo_dataset_ids_by_bioproject=geo_dataset_ids,
                    retrieved_at=retrieved_at,
                )
                by_strategy = sra_mod.count_by_library_strategy(runs)
                print(
                    f"{family.name}: esearch count={search.count} "
                    f"(expected~{family.expected_count}), {len(runs)} runs harvested, "
                    f"{written} rows written; "
                    f"by_library_strategy={dict(sorted(by_strategy.items()))}"
                )
        except OmicsFetchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    finally:
        conn.close()
    return 0


def cmd_omics_references_fetch(args: argparse.Namespace, *, fetch: FetchFn | None = None) -> int:
    from . import references as references_mod  # deferred: see cmd_omics_discover

    settings = Settings.load()
    client = EutilsClient(fetch=fetch) if fetch is not None else _client_from_args(args)
    conn = open_db(settings.db_file)
    try:
        try:
            retrieved_at = utcnow_iso()
            rows: list[dict[str, Any]] = []
            if args.include in ("mitochondrial", "all"):
                rows.extend(
                    references_mod.fetch_mitochondrial_reference(
                        client, settings.genomes_dir, retrieved_at=retrieved_at
                    )
                )
            if args.include in ("nuclear", "all"):
                rows.extend(
                    references_mod.fetch_nuclear_reference(
                        client, settings.genomes_dir, retrieved_at=retrieved_at
                    )
                )
        except OmicsFetchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        written = references_mod.write_reference_rows(conn, rows)
        for row in rows:
            print(
                f"{row['kind']:<26}{row['sequence_accession']:<16}"
                f"{row['size_bytes']:>10} bytes  sha256={row['checksum_sha256'][:12]}..."
            )
        print(f"{written} reference_sequence row(s) written")
    finally:
        conn.close()
    return 0


def cmd_omics_status(_args: argparse.Namespace) -> int:
    settings = Settings.load()
    families = load_dataset_families(dataset_families_path(settings))
    conn = open_db(settings.db_file)
    try:
        # Wide enough for the longest configured family name, so one never runs into the next
        # column -- a fixed width would silently truncate the moment a longer name is added.
        name_width = max((len(f.name) for f in families), default=6) + 2
        print(f"{'family':<{name_width}}{'target':<6}{'expected':>10}{'live':>10}")
        for family in families:
            # sra_run is per-run; dataset (repository='GEO') is per-series -- the two live counts
            # below are deliberately read from different tables for that reason.
            if family.target == "sra":
                live = conn.execute("SELECT COUNT(*) FROM sra_run").fetchone()[0]
            else:
                live = conn.execute(
                    "SELECT COUNT(*) FROM dataset WHERE repository = 'GEO'"
                ).fetchone()[0]
            expected = "-" if family.expected_count is None else str(family.expected_count)
            guard = "  [guarded]" if family.guard else ""
            print(f"{family.name:<{name_width}}{family.target:<6}{expected:>10}{live:>10}{guard}")

        print()
        by_strategy = conn.execute(
            "SELECT library_strategy, COUNT(*) AS n FROM sra_run "
            "GROUP BY library_strategy ORDER BY n DESC"
        ).fetchall()
        print("sra_run by library_strategy:")
        for row in by_strategy:
            print(f"  {row['library_strategy'] or '(none)':<16}{row['n']:>6}")

        ref_rows = conn.execute(
            "SELECT kind, sequence_accession, translation_verified FROM reference_sequence "
            "ORDER BY kind"
        ).fetchall()
        print(f"\nreference_sequence: {len(ref_rows)} row(s)")
        for row in ref_rows:
            verified = "verified" if row["translation_verified"] else "not verified"
            print(f"  {row['kind']:<26}{row['sequence_accession']:<16}{verified}")
    finally:
        conn.close()
    return 0


def cmd_omics_load(_args: argparse.Namespace) -> int:
    """Load the reference genomes, SRA runs and expression matrices already on disk."""
    from .load import load_all

    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        report = load_all(conn, settings)
    finally:
        conn.close()
    for table, count in report.as_dict().items():
        print(f"{table:<26}{count:>7}")
    return 0


def cmd_omics_experiments(args: argparse.Namespace) -> int:
    """Derive one `experiment` per SRA study from recorded metadata, and link each sample to it.

    The derivation always runs and always prints, including under `--dry-run`: it is the report of
    how much of `experiment` is recoverable at all, and it is what a reader needs in front of them
    before deciding to write. The rows written are exactly the rows printed -- `load_experiments`
    is handed the derivation this command already reported, rather than re-deriving inside the
    writer, so the summary cannot describe a different set of rows from the ones that landed.
    """
    from . import experiments as experiments_mod

    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        report = experiments_mod.derive_experiments(conn)
        print(report.summary())
        print()
        print(f"{'experiment':<30}{'study':<12}{'bioproject':<14}{'samples':>8}")
        for experiment in report.experiments:
            print(
                f"{experiment.id:<30}{experiment.accession or '-':<12}"
                f"{experiment.bioproject or '-':<14}{experiment.sample_count:>8}"
            )
        if report.orphan_sample_ids:
            print()
            print(f"no dataset, so no experiment: {', '.join(report.orphan_sample_ids)}")
        print()
        # Printed on every run, not only the first: the NULL `publication_id` is this module's
        # finding, and a curator who later fills it in should be overruling a stated reason.
        print(experiments_mod.PUBLICATION_LINK_REFUSAL)
        if args.dry_run:
            print()
            print("dry run: nothing written")
            return 0
        written = experiments_mod.load_experiments(conn, experiments=report.experiments)
        linked = conn.execute(
            "SELECT COUNT(*) FROM sample WHERE experiment_id IS NOT NULL"
        ).fetchone()[0]
        unlinked = conn.execute(
            "SELECT COUNT(*) FROM sample WHERE experiment_id IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    print()
    print(f"{'experiment':<26}{written['experiment']:>7}")
    print(f"{'sample.experiment_id':<26}{linked:>7}")
    print(f"{'sample (still unlinked)':<26}{unlinked:>7}")
    return 0


def cmd_omics_genes(_args: argparse.Namespace) -> int:
    """Resolve the DUET gene set from the transcript FASTA and verify it against the matrix."""
    from . import genes as genes_mod

    settings = Settings.load()
    conn = open_db(settings.db_file)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        report = genes_mod.build(settings, conn)
    finally:
        conn.close()
    check = report.matrix_check
    for table, count in report.written.items():
        print(f"{table:<26}{count:>7}")
    print()
    print(
        f"matrix cross-check: {len(check.present)} of "
        f"{len(check.present) + len(check.missing)} resolved genes present "
        f"among {check.matrix_rows} matrix rows"
    )
    if check.missing:
        print(f"  MISSING from the matrix: {', '.join(check.missing)}")
    if report.resolution.gaps:
        print(f"  not found in the FASTA: {[g.symbol for g in report.resolution.gaps]}")
    if report.panel_path:
        print(f"panel written to {report.panel_path}")
    return 0


def cmd_omics_baseline(args: argparse.Namespace) -> int:
    """Print the DUET expression baseline. No contrasts -- see PLAN.md F.3."""
    from .baseline import build_baseline

    settings = Settings.load()
    report = build_baseline(settings)
    print(
        f"{report.samples} samples | {report.matrix_genes} matrix genes | "
        f"{len(report.profiles)} profiled"
    )
    if report.missing_mitochondrial_proteins:
        print()
        print(
            "WARNING: the transcriptome behind this matrix contains no mtDNA protein-coding "
            "genes, so mitochondrial gene expression was never measured:"
        )
        print("  " + ", ".join(report.missing_mitochondrial_proteins))
    print()
    print(f"{'gene':10}{'systematic':11}{'kind':7}{'median':>10}{'detected':>11}  role")
    rows = sorted(report.profiles, key=lambda p: -p.median_tpm)
    for profile in rows[: args.limit] if args.limit else rows:
        print(
            f"{(profile.standard_name or '-'):10}{profile.systematic_name:11}"
            f"{profile.feature_kind:7}{profile.median_tpm:10.1f}"
            f"{profile.detected_in:>6}/{profile.samples:<4}  {profile.role or ''}"
        )
    return 0


def add_omics_subcommand(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `fermdb omics ...` to an existing top-level subparsers action.

    The only integration point `src/fermdb/cli.py` needs: `from .omics import
    add_omics_subcommand` and one call with the `sub` object `build_parser()` already has.
    """
    p_omics = sub.add_parser(
        "omics", help="SRA/GEO metadata discovery and the small DNA reference sequences"
    )
    p_omics.add_argument(
        "--ncbi-email",
        dest="ncbi_email",
        default=None,
        help="contact email sent to NCBI E-utilities",
    )
    omics_sub = p_omics.add_subparsers(dest="omics_command", required=True)

    p_discover = omics_sub.add_parser(
        "discover", help="run one or every family in data/omics/dataset_families.yaml"
    )
    p_discover.add_argument(
        "--family", default=None, help="run only this family (default: every non-guarded family)"
    )
    p_discover.add_argument(
        "--force-guarded",
        dest="force_guarded",
        action="store_true",
        help="run a guarded family (e.g. the capped ethanol reference layer) anyway",
    )
    p_discover.set_defaults(func=cmd_omics_discover)

    p_references = omics_sub.add_parser(
        "references", help="fetch and store the small DNA reference sequences"
    )
    references_sub = p_references.add_subparsers(dest="references_command", required=True)
    p_ref_fetch = references_sub.add_parser(
        "fetch", help="fetch S288C nuclear and/or mitochondrial reference sequences"
    )
    p_ref_fetch.add_argument(
        "--include",
        choices=["all", "nuclear", "mitochondrial"],
        default="all",
        help="which reference(s) to fetch (default: all)",
    )
    p_ref_fetch.set_defaults(func=cmd_omics_references_fetch)

    p_status = omics_sub.add_parser(
        "status", help="sra_run/dataset/reference_sequence counts against dataset_families.yaml"
    )
    p_status.set_defaults(func=cmd_omics_status)

    p_load = omics_sub.add_parser(
        "load", help="load the reference genomes, SRA runs and matrices already on disk"
    )
    p_load.set_defaults(func=cmd_omics_load)

    p_experiments = omics_sub.add_parser(
        "experiments",
        help="derive one experiment per SRA study and link each sample to it (no publication link)",
    )
    p_experiments.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="report what would be written and change nothing",
    )
    p_experiments.set_defaults(func=cmd_omics_experiments)

    p_genes = omics_sub.add_parser(
        "genes", help="resolve the DUET gene set and cross-check it against the expression matrix"
    )
    p_genes.set_defaults(func=cmd_omics_genes)

    p_baseline = omics_sub.add_parser(
        "baseline", help="DUET expression baseline across the S288C corpus (no contrasts; F.3)"
    )
    p_baseline.add_argument(
        "--limit", type=int, default=0, help="show only the N highest-expressed genes"
    )
    p_baseline.set_defaults(func=cmd_omics_baseline)
