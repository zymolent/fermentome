"""Does a proposal's own quote support the claim the proposal makes about it?

`verify_span` answers a different question, and the gap between the two is where every wrong Zone
R row this project has found actually came from.

`verify_span` proves the quote is **really in the document at its offsets**. It says nothing about
whether the quote *supports the payload*. On 2026-09-22 three promoted rows were found to be
false, and **every one of them had a perfectly valid span**: the quote was genuinely in the paper,
and it simply did not name the strain the payload attributed it to. The model had read a sentence
from a structured abstract -- "the integration of PDH suppression by lpd1delta ... in BSW205 and
BSW206 strains" -- and filed it against BSW191.

So there is a second, cheaper question that nothing was asking:

    does the quoted text itself contain the things the payload says it is about?

A strain name, a number, a unit, a gene. If the payload claims a titer of 1.62 g/L for BSW191 and
the quote contains neither "BSW191" nor "1.62", then the subject was **inferred** -- from context,
from an adjacent sentence, from the model's reading of the paper as a whole. That inference may be
right, and often is; it is simply not *evidenced by the span the row cites*, and a Zone R row is
supposed to be.

**What this is for.** Reviewing every proposal by reading every paper is the project's rate limit
(PLAN.md W.2). Bulk-accepting without reading is the alternative, and it does not work here: the
errors are not outliers. 1.62 g/L is a perfectly ordinary isobutanol titer and `lpd1delta` is a
perfectly ordinary genotype, so no distributional check finds them. This gate splits the queue
instead. A proposal whose own quote names its subject and its value is *self-evidencing* and can
be accepted in bulk with a recorded reason. A proposal whose subject appears nowhere in its quote
is where the reading effort belongs, because that is where the errors have actually been.

**The bias is deliberate and one-directional.** A false negative costs a human one glance at a
proposal that was fine. A false positive admits a wrong row into the tier that means "a person
checked this". So every ambiguity resolves toward `REVIEW`: unknown record kind, missing field,
unparseable number, empty quote. This module never guesses in the direction of acceptance.

**One thing it cannot do, stated so nobody assumes otherwise.** Where a sentence pairs several
subjects with several numbers -- "the titer of the BSW205 and BSW206 strains reached 230 +/- 13
and 221 +/- 27 mg/L, respectively" -- containment proves both the strain and the number are in
the quote but says nothing about *which was paired with which*. Swapping the two would pass this
gate. It was checked by hand on the pending queue and the extractor had the pairing right in all
four such cases, so they are cleared rather than held; the alternative rule, "hold any quote
mentioning another strain", would have held every one of those four correct rows and most of the
gate's value with them. The multi-subject rule above is different in kind and is enforced,
because a field naming four strains is wrong *always*, not merely sometimes.

**It is not a substitute for reading.** It cannot tell a true claim from a false one -- only
whether the cited sentence carries the claim's identifying parts. A corroborated proposal can
still be wrong about something the quote does not mention, which is why `confidence` stays
`unverified` and `verified` stays false exactly as before. What it buys is that the *subject
inference* failure -- the one class of error this project has actually measured -- cannot pass
silently.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "IDENTIFYING_FIELDS",
    "CorroborationReport",
    "FieldCheck",
    "Verdict",
    "corroborate_payload",
    "corroborate_queue",
]


#: The fields whose presence in the quote makes a proposal self-evidencing, per record kind.
#:
#: Chosen as *identity* fields, not as every field: the question is "is this sentence about the
#: thing the row says it is about", so what matters is the subject, the number and the unit --
#: the parts that decide which row this becomes. A measurement's `basis` or `time_h` being absent
#: from the quote is normal and says nothing about whether the row is correctly attributed.
#:
#: `pathway_configurations` is deliberately absent. Its payload carries no subject at all -- the
#: extraction schema has no host field, which is why `curate.promote._plan_configuration` refuses
#: to guess one -- so there is nothing here to corroborate and every configuration goes to review
#: by construction. That is correct rather than a gap.
IDENTIFYING_FIELDS: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    # (payload key, what kind of thing it is)
    "strains": (("name_as_reported", "text"),),
    "modifications": (
        ("strain_name_as_reported", "text"),
        ("target_as_reported", "text"),
    ),
    "measurements": (
        ("strain_name_as_reported", "text"),
        ("value", "number"),
        ("unit", "unit"),
    ),
    "co_reported_higher_alcohols": (
        ("strain_name_as_reported", "text"),
        ("value", "number"),
        ("unit", "unit"),
    ),
    "conditions": (("value_as_reported", "text"),),
    "bottlenecks": (("node_as_reported", "text"),),
    "part_expression_records": (
        ("part_as_reported", "text"),
        ("host_as_reported", "text"),
    ),
}

#: Verdicts. `REVIEW` is the default for everything this module cannot positively clear.
ACCEPT: Final[str] = "accept"
REVIEW: Final[str] = "review"

Verdict = str

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
#: Characters a PDF or JATS text layer varies on and a human would not: the ligature and dash
#: families, and the several spellings of a prime. Folded on BOTH sides, so folding can only make
#: a match easier -- never make two genuinely different strings compare equal on the identity
#: that matters (a strain name differing only by a dash is the same strain).
_FOLD: Final[Mapping[str, str]] = {
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "−": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "×": "x",
}


def _normalize(text: str) -> str:
    """Casefolded, NFKC-normalised, whitespace-collapsed, dash-folded.

    NFKC is what turns the ligature in "five" back into `fi` and splits the superscripts a PDF
    text layer leaves behind -- the same class of artefact that made eight `parts_catalog.yaml`
    quotes fail their own span check on 2026-09-22.
    """
    folded = unicodedata.normalize("NFKC", text)
    for source, target in _FOLD.items():
        folded = folded.replace(source, target)
    return _WS_RE.sub(" ", folded).strip().casefold()


def _number_spellings(value: Any) -> tuple[str, ...]:
    """Every way a paper might print this number, so a miss means it is genuinely absent.

    `22` may be written `22`; `22.0` is the same number and `0.016` must not match `0.0160` only
    by luck. Trailing zeros are stripped and the bare integer form is offered alongside the
    decimal one. Anything that is not a number at all yields nothing, which routes to review.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ()
    spellings = {repr(value).strip("'\""), str(value)}
    if number.is_integer():
        spellings.add(str(int(number)))
        spellings.add(f"{int(number)}.0")
    text = f"{number:.10f}".rstrip("0").rstrip(".")
    spellings.add(text)
    return tuple(s for s in spellings if s)


#: Unit spellings that mean the same quantity. A paper writing `g L-1` for `g/L` is not evidence
#: of a mis-attribution, and treating it as one would send correct rows to review for no gain.
_UNIT_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "g/l": ("g/l", "g l-1", "gl-1", "g.l-1", "grams per liter", "grams per litre"),
    "mg/l": ("mg/l", "mg l-1", "mgl-1", "mg.l-1"),
    "g/g": ("g/g", "g g-1", "gg-1"),
    "mg/g": ("mg/g", "mg g-1", "mgg-1"),
    "%": ("%", "percent"),
    "h": ("h", "hour", "hours", "hr"),
}


@dataclass(frozen=True)
class FieldCheck:
    """One identifying field, and whether the quote carries it."""

    field: str
    kind: str
    claimed: str
    found: bool
    #: Why it failed, when "absent from the quote" is not the reason.
    note: str = ""

    def __str__(self) -> str:
        mark = "ok" if self.found else "ABSENT"
        return f"{self.field}={self.claimed!r} {mark}" + (f" ({self.note})" if self.note else "")


@dataclass(frozen=True)
class CorroborationReport:
    """What the quote does and does not support, for one proposal."""

    task_id: str
    record_kind: str
    verdict: Verdict
    checks: tuple[FieldCheck, ...]
    note: str

    @property
    def absent(self) -> tuple[str, ...]:
        return tuple(check.field for check in self.checks if not check.found)


#: Separators that mean the field lists several things rather than naming one.
_PLURAL_RE: Final[re.Pattern[str]] = re.compile(r",|\band\b|\bor\b|/")


def _names_one_thing(value: str) -> bool:
    """Is this field an identity, or a list of them?

    A real case from the pending queue: a measurement whose `strain_name_as_reported` was
    `"BSW100 pda1delta, BSW100 pdb1delta, BSW100 lpd1delta, and BSW100 lat1delta"`, taken from
    "isobutanol production ... increased to 138-159 mg/L in [those four] strains". The whole list
    appears verbatim in the quote, so every containment check passes -- and the row is still
    unusable, because 138 is the bottom of a range across four strains and the payload does not
    say which strain it belongs to.

    Containment cannot catch this; only counting can. A field naming several things is never an
    identity, so it goes to a reader regardless of how well the quote corroborates it.
    """
    fragments = [f for f in _PLURAL_RE.split(value) if len(f.strip()) >= 3]
    return len(fragments) <= 1


def _contains(haystack: str, needle: str) -> bool:
    normalized = _normalize(needle)
    # A one- or two-character "identity" is not evidence of anything -- it would match inside
    # almost any sentence. Treated as absent rather than as a match.
    return len(normalized) >= 3 and normalized in haystack


def _check_unit(haystack: str, claimed: str) -> bool:
    normalized = _normalize(claimed)
    for canonical, aliases in _UNIT_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return any(_normalize(alias) in haystack for alias in aliases)
    return len(normalized) >= 1 and normalized in haystack


def corroborate_payload(
    task_id: str, record_kind: str, payload: Mapping[str, Any]
) -> CorroborationReport:
    """Does this proposal's own quote contain the things the proposal is about?"""
    fields = IDENTIFYING_FIELDS.get(record_kind)
    if fields is None:
        return CorroborationReport(
            task_id,
            record_kind,
            REVIEW,
            (),
            f"no identifying fields defined for {record_kind!r}; nothing to corroborate, so this "
            "goes to a reader rather than being cleared by default",
        )

    span = payload.get("span")
    quote = str(span.get("quote", "")) if isinstance(span, dict) else ""
    if not quote.strip():
        return CorroborationReport(
            task_id, record_kind, REVIEW, (), "the proposal carries no quote to corroborate against"
        )
    haystack = _normalize(quote)

    checks: list[FieldCheck] = []
    for key, kind in fields:
        raw = payload.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            checks.append(FieldCheck(key, kind, "", False))
            continue
        if kind == "number":
            spellings = _number_spellings(raw)
            checks.append(FieldCheck(key, kind, str(raw), any(s in haystack for s in spellings)))
        elif kind == "unit":
            checks.append(FieldCheck(key, kind, str(raw), _check_unit(haystack, str(raw))))
        elif not _names_one_thing(str(raw)):
            # Fails even when the quote contains it verbatim -- see `_names_one_thing`.
            checks.append(
                FieldCheck(key, kind, str(raw), False, "names several things, not one subject")
            )
        else:
            checks.append(FieldCheck(key, kind, str(raw), _contains(haystack, str(raw))))

    missing = [c for c in checks if not c.found]
    if not missing:
        return CorroborationReport(
            task_id,
            record_kind,
            ACCEPT,
            tuple(checks),
            "the quote names every identifying field, so the subject was read rather than inferred",
        )
    absent = [c for c in missing if not c.note]
    other = [c for c in missing if c.note]
    parts: list[str] = []
    if absent:
        parts.append(
            "the quote does not contain "
            + ", ".join(f"{c.field}={c.claimed!r}" for c in absent)
            + " -- so that much was inferred from elsewhere and a reader should confirm it"
        )
    parts.extend(f"{c.field}={c.claimed!r} {c.note}" for c in other)
    return CorroborationReport(task_id, record_kind, REVIEW, tuple(checks), "; ".join(parts))


def corroborate_queue(
    conn: sqlite3.Connection, *, statuses: Sequence[str] = ("pending",)
) -> tuple[CorroborationReport, ...]:
    """Run the check over every task in ``statuses``. Reads only; writes nothing."""
    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        "SELECT id, record_kind, payload, edited_payload FROM curation_task "  # noqa: S608
        f"WHERE status IN ({placeholders}) ORDER BY id",
        tuple(statuses),
    ).fetchall()
    reports: list[CorroborationReport] = []
    for row in rows:
        raw = row["edited_payload"] or row["payload"]
        try:
            loaded = json.loads(str(raw))
        except json.JSONDecodeError:
            reports.append(
                CorroborationReport(
                    str(row["id"]), str(row["record_kind"]), REVIEW, (), "payload is not JSON"
                )
            )
            continue
        if not isinstance(loaded, dict):
            reports.append(
                CorroborationReport(
                    str(row["id"]), str(row["record_kind"]), REVIEW, (), "payload is not an object"
                )
            )
            continue
        reports.append(corroborate_payload(str(row["id"]), str(row["record_kind"]), loaded))
    return tuple(reports)
