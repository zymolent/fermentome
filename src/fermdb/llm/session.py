"""A provider for extractions produced by the model driving this Claude Code session.

MODEL_ROUTING.md §7a routes escalation to "Claude Code with the account's subscription" rather
than the metered API, because the project owner has a subscription and no API spend is permitted.
That path works when the Agent SDK is installed and ``CLAUDE_CODE_OAUTH_TOKEN`` is set. Neither is
true here, and there is a simpler route that needs neither: the session already *is* a Claude
model, reading the excerpt and writing the payload inline.

This provider exists so that route is recorded **honestly** rather than borrowed from
``MockProvider``. A mock is for tests and says ``provider='mock'``; an extraction produced this way
is real model output and its row must say which model produced it, or the provenance is a lie that
looks like an implementation detail.

**It gets no special standing.** MODEL_ROUTING.md §3 is explicit that capability increases the
plausibility of errors rather than reducing them, and §5 that nothing in the validator may be
relaxed because a better model is in use. So an extraction from here is Zone I with
``review_state='proposed'`` and ``confidence='unverified'``, its spans are re-resolved at their
offsets against the source exactly as a 7B model's are, and a quote that is not in the paper is
rejected on the same terms. The only thing this class changes is the name on the row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from ..config import DEFAULT_ESCALATION_MODEL
from .providers import Completion, ProviderError

__all__ = ["SESSION_PROVIDER_NAME", "SessionProvider"]

SESSION_PROVIDER_NAME: Final[str] = "claude-code-session"


class SessionProvider:
    """Serves payloads the session model wrote, one per call, with honest provenance.

    The session cannot be called as a function -- it produces its answer by reading the excerpt
    and writing the JSON, which happens between turns rather than inside a call stack. So the
    payloads are prepared and handed over, and the extraction harness runs its whole validation
    chain over them unchanged: schema check, span verification against the excerpt, translation
    into document offsets, re-verification against the document.
    """

    name = SESSION_PROVIDER_NAME

    #: Defaults to the configured escalation model, because that is what this path IS: MODEL_ROUTING
    #: section 7a's escalation tier, reached through the session rather than through the Agent SDK.
    #: No model name is written here -- config.py is the one place they live.

    def __init__(
        self,
        payloads: Sequence[str],
        *,
        model: str = DEFAULT_ESCALATION_MODEL,
        note: str = "written inline by the session model, not fetched from a backend",
    ) -> None:
        if not payloads:
            raise ProviderError(
                "SessionProvider was given no payloads. An empty queue would make the harness "
                "report 'the model produced nothing', which is a claim about a paper rather than "
                "about a missing input."
            )
        self._queue = list(payloads)
        self._model = model
        self._note = note
        self.calls: list[tuple[str, str]] = []

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Completion:
        """Return the next prepared payload. Never opens a socket and never costs API spend."""
        self.calls.append((prompt, model))
        if not self._queue:
            raise ProviderError(
                f"SessionProvider ran out of payloads on call {len(self.calls)}. The harness "
                f"retries once with the validator's complaints fed back, so a paper that fails "
                f"validation needs a second payload written against those complaints."
            )
        return Completion(
            text=self._queue.pop(0),
            provider=self.name,
            # The model asked for by config is ignored: what answered is the session, and the row
            # has to say so. Recording the configured local model here would attribute this
            # extraction to a daemon that was never running.
            model=self._model,
            model_version=f"{self._model} ({self._note})",
            prompt_tokens=None,
            completion_tokens=None,
            duration_s=0.0,
            finish_reason="stop",
        )
