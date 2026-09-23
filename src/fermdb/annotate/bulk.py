"""Whole-proteome annotation files -> `gene_annotation` rows, at ~6,600 genes instead of 36.

`importers.py` fetches one gene at a time over HTTP. That is the right shape for the 36 genes
docs/design/DUET_TARGET.md names by hand, and the wrong shape for the genome: 6,600 HTTP round
trips against SGD and UniProt to obtain data both of them publish as a single file is slow, rude,
and gives a different answer depending on which day each request landed. This module reads those
files instead -- streaming, so a 150,000-line GAF never lands in memory -- and emits exactly the
same `GeneAnnotationRow` the single-gene importers emit, so `write_gene_annotation`, the query
layer, the API and every existing test keep working unchanged.

**The hard part is not parsing. It is that every file keys on a different identifier.** The GAF
keys on an SGDID and a gene symbol, the UniProt export on a UniProt accession, KEGG on
`sce:YMR303C`, InterPro and Pfam on a UniProt accession again -- and the atlas keys on
`gene_group_id`, anchored to the SGD systematic name, because that is what lets a *CEN.PK* gene
inherit an annotation curated against S288C. `resolve.py` owns that problem; read its docstring
before this one. Everything here hands raw identifiers to an `IdentifierResolver` and counts what
comes back, and no row is written for an identifier the resolver would have had to guess at.

## Three decisions taken here that a reader should be able to argue with

**`NOT`-qualified GO annotations are dropped, counted, and named in the report.** A GAF qualifier
column of `NOT|involved_in` states that the gene is *not* involved in that process -- usually the
most interesting thing on the line, because somebody went and checked. `gene_annotation` has no
polarity column, and this task may not write a migration to add one. That leaves three options:
store it as a positive row (every consumer filters on `term_id` and would read the negative as a
positive -- a corrupting lie), encode the negation in `term_label` or `evidence` prose (same
outcome, since nothing parses prose), or drop it. Dropping is the only one that does not put a
false statement in the atlas, so `gaf_annotation_rows` drops it and `BulkReport.negated_dropped`
counts it with examples. This is in tension with CONVENTIONS.md's "Null and negative results are
stored with the same status as positive ones", and the tension is real: the fix is a
`negated INTEGER NOT NULL DEFAULT 0` column on `gene_annotation` in a future migration, after
which `gaf_annotation_rows` can stop dropping. Until then a counted, reported, absent row beats a
silent, plausible, wrong one. (SGD's current GAF carries very few: 2 in the first 150,000 lines.)

**An unknown GO evidence code raises by default.** `sources.py` is explicit that guessing a
category for an unrecognised code is not allowed, so `on_unknown_evidence="raise"` is the default
and a caller must opt into `"collect"`, which counts the code in the report and emits no row
rather than inventing a confidence. This is not hypothetical: SGD's real GAF contains `BSR`, which
is not a GO Consortium evidence code, on 201 of the first 150,000 lines -- every one of them a
Complex Portal `protein_complex` row rather than a gene, which is exactly the kind of thing that
should surface as a named gap rather than silently acquire `confidence = 'low'`.

**`source = 'sgd_phenotype'` carries SGD_features.tab's curated description, off-label.**
`gene_annotation.source` is CHECK-constrained to a closed list, and this task may not migrate it.
SGD's per-feature description ("Lysine methyltransferase; involved in the dimethylation of
eEF1A...") is SGD curation about a gene and has no better home in that list; `sgd_phenotype` is
the nearest, and the rows are marked `term_namespace = 'sgd_description'` so nothing mistakes them
for phenotype observations. Said loudly here because it is a compromise, not a fit: the clean fix
is an `sgd_feature` source id in the same future migration.

## What is where

* `GafReader` / `GafRecord` -- GAF 2.2, 17 columns, `!`-headers. Feeds `sgd_go`/`uniprot_goa`.
* `parse_sgd_features` / `SgdFeature` -- SGD_features.tab, 16 columns, headerless. The alias list
  here is the bridge that lets a paper saying "ADH2" reach `YAA:GG:ymr303c`.
* `parse_uniprot_tsv` / `UniProtRecord` -- a UniProt search/stream TSV export. Feeds `uniprot`,
  `interpro` and `pfam`.
* `parse_kegg_list` / `parse_kegg_pathway_links` -- `rest.kegg.jp/list/sce` and
  `rest.kegg.jp/link/pathway/sce`. Feeds `kegg`.
* `learn_from_*` -- build the resolver from the same parsed records.
* `load_gene_annotations` -- idempotent, batched, and it does not clobber curated rows.

Format notes are from real files sampled in the session that wrote this module (a 60 KB range of
`gene_association.sgd.gaf.gz`, a 40 KB range of `SGD_features.tab`, both KEGG endpoints in full,
and a handful of UniProt TSV rows); the fixtures under `tests/fixtures/annotate/bulk/` are cut
from those samples rather than invented, because the bugs in these formats are all in their edge
cases -- the trailing `;` on every UniProt cross-reference list, the four-column `list/sce` that
the two-column documentation does not mention, the `CDS` rows in SGD_features.tab whose systematic
name column is empty because the name lives on their parent.
"""

from __future__ import annotations

import gzip
import io
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TextIO

from .importers import GeneAnnotationRow
from .resolve import (
    IdentifierKind,
    IdentifierResolver,
    ResolutionReport,
    normalize_identifier,
)
from .sources import (
    AnnotationSource,
    UnknownGoEvidenceCodeError,
    recommended_confidence_for_go_evidence,
    source_by_id,
)

__all__ = [
    "GAF_ASPECT_NAMESPACES",
    "GENE_FEATURE_TYPES",
    "BulkFile",
    "BulkLoadResult",
    "BulkParseError",
    "BulkReport",
    "GafHeader",
    "GafReader",
    "GafRecord",
    "GeneGroupLoadResult",
    "KeggGeneEntry",
    "SgdFeature",
    "UniProtCofactor",
    "UniProtRecord",
    "gaf_annotation_rows",
    "kegg_annotation_rows",
    "learn_from_gaf",
    "learn_from_kegg_list",
    "learn_from_sgd_features",
    "learn_from_uniprot",
    "load_gene_annotations",
    "load_gene_groups_from_sgd_features",
    "open_annotation_file",
    "parse_kegg_list",
    "parse_kegg_pathway_links",
    "parse_sgd_features",
    "parse_uniprot_tsv",
    "sgd_feature_annotation_rows",
    "uniprot_annotation_rows",
]


class BulkParseError(ValueError):
    """A bulk annotation file is not in the format this module was told it is in.

    Raised on a structural problem (a GAF line with 9 columns, a UniProt export with no `Entry`
    column) rather than on a missing value -- a file whose *shape* is wrong will produce garbage
    quietly for 200,000 rows if it is tolerated, which is the failure this exception exists to
    convert into a stop.
    """


# GO's three aspects, as the one-letter code the GAF writes them and the namespace name every
# other part of this atlas uses (`tests/test_annotate.py` already expects the long form on a row).
GAF_ASPECT_NAMESPACES: Final[dict[str, str]] = {
    "P": "biological_process",
    "F": "molecular_function",
    "C": "cellular_component",
}

#: SGD feature types that name a gene, i.e. the ones a `gene_group` may reasonably be created for.
#: Everything else in SGD_features.tab (ARS, telomere, LTR, centromere, ...) is a genomic element
#: with no gene product and no GO annotation, and giving it a gene group would put 10,000 rows in
#: a table whose whole purpose is cross-strain gene joins.
GENE_FEATURE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ORF",
        "blocked_reading_frame",
        "gene_group",
        "ncRNA_gene",
        "pseudogene",
        "rRNA_gene",
        "snRNA_gene",
        "snoRNA_gene",
        "tRNA_gene",
        "telomerase_RNA_gene",
        "transposable_element_gene",
    }
)

# Nuclear ORFs (`YMR303C`, `YDL204W-A`), mitochondrial genes (`Q0010`) and the 2-micron plasmid
# (`R0010W`). Used only to decide whether a free-text GAF synonym is worth offering to the
# resolver as a systematic name -- the resolver's own index is the authority, this is the filter
# that keeps "glycerophosphocholine acyltransferase" out of the systematic-name lane.
_SYSTEMATIC_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Y[A-P][LR]\d{3}[WC](?:-[A-Z])?|Q\d{4}|R\d{4}[WC])$"
)

_GAF_COLUMNS: Final[int] = 17
_SGD_FEATURES_COLUMNS: Final[int] = 16

_COFACTOR_NAME_RE: Final[re.Pattern[str]] = re.compile(r"Name=([^;]+)")
_COFACTOR_CHEBI_RE: Final[re.Pattern[str]] = re.compile(r"Xref=ChEBI:(CHEBI:\d+)")
_EVIDENCE_BRACES_RE: Final[re.Pattern[str]] = re.compile(r"\{[^{}]*\}")
_ISOFORM_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\[[^\]]*\]:\s*")


def open_annotation_file(path: str | Path, *, encoding: str = "utf-8") -> TextIO:
    """Open a bulk annotation file for streaming, transparently gunzipping a `.gz`.

    SGD ships the GAF gzipped and SGD_features.tab plain, and a caller should not have to care
    which. `errors="replace"` is deliberate: these files are mostly ASCII but carry the occasional
    Greek letter or typographic dash in a description field, and one bad byte must not abort a
    6,600-gene load -- the affected character lands in a `term_label`, where it is visible, rather
    than in a traceback.
    """
    location = Path(path)
    if location.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(location, "rb"), encoding=encoding, errors="replace")
    return location.open("r", encoding=encoding, errors="replace")


@dataclass(frozen=True)
class BulkFile:
    """The file a batch of rows was read from, as those rows' `evidence` string will name it.

    One object rather than three loose strings at every call site, because `evidence` is the
    column a later reader uses to decide whether to believe a row, and "which release of which
    file" is the whole of that decision for a bulk import. `url` becomes the rows' `source_url`:
    for a bulk row that is the file's own download location, NOT the per-gene API URL
    `annotation_sources.yaml` carries, because claiming the latter would describe a fetch that
    never happened.
    """

    label: str
    version: str | None = None
    url: str | None = None

    def describe(self) -> str:
        return f"{self.label} ({self.version})" if self.version else self.label


# ---------------------------------------------------------------------------------------------
# Reporting: what got read, what got dropped, and why. Every drop in this module lands here.
# ---------------------------------------------------------------------------------------------


@dataclass
class BulkReport:
    """Counts for one bulk run: parsed, emitted, and every reason a record produced no row.

    Deliberately mutable and passed in by the caller, so one report can span a GAF, a UniProt
    export and both KEGG files and still answer "what fraction of everything I read reached the
    atlas" -- which is the only number that makes a bulk load trustworthy.
    """

    resolution: ResolutionReport = field(default_factory=ResolutionReport)
    records_read: int = 0
    rows_emitted: int = 0
    negated_dropped: int = 0
    negated_examples: list[str] = field(default_factory=list)
    unknown_evidence_codes: Counter[str] = field(default_factory=Counter)
    skipped_missing_term: int = 0
    skipped_unknown_aspect: Counter[str] = field(default_factory=Counter)
    #: Rows whose gene group resolved but does not exist in this database (set by the loader).
    gene_group_absent: Counter[str] = field(default_factory=Counter)

    def note_negated(self, description: str, *, example_limit: int = 20) -> None:
        self.negated_dropped += 1
        if len(self.negated_examples) < example_limit:
            self.negated_examples.append(description)

    @property
    def unresolved_records(self) -> int:
        return self.resolution.total_failed

    def summary(self) -> str:
        """A human-readable block. Names every non-zero drop bucket, and the zero ones too when
        they are the ones a reader came to check (`negated_dropped`, unresolved)."""
        lines = [
            f"bulk annotation: {self.records_read} records read, {self.rows_emitted} rows emitted",
            self.resolution.summary(),
            f"  NOT-qualified GO annotations dropped: {self.negated_dropped}",
        ]
        for example in self.negated_examples[:5]:
            lines.append(f"    e.g. {example}")
        if self.unknown_evidence_codes:
            total = sum(self.unknown_evidence_codes.values())
            lines.append(f"  UNKNOWN GO evidence codes (no row written): {total}")
            for code, count in self.unknown_evidence_codes.most_common():
                lines.append(f"    {code}: {count}")
        if self.skipped_missing_term:
            lines.append(f"  records with no term id: {self.skipped_missing_term}")
        if self.skipped_unknown_aspect:
            for aspect, count in self.skipped_unknown_aspect.most_common():
                lines.append(f"  unrecognised GAF aspect {aspect!r}: {count}")
        if self.gene_group_absent:
            lines.append(
                f"  rows for gene groups absent from this database: "
                f"{sum(self.gene_group_absent.values())} "
                f"across {len(self.gene_group_absent)} groups"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# GAF 2.2 -- sgd_go (yeast, from SGD) and uniprot_goa (from EBI). One format, two sources.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GafHeader:
    """The `!`-prefixed block at the top of a GAF. `source_version` is what lands on every row."""

    gaf_version: str | None = None
    date_generated: str | None = None
    generated_by: str | None = None
    lines: tuple[str, ...] = ()

    @property
    def source_version(self) -> str | None:
        """`'gaf-version 2.2, generated 20260922'`, or as much of it as the file stated.

        `None` when the file carried neither, rather than a placeholder string: CONVENTIONS.md's
        "Missing values" rule -- the source never recorded it, so the column is NULL.
        """
        parts: list[str] = []
        if self.gaf_version:
            parts.append(f"gaf-version {self.gaf_version}")
        if self.date_generated:
            parts.append(f"generated {self.date_generated}")
        return ", ".join(parts) if parts else None


@dataclass(frozen=True)
class GafRecord:
    """One GAF 2.2 data line, split and unpacked. Field names follow the GO Consortium's own.

    `negated` is lifted out of `qualifiers` into its own boolean because it is the one qualifier
    that inverts the meaning of the whole line, and a caller that forgets to look for it inside a
    tuple of strings writes a false annotation (see this module's docstring).
    """

    db: str
    db_object_id: str
    db_object_symbol: str
    qualifiers: tuple[str, ...]
    negated: bool
    go_id: str
    db_references: tuple[str, ...]
    evidence_code: str
    with_from: tuple[str, ...]
    aspect: str
    db_object_name: str | None
    synonyms: tuple[str, ...]
    db_object_type: str
    taxons: tuple[str, ...]
    date: str | None
    assigned_by: str | None
    annotation_extension: str | None
    gene_product_form_id: str | None

    @property
    def sgdid(self) -> str | None:
        """SGD's own primary key, when this line came from SGD (`DB` column == `SGD`)."""
        return self.db_object_id if self.db.upper() == "SGD" else None


def _split_pipe(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _blank_to_none(value: str) -> str | None:
    text = value.strip()
    return text or None


class GafReader:
    """Streams a GAF 2.2 file, header first.

    The header is consumed eagerly in `__init__` (it is the leading `!` block, a dozen lines) so
    that `source_version` is available *before* the first row is generated -- a row that cannot say
    which release of the file it came from is a row nobody can re-derive. Later `!` lines, which
    GAF permits mid-file, are skipped and appended to `header.lines` rather than parsed again.

    Iterating yields `GafRecord`s lazily; the underlying handle is never read twice and never held
    in memory, which is the whole point at 150,000+ lines.
    """

    def __init__(self, lines: Iterable[str], *, strict: bool = True) -> None:
        self._lines: Iterator[str] = iter(lines)
        self._strict = strict
        self._pending: str | None = None
        self._header = self._read_header()

    @property
    def header(self) -> GafHeader:
        return self._header

    def _read_header(self) -> GafHeader:
        collected: list[str] = []
        gaf_version: str | None = None
        date_generated: str | None = None
        generated_by: str | None = None
        for raw in self._lines:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            if not line.startswith("!"):
                self._pending = line
                break
            collected.append(line)
            body = line[1:].strip()
            key, _, value = body.partition(":")
            key_lower = key.strip().lower()
            value = value.strip()
            if key_lower == "gaf-version":
                gaf_version = value
            elif key_lower == "date-generated":
                date_generated = value
            elif key_lower == "generated-by":
                generated_by = value
        return GafHeader(
            gaf_version=gaf_version,
            date_generated=date_generated,
            generated_by=generated_by,
            lines=tuple(collected),
        )

    def __iter__(self) -> Iterator[GafRecord]:
        if self._pending is not None:
            pending, self._pending = self._pending, None
            record = self._parse_line(pending)
            if record is not None:
                yield record
        for raw in self._lines:
            record = self._parse_line(raw.rstrip("\r\n"))
            if record is not None:
                yield record

    def _parse_line(self, line: str) -> GafRecord | None:
        if not line.strip() or line.startswith("!"):
            return None
        fields = line.split("\t")
        if len(fields) < _GAF_COLUMNS:
            if self._strict:
                raise BulkParseError(
                    f"GAF line has {len(fields)} columns, expected {_GAF_COLUMNS}: {line[:120]!r}"
                )
            # Trailing empty columns are routinely lost by intermediate tooling; pad rather than
            # refuse, but only when the caller has explicitly asked for a lenient read.
            fields = fields + [""] * (_GAF_COLUMNS - len(fields))
        qualifiers = _split_pipe(fields[3])
        negated = any(q.upper() == "NOT" for q in qualifiers)
        return GafRecord(
            db=fields[0].strip(),
            db_object_id=fields[1].strip(),
            db_object_symbol=fields[2].strip(),
            qualifiers=tuple(q for q in qualifiers if q.upper() != "NOT"),
            negated=negated,
            go_id=fields[4].strip(),
            db_references=_split_pipe(fields[5]),
            evidence_code=fields[6].strip(),
            with_from=_split_pipe(fields[7]),
            aspect=fields[8].strip(),
            db_object_name=_blank_to_none(fields[9]),
            synonyms=_split_pipe(fields[10]),
            db_object_type=fields[11].strip(),
            taxons=_split_pipe(fields[12]),
            date=_blank_to_none(fields[13]),
            assigned_by=_blank_to_none(fields[14]),
            annotation_extension=_blank_to_none(fields[15]),
            gene_product_form_id=_blank_to_none(fields[16]),
        )


def _gaf_identifier_candidates(
    record: GafRecord, resolver: IdentifierResolver
) -> list[tuple[IdentifierKind, str]]:
    """Every identifier on a GAF line the resolver could use, unordered (it sorts by priority).

    The synonym column is the interesting one: SGD writes `YGR149W|glycerophosphocholine
    acyltransferase` there, so it carries the systematic name -- the strongest identifier on the
    line -- mixed in with free-text product names. Only synonyms that look like a systematic name
    or are already known to be one are offered, so that a prose synonym cannot become the reason a
    failure is attributed to the systematic-name lane.
    """
    candidates: list[tuple[IdentifierKind, str]] = []
    for synonym in record.synonyms:
        key = normalize_identifier(synonym, "systematic_name")
        if key in resolver.known_systematic_names or _SYSTEMATIC_NAME_RE.match(key):
            candidates.append(("systematic_name", synonym))
    sgdid = record.sgdid
    if sgdid:
        candidates.append(("sgdid", sgdid))
    if record.gene_product_form_id and record.gene_product_form_id.upper().startswith("UNIPROTKB:"):
        candidates.append(("uniprot", record.gene_product_form_id))
    if record.db_object_symbol:
        candidates.append(("symbol", record.db_object_symbol))
    return candidates


def gaf_annotation_rows(
    records: Iterable[GafRecord],
    resolver: IdentifierResolver,
    *,
    sources: Sequence[AnnotationSource],
    source_id: str,
    bulk_file: BulkFile,
    retrieved_at: str,
    report: BulkReport,
    on_unknown_evidence: Literal["raise", "collect"] = "raise",
) -> Iterator[GeneAnnotationRow]:
    """GAF records -> `gene_annotation` rows for `sgd_go` or `uniprot_goa`.

    Drops, each counted in `report`: a `NOT` qualifier (see this module's docstring -- the atlas
    cannot express a negative annotation and will not fake one), a record whose identifiers do not
    resolve to exactly one systematic name, a record with no GO id, and -- only under
    `on_unknown_evidence="collect"` -- a record whose evidence code `sources.py` does not
    recognise. Under the default `"raise"` an unknown code stops the run, because a confidence
    invented for an unrecognised code is exactly the guess `sources.py` forbids.
    """
    if source_id not in {"sgd_go", "uniprot_goa"}:
        raise BulkParseError(
            f"a GAF feeds 'sgd_go' or 'uniprot_goa', not {source_id!r} "
            "(gene_annotation's CHECK allows evidence_code on those two sources only)"
        )
    source = source_by_id(list(sources), source_id)
    version = bulk_file.version
    for record in records:
        report.records_read += 1
        if not record.go_id:
            report.skipped_missing_term += 1
            continue
        if record.negated:
            report.note_negated(
                f"{record.db_object_symbol} ({record.db_object_id}) NOT "
                f"{'|'.join(record.qualifiers) or '?'} {record.go_id}"
            )
            continue

        code = record.evidence_code.strip().upper()
        try:
            confidence = recommended_confidence_for_go_evidence(code) if code else "unverified"
        except UnknownGoEvidenceCodeError:
            if on_unknown_evidence == "raise":
                raise
            report.unknown_evidence_codes[code] += 1
            continue

        namespace = GAF_ASPECT_NAMESPACES.get(record.aspect.strip().upper())
        if namespace is None and record.aspect.strip():
            report.skipped_unknown_aspect[record.aspect.strip()] += 1

        gene_group = resolver.gene_group_id_for(
            _gaf_identifier_candidates(record, resolver), report=report.resolution
        )
        if gene_group is None:
            continue

        code_note = f" (evidence code {code})" if code else ""
        qualifier_note = f", qualifier {'|'.join(record.qualifiers)}" if record.qualifiers else ""
        report.rows_emitted += 1
        yield GeneAnnotationRow(
            gene_group_id=gene_group,
            source=source.id,
            term_id=record.go_id,
            term_label=record.db_object_name,
            term_namespace=namespace,
            evidence_code=code or None,
            reaction_id=None,
            pathway_id=None,
            source_url=bulk_file.url,
            source_version=version,
            retrieved_at=retrieved_at,
            zone="R",
            evidence=(
                f"{source.name}, GO term {record.go_id} for gene_group {gene_group}"
                f"{code_note}{qualifier_note}, read from {bulk_file.describe()} on {retrieved_at}"
            ),
            confidence=confidence,
        )


# ---------------------------------------------------------------------------------------------
# SGD_features.tab -- gene identity (the alias bridge) and SGD's curated description.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SgdFeature:
    """One line of SGD_features.tab: 16 tab-separated columns, no header, no quoting.

    Coordinates are carried `_as_reported` and are NOT converted here. SGD writes 1-based
    inclusive coordinates with a `W`/`C` strand letter; CONVENTIONS.md requires 0-based half-open
    with a numeric strand *in the database*. Nothing in this module writes a coordinate to any
    table, so converting would create a second conversion site for no caller -- and CONVENTIONS.md
    is explicit that conversion happens at exactly two places, parsers in and formatters out. The
    field names say which side of that line these values are on.
    """

    sgdid: str
    feature_type: str
    feature_qualifier: str | None
    systematic_name: str | None
    standard_name: str | None
    aliases: tuple[str, ...]
    parent_feature: str | None
    secondary_sgdids: tuple[str, ...]
    chromosome: str | None
    start_as_reported: int | None
    stop_as_reported: int | None
    strand_as_reported: str | None
    genetic_position: str | None
    coordinate_version: str | None
    sequence_version: str | None
    description: str | None

    @property
    def is_gene(self) -> bool:
        """True when this feature names a gene and so may carry a `gene_group`."""
        return self.systematic_name is not None and self.feature_type in GENE_FEATURE_TYPES


def _int_or_none(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_sgd_features(lines: Iterable[str]) -> Iterator[SgdFeature]:
    """Stream SGD_features.tab.

    Two shapes in the real file trip up a naive reader, and both are handled here rather than by
    the caller. First, sub-feature rows (`CDS`, `intron`, `noncoding_exon`) leave the systematic
    name column EMPTY and put the parent ORF's name in the parent-feature column instead -- so
    `systematic_name` is `None` on roughly half the lines and `is_gene` is the filter that matters.
    Second, an ORF with no standard name leaves that column empty too, which is NULL ("SGD never
    recorded one") and not the empty string.
    """
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        if not line.strip() or line.startswith("!"):
            continue
        fields = line.split("\t")
        if len(fields) < _SGD_FEATURES_COLUMNS:
            raise BulkParseError(
                f"SGD_features.tab line {number} has {len(fields)} columns, "
                f"expected {_SGD_FEATURES_COLUMNS}: {line[:120]!r}"
            )
        yield SgdFeature(
            sgdid=fields[0].strip(),
            feature_type=fields[1].strip(),
            feature_qualifier=_blank_to_none(fields[2]),
            systematic_name=_blank_to_none(fields[3]),
            standard_name=_blank_to_none(fields[4]),
            aliases=_split_pipe(fields[5]),
            parent_feature=_blank_to_none(fields[6]),
            secondary_sgdids=_split_pipe(fields[7]),
            chromosome=_blank_to_none(fields[8]),
            start_as_reported=_int_or_none(fields[9]),
            stop_as_reported=_int_or_none(fields[10]),
            strand_as_reported=_blank_to_none(fields[11]),
            genetic_position=_blank_to_none(fields[12]),
            coordinate_version=_blank_to_none(fields[13]),
            sequence_version=_blank_to_none(fields[14]),
            description=_blank_to_none(fields[15]),
        )


def sgd_feature_annotation_rows(
    features: Iterable[SgdFeature],
    resolver: IdentifierResolver,
    *,
    sources: Sequence[AnnotationSource],
    bulk_file: BulkFile,
    retrieved_at: str,
    report: BulkReport,
    include_aliases: bool = False,
) -> Iterator[GeneAnnotationRow]:
    """SGD_features.tab -> `sgd_phenotype` rows carrying SGD's curated per-gene description.

    Source id `sgd_phenotype` is used OFF-LABEL here; this module's docstring says why and what
    the clean fix is. `term_namespace = 'sgd_description'` keeps these rows distinguishable from
    real phenotype rows in one `WHERE` clause, which is the least a compromise like this owes its
    readers.

    `include_aliases` (default off) additionally emits one row per alias, namespace
    `'gene_alias'`. Off by default because an alias is gene *identity*, not function -- the
    schema's pattern for it is a dedicated table (`strain_alias` is the precedent) and no
    `gene_alias` table exists yet. The resolver already uses the alias list in memory for every
    load, so nothing depends on these rows; they exist for a caller who wants "which paper-facing
    names reach this gene group" answerable in SQL.
    """
    source = source_by_id(list(sources), "sgd_phenotype")
    for feature in features:
        report.records_read += 1
        if not feature.is_gene or feature.systematic_name is None:
            continue
        gene_group = resolver.gene_group_id_for(
            [("systematic_name", feature.systematic_name), ("sgdid", feature.sgdid)],
            report=report.resolution,
        )
        if gene_group is None:
            continue

        if feature.description:
            qualifier = f", {feature.feature_qualifier}" if feature.feature_qualifier else ""
            report.rows_emitted += 1
            yield GeneAnnotationRow(
                gene_group_id=gene_group,
                source=source.id,
                term_id=f"SGD:{feature.sgdid}",
                term_label=feature.description,
                term_namespace="sgd_description",
                evidence_code=None,
                reaction_id=None,
                pathway_id=None,
                source_url=bulk_file.url,
                source_version=bulk_file.version,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, curated description of {feature.systematic_name} "
                    f"({feature.feature_type}{qualifier}), read from {bulk_file.describe()} on "
                    f"{retrieved_at}"
                ),
                confidence="high",
            )

        if not include_aliases:
            continue
        for alias in feature.aliases:
            report.rows_emitted += 1
            yield GeneAnnotationRow(
                gene_group_id=gene_group,
                source=source.id,
                term_id=alias,
                term_label=feature.standard_name,
                term_namespace="gene_alias",
                evidence_code=None,
                reaction_id=None,
                pathway_id=None,
                source_url=bulk_file.url,
                source_version=bulk_file.version,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, alias {alias!r} of {feature.systematic_name}, read from "
                    f"{bulk_file.describe()} on {retrieved_at}"
                ),
                confidence="high",
            )


# ---------------------------------------------------------------------------------------------
# UniProt TSV export -- uniprot (EC, cofactor, subcellular location) and its interpro/pfam xrefs.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UniProtCofactor:
    """One `COFACTOR:` block. `chebi_id` is `None` when UniProt named a cofactor without an xref."""

    name: str
    chebi_id: str | None

    @property
    def term_id(self) -> str:
        """The ChEBI id when there is one, else the name -- matching `parse_uniprot_entry`'s
        `xref.get("id") or name`, so a bulk row and a single-gene row for the same cofactor
        collide on the idempotency key instead of both inserting."""
        return self.chebi_id or self.name


@dataclass(frozen=True)
class UniProtRecord:
    """One row of a UniProt search/stream TSV export, with every requested column unpacked."""

    accession: str
    entry_name: str | None = None
    protein_names: str | None = None
    gene_primary: str | None = None
    gene_synonyms: tuple[str, ...] = ()
    ordered_locus_names: tuple[str, ...] = ()
    ec_numbers: tuple[str, ...] = ()
    go_ids: tuple[str, ...] = ()
    interpro_ids: tuple[str, ...] = ()
    pfam_ids: tuple[str, ...] = ()
    subcellular_locations: tuple[str, ...] = ()
    cofactors: tuple[UniProtCofactor, ...] = ()
    sgdids: tuple[str, ...] = ()
    kegg_ids: tuple[str, ...] = ()


#: UniProt's own column headings -> this module's field names. Keyed on the lower-cased heading so
#: a caller who asked for the same fields in a different order, or asked for extra ones, still
#: parses -- a TSV export is a user-chosen column set, not a fixed format, and positional parsing
#: of one is a bug waiting for whoever next edits the download URL.
_UNIPROT_COLUMNS: Final[dict[str, str]] = {
    "entry": "accession",
    "entry name": "entry_name",
    "protein names": "protein_names",
    "gene names (primary)": "gene_primary",
    "gene names (synonym)": "gene_synonyms",
    "gene names (ordered locus)": "ordered_locus_names",
    "gene names (ordered locus )": "ordered_locus_names",
    "ec number": "ec_numbers",
    "gene ontology ids": "go_ids",
    "gene ontology (id)": "go_ids",
    "interpro": "interpro_ids",
    "cross-reference (interpro)": "interpro_ids",
    "pfam": "pfam_ids",
    "cross-reference (pfam)": "pfam_ids",
    "subcellular location [cc]": "subcellular_locations",
    "cofactor": "cofactors",
    "sgd": "sgdids",
    "cross-reference (sgd)": "sgdids",
    "kegg": "kegg_ids",
    "cross-reference (kegg)": "kegg_ids",
}


def _split_semicolons(value: str) -> tuple[str, ...]:
    """`'IPR000366;IPR027458;'` -> `('IPR000366', 'IPR027458')`.

    The trailing separator is not an anomaly: UniProt terminates *every* cross-reference list with
    one, so a naive `split(';')` yields an empty final element on every populated row. An empty
    `term_id` would violate nothing the schema checks (it is NOT NULL, not non-empty) and would
    quietly add one junk annotation per protein per cross-reference column.
    """
    return tuple(part.strip() for part in value.split(";") if part.strip())


def _split_whitespace(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split() if part)


def parse_uniprot_cofactors(value: str) -> tuple[UniProtCofactor, ...]:
    """`'COFACTOR: Name=Mg(2+); Xref=ChEBI:CHEBI:18420; Evidence={...};'` -> one entry per block.

    Splitting on the `COFACTOR:` marker rather than on `;` is what makes this survive real values:
    a cofactor name can itself contain a semicolon-free but bracket-heavy form (`[2Fe-2S] cluster`,
    the one that matters for Ilv3 in docs/design/DUET_TARGET.md section 2), and the `Evidence={...}`
    and `Note=...` tails carry semicolons of their own.
    """
    text = value.strip()
    if not text:
        return ()
    entries: list[UniProtCofactor] = []
    for block in text.split("COFACTOR:"):
        chunk = block.strip()
        if not chunk:
            continue
        name_match = _COFACTOR_NAME_RE.search(chunk)
        if name_match is None:
            continue
        name = _EVIDENCE_BRACES_RE.sub("", name_match.group(1)).strip().rstrip(".,;").strip()
        if not name:
            continue
        chebi_match = _COFACTOR_CHEBI_RE.search(chunk)
        entries.append(
            UniProtCofactor(name=name, chebi_id=chebi_match.group(1) if chebi_match else None)
        )
    return tuple(entries)


def parse_uniprot_subcellular_locations(value: str) -> tuple[str, ...]:
    """Pull the location terms out of UniProt's `Subcellular location [CC]` column.

    `'SUBCELLULAR LOCATION: Cell membrane {ECO:...}; Multi-pass membrane protein {...}. Note=...'`
    becomes `('Cell membrane', 'Multi-pass membrane protein')`.

    Evidence braces go first, then the `Note=` free-text tail (which is prose about trafficking,
    not a location), then the `[Isoform 2]:` labels UniProt prefixes onto per-isoform blocks.
    What survives is the location vocabulary terms themselves, deduplicated in first-seen order so
    a protein listed in the cytoplasm twice does not produce two identical rows.
    """
    text = value.strip()
    if not text:
        return ()
    text = _EVIDENCE_BRACES_RE.sub("", text)
    found: list[str] = []
    seen: set[str] = set()
    for section in text.split("SUBCELLULAR LOCATION:"):
        body = section.split("Note=", 1)[0]
        for piece in re.split(r"[;.]", body):
            location = _ISOFORM_LABEL_RE.sub("", piece.strip()).strip().strip(",").strip()
            if not location or location.lower() in seen:
                continue
            seen.add(location.lower())
            found.append(location)
    return tuple(found)


def parse_uniprot_tsv(lines: Iterable[str]) -> Iterator[UniProtRecord]:
    """Stream a UniProt TSV export, mapping columns by heading rather than by position.

    Raises `BulkParseError` when the export has no `Entry` column, because without an accession
    there is no identifier to resolve on and every row would be discarded -- a failure worth
    hearing at line 1 rather than as a report saying "0 of 6,060 resolved".
    """
    iterator = iter(lines)
    try:
        header_line = next(iterator)
    except StopIteration:
        return
    headings = [h.strip() for h in header_line.rstrip("\r\n").split("\t")]
    mapping: dict[int, str] = {}
    for index, heading in enumerate(headings):
        field_name = _UNIPROT_COLUMNS.get(heading.lower())
        if field_name is not None:
            mapping[index] = field_name
    if "accession" not in mapping.values():
        raise BulkParseError(
            "UniProt TSV export has no 'Entry' column; got "
            f"{headings[:8]}{'...' if len(headings) > 8 else ''}"
        )

    for raw in iterator:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        fields = line.split("\t")
        values: dict[str, str] = {}
        for index, field_name in mapping.items():
            values[field_name] = fields[index] if index < len(fields) else ""
        accession = values.get("accession", "").strip()
        if not accession:
            continue
        yield UniProtRecord(
            accession=accession,
            entry_name=_blank_to_none(values.get("entry_name", "")),
            protein_names=_blank_to_none(values.get("protein_names", "")),
            gene_primary=_blank_to_none(values.get("gene_primary", "")),
            gene_synonyms=_split_whitespace(values.get("gene_synonyms", "")),
            ordered_locus_names=_split_whitespace(values.get("ordered_locus_names", "")),
            ec_numbers=_split_semicolons(values.get("ec_numbers", "")),
            go_ids=_split_semicolons(values.get("go_ids", "")),
            interpro_ids=_split_semicolons(values.get("interpro_ids", "")),
            pfam_ids=_split_semicolons(values.get("pfam_ids", "")),
            subcellular_locations=parse_uniprot_subcellular_locations(
                values.get("subcellular_locations", "")
            ),
            cofactors=parse_uniprot_cofactors(values.get("cofactors", "")),
            sgdids=_split_semicolons(values.get("sgdids", "")),
            kegg_ids=_split_semicolons(values.get("kegg_ids", "")),
        )


def _uniprot_identifier_candidates(record: UniProtRecord) -> list[tuple[IdentifierKind, str]]:
    candidates: list[tuple[IdentifierKind, str]] = [("uniprot", record.accession)]
    candidates.extend(("systematic_name", name) for name in record.ordered_locus_names)
    candidates.extend(("sgdid", sgdid) for sgdid in record.sgdids)
    candidates.extend(("kegg", kegg_id) for kegg_id in record.kegg_ids)
    if record.gene_primary:
        candidates.append(("symbol", record.gene_primary))
    return candidates


def uniprot_annotation_rows(
    records: Iterable[UniProtRecord],
    resolver: IdentifierResolver,
    *,
    sources: Sequence[AnnotationSource],
    bulk_file: BulkFile,
    retrieved_at: str,
    report: BulkReport,
    include_go: bool = False,
) -> Iterator[GeneAnnotationRow]:
    """A UniProt TSV export -> `uniprot`, `interpro` and `pfam` rows.

    `uniprot` gets the EC numbers, the cofactors and the subcellular locations (the three things
    docs/design/DUET_TARGET.md sections 2 and 7 actually ask UniProt for); `interpro` and `pfam`
    get the cross-reference columns, which is the cheap way to obtain domain assignments for the
    whole proteome without 6,000 InterPro API calls.

    `include_go` is OFF by default and that is a judgement, not an oversight: the TSV's
    `Gene Ontology IDs` column carries GO ids with no evidence code, and `sources.py` builds a
    row's confidence *from* the evidence code. A GO row with no code could only be given a
    made-up confidence or `'unverified'`, and the GAF -- which does carry the code -- is the
    authority for GO anyway. Turn it on only when no GAF is available for an organism.
    """
    uniprot_source = source_by_id(list(sources), "uniprot")
    interpro_source = source_by_id(list(sources), "interpro")
    pfam_source = source_by_id(list(sources), "pfam")
    goa_source = source_by_id(list(sources), "uniprot_goa") if include_go else None
    stamp = f"read from {bulk_file.describe()} on {retrieved_at}"

    for record in records:
        report.records_read += 1
        gene_group = resolver.gene_group_id_for(
            _uniprot_identifier_candidates(record), report=report.resolution
        )
        if gene_group is None:
            continue

        emitted: list[tuple[AnnotationSource, str, str | None, str, str]] = [
            (uniprot_source, f"EC:{ec}", None, "ec", f"EC {ec}") for ec in record.ec_numbers
        ]
        emitted.extend(
            (
                uniprot_source,
                cofactor.term_id,
                cofactor.name,
                "cofactor",
                f"cofactor {cofactor.name!r}",
            )
            for cofactor in record.cofactors
        )
        emitted.extend(
            (
                uniprot_source,
                location,
                location,
                "subcellular_location",
                f"subcellular location {location!r}",
            )
            for location in record.subcellular_locations
        )
        emitted.extend(
            (interpro_source, interpro_id, None, "domain", f"InterPro entry {interpro_id}")
            for interpro_id in record.interpro_ids
        )
        emitted.extend(
            (pfam_source, pfam_id, None, "domain", f"Pfam entry {pfam_id}")
            for pfam_id in record.pfam_ids
        )
        for source, term_id, label, namespace, what in emitted:
            report.rows_emitted += 1
            yield GeneAnnotationRow(
                gene_group_id=gene_group,
                source=source.id,
                term_id=term_id,
                term_label=label,
                term_namespace=namespace,
                evidence_code=None,
                reaction_id=None,
                pathway_id=None,
                source_url=bulk_file.url,
                source_version=bulk_file.version,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, {what} for gene_group {gene_group} "
                    f"(UniProt {record.accession}), {stamp}"
                ),
                confidence="high",
            )
        if goa_source is not None:
            for go_id in record.go_ids:
                report.rows_emitted += 1
                yield GeneAnnotationRow(
                    gene_group_id=gene_group,
                    source=goa_source.id,
                    term_id=go_id,
                    term_label=None,
                    term_namespace=None,
                    # No code in this column, so none is claimed. `confidence` below is
                    # 'unverified' for exactly the same reason.
                    evidence_code=None,
                    reaction_id=None,
                    pathway_id=None,
                    source_url=bulk_file.url,
                    source_version=bulk_file.version,
                    retrieved_at=retrieved_at,
                    zone="R",
                    evidence=(
                        f"{goa_source.name}, GO term {go_id} for gene_group {gene_group} "
                        f"(UniProt {record.accession}; this export carries no GO evidence code), "
                        f"{stamp}"
                    ),
                    confidence="unverified",
                )


# ---------------------------------------------------------------------------------------------
# KEGG list/link -- kegg. redistributable: false, so identifiers, a short label and a link only.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KeggGeneEntry:
    """One line of `rest.kegg.jp/list/sce`.

    The documented shape is two columns (`sce:YMR303C<TAB>ADH2; alcohol dehydrogenase ...`). The
    endpoint as actually served returns FOUR
    (`sce:YAL068C<TAB>CDS<TAB>I:complement(1807..2169)<TAB>PAU8; seripauperin PAU8`), verified
    live in the session that wrote this. Both are parsed; `position` is `None` for the two-column
    form. `description` is kept out of what this module writes to the atlas, because KEGG is
    `redistributable: false` in `data/annotation/annotation_sources.yaml` -- only the identifier,
    the gene symbol and a resolvable link are stored.
    """

    kegg_id: str
    entry_type: str | None
    position: str | None
    symbols: tuple[str, ...]
    description: str | None


def parse_kegg_list(lines: Iterable[str]) -> Iterator[KeggGeneEntry]:
    """Stream `rest.kegg.jp/list/sce` in either its two- or four-column form."""
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        fields = line.split("\t")
        kegg_id = fields[0].strip()
        if not kegg_id:
            continue
        if len(fields) >= 4:
            entry_type: str | None = _blank_to_none(fields[1])
            position: str | None = _blank_to_none(fields[2])
            definition = fields[3]
        elif len(fields) == 2:
            entry_type, position, definition = None, None, fields[1]
        else:
            raise BulkParseError(
                f"KEGG list line has {len(fields)} columns, expected 2 or 4: {line[:120]!r}"
            )
        head, separator, tail = definition.partition(";")
        if separator:
            symbols = tuple(part.strip() for part in head.split(",") if part.strip())
            description = tail.strip() or None
        else:
            symbols = ()
            description = definition.strip() or None
        yield KeggGeneEntry(
            kegg_id=kegg_id,
            entry_type=entry_type,
            position=position,
            symbols=symbols,
            description=description,
        )


def parse_kegg_pathway_links(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Stream `rest.kegg.jp/link/pathway/sce` as `('sce:YMR303C', 'sce00010')` pairs.

    KEGG writes the pathway as `path:sce00010`; the `path:` prefix is stripped so that `term_id`
    matches the id in `https://www.kegg.jp/pathway/sce00010` and the one the single-gene
    `parse_kegg_flat_entry` already stores from a `PATHWAY` line.
    """
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            raise BulkParseError(f"KEGG link line has no target column: {line[:120]!r}")
        gene = fields[0].strip()
        pathway = fields[1].strip()
        if pathway.startswith("path:"):
            pathway = pathway[len("path:") :]
        if gene and pathway:
            yield gene, pathway


def kegg_annotation_rows(
    entries: Iterable[KeggGeneEntry],
    links: Iterable[tuple[str, str]],
    resolver: IdentifierResolver,
    *,
    sources: Sequence[AnnotationSource],
    bulk_file: BulkFile,
    retrieved_at: str,
    report: BulkReport,
    internal_pathway_ids: Mapping[str, str] | None = None,
) -> Iterator[GeneAnnotationRow]:
    """KEGG `list` + `link` -> `kegg` rows, one per gene entry and one per pathway membership.

    `internal_pathway_ids` maps a KEGG map id (`sce00010`) onto a `pathway.id` this atlas already
    curates (`YAA:PWY:...`), and is the ONLY way `gene_annotation.pathway_id` gets populated here.
    It is empty by default and has to be supplied, because the `pathway` table's ids are
    hand-curated slugs from ISOBUTANOL_PROGRAM.md's route with no KEGG cross-reference column to
    join on -- deriving one would either violate the foreign key or invent a linkage. That matches
    what schema.sql says the column is for: "set ONLY when a term already resolves to a row this
    atlas independently curates".

    `links` is materialised (it is a few thousand pairs, not a few hundred thousand) so the gene
    entries can stream past once; `entries` stays lazy.
    """
    source = source_by_id(list(sources), "kegg")
    pathway_map = dict(internal_pathway_ids or {})
    by_gene: dict[str, list[str]] = {}
    for gene, pathway in links:
        by_gene.setdefault(gene, []).append(pathway)
    stamp = f"read from {bulk_file.describe()} on {retrieved_at}"

    for entry in entries:
        report.records_read += 1
        candidates: list[tuple[IdentifierKind, str]] = [("kegg", entry.kegg_id)]
        candidates.extend(("symbol", symbol) for symbol in entry.symbols)
        gene_group = resolver.gene_group_id_for(candidates, report=report.resolution)
        if gene_group is None:
            continue

        report.rows_emitted += 1
        yield GeneAnnotationRow(
            gene_group_id=gene_group,
            source=source.id,
            term_id=entry.kegg_id,
            # Identifier + short label only: `redistributable: false`. The full KEGG definition
            # text on `entry.description` is deliberately not carried into the atlas.
            term_label=entry.symbols[0] if entry.symbols else None,
            term_namespace="gene",
            evidence_code=None,
            reaction_id=None,
            pathway_id=None,
            source_url=f"https://www.kegg.jp/entry/{entry.kegg_id}",
            source_version=bulk_file.version,
            retrieved_at=retrieved_at,
            zone="R",
            evidence=(
                f"{source.name}, KEGG gene {entry.kegg_id} for gene_group {gene_group}, {stamp}"
            ),
            confidence="high",
        )

        for pathway in by_gene.get(entry.kegg_id, ()):
            report.rows_emitted += 1
            yield GeneAnnotationRow(
                gene_group_id=gene_group,
                source=source.id,
                term_id=pathway,
                term_label=None,
                term_namespace="pathway",
                evidence_code=None,
                reaction_id=None,
                pathway_id=pathway_map.get(pathway),
                source_url=f"https://www.kegg.jp/pathway/{pathway}",
                source_version=bulk_file.version,
                retrieved_at=retrieved_at,
                zone="R",
                evidence=(
                    f"{source.name}, KEGG pathway {pathway} contains {entry.kegg_id} "
                    f"(gene_group {gene_group}), {stamp}"
                ),
                confidence="high",
            )


# ---------------------------------------------------------------------------------------------
# Building the resolver from the same files. Order matters: SGD_features first (it defines the
# systematic names), then UniProt and KEGG (which attach their own id spaces to those names).
# ---------------------------------------------------------------------------------------------


def learn_from_sgd_features(resolver: IdentifierResolver, features: Iterable[SgdFeature]) -> int:
    """Teach the resolver every gene in SGD_features.tab. Returns the number of genes learned.

    This is the file that makes the others resolvable: it is the only one carrying the alias list,
    and an alias is how a paper saying "ADH2" reaches `YAA:GG:ymr303c`. Secondary SGDIDs are
    learned too, because an annotation file written against an older SGD release can still be
    keyed on one.
    """
    learned = 0
    for feature in features:
        if not feature.is_gene or feature.systematic_name is None:
            continue
        symbols = list(feature.aliases)
        if feature.standard_name:
            symbols.append(feature.standard_name)
        resolver.learn(
            feature.systematic_name,
            sgdids=(feature.sgdid, *feature.secondary_sgdids),
            symbols=symbols,
            kegg_ids=(),
            locus_tags=(feature.systematic_name,),
        )
        learned += 1
    return learned


def learn_from_uniprot(resolver: IdentifierResolver, records: Iterable[UniProtRecord]) -> int:
    """Teach the resolver the UniProt accession -> systematic name bridge. Returns records used.

    A record with no ordered-locus name teaches nothing about a systematic name directly, but its
    SGD cross-reference still does -- so those are attached to the systematic name SGD_features
    already gave the SGDID, via a second pass rather than by inventing a name here. Records with
    neither are skipped and will simply not resolve later, which the report will say.
    """
    used = 0
    for record in records:
        anchors = [
            name for name in record.ordered_locus_names if _SYSTEMATIC_NAME_RE.match(name.upper())
        ]
        if not anchors:
            for sgdid in record.sgdids:
                names = resolver.candidates(sgdid, "sgdid")
                if len(names) == 1:
                    anchors.append(names[0])
                    break
        if not anchors:
            continue
        symbols = list(record.gene_synonyms)
        if record.gene_primary:
            symbols.append(record.gene_primary)
        for anchor in anchors:
            resolver.learn(
                anchor,
                sgdids=record.sgdids,
                symbols=symbols,
                uniprot_accessions=(record.accession,),
                kegg_ids=record.kegg_ids,
            )
        used += 1
    return used


def learn_from_gaf(resolver: IdentifierResolver, records: Iterable[GafRecord]) -> int:
    """Teach the resolver from a GAF's own columns. Returns the number of records used.

    Only useful when SGD_features.tab is unavailable: a GAF's synonym column carries the
    systematic name, its `DB_Object_ID` the SGDID and its `Gene_Product_Form_ID` a UniProt
    accession, which between them cover the same three bridges. It is a fallback, not the plan --
    a GAF has no alias list beyond what happens to appear as a synonym.
    """
    used = 0
    for record in records:
        anchors = [
            synonym
            for synonym in record.synonyms
            if _SYSTEMATIC_NAME_RE.match(normalize_identifier(synonym, "systematic_name"))
        ]
        if not anchors:
            continue
        accessions = (
            (record.gene_product_form_id,)
            if record.gene_product_form_id
            and record.gene_product_form_id.upper().startswith("UNIPROTKB:")
            else ()
        )
        for anchor in anchors:
            resolver.learn(
                anchor,
                sgdids=(record.db_object_id,) if record.sgdid else (),
                symbols=(record.db_object_symbol,) if record.db_object_symbol else (),
                uniprot_accessions=accessions,
            )
        used += 1
    return used


def learn_from_kegg_list(resolver: IdentifierResolver, entries: Iterable[KeggGeneEntry]) -> int:
    """Attach `sce:YMR303C`-style KEGG ids to the systematic names already known. Returns count.

    KEGG's yeast gene ids are the systematic name with an organism prefix, so this is nearly a
    no-op -- `IdentifierResolver.candidates` already strips the prefix. It exists for the
    organisms where that is not true (KEGG uses locus tags for most bacteria), so the bacterial
    side of this atlas can use the same code path without a special case.
    """
    learned = 0
    for entry in entries:
        bare = entry.kegg_id.split(":", 1)[1] if ":" in entry.kegg_id else entry.kegg_id
        names = resolver.candidates(bare, "systematic_name")
        if len(names) != 1:
            continue
        resolver.learn(names[0], kegg_ids=(entry.kegg_id,), symbols=entry.symbols)
        learned += 1
    return learned


# ---------------------------------------------------------------------------------------------
# Loading. Batched, idempotent, and it leaves curated rows alone.
# ---------------------------------------------------------------------------------------------

_INSERT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "gene_group_id",
    "source",
    "term_id",
    "term_label",
    "term_namespace",
    "evidence_code",
    "reaction_id",
    "pathway_id",
    "source_url",
    "source_version",
    "retrieved_at",
    "zone",
    "evidence",
    "confidence",
)

# The conflict target is `gene_annotation_dedup`'s exact expression list, including the COALESCE:
# SQLite matches an upsert target against an index by its expressions, and a target of the four
# bare columns does not match an index built on three columns plus COALESCE(evidence_code, '').
_CONFLICT_TARGET: Final[str] = "(gene_group_id, source, term_id, COALESCE(evidence_code, ''))"


@dataclass(frozen=True)
class BulkLoadResult:
    """What one `load_gene_annotations` call did. Every offered row is in exactly one bucket."""

    rows_offered: int
    rows_inserted: int
    rows_left_alone: int
    rows_refreshed: int
    gene_groups_absent: int

    def summary(self) -> str:
        return (
            f"gene_annotation: {self.rows_offered} offered, {self.rows_inserted} inserted, "
            f"{self.rows_left_alone} already present and left as-is, "
            f"{self.rows_refreshed} refreshed, "
            f"{self.gene_groups_absent} skipped (gene group not in this database)"
        )


def load_gene_annotations(
    conn: sqlite3.Connection,
    rows: Iterable[GeneAnnotationRow],
    *,
    report: BulkReport | None = None,
    on_conflict: Literal["skip", "refresh"] = "skip",
    batch_size: int = 5_000,
) -> BulkLoadResult:
    """Load bulk rows into `gene_annotation`. Idempotent, batched, curation-preserving.

    **The merge rule, and why it is this one.** On a collision with an existing row -- same
    `(gene_group_id, source, term_id, COALESCE(evidence_code, ''))`, which is
    `gene_annotation_dedup`'s key -- the default `on_conflict="skip"` leaves the EXISTING row
    untouched and counts the skip. The existing rows are there because somebody pointed a
    single-gene importer at a specific gene on purpose, and `sources.py` says in as many words
    that the confidence such a row carries is "an editorial default... a curator reviewing the row
    later is always free to override it". A whole-proteome file sweep is the lowest-attention
    write this atlas performs; letting it silently reset a curator's override -- or replace a
    `retrieved_at` that dates a real per-gene fetch with the date somebody re-ran a batch job --
    inverts that relationship. So bulk adds what is missing and argues with nothing.

    `on_conflict="refresh"` updates in place instead, and is the right choice for exactly one
    situation: re-importing a NEWER RELEASE of the same file, deliberately. It will overwrite
    curator overrides, and the docstring says so here rather than in a release note.

    Idempotency falls out of either mode: a second identical run inserts nothing under `"skip"`
    and rewrites identical values under `"refresh"`.

    Rows whose `gene_group_id` is not in this database are counted, not inserted -- the foreign
    key would reject them anyway, and a reported count is more useful than an `IntegrityError` on
    row 140,000. Use `load_gene_groups_from_sgd_features` first if the groups are missing because
    nothing has created them yet.

    Nothing here opens a database. `conn` is the caller's, and this function commits exactly once,
    at the end, so a failed load leaves the table as it was.
    """
    existing_groups = {str(row[0]) for row in conn.execute("SELECT id FROM gene_group").fetchall()}
    placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
    if on_conflict == "skip":
        action = "DO NOTHING"
    else:
        assignments = ", ".join(
            f"{column} = excluded.{column}" for column in _INSERT_COLUMNS if column != "id"
        )
        action = f"DO UPDATE SET {assignments}"
    statement = (
        f"INSERT INTO gene_annotation ({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT {_CONFLICT_TARGET} {action}"
    )

    offered = 0
    absent = 0
    changed_before = conn.total_changes
    batch: list[tuple[object, ...]] = []

    def flush() -> None:
        if batch:
            conn.executemany(statement, batch)
            batch.clear()

    for row in rows:
        if row.gene_group_id not in existing_groups:
            absent += 1
            if report is not None:
                report.gene_group_absent[row.gene_group_id] += 1
            continue
        offered += 1
        batch.append(
            (
                f"YAA:ANNOT:{uuid.uuid4().hex}",
                row.gene_group_id,
                row.source,
                row.term_id,
                row.term_label,
                row.term_namespace,
                row.evidence_code,
                row.reaction_id,
                row.pathway_id,
                row.source_url,
                row.source_version,
                row.retrieved_at,
                row.zone,
                row.evidence,
                row.confidence,
            )
        )
        if len(batch) >= batch_size:
            flush()
    flush()
    conn.commit()

    # `DO NOTHING` counts no change for a row it skipped, so under "skip" the delta IS the insert
    # count and the remainder is what was already there. `DO UPDATE` counts a change either way,
    # so under "refresh" the two cannot be told apart from here and the whole delta is reported as
    # refreshed rather than guessed at.
    changed = conn.total_changes - changed_before
    return BulkLoadResult(
        rows_offered=offered,
        rows_inserted=changed if on_conflict == "skip" else 0,
        rows_left_alone=offered - changed if on_conflict == "skip" else 0,
        rows_refreshed=changed if on_conflict == "refresh" else 0,
        gene_groups_absent=absent,
    )


@dataclass(frozen=True)
class GeneGroupLoadResult:
    """What `load_gene_groups_from_sgd_features` did."""

    features_seen: int
    groups_inserted: int
    groups_already_present: int

    def summary(self) -> str:
        return (
            f"gene_group: {self.features_seen} gene features read, "
            f"{self.groups_inserted} groups created, "
            f"{self.groups_already_present} already present and left as-is"
        )


def load_gene_groups_from_sgd_features(
    conn: sqlite3.Connection,
    features: Iterable[SgdFeature],
    *,
    bulk_file: BulkFile,
    retrieved_at: str,
    feature_types: frozenset[str] = GENE_FEATURE_TYPES,
    batch_size: int = 5_000,
) -> GeneGroupLoadResult:
    """Create the `gene_group` rows the bulk annotation load needs, from SGD's own feature file.

    `gene_annotation.gene_group_id` is a NOT NULL foreign key, so 6,600 genes' worth of
    annotations need 6,600 gene groups to hang on, and until something creates them a bulk load
    can only report that every row was skipped. SGD_features.tab is the right source for them:
    CONVENTIONS.md says the yeast anchor namespace is the S288C systematic name, and this file is
    where SGD states it.

    **Never clobbers.** An existing group -- whether created by a curator, by
    `fermdb.omics.genes`, or by a previous run of this function -- is left exactly as it is
    (`ON CONFLICT (id) DO NOTHING`), because a `gene_group` row carries `membership_method` and
    `evidence` that may describe an orthology computation this function knows nothing about.
    That also makes it idempotent.

    `confidence = 'high'` and `zone = 'R'`: the row asserts only that SGD's own feature file gives
    this systematic name to this SGDID, which is as directly-reported as a fact gets.
    """
    seen = 0
    inserted_before = conn.total_changes
    batch: list[tuple[object, ...]] = []
    statement = (
        "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
        "membership_method, zone, evidence, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO NOTHING"
    )

    def flush() -> None:
        if batch:
            conn.executemany(statement, batch)
            batch.clear()

    for feature in features:
        if feature.systematic_name is None or feature.feature_type not in feature_types:
            continue
        seen += 1
        qualifier = f", {feature.feature_qualifier}" if feature.feature_qualifier else ""
        batch.append(
            (
                f"YAA:GG:{feature.systematic_name.lower()}",
                "sgd_systematic",
                feature.systematic_name,
                feature.standard_name,
                "species",
                "anchor",
                "R",
                (
                    f"SGD feature {feature.sgdid} ({feature.feature_type}{qualifier}) names "
                    f"{feature.systematic_name}, read from {bulk_file.describe()} on "
                    f"{retrieved_at}"
                ),
                "high",
            )
        )
        if len(batch) >= batch_size:
            flush()
    flush()
    conn.commit()

    inserted = conn.total_changes - inserted_before
    return GeneGroupLoadResult(
        features_seen=seen,
        groups_inserted=inserted,
        groups_already_present=seen - inserted,
    )
