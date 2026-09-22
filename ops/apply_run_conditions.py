"""Materialise declared SRA metadata into strains, condition contexts and sample links.

Run against the live atlas after `docs/drafts/omics/*-run-attributes.tsv` has been refreshed:

    python ops/apply_run_conditions.py --apply --curator <name> --actor agent

Without ``--apply`` it reports what it would write and touches nothing. It takes a timestamped
backup before the first write, the same way `fermdb db migrate` does, because this is the first
tool that writes `condition_context` rows and an immutable table is a bad place to learn a lesson.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fermdb.config import Settings  # noqa: E402
from fermdb.curate.context_writer import write_contexts  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.omics.run_conditions import (  # noqa: E402
    context_writes,
    load_run_attributes,
    native_compartments,
    strain_declarations,
    write_strains,
)

#: The studies whose declared metadata supports a grouping at all, with the organism each is in.
#: A study is listed here only after a human-readable assessment of its attributes exists in
#: `docs/drafts/omics/2026-09-22-study-inventory.md`; the list is not "every study in the atlas".
STUDIES = {
    "SRP342112": "YAA:ORG:saccharomyces-cerevisiae-s288c",
    "ERP116462": "YAA:ORG:saccharomyces-cerevisiae-s288c",
    "SRP321884": "YAA:ORG:saccharomyces-cerevisiae-s288c",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attributes", default=None, help="the run-attributes TSV")
    parser.add_argument("--apply", action="store_true", help="write; otherwise report only")
    parser.add_argument("--curator", required=True)
    parser.add_argument("--actor", choices=("human", "agent"), default="agent")
    parser.add_argument("--study", action="append", default=None)
    parser.add_argument(
        "--reason",
        default=(
            "materialising submitter-declared SRA SAMPLE_ATTRIBUTES so PLAN.md F.3's "
            "condition-context gate can be satisfied for the studies that declare their design"
        ),
    )
    args = parser.parse_args()

    settings = Settings.load()
    attributes = (
        Path(args.attributes)
        if args.attributes
        else REPO / "docs" / "drafts" / "omics" / "2026-09-22-run-attributes.tsv"
    )
    runs = load_run_attributes(attributes)
    print(f"{len(runs)} runs read from {attributes.name}")

    studies = args.study or list(STUDIES)
    db_path = Path(settings.db_file)

    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = db_path.with_suffix(f".sqlite3.pre-conditions.{stamp}.bak")
        shutil.copy(db_path, backup)
        print(f"backup: {backup.name}")

    conn = open_db(db_path, create=False)
    conn.execute("PRAGMA foreign_keys = ON")
    native = native_compartments(conn)
    print(f"native compartments known for {len(native)} genes from the curated reactions")

    total_strains = total_linked = total_contexts = total_samples = 0

    for study in studies:
        organism = STUDIES.get(study)
        if organism is None:
            print(f"!! {study} is not in STUDIES; skipping")
            continue
        members = [r for r in runs if r.study_accession == study]
        if not members:
            print(f"!! {study}: no runs in the attributes file")
            continue

        print(f"\n=== {study} ({len(members)} runs)")
        declarations = strain_declarations(members, organism_id=organism, native=native)
        for declaration in declarations:
            print(
                f"  strain {declaration.canonical_name:8s} n={len(declaration.run_accessions):2d}"
                f"  {declaration.construct.compartment_summary()}"
            )
        writes = context_writes(members, study_accession=study)
        for write in writes:
            print(f"  context {write.label:44s} n={len(write.sample_ids)}")

        if not args.apply:
            continue

        written, linked, notes = write_strains(
            conn, declarations, curator=args.curator, actor_kind=args.actor
        )
        for note in notes:
            print(f"    note: {note}")
        report = write_contexts(
            conn,
            writes,
            vocabularies_dir=Path(settings.vocabularies_dir),
            approved_by=args.curator,
            approver_kind=args.actor,
            reason=args.reason,
        )
        if not report.ok:
            print("    REFUSED, nothing written for this study:")
            for refusal in report.refusals:
                print(f"      - {refusal}")
            continue
        print(
            f"    wrote {written} strain(s), linked {linked} sample(s) to a strain; "
            f"wrote {len(report.written)} context(s), reused {len(report.reused)}, "
            f"linked {report.samples_linked} sample(s) to a context"
        )
        total_strains += written
        total_linked += linked
        total_contexts += len(report.written)
        total_samples += report.samples_linked

    if args.apply:
        conn.commit()
        print(
            f"\ncommitted: {total_strains} strains, {total_linked} strain links, "
            f"{total_contexts} contexts, {total_samples} context links"
        )
        for table in ("condition_context", "condition_context_facet"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count}")
        contextualised = conn.execute(
            "SELECT COUNT(*) FROM sample WHERE condition_context_id IS NOT NULL"
        ).fetchone()[0]
        print(f"  samples with a context: {contextualised} of 172")
    else:
        print("\n(dry run; nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
