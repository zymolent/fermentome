"""Metabolic layer: the curated pathways, the parts catalog, and route enumeration.

PLAN.md G. The two core pathways are hand-curated (G.3) rather than imported, and every reaction
is balance-checked before it is stored -- an unbalanced reaction does not look wrong downstream,
it produces routes that score perfectly well and cannot happen.
"""

from __future__ import annotations

from .cli import add_atlas_subcommand
from .curated import (
    PATHWAYS_DIR,
    CuratedPathway,
    Metabolite,
    Part,
    PathwayError,
    Reaction,
    check_balance,
    load_parts,
    load_pathway_file,
    load_pathways,
    write_parts,
    write_pathway,
    write_pathways,
)

__all__ = [
    "PATHWAYS_DIR",
    "add_atlas_subcommand",
    "CuratedPathway",
    "Metabolite",
    "Part",
    "PathwayError",
    "Reaction",
    "check_balance",
    "load_parts",
    "load_pathway_file",
    "load_pathways",
    "write_parts",
    "write_pathway",
    "write_pathways",
]
