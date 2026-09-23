"""Tests for `fermdb.query.genome_browser` — the gene browser's reader.

The properties pinned here are the ones that a 6,600-gene atlas makes load-bearing and a
36-gene one hides completely:

* **`total_matching` is a count, not a page length.** The whole reason it exists is that a UI
  rendering `rows.length` says "50 genes" when it means "the first 50 of 4,812". A regression
  here is invisible on a small fixture and wrong on a real one, so the fixture is deliberately
  larger than the page.
* **One grouped query, not one per gene.** The annotation count is the obvious N+1 trap. The
  query count is measured with `set_trace_callback` and asserted to be the *same* for a 4-row
  atlas and a 60-row one — which is a property no amount of reading the code guarantees.
* **A missing column degrades, it does not raise.** `seqid`, `biotype`, `locus_tag` and
  `description` are landing on `gene` in a migration written in parallel with this module. Both
  states are tested, because a browser that only works after the migration and one that only
  works before it are the same bug.
* **Chromosome II sorts after chromosome I and before chromosome XI.** Roman numerals do not
  sort as text and accessions do not sort as chromosomes to anyone reading the page.
* **A filter that cannot be served is reported, never dropped.** A bookmarked `?biotype=tRNA`
  against a schema without the column must not answer with all 6,600 genes.

Everything runs against an in-memory database. The live atlas is being written to by other
processes while this suite runs, and a test that reads it tests whatever happened to be curated
this week.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import genome_browser as gb

# The two chromosomes the small fixture places genes on, plus one it does not, so an empty track
# is exercised alongside populated ones.
CHR_I = "NC_001133.9"
CHR_II = "NC_001134.8"
CHR_IV = "NC_001136.10"


#: The columns the browser adapts to. Named here as well as in the module under test so that a
#: migration renaming one of them fails these tests rather than passing them against a schema
#: that no longer exists.
NEW_COLUMNS = ("seqid", "biotype", "locus_tag", "description")


def _present(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(gene)")}


def _with_new_columns(conn: sqlite3.Connection) -> None:
    """The post-migration shape, whether or not `schema.sql` already carries it.

    Written to converge rather than to assume, because these columns landed in `schema.sql`
    *while this module was being written*. A fixture that assumes either side of that migration
    breaks on the other, and both sides are real: `schema.sql` has them now, deployed atlases do
    not yet.
    """
    present = _present(conn)
    for column in NEW_COLUMNS:
        if column not in present:
            conn.execute(f"ALTER TABLE gene ADD COLUMN {column} TEXT")


def _without_new_columns(conn: sqlite3.Connection) -> None:
    """The pre-migration shape: what every already-deployed atlas still looks like.

    The indexes go first. SQLite refuses to drop a column an index still names, and the migration
    that added these columns also added `gene_by_position` and `gene_by_biotype` over them.
    """
    present = _present(conn)
    doomed = [c for c in NEW_COLUMNS if c in present]
    if not doomed:
        return
    for name, sql in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'gene'"
    ).fetchall():
        if sql and any(column in str(sql) for column in doomed):
            conn.execute(f"DROP INDEX {name}")
    for column in doomed:
        conn.execute(f"ALTER TABLE gene DROP COLUMN {column}")


def _seed(conn: sqlite3.Connection, *, genes: int = 6, with_new_columns: bool = True) -> None:
    conn.execute(
        "INSERT INTO organism (id, name, ncbi_taxid, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'Saccharomyces cerevisiae', 559292, 'R', 'ncbi', 'high')"
    )
    if with_new_columns:
        _with_new_columns(conn)
    else:
        _without_new_columns(conn)

    biotypes = ("protein_coding", "tRNA", "pseudogene")
    seqids = (CHR_I, CHR_II)
    for index in range(genes):
        group = f"YAA:GG:g{index}"
        conn.execute(
            "INSERT INTO gene_group (id, anchor_namespace, anchor_id, standard_name, scope, "
            "membership_method, zone, evidence, confidence) "
            "VALUES (?, 'sgd_systematic', ?, ?, 'species', 'anchor', 'R', 'seeded', 'high')",
            (group, f"YAL{index:03d}W", f"GEN{index}"),
        )
        columns = [
            "id",
            "organism_id",
            "assembly_accession",
            "systematic_name",
            "standard_name",
            "gene_group_id",
            "start_pos",
            "end_pos",
            "strand",
            "zone",
            "evidence",
            "confidence",
        ]
        values: list[object] = [
            f"YAA:GENE:g{index}",
            "YAA:ORG:sc",
            "GCF_000146045.2",
            f"YAL{index:03d}W",
            # Every third gene is unnamed, as ~1000 real ORFs are, so name ordering has to cope.
            None if index % 3 == 2 else f"GEN{index}",
            group,
            1_000 + index * 5_000,
            1_000 + index * 5_000 + (index + 1) * 300,
            1 if index % 2 == 0 else -1,
            "R",
            "seeded",
            "high",
        ]
        if with_new_columns:
            columns += ["seqid", "biotype", "locus_tag", "description"]
            values += [
                seqids[index % 2],
                biotypes[index % 3],
                f"YAL{index:03d}W",
                f"synthetic gene {index} for the browser fixture",
            ]
        holes = ", ".join("?" for _ in columns)
        conn.execute(f"INSERT INTO gene ({', '.join(columns)}) VALUES ({holes})", values)

        # Gene 0 gets three annotations from two sources, gene 1 one, the rest none — so an
        # annotation count that is really a row count and one that is really a gene count differ.
        if index == 0:
            terms = (("uniprot_goa", "GO:0001"), ("uniprot_goa", "GO:0002"), ("pfam", "PF0001"))
        elif index == 1:
            terms = (("kegg", "K0001"),)
        else:
            terms = ()
        for source, term in terms:
            conn.execute(
                "INSERT INTO gene_annotation (id, gene_group_id, source, term_id, term_label, "
                "zone, evidence, confidence) VALUES (?, ?, ?, ?, ?, 'R', 'seeded', 'high')",
                (f"YAA:ANNOT:{index}-{term}", group, source, term, f"label {term}"),
            )
    conn.commit()


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(IN_MEMORY)
    _seed(connection, genes=6)
    yield connection
    connection.close()


@pytest.fixture()
def legacy() -> Iterator[sqlite3.Connection]:
    """The same atlas *before* the pending migration lands."""
    connection = open_db(IN_MEMORY)
    _seed(connection, genes=6, with_new_columns=False)
    yield connection
    connection.close()


# ------------------------------------------------------------------ the reference karyotype


def test_the_reference_lengths_match_what_the_atlas_records_about_the_assembly() -> None:
    """`reference_sequence.evidence` says "R64 assembly, 17 sequences, 12157105 bases".

    That sentence is the only place the atlas states the size of the genome these constants
    describe, so it is the check. If R64 is ever replaced, this fails instead of the karyotype
    silently drawing chromosomes at the wrong scale.
    """
    assert len(gb.R64_SEQUENCES) == 17
    assert sum(ref.length for ref in gb.R64_SEQUENCES) == 12_157_105
    nuclear = [ref for ref in gb.R64_SEQUENCES if ref.kind == "nuclear"]
    assert len(nuclear) == 16
    assert sum(ref.length for ref in nuclear) == 12_071_326


def test_chromosome_two_sorts_after_one_and_before_eleven() -> None:
    """The failure this guards against is `["I", "II", "XI"]` ordering as `["I", "XI", "II"]`."""
    shuffled = [CHR_IV, "NC_001143.9", CHR_II, CHR_I, "NC_001224.1"]
    ordered = [gb.reference_for(s).label for s in sorted(shuffled, key=gb._natural_key)]  # type: ignore[union-attr]
    assert ordered == ["chrI", "chrII", "chrIV", "chrXI", "chrM"]


def test_accession_order_and_chromosome_order_coincide_for_r64() -> None:
    """`ORDER BY seqid` is the SQL for "position", and it is only correct because of this.

    R64's RefSeq accessions happen to sort in chromosome order, with the mitochondrion last. That
    is a property of this assembly, not a law, and the position ordering leans on it — so it is
    asserted here rather than assumed in a comment nobody re-reads.
    """
    accessions = [ref.accession for ref in gb.R64_SEQUENCES]
    assert sorted(accessions) == accessions


def test_a_sequence_is_recognised_by_accession_label_or_roman_numeral() -> None:
    for spelling in ("NC_001136.10", "NC_001136", "chrIV", "IV", "chromosome IV", "chriv"):
        ref = gb.reference_for(spelling)
        assert ref is not None and ref.label == "chrIV", spelling
    assert gb.reference_for("chrM") is gb.R64_SEQUENCES[-1]
    assert gb.reference_for("scaffold_7") is None
    assert gb.reference_for(None) is None


# ------------------------------------------------------------------ listing and totals


def test_total_matching_is_the_size_of_the_answer_not_the_size_of_the_page(
    conn: sqlite3.Connection,
) -> None:
    read = gb.list_genes(conn, limit=2)
    assert len(read.rows) == 2
    assert read.total_matching == 6
    payload = read.as_json()
    assert payload["count"] == 2
    assert payload["total_matching"] == 6
    assert payload["has_more"] is True


def test_the_last_page_says_there_is_no_more(conn: sqlite3.Connection) -> None:
    read = gb.list_genes(conn, limit=2, offset=4)
    assert read.as_json()["has_more"] is False
    assert read.page.truncated is False


def test_truncation_is_reported_separately_from_the_total(conn: sqlite3.Connection) -> None:
    """`truncated` is about this page; `total_matching` is about the match. Both, always."""
    read = gb.list_genes(conn, limit=3)
    assert read.page.truncated is True
    assert read.total_matching == 6


def test_filters_combine_and_the_total_follows_them(conn: sqlite3.Connection) -> None:
    read = gb.list_genes(conn, seqid=CHR_I, biotype="protein_coding", limit=50)
    assert read.total_matching == len(read.rows)
    for row in read.rows:
        assert row.seqid.unwrap() == CHR_I
        assert row.biotype.unwrap() == "protein_coding"
    # Same chromosome, no biotype filter: strictly more genes, which is what makes the AND real.
    assert gb.list_genes(conn, seqid=CHR_I).total_matching > read.total_matching


def test_a_chromosome_can_be_named_by_its_label_as_well_as_its_accession(
    conn: sqlite3.Connection,
) -> None:
    assert gb.list_genes(conn, seqid="chrI").total_matching == (
        gb.list_genes(conn, seqid=CHR_I).total_matching
    )


def test_search_covers_every_name_column_the_schema_has(conn: sqlite3.Connection) -> None:
    assert gb.list_genes(conn, q="GEN4").total_matching == 1
    assert gb.list_genes(conn, q="YAL004W").total_matching == 1
    assert gb.list_genes(conn, q="browser fixture").total_matching == 6
    assert "description" in gb.list_genes(conn, q="x").searched_columns


def test_the_search_says_it_is_a_substring_match(conn: sqlite3.Connection) -> None:
    """`search.py` labels its own technique for the same reason: LIKE is not retrieval, and a
    caller that mistakes one for the other over-trusts a recall it does not have."""
    technique = gb.list_genes(conn, q="GEN").technique
    assert "LIKE" in technique and "not a full-text or semantic index" in technique


def test_strand_accepts_the_spellings_a_url_carries(conn: sqlite3.Connection) -> None:
    plus = gb.list_genes(conn, strand="+").total_matching
    assert plus == gb.list_genes(conn, strand=1).total_matching == 3
    assert gb.list_genes(conn, strand="-").total_matching == 3
    with pytest.raises(ValueError, match="strand"):
        gb.list_genes(conn, strand="sideways")


def test_annotated_by_filters_without_redefining_the_annotation_count(
    conn: sqlite3.Connection,
) -> None:
    """Filtering to one source must not turn `annotation_count` into that source's count.

    The natural implementation — a second join on `gene_annotation` with the source predicate on
    it — makes gene 0 report 1 annotation instead of 3 while the filter is on. That reads as data
    changing under a filter, which is the most expensive kind of wrong.
    """
    read = gb.list_genes(conn, annotated_by="pfam")
    assert read.total_matching == 1
    assert read.rows[0].annotation_count == 3


def test_has_coordinates_splits_the_atlas_in_two(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE gene SET start_pos = NULL, end_pos = NULL WHERE id = 'YAA:GENE:g0'")
    assert gb.list_genes(conn, has_coordinates=True).total_matching == 5
    assert gb.list_genes(conn, has_coordinates=False).total_matching == 1
    placeless = gb.list_genes(conn, has_coordinates=False).rows[0]
    assert not placeless.start.is_known
    assert not placeless.location.is_known


def test_an_unknown_ordering_is_refused_with_the_options(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="order_by"):
        gb.list_genes(conn, order_by="by_vibes")


def test_ordering_by_length_orders_by_length_across_pages(conn: sqlite3.Connection) -> None:
    """Sorting the rows of a page in Python sorts the wrong rows — right on page 1, wrong after.

    So the check is that page 2 continues page 1's order rather than restarting it.
    """
    first = gb.list_genes(conn, order_by="length", limit=3)
    second = gb.list_genes(conn, order_by="length", limit=3, offset=3)
    lengths = [r.length.unwrap() for r in first.rows] + [r.length.unwrap() for r in second.rows]
    assert lengths == sorted(lengths, reverse=True)
    assert len(set(r.id for r in first.rows) & set(r.id for r in second.rows)) == 0


def test_ordering_by_name_does_not_lead_with_the_unnamed(conn: sqlite3.Connection) -> None:
    """`ORDER BY standard_name` puts every unnamed ORF first, which is not a name order."""
    names = [r.display_name for r in gb.list_genes(conn, order_by="name", limit=50).rows]
    assert names == sorted(names)
    assert names[0].startswith("GEN")


def test_ordering_by_annotations_puts_the_best_annotated_first(conn: sqlite3.Connection) -> None:
    counts = [r.annotation_count for r in gb.list_genes(conn, order_by="annotations").rows]
    assert counts == [3, 1, 0, 0, 0, 0]


def test_position_ordering_is_chromosome_then_coordinate(conn: sqlite3.Connection) -> None:
    rows = gb.list_genes(conn, order_by="position", limit=50).rows
    keys = [(r.seqid.unwrap(), r.start.unwrap()) for r in rows]
    assert keys == sorted(keys)


# ------------------------------------------------------------------ the N+1 trap


def _count_queries(conn: sqlite3.Connection, run: object) -> int:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        run()  # type: ignore[operator]
    finally:
        conn.set_trace_callback(None)
    return len(statements)


def test_listing_costs_the_same_number_of_queries_for_6_genes_as_for_60() -> None:
    """The N+1 trap, asserted rather than reasoned about.

    An annotation count fetched per row is correct, invisible in review, and 6,600 queries on a
    real page load. Measuring the statement count on two atlases of different sizes is the only
    check that actually rules it out.
    """
    small = open_db(IN_MEMORY)
    _seed(small, genes=6)
    large = open_db(IN_MEMORY)
    _seed(large, genes=60)
    try:
        small_queries = _count_queries(small, lambda: gb.list_genes(small, limit=50))
        large_queries = _count_queries(large, lambda: gb.list_genes(large, limit=50))
        assert small_queries == large_queries
        # One PRAGMA, one COUNT, one page. The COUNT goes through `scalar` -> `one` -> `page`,
        # so it is a single statement; the ceiling leaves room for that without leaving room
        # for a loop.
        assert large_queries <= 4
    finally:
        small.close()
        large.close()


def test_every_row_carries_its_annotation_count_from_that_one_query(
    conn: sqlite3.Connection,
) -> None:
    by_id = {row.id: row.annotation_count for row in gb.list_genes(conn, limit=50).rows}
    assert by_id["YAA:GENE:g0"] == 3
    assert by_id["YAA:GENE:g1"] == 1
    assert by_id["YAA:GENE:g2"] == 0


# ------------------------------------------------------------------ facets


def test_facets_count_genes_per_option(conn: sqlite3.Connection) -> None:
    read = gb.facets(conn)
    by_key = {facet.key: facet for facet in read.facets}
    assert by_key["biotype"].available is True
    assert dict((v.key, v.count) for v in by_key["biotype"].values) == {
        "protein_coding": 2,
        "tRNA": 2,
        "pseudogene": 2,
    }
    assert read.totals["genes"] == 6
    assert read.totals["with_annotation"] == 2
    assert read.totals["without_annotation"] == 4


def test_the_chromosome_facet_is_in_chromosome_order(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE gene SET seqid = ? WHERE id = 'YAA:GENE:g0'", ("NC_001143.9",))
    facet = next(f for f in gb.facets(conn).facets if f.key == "seqid")
    assert [v.label for v in facet.values] == ["chrI", "chrII", "chrXI"]


def test_facet_counts_narrow_under_the_other_active_filters(conn: sqlite3.Connection) -> None:
    """A rail showing atlas-wide counts beside a result set of 251 answers a question nobody
    asked. Every count is "what clicking this would leave", under everything else already on."""
    coding = gb.facets(conn, biotype="protein_coding")
    unfiltered = next(f for f in gb.facets(conn).facets if f.key == "seqid")
    narrowed = next(f for f in coding.facets if f.key == "seqid")
    assert sum(v.count for v in unfiltered.values) == 6
    assert sum(v.count for v in narrowed.values) == 2
    # The totals stay atlas-wide: they are the denominator "2 of 6" is measured against, and
    # narrowing them would collapse it into "2 of 2".
    assert coding.totals["genes"] == 6


def test_a_facet_leaves_its_own_filter_out_of_its_own_counts(conn: sqlite3.Connection) -> None:
    """Otherwise selecting `biotype=tRNA` leaves the Biotype panel showing tRNA and nothing else,
    and there is no way to switch to protein_coding without clearing first."""
    facet = next(f for f in gb.facets(conn, biotype="tRNA").facets if f.key == "biotype")
    assert {v.key for v in facet.values} == {"protein_coding", "tRNA", "pseudogene"}


def test_facets_cost_the_same_number_of_queries_whatever_the_atlas_size() -> None:
    small = open_db(IN_MEMORY)
    _seed(small, genes=6)
    large = open_db(IN_MEMORY)
    _seed(large, genes=60)
    try:
        assert _count_queries(small, lambda: gb.facets(small)) == _count_queries(
            large, lambda: gb.facets(large)
        )
    finally:
        small.close()
        large.close()


def test_an_annotation_source_facet_counts_genes_not_annotation_rows(
    conn: sqlite3.Connection,
) -> None:
    """Gene 0 holds two `uniprot_goa` terms. The facet must say 1 gene, not 2."""
    facet = next(f for f in gb.facets(conn).facets if f.key == "annotated_by")
    assert dict((v.key, v.count) for v in facet.values) == {
        "uniprot_goa": 1,
        "pfam": 1,
        "kegg": 1,
    }


# ------------------------------------------------------------------ the missing-column race


def test_a_missing_column_blocks_its_facet_instead_of_raising(legacy: sqlite3.Connection) -> None:
    read = gb.facets(legacy)
    by_key = {facet.key: facet for facet in read.facets}
    for key in ("seqid", "biotype"):
        assert by_key[key].available is False
        assert by_key[key].values == ()
        assert by_key[key].blocked_reason
    # The facets that never depended on the migration keep working.
    assert by_key["assembly"].available is True
    assert by_key["annotated_by"].values


def test_listing_still_works_without_the_new_columns(legacy: sqlite3.Connection) -> None:
    read = gb.list_genes(legacy, limit=50)
    assert read.total_matching == 6
    assert set(read.missing_columns) == {"seqid", "biotype", "locus_tag", "description"}
    row = read.rows[0]
    for value in (row.seqid, row.biotype, row.locus_tag, row.description):
        assert not value.is_known
        assert value.absence is not None and value.absence.value == "not_recorded"
    # Coordinates are held even when the sequence they are on is not, and the location string
    # says as much rather than inventing a chromosome for them.
    assert row.start.is_known
    assert ":" not in row.location.unwrap()


def test_search_drops_the_columns_that_do_not_exist_and_says_which(
    legacy: sqlite3.Connection,
) -> None:
    read = gb.list_genes(legacy, q="GEN0")
    assert "description" not in read.searched_columns
    assert "locus_tag" not in read.searched_columns
    assert read.total_matching == 1


def test_an_unservable_filter_is_reported_not_silently_dropped(
    legacy: sqlite3.Connection,
) -> None:
    """A bookmarked `?biotype=tRNA` must not come back as "all 6 genes, filter applied"."""
    read = gb.list_genes(legacy, biotype="tRNA")
    assert read.total_matching == 6
    assert read.ignored_filters == ("biotype",)
    assert "biotype" not in read.filters
    payload = read.as_json()
    assert "biotype" in payload["ignored_filters"]
    assert "migration" in payload["missing_columns"]["seqid"] or payload["missing_columns"]["seqid"]


def test_ordering_by_position_survives_the_absent_seqid(legacy: sqlite3.Connection) -> None:
    starts = [r.start.unwrap() for r in gb.list_genes(legacy, order_by="position", limit=50).rows]
    assert starts == sorted(starts)


# ------------------------------------------------------------------ the karyotype


def test_the_karyotype_draws_all_seventeen_sequences_including_empty_ones(
    conn: sqlite3.Connection,
) -> None:
    read = gb.karyotype(conn)
    assert read.available is True
    assert [t.label for t in read.tracks[:3]] == ["chrI", "chrII", "chrIII"]
    assert len(read.tracks) == 17
    empty = next(t for t in read.tracks if t.label == "chrIII")
    assert empty.gene_count == 0 and empty.length == 316_620


def test_each_track_is_binned_at_the_same_number_of_bases(conn: sqlite3.Connection) -> None:
    """A fixed bin *count* would make one bin 2.3 kb on chrI and 15 kb on chrIV, and the two
    tracks would stop being comparable at exactly the moment they are drawn side by side."""
    read = gb.karyotype(conn, bin_width=10_000)
    for track in read.tracks:
        assert len(track.bins) == track.length // 10_000 + 1
    assert sum(t.gene_count for t in read.tracks) == 6


def test_the_karyotype_ignores_the_chromosome_filter_but_honours_the_others(
    conn: sqlite3.Connection,
) -> None:
    read = gb.karyotype(conn, biotype="protein_coding")
    assert sum(t.gene_count for t in read.tracks) == 2
    assert len({t.label for t in read.tracks}) == 17


def test_a_gene_with_no_coordinates_is_counted_as_unplaced(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE gene SET start_pos = NULL, end_pos = NULL WHERE id = 'YAA:GENE:g0'")
    read = gb.karyotype(conn)
    assert read.unplaced_genes == 1
    assert sum(t.gene_count for t in read.tracks) == 5


def test_an_unrecognised_sequence_gets_a_track_whose_length_is_flagged_as_a_bound(
    conn: sqlite3.Connection,
) -> None:
    conn.execute("UPDATE gene SET seqid = 'scaffold_7' WHERE id = 'YAA:GENE:g0'")
    read = gb.karyotype(conn)
    extra = next(t for t in read.tracks if t.seqid == "scaffold_7")
    assert extra.length_is_reference is False
    assert extra.gene_count == 1


def test_without_seqid_the_karyotype_is_blocked_but_still_drawn(
    legacy: sqlite3.Connection,
) -> None:
    """The empty state is the state this atlas is in today, so it has to be a designed one.

    All 17 tracks, no genes on any of them, every gene counted as unplaced, and a reason.
    """
    read = gb.karyotype(legacy)
    assert read.available is False
    assert read.blocked_reason
    assert len(read.tracks) == 17
    assert read.unplaced_genes == 6
    assert sum(t.gene_count for t in read.tracks) == 0


# ------------------------------------------------------------------ one gene's position


def test_a_gene_reads_its_own_position_and_its_neighbours(conn: sqlite3.Connection) -> None:
    read = gb.read_position(conn, "YAA:GENE:g2")
    assert read is not None
    assert read.chromosome.unwrap() == "chrI"
    assert read.sequence_length.unwrap() == 230_218
    assert read.length.unwrap() == 900
    assert "chrI:" in read.location.unwrap()
    # Genes on the same sequence within the window, and nothing from the other chromosome.
    assert {n.id for n in read.neighbours} <= {"YAA:GENE:g0", "YAA:GENE:g2", "YAA:GENE:g4"}
    assert read.gene_id in {n.id for n in read.neighbours}


def test_a_gene_resolves_by_systematic_or_standard_name(conn: sqlite3.Connection) -> None:
    for identifier in ("YAA:GENE:g1", "YAL001W", "gen1"):
        read = gb.read_position(conn, identifier)
        assert read is not None and read.gene_id == "YAA:GENE:g1", identifier
    assert gb.read_position(conn, "nothing-like-this") is None


def test_a_position_read_without_the_migration_is_absences_not_an_error(
    legacy: sqlite3.Connection,
) -> None:
    read = gb.read_position(legacy, "YAA:GENE:g1")
    assert read is not None
    assert not read.seqid.is_known
    assert not read.chromosome.is_known
    assert read.start.is_known
    assert read.neighbours == ()
    assert set(read.missing_columns) == {"seqid", "biotype", "locus_tag", "description"}


def test_strand_zero_is_recorded_not_missing(conn: sqlite3.Connection) -> None:
    """0 is `schema.sql`'s recorded "no strand". Rendering it as "not recorded" would claim the
    source stayed silent when it said something."""
    conn.execute("UPDATE gene SET strand = 0 WHERE id = 'YAA:GENE:g0'")
    row = next(r for r in gb.list_genes(conn, limit=50).rows if r.id == "YAA:GENE:g0")
    assert row.strand.is_known and row.strand.unwrap() == "unstranded"


def test_an_absent_value_never_serialises_a_value_key(legacy: sqlite3.Connection) -> None:
    """The contract from `values.py`: an absence has no `value` key, so `v.value ?? "-"` cannot
    silently collapse "not recorded" into a default on the client."""
    payload = gb.list_genes(legacy, limit=1).as_json()
    biotype = payload["rows"][0]["biotype"]
    assert "value" not in biotype
    assert biotype["absent"] == "not_recorded"
    assert biotype["display"] == "not recorded"


# ------------------------------------------------------------------ the endpoints


def _api_client(tmp_path: object, monkeypatch: object, *, migrated: bool = True) -> object:
    """A TestClient over a temp atlas, so the router's wiring is tested and not just the reader.

    A file rather than `:memory:`, because `api/deps.py` opens its own read-only connection by
    path — which is the guarantee being relied on and therefore the one worth exercising.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from fermdb.api.app import create_app

    atlas = tmp_path / "atlas.sqlite3"  # type: ignore[operator]
    connection = open_db(atlas)
    _seed(connection, genes=6, with_new_columns=migrated)
    connection.close()
    monkeypatch.setenv("FERMDB_DB_FILE", str(atlas))  # type: ignore[attr-defined]
    app = create_app()
    client = TestClient(app)
    client.fastapi_app = app  # type: ignore[attr-defined]
    return client


def test_the_router_is_registered_and_every_gene_route_is_a_get(
    tmp_path: object, monkeypatch: object
) -> None:
    """PLAN.md D.3: no write path exists.

    Read off the OpenAPI schema rather than by walking `app.routes`, and that is not a style
    choice. FastAPI 0.141 includes a router as a single lazy `_IncludedRouter` object with no
    `.path` and no `.methods`, so a walk of `app.routes` sees *nothing* from any `include_router`
    call — `tests/test_api.py`'s non-GET guard currently inspects four docs endpoints and
    `/api/health` and passes vacuously. The OpenAPI schema is what the app actually serves, on
    every version.
    """
    client = _api_client(tmp_path, monkeypatch)
    paths = client.fastapi_app.openapi()["paths"]  # type: ignore[attr-defined]
    ours = {
        path: sorted(methods) for path, methods in paths.items() if path.startswith("/api/genes")
    }
    assert set(ours) == {
        "/api/genes",
        "/api/genes/facets",
        "/api/genes/karyotype",
        "/api/genes/{gene_id}",
    }
    assert all(methods == ["get"] for methods in ours.values()), ours
    # And nothing anywhere else on the app writes either, for the same reason.
    assert all(set(methods) <= {"get"} for methods in paths.values()), {
        p: sorted(m) for p, m in paths.items() if set(m) - {"get"}
    }


def test_facets_and_karyotype_are_not_swallowed_by_the_gene_id_route(
    tmp_path: object, monkeypatch: object
) -> None:
    """`/genes/{gene_id:path}` matches anything. Declared after the two literal paths, it must
    not take them — if it ever does, the facets endpoint starts returning a 404 for a gene."""
    client = _api_client(tmp_path, monkeypatch)
    assert "facets" in client.get("/api/genes/facets").json()  # type: ignore[attr-defined]
    assert client.get("/api/genes/karyotype").json()["available"] is True  # type: ignore[attr-defined]


def test_an_unknown_ordering_is_a_422_carrying_the_options(
    tmp_path: object, monkeypatch: object
) -> None:
    client = _api_client(tmp_path, monkeypatch)
    response = client.get("/api/genes?order_by=by_vibes")  # type: ignore[attr-defined]
    assert response.status_code == 422
    assert "position" in response.json()["detail"]


def test_the_single_gene_endpoint_keeps_absent_sections_and_adds_position(
    tmp_path: object, monkeypatch: object
) -> None:
    """The positional data is added to the existing payload, never in place of it. Losing
    `absent_sections` would make the page look more complete while saying less."""
    client = _api_client(tmp_path, monkeypatch)
    body = client.get("/api/genes/YAA:GENE:g1").json()  # type: ignore[attr-defined]
    assert set(body["absent_sections"]) >= {"expression", "interactions", "regulators"}
    assert body["annotations"]
    assert body["position"]["chromosome"]["value"] == "chrII"
    assert client.get("/api/genes/no-such-gene").status_code == 404  # type: ignore[attr-defined]


def test_the_endpoints_do_not_500_on_an_unmigrated_atlas(
    tmp_path: object, monkeypatch: object
) -> None:
    """The race this module was written around: deployed atlases predate the columns.

    A 500 here would take the whole Annotations page down, which is strictly worse than a page
    that says which facet is waiting on a migration.
    """
    client = _api_client(tmp_path, monkeypatch, migrated=False)
    for url in ("/api/genes", "/api/genes/facets", "/api/genes/karyotype", "/api/genes/GEN1"):
        assert client.get(url).status_code == 200, url  # type: ignore[attr-defined]
    karyotype = client.get("/api/genes/karyotype").json()  # type: ignore[attr-defined]
    assert karyotype["available"] is False and len(karyotype["tracks"]) == 17
