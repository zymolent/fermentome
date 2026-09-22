"""Produce the assembled answer. `python ops/answer.py [--verbose] [--out FILE]`"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "ops"))

from score_routes import contrast_strain_map  # noqa: E402

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.metabolic.curated import load_parts  # noqa: E402
from fermdb.metabolic.transcript_support import (  # noqa: E402
    RouteSupport,
    contrast_tables,
    route_support,
    strain_constructs,
)
from fermdb.omics.baseline import transcriptome_features  # noqa: E402
from fermdb.omics.references_used import (  # noqa: E402
    CASSETTE_STUDIES,
    cassette_rows,
    matrix_for,
)
from fermdb.query.answer import assemble, render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every step's verdict")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    settings = Settings.load()
    conn = open_db(Path(settings.db_file), create=False)

    features = transcriptome_features(Path(settings.genomes_dir) / "s288c.transcripts.mito.fna.gz")
    symbols = {locus: gene for locus, (gene, _) in features.items() if gene}
    measurable = frozenset(symbols.values())
    parts = {
        f"YAA:PART:{p.id.replace('_', '-')}": (p.genes, p.source_organism)
        for p in load_parts(settings)
    }
    constructs = strain_constructs(conn)
    # Every cassette row any pinned study contributes, so a step on a construct is scored
    # on the construct's own row rather than on the native locus it leaks into.
    cassette: dict[str, str] = {}
    for study in CASSETTE_STUDIES:
        cassette.update(cassette_rows(matrix_for(Path(settings.data_dir), study)))
    tables = contrast_tables(conn, symbols=symbols, cassette=cassette)
    print(f"cassette rows available as evidence: {', '.join(sorted(cassette)) or '-'}")
    strain_map = contrast_strain_map(conn)

    # Only the routes that will be shown need a support object; compute by signature.
    signatures: dict[tuple, list[str]] = defaultdict(list)
    for (route_id,) in conn.execute(
        "SELECT id FROM pathway_route WHERE score_evidence IS NOT NULL"
    ):
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

    supports: dict[str, RouteSupport] = {}
    for _steps, route_ids in signatures.items():
        support = route_support(
            conn,
            route_ids[0],
            parts=parts,
            constructs=constructs,
            contrasts=tables,
            contrast_strains=strain_map,
            measurable_genes=measurable,
        )
        for route_id in route_ids:
            supports[route_id] = support

    answer = assemble(conn, repo_root=REPO, supports=supports, limit=args.limit)
    text = render(answer, verbose=args.verbose)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
