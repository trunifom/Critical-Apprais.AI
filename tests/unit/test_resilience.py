"""Retry, rate limiter, adaptive concurrency and circuit breaker (plan chapters 9.3 and 9.4)."""

from __future__ import annotations

import asyncio
import random

import pytest

from crapai.errors import (
    AuthError,
    ContentRefused,
    ContextTooLong,
    QuotaExceeded,
    RateLimited,
    TransientError,
)
from crapai.llm.resilience import (
    AdaptiveConcurrency,
    CircuitBreaker,
    RateLimiter,
    RetryPolicy,
    call_with_retry,
)


class FakeTime:
    """A clock that only moves when somebody sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def failing(errors: list[Exception], result: str = "done"):  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    async def call() -> str:
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return result

    return call, calls


# --- retry ---------------------------------------------------------------------------------------


def test_the_delay_doubles_and_is_capped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=10.0, jitter=0.0)
    rng = random.Random(1)
    assert [policy.delay(n, rng) for n in (1, 2, 3, 4, 5, 6)] == [1, 2, 4, 8, 10, 10]


def test_jitter_stays_inside_its_band() -> None:
    policy = RetryPolicy(base_delay_s=4.0, jitter=0.25)
    rng = random.Random(7)
    assert all(3.0 <= policy.delay(1, rng) <= 5.0 for _ in range(200))


async def test_a_transient_error_is_repeated_until_it_works() -> None:
    clock = FakeTime()
    call, calls = failing([TransientError("503"), TransientError("503")])
    result = await call_with_retry(
        call, RetryPolicy(jitter=0.0), sleep=clock.sleep, clock=clock.clock
    )
    assert result == "done" and calls["n"] == 3 and clock.sleeps == [1.0, 2.0]


async def test_transient_errors_stop_after_max_retries_with_the_last_error() -> None:
    clock = FakeTime()
    call, calls = failing([TransientError(f"e{i}") for i in range(10)])
    with pytest.raises(TransientError):
        await call_with_retry(
            call, RetryPolicy(max_retries=3), sleep=clock.sleep, clock=clock.clock
        )
    assert calls["n"] == 4  # the first try and three repeats


async def test_retry_after_of_the_provider_is_obeyed_and_reported() -> None:
    clock = FakeTime()
    lowered: list[int] = []
    error = RateLimited("429", code="E302", details={"retry_after_s": 7.0})
    call, _ = failing([error])
    await call_with_retry(
        call,
        RetryPolicy(),
        sleep=clock.sleep,
        clock=clock.clock,
        on_rate_limit=lambda: lowered.append(1),
    )
    assert clock.sleeps == [7.0] and lowered == [1]


async def test_retry_after_is_capped_by_the_longest_single_wait() -> None:
    clock = FakeTime()
    call, _ = failing([RateLimited("429", code="E302", details={"retry_after_s": 9999.0})])
    await call_with_retry(call, RetryPolicy(max_delay_s=30.0), sleep=clock.sleep, clock=clock.clock)
    assert clock.sleeps == [30.0]


async def test_a_rate_limit_that_lasts_too_long_raises() -> None:
    clock = FakeTime()
    call, calls = failing(
        [RateLimited("429", code="E302", details={"retry_after_s": 20.0}) for _ in range(100)]
    )
    with pytest.raises(RateLimited):
        await call_with_retry(
            call,
            RetryPolicy(max_retry_time_s=50.0, max_delay_s=20.0),
            sleep=clock.sleep,
            clock=clock.clock,
        )
    assert calls["n"] == 3 and clock.now == 40.0  # 2 waits fit into 50 s, the third does not


@pytest.mark.parametrize(
    "error",
    [
        AuthError("401", code="E301"),
        QuotaExceeded("q", code="E307"),
        ContextTooLong("c", code="E303"),
        ContentRefused("r", code="E306"),
    ],
)
async def test_errors_that_repeating_cannot_fix_are_raised_at_once(error: Exception) -> None:
    clock = FakeTime()
    call, calls = failing([error])
    with pytest.raises(type(error)):
        await call_with_retry(call, RetryPolicy(), sleep=clock.sleep, clock=clock.clock)
    assert calls["n"] == 1 and clock.sleeps == []


async def test_on_retry_is_told_about_every_wait() -> None:
    clock = FakeTime()
    seen: list[tuple[int, str, float]] = []
    call, _ = failing([TransientError("x"), TransientError("y")])
    await call_with_retry(
        call, RetryPolicy(jitter=0.0), sleep=clock.sleep, clock=clock.clock,
        on_retry=lambda n, error, wait: seen.append((n, error.code, wait)),
    )  # fmt: skip
    assert seen == [(1, "E305", 1.0), (2, "E305", 2.0)]


# --- rate limiter --------------------------------------------------------------------------------


async def test_requests_per_minute_are_enforced() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=3, tpm=10**9, clock=clock.clock, sleep=clock.sleep)
    waits = [await limiter.acquire(1) for _ in range(5)]
    assert waits[:3] == [0.0, 0.0, 0.0]
    assert waits[3] == pytest.approx(60.0) and waits[4] == pytest.approx(0.0, abs=1e-9)
    assert clock.now == pytest.approx(60.0)


async def test_tokens_per_minute_are_enforced() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=10**6, tpm=1000, clock=clock.clock, sleep=clock.sleep)
    assert await limiter.acquire(600) == 0.0
    assert await limiter.acquire(300) == 0.0
    assert await limiter.acquire(300) == pytest.approx(60.0)  # 600 + 300 + 300 > 1000


async def test_a_request_larger_than_the_limit_is_let_through_alone() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=100, tpm=1000, clock=clock.clock, sleep=clock.sleep)
    assert await limiter.acquire(5000) == 0.0  # would otherwise wait forever
    assert await limiter.acquire(10) > 0.0


async def test_the_window_slides() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=2, tpm=10**9, clock=clock.clock, sleep=clock.sleep)
    await limiter.acquire(1)
    clock.now = 30.0
    await limiter.acquire(1)
    assert await limiter.acquire(1) == pytest.approx(30.0)  # the first one leaves the window at 60


async def test_correct_replaces_the_reservation_with_the_real_count() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=100, tpm=1000, clock=clock.clock, sleep=clock.sleep)
    await limiter.acquire(900)
    limiter.correct(900, 100)
    assert await limiter.acquire(800) == 0.0  # 100 + 800 fits


async def test_the_total_wait_is_recorded() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=1, tpm=10**9, clock=clock.clock, sleep=clock.sleep)
    await limiter.acquire(1)
    await limiter.acquire(1)
    assert limiter.waited_s == pytest.approx(60.0)


async def test_many_tasks_share_one_limiter() -> None:
    clock = FakeTime()
    limiter = RateLimiter(rpm=4, tpm=10**9, clock=clock.clock, sleep=clock.sleep)
    await asyncio.gather(*(limiter.acquire(1) for _ in range(8)))
    assert clock.now == pytest.approx(
        60.0
    )  # 8 requests at 4 per minute: one full window of waiting


# --- adaptive concurrency ------------------------------------------------------------------------


async def test_the_limit_halves_on_rate_limits_and_never_goes_below_the_minimum() -> None:
    concurrency = AdaptiveConcurrency(8)
    for expected in (4, 2, 1, 1):
        concurrency.on_rate_limited()
        assert concurrency.limit == expected


async def test_successes_raise_the_limit_one_step_at_a_time() -> None:
    concurrency = AdaptiveConcurrency(4, recover_after=3)
    concurrency.on_rate_limited()
    concurrency.on_rate_limited()
    assert concurrency.limit == 1
    for _ in range(3):
        concurrency.on_success()
    assert concurrency.limit == 2
    for _ in range(30):
        concurrency.on_success()
    assert concurrency.limit == 4  # never above the configured maximum


async def test_a_rate_limit_resets_the_run_of_successes() -> None:
    concurrency = AdaptiveConcurrency(4, recover_after=3)
    concurrency.on_rate_limited()
    concurrency.on_success()
    concurrency.on_success()
    concurrency.on_rate_limited()
    concurrency.on_success()
    assert concurrency.limit == 1


async def test_no_more_than_the_limit_run_at_once() -> None:
    concurrency = AdaptiveConcurrency(3)
    running = peak = 0

    async def task() -> None:
        nonlocal running, peak
        await concurrency.acquire()
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        await concurrency.release()

    await asyncio.gather(*(task() for _ in range(12)))
    assert peak == 3


# --- circuit breaker -------------------------------------------------------------------------------


def test_the_breaker_opens_after_failures_in_a_row_and_a_success_resets_the_count() -> None:
    breaker = CircuitBreaker(3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.open
    breaker.record_failure()
    assert breaker.open and breaker.consecutive == 3 and breaker.total_failures == 5


def test_a_threshold_of_zero_switches_the_breaker_off() -> None:
    breaker = CircuitBreaker(0)
    for _ in range(100):
        breaker.record_failure()
    assert not breaker.open
