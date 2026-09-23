"""The tools the MCP server exposes, and the shape every one of their results must have.

Each handler is the same three lines the HTTP layer's handlers are (`api/routes.py`): take the
read-only connection, call one query-layer reader, return its `as_json()`. PLAN.md L.4 says the
MCP server is "a read-only MCP server over the same API the UI uses -- **never a second
implementation**", and the cheapest way to honour that is for this module to contain no domain
logic at all. Where a handler is longer than three lines it is assembling the *contract* below,
never computing a fact.

The contract is the point of this item, and it is PLAN.md O.2 verbatim:

1. Every factual clause carries a citation that resolves to an assertion, a measurement or a
   publication.
2. Evidence level is shown inline.
3. Zone I content is marked as inference.
4. Absence is reported as absence.
5. Conflicts are surfaced, not averaged.

An HTTP client is a program, and a program that drops the zone field renders a page that is
merely wrong. An MCP client is a language model, and a model handed a bare number will write a
sentence around it -- with the confidence the sentence's grammar implies and none of the
qualification the number deserves. So none of the five is left to the caller's diligence:
:class:`Result` has a slot for each, `zone` is a field rather than a formatting convention (O.2.3
is explicit about that), and :func:`Result.as_json` emits all five keys on every response
including the ones that are empty. An empty `conflicts` list is a claim -- "this was looked at
and there were none" -- and a missing `conflicts` key is not.

Absence gets the most machinery because it is the answer most likely to be thrown away. "No study
in this atlas reports isobutanol yield for that strain" is a *result*, and it is a different
statement from "that strain has no isobutanol yield". The first is about the corpus, the second
is about the world, and the corpus cannot support the second. `query/values.py` already carries
that distinction for a single field; here it is carried for a whole answer, reusing the same
`Absence` enum so the wire values are the ones the rest of the system already speaks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ..config import Settings
from ..query import answer, coverage, genes, networks, publications, records, traceability
from ..query import search as search_query
from ..query.builder import Page, QueryError, Select
from ..query.values import Absence, Cited, EvidenceLevel, Value, Zone

__all__ = [
    "ACCESS_COMPUTE",
    "ACCESS_READ",
    "TOOLS",
    "Context",
    "Result",
    "Tool",
    "ToolError",
    "repo_root",
]

#: PLAN.md L.4: "Tools are annotated READ / COMPUTE / WRITE, and writes are off unless explicitly
#: enabled." There is no `ACCESS_WRITE` here, and its absence is the enforcement: a write tool
#: cannot be annotated, so it cannot be registered, so it cannot exist. A constant that is never
#: defined is a stronger guarantee than a flag that defaults to off, because a flag can be
#: flipped by an edit nobody reviews and a missing constant fails at import.
ACCESS_READ: Final[str] = "READ"
ACCESS_COMPUTE: Final[str] = "COMPUTE"

#: How the two differ, for the annotation a client shows. READ is a row lookup; COMPUTE walks or
#: assembles across tables and may take noticeably longer on the real atlas.
ACCESS_NOTE: Final[Mapping[str, str]] = {
    ACCESS_READ: "reads rows; no computation beyond the query",
    ACCESS_COMPUTE: "walks or assembles across several tables; still writes nothing",
}


class ToolError(RuntimeError):
    """A tool could not answer. Reported to the client as a failed call, never as an empty one.

    The distinction matters for the same reason absence does: a tool that returns `{}` when its
    argument was malformed has told the model "there is nothing", which the model will faithfully
    report as a finding about the atlas.
    """


def repo_root() -> Path:
    """The checkout this package was installed from.

    `query/answer.py` reads one file relative to it -- the yield harvest TSV that carries the
    agent-extracted numbers the curated `measurement` table does not yet hold. Resolved the same
    way `api/app.py` resolves `apps/web/dist`, so an installed wheel and a source checkout agree.
    """
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Context:
    """What a handler is given: a read-only connection, the settings, and the checkout.

    `settings` is resolved once per process rather than per call. `Settings.load()` re-reads
    `env/paths.yaml` every time, and a stdio server answers many calls against one configuration.
    """

    conn: sqlite3.Connection
    settings: Settings
    root: Path


# ------------------------------------------------------------------------------- the contract


def _citation(
    claim: str, kind: str, source_id: str, *, locator: str | None = None
) -> dict[str, Any]:
    """One clause and the row it resolves to (O.2.1).

    Built through `Cited`, whose `source_id` is not optional, so there is no way to emit a
    citation that cites nothing -- the type refuses it rather than this function checking for it.
    """
    cited: Cited[str] = Cited(payload=claim, source_kind=kind, source_id=source_id, locator=locator)
    return {"claim": claim, **cited.as_json()}


def _absent(
    claim: str, absence: Absence, *, zone: Zone | None = None, detail: str = ""
) -> dict[str, Any]:
    """An absence reported as an absence (O.2.4), in the same wire form a field's absence takes.

    `Value.as_json()` omits the `value` key entirely on an absence, so a consumer reaching for a
    number here gets nothing to render rather than a `null` that formats as a dash beside real
    numbers. Reusing it means an absent *answer* and an absent *field* are the same shape, and a
    client that handles one handles the other.
    """
    value: Value[str] = Value.absent(absence, zone=zone)
    payload = value.as_json()
    payload["claim"] = claim
    if detail:
        payload["detail"] = detail
    return payload


@dataclass(frozen=True)
class Result:
    """A tool's answer, with the five things PLAN.md O.2 requires an answer to carry.

    `data` is the query layer's own `as_json()`, unreshaped. Nothing here rewrites a reader's
    payload, because reshaping it is exactly how the absence-versus-null distinction gets lost --
    the same reasoning `api/routes.py` gives for adding nothing.
    """

    data: Any
    #: The zone of the answer as a whole, where one applies. None is legitimate -- an index of
    #: identifiers or a count across zones has no single zone -- but then `zone_note` must say so,
    #: because a bare missing zone reads as "unmarked" and Zone I unmarked is the failure O.2.3
    #: exists to prevent.
    zone: Zone | None = None
    zone_note: str = ""
    citations: tuple[dict[str, Any], ...] = ()
    absences: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    evidence_levels: tuple[dict[str, Any], ...] = ()
    caveats: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.zone is None and not self.zone_note:
            raise ToolError(
                "a result with no single zone must say why in `zone_note`; an unmarked zone is "
                "indistinguishable from unmarked Zone I, which PLAN.md O.2.3 forbids"
            )

    def as_json(self) -> dict[str, Any]:
        """The envelope. Every contract key is present on every response, empty ones included."""
        contract: dict[str, Any] = {
            "zone": self.zone.value if self.zone is not None else None,
            "zone_display": self.zone.display if self.zone is not None else None,
            "citations": list(self.citations),
            "absences": list(self.absences),
            "conflicts": list(self.conflicts),
            "evidence_levels": list(self.evidence_levels),
            "caveats": list(self.caveats),
        }
        if self.zone_note:
            contract["zone_note"] = self.zone_note
        if self.zone is Zone.INFERRED:
            contract["inference_warning"] = (
                "Zone I: inferred, not reported. It may not support a conclusion until a curator "
                "promotes it (PLAN.md D.2)."
            )
        return {"data": self.data, "contract": contract}


# --------------------------------------------------------------------------- argument reading


def _string(args: Mapping[str, Any], name: str, *, required: bool = False) -> str | None:
    raw = args.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise ToolError(f"{name!r} is required")
        return None
    if not isinstance(raw, str):
        raise ToolError(f"{name!r} must be a string, got {type(raw).__name__}")
    return raw.strip()


def _integer(args: Mapping[str, Any], name: str, *, default: int, low: int, high: int) -> int:
    raw = args.get(name)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolError(f"{name!r} must be an integer, got {type(raw).__name__}")
    if not low <= raw <= high:
        raise ToolError(f"{name!r} must be between {low} and {high}, got {raw}")
    return raw


def _flag(args: Mapping[str, Any], name: str, *, default: bool = False) -> bool:
    raw = args.get(name)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ToolError(f"{name!r} must be true or false")
    return raw


# ------------------------------------------------------------------------------ small reads


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Whether the live schema has this column, asked rather than assumed.

    The same check `query/search.py` makes, for the same reason: a migration that has not run yet
    must degrade one field, not fail the whole call.
    """
    return any(str(row[1]) == column for row in conn.execute(f'PRAGMA table_info("{table}")'))


def _zones_for(conn: sqlite3.Connection, table: str, ids: Sequence[str]) -> dict[str, str]:
    """``{id: zone}`` for the named rows, or an empty map if the table carries no zone."""
    if not ids or not _has_column(conn, table, "zone") or not _has_column(conn, table, "id"):
        return {}
    page = Select(table).columns("id", "zone").where_in("id", list(ids)).page(conn, limit=len(ids))
    return {str(row["id"]): str(row["zone"]) for row in page}


def _with_zones(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> str:
    """Attach each row's zone in place and return the note describing what was possible.

    Rows are annotated rather than filtered. A row whose zone cannot be established is left
    carrying no `zone` key at all, which is the `Value.as_json()` trick again -- an absent key is
    a visible hole, and `"zone": null` is an invisible one that renders like every other unmarked
    field.
    """
    ids = [str(row["id"]) for row in rows if row.get("id") is not None]
    zones = _zones_for(conn, table, ids)
    if not zones:
        return f"`{table}` carries no zone column in this schema; no row here is zone-marked"
    for row in rows:
        zone = zones.get(str(row.get("id")))
        if zone is not None:
            row["zone"] = zone
            row["zone_display"] = Zone(zone).display
    return f"each row carries its own `zone` from `{table}`"


def _evidence_level(conn: sqlite3.Connection, assertion_id: str) -> EvidenceLevel | None:
    """The L1-L5 level of one assertion, or None if it has no row in the view.

    Imported inside the function for the reason `curate.assertions.level_of` documents its own
    lazy import: `fermdb.query` imports `fermdb.curate.promote` at module scope, and a top-level
    import here closes that cycle. `level_of` is a read -- it is the only reader of the
    `assertion_level` view anywhere, and reimplementing its NULL-versus-conflicted handling here
    would be the second implementation PLAN.md L.4 forbids.
    """
    from ..curate.assertions import NotAssertable, level_of

    try:
        return level_of(conn, assertion_id)
    except NotAssertable:
        return None


# ----------------------------------------------------------------------------- the handlers


def _overview(context: Context, args: Mapping[str, Any]) -> Result:
    read = coverage.read_coverage(context.conn)
    empty = [entity for entity in read.entities if entity.count == 0]
    absences = tuple(
        _absent(
            f"the atlas holds no {entity.label}",
            Absence.NOT_RECORDED,
            detail=entity.note,
        )
        for entity in empty
    )
    return Result(
        data=read.as_json(),
        zone=None,
        zone_note=(
            "counts span every zone; this is a census of the atlas, not a factual claim about "
            "any subject in it"
        ),
        absences=absences,
        caveats=(
            "an empty entity here is classified by *why* it is empty -- `never_populated` means "
            "nothing was ever proposed, which is 'never looked' and not 'nothing exists'",
            "`pending_curation` counts proposals awaiting a human; they are not atlas content "
            "and must never be quoted as rows the atlas holds",
        ),
    )


def _search(context: Context, args: Mapping[str, Any]) -> Result:
    term = _string(args, "query", required=True) or ""
    limit = _integer(args, "limit", default=10, low=1, high=50)
    kinds_raw = args.get("kinds")
    kinds: tuple[str, ...] | None = None
    if kinds_raw is not None:
        if not isinstance(kinds_raw, list) or not all(isinstance(k, str) for k in kinds_raw):
            raise ToolError("'kinds' must be a list of strings")
        kinds = tuple(str(k) for k in kinds_raw)

    payload = search_query.search(context.conn, term, kinds=kinds, limit=limit).as_json()
    # Every kind in `query/search.py` is named after the table it searches, so the kind is the
    # table to read a zone from. Checked against the live schema rather than trusted.
    notes: list[str] = []
    for group in payload.get("groups", []):
        notes.append(_with_zones(context.conn, str(group["kind"]), group["rows"]))

    absences = tuple(
        _absent(
            f"nothing of kind {kind!r} matches {term!r}",
            Absence.NOT_RECORDED,
            detail="this search is a substring match, so a synonym or a morphological variant "
            "would not have matched either -- absence here is weaker evidence than absence "
            "from a detail read",
        )
        for kind in payload.get("empty_kinds", [])
    )
    return Result(
        data=payload,
        zone=None,
        zone_note=(
            "search returns identifiers to look up, not factual clauses; where the table carries "
            "a zone each row is marked individually. " + "; ".join(sorted(set(notes)))
        ),
        absences=absences,
        caveats=(
            str(payload.get("recall_caveat", "")),
            "no hit is ranked against a hit of another kind; the groups are not comparable",
            "a hit is an identifier, not a fact. Fetch it with a detail tool before citing it.",
        ),
    )


def _route_answer(context: Context, args: Mapping[str, Any]) -> Result:
    """The atlas's headline question, assembled from `query/answer.py`.

    One part of that module's answer is **not** computed here, and saying so is the whole reason
    this handler is longer than three lines. `answer.assemble` takes a mapping of per-route
    `RouteSupport` objects, and building those needs the transcriptome FASTA, the quantified
    count matrices and the contrast payloads on disk -- an offline pipeline (`ops/answer.py`), not
    a database read. Handed an empty mapping, `assemble` returns *no routes at all*, and
    `answer.render` would then print "No route has any transcript evidence."

    That sentence would be false, and false in the worst available direction: it reads as a
    finding about the atlas when it is a fact about this process's inputs. So the rendered text is
    not used. The stored `score_evidence` ranking -- which `ops/answer.py` computed and wrote back
    to `pathway_route`, and which is therefore a real reading of the same evidence -- is served
    instead, and the step-level transcript support is reported as not computed, by name.
    """
    limit = _integer(args, "limit", default=6, low=1, high=25)
    assembled = answer.assemble(context.conn, repo_root=context.root, supports={}, limit=limit)
    ranked = networks.rank_routes(context.conn, order_by="score_evidence", limit=limit).as_json()
    zone_note = _with_zones(context.conn, "pathway_route", ranked["rows"])

    def _yield_json(record: answer.YieldRecord) -> dict[str, Any]:
        return {
            "host": record.host,
            "strain": record.strain,
            "value_as_reported": record.value_as_reported,
            "unit_as_reported": record.unit_as_reported,
            "value_g_per_g": record.value_g_per_g,
            "percent_of_theoretical_ceiling": record.percent_of_ceiling,
            "carbon_source": record.carbon_source,
            "doi": record.doi,
            "confidence": record.confidence,
            "curator_reviewed": record.reviewed,
            "zone": Zone.REPORTED.value if record.reviewed else Zone.INFERRED.value,
            "zone_display": (Zone.REPORTED if record.reviewed else Zone.INFERRED).display,
            "note": record.note,
        }

    reviewed = [r for r in assembled.yeast_yields if r.reviewed]
    harvested = [r for r in assembled.yeast_yields if not r.reviewed]
    data: dict[str, Any] = {
        "question": (
            "which pathway engineering is feasible, transcript-backed, and high-yielding?"
        ),
        "three_separate_questions": (
            "feasible, transcript-backed and high-yield are reported as three independent "
            "columns and are never fused into one number; in this corpus they do not point the "
            "same way"
        ),
        "transcript_coverage": {
            "stored_differential_expression_contrasts": assembled.contrasts,
            "samples_with_an_approved_condition_context": assembled.contextualised_samples,
            "samples_total": assembled.total_samples,
            "built_strains_with_a_parsed_construct": list(assembled.builds),
            "unmeasurable_note": assembled.unmeasurable_note,
        },
        "routes_by_stored_evidence_score": ranked,
        "route_transcript_support": {
            "computed": False,
            "reason": (
                "per-step transcript support needs the transcriptome index, the quantified count "
                "matrices and the contrast payloads on disk. This server reads the database "
                "only. Run `python ops/answer.py` for the step-level verdicts."
            ),
            "what_is_served_instead": (
                "`score_evidence` as stored on `pathway_route` by that same pipeline"
            ),
        },
        "yields": {
            "s_cerevisiae_curator_reviewed": [_yield_json(r) for r in reviewed],
            "s_cerevisiae_agent_harvested_not_yet_reviewed": [_yield_json(r) for r in harvested],
            "other_hosts": [_yield_json(r) for r in assembled.other_host_yields],
            "theoretical_maximum_g_per_g": answer.THEORETICAL_MAX_G_PER_G,
        },
        "open_knowledge_gaps": list(assembled.gaps),
    }

    citations = tuple(
        _citation(
            f"{record.host} {record.strain}: {record.value_as_reported} {record.unit_as_reported}",
            "publication",
            record.doi or "unknown",
        )
        for record in (*assembled.yeast_yields, *assembled.other_host_yields)
        if record.doi
    )

    absences: list[dict[str, Any]] = []
    if not reviewed:
        absences.append(
            _absent(
                "no curator-reviewed S. cerevisiae isobutanol yield is in the atlas",
                Absence.NOT_RECORDED,
                zone=Zone.REPORTED,
                detail="`measurement` holds no promoted yield row for this product; the "
                "harvested numbers below are Zone I proposals, not atlas facts",
            )
        )
    if not assembled.builds:
        absences.append(
            _absent(
                "no built strain has both a parsed construct and a contextualised sample",
                Absence.NOT_RECORDED,
                detail="so no route's transcript profile can be attached to a strain",
            )
        )
    if not assembled.gaps:
        absences.append(
            _absent(
                "no 'never_attempted' knowledge gap is recorded",
                Absence.NOT_RECORDED,
                detail="nothing has been proposed as never attempted -- that is 'never looked', "
                "not 'everything has been tried'",
            )
        )

    # A host gap is not a route gap, and reporting the higher number as the answer to a question
    # about yeast answers a different question. Surfaced as a conflict (O.2.5) rather than
    # averaged into a single "best known yield", which is what a mean of these rows would be.
    conflicts: list[dict[str, Any]] = []
    best_yeast = next((r for r in assembled.yeast_yields if r.value_g_per_g), None)
    best_other = next((r for r in assembled.other_host_yields if r.value_g_per_g), None)
    if best_yeast and best_other and best_yeast.value_g_per_g and best_other.value_g_per_g:
        conflicts.append(
            {
                "kind": "host_gap",
                "detail": (
                    f"the best yield in this corpus is {best_other.value_g_per_g:.3f} g/g in "
                    f"{best_other.host}, against {best_yeast.value_g_per_g:.4f} g/g in "
                    f"S. cerevisiae -- a factor of "
                    f"{best_other.value_g_per_g / best_yeast.value_g_per_g:.1f}"
                ),
                "why_it_is_not_averaged": (
                    "it is a host gap, not a route gap: no route ranked here closes it and no "
                    "transcript evidence bears on it"
                ),
                "members": [best_yeast.doi, best_other.doi],
            }
        )

    return Result(
        data=data,
        zone=None,
        zone_note=(
            "mixed by section: curator-reviewed yields are Zone R, agent-harvested yields are "
            f"Zone I proposals, and {zone_note}"
        ),
        citations=citations,
        absences=tuple(absences),
        conflicts=tuple(conflicts),
        caveats=(
            "transcript abundance is not flux: 'elevated' means a construct is transcribed, not "
            "that its enzyme folds, imports or carries carbon",
            "no yield in this atlas is linked to any sequenced sample (`measurement.sample_id` "
            "is NULL on every row), so no route's transcript profile can be regressed on a titer",
            "the routes are ordered by how much of each has been MEASURED, which is not the same "
            "ordering as how well each works",
            "a yield from another host is labelled as such on every row and must stay labelled "
            "in any sentence built from it",
        ),
    )


def _evidence_chain(context: Context, args: Mapping[str, Any]) -> Result:
    """The J.5 chain: assertion -> evidence -> span -> publication, and where it breaks."""
    assertion_id = _string(args, "assertion_id")
    limit = _integer(args, "limit", default=25, low=1, high=200)
    only_broken = _flag(args, "only_broken")

    walk = traceability.walk_assertions(
        context.conn, assertion_ids=[assertion_id] if assertion_id else None
    )
    if assertion_id and not walk.chains:
        raise ToolError(f"no active assertion {assertion_id!r}")

    chains = walk.broken if only_broken else walk.chains
    shown = chains[:limit]

    rows: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for chain in shown:
        payload = chain.as_json()
        level = _evidence_level(context.conn, chain.assertion_id)
        if level is not None:
            # O.2.2: inline on the row, not only in the contract block. A model reading the rows
            # and skipping the envelope must still see the level beside the claim.
            payload["evidence_level"] = level.as_json()
            levels.append({"assertion_id": chain.assertion_id, **level.as_json()})
            if level.is_conflicted:
                conflicts.append(
                    {
                        "kind": "direct_evidence_discordant",
                        "assertion_id": chain.assertion_id,
                        "detail": (
                            "direct evidence exists on both sides and the conflict is "
                            "unresolved, so `assertion_level` declines to grade rather than "
                            "downgrading. This is not 'unknown'."
                        ),
                    }
                )
        rows.append(payload)
        citations.append(
            _citation(
                f"{chain.subject} {chain.predicate} {chain.object}",
                "assertion",
                chain.assertion_id,
            )
        )

    absences: list[dict[str, Any]] = []
    if walk.is_vacuous:
        absences.append(
            _absent(
                "the atlas holds no active assertion",
                Absence.NOT_RECORDED,
                detail="a walk of nothing closes vacuously; it is not evidence that the chains "
                "are sound",
            )
        )

    data = {
        "summary": {
            "walked": walk.n_walked,
            "closed": walk.n_closed,
            "broken": len(walk.broken),
            "vacuous": walk.is_vacuous,
            "breaks_by_kind": walk.breaks_by_kind(),
            "gaps_by_kind": walk.gaps_by_kind(),
        },
        "assertions": rows,
        "shown": len(rows),
        "matched": len(chains),
        "truncated": len(chains) > len(rows),
    }
    return Result(
        data=data,
        zone=None,
        zone_note="each assertion carries its own `zone`; the summary spans all of them",
        citations=tuple(citations),
        absences=tuple(absences),
        conflicts=tuple(conflicts),
        evidence_levels=tuple(levels),
        caveats=(
            "a `break` is a chain that does not resolve to a source; a `gap` is a hop J.5 names "
            "that the schema cannot traverse. A gap is never fatal and the two must not be "
            "reported as the same thing.",
            "a level of None with basis 'no_evidence' and a level of None with basis "
            "'direct_evidence_discordant' are opposite states that arrive as the same NULL",
        ),
    )


def _absences(context: Context, args: Mapping[str, Any]) -> Result:
    """What the atlas does *not* hold, which PLAN.md O.2.4 makes a first-class answer.

    Four different absences, kept apart because they send you to four different places: a
    recorded knowledge gap (a scientist's open question), an entity nobody has proposed anything
    for (acquisition), an entity whose proposals are waiting on a curator (review), and an
    assertion the evidence view grades NULL for want of any evidence at all (J.5).
    """
    limit = _integer(args, "limit", default=25, low=1, high=200)
    read = coverage.read_coverage(context.conn)

    gaps: Page = (
        Select("knowledge_gap")
        .columns(
            "id",
            "kind",
            "description",
            "why_it_matters",
            "status",
            "zone",
            "evidence",
            "confidence",
            "route_id",
            "step_role_id",
            "compartment_id",
        )
        .where("status = ?", "open")
        .order_by("kind", "id")
        .page(context.conn, limit=limit)
    )
    unevidenced: Page = (
        Select("assertion_level")
        .columns("assertion_id", "n_evidence", "derived_reason")
        .where("derived_reason = ?", "no_evidence")
        .order_by("assertion_id")
        .page(context.conn, limit=limit)
    )

    never_looked = [e for e in read.entities if e.state == "never_populated"]
    awaiting = [e for e in read.entities if e.state == "awaiting_curation"]
    unrenderable = [p for p in read.pages if not p.renderable]

    data = {
        "recorded_knowledge_gaps": gaps.as_json(),
        "entities_never_populated": [e.as_json() for e in never_looked],
        "entities_awaiting_curation": [e.as_json() for e in awaiting],
        "pages_with_nothing_to_render": [p.as_json() for p in unrenderable],
        "assertions_with_no_evidence": unevidenced.as_json(),
    }

    absences = tuple(
        _absent(
            str(row["description"]),
            Absence.NOT_RECORDED,
            zone=Zone(str(row["zone"])),
            detail=str(row["why_it_matters"] or "no rationale recorded"),
        )
        for row in gaps
    ) + tuple(
        _absent(
            f"the atlas holds no {entity.label} and none has been proposed",
            Absence.NOT_RECORDED,
            detail=entity.note,
        )
        for entity in never_looked
    )

    if not gaps.rows and not never_looked:
        absences = absences + (
            _absent(
                "no absence of either kind is recorded",
                Absence.NOT_RECORDED,
                detail="every entity has rows and no knowledge gap is open. That is a statement "
                "about this atlas, not about the field.",
            ),
        )

    return Result(
        data=data,
        zone=None,
        zone_note="each knowledge gap carries its own `zone`; the entity counts span all zones",
        absences=absences,
        caveats=(
            '"no study in this atlas reports X" is a statement about this corpus. It is not '
            '"X is not the case", and a sentence built from it must say which one it means.',
            "an entity in `entities_never_populated` has had nothing proposed for it, which is "
            "'never looked' -- the weakest possible absence and the easiest to overstate",
            "the literature corpus is screened for isobutanol in yeast; absence of a topic "
            "outside that scope says nothing at all",
        ),
    )


def _conflicts(context: Context, args: Mapping[str, Any]) -> Result:
    """Recorded conflicts, and the assertions the evidence view refuses to grade because of one.

    PLAN.md O.2.5: conflicts are surfaced, not averaged. Nothing here resolves one -- resolving a
    conflict is a curator act that PLAN.md L.5 forbids an agent outright, and there is
    deliberately no tool for it.
    """
    limit = _integer(args, "limit", default=50, low=1, high=200)
    open_only = _flag(args, "open_only", default=False)

    query = Select("conflict").columns(
        "id",
        "kind",
        "context_difference",
        "status",
        "resolution_note",
        "curator",
        "created_at",
        "zone",
    )
    if open_only:
        query = query.where("status = ?", "open")
    rows: Page = query.order_by("created_at", "id").page(context.conn, limit=limit)

    ids = [str(row["id"]) for row in rows]
    members: Page = (
        Select("conflict_member")
        .columns("conflict_id", "assertion_id")
        .where_in("conflict_id", ids)
        .order_by("conflict_id", "assertion_id")
        .page(context.conn, limit=limit * 8)
    )
    by_conflict: dict[str, list[str]] = {}
    for member in members:
        by_conflict.setdefault(str(member["conflict_id"]), []).append(str(member["assertion_id"]))

    discordant: Page = (
        Select("assertion_level")
        .columns("assertion_id", "n_direct", "n_evidence", "derived_reason")
        .where("derived_reason = ?", "direct_evidence_discordant")
        .order_by("assertion_id")
        .page(context.conn, limit=limit)
    )

    conflict_rows = rows.dicts()
    for row in conflict_rows:
        row["members"] = by_conflict.get(str(row["id"]), [])
        row["zone_display"] = Zone(str(row["zone"])).display

    data = {
        "conflicts": {**rows.as_json(), "rows": conflict_rows},
        "assertions_ungraded_by_discordance": discordant.as_json(),
        "totals": {
            "conflict_rows": len(conflict_rows),
            "open": sum(1 for row in conflict_rows if row["status"] == "open"),
            "ungraded_by_discordance": len(discordant.rows),
        },
    }

    absences: list[dict[str, Any]] = []
    if not conflict_rows:
        absences.append(
            _absent(
                "no conflict row exists in the atlas",
                Absence.NOT_RECORDED,
                detail="no conflict has been proposed, found or ruled out. The honest reading is "
                "'never looked', which is not 'the literature agrees'.",
            )
        )

    return Result(
        data=data,
        zone=None,
        zone_note="each conflict row carries its own `zone`",
        conflicts=tuple(
            {
                "kind": str(row["kind"]),
                "conflict_id": str(row["id"]),
                "status": str(row["status"]),
                "detail": str(row["context_difference"] or "no context difference recorded"),
                "members": row["members"],
            }
            for row in conflict_rows
        ),
        absences=tuple(absences),
        caveats=(
            "the commonest real resolution is `explained_by_context`, not a winner. A conflict "
            "with a `context_difference` is two findings under different conditions, and "
            "collapsing it to one number destroys the finding.",
            "nothing in this server resolves a conflict; PLAN.md L.5 forbids an agent from doing "
            "so and no tool here offers it",
        ),
    )


def _publications(context: Context, args: Mapping[str, Any]) -> Result:
    page = publications.search_publications(
        context.conn,
        query=_string(args, "query"),
        year=_integer(args, "year", default=0, low=0, high=2200) or None,
        family=_string(args, "family"),
        triage_state=_string(args, "triage_state"),
        readable_only=_flag(args, "readable_only"),
        limit=_integer(args, "limit", default=25, low=1, high=100),
        offset=_integer(args, "offset", default=0, low=0, high=100_000),
    )
    payload = page.as_json()
    zone_note = _with_zones(context.conn, "publication", payload["rows"])
    shape = publications.corpus_shape(context.conn)

    absences: list[dict[str, Any]] = []
    if not payload["rows"]:
        absences.append(
            _absent(
                "no publication in this atlas matches those facets",
                Absence.NOT_RECORDED,
                detail="the corpus is screened for isobutanol in yeast; a paper outside that "
                "scope was never sought, so its absence here is not evidence it does not exist",
            )
        )

    return Result(
        data={"page": payload, "corpus_shape": shape},
        zone=None,
        zone_note=zone_note,
        citations=tuple(
            _citation(str(row.get("title") or row["id"]), "publication", str(row["id"]))
            for row in payload["rows"]
        ),
        absences=tuple(absences),
        caveats=(
            "`corpus_shape` counts papers by how much of each the atlas actually holds; a paper "
            "the atlas knows of is not a paper the atlas has read",
            "a truncated page reports `truncated: true`; its `count` is a page size, not a total",
        ),
    )


def _publication(context: Context, args: Mapping[str, Any]) -> Result:
    publication_id = _string(args, "publication_id", required=True) or ""
    read = publications.read_publication(
        context.conn,
        publication_id,
        settings=context.settings,
        finding_limit=_integer(args, "finding_limit", default=100, low=1, high=1000),
    )
    if read is None:
        raise ToolError(f"no publication {publication_id!r}")

    payload = read.as_json()
    unresolved = read.unresolved_findings
    absences: list[dict[str, Any]] = []
    if not read.fulltext.is_readable:
        absences.append(
            _absent(
                f"the full text of {publication_id} is not readable in this atlas",
                Absence.NOT_RECORDED,
                zone=Zone.REPORTED,
                detail=f"availability: {read.fulltext.display}. Every finding below came from "
                "whatever text was available, and a section that was never read cannot have "
                "yielded a finding.",
            )
        )
    if not read.findings:
        absences.append(
            _absent(
                f"no finding has been extracted from {publication_id}",
                Absence.NOT_RECORDED,
                detail="the paper is in the corpus and nothing has been extracted from it; that "
                "is a statement about the pipeline, not about the paper",
            )
        )

    return Result(
        data=payload,
        zone=Zone.REPORTED,
        zone_note="the publication record is Zone R; each finding carries its own state",
        citations=({"claim": read.title.display, **read.citation.as_json()},),
        absences=tuple(absences),
        caveats=(
            f"{len(unresolved)} of {len(read.findings)} findings are still proposals awaiting a "
            "curator; an unresolved finding is not an atlas fact and must not be cited as one",
            "`quote_in_source` is the sentence as it appears in the stored text. Where it is "
            "absent the quote could not be located, and the finding is unverified against the "
            "source.",
        ),
    )


def _gene(context: Context, args: Mapping[str, Any]) -> Result:
    gene_id = _string(args, "gene_id", required=True) or ""
    read = genes.read_gene(context.conn, gene_id)
    if read is None:
        raise ToolError(
            f"no gene {gene_id!r}. Try the systematic name (YLR355C), the standard name (ILV5) "
            "or the atlas id; all three resolve."
        )
    payload = read.as_json()
    absences = tuple(
        _absent(
            f"the atlas holds no {section} for {gene_id}",
            Absence.NOT_RECORDED,
            detail=reason,
        )
        for section, reason in read.absent_sections.items()
    )
    return Result(
        data=payload,
        zone=None,
        zone_note="every field carries its own `zone`; annotations and reaction roles differ",
        citations=tuple(
            _citation(
                f"{gene_id} is annotated {annotation.get('term', {}).get('display', '?')}",
                "assertion",
                str(annotation.get("id") or gene_id),
            )
            for annotation in payload["annotations"]
            if isinstance(annotation, dict)
        ),
        absences=absences,
        caveats=(
            "`absent_sections` lists the parts of the Gene page this reader does not serve and "
            "why. A section missing from a page looks complete; a section reported absent is not.",
        ),
    )


def _routes(context: Context, args: Mapping[str, Any]) -> Result:
    route_id = _string(args, "route_id")
    if route_id:
        read = networks.read_route(context.conn, route_id)
        if read is None:
            raise ToolError(f"no route {route_id!r}")
        payload: dict[str, Any] = read.as_json()
        rows = [payload]
        zone_note = _with_zones(context.conn, "pathway_route", rows)
        payload = rows[0]
        data: dict[str, Any] = {"route": payload}
    else:
        order_by = _string(args, "order_by") or "score_evidence"
        try:
            page = networks.rank_routes(
                context.conn,
                cofactor_strategy=_string(args, "cofactor_strategy"),
                balance_status=_string(args, "balance_status"),
                order_by=order_by,
                limit=_integer(args, "limit", default=25, low=1, high=100),
                offset=_integer(args, "offset", default=0, low=0, high=100_000),
            )
        except (ValueError, QueryError) as error:
            raise ToolError(str(error)) from error
        listing = page.as_json()
        zone_note = _with_zones(context.conn, "pathway_route", listing["rows"])
        listing["ordered_by"] = order_by
        data = {"routes": listing, "overview": networks.read_overview(context.conn).as_json()}

    return Result(
        data=data,
        zone=None,
        zone_note=zone_note,
        caveats=(
            "routes are ordered by one *named* axis. No composite score exists: weighting the "
            "axes into one number is a scientific claim this layer does not hold.",
            "a score that was never computed is NULL, not zero. A NULL axis must not be ranked "
            "as a low value.",
            "an enumerated route is derived (Zone H or I). It is a possibility the model "
            "enumerated, not a construction anyone built.",
        ),
    )


def _measurements(context: Context, args: Mapping[str, Any]) -> Result:
    reads, page = records.list_measurements(
        context.conn,
        product_id=_string(args, "product_id"),
        strain_id=_string(args, "strain_id"),
        quantity_kind=_string(args, "quantity_kind"),
        publication_id=_string(args, "publication_id"),
        limit=_integer(args, "limit", default=50, low=1, high=200),
        offset=_integer(args, "offset", default=0, low=0, high=100_000),
    )
    rows = [read.as_json() for read in reads]
    zone_note = _with_zones(context.conn, "measurement", rows)

    citations: list[dict[str, Any]] = []
    uncited: list[str] = []
    for read in reads:
        source = read.publication_id.or_none()
        if source is None:
            uncited.append(read.id)
            continue
        citations.append(
            _citation(
                f"{read.quantity_kind} {read.quantity.display}",
                "measurement",
                read.id,
                locator=read.source_locator.or_none(),
            )
        )
        citations.append(
            _citation(f"{read.quantity_kind} {read.quantity.display}", "publication", str(source))
        )

    absences: list[dict[str, Any]] = []
    if not rows:
        absences.append(
            _absent(
                "no measurement in this atlas matches those facets",
                Absence.NOT_RECORDED,
                detail="the `measurement` table holds only values a curator promoted after "
                "reading the paper. An extracted value awaiting review is not here and is not a "
                "measurement the atlas holds.",
            )
        )
    if uncited:
        absences.append(
            _absent(
                f"{len(uncited)} measurement(s) name no publication",
                Absence.NOT_RECORDED,
                detail="PLAN.md O.2.1 requires a resolvable citation for every factual clause; "
                f"these rows cannot supply one and must not be quoted: {', '.join(uncited[:5])}",
            )
        )

    return Result(
        data={
            "rows": rows,
            "count": len(rows),
            "truncated": page.truncated,
            "limit": page.limit,
            "offset": page.offset,
        },
        zone=None,
        zone_note=(
            "each measurement carries both forms: `value_as_reported` is Zone R and immutable, "
            f"`value_si` is Zone H and derived. {zone_note}"
        ),
        citations=tuple(citations),
        absences=tuple(absences),
        caveats=(
            "`comparability_warnings` travels with every row and is the reason two numbers here "
            "may not be comparable. Quoting a row without its warnings loses the warning.",
            "a measurement with no `sample_id` is not attached to a condition context, so its "
            "comparability class cannot be computed",
        ),
    )


# ------------------------------------------------------------------------------- the registry


@dataclass(frozen=True)
class Tool:
    """One tool: its MCP definition, its access annotation, and the handler behind it."""

    name: str
    title: str
    description: str
    access: str
    input_schema: dict[str, Any]
    handler: Callable[[Context, Mapping[str, Any]], Result]

    def __post_init__(self) -> None:
        if self.access not in ACCESS_NOTE:
            raise ToolError(
                f"{self.name}: access must be one of {sorted(ACCESS_NOTE)}; there is no write "
                "annotation, because there is no write tool (PLAN.md L.4, L.5)"
            )

    def definition(self) -> dict[str, Any]:
        """The MCP `Tool` object a client sees in `tools/list`.

        `annotations` carries the spec's own hints. All four are stated rather than only
        `readOnlyHint`, because a client showing a consent prompt reads `destructiveHint` and
        `openWorldHint` too, and leaving them to a default is leaving the prompt to a default.
        `_meta` carries the READ/COMPUTE annotation PLAN.md L.4 asks for, under a namespaced key,
        since the spec reserves `_meta` for exactly this and defines no field of its own for it.
        """
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "_meta": {
                "fermdb/access": self.access,
                "fermdb/access_note": ACCESS_NOTE[self.access],
            },
        }


def _schema(properties: dict[str, Any], *, required: Sequence[str] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


_LIMIT = {"type": "integer", "description": "maximum rows to return"}
_OFFSET = {"type": "integer", "description": "rows to skip", "minimum": 0}


TOOLS: Final[tuple[Tool, ...]] = (
    Tool(
        name="atlas_overview",
        title="Atlas coverage",
        description=(
            "What the atlas holds and -- the useful half -- what it does not. Row counts per "
            "entity, each empty entity classified by WHY it is empty (never proposed / awaiting "
            "a curator / awaiting a promoter / no such table), and which interface pages have "
            "anything to render. Start here when you do not know what is in the atlas."
        ),
        access=ACCESS_READ,
        input_schema=_schema({}),
        handler=_overview,
    ),
    Tool(
        name="atlas_search",
        title="Search the atlas",
        description=(
            "Substring search across publications, genes, gene groups, strains, products, "
            "pathways, metabolites and reactions. Results are grouped by kind and never ranked "
            "across kinds. Returns identifiers to look up with a detail tool -- a hit is not a "
            "fact. Recall is substring-only: a synonym or a morphological variant will not match."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "substring to look for"},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "restrict to these kinds: publication, gene, gene_group, strain, "
                        "product, pathway, metabolite, reaction"
                    ),
                },
                "limit": {**_LIMIT, "minimum": 1, "maximum": 50},
            },
            required=("query",),
        ),
        handler=_search,
    ),
    Tool(
        name="atlas_route_answer",
        title="Which pathway engineering is feasible, transcript-backed and high-yielding?",
        description=(
            "The atlas's headline question, assembled from the route scores, the transcript "
            "coverage, and every isobutanol yield the corpus holds -- partitioned by who checked "
            "it and by host. Feasible, transcript-backed and high-yield are three independent "
            "columns and are never fused into one number. Per-step transcript support is NOT "
            "recomputed here (it needs on-disk matrices) and the result says so by name."
        ),
        access=ACCESS_COMPUTE,
        input_schema=_schema({"limit": {**_LIMIT, "minimum": 1, "maximum": 25}}),
        handler=_route_answer,
    ),
    Tool(
        name="atlas_evidence_chain",
        title="Evidence chain (PLAN.md J.5)",
        description=(
            "Walk an assertion from claim to evidence item to span to publication and report "
            "where the chain breaks, with the L1-L5 evidence level and its basis inline. Omit "
            "`assertion_id` to walk every active assertion. A level of NULL means either 'no "
            "evidence' or 'direct evidence on both sides, unresolved' -- the basis says which."
        ),
        access=ACCESS_COMPUTE,
        input_schema=_schema(
            {
                "assertion_id": {"type": "string", "description": "one assertion; omit for all"},
                "only_broken": {
                    "type": "boolean",
                    "description": "return only the chains that do not close",
                },
                "limit": {**_LIMIT, "minimum": 1, "maximum": 200},
            }
        ),
        handler=_evidence_chain,
    ),
    Tool(
        name="atlas_absences",
        title="What the atlas does not hold",
        description=(
            "Absence as a first-class answer (PLAN.md O.2.4): recorded knowledge gaps, entities "
            "nothing has ever been proposed for, entities whose proposals await a curator, "
            "pages with nothing to render, and assertions the evidence view grades NULL for "
            "want of any evidence. Use this before concluding that something is not the case."
        ),
        access=ACCESS_READ,
        input_schema=_schema({"limit": {**_LIMIT, "minimum": 1, "maximum": 200}}),
        handler=_absences,
    ),
    Tool(
        name="atlas_conflicts",
        title="Recorded conflicts",
        description=(
            "Conflicts the atlas records, their members and their status, plus the assertions "
            "`assertion_level` refuses to grade because direct evidence exists on both sides. "
            "Conflicts are surfaced, never averaged (PLAN.md O.2.5). Nothing here resolves one."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "open_only": {"type": "boolean", "description": "only unresolved conflicts"},
                "limit": {**_LIMIT, "minimum": 1, "maximum": 200},
            }
        ),
        handler=_conflicts,
    ),
    Tool(
        name="atlas_publications",
        title="Search publications",
        description=(
            "Publications matching year, screening family, triage state or a title substring, "
            "as a page that reports its own truncation, plus the corpus shape -- how many of the "
            "known papers the atlas can actually read."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "title substring"},
                "year": {"type": "integer", "description": "publication year"},
                "family": {"type": "string", "description": "screening family"},
                "triage_state": {"type": "string", "description": "e.g. included, excluded"},
                "readable_only": {
                    "type": "boolean",
                    "description": "only papers whose full text is stored and readable",
                },
                "limit": {**_LIMIT, "minimum": 1, "maximum": 100},
                "offset": _OFFSET,
            }
        ),
        handler=_publications,
    ),
    Tool(
        name="atlas_publication",
        title="One publication",
        description=(
            "One paper with every extracted finding and the sentence each came from, its "
            "full-text availability and licence, and its screening decisions. Findings still "
            "awaiting a curator are marked as such and are not atlas facts."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "publication_id": {"type": "string", "description": "atlas publication id"},
                "finding_limit": {**_LIMIT, "minimum": 1, "maximum": 1000},
            },
            required=("publication_id",),
        ),
        handler=_publication,
    ),
    Tool(
        name="atlas_gene",
        title="One gene",
        description=(
            "One gene by atlas id, systematic name (YLR355C) or standard name (ILV5): its "
            "identity, gene group, functional annotations, reaction roles and competing "
            "reactions -- with `absent_sections` naming the parts of the gene picture this atlas "
            "does not hold and why."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {"gene_id": {"type": "string", "description": "atlas id, systematic or standard name"}},
            required=("gene_id",),
        ),
        handler=_gene,
    ),
    Tool(
        name="atlas_routes",
        title="Enumerated pathway routes",
        description=(
            "Enumerated isobutanol routes ranked by one NAMED scoring axis (no composite score "
            "exists), or one route in full with its steps and every score it does and does not "
            "have. Pass `route_id` for the detail read. A route is derived, not built."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "route_id": {"type": "string", "description": "one route; omit to rank"},
                "cofactor_strategy": {"type": "string"},
                "balance_status": {"type": "string"},
                "order_by": {
                    "type": "string",
                    "description": "scoring axis, e.g. score_evidence or score_feasibility",
                },
                "limit": {**_LIMIT, "minimum": 1, "maximum": 100},
                "offset": _OFFSET,
            }
        ),
        handler=_routes,
    ),
    Tool(
        name="atlas_measurements",
        title="Curated measurements",
        description=(
            "Promoted measurements with both the reported and the harmonized form, their "
            "comparability warnings, and their quality flags. Only values a curator promoted "
            "after reading the paper are here; an extracted value awaiting review is not."
        ),
        access=ACCESS_READ,
        input_schema=_schema(
            {
                "product_id": {"type": "string"},
                "strain_id": {"type": "string"},
                "quantity_kind": {"type": "string", "description": "e.g. titer, yield"},
                "publication_id": {"type": "string"},
                "limit": {**_LIMIT, "minimum": 1, "maximum": 200},
                "offset": _OFFSET,
            }
        ),
        handler=_measurements,
    ),
)


def by_name(tools: Sequence[Tool] = TOOLS) -> dict[str, Tool]:
    """The registry keyed by name, checked for duplicates as it is built."""
    registry: dict[str, Tool] = {}
    for tool in tools:
        if tool.name in registry:
            raise ToolError(f"two tools are named {tool.name!r}")
        registry[tool.name] = tool
    return registry
