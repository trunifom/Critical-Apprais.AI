"""Client for Jev, TypeSafe AI's "System One" typed-decision model (ADR 0029).

Jev is not a chat-completion provider: one request asks one or more typed questions ("noul",
"choice" or "score") about a piece of text ("state") and gets back a typed answer with calibrated
probabilities, never free text. It therefore does not implement :class:`crapai.llm.base.LLMProvider`
(there is no text answer for :mod:`crapai.screening.answer` to parse) and is not used by the
screening engine. :mod:`crapai.services.ai_prefilter` is its only caller.

Only the ``noul`` ("yes/no proposition") primitive is used here, with exactly one question per
call: whether the given title/abstract clearly does *not* meet the project's inclusion criteria.
``choice``/``score`` are not needed for this and are out of scope (ADR 0029).

Endpoint: ``POST <base_url>`` (default ``https://api.typesafe.ai/v1/systemone``),
``Authorization: Bearer <key>``, body ``{model, state, questions: {id: {type, instructions}}}``.
Response: ``{model, answers: {id: {probabilities, confidence}}, usage: {input_tokens,
output_tokens, cost}}``.

Errors are translated into the program's own classes, the same ones
:mod:`crapai.llm.openai_provider` uses, so the retry policy in :mod:`crapai.llm.resilience` applies
unchanged:

==============================================  ==============================================
What happened                                   Error
==============================================  ==============================================
401, 403                                        ``AuthError`` (E301): stop
429, quota wording                              ``QuotaExceeded`` (E307): stop
429 otherwise                                   ``RateLimited`` (E302)
timeout, no connection, 5xx                     ``TransientError`` (E305)
state over the context window                   ``ContextTooLong`` (E303): never retried
any other 4xx                                   ``ProviderError`` (E305), not retried
==============================================  ==============================================

The key is read from the environment variable ``ai_prefilter.api_key_env`` names; it is held in
memory only, never written to a file or a log, and never part of an error message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from crapai.errors import (
    AuthError,
    ContextTooLong,
    ProviderError,
    QuotaExceeded,
    RateLimited,
    TransientError,
)

logger = logging.getLogger(__name__)

QUESTION_ID = "exclude"
_QUOTA_WORDS = ("quota", "billing", "credit")
_CONTEXT_WORDS = ("too large", "context window", "32768", "32,768", "state too large")


@dataclass(frozen=True)
class JevDecision:
    """One ``noul`` answer: whether the record clearly does not meet the criteria.

    Attributes:
        probability_true: Calibrated probability that the proposition ("does not meet the
            criteria") is true.
        probability_false: Calibrated probability that it is false (meets the criteria, or it is
            unclear).
        confidence: Jev's own confidence in this answer (published calibration: reliable from
            about 0.9 upward, see ADR 0029).
        cost: USD cost of this one request, as reported by Jev.
        tokens_in: Input tokens billed.
        tokens_out: Output tokens (always free, but reported for transparency).
        model_returned: Model name Jev reports (can differ from the one requested).
    """

    probability_true: float
    probability_false: float
    confidence: float
    cost: float
    tokens_in: int
    tokens_out: int
    model_returned: str


def translate(status: int | None, body_text: str) -> ProviderError:
    """Turn an HTTP status and lower-cased response body into one of our provider errors."""
    text = body_text.lower()
    if status in (401, 403):
        return AuthError(f"The key was refused (HTTP {status})", code="E301")
    if status == 429:
        if any(word in text for word in _QUOTA_WORDS):
            return QuotaExceeded("The credit or quota is used up", code="E307")
        return RateLimited("Too many requests (HTTP 429)", code="E302")
    if status == 400 and any(word in text for word in _CONTEXT_WORDS):
        return ContextTooLong("The state is longer than Jev's context window", code="E303")
    if isinstance(status, int) and status >= 500:
        return TransientError(f"Server error (HTTP {status})", code="E305")
    if isinstance(status, int) and status >= 400:
        return ProviderError(f"Jev rejected the request (HTTP {status})", code="E305")
    return ProviderError("Jev answered with an unexpected status", code="E305")


class JevClient:
    """Talks to the Jev "System One" endpoint; one ``noul`` question per call.

    Args:
        api_key: The key (from the environment; never stored on disk).
        base_url: Address of the endpoint (``ai_prefilter.base_url``).
        timeout_s: HTTP timeout of one request.
        client: A ready ``httpx.AsyncClient`` (for tests, with a mock transport); otherwise one
            is created.

    Raises:
        ProviderError: E305 if the ``httpx`` package is not installed.
    """

    name = "jev"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.typesafe.ai/v1/systemone",
        timeout_s: float = 30.0,
        client: Any = None,
    ) -> None:
        self._base_url = base_url
        if client is not None:
            self._client = client
            return
        try:
            import httpx
        except ImportError as exc:
            raise ProviderError(
                "The package httpx is not installed",
                code="E305",
                hint='Install it with: pip install "crapai[prefilter-jev]"',
            ) from exc
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout_s
        )

    async def classify(self, state: str, instructions: str, *, model: str) -> JevDecision:
        """Ask the one ``noul`` question about ``state`` and return the typed answer.

        Raises:
            ProviderError: one of the classes in the module docstring.
        """
        import httpx

        payload = {
            "model": model,
            "state": state,
            "questions": {QUESTION_ID: {"type": "noul", "instructions": instructions}},
        }
        try:
            response = await self._client.post(self._base_url, json=payload)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            name = type(exc).__name__
            raise TransientError(f"No connection to Jev ({name})", code="E305") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Jev request failed ({type(exc).__name__})", code="E305") from exc
        if response.status_code >= 400:
            raise translate(response.status_code, response.text)
        data = response.json()
        answer = data.get("answers", {}).get(QUESTION_ID, {})
        probabilities = answer.get("probabilities", {})
        usage = data.get("usage", {})
        return JevDecision(
            probability_true=float(probabilities.get("true", 0.0)),
            probability_false=float(probabilities.get("false", 0.0)),
            confidence=float(answer.get("confidence", 0.0)),
            cost=float(usage.get("cost", 0.0)),
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            model_returned=str(data.get("model", "")),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


class MockJevClient:
    """A deterministic stand-in for :class:`JevClient`; no network, no key.

    The answer for a ``state`` is chosen by a marker inside it (checked in this order), so tests
    can pick an exact scenario by writing it into the record's title/abstract:

    ===================  ========================================================================
    Marker                Jev's answer
    ===================  ========================================================================
    ``JEV_TRUE_HIGH``     true (does not meet criteria), confidence 0.95 -- marks the record
    ``JEV_TRUE_LOW``      true, confidence 0.6 -- below any sane floor, must not mark the record
    ``JEV_FALSE``         false (meets the criteria, or unclear), confidence 0.95
    ``JEV_ERROR_AUTH``    raises ``AuthError`` (E301)
    ``JEV_ERROR_RATE``    raises ``RateLimited`` (E302)
    ``JEV_ERROR_QUOTA``   raises ``QuotaExceeded`` (E307)
    ``JEV_ERROR_CONTEXT`` raises ``ContextTooLong`` (E303)
    ``JEV_ERROR_TRANSIENT`` raises ``TransientError`` (E305)
    (none of the above)   false, confidence 0.5 (the safe default: never marks the record)
    ===================  ========================================================================
    """

    name = "jev"

    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, state: str, instructions: str, *, model: str) -> JevDecision:
        """The scripted answer for ``state`` (see the class docstring for the markers)."""
        self.calls += 1
        if "JEV_ERROR_AUTH" in state:
            raise AuthError("The key was refused (mock)", code="E301")
        if "JEV_ERROR_RATE" in state:
            raise RateLimited("Too many requests (mock)", code="E302")
        if "JEV_ERROR_QUOTA" in state:
            raise QuotaExceeded("The credit is used up (mock)", code="E307")
        if "JEV_ERROR_CONTEXT" in state:
            raise ContextTooLong("The state is too large (mock)", code="E303")
        if "JEV_ERROR_TRANSIENT" in state:
            raise TransientError("Server error (mock)", code="E305")
        if "JEV_TRUE_HIGH" in state:
            probability_true, confidence = 0.95, 0.95
        elif "JEV_TRUE_LOW" in state:
            probability_true, confidence = 0.7, 0.6
        elif "JEV_FALSE" in state:
            probability_true, confidence = 0.05, 0.95
        else:
            probability_true, confidence = 0.4, 0.5
        return JevDecision(
            probability_true=probability_true,
            probability_false=1.0 - probability_true,
            confidence=confidence,
            cost=len(state) / 1_000_000 * 0.042,
            tokens_in=len(state) // 4,
            tokens_out=8,
            model_returned=model,
        )

    async def aclose(self) -> None:
        """No-op: nothing to close."""
