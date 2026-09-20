"""The Pathway read: the reaction graph as the *database* holds it, gaps included.

PLAN.md P.2 asks this page for "Reaction graph with compartments, genes, enzymes, cofactors,
competing branches, regulation, interventions mapped onto reactions", and P.3 sets the rule that
makes the page worth building at all:

    **if a diagram can disagree with the database, it is decoration.**

Taking that rule seriously is what this module is for, and what it turned up is that **three of
the facts P.2 requires do not survive the load.** `data/pathways/*.yaml` records all three and
`metabolic/curated.py` parses all three into its dataclasses, and then:

* ``competing`` is never written. The `reaction` table has no such column and the INSERT does not
  mention one. Which reactions drain the 2-ketoisovalerate pool -- the valine branch, the leucine
  branch, ECM31 -- is the single most decision-relevant fact in the isobutanol pathway, and the
  database does not know it. `fermdb atlas pathways` prints "(3 competing)" from the in-memory
  YAML objects, so the CLI looks like it knows and the atlas does not.
* ``genes`` are concatenated into the evidence sentence as ``[genes: LEU4, LEU9]`` rather than
  joined to the `gene` table, whose 36 resolved rows include most of them.
* ``carrier`` is dropped. `reaction_participant.role` permits 'cofactor' and the loader never
  writes it -- 32 products, 29 substrates, zero cofactors -- and `metabolite` has no `carrier`
  column to hold the YAML's flag. NADPH is stored as an ordinary substrate of KARI, structurally
  identical to acetolactate.

So a diagram drawn from this database today would show the three drains as ordinary reactions and
NADPH as backbone carbon. It could not do otherwise: nothing in the atlas says they are anything
else. Under P.3's rule that diagram is decoration.

**This module papers over none of the three, and specifically does not parse the genes back out
of the evidence string.** Recovering a structured fact from free text is how a UI starts asserting
things the atlas cannot defend, and it would hide the loader bug behind an apparently-working
page. Each is reported as absent with a reason, through the same `Value` machinery that carries
any other missing datum, and :attr:`PathwayRead.gaps` names them in the payload so an interface
can say *why* the picture is incomplete instead of rendering a confident, wrong one.

The absence is deliberately ``not recorded`` and never ``False``. Writing ``competing: false`` for
the valine branch would not be a missing fact; it would be a false one.

When the schema does grow the column, :func:`read_pathway` picks it up on its own -- it asks the
database what columns exist rather than carrying a hard-coded list that would go stale.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .builder import Select
from .values import Absence, Value, Zone

__all__ = [
    "PathwayRead",
    "ParticipantRead",
    "ReactionRead",
    "list_pathways",
    "read_pathway",
]


def _columns_of(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    """The column names a table actually has, so a reader can adapt instead of assuming."""
    return frozenset(str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})"))


def _zone_of(raw: Any) -> Zone | None:
    return Zone(str(raw)) if raw else None


@dataclass(frozen=True)
class ParticipantRead:
    """One metabolite on one side of a reaction.

    ``is_carrier`` is what would let a renderer put NAD(H) and ATP on the edge rather than in the
    backbone (P.2: "cofactors on the edges"), and in this atlas it is usually **not knowable**.

    `reaction_participant.role` has 'cofactor' in its CHECK constraint and the curated loader
    never writes it: 32 products, 29 substrates, zero cofactors. NADPH is stored as an ordinary
    substrate of the KARI reaction, indistinguishable from acetolactate. The YAML says
    ``carrier: true`` and `metabolite` has no column to put it in, so the flag is dropped on load
    along with ``competing``.

    Hence a `Value` rather than a bool. Role 'cofactor' settles the question; anything else leaves
    it open, because with the loader as it stands "stored as a substrate" and "is a substrate" are
    the same row. Returning False there would have been the quiet kind of wrong -- every carrier
    in the atlas confidently reported as backbone carbon.
    """

    metabolite_id: str
    name: str
    role: str
    coefficient: float
    formula: Value[str]
    is_carrier: Value[bool]

    def as_json(self) -> dict[str, Any]:
        return {
            "metabolite_id": self.metabolite_id,
            "name": self.name,
            "role": self.role,
            "coefficient": self.coefficient,
            "is_carrier": self.is_carrier.as_json(),
            "formula": self.formula.as_json(),
        }


@dataclass(frozen=True)
class ReactionRead:
    """One reaction with everything the atlas structurally knows about it, and nothing more."""

    id: str
    name: Value[str]
    ec_number: Value[str]
    equation: Value[str]
    compartment: Value[str]
    reversible: Value[bool]
    competing: Value[bool]
    genes: Value[tuple[str, ...]]
    step_role: Value[str]
    step_order: int
    evidence: str
    confidence: str
    zone: Zone | None
    participants: tuple[ParticipantRead, ...]

    @property
    def substrates(self) -> tuple[ParticipantRead, ...]:
        return tuple(p for p in self.participants if p.role == "substrate")

    @property
    def products(self) -> tuple[ParticipantRead, ...]:
        return tuple(p for p in self.participants if p.role == "product")

    @property
    def cofactors(self) -> tuple[ParticipantRead, ...]:
        """Only the participants the atlas *says* are carriers -- often none. See ParticipantRead.

        A caller wanting "the backbone" must not take the complement of this: an unknown carrier
        status is not a known non-carrier.
        """
        return tuple(p for p in self.participants if p.is_carrier.or_none() is True)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name.as_json(),
            "ec_number": self.ec_number.as_json(),
            "equation": self.equation.as_json(),
            "compartment": self.compartment.as_json(),
            "reversible": self.reversible.as_json(),
            "competing": self.competing.as_json(),
            "genes": self.genes.as_json(),
            "step_role": self.step_role.as_json(),
            "step_order": self.step_order,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "zone": self.zone.value if self.zone else None,
            "participants": [p.as_json() for p in self.participants],
        }


@dataclass(frozen=True)
class PathwayRead:
    """A pathway, its ordered reactions, and what the page cannot show."""

    id: str
    name: str
    evidence: str
    confidence: str
    zone: Zone | None
    reactions: tuple[ReactionRead, ...]
    gaps: tuple[str, ...]

    @property
    def is_renderable_as_specified(self) -> bool:
        """False while any fact PLAN.md P.2 requires of this page is missing from the atlas.

        A renderer is expected to check this and say so. P.3 forbids a diagram that can disagree
        with the database; a diagram missing the competing branches disagrees with the *curated
        source*, which is worse, because it looks complete.
        """
        return not self.gaps

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "zone": self.zone.value if self.zone else None,
            "reactions": [r.as_json() for r in self.reactions],
            "gaps": list(self.gaps),
            "is_renderable_as_specified": self.is_renderable_as_specified,
        }


def list_pathways(conn: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    """``(id, name)`` for every curated pathway, in name order."""
    page = Select("pathway").columns("id", "name").order_by("name").page(conn)
    return tuple((str(row["id"]), str(row["name"])) for row in page)


def _participants(
    conn: sqlite3.Connection, reaction_id: str, *, has_carrier_column: bool
) -> tuple[ParticipantRead, ...]:
    selected = [
        "rp.metabolite_id AS metabolite_id",
        "rp.role AS role",
        "rp.coefficient AS coefficient",
        "m.name AS name",
        "m.formula AS formula",
        "m.zone AS zone",
    ]
    if has_carrier_column:
        selected.append("m.carrier AS carrier")
    page = (
        Select("reaction_participant", alias="rp")
        .columns(*selected)
        .join("metabolite", "rp.metabolite_id = m.id", alias="m", kind="INNER")
        .where("rp.reaction_id = ?", reaction_id)
        .order_by("rp.role", "rp.metabolite_id")
        .page(conn)
    )

    participants: list[ParticipantRead] = []
    for row in page:
        zone = _zone_of(row["zone"])
        role = str(row["role"])
        if role == "cofactor":
            carrier: Value[bool] = Value.known(True, zone=zone)
        elif has_carrier_column and row["carrier"] is not None:
            carrier = Value.known(bool(row["carrier"]), zone=zone)
        else:
            # Neither the role nor a carrier column settles it, so nothing here does.
            carrier = Value.absent(Absence.NOT_RECORDED, zone=zone)
        participants.append(
            ParticipantRead(
                metabolite_id=str(row["metabolite_id"]),
                name=str(row["name"]),
                role=role,
                coefficient=float(row["coefficient"]),
                formula=_optional_text(row["formula"], zone),
                is_carrier=carrier,
            )
        )
    return tuple(participants)


def _any_cofactor_role(conn: sqlite3.Connection, pathway_id: str) -> bool:
    """Whether this pathway records even one participant as a cofactor.

    Checked per pathway rather than globally: one pathway loaded by a fixed loader should not have
    its gap suppressed by another that was not, nor the reverse.
    """
    row = (
        Select("reaction_participant", alias="rp")
        .columns("COUNT(*) AS n")
        .join("pathway_reaction", "rp.reaction_id = pr.reaction_id", alias="pr", kind="INNER")
        .where("pr.pathway_id = ? AND rp.role = ?", pathway_id, "cofactor")
        .one(conn)
    )
    return bool(row is not None and int(row["n"]) > 0)


def _optional_text(raw: Any, zone: Zone | None) -> Value[str]:
    return (
        Value.known(str(raw), zone=zone)
        if raw is not None
        else Value.absent(Absence.NOT_RECORDED, zone=zone)
    )


def read_pathway(conn: sqlite3.Connection, pathway_id: str) -> PathwayRead | None:
    """One pathway's full reaction graph, or None if there is no such pathway.

    ``competing`` and ``genes`` are read if the schema carries them and reported as absent if it
    does not, so this function needs no change on the day the loader is fixed -- only the gap list
    shrinks, because it is computed from the same check.
    """
    header = (
        Select("pathway")
        .columns("id", "name", "evidence", "confidence", "zone")
        .where("id = ?", pathway_id)
        .one(conn)
    )
    if header is None:
        return None

    reaction_columns = _columns_of(conn, "reaction")
    has_competing = "competing" in reaction_columns
    has_gene_link = "reaction_gene" in {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    gaps: list[str] = []
    if not has_competing:
        gaps.append(
            "competing branches: data/pathways/*.yaml records `competing` per reaction and "
            "metabolic/curated.py parses it, but `reaction` has no such column and the INSERT "
            "does not write it. Which reactions drain the 2-KIV pool is not in the database"
        )
    if not has_gene_link:
        gaps.append(
            "genes: curated.py appends them to the evidence sentence as '[genes: ...]' instead "
            "of joining to `gene`. Not parsed back out here -- recovering a structured fact from "
            "free text would assert a link the atlas cannot defend"
        )
    has_carrier_column = "carrier" in _columns_of(conn, "metabolite")
    if not has_carrier_column and not _any_cofactor_role(conn, pathway_id):
        gaps.append(
            "cofactors: `reaction_participant.role` permits 'cofactor' and the loader never "
            "writes it, and `metabolite` has no `carrier` column, so NADPH is stored as an "
            "ordinary substrate. Carriers cannot be drawn on the edges because nothing "
            "distinguishes them from backbone carbon"
        )

    selected = [
        "r.id AS id",
        "r.name AS name",
        "r.ec_number AS ec_number",
        "r.equation AS equation",
        "r.compartment_id AS compartment_id",
        "r.reversible AS reversible",
        "r.evidence AS evidence",
        "r.confidence AS confidence",
        "r.zone AS zone",
        "pr.step_order AS step_order",
        "pr.step_role_id AS step_role_id",
    ]
    if has_competing:
        selected.append("r.competing AS competing")

    rows = (
        Select("pathway_reaction", alias="pr")
        .columns(*selected)
        .join("reaction", "pr.reaction_id = r.id", alias="r", kind="INNER")
        .where("pr.pathway_id = ?", pathway_id)
        .order_by("pr.step_order")
        .page(conn)
    )

    reactions: list[ReactionRead] = []
    for row in rows:
        zone = _zone_of(row["zone"])
        keys = row.keys()
        if has_competing and "competing" in keys and row["competing"] is not None:
            competing: Value[bool] = Value.known(bool(row["competing"]), zone=zone)
        else:
            competing = Value.absent(Absence.NOT_RECORDED, zone=zone)
        reactions.append(
            ReactionRead(
                id=str(row["id"]),
                name=_optional_text(row["name"], zone),
                ec_number=_optional_text(row["ec_number"], zone),
                equation=_optional_text(row["equation"], zone),
                compartment=_optional_text(row["compartment_id"], zone),
                reversible=(
                    Value.known(bool(row["reversible"]), zone=zone)
                    if row["reversible"] is not None
                    else Value.absent(Absence.NOT_RECORDED, zone=zone)
                ),
                competing=competing,
                genes=Value.absent(Absence.NOT_RECORDED, zone=zone),
                step_role=_optional_text(row["step_role_id"], zone),
                step_order=int(row["step_order"]),
                evidence=str(row["evidence"]),
                confidence=str(row["confidence"]),
                zone=zone,
                participants=_participants(
                    conn, str(row["id"]), has_carrier_column=has_carrier_column
                ),
            )
        )

    return PathwayRead(
        id=str(header["id"]),
        name=str(header["name"]),
        evidence=str(header["evidence"]),
        confidence=str(header["confidence"]),
        zone=_zone_of(header["zone"]),
        reactions=tuple(reactions),
        gaps=tuple(gaps),
    )


def pathway_gaps(conn: sqlite3.Connection) -> Mapping[str, tuple[str, ...]]:
    """Every curated pathway's gap list, for the dashboard's coverage section."""
    result: dict[str, tuple[str, ...]] = {}
    for pathway_id, _ in list_pathways(conn):
        read = read_pathway(conn, pathway_id)
        if read is not None:
            result[pathway_id] = read.gaps
    return result
