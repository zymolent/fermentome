"""Narrow one paper's excerpt to the passages that can support a record.

Reading a 50,000-character excerpt to find four numbers is the expensive part of extraction, and
the cost is the same whether a human or a model does the reading. This prints only the passages
that could carry a strain, a modification, a titre or a condition.

**It narrows what is read, not what may be quoted.** Every span in a payload has to re-resolve
against the full excerpt, so a quote taken from a passage printed here is checked against the
document exactly as any other is. Nothing is quoted that was not seen, and nothing is accepted
because it was convenient to find.

The titre filter is the part worth explaining. A methods section is full of "20 g/L glucose" and
"10 g/L yeast extract", which match any pattern for a number beside a mass concentration; a naive
filter returns the medium recipe and buries the four numbers that matter. So a number only counts
as a candidate measurement when a product word sits within ~110 characters of it, on either side.
That still admits medium lines mentioning a product, which is the right direction to err: a
reader discards a false positive in a second, and never sees a false negative at all.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from ..config import Settings
from .harness import (
    DEFAULT_EXTRACTION_SECTIONS,
    build_excerpt,
    load_source_text,
    split_sections,
)

__all__ = ["SECTIONS", "BriefSection", "build_brief"]

#: A number followed by a unit this atlas records, tolerating a "± sd" between them.
_QUANTITY: Final[str] = (
    r"\d+(?:\.\d+)?\s*(?:±\s*\d+(?:\.\d+)?\s*)?"
    r"(?:g\s*/\s*L|mg\s*/\s*L|g\s*/\s*g|mg\s*/\s*g|mol\s*/\s*mol|%\s*\(?v/v\)?|g/L/h)"
)

#: Words that make a nearby number a candidate product measurement rather than a medium component.
_PRODUCT: Final[str] = (
    r"(?:isobutanol|isobutyl|ethanol|butanol|titer|titre|yield|productivity|produced|production)"
)

SECTIONS: Final[tuple[tuple[str, str, int], ...]] = (
    (
        "PRODUCT TITRES AND YIELDS",
        rf"(?:{_PRODUCT}[^.]{{0,110}}?{_QUANTITY}|{_QUANTITY}[^.]{{0,110}}?{_PRODUCT})",
        16,
    ),
    (
        "STRAINS AND GENOTYPES",
        r"(?:^|\n)[A-Za-z][A-Za-z0-9\-\.]{1,18}\s*\|[^\n]{0,150}",
        18,
    ),
    (
        "MODIFICATIONS",
        r"(?:overexpress\w*|deletion|deleted|knock\w*|disrupt\w*|Δ|∆|heterolog\w*|"
        r"codon.optimi\w*|CRISPR|integrat\w*|episom\w*|plasmid)",
        12,
    ),
    (
        "CONDITIONS",
        r"(?:aerobic|anaerobic|micro-?aerobic|YPD|YNB|SD medium|minimal medium|"
        r"fed-?batch|bioreactor|shake.flask|°C|rpm|pH\s*\d)",
        10,
    ),
    (
        "BOTTLENECKS AND LIMITS",
        r"(?:bottleneck|rate-?limiting|limiting step|accumulat\w+|toxic\w*|inhibit\w*|"
        r"below the (?:detection|quantification) limit|not exceeding)",
        10,
    ),
)


@dataclass(frozen=True)
class BriefSection:
    title: str
    passages: tuple[str, ...]


def _passages(text: str, pattern: str, limit: int, window: int = 150) -> Iterator[str]:
    """Deduplicated windows around each match, in document order."""
    seen: set[str] = set()
    for match in re.finditer(pattern, text, re.I | re.M):
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        passage = " ".join(text[start:end].split())
        key = passage[:60]
        if key in seen:
            continue
        seen.add(key)
        yield passage
        if len(seen) >= limit:
            return


def build_brief(
    conn: sqlite3.Connection, settings: Settings, *, publication_id: str
) -> tuple[str, tuple[BriefSection, ...]]:
    """``(excerpt text, sections)``. The excerpt is returned so a caller can verify a quote."""
    text, _ = load_source_text(conn, settings, publication_id=publication_id)
    excerpt = build_excerpt(text, split_sections(text), DEFAULT_EXTRACTION_SECTIONS)
    sections = tuple(
        BriefSection(title=title, passages=tuple(_passages(excerpt.text, pattern, limit)))
        for title, pattern, limit in SECTIONS
    )
    return excerpt.text, sections
