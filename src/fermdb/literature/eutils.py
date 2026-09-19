"""A polite NCBI E-utilities client (esearch / esummary / efetch).

"Polite" per NCBI's usage guidelines: at most 3 requests/second without an API key, 10/second
with one, retried with exponential backoff on transport failure, and every request identifies
itself with a `tool` and (when configured) an `email`. See
https://www.ncbi.nlm.nih.gov/books/NBK25497/ (unverified — read from general knowledge of the
E-utilities documentation, not fetched in this session).

**Networking is fully pluggable.** `EutilsClient` never imports `urllib` itself for anything the
tests exercise; it calls `self.transport.get(url, timeout=...)`, where `transport` satisfies the
`Transport` protocol below. `UrllibTransport` is the real, network-touching implementation used in
production; tests inject a fake transport instead, so `tests/test_literature.py` never reaches the
network (project instruction: "tests MUST NOT hit the network").

Rate limiting and retry backoff both sleep through injectable `sleep`/`monotonic` callables rather
than the real `time` functions directly, so a test can assert on throttling behaviour without
actually waiting.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

#: NCBI's stated rate limits (requests/second): 3 without an API key, 10 with one.
RATE_LIMIT_NO_KEY = 3.0
RATE_LIMIT_WITH_KEY = 10.0

#: Settings has no concept of a secret/credential (it only resolves filesystem paths), so the
#: NCBI API key and contact email are read directly from the environment instead, following the
#: same "every value is also an environment variable" spirit as fermdb.paths without pretending
#: they are paths.
NCBI_API_KEY_ENV = "FERMDB_NCBI_API_KEY"
NCBI_EMAIL_ENV = "FERMDB_NCBI_EMAIL"

_DEFAULT_TOOL = "fermdb"


class EutilsError(RuntimeError):
    """An E-utilities request failed after retries, or its response could not be parsed."""


class Transport(Protocol):
    """Whatever can fetch a URL. `UrllibTransport` is the only real implementation.

    A transport signals failure by raising `OSError` (or a subclass — `urllib.error.URLError` and
    `TimeoutError` both qualify); `EutilsClient` retries on that and only that, so a transport bug
    that raises something else (a programming error) is not silently swallowed as "the network is
    down".
    """

    def get(self, url: str, *, timeout: float) -> bytes: ...  # pragma: no cover - protocol


@dataclass
class UrllibTransport:
    """The real transport: `urllib.request`. Never exercised by the test suite."""

    user_agent: str = "fermdb/0.0"

    def get(self, url: str, *, timeout: float = 30.0) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return bytes(response.read())


@dataclass(frozen=True)
class EsearchResult:
    """One page of an esearch call."""

    count: int
    ids: tuple[str, ...]
    retmax: int
    retstart: int
    query_translation: str | None


@dataclass
class EutilsClient:
    """A rate-limited, retrying E-utilities client over a pluggable `Transport`.

    Every public method takes explicit keyword arguments and returns parsed data (never raw bytes,
    except `efetch`, whose payload shape depends on the caller's chosen `rettype`/`retmode`).

    Deliberately not frozen: `_last_request_at` is genuine, private, mutable throttle state, not a
    configuration value, and mutating it in place is what lets one client instance be reused
    across many calls without re-measuring elapsed time from a stale snapshot.
    """

    transport: Transport = field(default_factory=UrllibTransport)
    api_key: str | None = None
    email: str | None = None
    tool: str = _DEFAULT_TOOL
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    timeout_seconds: float = 30.0
    #: Injected so tests can run instantly instead of sleeping through real rate limits/backoff.
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    # -inf, not 0.0: with a real monotonic clock the first call is always fine either way (real
    # clocks aren't near 0), but a test's fake clock legitimately starts at 0.0, and 0.0 would make
    # the very first call throttle as if a previous request had just happened at time zero.
    _last_request_at: float = field(default=float("-inf"), init=False, repr=False, compare=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides: Any) -> EutilsClient:
        """Build a client from `FERMDB_NCBI_API_KEY` / `FERMDB_NCBI_EMAIL`, if set.

        Passing `env` (rather than reading `os.environ` directly) is what lets a caller isolate
        this from the real process environment, the same pattern `fermdb.paths.load_paths` uses.
        """
        active_env = os.environ if env is None else env
        defaults: dict[str, Any] = {
            "api_key": active_env.get(NCBI_API_KEY_ENV) or None,
            "email": active_env.get(NCBI_EMAIL_ENV) or None,
        }
        defaults.update(overrides)
        return cls(**defaults)

    @property
    def rate_limit_per_second(self) -> float:
        return RATE_LIMIT_WITH_KEY if self.api_key else RATE_LIMIT_NO_KEY

    # ------------------------------------------------------------------------------- internals

    def _throttle(self) -> None:
        min_interval = 1.0 / self.rate_limit_per_second
        now = self.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            self.sleep(min_interval - elapsed)
        # Re-read rather than reusing `now`: the sleep above (real or faked) is what the next
        # call's elapsed time must be measured from.
        self._last_request_at = self.monotonic()

    def _common_params(self, extra: Mapping[str, str]) -> dict[str, str]:
        params: dict[str, str] = {"tool": self.tool, **extra}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _request(self, endpoint: str, params: Mapping[str, str]) -> bytes:
        url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        last_exc: OSError | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return self.transport.get(url, timeout=self.timeout_seconds)
            except OSError as exc:
                last_exc = exc
                if attempt + 1 >= self.max_retries:
                    break
                self.sleep(self.backoff_base_seconds * (2**attempt))
        raise EutilsError(
            f"{endpoint} failed after {self.max_retries} attempt(s): {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse_json(endpoint: str, raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EutilsError(f"{endpoint} did not return valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise EutilsError(f"{endpoint} returned a non-object JSON payload: {payload!r}")
        return payload

    # --------------------------------------------------------------------------------- esearch

    def esearch(
        self,
        *,
        db: str,
        term: str,
        retstart: int = 0,
        retmax: int = 200,
        mindate: str | None = None,
        maxdate: str | None = None,
        datetype: str | None = None,
    ) -> EsearchResult:
        params = {
            "db": db,
            "term": term,
            "retstart": str(retstart),
            "retmax": str(retmax),
            "retmode": "json",
        }
        if mindate is not None:
            params["mindate"] = mindate
        if maxdate is not None:
            params["maxdate"] = maxdate
        if datetype is not None:
            params["datetype"] = datetype

        raw = self._request("esearch.fcgi", self._common_params(params))
        payload = self._parse_json("esearch.fcgi", raw)
        result = payload.get("esearchresult")
        if not isinstance(result, dict):
            raise EutilsError(f"esearch.fcgi response missing 'esearchresult': {payload!r}")
        try:
            count = int(result["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EutilsError(f"esearch.fcgi response has no usable 'count': {result!r}") from exc
        return EsearchResult(
            count=count,
            ids=tuple(str(i) for i in result.get("idlist", [])),
            retmax=int(result.get("retmax", retmax)),
            retstart=int(result.get("retstart", retstart)),
            query_translation=result.get("querytranslation"),
        )

    def esearch_all_ids(
        self,
        *,
        db: str,
        term: str,
        page_size: int = 200,
        max_records: int | None = None,
        mindate: str | None = None,
        maxdate: str | None = None,
        datetype: str | None = None,
    ) -> list[str]:
        """Page through esearch until every id is collected (or `max_records` is reached)."""
        ids: list[str] = []
        retstart = 0
        while True:
            if max_records is not None:
                remaining = max_records - len(ids)
                if remaining <= 0:
                    break
                page = min(page_size, remaining)
            else:
                page = page_size
            result = self.esearch(
                db=db,
                term=term,
                retstart=retstart,
                retmax=page,
                mindate=mindate,
                maxdate=maxdate,
                datetype=datetype,
            )
            if not result.ids:
                break
            ids.extend(result.ids)
            retstart += len(result.ids)
            if retstart >= result.count:
                break
        return ids if max_records is None else ids[:max_records]

    # -------------------------------------------------------------------------------- esummary

    def esummary(self, *, db: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """Return one summary dict per id, in the order NCBI reports `uids` (not input order)."""
        if not ids:
            return []
        params = {"db": db, "id": ",".join(ids), "retmode": "json"}
        raw = self._request("esummary.fcgi", self._common_params(params))
        payload = self._parse_json("esummary.fcgi", raw)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise EutilsError(f"esummary.fcgi response missing 'result': {payload!r}")
        uids = result.get("uids", [])
        summaries = []
        for uid in uids:
            doc = result.get(uid)
            if isinstance(doc, dict):
                summaries.append(doc)
        return summaries

    # ---------------------------------------------------------------------------------- efetch

    def efetch(
        self,
        *,
        db: str,
        ids: Sequence[str],
        rettype: str = "abstract",
        retmode: str = "xml",
    ) -> bytes:
        """Return the raw efetch payload (XML by default); the caller parses it.

        Full text is not stored unless licence terms permit it (PLAN.md H.4); this client fetches
        bytes and leaves that decision entirely to the caller.
        """
        if not ids:
            return b""
        params = {"db": db, "id": ",".join(ids), "rettype": rettype, "retmode": retmode}
        return self._request("efetch.fcgi", self._common_params(params))
