"""Provider for OpenAI and for OpenAI-compatible services such as SwissGPT (plan chapters 9.2, 29).

One class serves both: OpenAI itself, and every service that speaks the same chat-completions
protocol at another address (SwissGPT/AlpineAI, Azure OpenAI, vLLM, LM Studio, Ollama). It uses the
official ``openai`` package (extra ``llm-openai``) and **always switches the package's own retries
off**: the engine owns retrying, so that waits, limits and logs stay in one place.

Every failure of the package is translated into the program's own error classes
(:mod:`crapai.llm.base`), so nothing above this module knows about HTTP or the SDK:

==============================================  ==============================================
What happened                                   Error
==============================================  ==============================================
401, 403                                        ``AuthError`` (E301): stop the run
429 with ``insufficient_quota`` / "billing"     ``QuotaExceeded`` (E307): pause the run
429 otherwise                                   ``RateLimited`` (E302) with ``Retry-After``
timeout, no connection, 5xx                     ``TransientError`` (E305)
400 "context length"                            ``ContextTooLong`` (E303)
``finish_reason = content_filter``, 400 filter  ``ContentRefused`` (E306)
any other 4xx                                   ``ProviderError`` (E305), not retried
==============================================  ==============================================

The key is read from the environment variable that ``llm.api_key_env`` names; it is held in memory
only, never written to a file or a log, and never part of an error message.

SwissGPT's published specification has no ``response_format`` and no ``seed``, so neither is sent
unless the project asks for a seed; the answer is validated in code whatever the service is.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from crapai.cost.tokenizers import tokenizer_for
from crapai.errors import (
    AuthError,
    ContentRefused,
    ContextTooLong,
    ProviderError,
    QuotaExceeded,
    RateLimited,
    TransientError,
)
from crapai.llm.base import Capabilities, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

_QUOTA_WORDS = ("insufficient_quota", "billing", "exceeded your current quota", "credit")
_CONTEXT_WORDS = ("context_length", "maximum context", "too many tokens", "context window")
_FILTER_WORDS = ("content_filter", "content management policy", "safety")


def _body_text(error: Any) -> str:
    """Lower-case text of an SDK error body and message, for matching (never logged whole)."""
    parts = [str(getattr(error, "message", "")), str(getattr(error, "code", ""))]
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        parts.append(str(body))
    return " ".join(parts).lower()


def translate(error: Exception) -> ProviderError:
    """Turn an exception of the ``openai`` package into one of our provider errors.

    The original exception is chained by the caller; only the type, the status and a short fixed
    message are kept, never the request or the key.
    """
    import openai

    status = getattr(error, "status_code", None)
    text = _body_text(error)
    if isinstance(error, openai.APITimeoutError):
        return TransientError("The request timed out", code="E305")
    if isinstance(error, openai.APIConnectionError):
        return TransientError("No connection to the service", code="E305")
    if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
        return AuthError(f"The key was refused (HTTP {status})", code="E301")
    if isinstance(error, openai.RateLimitError):
        if any(word in text for word in _QUOTA_WORDS):
            return QuotaExceeded("The credit or quota is used up", code="E307")
        retry_after = None
        headers = getattr(getattr(error, "response", None), "headers", None)
        if headers is not None:
            try:
                retry_after = float(headers.get("retry-after", ""))
            except (TypeError, ValueError):
                retry_after = None
        details = {"retry_after_s": retry_after} if retry_after is not None else {}
        return RateLimited("Too many requests (HTTP 429)", code="E302", details=details)
    if isinstance(error, openai.BadRequestError):
        if any(word in text for word in _CONTEXT_WORDS):
            return ContextTooLong("The input is longer than the context window", code="E303")
        if any(word in text for word in _FILTER_WORDS):
            return ContentRefused("The content was refused by the safety filter", code="E306")
        return ProviderError(f"The service rejected the request (HTTP {status})", code="E305")
    if isinstance(error, openai.InternalServerError) or (isinstance(status, int) and status >= 500):
        return TransientError(f"Server error (HTTP {status})", code="E305")
    if isinstance(error, openai.APIStatusError):
        return ProviderError(f"The service answered HTTP {status}", code="E305")
    return ProviderError(
        f"Unexpected error of the service client ({type(error).__name__})", code="E305"
    )


class OpenAICompatibleProvider:
    """OpenAI or a service with the same chat-completions protocol.

    Args:
        api_key: The key (from the environment; never stored).
        base_url: Address of the service, or None for OpenAI itself.
        name: ``openai`` or ``openai_compatible``; decides the name of the token-limit parameter.
        context_tokens: The model's context window if known (None = unknown).
        client: A ready ``AsyncOpenAI`` client (for tests); otherwise one is created.
        http_client: An HTTP client for the SDK to use (for tests, with a fake transport).

    Raises:
        ProviderError: E305 if the ``openai`` package is not installed.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        name: str = "openai",
        context_tokens: int | None = None,
        client: Any = None,
        http_client: Any = None,
    ) -> None:
        self.name = name
        self._context_tokens = context_tokens
        if client is not None:
            self._client = client
            return
        try:
            import openai
        except ImportError as exc:
            raise ProviderError(
                "The package openai is not installed",
                code="E305",
                hint='Install it with: pip install "crapai[llm-openai]"',
            ) from exc
        # max_retries=0: the engine retries, with its own waits, limits and log lines.
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, http_client=http_client
        )

    def count_tokens(self, text: str, model: str) -> int:
        """Tokens of ``text``: exact for OpenAI models with ``tiktoken``, else an estimate."""
        return tokenizer_for("openai" if self.name == "openai" else self.name, model).count(text)

    def capabilities(self, model: str) -> Capabilities:
        """The context window if the project named one; everything else is unknown."""
        return Capabilities(context_tokens=self._context_tokens)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one chat-completions request.

        Raises:
            ProviderError: one of the classes in the module docstring.
        """
        arguments: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "timeout": request.timeout_s,
        }
        # OpenAI's newer models want max_completion_tokens; compatible services know max_tokens.
        limit_name = "max_completion_tokens" if self.name == "openai" else "max_tokens"
        arguments[limit_name] = request.max_output_tokens
        if request.top_p is not None:
            arguments["top_p"] = request.top_p
        if request.seed is not None:
            arguments["seed"] = request.seed
        started = time.monotonic()
        try:
            completion = await self._client.chat.completions.create(**arguments)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated; anything unknown becomes E305
            raise translate(exc) from exc
        latency = time.monotonic() - started
        if not completion.choices:
            raise TransientError("The service returned no answer", code="E305")
        choice = completion.choices[0]
        finish = str(choice.finish_reason or "stop")
        if finish == "content_filter":
            raise ContentRefused("The content was refused by the safety filter", code="E306")
        usage = getattr(completion, "usage", None)
        return LLMResponse(
            text=choice.message.content or "",
            model_returned=str(getattr(completion, "model", "") or ""),
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=finish,
            request_id=str(getattr(completion, "id", "") or "") or None,
            latency_s=latency,
        )
