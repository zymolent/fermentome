"""The Publication read: what the atlas holds about one paper, and what it can prove.

PLAN.md P.2 gives this page one thing it must get right:

    Extraction provenance -- click a value, see the sentence

That is the whole design. Every finding on this page carries the sentence it came from, **read
back out of the stored document** rather than echoed from the extraction that proposed it. The
difference is not pedantry: a stored quote proves that a model once emitted that string, and
nothing else. Resolving it against the source proves the paper says it.

The other thing this page has to be honest about is that **the atlas mostly does not have the
paper**. 5,164 publications are known and 1,308 have stored full text; the rest are a DOI, an
open-access status, and a link. A page that renders those identically is claiming a corpus four
times the size of the real one, so :class:`FullTextAvailability` distinguishes four states --
stored, pointer only, looked for and not found, and never looked -- and the last two are as
different as any pair in this codebase.

Findings come from the `span` table rather than from `curation_task`, because a span outlives the
task: a rejected proposal's span is still a record of what the model quoted, and the Publication
page is the place where a reader would want to see that a claim about this paper was considered
and thrown out. Task status travels beside each finding so an unreviewed proposal never renders
as an established one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from ..config import Settings
from .builder import Page, Select
from .values import Absence, Cited, Value, Zone

__all__ = [
    "CONTEXT_CHARS",
    "Finding",
    "FullTextAvailability",
    "PublicationRead",
    "ScreeningRead",
    "corpus_shape",
    "read_publication",
    "search_publications",
]

#: Characters either side of a quote, matching `review.CONTEXT_CHARS` so the two agree on screen.
CONTEXT_CHARS: Final[int] = 260


def _text(raw: Any, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or str(raw).strip() == "":
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(str(raw), zone=zone)


@dataclass(frozen=True)
class FullTextAvailability:
    """Whether the atlas actually has the paper, in four states rather than a boolean.

    ``never_looked`` and ``not_found`` are the pair that matters. One means acquisition has not
    reached this publication; the other means it has, and the paper is not obtainable. They imply
    completely different next actions and a boolean ``has_fulltext`` collapses them.
    """

    state: str
    media_type: Value[str]
    oa_status: Value[str]
    license: Value[str]
    text_mining_allowed: Value[bool]
    characters: Value[int]

    @property
    def is_readable(self) -> bool:
        return self.state == "stored_fulltext"

    @property
    def display(self) -> str:
        return {
            "stored_fulltext": "full text stored",
            "pointer_only": "link only -- the text is not held here",
            "not_found": "looked for and not obtainable",
            "never_looked": "acquisition has not reached this paper",
        }[self.state]

    def as_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "display": self.display,
            "is_readable": self.is_readable,
            "media_type": self.media_type.as_json(),
            "oa_status": self.oa_status.as_json(),
            "license": self.license.as_json(),
            "text_mining_allowed": self.text_mining_allowed.as_json(),
            "characters": self.characters.as_json(),
        }


@dataclass(frozen=True)
class ScreeningRead:
    """Why this publication is in the corpus at all."""

    family: str
    triage_state: str
    product_tier: str
    admitted_criterion: Value[str]
    exclusion_reason: Value[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "triage_state": self.triage_state,
            "product_tier": self.product_tier,
            "admitted_criterion": self.admitted_criterion.as_json(),
            "exclusion_reason": self.exclusion_reason.as_json(),
        }


@dataclass(frozen=True)
class Finding:
    """One extracted record, with the sentence it came from as the document has it now."""

    record_path: Value[str]
    record_kind: Value[str]
    task_status: Value[str]
    section: Value[str]
    quote_as_recorded: Value[str]
    quote_in_source: Value[str]
    before: str = ""
    after: str = ""
    char_start: int | None = None

    @property
    def resolves(self) -> bool:
        """Whether the document still says, at those offsets, what the extraction claims."""
        return (
            self.quote_in_source.is_known
            and self.quote_as_recorded.is_known
            and self.quote_in_source.unwrap() == self.quote_as_recorded.unwrap()
        )

    @property
    def is_established(self) -> bool:
        """False for anything still proposed. A pending record is not a finding about the paper."""
        return self.task_status.or_none() in {"accepted", "edited"}

    @property
    def context(self) -> str:
        if not self.quote_in_source.is_known:
            return ""
        return f"{self.before}>>>{self.quote_in_source.unwrap()}<<<{self.after}"

    def as_json(self) -> dict[str, Any]:
        return {
            "record_path": self.record_path.as_json(),
            "record_kind": self.record_kind.as_json(),
            "task_status": self.task_status.as_json(),
            "section": self.section.as_json(),
            "quote_as_recorded": self.quote_as_recorded.as_json(),
            "quote_in_source": self.quote_in_source.as_json(),
            "resolves": self.resolves,
            "is_established": self.is_established,
            "before": self.before,
            "after": self.after,
            "char_start": self.char_start,
        }


@dataclass(frozen=True)
class PublicationRead:
    """One paper: what is known of it, whether it is held, and what was read out of it."""

    id: str
    title: Value[str]
    year: Value[int]
    journal: Value[str]
    doi: Value[str]
    pmid: Value[str]
    license: Value[str]
    fulltext: FullTextAvailability
    screening: tuple[ScreeningRead, ...]
    findings: tuple[Finding, ...]
    findings_truncated: bool = False

    @property
    def citation(self) -> Cited[str]:
        return Cited(payload=self.id, source_kind="publication", source_id=self.id)

    @property
    def unresolved_findings(self) -> tuple[Finding, ...]:
        """Findings whose span no longer matches -- the page's own integrity check."""
        return tuple(f for f in self.findings if not f.resolves)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title.as_json(),
            "year": self.year.as_json(),
            "journal": self.journal.as_json(),
            "doi": self.doi.as_json(),
            "pmid": self.pmid.as_json(),
            "license": self.license.as_json(),
            "citation": self.citation.as_json(),
            "fulltext": self.fulltext.as_json(),
            "screening": [s.as_json() for s in self.screening],
            "findings": [f.as_json() for f in self.findings],
            "findings_truncated": self.findings_truncated,
            "counts": {
                "findings": len(self.findings),
                "established": sum(1 for f in self.findings if f.is_established),
                "unresolved_spans": len(self.unresolved_findings),
            },
        }


def _availability(
    conn: sqlite3.Connection, settings: Settings, publication_id: str
) -> FullTextAvailability:
    row = (
        Select("fulltext_asset")
        .columns("storage_state", "media_type", "oa_status", "license", "text_mining_allowed")
        .where("publication_id = ?", publication_id)
        .order_by("storage_state")
        .page(conn, limit=1)
    )
    if not row.rows:
        return FullTextAvailability(
            state="never_looked",
            media_type=Value.absent(Absence.NOT_RECORDED),
            oa_status=Value.absent(Absence.NOT_RECORDED),
            license=Value.absent(Absence.NOT_RECORDED),
            text_mining_allowed=Value.absent(Absence.NOT_RECORDED),
            characters=Value.absent(Absence.NOT_RECORDED),
        )
    first = row.rows[0]
    state = str(first["storage_state"])
    characters: Value[int] = Value.absent(Absence.NOT_RECORDED)
    if state == "stored_fulltext":
        from ..extract.harness import load_source_text

        try:
            text, _ = load_source_text(conn, settings, publication_id=publication_id)
            characters = Value.known(len(text), zone=Zone.HARMONIZED)
        except Exception:
            # The row says stored and the bytes are not readable. Reported as 'not_found'
            # rather than 'stored': a page claiming to hold a paper it cannot open is worse
            # than one admitting it does not.
            state = "not_found"
    allowed = first["text_mining_allowed"]
    return FullTextAvailability(
        state=state,
        media_type=_text(first["media_type"]),
        oa_status=_text(first["oa_status"]),
        license=_text(first["license"]),
        text_mining_allowed=(
            Value.absent(Absence.NOT_RECORDED)
            if allowed is None
            else Value.known(bool(allowed), zone=Zone.REPORTED)
        ),
        characters=characters,
    )


def _findings(
    conn: sqlite3.Connection, settings: Settings, publication_id: str, *, limit: int
) -> tuple[tuple[Finding, ...], bool]:
    page: Page = (
        Select("span", alias="s")
        .columns(
            "s.record_path AS record_path",
            "s.section AS section",
            "s.char_start AS char_start",
            "s.char_end AS char_end",
            "s.quoted_text AS quoted_text",
            "t.record_kind AS record_kind",
            "t.status AS status",
        )
        .join(
            "curation_task",
            ("s.extraction_id = t.extraction_id", "s.record_path = t.record_path"),
            alias="t",
        )
        .where("s.publication_id = ?", publication_id)
        .order_by("s.char_start")
        .page(conn, limit=limit)
    )

    text: str | None = None
    try:
        from ..extract.harness import load_source_text

        text, _ = load_source_text(conn, settings, publication_id=publication_id)
    except Exception:
        text = None  # no stored text: quotes travel as recorded, and resolves() stays false

    findings: list[Finding] = []
    for row in page:
        start, end = row["char_start"], row["char_end"]
        in_source: Value[str] = Value.absent(Absence.NOT_RECORDED)
        before = after = ""
        if text is not None and isinstance(start, int) and isinstance(end, int):
            in_source = Value.known(text[start:end], zone=Zone.REPORTED)
            before = text[max(0, start - CONTEXT_CHARS) : start]
            after = text[end : min(len(text), end + CONTEXT_CHARS)]
        findings.append(
            Finding(
                record_path=_text(row["record_path"]),
                record_kind=_text(row["record_kind"]),
                task_status=_text(row["status"]),
                section=_text(row["section"]),
                quote_as_recorded=_text(row["quoted_text"], zone=Zone.INFERRED),
                quote_in_source=in_source,
                before=before,
                after=after,
                char_start=start if isinstance(start, int) else None,
            )
        )
    return tuple(findings), page.truncated


def read_publication(
    conn: sqlite3.Connection,
    publication_id: str,
    *,
    settings: Settings | None = None,
    finding_limit: int = 200,
) -> PublicationRead | None:
    """One publication, or None if there is no such row."""
    settings = settings or Settings.load()
    row = (
        Select("publication")
        .columns("id", "doi", "pmid", "title", "year", "journal", "license")
        .where("id = ?", publication_id)
        .one(conn)
    )
    if row is None:
        return None

    screening = (
        Select("screening_record")
        .columns("family", "triage_state", "product_tier", "admitted_criterion", "exclusion_reason")
        .where("publication_id = ?", publication_id)
        .order_by("family")
        .page(conn, limit=50)
    )
    findings, truncated = _findings(conn, settings, publication_id, limit=finding_limit)

    year = row["year"]
    return PublicationRead(
        id=str(row["id"]),
        title=_text(row["title"]),
        year=(
            Value.known(int(year), zone=Zone.REPORTED)
            if year is not None
            else Value.absent(Absence.NOT_RECORDED)
        ),
        journal=_text(row["journal"]),
        doi=_text(row["doi"]),
        pmid=_text(row["pmid"]),
        license=_text(row["license"]),
        fulltext=_availability(conn, settings, publication_id),
        screening=tuple(
            ScreeningRead(
                family=str(s["family"]),
                triage_state=str(s["triage_state"]),
                product_tier=str(s["product_tier"]),
                admitted_criterion=_text(s["admitted_criterion"]),
                exclusion_reason=_text(s["exclusion_reason"]),
            )
            for s in screening
        ),
        findings=findings,
        findings_truncated=truncated,
    )


def search_publications(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    year: int | None = None,
    family: str | None = None,
    triage_state: str | None = None,
    readable_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> Page:
    """Publications matching the given facets, as a `Page` that reports its own truncation.

    ``readable_only`` filters to publications whose full text is actually held, which is the
    facet that matters most in this corpus: 1,308 of 5,164. Without it a result count reads as
    "papers about this" when it means "papers we know the title of".
    """
    select = (
        Select("publication", alias="p")
        .columns(
            "p.id AS id",
            "p.title AS title",
            "p.year AS year",
            "p.journal AS journal",
            "p.doi AS doi",
        )
        .distinct()
    )
    if query:
        select = select.where("p.title LIKE ?", f"%{query}%")
    if year is not None:
        select = select.where("p.year = ?", year)
    if readable_only:
        select = select.join(
            "fulltext_asset", "p.id = f.publication_id", alias="f", kind="INNER"
        ).where("f.storage_state = ?", "stored_fulltext")
    if family or triage_state:
        select = select.join("screening_record", "p.id = r.publication_id", alias="r", kind="INNER")
        if family:
            select = select.where("r.family = ?", family)
        if triage_state:
            select = select.where("r.triage_state = ?", triage_state)
    return select.order_by("p.year DESC", "p.id").page(conn, limit=limit, offset=offset)


def corpus_shape(conn: sqlite3.Connection) -> dict[str, int]:
    """Publications by how much of them the atlas actually holds.

    The number worth putting in front of anyone: how many of the known papers can be read.
    """
    total = int(Select("publication").columns("COUNT(*) AS n").scalar(conn) or 0)
    by_state = {
        str(row["storage_state"]): int(row["n"])
        for row in Select("fulltext_asset")
        .columns("storage_state", "COUNT(DISTINCT publication_id) AS n")
        .group_by("storage_state")
        .page(conn)
    }
    accounted = sum(by_state.values())
    return {
        "publications": total,
        **by_state,
        "never_looked": max(0, total - accounted),
    }
