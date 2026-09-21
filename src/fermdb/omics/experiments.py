"""`experiment` rows derived from what SRA already recorded, and the link that is refused.

`sample` holds 172 rows and `experiment` holds none, so no sample says which study it came from
and `measurement` has no study-level anchor to reach for. Two different facts are missing there,
and conflating them is how an atlas mis-attributes a paper:

1. **Which runs belong to one study.** SRA's submitter declared this when they deposited: a run
   belongs to exactly one SRA study (`SRP...`/`ERP...`), and `omics/load.py` already turned each
   of those studies into a `dataset` row and pointed every `sample` at one. Re-reading that
   grouping is not inference -- it is the submitter's own statement, already in the atlas, at the
   same Zone R grade as the `dataset` row it comes from. :func:`derive_experiments` reads it and
   nothing else.

2. **Which publication that study belongs to.** Nothing in this corpus records it, and this
   module refuses to supply it. See :data:`PUBLICATION_LINK_REFUSAL` for the two candidate
   routes and why neither is evidence. An `experiment` wrongly attached to a publication
   mis-attributes every sample under it, and, unlike a missing link, nothing downstream would
   ever notice.

So every row this module derives carries `publication_id IS NULL`, and the NULL is the finding,
not an omission waiting to be filled in by whoever next opens the file. The refusal travels in
`evidence`, in words, so that a curator who later attaches a publication is overruling a stated
reason rather than filling in a blank.

`objective` and `design_type` stay NULL for the same reason: SRA's runinfo records neither, and
"transcriptomics of an isobutanol-producing strain" would be a sentence this module made up.

**Writing is opt-in.** :func:`derive_experiments` reads; :func:`load_experiments` writes, and is
called by nothing in this module. The derivation is worth having on its own -- it is also the
report of how much of `experiment` is recoverable at all.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "PUBLICATION_LINK_REFUSAL",
    "RUNINFO_PUBMED_COLUMN",
    "DerivationReport",
    "DerivedExperiment",
    "PublicationLink",
    "derive_experiments",
    "experiment_id_for",
    "load_experiments",
    "runinfo_pubmed_values",
]

#: The runinfo column that looks like a publication link and is not one.
RUNINFO_PUBMED_COLUMN: Final[str] = "Study_Pubmed_id"

#: Why no derived `experiment` names a publication. Stored verbatim in `evidence` so the refusal
#: is readable from the row itself, and quoted in the report a curator reads before overriding it.
#:
#: Two routes were checked and both refused:
#:
#: * **SRA runinfo's `Study_Pubmed_id`.** In `data/omics/sra_isobutanol_runinfo.csv` this column
#:   holds `3` for five studies and is empty for the other ten. A single-digit value repeated
#:   across five unrelated deposits -- four `S. cerevisiae` studies and one `Lactococcus` one --
#:   is not identifying any of them; it is the legacy runinfo link-type code the column has
#:   always carried. Read as a PMID it would attach one arbitrary early record to 98 of this
#:   corpus's 172 runs, and nothing downstream would ever query it hard enough to notice.
#: * **The accession appearing in a stored full text.** Scanning all 1,429 stored full texts for
#:   every study and BioProject accession in the atlas returns exactly one hit, and a paper
#:   *mentioning* an accession is not the same claim as a paper *depositing* it -- a reanalysis
#:   cites the accession in the same words a deposit does. One hit is also not a mechanism.
#:
#: The route that would be evidence -- NCBI's own BioProject-to-publication link, via
#: `elink(dbfrom=bioproject, db=pubmed)` -- has not been harvested. Harvesting it is the work
#: that would make this column derivable; guessing it is not.
PUBLICATION_LINK_REFUSAL: Final[str] = (
    "publication_id refused: nothing recorded in this atlas links this SRA study to a paper. "
    f"SRA runinfo's {RUNINFO_PUBMED_COLUMN} is a legacy link-type code (it reads '3' for five "
    "unrelated studies in this corpus), not a PMID, and a full-text mention of an accession is a "
    "citation, not a deposit. NCBI elink(bioproject->pubmed) would be evidence and has not been "
    "harvested"
)

_ZONE: Final[str] = "R"
_CONFIDENCE: Final[str] = "high"


def experiment_id_for(dataset_id: str) -> str:
    """The experiment id for a dataset id, derived rather than generated.

    `YAA:DATASET:srp321884` gives `YAA:EXPERIMENT:srp321884`. Deriving it means re-running the
    derivation writes the same rows instead of a second set, and it means a reader can see which
    study an experiment is without a join.
    """
    tail = dataset_id.rsplit(":", 1)[-1]
    if not tail:
        raise ValueError(f"dataset id has no local part: {dataset_id!r}")
    return f"YAA:EXPERIMENT:{tail}"


@dataclass(frozen=True)
class PublicationLink:
    """Whether an experiment may name a publication, and on what evidence.

    `state` is never `'derived'` in this module today. It exists so that a caller which *does*
    have evidence (a harvested elink result, a curator's reading of a data-availability
    statement) has somewhere to put it that is distinguishable from this module's refusal.
    """

    state: str  # 'derived' | 'refused'
    publication_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.state not in {"derived", "refused"}:
            raise ValueError(f"publication link state must be derived or refused: {self.state!r}")
        if self.state == "refused" and self.publication_id is not None:
            raise ValueError("a refused publication link cannot also name a publication")
        if self.state == "derived" and not self.publication_id:
            raise ValueError("a derived publication link must name the publication it derived")


@dataclass(frozen=True)
class DerivedExperiment:
    """One `experiment` row that recorded metadata supports, with the samples it would cover."""

    id: str
    dataset_id: str
    accession: str | None
    bioproject: str | None
    sample_ids: tuple[str, ...]
    publication: PublicationLink
    evidence: str
    objective: str | None = None
    design_type: str | None = None
    zone: str = _ZONE
    confidence: str = _CONFIDENCE

    @property
    def sample_count(self) -> int:
        return len(self.sample_ids)

    def as_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "accession": self.accession,
            "bioproject": self.bioproject,
            "sample_count": self.sample_count,
            "publication_state": self.publication.state,
            "publication_id": self.publication.publication_id,
            "publication_reason": self.publication.reason,
            "objective": self.objective,
            "design_type": self.design_type,
            "zone": self.zone,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class DerivationReport:
    """What `experiment` can be populated with, and what it cannot."""

    experiments: tuple[DerivedExperiment, ...]
    orphan_sample_ids: tuple[str, ...]

    @property
    def samples_covered(self) -> int:
        return sum(e.sample_count for e in self.experiments)

    @property
    def with_publication(self) -> tuple[DerivedExperiment, ...]:
        return tuple(e for e in self.experiments if e.publication.state == "derived")

    @property
    def without_publication(self) -> tuple[DerivedExperiment, ...]:
        return tuple(e for e in self.experiments if e.publication.state == "refused")

    def summary(self) -> str:
        """One paragraph for a CLI, stating the refusal rather than only the count."""
        return (
            f"{len(self.experiments)} experiment row(s) derivable from recorded SRA study "
            f"grouping, covering {self.samples_covered} sample(s); "
            f"{len(self.orphan_sample_ids)} sample(s) have no dataset and get none. "
            f"{len(self.with_publication)} name a publication, "
            f"{len(self.without_publication)} refuse to."
        )


def _evidence_for(accession: str | None, bioproject: str | None, sample_count: int) -> str:
    named = accession or "an SRA study with no accession recorded"
    project = f" (BioProject {bioproject})" if bioproject else ""
    return (
        f"one experiment per SRA study: {named}{project} groups {sample_count} run(s), "
        "a grouping the submitter declared at deposit and already stored as this atlas's "
        f"`dataset` row. {PUBLICATION_LINK_REFUSAL}"
    )


def derive_experiments(conn: sqlite3.Connection) -> DerivationReport:
    """Every `experiment` row recorded metadata supports. Reads only; writes nothing.

    The grouping comes from `sample.dataset_id`, not from re-parsing the runinfo CSV: the CSV is
    where the grouping entered the atlas, but `dataset` is where it now lives, and a derivation
    that re-read the file could disagree with the rows every other query sees.

    A sample with no `dataset_id` gets no experiment and is reported instead. There is no such
    sample today, and there being none is worth asserting rather than assuming -- the alternative
    is an "unassigned" experiment that quietly becomes a bucket.
    """
    rows = conn.execute(
        "SELECT s.id AS sample_id, s.dataset_id AS dataset_id, d.accession AS accession, "
        "d.bioproject AS bioproject "
        "FROM sample s LEFT JOIN dataset d ON d.id = s.dataset_id "
        "ORDER BY s.dataset_id, s.id"
    ).fetchall()

    orphans: list[str] = []
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        dataset_id = row["dataset_id"]
        if not dataset_id:
            orphans.append(str(row["sample_id"]))
            continue
        grouped.setdefault(str(dataset_id), []).append(row)

    experiments: list[DerivedExperiment] = []
    for dataset_id, members in sorted(grouped.items()):
        accession = members[0]["accession"]
        bioproject = members[0]["bioproject"]
        sample_ids = tuple(str(m["sample_id"]) for m in members)
        experiments.append(
            DerivedExperiment(
                id=experiment_id_for(dataset_id),
                dataset_id=dataset_id,
                accession=str(accession) if accession else None,
                bioproject=str(bioproject) if bioproject else None,
                sample_ids=sample_ids,
                publication=PublicationLink(
                    state="refused", publication_id=None, reason=PUBLICATION_LINK_REFUSAL
                ),
                evidence=_evidence_for(
                    str(accession) if accession else None,
                    str(bioproject) if bioproject else None,
                    len(sample_ids),
                ),
            )
        )
    return DerivationReport(experiments=tuple(experiments), orphan_sample_ids=tuple(orphans))


def runinfo_pubmed_values(path: Path) -> Mapping[str, tuple[str, ...]]:
    """What `Study_Pubmed_id` actually holds, per SRA study, in a runinfo export.

    Exists so :data:`PUBLICATION_LINK_REFUSAL` is a checked statement rather than a remembered
    one: a test reads the committed corpus export through this function and asserts the column
    says `3` for several unrelated studies, which is the fact the refusal rests on.

    Never used to *derive* anything. The return type is per-study sets of strings precisely
    because the interesting property is that the values collide across studies.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or RUNINFO_PUBMED_COLUMN not in reader.fieldnames:
            raise ValueError(f"{path} has no {RUNINFO_PUBMED_COLUMN} column")
        seen: dict[str, set[str]] = {}
        for row in reader:
            study = (row.get("SRAStudy") or "").strip()
            if not study:
                continue
            seen.setdefault(study, set()).add((row.get(RUNINFO_PUBMED_COLUMN) or "").strip())
    return {study: tuple(sorted(values)) for study, values in sorted(seen.items())}


def load_experiments(
    conn: sqlite3.Connection, *, experiments: Sequence[DerivedExperiment] | None = None
) -> dict[str, int]:
    """Write the derived rows and point each sample at its experiment. Idempotent.

    Called by nothing else here. Deriving is the cheap, safe half and is what a report wants;
    writing is a decision a caller makes explicitly, once, against a database it names.

    `publication_id` is never written, and not because no derivation produced one -- the
    ``INSERT`` below has no column for it. A refusal that an accidental keyword argument could
    turn into a write is not a refusal.
    """
    derived = (
        tuple(experiments) if experiments is not None else derive_experiments(conn).experiments
    )
    for experiment in derived:
        if experiment.publication.state != "refused":
            raise ValueError(
                f"{experiment.id} claims a publication link; this writer has no column for one, "
                "so attaching a publication is a separate, evidenced step"
            )
        conn.execute(
            "INSERT INTO experiment (id, objective, design_type, zone, evidence, confidence) "
            "VALUES (?, NULL, NULL, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence",
            (experiment.id, experiment.zone, experiment.evidence, experiment.confidence),
        )
        conn.executemany(
            "UPDATE sample SET experiment_id = ? WHERE id = ?",
            [(experiment.id, sample_id) for sample_id in experiment.sample_ids],
        )
    conn.commit()
    return {
        "experiment": len(derived),
        "sample_linked": sum(e.sample_count for e in derived),
    }
