"""Compute each route's transcript support and write `pathway_route.score_evidence`.

    python ops/score_routes.py --apply

Routes are scored by step signature, not one at a time: 6,400 routes share a few hundred distinct
(role, part, compartment) tuples, and the transcript evidence depends only on the signature.
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
sys.path.insert(0, str(REPO / "ops"))

from run_contrasts import build_specs  # noqa: E402

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.metabolic.curated import load_parts  # noqa: E402
from fermdb.metabolic.transcript_support import (  # noqa: E402
    contrast_tables,
    describe,
    route_support,
    strain_constructs,
    write_scores,
)
from fermdb.omics.baseline import transcriptome_features  # noqa: E402
from fermdb.omics.evidence import (  # noqa: E402
    assertions_from_support,
    write_assertions,
)
from fermdb.omics.references_used import (  # noqa: E402
    CASSETTE_STUDIES,
    cassette_rows,
    matrix_for,
)


def contrast_strain_map(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """analysis_result id -> (reference strain id, treatment strain id) for genotype contrasts."""
    out: dict[str, tuple[str, str]] = {}
    for spec in build_specs(conn):
        if spec.axis != "genotype":
            continue

        def strain_of(sample_ids: tuple[str, ...]) -> str:
            row = conn.execute(
                "SELECT DISTINCT strain_id FROM sample WHERE id IN "
                f"({','.join('?' for _ in sample_ids)})",
                sample_ids,
            ).fetchone()
            return str(row[0]) if row and row[0] else ""

        slug = spec.id.rsplit(":", 1)[-1].lower()
        out[f"YAA:ANALYSIS:de-{slug}"] = (
            strain_of(spec.reference.sample_ids),
            strain_of(spec.treatment.sample_ids),
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--show", type=int, default=3, help="how many signatures to print")
    args = parser.parse_args()

    settings = Settings.load()
    db_path = Path(settings.db_file)
    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy(db_path, db_path.with_suffix(f".sqlite3.pre-evidence.{stamp}.bak"))
    conn = open_db(db_path, create=False)

    # The genes the quantification can actually see, by symbol.
    transcriptome = Path(settings.genomes_dir) / "s288c.transcripts.mito.fna.gz"
    features = transcriptome_features(transcriptome)
    symbols = {locus: gene for locus, (gene, _) in features.items() if gene}
    measurable = frozenset(symbols.values())
    print(f"{len(measurable)} gene symbols are measurable in {transcriptome.name}")

    parts = {
        f"YAA:PART:{p.id.replace('_', '-')}": (p.genes, p.source_organism)
        for p in load_parts(settings)
    }
    constructs = strain_constructs(conn)
    print(
        f"{len(constructs)} built strain(s) with a parsed construct: "
        + ", ".join(
            f"{c.name}({'/'.join(sorted(c.topology))},KARI={c.kari_cofactor()})"
            for c in constructs.values()
        )
    )
    # Every cassette row any pinned study contributes, so a step on a construct is scored
    # on the construct's own row rather than on the native locus it leaks into.
    cassette: dict[str, str] = {}
    for study in CASSETTE_STUDIES:
        cassette.update(cassette_rows(matrix_for(Path(settings.data_dir), study)))
    tables = contrast_tables(conn, symbols=symbols, cassette=cassette)
    print(f"cassette rows available as evidence: {', '.join(sorted(cassette)) or '-'}")
    strain_map = contrast_strain_map(conn)
    print(f"{len(tables)} stored contrast(s) readable; {len(strain_map)} genotype contrast(s)")

    # group routes by step signature
    signatures: dict[tuple[tuple[int, str, str, str], ...], list[str]] = defaultdict(list)
    for (route_id,) in conn.execute("SELECT id FROM pathway_route"):
        # encoding_genome is part of the signature, and leaving it out is not a performance
        # shortcut -- it is the compartment/encoding conflation the README calls the most
        # expensive modelling error available here. Two routes with identical parts in identical
        # compartments, one nuclear-encoded and one requiring mtDNA editing, are the same
        # signature without it, and the second silently inherits the first's evidence.
        steps = tuple(
            (int(a), str(b), str(c), str(d), str(e))
            for a, b, c, d, e in conn.execute(
                "SELECT step_order, step_role_id, part_id, compartment_id, encoding_genome "
                "FROM pathway_route_step WHERE route_id = ? ORDER BY step_order",
                (str(route_id),),
            )
        )
        signatures[steps].append(str(route_id))
    print(
        f"{sum(len(v) for v in signatures.values())} routes in "
        f"{len(signatures)} distinct step signatures"
    )

    supports = []
    by_signature = {}
    for steps, route_ids in signatures.items():
        representative = route_ids[0]
        support = route_support(
            conn,
            representative,
            parts=parts,
            constructs=constructs,
            contrasts=tables,
            contrast_strains=strain_map,
            measurable_genes=measurable,
        )
        by_signature[steps] = support
        for route_id in route_ids:
            supports.append(
                type(support)(
                    route_id=route_id,
                    strategy=support.strategy,
                    steps=support.steps,
                    matched_strains=support.matched_strains,
                    score=support.score,
                    caveats=support.caveats,
                )
            )

    scored = [s for s in supports if s.score is not None and s.score > 0]
    print(f"\n{len(scored)} of {len(supports)} routes have at least one transcript-backed step")
    distribution: dict[float, int] = defaultdict(int)
    for support in supports:
        distribution[round(support.score, 3) if support.score is not None else -1.0] += 1
    for score in sorted(distribution, reverse=True):
        label = "no catalytic steps" if score < 0 else f"{score:.2f}"
        print(f"  score_evidence {label:>18s}: {distribution[score]} route(s)")

    shown = sorted(
        by_signature.values(),
        key=lambda s: (-(s.score or 0), -s.elevated),
    )[: args.show]
    for support in shown:
        print()
        print(describe(support))

    if args.apply:
        written = write_scores(conn, supports)
        # The contrasts are only evidence once something can walk to them. PLAN.md J.5's gate
        # walks assertions, so an unattached analysis_result is a number the atlas cannot cite.
        claims = assertions_from_support(list(by_signature.values()), contrast_strains=strain_map)
        made, cited = write_assertions(conn, claims)
        conn.commit()
        print(f"\nwrote score_evidence on {written} route(s)")
        print(
            f"wrote {made} assertion(s) and {cited} correlative_omics evidence item(s) "
            f"from {len(claims)} evidenced step(s)"
        )
    else:
        print("\n(dry run; nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
