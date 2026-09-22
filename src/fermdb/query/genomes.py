"""The Genomes read: reference sequences, and the compartments that decide how they are read.

This atlas is not a genome browser and this module is not pretending to be one. What it holds
about genomes is the part the isobutanol and mitochondrial programs actually turn on:

* **Which references are on disk**, with the accession and the checksum, so a coordinate can be
  traced to a file rather than to a memory of which assembly was used.
* **Which genetic code each compartment reads.** `compartment_encoding_genome` is a many-to-many
  for one reason: the mitochondrial matrix and inner membrane are read by *both* genomes, and a
  sequence filed against them is ambiguous until it says which. Table 1 reads `CUN` as leucine
  and `UGA` as stop; table 3 reads them as threonine and tryptophan. A gene moved between them
  without recoding does not misbehave subtly -- it truncates.
* **The mtDNA loci**, with whether displacing one leaves respiration intact and whether a
  nuclear allotopic rescue exists. Those two columns are the difference between a route that is
  merely difficult and a route that kills the cell.

So the payload is organised around the code table, not around coordinates. The dual-coded
compartments are flagged rather than left for a reader to notice, because not noticing is the
failure this whole layer exists to prevent.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fermdb.query.builder import Select
from fermdb.query.values import Absence, Value, Zone

__all__ = [
    "CompartmentRead",
    "EncodingGenomeRead",
    "GenomeOverview",
    "MtdnaLocusRead",
    "ReferenceRead",
    "read_overview",
]


def _text(raw: Any, *, zone: Zone | None = Zone.REPORTED) -> Value[str]:
    """A string column as a `Value`, with NULL read as "the source never recorded it"."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value.absent(Absence.NOT_RECORDED)
    return Value.known(str(raw), zone=zone)


@dataclass(frozen=True)
class ReferenceRead:
    """One reference sequence or assembly asset held on disk."""

    id: str
    kind: str
    organism: Value[str]
    accession: Value[str]
    encoding_genome: Value[str]
    size_bytes: int | None
    checksum: Value[str]
    #: Whether a translation round-trip was run against this sequence and passed. Only
    #: meaningful for the mitochondrial reference, where the code table is the whole risk.
    translation_verified: bool | None

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "organism": self.organism.as_json(),
            "accession": self.accession.as_json(),
            "encoding_genome": self.encoding_genome.as_json(),
            "size_bytes": self.size_bytes,
            "checksum": self.checksum.as_json(),
            "translation_verified": self.translation_verified,
        }


@dataclass(frozen=True)
class EncodingGenomeRead:
    """A genetic code table, with the ribosome that reads it and where it applies."""

    id: str
    genetic_code_table: int
    table_name: Value[str]
    ribosome: Value[str]
    compartments: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "genetic_code_table": self.genetic_code_table,
            "table_name": self.table_name.as_json(),
            "ribosome": self.ribosome.as_json(),
            "compartments": list(self.compartments),
        }


@dataclass(frozen=True)
class CompartmentRead:
    """A compartment and the genome(s) whose code applies inside it.

    ``is_dual_coded`` is computed, not stored, and it is the single most load-bearing flag in
    this module: a compartment read by two code tables cannot accept a sequence that does not
    declare which one it was written for.
    """

    id: str
    import_machinery: Value[str]
    encoding_genomes: tuple[str, ...]
    ph_estimate: Value[str]
    redox_estimate: Value[str]

    @property
    def is_dual_coded(self) -> bool:
        return len(self.encoding_genomes) > 1

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "import_machinery": self.import_machinery.as_json(),
            "encoding_genomes": list(self.encoding_genomes),
            "is_dual_coded": self.is_dual_coded,
            "ph_estimate": self.ph_estimate.as_json(),
            "redox_estimate": self.redox_estimate.as_json(),
        }
        if self.is_dual_coded:
            payload["warning"] = (
                "read by more than one genetic code -- a sequence filed here is ambiguous "
                "until it names the code it was written for"
            )
        return payload


@dataclass(frozen=True)
class MtdnaLocusRead:
    """One mitochondrial locus, with what displacing it costs.

    ``respiration_retained_if_used`` is the field that separates a usable insertion site from a
    lethal one, and ``rescue_available`` says whether the cost can be paid back from the nucleus.
    """

    id: str
    locus: str
    encodes: Value[str]
    activators: Value[str]
    rescue_available: Value[str]
    respiration_retained_if_used: bool | None
    displaced_if_used: Value[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "locus": self.locus,
            "encodes": self.encodes.as_json(),
            "activators": self.activators.as_json(),
            "rescue_available": self.rescue_available.as_json(),
            "respiration_retained_if_used": self.respiration_retained_if_used,
            "displaced_if_used": self.displaced_if_used.as_json(),
        }


@dataclass(frozen=True)
class GenomeOverview:
    """Everything the Genomes page shows, in one read."""

    references: tuple[ReferenceRead, ...]
    assets: tuple[ReferenceRead, ...]
    encoding_genomes: tuple[EncodingGenomeRead, ...]
    compartments: tuple[CompartmentRead, ...]
    mtdna_loci: tuple[MtdnaLocusRead, ...]
    organisms: tuple[dict[str, Any], ...]
    strains_by_class: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        return {
            "references": [r.as_json() for r in self.references],
            "assets": [a.as_json() for a in self.assets],
            "encoding_genomes": [e.as_json() for e in self.encoding_genomes],
            "compartments": [c.as_json() for c in self.compartments],
            "dual_coded_compartments": [c.id for c in self.compartments if c.is_dual_coded],
            "mtdna_loci": [m.as_json() for m in self.mtdna_loci],
            "organisms": list(self.organisms),
            "strains_by_class": self.strains_by_class,
        }


def _compartment_genomes(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """``{compartment_id: (encoding_genome, ...)}``, ordered so the rendering is stable."""
    mapping: dict[str, list[str]] = {}
    for row in (
        Select("compartment_encoding_genome")
        .columns("compartment_id", "encoding_genome")
        .order_by("compartment_id", "encoding_genome")
        .page(conn)
    ):
        mapping.setdefault(str(row["compartment_id"]), []).append(str(row["encoding_genome"]))
    return {key: tuple(value) for key, value in mapping.items()}


def read_overview(conn: sqlite3.Connection) -> GenomeOverview:
    """The Genomes page payload."""
    by_compartment = _compartment_genomes(conn)

    references = tuple(
        ReferenceRead(
            id=str(row["id"]),
            kind=str(row["kind"]),
            organism=_text(row["organism_id"]),
            accession=_text(row["sequence_accession"]),
            encoding_genome=_text(row["encoding_genome"]),
            size_bytes=row["size_bytes"],
            checksum=_text(row["checksum_sha256"]),
            translation_verified=(
                None if row["translation_verified"] is None else bool(row["translation_verified"])
            ),
        )
        for row in Select("reference_sequence")
        .columns(
            "id",
            "kind",
            "organism_id",
            "sequence_accession",
            "encoding_genome",
            "size_bytes",
            "checksum_sha256",
            "translation_verified",
        )
        .order_by("kind", "id")
        .page(conn)
    )

    assets = tuple(
        ReferenceRead(
            id=str(row["id"]),
            kind=str(row["kind"]),
            organism=_text(row["organism"]),
            accession=_text(row["sequence_accession"]),
            encoding_genome=Value.absent(Absence.NOT_APPLICABLE),
            size_bytes=row["size_bytes"],
            checksum=_text(row["checksum_sha256"]),
            translation_verified=None,
        )
        for row in Select("reference_genome_asset")
        .columns("id", "kind", "organism", "sequence_accession", "size_bytes", "checksum_sha256")
        .order_by("organism", "id")
        .page(conn)
    )

    applies_to: dict[str, list[str]] = {}
    for compartment, genomes in by_compartment.items():
        for genome in genomes:
            applies_to.setdefault(genome, []).append(compartment)

    encoding_genomes = tuple(
        EncodingGenomeRead(
            id=str(row["id"]),
            genetic_code_table=int(row["genetic_code_table"]),
            table_name=_text(row["table_name"]),
            ribosome=_text(row["ribosome"]),
            compartments=tuple(sorted(applies_to.get(str(row["id"]), ()))),
        )
        for row in Select("encoding_genome")
        .columns("id", "genetic_code_table", "table_name", "ribosome")
        .order_by("genetic_code_table")
        .page(conn)
    )

    compartments = tuple(
        CompartmentRead(
            id=str(row["id"]),
            import_machinery=_text(row["import_machinery"]),
            encoding_genomes=by_compartment.get(str(row["id"]), ()),
            ph_estimate=_text(row["ph_estimate"]),
            redox_estimate=_text(row["redox_estimate"]),
        )
        for row in Select("compartment")
        .columns("id", "import_machinery", "ph_estimate", "redox_estimate")
        .order_by("id")
        .page(conn)
    )

    mtdna_loci = tuple(
        MtdnaLocusRead(
            id=str(row["id"]),
            locus=str(row["locus"]),
            encodes=_text(row["encodes"]),
            activators=_text(row["activators"]),
            rescue_available=_text(row["rescue_available"]),
            respiration_retained_if_used=(
                None
                if row["respiration_retained_if_used"] is None
                else bool(row["respiration_retained_if_used"])
            ),
            displaced_if_used=_text(row["displaced_if_used"]),
        )
        for row in Select("mtdna_locus")
        .columns(
            "id",
            "locus",
            "encodes",
            "activators",
            "rescue_available",
            "respiration_retained_if_used",
            "displaced_if_used",
        )
        .order_by("locus")
        .page(conn)
    )

    organisms = tuple(
        {
            "id": str(row["id"]),
            "name": row["name"],
            "ncbi_taxid": row["ncbi_taxid"],
            "rank": row["rank"],
        }
        for row in Select("organism")
        .columns("id", "name", "ncbi_taxid", "rank")
        .order_by("name")
        .page(conn)
    )

    strains_by_class = {
        (str(row["k"]) if row["k"] is not None else "unclassified"): int(row["n"])
        for row in Select("strain")
        .columns("class AS k", "COUNT(*) AS n")
        .group_by("class")
        .page(conn)
    }

    return GenomeOverview(
        references=references,
        assets=assets,
        encoding_genomes=encoding_genomes,
        compartments=compartments,
        mtdna_loci=mtdna_loci,
        organisms=organisms,
        strains_by_class=strains_by_class,
    )
