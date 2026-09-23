"""The declared Zone R -> Zone H derivations, and nothing else.

Two entries, which is the honest count as of 2026-09-24. See the package docstring for the survey
that produced it and for what the other Zone H tables would need. What matters here is that each
entry states its own reach in the :class:`~fermdb.rebuild.Regenerator` fields rather than in
prose, so the report can print coverage instead of implying it.

**A regenerator calls the producing code where the producing code is callable.**
:func:`_screening_triage` imports `discovery._triage` rather than restating the R.2 rule. A
restatement would be a second copy of the rule, and a test that compares a copy of the rule
against rows written by the rule passes exactly when the two copies agree -- including when both
are wrong, and excluding the one case worth catching, which is the rule changing without the
rows being rebuilt. `_triage` is private and is imported anyway, deliberately: the alternative is
worse than the smell.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, Final

from ..literature.discovery import _triage
from ..literature.queries import QueryFamily
from . import Declined, Regenerated, Regenerator

__all__ = ["REGENERATORS", "gene_group_evidence", "source_clause"]


# --------------------------------------------------------------------------------- gene_group


#: The constants `omics.genes.gene_group_rows` writes into every anchor group. Restated here
#: rather than imported because they are literals inside a dict comprehension there, not names.
#: If that module starts writing a different scope, this harness reports a diff -- which is
#: correct: a changed derivation rule with unchanged rows is exactly the undeclared-input bug
#: T.3 exists to catch, and the fix is to rebuild the rows, not to edit this constant quietly.
_ANCHOR_NAMESPACE: Final[str] = "sgd_systematic"
_SCOPE: Final[str] = "species"
_MEMBERSHIP_METHOD: Final[str] = "anchor"
#: `omics.genes.gene_group_rows`'s own reasoning: "the anchor itself is a verbatim RefSeq
#: locus_tag, not a recollection and not an orthology call -- there is nothing left to verify
#: about a one-member anchor group."
_ANCHOR_CONFIDENCE: Final[str] = "high"

#: The separator `omics.genes.gene_rows` puts between a gene's own bracketed fields and the
#: clause naming where the bytes came from. See :func:`source_clause`.
_ON_MARKER: Final[str] = "] on "
_CLAUSE_MARKER: Final[str] = "; "


def source_clause(gene_evidence: str) -> str:
    """The part of a Zone R `gene.evidence` that names the source file, not the gene.

    `omics.genes.gene_rows` builds the column as::

        [locus_tag=..] [gene=..] [db_xref=..] [product=..] on <accession> (<genome>-encoded); <src>

    and `gene_group_rows` re-uses `<src>` verbatim. So `<src>` is recoverable from Zone R, which
    is what makes the whole `gene_group` row rebuildable rather than only its structural columns.

    Splitting on the first ``'; '`` is wrong and was tried first: a RefSeq ``[product=..]``
    description may contain a semicolon, and one that does would silently truncate the clause and
    report 6,000 false diffs on the next genome. Anchoring on the **last** ``'] on '`` instead
    puts the search past every bracketed field, and the accession and genome that follow contain
    no ``'; '`` -- so the next ``'; '`` is the real separator. Verified against the live atlas on
    2026-09-24: all 36 `gene_group` rows reconstruct byte-identically, evidence column included.

    A string with neither marker is returned whole rather than guessed at. That is the case where
    a `gene` row came from somewhere this function does not know about, and a wrong clause is
    worse than an obviously-unsplit one: the diff still fires, and it names the real text.
    """
    marker = gene_evidence.rfind(_ON_MARKER)
    if marker == -1:
        return gene_evidence
    separator = gene_evidence.find(_CLAUSE_MARKER, marker)
    if separator == -1:
        return gene_evidence
    return gene_evidence[separator + len(_CLAUSE_MARKER) :]


def gene_group_evidence(systematic_name: str, gene_evidence: str) -> str:
    """The `gene_group.evidence` `omics.genes.gene_group_rows` writes for this gene."""
    return (
        f"anchored on the S288C systematic name {systematic_name}; {source_clause(gene_evidence)}"
    )


def _gene_groups(conn: sqlite3.Connection, _carried: tuple[Mapping[str, Any], ...]) -> Regenerated:
    """Every anchor `gene_group`, rebuilt from the Zone R `gene` rows alone.

    `_carried` is empty and unused: this is the one derivation in the atlas that is what D.2
    describes -- Zone R in, Zone H out, nothing else. The row set comes from `gene`, so a
    `gene_group` with no gene behind it is reported as a row the rebuild does not produce, and a
    gene whose group is missing is reported as a row only the rebuild has.

    **A known divergence, reported rather than papered over.** `genomics/load_genes.py` also
    writes anchor `gene_group` rows, with a different evidence template ("anchored on the
    {namespace} name {tag} of assembly {accession}; ...") and a different `standard_name` fallback.
    Nothing it has written is in the live atlas -- all 36 Zone H groups carry the `omics.genes`
    shape -- so this function reproduces that one. The day the GFF3 loader writes a group, this
    check goes red, and that is the correct outcome: two producers deriving the same Zone H table
    by two different rules is precisely the bug T.3 is looking for. The fix is one producer, not
    a second template here.
    """
    # Unpacked positionally rather than by name: this function is handed whatever connection the
    # caller has, and `sqlite3.Row` is only set by `open_db`. A raw connection returns tuples,
    # and keying by name would work under pytest and fail under a notebook.
    rows = conn.execute(
        "SELECT systematic_name, standard_name, gene_group_id, evidence FROM gene "
        "WHERE zone = 'R' AND gene_group_id IS NOT NULL "
        "ORDER BY gene_group_id"
    ).fetchall()
    return Regenerated(
        rows=tuple(
            {
                "id": str(group_id),
                "anchor_namespace": _ANCHOR_NAMESPACE,
                "anchor_id": systematic_name,
                "standard_name": standard_name,
                "scope": _SCOPE,
                "membership_method": _MEMBERSHIP_METHOD,
                "evidence": gene_group_evidence(str(systematic_name), str(evidence)),
                "confidence": _ANCHOR_CONFIDENCE,
            }
            for systematic_name, standard_name, group_id, evidence in rows
        )
    )


# --------------------------------------------------------------------------- screening_record


#: `_triage` reads exactly two attributes of the family it is handed: `default_disposition` and
#: `name` (the latter only to name the family in an exclusion reason). Everything else on
#: :class:`QueryFamily` exists to satisfy its own validation, and this placeholder term is never
#: read by anything the rebuild calls -- it is there because `__post_init__` requires exactly one
#: of `term` or `sub_queries` to be set. Taking the real term from `query_families.yaml` would be
#: worse, not better: the stored row's `default_disposition` is denormalized "as of the run that
#: first wrote this row" (schema.sql section 14), so re-deriving policy from today's YAML would
#: report a legitimate policy change as a rebuild failure.
_PLACEHOLDER_TERM: Final[str] = "(not read by the triage rule)"

#: `discovery.py` refreshes `triage_state` only while a record is still awaiting review. A
#: curator's verdict is not a function of the query file and must not be rebuilt over.
_LIVE_REVIEW_STATE: Final[str] = "proposed"


def _screening_triage(
    _conn: sqlite3.Connection, carried: tuple[Mapping[str, Any], ...]
) -> Regenerated:
    """Re-run the R.2 triage rule over every stored screening record.

    **This is a rule check, not a provenance rebuild, and the distinction is the whole point.**
    `screening_record.zone` is 'H' because schema.sql section 14 argues `triage_state` is "a
    deterministic function of query_families.yaml and the recorded rule in discovery.py". That
    argument is sound and this function tests it: `triage_state` and `exclusion_reason` are
    recomputed and diffed, so a hand-edited state, or a change to the exclusion wording without a
    re-run, is caught.

    What it cannot do is rebuild the row *set*, or the columns that record which PubMed hit the
    row came from. The esummary response that decided a record exists at all is never persisted
    anywhere -- there is no Zone R row for it -- so `row_source` is `"store"` and eleven of the
    table's sixteen columns are listed `unchecked` in the report. That is the single largest
    undeclared input in the atlas: 6,381 of 6,483 Zone H rows. See the package docstring.

    `admitted_criterion` is carried rather than rebuilt for the same reason: it is set from which
    criterion-tagged sub-query returned the hit, which is a fact about a network response, not
    about anything in the store.
    """
    rows: list[dict[str, Any]] = []
    declined: list[Declined] = []
    for record in carried:
        key = (str(record["publication_id"]), str(record["family"]))
        if record["review_state"] != _LIVE_REVIEW_STATE:
            declined.append(
                Declined(
                    key=key,
                    reason=(
                        f"review_state={record['review_state']!r}: a curator has taken this "
                        "record out of the triage rule's hands and discovery.py no longer "
                        "refreshes it"
                    ),
                )
            )
            continue
        family = QueryFamily(
            name=str(record["family"]),
            db="pubmed",
            product_tier=str(record["product_tier"]),
            default_disposition=str(record["default_disposition"]),
            expected_count=0,
            term=_PLACEHOLDER_TERM,
        )
        criterion = record["admitted_criterion"]
        state, reason, _candidate_for = _triage(
            family, None if criterion is None else str(criterion)
        )
        rows.append(
            {
                "publication_id": record["publication_id"],
                "family": record["family"],
                "triage_state": state,
                "exclusion_reason": reason,
            }
        )
    return Regenerated(rows=tuple(rows), declined=tuple(declined))


# ------------------------------------------------------------------------------- the registry


REGENERATORS: Final[tuple[Regenerator, ...]] = (
    Regenerator(
        table="gene_group",
        key=("id",),
        rebuilt=(
            "anchor_namespace",
            "anchor_id",
            "standard_name",
            "scope",
            "membership_method",
            "evidence",
            "confidence",
        ),
        carried=(),
        row_source="zone_r",
        source="fermdb.omics.genes.gene_group_rows",
        regenerate=_gene_groups,
    ),
    Regenerator(
        table="screening_record",
        key=("publication_id", "family"),
        rebuilt=("triage_state", "exclusion_reason"),
        carried=("product_tier", "default_disposition", "admitted_criterion", "review_state"),
        row_source="store",
        source="fermdb.literature.discovery._triage",
        regenerate=_screening_triage,
    ),
)
