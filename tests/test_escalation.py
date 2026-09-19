"""Tests for `fermdb.llm.escalation` — the four §7a triggers, the budget, and the confidence rule.

Three properties this file exists to hold down:

* **No test touches the network and no test needs a credential.** Every escalation runs through
  `MockProvider`; the real `agent-sdk` provider is never constructed here. An autouse fixture
  makes both a socket call and a credential lookup fail loudly if one ever appears.
* **The budget is a cap.** When it is exhausted the document is marked `escalation_pending`, not
  quietly left with its local result. The difference between those two is the whole reason the
  status exists, so it is asserted on the stored value, not on a log line.
* **Escalation never changes a confidence value.** The most tempting bug in the whole design is
  "Claude said high, and Claude is the expensive tier, so let it through". The test for it feeds
  exactly that answer in.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Mapping
from typing import Any

import pytest

from fermdb.llm import MockProvider, ProviderError
from fermdb.llm.escalation import (
    ESCALATION_STATUSES,
    ESCALATION_TRIGGERS,
    EXTRACTION_TIERS,
    HIGH_VALUE_CORPUS_RETRIEVED,
    HIGH_VALUE_CORPUS_SIZE,
    HIGH_VALUE_CORPUS_TAG,
    TIER_FIELD,
    Budget,
    BudgetExhausted,
    EscalationRunner,
    compare_passes,
    decide,
    stamp_provenance,
)
from fermdb.llm.providers import ESCALATION_ROLE, LlmConfig

PAYLOAD_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {"measurements": {"type": "array"}},
}

ESCALATED_PAYLOAD = (
    '{"measurements": [{"value": 22.6, "unit": "g/L", "confidence": "high", '
    '"quote": "22.6 g/L isobutanol"}]}'
)


@pytest.fixture(autouse=True)
def no_network_and_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that opens a socket, or reaches for a token, is a broken test."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def local_payload(confidence: str = "unverified") -> dict[str, Any]:
    return {
        "measurements": [
            {"value": 22.6, "unit": "g/L", "confidence": confidence, "quote": "22.6 g/L"}
        ]
    }


def runner(*, responses: list[str] | None = None, budget: Budget | None = None) -> EscalationRunner:
    """A runner wired to a mock. The model name comes from configuration, never a literal."""
    config = LlmConfig.load(env={})
    return EscalationRunner(
        provider=MockProvider(responses=responses if responses is not None else []),
        model=config.model_for(ESCALATION_ROLE),
        budget=Budget(max_documents=10) if budget is None else budget,
        prompt_version="measurement/v3",
    )


# --------------------------------------------------------------------------- self-consistency


def test_a_field_only_one_pass_proposed_is_reported_as_an_omission() -> None:
    """§7's false-negative risk: you cannot review what was never proposed.

    The second pass simply does not mention the yield. Nothing about that answer is invalid, so
    no validator would object — which is exactly why self-consistency is the trigger that catches
    it.
    """
    first = {"measurements": [{"value": 22.6}, {"value": 0.31, "basis": "consumed"}]}
    second = {"measurements": [{"value": 22.6}]}

    disagreement = compare_passes(first, second)

    assert disagreement.disagreed
    assert disagreement.omissions == ("measurements[1].basis", "measurements[1].value")
    assert disagreement.differing == ()
    assert "proposed by one pass only" in disagreement.describe()


def test_a_differing_value_is_reported_separately_from_an_omission() -> None:
    first = {"measurements": [{"value": 22.6}]}
    second = {"measurements": [{"value": 2.26}]}
    disagreement = compare_passes(first, second)
    assert disagreement.differing == ("measurements[0].value",)
    assert disagreement.omissions == ()


def test_two_identical_passes_do_not_escalate() -> None:
    payload = local_payload()
    disagreement = compare_passes(payload, dict(payload))
    assert not disagreement.disagreed
    assert decide(disagreement=disagreement).escalate is False


# ---------------------------------------------------------------------------------- triggers


def test_each_of_the_four_triggers_escalates_on_its_own() -> None:
    fired = {
        "self_consistency": decide(disagreement=compare_passes({"a": 1}, {"a": 2})),
        "validator_failure": decide(validator_failed_after_retry=True),
        "high_value_corpus": decide(corpus_tags=[HIGH_VALUE_CORPUS_TAG]),
        "curator_flag": decide(curator_flagged=True),
    }
    assert set(fired) == set(ESCALATION_TRIGGERS)
    for trigger, decision in fired.items():
        assert decision.escalate, trigger
        assert decision.triggers == (trigger,)
        assert decision.reasons and decision.reasons[0]


def test_nothing_escalates_when_no_trigger_fires() -> None:
    decision = decide()
    assert decision.escalate is False
    assert decision.triggers == ()
    assert decision.describe() == "no trigger fired"


def test_the_high_value_corpus_escalates_unconditionally_and_names_its_measurement() -> None:
    """The 33 isobutanol × mitochondria papers. The count is provenance, not a gate.

    Recording the retrieval date matters because the corpus can grow: the rule is "every member",
    and a re-count that disagrees with 33 is a fact about the corpus, not a reason to stop at 33.
    """
    decision = decide(corpus_tags=["something_else", HIGH_VALUE_CORPUS_TAG])
    assert decision.triggers == ("high_value_corpus",)
    assert str(HIGH_VALUE_CORPUS_SIZE) in decision.reasons[0]
    assert HIGH_VALUE_CORPUS_RETRIEVED in decision.reasons[0]
    assert HIGH_VALUE_CORPUS_SIZE == 33


def test_triggers_accumulate_rather_than_short_circuiting() -> None:
    """Which triggers fired is measurement data: it is how §7a's rules get re-tuned later."""
    decision = decide(
        disagreement=compare_passes({"a": 1}, {}),
        validator_failed_after_retry=True,
        corpus_tags=[HIGH_VALUE_CORPUS_TAG],
        curator_flagged=True,
    )
    assert decision.triggers == ESCALATION_TRIGGERS


# ------------------------------------------------------------------------------------- tier


def test_every_extraction_records_which_tier_produced_it() -> None:
    """Without `extracted_by_tier` on both tiers, per-field recall cannot be measured at all."""
    escalated = runner(responses=[ESCALATED_PAYLOAD]).escalate(
        "pmid:1",
        decision=decide(curator_flagged=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    kept = runner().escalate(
        "pmid:2",
        decision=decide(),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )

    assert escalated.value[TIER_FIELD] == "claude"
    assert escalated.value["measurements"][0][TIER_FIELD] == "claude"
    assert kept.value[TIER_FIELD] == "local"
    assert kept.value["measurements"][0][TIER_FIELD] == "local"
    assert {"claude", "local"} <= set(EXTRACTION_TIERS)


def test_an_unknown_tier_is_refused_rather_than_written() -> None:
    with pytest.raises(ValueError, match="unknown extraction tier"):
        stamp_provenance(local_payload(), tier="gpt")


def test_stamping_does_not_mutate_the_payload_it_was_given() -> None:
    payload = local_payload()
    stamp_provenance(payload, tier="claude")
    assert TIER_FIELD not in payload
    assert TIER_FIELD not in payload["measurements"][0]


# ------------------------------------------------------------------------------- confidence


def test_escalation_never_changes_a_confidence_value() -> None:
    """MODEL_ROUTING.md §5.2 / §7a: tier is not part of the derivation of confidence.

    The mock returns `"confidence": "high"` — the exact claim a more capable model is most likely
    to make and a reviewer most likely to accept. It stays `unverified` until a curator says
    otherwise, and what the model claimed is kept beside it as evidence about the model.
    """
    outcome = runner(responses=[ESCALATED_PAYLOAD]).escalate(
        "pmid:33",
        decision=decide(corpus_tags=[HIGH_VALUE_CORPUS_TAG]),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )

    record = outcome.value["measurements"][0]
    assert outcome.status == "escalated"
    assert record["confidence"] == "unverified"
    assert record["claimed_confidence"] == "high"


def test_a_local_record_keeps_its_unverified_confidence_too() -> None:
    outcome = runner().escalate(
        "pmid:5",
        decision=decide(),
        local_value=local_payload(confidence="medium"),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert outcome.value["measurements"][0]["confidence"] == "unverified"
    assert outcome.value["measurements"][0]["claimed_confidence"] == "medium"


# ----------------------------------------------------------------------------------- budget


def test_an_exhausted_budget_marks_the_document_pending_rather_than_keeping_it_silently() -> None:
    spent = Budget(max_documents=1)
    escalation = runner(responses=[ESCALATED_PAYLOAD], budget=spent)

    first = escalation.escalate(
        "pmid:1",
        decision=decide(curator_flagged=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    second = escalation.escalate(
        "pmid:2",
        decision=decide(curator_flagged=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )

    assert first.status == "escalated"
    assert second.status == "escalation_pending"
    assert second.needs_attention
    # The local result is still there — but it is labelled local, and the detail says why.
    assert second.tier == "local"
    assert second.value["measurements"][0][TIER_FIELD] == "local"
    assert "NOT been checked by the escalation tier" in second.detail
    assert "1/1 documents" in second.detail
    assert second.triggers == ("curator_flag",)


def test_a_token_budget_stops_escalation_once_it_is_spent() -> None:
    budget = Budget(max_documents=100, max_tokens=5)
    escalation = EscalationRunner(
        provider=MockProvider(
            responses=[ESCALATED_PAYLOAD, ESCALATED_PAYLOAD],
            prompt_tokens=4,
            completion_tokens=4,
        ),
        model=LlmConfig.load(env={}).model_for(ESCALATION_ROLE),
        budget=budget,
        prompt_version="v1",
    )
    decision = decide(curator_flagged=True)
    first = escalation.escalate(
        "pmid:1", decision=decision, local_value=local_payload(), prompt="p", schema=PAYLOAD_SCHEMA
    )
    second = escalation.escalate(
        "pmid:2", decision=decision, local_value=local_payload(), prompt="p", schema=PAYLOAD_SCHEMA
    )
    assert first.status == "escalated"
    assert budget.tokens == 8
    assert second.status == "escalation_pending"


def test_an_unlimited_budget_is_not_the_same_as_a_zero_budget() -> None:
    assert Budget().exhausted is False
    assert Budget().documents_remaining is None
    assert Budget(max_documents=1).documents_remaining == 1
    spent = Budget(max_documents=1)
    spent.claim()
    assert spent.exhausted
    assert spent.documents_remaining == 0
    with pytest.raises(BudgetExhausted):
        spent.claim()


def test_a_run_that_never_escalates_spends_nothing() -> None:
    escalation = runner()
    escalation.escalate(
        "pmid:1",
        decision=decide(),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert escalation.budget.documents == 0
    assert escalation.summary()["not_escalated"] == 1


# ------------------------------------------------------------------------------- the run loop


def test_a_failed_escalation_is_distinct_from_an_exhausted_budget() -> None:
    """A rejected Claude answer and an exhausted budget call for different actions.

    So they are different statuses rather than one catch-all: one needs a prompt or a curator,
    the other needs a bigger cap.
    """
    # Two bad answers: the run loop already feeds the errors back and retries once (L.1.3).
    escalation = runner(responses=["not json at all", "still not json"])
    outcome = escalation.escalate(
        "pmid:9",
        decision=decide(validator_failed_after_retry=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert outcome.status == "escalation_failed"
    assert outcome.needs_attention
    assert outcome.tier == "local"
    assert outcome.errors and "LlmValidationError" in outcome.errors[0]


def test_a_provider_failure_is_not_swallowed() -> None:
    """A backend that is down is an operational failure, not a per-document outcome.

    `LlmError` is caught, because a model that answered badly is a fact about the document.
    A `ProviderError` is not: it will be true for every remaining document, and turning it into
    a per-document status would produce a run that looks like 3,000 hard papers.
    """
    escalation = runner(responses=[])
    with pytest.raises(ProviderError):
        escalation.escalate(
            "pmid:9",
            decision=decide(curator_flagged=True),
            local_value=local_payload(),
            prompt="extract",
            schema=PAYLOAD_SCHEMA,
        )


def test_the_escalation_run_uses_the_configured_model_not_a_literal() -> None:
    provider = MockProvider(responses=[ESCALATED_PAYLOAD])
    configured = LlmConfig.load(env={"FERMDB_LLM_ESCALATION_MODEL": "some-configured-model"})
    EscalationRunner(
        provider=provider,
        model=configured.model_for(ESCALATION_ROLE),
        budget=Budget(max_documents=1),
        prompt_version="v1",
    ).escalate(
        "pmid:1",
        decision=decide(curator_flagged=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert [call[1] for call in provider.calls] == ["some-configured-model"]


def test_the_outcome_summary_names_every_status_even_at_zero() -> None:
    """A report that omits an empty status reads as "this did not happen" when it means "none"."""
    escalation = runner()
    escalation.escalate(
        "pmid:1",
        decision=decide(),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert set(escalation.summary()) == set(ESCALATION_STATUSES)
    assert escalation.summary()["escalated"] == 0


def test_escalation_records_the_provenance_of_the_run_that_produced_it() -> None:
    outcome = runner(responses=[ESCALATED_PAYLOAD]).escalate(
        "pmid:1",
        decision=decide(curator_flagged=True),
        local_value=local_payload(),
        prompt="extract",
        schema=PAYLOAD_SCHEMA,
    )
    assert outcome.stats is not None
    assert outcome.stats.model == LlmConfig.load(env={}).model_for(ESCALATION_ROLE)
    assert outcome.stats.prompt_version == "measurement/v3"
    assert outcome.escalated
