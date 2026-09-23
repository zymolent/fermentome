"""Functional annotation: GO terms, pathway/KO/EC membership, protein domains, cofactor
specificity, subcellular location, transporter family, complex membership, TF targets and
phenotypes for every organism DUET_TARGET.md and ISOBUTANOL_PROGRAM.md name.

THE KEY DESIGN POINT, stated once here because every importer in `importers.py` exists to serve
it: for *S. cerevisiae*, nearly all of this is ALREADY CURATED at SGD and UniProt, better than
this atlas could compute it from sequence alone -- SGD biocurators read the primary literature and
assign GO terms and phenotypes directly; UniProt curators assign cofactor specificity and
subcellular location the same way. So this package IMPORTS, it does not compute. That is the
opposite of the sibling project's situation (T. reesei's shipped annotation was materially
incomplete, and de novo HMMER annotation was necessary there); it is also true, via UniProt/KEGG,
for the bacterial hosts this atlas studies for comparison (`escherichia_coli`, `zymomonas_mobilis`,
`lactococcus_cremoris`, `corynebacterium_glutamicum`, `bacillus_subtilis` -- the owner's directive
to look at isobutanol production in popular bacterial strains too, alongside the two yeast
chassis).

Two things are the deliberate exception, because no external database provides either
systematically and both sit on DUET's own critical path
(docs/design/DUET_TARGET.md section 2, "Mitochondrial, not cytosolic" and "Fe-S protection,
dual-purpose"):

* mitochondrial targeting sequence / presequence prediction (yeast only) --
  `predict_mitochondrial_presequence` below.
* Fe-S cluster protein annotation (Ilv3/DHAD is the named critical case; cytosolic Fe-S cluster
  maturation is a documented failure mode for the cytosolic-relocalization strategy this atlas is
  deciding against) -- `annotate_fe_s_cluster` below.

Both are TODO STUBS in this build: the interface (a typed dataclass and a function with the right
signature) exists so callers and the schema can be written against it now, but neither is
implemented here, and each raises `NotImplementedError` naming why. See each dataclass's and
function's own docstring for the full rationale.

Module layout:

* `sources.py` -- the `data/annotation/annotation_sources.yaml` registry (one row per external
  database, its licence/redistributability, and the GO-evidence-code-to-confidence mapping every
  GO-backed importer uses).
* `importers.py` -- pluggable-`Transport` fetchers and pure parsers for each source, plus the
  idempotent `gene_annotation` writer. Tests run entirely offline against recorded fixtures under
  `tests/fixtures/annotate/` (the harness's binding rule: tests must never touch the network).

`gene_annotation` (src/fermdb/db/schema.sql, "functional annotation") is this package's one table.
`SCHEMA_VERSION` was bumped for it -- see `fermdb.db`'s own module docstring for the exact
before/after value and the reviewer note about coordinating with any other agent also bumping it
in this build.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bulk import (
    GENE_FEATURE_TYPES,
    BulkFile,
    BulkLoadResult,
    BulkParseError,
    BulkReport,
    GafHeader,
    GafReader,
    GafRecord,
    GeneGroupLoadResult,
    KeggGeneEntry,
    SgdFeature,
    UniProtCofactor,
    UniProtRecord,
    gaf_annotation_rows,
    kegg_annotation_rows,
    learn_from_gaf,
    learn_from_kegg_list,
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
from .importers import (
    AnnotationImportError,
    AnnotationTransportError,
    GeneAnnotationRow,
    Transport,
    UrllibTransport,
    fetch_generic_term_list,
    fetch_kegg_entry,
    fetch_sgd_go,
    fetch_uniprot_entry,
    fetch_uniprot_goa,
    find_gene_annotation,
    parse_generic_term_list,
    parse_kegg_flat_entry,
    parse_sgd_go_response,
    parse_uniprot_entry,
    parse_uniprot_goa_response,
    write_gene_annotation,
    write_gene_annotations,
)
from .resolve import (
    IDENTIFIER_KINDS,
    IdentifierKind,
    IdentifierResolver,
    ResolutionFailure,
    ResolutionReport,
)
from .sources import (
    GO_EVIDENCE_CATEGORIES,
    KNOWN_SOURCE_IDS,
    AnnotationSource,
    AnnotationSourcesError,
    UnknownGoEvidenceCodeError,
    annotation_sources_path,
    go_evidence_category,
    load_annotation_sources,
    recommended_confidence_for_go_evidence,
    resolve_source_url,
    source_by_id,
    sources_for_organism,
)

__all__ = [
    "GENE_FEATURE_TYPES",
    "GO_EVIDENCE_CATEGORIES",
    "IDENTIFIER_KINDS",
    "KNOWN_SOURCE_IDS",
    "AnnotationImportError",
    "AnnotationSource",
    "AnnotationSourcesError",
    "AnnotationTransportError",
    "BulkFile",
    "BulkLoadResult",
    "BulkParseError",
    "BulkReport",
    "FeSClusterAnnotation",
    "GafHeader",
    "GafReader",
    "GafRecord",
    "GeneAnnotationRow",
    "GeneGroupLoadResult",
    "IdentifierKind",
    "IdentifierResolver",
    "KeggGeneEntry",
    "PresequencePrediction",
    "ResolutionFailure",
    "ResolutionReport",
    "SgdFeature",
    "Transport",
    "UniProtCofactor",
    "UniProtRecord",
    "UnknownGoEvidenceCodeError",
    "UrllibTransport",
    "annotate_fe_s_cluster",
    "annotation_sources_path",
    "fetch_generic_term_list",
    "gaf_annotation_rows",
    "kegg_annotation_rows",
    "learn_from_gaf",
    "learn_from_kegg_list",
    "learn_from_sgd_features",
    "learn_from_uniprot",
    "load_gene_annotations",
    "load_gene_groups_from_sgd_features",
    "open_annotation_file",
    "parse_kegg_list",
    "parse_kegg_pathway_links",
    "parse_sgd_features",
    "parse_uniprot_tsv",
    "sgd_feature_annotation_rows",
    "uniprot_annotation_rows",
    "fetch_kegg_entry",
    "fetch_sgd_go",
    "fetch_uniprot_entry",
    "fetch_uniprot_goa",
    "find_gene_annotation",
    "go_evidence_category",
    "load_annotation_sources",
    "parse_generic_term_list",
    "parse_kegg_flat_entry",
    "parse_sgd_go_response",
    "parse_uniprot_entry",
    "parse_uniprot_goa_response",
    "predict_mitochondrial_presequence",
    "recommended_confidence_for_go_evidence",
    "resolve_source_url",
    "source_by_id",
    "sources_for_organism",
    "write_gene_annotation",
    "write_gene_annotations",
]


# ---------------------------------------------------------------------------------------------
# TODO STUBS -- interfaces only, deliberately not implemented in this task. See the module
# docstring above for why these two (and only these two) are computed rather than imported.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PresequencePrediction:
    """TODO STUB -- interface only, not implemented in this task.

    Shape a mitochondrial N-terminal presequence / cleavage-site predictor (TargetP-2.0- or
    MitoFates-style) must return, so `predict_mitochondrial_presequence`'s callers and a future
    `gene_annotation`-adjacent table can be written against a stable contract now. Nothing here
    computes it: docs/design/DUET_TARGET.md section 2's "Mitochondrial, not cytosolic" claim rests
    on the nuclear-encoded pathway genes (`ILV2`/`ILV6`/`ILV5`/`ILV3`/`ARO10`/`BAT1`/`BAT2`/
    `LEU4`/`LEU9`/`ADH3`/`POS5`) being reliably presequence-targeted to the matrix, and no source
    in `importers.py` scores that -- GO/UniProt record an OBSERVED subcellular location
    (`uniprot`'s `SUBCELLULAR LOCATION` comment), never a PREDICTED signal from a specific
    sequence, which is a different fact and the one this stub names.
    """

    gene_group_id: str
    is_mitochondrial_presequence: bool
    cleavage_site: int | None  # 0-based index of the mature protein's first residue
    score: float | None
    method: str
    method_version: str


def predict_mitochondrial_presequence(
    sequence: str, *, gene_group_id: str
) -> PresequencePrediction:
    """TODO: not implemented in this task.

    Rationale: this is a genuine sequence-based computation (an N-terminal scan against a trained
    model, e.g. TargetP-2.0 or MitoFates), not something any source in `importers.py` provides
    systematically -- the opposite situation from every other annotation kind this package
    handles. Implementing it here would also mean picking and validating a specific tool/model
    version, which is a decision this build's scope explicitly excludes ("do not implement
    predictors in this task"). A real implementation should run as a `processing_run`
    (src/fermdb/db/schema.sql section 7) like any other computed result, with its tool version and
    parameters recorded, not as a bare function call with no provenance.
    """
    raise NotImplementedError(
        "fermdb.annotate deliberately ships no mitochondrial presequence predictor yet. See "
        "docs/design/DUET_TARGET.md section 2 and fermdb.annotate's module docstring: a "
        "TargetP-2.0- or MitoFates-style N-terminal scan over the nuclear-encoded pathway gene "
        "set is the next build step, run as a recorded processing_run -- not invented here."
    )


@dataclass(frozen=True)
class FeSClusterAnnotation:
    """TODO STUB -- interface only, not implemented in this task.

    Ilv3 (DHAD) carries a [4Fe-4S] cluster (docs/design/ISOBUTANOL_PROGRAM.md's parts-catalog
    table: "[4Fe-4S] cluster: oxygen lability, and cytosolic Fe-S maturation if relocalized"), and
    DUET's own "Fe-S protection, dual-purpose" design claim
    (docs/design/DUET_TARGET.md section 2) treats this as the rate-limiting, most fragile step:
    "Isobutanol toxicity destroys Fe-S clusters and the rate-limiting enzyme is one." No GO/
    UniProt/KEGG bulk annotation flags "requires cytosolic Fe-S cluster maturation machinery (the
    CIA pathway: `NFS1`/`ISU1`/`YFH1`/...)" as a queryable property -- `uniprot`'s `COFACTOR`
    comment (`importers.parse_uniprot_entry`) records THAT a protein binds an Fe-S cluster when
    UniProt has curated it, but not which maturation pathway or compartment that dependency
    implies, which is the fact this atlas actually needs for route selection.
    """

    gene_group_id: str
    has_fe_s_cluster: bool
    cluster_type: str | None  # e.g. '[4Fe-4S]', '[2Fe-2S]'
    maturation_pathway: str | None  # e.g. 'cytosolic_cia', 'mitochondrial_isc'
    method: str
    method_version: str


def annotate_fe_s_cluster(
    gene_group_id: str, *, sequence: str | None = None
) -> FeSClusterAnnotation:
    """TODO: not implemented in this task.

    Rationale: a real pass is not sequence-only prediction from nothing -- it combines a curated
    seed list (Fe-S proteins named in the literature for this pathway, starting with Ilv3/DHAD)
    with a domain/motif scan (the Fe-S-binding Pfam/InterPro entries `fetch_pfam`/`fetch_interpro`
    in `importers.py` already know how to fetch, once a production integration confirms their
    exact field names live) plus a maturation-pathway lookup this atlas would need to curate by
    hand (CIA vs ISC pathway membership is not itself a GO/UniProt-queryable property in the
    general case). That composition is exactly why it is scoped OUT of this task rather than
    stubbed in as a bad heuristic (docs/reference/CONVENTIONS.md: never write confidence from
    memory, and a made-up Fe-S call would be worse than an honest `NotImplementedError`).
    """
    raise NotImplementedError(
        "fermdb.annotate deliberately ships no Fe-S cluster predictor/curation pass yet. Ilv3 "
        "(DHAD) is the known critical case (docs/design/ISOBUTANOL_PROGRAM.md; "
        "docs/design/DUET_TARGET.md section 2, 'Fe-S protection, dual-purpose'): cytosolic Fe-S "
        "cluster maturation is a documented failure mode for the cytosolic-relocalization "
        "strategy this atlas is deciding against. A real pass combines a curated seed list with "
        "a Pfam/InterPro domain scan and a hand-curated CIA/ISC maturation-pathway lookup -- it "
        "is not built here."
    )
