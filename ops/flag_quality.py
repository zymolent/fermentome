"""Run the data-quality detectors over every contextualised study and record what they find.

    python ops/flag_quality.py --apply --curator <you>

Without ``--apply`` it reports and writes nothing. Flags a person has already confirmed or
cleared are left alone; see `omics.quality.write_flags`.
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
from fermdb.db import open_db  # noqa: E402
from fermdb.metabolic.transcript_support import strain_constructs  # noqa: E402
from fermdb.omics.baseline import transcriptome_features  # noqa: E402
from fermdb.omics.quality import (  # noqa: E402
    coherence_flags,
    marker_flags,
    redundancy_flags,
    write_flags,
)
from fermdb.omics.references_used import (  # noqa: E402
    cassette_rows,
    matrix_for,
    reference_includes_constructs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--curator", default="claude-opus-5")
    parser.add_argument("--actor", choices=("human", "agent"), default="agent")
    args = parser.parse_args()

    settings = Settings.load()
    db_path = Path(settings.db_file)
    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy(db_path, db_path.with_suffix(f".sqlite3.pre-flags.{stamp}.bak"))
    conn = open_db(db_path, create=False)

    data_dir = Path(settings.data_dir)
    features = transcriptome_features(Path(settings.genomes_dir) / "s288c.transcripts.mito.fna.gz")
    symbols = {locus: gene for locus, (gene, _) in features.items() if gene}

    # Genes any build carries on its own cassette cannot serve as markers against a native-only
    # reference: their rows mix native expression with construct spillover.
    constructs = strain_constructs(conn)
    confounded = frozenset(g for c in constructs.values() for g in c.localization)
    print(f"marker genes excluded as construct-confounded: {', '.join(sorted(confounded)) or '-'}")

    studies = [
        str(s)
        for (s,) in conn.execute(
            "SELECT DISTINCT r.study_accession FROM sra_run r "
            "JOIN sample s ON s.id = 'YAA:SAMPLE:' || r.run_accession "
            "WHERE s.condition_context_id IS NOT NULL ORDER BY r.study_accession"
        )
    ]
    print(f"{len(studies)} contextualised study(ies): {', '.join(studies)}\n")

    everything = []
    for study in studies:
        gate_a = coherence_flags(
            conn,
            matrix_path=matrix_for(data_dir, study),
            study_accession=study,
            raised_by=args.curator,
            actor_kind=args.actor,
        )
        # Where the index carries the constructs, the cassette row is the marker: it is not
        # shared with the native locus, and it separates a build from a parent by four orders of
        # magnitude. Those genes stop being confounded the moment that row exists.
        study_matrix = matrix_for(data_dir, study)
        augmented = reference_includes_constructs(data_dir, study)
        study_symbols = dict(symbols)
        study_confounded = confounded
        if augmented:
            for symbol, row in cassette_rows(study_matrix).items():
                study_symbols[row] = symbol
            study_confounded = frozenset()
        gate_b = marker_flags(
            conn,
            matrix_path=study_matrix,
            study_accession=study,
            raised_by=args.curator,
            symbols=study_symbols,
            confounded_genes=study_confounded,
            actor_kind=args.actor,
        )
        print(f"=== {study}: gate A raised {len(gate_a)}, gate B raised {len(gate_b)}")
        for flag in gate_a + gate_b:
            print(f"  {flag.severity:10s} {flag.target_id:24s} {flag.detector.split(':')[-1]}")
            print(f"             {flag.rationale[:150]}")
        everything.extend(gate_a + gate_b)

    redundant = redundancy_flags(conn, raised_by=args.curator, actor_kind=args.actor)
    by_sample = len({f.resembles for f in redundant})
    print(
        f"\n=== corpus-wide: {len(redundant)} run(s) across {by_sample} BioSample(s) are "
        "technical replicates of one another (warn, never excluded)"
    )
    everything.extend(redundant)

    if args.apply:
        written, respected = write_flags(
            conn, everything, raised_by=args.curator, actor_kind=args.actor
        )
        conn.commit()
        print(f"\nwrote {written} flag(s); {respected} left alone because already decided")
        total = conn.execute(
            "SELECT COUNT(*) FROM data_quality_flag WHERE status = 'active'"
        ).fetchone()[0]
        print(f"active flags in the atlas: {total}")
    else:
        print(f"\n(dry run; {len(everything)} flag(s) would be written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
