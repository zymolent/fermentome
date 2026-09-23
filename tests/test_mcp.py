"""Tests for `fermdb.mcp` -- the read-only MCP server (PLAN.md L.4).

Three groups of property, and each one is a rule from PLAN.md rather than a preference.

**Read-only is structural, not polite.** `tests/test_api.py` asserts this for the HTTP layer by
reading every route out of the OpenAPI schema and failing on any non-GET method, so that adding
a POST handler breaks the build rather than quietly shipping. The equivalent here is three
assertions, because an MCP server can leak a write in three places: the connection, the tool
surface, and the SQL a handler composes. So the connection is opened and an INSERT through it is
required to raise; every registered tool is required to carry a read annotation, of which there
are only two and neither is a write; and **every statement every tool issues is traced** and
required to be a SELECT or a PRAGMA. The last one is the only one of the three that can catch a
handler that starts writing tomorrow, and `test_the_write_guard_is_not_vacuous` is its guard on
the guard -- without it, a registry that had lost all its tools would pass.

**The answer contract (PLAN.md O.2).** A tool that returns a bare number with no zone, no
evidence level and no citation violates the architecture this repository exists to enforce, and
"it returns one anyway" is not something a reviewer reliably notices. So every tool is called and
its envelope checked for all five contract keys, absence is asserted to come back as an absence
rather than as an empty list, and Zone I is asserted to be a `zone` field rather than a wording.

**The wire format.** The handshake, the notification that carries no reply, the refusal of calls
that arrive before `initialize`, and the difference between a JSON-RPC error and a tool result
with `isError` -- all round-tripped through `Server.handle` and through the real `serve` loop
over a pair of string buffers, because a server that answers a unit test and not a stream is a
server that fails against a real client.
"""

from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.mcp import budget as B
from fermdb.mcp import tools as T
from fermdb.mcp.server import (
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    NOT_INITIALIZED,
    PARSE_ERROR,
    Server,
    read_only_connection,
)

PUB = "doi:10.9999/paper-a"
ASSERT = "YAA:ASSERT:fx"
CONFLICTED = "YAA:ASSERT:cx"
OPPOSED = "YAA:ASSERT:cy"

#: One of everything the tools read, small enough to hold in the head. Adapted from
#: `tests/test_traceability.py`'s fixture, which is where the assertion/evidence/span shape that
#: closes a J.5 chain is already worked out.
FIXTURE_SQL = f"""
INSERT INTO organism (id, name, zone, evidence, confidence)
    VALUES ('YAA:ORG:scer', 'Saccharomyces cerevisiae', 'R', 'fixture', 'low');
INSERT INTO product (id, name, tier, zone, evidence, confidence)
    VALUES ('YAA:PRODUCT:ibut', 'isobutanol', 'primary', 'R', 'fixture', 'low');
INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence)
    VALUES ('YAA:STRAIN:host', 'YAA:ORG:scer', 'HOST-1', 'engineered', 'R', 'x', 'low'),
           ('YAA:STRAIN:ctrl', 'YAA:ORG:scer', 'CTRL-1', 'laboratory', 'R', 'x', 'low');
INSERT INTO publication (id, title, year, zone, evidence, confidence)
    VALUES ('{PUB}', 'Isobutanol production in yeast', 2019, 'R', 'fixture', 'low');
INSERT INTO gene (id, organism_id, assembly_accession, systematic_name, standard_name,
                  zone, evidence, confidence)
    VALUES ('YAA:GENE:ilv5', 'YAA:ORG:scer', 'GCF_000146045.2', 'YLR355C', 'ILV5',
            'R', 'fixture', 'low');
INSERT INTO span (id, publication_id, char_start, char_end, quoted_text, record_path, zone)
    VALUES ('YAA:SPAN:a', '{PUB}', 10, 40, 'the titer reached 1.32 g/L', 'measurements[0]', 'R');
INSERT INTO measurement (id, strain_id, quantity_kind, product_id, publication_id,
                         value_as_reported, unit_as_reported, source_locator, zone, evidence,
                         confidence)
    VALUES ('YAA:MEAS:a', 'YAA:STRAIN:host', 'titer', 'YAA:PRODUCT:ibut', '{PUB}', 1.32,
            'g/L', 'Table 2', 'R', 'promoted', 'medium');

INSERT INTO assertion (id, subject_type, subject_id, predicate, object_type, object_id,
                       product_id, direction, created_by_kind, created_by, zone, evidence,
                       confidence)
    VALUES ('{ASSERT}', 'strain', 'YAA:STRAIN:host', 'affects_production_of', 'product',
            'YAA:PRODUCT:ibut', 'YAA:PRODUCT:ibut', 'increases', 'curator', 'kangkon', 'R',
            'fixture', 'medium'),
           ('{CONFLICTED}', 'strain', 'YAA:STRAIN:ctrl', 'affects_production_of', 'product',
            'YAA:PRODUCT:ibut', 'YAA:PRODUCT:ibut', 'increases', 'curator', 'kangkon', 'R',
            'fixture', 'medium'),
           ('{OPPOSED}', 'strain', 'YAA:STRAIN:ctrl', 'affects_production_of', 'product',
            'YAA:PRODUCT:ibut', 'YAA:PRODUCT:ibut', 'decreases', 'curator', 'kangkon', 'R',
            'fixture', 'medium');
INSERT INTO evidence_item (id, assertion_id, evidence_type, direction, independent_group,
                           publication_id, span_id, strain_id, control_strain_id,
                           measurement_id, zone, evidence, confidence)
    VALUES ('YAA:EV:fx', '{ASSERT}', 'direct_perturbation', 'increases', 'lab-1', '{PUB}',
            'YAA:SPAN:a', 'YAA:STRAIN:host', 'YAA:STRAIN:ctrl', 'YAA:MEAS:a', 'R', 'fixture',
            'medium'),
           ('YAA:EV:up', '{CONFLICTED}', 'direct_perturbation', 'increases', 'lab-1', '{PUB}',
            'YAA:SPAN:a', 'YAA:STRAIN:ctrl', 'YAA:STRAIN:host', 'YAA:MEAS:a', 'R', 'fixture',
            'medium'),
           ('YAA:EV:down', '{OPPOSED}', 'direct_perturbation', 'decreases', 'lab-2', '{PUB}',
            'YAA:SPAN:a', 'YAA:STRAIN:ctrl', 'YAA:STRAIN:host', 'YAA:MEAS:a', 'R', 'fixture',
            'medium');
INSERT INTO curation_event (id, curator, actor_kind, action, target_type, target_id, rationale,
                            created_at, zone)
    VALUES ('YAA:CUEV:1', 'kangkon', 'human', 'create', 'assertion', '{ASSERT}',
            'read the paper', '2026-09-22T10:00:00+00:00', 'R'),
           ('YAA:CUEV:2', 'kangkon', 'human', 'create', 'assertion', '{CONFLICTED}',
            'read both papers', '2026-09-22T10:05:00+00:00', 'R'),
           ('YAA:CUEV:3', 'kangkon', 'human', 'create', 'assertion', '{OPPOSED}',
            'the other paper disagrees', '2026-09-22T10:06:00+00:00', 'R');

INSERT INTO conflict (id, kind, context_difference, status, zone)
    VALUES ('YAA:CONFLICT:1', 'direction', 'aerobic vs micro-aerobic', 'open', 'R');
INSERT INTO conflict_member (conflict_id, assertion_id)
    VALUES ('YAA:CONFLICT:1', '{CONFLICTED}'), ('YAA:CONFLICT:1', '{OPPOSED}');

INSERT INTO knowledge_gap (id, kind, description, why_it_matters, status, zone, evidence,
                           confidence)
    VALUES ('YAA:GAP:1', 'never_attempted',
            'no study reports a cytosolic KARI in this background', 'it is the cheapest route',
            'open', 'I', 'enumeration', 'low');

INSERT INTO pathway_route (id, cofactor_strategy, balance_status, score_evidence,
                           score_feasibility, zone)
    VALUES ('YAA:ROUTE:1', 'nadph_cytosolic', 'pass', 0.8, 0.6, 'I'),
           ('YAA:ROUTE:2', 'nadh_mitochondrial', 'fail', 0.4, 0.9, 'I');
"""

#: Arguments that make each tool answer against the fixture. Every tool is exercised, because a
#: write guard that skips a tool is a write guard with a hole in it.
ARGUMENTS: dict[str, dict[str, Any]] = {
    "atlas_overview": {},
    "atlas_search": {"query": "isobutanol"},
    "atlas_route_answer": {"limit": 5},
    "atlas_evidence_chain": {},
    "atlas_absences": {},
    "atlas_conflicts": {},
    "atlas_publications": {},
    "atlas_publication": {"publication_id": PUB},
    "atlas_gene": {"gene_id": "ILV5"},
    "atlas_routes": {},
    "atlas_measurements": {},
}


@pytest.fixture()
def atlas(tmp_path: Path) -> Path:
    """A file-backed atlas, because the server takes a path and opens it `mode=ro` itself."""
    path = tmp_path / "atlas.sqlite3"
    conn = open_db(path)
    try:
        conn.executescript(FIXTURE_SQL)
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture()
def server(atlas: Path) -> Server:
    instance = Server(atlas=atlas, settings=Settings.load())
    instance.handle(_request(1, "initialize", {"protocolVersion": LATEST_PROTOCOL_VERSION}))
    return instance


@pytest.fixture()
def writable(atlas: Path) -> Iterator[sqlite3.Connection]:
    conn = open_db(atlas)
    try:
        yield conn
    finally:
        conn.close()


def _request(request_id: Any, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _call(server: Server, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    response = server.handle(
        _request(
            9,
            "tools/call",
            {
                "name": name,
                "arguments": arguments if arguments is not None else ARGUMENTS[name],
            },
        )
    )
    assert response is not None
    result: dict[str, Any] = response["result"]
    return result


def _envelope(server: Server, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _call(server, name, arguments)
    assert result["isError"] is False, result["content"]
    payload: dict[str, Any] = result["structuredContent"]
    return payload


# ------------------------------------------------------------------ read-only, three ways


def test_the_connection_cannot_write(atlas: Path) -> None:
    """`mode=ro` at the SQLite level, exactly as `api/deps.py` opens the HTTP layer's.

    A mode that makes a write *impossible* is a different guarantee from a policy that makes it
    *disallowed*: a bug in a handler surfaces here as an exception rather than as a silent edit
    to an atlas that is genuinely shared with curation processes.
    """
    conn = read_only_connection(atlas)
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            conn.execute(
                "INSERT INTO product (id, name, zone, evidence, confidence) "
                "VALUES ('x', 'x', 'R', 'x', 'low')"
            )
        assert "readonly" in str(caught.value).lower()
    finally:
        conn.close()


def test_no_tool_is_annotated_as_a_write() -> None:
    """PLAN.md L.4 annotates tools READ / COMPUTE / WRITE. This server defines no WRITE.

    The absence of the constant is the enforcement. A flag that defaults to off can be flipped in
    an edit nobody reads; an annotation that was never defined has to be *added*, in a diff a
    reviewer sees, before a write tool can even be registered.
    """
    assert not hasattr(T, "ACCESS_WRITE")
    assert set(T.ACCESS_NOTE) == {T.ACCESS_READ, T.ACCESS_COMPUTE}
    for tool in T.TOOLS:
        assert tool.access in {T.ACCESS_READ, T.ACCESS_COMPUTE}, tool.name
        annotations = tool.definition()["annotations"]
        assert annotations["readOnlyHint"] is True, tool.name
        assert annotations["destructiveHint"] is False, tool.name
        assert tool.definition()["_meta"]["fermdb/access"] == tool.access


def test_no_tool_issues_a_statement_that_writes(writable: sqlite3.Connection) -> None:
    """Every statement every tool issues, traced, on a connection that *would* let it through.

    Deliberately a writable connection. Tracing a `mode=ro` connection would prove only that
    SQLite refuses writes, which the test above already establishes; what is unproven until here
    is that no handler ever *composes* one. A handler that starts issuing an UPDATE fails here
    even while the read-only connection is quietly swallowing it in production.
    """
    statements: list[str] = []
    writable.set_trace_callback(statements.append)
    context = T.Context(conn=writable, settings=Settings.load(), root=T.repo_root())
    try:
        for tool in T.TOOLS:
            tool.handler(context, ARGUMENTS[tool.name])
    finally:
        writable.set_trace_callback(None)

    assert statements, "the trace caught nothing, so this test would pass vacuously"
    writes = [
        sql
        for sql in statements
        if sql.lstrip()
        .upper()
        .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"))
    ]
    assert writes == [], f"a tool composed a write: {writes}"


def test_the_write_guard_is_not_vacuous() -> None:
    """The guard above must be looking at the real tool surface, not at an empty registry.

    Without this, deleting every tool would make it pass -- the same failure `test_api.py`'s
    `test_the_guard_can_actually_see_the_endpoints` exists to prevent.
    """
    names = {tool.name for tool in T.TOOLS}
    assert len(names) >= 8, f"only {len(names)} tools visible; the guard has gone blind"
    for expected in (
        "atlas_search",
        "atlas_route_answer",
        "atlas_evidence_chain",
        "atlas_absences",
        "atlas_conflicts",
    ):
        assert expected in names
    assert names == set(ARGUMENTS), "every tool must be exercised by the write guard"


def test_no_tool_offers_anything_PLAN_L5_forbids() -> None:
    """L.5's list, checked against the tool surface by name.

    Not a test of behaviour -- there is no promote handler to call -- but of vocabulary. A tool
    named `promote_proposal` would be caught by a reviewer; one named `atlas_apply` might not.
    """
    forbidden = ("promote", "accept", "reject", "resolve", "delete", "write", "set", "assign")
    for tool in T.TOOLS:
        assert not any(word in tool.name for word in forbidden), tool.name


# ------------------------------------------------------------------ the O.2 answer contract


def test_every_tool_result_carries_the_whole_contract(server: Server) -> None:
    """All five O.2 keys on every response, the empty ones included.

    An empty `conflicts` list is a claim -- this was looked at and there were none. A missing
    `conflicts` key is not a claim at all, and a model cannot tell the second from an oversight.
    """
    for tool in T.TOOLS:
        envelope = _envelope(server, tool.name)
        contract = envelope["contract"]
        for key in ("zone", "citations", "absences", "conflicts", "evidence_levels", "caveats"):
            assert key in contract, f"{tool.name} dropped {key}"
        assert contract["zone"] is not None or contract["zone_note"], tool.name
        assert envelope["tool"] == tool.name
        assert envelope["access"] == tool.access
        assert envelope["budget"]["limit_chars"] > 0


def test_a_result_with_no_zone_must_say_why() -> None:
    """O.2.3 asks for a zone *field*. An unmarked zone is indistinguishable from unmarked Zone I.

    So a `Result` refuses to be built with neither a zone nor an explanation, which moves the
    failure to where the tool is written rather than to where its answer is read.
    """
    with pytest.raises(T.ToolError):
        T.Result(data={}, zone=None)
    assert T.Result(data={}, zone=None, zone_note="counts span every zone").as_json()


def test_zone_i_is_marked_as_inference_not_formatted_as_one(server: Server) -> None:
    """The enumerated routes are Zone I, and the envelope says so as data."""
    envelope = _envelope(server, "atlas_routes")
    rows = envelope["data"]["routes"]["rows"]
    assert rows, "the fixture has routes; without them this asserts nothing"
    for row in rows:
        assert row["zone"] == "I"
        assert row["zone_display"] == "inferred"


def test_a_measurement_carries_a_resolvable_citation(server: Server) -> None:
    """O.2.1: every factual clause resolves to an assertion, a measurement or a publication."""
    envelope = _envelope(server, "atlas_measurements")
    assert envelope["data"]["rows"], "the fixture has a measurement"
    kinds = {citation["source_kind"] for citation in envelope["contract"]["citations"]}
    assert kinds == {"measurement", "publication"}
    for citation in envelope["contract"]["citations"]:
        assert citation["source_id"]
        assert citation["claim"]


def test_an_uncited_measurement_is_reported_as_uncitable(
    server: Server, writable: sqlite3.Connection
) -> None:
    """A row that cannot supply a citation is named, not quietly served beside rows that can."""
    writable.execute("UPDATE measurement SET publication_id = NULL WHERE id = 'YAA:MEAS:a'")
    writable.commit()
    envelope = _envelope(server, "atlas_measurements")
    claims = [absence["claim"] for absence in envelope["contract"]["absences"]]
    assert any("name no publication" in claim for claim in claims), claims


def test_the_evidence_level_is_inline_on_the_row_and_in_the_contract(server: Server) -> None:
    """O.2.2. On the row too, because a model reading rows may never reach the envelope."""
    envelope = _envelope(server, "atlas_evidence_chain", {"assertion_id": ASSERT})
    (row,) = envelope["data"]["assertions"]
    assert row["evidence_level"]["level"] == "L1"
    assert row["evidence_level"]["basis"] == "direct_evidence"
    assert envelope["contract"]["evidence_levels"][0]["assertion_id"] == ASSERT


def test_a_conflict_is_surfaced_rather_than_graded_away(server: Server) -> None:
    """Direct evidence on both sides: the view declines to grade, and the tool says why.

    `null` here means "unresolved dispute", and a `null` from `no_evidence` means "nothing is
    known". They are opposite states arriving as the same NULL, so the basis travels with it.
    """
    envelope = _envelope(server, "atlas_evidence_chain", {"assertion_id": CONFLICTED})
    (row,) = envelope["data"]["assertions"]
    assert row["evidence_level"]["level"] is None
    assert row["evidence_level"]["basis"] == "direct_evidence_discordant"
    assert row["evidence_level"]["is_conflicted"] is True
    assert row["evidence_level"]["display"] == "conflicted"
    kinds = {conflict["kind"] for conflict in envelope["contract"]["conflicts"]}
    assert "direct_evidence_discordant" in kinds


def test_recorded_conflicts_are_listed_with_their_members(server: Server) -> None:
    envelope = _envelope(server, "atlas_conflicts")
    (row,) = envelope["data"]["conflicts"]["rows"]
    assert row["status"] == "open"
    assert sorted(row["members"]) == sorted([CONFLICTED, OPPOSED])
    assert envelope["data"]["totals"]["ungraded_by_discordance"] == 2


def test_absence_is_reported_as_absence_not_as_an_empty_list(server: Server) -> None:
    """O.2.4. "No study in this atlas reports X" is a result, and it has to look like one."""
    envelope = _envelope(server, "atlas_measurements", {"strain_id": "YAA:STRAIN:nobody"})
    assert envelope["data"]["rows"] == []
    (absence,) = [a for a in envelope["contract"]["absences"] if "no measurement" in a["claim"]]
    # The `Value.as_json()` trick: an absence has no `value` key at all, so a consumer reaching
    # for one gets a visible hole rather than a null that renders like a real missing datum.
    assert "value" not in absence
    assert absence["absent"] == "not_recorded"
    assert absence["absent_because"]


def test_the_absences_tool_keeps_four_kinds_of_absence_apart(server: Server) -> None:
    """A recorded gap, a never-populated entity, a curation backlog and an unevidenced claim.

    They send you to four different places -- a scientist, an acquisition run, a curator and the
    J.5 walk -- so collapsing them into one "missing" list would lose the only actionable part.
    """
    envelope = _envelope(server, "atlas_absences")
    data = envelope["data"]
    assert data["recorded_knowledge_gaps"]["rows"][0]["kind"] == "never_attempted"
    assert data["recorded_knowledge_gaps"]["rows"][0]["zone"] == "I"
    assert {e["entity"] for e in data["entities_never_populated"]}
    assert any("never looked" in caveat for caveat in envelope["contract"]["caveats"])


def test_an_empty_atlas_says_never_looked_rather_than_nothing_exists(tmp_path: Path) -> None:
    """The distinction the whole contract turns on, at the one moment it is easiest to lose."""
    path = tmp_path / "empty.sqlite3"
    open_db(path).close()
    instance = Server(atlas=path, settings=Settings.load())
    instance.handle(_request(1, "initialize", {}))
    envelope = _envelope(instance, "atlas_conflicts")
    (absence,) = envelope["contract"]["absences"]
    assert "never looked" in absence["detail"]

    chain = _envelope(instance, "atlas_evidence_chain")
    assert chain["data"]["summary"]["vacuous"] is True
    assert chain["contract"]["absences"], "a vacuous walk is not a clean bill of health"


def test_the_route_answer_declares_what_it_did_not_compute(server: Server) -> None:
    """The step-level transcript support needs on-disk matrices this server does not read.

    Reporting no routes and letting the renderer say "no route has any transcript evidence" would
    be a false statement about the atlas produced by a true statement about this process, which
    is the worst available direction for the error to point.
    """
    envelope = _envelope(server, "atlas_route_answer")
    support = envelope["data"]["route_transcript_support"]
    assert support["computed"] is False
    assert "ops/answer.py" in support["reason"]
    assert envelope["data"]["routes_by_stored_evidence_score"]["rows"], "the stored ranking serves"


def test_the_route_answer_never_fuses_the_three_questions(server: Server) -> None:
    """Feasible, transcript-backed and high-yield stay three columns, and hosts stay labelled."""
    envelope = _envelope(server, "atlas_route_answer")
    yields = envelope["data"]["yields"]
    assert set(yields) >= {
        "s_cerevisiae_curator_reviewed",
        "s_cerevisiae_agent_harvested_not_yet_reviewed",
        "other_hosts",
    }
    assert "three independent" in envelope["data"]["three_separate_questions"]
    assert any("not flux" in caveat for caveat in envelope["contract"]["caveats"])


def test_a_search_hit_is_marked_as_an_identifier_and_zone_marked_where_possible(
    server: Server,
) -> None:
    envelope = _envelope(server, "atlas_search")
    groups = envelope["data"]["groups"]
    publications = next(group for group in groups if group["kind"] == "publication")
    assert publications["rows"][0]["zone"] == "R"
    assert any("not a fact" in caveat for caveat in envelope["contract"]["caveats"])


def test_a_publication_reports_an_unreadable_full_text_as_an_absence(server: Server) -> None:
    envelope = _envelope(server, "atlas_publication")
    claims = [absence["claim"] for absence in envelope["contract"]["absences"]]
    assert any("full text" in claim for claim in claims), claims
    assert envelope["contract"]["zone"] == "R"
    assert envelope["contract"]["citations"][0]["source_id"] == PUB


# ------------------------------------------------------------------------ the wire format


def test_initialize_echoes_a_version_it_speaks(atlas: Path) -> None:
    instance = Server(atlas=atlas, settings=Settings.load())
    response = instance.handle(
        _request(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    )
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "fermdb"
    assert "PLAN.md O.2" not in result["instructions"]  # it states the rules, not the citation
    assert "absences" in result["instructions"]


def test_an_unknown_protocol_version_gets_one_this_server_speaks(atlas: Path) -> None:
    """The spec's instruction: offer a version you do support and let the client decide."""
    instance = Server(atlas=atlas, settings=Settings.load())
    response = instance.handle(_request(1, "initialize", {"protocolVersion": "1999-01-01"}))
    assert response is not None
    assert response["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_a_notification_gets_no_reply(server: Server) -> None:
    """A JSON-RPC notification has no id, so there is no id to answer it with."""
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled"}) is None


def test_a_call_before_initialize_is_refused(atlas: Path) -> None:
    instance = Server(atlas=atlas, settings=Settings.load())
    response = instance.handle(_request(2, "tools/list"))
    assert response is not None
    assert response["error"]["code"] == NOT_INITIALIZED


def test_ping_is_answered_before_the_handshake(atlas: Path) -> None:
    """A client health-checking a server it just spawned should not need a handshake first."""
    instance = Server(atlas=atlas, settings=Settings.load())
    response = instance.handle(_request(2, "ping"))
    assert response is not None
    assert response["result"] == {}


def test_tools_list_is_a_valid_tool_surface(server: Server) -> None:
    response = server.handle(_request(3, "tools/list"))
    assert response is not None
    listed = response["result"]["tools"]
    assert len(listed) == len(T.TOOLS)
    assert "nextCursor" not in response["result"]
    for definition in listed:
        assert definition["name"] and definition["description"]
        schema = definition["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_an_unknown_method_is_a_jsonrpc_error(server: Server) -> None:
    response = server.handle(_request(4, "resources/list"))
    assert response is not None
    assert response["error"]["code"] == METHOD_NOT_FOUND


def test_an_unknown_tool_is_a_failed_call_not_a_protocol_error(server: Server) -> None:
    """The spec's split: a *tool* failure reaches the model, which is the party that can retry.

    A JSON-RPC error is handled by the client library and the model never learns the tool name
    was wrong, so it cannot correct itself.
    """
    result = _call(server, "atlas_nonexistent", {})
    assert result["isError"] is True
    assert "tools/list" in result["content"][0]["text"]


def test_a_bad_argument_fails_the_call_rather_than_returning_nothing(server: Server) -> None:
    """An empty result would tell the model "there is nothing", which it would then report."""
    result = _call(server, "atlas_publication", {"publication_id": "doi:10.9999/absent"})
    assert result["isError"] is True
    assert "no publication" in result["content"][0]["text"]

    bad_limit = _call(server, "atlas_search", {"query": "x", "limit": 9_000})
    assert bad_limit["isError"] is True


def test_a_result_carries_both_the_text_and_the_structured_form(server: Server) -> None:
    """The spec's backwards-compatibility recommendation, and both must be the same payload."""
    result = _call(server, "atlas_overview")
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_the_serve_loop_round_trips_a_real_stream(atlas: Path) -> None:
    """Handshake, notification, list, call -- through the loop, one JSON object per line."""
    instance = Server(atlas=atlas, settings=Settings.load())
    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps(_request(1, "initialize", {"protocolVersion": "2025-06-18"})),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                "",
                json.dumps(_request(2, "tools/list")),
                json.dumps(_request(3, "tools/call", {"name": "atlas_overview"})),
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    assert instance.serve(stdin, stdout) == 0

    lines = [line for line in stdout.getvalue().splitlines() if line]
    assert len(lines) == 3, "the notification and the blank line must produce no output"
    replies = [json.loads(line) for line in lines]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[2]["result"]["isError"] is False


def test_the_loop_survives_malformed_input(atlas: Path) -> None:
    """One bad message must not end the session: a client that sends one sends a good one next."""
    instance = Server(atlas=atlas, settings=Settings.load())
    stdin = io.StringIO(
        "not json\n"
        + json.dumps([_request(1, "ping")])
        + "\n"
        + json.dumps(_request(2, "ping"))
        + "\n"
    )
    stdout = io.StringIO()
    instance.serve(stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
    assert replies[0]["error"]["code"] == PARSE_ERROR
    assert replies[1]["error"]["code"] == INVALID_REQUEST
    assert "batches are not supported" in replies[1]["error"]["message"]
    assert replies[2]["result"] == {}


def test_nothing_but_protocol_messages_reach_stdout(atlas: Path) -> None:
    """Every line on stdout must parse as one JSON-RPC message.

    A stray `print` anywhere in the import graph corrupts the stream, and the client's error
    names JSON rather than the print -- which is a long afternoon.
    """
    instance = Server(atlas=atlas, settings=Settings.load())
    stdin = io.StringIO(json.dumps(_request(1, "initialize", {})) + "\n")
    stdout = io.StringIO()
    instance.serve(stdin, stdout)
    for line in stdout.getvalue().splitlines():
        assert json.loads(line)["jsonrpc"] == "2.0"


def test_the_wire_is_ascii_so_a_windows_pipe_cannot_break_the_session(atlas: Path) -> None:
    """The atlas's display strings carry "≤"; an unconfigured stdout would encode as cp1252."""
    stdout = io.StringIO()
    Server._write(stdout, {"jsonrpc": "2.0", "id": 1, "result": {"note": "≤ 2.09 g/L"}})
    assert stdout.getvalue().isascii()
    assert json.loads(stdout.getvalue())["result"]["note"] == "≤ 2.09 g/L"


# --------------------------------------------------------------------------- the result budget


def test_a_payload_within_budget_is_untouched() -> None:
    payload = {"rows": [1, 2, 3]}
    trimmed, report = B.apply_budget(payload, limit=10_000)
    assert trimmed == payload
    assert report.applied is False
    assert report.cuts == ()


def test_the_budget_trims_the_largest_list_and_names_it() -> None:
    """Largest first: the big list is where the characters are, the small one is the meaning."""
    payload = {
        "caveats": ["one", "two", "three", "four"],
        "data": {"rows": [{"id": f"row-{n}", "text": "x" * 80} for n in range(200)]},
    }
    trimmed, report = B.apply_budget(payload, limit=2_000)
    assert report.applied is True
    assert B.measure(trimmed) <= 2_000
    assert trimmed["caveats"] == payload["caveats"], "the small list must survive"
    (cut,) = report.cuts
    assert cut.path == "data.rows"
    assert cut.held == 200
    assert cut.kept < 200
    assert cut.dropped == 200 - cut.kept


def test_the_budget_says_so_in_the_response(server: Server) -> None:
    """A silent truncation makes the model report a count that is really the budget."""
    response = server.handle(_request(9, "tools/call", {"name": "atlas_overview", "arguments": {}}))
    assert response is not None
    envelope = response["result"]["structuredContent"]
    assert envelope["budget"]["applied"] is False

    tiny = Server(atlas=server.atlas, settings=server.settings, budget_chars=600)
    tiny.handle(_request(1, "initialize", {}))
    small = _envelope(tiny, "atlas_overview")
    assert small["budget"]["applied"] is True
    assert small["budget"]["cuts"]
    assert "page, not the size of the atlas" in small["budget"]["warning"]


def test_between_comparable_lists_the_rows_are_cut_and_the_citations_kept() -> None:
    """Trimming rows leaves the rest cited; trimming citations leaves the rest uncited.

    Regression, and a real one: the first run of `atlas_route_answer` against the live atlas
    dropped 107 of 142 citations, because the citation list honestly was the biggest list in the
    payload.
    """
    payload = {
        "data": {"rows": [{"id": n, "pad": "y" * 60} for n in range(300)]},
        "contract": {"citations": [{"source_id": f"doi:{n}", "pad": "z" * 60} for n in range(300)]},
    }
    # The citation list is the *larger* of the two here, and is still not the one that is cut.
    assert B.measure(payload["contract"]["citations"]) > B.measure(payload["data"]["rows"])
    trimmed, report = B.apply_budget(payload, limit=45_000)
    assert report.applied is True
    assert [cut.path for cut in report.cuts] == ["data.rows"]
    assert len(trimmed["contract"]["citations"]) == 300


def test_a_runaway_contract_list_is_still_cut() -> None:
    """The preference is a tie-break, not an exemption.

    Preferring `data` absolutely was the second wrong answer: it stripped a two-row route ranking
    to nothing while a citation list forty times its size sat untouched, because that tiny list
    was the only `data` list left.
    """
    payload = {
        "data": {"rows": [{"id": n} for n in range(2)]},
        "contract": {"citations": [{"source_id": f"doi:{n}", "pad": "z" * 60} for n in range(400)]},
    }
    trimmed, report = B.apply_budget(payload, limit=4_000)
    assert [cut.path for cut in report.cuts] == ["contract.citations"]
    assert len(trimmed["data"]["rows"]) == 2, "the small list a reader actually needs survives"


def test_a_trimmed_list_keeps_its_shape() -> None:
    """The record of the cut lives beside the payload, never spliced into the list as a marker.

    A sentinel string appended to a list of row objects changes that list's type, and a consumer
    iterating it hits a string where it expected a mapping.
    """
    payload = {"rows": [{"id": n} for n in range(500)]}
    trimmed, _ = B.apply_budget(payload, limit=1_000)
    assert all(isinstance(row, dict) for row in trimmed["rows"])


def test_the_budget_does_not_mutate_what_it_was_given() -> None:
    payload = {"rows": [{"id": n} for n in range(400)]}
    B.apply_budget(payload, limit=800)
    assert len(payload["rows"]) == 400
