"""The Jev client against a faked HTTP transport; no network, no real key (ADR 0029)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from crapai.errors import (
    AuthError,
    ContextTooLong,
    ProviderError,
    QuotaExceeded,
    RateLimited,
    TransientError,
)
from crapai.llm.jev_client import JevClient, MockJevClient, translate

URL = "https://api.typesafe.ai/v1/systemone"


class Server:
    """A fake HTTP server: one canned answer (or exception) and a record of the requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Any = httpx.Response(200, json=_answer())

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer  # type: ignore[no-any-return]

    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)  # type: ignore[no-any-return]


def _answer(
    probability_true: float = 0.9, confidence: float = 0.95, **usage: Any
) -> dict[str, Any]:
    payload = {
        "model": "jev-latest",
        "answers": {
            "exclude": {
                "type": "noul",
                "probabilities": {"true": probability_true, "false": 1 - probability_true},
                "confidence": confidence,
            }
        },
        "usage": {"input_tokens": 120, "output_tokens": 8, "cost": 0.000005},
    }
    payload["usage"].update(usage)
    return payload


@pytest.fixture
def server() -> Server:
    return Server()


def client(server: Server, **kw: Any) -> JevClient:
    transport = httpx.MockTransport(server.handler)
    return JevClient(
        "sk-test", base_url=URL, client=httpx.AsyncClient(transport=transport), **kw
    )


async def test_a_successful_call_returns_the_typed_answer_and_usage(server: Server) -> None:
    decision = await client(server).classify("title and abstract", "criteria text", model="jev-x")
    assert decision.probability_true == pytest.approx(0.9)
    assert decision.probability_false == pytest.approx(0.1)
    assert decision.confidence == pytest.approx(0.95)
    assert decision.tokens_in == 120 and decision.tokens_out == 8
    assert decision.cost == pytest.approx(0.000005)
    assert decision.model_returned == "jev-latest"
    body = server.body()
    assert body["model"] == "jev-x" and body["state"] == "title and abstract"
    assert body["questions"]["exclude"]["type"] == "noul"
    assert body["questions"]["exclude"]["instructions"] == "criteria text"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, "", AuthError),
        (403, "", AuthError),
        (429, "too many requests", RateLimited),
        (429, "quota exceeded", QuotaExceeded),
        (400, "state too large for the context window", ContextTooLong),
        (500, "internal error", TransientError),
        (503, "unavailable", TransientError),
        (418, "teapot", ProviderError),
    ],
)
async def test_http_errors_are_translated(
    server: Server, status: int, body: str, expected: type[ProviderError]
) -> None:
    server.answer = httpx.Response(status, text=body)
    with pytest.raises(expected):
        await client(server).classify("state", "instructions", model="jev-x")


def test_translate_falls_back_for_an_unknown_status() -> None:
    assert type(translate(None, "")) is ProviderError


async def test_a_connection_error_is_transient(server: Server) -> None:
    server.answer = httpx.ConnectError("refused")
    with pytest.raises(TransientError):
        await client(server).classify("state", "instructions", model="jev-x")


async def test_missing_httpx_raises_a_clear_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *a: Any, **kw: Any) -> Any:
        if name == "httpx":
            raise ImportError("no module named httpx")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ProviderError) as info:
        JevClient("sk-test")
    assert info.value.code == "E305" and "prefilter-jev" in (info.value.hint or "")


# --- MockJevClient -------------------------------------------------------------------------------


async def test_mock_true_high_marks_a_record() -> None:
    decision = await MockJevClient().classify("JEV_TRUE_HIGH text", "x", model="jev-latest")
    assert decision.probability_true == pytest.approx(0.95)
    assert decision.confidence == pytest.approx(0.95)


async def test_mock_true_low_is_below_any_sane_confidence_floor() -> None:
    decision = await MockJevClient().classify("JEV_TRUE_LOW text", "x", model="jev-latest")
    assert decision.confidence < 0.85


async def test_mock_default_never_marks_a_record() -> None:
    decision = await MockJevClient().classify("ordinary text", "x", model="jev-latest")
    assert decision.probability_true < 0.5


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("JEV_ERROR_AUTH", AuthError),
        ("JEV_ERROR_RATE", RateLimited),
        ("JEV_ERROR_QUOTA", QuotaExceeded),
        ("JEV_ERROR_CONTEXT", ContextTooLong),
        ("JEV_ERROR_TRANSIENT", TransientError),
    ],
)
async def test_mock_error_markers(marker: str, expected: type[ProviderError]) -> None:
    with pytest.raises(expected):
        await MockJevClient().classify(f"{marker} text", "x", model="jev-latest")
