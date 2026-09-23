"""Load the whole-proteome functional annotation into the atlas.

Runs the bulk parsers in `fermdb.annotate.bulk` over the files the acquisition step put under
`<genomes_dir>/s288c_r64/functional/`. Order matters and is not arbitrary:

1. **SGD_features.tab first, to build the resolver.** Every other file keys on a different
   identifier -- GAF on SGDID, UniProt on an accession, KEGG on `sce:YMR303C` -- and the atlas
   keys on the SGD systematic name. SGD_features is what bridges them, so nothing can resolve
   until it is read.
2. **UniProt next**, which adds the accession -> systematic-name lane the GAF needs.
3. **Gene groups**, because an annotation whose `gene_group_id` has no row cannot be inserted:
   the foreign key would reject it, and at GAF volume that is 130,000 silently dropped rows.
4. **Then the annotations themselves.**

Writes go wherever `FERMDB_DB_FILE` points. This script does not choose the database and will
refuse to guess: run it against a copy first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fermdb.annotate.bulk import (
    BulkFile,
    BulkReport,
    GafReader,
    gaf_annotation_rows,
    kegg_annotation_rows,
    learn_from_sgd_features,
    learn_from_uniprot,
    load_gene_annotations,
    load_gene_groups_from_sgd_features,
    open_annotation_file,
    parse_kegg_list,
    parse_kegg_pathway_links,
    parse_sgd_features,
    parse_uniprot_tsv,
    sgd_feature_annotation_rows,
    uniprot_annotation_rows,
)
from fermdb.annotate.importers import utcnow_iso
from fermdb.annotate.resolve import IdentifierResolver
from fermdb.annotate.sources import annotation_sources_path, load_annotation_sources
from fermdb.config import Settings
from fermdb.db import open_db

SGD_BASE = "https://downloads.yeastgenome.org/curation"


def main() -> int:
    settings = Settings.load()
    functional = Path(settings.genomes_dir) / "s288c_r64" / "functional"
    if not functional.is_dir():
        print(f"no functional directory at {functional}", file=sys.stderr)
        return 1

    sources = load_annotation_sources(annotation_sources_path(settings))
    retrieved_at = utcnow_iso()
    resolver = IdentifierResolver()
    report = BulkReport()

    print(f"database  {settings.db_file}")
    print(f"functional {functional}\n")

    # ---- 1. SGD features, which every other file resolves through -------------------------
    with open_annotation_file(functional / "SGD_features.tab") as handle:
        features = list(parse_sgd_features(handle))
    learned = learn_from_sgd_features(resolver, features)
    print(f"SGD_features.tab   {len(features):>7} records, {learned} names learned")

    # ---- 2. UniProt, for the accession lane ----------------------------------------------
    uniprot_path = functional / "uniprot_UP000002311.tsv.gz"
    with open_annotation_file(uniprot_path) as handle:
        uniprot_records = list(parse_uniprot_tsv(handle))
    learn_from_uniprot(resolver, uniprot_records)
    print(f"uniprot TSV        {len(uniprot_records):>7} records")

    conn = open_db(settings.db_file, create=False)

    # ---- 3. Gene groups, or every annotation below fails its foreign key ------------------
    groups = load_gene_groups_from_sgd_features(
        conn,
        features,
        bulk_file=BulkFile(
            "SGD_features.tab", url=f"{SGD_BASE}/chromosomal_feature/SGD_features.tab"
        ),
        retrieved_at=retrieved_at,
    )
    print(f"gene_group         {groups.summary()}\n")

    totals: list[tuple[str, str]] = []

    # ---- 4a. GO, from SGD's GAF ----------------------------------------------------------
    gaf_path = functional / "gene_association.sgd.gaf.gz"
    with open_annotation_file(gaf_path) as handle:
        reader = GafReader(handle)
        result = load_gene_annotations(
            conn,
            gaf_annotation_rows(
                reader,
                resolver,
                sources=sources,
                source_id="sgd_go",
                bulk_file=BulkFile(
                    "gene_association.sgd.gaf",
                    reader.header.source_version,
                    f"{SGD_BASE}/literature/gene_association.sgd.gaf.gz",
                ),
                retrieved_at=retrieved_at,
                report=report,
                # SGD ships `BSR`, which is not a GO Consortium code. Collect and count it
                # rather than raising mid-file or inventing a confidence for it.
                on_unknown_evidence="collect",
            ),
            report=report,
        )
    totals.append(("sgd_go", result.summary()))

    # ---- 4b. UniProt: EC numbers, domains, localisation, cofactors ------------------------
    with open_annotation_file(uniprot_path) as handle:
        result = load_gene_annotations(
            conn,
            uniprot_annotation_rows(
                parse_uniprot_tsv(handle),
                resolver,
                sources=sources,
                bulk_file=BulkFile("uniprot_UP000002311.tsv", url="https://rest.uniprot.org"),
                retrieved_at=retrieved_at,
                report=report,
            ),
            report=report,
        )
    totals.append(("uniprot/interpro/pfam", result.summary()))

    # ---- 4c. KEGG ------------------------------------------------------------------------
    with open_annotation_file(functional / "kegg_sce_genes.tsv") as genes_handle:
        entries = list(parse_kegg_list(genes_handle))
    with open_annotation_file(functional / "kegg_sce_gene2pathway.tsv") as links_handle:
        links = list(parse_kegg_pathway_links(links_handle))
    result = load_gene_annotations(
        conn,
        kegg_annotation_rows(
            entries,
            links,
            resolver,
            sources=sources,
            bulk_file=BulkFile("kegg list/sce", url="https://rest.kegg.jp/list/sce"),
            retrieved_at=retrieved_at,
            report=report,
        ),
        report=report,
    )
    totals.append(("kegg", result.summary()))

    # ---- 4d. SGD curated descriptions ----------------------------------------------------
    result = load_gene_annotations(
        conn,
        sgd_feature_annotation_rows(
            features,
            resolver,
            sources=sources,
            bulk_file=BulkFile(
                "SGD_features.tab", url=f"{SGD_BASE}/chromosomal_feature/SGD_features.tab"
            ),
            retrieved_at=retrieved_at,
            report=report,
        ),
        report=report,
    )
    totals.append(("sgd descriptions", result.summary()))

    conn.close()

    print("loaded:")
    for label, summary in totals:
        print(f"  {label:<24}{summary}")
    print()
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
