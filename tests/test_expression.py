"""Tests for `fermdb.query.expression` -- reading a transcriptome that lives in files.

The properties here are the ones that would let a wrong number reach a reader looking right:

* **"Not quantified" and "not expressed" must never collapse into each other.** The first is a
  statement about this corpus; the second would be a claim about the organism. A missing matrix
  row therefore returns `None`, not an empty profile whose median renders as 0.
* **A mitochondrial TPM from a poly(A)-selected library describes the library, not the
  organelle.** Every mitochondrial payload carries that caveat, because the number looks exactly
  like evidence and will be quoted out of context otherwise.
* **The run table and the matrix disagree, and the disagreement is load-bearing.**
  `sra_run.acquisition_status` says nothing was downloaded; 99 columns of real TPMs say
  otherwise. The payload has to name which one to trust rather than render both and let a reader
  guess.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from fermdb.db import IN_MEMORY, open_db
from fermdb.query import expression


def _write_matrix(path: Path, runs: list[str], rows: dict[str, list[float]]) -> None:
    """A TPM matrix in the shape the quantification pipeline emits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write("gene\t" + "\t".join(runs) + "\n")
        for gene, values in rows.items():
            handle.write(gene + "\t" + "\t".join(f"{v:g}" for v in values) + "\n")


@pytest.fixture()
def atlas() -> sqlite3.Connection:
    """Three runs, none of them marked downloaded -- the real corpus's state."""
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO dataset (id, accession, repository, omics_type, zone, evidence, "
        "confidence) VALUES ('ds:1', 'SRP1', 'SRA', 'transcriptomics', 'R', 'sra', 'high')"
    )
    for run in ("SRR1", "SRR2", "SRR3"):
        conn.execute(
            "INSERT INTO sra_run (id, run_accession, study_accession, library_strategy, "
            "acquisition_status, retrieved_at, evidence, confidence) "
            "VALUES (?, ?, 'SRP1', 'RNA-Seq', 'discovered', '2026-01-01', 'sra', 'high')",
            (f"run:{run}", run),
        )
    conn.commit()
    return conn


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: Any) -> Any:
    """Settings pointing at a scratch matrices directory, never the real one."""
    from fermdb.config import Settings

    matrices = tmp_path / "matrices"
    _write_matrix(
        matrices / "s288c.tpm.tsv.gz",
        ["SRR1", "SRR2", "SRR3"],
        {
            "YMR303C": [100.0, 120.0, 80.0],  # nuclear, always detected
            "Q0020": [5.0, 4.0, 6.0],  # mitochondrial
            "YAL001C": [0.0, 0.0, 0.0],  # quantified and silent -- not the same as absent
        },
    )
    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FERMDB_MATRICES_DIR", str(matrices))
    return Settings.load()


def test_a_gene_absent_from_the_matrix_is_none_not_an_empty_profile(
    atlas: sqlite3.Connection, settings: Any
) -> None:
    """ "Not quantified" is a statement about the corpus; returning zeros would make it a claim."""
    assert expression.read_gene_expression(atlas, "YNOSUCH", settings=settings) is None


def test_a_quantified_silent_gene_is_not_the_same_as_an_absent_one(
    atlas: sqlite3.Connection, settings: Any
) -> None:
    """YAL001C was measured and read zero. That is a real observation and must render as one."""
    read = expression.read_gene_expression(atlas, "YAL001C", settings=settings)
    assert read is not None
    payload = read.as_json()

    assert payload["median_tpm"]["value"] == 0.0, "a measured zero is a value, not an absence"
    assert payload["detected_in"] == 0
    # No ratio exists when the gene is undetected somewhere, and inventing one would put a
    # number where an absence belongs.
    assert "value" not in payload["fold_spread"]
    assert payload["fold_spread"]["absent"] == "not_applicable"


def test_mitochondrial_genes_carry_the_library_caveat(
    atlas: sqlite3.Connection, settings: Any
) -> None:
    """The number looks like evidence. Without the caveat it would be read as evidence."""
    read = expression.read_gene_expression(atlas, "Q0020", settings=settings)
    assert read is not None
    payload = read.as_json()

    assert payload["is_mitochondrial"] is True
    assert "caveat" in payload
    assert "poly(A)" in payload["caveat"]


def test_nuclear_genes_do_not_carry_it(atlas: sqlite3.Connection, settings: Any) -> None:
    """A caveat attached to everything is a caveat nobody reads."""
    read = expression.read_gene_expression(atlas, "YMR303C", settings=settings)
    assert read is not None
    payload = read.as_json()

    assert payload["is_mitochondrial"] is False
    assert "caveat" not in payload


def test_per_sample_values_keep_their_run_accession(
    atlas: sqlite3.Connection, settings: Any
) -> None:
    """A bare list of floats cannot be joined back to a condition, so it is not evidence."""
    read = expression.read_gene_expression(atlas, "YMR303C", settings=settings)
    assert read is not None

    assert read.per_sample == (("SRR1", 100.0), ("SRR2", 120.0), ("SRR3", 80.0))


def test_overview_reports_the_contradiction_with_the_run_table(
    atlas: sqlite3.Connection, settings: Any
) -> None:
    """Three runs are quantified; the status column says none was downloaded. Say so."""
    payload = expression.read_overview(atlas, settings=settings).as_json()

    assert payload["runs_quantified"] == 3
    assert payload["acquisition_status"] == {"discovered": 3}
    assert "status_warning" in payload
    assert "cannot" in payload["status_warning"]
    assert "acquisition triage" in payload["status_warning"]


def test_no_status_value_can_mean_quantified(atlas: sqlite3.Connection) -> None:
    """The reason the warning exists: the vocabulary has no term for it.

    Written as a constraint test rather than by setting a "downloaded" status, because the CHECK
    forbids that value -- which is exactly the finding. An earlier version of this suite tried it
    and got an IntegrityError, and that error is the whole point.
    """
    with pytest.raises(sqlite3.IntegrityError, match="acquisition_status"):
        atlas.execute("UPDATE sra_run SET acquisition_status = 'downloaded'")

    assert frozenset() == expression.QUANTIFICATION_STATES
    assert "downloaded" not in expression.ACQUISITION_STATES


def test_the_warning_is_silent_when_nothing_is_quantified(
    atlas: sqlite3.Connection, tmp_path: Path, monkeypatch: Any
) -> None:
    """It must not become wallpaper that appears whatever the data says."""
    from fermdb.config import Settings

    empty = tmp_path / "no-matrices"
    empty.mkdir()
    monkeypatch.setenv("FERMDB_MATRICES_DIR", str(empty))

    payload = expression.read_overview(atlas, settings=Settings.load()).as_json()
    assert payload["runs_quantified"] == 0
    assert "status_warning" not in payload


def test_matrix_samples_reads_only_the_header(settings: Any, tmp_path: Path) -> None:
    """Callers asking which runs exist should not pay to parse every gene."""
    path = Path(settings.matrices_dir) / "s288c.tpm.tsv.gz"
    assert expression.matrix_samples(path) == ("SRR1", "SRR2", "SRR3")


def test_a_missing_matrix_is_absent_not_empty(atlas: sqlite3.Connection, settings: Any) -> None:
    """A matrix that was never built and a gene that was never quantified read the same way."""
    payload = expression.read_overview(atlas, settings=settings).as_json()
    by_slug = {m["slug"]: m for m in payload["matrices"]}

    assert by_slug["s288c"]["present"] is True
    # ecoli and lcremoris were not written by the fixture.
    assert by_slug["ecoli"]["present"] is False
    assert "samples" not in by_slug["ecoli"]
