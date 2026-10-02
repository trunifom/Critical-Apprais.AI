"""Client for the Zotero Web API (ADR 0030): fetch a library or collection as RIS/BibTeX text.

Read-only: this module only ever issues GET requests. There is no write-back of decisions to
Zotero in this version (ADR 0030 defers that -- it would need version-based optimistic concurrency
and write permissions, a separate decision).

Endpoint: ``GET https://api.zotero.org/<users|groups>/<library_id>/items`` (or
``.../collections/<collection_key>/items`` for one collection), ``Zotero-API-Version: 3`` and
``Zotero-API-Key: <key>`` headers, ``format=ris`` or ``format=bibtex`` to get the export text
directly instead of JSON. Results are paginated (``limit``/``start``); the next page is the
``rel="next"`` entry of the response's ``Link`` header, followed until it is absent.

Errors are translated into the program's own classes (the same ones
:mod:`crapai.llm.openai_provider`/:mod:`crapai.llm.jev_client` use, reused here as-is -- they are
generic HTTP-outcome classes, not specific to a language-model provider):

==============================================  ==============================================
What happened                                   Error
==============================================  ==============================================
401, 403                                        ``AuthError`` (E301)
429                                              ``RateLimited`` (E302)
404 (unknown library/collection)                ``ImportFailed`` (E101)
empty result (library/collection has no items)  ``ImportFailed`` (E102)
timeout, no connection, 5xx                     ``TransientError`` (E305)
any other 4xx                                   ``ProviderError`` (E305)
==============================================  ==============================================

The key is read from the environment variable ``zotero.api_key_env`` names; it is held in memory
only, never written to a file or a log, and never part of an error message.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from crapai.errors import (
    AuthError,
    ImportFailed,
    ProviderError,
    RateLimited,
    SaraError,
    TransientError,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.zotero.org"
PAGE_LIMIT = 100


def _library_path(library_type: Literal["user", "group"], library_id: str) -> str:
    segment = "users" if library_type == "user" else "groups"
    return f"/{segment}/{library_id}"


def translate(status: int | None, body_text: str) -> SaraError:
    """Turn an HTTP status and lower-cased response body into one of our error classes."""
    text = body_text.lower()
    if status in (401, 403):
        return AuthError(f"The key was refused (HTTP {status})", code="E301")
    if status == 404:
        return ImportFailed("The library or collection was not found", code="E101")
    if status == 429:
        return RateLimited("Too many requests (HTTP 429)", code="E302")
    if isinstance(status, int) and status >= 500:
        return TransientError(f"Server error (HTTP {status})", code="E305")
    if isinstance(status, int) and status >= 400:
        detail = f"Zotero rejected the request (HTTP {status}): {text[:200]}"
        return ProviderError(detail, code="E305")
    return ProviderError("Zotero answered with an unexpected status", code="E305")


class ZoteroClient:
    """Talks to the Zotero Web API; read-only (``fetch_text`` is the only operation).

    Args:
        api_key: The key (from the environment; never stored on disk). Empty for a public
            library that needs no key.
        library_type: ``"user"`` or ``"group"``.
        library_id: The numeric user or group ID.
        collection_key: A collection's key, or ``""`` for the whole library.
        timeout_s: HTTP timeout of one request.
        client: A ready ``httpx.Client`` (for tests, with a mock transport); otherwise one is
            created.

    Raises:
        ProviderError: E305 if the ``httpx`` package is not installed.
    """

    def __init__(
        self,
        api_key: str,
        *,
        library_type: Literal["user", "group"] = "user",
        library_id: str = "",
        collection_key: str = "",
        timeout_s: float = 30.0,
        client: Any = None,
    ) -> None:
        self._library_type = library_type
        self._library_id = library_id
        self._collection_key = collection_key
        headers = {"Zotero-API-Version": "3"}
        if api_key:
            headers["Zotero-API-Key"] = api_key
        if client is not None:
            client.headers.update(headers)
            self._client = client
            return
        try:
            import httpx
        except ImportError as exc:
            raise ProviderError(
                "The package httpx is not installed",
                code="E305",
                hint='Install it with: pip install "crapai[zotero]"',
            ) from exc
        self._client = httpx.Client(base_url=API_BASE, headers=headers, timeout=timeout_s)

    def fetch_text(self, *, format: Literal["ris", "bibtex"]) -> str:
        """All items of the configured library/collection as one RIS or BibTeX text.

        Raises:
            ProviderError: one of the classes in the module docstring.
        """
        import httpx

        base = _library_path(self._library_type, self._library_id)
        path: str | None = (
            f"{base}/collections/{self._collection_key}/items"
            if self._collection_key
            else f"{base}/items"
        )
        params: dict[str, Any] | None = {"format": format, "limit": PAGE_LIMIT}
        parts: list[str] = []
        while path is not None:
            try:
                response = self._client.get(path, params=params)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                name = type(exc).__name__
                raise TransientError(f"No connection to Zotero ({name})", code="E305") from exc
            except httpx.HTTPError as exc:
                name = type(exc).__name__
                raise ProviderError(f"Zotero request failed ({name})", code="E305") from exc
            if response.status_code >= 400:
                raise translate(response.status_code, response.text)
            parts.append(response.text)
            next_link = response.links.get("next")
            path = next_link["url"] if next_link else None
            params = None  # the next-page URL already carries its own query string
        text = "\n".join(part for part in parts if part.strip())
        if not text.strip():
            raise ImportFailed("The library or collection has no items", code="E102")
        return text

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


class MockZoteroClient:
    """A deterministic stand-in for :class:`ZoteroClient`; no network, no key.

    ``items`` is the RIS/BibTeX text returned by :meth:`fetch_text`; set ``error`` to an exception
    instance to have :meth:`fetch_text` raise it instead, for testing error handling.
    """

    def __init__(self, items: str = "", *, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.calls = 0

    def fetch_text(self, *, format: Literal["ris", "bibtex"]) -> str:
        """The scripted ``items`` text, or raise the scripted ``error``."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.items.strip():
            raise ImportFailed("The library or collection has no items", code="E102")
        return self.items

    def close(self) -> None:
        """No-op: nothing to close."""
