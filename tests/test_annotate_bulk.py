"""Tests for `fermdb.annotate.bulk` and `fermdb.annotate.resolve` -- whole-proteome annotation.

Everything runs offline against `tests/fixtures/annotate/bulk/`, and those fixtures are CUT FROM
REAL FILES, not invented: a 60 KB range of `gene_association.sgd.gaf.gz` and a 2.5 MB range of
`SGD_features.tab` from sgd-archive.yeastgenome.org, both `rest.kegg.jp` endpoints in full, and
three `rest.uniprot.org` TSV exports, all sampled on 2026-09-23. Every line is a genuine record
except three `!SYNTHETIC`-commented lines in the GAF that document the one derived line they sit
above (a real record with its unambiguous identifiers removed, so the ambiguity path has something
to run on). That matters because every bug these parsers can have lives in a real file's edge
cases -- the trailing `;` UniProt puts on every cross-reference list, the four-column `list/sce`
its own documentation describes as two, the `CDS` rows in SGD_features.tab with an empty
systematic-name column, the `BSR` evidence code that is not a GO Consortium code at all.

No test here touches a network, and none touches `C:\\Users\\kangk\\fermdb-data\\fermdb.sqlite3`:
every database test runs against `open_db(IN_MEMORY)`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb.annotate import (
    AnnotationSource,
    BulkFile,
    BulkParseError,
    BulkReport,
    GafReader,
    GeneAnnotationRow,
    IdentifierResolver,
    ResolutionReport,
    SgdFeature,
    UniProtRecord,
    UnknownGoEvidenceCodeError,
    gaf_annotation_rows,
    kegg_annotation_rows,
    learn_from_kegg_list,
    learn_from_sgd_features,
    learn_from_uniprot,
    load_annotation_sources,
    load_gene_annotations,
    load_gene_groups_from_sgd_features,
    parse_kegg_list,
    parse_kegg_pathway_links,
    parse_sgd_features,
    parse_uniprot_tsv,
    sgd_feature_annotation_rows,
    uniprot_annotation_rows,
    write_gene_annotation,
)
from fermdb.annotate.bulk import open_annotation_file, parse_uniprot_subcellular_locations
from fermdb.db import IN_MEMORY, open_db

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "annotate" / "bulk"
REAL_ANNOTATION_SOURCES = REPO_ROOT / "data" / "annotation" / "annotation_sources.yaml"

RETRIEVED_AT = "2026-09-23T00:00:00Z"

GAF_FILE = BulkFile(
    label="gene_association.sgd.gaf",
    version="gaf-version 2.2, generated 20260922",
    url="http://sgd-archive.yeastgenome.org/curation/literature/gene_association.sgd.gaf.gz",
)
FEATURES_FILE = BulkFile(
    label="SGD_features.tab",
    version="2026-09-23 snapshot",
    url="http://sgd-archive.yeastgenome.org/curation/chromosomal_feature/SGD_features.tab",
)
UNIPROT_FILE = BulkFile(
    label="uniprotkb_organism_id_559292.tsv",
    version="UniProt release sampled 2026-09-23",
    url="https://rest.uniprot.org/uniprotkb/stream",
)
KEGG_FILE = BulkFile(label="rest.kegg.jp list/sce + link/pathway/sce", version="2026-09-23")


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _sources() -> list[AnnotationSource]:
    return load_annotation_sources(REAL_ANNOTATION_SOURCES)


def _features() -> list[SgdFeature]:
    return list(parse_sgd_features(_lines("SGD_features.tab")))


def _uniprot() -> list[UniProtRecord]:
    return list(parse_uniprot_tsv(_lines("uniprot_export.tsv")))


def _yeast_resolver(*, with_uniprot: bool = True, with_kegg: bool = False) -> IdentifierResolver:
    """The resolver as a real run would build it: SGD_features first, then the other files."""
    resolver = IdentifierResolver()
    learn_from_sgd_features(resolver, _features())
    if with_uniprot:
        learn_from_uniprot(resolver, _uniprot())
    if with_kegg:
        learn_from_kegg_list(resolver, parse_kegg_list(_lines("kegg_list_sce.txt")))
    return resolver


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    try:
        yield connection
    finally:
        connection.close()


def _seed_gene_groups(conn: sqlite3.Connection, *systematic_names: str) -> None:
    for name in systematic_names:
        conn.execute(
            "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
            "membership_method, zone, evidence, confidence) "
            "VALUES (?, 'sgd_systematic', ?, NULL, 'species', 'anchor', 'R', 'test fixture', "
            "'low')",
            (f"YAA:GG:{name.lower()}", name),
        )
    conn.commit()


# ---------------------------------------------------------------------------------------------
# The resolver: the part that decides which gene an identifier means, or refuses to.
# ---------------------------------------------------------------------------------------------


def test_sgd_features_teaches_systematic_name_sgdid_and_every_alias() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    for identifier, kind in (
        ("YMR303C", "systematic_name"),
        ("S000004918", "sgdid"),
        ("SGD:S000004918", "sgdid"),  # the prefixed form a GO cross-reference writes
        ("ADH2", "symbol"),
        ("ADR2", "symbol"),  # the alias column -- the whole point of reading this file
        ("adr2", "symbol"),  # case-insensitive
    ):
        assert resolver.resolve(identifier, kind) == "YMR303C", (identifier, kind)


def test_an_ambiguous_symbol_is_refused_and_counted_never_guessed() -> None:
    """`YRF1` is an alias of six real ORFs. Picking one would be a silent, permanent error."""
    resolver = _yeast_resolver(with_uniprot=False)
    report = ResolutionReport()

    assert resolver.resolve("YRF1", "symbol", report=report) is None

    assert report.failure_count("symbol", "ambiguous") == 1
    failure = report.examples("symbol", "ambiguous")[0]
    assert failure.reason == "ambiguous"
    assert set(failure.candidates) == {"YDR545W", "YER190W"}
    assert ("symbol", "YRF1") in report.ambiguities()
    assert "YRF1" in report.summary()


def test_a_stronger_identifier_rescues_the_record_but_the_ambiguity_is_still_reported() -> None:
    """Using an unambiguous SGDID beside an ambiguous symbol is not a guess -- but the collision
    is still worth knowing about, so it is recorded without being charged as a failure."""
    resolver = _yeast_resolver(with_uniprot=False)
    report = ResolutionReport()

    resolved = resolver.resolve_any([("symbol", "YRF1"), ("sgdid", "S000002953")], report=report)

    assert resolved == "YDR545W"
    assert report.total_failed == 0
    assert report.ambiguities()[("symbol", "YRF1")] == ("YDR545W", "YER190W")


def test_an_unknown_identifier_is_counted_not_silently_dropped() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    report = ResolutionReport()

    assert resolver.resolve("S000999999", "sgdid", report=report) is None

    assert report.failure_count("sgdid", "unknown") == 1
    assert report.total_resolved == 0
    assert "UNRESOLVED sgdid (unknown): 1" in report.summary()


def test_resolve_any_charges_one_failure_per_record_not_one_per_identifier() -> None:
    """Otherwise a GAF line carrying four identifiers inflates the unresolved count fourfold."""
    resolver = _yeast_resolver(with_uniprot=False)
    report = ResolutionReport()

    assert (
        resolver.resolve_any(
            [
                ("sgdid", "S000999999"),
                ("symbol", "NOTAGENE"),
                ("uniprot", "Q9XXXX"),
                ("systematic_name", "YZZ999W"),
            ],
            report=report,
        )
        is None
    )

    assert report.total_failed == 1
    # Attributed to the STRONGEST identifier present, so the report names the bridge that is
    # actually missing rather than whichever one happened to be tried last.
    assert report.failure_count("systematic_name", "unknown") == 1


def test_uniprot_accession_bridges_to_a_systematic_name() -> None:
    resolver = _yeast_resolver()
    assert resolver.resolve("P00330", "uniprot") == "YOL086C"
    assert resolver.resolve("UniProtKB:P00330", "uniprot") == "YOL086C"
    # An isoform accession is the same gene.
    assert resolver.resolve("P00330-2", "uniprot") == "YOL086C"


def test_kegg_organism_prefix_is_stripped() -> None:
    resolver = _yeast_resolver(with_uniprot=False, with_kegg=True)
    assert resolver.resolve("sce:YMR303C", "kegg") == "YMR303C"
    assert resolver.resolve("YMR303C", "kegg") == "YMR303C"


def test_a_standard_name_equal_to_the_systematic_name_is_not_indexed_as_a_symbol() -> None:
    resolver = IdentifierResolver()
    resolver.learn("YMR303C", symbols=["YMR303C", "ADH2"])
    assert resolver.candidates("ADH2", "symbol") == ("YMR303C",)
    assert resolver.candidates("YMR303C", "symbol") == ()


def test_gene_group_id_uses_the_projects_own_curie_rule() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    assert resolver.gene_group_id_for([("symbol", "ADH2")]) == "YAA:GG:ymr303c"


def test_ambiguous_identifiers_can_be_audited_before_a_load() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    collisions = dict(resolver.ambiguous_identifiers("symbol"))
    assert collisions["YRF1"] == ("YDR545W", "YER190W")


# ---------------------------------------------------------------------------------------------
# GAF 2.2
# ---------------------------------------------------------------------------------------------


def test_gaf_header_is_captured_before_the_first_record() -> None:
    reader = GafReader(_lines("gene_association.sgd.gaf"))
    assert reader.header.gaf_version == "2.2"
    assert reader.header.date_generated == "20260922"
    assert reader.header.generated_by == "Saccharomyces Genome Database (SGD)"
    assert reader.header.source_version == "gaf-version 2.2, generated 20260922"
    # And the records are still all there afterwards.
    assert len(list(reader)) == 15


def test_gaf_header_absent_means_null_source_version_not_a_placeholder() -> None:
    reader = GafReader(
        [
            "SGD\tS1\tADH2\tenables\tGO:1\tPMID:1\tIDA\t\tF\t\tYMR303C\tprotein\t"
            "taxon:559292\t20200101\tSGD\t\t"
        ]
    )
    assert reader.header.source_version is None


def test_a_not_qualified_annotation_is_never_loaded_as_a_positive_one() -> None:
    """The fixture's two real `NOT|involved_in GO:0007042` lines for VMA13 must produce no row.

    `gene_annotation` has no polarity column, so a stored row would read as "VMA13 IS involved in
    vacuole fusion" to every consumer -- the exact opposite of what SGD curated.
    """
    resolver = _yeast_resolver()
    resolver.learn("YPR036W", sgdids=["S000006240"], symbols=["VMA13"])
    report = BulkReport()

    rows = list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )

    assert [row for row in rows if row.term_id == "GO:0007042"] == []
    assert report.negated_dropped == 2
    assert any("VMA13" in example and "NOT" in example for example in report.negated_examples)
    assert "NOT-qualified GO annotations dropped: 2" in report.summary()
    # The same gene's non-negated annotation on the very next line is kept, so the drop is
    # qualifier-scoped and not gene-scoped.
    assert any(row.term_id == "GO:0000221" for row in rows)


@pytest.mark.parametrize(
    ("go_id", "code", "confidence", "namespace"),
    [
        ("GO:0036151", "IMP", "high", "biological_process"),  # experimental
        ("GO:0016887", "IDA", "high", "molecular_function"),  # experimental
        ("GO:0005524", "IEA", "low", "molecular_function"),  # electronic
        ("GO:0004455", "IBA", "medium", "molecular_function"),  # phylogenetic
        ("GO:0003674", "ND", "unverified", "molecular_function"),  # no data available
    ],
)
def test_evidence_code_drives_confidence_and_aspect_drives_namespace(
    go_id: str, code: str, confidence: str, namespace: str
) -> None:
    resolver = _yeast_resolver()
    report = BulkReport()
    rows = list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )
    matching = [row for row in rows if row.term_id == go_id and row.evidence_code == code]
    assert matching, (go_id, code)
    assert matching[0].confidence == confidence
    assert matching[0].term_namespace == namespace
    assert matching[0].zone == "R"


def test_an_unknown_evidence_code_surfaces_rather_than_being_guessed() -> None:
    """`BSR` is real: it is on 201 of the first 150,000 lines of SGD's current GAF, and it is not
    a GO Consortium evidence code."""
    resolver = _yeast_resolver()
    with pytest.raises(UnknownGoEvidenceCodeError, match="BSR"):
        list(
            gaf_annotation_rows(
                GafReader(_lines("gene_association.sgd.gaf")),
                resolver,
                sources=_sources(),
                source_id="sgd_go",
                bulk_file=GAF_FILE,
                retrieved_at=RETRIEVED_AT,
                report=BulkReport(),
            )
        )


def test_an_unknown_evidence_code_can_be_collected_but_never_becomes_a_row() -> None:
    resolver = _yeast_resolver()
    report = BulkReport()
    rows = list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )
    assert report.unknown_evidence_codes["BSR"] == 1
    assert [row for row in rows if row.term_id == "GO:0040029"] == []
    assert "UNKNOWN GO evidence codes" in report.summary()


def test_a_record_whose_only_identifier_is_ambiguous_produces_no_row() -> None:
    resolver = _yeast_resolver()
    report = BulkReport()
    rows = list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )
    assert all(row.gene_group_id not in {"YAA:GG:ydr545w", "YAA:GG:yer190w"} for row in rows)
    # The record's SGDID is unknown AND its symbol is ambiguous; the ambiguity is the more
    # actionable diagnosis, so that is what the one charged failure names.
    assert report.resolution.failure_count("symbol", "ambiguous") == 1
    assert report.resolution.ambiguities()[("symbol", "YRF1")] == ("YDR545W", "YER190W")


def test_gaf_rows_name_the_file_and_its_version_in_evidence_and_source_version() -> None:
    resolver = _yeast_resolver()
    report = BulkReport()
    rows = list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )
    row = next(row for row in rows if row.term_id == "GO:0016887")
    assert row.source == "sgd_go"
    assert row.source_version == "gaf-version 2.2, generated 20260922"
    assert row.source_url == GAF_FILE.url
    assert row.retrieved_at == RETRIEVED_AT
    assert "SGD Gene Ontology annotations" in row.evidence
    assert "gene_association.sgd.gaf (gaf-version 2.2, generated 20260922)" in row.evidence
    assert "evidence code IDA" in row.evidence


def test_a_gaf_can_only_feed_a_go_source() -> None:
    with pytest.raises(BulkParseError, match="sgd_go"):
        list(
            gaf_annotation_rows(
                [],
                IdentifierResolver(),
                sources=_sources(),
                source_id="kegg",
                bulk_file=GAF_FILE,
                retrieved_at=RETRIEVED_AT,
                report=BulkReport(),
            )
        )


def test_a_short_gaf_line_raises_rather_than_producing_garbage() -> None:
    with pytest.raises(BulkParseError, match="columns"):
        list(GafReader(["SGD\tS000004918\tADH2\tenables\tGO:0004022"]))


def test_a_short_gaf_line_can_be_padded_when_the_caller_asks_for_leniency() -> None:
    reader = GafReader(
        ["SGD\tS000004918\tADH2\tenables\tGO:0004022\tPMID:1\tIDA\t\tF\t\tYMR303C\tprotein"],
        strict=False,
    )
    (record,) = list(reader)
    assert record.gene_product_form_id is None
    assert record.synonyms == ("YMR303C",)


# ---------------------------------------------------------------------------------------------
# SGD_features.tab
# ---------------------------------------------------------------------------------------------


def test_sgd_features_unpacks_all_sixteen_columns() -> None:
    features = {f.systematic_name: f for f in _features() if f.systematic_name}
    adh2 = features["YMR303C"]
    assert adh2.sgdid == "S000004918"
    assert adh2.feature_type == "ORF"
    assert adh2.feature_qualifier == "Verified"
    assert adh2.standard_name == "ADH2"
    assert "ADR2" in adh2.aliases
    assert adh2.secondary_sgdids == ("L000000042", "L000000051")
    assert adh2.chromosome == "13"
    assert adh2.strand_as_reported == "C"
    assert adh2.description is not None
    assert adh2.description.startswith("Glucose-repressible alcohol dehydrogenase II")
    assert adh2.is_gene


def test_a_cds_subfeature_carries_no_systematic_name_and_is_not_a_gene() -> None:
    """Roughly half of the real file's lines are sub-features whose name lives on their parent."""
    cds = [f for f in _features() if f.feature_type == "CDS"]
    assert cds and cds[0].systematic_name is None
    assert cds[0].parent_feature == "YOL086C"
    assert not cds[0].is_gene


def test_a_non_gene_feature_type_is_not_given_a_gene_group() -> None:
    ars = [f for f in _features() if f.feature_type == "ARS"]
    assert ars and not ars[0].is_gene


def test_an_orf_with_no_standard_name_records_null_not_an_empty_string() -> None:
    resolver = IdentifierResolver()
    (feature,) = list(
        parse_sgd_features(
            [
                "S000350094\tORF\tVerified\tYDL204W-A\t\t\tchromosome 4\t\t4\t94133\t94285\tW\t\t"
                "2024-05-28\t2024-05-28\tProtein of unknown function"
            ]
        )
    )
    assert feature.standard_name is None
    assert feature.aliases == ()
    learn_from_sgd_features(resolver, [feature])
    assert resolver.resolve("YDL204W-A", "systematic_name") == "YDL204W-A"


def test_a_short_sgd_features_line_raises() -> None:
    with pytest.raises(BulkParseError, match="expected 16"):
        list(parse_sgd_features(["S000004918\tORF\tVerified\tYMR303C"]))


def test_sgd_description_rows_are_namespaced_so_nothing_mistakes_them_for_phenotypes() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    report = BulkReport()
    rows = list(
        sgd_feature_annotation_rows(
            _features(),
            resolver,
            sources=_sources(),
            bulk_file=FEATURES_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
        )
    )
    row = next(row for row in rows if row.gene_group_id == "YAA:GG:ymr303c")
    assert row.source == "sgd_phenotype"
    assert row.term_namespace == "sgd_description"
    assert row.term_id == "SGD:S000004918"
    assert row.term_label is not None and "Glucose-repressible" in row.term_label
    assert row.zone == "R"
    assert row.evidence_code is None
    assert "SGD_features.tab" in row.evidence
    # One description row per gene, and none for the CDS sub-feature or the ARS.
    assert len(rows) == 10


def test_alias_rows_are_opt_in() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    without = list(
        sgd_feature_annotation_rows(
            _features(),
            resolver,
            sources=_sources(),
            bulk_file=FEATURES_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
        )
    )
    with_aliases = list(
        sgd_feature_annotation_rows(
            _features(),
            resolver,
            sources=_sources(),
            bulk_file=FEATURES_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
            include_aliases=True,
        )
    )
    assert len(with_aliases) > len(without)
    assert any(row.term_namespace == "gene_alias" and row.term_id == "ADR2" for row in with_aliases)
    assert all(row.term_namespace != "gene_alias" for row in without)


# ---------------------------------------------------------------------------------------------
# UniProt TSV
# ---------------------------------------------------------------------------------------------


def test_a_trailing_semicolon_does_not_produce_an_empty_term() -> None:
    """Every populated UniProt cross-reference list ends in `;`. `PF02116;` is ONE Pfam id."""
    records = {r.accession: r for r in _uniprot()}
    ste2 = records["D6VTK4"]
    assert ste2.interpro_ids == ("IPR000366", "IPR027458")
    assert ste2.pfam_ids == ("PF02116",)
    assert ste2.sgdids == ("S000001868",)
    assert ste2.kegg_ids == ("sce:YFL026W",)
    assert all(term for term in ste2.interpro_ids + ste2.pfam_ids)

    resolver = _yeast_resolver()
    rows = list(
        uniprot_annotation_rows(
            [ste2],
            resolver,
            sources=_sources(),
            bulk_file=UNIPROT_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
        )
    )
    assert all(row.term_id.strip() for row in rows)
    assert {row.term_id for row in rows if row.source == "interpro"} == {
        "IPR000366",
        "IPR027458",
    }
    assert {row.term_id for row in rows if row.source == "pfam"} == {"PF02116"}


def test_multiple_ec_numbers_split_on_the_semicolon_list() -> None:
    records = {r.accession: r for r in _uniprot()}
    assert records["P00330"].ec_numbers == ("1.1.1.1", "1.1.1.54", "1.1.1.78")


def test_cofactors_keep_the_chebi_id_and_the_name() -> None:
    """ILV3's `[2Fe-2S] cluster` is the case docs/design/DUET_TARGET.md section 2 turns on."""
    records = {r.accession: r for r in _uniprot()}
    ilv3 = records["P39522"]
    assert [(c.name, c.chebi_id) for c in ilv3.cofactors] == [
        ("[2Fe-2S] cluster", "CHEBI:190135"),
        ("Mg(2+)", "CHEBI:18420"),
    ]
    assert ilv3.cofactors[0].term_id == "CHEBI:190135"


def test_subcellular_locations_drop_evidence_braces_and_the_note_tail() -> None:
    records = {r.accession: r for r in _uniprot()}
    assert records["D6VTK4"].subcellular_locations == (
        "Cell membrane",
        "Multi-pass membrane protein",
    )
    assert records["P06168"].subcellular_locations == ("Mitochondrion",)
    # Nothing from the `Note=` prose leaks through.
    assert all(
        "Internalized" not in location for location in records["D6VTK4"].subcellular_locations
    )


def test_an_isoform_labelled_location_block_loses_only_its_label() -> None:
    assert parse_uniprot_subcellular_locations(
        "SUBCELLULAR LOCATION: [Isoform 2]: Nucleus {ECO:0000255}. SUBCELLULAR LOCATION: Cytoplasm."
    ) == ("Nucleus", "Cytoplasm")


def test_an_export_with_no_entry_column_raises_at_the_header() -> None:
    with pytest.raises(BulkParseError, match="Entry"):
        list(parse_uniprot_tsv(["Protein names\tPfam", "some protein\tPF00001;"]))


def test_go_ids_are_parsed_but_not_emitted_unless_asked_for() -> None:
    records = {r.accession: r for r in _uniprot()}
    assert "GO:0004365" in records["P00358"].go_ids

    resolver = _yeast_resolver()
    default_rows = list(
        uniprot_annotation_rows(
            [records["P00330"]],
            resolver,
            sources=_sources(),
            bulk_file=UNIPROT_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
        )
    )
    assert all(row.source != "uniprot_goa" for row in default_rows)

    go_rows = [
        row
        for row in uniprot_annotation_rows(
            [records["P00330"]],
            resolver,
            sources=_sources(),
            bulk_file=UNIPROT_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
            include_go=True,
        )
        if row.source == "uniprot_goa"
    ]
    assert go_rows
    # No evidence code in this column, so no confidence is invented from one.
    assert all(row.evidence_code is None and row.confidence == "unverified" for row in go_rows)


def test_a_record_with_no_yeast_cross_reference_is_counted_not_dropped() -> None:
    """The two real *E. coli* rows in the export resolve against nothing in a yeast resolver."""
    records = {r.accession: r for r in _uniprot()}
    resolver = _yeast_resolver(with_uniprot=False)
    report = BulkReport()

    rows = list(
        uniprot_annotation_rows(
            [records["P05791"], records["P05793"]],
            resolver,
            sources=_sources(),
            bulk_file=UNIPROT_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
        )
    )

    assert rows == []
    assert report.records_read == 2
    assert report.resolution.total_failed == 2
    assert report.resolution.total_resolved == 0
    assert "UNRESOLVED" in report.summary()


def test_ordered_locus_names_are_whitespace_separated() -> None:
    records = {r.accession: r for r in _uniprot()}
    assert records["P05791"].ordered_locus_names == ("b3771", "JW5605")
    assert records["P05791"].kegg_ids == ("ecj:JW5605", "eco:b3771", "ecoc:C3026_20425")


def test_a_mitochondrial_systematic_name_is_recognised() -> None:
    """`Q0045` (COX1) is mtDNA-encoded and does not match the nuclear `Y__###_` pattern."""
    resolver = IdentifierResolver()
    records = {r.accession: r for r in _uniprot()}
    learn_from_uniprot(resolver, [records["P00401"]])
    assert resolver.resolve("P00401", "uniprot") == "Q0045"


# ---------------------------------------------------------------------------------------------
# KEGG
# ---------------------------------------------------------------------------------------------


def test_kegg_list_parses_the_four_column_form_the_endpoint_actually_serves() -> None:
    entries = {e.kegg_id: e for e in parse_kegg_list(_lines("kegg_list_sce.txt"))}
    adh2 = entries["sce:YMR303C"]
    assert adh2.entry_type == "CDS"
    assert adh2.position == "XIII:complement(873291..874337)"
    assert adh2.symbols == ("ADH2", "ADR2")
    assert adh2.description == "alcohol dehydrogenase ADH2"


def test_kegg_list_also_parses_the_two_column_form_the_documentation_describes() -> None:
    (entry,) = list(parse_kegg_list(["sce:YMR303C\tADH2; alcohol dehydrogenase ADH2"]))
    assert entry.entry_type is None
    assert entry.position is None
    assert entry.symbols == ("ADH2",)
    assert entry.description == "alcohol dehydrogenase ADH2"


def test_a_kegg_definition_with_no_symbol_yields_no_symbol() -> None:
    (entry,) = list(parse_kegg_list(["sce:YAL067W-A\tCDS\tI:2480..2707\tuncharacterized protein"]))
    assert entry.symbols == ()
    assert entry.description == "uncharacterized protein"


def test_kegg_links_strip_the_path_prefix() -> None:
    pairs = list(parse_kegg_pathway_links(_lines("kegg_link_pathway_sce.txt")))
    assert ("sce:YMR303C", "sce00010") in pairs
    assert all(not pathway.startswith("path:") for _, pathway in pairs)


def test_kegg_rows_carry_identifier_and_link_only_and_populate_pathway_id_only_when_told() -> None:
    conn = open_db(IN_MEMORY)
    try:
        resolver = _yeast_resolver(with_kegg=True)
        report = BulkReport()
        rows = list(
            kegg_annotation_rows(
                parse_kegg_list(_lines("kegg_list_sce.txt")),
                parse_kegg_pathway_links(_lines("kegg_link_pathway_sce.txt")),
                resolver,
                sources=_sources(),
                bulk_file=KEGG_FILE,
                retrieved_at=RETRIEVED_AT,
                report=report,
                internal_pathway_ids={"sce00010": "YAA:PWY:glycolysis"},
            )
        )
        gene_row = next(row for row in rows if row.term_id == "sce:YMR303C")
        assert gene_row.source == "kegg"
        assert gene_row.term_label == "ADH2"
        # `redistributable: false`: the KEGG definition text is never carried into the atlas.
        assert gene_row.term_label != "alcohol dehydrogenase ADH2"
        assert gene_row.source_url == "https://www.kegg.jp/entry/sce:YMR303C"

        glycolysis = [
            row
            for row in rows
            if row.term_id == "sce00010" and row.gene_group_id == "YAA:GG:ymr303c"
        ]
        assert glycolysis and glycolysis[0].pathway_id == "YAA:PWY:glycolysis"
        other = next(row for row in rows if row.term_id == "sce00071")
        assert other.pathway_id is None
    finally:
        conn.close()


def test_kegg_genes_absent_from_sgd_features_are_counted_not_dropped() -> None:
    resolver = _yeast_resolver(with_uniprot=False)
    report = BulkReport()
    list(
        kegg_annotation_rows(
            parse_kegg_list(_lines("kegg_list_sce.txt")),
            [],
            resolver,
            sources=_sources(),
            bulk_file=KEGG_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
        )
    )
    # `sce:YAL068C` and `sce:YJR009C` are in the KEGG fixture and not in the features fixture.
    assert report.resolution.total_failed == 2
    assert report.resolution.total_resolved == 10


def test_a_kegg_link_line_with_one_column_raises() -> None:
    with pytest.raises(BulkParseError, match="target column"):
        list(parse_kegg_pathway_links(["sce:YMR303C"]))


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


def _gaf_rows(resolver: IdentifierResolver, report: BulkReport) -> list[GeneAnnotationRow]:
    return list(
        gaf_annotation_rows(
            GafReader(_lines("gene_association.sgd.gaf")),
            resolver,
            sources=_sources(),
            source_id="sgd_go",
            bulk_file=GAF_FILE,
            retrieved_at=RETRIEVED_AT,
            report=report,
            on_unknown_evidence="collect",
        )
    )


def test_gene_groups_are_created_from_sgd_features_and_never_clobbered(
    conn: sqlite3.Connection,
) -> None:
    _seed_gene_groups(conn, "YMR303C")
    conn.execute(
        "UPDATE gene_group SET evidence = 'hand curated by a person', membership_method = "
        "'curated' WHERE id = 'YAA:GG:ymr303c'"
    )
    conn.commit()

    result = load_gene_groups_from_sgd_features(
        conn, _features(), bulk_file=FEATURES_FILE, retrieved_at=RETRIEVED_AT
    )

    assert result.features_seen == 10  # the 10 ORFs; not the CDS sub-feature, not the ARS
    assert result.groups_inserted == 9
    assert result.groups_already_present == 1
    kept = conn.execute(
        "SELECT evidence, membership_method FROM gene_group WHERE id = 'YAA:GG:ymr303c'"
    ).fetchone()
    assert kept[0] == "hand curated by a person"
    assert kept[1] == "curated"

    # Idempotent.
    again = load_gene_groups_from_sgd_features(
        conn, _features(), bulk_file=FEATURES_FILE, retrieved_at=RETRIEVED_AT
    )
    assert again.groups_inserted == 0
    assert conn.execute("SELECT COUNT(*) FROM gene_group").fetchone()[0] == 10


def test_a_double_load_does_not_duplicate_a_single_row(conn: sqlite3.Connection) -> None:
    load_gene_groups_from_sgd_features(
        conn, _features(), bulk_file=FEATURES_FILE, retrieved_at=RETRIEVED_AT
    )
    resolver = _yeast_resolver()
    rows = _gaf_rows(resolver, BulkReport())
    assert rows

    first = load_gene_annotations(conn, rows)
    count_after_first = conn.execute("SELECT COUNT(*) FROM gene_annotation").fetchone()[0]
    second = load_gene_annotations(conn, rows)
    count_after_second = conn.execute("SELECT COUNT(*) FROM gene_annotation").fetchone()[0]

    assert first.rows_inserted > 0
    assert count_after_second == count_after_first
    assert second.rows_inserted == 0
    assert second.rows_left_alone == second.rows_offered


def test_a_bulk_load_does_not_clobber_a_curated_row(conn: sqlite3.Connection) -> None:
    """The merge rule: bulk adds what is missing and argues with nothing already there."""
    _seed_gene_groups(conn, "YOL086C")
    curated = GeneAnnotationRow(
        gene_group_id="YAA:GG:yol086c",
        source="sgd_go",
        term_id="GO:0005737",
        term_label="curated by hand",
        term_namespace="cellular_component",
        evidence_code="IBA",
        reaction_id=None,
        pathway_id=None,
        source_url="https://www.yeastgenome.org/locus/YOL086C",
        source_version=None,
        retrieved_at="2026-01-01T00:00:00Z",
        zone="R",
        evidence="a curator read the paper and wrote this",
        confidence="high",  # deliberately ABOVE the IBA default of 'medium'
    )
    write_gene_annotation(conn, curated)
    conn.commit()

    resolver = _yeast_resolver()
    result = load_gene_annotations(conn, _gaf_rows(resolver, BulkReport()))

    row = conn.execute(
        "SELECT term_label, evidence, confidence, retrieved_at FROM gene_annotation "
        "WHERE gene_group_id = 'YAA:GG:yol086c' AND term_id = 'GO:0005737'"
    ).fetchall()
    assert len(row) == 1
    assert row[0][0] == "curated by hand"
    assert row[0][1] == "a curator read the paper and wrote this"
    assert row[0][2] == "high"  # the curator's override survived the sweep
    assert row[0][3] == "2026-01-01T00:00:00Z"
    assert result.rows_left_alone >= 1


def test_refresh_mode_updates_in_place_when_a_caller_deliberately_asks(
    conn: sqlite3.Connection,
) -> None:
    _seed_gene_groups(conn, "YOL086C")
    write_gene_annotation(
        conn,
        GeneAnnotationRow(
            gene_group_id="YAA:GG:yol086c",
            source="sgd_go",
            term_id="GO:0005737",
            term_label="stale",
            term_namespace="cellular_component",
            evidence_code="IBA",
            reaction_id=None,
            pathway_id=None,
            source_url=None,
            source_version=None,
            retrieved_at="2026-01-01T00:00:00Z",
            zone="R",
            evidence="stale",
            confidence="high",
        ),
    )
    conn.commit()

    resolver = _yeast_resolver()
    result = load_gene_annotations(conn, _gaf_rows(resolver, BulkReport()), on_conflict="refresh")

    label = conn.execute(
        "SELECT term_label FROM gene_annotation WHERE gene_group_id = 'YAA:GG:yol086c' "
        "AND term_id = 'GO:0005737'"
    ).fetchone()[0]
    assert label != "stale"
    assert result.rows_refreshed == result.rows_offered
    assert result.rows_inserted == 0


def test_rows_for_a_gene_group_this_database_does_not_have_are_counted_not_inserted(
    conn: sqlite3.Connection,
) -> None:
    _seed_gene_groups(conn, "YOL086C")  # and nothing else
    resolver = _yeast_resolver()
    report = BulkReport()

    result = load_gene_annotations(conn, _gaf_rows(resolver, report), report=report)

    assert result.gene_groups_absent > 0
    assert sum(report.gene_group_absent.values()) == result.gene_groups_absent
    assert "gene groups absent from this database" in report.summary()
    stored = conn.execute("SELECT DISTINCT gene_group_id FROM gene_annotation").fetchall()
    assert {row[0] for row in stored} == {"YAA:GG:yol086c"}


def test_every_bulk_row_is_zone_r(conn: sqlite3.Connection) -> None:
    """`gene_annotation` rows written by an importer are exactly what a source reported."""
    load_gene_groups_from_sgd_features(
        conn, _features(), bulk_file=FEATURES_FILE, retrieved_at=RETRIEVED_AT
    )
    resolver = _yeast_resolver(with_kegg=True)
    report = BulkReport()
    rows: list[GeneAnnotationRow] = []
    rows += _gaf_rows(resolver, report)
    rows += sgd_feature_annotation_rows(
        _features(),
        resolver,
        sources=_sources(),
        bulk_file=FEATURES_FILE,
        retrieved_at=RETRIEVED_AT,
        report=report,
    )
    rows += uniprot_annotation_rows(
        _uniprot(),
        resolver,
        sources=_sources(),
        bulk_file=UNIPROT_FILE,
        retrieved_at=RETRIEVED_AT,
        report=report,
    )
    rows += kegg_annotation_rows(
        parse_kegg_list(_lines("kegg_list_sce.txt")),
        parse_kegg_pathway_links(_lines("kegg_link_pathway_sce.txt")),
        resolver,
        sources=_sources(),
        bulk_file=KEGG_FILE,
        retrieved_at=RETRIEVED_AT,
        report=report,
    )

    assert all(row.zone == "R" for row in rows)
    assert all(row.evidence for row in rows)
    assert {row.source for row in rows} == {
        "sgd_go",
        "sgd_phenotype",
        "uniprot",
        "interpro",
        "pfam",
        "kegg",
    }

    result = load_gene_annotations(conn, rows, report=report)
    assert result.rows_inserted > 0
    assert conn.execute("SELECT COUNT(*) FROM gene_annotation WHERE zone != 'R'").fetchone()[0] == 0
    # Idempotent across all four sources at once, not just the GAF.
    assert load_gene_annotations(conn, rows).rows_inserted == 0


def test_an_evidence_code_is_never_written_for_a_non_go_source(conn: sqlite3.Connection) -> None:
    """schema.sql's CHECK enforces this; the test proves the bulk parsers never provoke it."""
    load_gene_groups_from_sgd_features(
        conn, _features(), bulk_file=FEATURES_FILE, retrieved_at=RETRIEVED_AT
    )
    resolver = _yeast_resolver()
    rows = list(
        uniprot_annotation_rows(
            _uniprot(),
            resolver,
            sources=_sources(),
            bulk_file=UNIPROT_FILE,
            retrieved_at=RETRIEVED_AT,
            report=BulkReport(),
        )
    )
    assert all(row.evidence_code is None for row in rows)
    load_gene_annotations(conn, rows)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM gene_annotation WHERE evidence_code IS NOT NULL "
            "AND source NOT IN ('sgd_go', 'uniprot_goa')"
        ).fetchone()[0]
        == 0
    )


def test_open_annotation_file_reads_a_plain_file(tmp_path: Path) -> None:
    target = tmp_path / "sample.tab"
    target.write_text("a\tb\n", encoding="utf-8")
    with open_annotation_file(target) as handle:
        assert handle.read() == "a\tb\n"


def test_open_annotation_file_gunzips_a_gz(tmp_path: Path) -> None:
    import gzip as gzip_module

    target = tmp_path / "sample.tab.gz"
    with gzip_module.open(target, "wt", encoding="utf-8") as handle:
        handle.write("!gaf-version: 2.2\n")
    with open_annotation_file(target) as handle:
        assert GafReader(handle).header.gaf_version == "2.2"
