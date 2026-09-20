"""The chassis, and what it rules out.

`ISOBUTANOL_PROGRAM.md` §6 defines `chassis_profile` — *"so 'which background' is answerable
rather than habitual"* — and nothing implemented it. The consequence was measurable: all 360
enumerated routes carried `host_strain_id = NULL` and a `score_feasibility` that is a constant per
strategy, so the ranker returned a generic answer to a specific question.

This module is the missing half. It loads the curated profile and applies it **per route**, which
is the part worth getting right.

**A chassis term must not be a constant.** The tempting implementation is to score every route
against the chassis the same way — a tolerance number folded into `score_toxicity`, say. That
would add a constant to all 360 and change no ordering, while looking like the ranker had become
chassis-aware. So instead the profile produces *gates*: facts about the strain that make a
particular route impossible, conditional, or more expensive than its strategy constant suggests.
Those differ between routes, which is the only way a chassis can change an answer.

**`score_toxicity` stays NULL, deliberately.** A route's toxicity score is a per-route × per-
chassis quantity: how close *this route's* expected titre sits to *this strain's* ceiling. The
atlas has the ceiling (once measured) and no expected titre, so computing one would be fake
precision. The tolerance travels as context on every route instead — visible, and not pretending
to be a score.

The three gates below come from the owner's own answers, recorded in
`docs/reference/OPEN_QUESTIONS.md`:

* **ρ status** — a ρ⁰ chassis cannot run a matrix pathway at all. Disqualifying, not costly.
* **respiration policy (M3)** — *"not an absolute requirement for pathway discovery, but the
  preferred requirement for the final industrial production strain unless a respiration-deficient
  strain demonstrates a compelling and scalable process advantage."* A conditional burden, so a
  route that costs respiration is flagged rather than excluded.
* **mtDNA tooling (M2)** — *"not available now, but will purchase if required"*, and the strains
  that can be purchased are all laboratory background. Strategy E therefore carries two different
  timelines, and the ranker should not average them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from ..config import Settings

__all__ = [
    "PROFILES_FILE",
    "ChassisGate",
    "ChassisProfile",
    "ChassisError",
    "gates_for",
    "load_profiles",
    "selected_profile",
    "write_profiles",
]

PROFILES_FILE: Final[str] = "chassis_profiles.yaml"


class ChassisError(RuntimeError):
    """The curated chassis file is missing, malformed, or names more than one selected strain."""


@dataclass(frozen=True)
class ChassisProfile:
    """One candidate background. Almost every field may be absent; absence is a real state."""

    id: str
    name_as_reported: str
    evidence: str
    confidence: str = "unverified"
    organism_id: str | None = None
    strain_id: str | None = None
    ploidy: int | None = None
    ploidy_candidates: tuple[int, ...] = ()
    marker_free_multiplex: bool | None = None
    rho_status: str | None = None
    pdc_status: str | None = None
    ferments_xylose: bool | None = None
    respiration_policy: str | None = None
    resolves_higher_alcohol_panel: bool | None = None
    higher_alcohol_panel_state: str | None = None
    isobutanol_tolerance_g_l: float | None = None
    tolerance_endpoint: str | None = None
    mtdna_tooling: str | None = None
    is_selected: bool = False

    @property
    def can_run_a_matrix_pathway(self) -> bool | None:
        """None when ρ status is unknown -- which is not the same as 'yes'."""
        if self.rho_status in (None, "unknown"):
            return None
        return self.rho_status != "rho_zero"

    @property
    def ploidy_scenarios(self) -> tuple[tuple[int, str], ...]:
        """``(ploidy, what it would mean)`` for every candidate not yet excluded.

        Empty once ploidy is measured -- at that point there is one answer and no scenarios.
        """
        if self.ploidy is not None:
            return ()
        return tuple(
            (
                n,
                "one allele per locus"
                if n == 1
                else (
                    f"{n} alleles per locus; marker-free multiplex keeps the transformation "
                    f"count flat but every locus must be verified {n} times"
                    if self.marker_free_multiplex
                    else f"{n} alleles per locus, each needing its own edit: roughly {n}x the work"
                ),
            )
            for n in sorted(self.ploidy_candidates)
        )

    @property
    def edit_burden_note(self) -> str:
        """How the ploidy and editing answers combine, in one line for a route explanation."""
        if self.ploidy is not None:
            if self.ploidy == 1:
                return "haploid: one allele per locus"
            if self.marker_free_multiplex:
                return (
                    f"ploidy {self.ploidy} with marker-free multiplex editing: transformation "
                    f"count stays flat, verification burden scales {self.ploidy}x"
                )
            return (
                f"ploidy {self.ploidy} without marker-free multiplex: each locus needs every "
                f"allele, so roughly {self.ploidy}x the edits"
            )
        if self.ploidy_candidates:
            low, high = min(self.ploidy_candidates), max(self.ploidy_candidates)
            return (
                f"ploidy not measured; candidates {low}-{high} remain open, so the verification "
                f"burden across DUET's loci spans {low}x to {high}x. Measuring it narrows the "
                f"estimate rather than changing the route"
            )
        return "edit burden unknown: ploidy not recorded and no candidate range given"


@dataclass(frozen=True)
class ChassisGate:
    """One consequence of the chassis for one route."""

    kind: str
    severity: str
    message: str

    @property
    def excludes(self) -> bool:
        return self.severity == "disqualifying"

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "excludes": self.excludes,
        }


def _profiles_path(settings: Settings) -> Path:
    return Path(settings.path("strains_dir")) / PROFILES_FILE


def _optional_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def load_profiles(settings: Settings) -> tuple[ChassisProfile, ...]:
    """Read ``data/strains/chassis_profiles.yaml``. An absent file yields no profiles.

    Absent is not an error: a project may not have chosen a chassis, and the route ranker's job
    is then to say so rather than to fail.
    """
    path = _profiles_path(settings)
    if not path.is_file():
        return ()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("chassis") or []
    if not isinstance(entries, list):
        raise ChassisError(f"{path}: 'chassis' must be a list")

    profiles: list[ChassisProfile] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ChassisError(f"{path}: every chassis entry must be a mapping")
        missing = [k for k in ("id", "name_as_reported", "evidence") if not entry.get(k)]
        if missing:
            raise ChassisError(f"{path}: entry {entry.get('id', '?')} is missing {missing}")
        profiles.append(
            ChassisProfile(
                id=str(entry["id"]),
                name_as_reported=str(entry["name_as_reported"]),
                evidence=str(entry["evidence"]),
                confidence=str(entry.get("confidence", "unverified")),
                organism_id=entry.get("organism_id"),
                strain_id=entry.get("strain_id"),
                ploidy=entry.get("ploidy"),
                ploidy_candidates=tuple(int(x) for x in (entry.get("ploidy_candidates") or ())),
                marker_free_multiplex=_optional_bool(entry.get("marker_free_multiplex")),
                rho_status=entry.get("rho_status"),
                pdc_status=entry.get("pdc_status"),
                ferments_xylose=_optional_bool(entry.get("ferments_xylose")),
                respiration_policy=entry.get("respiration_policy"),
                resolves_higher_alcohol_panel=_optional_bool(
                    entry.get("resolves_higher_alcohol_panel")
                ),
                higher_alcohol_panel_state=entry.get("higher_alcohol_panel_state"),
                isobutanol_tolerance_g_l=entry.get("isobutanol_tolerance_g_l"),
                tolerance_endpoint=entry.get("tolerance_endpoint"),
                mtdna_tooling=entry.get("mtdna_tooling"),
                is_selected=bool(entry.get("is_selected", False)),
            )
        )

    selected = [p for p in profiles if p.is_selected]
    if len(selected) > 1:
        raise ChassisError(
            f"{path}: {len(selected)} profiles are marked is_selected; the ranker scores against "
            "one chassis and cannot average two"
        )
    return tuple(profiles)


def selected_profile(profiles: Sequence[ChassisProfile]) -> ChassisProfile | None:
    """The chassis the ranker should score against, or None if none is chosen."""
    for profile in profiles:
        if profile.is_selected:
            return profile
    return None


def gates_for(profile: ChassisProfile | None, *, strategy: str) -> tuple[ChassisGate, ...]:
    """What this chassis does to a route of ``strategy``.

    Returns an empty tuple when no chassis is selected — which the caller should report as
    "ranked against no chassis" rather than as "no problems found". Those are different.
    """
    if profile is None:
        return ()

    gates: list[ChassisGate] = []
    matrix_strategies = {"A_native_split", "C_mitochondrial_ehrlich", "E_mtdna_encoded"}

    if strategy in matrix_strategies:
        runs_matrix = profile.can_run_a_matrix_pathway
        if runs_matrix is False:
            gates.append(
                ChassisGate(
                    "rho_status",
                    "disqualifying",
                    f"{profile.name_as_reported} is {profile.rho_status}: a matrix pathway "
                    "cannot run without mitochondrial DNA, so this is not a cost but an "
                    "impossibility",
                )
            )
        elif runs_matrix is None:
            gates.append(
                ChassisGate(
                    "rho_status",
                    "unknown",
                    "rho status not recorded, so whether this chassis can run a matrix pathway "
                    "at all is unknown -- not assumed",
                )
            )

    if strategy == "E_mtdna_encoded":
        tooling = profile.mtdna_tooling or "unknown"
        if tooling == "unavailable":
            gates.append(
                ChassisGate(
                    "mtdna_tooling", "disqualifying", "no route to mitochondrial transformation"
                )
            )
        elif tooling != "available_here":
            gates.append(
                ChassisGate(
                    "mtdna_tooling",
                    "conditional",
                    f"mtDNA tooling is {tooling.replace('_', ' ')}. The purchasable rho-zero and "
                    "kar1-1 strains are laboratory background, so discovery and delivery are two "
                    "different timelines",
                )
            )
        if profile.respiration_policy in ("required", "preferred"):
            gates.append(
                ChassisGate(
                    "respiration",
                    "conditional" if profile.respiration_policy == "preferred" else "disqualifying",
                    f"respiration is {profile.respiration_policy} for this chassis, and an mtDNA "
                    "insert behind a COX leader displaces that gene. A route taking a COX locus "
                    "must name a rescue strategy, or clear the process-advantage bar",
                )
            )

    if profile.pdc_status == "minus":
        gates.append(
            ChassisGate(
                "pdc_status",
                "conditional",
                "this chassis is Pdc-minus, and DUET_TARGET.md §5.1 requires Pdc-POSITIVE: the "
                "ethanol-acetaldehyde shuttle is the mechanism, not the competition",
            )
        )
    return tuple(gates)


def iter_context(profile: ChassisProfile | None) -> Iterator[str]:
    """Lines a route explanation should carry about the chassis, whether or not they gate."""
    if profile is None:
        yield "no chassis selected: every route below is ranked against none"
        return
    yield f"chassis: {profile.name_as_reported}"
    yield profile.edit_burden_note
    if profile.isobutanol_tolerance_g_l is not None:
        endpoint = profile.tolerance_endpoint or "endpoint not stated"
        yield f"tolerance ceiling: {profile.isobutanol_tolerance_g_l:g} g/L ({endpoint})"
    else:
        yield "tolerance ceiling: not measured -- no route's ceiling can be computed"
    if profile.ferments_xylose is not None:
        yield f"ferments xylose today: {'yes' if profile.ferments_xylose else 'no'}"


def write_profiles(conn: sqlite3.Connection, profiles: Sequence[ChassisProfile]) -> dict[str, int]:
    """Store the curated profiles. Idempotent on id."""
    for profile in profiles:
        conn.execute(
            "INSERT INTO chassis_profile (id, strain_id, name_as_reported, organism_id, ploidy, "
            "ploidy_state, ploidy_candidates, marker_free_multiplex, rho_status, pdc_status, "
            "ferments_xylose, "
            "respiration_policy, resolves_higher_alcohol_panel, higher_alcohol_panel_state, "
            "isobutanol_tolerance_g_l, isobutanol_tolerance_state, tolerance_endpoint, "
            "mtdna_tooling, is_selected, zone, evidence, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'R',?,?) "
            "ON CONFLICT(id) DO UPDATE SET name_as_reported=excluded.name_as_reported, "
            "ploidy=excluded.ploidy, ploidy_state=excluded.ploidy_state, "
            "ploidy_candidates=excluded.ploidy_candidates, "
            "rho_status=excluded.rho_status, pdc_status=excluded.pdc_status, "
            "respiration_policy=excluded.respiration_policy, "
            "isobutanol_tolerance_g_l=excluded.isobutanol_tolerance_g_l, "
            "isobutanol_tolerance_state=excluded.isobutanol_tolerance_state, "
            "mtdna_tooling=excluded.mtdna_tooling, is_selected=excluded.is_selected, "
            "evidence=excluded.evidence, confidence=excluded.confidence",
            (
                profile.id,
                profile.strain_id,
                profile.name_as_reported,
                profile.organism_id,
                profile.ploidy,
                "recorded" if profile.ploidy is not None else "unknown",
                json.dumps(list(profile.ploidy_candidates)) if profile.ploidy_candidates else None,
                None
                if profile.marker_free_multiplex is None
                else int(profile.marker_free_multiplex),
                profile.rho_status,
                profile.pdc_status,
                None if profile.ferments_xylose is None else int(profile.ferments_xylose),
                profile.respiration_policy,
                None
                if profile.resolves_higher_alcohol_panel is None
                else int(profile.resolves_higher_alcohol_panel),
                profile.higher_alcohol_panel_state,
                profile.isobutanol_tolerance_g_l,
                "recorded" if profile.isobutanol_tolerance_g_l is not None else None,
                profile.tolerance_endpoint,
                profile.mtdna_tooling,
                int(profile.is_selected),
                profile.evidence,
                profile.confidence,
            ),
        )
    conn.commit()
    return {"chassis_profile": len(profiles)}
