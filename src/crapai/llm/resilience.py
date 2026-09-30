"""Staying within limits and surviving trouble: retry, rate limit, adaptive concurrency, breaker.

Four small tools that the screening engine combines (plan chapters 9.3 and 9.4). All of them take
their clock and their ``sleep`` as parameters, so tests run in microseconds and never wait.

:class:`RetryPolicy` and :func:`call_with_retry`
    Repeat a call after a rate limit (429) or a transient error (5xx, timeout, lost connection)
    with exponential back-off and jitter; obey ``retry_after`` when the provider sends it. Errors
    that repeating cannot fix (wrong key, empty credit, context too long, refused content) are
    raised at once.
:class:`RateLimiter`
    Two limits over a sliding window of 60 seconds: requests per minute and tokens per minute.
    The caller reserves the tokens it expects and corrects the number when the real one is known.
:class:`AdaptiveConcurrency`
    How many requests may be in flight. It halves after a rate limit and grows back by one after a
    run of successes (additive increase, multiplicative decrease).
:class:`CircuitBreaker`
    Counts failures in a row; when they reach a limit the run is paused instead of burning through
    the remaining records (and the budget) with the same error.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from crapai.errors import ProviderError, RateLimited, TransientError
from crapai.llm.base import retry_after_of

logger = logging.getLogger(__name__)
T = TypeVar("T")

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class RetryPolicy:
    """How often and how patiently a failed call is repeated.

    Attributes:
        max_retries: Repeats after a transient error (not counting the first try).
        base_delay_s: Wait before the first repeat; doubled for each further repeat.
        max_delay_s: Upper limit of a single wait.
        jitter: Random share of the wait added or removed (0.25 = plus/minus 25 %), so that many
            workers do not come back at the same moment.
        max_retry_time_s: A rate limit is waited out for at most this long in total.
    """

    max_retries: int = 5
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    jitter: float = 0.25
    max_retry_time_s: float = 600.0

    def delay(self, attempt: int, rng: random.Random) -> float:
        """The wait before repeat number ``attempt`` (1 for the first repeat)."""
        raw = min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
        spread = raw * self.jitter
        return max(0.0, raw + rng.uniform(-spread, spread))


async def call_with_retry(
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = time.monotonic,
    rng: random.Random | None = None,
    on_rate_limit: Callable[[], None] | None = None,
    on_retry: Callable[[int, ProviderError, float], None] | None = None,
) -> T:
    """Run ``call`` and repeat it after a rate limit or a transient error.

    Args:
        call: A function that makes one attempt and returns an awaitable.
        policy: The retry rules.
        sleep: Used for the waits.
        clock: Monotonic seconds (to bound the total time spent waiting on rate limits).
        rng: Random source for the jitter (seeded in tests).
        on_rate_limit: Called each time a 429 arrives (the engine lowers its concurrency).
        on_retry: Called before each wait with ``(repeat number, error, wait in seconds)``.

    Raises:
        ProviderError: the last error once the retries or the waiting time are used up, or at
            once for an error that repeating cannot fix.
    """
    rng = rng or random.Random()
    started = clock()
    repeats = 0
    while True:
        try:
            return await call()
        except RateLimited as error:
            failure: ProviderError = error
            if on_rate_limit is not None:
                on_rate_limit()
            repeats += 1
            wait = retry_after_of(error)
            wait = policy.delay(repeats, rng) if wait is None else min(wait, policy.max_delay_s)
            if clock() - started + wait > policy.max_retry_time_s:
                logger.warning("Rate limit not lifted after %.0f s; giving up", clock() - started)
                raise
        except TransientError as error:
            failure = error
            repeats += 1
            if repeats > policy.max_retries:
                logger.warning("Giving up after %d repeat(s): %s", policy.max_retries, error.code)
                raise
            wait = policy.delay(repeats, rng)
        if on_retry is not None:
            on_retry(repeats, failure, wait)
        logger.info("Repeat %d in %.2f s (%s)", repeats, wait, failure.code)
        await sleep(wait)


class RateLimiter:
    """Requests per minute and tokens per minute over a sliding 60-second window.

    Args:
        rpm: Requests allowed per minute.
        tpm: Tokens allowed per minute.
        clock: Monotonic seconds.
        sleep: Used to wait for room in the window.
        window_s: Length of the window (60 in use; smaller in tests).
    """

    def __init__(
        self,
        rpm: int,
        tpm: int,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        window_s: float = 60.0,
    ) -> None:
        self.rpm, self.tpm = rpm, tpm
        self._clock, self._sleep, self._window = clock, sleep, window_s
        self._events: deque[list[float]] = deque()  # [time, tokens]
        self._lock = asyncio.Lock()
        self.waited_s = 0.0

    def _expire(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= self._window:
            self._events.popleft()

    def _wait_needed(self, now: float, tokens: int) -> float:
        """Seconds until a request of ``tokens`` fits, 0 if it fits now."""
        self._expire(now)
        used = sum(event[1] for event in self._events)
        too_many = len(self._events) >= self.rpm
        too_big = bool(self._events) and used + tokens > self.tpm
        if not too_many and not too_big:
            return 0.0
        needed = 0.0
        running_tokens, running_count = used, len(self._events)
        for moment, amount in self._events:  # when do enough old events leave the window?
            running_tokens -= amount
            running_count -= 1
            needed = moment + self._window - now
            if running_count < self.rpm and (
                not self._events or running_tokens + tokens <= self.tpm
            ):
                break
        return max(needed, 0.0)

    async def acquire(self, tokens: int) -> float:
        """Reserve room for one request of about ``tokens`` tokens; returns the seconds waited."""
        tokens = max(0, tokens)
        waited = 0.0
        async with self._lock:
            while True:
                wait = self._wait_needed(self._clock(), tokens)
                if wait <= 0:
                    break
                await self._sleep(wait)
                waited += wait
            self._events.append([self._clock(), float(tokens)])
        self.waited_s += waited
        return waited

    def correct(self, reserved: int, actual: int) -> None:
        """Replace the reservation of the newest matching request by the real token count."""
        for event in reversed(self._events):
            if int(event[1]) == reserved:
                event[1] = float(actual)
                return


class AdaptiveConcurrency:
    """How many requests may run at once; lowered by rate limits, raised by success.

    Args:
        maximum: The configured ``max_concurrency``.
        minimum: Never go below this.
        recover_after: Successes in a row that raise the limit by one.
    """

    def __init__(self, maximum: int, *, minimum: int = 1, recover_after: int = 20) -> None:
        self.maximum, self.minimum, self.recover_after = maximum, minimum, recover_after
        self.limit = maximum
        self._running = 0
        self._successes = 0
        self._condition = asyncio.Condition()

    async def acquire(self) -> None:
        """Wait until fewer than ``limit`` requests are running, then count this one."""
        async with self._condition:
            while self._running >= self.limit:
                await self._condition.wait()
            self._running += 1

    async def release(self) -> None:
        """Free a slot."""
        async with self._condition:
            self._running -= 1
            self._condition.notify_all()

    def on_rate_limited(self) -> None:
        """Halve the limit (not below the minimum) and start counting successes again."""
        self.limit = max(self.minimum, self.limit // 2)
        self._successes = 0
        logger.warning("Rate limited: concurrency lowered to %d", self.limit)

    def on_success(self) -> None:
        """Count a success; after a run of them the limit grows back by one."""
        self._successes += 1
        if self._successes >= self.recover_after and self.limit < self.maximum:
            self.limit += 1
            self._successes = 0
            logger.info("Concurrency raised to %d", self.limit)


class CircuitBreaker:
    """Stops a run that keeps failing.

    Args:
        threshold: Failures in a row that open the breaker (0 switches it off).
    """

    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.consecutive = 0
        self.total_failures = 0

    def record_success(self) -> None:
        """A record was processed without error: the count starts again."""
        self.consecutive = 0

    def record_failure(self) -> None:
        """A record failed for good (retries used up)."""
        self.consecutive += 1
        self.total_failures += 1

    @property
    def open(self) -> bool:
        """True once ``threshold`` failures happened in a row."""
        return self.threshold > 0 and self.consecutive >= self.threshold
