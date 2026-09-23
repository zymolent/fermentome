"""MCP over stdio, on the standard library: the framing, the handshake, and the read-only atlas.

PLAN.md L.4 asks for "a read-only MCP server over the same API the UI uses -- never a second
implementation -- so that Claude Code, Claude Desktop and other agents can query the atlas
directly". This module is the transport half of that; `tools.py` is the tools and `budget.py` is
the result budget L.4 also names.

**No SDK, deliberately.** `cli.py` at the root of this package explains the rule it follows:
argparse rather than Typer, "no dependency means `python -m fermdb.cli` works on a bare
interpreter". The same argument applies with more force here. MCP over stdio is JSON-RPC 2.0 in
newline-delimited JSON on stdin and stdout -- roughly two hundred lines of dispatch -- and taking
a dependency for it would mean the server, and every test of it, stops working in a clean
checkout with nothing installed. The suite must run there; `pyproject.toml` keeps three separate
optional extras precisely so that it can.

**Read-only is structural, not polite.** The connection is opened `file:...?mode=ro`, the same
way `api/deps.py` opens the one behind the HTTP layer and for the same stated reason: a mode that
makes a write *impossible* is a different guarantee from a policy that makes it *disallowed*. The
tool registry has no write tool and `tools.py` defines no write annotation for one to carry, so
the guarantee holds at three levels -- SQLite refuses it, no tool offers it, and no annotation
exists to describe it. `tests/test_mcp.py` asserts all three, and traces every statement every
tool issues to make sure the assertion is not vacuous.

**What is and is not certain about the wire format.** The framing (newline-delimited JSON-RPC
2.0 on stdio, nothing but protocol messages on stdout, logs to stderr), the `initialize` /
`notifications/initialized` / `tools/list` / `tools/call` sequence, the shape of a `Tool` and of
a `CallToolResult`, and the rule that tool *execution* failures come back as `isError: true`
rather than as a JSON-RPC error, are all pinned by the specification. Three things here are
judgement calls and are marked as such at their call sites: which unsolicited methods to answer
(`ping` is answered, `resources/*` and `prompts/*` are refused as not-found because this server
declares no such capability), the exact placement of the READ/COMPUTE annotation in `_meta`, and
the refusal of JSON-RPC batches, which the 2025-06-18 revision removed and earlier revisions
allowed. A client that needs batching will say so loudly rather than silently mis-parse.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TextIO

from ..config import Settings
from .budget import DEFAULT_BUDGET_CHARS, apply_budget
from .tools import TOOLS, Context, Tool, ToolError, by_name, repo_root

__all__ = [
    "LATEST_PROTOCOL_VERSION",
    "PROTOCOL_VERSIONS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "Server",
    "read_only_connection",
]

SERVER_NAME: Final[str] = "fermdb"
SERVER_VERSION: Final[str] = "0.0.1"

#: Revisions this server will speak, newest first. Negotiation echoes the client's choice when it
#: is one of these and otherwise offers the newest, which is what the specification prescribes:
#: the client then either accepts it or disconnects, rather than both sides guessing.
PROTOCOL_VERSIONS: Final[tuple[str, ...]] = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION: Final[str] = PROTOCOL_VERSIONS[0]

#: JSON-RPC 2.0's reserved codes, plus MCP's "not initialized". Named rather than inline, because
#: a bare -32602 at a call site is unreadable and mistyping one is silent.
PARSE_ERROR: Final[int] = -32700
INVALID_REQUEST: Final[int] = -32600
METHOD_NOT_FOUND: Final[int] = -32601
INVALID_PARAMS: Final[int] = -32602
INTERNAL_ERROR: Final[int] = -32603
NOT_INITIALIZED: Final[int] = -32002

#: Long enough to outlast a curation transaction in another process, short enough that a
#: genuinely stuck lock surfaces as an error rather than as a hung tool call. The same number
#: `api/deps.py` uses, for the same reason.
BUSY_TIMEOUT_MS: Final[int] = 60_000

#: Shown to the model once, at handshake, instead of being repeated in every response. PLAN.md
#: O.2 is the contract every result obeys, and a model that has read it here reads the `contract`
#: block correctly without the block having to re-explain itself 11 times per conversation.
INSTRUCTIONS: Final[str] = """\
The Fermentome atlas: an isobutanol strain-engineering decision-support database. Read-only.

Every tool result is `{"data": ..., "contract": {...}}`. The contract block is not decoration;
it is the part that makes the data quotable:

* `citations` -- every factual clause resolves to an assertion, a measurement or a publication.
  A clause you cannot cite from here must be removed from your answer, not softened.
* `evidence_levels` -- L1 to L5 with the basis that produced each. A level of `null` means
  either "no evidence" or "direct evidence on both sides, unresolved"; `basis` says which, and
  they are opposite states.
* `zone` -- R (reported by a source), H (harmonized by us), I (inferred). Zone I may not support
  a conclusion until a curator promotes it. Say "inferred" when you use it.
* `absences` -- "no study in this atlas reports X" is a real answer and a useful one. It is NOT
  "X is not the case". Report which one you mean.
* `conflicts` -- surfaced, never averaged. Two disagreeing findings are two findings.
* `caveats` -- carry these into the sentence you write, not into a footnote you drop.

A result may also carry `budget`, which reports what was trimmed to fit a character limit. If
`budget.applied` is true, every count under a listed path is the size of a page, not a total:
re-run with a narrower filter before quoting a number.

Nothing here writes. Promotion, evidence grading, conflict resolution and deletion are curator
acts performed by a named human through `fermdb curate` (PLAN.md L.5). Do not offer to do them.
"""


def read_only_connection(path: Path) -> sqlite3.Connection:
    """A connection that cannot write, because SQLite will not let it.

    `api/deps.py` does this for the HTTP layer and is not reused only because it is a FastAPI
    dependency -- importing it would drag an optional extra into a server whose entire point is
    that it runs on a bare interpreter. The four lines that matter are identical, including the
    decision *not* to pass `nolock=1`: the atlas is genuinely shared with curation processes, and
    skipping locking trades a clear error for a torn read.

    Opened per call rather than once per process. A stdio server is one client on one thread, so
    a shared connection would work -- but a per-call connection means a tool that somehow leaves
    a transaction open cannot poison the next tool, and against a local file it costs nothing.
    """
    if not path.exists():
        raise ToolError(
            f"no atlas at {path}. Set FERMDB_DB_FILE to a database file, or pass --atlas."
        )
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class Server:
    """One MCP session over one pair of streams.

    Holds no connection and no cursor between calls -- only the atlas path, the registry and the
    budget. State that outlives a call is state a later call can be surprised by, and the only
    state this server genuinely needs is whether `initialize` has happened.
    """

    def __init__(
        self,
        *,
        atlas: Path,
        settings: Settings | None = None,
        tools: tuple[Tool, ...] = TOOLS,
        budget_chars: int = DEFAULT_BUDGET_CHARS,
        root: Path | None = None,
    ) -> None:
        self.atlas = atlas
        self.settings = settings if settings is not None else Settings.load()
        self.tools = by_name(tools)
        self.budget_chars = budget_chars
        self.root = root if root is not None else repo_root()
        self.initialized = False
        self.negotiated_version = LATEST_PROTOCOL_VERSION

    # ------------------------------------------------------------------ the protocol methods

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        if isinstance(requested, str) and requested in PROTOCOL_VERSIONS:
            self.negotiated_version = requested
        else:
            # The spec's instruction for an unsupported version: answer with one this server
            # does speak and let the client decide, rather than failing the handshake outright.
            self.negotiated_version = LATEST_PROTOCOL_VERSION
        self.initialized = True
        return {
            "protocolVersion": self.negotiated_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "Fermentome atlas (read-only)",
                "version": SERVER_VERSION,
            },
            "instructions": INSTRUCTIONS + f"\nAtlas in use: {self.atlas}\n",
        }

    def _list_tools(self) -> dict[str, Any]:
        """Every tool in one page.

        `nextCursor` is omitted rather than sent as null: its absence is how the protocol says
        "that was all of them", and eleven tools will not grow into a paging problem. If it ever
        does, the cursor goes in here and not into a client's retry loop.
        """
        return {"tools": [tool.definition() for tool in self.tools.values()]}

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or name not in self.tools:
            raise ToolError(f"no tool named {name!r}; call tools/list for the available tools")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ToolError("'arguments' must be an object")

        tool = self.tools[name]
        conn = read_only_connection(self.atlas)
        try:
            result = tool.handler(
                Context(conn=conn, settings=self.settings, root=self.root), arguments
            )
        finally:
            conn.close()

        envelope = result.as_json()
        envelope["tool"] = name
        envelope["access"] = tool.access
        envelope["atlas"] = str(self.atlas)
        trimmed, budget = apply_budget(envelope, limit=self.budget_chars)
        trimmed["budget"] = budget.as_json()

        text = json.dumps(trimmed, ensure_ascii=True, indent=2, default=str)
        # Both forms, which is the spec's own backwards-compatibility recommendation: a client
        # that understands structured results reads `structuredContent`, and one that does not
        # reads the same JSON out of the text block rather than seeing an empty response.
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": trimmed,
            "isError": False,
        }

    # ------------------------------------------------------------------------- the dispatch

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """One message in, one response out -- or None, which means "say nothing".

        None is returned for notifications, and returning anything for one would be a protocol
        violation: a JSON-RPC notification has no id, so there is no id to answer it with.
        """
        if message.get("jsonrpc") != "2.0":
            return _error(message.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(message.get("id"), INVALID_REQUEST, "'method' must be a string")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message.get("id"), INVALID_PARAMS, "'params' must be an object")

        if "id" not in message:
            # A notification. `notifications/initialized` completes the handshake; `cancelled`
            # and `progress` are acknowledged by doing nothing, which is correct for a server
            # whose calls are synchronous and short. An unknown notification is ignored rather
            # than answered, because answering one is itself the error.
            return None

        request_id = message["id"]
        if method == "initialize":
            return _response(request_id, self._initialize(params))
        if method == "ping":
            # Answered before initialization on purpose: a client health-checking a server it
            # has just spawned should not have to complete a handshake to learn it is alive.
            return _response(request_id, {})
        if not self.initialized:
            return _error(
                request_id,
                NOT_INITIALIZED,
                f"{method!r} arrived before 'initialize'; complete the handshake first",
            )
        if method == "tools/list":
            return _response(request_id, self._list_tools())
        if method == "tools/call":
            try:
                return _response(request_id, self._call_tool(params))
            except ToolError as error:
                # A tool that could not answer is reported *inside* the result, not as a
                # JSON-RPC error. The spec is explicit about the difference and the reason is
                # practical: a protocol error is swallowed by the client, while `isError` reaches
                # the model, which is the party that can pick a different argument and retry.
                return _response(
                    request_id,
                    {
                        "content": [{"type": "text", "text": str(error)}],
                        "isError": True,
                    },
                )
            except Exception as error:  # noqa: BLE001 - one bad call must not end the session
                return _response(
                    request_id,
                    {
                        "content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}],
                        "isError": True,
                    },
                )
        return _error(
            request_id,
            METHOD_NOT_FOUND,
            f"{method!r} is not supported; this server declares only the 'tools' capability",
        )

    # ----------------------------------------------------------------------------- the loop

    def serve(self, stdin: TextIO, stdout: TextIO) -> int:
        """Read newline-delimited JSON-RPC until stdin closes.

        Nothing but protocol messages may reach `stdout`: a stray `print` anywhere in the import
        graph corrupts the stream and the client's error will name JSON, not the print. That is
        why `cli.py` sends its banner to stderr and why this loop never logs.
        """
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                self._write(stdout, _error(None, PARSE_ERROR, f"invalid JSON: {error}"))
                continue
            if isinstance(message, list):
                self._write(
                    stdout,
                    _error(
                        None,
                        INVALID_REQUEST,
                        "JSON-RPC batches are not supported; MCP removed them in revision "
                        "2025-06-18. Send one message per line.",
                    ),
                )
                continue
            if not isinstance(message, dict):
                self._write(stdout, _error(None, INVALID_REQUEST, "expected a JSON object"))
                continue
            try:
                response = self.handle(message)
            except Exception as error:  # noqa: BLE001 - the session outlives a bad message
                response = _error(
                    message.get("id"), INTERNAL_ERROR, f"{type(error).__name__}: {error}"
                )
            if response is not None:
                self._write(stdout, response)
        return 0

    @staticmethod
    def _write(stdout: TextIO, payload: Mapping[str, Any]) -> None:
        """One message, one line, flushed.

        `ensure_ascii=True` is not caution about the client, which is reading UTF-8 JSON either
        way -- it is caution about the pipe. On Windows an unconfigured stdout encodes with the
        locale codepage, and the atlas's display strings carry "≤" routinely, so the first
        conflicted measurement would otherwise kill the session with a UnicodeEncodeError.
        Escaping at the JSON layer makes the stream ASCII and the question moot.
        """
        stdout.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
        stdout.flush()


def serve_stdio(
    *, atlas: Path, budget_chars: int = DEFAULT_BUDGET_CHARS, settings: Settings | None = None
) -> int:
    """Run a session on the process's own stdin and stdout.

    Both streams are pinned to UTF-8 first. A Windows console or pipe otherwise picks the locale
    codepage, and the first "≤" in a payload ends the session with a UnicodeEncodeError that
    reads to the client as the server crashing. `_write` escapes to ASCII as well, which makes
    the output side doubly safe; the input side has only this.

    Reached through `getattr` rather than `hasattr` on purpose. `sys.stdin` is typed as `TextIO`,
    which declares no `reconfigure`, and whether a `hasattr` guard narrows it depends on the
    mypy version -- which would make the type gate pass or fail with the environment rather than
    with the code. `getattr` returns `Any` under every version.
    """
    for stream, options in (
        (sys.stdin, {"encoding": "utf-8"}),
        (sys.stdout, {"encoding": "utf-8", "newline": "\n"}),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(**options)
    server = Server(atlas=atlas, budget_chars=budget_chars, settings=settings)
    return server.serve(sys.stdin, sys.stdout)
