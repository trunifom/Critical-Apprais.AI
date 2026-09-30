"""The OpenAI-compatible provider against a faked HTTP transport; no network, no real key."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx2 as httpx  # the openai package speaks httpx2, not httpx
import pytest

from crapai.errors import (
    AuthError,
    ContentRefused,
    ContextTooLong,
    ProviderError,
    QuotaExceeded,
    RateLimited,
    TransientError,
)
from crapai.llm.base import LLMRequest
from crapai.llm.openai_provider import OpenAICompatibleProvider

BASE = "https://llm.example/v1"
URL = f"{BASE}/chat/completions"
KEY = "sk-test-SECRET-1234567890"


class Server:
    """A fake HTTP server: one canned answer (or exception) and a record of the requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Any = httpx.Response(200, json={})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer  # type: ignore[no-any-return]

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)  # type: ignore[no-any-return]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Server:
    fake = Server()
    transport = httpx.MockTransport(fake.handler)
    original = OpenAICompatibleProvider.__init__

    def init(self: OpenAICompatibleProvider, *args: Any, **kwargs: Any) -> None:
        original(self, *args, http_client=httpx.AsyncClient(transport=transport), **kwargs)

    monkeypatch.setattr(OpenAICompatibleProvider, "__init__", init)
    return fake


def provider(name: str = "openai_compatible", **kw: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(KEY, base_url=BASE, name=name, **kw)


def req(**changes: Any) -> LLMRequest:
    return LLMRequest("sys", "user text", "model-x", timeout_s=5.0, **changes)


def completion(content: str = "{}", finish: str = "stop", **extra: Any) -> dict[str, Any]:
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "model-x-0613",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    body.update(extra)
    return body


async def test_a_successful_call_returns_text_usage_and_ids(server: Server) -> None:
    server.answer = httpx.Response(200, json=completion('{"a": 1}'))
    response = await provider().complete(req())
    assert response.text == '{"a": 1}' and (response.tokens_in, response.tokens_out) == (11, 7)
    assert response.model_returned == "model-x-0613" and response.finish_reason == "stop"
    assert response.request_id == "chatcmpl-1" and server.call_count == 1


async def test_the_request_carries_the_key_the_messages_and_only_wanted_parameters(
    server: Server,
) -> None:
    server.answer = httpx.Response(200, json=completion())
    await provider().complete(req(max_output_tokens=321))
    sent = server.requests[0]
    body = server.body()
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["max_tokens"] == 321 and "max_completion_tokens" not in body
    assert "seed" not in body and "response_format" not in body and "top_p" not in body


async def test_openai_itself_gets_max_completion_tokens_and_optional_seed_and_top_p(
    server: Server,
) -> None:
    server.answer = httpx.Response(200, json=completion())
    await provider("openai").complete(req(seed=5, top_p=0.9))
    body = server.body()
    assert body["max_completion_tokens"] == 800 and "max_tokens" not in body
    assert body["seed"] == 5 and body["top_p"] == 0.9


@pytest.mark.parametrize(
    "status,payload,headers,error,code",
    [
        (401, {"error": {"message": "bad key"}}, {}, AuthError, "E301"),
        (403, {"error": {"message": "forbidden"}}, {}, AuthError, "E301"),
        (429, {"error": {"message": "slow down"}}, {"retry-after": "7"}, RateLimited, "E302"),
        (429, {"error": {"message": "x", "code": "insufficient_quota"}}, {}, QuotaExceeded, "E307"),
        (
            429,
            {"error": {"message": "You exceeded your current quota, check billing"}},
            {},
            QuotaExceeded,
            "E307",
        ),
        (
            400,
            {
                "error": {
                    "message": "maximum context length is 4096",
                    "code": "context_length_exceeded",
                }
            },
            {},
            ContextTooLong,
            "E303",
        ),
        (
            400,
            {"error": {"message": "blocked by content management policy"}},
            {},
            ContentRefused,
            "E306",
        ),
        (400, {"error": {"message": "unsupported parameter"}}, {}, ProviderError, "E305"),
        (404, {"error": {"message": "no such model"}}, {}, ProviderError, "E305"),
        (500, {"error": {"message": "oops"}}, {}, TransientError, "E305"),
        (503, {"error": {"message": "busy"}}, {}, TransientError, "E305"),
    ],
)
async def test_http_errors_become_our_error_classes(
    server: Server,
    status: int,
    payload: dict[str, Any],
    headers: dict[str, str],
    error: type[Exception],
    code: str,
) -> None:
    server.answer = httpx.Response(status, json=payload, headers=headers)
    with pytest.raises(error) as info:
        await provider().complete(req())
    assert type(info.value) is error and info.value.code == code  # type: ignore[attr-defined]


async def test_retry_after_is_passed_on(server: Server) -> None:
    server.answer = httpx.Response(
        429, json={"error": {"message": "x"}}, headers={"retry-after": "7"}
    )
    with pytest.raises(RateLimited) as info:
        await provider().complete(req())
    assert info.value.details == {"retry_after_s": 7.0}


async def test_no_connection_and_timeouts_are_transient(server: Server) -> None:
    server.answer = httpx.ConnectError("down")
    with pytest.raises(TransientError):
        await provider().complete(req())
    server.answer = httpx.ReadTimeout("slow")
    with pytest.raises(TransientError):
        await provider().complete(req())


async def test_the_sdk_does_not_retry_on_its_own(server: Server) -> None:
    server.answer = httpx.Response(503, json={"error": {"message": "busy"}})
    with pytest.raises(TransientError):
        await provider().complete(req())
    assert server.call_count == 1  # the engine owns retrying


async def test_a_content_filter_finish_is_a_refusal(server: Server) -> None:
    server.answer = httpx.Response(200, json=completion("", finish="content_filter"))
    with pytest.raises(ContentRefused):
        await provider().complete(req())


async def test_an_answer_without_choices_is_transient(server: Server) -> None:
    server.answer = httpx.Response(200, json=completion(choices=[]))
    with pytest.raises(TransientError):
        await provider().complete(req())


async def test_a_length_finish_is_reported_not_raised(server: Server) -> None:
    server.answer = httpx.Response(200, json=completion('{"x"', finish="length"))
    assert (await provider().complete(req())).finish_reason == "length"


async def test_missing_usage_and_null_content_do_not_crash(server: Server) -> None:
    body = completion()
    del body["usage"]
    body["choices"][0]["message"]["content"] = None
    server.answer = httpx.Response(200, json=body)
    response = await provider().complete(req())
    assert response.text == "" and response.tokens_in == response.tokens_out == 0


async def test_the_key_never_appears_in_errors_or_logs(
    server: Server, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    server.answer = httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})
    with pytest.raises(AuthError) as info:
        await provider().complete(req())
    assert KEY not in str(info.value) and KEY not in repr(info.value) and KEY not in caplog.text
    assert KEY not in repr(provider()) and KEY not in repr(vars(provider()).get("name"))


def test_token_counting_and_capabilities() -> None:
    p = provider(context_tokens=32_000)
    assert p.count_tokens("hello world, this is a test", "model-x") > 0
    assert p.capabilities("model-x").context_tokens == 32_000
    assert provider().capabilities("m").context_tokens is None


def test_translate_handles_foreign_exceptions() -> None:
    from crapai.llm.openai_provider import translate

    assert isinstance(translate(ValueError("x")), ProviderError)
