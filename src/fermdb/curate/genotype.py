"""Parsing a reported genotype into its parts, and saying so when it cannot.

`schema.sql`'s `genotype` table has carried `as_reported` beside `parsed_json` from the start:
the paper's string is Zone R and never touched, the decomposition is Zone H and rebuilt from it
by recorded code. This module is that code.

It exists because the alternative is worse. Asking a model to emit one `modifications` record per
deletion means ~120 proposals for a single paper's strain table, each needing human review, to
recover information that is already written down unambiguously in a form a parser handles. A
genotype string is not a judgement call -- "Δilv2" means one thing -- so it is harmonisation, not
curation, and CONVENTIONS.md puts that in Zone H.

**The rule that shapes everything here: no token is ever silently dropped.** A parser that
handles "Δilv2; Δbdh1" and quietly ignores "Δpdc1::MTH1" produces a strain that looks fully
characterised and is missing an integration. So every token comes back either parsed or recorded
as unparsed with its text intact, :attr:`ParsedGenotype.fully_parsed` is false whenever anything
failed, and the unparsed text travels in the stored JSON. A caller that wants only clean
genotypes can ask for that; a caller that does not gets the truth either way.

Two spellings of delta appear in real papers and both are handled, because they are different
characters and the difference is invisible: U+0394 GREEK CAPITAL LETTER DELTA and U+2206
INCREMENT. Wess et al. use both, in the same table, sometimes in the same row.

Plasmid-borne genotypes (``BY4741/pATP426-kivd-ADH6-ILV2/pILV532cytM``) are a different notation
entirely, and are recognised as episomal parts rather than forced into the deletion grammar.
Where the notation is not recognised at all the token is returned unparsed, which is the honest
outcome and the one that shows up in a report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "DELTA_CHARACTERS",
    "GenotypePart",
    "ParsedGenotype",
    "parse_genotype",
]

#: Both characters papers use for a deletion prefix. They look identical and are not.
DELTA_CHARACTERS: Final[str] = "Δ∆"  # Δ (Greek capital delta), ∆ (increment)

_DELTA_CLASS: Final[str] = f"[{DELTA_CHARACTERS}]"

#: ``Δpdc1::MTH1`` -- a deletion that simultaneously integrates something at the locus.
_DELETION_WITH_INSERT: Final[re.Pattern[str]] = re.compile(
    rf"^{_DELTA_CLASS}\s*([A-Za-z][A-Za-z0-9_-]*)\s*::\s*([A-Za-z0-9_.-]+)$"
)

#: ``Δmth1(+169; +393)`` -- a deletion qualified by coordinates or an allele note.
_DELETION_WITH_DETAIL: Final[re.Pattern[str]] = re.compile(
    rf"^{_DELTA_CLASS}\s*([A-Za-z][A-Za-z0-9_-]*)\s*\((.+)\)$"
)

#: ``Δilv2`` or ``ilv2Δ`` -- papers put the delta on either side.
_DELETION: Final[re.Pattern[str]] = re.compile(
    rf"^(?:{_DELTA_CLASS}\s*([A-Za-z][A-Za-z0-9_-]*)|([A-Za-z][A-Za-z0-9_-]*)\s*{_DELTA_CLASS})$"
)

#: ``pATP426-kivd-ADH6-ILV2`` -- a plasmid and what it carries.
_PLASMID: Final[re.Pattern[str]] = re.compile(r"^(p[A-Z][A-Za-z0-9]*)(?:-(.+))?$")

#: A bare strain or marker name: ``BY4741``, ``MATa``, ``SUC2``, ``MAL2-8c``.
_BARE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class GenotypePart:
    """One token of a genotype, parsed or not.

    ``kind`` is one of ``deletion``, ``deletion_with_insertion``, ``plasmid``, ``background``,
    ``marker`` or ``unparsed``. The last is not a failure to report elsewhere -- it is a value,
    and it keeps ``as_reported`` so nothing is lost.
    """

    as_reported: str
    kind: str
    target: str | None = None
    inserted: str | None = None
    detail: str | None = None
    carries: tuple[str, ...] = ()

    @property
    def parsed(self) -> bool:
        return self.kind != "unparsed"

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"as_reported": self.as_reported, "kind": self.kind}
        for key, value in (
            ("target", self.target),
            ("inserted", self.inserted),
            ("detail", self.detail),
        ):
            if value is not None:
                payload[key] = value
        if self.carries:
            payload["carries"] = list(self.carries)
        return payload


@dataclass(frozen=True)
class ParsedGenotype:
    """A genotype broken into parts, with whatever could not be broken down left visible."""

    as_reported: str
    parts: tuple[GenotypePart, ...]

    @property
    def fully_parsed(self) -> bool:
        return all(part.parsed for part in self.parts)

    @property
    def unparsed(self) -> tuple[GenotypePart, ...]:
        return tuple(part for part in self.parts if not part.parsed)

    @property
    def deletions(self) -> tuple[str, ...]:
        """Gene symbols deleted, upper-cased. Includes deletion-with-insertion targets.

        Upper-cased because papers write the deleted allele lower case (``Δilv2``) and the gene
        upper case (``ILV2``), and these are the same gene -- which is the whole point of joining
        them to `gene_group` later.
        """
        return tuple(
            part.target.upper()
            for part in self.parts
            if part.target and part.kind in {"deletion", "deletion_with_insertion"}
        )

    @property
    def plasmids(self) -> tuple[str, ...]:
        return tuple(part.target for part in self.parts if part.kind == "plasmid" and part.target)

    def as_json(self) -> dict[str, Any]:
        return {
            "as_reported": self.as_reported,
            "fully_parsed": self.fully_parsed,
            "parts": [part.as_json() for part in self.parts],
            "deletions": list(self.deletions),
            "plasmids": list(self.plasmids),
            "unparsed": [part.as_reported for part in self.unparsed],
        }


def _split(genotype: str) -> list[str]:
    """Tokens, on ``;`` then ``/``.

    Semicolons separate modifications (``Δilv2; Δbdh1``) and slashes separate a background from
    the plasmids it carries (``BY4741/pATP426-x/pILV532cytM``). Commas are deliberately NOT
    separators: ``Δmth1(+169; +393)`` shows that a qualifier can contain a semicolon, so splitting
    happens outside parentheses only.
    """
    tokens: list[str] = []
    depth = 0
    current = ""
    for char in genotype:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char in ";/" and depth == 0:
            tokens.append(current)
            current = ""
        else:
            current += char
    tokens.append(current)
    return [token.strip() for token in tokens if token.strip()]


def _parse_token(token: str, *, first: bool) -> tuple[GenotypePart, ...]:
    """The parts one token yields -- usually one, occasionally two.

    The whole token is tried first. Only if that fails, and the token contains whitespace, is a
    space split attempted -- ``BY4741 lpd1Δ`` is a background and a deletion written as one
    slash-token. Trying the split first would break ``Δmth1(+169; +393)``, whose qualifier
    contains a space.

    The split is accepted **only** when at least one half is a deletion or a plasmid. Every bare
    word matches the marker pattern, so accepting it unconditionally would turn an unparseable
    phrase into a tidy-looking list of "markers" -- which is the one outcome this module exists
    to prevent.
    """
    whole = _parse_one(token, first=first)
    if whole.parsed:
        return (whole,)
    parts = token.split()
    if len(parts) > 1:
        sub = [_parse_one(piece, first=first and index == 0) for index, piece in enumerate(parts)]
        if any(p.kind in {"deletion", "deletion_with_insertion", "plasmid"} for p in sub):
            return tuple(sub)
    return (GenotypePart(as_reported=token, kind="unparsed"),)


def _parse_one(token: str, *, first: bool) -> GenotypePart:
    match = _DELETION_WITH_INSERT.match(token)
    if match:
        return GenotypePart(
            as_reported=token,
            kind="deletion_with_insertion",
            target=match.group(1),
            inserted=match.group(2),
        )

    match = _DELETION_WITH_DETAIL.match(token)
    if match:
        return GenotypePart(
            as_reported=token,
            kind="deletion",
            target=match.group(1),
            detail=match.group(2).strip(),
        )

    match = _DELETION.match(token)
    if match:
        return GenotypePart(
            as_reported=token, kind="deletion", target=match.group(1) or match.group(2)
        )

    match = _PLASMID.match(token)
    if match:
        carried = match.group(2)
        return GenotypePart(
            as_reported=token,
            kind="plasmid",
            target=match.group(1),
            carries=tuple(carried.split("-")) if carried else (),
        )

    if _BARE.match(token):
        # The leading bare token is the background strain; a later one is a marker or allele.
        # Positional, because that is the only thing distinguishing "BY4741" from "SUC2" without
        # a strain registry to check against -- and guessing from a registry would be the
        # nearest-plausible-match error CONVENTIONS.md forbids.
        return GenotypePart(
            as_reported=token, kind="background" if first else "marker", target=token
        )

    return GenotypePart(as_reported=token, kind="unparsed")


def parse_genotype(genotype: str) -> ParsedGenotype:
    """Break a reported genotype into parts, keeping anything unrecognised as ``unparsed``.

    Never raises on unfamiliar notation: a genotype this does not understand is a fact about the
    corpus worth reporting, not an error worth aborting an import for. An empty or whitespace
    string comes back with no parts and ``fully_parsed`` true, which is correct -- there was
    nothing to fail on.
    """
    tokens = _split(genotype)
    return ParsedGenotype(
        as_reported=genotype,
        parts=tuple(
            part
            for index, token in enumerate(tokens)
            for part in _parse_token(token, first=index == 0)
        ),
    )
