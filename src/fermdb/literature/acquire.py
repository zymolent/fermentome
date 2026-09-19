"""Open-access resolution and full-text retrieval for one DOI/PMID at a time.

PLAN.md H.4 ("Legal and access constraints") is binding on everything here:

* Abstracts and metadata may always be stored; **full text may be stored only for open-access
  content under a licence that permits it**. Everything else keeps a pointer (the URL a copy was
  found at) plus whatever locally-derived, non-substitutive artifacts are produced downstream --
  this module stores none of those itself, only the pointer.
* `license`, `oa_status` and `text_mining_allowed` are recorded per publication and the pipeline
  *honours* them rather than discovering them at runtime by trying: `_STORABLE_OA_STATUSES` below
  is the one place that policy lives.
* A fetch that fails still produces a row that says so (`fulltext_asset.fetch_error`); nothing is
  ever silently dropped, and nothing is ever fabricated as if it had been retrieved.

Everything that talks to the network goes through the `Transport` protocol so tests stay offline
(the harness's binding rule: "tests MUST NOT hit the network"). `UrllibTransport` is the only
implementation that actually opens a socket, built from `urllib.request` alone per this project's
stdlib-first preference; nothing here is tested against it.

A paper this module could not get a stored copy of (paywalled, no OA copy found, a failed fetch,
or an OA copy whose licence does not permit storing it) is hoded off to
`enqueue_manual_download`, which writes it into `manual_download_queue`
(`fermdb.literature.manual_queue` owns reading that queue back out). Every path through
`acquire_fulltext` ends in exactly one of "stored", "pointed at", or "queued for a human" -- never
a silent drop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from xml.etree import ElementTree

from ..config import Settings

__all__ = [
    "AcquisitionError",
    "AcquisitionOutcome",
    "FetchedContent",
    "OaResolution",
    "Transport",
    "TransportError",
    "UrllibTransport",
    "acquire_fulltext",
    "classify_topic",
    "compute_priority",
    "enqueue_manual_download",
    "find_fulltext_asset",
    "find_manual_queue_row",
    "fulltext_root",
    "resolve_oa_status",
    "store_bytes_content_addressed",
    "write_fulltext_asset",
]

_DEFAULT_CONTACT_EMAIL = "fermdb-atlas@example.org"
_DEFAULT_USER_AGENT = "fermdb-literature-acquire/0.1"

#: Unpaywall's five-way taxonomy plus 'unknown' for "checked, could not classify". This is the
#: vocabulary `fulltext_asset.oa_status` is defined against (schema.sql, "full text acquisition").
_OA_STATUSES = frozenset({"gold", "green", "hybrid", "bronze", "closed", "unknown"})

#: THE storage policy (PLAN.md H.4): only these carry a licence clear enough to keep a local copy.
#: 'bronze' (free to read, no stated licence) and 'unknown' are treated like 'closed' for storage
#: purposes even though the paper may be readable online -- a pointer is kept either way.
_STORABLE_OA_STATUSES = frozenset({"gold", "green", "hybrid"})

_QUEUE_WHY_UNAVAILABLE = frozenset({"paywalled", "no_pdf_found", "fetch_failed", "licence_forbids"})

#: PLAN.md H.4's manual-queue ranking rule, made mechanical. Lower is more urgent.
_TOPIC_PRIORITY: dict[str, int] = {
    "isobutanol": 1,
    "isobutanol_mitochondria": 2,
    "mtdna_engineering": 3,
    "ethanol": 4,
    "other": 5,
}

_EXTENSION_BY_MEDIA_TYPE: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/html": ".html",
    "application/x-tar": ".tar",
    "application/gzip": ".gz",
}

_ASSET_COLUMNS: tuple[str, ...] = (
    "publication_id",
    "doi",
    "pmid",
    "oa_status",
    "license",
    "text_mining_allowed",
    "resolved_via",
    "best_oa_url",
    "storage_state",
    "content_path",
    "checksum_sha256",
    "media_type",
    "source_url",
    "retrieved_at",
    "fetch_error",
)

_UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
_EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

# License strings seen from Unpaywall/Europe PMC that clearly do or do not permit text mining.
# (unverified: a small, conservative subset rather than an exhaustive licence parser -- anything
# not recognized here is 'unknown', never guessed into 'yes' or 'no'.)
_TDM_PERMISSIVE_MARKERS = ("cc0", "public-domain", "public domain")


class AcquisitionError(Exception):
    """Base for every error this module raises on purpose."""


class TransportError(AcquisitionError):
    """A network call to an OA source failed, timed out, or returned something unusable.

    Never treated as a confident "not open access": callers catch this and record 'could not
    check' (`oa_status='unknown'`, or a `fetch_error` on the `fulltext_asset` row), not a
    negative result.
    """


@dataclass(frozen=True)
class FetchedContent:
    """Raw bytes from `Transport.get_bytes`, plus what the response said about them."""

    data: bytes
    content_type: str | None
    status: int


class Transport(Protocol):
    """Everything this module needs from the network, injectable so tests stay offline."""

    def get_json(self, url: str) -> Any:
        """Fetch `url` and return its parsed JSON body."""
        ...

    def get_bytes(self, url: str) -> FetchedContent:
        """Fetch `url` and return its raw body."""
        ...


class UrllibTransport:
    """The real `Transport`: nothing beyond `urllib.request` (CONVENTIONS.md prefers the stdlib).

    Tests must never reach this class -- inject a fake `Transport` instead.
    """

    def __init__(self, *, timeout: float = 20.0, user_agent: str = _DEFAULT_USER_AGENT) -> None:
        self._timeout = timeout
        self._user_agent = user_agent

    def get_json(self, url: str) -> Any:
        fetched = self._get(url)
        try:
            return json.loads(fetched.data)
        except json.JSONDecodeError as exc:
            raise TransportError(f"invalid JSON from {url}: {exc}") from exc

    def get_bytes(self, url: str) -> FetchedContent:
        return self._get(url)

    def _get(self, url: str) -> FetchedContent:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json, application/pdf, application/xml;q=0.9, */*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type")
                status = getattr(response, "status", None) or 200
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"request to {url} failed: {exc}") from exc
        return FetchedContent(data=data, content_type=content_type, status=int(status))


@dataclass(frozen=True)
class OaResolution:
    """One resolved answer to "is this open access, and where do we get it".

    `oa_status` follows Unpaywall's taxonomy even when the source that actually answered was
    Europe PMC or PMC, because that is the vocabulary `fulltext_asset.oa_status` is defined
    against.
    """

    doi: str | None
    pmid: str | None
    oa_status: str
    license: str | None
    text_mining_allowed: str
    best_oa_url: str | None
    resolved_via: str
    checked_at: str


@dataclass(frozen=True)
class _EuropePmcLookup:
    """Internal: Europe PMC's answer plus the PMCID it names, so a PMC OA follow-up is possible
    without a second round-trip to Europe PMC itself."""

    resolution: OaResolution
    pmcid: str | None


@dataclass(frozen=True)
class AcquisitionOutcome:
    """What `acquire_fulltext` did, for a caller (or a test) to inspect without re-querying."""

    fulltext_asset_id: str
    resolution: OaResolution
    stored: bool
    why_unavailable: str | None
    manual_queue_id: str | None


# ---------------------------------------------------------------------------------------------
# Helpers with no I/O
# ---------------------------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _infer_text_mining_allowed(license_: str | None) -> str:
    """Map a licence string to 'yes' / 'no' / 'unknown'.

    Deliberately conservative (unverified heuristic, not a licence parser): CONVENTIONS.md
    forbids resolving an ambiguous case to a confident value, so anything this does not clearly
    recognize -- including any ND/NC combination, where reasonable people read the terms
    differently -- comes back 'unknown' rather than a guessed 'yes' or 'no'.
    """
    if not license_:
        return "unknown"
    normalized = re.sub(r"[\s_]+", "-", license_.strip().lower())
    if any(marker in normalized for marker in _TDM_PERMISSIVE_MARKERS):
        return "yes"
    if "cc-by" not in normalized:
        return "unknown"
    has_nd = "-nd" in normalized or "noderiv" in normalized
    has_nc = "-nc" in normalized or "noncommercial" in normalized
    if has_nd or has_nc:
        return "unknown" if has_nc and not has_nd else "no"
    return "yes"


def _pick_fulltext_url(entries: list[Any]) -> str | None:
    def _url_of(entry: Any) -> str | None:
        if not isinstance(entry, dict):
            return None
        url = entry.get("url")
        return str(url) if url else None

    pdf_open = [
        e
        for e in entries
        if isinstance(e, dict)
        and str(e.get("availability", "")).lower().startswith("open access")
        and e.get("documentStyle") == "pdf"
    ]
    if pdf_open:
        return _url_of(pdf_open[0])
    any_open = [
        e
        for e in entries
        if isinstance(e, dict) and str(e.get("availability", "")).lower().startswith("open access")
    ]
    if any_open:
        return _url_of(any_open[0])
    return None


def _license_from_fulltext_urls(entries: list[Any]) -> str | None:
    for entry in entries:
        if isinstance(entry, dict) and entry.get("license"):
            return str(entry["license"])
    return None


def _unknown_resolution(doi: str | None, pmid: str | None) -> OaResolution:
    return OaResolution(
        doi=doi,
        pmid=pmid,
        oa_status="unknown",
        license=None,
        text_mining_allowed="unknown",
        best_oa_url=None,
        resolved_via="none",
        checked_at=_utc_now_iso(),
    )


# ---------------------------------------------------------------------------------------------
# OA resolution: Europe PMC, then Unpaywall, then PMC's OA web service
# ---------------------------------------------------------------------------------------------


def _try_europepmc(
    *, doi: str | None, pmid: str | None, transport: Transport
) -> _EuropePmcLookup | None:
    clauses = []
    if doi:
        clauses.append(f'DOI:"{doi}"')
    if pmid:
        clauses.append(f"EXT_ID:{pmid} AND SRC:MED")
    if not clauses:
        return None
    query = " OR ".join(clauses)
    url = f"{_EUROPEPMC_URL}?query={urllib.parse.quote(query)}&format=json&resultType=core"
    try:
        payload = transport.get_json(url)
    except TransportError:
        return None
    if not isinstance(payload, dict):
        return None

    result_list = payload.get("resultList")
    results = result_list.get("result") if isinstance(result_list, dict) else None
    if not results:
        return _EuropePmcLookup(resolution=_unknown_resolution(doi, pmid), pmcid=None)

    record = results[0]
    if not isinstance(record, dict):
        return _EuropePmcLookup(resolution=_unknown_resolution(doi, pmid), pmcid=None)

    is_open = record.get("isOpenAccess") == "Y"
    fulltext_list = record.get("fullTextUrlList")
    fulltext_urls = fulltext_list.get("fullTextUrl") if isinstance(fulltext_list, dict) else None
    fulltext_urls = fulltext_urls if isinstance(fulltext_urls, list) else []

    best_url = _pick_fulltext_url(fulltext_urls)
    license_raw = record.get("license")
    license_ = str(license_raw) if license_raw else _license_from_fulltext_urls(fulltext_urls)

    if not is_open:
        oa_status = "closed"
    elif _infer_text_mining_allowed(license_) == "yes":
        oa_status = "gold"
    else:
        oa_status = "green"

    resolved_doi = record.get("doi")
    resolved_pmid = record.get("pmid")
    resolution = OaResolution(
        doi=str(resolved_doi) if resolved_doi else doi,
        pmid=str(resolved_pmid) if resolved_pmid else pmid,
        oa_status=oa_status,
        license=license_,
        text_mining_allowed=_infer_text_mining_allowed(license_),
        best_oa_url=best_url,
        resolved_via="europepmc",
        checked_at=_utc_now_iso(),
    )
    pmcid = record.get("pmcid")
    return _EuropePmcLookup(resolution=resolution, pmcid=str(pmcid) if pmcid else None)


def _try_unpaywall(
    *, doi: str, transport: Transport, contact_email: str | None
) -> OaResolution | None:
    email = contact_email or os.environ.get("FERMDB_CONTACT_EMAIL", _DEFAULT_CONTACT_EMAIL)
    encoded_doi = urllib.parse.quote(doi, safe="")
    url = f"{_UNPAYWALL_URL.format(doi=encoded_doi)}?email={urllib.parse.quote(email)}"
    try:
        payload = transport.get_json(url)
    except TransportError:
        return None
    if not isinstance(payload, dict):
        return None

    oa_status_raw = payload.get("oa_status")
    oa_status = str(oa_status_raw) if oa_status_raw in _OA_STATUSES else "unknown"

    best_location = payload.get("best_oa_location")
    best_location = best_location if isinstance(best_location, dict) else {}
    url_for_pdf = best_location.get("url_for_pdf")
    plain_url = best_location.get("url")
    best_url = str(url_for_pdf) if url_for_pdf else (str(plain_url) if plain_url else None)
    license_raw = best_location.get("license")
    license_ = str(license_raw) if license_raw else None

    resolved_doi = payload.get("doi")
    return OaResolution(
        doi=str(resolved_doi) if resolved_doi else doi,
        pmid=None,
        oa_status=oa_status,
        license=license_,
        text_mining_allowed=_infer_text_mining_allowed(license_),
        best_oa_url=best_url,
        resolved_via="unpaywall",
        checked_at=_utc_now_iso(),
    )


def _try_pmc_oa(
    *, pmcid: str, doi: str | None, pmid: str | None, transport: Transport
) -> OaResolution | None:
    url = f"{_PMC_OA_URL}?id={urllib.parse.quote(pmcid)}"
    try:
        fetched = transport.get_bytes(url)
    except TransportError:
        return None
    try:
        root = ElementTree.fromstring(fetched.data)
    except ElementTree.ParseError:
        return None

    if root.find("error") is not None:
        return OaResolution(
            doi=doi,
            pmid=pmid,
            oa_status="closed",
            license=None,
            text_mining_allowed="unknown",
            best_oa_url=None,
            resolved_via="pmc",
            checked_at=_utc_now_iso(),
        )

    record = root.find(".//record")
    if record is None:
        return None

    license_ = record.get("license")
    links = record.findall("link")
    best_url = next((link.get("href") for link in links if link.get("format") == "pdf"), None)
    if best_url is None and links:
        best_url = links[0].get("href")

    return OaResolution(
        doi=doi,
        pmid=pmid,
        oa_status="gold" if _infer_text_mining_allowed(license_) == "yes" else "green",
        license=license_,
        text_mining_allowed=_infer_text_mining_allowed(license_),
        best_oa_url=best_url,
        resolved_via="pmc",
        checked_at=_utc_now_iso(),
    )


def resolve_oa_status(
    *,
    doi: str | None,
    pmid: str | None,
    transport: Transport,
    contact_email: str | None = None,
) -> OaResolution:
    """Determine open-access status and a retrievable location for one DOI/PMID.

    Tries Europe PMC first (it accepts either identifier and, for anything in the PMC OA subset,
    hands back a direct full-text URL in one call), then Unpaywall by DOI, then falls back to
    PMC's own OA web service if Europe PMC named a PMCID but had no direct URL. Never raises on a
    network failure: an unreachable source is simply skipped, and if every source is unreachable
    or none of them has a retrievable location, this returns an 'unknown'/`resolved_via='none'`
    result rather than propagating the error -- resolution never crashes acquisition.
    """
    if doi is None and pmid is None:
        raise ValueError("resolve_oa_status requires a doi or a pmid")

    europepmc = _try_europepmc(doi=doi, pmid=pmid, transport=transport)
    if europepmc is not None and europepmc.resolution.best_oa_url is not None:
        return europepmc.resolution

    unpaywall = (
        _try_unpaywall(doi=doi, transport=transport, contact_email=contact_email)
        if doi is not None
        else None
    )
    if unpaywall is not None and unpaywall.best_oa_url is not None:
        return unpaywall

    if europepmc is not None and europepmc.pmcid is not None:
        pmc = _try_pmc_oa(pmcid=europepmc.pmcid, doi=doi, pmid=pmid, transport=transport)
        if pmc is not None and pmc.best_oa_url is not None:
            return pmc

    if unpaywall is not None:
        return unpaywall
    if europepmc is not None:
        return europepmc.resolution
    return _unknown_resolution(doi, pmid)


# ---------------------------------------------------------------------------------------------
# Manual-queue priority ranking
# ---------------------------------------------------------------------------------------------


def classify_topic(text: str) -> str:
    """Best-effort keyword classification, for manual-queue priority ranking ONLY.

    This decides where in the manual-download queue a paper lands; it is never written to
    `publication` or any curated table, and it is not a substitute for the relevance pipeline of
    PLAN.md H.3. A caller with a better classification should pass `topic=` explicitly to
    `enqueue_manual_download`/`acquire_fulltext` instead of relying on this fallback.
    """
    lowered = text.lower()
    has_isobutanol = "isobutanol" in lowered
    has_mito = any(k in lowered for k in ("mitochond", "mtdna", "mitochondrial dna"))
    has_ethanol = "ethanol" in lowered
    if has_isobutanol and has_mito:
        return "isobutanol_mitochondria"
    if has_isobutanol:
        return "isobutanol"
    mtdna_engineering_markers = (
        "mitotalen",
        "mitozfn",
        "biolistic",
        "base editor",
        "mitochondrial genome engineering",
        "mtdna engineering",
        "rho0",
        "rho-minus",
        "rho zero",
    )
    if has_mito and any(k in lowered for k in mtdna_engineering_markers):
        return "mtdna_engineering"
    if has_ethanol:
        return "ethanol"
    return "other"


def compute_priority(topic: str, reports_titer_or_yield: bool) -> int:
    """Lower is more urgent.

    PLAN.md H.4's ranking rule, made mechanical: topic tier first (isobutanol > isobutanol x
    mitochondria > mtDNA engineering > ethanol > everything else), then a paper reporting a titer
    or yield before one that does not, within the same tier. This is the single place that rule
    is computed; `manual_download_queue.priority` is only ever this function's output.
    """
    tier = _TOPIC_PRIORITY.get(topic, _TOPIC_PRIORITY["other"])
    return tier * 2 - (1 if reports_titer_or_yield else 0)


# ---------------------------------------------------------------------------------------------
# Content-addressed storage
# ---------------------------------------------------------------------------------------------


def _extension_for(media_type: str | None) -> str:
    if not media_type:
        return ".bin"
    bare = media_type.split(";", 1)[0].strip().lower()
    return _EXTENSION_BY_MEDIA_TYPE.get(bare, ".bin")


def fulltext_root(settings: Settings) -> Path:
    """The derived-tier directory full text is content-addressed into.

    Not a configured path key (docs/reference/CONVENTIONS.md "Paths and configuration"): it is a
    fixed subdirectory of `Settings.data_dir`, exactly the way `matrices_dir`/`quant_dir`/etc. are
    fixed *named* subdirectories of it in `env/paths.yaml` -- the difference is only that this one
    is not independently configurable, so no key had to be added there (and to
    `fermdb.paths._BUILTIN_DEFAULTS`, which `tests/test_paths.py` pins byte-for-byte against that
    file) just to name this module's cache location.
    """
    return settings.data_dir / "fulltext"


def store_bytes_content_addressed(
    settings: Settings, data: bytes, *, media_type: str | None
) -> tuple[str, str]:
    """Write `data` under `fulltext_root(settings)`, content-addressed by its sha256.

    Returns `(content_path, checksum_sha256)`. `content_path` is relative to `settings.data_dir`
    (what `fulltext_asset.content_path` stores), so the derived tier can be relocated without
    invalidating every row.
    """
    checksum = hashlib.sha256(data).hexdigest()
    relative = Path("fulltext") / checksum[:2] / f"{checksum}{_extension_for(media_type)}"
    absolute = settings.data_dir / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    if not absolute.exists():
        absolute.write_bytes(data)
    return str(relative), checksum


# ---------------------------------------------------------------------------------------------
# Database helpers -- fulltext_asset and manual_download_queue
# ---------------------------------------------------------------------------------------------


def find_fulltext_asset(
    conn: sqlite3.Connection, *, doi: str | None, pmid: str | None
) -> sqlite3.Row | None:
    """The existing `fulltext_asset` row for this DOI/PMID, if any, so a repeat acquisition
    attempt updates it in place rather than accumulating duplicates."""
    if doi is not None:
        found: sqlite3.Row | None = conn.execute(
            "SELECT * FROM fulltext_asset WHERE doi = ? COLLATE NOCASE", (doi,)
        ).fetchone()
        if found is not None:
            return found
    if pmid is not None:
        by_pmid: sqlite3.Row | None = conn.execute(
            "SELECT * FROM fulltext_asset WHERE pmid = ?", (pmid,)
        ).fetchone()
        return by_pmid
    return None


def write_fulltext_asset(
    conn: sqlite3.Connection,
    *,
    existing_id: str | None,
    doi: str | None,
    pmid: str | None,
    publication_id: str | None,
    oa_status: str,
    license_: str | None,
    text_mining_allowed: str | None,
    resolved_via: str,
    best_oa_url: str | None,
    storage_state: str,
    content_path: str | None,
    checksum_sha256: str | None,
    media_type: str | None,
    source_url: str | None,
    retrieved_at: str | None,
    fetch_error: str | None,
) -> str:
    """Insert a new `fulltext_asset` row, or update `existing_id` in place. Returns its id."""
    values: dict[str, Any] = {
        "publication_id": publication_id,
        "doi": doi,
        "pmid": pmid,
        "oa_status": oa_status,
        "license": license_,
        "text_mining_allowed": text_mining_allowed,
        "resolved_via": resolved_via,
        "best_oa_url": best_oa_url,
        "storage_state": storage_state,
        "content_path": content_path,
        "checksum_sha256": checksum_sha256,
        "media_type": media_type,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "fetch_error": fetch_error,
    }
    if existing_id is not None:
        assignments = ", ".join(f"{column} = :{column}" for column in _ASSET_COLUMNS)
        conn.execute(
            f"UPDATE fulltext_asset SET {assignments} WHERE id = :id",  # noqa: S608
            {**values, "id": existing_id},
        )
        return existing_id

    new_id = f"YAA:FTA:{uuid.uuid4().hex}"
    columns = ("id", *_ASSET_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in columns)
    conn.execute(
        f"INSERT INTO fulltext_asset ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
        {**values, "id": new_id},
    )
    return new_id


def find_manual_queue_row(
    conn: sqlite3.Connection, *, doi: str | None, pmid: str | None
) -> sqlite3.Row | None:
    """The existing `manual_download_queue` row for this DOI/PMID, if any."""
    if doi is not None:
        found: sqlite3.Row | None = conn.execute(
            "SELECT * FROM manual_download_queue WHERE doi = ? COLLATE NOCASE", (doi,)
        ).fetchone()
        if found is not None:
            return found
    if pmid is not None:
        by_pmid: sqlite3.Row | None = conn.execute(
            "SELECT * FROM manual_download_queue WHERE pmid = ? AND doi IS NULL", (pmid,)
        ).fetchone()
        return by_pmid
    return None


def enqueue_manual_download(
    conn: sqlite3.Connection,
    *,
    doi: str | None,
    pmid: str | None,
    why_unavailable: str,
    title: str | None = None,
    journal: str | None = None,
    year: int | None = None,
    publisher_url: str | None = None,
    best_known_link: str | None = None,
    publication_id: str | None = None,
    topic: str | None = None,
    reports_titer_or_yield: bool = False,
) -> str:
    """Add (or refresh) one row in `manual_download_queue`. Returns its id.

    A paper already in the queue is never duplicated: a repeat failed acquisition attempt updates
    the existing 'pending' row's reason/priority/links in place. A row already 'provided' or
    'skipped' by the owner is left alone -- a fresh failure to re-fetch the same paper must never
    silently undo a curator's decision.
    """
    if doi is None and pmid is None:
        raise ValueError("enqueue_manual_download requires a doi or a pmid")
    if why_unavailable not in _QUEUE_WHY_UNAVAILABLE:
        raise ValueError(f"unknown why_unavailable: {why_unavailable!r}")

    resolved_topic = topic or classify_topic(f"{title or ''} {journal or ''}")
    if resolved_topic not in _TOPIC_PRIORITY:
        raise ValueError(f"unknown topic: {resolved_topic!r}")
    priority = compute_priority(resolved_topic, reports_titer_or_yield)

    existing = find_manual_queue_row(conn, doi=doi, pmid=pmid)
    now = _utc_now_iso()

    if existing is not None:
        if existing["status"] != "pending":
            return str(existing["id"])
        conn.execute(
            "UPDATE manual_download_queue SET "
            "title = COALESCE(:title, title), "
            "journal = COALESCE(:journal, journal), "
            "year = COALESCE(:year, year), "
            "publisher_url = COALESCE(:publisher_url, publisher_url), "
            "best_known_link = COALESCE(:best_known_link, best_known_link), "
            "why_unavailable = :why_unavailable, "
            "priority = :priority, "
            "priority_topic = :priority_topic, "
            "reports_titer_or_yield = :reports_titer_or_yield, "
            "updated_at = :updated_at "
            "WHERE id = :id",
            {
                "title": title,
                "journal": journal,
                "year": year,
                "publisher_url": publisher_url,
                "best_known_link": best_known_link,
                "why_unavailable": why_unavailable,
                "priority": priority,
                "priority_topic": resolved_topic,
                "reports_titer_or_yield": int(reports_titer_or_yield),
                "updated_at": now,
                "id": existing["id"],
            },
        )
        return str(existing["id"])

    new_id = f"YAA:MDQ:{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO manual_download_queue "
        "(id, publication_id, pmid, doi, title, journal, year, publisher_url, best_known_link, "
        "why_unavailable, priority, priority_topic, reports_titer_or_yield, status, added_at) "
        "VALUES (:id, :publication_id, :pmid, :doi, :title, :journal, :year, :publisher_url, "
        ":best_known_link, :why_unavailable, :priority, :priority_topic, "
        ":reports_titer_or_yield, 'pending', :added_at)",
        {
            "id": new_id,
            "publication_id": publication_id,
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "journal": journal,
            "year": year,
            "publisher_url": publisher_url,
            "best_known_link": best_known_link,
            "why_unavailable": why_unavailable,
            "priority": priority,
            "priority_topic": resolved_topic,
            "reports_titer_or_yield": int(reports_titer_or_yield),
            "added_at": now,
        },
    )
    return new_id


# ---------------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------------


def acquire_fulltext(
    *,
    doi: str | None,
    pmid: str | None,
    conn: sqlite3.Connection,
    settings: Settings,
    transport: Transport,
    publication_id: str | None = None,
    title: str | None = None,
    journal: str | None = None,
    year: int | None = None,
    publisher_url: str | None = None,
    topic: str | None = None,
    reports_titer_or_yield: bool = False,
    contact_email: str | None = None,
) -> AcquisitionOutcome:
    """Resolve OA status for one DOI/PMID and fetch + store full text where the licence permits.

    Every call writes exactly one `fulltext_asset` row -- stored, pointer-only, or not-found --
    and never raises on a network failure (build step 4: "never fabricate a retrieval; if a fetch
    fails, the row says so"). Anything that ends up without a stored copy is also written into
    `manual_download_queue` via `enqueue_manual_download`, so it is never simply dropped.
    """
    if doi is None and pmid is None:
        raise ValueError("acquire_fulltext requires a doi or a pmid")

    resolution = resolve_oa_status(
        doi=doi, pmid=pmid, transport=transport, contact_email=contact_email
    )

    why_unavailable: str | None
    content_path: str | None = None
    checksum: str | None = None
    media_type: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    fetch_error: str | None = None

    if resolution.best_oa_url is None:
        storage_state = "not_found"
        why_unavailable = "paywalled" if resolution.oa_status == "closed" else "no_pdf_found"
    elif resolution.oa_status not in _STORABLE_OA_STATUSES:
        storage_state = "pointer_only"
        source_url = resolution.best_oa_url
        why_unavailable = "licence_forbids"
    else:
        try:
            fetched = transport.get_bytes(resolution.best_oa_url)
        except TransportError as exc:
            storage_state = "not_found"
            fetch_error = str(exc)
            why_unavailable = "fetch_failed"
        else:
            content_path, checksum = store_bytes_content_addressed(
                settings, fetched.data, media_type=fetched.content_type
            )
            media_type = fetched.content_type
            source_url = resolution.best_oa_url
            retrieved_at = _utc_now_iso()
            storage_state = "stored_fulltext"
            why_unavailable = None

    effective_doi = resolution.doi or doi
    effective_pmid = resolution.pmid or pmid
    existing = find_fulltext_asset(conn, doi=effective_doi, pmid=effective_pmid)
    asset_id = write_fulltext_asset(
        conn,
        existing_id=str(existing["id"]) if existing is not None else None,
        doi=effective_doi,
        pmid=effective_pmid,
        publication_id=publication_id,
        oa_status=resolution.oa_status,
        license_=resolution.license,
        text_mining_allowed=resolution.text_mining_allowed,
        resolved_via=resolution.resolved_via,
        best_oa_url=resolution.best_oa_url,
        storage_state=storage_state,
        content_path=content_path,
        checksum_sha256=checksum,
        media_type=media_type,
        source_url=source_url,
        retrieved_at=retrieved_at,
        fetch_error=fetch_error,
    )

    manual_queue_id: str | None = None
    if why_unavailable is not None:
        manual_queue_id = enqueue_manual_download(
            conn,
            doi=doi,
            pmid=pmid,
            why_unavailable=why_unavailable,
            title=title,
            journal=journal,
            year=year,
            publisher_url=publisher_url,
            best_known_link=resolution.best_oa_url or publisher_url,
            publication_id=publication_id,
            topic=topic,
            reports_titer_or_yield=reports_titer_or_yield,
        )

    conn.commit()
    return AcquisitionOutcome(
        fulltext_asset_id=asset_id,
        resolution=resolution,
        stored=(why_unavailable is None),
        why_unavailable=why_unavailable,
        manual_queue_id=manual_queue_id,
    )
