"""The owner's own include/exclude verdicts, and the working corpus they define."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.literature.screening import (
    DECISIONS_FILE,
    ScreeningError,
    corpus_counts,
    install_decisions,
    load_decisions,
    working_ids,
)

HEADER = (
    "publication_id\tdecision\treason\tsource\tdecided_by\tdecided_by_kind\t"
    "decided_at\tin_atlas\tpdf_file\n"
)


def _file(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / DECISIONS_FILE
    path.write_text("# a comment, not data\n" + HEADER + "".join(rows), encoding="utf-8")
    return path


def _row(
    pub: str,
    decision: str = "exclude",
    reason: str = "read and rejected",
    kind: str = "human",
) -> str:
    return f"{pub}\t{decision}\t{reason}\tpdf_excluded/\tkangkon\t{kind}\t2026-09-22\tyes\tx.pdf\n"


@pytest.fixture
def atlas() -> Iterator[sqlite3.Connection]:
    conn = open_db(IN_MEMORY)
    conn.executescript(
        """
        INSERT INTO publication (id, zone, evidence, confidence) VALUES
            ('doi:10.1/keep', 'R', 'test', 'low'),
            ('doi:10.1/drop', 'R', 'test', 'low'),
            ('doi:10.1/never-screened', 'R', 'test', 'low');
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_an_excluded_publication_leaves_the_working_corpus(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop"))))
    ids = working_ids(atlas)
    assert "doi:10.1/drop" not in ids
    assert "doi:10.1/keep" in ids


def test_a_publication_nobody_screened_stays_in_the_working_corpus(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """Never-opened is not the same as rejected, and conflating them discards the backlog.

    413 papers were read and rejected. The other ~4,600 were mostly never opened. A working
    corpus of "only what was explicitly included" would silently throw away everything still to
    be read, which is the opposite of what excluding the rejects is for.
    """
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop"))))
    assert "doi:10.1/never-screened" in working_ids(atlas)


def test_a_decision_about_a_publication_the_atlas_lacks_is_skipped_not_invented(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """14 real decisions name papers discovery never returned.

    Writing them would need a `publication` row, and manufacturing one from a PDF filename would
    put a paper into the corpus on the strength of a file someone happened to save.
    """
    counts = install_decisions(
        atlas, load_decisions(_file(tmp_path, _row("doi:10.1/nowhere"), _row("doi:10.1/drop")))
    )
    assert counts == {"written": 1, "no_such_publication": 1, "kept_human_verdict": 0}
    assert atlas.execute("SELECT count(*) FROM publication").fetchone()[0] == 3


def test_a_decision_with_no_reason_is_refused(atlas: sqlite3.Connection, tmp_path: Path) -> None:
    """Mirrors screening_record's own CHECK: an exclusion with no reason cannot be revisited.

    PLAN.md H.3 -- "an excluded paper is a decision, not an absence" -- is only true if the
    decision says something. A reasonless row is an absence wearing a decision's clothes.
    """
    with pytest.raises(ScreeningError, match="not reusable"):
        load_decisions(_file(tmp_path, _row("doi:10.1/drop", reason="")))


def test_two_verdicts_on_one_publication_are_refused(tmp_path: Path) -> None:
    """The table is keyed on the publication, so the file must not carry a contradiction."""
    with pytest.raises(ScreeningError, match="decided twice"):
        load_decisions(_file(tmp_path, _row("doi:10.1/drop"), _row("doi:10.1/drop", "include")))


def test_an_unknown_decision_word_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="not in"):
        load_decisions(_file(tmp_path, _row("doi:10.1/drop", decision="maybe")))


def test_reinstalling_updates_rather_than_duplicating(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """A curator who changes their mind must not end up with two verdicts on one paper."""
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop"))))
    install_decisions(
        atlas,
        load_decisions(
            _file(tmp_path, _row("doi:10.1/drop", "include", "re-read, it is in scope"))
        ),
    )
    rows = atlas.execute("SELECT decision, reason FROM screening_decision").fetchall()
    assert len(rows) == 1
    assert rows[0]["decision"] == "include"
    assert "re-read" in rows[0]["reason"]
    assert "doi:10.1/drop" in working_ids(atlas)


def test_the_counts_separate_rejected_from_merely_unread(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    install_decisions(
        atlas,
        load_decisions(_file(tmp_path, _row("doi:10.1/drop"), _row("doi:10.1/keep", "include"))),
    )
    counts = corpus_counts(atlas)
    assert counts["discovered"] == 3
    assert counts["excluded"] == 1
    assert counts["included"] == 1
    assert counts["working"] == 2
    assert counts["undecided"] == 1


def test_the_shipped_decisions_file_loads_and_matches_what_was_screened() -> None:
    """The committed layer itself, not a fixture: it is the record of 582 read PDFs."""
    path = Path(__file__).resolve().parents[1] / "data" / "literature" / DECISIONS_FILE
    decisions = load_decisions(path)
    assert len(decisions) == 582
    kinds = {d.decision for d in decisions}
    assert kinds == {"include", "exclude"}
    assert sum(1 for d in decisions if d.decision == "exclude") == 413
    # Every id is a DOI CURIE, lowercased -- the atlas's own key form, or nothing would match.
    assert all(d.publication_id.startswith("doi:") for d in decisions)
    assert all(d.publication_id == d.publication_id.lower() for d in decisions)


def test_a_classifier_verdict_never_overwrites_one_a_person_reached(
    atlas: sqlite3.Connection, tmp_path: Path
) -> None:
    """The defect this column was added for, before a classifier could commit it.

    `install_decisions` upserted blind, which was fine while the only input was 582 PDFs somebody
    had read -- and became a defect the moment a screening run over 1,606 papers was pointed at
    the same table. A title score and an afternoon with the paper are not interchangeable.
    """
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop"))))
    counts = install_decisions(
        atlas,
        load_decisions(
            _file(tmp_path, _row("doi:10.1/drop", "include", "title looks relevant", "model"))
        ),
    )
    assert counts["kept_human_verdict"] == 1
    assert counts["written"] == 0
    row = atlas.execute("SELECT decision, decided_by_kind FROM screening_decision").fetchone()
    assert (row["decision"], row["decided_by_kind"]) == ("exclude", "human")


def test_a_person_may_still_correct_a_classifier(atlas: sqlite3.Connection, tmp_path: Path) -> None:
    """The guard is one-directional on purpose: correcting the model is why a person is there."""
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop", kind="model"))))
    counts = install_decisions(
        atlas,
        load_decisions(_file(tmp_path, _row("doi:10.1/drop", "include", "read it; in scope"))),
    )
    assert counts["written"] == 1
    row = atlas.execute(
        "SELECT decision, decided_by_kind, confidence FROM screening_decision"
    ).fetchone()
    assert (row["decision"], row["decided_by_kind"]) == ("include", "human")
    # A read paper is checked; a scored title is a stored proposal.
    assert row["confidence"] == "high"


def test_a_model_verdict_is_stored_unverified(atlas: sqlite3.Connection, tmp_path: Path) -> None:
    install_decisions(atlas, load_decisions(_file(tmp_path, _row("doi:10.1/drop", kind="model"))))
    assert (
        atlas.execute("SELECT confidence FROM screening_decision").fetchone()["confidence"]
        == "unverified"
    )


def test_an_unknown_decider_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScreeningError, match="decided_by_kind"):
        load_decisions(_file(tmp_path, _row("doi:10.1/drop", kind="robot")))
