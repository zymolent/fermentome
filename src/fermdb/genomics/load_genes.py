"""Write a whole RefSeq annotation into `gene` without stepping on the 36 rows already there.

The atlas holds 36 `gene` rows. Every one was resolved symbol by symbol by
`fermdb.omics.genes`, carries an `evidence` string naming the exact checksummed file it came from,
and anchors a `gene_group` that other tables point at -- `reaction_gene` resolves pathway symbols
through them, and PLAN.md J.5's traceability walk runs over them. They are real curated data with
a chain behind them. A RefSeq GFF3 for the same assembly contains all 36 of those genes again,
computes the same deterministic ids for them, and would happily overwrite every field.

**So this loader never overwrites. It only fills in blanks.**

That is the whole policy, and it is worth being precise about, because "upsert" normally means
the opposite:

* A gene id that is not in the table is **inserted** in full, Zone R, with the evidence string
  below.
* A gene id that IS in the table has each column considered separately. A column that is NULL is
  filled from the GFF3. A column that already holds a value is left exactly as it is -- including
  `evidence`, `confidence`, `gene_group_id`, `start_pos`, `end_pos` and `strand`.
* Where a stored value and the GFF3 disagree, the disagreement is **reported**, not resolved.
  CONVENTIONS.md, "Evidence": *conflicts are recorded in both directions and are never silently
  resolved.* :class:`GeneLoadReport` hands them back for a curator to look at.

The disagreement that will actually occur, and why picking a winner would be wrong: the 36 rows'
coordinates are the extent of the **mRNA** feature in RefSeq's `rna_from_genomic` FASTA, and this
loader reads the extent of the **gene** feature in the GFF3. For S288C those agree almost
everywhere and they are not guaranteed to. They are two different features of the same locus, so
neither is a correction of the other, and silently replacing a coordinate a J.5 evidence chain was
built on -- to a value whose `evidence` column would still name the FASTA -- is precisely the
quiet corruption this atlas is built to make impossible.

**`evidence` on a filled-in row gets a suffix, never a replacement.** A row that has gained a
`seqid` from a GFF3 while its `evidence` still names only a transcript FASTA is carrying an
unprovenanced fact, which is worse than either alternative. The curated sentence is kept whole and
the new clause is appended after it, naming the columns it accounts for. A row where nothing was
filled is not touched at all, which is what makes a second run a no-op.

**`gene_group` is insert-only.** `omics.genes.write_resolution` upserts groups with
`DO UPDATE SET` on every column; running that logic over 6,600 genes would rewrite the evidence
and confidence of all 36 curated anchors. Here it is `DO NOTHING`: a group that exists is a group
somebody already justified.

New groups are anchored exactly as the curated ones are -- `anchor_namespace='sgd_systematic'`,
`anchor_id` the systematic name, `membership_method='anchor'`, `scope='species'`, Zone H -- so a
gene nobody curated lands in the same identity space as one who was. That anchor is what makes
"a paper says ADH2, the atlas keys on YMR303C" work, and it only works if both loaders build it
the same way.

**Zone R, confidence high.** A gene model read out of a checksummed RefSeq GFF3 is exactly what
the source reported, and it was checked against a source -- the bytes, by digest. That is the same
argument `omics.genes` makes for the same rows, and it is not "high confidence from memory":
nothing here is recalled, inferred or modelled.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..omics.genes import ACCESSION_ENCODING_GENOME, gene_group_id, gene_id, sha256_of
from .gff3 import GeneRecord, iter_gene_records

__all__ = [
    "Disagreement",
    "GeneLoadError",
    "GeneLoadReport",
    "GffSource",
    "SkippedGene",
    "load_gene_records",
    "load_gff3",
]


class GeneLoadError(ValueError):
    """The load cannot proceed: a missing organism, or a file that is not what it claims."""


#: The columns this loader will fill on an existing row, in report order. `evidence` is handled
#: separately because it is appended to rather than set.
_FILLABLE: Final[tuple[str, ...]] = (
    "systematic_name",
    "standard_name",
    "gene_group_id",
    "seqid",
    "biotype",
    "locus_tag",
    "description",
    "start_pos",
    "end_pos",
    "strand",
)

#: The columns worth reporting a disagreement on. `description` is excluded on purpose: RefSeq
#: rewords a product between releases constantly and a report full of prose diffs would bury the
#: coordinate disagreements, which are the ones that change an answer.
_COMPARED: Final[tuple[str, ...]] = (
    "systematic_name",
    "standard_name",
    "seqid",
    "biotype",
    "start_pos",
    "end_pos",
    "strand",
)


@dataclass(frozen=True)
class GffSource:
    """The bytes a load is attributable to. Every row it writes names all three of these."""

    assembly_accession: str
    file_name: str
    sha256: str

    @property
    def evidence(self) -> str:
        """The clause every row this source writes carries, phrased like `omics.genes`'."""
        return (
            f"RefSeq GFF3 gene feature for assembly {self.assembly_accession}, "
            f"parsed from {self.file_name} (sha256 {self.sha256})"
        )


@dataclass(frozen=True)
class SkippedGene:
    """A gene the loader declined to write, and the reason, so a count can be reconciled."""

    gff_id: str
    locus_tag: str | None
    reason: str
    detail: str


@dataclass(frozen=True)
class Disagreement:
    """A stored value and a GFF3 value that differ. Recorded; neither one wins."""

    gene_id: str
    column: str
    stored: Any
    from_gff3: Any


@dataclass(frozen=True)
class GeneLoadReport:
    """What the load did, in enough detail to reconcile against the file it read.

    `by_seqid` and `by_biotype` are here for the dry run rather than for the write. A count of
    "6,600 inserted" is not something a person can check; "sixteen chromosomes plus NC_001224.1,
    and the mitochondrion has 30-odd genes rather than 6,000" is. They are the cheapest available
    check that the file is the genome it claims to be, and they cost one dict each.
    """

    inserted: int
    updated: int
    unchanged: int
    gene_groups_inserted: int
    gene_groups_left_alone: int
    skipped: tuple[SkippedGene, ...]
    disagreements: tuple[Disagreement, ...]
    #: Genes written or considered per sequence accession, in file order of first appearance.
    by_seqid: tuple[tuple[str, int], ...] = ()
    #: Genes per RefSeq `gene_biotype`, most common first. `None` becomes the key `'unrecorded'`,
    #: which is what RefSeq stating no biotype means -- not a biotype called "unknown".
    by_biotype: tuple[tuple[str, int], ...] = ()
    #: True when nothing was written. Every count above is what a real run *would* do.
    dry_run: bool = False

    @property
    def considered(self) -> int:
        """Every gene feature the parser handed over, however it was disposed of."""
        return self.inserted + self.updated + self.unchanged + len(self.skipped)

    def as_dict(self) -> dict[str, int]:
        return {
            "considered": self.considered,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": len(self.skipped),
            "gene_groups_inserted": self.gene_groups_inserted,
            "gene_groups_left_alone": self.gene_groups_left_alone,
            "disagreements": len(self.disagreements),
        }

    def skipped_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.skipped:
            counts[entry.reason] = counts.get(entry.reason, 0) + 1
        return counts

    def as_json(self) -> dict[str, Any]:
        """The whole report, including every skip and every disagreement.

        The human table truncates both lists; this does not. A skip nobody can see is a silently
        dropped gene, so the wire form is the one that has to be complete.
        """
        return {
            "dry_run": self.dry_run,
            "counts": self.as_dict(),
            "skipped_by_reason": self.skipped_by_reason(),
            "by_seqid": [{"seqid": name, "genes": count} for name, count in self.by_seqid],
            "by_biotype": [{"biotype": name, "genes": count} for name, count in self.by_biotype],
            "skipped": [
                {
                    "gff_id": entry.gff_id,
                    "locus_tag": entry.locus_tag,
                    "reason": entry.reason,
                    "detail": entry.detail,
                }
                for entry in self.skipped
            ],
            "disagreements": [
                {
                    "gene_id": entry.gene_id,
                    "column": entry.column,
                    "stored": entry.stored,
                    "from_gff3": entry.from_gff3,
                }
                for entry in self.disagreements
            ],
        }


_INSERT_GENE: Final[str] = """
INSERT INTO gene (id, organism_id, assembly_accession, systematic_name, standard_name,
                  gene_group_id, seqid, biotype, locus_tag, description,
                  start_pos, end_pos, strand, zone, evidence, confidence)
VALUES (:id, :organism_id, :assembly_accession, :systematic_name, :standard_name,
        :gene_group_id, :seqid, :biotype, :locus_tag, :description,
        :start_pos, :end_pos, :strand, :zone, :evidence, :confidence)
"""

#: Insert-only. A `gene_group` that exists was justified by whoever created it, and this loader
#: has nothing to add to that justification -- see the module docstring.
_INSERT_GENE_GROUP: Final[str] = """
INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope,
                        membership_method, zone, evidence, confidence)
VALUES (:id, :anchor_namespace, :anchor_id, :standard_name, :scope,
        :membership_method, :zone, :evidence, :confidence)
ON CONFLICT(id) DO NOTHING
"""


def _standard_name(record: GeneRecord) -> str | None:
    """The gene's standard name, or NULL where RefSeq recorded none.

    `gene=` first, because that is the attribute that means "standard name". `Name=` only when it
    differs from the locus tag: RefSeq sets `Name` to the locus tag for an unnamed ORF, and
    storing YAL069W as the "standard name" of YAL069W would invent a synonym that does not exist.
    Roughly 1,000 of S288C's genes are in that state, and NULL is the honest value for them.
    """
    if record.symbol:
        return record.symbol
    if record.name and record.name != record.locus_tag:
        return record.name
    return None


def _gene_evidence(
    record: GeneRecord,
    source: GffSource,
    encoding_genomes: Mapping[str, str],
) -> str:
    """The evidence sentence for a newly inserted gene, shaped like the 36 curated rows'.

    The encoding genome is stated only where the sequence accession is one this build knows,
    because it decides which NCBI translation table the gene is read under and a wrong one is
    worse than a missing one. `omics.genes` raises on an unknown accession; here it cannot --
    refusing a whole genome over one unplaced contig would be a worse failure than omitting a
    clause -- so the clause is dropped and the accession still appears verbatim.
    """
    genome = encoding_genomes.get(record.seqid)
    where = f"{record.seqid} ({genome}-encoded)" if genome else record.seqid
    xref = f"GeneID:{record.ncbi_gene_id}" if record.ncbi_gene_id else "no GeneID"
    return (
        f"[locus_tag={record.locus_tag}] [gene={record.symbol or 'none'}] "
        f"[gene_biotype={record.biotype or 'none'}] [db_xref={xref}] "
        f"[product={record.description or 'none'}] on {where}; {source.evidence}"
    )


def _desired(
    record: GeneRecord,
    source: GffSource,
    *,
    organism_id: str,
    encoding_genomes: Mapping[str, str],
    confidence: str,
) -> dict[str, Any]:
    locus_tag = record.locus_tag
    assert locus_tag is not None  # callers filter these out; see _skip_reason
    return {
        "id": gene_id(locus_tag, source.assembly_accession),
        "organism_id": organism_id,
        "assembly_accession": source.assembly_accession,
        # For S288C the systematic name IS the locus tag. They are kept as separate columns
        # because that identity is a property of this naming scheme, not of `gene`.
        "systematic_name": locus_tag,
        "standard_name": _standard_name(record),
        "gene_group_id": gene_group_id(locus_tag),
        "seqid": record.seqid,
        "biotype": record.biotype,
        "locus_tag": locus_tag,
        "description": record.description,
        "start_pos": record.start_pos,
        "end_pos": record.end_pos,
        "strand": record.strand,
        "zone": "R",
        "evidence": _gene_evidence(record, source, encoding_genomes),
        "confidence": confidence,
    }


def _group_row(
    record: GeneRecord,
    source: GffSource,
    *,
    anchor_namespace: str,
    confidence: str,
) -> dict[str, Any]:
    locus_tag = record.locus_tag
    assert locus_tag is not None
    return {
        "id": gene_group_id(locus_tag),
        "anchor_namespace": anchor_namespace,
        "anchor_id": locus_tag,
        "standard_name": _standard_name(record),
        "scope": "species",
        "membership_method": "anchor",
        # Zone H: constructed from the Zone R anchor by this code, rebuildable by re-running it.
        "zone": "H",
        "evidence": (
            f"anchored on the {anchor_namespace} name {locus_tag} of assembly "
            f"{source.assembly_accession}; {source.evidence}"
        ),
        "confidence": confidence,
    }


def _existing_genes(conn: sqlite3.Connection, assembly_accession: str) -> dict[str, dict[str, Any]]:
    """Every `gene` row for this assembly, keyed by id.

    Read up front, in one statement, rather than with a SELECT per gene: 6,600 round trips to
    decide 6,600 merges is the difference between a load that takes a second and one that takes a
    minute, and the whole table for one assembly is a few megabytes.
    """
    columns = ("id", "evidence", *_FILLABLE)
    query = f"SELECT {', '.join(columns)} FROM gene WHERE assembly_accession = ?"
    return {
        str(row[0]): dict(zip(columns, row, strict=True))
        for row in conn.execute(query, (assembly_accession,))
    }


def _merge(
    existing: dict[str, Any],
    desired: dict[str, Any],
    source: GffSource,
) -> tuple[dict[str, Any], list[str], list[tuple[str, Any, Any]]]:
    """Return `(updates, filled_columns, disagreements)` for one existing row.

    `updates` contains only columns that were NULL. Nothing else is ever produced, which is the
    guarantee the module docstring makes.
    """
    updates: dict[str, Any] = {}
    filled: list[str] = []
    conflicts: list[tuple[str, Any, Any]] = []
    for column in _FILLABLE:
        stored = existing[column]
        incoming = desired[column]
        if stored is None:
            if incoming is not None:
                updates[column] = incoming
                filled.append(column)
        elif column in _COMPARED and incoming is not None and stored != incoming:
            conflicts.append((column, stored, incoming))
    if filled:
        clause = f" + {', '.join(filled)} from {source.evidence}"
        if clause not in str(existing["evidence"]):
            updates["evidence"] = str(existing["evidence"]) + clause
    return updates, filled, conflicts


def _skip_reason(record: GeneRecord, seen: set[str]) -> tuple[str, str] | None:
    if not record.locus_tag:
        return (
            "no_locus_tag",
            "the gene id convention is YAA:GENE:<assembly>-<locus tag>; there is no locus tag to "
            "build one from, and Name= is a display label, not an identifier",
        )
    if record.locus_tag in seen:
        return (
            "duplicate_locus_tag",
            f"{record.locus_tag} already appeared in this file; two features sharing a locus tag "
            "would collide on one id and choosing between them would be a guess",
        )
    return None


def load_gene_records(
    conn: sqlite3.Connection,
    records: Iterable[GeneRecord],
    *,
    source: GffSource,
    organism_id: str,
    encoding_genomes: Mapping[str, str] = ACCESSION_ENCODING_GENOME,
    anchor_namespace: str = "sgd_systematic",
    confidence: str = "high",
    batch_size: int = 2000,
    dry_run: bool = False,
) -> GeneLoadReport:
    """Insert or fill in `gene` and `gene_group` rows from a stream of parsed gene records.

    Idempotent on `gene.id`, which is `YAA:GENE:<assembly-slug>-<locus-tag>` and depends on
    nothing but the file's own content. A second run over the same file finds every column
    already filled, writes nothing, and reports every gene as `unchanged`.

    Does not open or close `conn` -- `fermdb.db.open_db` is the only function that does that --
    and commits once at the end, so a failure part-way leaves the table as it was.

    **`dry_run=True` decides everything and writes nothing.** It is not a separate code path: the
    same loop, the same merge, the same conflict detection, with the writes and the transaction
    skipped. A dry run that used different logic from the real one would be worse than no dry run
    at all, because it would be believed. It also takes no write lock, so it can be pointed at an
    atlas another process is using.

    Args:
        conn: An open connection. Never the live atlas from inside a test.
        records: A stream from `gff3.iter_gene_records`, or any iterable of the same.
        source: The assembly, file name and digest every row written will name.
        organism_id: An existing `organism` row. Not created here: inventing an organism for a
            genome nobody registered would put an unevidenced row in a curated table.
        encoding_genomes: seqid -> 'nuclear' | 'mitochondrial', for the evidence sentence.
            Defaults to the S288C map that `omics.genes` verified against NCBI.
        anchor_namespace: The `gene_group.anchor_namespace` for groups created here.
        confidence: For rows this load inserts. Existing rows keep their own.
        batch_size: Rows per `executemany`. Bounds memory; does not affect the result.
        dry_run: Decide everything, write nothing. The counts are what a real run would do.
    """
    if conn.execute("SELECT 1 FROM organism WHERE id = ?", (organism_id,)).fetchone() is None:
        raise GeneLoadError(
            f"no organism row {organism_id!r}; create it first (fermdb.omics.genes.organism_row() "
            "builds the S288C one) rather than having a bulk gene load invent one"
        )

    existing = _existing_genes(conn, source.assembly_accession)
    inserts: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    skipped: list[SkippedGene] = []
    disagreements: list[Disagreement] = []
    seen: set[str] = set()
    inserted = updated = unchanged = 0
    by_seqid: dict[str, int] = {}
    by_biotype: dict[str, int] = {}

    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")
    try:
        group_ids_before = {str(row[0]) for row in conn.execute("SELECT id FROM gene_group")}
        groups_left_alone = 0
        groups_inserted = 0

        def flush() -> None:
            if dry_run:
                groups.clear()
                inserts.clear()
                updates.clear()
                return
            if groups:
                conn.executemany(_INSERT_GENE_GROUP, groups)
                groups.clear()
            if inserts:
                conn.executemany(_INSERT_GENE, inserts)
                inserts.clear()
            for gene_key, changes in updates:
                assignments = ", ".join(f"{column} = :{column}" for column in changes)
                conn.execute(
                    f"UPDATE gene SET {assignments} WHERE id = :gene_id",
                    {**changes, "gene_id": gene_key},
                )
            updates.clear()

        for record in records:
            reason = _skip_reason(record, seen)
            if reason is not None:
                skipped.append(
                    SkippedGene(
                        gff_id=record.gff_id,
                        locus_tag=record.locus_tag,
                        reason=reason[0],
                        detail=reason[1],
                    )
                )
                continue
            assert record.locus_tag is not None
            seen.add(record.locus_tag)
            by_seqid[record.seqid] = by_seqid.get(record.seqid, 0) + 1
            # RefSeq stating no biotype is 'never recorded', not a biotype named 'unknown'.
            biotype_key = record.biotype or "unrecorded"
            by_biotype[biotype_key] = by_biotype.get(biotype_key, 0) + 1

            desired = _desired(
                record,
                source,
                organism_id=organism_id,
                encoding_genomes=encoding_genomes,
                confidence=confidence,
            )
            group = _group_row(
                record, source, anchor_namespace=anchor_namespace, confidence=confidence
            )
            if group["id"] in group_ids_before:
                groups_left_alone += 1
            else:
                group_ids_before.add(str(group["id"]))
                groups.append(group)
                groups_inserted += 1

            prior = existing.get(str(desired["id"]))
            if prior is None:
                inserts.append(desired)
                inserted += 1
                # So a file that names the same gene twice under different locus tags cannot
                # insert it twice within one run.
                existing[str(desired["id"])] = {"evidence": desired["evidence"], **desired}
            else:
                changes, filled, conflicts = _merge(prior, desired, source)
                for column, stored, incoming in conflicts:
                    disagreements.append(
                        Disagreement(
                            gene_id=str(desired["id"]),
                            column=column,
                            stored=stored,
                            from_gff3=incoming,
                        )
                    )
                if changes:
                    updates.append((str(desired["id"]), changes))
                    prior.update(changes)
                    updated += 1
                else:
                    unchanged += 1

            if len(inserts) >= batch_size or len(updates) >= batch_size:
                flush()

        flush()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise
    if not dry_run:
        conn.commit()

    return GeneLoadReport(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        gene_groups_inserted=groups_inserted,
        gene_groups_left_alone=groups_left_alone,
        skipped=tuple(skipped),
        disagreements=tuple(disagreements),
        # First appearance order for sequences (a genome's own order, which is the useful one)
        # and most-common-first for biotypes (where the shape of the tail is the signal).
        by_seqid=tuple(by_seqid.items()),
        by_biotype=tuple(sorted(by_biotype.items(), key=lambda kv: (-kv[1], kv[0]))),
        dry_run=dry_run,
    )


def load_gff3(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    assembly_accession: str,
    organism_id: str,
    encoding_genomes: Mapping[str, str] = ACCESSION_ENCODING_GENOME,
    anchor_namespace: str = "sgd_systematic",
    confidence: str = "high",
    dry_run: bool = False,
) -> GeneLoadReport:
    """Digest the file, stream it, and load it. The one-call form for a CLI or a notebook.

    The digest is taken first and over the whole file, so the evidence string names bytes that
    were actually read rather than a path that may be replaced tomorrow. That happens on a dry
    run too: a dry run whose report names a different digest from the write that follows it is
    not a rehearsal of anything.
    """
    location = Path(path)
    source = GffSource(
        assembly_accession=assembly_accession,
        file_name=location.name,
        sha256=sha256_of(location),
    )
    return load_gene_records(
        conn,
        iter_gene_records(location),
        source=source,
        organism_id=organism_id,
        encoding_genomes=encoding_genomes,
        anchor_namespace=anchor_namespace,
        confidence=confidence,
        dry_run=dry_run,
    )
