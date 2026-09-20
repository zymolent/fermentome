"""Load the controlled vocabularies from ``data/vocabularies/`` into their tables.

These files are the curated source of truth -- 53 products and 59 theoretical yields, each with
its own evidence string and confidence -- and nothing had ever loaded them. That is not a cosmetic
gap. ``measurement.product_id`` is a foreign key onto ``product``, so with the table empty **no
measurement could be stored at all**: perfect extraction would have had nowhere to put its
numbers, and the failure would have surfaced as a foreign-key error deep inside a curation run
rather than as the missing loader it actually is.

Zone R throughout. A vocabulary row is what the curated file says, and the file carries per-row
evidence and confidence already -- so those are read across rather than invented here.

**The three-state discipline applies to yields specifically.** ``theoretical_yields.tsv`` carries
a ``state`` column precisely because a yield can be *known*, *not applicable* to that pair, or
*sought and unsettled*. `fermdb.llm.validate` refuses to check a yield whose state is not known,
and it can only do that if the state survives the load, so it is copied into both
``g_per_g_state`` and ``mol_per_mol_state`` rather than being flattened into a NULL.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..config import Settings

__all__ = [
    "PRODUCTS_FILE",
    "YIELDS_FILE",
    "VocabularyError",
    "load_products",
    "load_theoretical_yields",
    "load_vocabularies",
    "read_tsv",
]

PRODUCTS_FILE: Final[str] = "products.tsv"
YIELDS_FILE: Final[str] = "theoretical_yields.tsv"


class VocabularyError(RuntimeError):
    """A vocabulary file is missing, empty, or missing a column the table requires."""


def read_tsv(path: Path) -> Iterator[dict[str, str]]:
    """Rows of a ``#``-commented TSV. Comment lines are stripped before the header is read."""
    if not path.is_file():
        raise VocabularyError(f"{path} is missing; it is the source of truth for its table")
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    if not lines:
        raise VocabularyError(f"{path} holds only comments")
    yield from csv.DictReader(lines, delimiter="\t")


def _vocabularies_dir(settings: Settings) -> Path:
    return Path(settings.path("vocabularies_dir"))


def _text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _number(value: str | None) -> float | None:
    """A float, or NULL. Never 0.0 -- an unrecorded yield and a yield of zero are different."""
    text = (value or "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def load_products(conn: sqlite3.Connection, settings: Settings) -> int:
    """Write one ``product`` row per line of ``products.tsv``. Idempotent."""
    written = 0
    for row in read_tsv(_vocabularies_dir(settings) / PRODUCTS_FILE):
        identifier = _text(row.get("id"))
        name = _text(row.get("name"))
        if identifier is None or name is None:
            raise VocabularyError(f"{PRODUCTS_FILE}: a row has no id or no name: {row}")
        carbon = row.get("carbon_number", "").strip()
        conn.execute(
            "INSERT INTO product (id, name, chebi_id, formula, carbon_number, canonical_unit, "
            "zone, evidence, confidence) VALUES (?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, formula=excluded.formula, "
            "evidence=excluded.evidence, confidence=excluded.confidence",
            (
                identifier,
                name,
                _text(row.get("chebi_id")),
                _text(row.get("formula")),
                int(carbon) if carbon.isdigit() else None,
                _text(row.get("canonical_unit")),
                _text(row.get("evidence")) or f"{PRODUCTS_FILE}, tier={row.get('tier', '?')}",
                _text(row.get("confidence")) or "unverified",
            ),
        )
        written += 1
    return written


def load_theoretical_yields(conn: sqlite3.Connection, settings: Settings) -> int:
    """Write one ``product_theoretical_yield`` row per (product, substrate) pair.

    ``state`` is copied into both the mass and molar state columns. A yield whose state is not
    'known' must not be used as a ceiling, and `validate.py` reads the state to decide -- so
    flattening it here would silently turn "sought and unsettled" into a number the validator
    would then enforce.
    """
    written = 0
    for row in read_tsv(_vocabularies_dir(settings) / YIELDS_FILE):
        product = _text(row.get("product_id"))
        substrate = _text(row.get("substrate"))
        if product is None or substrate is None:
            raise VocabularyError(f"{YIELDS_FILE}: a row has no product_id or substrate: {row}")
        state = _text(row.get("state")) or "unknown"
        conn.execute(
            "INSERT INTO product_theoretical_yield (product_id, substrate, g_per_g, "
            "g_per_g_state, mol_per_mol, mol_per_mol_state, stoichiometry, zone, evidence, "
            "confidence) VALUES (?,?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(product_id, substrate) DO UPDATE SET g_per_g=excluded.g_per_g, "
            "g_per_g_state=excluded.g_per_g_state, mol_per_mol=excluded.mol_per_mol, "
            "mol_per_mol_state=excluded.mol_per_mol_state, evidence=excluded.evidence",
            (
                product,
                substrate,
                _number(row.get("g_per_g")),
                state,
                _number(row.get("mol_per_mol")),
                state,
                _text(row.get("stoichiometry")),
                _text(row.get("evidence")) or YIELDS_FILE,
                _text(row.get("confidence")) or "unverified",
            ),
        )
        written += 1
    return written


def load_vocabularies(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Load every vocabulary that has a table, in dependency order, and commit once."""
    counts = {
        "product": load_products(conn, settings),
        "product_theoretical_yield": load_theoretical_yields(conn, settings),
    }
    conn.commit()
    return counts
