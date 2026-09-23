"""One identifier resolver for every bulk annotation file, because each one keys differently.

The atlas keys functional annotation on `gene_annotation.gene_group_id`, and a gene group is
anchored on the *S. cerevisiae* S288C systematic name (`YAA:GG:ymr303c`, per
docs/reference/CONVENTIONS.md "Gene identity"). Not one of the whole-proteome files this package
parses uses that key:

| file                | keys on                                              |
|---------------------|------------------------------------------------------|
| GAF 2.2 (SGD)       | SGDID (`S000003381`) + gene symbol (`GPC1`)          |
| SGD_features.tab    | SGDID, systematic name, standard name, alias list    |
| UniProt TSV export  | UniProt accession (`P39522`)                         |
| KEGG `list`/`link`  | `sce:YMR303C`                                        |
| InterPro / Pfam     | UniProt accession, via the UniProt export's xrefs    |

So every parser in `bulk.py` hands its raw identifiers to a :class:`IdentifierResolver` built from
the bulk files themselves. SGD_features.tab supplies SGDID -> systematic name and the alias list;
the UniProt export supplies UniProt accession -> systematic name (its `Gene Names (ordered locus)`
column *is* the systematic name) and accession -> SGDID; the GAF's own synonym column carries the
systematic name beside the symbol. Between them nothing external is needed.

**Two rules this class exists to enforce, and both are the reason it is a class and not a dict.**

*Refuse ambiguity rather than resolve it.* A gene symbol is not unique across the genome -- an
alias retired from one ORF and reused as a synonym of another maps to two systematic names, and
picking either one silently attaches somebody's GO term to the wrong gene forever. CONVENTIONS.md
is explicit ("An identifier that cannot be resolved is recorded as `UNRESOLVED:<as-written>`,
never mapped to the nearest plausible match"), and since `gene_annotation.gene_group_id` is a
NOT NULL foreign key there is nowhere to *write* `UNRESOLVED:`, so the honest equivalent is: drop
the row, count it, and name it in the report. :meth:`IdentifierResolver.resolve_any` will use a
stronger identifier on the same record when one is present -- an unambiguous SGDID beside an
ambiguous symbol is not a guess -- but it records the ambiguity either way, so that "this symbol
is not usable on its own" stays visible even on the records it did not cost anything.

*Count every miss.* A loader that quietly discards 30% of its input is worse than one that fails,
because the 70% looks complete. :class:`ResolutionReport` counts by identifier kind and by reason,
keeps a bounded sample of the actual identifiers that missed, and renders
:meth:`ResolutionReport.summary` for a human. Nothing in this module logs, prints or raises on a
miss -- the caller decides -- but nothing can miss without being counted either.

Nothing here touches a database, a file or the network. `bulk.py` builds the resolver from parsed
records; this module only defines what a resolution means.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Literal, get_args

from ..omics.genes import gene_group_id

__all__ = [
    "IDENTIFIER_KINDS",
    "RESOLUTION_PRIORITY",
    "IdentifierKind",
    "IdentifierResolver",
    "ResolutionFailure",
    "ResolutionReport",
    "normalize_identifier",
]

#: The identifier spaces the bulk files between them actually use. Deliberately closed: a new one
#: means a new bridge has to be built and evidenced, not a new string quietly accepted.
IdentifierKind = Literal["systematic_name", "sgdid", "symbol", "uniprot", "kegg", "locus_tag"]

IDENTIFIER_KINDS: Final[tuple[IdentifierKind, ...]] = get_args(IdentifierKind)

#: Strongest first. `resolve_any` walks this order and takes the first identifier on the record
#: that resolves to exactly one systematic name. The ordering is a statement about how many
#: assumptions each bridge makes: a systematic name IS the anchor; an SGDID is a stable primary
#: key SGD itself assigns; a UniProt accession is stable and cross-referenced by SGD both ways; a
#: KEGG `sce:` id is the systematic name with a prefix; a locus tag is the systematic name for
#: this assembly but is not guaranteed to be for another; a gene symbol is a human-facing label
#: that has been reused and is last for exactly that reason.
RESOLUTION_PRIORITY: Final[tuple[IdentifierKind, ...]] = (
    "systematic_name",
    "sgdid",
    "uniprot",
    "kegg",
    "locus_tag",
    "symbol",
)


def normalize_identifier(identifier: str, kind: IdentifierKind) -> str:
    """The comparison form for `identifier` in space `kind`.

    Case-folding to upper is safe in every one of these spaces (they are all case-insensitive
    ASCII by construction), and the prefix stripping handles the three forms the real files
    actually mix: a GAF writes `UniProtKB:P48236` in column 17 but `SGD` and `S000003381` as two
    separate columns, a UniProt TSV writes the same accession bare, and a GO cross-reference
    writes `SGD:S000003381` with the prefix attached. Normalising here rather than at each call
    site is what keeps those three from being three different keys.
    """
    text = identifier.strip().upper()
    if kind == "sgdid" and text.startswith("SGD:"):
        text = text[len("SGD:") :]
    elif kind == "uniprot" and text.startswith("UNIPROTKB:"):
        text = text[len("UNIPROTKB:") :]
    if kind == "uniprot" and "-" in text:
        # `P39522-2` is an isoform of `P39522`. The annotation belongs to the gene either way.
        text = text.split("-", 1)[0]
    return text


@dataclass(frozen=True)
class ResolutionFailure:
    """One identifier that did not reach a systematic name, and why.

    `candidates` is non-empty only for `reason == "ambiguous"`, and holds every systematic name
    the identifier could have meant -- the point being that a reader of the report can see what
    the collision actually was rather than only that there was one.
    """

    kind: IdentifierKind
    identifier: str
    reason: Literal["unknown", "ambiguous"]
    candidates: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.reason == "ambiguous":
            return (
                f"{self.kind} {self.identifier!r} -> {len(self.candidates)} candidates: "
                + ", ".join(self.candidates)
            )
        return f"{self.kind} {self.identifier!r} -> not in any bulk file"


class ResolutionReport:
    """What resolved, what did not, and enough of the misses to act on.

    Counts are exact; examples are capped at `example_limit` per (kind, reason) bucket, because a
    proteome-scale run can miss tens of thousands of identifiers and a report nobody can read is a
    report nobody reads.
    """

    def __init__(self, *, example_limit: int = 10) -> None:
        self._example_limit = example_limit
        self._resolved: Counter[IdentifierKind] = Counter()
        self._failed: Counter[tuple[IdentifierKind, str]] = Counter()
        self._examples: dict[tuple[IdentifierKind, str], list[ResolutionFailure]] = {}
        #: Every ambiguous lookup seen, INCLUDING the ones a stronger identifier on the same
        #: record rescued. Keyed by (kind, identifier) so a symbol colliding a thousand times is
        #: one entry, not a thousand.
        self._ambiguities: dict[tuple[IdentifierKind, str], tuple[str, ...]] = {}

    def record_resolved(self, kind: IdentifierKind) -> None:
        self._resolved[kind] += 1

    def record_failure(self, failure: ResolutionFailure) -> None:
        key = (failure.kind, failure.reason)
        self._failed[key] += 1
        bucket = self._examples.setdefault(key, [])
        if len(bucket) < self._example_limit:
            bucket.append(failure)

    def record_ambiguity(
        self, kind: IdentifierKind, identifier: str, candidates: Sequence[str]
    ) -> None:
        """Note a collision whether or not it cost a row. See `_ambiguities`."""
        self._ambiguities.setdefault((kind, identifier), tuple(candidates))

    @property
    def total_resolved(self) -> int:
        return sum(self._resolved.values())

    @property
    def total_failed(self) -> int:
        return sum(self._failed.values())

    def resolved_by_kind(self) -> dict[IdentifierKind, int]:
        return dict(self._resolved)

    def failed_by_kind(self) -> dict[tuple[IdentifierKind, str], int]:
        return dict(self._failed)

    def failure_count(self, kind: IdentifierKind, reason: str) -> int:
        return self._failed[(kind, reason)]

    def examples(self, kind: IdentifierKind, reason: str) -> tuple[ResolutionFailure, ...]:
        return tuple(self._examples.get((kind, reason), ()))

    def ambiguities(self) -> dict[tuple[IdentifierKind, str], tuple[str, ...]]:
        return dict(self._ambiguities)

    def summary(self) -> str:
        """A human-readable block. Always states the unresolved count, even when it is zero."""
        lines = [
            f"identifier resolution: {self.total_resolved} resolved, {self.total_failed} unresolved"
        ]
        for kind in IDENTIFIER_KINDS:
            count = self._resolved.get(kind, 0)
            if count:
                lines.append(f"  resolved via {kind}: {count}")
        for (kind, reason), count in sorted(self._failed.items(), key=lambda item: -item[1]):
            lines.append(f"  UNRESOLVED {kind} ({reason}): {count}")
            for example in self._examples.get((kind, reason), ())[:3]:
                lines.append(f"    e.g. {example}")
        if self._ambiguities:
            lines.append(f"  ambiguous identifiers seen: {len(self._ambiguities)}")
            for (kind, identifier), candidates in sorted(self._ambiguities.items())[:3]:
                lines.append(f"    {kind} {identifier!r} -> {', '.join(candidates)}")
        return "\n".join(lines)


class IdentifierResolver:
    """{SGDID, UniProt accession, gene symbol, KEGG id, locus tag} -> systematic name -> group id.

    Built by `learn`-ing from parsed bulk records (see `bulk.py`'s `learn_from_*` functions), then
    queried by every row generator in `bulk.py` and by tests. Learning is additive and idempotent:
    the same record may be learned from two files, and an identifier that genuinely maps to two
    different systematic names becomes ambiguous rather than last-write-wins.
    """

    def __init__(self) -> None:
        self._index: dict[IdentifierKind, dict[str, set[str]]] = {
            kind: {} for kind in IDENTIFIER_KINDS
        }

    # -- building -----------------------------------------------------------------------------

    def learn(
        self,
        systematic_name: str,
        *,
        sgdids: Iterable[str] = (),
        symbols: Iterable[str] = (),
        uniprot_accessions: Iterable[str] = (),
        kegg_ids: Iterable[str] = (),
        locus_tags: Iterable[str] = (),
    ) -> None:
        """Record that every identifier given names the gene whose systematic name is
        `systematic_name`.

        The systematic name is indexed under its own kind too, so that a file which already
        carries it (the GAF's synonym column, UniProt's ordered-locus column) resolves through the
        same path as everything else instead of a special case at each call site.
        """
        anchor = normalize_identifier(systematic_name, "systematic_name")
        if not anchor:
            return
        self._add("systematic_name", anchor, anchor)
        for sgdid in sgdids:
            self._add("sgdid", sgdid, anchor)
        for symbol in symbols:
            self._add("symbol", symbol, anchor)
        for accession in uniprot_accessions:
            self._add("uniprot", accession, anchor)
        for kegg_id in kegg_ids:
            self._add("kegg", kegg_id, anchor)
        for locus_tag in locus_tags:
            self._add("locus_tag", locus_tag, anchor)

    def _add(self, kind: IdentifierKind, identifier: str, systematic_name: str) -> None:
        key = normalize_identifier(identifier, kind)
        if not key:
            return
        if kind == "symbol" and key == systematic_name:
            # A standard name equal to the systematic name carries no information and would make
            # every ORF without a standard name look like a symbol collision waiting to happen.
            return
        self._index[kind].setdefault(key, set()).add(systematic_name)

    @property
    def known_systematic_names(self) -> frozenset[str]:
        return frozenset(self._index["systematic_name"])

    def __len__(self) -> int:
        return len(self._index["systematic_name"])

    def candidates(self, identifier: str, kind: IdentifierKind) -> tuple[str, ...]:
        """Every systematic name `identifier` could mean, sorted. Empty when it is unknown."""
        key = normalize_identifier(identifier, kind)
        if kind == "kegg":
            # `sce:YMR303C` -- the organism prefix is KEGG's, the rest is the systematic name.
            # Indexed under both, so a bare `YMR303C` in a KEGG column resolves too.
            bare = key.split(":", 1)[1] if ":" in key else key
            direct = self._index["kegg"].get(key)
            if direct:
                return tuple(sorted(direct))
            return tuple(sorted(self._index["systematic_name"].get(bare, ())))
        return tuple(sorted(self._index[kind].get(key, ())))

    # -- querying -----------------------------------------------------------------------------

    def resolve(
        self,
        identifier: str,
        kind: IdentifierKind,
        *,
        report: ResolutionReport | None = None,
    ) -> str | None:
        """The one systematic name `identifier` means, or `None` if it is unknown or ambiguous.

        `None` is returned for both reasons on purpose -- the caller must not act differently on
        them, because in both cases the atlas does not know which gene this is. `report` is where
        the difference is kept.
        """
        found = self.candidates(identifier, kind)
        if len(found) == 1:
            if report is not None:
                report.record_resolved(kind)
            return found[0]
        if len(found) > 1:
            if report is not None:
                report.record_ambiguity(kind, normalize_identifier(identifier, kind), found)
                report.record_failure(
                    ResolutionFailure(
                        kind=kind,
                        identifier=normalize_identifier(identifier, kind),
                        reason="ambiguous",
                        candidates=found,
                    )
                )
            return None
        if report is not None:
            report.record_failure(
                ResolutionFailure(
                    kind=kind,
                    identifier=normalize_identifier(identifier, kind),
                    reason="unknown",
                )
            )
        return None

    def resolve_any(
        self,
        candidates: Sequence[tuple[IdentifierKind, str]],
        *,
        report: ResolutionReport | None = None,
    ) -> str | None:
        """The systematic name for a record carrying several identifiers, strongest first.

        `candidates` is `(kind, identifier)` pairs in any order; they are walked in
        `RESOLUTION_PRIORITY` order and the FIRST that resolves to exactly one systematic name is
        the answer. Every candidate is looked at even after a winner is found, so that an
        ambiguity a stronger identifier happened to rescue still lands in
        `ResolutionReport.record_ambiguity` -- "this symbol is not usable on its own" stays true
        whether or not it cost a row this time, and the extra work is a handful of dict lookups.

        At most ONE failure is counted per record, because a GAF line carrying four identifiers
        would otherwise inflate the unresolved count fourfold. When the record failed and any
        candidate was ambiguous, the AMBIGUOUS one is what gets counted even if a stronger
        identifier was merely unknown: "the atlas knows these names and cannot choose between
        them" is a more specific, more actionable diagnosis than "never heard of it", and it is
        the one a curator can fix.
        """
        ordered = sorted(
            ((kind, value) for kind, value in candidates if value and value.strip()),
            key=lambda pair: RESOLUTION_PRIORITY.index(pair[0]),
        )
        resolved: tuple[IdentifierKind, str] | None = None
        ambiguous: list[ResolutionFailure] = []
        unknown: list[ResolutionFailure] = []
        for kind, value in ordered:
            found = self.candidates(value, kind)
            normalized = normalize_identifier(value, kind)
            if len(found) == 1:
                if resolved is None:
                    resolved = (kind, found[0])
                continue
            if len(found) > 1:
                if report is not None:
                    report.record_ambiguity(kind, normalized, found)
                ambiguous.append(
                    ResolutionFailure(
                        kind=kind, identifier=normalized, reason="ambiguous", candidates=found
                    )
                )
            else:
                unknown.append(
                    ResolutionFailure(kind=kind, identifier=normalized, reason="unknown")
                )
        if resolved is not None:
            if report is not None:
                report.record_resolved(resolved[0])
            return resolved[1]
        if report is not None:
            failures = ambiguous or unknown
            if failures:
                report.record_failure(failures[0])
        return None

    def gene_group_id_for(
        self,
        candidates: Sequence[tuple[IdentifierKind, str]],
        *,
        report: ResolutionReport | None = None,
    ) -> str | None:
        """`resolve_any`, then `YMR303C` -> `YAA:GG:ymr303c`.

        The slug rule lives in `fermdb.omics.genes.gene_group_id` and is imported rather than
        repeated: two places spelling a CURIE is how two places come to spell it differently.
        """
        systematic_name = self.resolve_any(candidates, report=report)
        if systematic_name is None:
            return None
        return gene_group_id(systematic_name)

    def ambiguous_identifiers(self, kind: IdentifierKind) -> Iterator[tuple[str, tuple[str, ...]]]:
        """Every identifier of `kind` that maps to more than one systematic name.

        Exposed so a caller can audit the collision set up front -- "which symbols are unusable in
        this genome" is a question worth answering before a load, not after it.
        """
        for identifier, names in sorted(self._index[kind].items()):
            if len(names) > 1:
                yield identifier, tuple(sorted(names))
