"""Assemble salmon output into gene x sample matrices, and a QC table beside them.

Salmon reports per *transcript*. For S. cerevisiae the transcript-to-gene relationship is almost
1:1 but not exactly, and the atlas joins on gene groups, so transcripts are summed to gene here
using the ``[locus_tag=...]`` field NCBI puts in the FASTA header. **A transcript whose gene
cannot be resolved is kept under its own id and counted**, never silently dropped -- a dropped
transcript is expression that vanishes without anything saying so.

Organisms get separate matrices and are never concatenated: they have different reference spaces,
and a row labelled ``YAL001C`` in one and ``b0001`` in another share nothing but a position.

Written with the standard library rather than pandas. The project is deliberately installable on
a bare interpreter (CONVENTIONS.md), and what happens here is a sum and a TSV write.

This module is the repo home of what began as a scratchpad script. Two things it learned there
are kept because they cost real time: the bucket is in ``us-east-1`` while the CLI's default
profile is ``ap-south-1``, so a call without an explicit region builds the wrong endpoint host and
follows a redirect into a signature failure; and the local connection drops often enough that one
unretried GET loses most of a hundred-file assembly.
"""

from __future__ import annotations

import collections
import gzip
import io
import json
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BUCKET",
    "REGION",
    "AssemblyReport",
    "MatrixError",
    "assemble",
    "run_accessions",
    "transcript_to_gene",
    "write_matrix",
]

BUCKET: Final[str] = "fermdb-raw-211125789985"

#: Pinned, and not left to the profile default. See the module docstring.
REGION: Final[str] = "us-east-1"


class MatrixError(RuntimeError):
    """The quantification output could not be assembled."""


def _aws(args: list[str], *, timeout: int = 300, retries: int = 4) -> str:
    """One AWS CLI call with the region pinned and transient failures retried."""
    last = ""
    for attempt in range(retries):
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [*args, "--region", REGION],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout
            last = result.stderr.strip()[:200]
        except subprocess.TimeoutExpired:
            last = f"timed out after {timeout}s"
        time.sleep(2 * (attempt + 1))
    raise MatrixError(f"{' '.join(args[:4])}: {last}")


def transcript_to_gene(transcripts: Path) -> dict[str, str]:
    """``{transcript id: gene}`` from the FASTA headers, preferring the locus tag.

    The locus tag is preferred over the gene symbol because it is what ``gene.systematic_name``
    holds, and a matrix keyed on symbols could not be joined to the atlas. A header with neither
    maps the transcript to itself, so its counts survive under an id rather than disappearing.
    """
    mapping: dict[str, str] = {}
    with gzip.open(transcripts, "rt", encoding="ascii", errors="replace") as handle:
        for line in handle:
            if not line.startswith(">"):
                continue
            transcript_id = line[1:].split()[0]
            gene = None
            for field_name in ("locus_tag=", "gene="):
                marker = f"[{field_name}"
                if marker in line:
                    gene = line.split(marker, 1)[1].split("]", 1)[0]
                    if field_name == "locus_tag=":
                        break
            mapping[transcript_id] = gene or transcript_id
    return mapping


def run_accessions(prefix: str) -> dict[str, str]:
    """``{run accession: quant.sf key}`` for everything quantified under ``prefix``."""
    listing = _aws(["aws", "s3", "ls", f"s3://{BUCKET}/{prefix}/", "--recursive"])
    found: dict[str, str] = {}
    for line in listing.splitlines():
        key = line.rsplit(" ", 1)[-1]
        if key.endswith("/quant.sf"):
            found[key.rsplit("/quant/", 1)[-1].split("/")[0]] = key
    return found


@dataclass
class AssemblyReport:
    genes: int = 0
    samples: int = 0
    unresolved_transcripts: int = 0
    detected_genes_median: int = 0
    mitochondrial_genes: int = 0
    qc: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "genes": self.genes,
            "samples": self.samples,
            "unresolved_transcripts": self.unresolved_transcripts,
            "detected_genes_median": self.detected_genes_median,
            "mitochondrial_genes": self.mitochondrial_genes,
        }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def write_matrix(
    path: Path, genes: list[str], samples: list[str], values: Mapping[str, Mapping[str, float]]
) -> None:
    """One gzipped TSV: genes down, samples across, zeros written explicitly.

    A missing cell and a zero mean the same thing for a count matrix -- salmon reports every
    transcript in the index for every sample -- so writing 0 rather than leaving a gap keeps the
    file rectangular for anything that reads it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("gene\t" + "\t".join(samples) + "\n")
        for gene in genes:
            row = (f"{values[sample].get(gene, 0.0):.6g}" for sample in samples)
            handle.write(gene + "\t" + "\t".join(row) + "\n")


def assemble(
    *,
    prefix: str,
    transcripts: Path,
    out_dir: Path,
    reference: str = "s288c",
    dropped: frozenset[str] = frozenset(),
) -> AssemblyReport:
    """Read every ``quant.sf`` under ``prefix`` and write the counts and TPM matrices.

    ``dropped`` runs are excluded from the matrices only. Their raw data and quantification stay
    in S3, because a rejected run is a recorded decision rather than a mistake to erase.
    """
    keys = run_accessions(prefix)
    if not keys:
        raise MatrixError(
            f"no quant.sf found under s3://{BUCKET}/{prefix}/. Writing empty matrices would look "
            f"exactly like a corpus in which nothing is expressed."
        )
    accessions = sorted(key for key in keys if key not in dropped)
    mapping = transcript_to_gene(transcripts)

    counts: dict[str, dict[str, float]] = {}
    tpms: dict[str, dict[str, float]] = {}
    report = AssemblyReport()

    for accession in accessions:
        body = _aws(["aws", "s3", "cp", f"s3://{BUCKET}/{keys[accession]}", "-"])
        per_gene_counts: dict[str, float] = collections.defaultdict(float)
        per_gene_tpm: dict[str, float] = collections.defaultdict(float)
        for line in io.StringIO(body).readlines()[1:]:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                continue
            gene = mapping.get(fields[0])
            if gene is None:
                gene = fields[0]
                report.unresolved_transcripts += 1
            per_gene_tpm[gene] += float(fields[3])
            per_gene_counts[gene] += float(fields[4])
        counts[accession] = dict(per_gene_counts)
        tpms[accession] = dict(per_gene_tpm)

        meta_key = keys[accession].replace("quant.sf", "meta_info.json")
        try:
            meta = json.loads(_aws(["aws", "s3", "cp", f"s3://{BUCKET}/{meta_key}", "-"]))
            report.qc.append(
                {
                    "run": accession,
                    "reference": reference,
                    "percent_mapped": round(float(meta.get("percent_mapped", 0.0)), 2),
                    "num_processed": meta.get("num_processed", 0),
                    "num_mapped": meta.get("num_mapped", 0),
                }
            )
        except (MatrixError, json.JSONDecodeError, ValueError) as exc:
            # QC is best-effort and never fatal: a missing meta_info.json does not invalidate the
            # quantification beside it.
            report.qc.append({"run": accession, "reference": reference, "error": str(exc)[:120]})

    genes = sorted({gene for sample in counts.values() for gene in sample})
    out_dir.mkdir(parents=True, exist_ok=True)
    write_matrix(out_dir / f"{reference}.counts.tsv.gz", genes, accessions, counts)
    write_matrix(out_dir / f"{reference}.tpm.tsv.gz", genes, accessions, tpms)

    report.genes = len(genes)
    report.samples = len(accessions)
    report.mitochondrial_genes = sum(1 for gene in genes if gene.startswith("Q0"))
    report.detected_genes_median = int(
        _median(
            [float(sum(1 for gene in genes if counts[a].get(gene, 0.0) > 0)) for a in accessions]
        )
    )
    return report
