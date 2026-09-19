"""Fetch and store the small DNA references everything else depends on.

The *S. cerevisiae* S288C nuclear genome (~12 Mb, assembly R64 / GCF_000146045.2) and the
mitochondrial genome (~86 kb, NC_001224.1), fetched via NCBI efetch (db=nuccore) and stored
content-addressed under `Settings.genomes_dir`, with a checksum recorded on every row.

**The mitochondrial fetch is guarded by a real check, not a hope.** PLAN.md's binding instruction
is to verify that the fetched mtDNA translates correctly under NCBI translation table 3 using
`fermdb.genetic_code` -- and FAILS under table 1 -- as the proof that the fetched reference and the
project's own code model agree. `verify_mitochondrial_translation` does exactly that, against the
GenBank record's own annotated CDS features and their `/translation` qualifiers (ground truth from
NCBI's curators, not this module's opinion), and `fetch_mitochondrial_reference` refuses to store
anything if it disagrees.

Everything here is Zone R (`reference_sequence.zone` fixes it by CHECK): exactly what NCBI
Nucleotide reported, checksummed, never a curator's or a model's reading of it.

**Reference selection, for "which genome is this transcriptomic run against".** The isobutanol SRA
corpus spans five organisms (docs/reference/DATA_VOLUME.md section 2), so quantification needs a
reference PER ORGANISM, not one for the whole corpus. `data/omics/reference_genomes.yaml` catalogs
every reference this atlas currently knows about -- the S288C anchor, the two parallel *S.
cerevisiae* comparators (CEN.PK113-7D, Ethanol Red), and the three small bacterial hosts (E. coli
K-12 MG1655, Zymomonas mobilis ZM4, Lactococcus cremoris) -- plus a Fusarium graminearum entry kept
only for curator review (see `is_relevance_uncertain`). `load_reference_genomes` parses it,
`select_reference` chooses per run (never guessing a strain runinfo did not report), and
`fetch_organism_reference` generalizes `fetch_fasta`/`fetch_genbank`/`store_content_addressed` to
fetch any small (2-5 Mb) organism's genome+annotation -- landing in `reference_genome_asset`, a
separate table from `reference_sequence`, because that table's `kind`/`encoding_genome` columns are
yeast-specific (nuclear/mitochondrial, NCBI tables 1/3) and would misrepresent a bacterial replicon
under table 11.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import genetic_code
from ..config import Settings
from . import EUTILS_BASE, EutilsClient, OmicsFetchError

#: Verified live against the NCBI Datasets API
#: (api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000146045.2/sequence_reports) on
#: 2026-09-19: assembly name R64, 16 nuclear chromosomes, 12,071,326 bp total -- matching
#: docs/reference/DATA_VOLUME.md's "~12 Mb" estimate. Order is chromosome I-XVI.
ASSEMBLY_ACCESSION = "GCF_000146045.2"
ASSEMBLY_NAME = "R64"
NUCLEAR_CHROMOSOME_ACCESSIONS: tuple[str, ...] = (
    "NC_001133.9",
    "NC_001134.8",
    "NC_001135.5",
    "NC_001136.10",
    "NC_001137.3",
    "NC_001138.5",
    "NC_001139.9",
    "NC_001140.6",
    "NC_001141.2",
    "NC_001142.9",
    "NC_001143.9",
    "NC_001144.5",
    "NC_001145.3",
    "NC_001146.8",
    "NC_001147.6",
    "NC_001148.4",
)

#: Verified live against NCBI esummary (db=nuccore, id=NC_001224.1) on 2026-09-19: 85,779 bp,
#: "Saccharomyces cerevisiae S288c mitochondrion, complete genome" -- matching DATA_VOLUME.md's
#: "~86 kb" estimate. Also verified as the assembly's own MT sequence via the Datasets API
#: sequence_reports call above (chr_name='MT').
MITOCHONDRIAL_ACCESSION = "NC_001224.1"


class ReferenceVerificationError(OmicsFetchError):
    """A fetched mtDNA reference did not translate the way NCBI's own annotation says it must."""


# ------------------------------------------------------------------------------------------ fetch


@dataclass(frozen=True)
class FetchedSequence:
    accession: str
    content: str
    source_url: str


def _efetch_url(accession: str, *, rettype: str) -> str:
    """Reconstructs the URL `EutilsClient.efetch` builds, for recording as `source_url`.

    Not used to make the request (the client owns that); this is purely so the stored
    `reference_sequence.source_url` names the exact resource fetched, per PLAN.md J.5 provenance.
    """
    return f"{EUTILS_BASE}/efetch.fcgi?db=nuccore&id={accession}&rettype={rettype}&retmode=text"


def fetch_fasta(client: EutilsClient, accession: str) -> FetchedSequence:
    content = client.efetch(db="nuccore", ids=[accession], rettype="fasta", retmode="text")
    if not content.strip().startswith(">"):
        raise OmicsFetchError(
            f"efetch fasta for {accession} did not return FASTA: {content[:80]!r}"
        )
    return FetchedSequence(accession, content, _efetch_url(accession, rettype="fasta"))


def _is_contig_stub(genbank_text: str) -> bool:
    """True if `genbank_text` is a bare CON-division master record, not an annotated sequence.

    Discovered live while fetching the S288C nuclear chromosomes (2026-09-20): a handful of them
    (chromosomes IV, VII, XII and XV in this assembly) are RefSeq CON-division records whose plain
    `rettype=gb` is just a `source` feature and a `CONTIG join(...)` line pointing at the real,
    fully-annotated INSDC component -- a few KB instead of the hundreds of KB a real gene model
    is. A genuine complete (PLN-division) record ends in `ORIGIN`/sequence/`//` and never has a
    `CONTIG` line at all, so its presence is what this function checks for.
    """
    return any(line.startswith("CONTIG") for line in genbank_text.splitlines())


def fetch_genbank(client: EutilsClient, accession: str) -> FetchedSequence:
    """Fetch the annotated GenBank flat file for `accession`.

    Falls back from `rettype=gb` to `rettype=gbwithparts` when the plain form turns out to be a
    CON-division stub (`_is_contig_stub`): the stub is valid GenBank text and would otherwise pass
    every check silently while carrying almost no annotation.
    """
    content = client.efetch(db="nuccore", ids=[accession], rettype="gb", retmode="text")
    first_line = content.splitlines()[0] if content else ""
    if "LOCUS" not in first_line:
        raise OmicsFetchError(f"efetch gb for {accession} did not return a GenBank record")
    if _is_contig_stub(content):
        expanded = client.efetch(
            db="nuccore", ids=[accession], rettype="gbwithparts", retmode="text"
        )
        if "LOCUS" not in (expanded.splitlines()[0] if expanded else ""):
            raise OmicsFetchError(
                f"efetch gbwithparts for {accession} did not return a GenBank record, after "
                "rettype=gb returned a bare CONTIG stub"
            )
        return FetchedSequence(accession, expanded, _efetch_url(accession, rettype="gbwithparts"))
    return FetchedSequence(accession, content, _efetch_url(accession, rettype="gb"))


def parse_fasta_sequence(fasta_text: str) -> str:
    """Strip the header line(s) and return the concatenated, upper-cased sequence."""
    return "".join(
        line.strip().upper() for line in fasta_text.splitlines() if not line.startswith(">")
    )


# ------------------------------------------------------------------------- GenBank flat-file parse
#
# A purpose-built parser for exactly what `verify_mitochondrial_translation` needs: the ORIGIN
# sequence block, and CDS features with a simple (non-join, non-complement) location plus
# `/transl_table` and `/translation` qualifiers. It is not a general GenBank reader -- a `join(...)`
# CDS (COX1 and its introns) or a `complement(...)` feature is skipped, not mis-parsed, because
# this module only needs ONE trustworthy CDS per reference to run the table-agreement check, not a
# full gene model.

_SIMPLE_LOCATION_RE = re.compile(r"^(\d+)\.\.(\d+)$")


def _parse_genbank_sequence(genbank_text: str) -> str:
    lines = genbank_text.splitlines()
    try:
        origin_index = next(i for i, line in enumerate(lines) if line.startswith("ORIGIN"))
    except StopIteration as exc:
        raise OmicsFetchError("GenBank record has no ORIGIN block") from exc
    chars: list[str] = []
    for line in lines[origin_index + 1 :]:
        if line.startswith("//"):
            break
        chars.extend(line.split()[1:])  # drop the leading position number
    return "".join(chars).upper()


def _iter_features(genbank_text: str) -> Iterator[tuple[str, str, list[str]]]:
    """Yield `(feature_key, location, qualifier_lines)` for each feature in the FEATURES table."""
    lines = genbank_text.splitlines()
    in_features = False
    key: str | None = None
    location = ""
    qualifiers: list[str] = []
    for line in lines:
        if line.startswith("FEATURES"):
            in_features = True
            continue
        if not in_features:
            continue
        if line.startswith("ORIGIN") or line.startswith("//"):
            break
        # A new feature line starts at column 6 (5 spaces) with a non-space key; a qualifier or
        # continuation line is indented further still.
        if line[:5] == "     " and len(line) > 5 and line[5] != " ":
            if key is not None:
                yield key, location, qualifiers
            rest = line[5:].strip()
            parts = rest.split(None, 1)
            key = parts[0]
            location = parts[1].strip() if len(parts) > 1 else ""
            qualifiers = []
        elif key is not None:
            qualifiers.append(line.strip())
    if key is not None:
        yield key, location, qualifiers


def _parse_qualifiers(qualifier_lines: list[str]) -> dict[str, str]:
    """`["/gene=\"ATP8\"", "/translation=\"MPQ...", "ISKL\""]` -> `{"gene": "ATP8", ...}`.

    A qualifier's value can wrap across several lines with no separator between them (this is how
    GenBank wraps `/translation`); a continuation line is anything that does not itself start a new
    `/qualifier`.
    """
    quals: dict[str, str] = {}
    name: str | None = None
    value_parts: list[str] = []

    def flush() -> None:
        if name is not None:
            quals[name] = "".join(value_parts).strip('"')

    for line in qualifier_lines:
        if line.startswith("/"):
            flush()
            key, _, value = line[1:].partition("=")
            name = key
            value_parts = [value]
        elif name is not None:
            value_parts.append(line)
    flush()
    return quals


@dataclass(frozen=True)
class TranslationCheck:
    """One CDS, translated under both tables and compared against NCBI's own `/translation`."""

    gene: str
    transl_table: int
    reference_translation: str
    table3_translation: str
    table1_translation: str

    @property
    def matches_table3(self) -> bool:
        return self.table3_translation == self.reference_translation

    @property
    def matches_table1(self) -> bool:
        return self.table1_translation == self.reference_translation


def verify_mitochondrial_translation(genbank_text: str) -> list[TranslationCheck]:
    """Translate every simple annotated CDS in `genbank_text` under both tables and compare.

    Raises `ReferenceVerificationError` if:

    * no simple (non-join, non-complement) CDS with `/translation` was found to check -- the
      parser found nothing, which is itself worth failing loudly on rather than silently
      "verifying" zero genes;
    * any checked CDS fails to reproduce NCBI's own `/translation` under table 3 -- the check that
      proves `fermdb.genetic_code` and the fetched reference agree;
    * every checked CDS *also* reproduces it under table 1 -- meaning nothing in the reference
      exercised an ambiguous codon, so the reference does not demonstrate the table 1/table 3
      disagreement it is fetched specifically to prove.
    """
    sequence = _parse_genbank_sequence(genbank_text)
    checks: list[TranslationCheck] = []
    for feature_key, location, qualifier_lines in _iter_features(genbank_text):
        if feature_key != "CDS":
            continue
        quals = _parse_qualifiers(qualifier_lines)
        translation = quals.get("translation")
        transl_table = quals.get("transl_table")
        if translation is None or transl_table is None:
            continue
        match = _SIMPLE_LOCATION_RE.match(location)
        if match is None:
            continue  # join(...)/complement(...): out of scope for this check, not an error
        start, end = int(match.group(1)), int(match.group(2))
        cds_seq = sequence[start - 1 : end]
        checks.append(
            TranslationCheck(
                gene=quals.get("gene", "?"),
                transl_table=int(transl_table),
                reference_translation=translation,
                table3_translation=genetic_code.translate(
                    cds_seq, genetic_code.TABLE_3, to_stop=True
                ),
                table1_translation=genetic_code.translate(
                    cds_seq, genetic_code.TABLE_1, to_stop=True
                ),
            )
        )
    if not checks:
        raise ReferenceVerificationError(
            "no simple (non-join, non-complement) annotated CDS with /translation found to "
            "verify against; the GenBank record's FEATURES table may be malformed or empty"
        )
    failing_table3 = [c.gene for c in checks if not c.matches_table3]
    if failing_table3:
        raise ReferenceVerificationError(
            "reference does not translate correctly under table 3 (fermdb.genetic_code.TABLE_3): "
            + ", ".join(failing_table3)
        )
    if all(c.matches_table1 for c in checks):
        raise ReferenceVerificationError(
            "every checked CDS also translates correctly under table 1, so this reference does "
            "not demonstrate the table 1/table 3 disagreement it is fetched to prove"
        )
    return checks


# ------------------------------------------------------------------------------- content-addressed


@dataclass(frozen=True)
class StoredFile:
    path: Path
    checksum_sha256: str
    size_bytes: int


def store_content_addressed(genomes_dir: Path, content: str) -> StoredFile:
    """Write `content` under `genomes_dir/reference/<sha256[:2]>/<sha256>`, keyed by its own hash.

    Writing is a no-op if the exact bytes are already there: identical content re-fetched (the
    same accession twice, or two accessions that happen to be byte-identical) is stored once. This
    is the derived tier (`Settings.genomes_dir`), the only tier fermdb ever creates on its own
    (docs/reference/CONVENTIONS.md "Paths and configuration").
    """
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    target_dir = genomes_dir / "reference" / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / digest
    if not target.exists():
        target.write_bytes(payload)
    return StoredFile(path=target, checksum_sha256=digest, size_bytes=len(payload))


def _reference_row(
    *,
    kind: str,
    sequence_accession: str,
    encoding_genome: str,
    stored: StoredFile,
    source_url: str,
    retrieved_at: str,
    translation_verified: bool,
    evidence: str,
) -> dict[str, object]:
    slug = sequence_accession.lower().replace(".", "-").replace("_", "-")
    return {
        "id": f"YAA:REFSEQ:{kind.replace('_', '-')}-{slug}",
        "kind": kind,
        "organism_id": None,  # organism curation is out of this package's scope
        "assembly_accession": ASSEMBLY_ACCESSION,
        "sequence_accession": sequence_accession,
        "encoding_genome": encoding_genome,
        "file_path": str(stored.path),
        "checksum_sha256": stored.checksum_sha256,
        "size_bytes": stored.size_bytes,
        "source_url": source_url,
        "translation_verified": 1 if translation_verified else 0,
        "retrieved_at": retrieved_at,
        "zone": "R",
        "evidence": evidence,
        "confidence": "high",
    }


def fetch_mitochondrial_reference(
    client: EutilsClient,
    genomes_dir: Path,
    *,
    retrieved_at: str,
    accession: str = MITOCHONDRIAL_ACCESSION,
) -> list[dict[str, object]]:
    """Fetch, verify and store the mitochondrial genome and its annotation.

    Raises `ReferenceVerificationError` (without storing anything as verified) if
    `verify_mitochondrial_translation` disagrees -- the gate PLAN.md requires: the reference is
    not trusted merely because it downloaded successfully.
    """
    fasta = fetch_fasta(client, accession)
    genbank = fetch_genbank(client, accession)
    checks = verify_mitochondrial_translation(genbank.content)

    stored_fasta = store_content_addressed(genomes_dir, fasta.content)
    stored_genbank = store_content_addressed(genomes_dir, genbank.content)
    evidence = (
        f"NCBI Nucleotide accession {accession}, fetched live via eutils efetch on {retrieved_at}; "
        f"translation verified against fermdb.genetic_code table 3 ({len(checks)} CDS checked: "
        f"{', '.join(c.gene for c in checks)}) and confirmed to disagree under table 1"
    )
    return [
        _reference_row(
            kind="mitochondrial_genome",
            sequence_accession=accession,
            encoding_genome="mitochondrial",
            stored=stored_fasta,
            source_url=fasta.source_url,
            retrieved_at=retrieved_at,
            translation_verified=True,
            evidence=evidence,
        ),
        _reference_row(
            kind="mitochondrial_annotation",
            sequence_accession=accession,
            encoding_genome="mitochondrial",
            stored=stored_genbank,
            source_url=genbank.source_url,
            retrieved_at=retrieved_at,
            translation_verified=True,
            evidence=evidence,
        ),
    ]


def fetch_nuclear_reference(
    client: EutilsClient,
    genomes_dir: Path,
    *,
    retrieved_at: str,
    accessions: tuple[str, ...] = NUCLEAR_CHROMOSOME_ACCESSIONS,
) -> list[dict[str, object]]:
    """Fetch and store each nuclear chromosome's sequence and annotation.

    Nuclear genes are translated under table 1 unconditionally (docs/reference/CONVENTIONS.md
    "Genetic code and compartment": the code follows the encoding genome, and every nuclear gene
    is table 1 by definition), so there is no table-agreement check to run here the way there is
    for mtDNA -- `translation_verified` is `False` on these rows for that reason, not because the
    fetch is less trustworthy.
    """
    rows: list[dict[str, object]] = []
    for accession in accessions:
        fasta = fetch_fasta(client, accession)
        genbank = fetch_genbank(client, accession)
        stored_fasta = store_content_addressed(genomes_dir, fasta.content)
        stored_genbank = store_content_addressed(genomes_dir, genbank.content)
        evidence = (
            f"NCBI Nucleotide accession {accession}, part of assembly {ASSEMBLY_ACCESSION} "
            f"({ASSEMBLY_NAME}), fetched live via eutils efetch on {retrieved_at}"
        )
        rows.append(
            _reference_row(
                kind="nuclear_genome",
                sequence_accession=accession,
                encoding_genome="nuclear",
                stored=stored_fasta,
                source_url=fasta.source_url,
                retrieved_at=retrieved_at,
                translation_verified=False,
                evidence=evidence,
            )
        )
        rows.append(
            _reference_row(
                kind="nuclear_annotation",
                sequence_accession=accession,
                encoding_genome="nuclear",
                stored=stored_genbank,
                source_url=genbank.source_url,
                retrieved_at=retrieved_at,
                translation_verified=False,
                evidence=evidence,
            )
        )
    return rows


_UPSERT_REFERENCE_SQL = """
INSERT INTO reference_sequence (id, kind, organism_id, assembly_accession, sequence_accession,
                                 encoding_genome, file_path, checksum_sha256, size_bytes,
                                 source_url, translation_verified, retrieved_at, zone, evidence,
                                 confidence)
VALUES (:id, :kind, :organism_id, :assembly_accession, :sequence_accession, :encoding_genome,
        :file_path, :checksum_sha256, :size_bytes, :source_url, :translation_verified,
        :retrieved_at, :zone, :evidence, :confidence)
ON CONFLICT(sequence_accession, kind) DO UPDATE SET
    file_path = excluded.file_path,
    checksum_sha256 = excluded.checksum_sha256,
    size_bytes = excluded.size_bytes,
    translation_verified = excluded.translation_verified,
    retrieved_at = excluded.retrieved_at,
    evidence = excluded.evidence
"""


def write_reference_rows(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> int:
    """Upsert `rows` into `reference_sequence`, keyed by `(sequence_accession, kind)`.

    Does not open or close `conn`; `fermdb.db.open_db` is the only function that does that.
    """
    for row in rows:
        conn.execute(_UPSERT_REFERENCE_SQL, row)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------------------------
# data/omics/reference_genomes.yaml: the reference genome catalog, and per-run selection.
#
# THE OWNER'S QUESTION this section answers: "transcriptomic data is based on which genome" --
# quantified PER ORGANISM (five in the isobutanol corpus, docs/reference/DATA_VOLUME.md section 2),
# never assumed to be one reference for the whole atlas. Loading this file is package-level (like
# `load_dataset_families` in `omics/__init__.py`) for the same reason: it is a curated fact table,
# not something either `sra.py` or a hypothetical future quantification module owns more than the
# other.
# ---------------------------------------------------------------------------------------------

_CONFIDENCE_VALUES: tuple[str, ...] = ("unverified", "low", "medium", "high")

#: `sra_run.reference_match_quality`'s CHECK constraint (schema.sql, "omics acquisition"), restated
#: here because `select_reference` is the one function that produces these four strings. `'none'`
#: is a real, storable value -- "this atlas looked and found no reference" -- never confused with
#: the column being left NULL ("selection was never attempted"; see `sra.sra_run_row`).
REFERENCE_MATCH_QUALITIES: tuple[str, ...] = (
    "strain_matched",
    "species_exact",
    "species_proxy",
    "none",
)


class ReferenceGenomesError(ValueError):
    """`data/omics/reference_genomes.yaml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class ReferenceGenome:
    """One row of `data/omics/reference_genomes.yaml`: a reference genome the isobutanol/ethanol
    corpus's organisms need, independent of whether fermdb has fetched its bytes yet (`fetched`).

    `strain_match_names` and `species_match_names` are exact strings as SRA runinfo's
    `ScientificName` reports them -- `select_reference` below matches on exact string equality
    only, deliberately, never a prefix or substring (docs/reference/CONVENTIONS.md "never guess"
    applied to reference selection, not only to strain identity).
    """

    id: str
    organism: str
    taxid: int | None
    accession: str
    assembly_level: str
    n50_bp: int | None
    role: str
    is_species_default: bool
    fetched: bool
    structural_caveats: str | None
    strain_match_names: tuple[str, ...]
    species_match_names: tuple[str, ...]
    proxy_for: tuple[str, ...]
    relevance_uncertain: bool
    relevance_note: str | None
    evidence: str
    confidence: str


def load_reference_genomes(path: str | Path) -> list[ReferenceGenome]:
    """Parse `data/omics/reference_genomes.yaml`'s `references` list into `ReferenceGenome` rows.

    No path is hardcoded here: the caller resolves `path` from `Settings` (repo tier), per
    docs/reference/CONVENTIONS.md ("Paths and configuration") -- see `reference_genomes_path`.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ReferenceGenomesError(f"no reference genomes file at {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or "references" not in document:
        raise ReferenceGenomesError(
            f"{file_path}: expected a mapping with a top-level 'references'"
        )
    entries = document["references"]
    if not isinstance(entries, list):
        raise ReferenceGenomesError(f"{file_path}: 'references' must be a list")

    result: list[ReferenceGenome] = []
    seen: set[str] = set()
    for index, row in enumerate(entries):
        if not isinstance(row, dict):
            raise ReferenceGenomesError(f"{file_path}: references[{index}] must be a mapping")
        try:
            entry_id = str(row["id"])
            organism = str(row["organism"])
            accession = str(row["accession"])
            assembly_level = str(row["assembly_level"])
            role = str(row["role"])
            evidence = str(row["evidence"])
            confidence = str(row["confidence"])
        except KeyError as exc:
            raise ReferenceGenomesError(f"{file_path}: references[{index}] missing {exc}") from exc
        if confidence not in _CONFIDENCE_VALUES:
            raise ReferenceGenomesError(
                f"{file_path}: references[{index}] ({entry_id!r}) has confidence {confidence!r}; "
                f"must be one of {'/'.join(_CONFIDENCE_VALUES)}"
            )
        if entry_id in seen:
            raise ReferenceGenomesError(f"{file_path}: duplicate reference id {entry_id!r}")
        seen.add(entry_id)
        result.append(
            ReferenceGenome(
                id=entry_id,
                organism=organism,
                taxid=row.get("taxid"),
                accession=accession,
                assembly_level=assembly_level,
                n50_bp=row.get("n50_bp"),
                role=role,
                is_species_default=bool(row.get("is_species_default", False)),
                fetched=bool(row.get("fetched", False)),
                structural_caveats=row.get("structural_caveats"),
                strain_match_names=tuple(row.get("strain_match_names") or ()),
                species_match_names=tuple(row.get("species_match_names") or ()),
                proxy_for=tuple(row.get("proxy_for") or ()),
                relevance_uncertain=bool(row.get("relevance_uncertain", False)),
                relevance_note=row.get("relevance_note"),
                evidence=evidence,
                confidence=confidence,
            )
        )
    return result


def reference_genomes_path(settings: Settings) -> Path:
    """`data/omics/reference_genomes.yaml`, resolved off `settings.repo_root`.

    Same pattern as `fermdb.omics.dataset_families_path`: a fixed sub-path off the already-
    configurable `repo_root` rather than its own `env/paths.yaml` key.
    """
    return settings.repo_root / "data" / "omics" / "reference_genomes.yaml"


@dataclass(frozen=True)
class ReferenceSelection:
    """The reference chosen for one `sra_run.organism`, and how well it matches."""

    assembly_accession: str | None
    match_quality: str
    matched_reference_id: str | None


def select_reference(organism: str, references: Sequence[ReferenceGenome]) -> ReferenceSelection:
    """Choose a reference for `organism` (an SRA runinfo `ScientificName`, verbatim).

    Three passes, most specific first, each an EXACT string match -- no prefix or substring
    matching, deliberately: a looser match could silently pair, say, a pathogenic *E. coli*
    isolate's run with the K-12 lab-strain reference (PLAN.md S.3 "never guess").

    1. `strain_matched` -- `organism` names a cataloged reference's own strain exactly.
    2. `species_exact` -- `organism`'s species matches a reference marked `is_species_default`
       for that species (at most one default per species in this catalog; a plain "Saccharomyces
       cerevisiae" run resolves to the S288C anchor here, never to CEN.PK or Ethanol Red).
    3. `species_proxy` -- no exact species reference exists, but a cataloged reference declares
       itself a stand-in (`proxy_for`) for this organism. Not exercised by the current five-organism
       corpus (each already has its own species-level default); the mechanism exists for the day a
       run appears in a species this catalog has not been extended to cover.

    Returns `('none', None)` when nothing matches -- a real, recorded answer (PLAN.md F.3's
    metadata-poverty problem means an unrecognized organism string is expected, not a bug), and
    when `organism` itself is blank.
    """
    name = organism.strip() if organism else ""
    if not name:
        return ReferenceSelection(None, "none", None)

    for ref in references:
        if name in ref.strain_match_names:
            return ReferenceSelection(ref.accession, "strain_matched", ref.id)

    for ref in references:
        if ref.is_species_default and name in ref.species_match_names:
            return ReferenceSelection(ref.accession, "species_exact", ref.id)

    for ref in references:
        if name in ref.proxy_for:
            return ReferenceSelection(ref.accession, "species_proxy", ref.id)

    return ReferenceSelection(None, "none", None)


#: Runs whose organism resolves to one of these are flagged for curator review rather than folded
#: silently into the corpus: PLAN.md's "never guess" rule applied to relevance, not only to strain.
#: Fusarium graminearum (8 RNA-Seq runs in the isobutanol SRA corpus, docs/reference/DATA_VOLUME.md
#: section 2) is very plausibly a false-positive hit on the word "isobutanol" (unverified: this
#: session's own domain judgement -- see data/omics/reference_genomes.yaml's
#: `fusarium_graminearum_ph1` entry), not a project decision that these runs belong in the
#: isobutanol program.
_RELEVANCE_UNCERTAIN_ORGANISM_PREFIXES: tuple[str, ...] = ("Fusarium graminearum",)


def is_relevance_uncertain(organism: str) -> bool:
    """True if `organism` (an SRA runinfo `ScientificName`) should set `sra_run.
    relevance_uncertain`.

    A prefix check, unlike `select_reference`'s exact match: flagging for review is a caution
    (worst case a curator looks at one extra, genuinely relevant run) rather than an identity
    claim, so it deliberately also catches a strain-suffixed variant such as "Fusarium graminearum
    PH-1".
    """
    name = organism.strip() if organism else ""
    return any(name.startswith(prefix) for prefix in _RELEVANCE_UNCERTAIN_ORGANISM_PREFIXES)


# ---------------------------------------------------------------------------------------------
# Generic organism reference fetch (item 5: "extend the reference fetch to handle the bacterial
# genomes"). `fetch_fasta`/`fetch_genbank`/`store_content_addressed` above are already generic and
# accession-agnostic -- this is the loop over them for an organism this module has no per-gene
# translation check for. Rows land in `reference_genome_asset` (schema.sql, "omics acquisition"),
# never in `reference_sequence`: that table's `kind` CHECK and `encoding_genome` foreign key are
# yeast-specific (nuclear/mitochondrial, NCBI genetic code tables 1/3) and would misrepresent a
# bacterial replicon, which reads under table 11 (data/omics/reference_genomes.yaml notes this per
# bacterial entry).
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchedReferenceAsset:
    accession: str
    kind: str  # 'genome' | 'annotation'
    stored: StoredFile
    source_url: str


def fetch_organism_reference(
    client: EutilsClient,
    genomes_dir: Path,
    accessions: Sequence[str],
    *,
    retrieved_at: str,
) -> list[FetchedReferenceAsset]:
    """Fetch and content-address FASTA + GenBank for each of `accessions`, generically.

    No translation-table verification is performed (unlike `fetch_mitochondrial_reference`): a
    bacterial genome's genetic code is uniform per replicon under NCBI table 11, not compartment-
    dependent the way yeast's is, so there is no table-1-vs-table-3 disagreement here to prove.
    `retrieved_at` is the caller's single wall-clock read, exactly as `fetch_nuclear_reference`
    takes it, so every asset from one call carries the same timestamp.
    """
    assets: list[FetchedReferenceAsset] = []
    for accession in accessions:
        fasta = fetch_fasta(client, accession)
        genbank = fetch_genbank(client, accession)
        assets.append(
            FetchedReferenceAsset(
                accession=accession,
                kind="genome",
                stored=store_content_addressed(genomes_dir, fasta.content),
                source_url=fasta.source_url,
            )
        )
        assets.append(
            FetchedReferenceAsset(
                accession=accession,
                kind="annotation",
                stored=store_content_addressed(genomes_dir, genbank.content),
                source_url=genbank.source_url,
            )
        )
    return assets


def reference_genome_asset_row(
    asset: FetchedReferenceAsset,
    *,
    reference_id: str,
    organism: str,
    retrieved_at: str,
) -> dict[str, object]:
    """One `asset` as a `reference_genome_asset` table row, ready for a parameterized INSERT."""
    slug = asset.accession.lower().replace(".", "-").replace("_", "-")
    return {
        "id": f"YAA:REFASSET:{reference_id}-{asset.kind}-{slug}",
        "reference_id": reference_id,
        "organism": organism,
        "sequence_accession": asset.accession,
        "kind": asset.kind,
        "file_path": str(asset.stored.path),
        "checksum_sha256": asset.stored.checksum_sha256,
        "size_bytes": asset.stored.size_bytes,
        "source_url": asset.source_url,
        "retrieved_at": retrieved_at,
        "zone": "R",
        "evidence": (
            f"NCBI Nucleotide accession {asset.accession}, fetched live via eutils efetch on "
            f"{retrieved_at}, catalogued in data/omics/reference_genomes.yaml as {reference_id!r}"
        ),
        "confidence": "high",
    }


_UPSERT_REFERENCE_GENOME_ASSET_SQL = """
INSERT INTO reference_genome_asset (id, reference_id, organism, sequence_accession, kind,
                                     file_path, checksum_sha256, size_bytes, source_url,
                                     retrieved_at, zone, evidence, confidence)
VALUES (:id, :reference_id, :organism, :sequence_accession, :kind, :file_path, :checksum_sha256,
        :size_bytes, :source_url, :retrieved_at, :zone, :evidence, :confidence)
ON CONFLICT(sequence_accession, kind) DO UPDATE SET
    file_path = excluded.file_path,
    checksum_sha256 = excluded.checksum_sha256,
    size_bytes = excluded.size_bytes,
    retrieved_at = excluded.retrieved_at,
    evidence = excluded.evidence
"""


def write_reference_genome_asset_rows(
    conn: sqlite3.Connection, rows: list[dict[str, object]]
) -> int:
    """Upsert `rows` into `reference_genome_asset`, keyed by `(sequence_accession, kind)`.

    Does not open or close `conn`; `fermdb.db.open_db` is the only function that does that.
    """
    for row in rows:
        conn.execute(_UPSERT_REFERENCE_GENOME_ASSET_SQL, row)
    conn.commit()
    return len(rows)


__all__ = [
    "ASSEMBLY_ACCESSION",
    "ASSEMBLY_NAME",
    "MITOCHONDRIAL_ACCESSION",
    "NUCLEAR_CHROMOSOME_ACCESSIONS",
    "REFERENCE_MATCH_QUALITIES",
    "FetchedReferenceAsset",
    "FetchedSequence",
    "ReferenceGenome",
    "ReferenceGenomesError",
    "ReferenceSelection",
    "ReferenceVerificationError",
    "StoredFile",
    "TranslationCheck",
    "fetch_fasta",
    "fetch_genbank",
    "fetch_mitochondrial_reference",
    "fetch_nuclear_reference",
    "fetch_organism_reference",
    "is_relevance_uncertain",
    "load_reference_genomes",
    "parse_fasta_sequence",
    "reference_genome_asset_row",
    "reference_genomes_path",
    "select_reference",
    "store_content_addressed",
    "verify_mitochondrial_translation",
    "write_reference_genome_asset_rows",
    "write_reference_rows",
]
