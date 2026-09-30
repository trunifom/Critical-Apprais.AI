"""The interface between the screening engine and a language-model provider (plan chapter 9.1).

The engine knows only :class:`LLMProvider`. A provider turns one :class:`LLMRequest` into one
:class:`LLMResponse` or raises a subclass of :class:`~crapai.errors.ProviderError`; it never
returns a half-result and never hides an error in the text. The error classes carry the retry rule:

========================  =====================================================================
``RateLimited`` (E302)    wait (``retry_after_s`` if given) and try again
``TransientError`` (E305) server error, timeout, lost connection: try again with back-off
``AuthError`` (E301)      the key is wrong or missing: stop the whole run
``QuotaExceeded`` (E307)  credit used up: pause the whole run
``ContextTooLong`` (E303) the record does not fit: no retry, the record gets status ``too_long``
``ContentRefused`` (E306) safety filter: no retry, the record is marked for manual review
========================  =====================================================================

This module holds data classes and the protocol only: no network, no SDK import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from crapai.errors import ProviderError


@dataclass(frozen=True)
class LLMRequest:
    """One question to the model.

    Attributes:
        system: The system prompt (role, rules, output contract).
        user: The user message (criteria and the record).
        model: Model name as the provider knows it.
        temperature: Sampling temperature (0 = as deterministic as the provider allows).
        top_p: Nucleus sampling, or None to leave it to the provider.
        max_output_tokens: Hard limit for the answer.
        response_schema: JSON schema for providers with structured output, else None (the
            answer is then validated in code).
        seed: Seed for providers that support one ("best effort", never a guarantee).
        timeout_s: Time allowed for this one request.
        request_id: Our own id (study id and attempt) for the log; never sent as content.
    """

    system: str
    user: str
    model: str
    temperature: float = 0.0
    top_p: float | None = None
    max_output_tokens: int = 800
    response_schema: dict[str, Any] | None = None
    seed: int | None = None
    timeout_s: float = 60.0
    request_id: str = ""


@dataclass
class LLMResponse:
    """The model's answer.

    Attributes:
        text: Raw text of the answer (a JSON string for structured output).
        model_returned: Model name the provider reports; it can differ from the request.
        tokens_in: Input tokens as counted by the provider.
        tokens_out: Output tokens as counted by the provider.
        finish_reason: ``stop``, ``length`` (cut off), ``content_filter`` ...
        request_id: The provider's own id of the call, if any.
        latency_s: Time the call took.
        raw: The provider's full answer (kept only when ``output.keep_raw_responses`` is on).
    """

    text: str
    model_returned: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = "stop"
    request_id: str | None = None
    latency_s: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Capabilities:
    """What a model can do (from ``templates/models.yaml``, extended by the project).

    ``None`` means unknown, which is treated like "not supported" but may be tried.
    """

    context_tokens: int | None = None
    structured_output: bool | None = None
    seed: bool | None = None
    note: str = ""


@runtime_checkable
class LLMProvider(Protocol):
    """A language-model provider (OpenAI, an OpenAI-compatible service such as SwissGPT, a mock)."""

    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one request and return the answer.

        Raises:
            ProviderError: a subclass as described in the module docstring.
        """
        ...

    def count_tokens(self, text: str, model: str) -> int:
        """Tokens of ``text`` for ``model`` (an estimate where the provider has no tokenizer)."""
        ...

    def capabilities(self, model: str) -> Capabilities:
        """What ``model`` supports."""
        ...


def retry_after_of(error: ProviderError) -> float | None:
    """Seconds the provider asked us to wait (``details["retry_after_s"]``), if it said so."""
    value = error.details.get("retry_after_s")
    return float(value) if isinstance(value, int | float) and value >= 0 else None
