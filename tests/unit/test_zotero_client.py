"""The Zotero client against a faked HTTP transport; no network, no real key (ADR 0030)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from crapai.errors import AuthError, ImportFailed, ProviderError, RateLimited, TransientError
from crapai.zotero.client import MockZoteroClient, ZoteroClient, translate

RIS_PAGE_1 = "TY  - JOUR\nTI  - Study One\nER  - \n"
RIS_PAGE_2 = "TY  - JOUR\nTI  - Study Two\nER  - \n"


class Server:
    """A fake Zotero server: canned responses per path, records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = [httpx.Response(200, text=RIS_PAGE_1)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        answer = self.responses[index]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def server() -> Server:
    return Server()


def client(server: Server, **kw: Any) -> ZoteroClient:
    transport = httpx.MockTransport(server.handler)
    return ZoteroClient(
        "key",
        library_type="user",
        library_id="123",
        client=httpx.Client(base_url="https://api.zotero.org", transport=transport),
        **kw,
    )


def test_a_successful_call_returns_the_export_text(server: Server) -> None:
    text = client(server).fetch_text(format="ris")
    assert "Study One" in text
    request = server.requests[0]
    assert request.url.path == "/users/123/items"
    assert request.url.params["format"] == "ris"
    assert request.headers["Zotero-API-Key"] == "key"
    assert request.headers["Zotero-API-Version"] == "3"


def test_a_collection_key_changes_the_path(server: Server) -> None:
    client(server, collection_key="ABCD1234").fetch_text(format="bibtex")
    assert server.requests[0].url.path == "/users/123/collections/ABCD1234/items"


def test_pagination_follows_the_link_header_until_absent(server: Server) -> None:
    server.responses = [
        httpx.Response(
            200,
            text=RIS_PAGE_1,
            headers={"Link": '<https://api.zotero.org/users/123/items?start=100>; rel="next"'},
        ),
        httpx.Response(200, text=RIS_PAGE_2),
    ]
    text = client(server).fetch_text(format="ris")
    assert "Study One" in text and "Study Two" in text
    assert len(server.requests) == 2
    assert str(server.requests[1].url).endswith("start=100")


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, "", AuthError),
        (403, "", AuthError),
        (404, "", ImportFailed),
        (429, "", RateLimited),
        (500, "internal error", TransientError),
        (503, "unavailable", TransientError),
        (418, "teapot", ProviderError),
    ],
)
def test_http_errors_are_translated(
    server: Server, status: int, body: str, expected: type[Exception]
) -> None:
    server.responses = [httpx.Response(status, text=body)]
    with pytest.raises(expected):
        client(server).fetch_text(format="ris")


def test_an_empty_library_is_import_failed(server: Server) -> None:
    server.responses = [httpx.Response(200, text="   ")]
    with pytest.raises(ImportFailed) as info:
        client(server).fetch_text(format="ris")
    assert info.value.code == "E102"


def test_translate_falls_back_for_an_unknown_status() -> None:
    assert type(translate(None, "")) is ProviderError


def test_a_connection_error_is_transient(server: Server) -> None:
    server.responses = [httpx.ConnectError("refused")]  # type: ignore[list-item]
    with pytest.raises(TransientError):
        client(server).fetch_text(format="ris")


def test_missing_httpx_raises_a_clear_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *a: Any, **kw: Any) -> Any:
        if name == "httpx":
            raise ImportError("no module named httpx")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ProviderError) as info:
        ZoteroClient("key")
    assert info.value.code == "E305" and "zotero" in (info.value.hint or "")


# --- MockZoteroClient ----------------------------------------------------------------------------


def test_mock_returns_the_scripted_items() -> None:
    mock = MockZoteroClient(RIS_PAGE_1)
    assert mock.fetch_text(format="ris") == RIS_PAGE_1
    assert mock.calls == 1


def test_mock_raises_the_scripted_error() -> None:
    mock = MockZoteroClient(error=AuthError("no", code="E301"))
    with pytest.raises(AuthError):
        mock.fetch_text(format="ris")


def test_mock_empty_items_is_import_failed() -> None:
    with pytest.raises(ImportFailed):
        MockZoteroClient("").fetch_text(format="ris")
