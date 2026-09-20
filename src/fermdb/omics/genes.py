"""Resolve the DUET gene set into `gene_group` and `gene` rows.

PLAN.md E.4 lists the genes "that must be right on day one" and marks every one of them ⚠:
"Every entry is ⚠ and must be resolved against SGD during phase 1 -- that resolution *is* the
phase-1 genomics acceptance criterion." This module performs that resolution for the DUET subset
(`docs/design/DUET_TARGET.md` §3), and it performs it by **parsing**, never by recall.

Two files are the whole input, and both are already on disk:

1. ``<genomes_dir>/s288c.transcripts.fna.gz`` -- the RefSeq ``rna_from_genomic`` FASTA for
   assembly ``GCF_000146045.2`` (R64). Its headers carry exactly the five facts wanted::

       >lcl|NC_001145.3_mrna_NM_001182582.1_4662 [gene=ADH3] [locus_tag=YMR083W]
        [db_xref=GeneID:855107] [product=alcohol dehydrogenase ADH3] ... [location=<434788..>435915]

   Standard name, systematic name, NCBI GeneID, product description and -- via the sequence
   accession the transcript sits on -- the encoding genome. Nothing here is typed from memory;
   a symbol absent from this file is recorded as a gap and reported, never guessed
   (docs/reference/CONVENTIONS.md, "Curation": *never write high confidence from memory*).

2. ``docs/design/DUET_TARGET.md`` §3 -- the role table, parsed out of the Markdown rather than
   transcribed, so that editing the destination document changes the roles and nothing silently
   disagrees with it.

**Why the encoding genome comes from the accession and not from the compartment.** ``ADH3`` is
the mitochondrial alcohol dehydrogenase: it works in the matrix, and DUET's whole redox
architecture runs through it (DUET_TARGET §2, §7). It is nevertheless **nuclear-encoded** -- its
transcript sits on ``NC_001145.3``, chromosome XIII -- so it is translated on cytosolic ribosomes
under NCBI table 1, and a presequence-targeted construct of it needs **no recoding**. Only genes
physically carried on ``NC_001224.1`` (the mtDNA) read under table 3. This module therefore
derives ``encoding_genome`` from the sequence accession in the header and **raises** on an
accession it does not recognise, rather than defaulting to ``'nuclear'``: silently assuming the
standard code is the exact failure `fermdb.genetic_code` exists to prevent, and the matrix is
served by *both* genomes, so the compartment could not answer the question anyway.

**The `gene_group` decision (PLAN.md C.3).** Every group here is anchored on the S288C systematic
name: ``anchor_namespace='sgd_systematic'``, ``anchor_id='YMR083W'``,
``membership_method='anchor'``, ``scope='species'``. Each group therefore has exactly **one**
member today -- the S288C gene row -- and that is the honest state, not an omission:

* A CEN.PK113-7D or Ethanol Red gene joins a group only through a recorded orthology run
  (``membership_method`` ``'rbh'`` / ``'ygob'`` / ``'orthofinder'``) carrying per-member identity
  evidence. No such run has been performed, so no such member is asserted.
* A cross-species counterpart (``ILV5`` ↔ *E. coli* ``ilvC``) is **never** merged in at all. That
  is an ``ortholog_link`` -- a claim with a method and a score -- because asserting the two are
  "the same gene" is a claim, not an identifier (CONVENTIONS.md, "Gene identity").
* A heterologous part in an engineered strain (``kivD``) belongs to *its own* organism's group and
  reaches the host through ``modification``. It does not become a yeast gene.

So the group is the stable join key the rest of the atlas quantifies and asserts against, and
widening it later adds member rows without ever re-pointing an existing id.

**Zones.** ``gene`` rows are Zone R: a verbatim parse of what RefSeq reported, with the single
transformation CONVENTIONS.md mandates at every parser boundary (1-based inclusive coordinates in
the file become 0-based half-open in the database). ``gene_group`` rows are Zone H: they are
constructed from those Zone R anchors by the code in this file and are rebuildable by re-running
it. Nothing here is Zone I -- there is no model, no heuristic and no inference anywhere in this
module.

**Where the DUET role is *not* stored, and why.** There is no column for it. ``gene_group`` and
``gene`` have no role field; ``gene_annotation.source`` is a closed CHECK set of external
annotation authorities (``sgd_go``, ``kegg``, ...) that a project-internal program role is not one
of; and ``predicate`` is a deliberately closed vocabulary (PLAN.md J.2) with no
"is-a-member-of-this-program" term. Stretching any of those to fit would record a fabrication in a
column that means something else. PLAN.md N's path layout already designates the right home --
``data/panels/`` , "curated gene panels per topic" -- so the role travels as a repo-tier TSV
(:func:`format_panel_tsv`), reviewed as a diff like every other curated fact, and the schema gap
is reported rather than papered over.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..config import Settings
from .references import ASSEMBLY_ACCESSION, MITOCHONDRIAL_ACCESSION, NUCLEAR_CHROMOSOME_ACCESSIONS

# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------

#: The RefSeq `rna_from_genomic` FASTA for GCF_000146045.2, under `Settings.genomes_dir`.
TRANSCRIPTS_FILENAME: Final[str] = "s288c.transcripts.fna.gz"

#: The uniformly reprocessed S288C TPM matrix, under `Settings.matrices_dir`. Its first column is
#: the systematic name, which is exactly what a resolution is checked against.
TPM_MATRIX_FILENAME: Final[str] = "s288c.tpm.tsv.gz"

#: The destination document whose §3 table names the gene set and its roles.
DUET_TARGET_DOC: Final[str] = "docs/design/DUET_TARGET.md"

#: `PDC6` is asked for by the phase-1 task and by PLAN.md E.4's "Ethanol and central carbon" list,
#: but it is **not** in DUET_TARGET.md §3 -- that table's competing/by-product row names
#: `PDC1 PDC5 ALD6 GPD1 BDH1 BDH2 ATF1 ECM31` and stops. So it is resolved like every other
#: symbol, and its role comes back `'unknown'` in the CONVENTIONS.md sense: somebody looked, in
#: the document that decides DUET's roles, and it was not there. That is a curator's call to make,
#: not this module's -- grouping it with PDC1/PDC5 because the names rhyme would be inference.
EXTRA_SYMBOLS: Final[tuple[str, ...]] = ("PDC6",)

#: Written where a controlled value was sought and not found. Never NULL (nobody looked) and never
#: 'NA' (not applicable) -- the three states stay distinct (CONVENTIONS.md, "Missing values").
UNKNOWN: Final[str] = "unknown"


class GeneResolutionError(ValueError):
    """An input file is missing, malformed, or says something this module refuses to guess at."""


# ---------------------------------------------------------------------------------------------
# FASTA header parsing
# ---------------------------------------------------------------------------------------------

_BRACKET_FIELD = re.compile(r"\[([A-Za-z_]+)=(.*?)\](?=\s|$)")
_HEADER_ACCESSION = re.compile(r"^>?lcl\|([A-Za-z]{2}_[0-9]+\.[0-9]+)_")
_GENEID = re.compile(r"\bGeneID:(\d+)\b")
_SEGMENT = re.compile(r"^[<>]?(\d+)(?:\.\.[<>]?(\d+))?$")


@dataclass(frozen=True)
class TranscriptHeader:
    """One parsed `>lcl|...` line. Every field is verbatim except the coordinates."""

    sequence_accession: str
    locus_tag: str
    gene: str | None
    gene_id: str | None
    product: str
    gbkey: str
    transcript_id: str | None
    location: str
    #: 0-based half-open [start_pos, end_pos), per CONVENTIONS.md "Coordinates and sequence".
    #: For a spliced feature this is the genomic extent (first segment's start to last segment's
    #: end), which is what a `gene` row's span means; the exon structure is not modelled here.
    start_pos: int
    end_pos: int
    #: +1 forward, -1 reverse. Never "+"/"-" outside this parser.
    strand: int


def parse_location(location: str) -> tuple[int, int, int]:
    """Convert an INSDC location string to 0-based half-open `(start, end, strand)`.

    Handles the five forms this assembly's FASTA actually contains -- `N..N`,
    `complement(N..N)`, `join(...)`, `complement(join(...))`, and the `<`/`>` partial markers NCBI
    puts on every mRNA feature whose CDS does not span the transcript. A `join` collapses to its
    genomic extent, and a bare `<N` segment (two of them exist in this file) is a single position.
    """
    text = location.strip()
    strand = 1
    if text.startswith("complement(") and text.endswith(")"):
        strand = -1
        text = text[len("complement(") : -1]
    if text.startswith("join(") and text.endswith(")"):
        text = text[len("join(") : -1]

    starts: list[int] = []
    ends: list[int] = []
    for segment in text.split(","):
        match = _SEGMENT.match(segment.strip())
        if match is None:
            raise GeneResolutionError(f"unparsable location segment {segment!r} in {location!r}")
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) is not None else first
        starts.append(first)
        ends.append(last)

    # 1-based inclusive in the file -> 0-based half-open in the database. This is one of the two
    # places CONVENTIONS.md allows the conversion to happen: a parser on the way in.
    return min(starts) - 1, max(ends), strand


def parse_transcript_header(line: str) -> TranscriptHeader:
    """Parse one FASTA header line. Raises rather than returning a half-filled record."""
    accession_match = _HEADER_ACCESSION.match(line.strip())
    if accession_match is None:
        raise GeneResolutionError(f"header carries no sequence accession: {line.strip()[:120]!r}")

    fields = {key: value for key, value in _BRACKET_FIELD.findall(line)}
    for required in ("locus_tag", "product", "gbkey", "location"):
        if required not in fields:
            raise GeneResolutionError(f"header is missing [{required}=...]: {line.strip()[:120]!r}")

    geneid_match = _GENEID.search(fields.get("db_xref", ""))
    start, end, strand = parse_location(fields["location"])
    return TranscriptHeader(
        sequence_accession=accession_match.group(1),
        locus_tag=fields["locus_tag"],
        # 993 of this file's 6,452 features are uncharacterised ORFs with no [gene=] at all.
        # NULL is correct for them: RefSeq recorded no standard name, it is not "unknown".
        gene=fields.get("gene"),
        gene_id=geneid_match.group(1) if geneid_match else None,
        product=fields["product"],
        gbkey=fields["gbkey"],
        transcript_id=fields.get("transcript_id"),
        location=fields["location"],
        start_pos=start,
        end_pos=end,
        strand=strand,
    )


def iter_transcript_headers(path: str | Path) -> Iterator[TranscriptHeader]:
    """Yield every header in a (gzipped) transcript FASTA, in file order."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                yield parse_transcript_header(line)


def sha256_of(path: str | Path) -> str:
    """The content hash recorded as this resolution's evidence. Read in blocks; the file is 3 MB."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------------
# Encoding genome
# ---------------------------------------------------------------------------------------------

#: The 16 nuclear chromosomes of GCF_000146045.2 and the mitochondrion, both taken from
#: `fermdb.omics.references`, where they were verified live against the NCBI Datasets API on
#: 2026-09-19. Imported rather than re-listed so there is one authority per fact.
ACCESSION_ENCODING_GENOME: Final[Mapping[str, str]] = {
    **{accession: "nuclear" for accession in NUCLEAR_CHROMOSOME_ACCESSIONS},
    MITOCHONDRIAL_ACCESSION: "mitochondrial",
}


def encoding_genome_for_accession(accession: str) -> str:
    """The genome that physically carries `accession`, hence the NCBI table it is read under.

    Raises on anything unrecognised. Defaulting to `'nuclear'` would be a guess that reads a
    table-3 gene under table 1, which is precisely the mistake `fermdb.genetic_code` is built to
    make impossible.
    """
    try:
        return ACCESSION_ENCODING_GENOME[accession]
    except KeyError as exc:
        known = ", ".join(sorted(ACCESSION_ENCODING_GENOME))
        raise GeneResolutionError(
            f"unknown sequence accession {accession!r}; refusing to assume an encoding genome. "
            f"Known accessions for {ASSEMBLY_ACCESSION}: {known}"
        ) from exc


# ---------------------------------------------------------------------------------------------
# DUET_TARGET.md §3: the role table, parsed
# ---------------------------------------------------------------------------------------------

_SECTION_3 = re.compile(r"^##\s+3\.\s", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^##\s+\d", re.MULTILINE)
_BACKTICKED = re.compile(r"`([A-Za-z][A-Za-z0-9_-]*)`")


@dataclass(frozen=True)
class DuetRole:
    """One row of DUET_TARGET.md §3: the document's own label, plus a stable slug for it."""

    slug: str
    label: str


def _slugify_role(label: str) -> str:
    """Role label to slug: `'Competing / by-product'` -> `'competing_by_product'`."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", label.lower())).strip("_")


def parse_duet_roles(markdown: str) -> dict[str, DuetRole]:
    """Map gene symbol -> role, read out of DUET_TARGET.md §3's table.

    Parsed, not transcribed: the destination document decides which genes serve which part of the
    program, and a copy of that table in Python would be a second authority that could drift.
    Gene symbols are the backticked tokens in the second column, so the prose in parentheses
    ("(mitochondrial NADH kinase)") and the `**bold**` emphasis around them are both ignored.
    """
    start = _SECTION_3.search(markdown)
    if start is None:
        raise GeneResolutionError(f"{DUET_TARGET_DOC}: no '## 3.' section found")
    tail = markdown[start.end() :]
    end = _NEXT_SECTION.search(tail)
    section = tail[: end.start()] if end else tail

    roles: dict[str, DuetRole] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        label = cells[0].replace("*", "").strip()
        if not label or label.lower() == "role" or set(label) <= set("-: "):
            continue
        role = DuetRole(slug=_slugify_role(label), label=label)
        for symbol in _BACKTICKED.findall(cells[1]):
            if symbol in roles and roles[symbol] != role:
                raise GeneResolutionError(
                    f"{DUET_TARGET_DOC} §3 gives {symbol} two roles: "
                    f"{roles[symbol].label!r} and {role.label!r}"
                )
            roles[symbol] = role
    if not roles:
        raise GeneResolutionError(f"{DUET_TARGET_DOC} §3: no gene symbols found in the table")
    return roles


def duet_symbols(roles: Mapping[str, DuetRole]) -> tuple[str, ...]:
    """The symbols to resolve: DUET_TARGET §3's own set, plus `EXTRA_SYMBOLS`, sorted."""
    return tuple(sorted(set(roles) | set(EXTRA_SYMBOLS)))


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedGene:
    """One DUET symbol, resolved to everything the FASTA header states about it."""

    symbol: str
    systematic_name: str
    ncbi_gene_id: str | None
    product: str
    encoding_genome: str
    sequence_accession: str
    start_pos: int
    end_pos: int
    strand: int
    #: `'unknown'` where DUET_TARGET §3 does not place the gene; see `EXTRA_SYMBOLS`.
    role_slug: str
    role_label: str

    @property
    def gene_group_id(self) -> str:
        return gene_group_id(self.systematic_name)

    @property
    def gene_id(self) -> str:
        return gene_id(self.systematic_name, ASSEMBLY_ACCESSION)


@dataclass(frozen=True)
class ResolutionGap:
    """A symbol the transcript FASTA does not contain. Recorded, reported, and never guessed."""

    symbol: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    """The full result: what resolved, what did not, and against exactly which bytes."""

    genes: tuple[ResolvedGene, ...]
    gaps: tuple[ResolutionGap, ...]
    assembly_accession: str
    source_path: str
    source_sha256: str

    @property
    def evidence(self) -> str:
        """The `evidence` string every row this resolution writes carries."""
        return (
            f"RefSeq rna_from_genomic FASTA for assembly {self.assembly_accession}, "
            f"parsed from {self.source_path} (sha256 {self.source_sha256})"
        )


def gene_group_id(systematic_name: str) -> str:
    """`'YMR083W'` -> `'YAA:GG:ymr083w'` (CONVENTIONS.md, "Identifiers")."""
    return f"YAA:GG:{systematic_name.lower()}"


def _assembly_slug(assembly_accession: str) -> str:
    return assembly_accession.lower().replace("_", "-").replace(".", "-")


def gene_id(systematic_name: str, assembly_accession: str) -> str:
    """`'YMR083W'`, `'GCF_000146045.2'` -> `'YAA:GENE:gcf-000146045-2-ymr083w'`.

    The assembly is *inside* the id on purpose. `genome-db` found 520 gene ids shared between two
    assemblies while naming different genes, and `gene.assembly_accession` is NOT NULL for the
    same reason; an id that omits the assembly invites exactly the join that mistake enables.
    """
    return f"YAA:GENE:{_assembly_slug(assembly_accession)}-{systematic_name.lower()}"


def resolve_symbols(
    symbols: Sequence[str],
    headers: Iterable[TranscriptHeader],
    roles: Mapping[str, DuetRole],
    *,
    assembly_accession: str = ASSEMBLY_ACCESSION,
    source_path: str = "",
    source_sha256: str = "",
) -> Resolution:
    """Resolve `symbols` against parsed FASTA `headers`. One pass, no network, no inference."""
    wanted = set(symbols)
    by_symbol: dict[str, TranscriptHeader] = {}
    for header in headers:
        if header.gene is None or header.gene not in wanted:
            continue
        if header.gene in by_symbol:
            # Two transcripts claiming one standard name would make the mapping ambiguous, and
            # picking one would be a guess. This assembly has no such case; if a future one does,
            # it must be resolved by a curator, not silently.
            raise GeneResolutionError(
                f"{header.gene} appears on two features "
                f"({by_symbol[header.gene].locus_tag} and {header.locus_tag}); "
                "refusing to choose between them"
            )
        by_symbol[header.gene] = header

    genes: list[ResolvedGene] = []
    gaps: list[ResolutionGap] = []
    for symbol in sorted(wanted):
        found = by_symbol.get(symbol)
        if found is None:
            gaps.append(
                ResolutionGap(
                    symbol=symbol,
                    reason=(
                        f"no feature with [gene={symbol}] in the {assembly_accession} "
                        "transcript FASTA"
                    ),
                )
            )
            continue
        role = roles.get(symbol)
        genes.append(
            ResolvedGene(
                symbol=symbol,
                systematic_name=found.locus_tag,
                ncbi_gene_id=found.gene_id,
                product=found.product,
                encoding_genome=encoding_genome_for_accession(found.sequence_accession),
                sequence_accession=found.sequence_accession,
                start_pos=found.start_pos,
                end_pos=found.end_pos,
                strand=found.strand,
                role_slug=role.slug if role else UNKNOWN,
                role_label=role.label if role else UNKNOWN,
            )
        )
    return Resolution(
        genes=tuple(genes),
        gaps=tuple(gaps),
        assembly_accession=assembly_accession,
        source_path=source_path,
        source_sha256=source_sha256,
    )


def resolve_duet_gene_set(
    transcripts_path: str | Path,
    duet_target_path: str | Path,
    *,
    assembly_accession: str = ASSEMBLY_ACCESSION,
) -> Resolution:
    """The whole phase-1 resolution, from the two files on disk."""
    transcripts_path = Path(transcripts_path)
    roles = parse_duet_roles(Path(duet_target_path).read_text(encoding="utf-8"))
    return resolve_symbols(
        duet_symbols(roles),
        iter_transcript_headers(transcripts_path),
        roles,
        assembly_accession=assembly_accession,
        source_path=transcripts_path.name,
        source_sha256=sha256_of(transcripts_path),
    )


# ---------------------------------------------------------------------------------------------
# Verification against the expression matrix
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MatrixCheck:
    """Which resolved systematic names the reprocessed TPM matrix actually carries a row for."""

    present: tuple[str, ...]
    missing: tuple[str, ...]
    matrix_rows: int

    @property
    def ok(self) -> bool:
        return not self.missing


def matrix_row_names(path: str | Path) -> tuple[str, ...]:
    """The first column of every data row of a gzipped TSV matrix, in file order."""
    names: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        next(handle, None)  # header row: 'gene' then one column per run accession
        for line in handle:
            if line.strip():
                names.append(line.split("\t", 1)[0])
    return tuple(names)


def verify_against_matrix(resolution: Resolution, row_names: Iterable[str]) -> MatrixCheck:
    """Check every resolved systematic name against the matrix's row index.

    A miss is a real finding, not a nuisance: it means the quantification reference and the
    annotation this resolution was built from disagree about which genes exist, and every
    expression answer for that gene would silently be empty.
    """
    rows = set(row_names)
    present = tuple(g.systematic_name for g in resolution.genes if g.systematic_name in rows)
    missing = tuple(g.systematic_name for g in resolution.genes if g.systematic_name not in rows)
    return MatrixCheck(present=present, missing=missing, matrix_rows=len(rows))


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------

#: The S288C organism row every `gene` row points at. `ncbi_taxid` and its provenance are taken
#: from data/omics/reference_genomes.yaml's `s288c_r64` entry, which records the taxid as verified
#: live against NCBI Taxonomy on 2026-09-20 -- not recalled here.
ORGANISM_ID: Final[str] = "YAA:ORG:saccharomyces-cerevisiae-s288c"
ORGANISM_NAME: Final[str] = "Saccharomyces cerevisiae S288C"
ORGANISM_TAXID: Final[int] = 559292


def organism_row() -> dict[str, object]:
    return {
        "id": ORGANISM_ID,
        "ncbi_taxid": ORGANISM_TAXID,
        "name": ORGANISM_NAME,
        "rank": "strain",
        "zone": "R",
        "evidence": (
            "data/omics/reference_genomes.yaml entry 's288c_r64' (taxid 559292, assembly "
            f"{ASSEMBLY_ACCESSION}); that entry records the taxid as verified live against NCBI "
            "Taxonomy esearch on 2026-09-20"
        ),
        "confidence": "high",
    }


def gene_group_rows(resolution: Resolution) -> list[dict[str, object]]:
    """One anchor group per resolved gene (PLAN.md C.3).

    Zone H: constructed from the Zone R anchor by this code, and rebuildable by re-running it.
    """
    return [
        {
            "id": gene.gene_group_id,
            "anchor_namespace": "sgd_systematic",
            "anchor_id": gene.systematic_name,
            "standard_name": gene.symbol,
            "scope": "species",
            "membership_method": "anchor",
            "zone": "H",
            "evidence": (
                f"anchored on the S288C systematic name {gene.systematic_name}; "
                f"{resolution.evidence}"
            ),
            # The anchor itself is a verbatim RefSeq locus_tag, not a recollection and not an
            # orthology call -- there is nothing left to verify about a one-member anchor group.
            "confidence": "high",
        }
        for gene in resolution.genes
    ]


def gene_rows(resolution: Resolution) -> list[dict[str, object]]:
    """One S288C gene row per resolved gene. Zone R: a verbatim parse of the RefSeq header."""
    return [
        {
            "id": gene.gene_id,
            "organism_id": ORGANISM_ID,
            "assembly_accession": resolution.assembly_accession,
            "systematic_name": gene.systematic_name,
            "standard_name": gene.symbol,
            "gene_group_id": gene.gene_group_id,
            "start_pos": gene.start_pos,
            "end_pos": gene.end_pos,
            "strand": gene.strand,
            "zone": "R",
            "evidence": (
                f"[locus_tag={gene.systematic_name}] [gene={gene.symbol}] "
                f"[db_xref=GeneID:{gene.ncbi_gene_id}] [product={gene.product}] on "
                f"{gene.sequence_accession} ({gene.encoding_genome}-encoded); "
                f"{resolution.evidence}"
            ),
            "confidence": "high",
        }
        for gene in resolution.genes
    ]


_UPSERT_ORGANISM = """
INSERT INTO organism (id, ncbi_taxid, name, rank, zone, evidence, confidence)
VALUES (:id, :ncbi_taxid, :name, :rank, :zone, :evidence, :confidence)
ON CONFLICT(id) DO NOTHING
"""

_UPSERT_GENE_GROUP = """
INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope,
                        membership_method, zone, evidence, confidence)
VALUES (:id, :anchor_namespace, :anchor_id, :standard_name, :scope,
        :membership_method, :zone, :evidence, :confidence)
ON CONFLICT(id) DO UPDATE SET
    anchor_namespace = excluded.anchor_namespace,
    anchor_id        = excluded.anchor_id,
    standard_name    = excluded.standard_name,
    scope            = excluded.scope,
    membership_method= excluded.membership_method,
    zone             = excluded.zone,
    evidence         = excluded.evidence,
    confidence       = excluded.confidence
"""

_UPSERT_GENE = """
INSERT INTO gene (id, organism_id, assembly_accession, systematic_name, standard_name,
                  gene_group_id, start_pos, end_pos, strand, zone, evidence, confidence)
VALUES (:id, :organism_id, :assembly_accession, :systematic_name, :standard_name,
        :gene_group_id, :start_pos, :end_pos, :strand, :zone, :evidence, :confidence)
ON CONFLICT(id) DO UPDATE SET
    organism_id        = excluded.organism_id,
    assembly_accession = excluded.assembly_accession,
    systematic_name    = excluded.systematic_name,
    standard_name      = excluded.standard_name,
    gene_group_id      = excluded.gene_group_id,
    start_pos          = excluded.start_pos,
    end_pos            = excluded.end_pos,
    strand             = excluded.strand,
    zone               = excluded.zone,
    evidence           = excluded.evidence,
    confidence         = excluded.confidence
"""


def write_resolution(conn: sqlite3.Connection, resolution: Resolution) -> dict[str, int]:
    """Write organism, `gene_group` and `gene` rows in one short transaction.

    The database is shared with other agents and runs in WAL mode, so the caller sets
    `PRAGMA busy_timeout` and this function keeps the write window as small as it can: build every
    row first, then one `BEGIN IMMEDIATE`, then commit. Does not open or close `conn` --
    `fermdb.db.open_db` is the only function that does that.
    """
    organism = organism_row()
    groups = gene_group_rows(resolution)
    genes = gene_rows(resolution)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(_UPSERT_ORGANISM, organism)
        conn.executemany(_UPSERT_GENE_GROUP, groups)
        conn.executemany(_UPSERT_GENE, genes)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return {"organism": 1, "gene_group": len(groups), "gene": len(genes)}


# ---------------------------------------------------------------------------------------------
# The panel TSV (data/panels/, PLAN.md N.2) -- where the DUET role lives, for want of a column
# ---------------------------------------------------------------------------------------------

PANEL_FILENAME: Final[str] = "duet.tsv"

PANEL_COLUMNS: Final[tuple[str, ...]] = (
    "standard_name",
    "systematic_name",
    "gene_group_id",
    "ncbi_gene_id",
    "encoding_genome",
    "duet_role",
    "duet_role_label",
    "product",
    "evidence",
    "confidence",
)


def format_panel_tsv(resolution: Resolution) -> str:
    """Render the DUET panel as a commented, reviewable TSV (CONVENTIONS.md, "Curation").

    Two different provenances travel in one file, so each row carries its own. The identity
    columns are a verbatim parse of a checksummed RefSeq artifact. The `duet_role` columns are the
    owner's own grouping in DUET_TARGET.md §3, transcribed there from the concept note and never
    checked against a primary source by this project -- `unverified`, exactly as CONVENTIONS.md
    requires, and a row whose role is `unknown` says that the role table was consulted and did not
    place that gene.
    """
    lines = [
        "# DUET gene panel -- PLAN.md E.4 phase-1 resolution, PLAN.md N.2 data/panels/.",
        "#",
        "# GENERATED by src/fermdb/omics/genes.py from two sources, and reviewed as a diff:",
        f"#   identity columns : {resolution.source_path} (sha256 {resolution.source_sha256}),",
        "#                      the RefSeq rna_from_genomic FASTA for "
        f"{resolution.assembly_accession}",
        f"#   duet_role columns: {DUET_TARGET_DOC} §3, parsed from its Markdown table",
        "#",
        "# The role lives here rather than in the database because no table models it: gene and",
        "# gene_group have no role column, gene_annotation.source is a closed set of external",
        "# annotation authorities, and `predicate` is a closed vocabulary with no membership term.",
        "# Recording it in one of those would be a fabrication in a column that means something",
        "# else. See this module's docstring.",
        "#",
        "# duet_role 'unknown' = the role table was consulted and does not place this gene.",
        "# It is not NULL (nobody looked) and not 'NA' (not applicable).",
        "\t".join(PANEL_COLUMNS),
    ]
    for gene in resolution.genes:
        lines.append(
            "\t".join(
                (
                    gene.symbol,
                    gene.systematic_name,
                    gene.gene_group_id,
                    gene.ncbi_gene_id or "",
                    gene.encoding_genome,
                    gene.role_slug,
                    gene.role_label,
                    gene.product,
                    f"{DUET_TARGET_DOC} §3 for the role; {resolution.evidence} for the identity",
                    "unverified",
                )
            )
        )
    for gap in resolution.gaps:
        lines.append(f"# GAP\t{gap.symbol}\t{gap.reason}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# Wiring it together
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildReport:
    """What one run of :func:`build` did, for the caller to print or assert on."""

    resolution: Resolution
    matrix_check: MatrixCheck
    written: Mapping[str, int]
    panel_path: Path | None


def build(
    settings: Settings,
    conn: sqlite3.Connection,
    *,
    repo_root: Path | None = None,
    write_panel: bool = True,
) -> BuildReport:
    """Resolve, verify against the TPM matrix, write the rows, and emit the panel TSV."""
    root = repo_root if repo_root is not None else settings.repo_root
    resolution = resolve_duet_gene_set(
        Path(settings.genomes_dir) / TRANSCRIPTS_FILENAME,
        root / DUET_TARGET_DOC,
    )
    check = verify_against_matrix(
        resolution, matrix_row_names(Path(settings.matrices_dir) / TPM_MATRIX_FILENAME)
    )
    written = write_resolution(conn, resolution)

    panel_path: Path | None = None
    if write_panel:
        panel_dir = Path(settings.panels_dir)
        panel_dir.mkdir(parents=True, exist_ok=True)
        panel_path = panel_dir / PANEL_FILENAME
        panel_path.write_text(format_panel_tsv(resolution), encoding="utf-8")

    return BuildReport(
        resolution=resolution, matrix_check=check, written=written, panel_path=panel_path
    )
