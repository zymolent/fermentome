"""Load the transcriptomics and reference-genome layer into the atlas.

This layer had never reached the database. 172 SRA runs were staged to S3, six reference genomes
were fetched and checksummed, 109 runs were quantified and three expression matrices were built --
and none of it produced a row. Not a regression from the v5 schema rebuild either: the v4 backup
holds only publications too. The work existed as files and S3 objects that nothing pointed at.

Almost everything here is Zone R, because every value is what a source reported: RefSeq's bytes,
SRA's run metadata, S3's object listing. The one derived thing -- the expression matrices -- is
Zone H, rebuildable from the raw objects by re-running the pipeline.

**Expression values are not stored as rows.** ``analysis_result`` says so in the schema itself
("Points at Parquet on disk, never a BLOB in the database"), and 6,187 genes by 99 samples is six
hundred thousand numbers that no query in this atlas asks for one at a time. The matrices are
registered as files with their checksums. ``part_expression_record`` is a different thing
entirely -- engineered parts, not transcript abundance -- and is deliberately left alone.

**What is honestly gone.** The per-run ``quant.sf`` files were on the AWS instance and the
instance was terminated; only the aggregated matrices were downloaded. Per-run quantification is
therefore *not* re-derivable from what is local -- it would need the S3 raw objects reprocessed --
and this module records that rather than implying otherwise.

Inputs live in ``data/omics/`` rather than in a scratchpad, because a scratchpad is deleted with
its session and these files are the provenance for every row written here.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ..config import Settings
from . import references as references_mod

__all__ = [
    "DROPPED_RUNS",
    "OMICS_DIR",
    "REFERENCE_MANIFEST",
    "RUNINFO_CSV",
    "STAGING_MANIFEST",
    "LoadReport",
    "OmicsLoadError",
    "load_all",
    "load_matrices",
    "load_reference_genomes",
    "load_samples",
    "load_sra_runs",
    "load_yeast_reference_sequences",
    "matrix_shape",
    "sha256_of",
]

#: Curation inputs, committed alongside the code (PLAN.md N.2: ``data/`` is a curation tier).
OMICS_DIR: Final[str] = "data/omics"
REFERENCE_MANIFEST: Final[str] = "reference_manifest.json"
STAGING_MANIFEST: Final[str] = "staging_manifest.json"
DROPPED_RUNS: Final[str] = "dropped_runs.json"
RUNINFO_CSV: Final[str] = "sra_isobutanol_runinfo.csv"

_SALMON_PIPELINE: Final[str] = "salmon-selective-alignment"


class OmicsLoadError(RuntimeError):
    """An input is missing, or two inputs disagree. Never resolved by guessing."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def _int_or_none(value: str | None) -> int | None:
    """An integer, or NULL. Never 0 -- a missing count and a count of zero are different facts."""
    text = (value or "").strip()
    return int(text) if text.isdigit() else None


def _float_or_none(value: str | None) -> float | None:
    """A float, or NULL. `size_mb` is REAL in the schema, so 143.5 must not become 143."""
    text = (value or "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _text_or_none(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def omics_dir(settings: Settings) -> Path:
    return Path(settings.repo_root) / OMICS_DIR


def fasta_identity(path: Path) -> tuple[tuple[str, ...], int, str]:
    """``(sequence accessions, total bases, first header)`` read from the file itself.

    The point is to have an identity that does not come from whatever metadata happens to sit
    beside the file. This project has already shipped a manifest naming ``GCF_000092685.1`` --
    *Chlamydia trachomatis* -- for its *Zymomonas mobilis* genome. The download was fine; the
    label was not, and nothing downstream could tell, because everything downstream read the label.
    """
    accessions: list[str] = []
    bases = 0
    first = ""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if not first:
                    first = line[1:].strip()
                accessions.append(line[1:].split()[0])
            else:
                bases += len(line.strip())
    return tuple(accessions), bases, first


def _check_organism_matches(path: Path, organism: str, accession: str) -> str:
    """Confirm the FASTA's own headers name the organism the catalog expects.

    A genus-and-species check, not an exact one: RefSeq headers carry strain and assembly detail
    the catalog's name does not ("...ZM4 = ATCC 31821 strain ZM4 chromosome"), and demanding an
    exact match would reject correct files. Genus plus species is enough to separate *Zymomonas*
    from *Chlamydia*, which is the confusion that actually happened.
    """
    accessions, bases, first = fasta_identity(path)
    binomial = " ".join(organism.split()[:2]).lower()
    if binomial and binomial not in first.lower():
        raise OmicsLoadError(
            f"{path.name} is registered as {accession} ({organism}) but its first FASTA header "
            f"reads {first[:100]!r}. The bytes, not the label, say what a genome is -- refusing "
            f"to register it under a name its own sequences do not support."
        )
    return f"{len(accessions)} sequences, {bases} bases, first header {first[:60]!r}"


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise OmicsLoadError(f"{path} is missing; it is the provenance for rows this would write")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- reference genomes


def load_reference_genomes(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Register each fetched reference genome against the curated catalog.

    ``data/omics/reference_genomes.yaml`` is the spine, not the download manifest: it carries the
    ``reference_id`` that ``sra_run.reference_assembly`` joins on, the taxid, and the strain/species
    match names. The manifest only says what was actually downloaded and what its bytes hash to.
    An accession in one and not the other is a disagreement between the plan and the result, so it
    raises rather than silently registering whichever it happened to find.

    Rows go to ``reference_genome_asset`` and never to ``reference_sequence`` -- that table's
    ``encoding_genome`` foreign key is yeast-specific (nuclear/mitochondrial, NCBI tables 1 and 3)
    and would misrepresent a bacterial replicon, which reads under table 11. ``references.py``
    states this; it is repeated here because this is the other place that could get it wrong.

    The checksum is recomputed from the file on disk rather than trusted from the manifest. A
    truncated download is byte-for-byte plausible otherwise.
    """
    catalog = {
        entry.accession: entry
        for entry in references_mod.load_reference_genomes(
            references_mod.reference_genomes_path(settings)
        )
    }
    manifest = _read_json(omics_dir(settings) / REFERENCE_MANIFEST)
    genomes = Path(settings.genomes_dir)
    counts = {"organism": 0, "reference_genome_asset": 0}

    for entry in manifest:
        accession = str(entry["accession"])
        cataloged = catalog.get(accession)
        if cataloged is None:
            raise OmicsLoadError(
                f"{accession} was downloaded but is not in reference_genomes.yaml. The catalog is "
                f"what sra_run.reference_assembly joins on, so registering an asset outside it "
                f"would create a reference nothing can select."
            )
        path = genomes / Path(str(entry["path"])).name
        if not path.is_file():
            raise OmicsLoadError(
                f"{accession} ({cataloged.organism}) is in the manifest but {path} is not on "
                f"disk. Re-fetch it rather than writing a row that points at nothing."
            )
        measured = _check_organism_matches(path, cataloged.organism, accession)
        actual = sha256_of(path)
        if actual != entry["sha256"]:
            raise OmicsLoadError(
                f"{path.name}: the manifest records sha256 {entry['sha256']} but the file on disk "
                f"is {actual}. Refusing to choose between them."
            )

        conn.execute(
            "INSERT INTO organism (id, ncbi_taxid, name, zone, evidence, confidence) "
            "VALUES (?,?,?,'R',?,'high') ON CONFLICT(id) DO NOTHING",
            (
                f"YAA:ORG:{_slug(cataloged.id)}",
                cataloged.taxid,
                cataloged.organism,
                f"data/omics/reference_genomes.yaml: {cataloged.id}",
            ),
        )
        counts["organism"] += 1
        conn.execute(
            "INSERT INTO reference_genome_asset (id, reference_id, organism, sequence_accession, "
            "kind, file_path, checksum_sha256, size_bytes, source_url, retrieved_at, zone, "
            "evidence, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(sequence_accession, kind) DO UPDATE SET "
            "file_path=excluded.file_path, checksum_sha256=excluded.checksum_sha256, "
            "size_bytes=excluded.size_bytes, retrieved_at=excluded.retrieved_at",
            (
                f"YAA:RGA:{_slug(cataloged.id)}",
                cataloged.id,
                cataloged.organism,
                accession,
                "genome",
                str(path),
                actual,
                int(entry["bytes"]),
                str(entry["url"]),
                _utc_now(),
                f"{cataloged.role} ({measured}); catalog evidence: {cataloged.evidence}",
                cataloged.confidence,
            ),
        )
        counts["reference_genome_asset"] += 1
    return counts


# ------------------------------------------------------------------------------------ SRA runs


@dataclass(frozen=True)
class _Drop:
    run: str
    reason: str
    decided_by: str
    decided_on: str


def _dropped(settings: Settings) -> dict[str, _Drop]:
    payload = _read_json(omics_dir(settings) / DROPPED_RUNS)
    return {
        str(item["run"]): _Drop(
            run=str(item["run"]),
            reason=str(item["reason"]),
            decided_by=str(item["decided_by"]),
            decided_on=str(item["decided_on"]),
        )
        for item in payload["dropped"]
    }


def load_sra_runs(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Write one ``sra_run`` per run in the corpus, plus the ``raw_object`` staged to S3.

    Three facts that must survive, and that simply omitting rows would lose:

    * The two runs excluded from the matrices are still written, with the exclusion, who decided
      it and why recorded as evidence. A run dropped for a 9.6% mapping rate is a finding about
      its metadata, not an absence.
    * Runs whose organism the corpus doubts carry ``relevance_uncertain=1`` rather than being
      filtered out, so a later comparison cannot pick them up unaware.
    * ``reference_assembly`` and ``reference_match_quality`` come from
      ``references.select_reference`` against the curated catalog -- an exact string match, so a
      plain "Saccharomyces cerevisiae" run resolves to the S288C anchor as ``species_exact`` and
      never silently to CEN.PK. ``unmapped_fraction`` stays NULL: nobody has computed it per run
      in this database, and NULL says that where 0 would claim a perfect mapping.
    """
    directory = omics_dir(settings)
    catalog = references_mod.load_reference_genomes(references_mod.reference_genomes_path(settings))
    staging = _read_json(directory / STAGING_MANIFEST)
    drops = _dropped(settings)
    staged = {
        str(result["run"]): result
        for result in staging["results"]
        if result.get("status") == "copied"
    }
    destination = str(staging["destination"])
    bucket, prefix = destination.split("//", 1)[1].split("/", 1)

    runinfo_path = directory / RUNINFO_CSV
    if not runinfo_path.is_file():
        raise OmicsLoadError(f"{runinfo_path} is missing; it is the metadata for every run row")

    counts = {"dataset": 0, "sra_run": 0, "raw_object": 0}
    seen_studies: set[str] = set()
    retrieved_at = str(staging["staged_at_utc"])

    with runinfo_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            run = row["Run"].strip()
            if not run:
                continue

            study = _text_or_none(row.get("SRAStudy"))
            if study is not None and study not in seen_studies:
                conn.execute(
                    "INSERT INTO dataset (id, accession, repository, omics_type, platform, zone, "
                    "evidence, confidence, bioproject, organism, retrieved_at) "
                    "VALUES (?,?,'SRA','transcriptomics',?,'R',?,'high',?,?,?) "
                    "ON CONFLICT(id) DO NOTHING",
                    (
                        f"YAA:DATASET:{_slug(study)}",
                        study,
                        _text_or_none(row.get("Platform")),
                        f"SRA run selector export, {RUNINFO_CSV}",
                        _text_or_none(row.get("BioProject")),
                        _text_or_none(row.get("ScientificName")),
                        retrieved_at,
                    ),
                )
                seen_studies.add(study)
                counts["dataset"] += 1

            drop = drops.get(run)
            evidence = f"SRA run selector export, {RUNINFO_CSV}"
            if drop is not None:
                evidence = (
                    f"{evidence}; EXCLUDED from the expression matrices by {drop.decided_by} on "
                    f"{drop.decided_on}: {drop.reason}"
                )
            organism = _text_or_none(row.get("ScientificName"))
            selection = references_mod.select_reference(organism or "", catalog)
            conn.execute(
                "INSERT INTO sra_run (id, run_accession, dataset_id, experiment_accession, "
                "study_accession, bioproject, biosample, organism, taxid, library_strategy, "
                "library_layout, platform, instrument_model, spots, bases, size_mb, location_url, "
                "acquisition_status, priority_rank, retrieved_at, zone, evidence, confidence, "
                "reference_assembly, reference_match_quality, relevance_uncertain) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'R',?,'high',?,?,?) "
                "ON CONFLICT(run_accession) DO UPDATE SET evidence=excluded.evidence, "
                "acquisition_status=excluded.acquisition_status",
                (
                    f"YAA:SRARUN:{run}",
                    run,
                    f"YAA:DATASET:{_slug(study)}" if study else None,
                    _text_or_none(row.get("Experiment")),
                    study,
                    _text_or_none(row.get("BioProject")),
                    _text_or_none(row.get("BioSample")),
                    organism,
                    _int_or_none(row.get("TaxID")),
                    _text_or_none(row.get("LibraryStrategy")),
                    _text_or_none(row.get("LibraryLayout")),
                    _text_or_none(row.get("Platform")),
                    _text_or_none(row.get("Model")),
                    _int_or_none(row.get("spots")),
                    _int_or_none(row.get("bases")),
                    _float_or_none(row.get("size_MB")),
                    _text_or_none(row.get("download_path")),
                    # PLAN.md F.3, quoted in the schema beside this column: a run enters
                    # quantification only once its conditions are annotated, and none are, so
                    # 'discovered' is the only state a metadata harvest may write. That a run's
                    # bytes reached S3 is an object fact and lives in raw_object, not here.
                    "excluded" if drop is not None else "discovered",
                    0,
                    retrieved_at,
                    evidence,
                    selection.assembly_accession,
                    selection.match_quality,
                    1 if references_mod.is_relevance_uncertain(organism or "") else 0,
                ),
            )
            counts["sra_run"] += 1

            result = staged.get(run)
            if result is not None:
                conn.execute(
                    "INSERT INTO raw_object (id, run_accession, bucket, object_key, size_bytes, "
                    "retrieved_at, source_url, media_type, zone) "
                    "VALUES (?,?,?,?,?,?,?,'application/octet-stream','R') "
                    "ON CONFLICT(id) DO UPDATE SET size_bytes=excluded.size_bytes",
                    (
                        f"YAA:RAWOBJ:{run}",
                        run,
                        bucket,
                        f"{prefix}{run}",
                        int(result["bytes"]),
                        retrieved_at,
                        f"{staging['source']}{run}",
                    ),
                )
                counts["raw_object"] += 1
    return counts


# ------------------------------------------------------------------------------------ matrices


def matrix_shape(path: Path) -> tuple[int, int]:
    """``(genes, samples)`` read from the file itself, not from a manifest that may have drifted."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        samples = len(handle.readline().rstrip("\n").split("\t")) - 1
        genes = sum(1 for _ in handle)
    return genes, samples


def load_matrices(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Register the built expression matrices as analysis results pointing at their files.

    One ``processing_run`` covers the quantification, because one pipeline invocation produced all
    three matrices. Its ``finished_at`` is the newest matrix mtime -- the honest answer available
    locally, since the instance that ran it is gone and its logs with it.
    """
    matrices = Path(settings.matrices_dir)
    if not matrices.is_dir():
        raise OmicsLoadError(f"{matrices} does not exist; there is nothing to register")
    files = sorted(p for p in matrices.iterdir() if p.suffix in {".gz", ".tsv", ".json"})
    if not files:
        raise OmicsLoadError(f"{matrices} holds no matrix files")

    run_id = "YAA:PROCRUN:salmon-quantification"
    finished = datetime.fromtimestamp(max(p.stat().st_mtime for p in files), UTC)
    conn.execute(
        "INSERT INTO processing_run (id, pipeline, version, parameters_hash, finished_at, "
        "exit_status) VALUES (?,?,?,?,?,0) "
        "ON CONFLICT(id) DO UPDATE SET finished_at=excluded.finished_at",
        (
            run_id,
            _SALMON_PIPELINE,
            "salmon 1.10.x, decoy-aware gentrome index",
            "",
            finished.isoformat(timespec="seconds"),
        ),
    )

    written = 0
    for path in files:
        if path.name.endswith(".tsv.gz"):
            genes, samples = matrix_shape(path)
            kind = "expression_matrix"
            detail = f"{genes} genes x {samples} samples"
        else:
            kind = "quantification_summary"
            detail = path.name
        conn.execute(
            "INSERT INTO analysis_result (id, processing_run_id, kind, payload_ref, zone) "
            "VALUES (?,?,?,?,'H') ON CONFLICT(id) DO UPDATE SET payload_ref=excluded.payload_ref",
            (f"YAA:ANALYSIS:{_slug(path.name)}", run_id, kind, f"{path} ({detail})"),
        )
        written += 1
    return {"processing_run": 1, "analysis_result": written}


# ----------------------------------------------------------------------------------------- all


@dataclass(frozen=True)
class LoadReport:
    """Row counts per table, so a load is checked against an expectation rather than trusted."""

    references: dict[str, int]
    runs: dict[str, int]
    matrices: dict[str, int]
    samples: dict[str, int] = field(default_factory=dict)
    sequences: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for part in (self.references, self.runs, self.matrices, self.samples, self.sequences):
            merged.update(part)
        return merged


def load_all(conn: sqlite3.Connection, settings: Settings) -> LoadReport:
    """Load every omics layer in dependency order and commit once."""
    references = load_reference_genomes(conn, settings)
    runs = load_sra_runs(conn, settings)
    matrices = load_matrices(conn, settings)
    # After the runs, because a sample points at the dataset a run belongs to.
    samples = load_samples(conn)
    sequences = load_yeast_reference_sequences(conn, settings)
    conn.commit()
    return LoadReport(
        references=references,
        runs=runs,
        matrices=matrices,
        samples=samples,
        sequences=sequences,
    )


# ------------------------------------------------------------------- samples and yeast sequences


def _sample_evidence(run_accession: str, organism: str | None) -> str:
    suffix = f" ({organism})" if organism else ""
    return f"one sample per SRA run; run {run_accession}{suffix}"


def load_samples(conn: sqlite3.Connection) -> dict[str, int]:
    """One ``sample`` per SRA run, so a measurement has something to attach to.

    ``measurement`` requires a sample, strain or experiment -- the table's own CHECK says so --
    and all three were empty, which made a measurement unstorable however good the extraction.
    This closes the cheapest of the three.

    ``strain_id`` and ``condition_context_id`` stay NULL, and that is the honest state rather
    than an omission: which strain a run used and under what conditions are curation questions
    (PLAN.md F.3 blocks a contrast until a condition context is *approved*), and a guessed value
    here would be indistinguishable from a curated one.
    """
    rows = conn.execute(
        "SELECT id, run_accession, dataset_id, organism FROM sra_run ORDER BY run_accession"
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO sample (id, dataset_id, zone, evidence, confidence) "
            "VALUES (?,?,'R',?,'high') "
            "ON CONFLICT(id) DO UPDATE SET dataset_id=excluded.dataset_id",
            (
                f"YAA:SAMPLE:{row['run_accession']}",
                row["dataset_id"],
                _sample_evidence(row["run_accession"], row["organism"]),
            ),
        )
    conn.commit()
    return {"sample": len(rows)}


def load_yeast_reference_sequences(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Register the S288C nuclear and mitochondrial references in ``reference_sequence``.

    Separate from ``reference_genome_asset`` on purpose, and only for yeast. That table's
    ``encoding_genome`` foreign key and its nuclear/mitochondrial ``kind`` vocabulary are
    yeast-specific; a bacterial replicon reading under table 11 has no place in either, which is
    why ``load_reference_genomes`` deliberately does not write here.

    ``translation_verified`` is set on the mitochondrial row only if the CDS in the GenBank record
    actually reproduce NCBI's own ``/translation`` under table 3. It is a claim about this
    reference agreeing with `fermdb.genetic_code`, so it is earned per load rather than assumed
    from a previous one.
    """
    from .mito_transcripts import MITOCHONDRIAL_ACCESSION, parse_mitochondrial_cds

    genomes = Path(settings.genomes_dir)
    organism = "YAA:ORG:s288c-r64"
    written = 0

    nuclear = genomes / "s288c.fna.gz"
    if not nuclear.is_file():
        raise OmicsLoadError(f"{nuclear} is missing; it is the nuclear reference")
    accessions, bases, _ = fasta_identity(nuclear)
    conn.execute(
        "INSERT INTO reference_sequence (id, kind, organism_id, assembly_accession, "
        "sequence_accession, encoding_genome, file_path, checksum_sha256, size_bytes, source_url, "
        "translation_verified, retrieved_at, zone, evidence, confidence) "
        "VALUES (?,'nuclear_genome',?,?,?,'nuclear',?,?,?,?,0,?,'R',?,'high') "
        "ON CONFLICT(sequence_accession, kind) DO UPDATE SET "
        "checksum_sha256=excluded.checksum_sha256",
        (
            "YAA:REFSEQ:s288c-nuclear",
            organism,
            "GCF_000146045.2",
            # The whole assembly rather than one chromosome; the accession column names what the
            # file is, and this file is every nuclear chromosome plus the mitochondrion.
            "GCF_000146045.2",
            str(nuclear),
            sha256_of(nuclear),
            nuclear.stat().st_size,
            "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/146/045/GCF_000146045.2_R64/",
            _utc_now(),
            f"R64 assembly, {len(accessions)} sequences, {bases} bases. Read under NCBI table 1.",
        ),
    )
    written += 1

    genbank = genomes / "nc_001224.gb"
    if genbank.is_file():
        records, _ = parse_mitochondrial_cds(genbank.read_text(encoding="utf-8"))
        # Every returned CDS has already reproduced NCBI's /translation under table 3, and at
        # least one exercises a codon table 1 reads differently -- otherwise the reference does
        # not demonstrate the disagreement it is kept to prove.
        verified = bool(records) and any(record.table_1_would_differ for record in records)
        conn.execute(
            "INSERT INTO reference_sequence (id, kind, organism_id, assembly_accession, "
            "sequence_accession, encoding_genome, file_path, checksum_sha256, size_bytes, "
            "source_url, translation_verified, retrieved_at, zone, evidence, confidence) "
            "VALUES (?,'mitochondrial_genome',?,?,?,'mitochondrial',?,?,?,?,?,?,'R',?,'high') "
            "ON CONFLICT(sequence_accession, kind) DO UPDATE SET "
            "translation_verified=excluded.translation_verified",
            (
                "YAA:REFSEQ:s288c-mitochondrial",
                organism,
                "GCF_000146045.2",
                MITOCHONDRIAL_ACCESSION,
                str(genbank),
                sha256_of(genbank),
                genbank.stat().st_size,
                f"https://www.ncbi.nlm.nih.gov/nuccore/{MITOCHONDRIAL_ACCESSION}",
                1 if verified else 0,
                _utc_now(),
                f"{len(records)} CDS reproduce NCBI's own /translation under table 3; "
                f"{sum(1 for r in records if r.table_1_would_differ)} of them read differently "
                f"under table 1, which is the disagreement this reference exists to demonstrate.",
            ),
        )
        written += 1
    conn.commit()
    return {"reference_sequence": written}
