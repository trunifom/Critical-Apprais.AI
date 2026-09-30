"""The mock provider itself: deterministic, one behaviour per scenario."""

from __future__ import annotations

import json

import pytest

from crapai.errors import AuthError, ContentRefused, QuotaExceeded, RateLimited, TransientError
from crapai.llm.base import LLMRequest
from crapai.llm.mock_provider import (
    SCENARIOS,
    MockProvider,
    answer_json,
    bucket,
    default_decision,
    record_text,
)
from crapai.screening.answer import parse_answer


def request(n: int = 0, *, text: str = "", timeout: float = 5.0, limit: int = 800) -> LLMRequest:
    user = f"criteria\n<record>\nTitle: T{n}\nAbstract: adults number {n} were enrolled {text}\n</record>"
    return LLMRequest("system", user, "mock-model", max_output_tokens=limit, timeout_s=timeout)


def test_fifteen_scenarios_exist_and_unknown_ones_are_refused() -> None:
    assert tuple(f"S{n}" for n in range(1, 16)) == SCENARIOS
    with pytest.raises(ValueError):
        MockProvider("S99")


def test_record_text_and_bucket_and_decision() -> None:
    assert (
        record_text("x <record> inner </record> y") == "inner" and record_text("plain") == "plain"
    )
    assert bucket("a", 20) == bucket("a", 20) and 0 <= bucket("b", 7) < 7
    assert [default_decision(t) for t in ("x", "EXCLUDE_ME", "UNSURE_ME")] == [
        "INCLUDE",
        "EXCLUDE",
        "UNCERTAIN",
    ]


@pytest.mark.parametrize("decision", ["INCLUDE", "EXCLUDE", "UNCERTAIN"])
def test_default_answers_are_valid_and_consistent(decision: str) -> None:
    answer = parse_answer(answer_json("Abstract: some text here", decision=decision))
    assert answer.decision == decision and answer.consistent


async def test_s1_answers_everything() -> None:
    provider = MockProvider("S1")
    responses = [await provider.complete(request(n)) for n in range(30)]
    assert all(parse_answer(r.text).decision == "INCLUDE" for r in responses)
    assert (
        provider.calls == 30 and responses[0].tokens_in > 0 and responses[0].finish_reason == "stop"
    )


async def test_it_is_deterministic_across_instances() -> None:
    first = [(await MockProvider("S5").complete(request(n))).text for n in range(20)]
    second = [(await MockProvider("S5").complete(request(n))).text for n in range(20)]
    assert first == second


async def test_s2_answers_429_with_retry_after_for_the_first_calls() -> None:
    provider = MockProvider("S2", burst=2, retry_after_s=3.0)
    for _ in range(2):
        with pytest.raises(RateLimited) as info:
            await provider.complete(request())
        assert info.value.details["retry_after_s"] == 3.0
    assert (await provider.complete(request())).text


async def test_s3_fails_every_seventh_call() -> None:
    provider = MockProvider("S3")
    failures = []
    for call in range(1, 15):
        try:
            await provider.complete(request(call))
        except TransientError:
            failures.append(call)
    assert failures == [7, 14]


async def test_s7_and_s14_fail_after_n_calls() -> None:
    for scenario, error in (("S7", AuthError), ("S14", QuotaExceeded)):
        provider = MockProvider(scenario, after=3)
        for n in range(3):
            await provider.complete(request(n))
        with pytest.raises(error):
            await provider.complete(request(4))


async def test_s8_is_slower_than_a_short_time_limit() -> None:
    provider = MockProvider("S8", delay_s=0.2)
    with pytest.raises(TransientError):
        await provider.complete(request(timeout=0.05))
    assert (await provider.complete(request(timeout=5.0))).latency_s == 0.2


async def test_s11_refuses_some_records() -> None:
    provider = MockProvider("S11")
    refused = 0
    for n in range(40):
        try:
            await provider.complete(request(n))
        except ContentRefused:
            refused += 1
    assert 0 < refused < 40


async def test_s6_cuts_the_first_answer_and_a_higher_limit_helps_some_records() -> None:
    provider = MockProvider("S6")
    cut_first = [(await provider.complete(request(n))).finish_reason for n in range(20)]
    assert set(cut_first) == {"length"}
    second = [(await provider.complete(request(n, limit=1600))).finish_reason for n in range(20)]
    assert "stop" in second and "length" in second


async def test_s15_changes_the_model_name_after_five_calls() -> None:
    provider = MockProvider("S15")
    names = [(await provider.complete(request(n))).model_returned for n in range(8)]
    assert names[:5] == ["mock-model"] * 5 and names[5].endswith("-2026-update")


def test_reset_and_summary_and_capabilities() -> None:
    provider = MockProvider("S1")
    assert provider.count_tokens("", "m") == 0 and provider.count_tokens("abcde", "m") == 2
    assert provider.capabilities("m").context_tokens == 128_000
    provider.calls = 4
    provider.reset()
    assert provider.summary() == {"scenario": "S1", "calls": 0}
    json.dumps(provider.summary())
