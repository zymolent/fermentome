"""Condition-context proposals: the curation decision made cheap, and never made automatically.

`curate.promote`'s `PROMOTERS` refuses to promote `conditions`, and the refusal is right. The
extraction emits **one record per facet** ("carbon_sources: 2% glucose or galactose"), while
`condition_context` is one immutable row per *whole context*. Turning N facet records into one
context means deciding which facets belong together, and nothing in a payload says. Grouping by
strain is a guess; a wrong grouping produces a context that never existed and that measurements
are then compared across -- the single failure PLAN.md K.4 and A.3.3 exist to prevent.

**So this module does not group. It proposes.** The difference is not rhetorical:

* Every candidate names the **recorded fact** that put its facets together
  (:class:`Basis`), and a candidate whose basis is weaker than co-occurrence in one quoted
  sentence says so, in a warning, on the candidate itself.
* Nothing here writes a `condition_context` row, and nothing here can. There is no writer in this
  module and no `PROMOTERS` entry for it. The output is a :class:`ContextProposal`, which a
  curator accepts, splits or merges, and the approved result comes back as a document
  (:func:`load_approval`) that is validated and hashed but still not written.
* :func:`context_hash` is a pure function of facets a curator has committed to. It refuses a
  facet set that a proposal could produce on its own, because a proposal's facets are
  `as_reported` strings with no parsed value and no missing-value state, and hashing those would
  be inventing both.

## `context_hash`

PLAN.md C.5: a stable hash over the *recorded* facets only, so identical contexts across papers
converge on one row. `schema.sql` sharpens "recorded" to the `(value, state)` pair, and this
module implements exactly that:

* A facet the source never mentioned contributes **nothing** -- it is not in the mapping at all.
* A facet the source recorded as not applicable (`state='not_applicable'`, PLAN.md C.5's `'NA'`)
  contributes, and hashes differently from the same facet left out, and differently again from
  `state='unknown'`. "The source never recorded it" and "recorded as not applicable" are
  different facts and are never coerced into each other -- not by this hash, and not by the
  constructor, which refuses a value of the literal string `'NA'` or `'unknown'` because that is
  the coercion arriving through the front door.
* `as_reported` shadows are **not** hashed. Two papers writing "30 C" and "30 +/- 1 C" for the
  same parsed 30.0 are the same context; the shadows are kept on the row for provenance and
  differ freely.
* `zone`, `evidence`, `confidence` and `completeness_score` are not hashed either. They describe
  how well the context is known, not which context it is.

Values are canonicalised only where two spellings are certainly the same value: whitespace is
collapsed, and numbers go through a decimal normal form so `30` and `30.0` converge. Case is
**not** folded. Whether `"YPD"` and `"ypd"` name the same medium is a synonymy question, and
answering it inside a hash would silently merge two contexts on a guess -- the same class of
mistake this whole module exists to refuse.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CLASS_DEFINING_FACETS",
    "FACET_STATES",
    "UNRECORDED_TOKENS",
    "Basis",
    "ContextCandidate",
    "ContextProposal",
    "Facet",
    "FacetRecord",
    "Note",
    "build_context_page",
    "context_hash",
    "context_proposal",
    "context_proposals",
    "load_approval",
    "load_condition_facets",
    "page_payload",
]


# ------------------------------------------------------------------------------- the hash side


#: The three states PLAN.md C.5 and `schema.sql` allow a facet to be in. `'recorded'` carries a
#: value; the other two are themselves the recorded fact and carry none.
FACET_STATES: Final[tuple[str, ...]] = ("recorded", "not_applicable", "unknown")

#: Strings that are a *state* wearing a value's clothes. A caller passing one of these as a value
#: is coercing "not applicable" or "not resolvable" into a medium name, and the two would then
#: hash as though the source had written them down as text. Refused at construction.
UNRECORDED_TOKENS: Final[frozenset[str]] = frozenset(
    {"na", "n/a", "n.a.", "unknown", "not applicable", "not recorded", "none recorded", "-", ""}
)

#: PLAN.md C.5's 2026-09-20 amendment makes these three **class-defining** rather than
#: descriptive: they participate in `context_hash`, appear in every comparability class (K.4),
#: and a measurement whose value is `'unknown'` may not enter an aggregate with one that states a
#: value. A context missing any of them is not wrong, but it is not yet usable for comparison,
#: and a proposal says so rather than letting it be discovered at aggregation time.
#:
#: Two of the three have **no column in `condition_context` and no row in
#: `data/vocabularies/condition_facets.tsv`** -- the amendment was written and never migrated.
#: This module names them anyway, because a proposal that only warned about the facet that
#: happens to have a column would under-report the gap.
CLASS_DEFINING_FACETS: Final[tuple[str, ...]] = (
    "aeration_class",
    "carbon_regime",
    "in_situ_product_removal",
)


def _canonical_number(value: float | int | Decimal) -> str:
    """A decimal normal form, so 30, 30.0 and Decimal('30.00') all canonicalise the same."""
    try:
        normalised = Decimal(str(value)).normalize()
    except InvalidOperation as exc:  # pragma: no cover - only reachable for NaN/inf
        raise ValueError(f"{value!r} has no decimal normal form") from exc
    if not normalised.is_finite():
        raise ValueError(f"{value!r} is not a finite number, so it is not a recorded value")
    return format(normalised, "f")


@dataclass(frozen=True)
class Facet:
    """One facet of a context, as a curator committed to it.

    Not what an extraction proposed. An extraction proposes a string and a quote; this is the
    parsed value plus the missing-value state, which only a person supplies. The type tag in the
    canonical form is why `ph_controlled=True` and `medium_name='true'` cannot collide.
    """

    name: str
    state: str
    value: str | float | int | bool | Decimal | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a facet must be named; an anonymous facet cannot be deduplicated")
        if self.state not in FACET_STATES:
            raise ValueError(
                f"facet {self.name!r} has state {self.state!r}; must be one of {FACET_STATES}"
            )
        if self.state == "recorded" and self.value is None:
            raise ValueError(
                f"facet {self.name!r} is 'recorded' with no value -- schema.sql refuses that row "
                "in both directions, and a hash over it would claim a value the source has not"
            )
        if self.state != "recorded" and self.value is not None:
            raise ValueError(
                f"facet {self.name!r} is {self.state!r} but carries the value {self.value!r}; "
                "a value and a not-recorded state are contradictory claims"
            )
        if isinstance(self.value, str) and self.value.strip().lower() in UNRECORDED_TOKENS:
            raise ValueError(
                f"facet {self.name!r} was given {self.value!r} as a value. That is a state, not a "
                "value: pass state='not_applicable' or state='unknown'. PLAN.md C.5 forbids "
                "coercing 'the source never recorded it' and 'recorded as not applicable' into "
                "each other, and storing either as text does exactly that"
            )

    def canonical(self) -> list[str]:
        """`[name, state, type-tag, value]`, the tuple the hash is taken over."""
        if self.value is None:
            return [self.name.strip(), self.state, "none", ""]
        if isinstance(self.value, bool):
            return [self.name.strip(), self.state, "bool", "true" if self.value else "false"]
        if isinstance(self.value, (int, float, Decimal)):
            return [self.name.strip(), self.state, "number", _canonical_number(self.value)]
        return [self.name.strip(), self.state, "text", " ".join(str(self.value).split())]


def context_hash(facets: Iterable[Facet] | Mapping[str, Facet]) -> str:
    """A stable hash over the recorded facets of one context (PLAN.md C.5).

    Stable across processes and releases: sha256 over sorted, compact JSON of each facet's
    canonical tuple, with no Python object identity, no dict ordering and no float repr in it.
    Identical contexts in two papers therefore produce one `context_hash` and converge on one
    `condition_context` row, which is the whole point -- a saved analysis names a context and
    gets the same rows back.

    Refuses an empty facet set. A context with nothing recorded would hash to one shared value,
    and every measurement whose conditions are unknown would then land in the same context and be
    pooled. PLAN.md C.7 keeps such a sample deliberately at `condition_context = NULL`; an empty
    context is that NULL wearing an id.
    """
    values = list(facets.values()) if isinstance(facets, Mapping) else list(facets)
    if not values:
        raise ValueError(
            "no recorded facets, so there is no context to hash -- a sample with unknown "
            "conditions carries condition_context = NULL, not a shared empty context"
        )
    seen: set[str] = set()
    for facet in values:
        name = facet.name.strip()
        if name in seen:
            raise ValueError(
                f"facet {name!r} appears twice; a condition_context holds one value per facet, so "
                "two values for one facet are two contexts and the split is a curator's call"
            )
        seen.add(name)
    canonical = json.dumps(
        sorted(facet.canonical() for facet in values), separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_condition_facets(vocabularies_dir: Path | str) -> frozenset[str]:
    """The facet names `data/vocabularies/condition_facets.tsv` allows.

    Read here rather than through `extract.schemas.load_vocabulary` because that builds the whole
    payload vocabulary and needs a database connection; a proposal only needs to know whether a
    facet name is one the atlas recognises.
    """
    path = Path(vocabularies_dir) / "condition_facets.tsv"
    names: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        header: list[str] | None = None
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\n").split("\t")
            if header is None:
                header = cells
                continue
            row = dict(zip(header, cells, strict=False))
            field_name = (row.get("field") or "").strip()
            if field_name:
                names.add(field_name)
    if not names:
        raise ValueError(f"{path} lists no facets, so nothing could be validated against it")
    return frozenset(names)


# --------------------------------------------------------------------------- the proposal side


class Basis(StrEnum):
    """What recorded fact put a candidate's facets together. Never "it seemed related".

    Ordered strongest first. The point of naming the basis on every candidate is that a curator
    can see, without opening the paper, whether a grouping is something the source said or
    something this module merely offered.
    """

    #: The facets were read from the *same quoted span*. One sentence describing two facets is
    #: the source co-reporting them, which is as close to recorded co-occurrence as an extraction
    #: gets. Still not proof they describe one vessel, which is why it is a candidate.
    SAME_SPAN = "same_span"
    #: The extraction recorded the same `strain_name_as_reported` for each. A real recorded
    #: field, and a weak basis: one strain routinely appears under several contexts in one paper,
    #: which is usually the whole experiment. Always carries `grouping_not_recorded`.
    SAME_STRAIN_AS_REPORTED = "same_strain_as_reported"
    #: The record named no strain and shares no span, so nothing groups it. Its own candidate of
    #: one -- the honest default, and the reason this module has no fallback bucket.
    UNATTRIBUTED = "unattributed"


@dataclass(frozen=True)
class Note:
    """Something a curator should see before accepting a candidate. Mirrors `query.review`."""

    code: str
    message: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class FacetRecord:
    """One accepted `conditions` proposal, with the span that justifies it.

    `value_as_reported` is the paper's own string and is all there is. There is deliberately no
    parsed value and no missing-value state on this class: producing either is the curator's
    work, and a field here that quietly held a parse would be the automatic grouper arriving by
    another route.
    """

    task_id: str
    record_path: str
    publication_id: str
    facet: str
    value_as_reported: str
    strain_as_reported: str | None
    quote: str | None
    section: str | None
    char_start: int | None
    char_end: int | None
    confidence: str | None

    @property
    def span_key(self) -> tuple[int, int] | None:
        if self.char_start is None or self.char_end is None:
            return None
        return (self.char_start, self.char_end)

    def as_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "record_path": self.record_path,
            "facet": self.facet,
            "value_as_reported": self.value_as_reported,
            "strain_as_reported": self.strain_as_reported,
            "quote": self.quote,
            "section": self.section,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ContextCandidate:
    """A *suggested* grouping of facet records. Never a context, never a row.

    `decided` is hard-coded False and there is no code path that sets it True. It is in the
    payload the review page reads so that a page can never render a candidate as settled, and in
    `as_json` so that anything that consumes a proposal downstream sees an undecided record.
    """

    key: str
    basis: Basis
    facets: tuple[FacetRecord, ...]
    notes: tuple[Note, ...] = ()
    decided: bool = False

    @property
    def facet_names(self) -> tuple[str, ...]:
        return tuple(record.facet for record in self.facets)

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "basis": self.basis.value,
            "decided": self.decided,
            "facets": [record.as_json() for record in self.facets],
            "notes": [note.as_json() for note in self.notes],
        }


@dataclass(frozen=True)
class ContextProposal:
    """Every candidate for one publication, plus what is missing across all of them."""

    publication_id: str
    title: str
    candidates: tuple[ContextCandidate, ...] = ()
    notes: tuple[Note, ...] = ()
    unknown_facets: tuple[str, ...] = field(default=())

    @property
    def facet_count(self) -> int:
        return sum(len(candidate.facets) for candidate in self.candidates)

    def as_json(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "title": self.title,
            "facet_count": self.facet_count,
            "candidates": [candidate.as_json() for candidate in self.candidates],
            "notes": [note.as_json() for note in self.notes],
            "unknown_facets": list(self.unknown_facets),
        }


_ACCEPTED_STATUSES: Final[tuple[str, ...]] = ("accepted", "edited")


def _facet_records(conn: sqlite3.Connection, publication_id: str) -> tuple[FacetRecord, ...]:
    placeholders = ",".join("?" for _ in _ACCEPTED_STATUSES)
    rows = conn.execute(
        "SELECT id, record_path, publication_id, payload, edited_payload FROM curation_task "
        f"WHERE record_kind = 'conditions' AND publication_id = ? AND status IN ({placeholders}) "
        "ORDER BY record_path, id",
        (publication_id, *_ACCEPTED_STATUSES),
    ).fetchall()
    out: list[FacetRecord] = []
    for row in rows:
        raw = row["edited_payload"] or row["payload"]
        loaded: Any = json.loads(str(raw))
        if not isinstance(loaded, dict):
            continue
        span = loaded.get("span") if isinstance(loaded.get("span"), dict) else {}
        strain = loaded.get("strain_name_as_reported")
        out.append(
            FacetRecord(
                task_id=str(row["id"]),
                record_path=str(row["record_path"]),
                publication_id=str(row["publication_id"]),
                facet=str(loaded.get("facet") or "").strip(),
                value_as_reported=str(loaded.get("value_as_reported") or "").strip(),
                strain_as_reported=(str(strain).strip() or None) if strain else None,
                quote=str(span.get("quote")) if span.get("quote") else None,
                section=str(span.get("section")) if span.get("section") else None,
                char_start=span.get("char_start"),
                char_end=span.get("char_end"),
                confidence=str(loaded.get("confidence")) if loaded.get("confidence") else None,
            )
        )
    return tuple(out)


def _group(records: Sequence[FacetRecord]) -> list[tuple[str, Basis, list[FacetRecord]]]:
    """Candidates, strongest basis first. Each record lands in exactly one candidate.

    A record is placed by the strongest recorded fact available to it: an identical span first,
    then an identical reported strain, then nothing at all. Because the passes run in that order
    a record already claimed by a span never also appears under a strain, so a facet is never
    shown twice and a curator never has to work out which of two candidates owns it.
    """
    by_span: dict[tuple[int, int], list[FacetRecord]] = {}
    for record in records:
        key = record.span_key
        if key is not None:
            by_span.setdefault(key, []).append(record)

    claimed: set[str] = set()
    groups: list[tuple[str, Basis, list[FacetRecord]]] = []
    for key, members in sorted(by_span.items()):
        if len(members) < 2:
            continue
        groups.append((f"span:{key[0]}-{key[1]}", Basis.SAME_SPAN, list(members)))
        claimed.update(member.task_id for member in members)

    by_strain: dict[str, list[FacetRecord]] = {}
    for record in records:
        if record.task_id in claimed or not record.strain_as_reported:
            continue
        by_strain.setdefault(record.strain_as_reported, []).append(record)
    for strain, members in sorted(by_strain.items()):
        groups.append((f"strain:{strain}", Basis.SAME_STRAIN_AS_REPORTED, list(members)))
        claimed.update(member.task_id for member in members)

    for record in records:
        if record.task_id in claimed:
            continue
        groups.append((f"facet:{record.task_id}", Basis.UNATTRIBUTED, [record]))
    return groups


_BASIS_NOTES: Final[Mapping[Basis, Note]] = {
    Basis.SAME_SPAN: Note(
        "grouping_is_co_reported",
        "these facets were read from one quoted sentence, so the source reported them together. "
        "That is co-occurrence in the text, not a statement that they describe one vessel -- "
        "check the sentence before accepting",
    ),
    Basis.SAME_STRAIN_AS_REPORTED: Note(
        "grouping_not_recorded",
        "these facets share only the strain name the extraction recorded. Nothing in the payload "
        "says they describe one context, and one strain routinely spans several in a paper. "
        "Offered as a starting point to split, not as a finding",
    ),
    Basis.UNATTRIBUTED: Note(
        "no_grouping_available",
        "nothing recorded groups this facet with any other -- no shared span, no reported "
        "strain. It is shown alone rather than placed in a default bucket",
    ),
}


#: A strain-grouped candidate holding one facet is not a grouping at all, and saying
#: `grouping_not_recorded` about it would be noise on a card where nothing was grouped. What is
#: worth saying instead is what accepting it would mean: a context in which exactly one facet is
#: recorded, which the hash will happily produce and which almost never matches a real vessel.
_SINGLETON_NOTE: Final[Note] = Note(
    "one_facet_only",
    "one facet was recorded against this strain, so nothing here was grouped. Accepting it as a "
    "context means a context in which exactly one facet is known -- legitimate, hashable, and "
    "almost never what the paper describes. Merging later facets into it is the usual move",
)


def _candidate_notes(
    basis: Basis, members: Sequence[FacetRecord], known: frozenset[str] | None
) -> tuple[Note, ...]:
    lone = len(members) == 1 and basis is Basis.SAME_STRAIN_AS_REPORTED
    notes: list[Note] = [_SINGLETON_NOTE if lone else _BASIS_NOTES[basis]]

    counts: dict[str, list[FacetRecord]] = {}
    for record in members:
        counts.setdefault(record.facet, []).append(record)
    for facet, duplicates in sorted(counts.items()):
        if len(duplicates) > 1:
            values = ", ".join(sorted(f"{d.value_as_reported!r}" for d in duplicates))
            notes.append(
                Note(
                    "facet_recorded_twice",
                    f"{facet} appears {len(duplicates)} times here ({values}). A condition_context "
                    "holds one value per facet, so this candidate cannot be accepted whole: it is "
                    "at least two contexts and splitting it is the decision",
                )
            )

    missing = [f for f in CLASS_DEFINING_FACETS if f not in counts]
    if missing:
        notes.append(
            Note(
                "class_defining_facet_absent",
                f"no record here states {', '.join(missing)}. PLAN.md C.5's 2026-09-20 amendment "
                "makes these class-defining: a measurement that does not state them cannot enter "
                "an aggregate with one that does. 'unknown' is a legitimate value and is a "
                "different fact from the facet being absent, so recording it is worth the minute",
            )
        )

    if known is not None:
        strays = sorted({r.facet for r in members if r.facet and r.facet not in known})
        if strays:
            notes.append(
                Note(
                    "facet_not_in_vocabulary",
                    f"{', '.join(strays)} is not in data/vocabularies/condition_facets.tsv. A "
                    "facet name the atlas does not know changes context_hash without changing "
                    "any recorded fact, so two spellings of one facet would stop deduplicating",
                )
            )

    unspanned = [r.task_id for r in members if r.span_key is None]
    if unspanned:
        notes.append(
            Note(
                "facet_without_span",
                f"{len(unspanned)} record(s) here carry no span offsets, so the quote cannot be "
                "re-resolved against the stored full text. A stored quote proves only that a "
                "model once emitted that string",
            )
        )
    return tuple(notes)


def context_proposal(
    conn: sqlite3.Connection,
    publication_id: str,
    *,
    known_facets: frozenset[str] | None = None,
) -> ContextProposal:
    """Candidates for one publication's accepted `conditions` records. Reads only.

    Only `accepted` and `edited` tasks are read. A pending proposal has not been judged, and
    grouping facets a curator has not yet agreed are true would put the expensive decision before
    the cheap one.
    """
    records = _facet_records(conn, publication_id)
    sql = "SELECT title FROM publication WHERE id = ?"
    row = conn.execute(sql, (publication_id,)).fetchone()
    title = str(row["title"]) if row is not None and row["title"] else publication_id

    if not records:
        return ContextProposal(
            publication_id=publication_id,
            title=title,
            notes=(
                Note(
                    "no_accepted_conditions",
                    "this publication has no accepted 'conditions' record, so there is nothing to "
                    "propose a context from. Its measurements stay at condition_context = NULL",
                ),
            ),
        )

    candidates = tuple(
        ContextCandidate(
            key=key,
            basis=basis,
            facets=tuple(members),
            notes=_candidate_notes(basis, members, known_facets),
        )
        for key, basis, members in _group(records)
    )
    unknown = (
        tuple(sorted({r.facet for r in records if r.facet and r.facet not in known_facets}))
        if known_facets is not None
        else ()
    )
    notes: list[Note] = [
        Note(
            "proposal_only",
            f"{len(candidates)} candidate(s) over {len(records)} facet record(s). None of this is "
            "a condition_context: no row is written here or anywhere downstream of here until a "
            "curator groups the facets and supplies a parsed value and a missing-value state for "
            "each. Grouping by strain is a guess and is labelled as one",
        )
    ]
    return ContextProposal(
        publication_id=publication_id,
        title=title,
        candidates=candidates,
        notes=tuple(notes),
        unknown_facets=unknown,
    )


def context_proposals(
    conn: sqlite3.Connection, *, known_facets: frozenset[str] | None = None
) -> tuple[ContextProposal, ...]:
    """One proposal per publication that has any accepted `conditions` record, ordered by id."""
    placeholders = ",".join("?" for _ in _ACCEPTED_STATUSES)
    rows = conn.execute(
        "SELECT DISTINCT publication_id FROM curation_task WHERE record_kind = 'conditions' "
        f"AND status IN ({placeholders}) ORDER BY publication_id",
        _ACCEPTED_STATUSES,
    ).fetchall()
    return tuple(
        context_proposal(conn, str(row["publication_id"]), known_facets=known_facets)
        for row in rows
    )


# ---------------------------------------------------------------------------- the approval side


def load_approval(document: Mapping[str, Any]) -> tuple[tuple[str, str, tuple[Facet, ...]], ...]:
    """Validate a curator's approved grouping and hash each context. Writes nothing.

    The document is what a curator produces after working through a proposal -- the review page
    below emits it -- and its shape is deliberately *not* the proposal's. A proposal carries
    `as_reported` strings; an approval carries the parsed value and the missing-value state the
    curator decided, per facet::

        {"publication_id": "doi:...",
         "contexts": [{"label": "aerobic flask, glucose",
                       "facets": [{"name": "aeration_class", "state": "recorded",
                                   "value": "aerobic"},
                                  {"name": "ph", "state": "unknown"}]}]}

    Returns `(label, context_hash, facets)` per approved context. It returns rather than writes
    because the write is a separate, evidenced step: `condition_context` has no `carbon_regime`
    and no `in_situ_product_removal` column yet, so a writer today would drop two facets PLAN.md
    C.5 calls class-defining -- silently, and out of the hash.
    """
    contexts = document.get("contexts")
    if not isinstance(contexts, Sequence) or isinstance(contexts, (str, bytes)) or not contexts:
        raise ValueError("an approval must carry a non-empty 'contexts' list")
    out: list[tuple[str, str, tuple[Facet, ...]]] = []
    for index, entry in enumerate(contexts):
        if not isinstance(entry, Mapping):
            raise ValueError(f"contexts[{index}] is not an object")
        label = str(entry.get("label") or f"context {index + 1}")
        raw_facets = entry.get("facets")
        if not isinstance(raw_facets, Sequence) or isinstance(raw_facets, (str, bytes)):
            raise ValueError(f"{label}: 'facets' must be a list")
        facets: list[Facet] = []
        for item in raw_facets:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").strip()
            state = item.get("state")
            if state is None:
                raise ValueError(
                    f"{label}: facet {name!r} has no state. The review page emits a skeleton with "
                    "the paper's own string and no state on purpose -- deciding whether a blank "
                    "is 'recorded as not applicable' or 'never recorded' is the curation "
                    "decision, and PLAN.md C.5 forbids defaulting one into the other"
                )
            facets.append(Facet(name=name, state=str(state), value=item.get("value")))
        out.append((label, context_hash(facets), tuple(facets)))
    hashes = [entry[1] for entry in out]
    if len(set(hashes)) != len(hashes):
        raise ValueError(
            "two approved contexts hash identically, so they are the same context recorded twice. "
            "Merge them, or record what actually differs -- an unrecorded difference is not one"
        )
    return tuple(out)


# -------------------------------------------------------------------------------- the one pass


_TEMPLATE: Final[str] = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fermdb condition contexts &mdash; __COUNT__ facet records</title>
<style>
:root{
  --paper:#F6F8F7;--surface:#fff;--sunk:#EDF1EF;--ink:#131C1B;--ink2:#3C4947;--ink3:#6C7A77;
  --rule:#D8E0DD;--rule2:#C2CDC9;--accent:#A8641F;
  --ok:#2E6B4E;--ok-s:#E1EFE7;--no:#9A3B32;--no-s:#F6E4E1;--edit:#8A6A2F;--edit-s:#F6EEDC;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#0F1615;--surface:#161F1E;--sunk:#1C2725;--ink:#E8EDEB;--ink2:#B4C0BD;--ink3:#87938F;
  --rule:#2A3634;--rule2:#3A4846;--accent:#D69A5C;
  --ok:#6FB78F;--ok-s:#17281F;--no:#D98A80;--no-s:#2B1B19;--edit:#C9A45F;--edit-s:#2A2318;}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--sans)}
header{position:sticky;top:0;z-index:5;background:var(--surface);
  border-bottom:1px solid var(--rule);padding:12px 20px;display:flex;gap:18px;
  align-items:center;flex-wrap:wrap}
header h1{font-size:15px;margin:0;font-weight:600}
.counts{font-family:var(--mono);font-size:12.5px;color:var(--ink3);display:flex;gap:14px;
  flex-wrap:wrap}
.counts b{font-weight:500}
button{font:inherit;font-size:13px;padding:5px 11px;border:1px solid var(--rule2);
  background:var(--surface);color:var(--ink);border-radius:3px;cursor:pointer}
button:hover{border-color:var(--accent)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
main{max-width:940px;margin:0 auto;padding:22px 20px 130px}
.paper{margin:30px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--rule)}
.paper h2{font-size:15px;margin:0 0 3px;font-weight:600}
.paper .doi{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.grp{margin:16px 0 4px;font-family:var(--mono);font-size:11px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink3);display:flex;gap:9px;align-items:center}
.grp i{flex:1;height:1px;background:var(--rule);font-style:normal}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:4px;
  padding:14px 16px;margin:8px 0 8px 26px}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.card.out{opacity:.5;border-left:4px solid var(--no)}
.hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:9px}
.facet{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  background:var(--sunk);color:var(--ink3);padding:2px 7px;border-radius:2px}
.val{font-weight:600}
.gtag{margin-left:auto;font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:2px;
  background:var(--ok-s);color:var(--ok)}
blockquote{margin:0 0 10px;padding:11px 13px;background:var(--sunk);border-radius:3px;
  font-size:13.5px;line-height:1.6;color:var(--ink2)}
blockquote .sec{font-family:var(--mono);font-size:10.5px;color:var(--ink3);display:block;
  margin-bottom:4px}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--ink3);margin-bottom:9px}
.note{background:var(--edit-s);border-left:3px solid var(--edit);padding:8px 11px;
  border-radius:3px;font-size:12.5px;margin:0 0 8px 26px;color:var(--ink2)}
.note b{font-family:var(--mono);font-size:10.5px;color:var(--edit);display:block;
  margin-bottom:2px}
.note.top{margin-left:0}
.acts{display:flex;gap:7px;flex-wrap:wrap}
footer{position:fixed;bottom:0;left:0;right:0;background:var(--surface);
  border-top:1px solid var(--rule);padding:10px 20px;display:flex;gap:12px;align-items:center;
  flex-wrap:wrap;font-size:12.5px}
kbd{font-family:var(--mono);font-size:11px;background:var(--sunk);border:1px solid var(--rule2);
  border-radius:3px;padding:1px 5px}
.hint{color:var(--ink3)}
dialog{border:1px solid var(--rule2);border-radius:5px;background:var(--surface);color:var(--ink);
  max-width:860px;width:92vw;padding:0}
dialog::backdrop{background:rgba(0,0,0,.45)}
dialog .dh{padding:14px 18px;border-bottom:1px solid var(--rule);display:flex;
  align-items:center;gap:12px}
dialog h3{margin:0;font-size:14px}
dialog pre{margin:0;padding:16px 18px;font-family:var(--mono);font-size:12px;line-height:1.6;
  white-space:pre-wrap;word-break:break-word;max-height:56vh;overflow:auto;background:var(--sunk)}
</style></head><body>
<header>
  <h1>fermdb condition contexts</h1>
  <div class="counts" id="counts"></div>
  <button id="show">Show approval</button>
  <button id="reset">Reset</button>
</header>
<main id="list"></main>
<footer>
  <span class="hint">
    <kbd>j</kbd>/<kbd>k</kbd> move &nbsp; <kbd>s</kbd> split out &nbsp;
    <kbd>m</kbd> merge into the group above &nbsp; <kbd>1</kbd>&ndash;<kbd>9</kbd> assign group
    &nbsp; <kbd>x</kbd> exclude &nbsp; <kbd>c</kbd> approval
  </span>
  <span class="hint" style="margin-left:auto">Grouping is yours. No condition_context row is
  written by this page, or by anything it produces.</span>
</footer>
<dialog id="dlg">
  <div class="dh"><h3>Approved grouping &mdash; a skeleton, not a context</h3>
    <button id="copy" style="margin-left:auto">Copy</button>
    <button id="close">Close</button></div>
  <pre id="out"></pre>
</dialog>
<script>
const DATA = __DATA__;
const KEY = "fermdb.contexts.v1";
let groups = {};
try { groups = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { groups = {}; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(groups)); } catch (e) {} };
let cursor = 0;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const groupOf = d => groups[d.task_id] === undefined ? d.group : groups[d.task_id];
const setGroup = (d, g) => { groups[d.task_id] = g; save(); render(); };

function render() {
  const list = document.getElementById("list");
  list.innerHTML = "";
  let lastPub = null, lastGroup = null;
  // Rendered in group order rather than payload order, so a split or a merge is visible where it
  // happened instead of leaving the moved facet stranded under its old heading. The card id stays
  // the payload index, so the cursor and every keystroke still address the same record.
  const order = DATA.map((d, i) => i).sort((a, b) => {
    const A = DATA[a], B = DATA[b];
    if (A.publication_id !== B.publication_id)
      return A.publication_id < B.publication_id ? -1 : 1;
    const ga = String(groupOf(A)).padStart(6, "0"), gb = String(groupOf(B)).padStart(6, "0");
    return ga === gb ? a - b : (ga < gb ? -1 : 1);
  });
  order.forEach(i => {
    const d = DATA[i];
    if (d.publication_id !== lastPub) {
      lastPub = d.publication_id; lastGroup = null;
      const h = document.createElement("div");
      h.className = "paper";
      h.innerHTML = `<h2>${esc(d.title)}</h2><div class="doi">${esc(d.publication_id)}</div>`;
      list.appendChild(h);
      (d.paper_notes || []).forEach(n => {
        const p = document.createElement("div");
        p.className = "note top";
        p.innerHTML = `<b>${esc(n.code)}</b>${esc(n.message)}`;
        list.appendChild(p);
      });
    }
    const g = groupOf(d);
    if (g !== lastGroup) {
      lastGroup = g;
      const head = document.createElement("div");
      head.className = "grp";
      head.innerHTML = g === "out"
        ? `<span>excluded</span><i></i>`
        : `<span>candidate ${esc(g)} &middot; ${esc(d.basis)}</span><i></i>`;
      list.appendChild(head);
      (d.notes || []).forEach(n => {
        const p = document.createElement("div");
        p.className = "note";
        p.innerHTML = `<b>${esc(n.code)}</b>${esc(n.message)}`;
        list.appendChild(p);
      });
    }
    const card = document.createElement("article");
    card.className = "card" + (i === cursor ? " sel" : "") + (g === "out" ? " out" : "");
    card.id = "f" + i;
    card.innerHTML = `
      <div class="hd">
        <span class="facet">${esc(d.facet)}</span>
        <span class="val">${esc(d.value_as_reported)}</span>
        <span class="gtag">${esc(g)}</span>
      </div>
      ${d.quote ? `<blockquote><span class="sec">${esc(d.section || "text")}
        ${d.char_start == null ? "(no offsets)" : esc(d.char_start) + "&ndash;" + esc(d.char_end)}
        </span>${esc(d.quote)}</blockquote>`
        : `<blockquote><em>no quoted span recorded for this facet</em></blockquote>`}
      <div class="meta">strain as reported: ${esc(d.strain_as_reported || "not recorded")}
        &nbsp;&middot;&nbsp; ${esc(d.task_id)}</div>
      <div class="acts">
        <button data-i="${i}" data-a="split">Split out</button>
        <button data-i="${i}" data-a="merge">Merge up</button>
        <button data-i="${i}" data-a="out">Exclude</button>
      </div>`;
    list.appendChild(card);
  });
  counts();
}

function counts() {
  const seen = {};
  let excluded = 0;
  DATA.forEach(d => {
    const g = groupOf(d);
    if (g === "out") { excluded++; return; }
    seen[d.publication_id + "/" + g] = true;
  });
  document.getElementById("counts").innerHTML =
    `<span><b>${DATA.length}</b> facet records</span>` +
    `<span><b>${Object.keys(seen).length}</b> candidate contexts</span>` +
    `<span style="color:var(--no)"><b>${excluded}</b> excluded</span>`;
}

function nextGroup(pub) {
  let n = 0;
  DATA.forEach(d => {
    if (d.publication_id !== pub) return;
    const g = groupOf(d);
    if (typeof g === "number" && g > n) n = g;
  });
  return n + 1;
}

function act(i, a) {
  const d = DATA[i];
  if (a === "out") { setGroup(d, groupOf(d) === "out" ? d.group : "out"); return; }
  if (a === "split") { setGroup(d, nextGroup(d.publication_id)); return; }
  if (a === "merge") {
    for (let j = i - 1; j >= 0; j--) {
      if (DATA[j].publication_id !== d.publication_id) break;
      const g = groupOf(DATA[j]);
      if (g !== "out") { setGroup(d, g); return; }
    }
  }
}

function approval() {
  const lines = [
    "# Produced by fermdb.curate.contexts.build_context_page. It is a SKELETON:",
    "# every facet below has the paper's own string and NO state and NO parsed value.",
    "# fermdb.curate.contexts.load_approval refuses it until you supply, per facet,",
    "#   state: 'recorded' + value, or 'not_applicable', or 'unknown'.",
    "# 'never recorded' is a facet you delete from the list, not a state. PLAN.md C.5.",
    ""
  ];
  const byPub = {};
  DATA.forEach(d => {
    const g = groupOf(d);
    if (g === "out") return;
    byPub[d.publication_id] = byPub[d.publication_id] || {};
    (byPub[d.publication_id][g] = byPub[d.publication_id][g] || []).push(d);
  });
  Object.keys(byPub).sort().forEach(pub => {
    const doc = { publication_id: pub, contexts: [] };
    Object.keys(byPub[pub]).sort().forEach(g => {
      doc.contexts.push({
        label: pub + " candidate " + g,
        facets: byPub[pub][g].map(d => ({
          name: d.facet, state: null, value: null, as_reported: d.value_as_reported,
          from_task: d.task_id
        }))
      });
    });
    lines.push(JSON.stringify(doc, null, 2));
  });
  document.getElementById("out").textContent = lines.join("\\n");
  document.getElementById("dlg").showModal();
}

document.addEventListener("click", e => {
  const b = e.target.closest("button[data-i]");
  if (b) { act(+b.dataset.i, b.dataset.a); return; }
  if (e.target.id === "show") approval();
  if (e.target.id === "close") document.getElementById("dlg").close();
  if (e.target.id === "copy") {
    navigator.clipboard?.writeText(document.getElementById("out").textContent);
    e.target.textContent = "Copied";
    setTimeout(() => { e.target.textContent = "Copy"; }, 1200);
  }
  if (e.target.id === "reset" &&
      confirm("Clear every grouping you made here? The atlas is untouched either way.")) {
    groups = {}; save(); render();
  }
});

document.addEventListener("keydown", e => {
  if (e.target.matches("input,textarea") || document.getElementById("dlg").open) {
    if (e.key === "Escape") document.getElementById("dlg").close();
    return;
  }
  const k = e.key.toLowerCase();
  if (k === "j" || k === "arrowdown") { cursor = Math.min(cursor + 1, DATA.length - 1); render(); }
  else if (k === "k" || k === "arrowup") { cursor = Math.max(cursor - 1, 0); render(); }
  else if (k === "s") act(cursor, "split");
  else if (k === "m") act(cursor, "merge");
  else if (k === "x") act(cursor, "out");
  else if (/^[1-9]$/.test(k)) setGroup(DATA[cursor], +k);
  else if (k === "c") { approval(); return; }
  else return;
  e.preventDefault();
  document.getElementById("f" + cursor)?.scrollIntoView({ block: "center" });
});

render();
</script></body></html>
"""


def page_payload(proposals: Sequence[ContextProposal]) -> list[dict[str, Any]]:
    """One flat, ordered row per facet record, carrying the candidate it starts in.

    Flat rather than nested because the page's job is regrouping: a curator moves a facet between
    candidates, and a nested payload would need rebuilding on every keystroke. The candidate a
    facet starts in travels as ``group``, a small integer per publication -- the proposal's
    opening offer, which every later keystroke overrides.
    """
    out: list[dict[str, Any]] = []
    for proposal in proposals:
        first_of_paper = True
        for index, candidate in enumerate(proposal.candidates, start=1):
            first_of_candidate = True
            for record in candidate.facets:
                row = record.as_json()
                row.update(
                    {
                        "publication_id": proposal.publication_id,
                        "title": proposal.title,
                        "basis": candidate.basis.value,
                        "group": index,
                        "notes": (
                            [note.as_json() for note in candidate.notes]
                            if first_of_candidate
                            else []
                        ),
                        "paper_notes": (
                            [note.as_json() for note in proposal.notes] if first_of_paper else []
                        ),
                    }
                )
                out.append(row)
                first_of_candidate = False
                first_of_paper = False
    return out


def build_context_page(
    conn: sqlite3.Connection, *, known_facets: frozenset[str] | None = None
) -> str:
    """The whole grouping page as one HTML string, data embedded. Reads only.

    Modelled on ``query.reviewhtml.build_review_page``, and for the same reason: the expensive
    part of the decision is holding the paper's sentence, the facet and the consequence in view
    at once, and that is a layout problem. What differs is the verb. The review page decides
    accept/reject per record and emits the ``fermdb curate`` commands that carry the decision
    out. This page decides *which facets are one context* and emits an approval skeleton that
    nothing can carry out yet -- deliberately, because the write is a curation decision with a
    schema gap behind it, and a page that could write a ``condition_context`` would be the
    automatic grouper with a human-shaped button on it.
    """
    proposals = context_proposals(conn, known_facets=known_facets)
    data = page_payload(proposals)
    return _TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace(
        "__COUNT__", str(len(data))
    )
