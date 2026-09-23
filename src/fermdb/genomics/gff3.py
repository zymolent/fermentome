"""Stream an NCBI RefSeq GFF3 into one record per gene.

**Coordinates: the file is 1-based inclusive, this module emits 0-based half-open, and that is
not a preference.** `docs/reference/CONVENTIONS.md` ("Coordinates and sequence") fixes 0-based
half-open `[start, end)` for the database, the API and all internal code, and allows exactly two
places to convert: a parser on the way in and a formatter on the way out. This is one of the two.
`_half_open` subtracts one from the start and leaves the end alone; length is `end - start`,
never `end - start + 1`.

The 36 rows already in `gene` were written by `fermdb.omics.genes.parse_location`, which does the
identical thing to an INSDC location string (`min(starts) - 1, max(ends)`), and a copy of the
atlas confirms the result rather than the intention: every one of those 36 rows has
`(end_pos - start_pos) % 3 == 0`. Each is a single-CDS ORF, so its stored length is the coding
length including the stop codon -- a multiple of three. Stored 1-based inclusive the difference
would be `length - 1` and no row would be divisible by three. YMR083W/ADH3 is stored as
`434787..435915` against a RefSeq location of `434788..435915`. One base out on 6,600 genes would
frame-shift every downstream sequence extraction and silently misplace every interval join, so
the convention is asserted here by test rather than trusted.

**Strand is an integer.** `+1` forward, `-1` reverse, `0` unknown -- never `"+"`/`"-"` outside
this module. GFF3's fourth strand token `?` ("stranded but unknown") and `.` ("not stranded") both
become `0`: the schema's CHECK admits three values and the distinction between them is not one the
atlas can act on. That is a real loss and it is recorded here rather than hidden in a mapping.

**Why it streams, and what "streams" actually costs.** The S288C GFF3 is ~400k lines and the
bacterial ones are larger; reading one into a list to filter it is a habit that stops working at
the first vertebrate genome and teaches nothing in the meantime. But a gene's `product`, its exon
count and its CDS count live on its *children*, which appear after it -- so a gene cannot be
emitted the instant it is read. This module therefore holds open only the genes that could still
gain a child, and flushes one as soon as that becomes impossible:

* on `###`, the spec's "everything before this point is resolved" directive, which NCBI emits
  after every gene's feature group -- so against a real RefSeq file the working set is one gene;
* when the sequence changes, since a child never crosses a seqid;
* when a feature begins past an open gene's end. Features are position-sorted within a sequence
  and a child lies within its parent, so nothing later can belong to it. This rule is what keeps
  a file with no `###` at all from accumulating a whole chromosome.

**URL escaping is undone after splitting, not before.** GFF3 separates multiple values with a
comma and escapes a literal one as `%2C`; unescaping first would split
`product=aldehyde dehydrogenase%2C mitochondrial` into two products. The same argument applies to
`%3B` and `%3D`. Getting this backwards is the classic GFF3 parser bug and it is silent.

**A pseudogene is a gene here.** RefSeq gives pseudogenes the feature type `pseudogene`, not
`gene`, so a parser that keys on `type == "gene"` drops every one of them without a word -- and
the count it reports still looks plausible.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TextIO
from urllib.parse import unquote

__all__ = [
    "GENE_FEATURE_TYPES",
    "GeneRecord",
    "Gff3Error",
    "iter_gene_records",
    "open_gff3",
    "parse_attributes",
    "parse_gene_records",
    "parse_strand",
]


class Gff3Error(ValueError):
    """A GFF3 line is malformed. Raised rather than skipped: a silently dropped gene is a gap
    that looks exactly like a real absence."""


#: The feature types that are a gene. `pseudogene` is here because RefSeq uses it as a top-level
#: type in its own right -- see the module docstring.
GENE_FEATURE_TYPES: Final[frozenset[str]] = frozenset({"gene", "pseudogene"})

#: Child types that carry the `product=` string worth promoting onto the gene. Deliberately a
#: set of *types* rather than "anything with a product": a `region` feature has attributes too.
_PRODUCT_BEARING_TYPES: Final[frozenset[str]] = frozenset(
    {
        "mRNA",
        "CDS",
        "tRNA",
        "rRNA",
        "ncRNA",
        "snoRNA",
        "snRNA",
        "tmRNA",
        "RNase_P_RNA",
        "SRP_RNA",
        "antisense_RNA",
        "transcript",
        "primary_transcript",
        "precursor_RNA",
        "telomerase_RNA",
        "guide_RNA",
        "rnase_MRP_RNA",
        "RNase_MRP_RNA",
        "Y_RNA",
        "V_gene_segment",
        "C_gene_segment",
    }
)

_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "TRUE", "True"})


@dataclass(frozen=True)
class GeneRecord:
    """One gene feature plus everything its children said about it.

    Coordinates are 0-based half-open; `strand` is `+1`/`-1`/`0`. Every other field is verbatim
    from the file, URL-unescaped, or `None` where the annotation did not state it -- never `''`
    and never `'unknown'`, which mean different things (CONVENTIONS.md, "Missing values").
    """

    seqid: str
    source: str
    feature_type: str
    #: The GFF3 `ID` attribute -- `gene-YMR083W`. Unique within the file; not an atlas id.
    gff_id: str
    locus_tag: str | None
    #: The `Name` attribute. Equal to the locus tag for an unnamed ORF, and different from it
    #: wherever a standard name exists -- `Name=COX1` on `locus_tag=Q0045`.
    name: str | None
    #: The `gene` attribute: the standard name, absent for the ~1,000 S288C ORFs that have none.
    symbol: str | None
    #: RefSeq's `gene_biotype`, verbatim. Not validated against a list; see schema.sql.
    biotype: str | None
    #: The gene's own `description`, else a child's `product`, else the gene's `Note`.
    description: str | None
    ncbi_gene_id: str | None
    sgd_id: str | None
    dbxrefs: tuple[str, ...]
    synonyms: tuple[str, ...]
    start_pos: int
    end_pos: int
    strand: int
    exon_count: int
    cds_count: int
    #: `partial=true` -- the feature runs off the end of the assembled sequence. The stored span
    #: is then a lower bound, which matters before anyone extracts a sequence from it.
    partial: bool
    pseudo: bool
    #: 1-based line number of the gene feature, so an error message can name it.
    line_number: int

    @property
    def length(self) -> int:
        """`end_pos - start_pos`. Never `+ 1` (CONVENTIONS.md)."""
        return self.end_pos - self.start_pos


@dataclass
class _Open:
    """A gene whose children have not all been seen yet."""

    seqid: str
    source: str
    feature_type: str
    gff_id: str
    attributes: dict[str, tuple[str, ...]]
    start_pos: int
    end_pos: int
    strand: int
    line_number: int
    exon_count: int = 0
    cds_count: int = 0
    product: str | None = None
    fallback_product: str | None = None
    child_ids: set[str] = field(default_factory=set)


def parse_strand(token: str) -> int:
    """`'+'` -> `1`, `'-'` -> `-1`, `'.'` / `'?'` -> `0`. Anything else is an error."""
    if token == "+":
        return 1
    if token == "-":
        return -1
    if token in (".", "?"):
        return 0
    raise Gff3Error(f"unparsable strand {token!r}; GFF3 allows only '+', '-', '.' and '?'")


def parse_attributes(column: str) -> dict[str, tuple[str, ...]]:
    """Parse the ninth column into `{tag: (value, ...)}`, unescaped.

    Multi-value tags (`Parent=a,b`, `Dbxref=GeneID:1,SGD:S1`) keep every value. Splitting happens
    **before** unescaping, so an escaped comma inside one value stays inside it -- see the module
    docstring for why that order is the whole ballgame.
    """
    attributes: dict[str, tuple[str, ...]] = {}
    for part in column.split(";"):
        entry = part.strip()
        if not entry:
            continue
        tag, separator, raw = entry.partition("=")
        if not separator:
            raise Gff3Error(f"attribute {entry!r} has no '='; GFF3 column 9 is tag=value pairs")
        key = unquote(tag.strip())
        values = tuple(unquote(value) for value in raw.split(","))
        if key in attributes:
            attributes[key] = attributes[key] + values
        else:
            attributes[key] = values
    return attributes


def _first(attributes: dict[str, tuple[str, ...]], key: str) -> str | None:
    values = attributes.get(key)
    if not values:
        return None
    # A tag present with an empty value is the source declining to say, not a value of ''.
    return values[0] or None


def _half_open(start_field: str, end_field: str, line_number: int) -> tuple[int, int]:
    """1-based inclusive `(start, end)` from the file -> 0-based half-open `[start, end)`.

    One of the two places CONVENTIONS.md permits the conversion. NCBI writes `start_range=.,1807`
    for a partial feature but keeps columns 4 and 5 numeric, so no `<`/`>` handling is needed
    here -- unlike the INSDC location strings `omics.genes.parse_location` reads.
    """
    try:
        start = int(start_field)
        end = int(end_field)
    except ValueError as exc:
        raise Gff3Error(
            f"line {line_number}: non-numeric coordinates {start_field!r}..{end_field!r}"
        ) from exc
    if start < 1 or end < start:
        raise Gff3Error(f"line {line_number}: coordinates {start}..{end} are not 1-based inclusive")
    return start - 1, end


def _describe(attributes: dict[str, tuple[str, ...]], product: str | None) -> str | None:
    """The gene's own `description`, else a child's `product`, else its `Note`.

    In that order because they are different claims: `description` is the annotation's statement
    about the *gene*, `product` about one of its transcripts, `Note` is free commentary. Taking
    the product first would let a single isoform's name stand for the locus.
    """
    return _first(attributes, "description") or product or _first(attributes, "Note")


def _dbxref_value(dbxrefs: tuple[str, ...], prefix: str) -> str | None:
    marker = f"{prefix}:"
    for xref in dbxrefs:
        if xref.startswith(marker):
            return xref[len(marker) :]
    return None


def _finish(pending: _Open) -> GeneRecord:
    attributes = pending.attributes
    dbxrefs = attributes.get("Dbxref", ()) + attributes.get("db_xref", ())
    return GeneRecord(
        seqid=pending.seqid,
        source=pending.source,
        feature_type=pending.feature_type,
        gff_id=pending.gff_id,
        locus_tag=_first(attributes, "locus_tag"),
        name=_first(attributes, "Name"),
        symbol=_first(attributes, "gene"),
        biotype=_first(attributes, "gene_biotype"),
        description=_describe(attributes, pending.product or pending.fallback_product),
        ncbi_gene_id=_dbxref_value(dbxrefs, "GeneID"),
        sgd_id=_dbxref_value(dbxrefs, "SGD"),
        dbxrefs=dbxrefs,
        synonyms=attributes.get("gene_synonym", ()),
        start_pos=pending.start_pos,
        end_pos=pending.end_pos,
        strand=pending.strand,
        exon_count=pending.exon_count,
        cds_count=pending.cds_count,
        partial=(_first(attributes, "partial") or "") in _TRUE_TOKENS,
        # `pseudo=true` on a gene feature, or the feature type itself. RefSeq uses both.
        pseudo=(_first(attributes, "pseudo") or "") in _TRUE_TOKENS
        or pending.feature_type == "pseudogene",
        line_number=pending.line_number,
    )


def parse_gene_records(lines: Iterable[str]) -> Iterator[GeneRecord]:
    """Yield one :class:`GeneRecord` per gene feature.

    Takes any iterable of lines, so a test can pass a list and a caller can pass an open handle
    without either of them knowing about gzip.

    Order is the order genes *close* in, which is file order except where two genes overlap and
    the inner one ends first. Nothing downstream depends on the order -- ids are deterministic --
    and guaranteeing file order would mean holding the outer gene's record back behind the inner
    one, which is the buffering this module exists to avoid.
    """
    open_genes: dict[str, _Open] = {}
    # Maps any feature id (a gene's, an mRNA's, a CDS's) to the gene it descends from, so a
    # grandchild resolves in one lookup instead of by walking the Parent chain twice.
    owner_of: dict[str, str] = {}

    def flush(keys: list[str]) -> Iterator[GeneRecord]:
        for key in keys:
            pending = open_genes.pop(key)
            for child in pending.child_ids:
                owner_of.pop(child, None)
            owner_of.pop(pending.gff_id, None)
            yield _finish(pending)

    for line_number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n").rstrip("\r")
        if not line:
            continue
        if line.startswith("#"):
            directive = line.strip()
            if directive == "###":
                yield from flush(list(open_genes))
            elif directive.startswith("##FASTA"):
                # The spec's end-of-annotation marker: everything after it is sequence.
                break
            continue

        columns = line.split("\t")
        if len(columns) != 9:
            raise Gff3Error(
                f"line {line_number}: {len(columns)} tab-separated columns, GFF3 requires 9"
            )
        seqid, source, feature_type, start_field, end_field, _score, strand_field, _phase, attr = (
            columns
        )
        seqid = unquote(seqid)
        start_pos, end_pos = _half_open(start_field, end_field, line_number)

        # Anything that can no longer gain a child goes out now, before this line is handled, so
        # the working set stays at the genes that overlap the current position.
        stale = [
            key
            for key, pending in open_genes.items()
            if pending.seqid != seqid or start_pos >= pending.end_pos
        ]
        yield from flush(stale)

        attributes = parse_attributes(attr)

        if feature_type in GENE_FEATURE_TYPES:
            gff_id = _first(attributes, "ID") or _first(attributes, "locus_tag")
            if gff_id is None:
                raise Gff3Error(
                    f"line {line_number}: {feature_type} feature has neither ID= nor locus_tag=; "
                    "there is nothing to attach its children to"
                )
            open_genes[gff_id] = _Open(
                seqid=seqid,
                source=unquote(source),
                feature_type=feature_type,
                gff_id=gff_id,
                attributes=attributes,
                start_pos=start_pos,
                end_pos=end_pos,
                strand=parse_strand(strand_field),
                line_number=line_number,
            )
            owner_of[gff_id] = gff_id
            continue

        parents = attributes.get("Parent", ())
        owner_key = next((owner_of[p] for p in parents if p in owner_of), None)
        if owner_key is None:
            # A `region` feature, a standalone `mobile_genetic_element`, or a child whose gene has
            # already been flushed. None of them is an error; only a gene's own attributes and the
            # children that reach it are this module's business.
            continue
        pending = open_genes[owner_key]
        own_id = _first(attributes, "ID")
        if own_id is not None:
            owner_of[own_id] = owner_key
            pending.child_ids.add(own_id)
        if feature_type == "exon":
            pending.exon_count += 1
        elif feature_type == "CDS":
            pending.cds_count += 1
        if feature_type in _PRODUCT_BEARING_TYPES:
            if pending.product is None:
                pending.product = _first(attributes, "product")
        elif pending.fallback_product is None:
            # An `exon` or a bare `CDS` carries a product too. It is only consulted when no
            # transcript-level feature offered one -- a pseudogene's lone exon is the case that
            # needs it -- because a transcript's own product is the better-typed statement.
            pending.fallback_product = _first(attributes, "product")

    yield from flush(list(open_genes))


def open_gff3(path: str | Path) -> TextIO:
    """Open a GFF3, gzipped or not, as text. Decided by the magic bytes, not the file name.

    RefSeq ships `*.gff.gz`; a fixture is easier to review uncompressed; and a file renamed by a
    download script is exactly the case a suffix check gets wrong.
    """
    location = Path(path)
    with open(location, "rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(location, "rt", encoding="utf-8")
    return open(location, encoding="utf-8")


def iter_gene_records(path: str | Path) -> Iterator[GeneRecord]:
    """Yield every gene in a (optionally gzipped) GFF3 without holding the file in memory."""
    with open_gff3(path) as handle:
        yield from parse_gene_records(handle)
