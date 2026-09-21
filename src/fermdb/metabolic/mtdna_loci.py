"""The translational activator map, loaded from YAML into a table a query can reach.

``MITOCHONDRIAL_PROGRAM.md`` §2.1 calls the activator constraint **"the binding constraint"**:
yeast mitochondrial mRNAs are not translated generically, so a heterologous ORF has to sit behind
an existing gene's 5′ leader, at a site that leader controls, driven by the resident nuclear-
encoded activator. Which site you pick decides what you lose.

The map was curated into ``data/mitochondria/activator_map.yaml`` — all eight protein-coding loci,
each activator quoted from a paper held in this corpus, plus a ninth row that is not a gene. Then
nothing read it. Benchmark **BM-MIT-004** asks the atlas, for a proposed insertion locus, to
return ``utr_source``, ``activator_required`` and ``displaced_gene``, and the atlas returned
nothing at all — the knowledge sat in the repository, unreachable from a query. This module is
that gap closed.

**Why a separate table from ``mtdna_insertion``.** They answer different questions.
``mtdna_insertion`` records a proposed or performed *edit* and hangs off a ``modification``.
``mtdna_locus`` is the *catalogue of sites an edit may target* and exists independently of whether
anyone has ever proposed one. Reading a menu is not placing an order, and a schema that conflates
them cannot answer "where could this go" until after someone has already decided where it went.

**Absence is not emptiness.** ``activators`` is NULL when no activator is recorded for a locus,
never ``[]``. An insert designed against a locus whose activator is unknown is precisely the
failure BM-MIT-004 exists to catch, and it is only catchable if "we do not know" and "none is
needed" are stored differently.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..config import Settings

__all__ = [
    "ACTIVATOR_MAP_FILE",
    "PRECEDENTS_FILE",
    "ProgrammeGap",
    "MtdnaLocus",
    "MtdnaLocusError",
    "load_activator_map",
    "load_programme_gaps",
    "loci_without_activator",
    "non_displacing_loci",
    "write_loci",
    "write_programme_gaps",
]

ACTIVATOR_MAP_FILE: Final[str] = "activator_map.yaml"
PRECEDENTS_FILE: Final[str] = "heterologous_orf_precedents.yaml"

#: The kinds the `knowledge_gap` table accepts. A curated gap naming anything else is a typo, and
#: a typo here would be written to the database as a legal-looking row.
_GAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        "transport_carrier_unknown",
        "enzyme_unidentified",
        "mechanism_unknown",
        "quantitative_value_missing",
        "never_attempted",
    }
)
_GAP_STATUSES: Final[frozenset[str]] = frozenset({"open", "candidate_proposed", "resolved"})

#: The closed set the schema accepts. 'unknown' is a real answer and the default for a locus whose
#: rescue options nobody has looked into; it is not a synonym for 'none'.
_RESCUE_VALUES: Final[frozenset[str]] = frozenset(
    {"none", "nuclear_allotopic_copy", "second_locus", "other", "unknown"}
)


class MtdnaLocusError(RuntimeError):
    """The activator map is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class MtdnaLocus:
    """One site an mtDNA insert could target, and what targeting it costs."""

    id: str
    locus: str
    encodes: str | None
    #: None means "not recorded". An empty tuple would mean "none required", which is a claim
    #: about biology that this atlas has no source for at any locus.
    activators: tuple[str, ...] | None
    utr_source: str | None
    #: None means an insert here displaces nothing — true of exactly one row, and that row is the
    #: reason MITOCHONDRIAL_PROGRAM.md §2.1's "inserting costs you the gene whose UTR you
    #: borrowed" is true of the replacement route and not in general.
    displaced_if_used: str | None
    respiration_retained_if_used: bool | None
    rescue_available: str | None
    evidence: str
    confidence: str

    @property
    def is_free(self) -> bool:
        """Displaces nothing and keeps respiration — the cheap default, if one exists."""
        return self.displaced_if_used is None and self.respiration_retained_if_used is True


def _map_path(settings: Settings) -> Path:
    # The map lives beside the other curated mitochondrial data, under the repo tier. It is
    # committed curation, not a rebuildable artifact, so it is never auto-created.
    return Path(settings.repo_root) / "data" / "mitochondria" / ACTIVATOR_MAP_FILE


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_activator_map(settings: Settings, *, path: Path | None = None) -> tuple[MtdnaLocus, ...]:
    """Read the curated activator map. Raises rather than returning an empty map.

    An empty map would make every downstream design query answer "no constraint", which is the
    opposite of what §2.1 says is true and is a far more dangerous output than an error.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without the dependency
        raise MtdnaLocusError("PyYAML is required to read the activator map") from exc

    source = _map_path(settings) if path is None else path
    if not source.is_file():
        raise MtdnaLocusError(
            f"no activator map at {source}. It is curated, committed data "
            f"(MITOCHONDRIAL_PROGRAM.md §2.1) and is not generated."
        )

    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    rows = document.get("loci")
    if not isinstance(rows, list) or not rows:
        raise MtdnaLocusError(f"{source}: 'loci' must be a non-empty list")

    loci: list[MtdnaLocus] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MtdnaLocusError(f"{source}: loci[{index}] is not a mapping")
        name = _optional_str(row.get("locus"))
        if name is None:
            raise MtdnaLocusError(f"{source}: loci[{index}] has no 'locus'")
        if name in seen:
            raise MtdnaLocusError(f"{source}: '{name}' appears twice; the map is a catalogue")
        seen.add(name)

        raw_activators = row.get("activators")
        if raw_activators is None:
            activators: tuple[str, ...] | None = None
        elif isinstance(raw_activators, list):
            if not raw_activators:
                raise MtdnaLocusError(
                    f"{source}: '{name}' has an empty activator list. Omit the key to mean "
                    f"'not recorded'; an empty list would assert that none is required, which "
                    f"is a claim about biology this atlas has no source for."
                )
            activators = tuple(str(a).strip() for a in raw_activators)
        else:
            raise MtdnaLocusError(f"{source}: '{name}' activators must be a list")

        rescue = _optional_str(row.get("rescue_available"))
        if rescue is not None and rescue not in _RESCUE_VALUES:
            raise MtdnaLocusError(
                f"{source}: '{name}' rescue_available={rescue!r} is not one of "
                f"{sorted(_RESCUE_VALUES)}"
            )

        evidence = _optional_str(row.get("evidence"))
        if evidence is None:
            raise MtdnaLocusError(
                f"{source}: '{name}' has no evidence. CONVENTIONS.md requires evidence and "
                f"confidence on every curated row."
            )
        confidence = _optional_str(row.get("confidence")) or "unverified"

        retained = row.get("respiration_retained_if_used")
        loci.append(
            MtdnaLocus(
                id=f"YAA:MTLOCUS:{name.lower().replace('_', '-')}",
                locus=name,
                encodes=_optional_str(row.get("encodes")),
                activators=activators,
                # A locus whose leader is not named drives an insert with its own, which is the
                # overwhelmingly common case and the one §2.1 describes.
                utr_source=_optional_str(row.get("utr_source")) or name,
                displaced_if_used=_optional_str(row.get("displaced_if_used")),
                respiration_retained_if_used=None if retained is None else bool(retained),
                rescue_available=rescue,
                evidence=evidence,
                confidence=confidence,
            )
        )
    return tuple(loci)


def non_displacing_loci(loci: Sequence[MtdnaLocus]) -> tuple[MtdnaLocus, ...]:
    """Sites where an insert costs no resident gene.

    Worth its own function because the whole shape of strategy E's cost depends on whether this
    is empty. It is not: the pPT24 route adds an ORF as an extra gene in a silent region and
    leaves respiration measurably intact.
    """
    return tuple(locus for locus in loci if locus.is_free)


def loci_without_activator(loci: Sequence[MtdnaLocus]) -> tuple[MtdnaLocus, ...]:
    """Sites offered as insertion targets with no activator recorded.

    BM-MIT-004: *"An insertion design returned with activator_required NULL is the failure mode
    this entry exists to catch."* This is the query that catches it.
    """
    return tuple(locus for locus in loci if locus.activators is None)


def write_loci(conn: sqlite3.Connection, loci: Sequence[MtdnaLocus]) -> int:
    """Store the catalogue. Idempotent on id."""
    for locus in loci:
        conn.execute(
            "INSERT INTO mtdna_locus (id, locus, encodes, activators, utr_source, "
            "displaced_if_used, respiration_retained_if_used, rescue_available, zone, evidence, "
            "confidence) VALUES (?,?,?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(id) DO UPDATE SET encodes=excluded.encodes, "
            "activators=excluded.activators, utr_source=excluded.utr_source, "
            "displaced_if_used=excluded.displaced_if_used, "
            "respiration_retained_if_used=excluded.respiration_retained_if_used, "
            "rescue_available=excluded.rescue_available, evidence=excluded.evidence, "
            "confidence=excluded.confidence",
            (
                locus.id,
                locus.locus,
                locus.encodes,
                json.dumps(list(locus.activators)) if locus.activators is not None else None,
                locus.utr_source,
                locus.displaced_if_used,
                None
                if locus.respiration_retained_if_used is None
                else int(locus.respiration_retained_if_used),
                locus.rescue_available,
                locus.evidence,
                locus.confidence,
            ),
        )
    # The house convention: a `write_*` owns its transaction and commits (cf. `write_profiles`,
    # `write_parts`). Omitting this made `atlas loci` print nine rows and persist none -- the
    # command reported success from its in-memory list, not from the database.
    conn.commit()
    return len(loci)


@dataclass(frozen=True)
class ProgrammeGap:
    """A gap in what has ever been ATTEMPTED, rather than in what a route needs.

    `write_routes` emits a gap per route from gate output -- a missing carrier, an unmeasured
    cofactor pool. Those are properties of a proposed route. These are different: they are
    properties of the *field*, established by reading the corpus and finding nothing, and they
    exist whether or not anyone enumerates a route. So they carry no `route_id`.
    """

    id: str
    kind: str
    description: str
    why_it_matters: str
    status: str
    compartment_id: str | None
    evidence: str


def load_programme_gaps(
    settings: Settings, *, path: Path | None = None
) -> tuple[ProgrammeGap, ...]:
    """The `open_gaps` of the heterologous-ORF precedents file, as gap rows.

    ``MITOCHONDRIAL_PROGRAM.md`` §2.3 says the atlas "records this as a ``knowledge_gap`` of kind
    ``never_attempted``, with the Arg8ᵐ precedent attached as the nearest supporting evidence --
    which is exactly the shape of an honest research question." It did not: before this loader the
    table held 208 rows and not one of kind ``never_attempted``. Sixth instance of the failure mode
    the 2026-09-21 handover names -- a fact recorded faithfully and wired to nothing.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise MtdnaLocusError("PyYAML is required to read the precedents file") from exc

    source = (
        Path(settings.repo_root) / "data" / "mitochondria" / PRECEDENTS_FILE
        if path is None
        else path
    )
    if not source.is_file():
        raise MtdnaLocusError(f"no precedents file at {source}; it is curated, not generated.")

    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    rows = document.get("open_gaps")
    if not isinstance(rows, list) or not rows:
        raise MtdnaLocusError(f"{source}: 'open_gaps' must be a non-empty list")

    gaps: list[ProgrammeGap] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MtdnaLocusError(f"{source}: open_gaps[{index}] is not a mapping")
        description = _optional_str(row.get("gap"))
        if description is None:
            raise MtdnaLocusError(f"{source}: open_gaps[{index}] has no 'gap'")
        kind = _optional_str(row.get("kind"))
        if kind not in _GAP_KINDS:
            raise MtdnaLocusError(
                f"{source}: '{description}' has kind={kind!r}, not one of {sorted(_GAP_KINDS)}. "
                f"'kind' is what the gap IS; 'status' is how far it has got."
            )
        status = _optional_str(row.get("status")) or "open"
        if status not in _GAP_STATUSES:
            raise MtdnaLocusError(
                f"{source}: '{description}' has status={status!r}, not one of "
                f"{sorted(_GAP_STATUSES)}"
            )
        slug = description.lower().split(":")[0].replace(" ", "-")[:40]
        gaps.append(
            ProgrammeGap(
                id=f"YAA:GAP:mtdna-{index}-{slug}",
                kind=kind,
                description=description,
                why_it_matters=_optional_str(row.get("note")) or description,
                status=status,
                # These are all matrix-capability questions, so they hang off the compartment
                # rather than off a route -- they are true regardless of which route is proposed.
                compartment_id="mitochondrial_matrix",
                evidence=f"data/mitochondria/{PRECEDENTS_FILE}, open_gaps[{index}]",
            )
        )
    return tuple(gaps)


def write_programme_gaps(conn: sqlite3.Connection, gaps: Sequence[ProgrammeGap]) -> int:
    """Store programme-level gaps. Idempotent on id. Zone I: inferred from an absence."""
    for gap in gaps:
        conn.execute(
            "INSERT INTO knowledge_gap (id, kind, compartment_id, description, why_it_matters, "
            "status, zone, evidence, confidence) VALUES (?,?,?,?,?,?,'I',?,'medium') "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, description=excluded.description, "
            "why_it_matters=excluded.why_it_matters, status=excluded.status, "
            "evidence=excluded.evidence",
            (
                gap.id,
                gap.kind,
                gap.compartment_id,
                gap.description,
                gap.why_it_matters,
                gap.status,
                gap.evidence,
            ),
        )
    conn.commit()
    return len(gaps)
