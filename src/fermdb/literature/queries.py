"""Query family definitions (`data/literature/query_families.yaml`) and read queries over the
literature-discovery tables (`search_run`, `screening_record`) added to `schema.sql`.

Nothing here opens a database connection — every function takes one it was handed, per
`docs/reference/CONVENTIONS.md` ("Paths and configuration": `src/fermdb/db/__init__.py` is the
only module that opens the database).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_PRODUCT_TIERS = ("isobutanol", "ethanol")
VALID_DISPOSITIONS = ("include_unless_excluded", "exclude_unless_admitted")
#: The ethanol admission criteria. E1-E4 are PLAN.md B.3.1-B.3.4 / R.2.
#:
#: E5 was added 2026-09-20 from docs/design/DUET_TARGET.md: in the target architecture ethanol is
#: not only the competing sink to be deleted (E1) but the **redox carrier** into the mitochondrial
#: matrix -- Adh3 oxidises it there, and the resulting NADH drives the Ehrlich ADH step and, via
#: the Pos5 NADH kinase, supplies Ilv5's NADPH. That literature is load-bearing, so it needs an
#: admission route of its own.
#:
#: This tuple is a closed vocabulary rather than data because the *meaning* of each criterion is
#: written into PLAN.md B.3 and the schema's CHECK; adding one is a scoping decision that should
#: show up in a diff here, not appear silently in a YAML file. Keep it in step with
#: data/literature/query_families.yaml and the screening_record CHECK constraint.
VALID_CRITERIA = ("E1", "E2", "E3", "E4", "E5")

#: Every key a family mapping may carry. Anything else is an error, not a silent no-op.
_FAMILY_KEYS = frozenset(
    {
        "name",
        "db",
        "product_tier",
        "default_disposition",
        "expected_count",
        "term",
        "sub_queries",
        "mtdna_scope",
        "description",
        "notes",
        "capped",
    }
)

#: The three mtDNA-literature scopes the project owner requires be covered (harness "comments (1)":
#: (a) yeast mtDNA genetic engineering generally, (b) isobutanol x mtDNA, (c) ethanol x mtDNA).
#: `None` means a family is not part of the mtDNA-scope requirement at all (e.g. plain isobutanol
#: production queries with no mitochondrial angle).
VALID_MTDNA_SCOPES = ("engineering_general", "isobutanol_x_mtdna", "ethanol_x_mtdna")


class QueryFamiliesError(ValueError):
    """`query_families.yaml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class SubQuery:
    """One targeted sub-query of a family, tagged with the B.3 criterion it targets.

    Used only by ethanol-tier families under R.2: "Targeted queries against the four B.3 criteria
    only." A hit retrieved through a criterion-tagged sub-query carries that criterion as its
    admission signal (`discovery._triage`); a hit from an untagged family term does not.
    """

    criterion: str
    label: str
    term: str

    def __post_init__(self) -> None:
        if self.criterion not in VALID_CRITERIA:
            raise QueryFamiliesError(
                f"sub-query {self.label!r}: unknown criterion {self.criterion!r}; "
                f"must be one of {VALID_CRITERIA}"
            )
        if not self.term.strip():
            raise QueryFamiliesError(f"sub-query {self.label!r}: empty term")


@dataclass(frozen=True)
class QueryFamily:
    """One row of `data/literature/query_families.yaml`."""

    name: str
    db: str
    product_tier: str
    default_disposition: str
    expected_count: int
    term: str | None = None
    sub_queries: tuple[SubQuery, ...] = ()
    mtdna_scope: str | None = None
    description: str | None = None
    notes: str | None = None
    capped: bool = False

    def __post_init__(self) -> None:
        if self.product_tier not in VALID_PRODUCT_TIERS:
            raise QueryFamiliesError(
                f"{self.name}: unknown product_tier {self.product_tier!r}; "
                f"must be one of {VALID_PRODUCT_TIERS}"
            )
        if self.default_disposition not in VALID_DISPOSITIONS:
            raise QueryFamiliesError(
                f"{self.name}: unknown default_disposition {self.default_disposition!r}; "
                f"must be one of {VALID_DISPOSITIONS}"
            )
        if bool(self.term and self.term.strip()) == bool(self.sub_queries):
            raise QueryFamiliesError(
                f"{self.name}: exactly one of `term` or `sub_queries` must be set"
            )
        if self.mtdna_scope is not None and self.mtdna_scope not in VALID_MTDNA_SCOPES:
            raise QueryFamiliesError(
                f"{self.name}: unknown mtdna_scope {self.mtdna_scope!r}; "
                f"must be one of {VALID_MTDNA_SCOPES} or omitted"
            )
        if self.expected_count < 0:
            raise QueryFamiliesError(f"{self.name}: expected_count must be >= 0")


@dataclass(frozen=True)
class QueryFamilies:
    """The parsed corpus definition: every family, plus the file's own version/measurement date."""

    version: int
    measured_on: str
    families: tuple[QueryFamily, ...]

    def __getitem__(self, name: str) -> QueryFamily:
        for family in self.families:
            if family.name == name:
                return family
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(family.name for family in self.families)

    def by_mtdna_scope(self, scope: str) -> tuple[QueryFamily, ...]:
        return tuple(f for f in self.families if f.mtdna_scope == scope)


def _parse_sub_query(raw: Any, *, family_name: str) -> SubQuery:
    if not isinstance(raw, dict):
        raise QueryFamiliesError(f"{family_name}: each sub_queries entry must be a mapping")
    try:
        return SubQuery(criterion=raw["criterion"], label=raw["label"], term=raw["term"])
    except KeyError as exc:
        raise QueryFamiliesError(
            f"{family_name}: sub_queries entry missing required key {exc}"
        ) from exc


def _parse_family(raw: Any) -> QueryFamily:
    if not isinstance(raw, dict):
        raise QueryFamiliesError(f"family entry must be a mapping, got {raw!r}")
    try:
        name = str(raw["name"])
    except KeyError as exc:
        raise QueryFamiliesError(f"family entry missing 'name': {raw!r}") from exc
    sub_queries = tuple(
        _parse_sub_query(entry, family_name=name) for entry in raw.get("sub_queries") or []
    )
    unknown = set(raw) - _FAMILY_KEYS
    if unknown:
        raise QueryFamiliesError(
            f"{name}: unknown key(s) {sorted(unknown)}; a key this parser ignores reads as "
            f"policy while doing nothing. Known keys: {sorted(_FAMILY_KEYS)}"
        )
    try:
        expected_count = int(raw["expected_count"])
        product_tier = str(raw["product_tier"])
        default_disposition = str(raw["default_disposition"])
    except KeyError as exc:
        raise QueryFamiliesError(f"{name}: missing required key {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise QueryFamiliesError(f"{name}: malformed value: {exc}") from exc
    return QueryFamily(
        name=name,
        db=str(raw.get("db", "pubmed")),
        product_tier=product_tier,
        default_disposition=default_disposition,
        expected_count=expected_count,
        term=raw.get("term"),
        sub_queries=sub_queries,
        mtdna_scope=raw.get("mtdna_scope"),
        description=raw.get("description"),
        notes=raw.get("notes"),
        capped=bool(raw.get("capped", False)),
    )


def load_query_families(path: Path) -> QueryFamilies:
    """Parse and validate `query_families.yaml`. Raises `QueryFamiliesError` on any problem."""
    if not path.is_file():
        raise QueryFamiliesError(f"query families file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    if not isinstance(doc, dict):
        raise QueryFamiliesError(f"{path}: expected a mapping at the top level")
    raw_families = doc.get("families")
    if not isinstance(raw_families, list) or not raw_families:
        raise QueryFamiliesError(f"{path}: missing or empty top-level 'families' list")

    families = tuple(_parse_family(entry) for entry in raw_families)
    names = [family.name for family in families]
    if len(names) != len(set(names)):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise QueryFamiliesError(f"{path}: duplicate family name(s): {duplicates}")

    return QueryFamilies(
        version=int(doc.get("version", 1)),
        measured_on=str(doc.get("measured_on", "")),
        families=families,
    )


# ---------------------------------------------------------------------------------------------
# Read queries over search_run / screening_record
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FamilyStatus:
    """One row of `fermdb literature status`: the last run's counts against `expected_count`."""

    family: str
    product_tier: str
    default_disposition: str
    expected_count: int
    last_hit_count: int | None
    last_retrieved_count: int | None
    last_run_finished_at: str | None
    included: int
    needs_full_text: int
    excluded: int

    @property
    def drift(self) -> int | None:
        """`last_hit_count - expected_count`, or None if the family has never been run.

        Drift is informational, not a failure: PLAN.md's `expected_count` is a fixed measurement
        from 2026-09-19/20, and the live literature grows every day. A large *negative* drift is
        the more actionable case -- it usually means the query term stopped matching what it used
        to (an index change, a typo introduced later), not that the literature shrank.
        """
        if self.last_hit_count is None:
            return None
        return self.last_hit_count - self.expected_count


def family_status(conn: sqlite3.Connection, families: QueryFamilies) -> list[FamilyStatus]:
    """One `FamilyStatus` per family in `families`, most-recently-defined order preserved."""
    statuses = []
    for family in families.families:
        run_row = conn.execute(
            "SELECT hit_count, retrieved_count, finished_at FROM search_run "
            "WHERE family = ? AND dry_run = 0 AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1",
            (family.name,),
        ).fetchone()
        triage_counts = {"included": 0, "needs_full_text": 0, "excluded": 0}
        for row in conn.execute(
            "SELECT triage_state, COUNT(*) AS n FROM screening_record "
            "WHERE family = ? GROUP BY triage_state",
            (family.name,),
        ):
            triage_counts[row["triage_state"]] = row["n"]
        statuses.append(
            FamilyStatus(
                family=family.name,
                product_tier=family.product_tier,
                default_disposition=family.default_disposition,
                expected_count=family.expected_count,
                last_hit_count=run_row["hit_count"] if run_row else None,
                last_retrieved_count=run_row["retrieved_count"] if run_row else None,
                last_run_finished_at=run_row["finished_at"] if run_row else None,
                included=triage_counts["included"],
                needs_full_text=triage_counts["needs_full_text"],
                excluded=triage_counts["excluded"],
            )
        )
    return statuses


def excluded_records(conn: sqlite3.Connection, *, family: str | None = None) -> list[sqlite3.Row]:
    """Every currently excluded `screening_record`, for re-running a changed inclusion policy.

    PLAN.md H.3 / R.2: "a changed inclusion policy must be re-runnable against the exclusions".
    This is the read side of that requirement -- it does not itself re-triage anything, it just
    returns what a policy change would need to reconsider, each with its `exclusion_reason` for a
    human (or a later, more capable classifier) to read.
    """
    if family is not None:
        return conn.execute(
            "SELECT * FROM screening_record WHERE triage_state = 'excluded' AND family = ? "
            "ORDER BY publication_id",
            (family,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM screening_record WHERE triage_state = 'excluded' "
        "ORDER BY family, publication_id"
    ).fetchall()


def needs_full_text(conn: sqlite3.Connection, *, family: str | None = None) -> list[sqlite3.Row]:
    """Every `screening_record` awaiting a full-text read before it can be triaged further."""
    if family is not None:
        return conn.execute(
            "SELECT * FROM screening_record WHERE triage_state = 'needs_full_text' "
            "AND family = ? ORDER BY publication_id",
            (family,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM screening_record WHERE triage_state = 'needs_full_text' "
        "ORDER BY family, publication_id"
    ).fetchall()
