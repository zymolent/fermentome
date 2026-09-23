"""The protein translation QC gate of PLAN.md E.3, run over a whole annotation.

PLAN.md E.3 states it and calls it non-negotiable:

    **The protein QC gate.** Re-splice and translate every CDS, compare to the source protein
    FASTA, refuse the ingest below a threshold. `genome-db` runs this at 99.5% and reports
    99.86% achieved. It catches phase errors, coordinate errors and off-by-ones that are
    otherwise invisible until a promoter sequence is silently wrong. **Non-negotiable; it is
    the cheapest correctness insurance in the whole system.**

**What it is actually for.** Nothing else in this atlas ever notices a one-base coordinate error.
`gff3.py`'s module docstring already makes the argument -- "one base out on 6,600 genes would
frame-shift every downstream sequence extraction and silently misplace every interval join" -- and
asserts the 1-based-to-0-based conversion against three loci whose spans were curated by hand.
Three loci is a spot check. This is the same claim tested against every CDS in the file, using the
one piece of evidence that cannot be got wrong in the same direction as the coordinates: the
protein sequence NCBI published from those same coordinates. A frameshift survives a schema CHECK,
a length-divisible-by-three assertion and a reviewer; it does not survive being translated.

**The table is resolved per sequence, and never defaulted.** This atlas exists for mitochondrial
engineering (docs/design/MITOCHONDRIAL_PROGRAM.md), and `genetic_code.py` is a module written
because the compartment-keyed version of it "would have told a bench scientist to recode a
construct that must not be recoded". A QC gate that assumed NCBI table 1 would report a clean
99.9% on an S288C annotation while every one of the 50 mtDNA CDS lines in it was mistranslated --
and it would look *more* convincing than a gate that noticed, because 50 out of 6,386 is 0.8% and
the threshold is 0.5%. Resolution order, most specific first:

1. `transl_table=` on the CDS feature itself. The annotation's own statement about that CDS.
   NCBI writes it on all 50 mitochondrial CDS lines of GCF_000146045.2 and on all 4,340 CDS of
   GCF_000005845.2 (E. coli, table 11), and omits it everywhere it would say 1.
2. The `genome=` attribute on the sequence's `region` feature -- `genome=mitochondrion` for
   NC_001224.1, `genome=chromosome` for the sixteen nuclear ones -- mapped to an encoding genome
   and then through `genetic_code.ENCODING_GENOME_TABLE`, which is the same mapping the atlas's
   `encoding_genome` table holds (tests/test_schema.py keeps the two in agreement, which is why
   this module needs no database connection to honour the schema's authority on the point).
3. `--genetic-code SEQID=N`, which the operator types. A declaration that *disagrees* with the
   annotation does not win: it is recorded as a disagreement and the annotation is used, the
   same way `load_genes` keeps the stored value and reports the clash.
4. Nothing. The CDS is `no_genetic_code` -- refused by name, counted against the identity
   fraction, and printed. It is not read under table 1.

**The one residual assumption, stated rather than hidden.** Route 2 reads `genome=chromosome` as
nuclear-and-therefore-table-1. That is sound for a RefSeq file, because RefSeq writes
`transl_table=` wherever the answer is not 1 and route 1 has already answered by then. It is not
sound for a submitter-generated GFF3 of a bacterium that omits the qualifier: table 11 differs
from table 1 only in its start codons, so such a file would pass this gate rather than fail it.
`--genetic-code` is how that is removed, and the report prints how many CDS took each route so
the assumption is visible in every run rather than only in this docstring.

**Two normalisations are applied, and both are counted.** A protein FASTA record does not carry
the terminal stop codon the CDS encodes, and NCBI writes an initiator methionine even where the
start codon is one of the alternatives its own table lists (`TTG`/`CTG` under table 1). Neither is
a defect and neither may be silently absorbed either: `trailing_stop_trimmed` and
`alternative_start_to_methionine` appear as counts in the report, so a run in which they fire on a
surprising number of genes is visible. A third count, `declared_phase_disagrees`, is not a
normalisation at all but the finding this gate is named for: a downstream CDS segment whose
`phase` column contradicts the lengths of the segments before it. The translation is taken from
the coordinates and is usually still exact, which is exactly why the count has to be printed --
an internally inconsistent phase is invisible in the identity number and is a genuine defect in
the annotation or in whatever wrote it.

**The metric is per protein, not per residue.** One gene frameshifted end to end costs 1/6386 of
a per-protein score and almost nothing of a per-residue average, and it is the frameshifted gene
that ruins a promoter extraction. So the number the threshold is compared against is the fraction
of CDS in the annotation that reproduce their protein record *exactly*, after the two
normalisations above. Everything that is not `exact` -- a mismatch, an internal stop, an
ambiguity, an unresolvable table, a CDS whose protein record is absent -- counts against it.

**A pseudogene CDS counts as a failure, and that is deliberate.** RefSeq gives six loci in
GCF_000146045.2 -- CCW22, FLO8, SDL1, YIR043C, YOL153C and YOR031W -- a `pseudo=true` CDS with no
`protein_id` and no record in the protein FASTA, so they can never be `exact` and they hold that
annotation permanently at 6021/6027 rather than 6021/6021. Excluding them would raise the measured
identity by 0.1% for free, which is precisely the shape of change PLAN.md S.2 forbids: the
exclusion would have been invented after seeing which rows it helped. They stay in the
denominator, the verdict detail says `pseudo=true` so nobody has to go and look it up, and the
gate passes on the number it actually measured.

A protein FASTA record that no CDS produces is the one case outside that fraction: there is no CDS
to re-splice, so E.3's sentence does not reach it. It is reported as `missing_model`, counted, and
named in the output, because a protein the annotation cannot account for is a real finding about
the pair of files -- it is simply not a translation failure.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO
from urllib.parse import unquote

from ..genetic_code import ENCODING_GENOME_TABLE, TABLES, GeneticCode, translate
from .gff3 import Gff3Error, parse_attributes, parse_strand

__all__ = [
    "AMBIGUOUS",
    "ALTERNATIVE_START",
    "CdsModel",
    "CdsSegment",
    "CodeResolution",
    "DECLARED_PHASE_DISAGREES",
    "EXACT",
    "GeneticCodeDisagreement",
    "INTERNAL_STOP",
    "MIN_PROTEIN_IDENTITY",
    "MISMATCH",
    "MISSING_MODEL",
    "MISSING_PROTEIN",
    "NO_GENETIC_CODE",
    "ParsedAnnotation",
    "ProteinQcReport",
    "ProteinVerdict",
    "REGION_GENOME_ENCODING",
    "TRAILING_PARTIAL_CODON",
    "TRAILING_STOP_TRIMMED",
    "UNSUPPORTED_GENETIC_CODE",
    "UNTRANSLATABLE",
    "VERDICTS",
    "check_cds",
    "format_report",
    "parse_annotation",
    "read_fasta",
    "read_genome",
    "read_proteins",
    "resolve_genetic_code",
    "reverse_complement",
    "run_protein_qc",
    "splice_cds",
]

#: The fraction of CDS that must reproduce their protein record exactly, or the ingest is refused.
#:
#: **Provenance: 99.5%, carried verbatim from `genome-db`, which runs this gate at that value and
#: reports 99.86% achieved** (PLAN.md E.3). It is not derived from anything in this repository and
#: it was written down before this module was first run against any annotation, which is the whole
#: of PLAN.md S.2: *"A threshold chosen after looking at the results it will filter is not a
#: quality gate, it is a rationalization."* A run that comes in under it is a finding about the
#: annotation, the genome FASTA or this code -- never a reason to edit this line.
#:
#: **The owner has final say on this value.** Changing it is a reviewed diff to this constant and,
#: per S.2, requires re-running everything it gated; it is not a command-line flag, and
#: `fermdb genomics protein-qc` deliberately offers no way to override it for one run.
MIN_PROTEIN_IDENTITY: Final[float] = 0.995

# ---------------------------------------------------------------------------------- the verdicts
#
# One per CDS, and one per protein record no CDS produced. Named rather than boolean because the
# failures are not interchangeable: an internal stop is a frame or coordinate error, an ambiguity
# is an unread base in the assembly, an absent protein record is a mismatch between two files, and
# an unresolved genetic code is this gate declining to guess. Collapsing them into "failed" would
# throw away the only thing that tells a curator which of those to go and look at.

#: The translation reproduced the protein record, after the counted normalisations. The only pass.
EXACT: Final[str] = "exact"
#: Differs somewhere that is neither a stop nor an ambiguity. A coordinate or strand error.
MISMATCH: Final[str] = "mismatch"
#: A stop codon before the end of the CDS. Almost always a frameshift or a wrong phase.
INTERNAL_STOP: Final[str] = "internal_stop"
#: Every difference sits at a residue no codon table produces -- an `X` from an ambiguity codon in
#: the assembly, or a `U`/`O` (selenocysteine, pyrrolysine) the protein record reads through a
#: codon this table calls something else. Counted separately and **not** a pass: an `X` is a base
#: the assembly does not know, and passing it would mean the gate accepted a sequence it could
#: not read.
AMBIGUOUS: Final[str] = "ambiguous"
#: There is no sequence to translate: the seqid is absent from the genome FASTA, the CDS runs off
#: the end of it, or it is shorter than one whole codon.
UNTRANSLATABLE: Final[str] = "untranslatable"
#: No route stated a genetic code for this sequence. Refused rather than read under table 1.
NO_GENETIC_CODE: Final[str] = "no_genetic_code"
#: A table was stated and `fermdb.genetic_code` does not implement it -- table 11 for every
#: bacterial CDS in this corpus's E. coli and Z. mobilis annotations. Refused by name.
UNSUPPORTED_GENETIC_CODE: Final[str] = "unsupported_genetic_code"
#: The annotation has a CDS whose `protein_id` names no record in the protein FASTA.
MISSING_PROTEIN: Final[str] = "missing_protein"
#: The protein FASTA has a record no CDS in the annotation produces. Outside the identity
#: fraction -- there is no CDS to re-splice -- but counted and named.
MISSING_MODEL: Final[str] = "missing_model"

#: Every verdict, in report order. Printed in full including the zeroes, so a reader sees the
#: whole vocabulary and can tell "none of these" from "this gate does not look for that".
VERDICTS: Final[tuple[str, ...]] = (
    EXACT,
    MISMATCH,
    INTERNAL_STOP,
    AMBIGUOUS,
    UNTRANSLATABLE,
    NO_GENETIC_CODE,
    UNSUPPORTED_GENETIC_CODE,
    MISSING_PROTEIN,
    MISSING_MODEL,
)

#: The CDS encoded a terminal stop the protein record does not carry. The NCBI norm.
TRAILING_STOP_TRIMMED: Final[str] = "trailing_stop_trimmed"
#: The first codon is one of this table's start codons but is not `ATG`, and the protein record
#: begins with methionine. NCBI's own convention, applied only at position 1 and only when the
#: codon really is a start codon for the table this CDS was resolved to.
ALTERNATIVE_START: Final[str] = "alternative_start_to_methionine"
#: The spliced CDS length is not a multiple of three, so a partial codon was discarded. Legitimate
#: on a `partial=true` gene running off the end of a contig, and a defect anywhere else.
TRAILING_PARTIAL_CODON: Final[str] = "trailing_partial_codon"
#: A downstream CDS segment's `phase` column contradicts the lengths of the segments before it.
#: Not a normalisation -- nothing is adjusted -- but counted and printed beside them.
DECLARED_PHASE_DISAGREES: Final[str] = "declared_phase_disagrees"

NORMALISATIONS: Final[tuple[str, ...]] = (
    TRAILING_STOP_TRIMMED,
    ALTERNATIVE_START,
    TRAILING_PARTIAL_CODON,
    DECLARED_PHASE_DISAGREES,
)

#: `genome=` on a GFF3 `region` feature -> the atlas's `encoding_genome` id. Deliberately partial:
#: a token that is not here (`plasmid`, `chloroplast`, `apicoplast`, an absent attribute) resolves
#: to nothing and the CDS is refused, because the failure this whole module exists to prevent is
#: an organelle read under the wrong code.
REGION_GENOME_ENCODING: Final[dict[str, str]] = {
    "chromosome": "nuclear",
    "genomic": "nuclear",
    "linkage group": "nuclear",
    "mitochondrion": "mitochondrial",
}

#: Residues no codon table emits. A difference at one of these is an ambiguity, not a mismatch:
#: `X`/`B`/`Z`/`J` are ambiguity codes on either side, and `U`/`O` are the two co-translationally
#: inserted residues (selenocysteine, pyrrolysine) that a protein record can carry at a position
#: whose codon every NCBI table calls something else.
NON_CODING_RESIDUES: Final[frozenset[str]] = frozenset("XUOBZJ")

_COMPLEMENT: Final[dict[str, str]] = {
    "A": "T",
    "T": "A",
    "G": "C",
    "C": "G",
    "N": "N",
    "U": "A",
    "R": "Y",
    "Y": "R",
    "S": "S",
    "W": "W",
    "K": "M",
    "M": "K",
    "B": "V",
    "V": "B",
    "D": "H",
    "H": "D",
}


def reverse_complement(sequence: str) -> str:
    """Reverse-complement, mapping anything unrecognised to `N`.

    `N` rather than a raise, and unlike `omics.mito_transcripts._reverse_complement` this keeps
    the IUPAC ambiguity codes as their own complements instead of flattening them: a `Y` that
    became `N` on the minus strand would translate to `X` on one strand and possibly not on the
    other, which would make a verdict depend on which strand a gene happens to sit on.
    """
    return "".join(_COMPLEMENT.get(base, "N") for base in reversed(sequence))


# --------------------------------------------------------------------------------- the gene model


@dataclass(frozen=True)
class CdsSegment:
    """One CDS line. Coordinates 0-based half-open, per CONVENTIONS.md."""

    start_pos: int
    end_pos: int
    #: GFF3 column 8: bases to remove from the start of this segment to reach a codon boundary.
    phase: int
    line_number: int

    @property
    def length(self) -> int:
        return self.end_pos - self.start_pos


@dataclass(frozen=True)
class CdsModel:
    """Every CDS line that belongs to one protein, plus what the annotation said about it."""

    #: The join key to the protein FASTA. `protein_id=` where the annotation gives one; failing
    #: that the CDS feature's own `ID`, which will not match any FASTA record and so becomes a
    #: `missing_protein` rather than a crash -- 6 of the 6,386 CDS lines in GCF_000146045.2 carry
    #: no `protein_id` at all.
    protein_id: str
    seqid: str
    #: `+1` / `-1` / `0`, as `gff3.parse_strand` returns. A CDS on strand `0` cannot be spliced.
    strand: int
    locus_tag: str | None
    gene: str | None
    product: str | None
    segments: tuple[CdsSegment, ...]
    #: `transl_table=` on the CDS feature, where the annotation stated one.
    declared_table: int | None
    #: `pseudo=true`. RefSeq publishes no protein for these, so they land as `missing_protein`
    #: and the flag is what lets the report say so rather than leaving a curator to look it up.
    pseudo: bool = False

    @property
    def coding_length(self) -> int:
        return sum(segment.length for segment in self.segments)

    @property
    def ordered_segments(self) -> tuple[CdsSegment, ...]:
        """Segments in *translation* order: ascending on the plus strand, descending on the minus.

        GFF3 writes CDS lines in ascending coordinate order on both strands, so a minus-strand
        gene's first codon is in the line with the **highest** start. Taking them in file order
        and reverse-complementing the whole concatenation gives the same answer here only because
        reverse-complement of a concatenation is the reverse concatenation of the
        reverse-complements -- but the phase belongs to a particular segment, and picking the
        wrong end's phase is a silent one- or two-base frameshift on every minus-strand gene.
        """
        return tuple(sorted(self.segments, key=lambda s: s.start_pos, reverse=self.strand < 0))


@dataclass(frozen=True)
class ParsedAnnotation:
    """What one GFF3 says about coding sequences, and about the sequences they sit on."""

    cds: tuple[CdsModel, ...]
    #: seqid -> the `genome=` attribute of its `region` feature. The key is present with a value
    #: of `None` when the region feature exists but states no `genome=`, and absent entirely when
    #: the file has no region feature for that sequence. The two are different failures and
    #: CONVENTIONS.md ("Missing values") does not let them be collapsed.
    sequence_genome: Mapping[str, str | None]


@dataclass(frozen=True)
class CodeResolution:
    """Which NCBI table a CDS is read under, and which of the four routes said so."""

    table_id: int | None
    #: 'annotation' | 'region' | 'declared' | 'none'
    source: str
    encoding_genome: str | None
    detail: str

    @property
    def code(self) -> GeneticCode | None:
        """The table, or `None` when it is unresolved *or* not one this atlas implements."""
        if self.table_id is None:
            return None
        return TABLES.get(self.table_id)


@dataclass(frozen=True)
class GeneticCodeDisagreement:
    """An operator declaration that contradicts the annotation. Recorded; the annotation wins."""

    seqid: str
    declared_table: int
    annotation_table: int
    source: str


@dataclass(frozen=True)
class ProteinVerdict:
    """The gate's answer for one CDS, or for one protein record no CDS produced."""

    protein_id: str
    verdict: str
    seqid: str | None
    strand: int
    locus_tag: str | None
    gene: str | None
    table_id: int | None
    code_source: str
    segments: int
    coding_length: int
    translated_length: int
    reference_length: int
    mismatches: int
    #: 1-based residue position of the first difference, for the human report. `None` when the
    #: sequences agree or when no comparison was possible.
    first_mismatch: int | None
    normalisations: tuple[str, ...]
    detail: str

    @property
    def is_pass(self) -> bool:
        return self.verdict == EXACT

    @property
    def from_gene_model(self) -> bool:
        """False only for `missing_model`, which is the one verdict with no CDS behind it."""
        return self.verdict != MISSING_MODEL


@dataclass(frozen=True)
class ProteinQcReport:
    """Everything the gate found, and the one number the threshold is compared against."""

    threshold: float
    verdicts: tuple[ProteinVerdict, ...]
    disagreements: tuple[GeneticCodeDisagreement, ...]
    #: seqid -> (table_id, route), for the per-sequence summary the report prints. This is where a
    #: mitochondrion read under table 1 would be visible at a glance rather than as 50 mismatches.
    sequence_codes: Mapping[str, tuple[int | None, str]]

    @property
    def cds_verdicts(self) -> tuple[ProteinVerdict, ...]:
        return tuple(v for v in self.verdicts if v.from_gene_model)

    @property
    def checked(self) -> int:
        """The denominator: every CDS in the annotation, per E.3's "every CDS"."""
        return len(self.cds_verdicts)

    @property
    def exact(self) -> int:
        return sum(1 for v in self.cds_verdicts if v.is_pass)

    @property
    def identity(self) -> float:
        """Fraction of CDS that reproduce their protein record exactly. `0.0` for an empty run."""
        if self.checked == 0:
            return 0.0
        return self.exact / self.checked

    @property
    def passed(self) -> bool:
        """An annotation with no CDS at all fails. It has not been verified, and a gate that
        returns "pass" for a file it never read is worse than no gate."""
        return self.checked > 0 and self.identity >= self.threshold

    def verdict_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(VERDICTS, 0)
        for verdict in self.verdicts:
            counts[verdict.verdict] = counts.get(verdict.verdict, 0) + 1
        return counts

    def normalisation_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(NORMALISATIONS, 0)
        for verdict in self.verdicts:
            for name in verdict.normalisations:
                counts[name] = counts.get(name, 0) + 1
        return counts

    def code_source_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for verdict in self.cds_verdicts:
            counts[verdict.code_source] = counts.get(verdict.code_source, 0) + 1
        return counts

    def failures(self) -> tuple[ProteinVerdict, ...]:
        """Everything that is not a pass, in file order -- what a curator actually reads."""
        return tuple(v for v in self.verdicts if not v.is_pass)

    def as_json(self) -> dict[str, Any]:
        """The whole report, untruncated. The human table abbreviates; this never does."""
        return {
            "threshold": self.threshold,
            "checked": self.checked,
            "exact": self.exact,
            "identity": self.identity,
            "passed": self.passed,
            "verdict_counts": self.verdict_counts(),
            "normalisation_counts": self.normalisation_counts(),
            "genetic_code_sources": self.code_source_counts(),
            "sequence_genetic_codes": {
                seqid: {"table_id": table_id, "source": source}
                for seqid, (table_id, source) in sorted(self.sequence_codes.items())
            },
            "genetic_code_disagreements": [
                {
                    "seqid": clash.seqid,
                    "declared_table": clash.declared_table,
                    "annotation_table": clash.annotation_table,
                    "annotation_source": clash.source,
                }
                for clash in self.disagreements
            ],
            "failures": [
                {
                    "protein_id": v.protein_id,
                    "verdict": v.verdict,
                    "seqid": v.seqid,
                    "strand": v.strand,
                    "locus_tag": v.locus_tag,
                    "gene": v.gene,
                    "table_id": v.table_id,
                    "genetic_code_source": v.code_source,
                    "segments": v.segments,
                    "coding_length": v.coding_length,
                    "translated_length": v.translated_length,
                    "reference_length": v.reference_length,
                    "mismatches": v.mismatches,
                    "first_mismatch": v.first_mismatch,
                    "normalisations": list(v.normalisations),
                    "detail": v.detail,
                }
                for v in self.failures()
            ],
        }


# ------------------------------------------------------------------------------------ file readers


def _open_text(path: str | Path) -> TextIO:
    """Open a file, gzipped or not, as text -- decided by the magic bytes, not the name.

    The same two-line decision `gff3.open_gff3` makes, under a name that does not claim the file
    is a GFF3. Duplicated rather than widening that function, whose docstring is about RefSeq
    annotations and whose readers should be able to keep believing it.
    """
    location = Path(path)
    with open(location, "rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(location, "rt", encoding="utf-8")
    return open(location, encoding="utf-8")


def read_fasta(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield `(name, sequence)` per record, where `name` is the header's first whitespace token.

    The first token is the identifier for both files this gate reads: `>NC_001133.9 Saccharomyces
    cerevisiae S288C chromosome I...` and `>NP_009342.1 seripauperin PAU8 [S. cerevisiae S288C]`.
    Sequence is upper-cased; whitespace inside a record, including the blank line some tools emit
    between records, is dropped rather than carried into a codon.
    """
    name: str | None = None
    chunks: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line.startswith(">"):
            if name is not None:
                yield name, "".join(chunks)
            header = line[1:].strip()
            name = header.split()[0] if header else ""
            chunks = []
            continue
        if name is None:
            if not line:
                continue
            raise Gff3Error(f"FASTA begins with sequence before any '>' header: {line[:40]!r}")
        chunks.append(line.upper())
    if name is not None:
        yield name, "".join(chunks)


def _read_fasta_map(path: str | Path, *, what: str) -> dict[str, str]:
    records: dict[str, str] = {}
    with _open_text(path) as handle:
        for name, sequence in read_fasta(handle):
            if name in records:
                # Refused rather than last-one-wins: with duplicate ids there is no way to know
                # which record a verdict was measured against, so every verdict from this file
                # would be unattributable.
                raise Gff3Error(f"{what} {path}: duplicate record id {name!r}")
            records[name] = sequence
    return records


def read_genome(path: str | Path) -> dict[str, str]:
    """seqid -> sequence, for a genomic FASTA (gzipped or not)."""
    return _read_fasta_map(path, what="genome FASTA")


def read_proteins(path: str | Path) -> dict[str, str]:
    """protein accession -> peptide, for a protein FASTA (gzipped or not)."""
    return _read_fasta_map(path, what="protein FASTA")


# -------------------------------------------------------------------------------- GFF3 CDS models


def _phase(field: str, line_number: int) -> int:
    """GFF3 column 8. `.` on a CDS is not legal and is not quietly read as 0."""
    if field in {"0", "1", "2"}:
        return int(field)
    raise Gff3Error(
        f"line {line_number}: CDS phase {field!r}; GFF3 requires 0, 1 or 2 on a CDS feature"
    )


def parse_annotation(lines: Iterable[str]) -> ParsedAnnotation:
    """Collect every CDS line into one model per protein, plus each sequence's `region` feature.

    Unlike `gff3.parse_gene_records` this does **not** stream: a CDS's segments are gathered
    across the whole file and the result is one object. That is a deliberate difference and it is
    affordable -- the models are ~6,400 records of a handful of integers for a yeast annotation,
    against the 12 Mb genome FASTA this gate has to hold in memory anyway to splice against.
    Streaming here would buy nothing and would forbid the one thing the gate needs, which is to
    ask whether every protein record was accounted for once the file is finished.
    """
    segments: dict[str, list[CdsSegment]] = {}
    facts: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    sequence_genome: dict[str, str | None] = {}

    for line_number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n").rstrip("\r")
        if not line:
            continue
        if line.startswith("#"):
            if line.strip().startswith("##FASTA"):
                break
            continue
        columns = line.split("\t")
        if len(columns) != 9:
            raise Gff3Error(
                f"line {line_number}: {len(columns)} tab-separated columns, GFF3 requires 9"
            )
        seqid, _source, feature_type, start_field, end_field, _score, strand_field, phase, attr = (
            columns
        )
        if feature_type not in {"CDS", "region"}:
            continue
        # Unquoted for the same reason `gff3.parse_gene_records` unquotes it, plus one this gate
        # owns: a FASTA header carries the seqid raw, so an escaped character left escaped here
        # would make the sequence unfindable and every CDS on it `untranslatable`.
        seqid = unquote(seqid)
        attributes = parse_attributes(attr)

        if feature_type == "region":
            # NCBI writes one `region` per sequence, spanning it. A `region` that is a sub-span of
            # its sequence is a different feature (a telomere, a centromere) and says nothing
            # about the genome the sequence belongs to, so only the first one is taken.
            sequence_genome.setdefault(seqid, _first(attributes, "genome"))
            continue

        try:
            start = int(start_field)
            end = int(end_field)
        except ValueError as exc:
            raise Gff3Error(
                f"line {line_number}: non-numeric coordinates {start_field!r}..{end_field!r}"
            ) from exc
        if start < 1 or end < start:
            raise Gff3Error(
                f"line {line_number}: coordinates {start}..{end} are not 1-based inclusive"
            )

        # `protein_id` first because it is the join key to the protein FASTA; `ID` and `Parent`
        # only group the segments, and a model keyed on either will land as `missing_protein`.
        key = _first(attributes, "protein_id") or _first(attributes, "ID")
        if key is None:
            parents = attributes.get("Parent", ())
            key = parents[0] if parents else None
        if key is None:
            raise Gff3Error(
                f"line {line_number}: CDS feature has no protein_id=, ID= or Parent=; there is "
                "nothing to group its segments by and nothing to look up in the protein FASTA"
            )

        if key not in segments:
            segments[key] = []
            order.append(key)
            facts[key] = {
                "seqid": seqid,
                "strand": parse_strand(strand_field),
                "locus_tag": _first(attributes, "locus_tag"),
                "gene": _first(attributes, "gene"),
                "product": _first(attributes, "product"),
                "transl_table": _transl_table(attributes, line_number),
                "pseudo": (_first(attributes, "pseudo") or "").lower() == "true",
            }
        elif facts[key]["seqid"] != seqid:
            raise Gff3Error(
                f"line {line_number}: CDS {key!r} has segments on both "
                f"{facts[key]['seqid']!r} and {seqid!r}; a CDS does not cross sequences"
            )
        # `_half_open`'s rule, inlined: subtract one from the start, leave the end alone.
        segments[key].append(CdsSegment(start - 1, end, _phase(phase, line_number), line_number))

    models = tuple(
        CdsModel(
            protein_id=key,
            seqid=str(facts[key]["seqid"]),
            strand=int(facts[key]["strand"]),
            locus_tag=facts[key]["locus_tag"],
            gene=facts[key]["gene"],
            product=facts[key]["product"],
            segments=tuple(segments[key]),
            declared_table=facts[key]["transl_table"],
            pseudo=bool(facts[key]["pseudo"]),
        )
        for key in order
    )
    return ParsedAnnotation(cds=models, sequence_genome=sequence_genome)


def _first(attributes: Mapping[str, tuple[str, ...]], key: str) -> str | None:
    values = attributes.get(key)
    if not values:
        return None
    return values[0] or None


def _transl_table(attributes: Mapping[str, tuple[str, ...]], line_number: int) -> int | None:
    value = _first(attributes, "transl_table")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise Gff3Error(f"line {line_number}: transl_table={value!r} is not an integer") from exc


# ------------------------------------------------------------------------- genetic code resolution


def resolve_genetic_code(
    model: CdsModel,
    sequence_genome: Mapping[str, str | None],
    declared: Mapping[str, int],
) -> CodeResolution:
    """Which table this CDS is read under. See the module docstring for the order and the why.

    Returns a resolution with `table_id=None` and `source='none'` rather than raising or
    defaulting, because "this gate could not determine the code" is a verdict the report has to
    carry per CDS, not an exception that ends the run at the first odd sequence.
    """
    if model.declared_table is not None:
        return CodeResolution(
            table_id=model.declared_table,
            source="annotation",
            encoding_genome=None,
            detail=f"transl_table={model.declared_table} on the CDS feature",
        )

    token = sequence_genome.get(model.seqid)
    if token is not None:
        encoding_genome = REGION_GENOME_ENCODING.get(token.strip().lower())
        if encoding_genome is not None:
            return CodeResolution(
                table_id=ENCODING_GENOME_TABLE[encoding_genome],
                source="region",
                encoding_genome=encoding_genome,
                detail=f"region genome={token} -> encoding genome {encoding_genome}",
            )

    stated = declared.get(model.seqid)
    if stated is not None:
        return CodeResolution(
            table_id=stated,
            source="declared",
            encoding_genome=None,
            detail=f"--genetic-code {model.seqid}={stated}",
        )

    if model.seqid not in sequence_genome:
        detail = f"no region feature for {model.seqid} and no --genetic-code for it"
    elif token is None:
        detail = f"the region feature for {model.seqid} states no genome=, and no --genetic-code"
    else:
        detail = (
            f"region genome={token!r} is not one this gate maps to an encoding genome "
            f"({', '.join(sorted(REGION_GENOME_ENCODING))}), and no --genetic-code"
        )
    return CodeResolution(table_id=None, source="none", encoding_genome=None, detail=detail)


# ------------------------------------------------------------------------------ splice and compare


def splice_cds(model: CdsModel, sequence: str) -> str:
    """Concatenate the CDS segments in translation order and trim the leading phase.

    The phase that is applied is the **first segment in translation order**'s -- the number of
    bases between the start of the CDS as annotated and the first complete codon, which is
    non-zero only on a 5'-partial gene. Every later segment's phase is redundant with the lengths
    before it; `phase_disagreement` checks them rather than obeying them, because a file whose
    phases and lengths contradict each other has a defect that applying either one would hide.
    """
    ordered = model.ordered_segments
    parts = [sequence[segment.start_pos : segment.end_pos] for segment in ordered]
    if model.strand < 0:
        parts = [reverse_complement(part) for part in parts]
    return "".join(parts)[ordered[0].phase :]


def phase_disagreement(model: CdsModel) -> str | None:
    """The first downstream segment whose declared phase contradicts the lengths before it.

    Expected phase of a segment is `(3 - (bases so far) % 3) % 3`, where "bases so far" is the
    **full** length of every preceding segment, less only the first segment's own phase. The
    first segment is exempt: its phase says where the CDS starts and is not a consequence of
    anything before it.

    A downstream segment's phase is **not** subtracted from that running total, and getting this
    wrong is a trap worth naming because it produces a check that is confidently wrong. GFF3's
    phase is the offset to the *next* codon boundary, which means it double-counts the bases at
    the start of the segment that finish the previous segment's codon -- those bases are part of
    the coding sequence and are spliced in, they are simply not the start of a codon. Subtracting
    each one reported 16 disagreements against GCF_000146045.2 (SUS1, VMA9, DYN2, RPL7A/RPL7B,
    COX1, COB and nine others), every one of which was this function's error and not RefSeq's;
    all 16 translated exactly. With the full length the same file reports zero.
    """
    ordered = model.ordered_segments
    if len(ordered) < 2:
        return None
    consumed = ordered[0].length - ordered[0].phase
    for segment in ordered[1:]:
        expected = (3 - consumed % 3) % 3
        if segment.phase != expected:
            return (
                f"CDS line {segment.line_number} declares phase {segment.phase}; the "
                f"{consumed} coding bases before it make the first codon boundary {expected}"
            )
        consumed += segment.length
    return None


def _compare(translated: str, reference: str) -> tuple[str, int, int | None]:
    """`(verdict, mismatch count, 1-based first mismatch)` for two peptides.

    Compared position by position over the longer of the two, so a truncation is a run of
    mismatches rather than an equal-prefix pass. The classification order is deliberate: an
    ambiguity explains a difference that a stop does not, and a stop explains one that "mismatch"
    does not, so the most specific reading that accounts for **every** difference wins.
    """
    width = max(len(translated), len(reference))
    differences = [
        index for index in range(width) if _residue(translated, index) != _residue(reference, index)
    ]
    if not differences:
        return EXACT, 0, None
    first = differences[0] + 1
    if all(
        _residue(translated, index) in NON_CODING_RESIDUES
        or _residue(reference, index) in NON_CODING_RESIDUES
        for index in differences
    ):
        return AMBIGUOUS, len(differences), first
    if "*" in translated:
        return INTERNAL_STOP, len(differences), first
    return MISMATCH, len(differences), first


def _residue(peptide: str, index: int) -> str:
    """The residue at `index`, or `-` past the end. `-` is not a residue either sequence can
    hold, so a length difference cannot accidentally compare equal to anything."""
    return peptide[index] if index < len(peptide) else "-"


def check_cds(
    model: CdsModel,
    genome: Mapping[str, str],
    proteins: Mapping[str, str],
    resolution: CodeResolution,
) -> ProteinVerdict:
    """Re-splice, translate and compare one CDS. Never raises on bad input; it returns a verdict.

    The order the refusals are tested in is the order in which they make the later ones
    unanswerable: with no protein record there is nothing to compare to whatever the code turns
    out to be, and with no code there is nothing to translate whatever the sequence turns out to
    be. Reporting the first blocker rather than the last is what makes the counts add up to
    something a curator can act on one class at a time.
    """
    base = {
        "protein_id": model.protein_id,
        "seqid": model.seqid,
        "strand": model.strand,
        "locus_tag": model.locus_tag,
        "gene": model.gene,
        "table_id": resolution.table_id,
        "code_source": resolution.source,
        "segments": len(model.segments),
        "coding_length": model.coding_length,
    }
    phase_note = phase_disagreement(model)
    flags: list[str] = [DECLARED_PHASE_DISAGREES] if phase_note is not None else []

    reference = proteins.get(model.protein_id)
    if reference is None:
        note = " (the CDS declares pseudo=true)" if model.pseudo else ""
        return _verdict(
            base,
            MISSING_PROTEIN,
            flags,
            detail=(
                f"protein_id {model.protein_id} is in the annotation and not in the FASTA{note}"
            ),
        )

    if resolution.table_id is None:
        return _verdict(base, NO_GENETIC_CODE, flags, reference=reference, detail=resolution.detail)
    code = resolution.code
    if code is None:
        return _verdict(
            base,
            UNSUPPORTED_GENETIC_CODE,
            flags,
            reference=reference,
            detail=(
                f"{resolution.detail}; fermdb.genetic_code implements tables "
                f"{', '.join(str(t) for t in sorted(TABLES))} and not {resolution.table_id}"
            ),
        )

    sequence = genome.get(model.seqid)
    if sequence is None:
        return _verdict(
            base,
            UNTRANSLATABLE,
            flags,
            reference=reference,
            detail=f"{model.seqid} is not a record in the genome FASTA",
        )
    if model.strand == 0:
        return _verdict(
            base,
            UNTRANSLATABLE,
            flags,
            reference=reference,
            detail="strand is '.' or '?'; a CDS with no strand cannot be spliced",
        )
    overrun = max((s.end_pos for s in model.segments), default=0)
    if overrun > len(sequence):
        return _verdict(
            base,
            UNTRANSLATABLE,
            flags,
            reference=reference,
            detail=(
                f"CDS ends at {overrun} and {model.seqid} is {len(sequence)} bases; the "
                "annotation and the genome FASTA are not the same assembly"
            ),
        )

    spliced = splice_cds(model, sequence)
    if len(spliced) < 3:
        return _verdict(
            base,
            UNTRANSLATABLE,
            flags,
            reference=reference,
            detail=f"{len(spliced)} coding bases after the leading phase; not one whole codon",
        )
    if len(spliced) % 3:
        flags.append(TRAILING_PARTIAL_CODON)

    translated = translate(spliced, code)
    if translated.endswith("*"):
        translated = translated[:-1]
        flags.append(TRAILING_STOP_TRIMMED)
    if (
        translated
        and reference.startswith("M")
        and not translated.startswith("M")
        and spliced[:3] in code.start_codons
    ):
        translated = "M" + translated[1:]
        flags.append(ALTERNATIVE_START)

    verdict, mismatches, first = _compare(translated, reference)
    detail = "" if verdict == EXACT else _describe(translated, reference, first)
    if phase_note is not None:
        detail = f"{detail}; {phase_note}" if detail else phase_note
    return _verdict(
        base,
        verdict,
        flags,
        reference=reference,
        translated=translated,
        mismatches=mismatches,
        first_mismatch=first,
        detail=detail,
    )


def _describe(translated: str, reference: str, first: int | None) -> str:
    if first is None:
        return ""
    index = first - 1
    return (
        f"residue {first}: translated {_residue(translated, index)!r}, "
        f"FASTA {_residue(reference, index)!r} "
        f"(translated {len(translated)} aa, FASTA {len(reference)} aa)"
    )


def _verdict(
    base: Mapping[str, Any],
    verdict: str,
    flags: Sequence[str],
    *,
    reference: str = "",
    translated: str = "",
    mismatches: int = 0,
    first_mismatch: int | None = None,
    detail: str = "",
) -> ProteinVerdict:
    return ProteinVerdict(
        protein_id=str(base["protein_id"]),
        verdict=verdict,
        seqid=base["seqid"],
        strand=int(base["strand"]),
        locus_tag=base["locus_tag"],
        gene=base["gene"],
        table_id=base["table_id"],
        code_source=str(base["code_source"]),
        segments=int(base["segments"]),
        coding_length=int(base["coding_length"]),
        translated_length=len(translated),
        reference_length=len(reference),
        mismatches=mismatches,
        first_mismatch=first_mismatch,
        normalisations=tuple(flags),
        detail=detail,
    )


# ------------------------------------------------------------------------------------- the gate


def run_protein_qc(
    gff3_path: str | Path,
    genome_path: str | Path,
    protein_path: str | Path,
    *,
    declared_tables: Mapping[str, int] | None = None,
    threshold: float = MIN_PROTEIN_IDENTITY,
) -> ProteinQcReport:
    """Run the gate over one (annotation, genome FASTA, protein FASTA) triple.

    `threshold` is a parameter so a test can prove the refusal path fires without editing the
    constant; every caller in this package passes the constant, and the CLI offers no flag for it
    (PLAN.md S.2 -- a threshold that can be relaxed for one run is not a threshold).
    """
    declared = dict(declared_tables or {})
    with _open_text(gff3_path) as handle:
        annotation = parse_annotation(handle)
    genome = read_genome(genome_path)
    proteins = read_proteins(protein_path)

    verdicts: list[ProteinVerdict] = []
    sequence_codes: dict[str, tuple[int | None, str]] = {}
    disagreements: list[GeneticCodeDisagreement] = []
    seen_disagreement: set[str] = set()
    accounted: set[str] = set()

    for model in annotation.cds:
        resolution = resolve_genetic_code(model, annotation.sequence_genome, declared)
        stated = declared.get(model.seqid)
        if (
            stated is not None
            and resolution.source not in {"declared", "none"}
            and resolution.table_id != stated
            and model.seqid not in seen_disagreement
        ):
            seen_disagreement.add(model.seqid)
            disagreements.append(
                GeneticCodeDisagreement(
                    seqid=model.seqid,
                    declared_table=stated,
                    annotation_table=int(resolution.table_id or 0),
                    source=resolution.source,
                )
            )
        sequence_codes.setdefault(model.seqid, (resolution.table_id, resolution.source))
        accounted.add(model.protein_id)
        verdicts.append(check_cds(model, genome, proteins, resolution))

    for accession in proteins:
        if accession in accounted:
            continue
        verdicts.append(
            ProteinVerdict(
                protein_id=accession,
                verdict=MISSING_MODEL,
                seqid=None,
                strand=0,
                locus_tag=None,
                gene=None,
                table_id=None,
                code_source="none",
                segments=0,
                coding_length=0,
                translated_length=0,
                reference_length=len(proteins[accession]),
                mismatches=0,
                first_mismatch=None,
                normalisations=(),
                detail="in the protein FASTA; no CDS in the annotation carries this protein_id",
            )
        )

    return ProteinQcReport(
        threshold=threshold,
        verdicts=tuple(verdicts),
        disagreements=tuple(disagreements),
        sequence_codes=sequence_codes,
    )


def format_report(report: ProteinQcReport, *, max_detail: int = 20) -> list[str]:
    """The human rendering, as lines so a test can read it without capturing stdout."""
    lines = [
        "",
        f"{'CDS checked':<28}{report.checked:>10}",
        f"{'  exact':<28}{report.exact:>10}",
        f"{'identity':<28}{report.identity:>10.5f}",
        f"{'threshold':<28}{report.threshold:>10.5f}",
    ]

    lines += ["", "verdicts"]
    counts = report.verdict_counts()
    for name in VERDICTS:
        lines.append(f"  {name:<26}{counts[name]:>10}")

    lines += ["", "normalisations and phase checks (counted, not failures on their own)"]
    normalisations = report.normalisation_counts()
    for name in NORMALISATIONS:
        lines.append(f"  {name:<34}{normalisations[name]:>10}")

    lines += ["", "genetic code per sequence (route: annotation > region > declared > refused)"]
    for seqid, (table_id, source) in sorted(report.sequence_codes.items()):
        shown = "REFUSED" if table_id is None else f"table {table_id}"
        lines.append(f"  {seqid:<26}{shown:>10}  from {source}")

    if report.disagreements:
        lines += [
            "",
            "GENETIC CODE DISAGREEMENTS -- the annotation was used in every case. A --genetic-code",
            "you typed contradicts what the file states; neither was silently preferred.",
        ]
        lines += [
            f"  {clash.seqid}: you said table {clash.declared_table}, the {clash.source} says "
            f"table {clash.annotation_table}"
            for clash in report.disagreements
        ]

    failures = report.failures()
    if failures:
        lines += [
            "",
            f"FAILURES -- {len(failures)} of {len(report.verdicts)} records. Every one of these is",
            "a claim about the annotation, the genome FASTA, or this gate; none is a rounding",
            "error. Fix the input, not the threshold (PLAN.md S.2).",
            "",
        ]
        for verdict in failures[:max_detail]:
            where = f"{verdict.seqid}:{verdict.locus_tag or verdict.gene or '-'}"
            lines.append(f"  {verdict.protein_id}  {where}  {verdict.verdict}")
            if verdict.detail:
                lines.append(f"      {verdict.detail}")
        if len(failures) > max_detail:
            lines.append(f"  ... and {len(failures) - max_detail} more; --json lists every one")

    lines.append("")
    if report.passed:
        lines.append(
            f"PASS -- {report.exact}/{report.checked} CDS reproduce their protein record exactly."
        )
    elif report.checked == 0:
        lines.append("REFUSED -- the annotation contains no CDS. Nothing was verified.")
    else:
        lines.append(
            f"REFUSED -- identity {report.identity:.5f} is below the {report.threshold:.5f} "
            "gate. The ingest must not proceed."
        )
    return lines
