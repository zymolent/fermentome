"""The read-only MCP server (PLAN.md L.4).

`fermdb mcp` speaks JSON-RPC 2.0 over stdin and stdout so Claude Code, Claude Desktop and other
agents can query the atlas directly, through the same query-layer readers the web interface uses.

Three modules, one job each:

* :mod:`fermdb.mcp.server` -- the framing, the handshake and the read-only connection.
* :mod:`fermdb.mcp.tools` -- the tools, and the PLAN.md O.2 answer contract every result carries.
* :mod:`fermdb.mcp.budget` -- the character budget, and the report of what it cut.

There is no write path here and no way to add one without it being obvious: `tools.py` defines a
READ and a COMPUTE access annotation and no write annotation at all, the connection is opened
`mode=ro`, and `tests/test_mcp.py` traces every statement every tool issues to prove both.
"""

from __future__ import annotations

from .budget import DEFAULT_BUDGET_CHARS, Budget, apply_budget
from .server import PROTOCOL_VERSIONS, Server, read_only_connection, serve_stdio
from .tools import ACCESS_COMPUTE, ACCESS_READ, TOOLS, Context, Result, Tool, ToolError

__all__ = [
    "ACCESS_COMPUTE",
    "ACCESS_READ",
    "DEFAULT_BUDGET_CHARS",
    "PROTOCOL_VERSIONS",
    "TOOLS",
    "Budget",
    "Context",
    "Result",
    "Server",
    "Tool",
    "ToolError",
    "apply_budget",
    "read_only_connection",
    "serve_stdio",
]
