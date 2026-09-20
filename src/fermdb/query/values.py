"""The unit of the query layer: a fact, or a stated reason there is no fact.

This module exists because of one line in `docs/reference/CONVENTIONS.md`:

    Three distinct states, never collapsed. ... Never coerce any of the three into another, and
    never into zero. The UI renders "not recorded", "not applicable" and "unknown" differently.

That rule survives the database easily -- `schema.sql` spends a hundred lines of CHECK constraints
enforcing it -- and then dies at the first `json.dumps`. JSON has exactly one absence, `null`, and
a consumer writing ``value ?? "-"`` collapses all three in a single character. So the rule has to
be carried in the *shape of the value*, not in a comment addressed to whoever writes the frontend.

Hence :class:`Value`. It is the only thing the query layer returns for a fact. It holds either a
value or an :class:`Absence`, never neither and never both, and it serializes with a ``display``
string already filled in. That last part is the design decision worth defending: **the laziest
possible consumer must be the correct one.** A UI that renders ``v.display`` and nothing else
shows "not recorded" and "not applicable" as different text, which is what PLAN.md P.4 asks for.
If the honest rendering needed extra work, it would eventually not get done.

There is a second absence problem, subtler and worse, and it is the reason :class:`EvidenceLevel`
is here rather than being a bare string. The `assertion_level` view in `schema.sql` returns a NULL
level for **two opposite reasons**:

  * ``no_evidence`` -- nothing supports this assertion. The atlas knows nothing.
  * ``direct_evidence_discordant`` -- direct evidence exists on *both sides* and the conflict is
    unresolved, so the view deliberately declines to grade rather than downgrading.

Those are as far apart as two states get: one is an empty cell, the other is an open scientific
dispute the atlas has gone to the trouble of recording. They arrive as the same NULL. The view
already distinguishes them in its ``basis`` column, so :class:`EvidenceLevel` requires the basis
and refuses to construct without it -- an ungraded level that cannot say why is not permitted to
exist, because the only thing a consumer could do with it is render a dash.

Nothing here talks to a database. `readers.py` builds these; this module defines what they mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Generic, TypeVar

__all__ = [
    "NOT_APPLICABLE_LITERAL",
    "UNKNOWN_LITERAL",
    "Absence",
    "Cited",
    "EvidenceLevel",
    "Quantity",
    "QueryValueError",
    "Value",
    "Zone",
    "from_state_column",
    "from_text_column",
]

T = TypeVar("T")

#: The literal strings `schema.sql` stores for the two non-NULL absences (see its header).
NOT_APPLICABLE_LITERAL: Final[str] = "NA"
UNKNOWN_LITERAL: Final[str] = "unknown"


class QueryValueError(RuntimeError):
    """A `Value` was asked for something it does not hold, or built in a state it may not be in.

    Not a subclass of the builtin `ValueError`, which it is not a kind of: a builtin ValueError
    means a caller passed bad data, while this means the *atlas* is in a state that should be
    impossible, and silently papering over it would hide the bug.
    """


class Zone(Enum):
    """PLAN.md D.2. Every fact leaving this layer carries one."""

    REPORTED = "R"
    HARMONIZED = "H"
    INFERRED = "I"

    @property
    def may_support_a_conclusion(self) -> bool:
        """False for Zone I until a curator promotes it (CONVENTIONS.md, "Data zones").

        Exposed as a property rather than left to the consumer to remember, because "is this
        allowed to be treated as a fact" is precisely the question a UI badge is answering.
        """
        return self is not Zone.INFERRED

    @property
    def display(self) -> str:
        return {"R": "reported", "H": "harmonized", "I": "inferred"}[self.value]


class Absence(Enum):
    """The three states of `CONVENTIONS.md` "Missing values", plus their rendering.

    The wire values match what `schema.sql` stores wherever it stores a string, so a round trip
    through this enum is lossless and greppable against the database.
    """

    NOT_RECORDED = "not_recorded"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"

    @property
    def display(self) -> str:
        return {
            "not_recorded": "not recorded",
            "not_applicable": "not applicable",
            "unknown": "unknown",
        }[self.value]

    @property
    def explanation(self) -> str:
        """Why the value is missing, in CONVENTIONS.md's words. For tooltips and exports."""
        return {
            "not_recorded": "the source never recorded it",
            "not_applicable": "recorded as not applicable",
            "unknown": "recorded, but could not be resolved to a controlled value",
        }[self.value]


@dataclass(frozen=True)
class Value(Generic[T]):
    """A fact with its zone, or an absence with its reason. Never both, never neither.

    Construct through :meth:`known` or :meth:`absent`; the invariant is checked in
    ``__post_init__`` so an illegal one fails where it is built rather than where it is read.
    """

    held: T | None
    absence: Absence | None
    zone: Zone | None = None

    def __post_init__(self) -> None:
        if (self.held is None) == (self.absence is None):
            raise QueryValueError(
                "a Value holds exactly one of a value or an absence; "
                f"got held={self.held!r}, absence={self.absence!r}"
            )

    @classmethod
    def known(cls, value: T, *, zone: Zone | None = None) -> Value[T]:
        return cls(held=value, absence=None, zone=zone)

    @classmethod
    def absent(cls, absence: Absence, *, zone: Zone | None = None) -> Value[T]:
        return cls(held=None, absence=absence, zone=zone)

    @property
    def is_known(self) -> bool:
        return self.absence is None

    def unwrap(self) -> T:
        """The value, or raise. Use where absence is genuinely a programming error."""
        if self.held is None:
            raise QueryValueError(
                f"value is absent ({self.absence.display if self.absence else '?'})"
            )
        return self.held

    def or_none(self) -> T | None:
        """The value or None, for a caller that has *already* handled the three states.

        Deliberately a method and not a property: the call site reads as a decision, which is the
        point. Every use of this is a place where three states become one, so it should be
        visible in review.
        """
        return self.held

    @property
    def display(self) -> str:
        if self.absence is not None:
            return self.absence.display
        return str(self.held)

    def as_json(self) -> dict[str, Any]:
        """The wire form. ``display`` is always present and always correct.

        A known value carries a ``value`` key; an absent one **has no ``value`` key at all**,
        rather than carrying ``"value": null``. That is the whole trick: a consumer reaching for
        `.value` on an absence gets `undefined` and a visible bug, instead of `null` and a silent
        one that renders identically to a real missing datum.
        """
        payload: dict[str, Any] = {"display": self.display}
        if self.zone is not None:
            payload["zone"] = self.zone.value
            payload["zone_display"] = self.zone.display
        if self.absence is None:
            payload["value"] = self.held
        else:
            payload["absent"] = self.absence.value
            payload["absent_because"] = self.absence.explanation
        return payload


@dataclass(frozen=True)
class Quantity:
    """A number that means something: value, unit, and the verbatim form it was reported in.

    `measurement` stores `value_as_reported`/`unit_as_reported` (Zone R, immutable, enforced by a
    trigger) beside `value_si`/`unit_si` (Zone H, derived). Both travel, because "2.09 g/L as the
    paper wrote it" and "2.09 g/L after our conversion" are different claims with different zones,
    and a view showing only the harmonized number has quietly dropped the source's actual words.
    """

    reported: Value[float]
    unit_reported: Value[str]
    si: Value[float]
    unit_si: Value[str]
    is_below_lod: bool = False
    is_upper_bound: bool = False

    @property
    def display(self) -> str:
        if not self.reported.is_known:
            return self.reported.display
        prefix = "<" if self.is_below_lod else ("≤" if self.is_upper_bound else "")
        unit = self.unit_reported.or_none() or ""
        return f"{prefix}{self.reported.unwrap():g} {unit}".strip()

    def as_json(self) -> dict[str, Any]:
        return {
            "display": self.display,
            "reported": self.reported.as_json(),
            "unit_reported": self.unit_reported.as_json(),
            "si": self.si.as_json(),
            "unit_si": self.unit_si.as_json(),
            "is_below_lod": self.is_below_lod,
            "is_upper_bound": self.is_upper_bound,
        }


@dataclass(frozen=True)
class EvidenceLevel:
    """L1-L5 with the basis that produced it, from the `assertion_level` view.

    ``level`` may be None, and when it is, ``basis`` is the only thing that says whether that
    means "nothing known" or "direct evidence, in open conflict". Constructing one without a
    basis is refused for that reason.
    """

    #: Bases on which the view declines to grade. Both yield ``level is None``.
    UNGRADED_BASES: ClassVar[frozenset[str]] = frozenset(
        {"no_evidence", "direct_evidence_discordant"}
    )

    level: str | None
    basis: str
    is_overridden: bool = False
    override_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.basis:
            raise QueryValueError("an evidence level must carry the basis it was derived from")
        if self.level is None and self.basis not in self.UNGRADED_BASES:
            raise QueryValueError(f"ungraded level with basis {self.basis!r}, which grades")

    @property
    def is_conflicted(self) -> bool:
        """True where the atlas holds direct evidence on both sides and has not resolved it.

        Not the same as unknown, and PLAN.md J.4 ("conflicts are first-class") is why this is a
        question a consumer can ask rather than one it has to infer from a string.
        """
        return self.basis == "direct_evidence_discordant"

    @property
    def display(self) -> str:
        if self.level is not None:
            return f"{self.level} (overridden)" if self.is_overridden else self.level
        return "conflicted" if self.is_conflicted else "no evidence"

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "level": self.level,
            "basis": self.basis,
            "display": self.display,
            "is_conflicted": self.is_conflicted,
            "is_overridden": self.is_overridden,
        }
        if self.override_reason is not None:
            payload["override_reason"] = self.override_reason
        return payload


@dataclass(frozen=True)
class Cited(Generic[T]):
    """A payload with the thing it can be traced back to.

    PLAN.md O.2.1: "Every factual clause carries a citation that resolves to an assertion, a
    measurement or a publication. A clause that cannot be cited is removed, not softened." This is
    that rule as a type -- ``source_id`` is not optional, so there is no way to emit a cited
    payload without saying what it cites.
    """

    payload: T
    source_kind: str
    source_id: str
    locator: str | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
        }
        if self.locator is not None:
            payload["locator"] = self.locator
        return payload


def _zone(raw: str | None) -> Zone | None:
    return Zone(raw) if raw else None


def from_text_column(raw: str | None, *, zone: str | None = None) -> Value[str]:
    """Read one of `schema.sql`'s text facets into a `Value`, honouring 'NA' and 'unknown'.

    The two literals are matched exactly, not case-folded: they are controlled values written by
    the loaders, and a row spelling one of them differently is a data bug better seen as a
    surprising string than silently absorbed here.
    """
    if raw is None:
        return Value.absent(Absence.NOT_RECORDED, zone=_zone(zone))
    if raw == NOT_APPLICABLE_LITERAL:
        return Value.absent(Absence.NOT_APPLICABLE, zone=_zone(zone))
    if raw == UNKNOWN_LITERAL:
        return Value.absent(Absence.UNKNOWN, zone=_zone(zone))
    return Value.known(raw, zone=_zone(zone))


def from_state_column(
    value: float | None, state: str | None, *, zone: str | None = None
) -> Value[float]:
    """Read a numeric facet and its `<col>_state` companion.

    The schema's rule, from its header: the numeric is NULL unless the state is 'recorded', and
    numeric NULL *with* state NULL means never recorded at all.

    A 'recorded' state over a NULL number is refused rather than reported as absent. A CHECK
    constraint already forbids it, so encountering one means either the constraint was bypassed or
    this function was handed mismatched columns -- and both are bugs that a quiet "not recorded"
    would bury exactly where nobody would look for it.
    """
    zone_ = _zone(zone)
    if state is None:
        if value is not None:
            raise QueryValueError(f"numeric {value!r} with no state column; the pair is mismatched")
        return Value.absent(Absence.NOT_RECORDED, zone=zone_)
    if state == "recorded":
        if value is None:
            raise QueryValueError("state is 'recorded' but the value is NULL")
        return Value.known(value, zone=zone_)
    if state == "not_applicable":
        return Value.absent(Absence.NOT_APPLICABLE, zone=zone_)
    if state == UNKNOWN_LITERAL:
        return Value.absent(Absence.UNKNOWN, zone=zone_)
    raise QueryValueError(f"unrecognised state {state!r}")
