"""The Gene read: what the atlas knows about one gene, and how much of it is measured.

PLAN.md P.2 asks this page for "Function, gene group membership, expression across conditions,
pathways, interactions, regulators, engineering history, variants across strains, literature,
evidence summary", and names the thing it must get right:

    The engineering history table with outcomes, including null results

Most of that is not available yet, and the page's job is to be exact about which parts. Of the
nine sections P.2 lists, this reader serves four — identity, function, pathway role, and the
engineering history — and reports the other five as absent rather than omitting them, because a
page that silently drops "interactions" looks complete.

Two things worth stating about how it reads.

**Gene identity is not the gene group.** `gene` rows are per assembly — the same ILV5 in two
assemblies is two rows — while `gene_group` is the stable cross-assembly anchor that annotations
and orthologs hang from (PLAN.md C.3 calls it "the single most important decision"). Annotations
therefore join through the group, never through the gene, and this module keeps them apart in the
return shape so a caller cannot conflate them.

**Expression lives outside the database.** The 99-run baseline sits in on-disk matrices, not in a
table. Rather than half-report it, :class:`GeneRead` carries expression as an explicit absence
naming where the numbers are, so the page can link out instead of showing a blank panel.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .builder import Select
from .values import Absence, Value, Zone

__all__ = [
    "AnnotationRead",
    "GeneRead",
    "ReactionRoleRead",
    "list_genes",
    "read_gene",
]


def _text(raw: Any, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    if raw is None or str(raw).strip() == "":
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(str(raw), zone=zone)


@dataclass(frozen=True)
class AnnotationRead:
    """One functional term, with the source that asserted it."""

    source: str
    term_id: str
    term_label: Value[str]
    namespace: Value[str]
    evidence_code: Value[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "term_id": self.term_id,
            "term_label": self.term_label.as_json(),
            "namespace": self.namespace.as_json(),
            "evidence_code": self.evidence_code.as_json(),
        }


@dataclass(frozen=True)
class ReactionRoleRead:
    """A reaction this gene's product is named for, and whether that reaction competes.

    ``competing`` is the field schema v6 recovered. Before it existed this page could say a gene
    ran a reaction but not whether that reaction drains the pathway it sits in — which is the
    difference between "ECM31 is in the pathway" and "ECM31 takes carbon out of it".
    """

    reaction_id: str
    reaction_name: Value[str]
    pathway_id: Value[str]
    compartment: Value[str]
    competing: Value[bool]
    resolution: str

    def as_json(self) -> dict[str, Any]:
        return {
            "reaction_id": self.reaction_id,
            "reaction_name": self.reaction_name.as_json(),
            "pathway_id": self.pathway_id.as_json(),
            "compartment": self.compartment.as_json(),
            "competing": self.competing.as_json(),
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class GeneRead:
    """One gene: identity, group, function, pathway role, and what is not held."""

    id: str
    systematic_name: Value[str]
    standard_name: Value[str]
    organism_id: Value[str]
    assembly_accession: Value[str]
    gene_group_id: Value[str]
    gene_group_anchor: Value[str]
    annotations: tuple[AnnotationRead, ...]
    reactions: tuple[ReactionRoleRead, ...]
    modifications: tuple[str, ...] = ()

    #: PLAN.md P.2 sections this reader does not serve, with why. Reported rather than omitted:
    #: a page that silently drops a section looks complete.
    @property
    def absent_sections(self) -> dict[str, str]:
        return {
            "expression": (
                "the 99-run baseline is in on-disk matrices, not a table; see "
                "docs/reports/2026-09-20-duet-expression-baseline.md"
            ),
            "interactions": "no interaction source has been ingested",
            "regulators": "YEASTRACT is not ingested; no regulator table holds rows",
            "variants_across_strains": "chassis genomics is deferred (PLAN.md Q.5)",
            "engineering_history": (
                f"{len(self.modifications)} modification(s) recorded"
                if self.modifications
                else "no modification rows yet -- every proposal is still in the curation queue"
            ),
        }

    @property
    def competing_reactions(self) -> tuple[ReactionRoleRead, ...]:
        return tuple(r for r in self.reactions if r.competing.or_none() is True)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "systematic_name": self.systematic_name.as_json(),
            "standard_name": self.standard_name.as_json(),
            "organism_id": self.organism_id.as_json(),
            "assembly_accession": self.assembly_accession.as_json(),
            "gene_group_id": self.gene_group_id.as_json(),
            "gene_group_anchor": self.gene_group_anchor.as_json(),
            "annotations": [a.as_json() for a in self.annotations],
            "reactions": [r.as_json() for r in self.reactions],
            "modifications": list(self.modifications),
            "absent_sections": self.absent_sections,
            "counts": {
                "annotations": len(self.annotations),
                "reactions": len(self.reactions),
                "competing_reactions": len(self.competing_reactions),
            },
        }


def list_genes(conn: sqlite3.Connection, *, limit: int = 200) -> tuple[tuple[str, str], ...]:
    """``(id, standard_name or systematic_name)`` for every resolved gene, in name order."""
    page = (
        Select("gene")
        .columns("id", "standard_name", "systematic_name")
        .order_by("standard_name", "id")
        .page(conn, limit=limit)
    )
    return tuple(
        (str(r["id"]), str(r["standard_name"] or r["systematic_name"] or r["id"])) for r in page
    )


def _annotations(conn: sqlite3.Connection, group_id: str | None) -> tuple[AnnotationRead, ...]:
    """Annotations hang from the gene GROUP, never from the gene row (PLAN.md C.3)."""
    if not group_id:
        return ()
    page = (
        Select("gene_annotation")
        .columns("source", "term_id", "term_label", "term_namespace", "evidence_code")
        .where("gene_group_id = ?", group_id)
        .order_by("source", "term_id")
        .page(conn, limit=500)
    )
    return tuple(
        AnnotationRead(
            source=str(r["source"]),
            term_id=str(r["term_id"]),
            term_label=_text(r["term_label"]),
            namespace=_text(r["term_namespace"]),
            evidence_code=_text(r["evidence_code"]),
        )
        for r in page
    )


def _reactions(conn: sqlite3.Connection, gene_id: str) -> tuple[ReactionRoleRead, ...]:
    """Reactions this gene is named for, via the `reaction_gene` table schema v6 added."""
    page = (
        Select("reaction_gene", alias="rg")
        .columns(
            "rg.reaction_id AS reaction_id",
            "rg.resolution AS resolution",
            "r.name AS name",
            "r.compartment_id AS compartment_id",
            "r.competing AS competing",
            "pr.pathway_id AS pathway_id",
        )
        .join("reaction", "rg.reaction_id = r.id", alias="r", kind="INNER")
        .join("pathway_reaction", "rg.reaction_id = pr.reaction_id", alias="pr")
        .where("rg.gene_id = ?", gene_id)
        .order_by("rg.reaction_id")
        .page(conn, limit=100)
    )
    out: list[ReactionRoleRead] = []
    for r in page:
        competing = r["competing"]
        out.append(
            ReactionRoleRead(
                reaction_id=str(r["reaction_id"]),
                reaction_name=_text(r["name"]),
                pathway_id=_text(r["pathway_id"]),
                compartment=_text(r["compartment_id"]),
                competing=(
                    Value.known(bool(competing), zone=Zone.REPORTED)
                    if competing is not None
                    else Value.absent(Absence.NOT_RECORDED, zone=Zone.REPORTED)
                ),
                resolution=str(r["resolution"]),
            )
        )
    return tuple(out)


def read_gene(conn: sqlite3.Connection, gene_id: str) -> GeneRead | None:
    """One gene, or None if there is no such row.

    ``gene_id`` may be the internal id, the systematic name (``YLR355C``) or the standard name
    (``ILV5``) — all three are how a person refers to a gene, and refusing two of them would make
    the page usable only by someone who already knows the atlas's own identifiers.
    """
    row = (
        Select("gene")
        .columns(
            "id",
            "organism_id",
            "assembly_accession",
            "systematic_name",
            "standard_name",
            "gene_group_id",
        )
        .where(
            "id = ? OR UPPER(systematic_name) = UPPER(?) OR UPPER(standard_name) = UPPER(?)",
            gene_id,
            gene_id,
            gene_id,
        )
        .page(conn, limit=2)
    )
    if not row.rows:
        return None
    first = row.rows[0]

    group_id = first["gene_group_id"]
    anchor = None
    if group_id:
        group = (
            Select("gene_group")
            .columns("anchor_id", "anchor_namespace")
            .where("id = ?", str(group_id))
            .one(conn)
        )
        if group is not None:
            anchor = group["anchor_id"]

    # No join needed: `modification.target_gene_group_id` is the link, and joining `gene_group`
    # only to prove it exists made `id` ambiguous between the two tables.
    modifications = (
        Select("modification")
        .columns("id")
        .where("target_gene_group_id = ?", str(group_id or ""))
        .page(conn, limit=100)
    )

    return GeneRead(
        id=str(first["id"]),
        systematic_name=_text(first["systematic_name"]),
        standard_name=_text(first["standard_name"]),
        organism_id=_text(first["organism_id"]),
        assembly_accession=_text(first["assembly_accession"]),
        gene_group_id=_text(group_id),
        gene_group_anchor=_text(anchor),
        annotations=_annotations(conn, str(group_id) if group_id else None),
        reactions=_reactions(conn, str(first["id"])),
        modifications=tuple(str(m["id"]) for m in modifications),
    )
