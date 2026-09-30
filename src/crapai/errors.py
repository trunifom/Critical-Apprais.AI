"""Exception hierarchy of the core (plan chapter 28.7) with user-facing error codes (chapter 26.4).

The core raises only :class:`SaraError` subclasses. Unexpected exceptions are caught at a boundary
(CLI command, worker loop, UI handler), logged with the traceback and shown as ``E999``.
User-visible texts live in the i18n files under ``errors.<code>.*``; the exception only carries the
code, a short English message, a hint and technical details.
"""

from __future__ import annotations

from typing import Any

UNEXPECTED_ERROR_CODE = "E999"


class SaraError(Exception):
    """Base class of all errors raised by the core.

    Args:
        message: Short English description of what happened (for logs and as fallback text).
        code: Error code such as ``"E203"``. Subclasses provide a default via ``default_code``.
        hint: Optional advice on what the user can do.
        details: Optional technical context (paths, field names). Must never contain secrets,
            abstracts or full payloads.
    """

    default_code: str = UNEXPECTED_ERROR_CODE

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.user_message = message
        self.hint = hint
        self.details: dict[str, Any] = dict(details or {})

    @property
    def text_key(self) -> str:
        """Prefix of the i18n keys for this error, e.g. ``errors.E203``."""
        return f"errors.{self.code}"

    def __str__(self) -> str:
        return f"[{self.code}] {self.user_message}"


class ConfigError(SaraError):
    """Invalid or incomplete configuration (E2xx)."""

    default_code = "E203"


class ImportFailed(SaraError):
    """A bibliographic file could not be imported (E1xx)."""

    default_code = "E101"


class ProviderError(SaraError):
    """Base class of LLM provider failures (E3xx)."""

    default_code = "E305"


class AuthError(ProviderError):
    """HTTP 401/403 or missing key: stops the whole run."""

    default_code = "E301"


class RateLimited(ProviderError):
    """HTTP 429: wait and retry."""

    default_code = "E302"


class TransientError(ProviderError):
    """HTTP 5xx, timeout or connection problem: retry."""

    default_code = "E305"


class ContextTooLong(ProviderError):
    """Input exceeds the context window: never retried."""

    default_code = "E303"


class ContentRefused(ProviderError):
    """The provider's safety filter refused the content."""

    default_code = "E306"


class QuotaExceeded(ProviderError):
    """Credit or quota exhausted: pause the run."""

    default_code = "E307"


class ParseError(SaraError):
    """The model answer does not match the answer schema (retried a limited number of times)."""

    default_code = "E304"


class StorageError(SaraError):
    """File-system problem: lock, disk space, permissions, outdated project folder (E4xx)."""

    default_code = "E401"


class EvaluationError(SaraError):
    """Statistics or evaluation cannot be computed (E5xx)."""

    default_code = "E501"
