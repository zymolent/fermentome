"""The Tn-Seq fitness screens: what they are, where they are, and the unit they still need.

PLAN.md phase 4 requires that *every Tn-Seq screen is represented as perturbation evidence rather
than folded in with expression*, and calls the screens "per-run the most informative data in the
set" because a fitness screen is a perturbation (L1/L2 under J.3) and differential expression is
a correlation (L3). `docs/reference/DATA_VOLUME.md` section 2 adds the correction that earlier
work got wrong: **the Tn-Seq runs are *Zymomonas mobilis* ZM4, not yeast.** Reading them requires
the *Z. mobilis* genome and annotation; reading them as yeast would be wrong twice over.

The clause has two halves, and they are in different states.

**Not folded in with expression -- holds, and this module makes it checkable.** No Tn-Seq run is
in `data/omics/quant_plan.json` and none is a column of any expression matrix. That is currently
true by construction rather than by rule (`references.select_reference` sends a *Z. mobilis* run
to its own genome, and no *Z. mobilis* matrix was ever built), which is exactly the kind of
accident that quietly stops being true. :func:`build_report` turns it into a stated invariant:
:attr:`ScreenReport.folded_into_expression` names any Tn-Seq run that has reached the expression
layer, and a test asserts it is empty against the real corpus.

**Represented as perturbation evidence -- does not hold, and cannot be made to hold here.** See
:data:`SCREEN_UNIT_REFUSAL`. A Tn-Seq screen is a genome-wide result: one library, one selection,
and a fitness statistic for every gene it has insertions in. The `evidence_item` table has no unit
that fits it, and the three types whose *shape* is close are each wrong for a different reason.
Writing one anyway would be manufacturing entities -- a `strain` row per disrupted gene and a
`measurement` row per gene, neither of which anybody made or measured. This module therefore
reports the gap in the same voice `experiments.py` reports its missing publication link: the
refusal is the finding, carried in words, so that whoever closes it is overruling a stated reason.

What is fixable from inside this package, and is fixed: `load.py` used to write
`priority_rank = 0` for every loaded run, which silently discarded the one mechanism the codebase
already had for marking a Tn-Seq run as different from an expression run
(`sra.priority_rank_for`). It now calls that function, and :func:`build_report` reports the rank
each screen's runs actually carry.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..config import Settings
from .sra import priority_rank_for

__all__ = [
    "PERTURBATION_CANDIDATE_STRATEGIES",
    "SCREEN_UNIT_REFUSAL",
    "TN_SEQ_STRATEGY",
    "Screen",
    "ScreenReport",
    "ScreenRun",
    "build_report",
    "expression_layer_runs",
    "screens",
]

#: SRA's own library-strategy string. The corpus's only genome-wide perturbation data type.
TN_SEQ_STRATEGY: Final[str] = "Tn-Seq"

#: Strategies that may hide a perturbation screen behind SRA's catch-all label. A run here is
#: neither prioritised as a screen nor quantified as expression -- it is in no layer at all, which
#: is a curation question rather than a state to leave unreported.
PERTURBATION_CANDIDATE_STRATEGIES: Final[frozenset[str]] = frozenset({"OTHER"})

#: Why no Tn-Seq screen is written as `evidence_item` today. Quoted verbatim in the report a
#: curator reads before deciding, because the decision is theirs and the reason has to travel
#: with it.
#:
#: The unit a screen wants is **one evidence item per gene per screen**: gene *g* disrupted, in
#: library *L*, under selection *s* against control *c*, with fitness statistic *w* and its
#: adjusted p-value. That is a perturbation -- the gene was broken and a phenotype measured --
#: and it is the reason PLAN.md grades a screen L1/L2 rather than L3. The schema cannot express
#: it:
#:
#: * **`direct_perturbation`** requires `strain_id`, a `control_strain_id` or
#:   `control_condition_id`, and a `measurement_id`. A pooled transposon library is one population,
#:   not one `strain` row per disrupted gene, and a per-gene fitness score is a statistic over read
#:   counts, not a `measurement` anybody took of a `sample`. Satisfying the constraint would mean
#:   inventing roughly 1,800 strain rows and 1,800 measurement rows for *Z. mobilis* ZM4 -- rows
#:   that would be indistinguishable, downstream, from ones a curator read out of a paper.
#: * **`correlative_omics`** fits the shape exactly (`analysis_result_id`, `effect_size`,
#:   `p_adjusted`) and is the wrong type: it is the differential-expression slot, so using it is
#:   *literally* the folding-in that this clause forbids, and it would cap a screen at L3.
#: * **`comparative_genomic`** also fits the shape (`variant_or_gene_set`, `strain_set`,
#:   `statistic`) and is wrong for the same reason in a different dress: it means an association
#:   observed across strains nobody perturbed. A screen is not an association.
#:
#: Closing this needs a schema decision -- either a new `evidence_type` (say
#: `pooled_perturbation_screen`, requiring the screen's `analysis_result_id`, the gene set, the
#: selection and control condition contexts, the fitness statistic and its adjusted p-value), or
#: widening `direct_perturbation` to accept a disruption plus a screen statistic where it now
#: demands a strain plus a measurement. Both are edits to `src/fermdb/db/schema.sql` plus a
#: migration, and both are the project owner's call rather than this package's.
SCREEN_UNIT_REFUSAL: Final[str] = (
    "no evidence_item is written for a Tn-Seq screen: the right unit is one item per gene per "
    "screen (gene disrupted, library, selection vs control, fitness statistic, adjusted p), and "
    "no evidence_type can carry it. direct_perturbation demands a strain row and a measurement "
    "row per gene, which a pooled library does not have; correlative_omics is the "
    "differential-expression slot and using it would be the folding-in phase 4 forbids, capping "
    "the screen at L3; comparative_genomic means association across unperturbed strains. Closing "
    "this needs a new evidence_type (or a widened direct_perturbation) in "
    "src/fermdb/db/schema.sql plus a migration -- a schema decision, not a load"
)


@dataclass(frozen=True)
class ScreenRun:
    """One sequencing run belonging to a screen, with everything that decides how it is read."""

    run_accession: str
    study_accession: str | None
    bioproject: str | None
    organism: str | None
    library_strategy: str | None
    reference_assembly: str | None
    reference_match_quality: str | None
    bases: int | None
    size_mb: float | None
    acquisition_status: str
    priority_rank: int

    @property
    def expected_priority_rank(self) -> int:
        """What `sra.priority_rank_for` says this run's rank should be.

        Compared against the stored rank rather than assumed equal to it: the two disagreed for
        every row in the corpus until `load.py` was fixed, and nothing noticed.
        """
        return priority_rank_for(self.library_strategy or "")


@dataclass(frozen=True)
class Screen:
    """One screen: an SRA study's worth of Tn-Seq runs against one reference."""

    study_accession: str
    bioproject: str | None
    organism: str | None
    reference_assembly: str | None
    runs: tuple[ScreenRun, ...]
    #: `evidence_item` rows citing this screen. Zero for every screen today; see
    #: :data:`SCREEN_UNIT_REFUSAL`.
    evidence_items: int = 0

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def total_bases(self) -> int:
        return sum(run.bases or 0 for run in self.runs)

    @property
    def misranked_runs(self) -> tuple[str, ...]:
        """Runs whose stored `priority_rank` is not the one the rule computes."""
        return tuple(
            run.run_accession
            for run in self.runs
            if run.priority_rank != run.expected_priority_rank
        )

    @property
    def represented_as_perturbation_evidence(self) -> bool:
        return self.evidence_items > 0


@dataclass(frozen=True)
class ScreenReport:
    """How the corpus's screens are represented, and where that falls short of the clause."""

    screens: tuple[Screen, ...]
    #: Tn-Seq runs that have reached the expression layer -- a quant plan entry or a matrix
    #: column. Empty is the required state; a non-empty tuple is the clause being violated.
    folded_into_expression: tuple[str, ...]
    #: Runs under a catch-all strategy in an organism that also has screens: in neither layer,
    #: and unclassified rather than decided.
    unclassified_candidates: tuple[ScreenRun, ...]
    refusal: str = SCREEN_UNIT_REFUSAL

    @property
    def screen_count(self) -> int:
        return len(self.screens)

    @property
    def run_count(self) -> int:
        return sum(screen.run_count for screen in self.screens)

    @property
    def screens_with_evidence(self) -> tuple[Screen, ...]:
        return tuple(s for s in self.screens if s.represented_as_perturbation_evidence)

    @property
    def clause_not_folded_in_holds(self) -> bool:
        """Half the clause: no screen is folded in with expression."""
        return not self.folded_into_expression

    @property
    def clause_represented_as_evidence_holds(self) -> bool:
        """The other half: every screen carries perturbation evidence. False, and stated so."""
        return bool(self.screens) and len(self.screens_with_evidence) == self.screen_count

    def summary(self) -> str:
        """One paragraph for a CLI: both halves of the clause, then the refusal."""
        folded = (
            "none folded in with expression"
            if self.clause_not_folded_in_holds
            else f"FOLDED IN WITH EXPRESSION: {', '.join(self.folded_into_expression)}"
        )
        return (
            f"{self.screen_count} Tn-Seq screen(s), {self.run_count} run(s); {folded}. "
            f"{len(self.screens_with_evidence)} of {self.screen_count} represented as "
            f"perturbation evidence. "
            f"{len(self.unclassified_candidates)} run(s) in neither layer."
        )


def expression_layer_runs(settings: Settings, *, references: Iterable[str] = ()) -> frozenset[str]:
    """Every run the expression layer has taken in: quant plan entries plus matrix columns.

    Both sources, not either: the quant plan is the intent and the matrix header is the result,
    and a run can appear in one without the other. The union is what "folded in with expression"
    has to mean if the check is to be worth running.
    """
    found: set[str] = set()
    plan = Path(settings.repo_root) / "data" / "omics" / "quant_plan.json"
    if plan.is_file():
        payload = json.loads(plan.read_text(encoding="utf-8"))
        found.update(str(entry["run"]) for entry in payload if "run" in entry)

    matrices = Path(settings.matrices_dir)
    if matrices.is_dir():
        names = (
            [f"{reference}.tpm.tsv.gz" for reference in references]
            if references
            else [path.name for path in sorted(matrices.iterdir()) if path.name.endswith(".tsv.gz")]
        )
        for name in names:
            path = matrices / name
            if not path.is_file():
                continue
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                found.update(handle.readline().rstrip("\n").split("\t")[1:])
    return frozenset(found)


def _run(row: Mapping[str, object]) -> ScreenRun:
    def text(key: str) -> str | None:
        value = row[key]
        return None if value is None else str(value)

    def integer(key: str) -> int | None:
        value = row[key]
        return None if value is None else int(str(value))

    def number(key: str) -> float | None:
        value = row[key]
        return None if value is None else float(str(value))

    return ScreenRun(
        run_accession=str(row["run_accession"]),
        study_accession=text("study_accession"),
        bioproject=text("bioproject"),
        organism=text("organism"),
        library_strategy=text("library_strategy"),
        reference_assembly=text("reference_assembly"),
        reference_match_quality=text("reference_match_quality"),
        bases=integer("bases"),
        size_mb=number("size_mb"),
        acquisition_status=str(row["acquisition_status"]),
        priority_rank=int(str(row["priority_rank"])),
    )


_RUN_COLUMNS: Final[str] = (
    "run_accession, study_accession, bioproject, organism, library_strategy, "
    "reference_assembly, reference_match_quality, bases, size_mb, acquisition_status, "
    "priority_rank"
)


def screens(conn: sqlite3.Connection) -> tuple[Screen, ...]:
    """Every Tn-Seq screen in the atlas, one per SRA study, with its runs. Reads only.

    Grouped by study because that is the unit a screen is published and deposited as: one library
    challenged under one design. Grouping by run would count eight replicates as eight screens,
    and grouping by organism would merge two unrelated deposits into one.
    """
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM sra_run WHERE library_strategy = ? "
        "ORDER BY study_accession, run_accession",
        (TN_SEQ_STRATEGY,),
    ).fetchall()

    grouped: dict[str, list[ScreenRun]] = {}
    for row in rows:
        run = _run(row)
        grouped.setdefault(run.study_accession or "(no study accession)", []).append(run)

    result: list[Screen] = []
    for study, members in sorted(grouped.items()):
        first = members[0]
        result.append(
            Screen(
                study_accession=study,
                bioproject=first.bioproject,
                organism=first.organism,
                reference_assembly=first.reference_assembly,
                runs=tuple(members),
                evidence_items=_evidence_items_for(conn, study),
            )
        )
    return tuple(result)


def _evidence_items_for(conn: sqlite3.Connection, study_accession: str) -> int:
    """`evidence_item` rows naming this screen anywhere a screen could be named.

    Deliberately a broad text match over `evidence` and the two id columns a screen result could
    plausibly hang from, rather than a join: there is no column that *means* "this screen", which
    is the whole finding. A broad search that returns zero is a stronger statement than a narrow
    one that returns zero because it looked in the wrong place.
    """
    pattern = f"%{study_accession}%"
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM evidence_item "
            "WHERE status = 'active' AND (evidence LIKE ? OR contrast_id LIKE ? "
            "OR analysis_result_id LIKE ?)",
            (pattern, pattern, pattern),
        ).fetchone()[0]
    )


def _unclassified(conn: sqlite3.Connection, organisms: frozenset[str]) -> tuple[ScreenRun, ...]:
    if not organisms:
        return ()
    placeholders = ",".join("?" for _ in organisms)
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM sra_run WHERE organism IN ({placeholders}) "
        f"AND library_strategy <> ? ORDER BY run_accession",
        (*sorted(organisms), TN_SEQ_STRATEGY),
    ).fetchall()
    return tuple(
        run
        for run in (_run(row) for row in rows)
        if (run.library_strategy or "") in PERTURBATION_CANDIDATE_STRATEGIES
    )


def build_report(conn: sqlite3.Connection, settings: Settings) -> ScreenReport:
    """How the screens are represented today, with the half of the clause that holds checked."""
    found = screens(conn)
    expression = expression_layer_runs(settings)
    folded = tuple(
        sorted(
            run.run_accession
            for screen in found
            for run in screen.runs
            if run.run_accession in expression
        )
    )
    organisms = frozenset(screen.organism for screen in found if screen.organism)
    return ScreenReport(
        screens=found,
        folded_into_expression=folded,
        unclassified_candidates=_unclassified(conn, organisms),
    )
