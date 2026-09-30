"""A provider that needs no network and no key, with the 15 failure scenarios of plan chapter 33.2.

The whole screening engine is tested against this class, so that ordinary runs, rate limits,
broken answers, stopped runs and exhausted credit can be rehearsed on any computer for free.
Everything is deterministic: what the mock does for a record depends on the record's text (a
CRC32 of the user message) and on the number of calls so far, never on the clock or on chance.

Decisions of the default answers: a record whose text contains ``EXCLUDE_ME`` is excluded, one
containing ``UNSURE_ME`` is uncertain, every other record is included.

=====  ==========================================================  ==============================
ID     What the mock does                                          What the engine must do
=====  ==========================================================  ==============================
S1     everything works                                            all records ``ok``
S2     the first ``burst`` calls answer 429 with ``retry_after``   throttle, lose nothing
S3     every 7th call is a 5xx error                               retry; all ``ok``
S4     a quarter of the records always time out                    retry, then ``api_error``
S5     a quarter of the records always get broken JSON             ``parse_error``, no silent label
S6     the first answer is cut off (``length``); half of the       retry with a higher limit, else
       records are always cut off                                  ``truncated``
S7     the key is refused after ``after`` calls (401)              stop at once, state ``failed``
S8     slow answers (``delay_s``); longer than the timeout fails   time limit; progress stays sane
S9     like S1 but slow: the run can be stopped with calls in      no double line after a resume
       flight
S10    a quarter of the records get an empty answer                ``parse_error``
S11    a fifth of the records are refused (safety filter)          ``api_error`` with code E306
S12    a third of the answers contradict their own verdicts        ``consistent = false``
S13    a third of the answers cite text that is not in the record  ``quote_unverified``
S14    the credit is used up after ``after`` calls                 pause, code E307, resume possible
S15    the model name in the answer changes after 5 calls          warning in the manifest
=====  ==========================================================  ==============================
"""

from __future__ import annotations

import asyncio
import json
import re
import zlib
from typing import Any

from crapai.errors import (
    AuthError,
    ContentRefused,
    QuotaExceeded,
    RateLimited,
    TransientError,
)
from crapai.llm.base import Capabilities, LLMRequest, LLMResponse

SCENARIOS = tuple(f"S{number}" for number in range(1, 16))
_RECORD = re.compile(r"<record>(.*?)</record>", re.DOTALL)


def record_text(user_message: str) -> str:
    """The record part of a user message (between ``<record>`` tags), else the whole message."""
    match = _RECORD.search(user_message)
    return match.group(1).strip() if match else user_message


def bucket(text: str, modulo: int) -> int:
    """A stable number from 0 to ``modulo - 1`` for a text (same text, same number, every run)."""
    return zlib.crc32(text.encode("utf-8")) % modulo


def default_decision(text: str) -> str:
    """The decision the mock gives for a record text."""
    if "EXCLUDE_ME" in text:
        return "EXCLUDE"
    if "UNSURE_ME" in text:
        return "UNCERTAIN"
    return "INCLUDE"


def answer_json(text: str, *, decision: str | None = None, quote: str | None = None) -> str:
    """A valid answer for ``text`` as JSON (the format of plan chapter 10.3)."""
    chosen = decision or default_decision(text)
    snippet = " ".join(text.split("Abstract:")[-1].split()[:6]) if quote is None else quote
    inclusion = [
        {
            "criterion": "Population",
            "verdict": "met"
            if chosen == "INCLUDE"
            else "unclear"
            if chosen == "UNCERTAIN"
            else "not_met",
            "note": "as described",
            "quote": snippet,
        }
    ]
    exclusion = [
        {
            "criterion": "Design",
            "verdict": "triggered" if chosen == "EXCLUDE" else "not_triggered",
            "note": "checked",
        }
    ]
    body = {
        "inclusion": inclusion,
        "exclusion": exclusion,
        "ambiguities": [],
        "reasoning": f"Mock reasoning for a record of {len(text)} characters.",
        "decision": chosen,
    }
    return json.dumps(body)


class MockProvider:
    """A deterministic provider for tests and demonstrations.

    Args:
        scenario: One of ``S1`` to ``S15`` (see the module docstring).
        burst: S2: how many calls in a row answer 429.
        after: S7 and S14: how many calls work before the failure starts.
        delay_s: S8 and S9: seconds every answer takes.
        retry_after_s: S2: the ``retry_after`` the mock reports.
        model: The model name the mock reports.
    """

    name = "mock"

    def __init__(
        self,
        scenario: str = "S1",
        *,
        burst: int = 5,
        after: int = 10,
        delay_s: float = 0.02,
        retry_after_s: float = 0.01,
        model: str = "mock-model",
    ) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; use one of {', '.join(SCENARIOS)}")
        self.scenario = scenario
        self.burst, self.after = burst, after
        self.delay_s, self.retry_after_s = delay_s, retry_after_s
        self.model = model
        self.calls = 0
        self.requests: list[LLMRequest] = []
        self._seen_length: dict[str, int] = {}

    # -- protocol ------------------------------------------------------------------------------

    def count_tokens(self, text: str, model: str) -> int:
        """Four characters per token, rounded up (the mock has no tokenizer)."""
        return max(1, -(-len(text) // 4)) if text else 0

    def capabilities(self, model: str) -> Capabilities:
        """The mock supports everything and has a large context."""
        return Capabilities(context_tokens=128_000, structured_output=True, seed=True)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Answer (or fail) according to the scenario; see the module docstring."""
        self.calls += 1
        self.requests.append(request)
        call = self.calls
        text = record_text(request.user)
        key = bucket(request.user, 20)  # 0..19, stable per record
        scenario = self.scenario

        if scenario in ("S8", "S9"):
            if self.delay_s > request.timeout_s:
                await asyncio.sleep(request.timeout_s)
                raise TransientError("The request timed out", code="E305")
            await asyncio.sleep(self.delay_s)
        if scenario == "S2" and call <= self.burst:
            raise RateLimited(
                "Too many requests", code="E302", details={"retry_after_s": self.retry_after_s}
            )
        if scenario == "S3" and call % 7 == 0:
            raise TransientError("Server error (HTTP 503)", code="E305")
        if scenario == "S4" and key % 4 == 0:
            raise TransientError("The request timed out", code="E305")
        if scenario == "S7" and call > self.after:
            raise AuthError("The key was refused (HTTP 401)", code="E301")
        if scenario == "S11" and key % 5 == 0:
            raise ContentRefused("The content was refused by the safety filter", code="E306")
        if scenario == "S14" and call > self.after:
            raise QuotaExceeded("The credit is used up", code="E307")

        finish, body = "stop", answer_json(text)
        if scenario == "S5" and key % 4 == 0:
            body = '{"inclusion": [ {"criterion": "Population", "verdict": '  # cut in the middle
        if scenario == "S10" and key % 4 == 0:
            body = ""
        if scenario == "S6":
            previous = self._seen_length.get(text)
            self._seen_length[text] = request.max_output_tokens
            always_cut = key % 2 == 1
            if always_cut or previous is None or request.max_output_tokens <= previous:
                finish, body = "length", body[: len(body) // 2]
        if scenario == "S12" and key % 3 == 0:
            body = answer_json(text, decision="INCLUDE").replace('"not_triggered"', '"triggered"')
        if scenario == "S13" and key % 3 == 0:
            body = answer_json(text, quote="words that are nowhere in this record")
        model = self.model
        if scenario == "S15" and call > 5:
            model = f"{self.model}-2026-update"

        tokens_in = self.count_tokens(request.system + request.user, request.model)
        return LLMResponse(
            text=body,
            model_returned=model,
            tokens_in=tokens_in,
            tokens_out=self.count_tokens(body, request.model),
            finish_reason=finish,
            request_id=f"mock-{call}",
            latency_s=self.delay_s if scenario in ("S8", "S9") else 0.0,
            raw={"scenario": scenario, "call": call} if request.request_id else {},
        )

    def reset(self) -> None:
        """Forget the calls so far (a fresh run of the same scenario)."""
        self.calls = 0
        self.requests.clear()
        self._seen_length.clear()

    def summary(self) -> dict[str, Any]:
        """Counters for test output."""
        return {"scenario": self.scenario, "calls": self.calls}
