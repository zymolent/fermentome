"""Build the mitochondrial CDS the S288C transcriptome is missing.

``docs/reports/2026-09-20-duet-expression-baseline.md`` found that the RefSeq
``rna_from_genomic`` FASTA the salmon index was built from contains **no mtDNA protein-coding
genes at all** -- COX1, COX2, COX3, COB, ATP6, ATP8, ATP9 and VAR1 are absent, and its 27
mitochondrial features are 24 tRNAs, 2 rRNAs and one ncRNA. Mitochondrial gene expression was
therefore never measured, reads from those mRNAs had nowhere to map, and strategy E has no
transcriptomic evidence base.

That is a reference-construction gap, not biology, and this module closes the local half of it:
it reads the annotated CDS out of the mitochondrial GenBank record, checks each one translates to
NCBI's own ``/translation`` **under table 3**, and writes them as a FASTA supplement in the same
header style the transcriptome uses. Requantifying against transcriptome + supplement is then a
single job over the raw objects already in S3.

**Why the translation check is not optional here.** These eight genes are exactly the ones that
read differently under the two tables -- UGA is tryptophan rather than a stop, CUN is threonine
rather than leucine. A CDS that silently went into the index without being checked would still
produce counts, and those counts would be attached to a protein sequence nobody verified. The
check is the same one ``references.verify_mitochondrial_translation`` runs, and it is what makes
this supplement evidence rather than a plausible file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..genetic_code import table_for_compartment
from .references import _iter_features, _parse_genbank_sequence, _parse_qualifiers

__all__ = [
    "MITOCHONDRIAL_ACCESSION",
    "MitoCds",
    "MitoTranscriptError",
    "format_supplement",
    "parse_mitochondrial_cds",
]

MITOCHONDRIAL_ACCESSION: Final[str] = "NC_001224.1"

#: One exon: a span, optionally complemented on its own.
_SPAN: Final[re.Pattern[str]] = re.compile(
    r"(?P<complement>complement\()?(?P<start>\d+)\.\.>?(?P<end>\d+)\)?"
)

#: GenBank wraps a long location across lines, and `_iter_features` returns only the first line
#: with the rest arriving as qualifier lines. COX1's location runs to two lines and eight exons,
#: so a parser that ignored the continuation would silently take the first four exons and build a
#: sequence that is wrong rather than absent.
_LOCATION_CONTINUATION: Final[re.Pattern[str]] = re.compile(r"^[\d\.,()<>\s]+$")

_COMPLEMENT: Final[dict[str, str]] = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}


class MitoTranscriptError(RuntimeError):
    """A CDS could not be extracted, or did not translate to what NCBI recorded."""


@dataclass(frozen=True)
class MitoCds:
    """One mitochondrial protein-coding sequence, verified against its own ``/translation``."""

    locus_tag: str
    gene: str | None
    product: str
    sequence: str
    translation: str
    #: True when the CDS exercises a codon the two tables disagree on, so it is direct evidence
    #: that the supplement had to be read under table 3.
    table_1_would_differ: bool
    #: How many exons were joined. 1 is a plain span; more means the assembly was checked by the
    #: translation comparison rather than assumed.
    exons: int = 1


def _reverse_complement(sequence: str) -> str:
    return "".join(_COMPLEMENT.get(base, "N") for base in reversed(sequence))


def _full_location(location: str, qualifier_lines: list[str]) -> tuple[str, list[str]]:
    """Reassemble a location that wrapped, and return it with the qualifier lines that remain.

    A wrapped location's continuation lines reach `_iter_features` as qualifiers, because nothing
    distinguishes them by indentation. They are recognisable by content instead: digits, dots,
    commas and brackets only, and always before the first `/qualifier`.
    """
    text = location.strip()
    remaining = list(qualifier_lines)
    while remaining and not remaining[0].startswith("/"):
        candidate = remaining[0].strip()
        if not _LOCATION_CONTINUATION.match(candidate):
            break
        text += candidate
        remaining.pop(0)
    return text, remaining


def _exons(location: str) -> list[tuple[int, int, bool]]:
    """`[(start, end, complement)]` in transcription order, or [] if the location is unparseable.

    `complement(join(a,b))` reverses the order of its parts as well as each part's strand, which
    is why the whole-location complement is applied here rather than left to the caller.
    """
    text = location.replace(" ", "")
    whole_complement = text.startswith("complement(")
    spans = [
        (int(m.group("start")) - 1, int(m.group("end")), bool(m.group("complement")))
        for m in _SPAN.finditer(text)
    ]
    if not spans:
        return []
    if whole_complement:
        spans = [(start, end, True) for start, end, _ in reversed(spans)]
    return spans


def _translate(sequence: str, table_id: int) -> str:
    code = table_for_compartment(
        "mitochondrial_matrix", "mitochondrial" if table_id == 3 else "nuclear"
    )
    residues: list[str] = []
    for index in range(0, len(sequence) - 2, 3):
        codon = sequence[index : index + 3]
        residue = code.codon_to_aa.get(codon)
        if residue is None:
            raise MitoTranscriptError(f"codon {codon!r} is not in table {table_id}")
        if residue == "*":
            break
        residues.append(residue)
    return "".join(residues)


def parse_mitochondrial_cds(genbank_text: str) -> tuple[list[MitoCds], list[str]]:
    """``(verified CDS, reasons a CDS was skipped)`` from a mitochondrial GenBank record.

    Intron-containing genes -- COX1 and COB both are -- are assembled from their exons. That is
    only safe because every assembly is then translated and compared to NCBI's own
    ``/translation``: a mis-joined CDS still translates to *something*, so the comparison is what
    separates "assembled" from "assembled correctly", and a mismatch raises.

    Every returned CDS has been translated under table 3 and compared to NCBI's own
    ``/translation``; one that does not match raises rather than being returned with a warning.
    Skips are returned rather than logged away, because a silently-skipped gene is a gene missing
    from the index for the second time.
    """
    sequence = _parse_genbank_sequence(genbank_text).upper()
    verified: list[MitoCds] = []
    skipped: list[str] = []

    for key, location, qualifier_lines in _iter_features(genbank_text):
        if key != "CDS":
            continue
        full_location, qualifier_lines = _full_location(location, qualifier_lines)
        qualifiers = _parse_qualifiers(qualifier_lines)
        translation = qualifiers.get("translation")
        locus_tag = qualifiers.get("locus_tag", "")
        gene = qualifiers.get("gene")
        label = gene or locus_tag or location
        if not translation:
            skipped.append(f"{label}: no /translation recorded")
            continue

        exons = _exons(full_location)
        if not exons:
            skipped.append(f"{label}: location {full_location!r} could not be parsed")
            continue

        # Exons are concatenated in order. This is only safe because the translation check below
        # rejects a wrong assembly: a mis-joined CDS still translates to something, so the check
        # is what separates "assembled" from "assembled correctly".
        pieces = [
            _reverse_complement(sequence[start:end]) if complement else sequence[start:end]
            for start, end, complement in exons
        ]
        extracted = "".join(pieces)

        under_3 = _translate(extracted, 3)
        if under_3 != translation:
            raise MitoTranscriptError(
                f"{label}: translating {MITOCHONDRIAL_ACCESSION} {full_location} under table 3 "
                f"gives {under_3[:40]!r} but NCBI records {translation[:40]!r}. Refusing to add a "
                f"CDS to the index whose protein this atlas cannot reproduce."
            )
        try:
            differs = _translate(extracted, 1) != translation
        except MitoTranscriptError:
            # A codon absent from table 1 is itself a disagreement.
            differs = True

        verified.append(
            MitoCds(
                locus_tag=locus_tag,
                gene=gene,
                product=qualifiers.get("product", ""),
                sequence=extracted,
                translation=translation,
                table_1_would_differ=differs,
                exons=len(exons),
            )
        )
    return verified, skipped


def format_supplement(records: list[MitoCds], *, width: int = 70) -> str:
    """The CDS as FASTA, in the header style the RefSeq transcriptome uses.

    Matching that style matters: the matrix builder derives a row name from ``[locus_tag=...]``,
    so a supplement written any other way would quantify fine and then produce rows nothing could
    join to ``gene.systematic_name``.
    """
    lines: list[str] = []
    for record in records:
        gene = f" [gene={record.gene}]" if record.gene else ""
        lines.append(
            f">lcl|{MITOCHONDRIAL_ACCESSION}_cds_{record.locus_tag}{gene} "
            f"[locus_tag={record.locus_tag}] [product={record.product}] [gbkey=CDS]"
        )
        for index in range(0, len(record.sequence), width):
            lines.append(record.sequence[index : index + width])
    return "\n".join(lines) + "\n"


def build_supplement(genbank_path: Path, output_path: Path) -> tuple[list[MitoCds], list[str]]:
    """Read a GenBank record, verify its CDS and write the FASTA supplement. Returns what it did."""
    records, skipped = parse_mitochondrial_cds(genbank_path.read_text(encoding="utf-8"))
    if not records:
        raise MitoTranscriptError(
            f"{genbank_path} yielded no verifiable CDS; writing an empty supplement would leave "
            f"the index exactly as incomplete as it is now while looking fixed"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_supplement(records), encoding="utf-8")
    return records, skipped
