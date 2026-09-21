"""Full-text re-screen: find the E1 evidence that lives below the abstract line.

**What this is for.** `discovery.py` asks PubMed a question about title+abstract, and
`docs/drafts/literature/E1_QUERY_BLINDNESS.md` §4.1 measured what that instrument can see for the
B.3.1 competing-sink criterion. Across the iso-only publications with stored full text, **5 carry
Pdc evidence in title+abstract and 56 carry it in the body; 51 of those 56 are invisible to every
`[tiab]` query that could ever be written**, in any notation. Abstract screening reaches about 9%
of the E1-relevant material in the readable corpus. That is not a vocabulary problem and the
query edits shipped alongside this module do not fix it -- they rescue one paper in six.

**Why E1 and nothing else.** E1 is the only B.3 criterion whose admission test is a *genotype*,
and a genotype is a methods fact: it appears in an abstract only when the paper is about the
genotype, and the entire class of papers this defect loses are papers that *use* a Pdc-minus
chassis to study something else. E2/E3/E4/E5/E6 are outcome criteria whose evidence is in the
abstract by construction. The scope lives in `data/literature/rescreen_patterns.yaml`, which says
the same thing at more length.

**This screen does not subsume discovery and discovery does not subsume it.** A full-text screen
only re-reads what is already in the corpus: it would have found 0 of the 43 publications the E1
and E6 query edits newly admit. The two mechanisms are complementary.

---

## The provenance problem, and what this module does about it

`screening_record` cannot hold a row this screen produces. Three of its columns say so:

    family             TEXT NOT NULL
    first_seen_run_id  TEXT NOT NULL REFERENCES search_run(id)
    last_seen_run_id   TEXT NOT NULL REFERENCES search_run(id)

A full-text screen ran no query, so it has no family and no `search_run`. There are two ways to
make the row fit and one of them is a lie:

* **A synthetic `search_run`** would work mechanically and is refused here. `search_run` means
  "one E-utilities query was executed"; a row that never touched E-utilities makes the table mean
  two things, and `queries.family_status` reads `search_run.hit_count` against
  `query_families.yaml`'s `expected_count` to compute drift. A screen's row would either be
  invisible to `status` (a family name not in the YAML is never iterated) or would corrupt the
  drift arithmetic of a real family -- and `screening_record`'s `UNIQUE (publication_id, family)`
  means writing under a real family name would *overwrite* that family's genuine triage. Every
  variant of this is worse than not storing the row.

* **A distinct provenance path**, which is correct and needs a schema change this module
  deliberately does not make. See :data:`SCHEMA_CHANGE_REQUIRED`.

So this module writes **no database rows at all**. It emits a proposal document -- every record
carrying `review_state='proposed'`, `triage_state='needs_full_text'` and
`provenance='fulltext_rescreen'` -- into the derived tier, and reports what it found. That is not
a workaround pretending to be a design: the screen is a deterministic function of a committed
pattern file and this recorded code over bytes already in the store, so it is re-runnable in
under two minutes and its output is rebuildable by definition. A proposal that can be regenerated
exactly does not need durable storage; it needs a reviewer. What it *would* need storage for is
the moment a curator accepts one, and that is the moment the schema change below is due.

## Two things every row here carries that a `screening_record` row structurally cannot

Both are from E1_QUERY_BLINDNESS.md §4.4, and both are the reason a bare
`admitted_criterion='E1'` would misrepresent how the paper was found:

1. **The coverage denominator.** Only 1,429 of 5,164 publications have stored bytes. A screen
   that can only ever see 28% of the corpus must say so at the point of use, or its silence reads
   as "we looked everywhere".
2. **The licence conditioning.** That 28% skews heavily open-access, because open access is what
   made it storable. Admitting from it without recording that turns B.3's "admitted against a
   stated criterion" into "admitted against a stated criterion, if we happened to be allowed to
   read it." Each candidate therefore carries its own `oa_status`, `text_mining_allowed` and
   `license` as reported, and the run carries the distribution.

Nothing here admits anything. `admitted_criterion` is a curator's word (PLAN.md B.3, L.5); this
module proposes candidates for one and says how confident it is not.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from ..config import Settings
from ..extract import UNSECTIONED, Section, SourceTextError, load_source_text, split_sections
from .queries import VALID_CRITERIA

__all__ = [
    "PATTERNS_FILE",
    "PROVENANCE",
    "SCHEMA_CHANGE_REQUIRED",
    "Coverage",
    "CriterionPatterns",
    "Licence",
    "RescreenCandidate",
    "RescreenError",
    "RescreenPatterns",
    "RescreenResult",
    "load_rescreen_patterns",
    "proposal_document",
    "rescreen",
    "write_proposals",
]

#: The committed pattern file, under `settings.literature_dir`. Repo tier, Zone R.
PATTERNS_FILE: Final[str] = "rescreen_patterns.yaml"

#: What every proposal this module emits records about where it came from. The value exists to be
#: distinguishable from search-derived screening at a glance and in a `grep`.
PROVENANCE: Final[str] = "fulltext_rescreen"

#: Sections treated as "not the body" when the abstract/body split is made. `front_matter` is the
#: title block; `abstract` is the abstract, with any structured sub-headings already folded into
#: it by the sectioner. Everything else is body.
_HEAD_SECTIONS: Final[frozenset[str]] = frozenset({"front_matter", "abstract"})

#: The v12 -> v13 migration this module needs before a single row can be stored, written out so
#: the next agent inherits the decision rather than re-deriving it. NOT APPLIED: the live database
#: is at v12 with other work in flight, and `migrations.py` is explicit that an unreviewed schema
#: change is an unreviewed data change.
#:
#: Note the second half. The new table alone is not enough, because `first_seen_run_id` and
#: `last_seen_run_id` are NOT NULL and SQLite cannot relax a NOT NULL with `ALTER TABLE`. That
#: needs a new-table-plus-copy of `screening_record` -- which `migrations.py` already sanctions
#: ("A migration that genuinely needs to drop a column should be written as a new table plus a
#: copy, so the old data is still there to compare against when it goes wrong") but which is a
#: rebuild of the busiest table in the literature layer and is not a thing to do in passing.
SCHEMA_CHANGE_REQUIRED: Final[str] = """\
v12 -> v13, to give a full-text re-screen a provenance path of its own:

  1. CREATE TABLE rescreen_run (
         id                TEXT PRIMARY KEY,
         criterion         TEXT NOT NULL CHECK (criterion IN ('E1','E2','E3','E4','E5','E6')),
         patterns_version  INTEGER NOT NULL,
         patterns_digest   TEXT NOT NULL,   -- sha256 of rescreen_patterns.yaml, so a run is
                                            -- reproducible from a recorded input (Zone H)
         started_at        TEXT NOT NULL,
         finished_at       TEXT,
         corpus_size       INTEGER NOT NULL,  -- publications in the atlas
         readable_size     INTEGER NOT NULL,  -- of those, with stored bytes: THE DENOMINATOR
         pool_size         INTEGER NOT NULL,  -- of those, actually screened
         unreadable        INTEGER NOT NULL
     );
     -- Separate from search_run on purpose: that table means "an E-utilities query ran", and
     -- `queries.family_status` does drift arithmetic on its hit_count. This one means "a regex
     -- screen ran over stored bytes". Merging them would make both unreadable.

  2. ALTER TABLE screening_record ADD COLUMN provenance TEXT NOT NULL DEFAULT 'search'
         CHECK (provenance IN ('search', 'fulltext_rescreen'));
     ALTER TABLE screening_record ADD COLUMN rescreen_run_id TEXT REFERENCES rescreen_run(id);
     ALTER TABLE screening_record ADD COLUMN evidence_locator TEXT;  -- section + quote

  3. Relax screening_record.first_seen_run_id / last_seen_run_id to nullable, with a CHECK that
     exactly one provenance is named:
         CHECK ((provenance = 'search'            AND first_seen_run_id IS NOT NULL)
             OR (provenance = 'fulltext_rescreen' AND rescreen_run_id   IS NOT NULL))
     SQLite cannot drop a NOT NULL via ALTER TABLE, so this step is a new-table-plus-copy of
     screening_record, not an ALTER. It is the expensive part and the reason this is a reviewed
     migration rather than an incidental one.

Until (3) exists, `family NOT NULL` and the two NOT NULL run-id foreign keys make a rescreen row
unstorable, and `fermdb literature rescreen` writes a proposal document instead of rows."""


class RescreenError(RuntimeError):
    """`rescreen_patterns.yaml` is missing or malformed, or a criterion has no pattern set."""


def _default_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------------------------
# The pattern file
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionPatterns:
    """One criterion's screen: what counts as a mention, a genotype, a phrase, and where."""

    criterion: str
    label: str
    min_mentions: int
    sections: tuple[str, ...]
    mention: re.Pattern[str]
    genotype: re.Pattern[str]
    phrase: re.Pattern[str]
    description: str | None = None


@dataclass(frozen=True)
class RescreenPatterns:
    """The parsed `rescreen_patterns.yaml`, plus the digest of the bytes it was parsed from.

    The digest is not decoration. A screen is Zone H only if it is reconstructible from a recorded
    input, and "the pattern file" is not a recorded input unless the run says *which* pattern file.
    """

    version: int
    measured_on: str
    digest: str
    criteria: tuple[CriterionPatterns, ...]

    def __getitem__(self, criterion: str) -> CriterionPatterns:
        for entry in self.criteria:
            if entry.criterion == criterion:
                return entry
        known = ", ".join(entry.criterion for entry in self.criteria) or "(none)"
        raise RescreenError(
            f"no pattern set for criterion {criterion!r} in {PATTERNS_FILE} (defined: {known}). "
            f"A criterion belongs here only with a measurement behind it showing its evidence "
            f"does not live in abstracts -- see the file's header."
        )

    def criteria_names(self) -> tuple[str, ...]:
        return tuple(entry.criterion for entry in self.criteria)


def _compile(raw: Any, *, criterion: str, field: str) -> re.Pattern[str]:
    if not isinstance(raw, list) or not raw:
        raise RescreenError(f"{criterion}: '{field}' must be a non-empty list of regexes")
    parts: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise RescreenError(f"{criterion}: '{field}' contains a non-string or empty pattern")
        parts.append(entry)
    combined = "|".join(f"(?:{part})" for part in parts)
    try:
        return re.compile(combined, re.IGNORECASE)
    except re.error as exc:
        raise RescreenError(f"{criterion}: '{field}' is not a valid regex: {exc}") from exc


def _parse_criterion(raw: Any) -> CriterionPatterns:
    if not isinstance(raw, dict):
        raise RescreenError(f"each entry under 'criteria' must be a mapping, got {raw!r}")
    try:
        criterion = str(raw["criterion"])
        label = str(raw["label"])
        min_mentions = int(raw["min_mentions"])
    except KeyError as exc:
        raise RescreenError(f"criteria entry missing required key {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise RescreenError(f"criteria entry has a malformed value: {exc}") from exc

    if criterion not in VALID_CRITERIA:
        raise RescreenError(
            f"unknown criterion {criterion!r}; must be one of {VALID_CRITERIA}. This vocabulary "
            f"is closed in queries.py because the meaning of each criterion is written into "
            f"PLAN.md B.3 and enforced by a schema CHECK."
        )
    if min_mentions < 1:
        raise RescreenError(f"{criterion}: min_mentions must be >= 1, got {min_mentions}")

    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise RescreenError(f"{criterion}: 'sections' must be a non-empty list")
    sections = tuple(str(name) for name in sections_raw)

    return CriterionPatterns(
        criterion=criterion,
        label=label,
        min_mentions=min_mentions,
        sections=sections,
        mention=_compile(raw.get("mention"), criterion=criterion, field="mention"),
        genotype=_compile(raw.get("genotype"), criterion=criterion, field="genotype"),
        phrase=_compile(raw.get("phrase"), criterion=criterion, field="phrase"),
        description=raw.get("description"),
    )


def load_rescreen_patterns(path: Path) -> RescreenPatterns:
    """Parse and validate `rescreen_patterns.yaml`, recording the digest of its bytes."""
    if not path.is_file():
        raise RescreenError(f"rescreen pattern file not found: {path}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    doc = yaml.safe_load(data.decode("utf-8")) or {}
    if not isinstance(doc, dict):
        raise RescreenError(f"{path}: expected a mapping at the top level")
    raw_criteria = doc.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise RescreenError(f"{path}: missing or empty top-level 'criteria' list")
    criteria = tuple(_parse_criterion(entry) for entry in raw_criteria)
    names = [entry.criterion for entry in criteria]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise RescreenError(f"{path}: duplicate criterion(s): {duplicates}")
    return RescreenPatterns(
        version=int(doc.get("version", 1)),
        measured_on=str(doc.get("measured_on", "")),
        digest=digest,
        criteria=criteria,
    )


# ---------------------------------------------------------------------------------------------
# What a screen produces
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Licence:
    """The access terms that made this publication readable, as the OA source reported them.

    Carried on every candidate because the selection is conditioned on it: a paper is a candidate
    only if it was storable, and what was storable is not a random sample of the literature.
    """

    oa_status: str
    text_mining_allowed: str | None
    license: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "oa_status": self.oa_status,
            "text_mining_allowed": self.text_mining_allowed,
            "license": self.license,
        }


@dataclass(frozen=True)
class Coverage:
    """The denominator the screen ran against, and how biased it is.

    Every number here is reported in the command's own output rather than kept for a footnote.
    E1_QUERY_BLINDNESS.md §4.4: a screen that can only see the open-access 28% and does not say so
    "introduces an open-access bias into the ethanol layer, silently".
    """

    corpus_size: int
    readable_size: int
    pool_size: int
    read_ok: int
    unsectioned: int
    unreadable: tuple[tuple[str, str], ...]
    oa_status_counts: tuple[tuple[str, int], ...]
    text_mining_counts: tuple[tuple[str | None, int], ...]

    @property
    def readable_fraction(self) -> float:
        """Stored bytes over the whole atlas. The number that bounds what any screen can see."""
        return self.readable_size / self.corpus_size if self.corpus_size else 0.0

    @property
    def open_access_size(self) -> int:
        """Candidates whose bytes are open-access by `fulltext_asset.oa_status`."""
        return sum(n for status, n in self.oa_status_counts if status != "closed")

    @property
    def open_access_fraction(self) -> float:
        return self.open_access_size / self.pool_size if self.pool_size else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_size": self.corpus_size,
            "readable_size": self.readable_size,
            "readable_fraction": round(self.readable_fraction, 4),
            "pool_size": self.pool_size,
            "read_ok": self.read_ok,
            "unreadable": [
                {"publication_id": pub_id, "why": why} for pub_id, why in self.unreadable
            ],
            "unsectioned": self.unsectioned,
            "oa_status_counts": dict(self.oa_status_counts),
            "text_mining_allowed_counts": {
                str(key): value for key, value in self.text_mining_counts
            },
            "open_access_fraction": round(self.open_access_fraction, 4),
            "selection_is_conditioned_on_licence": True,
        }


@dataclass(frozen=True)
class RescreenCandidate:
    """One publication the screen proposes for a criterion, and the evidence for proposing it."""

    publication_id: str
    doi: str | None
    pmid: str | None
    title: str | None
    year: int | None
    journal: str | None
    body_mentions: int
    genotype_quote: str
    genotype_section: str
    in_wanted_section: bool
    phrase_quote: str | None
    abstract_visible: bool
    sectioned: bool
    licence: Licence

    def as_proposal(self, *, criterion: str, screen_id: str) -> dict[str, Any]:
        """This candidate as the row a curator reviews -- proposed, never admitted.

        The field names mirror `screening_record` deliberately, so that when
        :data:`SCHEMA_CHANGE_REQUIRED` is applied this document loads into it without a
        translation layer inventing anything.
        """
        return {
            "publication_id": self.publication_id,
            "doi": self.doi,
            "pmid": self.pmid,
            "title": self.title,
            "year": self.year,
            "journal": self.journal,
            # The three states this screen is entitled to assert, and no more.
            "review_state": "proposed",
            "triage_state": "needs_full_text",
            "product_tier": "ethanol",
            "default_disposition": "exclude_unless_admitted",
            # NOT 'admitted_criterion'. A keyword match cannot establish an admission; only a
            # curator reading the paper against B.3 can (PLAN.md B.3, L.5).
            "candidate_criterion": criterion,
            "admitted_criterion": None,
            "provenance": PROVENANCE,
            "rescreen_id": screen_id,
            "evidence": {
                "body_mentions": self.body_mentions,
                "genotype_quote": self.genotype_quote,
                "genotype_section": self.genotype_section,
                "in_wanted_section": self.in_wanted_section,
                "phrase_quote": self.phrase_quote,
                "abstract_visible": self.abstract_visible,
                "sectioned": self.sectioned,
            },
            # Why this row exists at all, and what it cost to be able to read the paper.
            "selection_conditioned_on_licence": self.licence.as_dict(),
        }


@dataclass(frozen=True)
class RescreenResult:
    """Everything one `fermdb literature rescreen` run found, and what it could not see."""

    criterion: str
    label: str
    screen_id: str
    started_at: str
    finished_at: str
    patterns_version: int
    patterns_digest: str
    min_mentions: int
    wanted_sections: tuple[str, ...]
    coverage: Coverage
    abstract_visible: int
    body_evidence: int
    candidates: tuple[RescreenCandidate, ...]

    @property
    def body_only(self) -> int:
        """Publications whose criterion evidence is in the body and nowhere an abstract query
        could reach it. This number is the whole argument for the screen existing."""
        return self.body_evidence - self.abstract_visible

    @property
    def sectioned_candidates(self) -> tuple[RescreenCandidate, ...]:
        """Candidates whose genotype match landed in a wanted section.

        The stricter of the two gates, and the one to act on: a regex over a whole paper hits
        every passing Discussion citation ("unlike Pdc-minus strains..."). Both counts are kept so
        the gate's effect is visible rather than assumed.
        """
        return tuple(c for c in self.candidates if c.in_wanted_section)

    @property
    def unreachable_by_any_query(self) -> tuple[RescreenCandidate, ...]:
        """Sectioned candidates with no criterion evidence in title+abstract at all.

        No `[tiab]` query, in any notation, can ever reach these. They are the screen's reason
        for existing rather than a second opinion on discovery's work.
        """
        return tuple(c for c in self.sectioned_candidates if not c.abstract_visible)


# ---------------------------------------------------------------------------------------------
# The screen
# ---------------------------------------------------------------------------------------------

#: The pool: publications that hold a screening row in the isobutanol tier ONLY, and whose bytes
#: are stored. This is E1_QUERY_BLINDNESS.md §7's reporting gap (b) made executable -- "a check
#: that flags publications holding screening rows in one tier only while their stored full text
#: matches another tier's criterion terms". A publication already carrying an ethanol-tier row has
#: been through ethanol triage and needs no proposal from here.
_POOL_SQL: Final[str] = """
SELECT p.id, p.doi, p.pmid, p.title, p.year, p.journal,
       f.oa_status, f.text_mining_allowed, f.license
  FROM publication p
  JOIN fulltext_asset f
    ON f.publication_id = p.id AND f.storage_state = 'stored_fulltext'
 WHERE EXISTS (SELECT 1 FROM screening_record s
                WHERE s.publication_id = p.id AND s.product_tier = 'isobutanol')
   AND NOT EXISTS (SELECT 1 FROM screening_record s
                    WHERE s.publication_id = p.id AND s.product_tier = 'ethanol')
 GROUP BY p.id
 ORDER BY p.id
"""


def _quote(match: re.Match[str] | None, text: str, *, window: int = 60) -> str | None:
    """A match with enough either side to be read as a sentence, whitespace collapsed."""
    if match is None:
        return None
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return " ".join(text[start:end].split())


def _split_head_and_body(text: str, sections: Sequence[Section]) -> tuple[str, str]:
    """(title+abstract, body). An unsectioned document is all body and no head.

    Not a guess: a document with no recognizable headings -- chiefly a PDF, of which 152 are
    stored -- has no machine-readable abstract/body boundary, so calling any of it "abstract"
    would be inventing one. Treating it as all body means its abstract-visibility is reported as
    unknown-shaped rather than falsely resolved, and the run counts it separately.
    """
    head_parts: list[str] = []
    body_parts: list[str] = []
    for section in sections:
        (head_parts if section.name in _HEAD_SECTIONS else body_parts).append(section.text_of(text))
    return "".join(head_parts), "".join(body_parts)


def _section_of(sections: Sequence[Section], offset: int) -> str:
    for section in sections:
        if section.char_start <= offset < section.char_end:
            return section.name
    return UNSECTIONED


def rescreen(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    criterion: str,
    patterns: RescreenPatterns | None = None,
    now: Callable[[], str] = _default_now,
    id_factory: Callable[[], str] = _default_id,
) -> RescreenResult:
    """Screen every readable iso-only publication for one criterion's evidence.

    Writes nothing to `conn` -- reads only. See the module docstring for why: a row this produces
    has no `search_run` to point at, and inventing one would make `search_run` mean two things.
    """
    if patterns is None:
        patterns = load_rescreen_patterns(settings.literature_dir / PATTERNS_FILE)
    spec = patterns[criterion]
    wanted = frozenset(spec.sections)

    started_at = now()
    screen_id = id_factory()

    corpus_size = int(conn.execute("SELECT COUNT(*) FROM publication").fetchone()[0])
    readable_size = int(
        conn.execute(
            "SELECT COUNT(DISTINCT publication_id) FROM fulltext_asset "
            "WHERE storage_state = 'stored_fulltext' AND publication_id IS NOT NULL"
        ).fetchone()[0]
    )

    rows = conn.execute(_POOL_SQL).fetchall()

    candidates: list[RescreenCandidate] = []
    unreadable: list[tuple[str, str]] = []
    oa_counts: dict[str, int] = {}
    mining_counts: dict[str | None, int] = {}
    abstract_visible = 0
    body_evidence = 0
    unsectioned = 0
    read_ok = 0

    for row in rows:
        publication_id = str(row["id"])
        oa_status = str(row["oa_status"])
        oa_counts[oa_status] = oa_counts.get(oa_status, 0) + 1
        mining = row["text_mining_allowed"]
        mining_counts[mining] = mining_counts.get(mining, 0) + 1

        try:
            text, _origin = load_source_text(conn, settings, publication_id=publication_id)
        except SourceTextError as exc:
            # Never silently dropped: a paper the screen could not read is a hole in the screen,
            # and a hole nobody counted is indistinguishable from a paper with no evidence.
            unreadable.append((publication_id, str(exc).splitlines()[0]))
            continue
        read_ok += 1

        sections = split_sections(text)
        is_sectioned = not (len(sections) == 1 and sections[0].name == UNSECTIONED)
        if not is_sectioned:
            unsectioned += 1
        head, body = _split_head_and_body(text, sections)

        head_hit = bool(
            spec.mention.search(head) or spec.genotype.search(head) or spec.phrase.search(head)
        )
        if head_hit:
            abstract_visible += 1
        if spec.mention.search(body) or spec.genotype.search(body) or spec.phrase.search(body):
            body_evidence += 1

        mentions = len(spec.mention.findall(body))
        if mentions < spec.min_mentions:
            continue

        # Look for the genotype in the document rather than in the body slice, so the match offset
        # can be resolved back to the section it actually landed in.
        best: re.Match[str] | None = None
        best_section = UNSECTIONED
        for match in spec.genotype.finditer(text):
            section_name = _section_of(sections, match.start())
            if section_name in _HEAD_SECTIONS:
                continue
            if best is None:
                best, best_section = match, section_name
            if section_name in wanted:
                best, best_section = match, section_name
                break
        if best is None:
            continue

        quote = _quote(best, text)
        assert quote is not None  # `best` is not None, so `_quote` returns a string
        candidates.append(
            RescreenCandidate(
                publication_id=publication_id,
                doi=row["doi"],
                pmid=row["pmid"],
                title=row["title"],
                year=row["year"],
                journal=row["journal"],
                body_mentions=mentions,
                genotype_quote=quote,
                genotype_section=best_section,
                in_wanted_section=best_section in wanted,
                phrase_quote=_quote(spec.phrase.search(body), body),
                abstract_visible=head_hit,
                sectioned=is_sectioned,
                licence=Licence(
                    oa_status=oa_status,
                    text_mining_allowed=None if mining is None else str(mining),
                    license=row["license"],
                ),
            )
        )

    coverage = Coverage(
        corpus_size=corpus_size,
        readable_size=readable_size,
        pool_size=len(rows),
        read_ok=read_ok,
        unsectioned=unsectioned,
        unreadable=tuple(unreadable),
        oa_status_counts=tuple(sorted(oa_counts.items())),
        text_mining_counts=tuple(sorted(mining_counts.items(), key=lambda kv: str(kv[0]))),
    )
    return RescreenResult(
        criterion=spec.criterion,
        label=spec.label,
        screen_id=screen_id,
        started_at=started_at,
        finished_at=now(),
        patterns_version=patterns.version,
        patterns_digest=patterns.digest,
        min_mentions=spec.min_mentions,
        wanted_sections=spec.sections,
        coverage=coverage,
        abstract_visible=abstract_visible,
        body_evidence=body_evidence,
        candidates=tuple(candidates),
    )


# ---------------------------------------------------------------------------------------------
# The proposal document
# ---------------------------------------------------------------------------------------------


def proposal_document(result: RescreenResult, *, sectioned_only: bool = True) -> dict[str, Any]:
    """The reviewable artifact: run provenance, the coverage it is conditioned on, and the rows.

    `sectioned_only` keeps the stricter gate (a genotype match inside Methods/Results). The looser
    set is still reachable through `result.candidates`; it is not what a reviewer should be handed
    by default, because its extra members are mostly Discussion citations.
    """
    chosen = result.sectioned_candidates if sectioned_only else result.candidates
    return {
        "kind": "fermdb.literature.rescreen.proposals",
        "provenance": PROVENANCE,
        "criterion": result.criterion,
        "label": result.label,
        "rescreen_id": result.screen_id,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "patterns_file": PATTERNS_FILE,
        "patterns_version": result.patterns_version,
        "patterns_sha256": result.patterns_digest,
        "gate": {
            "min_mentions": result.min_mentions,
            "sections": list(result.wanted_sections),
            "sectioned_only": sectioned_only,
        },
        "nothing_is_admitted": (
            "Every record below is review_state='proposed' with admitted_criterion=None. A "
            "keyword match cannot establish a B.3 admission; only a curator reading the paper "
            "can (PLAN.md B.3, L.5)."
        ),
        "coverage": result.coverage.as_dict(),
        "coverage_caveat": (
            f"This screen can only ever see the {result.coverage.readable_size} of "
            f"{result.coverage.corpus_size} publications with stored bytes "
            f"({result.coverage.readable_fraction:.0%}), and that sample skews open-access "
            f"because open access is what made it storable. Every record below is therefore "
            f"conditioned on licence, and says so in its own "
            f"`selection_conditioned_on_licence` field."
        ),
        "storage_note": SCHEMA_CHANGE_REQUIRED,
        "counts": {
            "pool": result.coverage.pool_size,
            "abstract_visible": result.abstract_visible,
            "body_evidence": result.body_evidence,
            "body_only": result.body_only,
            "substantive": len(result.candidates),
            "substantive_in_wanted_section": len(result.sectioned_candidates),
            "unreachable_by_any_query": len(result.unreachable_by_any_query),
        },
        "proposals": [
            candidate.as_proposal(criterion=result.criterion, screen_id=result.screen_id)
            for candidate in chosen
        ],
    }


def write_proposals(result: RescreenResult, path: Path, *, sectioned_only: bool = True) -> Path:
    """Write the proposal document as YAML into the derived tier. Returns the path written.

    YAML rather than JSON because a curator reads this and then edits it, and because it is the
    same format as every other reviewable layer in `data/literature/`. It is written to the
    DERIVED tier, not the repo tier: the screen is a deterministic function of a committed pattern
    file and stored bytes, so this document is rebuildable and does not belong in a curated,
    committed directory. A record a curator has accepted does -- and that is the point at which
    `SCHEMA_CHANGE_REQUIRED` is due.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = proposal_document(result, sectioned_only=sectioned_only)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(document, handle, sort_keys=False, allow_unicode=True, width=100)
    return path


def summary_lines(result: RescreenResult) -> list[str]:
    """The run as `fermdb literature rescreen` prints it.

    Built here rather than in the CLI so the ordering is a property of the result and can be
    asserted on: the coverage denominator and the licence conditioning come BEFORE the findings,
    because a reader who stops after the interesting part must still have seen them.
    """
    coverage = result.coverage
    mining = ", ".join(f"{key}={value}" for key, value in coverage.text_mining_counts)
    oa = ", ".join(f"{key}={value}" for key, value in coverage.oa_status_counts)
    lines = [
        f"rescreen {result.criterion} ({result.label})  id={result.screen_id}",
        f"  patterns: {PATTERNS_FILE} v{result.patterns_version} "
        f"sha256={result.patterns_digest[:12]}",
        f"  gate: >={result.min_mentions} body mentions AND a genotype match in "
        f"{'/'.join(result.wanted_sections)}",
        "",
        "COVERAGE -- what this screen can see at all",
        f"  {coverage.readable_size} of {coverage.corpus_size} publications have stored bytes "
        f"({coverage.readable_fraction:.0%}); a full-text screen can never reach the rest",
        f"  pool screened: {coverage.pool_size} isobutanol-tier-only publications with stored "
        f"bytes ({coverage.read_ok} read, {len(coverage.unreadable)} unreadable, "
        f"{coverage.unsectioned} with no machine-readable section boundaries)",
        "",
        "SELECTION IS CONDITIONED ON LICENCE",
        f"  oa_status of the pool: {oa}",
        f"  text_mining_allowed:   {mining}",
        f"  {coverage.open_access_fraction:.0%} of the pool is open access. A candidate below is "
        f"a candidate because it was readable, and what is readable is not a random sample of "
        f"the literature -- every proposal records its own access terms.",
        "",
        "FINDINGS",
        f"  criterion evidence in title+abstract: {result.abstract_visible}",
        f"  criterion evidence in the body:       {result.body_evidence}",
        f"  body-only (no [tiab] query can ever reach these): {result.body_only}",
        f"  substantive (gate on mentions + genotype):        {len(result.candidates)}",
        f"  ... and in {'/'.join(result.wanted_sections)}:    {len(result.sectioned_candidates)}",
        f"  ... of which abstract-invisible:                  "
        f"{len(result.unreachable_by_any_query)}",
    ]
    if coverage.unreadable:
        lines.append("")
        lines.append("UNREADABLE (counted, never silently dropped)")
        lines.extend(f"  {pub_id}: {why}" for pub_id, why in coverage.unreadable)
    lines.append("")
    lines.append("PROPOSED (review_state='proposed'; nothing is admitted)")
    for candidate in result.sectioned_candidates:
        flag = "" if candidate.abstract_visible else "  [abstract-invisible]"
        lines.append(
            f"  {candidate.publication_id}  pmid={candidate.pmid}  "
            f"mentions={candidate.body_mentions}  section={candidate.genotype_section}  "
            f"oa={candidate.licence.oa_status}{flag}"
        )
        lines.append(f"      {candidate.title or '(no title)'}")
        lines.append(f"      genotype: ...{candidate.genotype_quote}...")
    return lines


def criterion_names(patterns: RescreenPatterns) -> Mapping[str, str]:
    """`{criterion: label}` for every criterion the pattern file defines, for CLI help/errors."""
    return {entry.criterion: entry.label for entry in patterns.criteria}
