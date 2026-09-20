"""The DUET expression baseline: what the S288C corpus says about the genes DUET depends on.

This is the first read-out the atlas can make from its own data. 99 S. cerevisiae RNA-Seq runs
were quantified against the R64 transcriptome, and 36 genes were resolved to systematic names by
:mod:`fermdb.omics.genes`. Crossing the two answers a question the DUET design cannot answer from
first principles: *is the cell already expressing the machinery strategy C would load?*

**What this deliberately does not do.** It computes no differential expression, no fold change and
no sample grouping. PLAN.md F.3 is explicit that a contrast requires an approved
``condition_context``, and none has been curated -- the 99 runs come from fifteen unrelated
studies whose conditions have never been harmonized. Grouping them by anything would be inventing
the very metadata F.3 says this corpus lacks. Distribution, detection and rank are properties of
the matrix alone and need no such approval; a fold change between two arbitrary sample sets would
look exactly as rigorous and mean nothing.

Everything produced here is Zone H -- rebuildable from the matrix by re-running this -- except the
interpretation in the report, which is Zone I and is written as prose rather than stored as rows.
"""

from __future__ import annotations

import gzip
import re
import statistics
from collections.abc import Container, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..config import Settings

__all__ = [
    "DETECTION_TPM",
    "MITOCHONDRIAL_PROTEIN_GENES",
    "missing_mitochondrial_proteins",
    "BaselineReport",
    "GeneProfile",
    "build_baseline",
    "read_matrix",
    "transcriptome_features",
]

#: A transcript is "detected" in a sample at or above this TPM. One transcript per million is the
#: conventional floor for calling a gene present rather than noise; it is a threshold, so it is
#: named here once and reported alongside every count that depends on it.
DETECTION_TPM: Final[float] = 1.0

#: Genes carried on the mitochondrial genome use the ``Q`` locus prefix in this assembly's
#: systematic naming. They read under NCBI table 3; everything on a chromosome reads under table 1.
_MITOCHONDRIAL_PREFIX: Final[str] = "Q"

_BRACKET: Final[re.Pattern[str]] = re.compile(r"\[([a-z_]+)=([^\]]*)\]")

#: The mtDNA protein-coding complement of S. cerevisiae. Checked for explicitly, because their
#: **absence** from the quantification is the single most consequential fact this module reports
#: and an absence is exactly what a summary statistic cannot show.
MITOCHONDRIAL_PROTEIN_GENES: Final[tuple[str, ...]] = (
    "COX1",
    "COX2",
    "COX3",
    "COB",
    "ATP6",
    "ATP8",
    "ATP9",
    "VAR1",
)

#: Symbols a source may use for one of the above. NC_001224 annotates ATP9 as OLI1, so a check
#: that only looked for "ATP9" would report it missing from a reference that in fact contains it --
#: a false alarm that would send someone to fix a gap that had already been closed.
_MITOCHONDRIAL_SYNONYMS: Final[Mapping[str, tuple[str, ...]]] = {
    "ATP9": ("OLI1",),
    "COB": ("CYTB", "COB1"),
}


def missing_mitochondrial_proteins(symbols: Container[str]) -> tuple[str, ...]:
    """Which of the mtDNA protein-coding complement `symbols` does not contain, synonyms allowed."""
    return tuple(
        gene
        for gene in MITOCHONDRIAL_PROTEIN_GENES
        if gene not in symbols
        and not any(alias in symbols for alias in _MITOCHONDRIAL_SYNONYMS.get(gene, ()))
    )


@dataclass(frozen=True)
class GeneProfile:
    """One gene's distribution across every sample in the matrix."""

    systematic_name: str
    standard_name: str | None
    role: str | None
    encoding_genome: str
    #: 'mRNA' | 'rRNA' | 'tRNA' | 'ncRNA' -- from the transcriptome's own [gbkey=], never guessed
    #: from the locus name. Lumping an rRNA in with protein-coding genes is how a mitochondrial
    #: rRNA gets read as evidence about mitochondrial enzyme expression.
    feature_kind: str
    median_tpm: float
    min_tpm: float
    max_tpm: float
    detected_in: int
    samples: int

    @property
    def detection_rate(self) -> float:
        return self.detected_in / self.samples if self.samples else 0.0

    @property
    def fold_spread(self) -> float | None:
        """max/min across samples, or None when the gene is absent from at least one.

        None rather than infinity, and never a substituted floor: a gene undetected somewhere has
        no meaningful ratio, and inventing one would put a number where an absence belongs.
        """
        return self.max_tpm / self.min_tpm if self.min_tpm > 0 else None


@dataclass(frozen=True)
class BaselineReport:
    profiles: tuple[GeneProfile, ...]
    samples: int
    matrix_genes: int
    matrix_path: str
    #: mtDNA protein-coding genes the transcriptome the index was built from does not contain.
    #: Non-empty means mitochondrial gene expression was never measured, however many
    #: ``Q``-prefixed rows the matrix happens to have.
    missing_mitochondrial_proteins: tuple[str, ...] = ()

    @property
    def absent(self) -> tuple[GeneProfile, ...]:
        """Genes detected in no sample at all -- a pathway step with no enzyme behind it."""
        return tuple(p for p in self.profiles if p.detected_in == 0)

    @property
    def sporadic(self) -> tuple[GeneProfile, ...]:
        """Detected in some samples and not others: conditional, and a risk a route must carry."""
        return tuple(p for p in self.profiles if 0 < p.detected_in < self.samples)


def read_matrix(path: Path, wanted: set[str]) -> tuple[dict[str, list[float]], int, int]:
    """``({systematic name: values}, sample count, total genes)`` for the wanted rows only.

    Streamed, and the whole matrix is never held in memory: 6,187 x 99 is small today but the
    same code reads whatever the corpus grows into.
    """
    values: dict[str, list[float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        samples = len(handle.readline().rstrip("\n").split("\t")) - 1
        total = 0
        for line in handle:
            total += 1
            name, _, rest = line.partition("\t")
            if name in wanted:
                values[name] = [float(cell) for cell in rest.rstrip("\n").split("\t")]
    return values, samples, total


def _encoding_genome(systematic_name: str) -> str:
    """Nuclear or mitochondrial, from the locus name's own convention.

    Derived rather than looked up so that a gene present in the matrix but absent from the
    resolved set still gets the right answer -- the mtDNA genes are exactly that case, and they
    are the ones the DUET comparison turns on.
    """
    return "mitochondrial" if systematic_name.startswith(_MITOCHONDRIAL_PREFIX) else "nuclear"


def transcriptome_features(path: Path) -> dict[str, tuple[str | None, str]]:
    """``{locus_tag: (gene symbol, gbkey)}`` for every transcript in the index's FASTA.

    ``gbkey`` is the transcriptome's own feature class. Reading it is what separates a
    mitochondrial rRNA from a mitochondrial enzyme, and the two are not interchangeable evidence.
    """
    features: dict[str, tuple[str | None, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(">"):
                continue
            fields = dict(_BRACKET.findall(line))
            locus = fields.get("locus_tag")
            if locus:
                features[locus] = (fields.get("gene"), fields.get("gbkey", "unknown"))
    return features


def build_baseline(
    settings: Settings,
    *,
    matrix_name: str = "s288c.tpm.tsv.gz",
    include_mitochondrial: bool = True,
) -> BaselineReport:
    """Profile the resolved DUET genes, plus whatever mtDNA features the matrix carries.

    Strategy C loads the matrix by importing nuclear-encoded enzymes into it; strategy E puts
    genes into the mtDNA itself. Deciding between them wants to know what the organelle already
    transcribes -- so this checks whether that is even measurable here, rather than assuming the
    ``Q``-prefixed rows in the matrix answer it. They do not: see
    ``missing_mitochondrial_proteins`` on the returned report.
    """
    from . import genes as genes_mod

    transcripts = Path(settings.genomes_dir) / genes_mod.TRANSCRIPTS_FILENAME
    resolution = genes_mod.resolve_duet_gene_set(
        transcripts, Path(settings.repo_root) / genes_mod.DUET_TARGET_DOC
    )
    by_name = {gene.systematic_name: gene for gene in resolution.genes}
    features = transcriptome_features(transcripts)
    symbols = {symbol for symbol, _ in features.values() if symbol}

    matrix_path = Path(settings.matrices_dir) / matrix_name
    wanted = set(by_name)
    if include_mitochondrial:
        with gzip.open(matrix_path, "rt", encoding="utf-8") as handle:
            handle.readline()
            wanted |= {
                line.partition("\t")[0] for line in handle if line.startswith(_MITOCHONDRIAL_PREFIX)
            }

    values, samples, total = read_matrix(matrix_path, wanted)

    profiles: list[GeneProfile] = []
    for name in sorted(values):
        series = values[name]
        gene = by_name.get(name)
        symbol, gbkey = features.get(name, (None, "unknown"))
        profiles.append(
            GeneProfile(
                systematic_name=name,
                standard_name=gene.symbol if gene else symbol,
                role=gene.role_label if gene else None,
                encoding_genome=_encoding_genome(name),
                feature_kind=gbkey,
                median_tpm=statistics.median(series),
                min_tpm=min(series),
                max_tpm=max(series),
                detected_in=sum(1 for value in series if value >= DETECTION_TPM),
                samples=samples,
            )
        )
    return BaselineReport(
        profiles=tuple(profiles),
        samples=samples,
        matrix_genes=total,
        matrix_path=str(matrix_path),
        missing_mitochondrial_proteins=missing_mitochondrial_proteins(symbols),
    )
