"""The result budget, and -- the half that matters -- the report of what it cut.

PLAN.md L.4 carries two features from `genome-db`'s MCP implementation, and this module is the
second of them:

    **A result budget that reports what it cut.** Large results are trimmed to a character
    budget, largest lists first, and the response says so -- because a silent truncation causes
    the model to report a count that is really the budget.

That failure mode is worth spelling out, because it is the one that makes a truncating server
actively worse than a failing one. A model handed 25 publications out of 1,400, with nothing in
the payload saying so, will write "the atlas holds 25 publications". The number is wrong, it is
wrong in the direction of confidence, and nothing downstream can tell. `Page` already solves this
for a single query -- it reports `truncated` per group, which is why `query/search.py` never
merges its groups. This module solves it for the *envelope*, where a payload assembled from
several readers can overflow a context window for reasons no single reader knows about.

Two decisions:

**Largest lists first.** Trimming proportionally across every list would shorten the four-element
caveat list that carries the reasoning as eagerly as the four-hundred-element row list that
carries the bulk. The big list is where the characters are and the small one is usually where the
meaning is, so the big one is cut first and cut repeatedly until the payload fits.

**The list is shortened; no marker is spliced into it.** A sentinel string appended to a list of
row objects changes that list's type, and a consumer iterating it hits a string where it expected
a mapping. The record of the cut lives in :class:`Budget`, beside the payload rather than inside
it, so the shape of a trimmed list is the shape of an untrimmed one.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["DEFAULT_BUDGET_CHARS", "Budget", "Cut", "apply_budget", "measure"]

#: Characters, not tokens. Roughly 6k tokens of JSON, which leaves room for a handful of calls in
#: one conversation without either party having to think about it. Overridable per run
#: (`fermdb mcp --budget-chars`), because the right number depends on the client's window and
#: this server cannot see it.
DEFAULT_BUDGET_CHARS: Final[int] = 24_000

#: A floor, so that a pathologically small budget cannot reduce every list to nothing and report
#: a payload that is technically within budget and carries no information at all.
MIN_BUDGET_CHARS: Final[int] = 512

#: Paths under this prefix are cut last. `tools.py` puts the citations, absences, conflicts,
#: evidence levels and caveats here, and those are what make the rows quotable -- see
#: :func:`apply_budget`.
CONTRACT_PREFIX: Final[str] = "contract"

#: How close to the largest list another list must be before the `data`-first preference applies
#: to it. A half rather than a tenth because the preference is a tie-break, not an exemption: a
#: contract list several times larger than anything else is still the right thing to cut.
COMPARABLE_FRACTION: Final[float] = 0.5


def measure(payload: Any) -> int:
    """How many characters this payload costs on the wire.

    Serialized the same way `server.py` serializes it -- `ensure_ascii=True` -- because the two
    must agree. A measurement taken with `ensure_ascii=False` under-counts every non-ASCII
    character by five sixths, and the atlas's display strings carry "≤" and "--" routinely.
    """
    return len(json.dumps(payload, ensure_ascii=True, default=str))


@dataclass(frozen=True)
class Cut:
    """One list that was shortened, named by where it sits in the payload."""

    path: str
    held: int
    kept: int

    @property
    def dropped(self) -> int:
        return self.held - self.kept

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "held": self.held,
            "kept": self.kept,
            "dropped": self.dropped,
            "note": (
                f"{self.dropped} of {self.held} entries at {self.path} were dropped to fit the "
                "budget; the kept count is a page, not a total"
            ),
        }


@dataclass(frozen=True)
class Budget:
    """What the budget was, what it cost, and what it cut. Always reported, even when empty."""

    limit: int
    chars_before: int
    chars_after: int
    cuts: tuple[Cut, ...] = ()

    @property
    def applied(self) -> bool:
        return bool(self.cuts)

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "limit_chars": self.limit,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "applied": self.applied,
            "cuts": [cut.as_json() for cut in self.cuts],
        }
        if self.applied:
            payload["warning"] = (
                "this result was trimmed to fit a character budget. Every count below the paths "
                "listed in `cuts` is the size of a page, not the size of the atlas. Re-run the "
                "tool with a narrower filter, or a larger --budget-chars, before quoting a total."
            )
        return payload


def _lists(node: Any, path: str, found: list[tuple[str, Any, Any]]) -> None:
    """Every list in the tree, as ``(path, container, key)`` so it can be replaced in place."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, list):
                found.append((child, node, key))
            _lists(value, child, found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = f"{path}[{index}]"
            if isinstance(value, list):
                found.append((child, node, index))
            _lists(value, child, found)


def apply_budget(payload: Any, *, limit: int) -> tuple[Any, Budget]:
    """Trim ``payload`` to ``limit`` characters, largest list first, and say what was cut.

    The input is deep-copied rather than mutated: a caller that also logs or caches the untrimmed
    payload must not find it silently shortened, and a tool handler returning a cached structure
    must not have that cache edited by the act of answering one call.

    Halving rather than computing an exact length is deliberate. The relationship between a
    list's element count and its serialized size is not linear -- one row can be fifty times
    another -- so a computed length would overshoot or undershoot and need re-measuring anyway.
    Halving converges in a handful of passes and each pass is one `json.dumps` of a payload that
    is, by construction, getting smaller.

    **Among lists of comparable size, `data` is cut before `contract`.** That tie-break was
    earned twice. The first run of `atlas_route_answer` against the real atlas dropped 107 of 142
    citations, because the citation list honestly *was* the largest list in the payload -- and
    trimming rows leaves the remaining rows cited, while trimming citations leaves the remaining
    rows uncited, which is the one thing PLAN.md O.2.1 does not permit. But preferring `data`
    absolutely is worse still: the second attempt stripped a two-row route ranking to nothing
    while a citation list forty times its size sat untouched, because the route list was the only
    `data` list left. So the preference applies only within :data:`COMPARABLE_FRACTION` of the
    largest list there is. A citation list that dwarfs everything else is still cut; a citation
    list merely comparable to the rows waits its turn behind them.
    """
    limit = max(limit, MIN_BUDGET_CHARS)
    trimmed = copy.deepcopy(payload)
    before = measure(trimmed)
    if before <= limit:
        return trimmed, Budget(limit=limit, chars_before=before, chars_after=before)

    held: dict[str, int] = {}
    kept: dict[str, int] = {}
    size = before
    while size > limit:
        found: list[tuple[str, Any, Any]] = []
        _lists(trimmed, "", found)
        candidates = [entry for entry in found if len(entry[1][entry[2]]) > 0]
        if not candidates:
            # Nothing left to shorten. The payload is over budget on scalars alone, which is a
            # tool returning one enormous string rather than many rows -- not something this
            # module is entitled to edit, so it is reported over budget rather than mangled.
            break
        sized = [(measure(entry[1][entry[2]]), entry) for entry in candidates]
        biggest = max(cost for cost, _ in sized)
        # Everything within a factor of `COMPARABLE_FRACTION` of the biggest list is a reasonable
        # thing to cut next; among those, the contract block goes last. Outside that band the
        # size wins, so one runaway list cannot hide behind the preference.
        comparable = [
            entry
            for cost, entry in sized
            if cost >= biggest * COMPARABLE_FRACTION and not entry[0].startswith(CONTRACT_PREFIX)
        ]
        path, container, key = max(
            comparable or [entry for _, entry in sized],
            key=lambda entry: measure(entry[1][entry[2]]),
        )
        current = container[key]
        held.setdefault(path, len(current))
        container[key] = current[: len(current) // 2]
        kept[path] = len(container[key])
        size = measure(trimmed)

    cuts = tuple(Cut(path=path, held=held[path], kept=kept[path]) for path in sorted(held))
    return trimmed, Budget(limit=limit, chars_before=before, chars_after=size, cuts=cuts)
