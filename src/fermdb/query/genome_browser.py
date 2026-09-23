"""Browsing a genome: filters, a page that knows its own total, and a karyotype drawn to scale.

`genes.py` serves *one* gene well. It also carries a `list_genes` that returns every gene as an
``(id, name)`` pair, which was an honest shape while the atlas held 36 of them. It stops being
one at ~6,600: a flat list has no way to express "protein-coding genes on chromosome IV with a
KEGG annotation", and a client-side substring filter over 6,600 cards answers a different
question from the one the reader asked -- it filters what was *sent*, which is not what the atlas
*holds* unless the two happen to coincide.

So this module exists beside `genes.py` rather than inside it, and three of its decisions are
worth defending.

**The total is counted, never inferred from the page.** ``total_matching`` is a real
``COUNT(*)`` over the filter. A UI that renders ``rows.length`` says "50 genes" when it means
"the first 50 of 4,812", and a reader has no way to tell those apart. `Page.truncated` says
whether *this page* was cut; ``total_matching`` says how big the answer is. Both travel.

**The annotation count is one grouped query, not one query per gene.** The obvious
implementation -- loop the page, count annotations for each -- is 50 extra queries per page and
6,600 if anything ever asks for everything. It is also invisible in review, because it is
correct. The count here comes from a ``LEFT JOIN`` and a ``GROUP BY``, so it is structurally one
statement and cannot regress into a loop without the shape of this function changing.

**The schema is inspected, not assumed.** `seqid`, `biotype`, `locus_tag` and `description` are
arriving on `gene` in a migration that is being written while this is. A reader that assumes them
500s the entire Annotations page the moment it is deployed a day early, and a reader that assumes
their absence never picks them up. So every column is checked with :func:`_columns_of` -- the same
move `pathways.py` and `search.py` already make -- and each facet reports itself as *blocked on
the pending migration* rather than silently vanishing. "This facet needs a migration that has not
landed" is a true and actionable sentence; an empty dropdown is neither.

One thing this module deliberately does **not** do: recover `seqid` from `gene.evidence`. The
evidence sentence today reads ``... on NC_001145.3 (nuclear-encoded); RefSeq rna_from_genomic
...``, so the accession is right there and a regex would fill the chromosome facet immediately.
`pathways.py` already refused the identical trade for genes in a reaction's evidence string --
"recovering a structured fact from a prose sentence" -- and it is the right refusal: the prose is
Zone R text written for a human, nothing guarantees its shape across loaders, and a browser built
on it would report a chromosome the schema does not actually hold. The facet stays blocked until
the column exists.

Search is ``LIKE '%term%'`` over named columns, exactly as `search.py` does it, and says so in
the payload for the same reason: substring matching is not retrieval, and a caller that mistakes
one for the other over-trusts a recall it does not have.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from .builder import MAX_ROWS, Page, Select
from .values import Absence, Value, Zone

__all__ = [
    "BIN_WIDTH_DEFAULT",
    "ORDERINGS",
    "Facet",
    "FacetValue",
    "FacetsRead",
    "GeneListRead",
    "GeneRow",
    "Karyotype",
    "KaryotypeRead",
    "PositionRead",
    "R64_SEQUENCES",
    "SequenceRef",
    "facets",
    "karyotype",
    "list_genes",
    "read_position",
]


# ------------------------------------------------------------------ the reference karyotype


@dataclass(frozen=True)
class SequenceRef:
    """One sequence of a reference assembly: its accession, its name, and how long it is.

    Length is the point. A karyotype where every chromosome is the same width is a legend, not a
    map -- chromosome IV is 6.6x chromosome I, and a gene-density track that does not say so
    makes a sparse large chromosome look like a dense small one.
    """

    accession: str
    label: str
    roman: str
    ordinal: int
    kind: str
    length: int

    def as_json(self) -> dict[str, Any]:
        return {
            "accession": self.accession,
            "label": self.label,
            "roman": self.roman,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "length": self.length,
        }


#: The 16 nuclear chromosomes and the mitochondrion of the S288C R64 assembly (GCF_000146045.2),
#: with the lengths RefSeq reports for each sequence.
#:
#: These are constants in code rather than rows in a table because the atlas has no table for
#: them: `reference_sequence` holds two rows (the nuclear genome as one file, and the mtDNA), not
#: seventeen. They are checkable against what the atlas *does* record, and that check is a test:
#: `reference_sequence.evidence` for the nuclear reference says "R64 assembly, 17 sequences,
#: 12157105 bases", and these 17 lengths sum to exactly 12,157,105. If the assembly is ever
#: replaced, that sum stops matching and the test says so rather than the page quietly drawing
#: the wrong genome.
R64_SEQUENCES: Final[tuple[SequenceRef, ...]] = (
    SequenceRef("NC_001133.9", "chrI", "I", 1, "nuclear", 230_218),
    SequenceRef("NC_001134.8", "chrII", "II", 2, "nuclear", 813_184),
    SequenceRef("NC_001135.5", "chrIII", "III", 3, "nuclear", 316_620),
    SequenceRef("NC_001136.10", "chrIV", "IV", 4, "nuclear", 1_531_933),
    SequenceRef("NC_001137.3", "chrV", "V", 5, "nuclear", 576_874),
    SequenceRef("NC_001138.5", "chrVI", "VI", 6, "nuclear", 270_161),
    SequenceRef("NC_001139.9", "chrVII", "VII", 7, "nuclear", 1_090_940),
    SequenceRef("NC_001140.6", "chrVIII", "VIII", 8, "nuclear", 562_643),
    SequenceRef("NC_001141.2", "chrIX", "IX", 9, "nuclear", 439_888),
    SequenceRef("NC_001142.9", "chrX", "X", 10, "nuclear", 745_751),
    SequenceRef("NC_001143.9", "chrXI", "XI", 11, "nuclear", 666_816),
    SequenceRef("NC_001144.5", "chrXII", "XII", 12, "nuclear", 1_078_177),
    SequenceRef("NC_001145.3", "chrXIII", "XIII", 13, "nuclear", 924_431),
    SequenceRef("NC_001146.8", "chrXIV", "XIV", 14, "nuclear", 784_333),
    SequenceRef("NC_001147.6", "chrXV", "XV", 15, "nuclear", 1_091_291),
    SequenceRef("NC_001148.4", "chrXVI", "XVI", 16, "nuclear", 948_066),
    SequenceRef("NC_001224.1", "chrM", "M", 17, "mitochondrial", 85_779),
)

#: Every spelling of a sequence a loader might plausibly write, folded to one reference.
#:
#: The migration is specified to store accessions (`NC_001133.9`), but a browser that only
#: understands one spelling degrades to "17 unplaced sequences" the first time an importer writes
#: `chrI` or drops the version suffix -- a total loss of the karyotype for a cosmetic difference.
_ALIASES: Final[dict[str, SequenceRef]] = {}
for _ref in R64_SEQUENCES:
    for _alias in (
        _ref.accession,
        _ref.accession.split(".")[0],
        _ref.label,
        _ref.roman,
        f"chromosome {_ref.roman}",
        f"chr{_ref.roman}",
    ):
        _ALIASES[_alias.casefold()] = _ref
_ALIASES["chrmt"] = R64_SEQUENCES[-1]
_ALIASES["mito"] = R64_SEQUENCES[-1]
_ALIASES["mt"] = R64_SEQUENCES[-1]


def reference_for(seqid: str | None) -> SequenceRef | None:
    """The reference sequence a `seqid` names, or None if it names something else."""
    if not seqid:
        return None
    return _ALIASES.get(seqid.strip().casefold())


def _natural_key(seqid: str) -> tuple[int, str]:
    """Sort key putting chromosome II after I and before XI, with unknowns last, by name.

    Roman numerals do not sort as text -- ``["I", "II", "XI"]`` sorts to ``["I", "II", "XI"]`` by
    luck and ``["IV", "IX", "V"]`` does not. So order comes from the reference table's own
    ordinal, and only a sequence the table does not know falls back to its name.
    """
    ref = reference_for(seqid)
    return (ref.ordinal, "") if ref is not None else (10_000, seqid)


# ------------------------------------------------------------------ schema inspection


#: Columns the pending migration adds to `gene`, with what each one unlocks. The text is the
#: message a blocked facet carries, so it is written for the person reading the page.
_PENDING_COLUMNS: Final[dict[str, str]] = {
    "seqid": (
        "the sequence accession each gene sits on. Until `gene.seqid` exists there is no "
        "chromosome to filter by and no karyotype to draw — the coordinates are held, but not "
        "what they are coordinates *on*"
    ),
    "biotype": (
        "protein_coding / tRNA / pseudogene / …. Until `gene.biotype` exists every gene is "
        "indistinguishable in kind, and a count of 'genes' silently mixes ORFs with tRNAs"
    ),
    "locus_tag": "the systematic locus tag as the source wrote it; searched when present",
    "description": "the source's free-text product description; searched when present",
}


def _columns_of(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    """The column names a table actually has, so a reader can adapt instead of assuming."""
    return frozenset(str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})"))


# ------------------------------------------------------------------ rows


def _text(raw: Any, zone: Zone | None) -> Value[str]:
    if raw is None or str(raw).strip() == "":
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(str(raw), zone=zone)


def _number(raw: Any, zone: Zone | None) -> Value[int]:
    if raw is None:
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known(int(raw), zone=zone)


def _strand(raw: Any, zone: Zone | None) -> Value[str]:
    """`schema.sql` stores -1, 0 or 1. Rendered as the symbols a genome browser uses.

    0 is not absence and must not render as one: it is the schema's recorded "no strand", which
    is what an rRNA or a feature spanning both strands gets. Collapsing it into "not recorded"
    would claim the source stayed silent when it did not.
    """
    if raw is None:
        return Value.absent(Absence.NOT_RECORDED, zone=zone)
    return Value.known({1: "+", -1: "-", 0: "unstranded"}.get(int(raw), str(raw)), zone=zone)


@dataclass(frozen=True)
class GeneRow:
    """One gene as a browser row: identity, where it is, what kind it is, how annotated it is.

    Everything the source may not have recorded is a `Value`, including the coordinates. A gene
    with no `start_pos` is not a gene at position 0, and `location` renders the absence rather
    than a plausible-looking ``:0-0``.
    """

    id: str
    display_name: str
    systematic_name: Value[str]
    standard_name: Value[str]
    locus_tag: Value[str]
    description: Value[str]
    assembly_accession: Value[str]
    seqid: Value[str]
    chromosome: Value[str]
    start: Value[int]
    end: Value[int]
    length: Value[int]
    strand: Value[str]
    biotype: Value[str]
    gene_group_id: Value[str]
    annotation_count: int

    @property
    def location(self) -> Value[str]:
        """``chrIV:1234217-1236125``, or the reason there is no such string."""
        if not self.start.is_known or not self.end.is_known:
            return Value.absent(self.start.absence or Absence.NOT_RECORDED, zone=self.start.zone)
        where = self.chromosome.or_none() or self.seqid.or_none()
        stem = f"{where}:" if where else ""
        return Value.known(
            f"{stem}{self.start.unwrap():,}-{self.end.unwrap():,}", zone=self.start.zone
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "systematic_name": self.systematic_name.as_json(),
            "standard_name": self.standard_name.as_json(),
            "locus_tag": self.locus_tag.as_json(),
            "description": self.description.as_json(),
            "assembly_accession": self.assembly_accession.as_json(),
            "seqid": self.seqid.as_json(),
            "chromosome": self.chromosome.as_json(),
            "start": self.start.as_json(),
            "end": self.end.as_json(),
            "length": self.length.as_json(),
            "strand": self.strand.as_json(),
            "biotype": self.biotype.as_json(),
            "gene_group_id": self.gene_group_id.as_json(),
            "location": self.location.as_json(),
            "annotation_count": self.annotation_count,
        }


def _row_from(raw: sqlite3.Row, present: frozenset[str]) -> GeneRow:
    keys = set(raw.keys())

    def maybe(name: str) -> Any:
        return raw[name] if name in keys else None

    zone = Zone(str(raw["zone"])) if "zone" in keys and raw["zone"] else None
    standard = _text(raw["standard_name"], zone)
    systematic = _text(raw["systematic_name"], zone)
    start = _number(raw["start_pos"], zone)
    end = _number(raw["end_pos"], zone)
    length = (
        Value.known(end.unwrap() - start.unwrap(), zone=zone)
        if start.is_known and end.is_known
        else Value.absent(Absence.NOT_RECORDED, zone=zone)
    )
    seqid_raw = maybe("seqid")
    ref = reference_for(str(seqid_raw)) if seqid_raw else None
    return GeneRow(
        id=str(raw["id"]),
        display_name=str(
            standard.or_none() or systematic.or_none() or maybe("locus_tag") or raw["id"]
        ),
        systematic_name=systematic,
        standard_name=standard,
        locus_tag=(
            _text(maybe("locus_tag"), zone)
            if "locus_tag" in present
            else Value.absent(Absence.NOT_RECORDED, zone=zone)
        ),
        description=(
            _text(maybe("description"), zone)
            if "description" in present
            else Value.absent(Absence.NOT_RECORDED, zone=zone)
        ),
        assembly_accession=_text(raw["assembly_accession"], zone),
        seqid=(
            _text(seqid_raw, zone)
            if "seqid" in present
            else Value.absent(Absence.NOT_RECORDED, zone=zone)
        ),
        chromosome=(
            Value.known(ref.label, zone=zone)
            if ref is not None
            else Value.absent(Absence.NOT_RECORDED, zone=zone)
        ),
        start=start,
        end=end,
        length=length,
        strand=_strand(raw["strand"], zone),
        biotype=(
            _text(maybe("biotype"), zone)
            if "biotype" in present
            else Value.absent(Absence.NOT_RECORDED, zone=zone)
        ),
        gene_group_id=_text(raw["gene_group_id"], zone),
        # Optional, because the single-gene read has no annotation join to carry it: that page
        # renders the annotations themselves, and counting them twice would be a second query
        # for a number already on screen.
        annotation_count=int(maybe("annotation_count") or 0),
    )


# ------------------------------------------------------------------ filtering


#: What each `order_by` means in SQL. A closed map, so an unrecognised ordering is a refusal with
#: the options in it rather than an unordered page that looks ordered.
ORDERINGS: Final[dict[str, tuple[str, ...]]] = {
    "position": ("seqid", "start_pos", "id"),
    "position_desc": ("seqid DESC", "start_pos DESC", "id"),
    "name": ("display_name", "id"),
    "name_desc": ("display_name DESC", "id"),
    "length": ("length DESC", "id"),
    "length_asc": ("length", "id"),
    "annotations": ("annotation_count DESC", "display_name"),
    "annotations_asc": ("annotation_count", "display_name"),
}

#: The strand spellings a URL might carry, folded to what `schema.sql` stores.
_STRANDS: Final[dict[str, int]] = {
    "+": 1,
    "1": 1,
    "plus": 1,
    "forward": 1,
    "-": -1,
    "-1": -1,
    "minus": -1,
    "reverse": -1,
    "0": 0,
    "unstranded": 0,
}

#: Columns `q` searches, in the order they are tried. Any that the schema does not have yet is
#: dropped from the search and named in the payload -- a search that silently stops covering
#: `description` looks like a search that found nothing.
_SEARCHABLE: Final[tuple[str, ...]] = (
    "systematic_name",
    "standard_name",
    "locus_tag",
    "description",
    "id",
)


def _apply_filters(
    select: Select,
    present: frozenset[str],
    *,
    q: str | None,
    assembly: str | None,
    seqid: str | None,
    biotype: str | None,
    strand: str | int | None,
    has_coordinates: bool | None,
    annotated_by: str | None,
) -> tuple[Select, dict[str, Any], list[str]]:
    """Add every requested predicate that the live schema can actually serve.

    Returns the narrowed select, the filters that were applied, and the ones that were *refused*
    because their column does not exist yet. The refusals are returned rather than swallowed: a
    bookmarked URL carrying ``?biotype=tRNA`` against a database without the column must not
    quietly return all 6,600 genes as though the filter had matched everything.
    """
    applied: dict[str, Any] = {}
    ignored: list[str] = []

    if q:
        columns = [c for c in _SEARCHABLE if c in present]
        clause = " OR ".join(f"g.{c} LIKE ?" for c in columns)
        select = select.where(clause, *[f"%{q}%" for _ in columns])
        applied["q"] = q

    if assembly:
        select = select.where("g.assembly_accession = ?", assembly)
        applied["assembly"] = assembly

    if seqid:
        if "seqid" in present:
            # Accept any spelling the karyotype knows, but query the one the schema stores.
            ref = reference_for(seqid)
            select = select.where(
                "g.seqid = ? OR g.seqid = ?", seqid, ref.accession if ref else seqid
            )
            applied["seqid"] = seqid
        else:
            ignored.append("seqid")

    if biotype:
        if "biotype" in present:
            select = select.where("g.biotype = ?", biotype)
            applied["biotype"] = biotype
        else:
            ignored.append("biotype")

    if strand is not None and str(strand) != "":
        folded = _STRANDS.get(str(strand).strip().casefold())
        if folded is None:
            raise ValueError(f"strand {strand!r} is not one of {sorted(set(_STRANDS))}")
        select = select.where("g.strand = ?", folded)
        applied["strand"] = folded

    if has_coordinates is not None:
        select = select.where(
            "g.start_pos IS NOT NULL AND g.end_pos IS NOT NULL"
            if has_coordinates
            else "g.start_pos IS NULL OR g.end_pos IS NULL"
        )
        applied["has_coordinates"] = has_coordinates

    if annotated_by:
        # EXISTS rather than a second join: joining `gene_annotation` twice would make the
        # grouped `annotation_count` the count *for that source*, so filtering to KEGG would
        # silently redefine the column beside it.
        select = select.where(
            "EXISTS (SELECT 1 FROM gene_annotation ga2 "
            "WHERE ga2.gene_group_id = g.gene_group_id AND ga2.source = ?)",
            annotated_by,
        )
        applied["annotated_by"] = annotated_by

    return select, applied, ignored


# ------------------------------------------------------------------ the list read


@dataclass(frozen=True)
class GeneListRead:
    """A page of genes, the size of the answer it came from, and what it could not filter on."""

    rows: tuple[GeneRow, ...]
    page: Page
    total_matching: int
    order_by: str
    filters: dict[str, Any]
    ignored_filters: tuple[str, ...]
    searched_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]

    @property
    def technique(self) -> str:
        return (
            "substring match (SQL LIKE '%term%') over "
            + ", ".join(self.searched_columns)
            + " — not a full-text or semantic index"
        )

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            **self.page.as_json(),
            "rows": [row.as_json() for row in self.rows],
            "total_matching": self.total_matching,
            "ordered_by": self.order_by,
            "orderings": sorted(ORDERINGS),
            "filters": self.filters,
            "searched_columns": list(self.searched_columns),
            "technique": self.technique,
        }
        payload["has_more"] = self.page.offset + len(self.rows) < self.total_matching
        if self.ignored_filters:
            payload["ignored_filters"] = {
                name: _PENDING_COLUMNS.get(name, "not available on this schema")
                for name in self.ignored_filters
            }
        if self.missing_columns:
            payload["missing_columns"] = {
                name: _PENDING_COLUMNS[name] for name in self.missing_columns
            }
        return payload


def list_genes(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    assembly: str | None = None,
    seqid: str | None = None,
    biotype: str | None = None,
    strand: str | int | None = None,
    has_coordinates: bool | None = None,
    annotated_by: str | None = None,
    order_by: str = "position",
    limit: int = 50,
    offset: int = 0,
) -> GeneListRead:
    """One page of genes matching the filters, with the true size of the match beside it.

    Exactly two statements run regardless of how many rows come back: a ``COUNT(*)`` for the
    total and one grouped ``SELECT`` for the page. The annotation count rides on the second via a
    ``LEFT JOIN`` onto `gene_annotation` -- which hangs off the gene *group*, never the gene row
    (PLAN.md C.3), so a gene with no group correctly counts zero rather than erroring.
    """
    if order_by not in ORDERINGS:
        raise ValueError(f"order_by {order_by!r} is not one of {sorted(ORDERINGS)}")

    present = _columns_of(conn, "gene")

    total_select, applied, ignored = _apply_filters(
        Select("gene", alias="g").columns("COUNT(*) AS n"),
        present,
        q=q,
        assembly=assembly,
        seqid=seqid,
        biotype=biotype,
        strand=strand,
        has_coordinates=has_coordinates,
        annotated_by=annotated_by,
    )
    total = int(total_select.scalar(conn) or 0)

    projection = [
        "g.id AS id",
        "g.assembly_accession AS assembly_accession",
        "g.systematic_name AS systematic_name",
        "g.standard_name AS standard_name",
        "g.gene_group_id AS gene_group_id",
        "g.start_pos AS start_pos",
        "g.end_pos AS end_pos",
        "g.strand AS strand",
        "g.zone AS zone",
        "g.end_pos - g.start_pos AS length",
        "COALESCE(g.standard_name, g.systematic_name, g.id) AS display_name",
        "COUNT(ga.id) AS annotation_count",
    ]
    projection.extend(f"g.{name} AS {name}" for name in _PENDING_COLUMNS if name in present)
    # `seqid` is only an orderable term when the column is there; without it, position ordering
    # degrades to "by coordinate, across an unknown set of sequences", which is still a
    # deterministic order and is honestly what the atlas can support today.
    terms = tuple(t for t in ORDERINGS[order_by] if "seqid" not in t or "seqid" in present)

    listing, _, _ = _apply_filters(
        Select("gene", alias="g").columns(*projection),
        present,
        q=q,
        assembly=assembly,
        seqid=seqid,
        biotype=biotype,
        strand=strand,
        has_coordinates=has_coordinates,
        annotated_by=annotated_by,
    )
    page = (
        listing.join("gene_annotation", "ga.gene_group_id = g.gene_group_id", alias="ga")
        .group_by("g.id")
        .order_by(*terms)
        .page(conn, limit=limit, offset=offset)
    )

    return GeneListRead(
        rows=tuple(_row_from(row, present) for row in page),
        page=page,
        total_matching=total,
        order_by=order_by,
        filters=applied,
        ignored_filters=tuple(ignored),
        searched_columns=tuple(c for c in _SEARCHABLE if c in present),
        missing_columns=tuple(c for c in _PENDING_COLUMNS if c not in present),
    )


# ------------------------------------------------------------------ facets


@dataclass(frozen=True)
class FacetValue:
    """One option in a facet, with how many genes it would leave."""

    key: str
    label: str
    count: int

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "count": self.count}


@dataclass(frozen=True)
class Facet:
    """A facet, or a stated reason there is no facet.

    ``available`` is the whole point of this type. A facet that is unavailable because its column
    has not landed and a facet that is available but happens to be empty are different facts, and
    an empty list renders them identically.
    """

    key: str
    label: str
    available: bool
    values: tuple[FacetValue, ...] = ()
    blocked_reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "available": self.available,
            "values": [v.as_json() for v in self.values],
        }
        if self.blocked_reason is not None:
            payload["blocked_reason"] = self.blocked_reason
        return payload


@dataclass(frozen=True)
class FacetsRead:
    """Every facet the browser offers, the totals a header needs, and what narrowed the counts."""

    facets: tuple[Facet, ...]
    totals: dict[str, int]
    missing_columns: tuple[str, ...]
    narrowed_by: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "facets": [f.as_json() for f in self.facets],
            "totals": self.totals,
            "missing_columns": {name: _PENDING_COLUMNS[name] for name in self.missing_columns},
            "narrowed_by": self.narrowed_by,
            "counting": (
                "Each count below is under the OTHER active filters, so it is what clicking "
                "that option would leave"
            ),
        }


def _grouped_counts(
    conn: sqlite3.Connection,
    column: str,
    present: frozenset[str],
    filters: dict[str, Any],
) -> list[tuple[str, int]]:
    """``SELECT col, COUNT(*) GROUP BY col`` over the genes the *other* filters leave.

    Excluding a facet's own filter from its own counts is what makes the rail usable: with it
    included, selecting `biotype=tRNA` would leave the Biotype panel showing tRNA and nothing
    else, and there would be no way to switch to `protein_coding` except by clearing first.

    NULLs are dropped rather than bucketed as an option, because a facet value of "null" is not
    something a reader can usefully click; how many genes lack the field belongs in the totals,
    where it is stated once instead of once per facet.
    """
    select, _, _ = _apply_filters(
        Select("gene", alias="g").columns(f"g.{column} AS key", "COUNT(*) AS n"),
        present,
        **filters,
    )
    page = (
        select.where(f"g.{column} IS NOT NULL").group_by(f"g.{column}").page(conn, limit=MAX_ROWS)
    )
    return [(str(r["key"]), int(r["n"])) for r in page]


def facets(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    assembly: str | None = None,
    seqid: str | None = None,
    biotype: str | None = None,
    strand: str | int | None = None,
    has_coordinates: bool | None = None,
    annotated_by: str | None = None,
) -> FacetsRead:
    """The filter options the atlas can offer, counted under the filters already applied.

    A facet's own filter is left out of its own counts (see :func:`_grouped_counts`), which is
    what lets a reader switch chromosomes rather than only clear them. The totals, by contrast,
    are atlas-wide: they are the denominator the page compares a match against, and narrowing
    them would make "251 of 6,636" collapse into "251 of 251".

    Bounded query count -- one per available facet plus three totals, none of them per-row.
    Facets whose column is not in the schema yet cost no query at all.
    """
    present = _columns_of(conn, "gene")
    out: list[Facet] = []
    active: dict[str, Any] = {
        "q": q,
        "assembly": assembly,
        "seqid": seqid,
        "biotype": biotype,
        "strand": strand,
        "has_coordinates": has_coordinates,
        "annotated_by": annotated_by,
    }

    def others(*without: str) -> dict[str, Any]:
        return {key: (None if key in without else value) for key, value in active.items()}

    out.append(
        Facet(
            key="assembly",
            label="Assembly",
            available=True,
            values=tuple(
                FacetValue(key=key, label=key, count=n)
                for key, n in sorted(
                    _grouped_counts(conn, "assembly_accession", present, others("assembly"))
                )
            ),
        )
    )

    if "seqid" in present:
        counts = _grouped_counts(conn, "seqid", present, others("seqid"))
        out.append(
            Facet(
                key="seqid",
                label="Chromosome",
                available=True,
                values=tuple(
                    FacetValue(
                        key=key,
                        label=(ref.label if (ref := reference_for(key)) else key),
                        count=n,
                    )
                    for key, n in sorted(counts, key=lambda kv: _natural_key(kv[0]))
                ),
            )
        )
    else:
        out.append(
            Facet(
                key="seqid",
                label="Chromosome",
                available=False,
                blocked_reason=_PENDING_COLUMNS["seqid"],
            )
        )

    if "biotype" in present:
        out.append(
            Facet(
                key="biotype",
                label="Biotype",
                available=True,
                values=tuple(
                    FacetValue(key=key, label=key.replace("_", " "), count=n)
                    for key, n in sorted(
                        _grouped_counts(conn, "biotype", present, others("biotype")),
                        key=lambda kv: (-kv[1], kv[0]),
                    )
                ),
            )
        )
    else:
        out.append(
            Facet(
                key="biotype",
                label="Biotype",
                available=False,
                blocked_reason=_PENDING_COLUMNS["biotype"],
            )
        )

    out.append(
        Facet(
            key="strand",
            label="Strand",
            available=True,
            values=tuple(
                FacetValue(
                    key={1: "+", -1: "-", 0: "0"}.get(int(key), key),
                    label={1: "+ (forward)", -1: "- (reverse)", 0: "unstranded"}.get(
                        int(key), str(key)
                    ),
                    count=n,
                )
                for key, n in sorted(
                    _grouped_counts(conn, "strand", present, others("strand")),
                    key=lambda kv: -int(kv[0]),
                )
            ),
        )
    )

    # Genes per annotation source, counted over DISTINCT genes rather than annotation rows: a
    # single gene carries dozens of InterPro terms, and a row count would claim more annotated
    # genes than the atlas holds in total.
    source_select, _, _ = _apply_filters(
        Select("gene", alias="g")
        .columns("ga.source AS key", "COUNT(DISTINCT g.id) AS n")
        .join("gene_annotation", "ga.gene_group_id = g.gene_group_id", alias="ga", kind="INNER"),
        present,
        **others("annotated_by"),
    )
    sources = source_select.group_by("ga.source").page(conn, limit=MAX_ROWS)
    out.append(
        Facet(
            key="annotated_by",
            label="Annotation source",
            available=True,
            values=tuple(
                FacetValue(key=str(r["key"]), label=str(r["key"]), count=int(r["n"]))
                for r in sorted(sources, key=lambda r: (-int(r["n"]), str(r["key"])))
            ),
        )
    )

    total = int(Select("gene").columns("COUNT(*) AS n").scalar(conn) or 0)
    placed = int(
        Select("gene")
        .columns("COUNT(*) AS n")
        .where("start_pos IS NOT NULL AND end_pos IS NOT NULL")
        .scalar(conn)
        or 0
    )
    annotated = int(
        Select("gene", alias="g")
        .columns("COUNT(DISTINCT g.id) AS n")
        .join("gene_annotation", "ga.gene_group_id = g.gene_group_id", alias="ga", kind="INNER")
        .scalar(conn)
        or 0
    )
    return FacetsRead(
        narrowed_by={key: value for key, value in active.items() if value not in (None, "")},
        facets=tuple(out),
        totals={
            "genes": total,
            "with_coordinates": placed,
            "without_coordinates": total - placed,
            "with_annotation": annotated,
            "without_annotation": total - annotated,
        },
        missing_columns=tuple(c for c in _PENDING_COLUMNS if c not in present),
    )


# ------------------------------------------------------------------ the karyotype


#: 10 kb per bin. At R64 scale that is 23 bins on chromosome I and 153 on chromosome IV, so a bin
#: is the same number of bases -- and therefore the same number of pixels -- on every track. A
#: fixed *bin count* per chromosome would instead make one bin on chrI mean 2.3 kb and one on
#: chrIV mean 15 kb, and the two tracks would no longer be comparable at all.
BIN_WIDTH_DEFAULT: Final[int] = 10_000
_BIN_WIDTH_MIN: Final[int] = 500
#: Coordinates are fetched in pages so the builder's `MAX_ROWS` ceiling cannot silently cut the
#: karyotype short. The cap bounds the work at 100k genes, ~15x the S. cerevisiae gene count.
_KARYOTYPE_PAGES: Final[int] = 20


@dataclass(frozen=True)
class Karyotype:
    """One sequence drawn as a track: its true length, its genes, and their density along it."""

    seqid: str
    label: str
    ordinal: int
    kind: str
    length: int
    length_is_reference: bool
    gene_count: int
    bins: tuple[int, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "seqid": self.seqid,
            "label": self.label,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "length": self.length,
            "length_is_reference": self.length_is_reference,
            "gene_count": self.gene_count,
            "bins": list(self.bins),
            "max_bin": max(self.bins) if self.bins else 0,
        }


@dataclass(frozen=True)
class KaryotypeRead:
    """Every track, at a stated bin width, with what could not be placed and why."""

    available: bool
    bin_width: int
    tracks: tuple[Karyotype, ...]
    unplaced_genes: int
    truncated: bool
    blocked_reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": self.available,
            "bin_width": self.bin_width,
            "tracks": [t.as_json() for t in self.tracks],
            "unplaced_genes": self.unplaced_genes,
            "truncated": self.truncated,
            "reference_assembly": "GCF_000146045.2 (S288C, R64)",
        }
        if self.blocked_reason is not None:
            payload["blocked_reason"] = self.blocked_reason
        return payload


def karyotype(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    assembly: str | None = None,
    biotype: str | None = None,
    strand: str | int | None = None,
    annotated_by: str | None = None,
    bin_width: int = BIN_WIDTH_DEFAULT,
) -> KaryotypeRead:
    """Gene density along each sequence, under every filter **except** the chromosome one.

    Leaving `seqid` out is deliberate. The karyotype is how a reader chooses a chromosome; if
    selecting chromosome IV erased the other sixteen tracks, the control would delete the view it
    lives in and there would be no way back except the URL.

    The tracks are always all 17 reference sequences, even when no gene is on them. A karyotype
    that hides an empty chromosome answers "which chromosomes have genes" when the reader asked
    "where are the genes" -- and in the state this atlas is in today, that difference is the
    entire message.
    """
    width = max(_BIN_WIDTH_MIN, int(bin_width))
    present = _columns_of(conn, "gene")

    if "seqid" not in present:
        return KaryotypeRead(
            available=False,
            bin_width=width,
            tracks=tuple(
                Karyotype(
                    seqid=ref.accession,
                    label=ref.label,
                    ordinal=ref.ordinal,
                    kind=ref.kind,
                    length=ref.length,
                    length_is_reference=True,
                    gene_count=0,
                    bins=(0,) * (ref.length // width + 1),
                )
                for ref in R64_SEQUENCES
            ),
            unplaced_genes=int(Select("gene").columns("COUNT(*) AS n").scalar(conn) or 0),
            truncated=False,
            blocked_reason=_PENDING_COLUMNS["seqid"],
        )

    select, _, _ = _apply_filters(
        Select("gene", alias="g").columns("g.seqid AS seqid", "g.start_pos AS start_pos"),
        present,
        q=q,
        assembly=assembly,
        seqid=None,
        biotype=biotype,
        strand=strand,
        has_coordinates=True,
        annotated_by=annotated_by,
    )
    select = select.order_by("g.id")

    counts: dict[str, dict[int, int]] = {}
    observed_end: dict[str, int] = {}
    offset = 0
    truncated = False
    for _ in range(_KARYOTYPE_PAGES):
        page = select.page(conn, limit=MAX_ROWS, offset=offset)
        for row in page:
            raw = str(row["seqid"] or "")
            if not raw:
                continue
            ref = reference_for(raw)
            key = ref.accession if ref else raw
            start = int(row["start_pos"])
            counts.setdefault(key, {})
            counts[key][start // width] = counts[key].get(start // width, 0) + 1
            observed_end[key] = max(observed_end.get(key, 0), start)
        if not page.truncated:
            break
        offset += len(page)
    else:
        truncated = True

    unplaced = int(
        Select("gene")
        .columns("COUNT(*) AS n")
        .where("seqid IS NULL OR start_pos IS NULL OR end_pos IS NULL")
        .scalar(conn)
        or 0
    )

    tracks: list[Karyotype] = []
    seen: set[str] = set()
    for ref in R64_SEQUENCES:
        seen.add(ref.accession)
        bins = counts.get(ref.accession, {})
        tracks.append(
            Karyotype(
                seqid=ref.accession,
                label=ref.label,
                ordinal=ref.ordinal,
                kind=ref.kind,
                length=ref.length,
                length_is_reference=True,
                gene_count=sum(bins.values()),
                bins=tuple(bins.get(i, 0) for i in range(ref.length // width + 1)),
            )
        )
    for key in sorted(set(counts) - seen, key=_natural_key):
        # A sequence the reference table does not know: a different assembly, a plasmid, a
        # contig. Its length is a *lower bound* from the genes seen on it, and the flag says so
        # rather than letting the UI draw a track that is scaled to nothing in particular.
        bins = counts[key]
        length = observed_end.get(key, 0) + width
        tracks.append(
            Karyotype(
                seqid=key,
                label=key,
                ordinal=10_000 + len(tracks),
                kind="unrecognised",
                length=length,
                length_is_reference=False,
                gene_count=sum(bins.values()),
                bins=tuple(bins.get(i, 0) for i in range(length // width + 1)),
            )
        )

    return KaryotypeRead(
        available=True,
        bin_width=width,
        tracks=tuple(tracks),
        unplaced_genes=unplaced,
        truncated=truncated,
    )


# ------------------------------------------------------------------ one gene's position


#: How far either side of a gene counts as its neighbourhood, in bases. 20 kb is roughly ten
#: yeast genes each way -- enough to see what a locus sits between without becoming a second
#: gene list.
NEIGHBOURHOOD_BASES: Final[int] = 20_000


@dataclass(frozen=True)
class PositionRead:
    """Where one gene is, and what sits beside it.

    This is returned *alongside* `genes.read_gene`'s payload rather than folded into it, because
    that reader and its `absent_sections` contract belong to the gene page and must not change
    shape to accommodate a browser.
    """

    gene_id: str
    seqid: Value[str]
    chromosome: Value[str]
    sequence_length: Value[int]
    start: Value[int]
    end: Value[int]
    length: Value[int]
    strand: Value[str]
    biotype: Value[str]
    locus_tag: Value[str]
    description: Value[str]
    location: Value[str]
    neighbours: tuple[GeneRow, ...]
    neighbourhood_bases: int
    missing_columns: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "gene_id": self.gene_id,
            "seqid": self.seqid.as_json(),
            "chromosome": self.chromosome.as_json(),
            "sequence_length": self.sequence_length.as_json(),
            "start": self.start.as_json(),
            "end": self.end.as_json(),
            "length": self.length.as_json(),
            "strand": self.strand.as_json(),
            "biotype": self.biotype.as_json(),
            "locus_tag": self.locus_tag.as_json(),
            "description": self.description.as_json(),
            "location": self.location.as_json(),
            "neighbours": [n.as_json() for n in self.neighbours],
            "neighbourhood_bases": self.neighbourhood_bases,
            "missing_columns": {name: _PENDING_COLUMNS[name] for name in self.missing_columns},
        }


def read_position(conn: sqlite3.Connection, gene_id: str) -> PositionRead | None:
    """The positional half of a gene page: coordinates, and the genes either side of it.

    Resolves the same three ways `genes.read_gene` does -- internal id, systematic name, standard
    name -- because a page reached by one identifier must not fail when the other is in the URL.
    """
    present = _columns_of(conn, "gene")
    projection = [
        "g.id AS id",
        "g.assembly_accession AS assembly_accession",
        "g.systematic_name AS systematic_name",
        "g.standard_name AS standard_name",
        "g.gene_group_id AS gene_group_id",
        "g.start_pos AS start_pos",
        "g.end_pos AS end_pos",
        "g.strand AS strand",
        "g.zone AS zone",
    ]
    projection.extend(f"g.{name} AS {name}" for name in _PENDING_COLUMNS if name in present)
    raw = (
        Select("gene", alias="g")
        .columns(*projection)
        .where(
            "g.id = ? OR UPPER(g.systematic_name) = UPPER(?) OR UPPER(g.standard_name) = UPPER(?)",
            gene_id,
            gene_id,
            gene_id,
        )
        .order_by("g.id")
        .page(conn, limit=1)
    )
    if not raw.rows:
        return None
    me = _row_from(raw.rows[0], present)

    neighbours: tuple[GeneRow, ...] = ()
    if "seqid" in present and me.seqid.is_known and me.start.is_known:
        listing = (
            Select("gene", alias="g")
            .columns(
                *projection,
                "g.end_pos - g.start_pos AS length",
                "COALESCE(g.standard_name, g.systematic_name, g.id) AS display_name",
                "COUNT(ga.id) AS annotation_count",
            )
            .join("gene_annotation", "ga.gene_group_id = g.gene_group_id", alias="ga")
            .where("g.seqid = ?", me.seqid.unwrap())
            .where(
                "g.start_pos BETWEEN ? AND ?",
                me.start.unwrap() - NEIGHBOURHOOD_BASES,
                me.start.unwrap() + NEIGHBOURHOOD_BASES,
            )
            .group_by("g.id")
            .order_by("start_pos")
            .page(conn, limit=60)
        )
        neighbours = tuple(_row_from(row, present) for row in listing)

    ref = reference_for(me.seqid.or_none())
    return PositionRead(
        gene_id=me.id,
        seqid=me.seqid,
        chromosome=me.chromosome,
        sequence_length=(
            Value.known(ref.length, zone=Zone.REPORTED)
            if ref is not None
            else Value.absent(Absence.NOT_RECORDED)
        ),
        start=me.start,
        end=me.end,
        length=me.length,
        strand=me.strand,
        biotype=me.biotype,
        locus_tag=me.locus_tag,
        description=me.description,
        location=me.location,
        neighbours=neighbours,
        neighbourhood_bases=NEIGHBOURHOOD_BASES,
        missing_columns=tuple(c for c in _PENDING_COLUMNS if c not in present),
    )
