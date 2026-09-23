"""Enumerate every contrast the contextualised samples support, run it, and store it.

A contrast is formed only between two cells of the (condition_context x strain) grid that differ
in exactly one coordinate:

* same context, different strain  -> ``axis='genotype'``
* same strain, different context  -> the axis named by the facet that differs

Nothing else is emitted. The combination that differs in both coordinates is the confounded one,
and leaving it unexpressible is cheaper than leaving it available and warning about it.

    python ops/run_contrasts.py --apply --curator <name>
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.omics.contrasts import (  # noqa: E402
    ContrastGroup,
    ContrastSpec,
    refusals,
    run_contrast,
    store_contrast,
)
from fermdb.omics.references_used import matrix_for  # noqa: E402

#: Minimum biological units per side. Two is the floor at which a variance exists at all; the
#: result of a 2-vs-2 is reported with its power, not treated as equal to a 3-vs-3.
MIN_UNITS = 2


def _cells(conn: sqlite3.Connection) -> dict[tuple[str, str, str], list[str]]:
    """(study, context_id, strain_id) -> sample ids, for every contextualised sample."""
    cells: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for sample_id, context_id, strain_id, study in conn.execute(
        "SELECT s.id, s.condition_context_id, s.strain_id, r.study_accession "
        "FROM sample s JOIN sra_run r ON 'YAA:SAMPLE:' || r.run_accession = s.id "
        "WHERE s.condition_context_id IS NOT NULL AND s.strain_id IS NOT NULL"
    ):
        cells[(str(study), str(context_id), str(strain_id))].append(str(sample_id))
    return cells


def _pool_map(conn: sqlite3.Connection) -> dict[str, str]:
    """sample id -> BioSample accession, the biological unit two runs of one library share."""
    return {
        f"YAA:SAMPLE:{run}": str(biosample)
        for run, biosample in conn.execute(
            "SELECT run_accession, biosample FROM sra_run WHERE biosample IS NOT NULL "
            "AND biosample <> ''"
        )
    }


def _context_labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(cid): str(evidence).split(";")[0]
        for cid, evidence in conn.execute("SELECT id, evidence FROM condition_context")
    }


def _strain_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(sid): str(name) for sid, name in conn.execute("SELECT id, canonical_name FROM strain")
    }


def _axis_for(conn: sqlite3.Connection, left: str, right: str) -> str:
    """What differs between two contexts, named from the facets rather than from the label."""

    def facets(context_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for facet, value, state in conn.execute(
            "SELECT facet, value, value_state FROM condition_context_facet WHERE context_id = ?",
            (context_id,),
        ):
            out[str(facet)] = f"{value}/{state}"
        row = conn.execute(
            "SELECT time_h, medium_name FROM condition_context WHERE id = ?", (context_id,)
        ).fetchone()
        if row is not None:
            if row[0] is not None:
                out["time_h"] = str(row[0])
            if row[1] is not None:
                out["medium_name"] = str(row[1])
        return out

    a, b = facets(left), facets(right)
    differing = sorted(
        key for key in set(a) | set(b) if a.get(key) != b.get(key) and key != "sampling_basis"
    )
    if differing == ["time_h"]:
        return "time"
    if differing == ["stressor.compound"] or differing == [
        "stressor.compound",
        "stressor.concentration",
    ]:
        return "isobutanol_exposure"
    if not differing:
        return "unknown"
    return "+".join(differing)


def build_specs(conn: sqlite3.Connection) -> list[ContrastSpec]:
    cells = _cells(conn)
    pool = _pool_map(conn)
    labels = _context_labels(conn)
    names = _strain_names(conn)
    specs: list[ContrastSpec] = []

    def units(samples: list[str]) -> int:
        return len({pool.get(s, s) for s in samples})

    # same context, different strain -> genotype
    by_context: dict[tuple[str, str], list[tuple[str, list[str]]]] = defaultdict(list)
    for (study, context_id, strain_id), samples in cells.items():
        by_context[(study, context_id)].append((strain_id, samples))
    for (study, context_id), members in sorted(by_context.items()):
        members.sort()
        for i, (strain_a, samples_a) in enumerate(members):
            for strain_b, samples_b in members[i + 1 :]:
                if units(samples_a) < MIN_UNITS or units(samples_b) < MIN_UNITS:
                    continue
                slug = (
                    (
                        f"{study}-{names.get(strain_b, strain_b)}-vs-"
                        f"{names.get(strain_a, strain_a)}-{context_id[-8:]}"
                    )
                    .replace(":", "")
                    .replace(" ", "")
                )
                specs.append(
                    ContrastSpec(
                        id=f"YAA:CONTRAST:{slug}",
                        study_accession=study,
                        reference=ContrastGroup(
                            label=names.get(strain_a, strain_a),
                            sample_ids=tuple(sorted(samples_a)),
                            context_id=context_id,
                            basis=f"declared strain {names.get(strain_a, strain_a)}",
                        ),
                        treatment=ContrastGroup(
                            label=names.get(strain_b, strain_b),
                            sample_ids=tuple(sorted(samples_b)),
                            context_id=context_id,
                            basis=f"declared strain {names.get(strain_b, strain_b)}",
                        ),
                        axis="genotype",
                        description=(
                            f"{names.get(strain_b, strain_b)} vs {names.get(strain_a, strain_a)} "
                            f"under {labels.get(context_id, context_id)}"
                        ),
                        pool_by=pool,
                    )
                )

    # same strain, different context -> the facet that differs
    by_strain: dict[tuple[str, str], list[tuple[str, list[str]]]] = defaultdict(list)
    for (study, context_id, strain_id), samples in cells.items():
        by_strain[(study, strain_id)].append((context_id, samples))
    for (study, strain_id), members in sorted(by_strain.items()):
        members.sort()
        for i, (context_a, samples_a) in enumerate(members):
            for context_b, samples_b in members[i + 1 :]:
                if units(samples_a) < MIN_UNITS or units(samples_b) < MIN_UNITS:
                    continue
                axis = _axis_for(conn, context_a, context_b)
                slug = (
                    (
                        f"{study}-{names.get(strain_id, strain_id)}-{axis}-"
                        f"{context_a[-6:]}-{context_b[-6:]}"
                    )
                    .replace(":", "")
                    .replace(" ", "")
                )
                specs.append(
                    ContrastSpec(
                        id=f"YAA:CONTRAST:{slug}",
                        study_accession=study,
                        reference=ContrastGroup(
                            label=labels.get(context_a, context_a),
                            sample_ids=tuple(sorted(samples_a)),
                            context_id=context_a,
                            basis="declared conditions",
                        ),
                        treatment=ContrastGroup(
                            label=labels.get(context_b, context_b),
                            sample_ids=tuple(sorted(samples_b)),
                            context_id=context_b,
                            basis="declared conditions",
                        ),
                        axis=axis,
                        description=(
                            f"{names.get(strain_id, strain_id)}: "
                            f"{labels.get(context_b, context_b)} vs "
                            f"{labels.get(context_a, context_a)}"
                        ),
                        pool_by=pool,
                    )
                )
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--curator", default="claude-opus-5")
    parser.add_argument("--axis", default=None, help="only this axis")
    args = parser.parse_args()

    settings = Settings.load()
    db_path = Path(settings.db_file)
    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy(db_path, db_path.with_suffix(f".sqlite3.pre-contrasts.{stamp}.bak"))

    conn = open_db(db_path, create=False)
    data_dir = Path(settings.data_dir)
    contrasts_dir = Path(settings.data_dir) / "contrasts"

    specs = build_specs(conn)
    if args.axis:
        specs = [s for s in specs if s.axis == args.axis]
    print(f"{len(specs)} contrast(s) supported by the contextualised samples\n")

    stored = 0
    pruned = 0
    for spec in specs:
        problems = refusals(conn, spec)
        if problems:
            print(f"-- {spec.id}\n   REFUSED: {problems[0]}")
            # A contrast stored before its samples were quarantined would otherwise survive as a
            # readable `analysis_result` that nothing downstream knows to distrust -- the gate
            # would hold for new work and quietly fail for everything already computed. Removing
            # it is safe: the payload is Zone H and rebuilds from the matrix the moment the flag
            # is cleared.
            slug = spec.id.rsplit(":", 1)[-1].lower()
            analysis_id = f"YAA:ANALYSIS:de-{slug}"
            if conn.execute(
                "SELECT 1 FROM analysis_result WHERE id = ?", (analysis_id,)
            ).fetchone():
                if args.apply:
                    conn.execute("DELETE FROM analysis_result WHERE id = ?", (analysis_id,))
                    conn.execute(
                        "DELETE FROM processing_run WHERE id = ?", (f"YAA:PROCRUN:de-{slug}",)
                    )
                pruned += 1
                print("   pruned the stored result computed before the quarantine")
            continue
        matrix = matrix_for(data_dir, spec.study_accession)
        result = run_contrast(conn, spec, matrix_path=matrix)
        n_ref = len(spec.units(spec.reference))
        n_trt = len(spec.units(spec.treatment))
        significant = result.significant()
        print(
            f"-- {spec.description}\n"
            f"   axis={spec.axis}  n={n_ref} vs {n_trt}  tested={result.tested_genes}  "
            f"significant(FDR 5%)={len(significant)}"
        )
        for note in result.notes:
            print(f"   note: {note}")
        if args.apply:
            store_contrast(
                conn,
                result,
                contrasts_dir=contrasts_dir,
                matrix_path=matrix,
                data_dir=Path(settings.data_dir),
            )
            stored += 1

    if args.apply:
        conn.commit()
        print(f"\nstored {stored} contrast(s) into analysis_result")
    else:
        print("\n(dry run; nothing stored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
