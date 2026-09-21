"""Tests for `fermdb.literature.rescreen`: the full-text re-screen for E1.

No test here reaches the network (the screen makes no requests at all) and none reads the
developer's live corpus: every test builds its own publications, its own stored bytes under
`tmp_path`, and its own pattern file where the shipped one is not the thing under test.

The invariants worth naming, because they are the ones a future change would break quietly:

* **The screen writes nothing to the database.** It cannot -- `screening_record.family` is NOT
  NULL and both run-id columns are NOT NULL foreign keys into `search_run`, and a full-text screen
  ran no query. `test_rescreen_writes_no_rows_to_the_database` is what stops someone "fixing" that
  with a synthetic `search_run` row, which would make that table mean two things and corrupt
  `fermdb literature status`'s drift arithmetic.
* **Nothing is admitted.** Every proposal carries `admitted_criterion=None`.
* **Every proposal says what it was conditioned on.** The screen can only see stored bytes, and
  stored bytes skew open-access; a row that does not carry its own licence misrepresents how the
  paper was found.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from fermdb import cli
from fermdb.config import Settings
from fermdb.db import open_db
from fermdb.literature.rescreen import (
    PATTERNS_FILE,
    PROVENANCE,
    SCHEMA_CHANGE_REQUIRED,
    RescreenError,
    load_rescreen_patterns,
    proposal_document,
    rescreen,
    summary_lines,
    write_proposals,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"
REAL_PATTERNS = REPO_ROOT / "data" / "literature" / PATTERNS_FILE


# ---------------------------------------------------------------------------------------------
# Fixtures: an isolated atlas with its own stored bytes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """The repo's paths with the derived tier under `tmp_path`, so nothing touches the real
    `~/fermdb-data` and `literature_dir` still points at the committed pattern file."""
    return Settings.load(
        paths_file=PATHS_FILE,
        env={
            "FERMDB_DATA_DIR": str(tmp_path / "derived"),
            "FERMDB_SOURCE_ROOT": str(tmp_path / "source"),
        },
    )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    database = open_db(tmp_path / "rescreen.sqlite3")
    database.execute(
        "INSERT INTO search_run (id, family, db, term, started_at, query_families_version) "
        "VALUES ('RUN', 'isobutanol_all', 'pubmed', 'isobutanol[tiab]', '2026-09-22T00:00:00Z', 2)"
    )
    database.commit()
    yield database
    database.close()


def _add(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    publication_id: str,
    text: str,
    tier: str = "isobutanol",
    oa_status: str = "gold",
    text_mining_allowed: str | None = "yes",
    store_bytes: bool = True,
    title: str = "A paper",
) -> None:
    """One publication, one screening row in `tier`, and (optionally) its stored full text."""
    conn.execute(
        "INSERT INTO publication (id, doi, pmid, title, year, journal, zone, evidence, "
        "confidence) VALUES (?, ?, ?, ?, 2020, 'J', 'R', 'test fixture', 'unverified')",
        (publication_id, publication_id.removeprefix("doi:"), "1", title),
    )
    conn.execute(
        "INSERT INTO screening_record (id, publication_id, family, first_seen_run_id, "
        "last_seen_run_id, triage_state, product_tier, default_disposition, review_state, zone) "
        "VALUES (?, ?, 'fam', 'RUN', 'RUN', 'included', ?, "
        "CASE ? WHEN 'ethanol' THEN 'exclude_unless_admitted' ELSE 'include_unless_excluded' END, "
        "'proposed', 'H')",
        (f"SCR:{publication_id}:{tier}", publication_id, tier, tier),
    )
    if store_bytes:
        relative = Path("fulltext") / (publication_id.replace("/", "_").replace(":", "_") + ".txt")
        target = settings.data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        conn.execute(
            "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, "
            "text_mining_allowed, resolved_via, storage_state, content_path, checksum_sha256, "
            "media_type, source_url, retrieved_at, zone) "
            "VALUES (?, ?, ?, ?, ?, 'europepmc', 'stored_fulltext', ?, ?, 'text/plain', "
            "'https://example.invalid/x', '2026-09-22T00:00:00Z', 'R')",
            (
                f"FA:{publication_id}",
                publication_id,
                publication_id.removeprefix("doi:"),
                oa_status,
                text_mining_allowed,
                str(relative),
                f"sha-{publication_id}",
            ),
        )
    conn.commit()


def _paper(*, abstract: str, methods: str = "", results: str = "", discussion: str = "") -> str:
    """A minimal document the real sectioner recognises, so tests exercise the real split."""
    return (
        "A Title Block\n\n"
        f"Abstract\n{abstract}\n\n"
        f"Methods\n{methods}\n\n"
        f"Results\n{results}\n\n"
        f"Discussion\n{discussion}\n"
    )


#: A strain-table line of the kind that makes E1 a full-text problem: the genotype is in Methods,
#: and the abstract says nothing about Pdc at all.
_STRAIN_TABLE = (
    "Strains used in this study. IMZ500 MATa ura3-52 pdc1::loxP pdc5::loxP pdc6::loxP. "
    "The pdc1 pdc5 pdc6 triple deletant was grown on glucose. PDC activity was assayed."
)


# ---------------------------------------------------------------------------------------------
# The shipped pattern file
# ---------------------------------------------------------------------------------------------


def test_the_shipped_pattern_file_loads_and_defines_exactly_e1() -> None:
    """E1 is scoped alone on purpose: it is the only B.3 criterion whose admission test is a
    genotype, and a genotype is a methods fact. A criterion appearing here without that argument
    would be widening the screen for the wrong reason."""
    patterns = load_rescreen_patterns(REAL_PATTERNS)
    assert patterns.criteria_names() == ("E1",)
    e1 = patterns["E1"]
    assert e1.label == "competing_sink"
    assert e1.min_mentions == 3
    assert e1.sections == ("methods", "results", "results_and_discussion")


@pytest.mark.parametrize(
    "spelling",
    [
        "pdc1Δ",  # GREEK CAPITAL LETTER DELTA -- the notation most papers use
        "pdc1∆",  # INCREMENT -- visually identical, compares unequal, and used for real
        "pdc1δ",  # GREEK SMALL LETTER DELTA
        "Δpdc1",
        "∆pdc1",
        "pdc1delta",
        "pdc1::loxP",
        "PDC1::KanMX",
    ],
)
def test_every_delta_spelling_publishers_actually_use_is_matched(spelling: str) -> None:
    """The three delta code points are the whole reason this is parameterised.

    U+0394 (Δ), U+2206 (∆) and U+03B4 (δ) render identically and compare unequal. A pattern set
    matching only U+0394 missed 10.1186/s12934-016-0449-z, whose stored text spells its genotype
    `pdc1∆ pdc5∆ pdc6∆` with U+2206 -- a paper E1_QUERY_BLINDNESS.md §4.1 names by hand and that
    the first draft of this screen silently did not find. `pdc1::loxP` is here for the opposite
    reason: it has no reachable PubMed `[tiab]` spelling at all, so it is only ever findable in
    full text.
    """
    genotype = load_rescreen_patterns(REAL_PATTERNS)["E1"].genotype
    assert genotype.search(f"the strain carries {spelling} and grows slowly")


def test_a_mention_inside_a_delta_token_is_still_counted() -> None:
    """`\\b` fails on the left of `pdc` in `Δpdc1`, because Δ is a word character to Python's
    `re` under Unicode. Anchoring the mention pattern that way under-counted a real candidate
    below the min_mentions gate while looking perfectly correct."""
    mention = load_rescreen_patterns(REAL_PATTERNS)["E1"].mention
    assert mention.search("Δpdc1")
    assert len(mention.findall("Δpdc1, Δpdc5 and pdc6")) == 3


def test_a_word_containing_pdc_is_not_a_mention() -> None:
    """`ipdC` is indolepyruvate decarboxylase and is not a yeast PDC gene."""
    mention = load_rescreen_patterns(REAL_PATTERNS)["E1"].mention
    assert not mention.search("the ipdCx locus")


def test_the_digest_is_of_the_file_that_was_actually_read(tmp_path: Path) -> None:
    """A screen is Zone H only if it is reconstructible from a recorded input, and "the pattern
    file" is not a recorded input unless the run says which one."""
    first = load_rescreen_patterns(REAL_PATTERNS)
    edited = tmp_path / PATTERNS_FILE
    edited.write_text(
        REAL_PATTERNS.read_text(encoding="utf-8").replace("min_mentions: 3", "min_mentions: 4"),
        encoding="utf-8",
    )
    second = load_rescreen_patterns(edited)
    assert second["E1"].min_mentions == 4
    assert second.digest != first.digest


def test_an_unknown_criterion_names_what_is_available_and_why() -> None:
    patterns = load_rescreen_patterns(REAL_PATTERNS)
    with pytest.raises(RescreenError) as exc:
        patterns["E4"]
    assert "E1" in str(exc.value)
    assert "abstract" in str(exc.value)


def test_a_criterion_outside_the_closed_vocabulary_is_refused(tmp_path: Path) -> None:
    path = tmp_path / PATTERNS_FILE
    path.write_text(
        yaml.safe_dump(
            {
                "criteria": [
                    {
                        "criterion": "E9",
                        "label": "invented",
                        "min_mentions": 1,
                        "sections": ["methods"],
                        "mention": ["pdc"],
                        "genotype": ["pdc1"],
                        "phrase": ["pdc"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RescreenError, match="unknown criterion"):
        load_rescreen_patterns(path)


def test_a_malformed_regex_is_refused_with_the_field_that_holds_it(tmp_path: Path) -> None:
    path = tmp_path / PATTERNS_FILE
    path.write_text(
        yaml.safe_dump(
            {
                "criteria": [
                    {
                        "criterion": "E1",
                        "label": "competing_sink",
                        "min_mentions": 1,
                        "sections": ["methods"],
                        "mention": ["pdc"],
                        "genotype": ["pdc1(unclosed"],
                        "phrase": ["pdc"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RescreenError, match="genotype"):
        load_rescreen_patterns(path)


# ---------------------------------------------------------------------------------------------
# The screen
# ---------------------------------------------------------------------------------------------


def test_a_methods_only_genotype_no_query_could_ever_reach_is_surfaced(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The case the whole module exists for: a paper that USES a Pdc-minus chassis to study
    something else. Its abstract has no Pdc token in any notation, so no `[tiab]` query can reach
    it; its Methods carries `pdc1::loxP`, which has no PubMed index term at all."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(
            abstract="We report improved isobutanol titers from an engineered strain.",
            methods=_STRAIN_TABLE,
            results="Isobutanol accumulated to 2 g/L.",
        ),
    )
    result = rescreen(conn, settings, criterion="E1")

    assert [c.publication_id for c in result.sectioned_candidates] == ["doi:10.1/chassis"]
    candidate = result.sectioned_candidates[0]
    assert candidate.genotype_section == "methods"
    assert candidate.abstract_visible is False
    assert result.unreachable_by_any_query == (candidate,)
    assert result.body_only == 1


def test_a_genotype_only_in_the_discussion_does_not_pass_the_section_gate(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """A regex over a whole paper hits every passing Discussion citation ("unlike Pdc-minus
    strains..."). The section restriction is what stops that being a candidate -- and both counts
    are kept, so the gate's effect stays visible rather than assumed."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/citing",
        text=_paper(
            abstract="A study of something else entirely.",
            results="Growth was normal.",
            discussion=(
                "Unlike pdc1Δ pdc5Δ pdc6Δ strains, which are C2 auxotrophs, "
                "our strain retained PDC activity."
            ),
        ),
    )
    result = rescreen(conn, settings, criterion="E1")

    assert [c.publication_id for c in result.candidates] == ["doi:10.1/citing"]
    assert result.candidates[0].genotype_section == "discussion"
    assert result.sectioned_candidates == ()


def test_a_paper_below_the_mention_floor_is_not_a_candidate(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/passing",
        text=_paper(
            abstract="Unrelated work.",
            methods="The strain pdc1Δ was obtained from a collection.",
        ),
    )
    result = rescreen(conn, settings, criterion="E1")
    assert result.candidates == ()
    # It is still counted as carrying body evidence: the floor is a precision gate, not a claim
    # that the paper says nothing.
    assert result.body_evidence == 1


def test_a_publication_already_in_the_ethanol_tier_is_not_in_the_pool(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The pool is publications screened into the isobutanol tier ONLY. One that already carries
    an ethanol-tier row has been through ethanol triage and needs no proposal from here."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/already",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
        tier="ethanol",
    )
    result = rescreen(conn, settings, criterion="E1")
    assert result.coverage.pool_size == 0
    assert result.candidates == ()


def test_a_publication_with_no_stored_bytes_is_outside_the_denominator(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/unstored",
        text="",
        store_bytes=False,
    )
    result = rescreen(conn, settings, criterion="E1")
    assert result.coverage.corpus_size == 1
    assert result.coverage.readable_size == 0
    assert result.coverage.pool_size == 0


def test_an_unreadable_paper_is_counted_never_silently_dropped(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """A paper the screen could not read is a hole in the screen. A hole nobody counted is
    indistinguishable from a paper with no evidence -- which is the exact failure mode
    E1_QUERY_BLINDNESS.md was written about."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/gone",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    (settings.data_dir / "fulltext").rename(settings.data_dir / "moved-away")

    result = rescreen(conn, settings, criterion="E1")
    assert result.coverage.pool_size == 1
    assert result.coverage.read_ok == 0
    assert [pub_id for pub_id, _why in result.coverage.unreadable] == ["doi:10.1/gone"]
    assert "UNREADABLE" in "\n".join(summary_lines(result))


def test_rescreen_writes_no_rows_to_the_database(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """The invariant that stops someone inventing a synthetic `search_run` to make the rows fit.

    `search_run` means "one E-utilities query was executed", and `queries.family_status` does
    drift arithmetic on its `hit_count`. A screen row in there would make the table mean two
    things. Until the migration in `SCHEMA_CHANGE_REQUIRED` exists, the honest number of rows this
    writes is zero.
    """
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        for table in ("search_run", "screening_record", "publication", "fulltext_asset")
    }
    rescreen(conn, settings, criterion="E1")
    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        for table in ("search_run", "screening_record", "publication", "fulltext_asset")
    }
    assert before == after


# ---------------------------------------------------------------------------------------------
# The proposal document
# ---------------------------------------------------------------------------------------------


def test_no_proposal_ever_claims_an_admission(conn: sqlite3.Connection, settings: Settings) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    document = proposal_document(rescreen(conn, settings, criterion="E1"))
    assert document["proposals"]
    for proposal in document["proposals"]:
        assert proposal["review_state"] == "proposed"
        assert proposal["triage_state"] == "needs_full_text"
        assert proposal["admitted_criterion"] is None
        assert proposal["candidate_criterion"] == "E1"
        assert proposal["provenance"] == PROVENANCE


def test_every_proposal_records_the_licence_its_selection_was_conditioned_on(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Only 28% of the corpus is readable and it skews open access. A row that does not say so
    turns B.3's "admitted against a stated criterion" into "admitted against a stated criterion,
    if we happened to be allowed to read it"."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
        oa_status="green",
        text_mining_allowed="unknown",
    )
    proposal = proposal_document(rescreen(conn, settings, criterion="E1"))["proposals"][0]
    assert proposal["selection_conditioned_on_licence"] == {
        "oa_status": "green",
        "text_mining_allowed": "unknown",
        "license": None,
    }


def test_the_document_carries_the_coverage_denominator_and_the_bias(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    _add(
        conn,
        settings,
        publication_id="doi:10.1/unstored",
        text="",
        store_bytes=False,
    )
    document = proposal_document(rescreen(conn, settings, criterion="E1"))
    coverage = document["coverage"]
    assert coverage["corpus_size"] == 2
    assert coverage["readable_size"] == 1
    assert coverage["readable_fraction"] == 0.5
    assert coverage["selection_is_conditioned_on_licence"] is True
    assert "open-access" in document["coverage_caveat"]
    assert document["storage_note"] == SCHEMA_CHANGE_REQUIRED


def test_the_summary_reports_coverage_before_findings(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Ordering is a property worth asserting: a reader who stops after the interesting part must
    still have seen what the screen could not look at."""
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    text = "\n".join(summary_lines(rescreen(conn, settings, criterion="E1")))
    assert text.index("COVERAGE") < text.index("SELECTION IS CONDITIONED ON LICENCE")
    assert text.index("SELECTION IS CONDITIONED ON LICENCE") < text.index("FINDINGS")
    assert "nothing is admitted" in text


def test_write_proposals_round_trips_as_yaml(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/chassis",
        text=_paper(abstract="x", methods=_STRAIN_TABLE),
    )
    out = tmp_path / "nested" / "E1.yaml"
    written = write_proposals(rescreen(conn, settings, criterion="E1"), out)
    loaded = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert loaded["criterion"] == "E1"
    assert loaded["provenance"] == PROVENANCE
    assert loaded["counts"]["substantive_in_wanted_section"] == 1
    assert loaded["proposals"][0]["publication_id"] == "doi:10.1/chassis"


def test_all_matches_widens_the_document_to_the_looser_gate(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    _add(
        conn,
        settings,
        publication_id="doi:10.1/citing",
        text=_paper(
            abstract="A study of something else entirely.",
            discussion=("Unlike pdc1Δ pdc5Δ pdc6Δ strains our strain retained PDC activity."),
        ),
    )
    result = rescreen(conn, settings, criterion="E1")
    assert proposal_document(result, sectioned_only=True)["proposals"] == []
    assert len(proposal_document(result, sectioned_only=False)["proposals"]) == 1


# ---------------------------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------------------------


def test_cli_refuses_a_criterion_with_no_pattern_set(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "derived"))
    exit_code = cli.main(["literature", "rescreen", "--criterion", "E2"])
    assert exit_code == 2
    assert "E1 (competing_sink)" in capsys.readouterr().err


def test_cli_parses_the_rescreen_flags() -> None:
    args = cli.build_parser().parse_args(
        ["literature", "rescreen", "--criterion", "E1", "--all-matches", "--no-write"]
    )
    assert args.criterion == "E1"
    assert args.all_matches is True
    assert args.no_write is True
    assert args.func is cli.cmd_literature_rescreen
