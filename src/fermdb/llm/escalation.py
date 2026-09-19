"""Local-to-Claude escalation: the four triggers of ``docs/reference/MODEL_ROUTING.md`` §7a.

The literature track runs local models on everything. That is affordable because span
verification is model-independent (§3) — the validator, not the model, is what rejects a number
that is not in the paper. But §7 names the risk that containment does *not* cover:

    A weaker model fails more often by **omission**. False positives are caught by the validator
    and by review. **False negatives are invisible: you cannot review what was never proposed.**

So local output is evaluated on recall, and these four triggers hand a document to Claude:

``self_consistency``
    Two local passes disagree. The cheap signal, and the interesting one: local inference is free,
    so running the same document twice costs nothing, and a field one pass extracts and the other
    misses is exactly the omission review cannot see. This is the only trigger that aims at the
    false-negative risk directly, which is why :func:`compare_passes` reports "present in one pass
    only" separately from "both passed, different value".
``validator_failure``
    The deterministic checks still rejected the answer after :mod:`fermdb.llm.runtime` had already
    fed the errors back once. The local model has demonstrably failed on this document.
``high_value_corpus``
    Unconditional, for the isobutanol × mitochondria set — 33 papers at the 2026-09-19/20 NCBI
    retrieval, a rounding error in cost and the core of the strategy C versus E decision.
``curator_flag``
    A human looked and wants it done properly.

Three rules this module makes structural rather than hoping for:

* **Every extraction records** ``extracted_by_tier``. Without it the phase-1 gold standard cannot
  measure local-versus-Claude recall per field type, which is the measurement that is supposed to
  decide the routing. Both tiers are stamped, not just the escalated one — a field only Claude
  proposed is only visible as a gap if the local rows say they are local.
* **The budget is a cap, not a hope.** When it is exhausted a document becomes
  ``escalation_pending`` and says so. Silently keeping the local result would make a budget
  overrun indistinguishable from a document nothing was wrong with.
* **Escalation never changes a confidence value.** A Claude-produced extraction is still
  ``unverified`` until a curator checks it. §5 rule 2 is about the *derivation* of confidence, and
  model tier is not part of that derivation — if it were, "high confidence" would come to mean
  "an expensive model said so", which is precisely the claim this project refuses to make.
  :func:`stamp_provenance` forces it, and ``tests/test_escalation.py`` asserts it.

This module holds no model name and no credential. The model comes from
``LlmConfig.model_for('escalation')`` and the credential from the environment, both by way of
:mod:`fermdb.llm.providers`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .providers import Provider
from .runtime import LlmError, ResultCache, RunResult, RunStats, run
from .validate import MODEL_CONFIDENCE

__all__ = [
    "ESCALATION_STATUSES",
    "ESCALATION_TRIGGERS",
    "EXTRACTION_TIERS",
    "HIGH_VALUE_CORPUS_RETRIEVED",
    "HIGH_VALUE_CORPUS_SIZE",
    "HIGH_VALUE_CORPUS_TAG",
    "TIER_FIELD",
    "Budget",
    "BudgetExhausted",
    "Disagreement",
    "EscalationDecision",
    "EscalationOutcome",
    "EscalationRunner",
    "compare_passes",
    "decide",
    "stamp_provenance",
]

JsonObject = dict[str, Any]

#: The four triggers, in the order §7a lists them.
ESCALATION_TRIGGERS: Final[tuple[str, ...]] = (
    "self_consistency",
    "validator_failure",
    "high_value_corpus",
    "curator_flag",
)

#: Which tier produced an extraction. A closed set, recorded on every record.
EXTRACTION_TIERS: Final[tuple[str, ...]] = ("local", "claude")

#: The field that carries it. Named once so a query and a writer cannot drift.
TIER_FIELD: Final[str] = "extracted_by_tier"

#: What can happen to one document.
#:
#: ``escalation_pending`` is the load-bearing one: the local result is still there, but it is
#: marked as *not* the answer the routing policy asked for. ``escalation_failed`` is kept distinct
#: because "the budget ran out" and "Claude answered and the validator rejected it" call for
#: different actions.
ESCALATION_STATUSES: Final[tuple[str, ...]] = (
    "not_escalated",
    "escalated",
    "escalation_pending",
    "escalation_failed",
)

#: The high-value corpus of §7a, identified by a tag on the document rather than by a list of
#: ids: the ids are a property of the literature index, not of this module, and a hardcoded list
#: would be a second authority for a set that the ingest already records.
HIGH_VALUE_CORPUS_TAG: Final[str] = "isobutanol_x_mitochondria"

#: Its measured size. NCBI PubMed, isobutanol × mitochondria, retrieved 2026-09-19/20. Recorded
#: for reporting and as the number a re-count is compared against — **not** used as a gate, so a
#: corpus that has since grown escalates every member rather than the first 33 of them.
HIGH_VALUE_CORPUS_SIZE: Final[int] = 33
HIGH_VALUE_CORPUS_RETRIEVED: Final[str] = "2026-09-19/20"


# ----------------------------------------------------------------------------- self-consistency


@dataclass(frozen=True)
class Disagreement:
    """How two local passes over the same document differ.

    Split three ways on purpose. ``only_in_first`` and ``only_in_second`` are *omissions* — the
    false-negative signal §7 says review cannot see — while ``differing`` is the ordinary
    disagreement a validator might also have caught. A caller that wants to weight them
    differently can; :func:`decide` treats any of the three as a trigger.
    """

    only_in_first: tuple[str, ...] = ()
    only_in_second: tuple[str, ...] = ()
    differing: tuple[str, ...] = ()

    @property
    def disagreed(self) -> bool:
        """True if the passes differ at all."""
        return bool(self.only_in_first or self.only_in_second or self.differing)

    @property
    def omissions(self) -> tuple[str, ...]:
        """Fields one pass proposed and the other did not, either way round."""
        return tuple(sorted({*self.only_in_first, *self.only_in_second}))

    def describe(self) -> str:
        """One line naming what differed, for the escalation record."""
        parts = []
        if self.omissions:
            parts.append(f"proposed by one pass only: {', '.join(self.omissions)}")
        if self.differing:
            parts.append(f"different values: {', '.join(self.differing)}")
        return "; ".join(parts) or "the two local passes agreed"


def compare_passes(first: Mapping[str, Any], second: Mapping[str, Any]) -> Disagreement:
    """Compare two local passes field by field, by flattened path.

    Records inside a payload section are compared **by position**, which is the honest reading of
    two independent passes: a record the second pass did not produce shows up as a missing path,
    which is the omission we are looking for. Two passes that found the same measurements in a
    different order will register as differing, and escalate; that is the safe direction to be
    wrong in, and it costs one Claude call rather than a missed measurement.
    """
    left = dict(_flatten(first))
    right = dict(_flatten(second))
    only_in_first = tuple(sorted(key for key in left if key not in right))
    only_in_second = tuple(sorted(key for key in right if key not in left))
    differing = tuple(sorted(key for key in left.keys() & right.keys() if left[key] != right[key]))
    return Disagreement(only_in_first, only_in_second, differing)


def _flatten(value: object, prefix: str = "") -> list[tuple[str, Any]]:
    """Every leaf of a JSON value as ``(path, leaf)``. Lists are indexed, dicts are keyed."""
    if isinstance(value, Mapping):
        flattened: list[tuple[str, Any]] = []
        for key in sorted(str(k) for k in value):
            flattened.extend(_flatten(value[key], f"{prefix}.{key}" if prefix else key))
        return flattened
    if isinstance(value, list):
        flattened = []
        for index, item in enumerate(value):
            flattened.extend(_flatten(item, f"{prefix}[{index}]"))
        return flattened
    return [(prefix or "$", value)]


# ------------------------------------------------------------------------------------- deciding


@dataclass(frozen=True)
class EscalationDecision:
    """Whether a document goes to Claude, and on which of the four triggers."""

    escalate: bool
    triggers: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def describe(self) -> str:
        """One line, for the escalation record and the log."""
        if not self.escalate:
            return "no trigger fired"
        return "; ".join(self.reasons) or ", ".join(self.triggers)


def decide(
    *,
    disagreement: Disagreement | None = None,
    validator_failed_after_retry: bool = False,
    corpus_tags: Iterable[str] = (),
    curator_flagged: bool = False,
) -> EscalationDecision:
    """Apply the four §7a triggers. Any one of them is enough.

    Every trigger is passed in rather than discovered here: whether the validator failed is the
    run loop's knowledge, which corpus a document belongs to is the literature index's, and a
    curator flag is the queue's. This function exists so the *policy* is in one readable place
    and can be tested without any of those three.
    """
    triggers: list[str] = []
    reasons: list[str] = []

    if disagreement is not None and disagreement.disagreed:
        triggers.append("self_consistency")
        reasons.append(f"two local passes disagreed ({disagreement.describe()})")
    if validator_failed_after_retry:
        triggers.append("validator_failure")
        reasons.append("the local model failed validation after its one retry")
    tags = {str(tag) for tag in corpus_tags}
    if HIGH_VALUE_CORPUS_TAG in tags:
        triggers.append("high_value_corpus")
        reasons.append(
            f"member of the {HIGH_VALUE_CORPUS_TAG} corpus "
            f"({HIGH_VALUE_CORPUS_SIZE} papers at the {HIGH_VALUE_CORPUS_RETRIEVED} retrieval), "
            "which escalates unconditionally"
        )
    if curator_flagged:
        triggers.append("curator_flag")
        reasons.append("a curator flagged this document")

    return EscalationDecision(bool(triggers), tuple(triggers), tuple(reasons))


# --------------------------------------------------------------------------------------- budget


class BudgetExhausted(RuntimeError):
    """The escalation budget is spent. Caught by the runner and turned into a pending status."""


@dataclass
class Budget:
    """How much escalation one run may do, and how much it has done.

    Documents are the primary cap because they are what an operator can reason about ("escalate
    at most the 33 high-value papers plus a hundred others"). A token cap is optional and
    secondary: it protects against one pathological document, not against volume.

    Mutable on purpose — it is the one piece of per-run state here — and every charge is recorded
    even when it takes the run over the line, so a report can say by how much.
    """

    max_documents: int = 0
    max_tokens: int | None = None
    documents: int = 0
    tokens: int = 0

    @property
    def exhausted(self) -> bool:
        """True when the next escalation would exceed a cap."""
        if self.max_documents and self.documents >= self.max_documents:
            return True
        return self.max_tokens is not None and self.tokens >= self.max_tokens

    @property
    def documents_remaining(self) -> int | None:
        """Documents left, or None when no document cap is set."""
        if not self.max_documents:
            return None
        return max(0, self.max_documents - self.documents)

    def claim(self) -> None:
        """Take one document's worth of budget, or raise :class:`BudgetExhausted`."""
        if self.exhausted:
            raise BudgetExhausted(self.describe())
        self.documents += 1

    def charge_tokens(self, tokens: int | None) -> None:
        """Record what an escalation actually cost. A backend that reports nothing charges 0."""
        self.tokens += tokens or 0

    def describe(self) -> str:
        """One line, for the pending record: what the cap was and where the run stands."""
        documents = f"{self.documents}/{self.max_documents or 'unlimited'} documents"
        tokens = f"{self.tokens}/{self.max_tokens} tokens" if self.max_tokens else "no token cap"
        return f"escalation budget: {documents}, {tokens}"


# ---------------------------------------------------------------------------------- provenance


def stamp_provenance(value: Mapping[str, Any], *, tier: str) -> JsonObject:
    """Return a copy of a payload with ``extracted_by_tier`` on it and every record inside it.

    Also forces ``confidence`` back to ``'unverified'`` on every record, whatever the model
    claimed and whichever tier produced it. :func:`fermdb.llm.validate.validate_records` already
    does this for the records it accepts; doing it here as well is not redundant, because this is
    the path where a *more capable* model's answer arrives, and that is exactly the path where
    "surely this one is reliable" would otherwise creep in.

    A payload is ``{section: [record, ...], ...}``, the shape
    :func:`fermdb.extract.schemas.iter_payload_records` reads; sections that are not lists of
    objects are copied through untouched.
    """
    if tier not in EXTRACTION_TIERS:
        raise ValueError(f"unknown extraction tier {tier!r}; expected one of {EXTRACTION_TIERS}")
    stamped: JsonObject = {}
    for key, section in value.items():
        if isinstance(section, list):
            stamped[key] = [
                _stamp_record(item, tier) if isinstance(item, Mapping) else item for item in section
            ]
        else:
            stamped[key] = section
    stamped[TIER_FIELD] = tier
    return stamped


def _stamp_record(record: Mapping[str, Any], tier: str) -> JsonObject:
    stamped: JsonObject = dict(record)
    claimed = stamped.get("confidence")
    if isinstance(claimed, str) and claimed != MODEL_CONFIDENCE:
        # Kept, not discarded: what a model claimed about itself is evidence about the model.
        stamped.setdefault("claimed_confidence", claimed)
    stamped["confidence"] = MODEL_CONFIDENCE
    stamped[TIER_FIELD] = tier
    return stamped


# --------------------------------------------------------------------------------------- runner


@dataclass(frozen=True)
class EscalationOutcome:
    """What happened to one document: the value to store, and the honest label for it."""

    document_id: str
    status: str
    tier: str
    value: JsonObject
    triggers: tuple[str, ...] = ()
    detail: str = ""
    stats: RunStats | None = None
    errors: tuple[str, ...] = ()

    @property
    def escalated(self) -> bool:
        """True only when Claude actually produced the stored value."""
        return self.status == "escalated"

    @property
    def needs_attention(self) -> bool:
        """True when the routing policy asked for Claude and did not get it."""
        return self.status in ("escalation_pending", "escalation_failed")


class EscalationRunner:
    """Runs the escalation tier for a run: one provider, one model, one budget.

    Constructed explicitly with a provider, never from configuration alone. That is deliberate:
    it means no code path can reach Claude because an environment variable happened to be set,
    and a test that has not passed a mock cannot accidentally start a subprocess.
    """

    def __init__(
        self,
        *,
        provider: Provider,
        model: str,
        budget: Budget,
        prompt_version: str,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
        cache: ResultCache | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.budget = budget
        self.prompt_version = prompt_version
        self.options = options
        self.timeout_s = timeout_s
        self.cache = cache
        #: Every outcome, in order, so a run can report its escalation shape without re-deriving it.
        self.outcomes: list[EscalationOutcome] = []

    def escalate(
        self,
        document_id: str,
        *,
        decision: EscalationDecision,
        local_value: Mapping[str, Any],
        prompt: str,
        schema: Mapping[str, Any],
        post_validate: Callable[[JsonObject], Sequence[str]] | None = None,
    ) -> EscalationOutcome:
        """Escalate one document if its decision says so, and record what happened either way.

        The local value is always returned as the fallback, stamped ``local`` — there is no
        outcome where a caller gets nothing and has to remember that "no escalation" meant "keep
        what you had".

        The budget is claimed *before* the call, so an escalation that fails still spends its
        document. That is deliberate: the tokens were spent whether or not the answer validated,
        and a budget that only counted successes would let a run of failures spend without limit.
        """
        local = stamp_provenance(local_value, tier="local")
        if not decision.escalate:
            return self._record(
                EscalationOutcome(
                    document_id=document_id,
                    status="not_escalated",
                    tier="local",
                    value=local,
                    detail=decision.describe(),
                )
            )

        try:
            self.budget.claim()
        except BudgetExhausted as exhausted:
            return self._record(
                EscalationOutcome(
                    document_id=document_id,
                    status="escalation_pending",
                    tier="local",
                    value=local,
                    triggers=decision.triggers,
                    detail=(
                        f"{decision.describe()}, but {exhausted}. The local result is kept and "
                        "queued: it has NOT been checked by the escalation tier."
                    ),
                )
            )

        try:
            result: RunResult = run(
                prompt,
                schema,
                provider=self.provider,
                model=self.model,
                prompt_version=self.prompt_version,
                options=self.options,
                timeout_s=self.timeout_s,
                cache=self.cache,
                post_validate=post_validate,
            )
        except LlmError as error:
            return self._record(
                EscalationOutcome(
                    document_id=document_id,
                    status="escalation_failed",
                    tier="local",
                    value=local,
                    triggers=decision.triggers,
                    detail=f"{decision.describe()}, but the escalation run failed",
                    errors=(f"{type(error).__name__}: {error}",),
                )
            )

        self.budget.charge_tokens(result.stats.total_tokens)
        return self._record(
            EscalationOutcome(
                document_id=document_id,
                status="escalated",
                tier="claude",
                value=stamp_provenance(result.value, tier="claude"),
                triggers=decision.triggers,
                detail=decision.describe(),
                stats=result.stats,
            )
        )

    def _record(self, outcome: EscalationOutcome) -> EscalationOutcome:
        self.outcomes.append(outcome)
        return outcome

    def summary(self) -> dict[str, int]:
        """Count of outcomes by status, every status present even at zero."""
        counts = dict.fromkeys(ESCALATION_STATUSES, 0)
        for outcome in self.outcomes:
            counts[outcome.status] += 1
        return counts
