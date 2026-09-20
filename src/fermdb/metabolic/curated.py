"""The two curated pathways, loaded from ``data/pathways/`` and checked before they are stored.

PLAN.md G.3: the core pathways are hand-curated rather than imported, because the details that
decide an engineering route -- compartment, cofactor specificity, which paralog carries flux --
are exactly what automated pathway imports omit or get wrong. Curated by hand, though, means
mistyped by hand, so nothing here is stored until it balances.

Three balance checks run over every reaction, and each is an expectation independent of whoever
typed the YAML:

* **Carbon.** Substrate carbons must equal product carbons. Each metabolite declares the carbons
  it contributes to the skeleton being tracked, not its molecular formula -- carriers such as
  NAD(H), CoA and THF are 0, because counting their full formulae would balance trivially on both
  sides and hide the error worth catching. Acetyl-CoA is the interesting case: 2 carbons, the
  acetyl group it donates, with free CoA appearing as a 0-carbon product.
* **Redox.** A reaction consuming NADPH must produce NADP+, one for one, and never silently swap
  pools. The NADPH/NADH mismatch across Ilv5 and the alcohol dehydrogenase is the whole reason the
  DUET architecture exists, so a typo that quietly balanced it would erase the problem the atlas
  is for.
* **Adenylate.** ATP consumed equals ADP produced.

A reaction that fails any of them raises rather than loading, because an unbalanced reaction in a
route enumerator does not look wrong -- it produces a route that scores perfectly well.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from ..config import Settings

__all__ = [
    "PARTS_FILE",
    "PATHWAYS_DIR",
    "CuratedPathway",
    "Part",
    "Metabolite",
    "PathwayError",
    "Reaction",
    "load_pathway_file",
    "load_parts",
    "load_pathways",
    "check_balance",
    "write_pathway",
    "write_parts",
    "write_pathways",
]

PATHWAYS_DIR: Final[str] = "data/pathways"

_SUBSTRATE: Final[str] = "substrate"
_PRODUCT: Final[str] = "product"


class PathwayError(ValueError):
    """A curated pathway file is malformed, or one of its reactions does not balance."""


@dataclass(frozen=True)
class Metabolite:
    id: str
    name: str
    carbons: int
    formula: str | None = None
    carrier: bool = False
    #: 'reduced' | 'oxidized' for a redox carrier, else None.
    redox: str | None = None
    #: The pool a redox carrier belongs to ('nad', 'nadp'), so the two halves can be matched.
    pair: str | None = None
    #: 'charged' | 'discharged' for ATP/ADP.
    adenylate: str | None = None


@dataclass(frozen=True)
class Participant:
    metabolite: str
    role: str
    coefficient: float


@dataclass(frozen=True)
class Reaction:
    id: str
    name: str
    step_role: str
    compartment: str
    genes: tuple[str, ...]
    equation: str
    participants: tuple[Participant, ...]
    reversible: bool
    evidence: str
    confidence: str
    ec: str | None = None
    competing: bool = False
    #: True for a reaction that moves a reducing equivalent BETWEEN the NAD and NADP pools rather
    #: than within one. Pos5's NADH kinase is the only such reaction here, and it is the DUET
    #: coupling itself -- so it must be declared, never inferred, and the per-pool balance check is
    #: relaxed for it alone while carrier conservation still applies.
    transfers_redox_pool: bool = False


@dataclass(frozen=True)
class CuratedPathway:
    id: str
    name: str
    product: str
    evidence: str
    confidence: str
    metabolites: Mapping[str, Metabolite]
    reactions: tuple[Reaction, ...]
    source_path: str
    problems: tuple[str, ...] = field(default=())


# ------------------------------------------------------------------------------ balance checks


def _sum_carbons(reaction: Reaction, metabolites: Mapping[str, Metabolite], role: str) -> float:
    total = 0.0
    for participant in reaction.participants:
        if participant.role != role:
            continue
        metabolite = metabolites.get(participant.metabolite)
        if metabolite is None:
            raise PathwayError(
                f"{reaction.id}: participant {participant.metabolite!r} is not declared in this "
                f"file's metabolites. A reaction referring to an undeclared metabolite cannot be "
                f"balance-checked, so it is refused rather than stored unchecked."
            )
        total += metabolite.carbons * participant.coefficient
    return total


def _count(
    reaction: Reaction,
    metabolites: Mapping[str, Metabolite],
    role: str,
    predicate: Any,
) -> float:
    return sum(
        participant.coefficient
        for participant in reaction.participants
        if participant.role == role and predicate(metabolites[participant.metabolite])
    )


def check_balance(reaction: Reaction, metabolites: Mapping[str, Metabolite]) -> list[str]:
    """Every way this reaction fails to balance, as human-readable strings. Empty means it does."""
    problems: list[str] = []

    substrate_c = _sum_carbons(reaction, metabolites, _SUBSTRATE)
    product_c = _sum_carbons(reaction, metabolites, _PRODUCT)
    if substrate_c != product_c:
        problems.append(f"carbon: {substrate_c:g} in, {product_c:g} out ({reaction.equation})")

    carriers_in = carriers_out = 0.0
    for pool in ("nad", "nadp"):
        # `pool=pool` binds the loop variable into each lambda. The lambdas are called
        # immediately here so late binding would not actually bite, but a checker that flags it
        # is right to: this is the shape that breaks the moment anyone defers the call.
        def reduced(m: Metabolite, pool: str = pool) -> bool:
            return m.pair == pool and m.redox == "reduced"

        def oxidized(m: Metabolite, pool: str = pool) -> bool:
            return m.pair == pool and m.redox == "oxidized"

        reduced_in = _count(reaction, metabolites, _SUBSTRATE, reduced)
        oxidized_out = _count(reaction, metabolites, _PRODUCT, oxidized)
        oxidized_in = _count(reaction, metabolites, _SUBSTRATE, oxidized)
        reduced_out = _count(reaction, metabolites, _PRODUCT, reduced)
        carriers_in += reduced_in + oxidized_in
        carriers_out += reduced_out + oxidized_out
        if reaction.transfers_redox_pool:
            # Pos5 phosphorylates NADH to NADPH: the molecule changes pool and its redox state
            # does not, so neither NAD+ nor NADP+ appears. Demanding per-pool conservation here
            # would reject the one reaction the DUET architecture is built on.
            continue
        if reduced_in != oxidized_out or oxidized_in != reduced_out:
            problems.append(
                f"{pool} redox: consumed {reduced_in:g} reduced / {oxidized_in:g} oxidized, "
                f"produced {reduced_out:g} reduced / {oxidized_out:g} oxidized"
            )

    # Carrier molecules are conserved whatever a reaction does to their redox state or pool: a
    # dinucleotide that goes in comes out. This catches the ordinary typo -- forgetting to emit
    # NADP+ -- even for a reaction the per-pool check above is relaxed for.
    if carriers_in != carriers_out:
        problems.append(
            f"redox carriers: {carriers_in:g} consumed but {carriers_out:g} produced; a "
            f"dinucleotide that enters a reaction has to leave it"
        )

    charged_in = _count(reaction, metabolites, _SUBSTRATE, lambda m: m.adenylate == "charged")
    discharged_out = _count(reaction, metabolites, _PRODUCT, lambda m: m.adenylate == "discharged")
    if charged_in != discharged_out:
        problems.append(
            f"adenylate: {charged_in:g} ATP consumed but {discharged_out:g} ADP produced"
        )

    return problems


# ------------------------------------------------------------------------------------- loading


def _metabolite(raw: Mapping[str, Any]) -> Metabolite:
    return Metabolite(
        id=str(raw["id"]),
        name=str(raw["name"]),
        carbons=int(raw["carbons"]),
        formula=str(raw["formula"]) if raw.get("formula") else None,
        carrier=bool(raw.get("carrier", False)),
        redox=str(raw["redox"]) if raw.get("redox") else None,
        pair=str(raw["pair"]) if raw.get("pair") else None,
        adenylate=str(raw["adenylate"]) if raw.get("adenylate") else None,
    )


def _reaction(raw: Mapping[str, Any]) -> Reaction:
    participants = tuple(
        Participant(
            metabolite=str(p["metabolite"]),
            role=str(p["role"]),
            coefficient=float(p["coefficient"]),
        )
        for p in raw["participants"]
    )
    return Reaction(
        id=str(raw["id"]),
        name=str(raw["name"]),
        step_role=str(raw["step_role"]),
        compartment=str(raw["compartment"]),
        genes=tuple(str(g) for g in raw.get("genes", ())),
        equation=str(raw["equation"]),
        participants=participants,
        reversible=bool(raw.get("reversible", False)),
        evidence=str(raw["evidence"]),
        confidence=str(raw["confidence"]),
        ec=str(raw["ec"]) if raw.get("ec") else None,
        competing=bool(raw.get("competing", False)),
        transfers_redox_pool=bool(raw.get("transfers_redox_pool", False)),
    )


def load_pathway_file(path: Path) -> CuratedPathway:
    """Parse one curated pathway file and balance-check every reaction in it.

    Raises on an unbalanced reaction. The alternative -- loading it with the problem recorded --
    would put a reaction that cannot happen into a route enumerator, where it produces routes that
    score perfectly well and are impossible.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "pathway" not in raw:
        raise PathwayError(f"{path}: not a curated pathway file (no top-level 'pathway' key)")

    header = raw["pathway"]
    metabolites = {m["id"]: _metabolite(m) for m in raw["metabolites"]}
    reactions = tuple(_reaction(r) for r in raw["reactions"])

    problems: list[str] = []
    for reaction in reactions:
        for problem in check_balance(reaction, metabolites):
            problems.append(f"{reaction.id}: {problem}")
    if problems:
        raise PathwayError(
            f"{path}: {len(problems)} reaction(s) do not balance, so nothing was loaded. An "
            f"unbalanced reaction does not look wrong downstream -- it produces routes that score "
            f"perfectly well and cannot happen.\n  " + "\n  ".join(problems)
        )

    return CuratedPathway(
        id=str(header["id"]),
        name=str(header["name"]),
        product=str(header["product"]),
        evidence=str(header["evidence"]),
        confidence=str(header["confidence"]),
        metabolites=metabolites,
        reactions=reactions,
        source_path=str(path),
    )


def load_pathways(settings: Settings) -> tuple[CuratedPathway, ...]:
    """Every curated pathway in ``data/pathways/``, in filename order."""
    directory = Path(settings.repo_root) / PATHWAYS_DIR
    if not directory.is_dir():
        raise PathwayError(f"{directory} does not exist; there are no curated pathways to load")
    files = [path for path in sorted(directory.glob("*.yaml")) if path.name != PARTS_FILE]
    if not files:
        raise PathwayError(f"{directory} holds no curated pathway files")
    return tuple(load_pathway_file(path) for path in files)


# ------------------------------------------------------------------------------------- storage


def _metabolite_id(local: str) -> str:
    return f"YAA:MET:{local.replace('_', '-')}"


def _reaction_id(pathway: str, local: str) -> str:
    return f"YAA:RXN:{pathway.replace('_', '-')}-{local.replace('_', '-')}"


def write_pathway(conn: sqlite3.Connection, pathway: CuratedPathway) -> dict[str, int]:
    """Write one curated pathway and everything it references. Idempotent."""
    counts = {
        "metabolite": 0,
        "reaction": 0,
        "pathway": 0,
        "pathway_reaction": 0,
        "reaction_participant": 0,
    }

    for metabolite in pathway.metabolites.values():
        conn.execute(
            "INSERT INTO metabolite (id, name, formula, zone, evidence, confidence) "
            "VALUES (?,?,?,'R',?,'high') ON CONFLICT(id) DO UPDATE SET formula=excluded.formula",
            (
                _metabolite_id(metabolite.id),
                metabolite.name,
                metabolite.formula,
                f"curated pathway {pathway.id} ({Path(pathway.source_path).name})",
            ),
        )
        counts["metabolite"] += 1

    conn.execute(
        "INSERT INTO pathway (id, name, zone, evidence, confidence) VALUES (?,?,'R',?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, evidence=excluded.evidence",
        (
            f"YAA:PWY:{pathway.id.replace('_', '-')}",
            pathway.name,
            pathway.evidence,
            pathway.confidence,
        ),
    )
    counts["pathway"] += 1

    for order, reaction in enumerate(pathway.reactions, start=1):
        reaction_id = _reaction_id(pathway.id, reaction.id)
        conn.execute(
            "INSERT INTO reaction (id, name, ec_number, equation, compartment_id, reversible, "
            "zone, evidence, confidence) VALUES (?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(id) DO UPDATE SET equation=excluded.equation, "
            "evidence=excluded.evidence, confidence=excluded.confidence",
            (
                reaction_id,
                reaction.name,
                reaction.ec,
                reaction.equation,
                reaction.compartment,
                1 if reaction.reversible else 0,
                f"{reaction.evidence} [genes: {', '.join(reaction.genes) or 'none named'}]",
                reaction.confidence,
            ),
        )
        counts["reaction"] += 1

        conn.execute(
            "INSERT INTO pathway_reaction (pathway_id, reaction_id, step_order, step_role_id) "
            "VALUES (?,?,?,?) ON CONFLICT(pathway_id, reaction_id) DO UPDATE SET "
            "step_order=excluded.step_order",
            (f"YAA:PWY:{pathway.id.replace('_', '-')}", reaction_id, order, reaction.step_role),
        )
        counts["pathway_reaction"] += 1

        for participant in reaction.participants:
            conn.execute(
                "INSERT INTO reaction_participant (reaction_id, metabolite_id, role, coefficient) "
                "VALUES (?,?,?,?) ON CONFLICT(reaction_id, metabolite_id, role) DO UPDATE SET "
                "coefficient=excluded.coefficient",
                (
                    reaction_id,
                    _metabolite_id(participant.metabolite),
                    participant.role,
                    participant.coefficient,
                ),
            )
            counts["reaction_participant"] += 1

    return counts


def write_pathways(
    conn: sqlite3.Connection, pathways: Sequence[CuratedPathway] | Iterable[CuratedPathway]
) -> dict[str, int]:
    """Write every pathway and commit once."""
    totals: dict[str, int] = {}
    for pathway in pathways:
        for table, count in write_pathway(conn, pathway).items():
            totals[table] = totals.get(table, 0) + count
    conn.commit()
    return totals


# --------------------------------------------------------------------------------------- parts

PARTS_FILE: Final[str] = "parts_catalog.yaml"


@dataclass(frozen=True)
class Part:
    """One candidate enzyme for a pathway step role."""

    id: str
    step_role: str
    source_organism: str
    genes: tuple[str, ...]
    native_compartment: str
    sequence_encoding_genome: str
    cofactor_preference: str
    oxygen_sensitivity: str
    evidence: str
    confidence: str
    variant_of: str | None = None
    engineered_switch: bool = False


def load_parts(settings: Settings) -> tuple[Part, ...]:
    """The parts catalog: candidate enzymes per step role, the first factor of G.7's product."""
    path = Path(settings.repo_root) / PATHWAYS_DIR / PARTS_FILE
    if not path.is_file():
        raise PathwayError(f"{path} is missing; route enumeration has nothing to choose between")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(
        Part(
            id=str(p["id"]),
            step_role=str(p["step_role"]),
            source_organism=str(p["source_organism"]),
            genes=tuple(str(g) for g in p.get("genes", ())),
            native_compartment=str(p["native_compartment"]),
            sequence_encoding_genome=str(p["sequence_encoding_genome"]),
            cofactor_preference=str(p["cofactor_preference"]),
            oxygen_sensitivity=str(p["oxygen_sensitivity"]),
            evidence=str(p["evidence"]),
            confidence=str(p["confidence"]),
            variant_of=str(p["variant_of"]) if p.get("variant_of") else None,
            engineered_switch=bool(p.get("engineered_switch", False)),
        )
        for p in raw["parts"]
    )


def write_parts(conn: sqlite3.Connection, parts: Sequence[Part]) -> dict[str, int]:
    """Write the parts catalog. Zone I throughout: every functional claim in it is background
    knowledge that has never been checked against a source, and the catalog says so itself."""
    written = 0
    for part in parts:
        conn.execute(
            "INSERT INTO part (id, step_role_id, source_organism_id, sequence_compartment_id, "
            "sequence_encoding_genome, variant_of, cofactor_preference, engineered_switch, "
            "oxygen_sensitivity, zone, evidence, confidence) VALUES (?,?,?,?,?,?,?,?,?,'I',?,?) "
            "ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence, "
            "cofactor_preference=excluded.cofactor_preference",
            (
                f"YAA:PART:{part.id.replace('_', '-')}",
                part.step_role,
                None,
                part.native_compartment,
                part.sequence_encoding_genome,
                f"YAA:PART:{part.variant_of.replace('_', '-')}" if part.variant_of else None,
                part.cofactor_preference,
                1 if part.engineered_switch else 0,
                part.oxygen_sensitivity,
                f"{part.evidence} [genes: {', '.join(part.genes)}; from {part.source_organism}]",
                part.confidence,
            ),
        )
        written += 1
    conn.commit()
    return {"part": written}
