"""The Networks read: the reaction graph, and the enumerated route space over it.

Two different graphs live here and they are not the same object:

* **The reaction graph** -- 16 curated reactions with their substrates, products and
  compartments. Small, hand-checked, and the thing a pathway diagram is drawn from. Edges carry
  the compartment, because a reaction in the matrix and the same EC number in the cytosol are
  different reactions with different cofactor pools.
* **The route space** -- 6,400 enumerated isobutanol routes, generated as the product of five
  cofactor strategies against the available parts and compartments. It is *generative*, not a
  list of published builds: PLAN.md's requirement that "what has never been tried" be answerable
  means the enumeration has to contain routes nobody has attempted.

Three properties of the current route table that any ranking has to state rather than hide:

1. **Every route fails the balance check.** All 6,400 carry `balance_status = 'fail'`. A
   leaderboard sorted by score, with that fact in a tooltip, would present 6,400 non-viable
   routes as a shortlist.
2. **`score_toxicity` is NULL everywhere.** Not zero -- never computed. A composite score that
   treats it as zero silently ranks on four axes while claiming five.
3. **No route is bound to a host or a configuration.** `host_strain_id` and
   `pathway_configuration_id` are NULL in every row, so a route is a shape, not a proposal
   against a strain.

So `rank_routes` returns the scores it has, names the axis it does not have, and refuses to
invent a composite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Page, Select
from fermdb.query.values import Absence, Value, Zone

__all__ = [
    "GraphEdge",
    "GraphNode",
    "NetworkOverview",
    "ReactionGraph",
    "RouteSummary",
    "rank_routes",
    "read_overview",
    "read_reaction_graph",
    "read_route",
]

#: Scoring axes stored on `pathway_route`. Ordered as they are rendered.
SCORE_AXES: tuple[str, ...] = (
    "score_balance",
    "score_evidence",
    "score_feasibility",
    "score_transport",
    "score_toxicity",
)


def _text(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value.absent(Absence.NOT_RECORDED)
    return Value.known(str(raw), zone=zone)


def _number(raw: Any, *, zone: Zone | None = Zone.INFERRED) -> Value[float]:
    """A score column. NULL is `not_recorded`, never 0.0 -- see the module docstring."""
    if raw is None:
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(float(raw), zone=zone)


@dataclass(frozen=True)
class GraphNode:
    """A metabolite or reaction, positioned in a compartment.

    ``kind`` drives the mark the renderer uses; ``compartment`` drives which container it is
    drawn inside. A node with no compartment is drawn outside every container rather than
    defaulted into the cytosol, because guessing here is how a diagram starts disagreeing with
    the database.
    """

    id: str
    label: str
    kind: str
    compartment: str | None = None
    is_cofactor: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "compartment": self.compartment,
            "is_cofactor": self.is_cofactor,
        }


@dataclass(frozen=True)
class GraphEdge:
    """A substrate or product link, with its stoichiometric coefficient."""

    source: str
    target: str
    role: str
    coefficient: float | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "role": self.role,
            "coefficient": self.coefficient,
        }


@dataclass(frozen=True)
class ReactionGraph:
    """The curated reaction graph, ready for a force layout or a compartment layout."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    compartments: tuple[str, ...]
    competing_reactions: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "nodes": [n.as_json() for n in self.nodes],
            "edges": [e.as_json() for e in self.edges],
            "compartments": list(self.compartments),
            "competing_reactions": list(self.competing_reactions),
            "note": (
                "compartment is a property of the reaction, not a layout hint -- the same EC "
                "number in two compartments is two nodes because it draws on two cofactor pools"
            ),
        }


@dataclass(frozen=True)
class RouteSummary:
    """One enumerated route: its strategy, its steps, and every score it does and does not have."""

    id: str
    cofactor_strategy: Value[str]
    balance_status: Value[str]
    host_strain_id: Value[str]
    deletion_set: Value[str]
    scores: dict[str, Value[float]]
    steps: tuple[dict[str, Any], ...]
    compartments: tuple[str, ...]
    uses_mitochondrial_code: bool

    @property
    def is_viable(self) -> bool:
        """False unless the balance check passed. Nothing else makes a route usable."""
        return self.balance_status.or_none() == "pass"

    def as_json(self) -> dict[str, Any]:
        missing = sorted(axis for axis, value in self.scores.items() if not value.is_known)
        payload: dict[str, Any] = {
            "id": self.id,
            "cofactor_strategy": self.cofactor_strategy.as_json(),
            "balance_status": self.balance_status.as_json(),
            "host_strain_id": self.host_strain_id.as_json(),
            "deletion_set": self.deletion_set.as_json(),
            "scores": {axis: value.as_json() for axis, value in self.scores.items()},
            "scored_axes": sorted(a for a in self.scores if self.scores[a].is_known),
            "unscored_axes": missing,
            "is_viable": self.is_viable,
            "steps": list(self.steps),
            "compartments": list(self.compartments),
            "uses_mitochondrial_code": self.uses_mitochondrial_code,
        }
        if missing:
            payload["ranking_caveat"] = (
                f"{len(missing)} scoring axis/axes were never computed ({', '.join(missing)}); "
                "any composite of the rest is a ranking on fewer axes than it appears to use"
            )
        return payload


@dataclass(frozen=True)
class NetworkOverview:
    """The Networks landing payload."""

    reactions: int
    metabolites: int
    reaction_genes: int
    pathways: int
    routes: int
    routes_by_strategy: dict[str, int]
    routes_by_balance: dict[str, int]
    steps_by_compartment: dict[str, int]
    steps_by_encoding_genome: dict[str, int]
    parts_by_role: dict[str, int]
    gaps_by_kind: dict[str, int]
    unscored_axes: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        viable = self.routes_by_balance.get("pass", 0)
        return {
            "reactions": self.reactions,
            "metabolites": self.metabolites,
            "reaction_genes": self.reaction_genes,
            "pathways": self.pathways,
            "routes": self.routes,
            "viable_routes": viable,
            "routes_by_strategy": self.routes_by_strategy,
            "routes_by_balance": self.routes_by_balance,
            "steps_by_compartment": self.steps_by_compartment,
            "steps_by_encoding_genome": self.steps_by_encoding_genome,
            "parts_by_role": self.parts_by_role,
            "gaps_by_kind": self.gaps_by_kind,
            "unscored_axes": list(self.unscored_axes),
            "headline": (
                f"{self.routes:,} routes enumerated, {viable:,} passing the balance check"
            ),
            "note": (
                "the enumeration is generative: it contains routes nobody has attempted, which "
                "is what makes 'what has never been tried' an answerable question"
            ),
        }


def read_reaction_graph(
    conn: sqlite3.Connection, *, pathway_id: str | None = None
) -> ReactionGraph:
    """The reaction graph, optionally narrowed to one pathway."""
    reactions_select = Select("reaction").columns(
        "id", "name", "ec_number", "compartment_id", "reversible", "competing"
    )
    if pathway_id is not None:
        reactions_select = reactions_select.join(
            "pathway_reaction", "reaction.id = pr.reaction_id", alias="pr", kind="INNER"
        ).where("pr.pathway_id = ?", pathway_id)
    reactions = list(reactions_select.order_by("reaction.id").page(conn))
    reaction_ids = {str(row["id"]) for row in reactions}

    metabolites = {
        str(row["id"]): row
        for row in Select("metabolite").columns("id", "name", "carrier", "redox").page(conn)
    }

    nodes: list[GraphNode] = []
    compartments: set[str] = set()
    for row in reactions:
        compartment = row["compartment_id"]
        if compartment is not None:
            compartments.add(str(compartment))
        label = row["name"] or row["ec_number"] or row["id"]
        nodes.append(
            GraphNode(
                id=str(row["id"]),
                label=str(label),
                kind="reaction",
                compartment=str(compartment) if compartment is not None else None,
            )
        )

    edges: list[GraphEdge] = []
    seen_metabolites: set[str] = set()
    for row in (
        Select("reaction_participant")
        .columns("reaction_id", "metabolite_id", "role", "coefficient")
        .order_by("reaction_id", "role", "metabolite_id")
        .page(conn)
    ):
        reaction_id = str(row["reaction_id"])
        if reaction_id not in reaction_ids:
            continue
        metabolite_id = str(row["metabolite_id"])
        if metabolite_id not in seen_metabolites:
            seen_metabolites.add(metabolite_id)
            meta = metabolites.get(metabolite_id)
            nodes.append(
                GraphNode(
                    id=metabolite_id,
                    label=str(meta["name"]) if meta and meta["name"] else metabolite_id,
                    kind="metabolite",
                    is_cofactor=bool(meta["carrier"]) if meta else False,
                )
            )
        role = str(row["role"])
        coefficient = row["coefficient"]
        # Direction follows the role, so an arrow drawn from this edge is chemically right:
        # substrates point into the reaction, products point out of it.
        if role == "substrate":
            edges.append(GraphEdge(metabolite_id, reaction_id, role, coefficient))
        else:
            edges.append(GraphEdge(reaction_id, metabolite_id, role, coefficient))

    return ReactionGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        compartments=tuple(sorted(compartments)),
        competing_reactions=tuple(str(row["id"]) for row in reactions if row["competing"]),
    )


def _route_steps(conn: sqlite3.Connection, route_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "step_order": row["step_order"],
            "step_role_id": row["step_role_id"],
            "part_id": row["part_id"],
            "compartment_id": row["compartment_id"],
            "encoding_genome": row["encoding_genome"],
        }
        for row in Select("pathway_route_step")
        .columns("step_order", "step_role_id", "part_id", "compartment_id", "encoding_genome")
        .where("route_id = ?", route_id)
        .order_by("step_order")
        .page(conn)
    )


def _summary(conn: sqlite3.Connection, row: sqlite3.Row) -> RouteSummary:
    steps = _route_steps(conn, str(row["id"]))
    return RouteSummary(
        id=str(row["id"]),
        cofactor_strategy=_text(row["cofactor_strategy"]),
        balance_status=_text(row["balance_status"]),
        host_strain_id=_text(row["host_strain_id"]),
        deletion_set=_text(row["deletion_set"]),
        scores={axis: _number(row[axis]) for axis in SCORE_AXES},
        steps=steps,
        compartments=tuple(
            sorted({str(s["compartment_id"]) for s in steps if s["compartment_id"]})
        ),
        uses_mitochondrial_code=any(str(s["encoding_genome"]) == "mitochondrial" for s in steps),
    )


def read_route(conn: sqlite3.Connection, route_id: str) -> RouteSummary | None:
    """One route with its steps, or None."""
    row = (
        Select("pathway_route")
        .columns(
            "id",
            "cofactor_strategy",
            "balance_status",
            "host_strain_id",
            "deletion_set",
            *SCORE_AXES,
        )
        .where("id = ?", route_id)
        .one(conn)
    )
    return None if row is None else _summary(conn, row)


def rank_routes(
    conn: sqlite3.Connection,
    *,
    cofactor_strategy: str | None = None,
    balance_status: str | None = None,
    order_by: str = "score_evidence",
    limit: int = 25,
    offset: int = 0,
) -> Page:
    """Routes ordered by one *named* axis.

    Deliberately one axis and not a composite. Weighting five axes into a single number is a
    scientific claim about their relative importance, and this layer does not hold one -- so the
    caller names the axis it is ranking on and the UI shows which axis that was.
    """
    if order_by not in SCORE_AXES:
        raise ValueError(
            f"{order_by!r} is not a scoring axis; expected one of {', '.join(SCORE_AXES)}"
        )
    select = Select("pathway_route").columns(
        "id",
        "cofactor_strategy",
        "balance_status",
        "host_strain_id",
        "deletion_set",
        *SCORE_AXES,
    )
    if cofactor_strategy:
        select = select.where("cofactor_strategy = ?", cofactor_strategy)
    if balance_status:
        select = select.where("balance_status = ?", balance_status)
    return select.order_by(f"{order_by} DESC", "id").page(conn, limit=limit, offset=offset)


def _counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        (str(row["k"]) if row["k"] is not None else "unassigned"): int(row["n"])
        for row in Select(table)
        .columns(f"{column} AS k", "COUNT(*) AS n")
        .group_by(column)
        .page(conn)
    }


def _scalar_int(conn: sqlite3.Connection, select: Select) -> int:
    return int(select.scalar(conn) or 0)


def read_overview(conn: sqlite3.Connection) -> NetworkOverview:
    """The Networks page payload."""
    unscored = tuple(
        axis
        for axis in SCORE_AXES
        if _scalar_int(
            conn,
            Select("pathway_route").columns("COUNT(*) AS n").where(f"{axis} IS NOT NULL"),
        )
        == 0
    )
    return NetworkOverview(
        reactions=_scalar_int(conn, Select("reaction").columns("COUNT(*) AS n")),
        metabolites=_scalar_int(conn, Select("metabolite").columns("COUNT(*) AS n")),
        reaction_genes=_scalar_int(conn, Select("reaction_gene").columns("COUNT(*) AS n")),
        pathways=_scalar_int(conn, Select("pathway").columns("COUNT(*) AS n")),
        routes=_scalar_int(conn, Select("pathway_route").columns("COUNT(*) AS n")),
        routes_by_strategy=_counts(conn, "pathway_route", "cofactor_strategy"),
        routes_by_balance=_counts(conn, "pathway_route", "balance_status"),
        steps_by_compartment=_counts(conn, "pathway_route_step", "compartment_id"),
        steps_by_encoding_genome=_counts(conn, "pathway_route_step", "encoding_genome"),
        parts_by_role=_counts(conn, "part", "step_role_id"),
        gaps_by_kind=_counts(conn, "knowledge_gap", "kind"),
        unscored_axes=unscored,
    )
