"""The screening engine: works through the records in batches, safely (plan 8.6, 9, 11, 28.4).

**What it does**

1. The records are split into *batches* ("packages") of ``batch_size``.
2. Inside a batch a pool of workers processes records at the same time. Each record is one prompt,
   one answer, one validated result line. The rate limiter, the retry rules and the adaptive
   concurrency stand between the workers and the provider.
3. Every result is appended to ``screening.jsonl`` at once (single writer, flushed to disk), so a
   crash loses at most the records that were in flight, never a finished one.
4. After each batch the engine **verifies** that every processed record really has a result line
   on disk, looks at how many failed, saves the manifest (the checkpoint) and only then starts the
   next batch.

**When it stops, and in which state** (every state but ``completed`` can be resumed)

=============================================  ===========  ==========
Cause                                          State        Code
=============================================  ===========  ==========
all records done                               completed
Ctrl+C, ``stop`` in control.json, kill         interrupted
``pause`` in control.json                      paused
wrong or refused key (401/403)                 failed       E301
credit used up                                 paused       E307
results cannot be saved (disk full, locked)    failed       E401/E403
too many failures in a row                     paused       E308
too many failures in one batch                 paused       E308
cost limit reached                             paused       E308
=============================================  ===========  ==========

One failed record never stops the run: it gets a result line with status ``parse_error``,
``api_error``, ``truncated`` or ``too_long`` and the error code, and is tried again on resume.
Nothing is logged of the record's content, only its ``study_uid`` and codes.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crapai.cost.pricing import Price
from crapai.errors import (
    AuthError,
    ContentRefused,
    ContextTooLong,
    ParseError,
    ProviderError,
    QuotaExceeded,
    SaraError,
    StorageError,
)
from crapai.llm.base import LLMProvider, LLMRequest, LLMResponse
from crapai.llm.resilience import (
    AdaptiveConcurrency,
    CircuitBreaker,
    RateLimiter,
    RetryPolicy,
    Sleep,
    call_with_retry,
)
from crapai.prompts.builder import STRUCTURED, PromptBuilder
from crapai.screening.answer import Answer, check_quotes, parse_answer, parse_legacy
from crapai.screening.store import BatchInfo, Manifest, ResultRow, RunState, RunStore, now_iso

logger = logging.getLogger(__name__)

MIN_RECORDS_FOR_RATE = 5  # a batch smaller than this is not judged by its error rate
LENGTH_RETRY_FACTOR = 2  # a cut-off answer is asked again with this many times the limit
MAX_OUTPUT_CAP = 16_000


@dataclass(frozen=True)
class PlanItem:
    """One record to screen."""

    uid: str
    title: str
    abstract: str


@dataclass
class EngineSettings:
    """Everything the engine needs from the configuration, as plain values."""

    model: str
    temperature: float = 0.0
    top_p: float | None = None
    seed: int | None = None
    max_output_tokens: int = 800
    expected_output_tokens: int = 120
    timeout_s: float = 60.0
    concurrency: int = 5
    rpm: int = 500
    tpm: int = 200_000
    max_retries: int = 5
    max_parse_retries: int = 2
    retry_base_delay_s: float = 1.0
    retry_max_delay_s: float = 60.0
    max_retry_time_s: float = 600.0
    max_cost: float | None = None
    batch_size: int = 1000
    max_batch_error_rate: float = 0.5
    max_consecutive_errors: int = 20
    checkpoint_seconds: float = 2.0
    heartbeat_seconds: float = 10.0
    stop_grace_seconds: float = 10.0
    keep_raw: bool = False
    currency: str = "USD"


@dataclass
class Progress:
    """A snapshot for the progress bar and the manifest."""

    state: str
    done: int
    total: int
    ok: int
    errors: int
    cost: float
    batch: int
    batches: int
    concurrency: int
    elapsed_s: float
    eta_s: float | None
    message: str = ""


@dataclass
class RunSummary:
    """The result of one engine session.

    ``total``, ``done`` and ``by_status`` are **cumulative over the whole run**: after a resume
    they include the records that earlier sessions finished, so "79'000 of 80'000" stays true.
    ``session_done`` is what this session alone did.
    """

    state: str
    total: int
    done: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    stop_reason: str = ""
    last_error: dict[str, str] = field(default_factory=dict)
    duration_s: float = 0.0
    batches_done: int = 0
    warnings: list[str] = field(default_factory=list)
    session_done: int = 0  # records this session processed (``done`` includes earlier sessions)

    @property
    def errors(self) -> int:
        """Records that ended in any status but ``ok``."""
        return sum(n for status, n in self.by_status.items() if status != "ok")

    @property
    def ok(self) -> int:
        """Records screened successfully."""
        return self.by_status.get("ok", 0)


class RunAbort(Exception):
    """A condition that ends the run (not just one record). Internal to the engine."""

    def __init__(self, state: RunState, reason: str, error: SaraError | None = None) -> None:
        super().__init__(reason)
        self.state, self.reason, self.error = state, reason, error


def chunks(items: list[PlanItem], size: int) -> list[list[PlanItem]]:
    """Split ``items`` into lists of at most ``size`` (the batches)."""
    return [items[start : start + size] for start in range(0, len(items), max(1, size))]


class ScreeningEngine:
    """Screens a list of records with one provider.

    Args:
        provider: Where the questions go (a real provider or the mock).
        builder: Builds the prompt of a record and fingerprints it.
        settings: Limits, retries, batch rules.
        store: Where results and the manifest are kept.
        manifest: The manifest of this run (updated and saved by the engine).
        price: Price of the model, for the cost figures (None = no cost).
        clock: Monotonic seconds (injectable for tests).
        sleep: Used for all waits (injectable for tests).
        rng: Random source for retry jitter.
        progress: Called with a :class:`Progress` after records and batches.
        control: Returns ``"pause"``, ``"stop"`` or None; asked once a second.
        heartbeat: Called every ``heartbeat_seconds`` to show the project lock is alive.
        already_ok: Records that already have an ``ok`` result (they are never sent again).
    """

    def __init__(
        self,
        provider: LLMProvider,
        builder: PromptBuilder,
        settings: EngineSettings,
        store: RunStore,
        manifest: Manifest,
        *,
        price: Price | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        progress: Callable[[Progress], None] | None = None,
        control: Callable[[], str | None] | None = None,
        heartbeat: Callable[[], None] | None = None,
        already_ok: set[str] | None = None,
    ) -> None:
        self.provider, self.builder, self.settings = provider, builder, settings
        self.store, self.manifest, self.price = store, manifest, price
        self._clock, self._sleep = clock, sleep
        self._rng = rng or random.Random(settings.seed or 0)
        self._progress, self._control, self._heartbeat = progress, control, heartbeat
        self._already_ok = set(already_ok or ())
        self.limiter = RateLimiter(settings.rpm, settings.tpm, clock=clock, sleep=sleep)
        self.concurrency = AdaptiveConcurrency(settings.concurrency)
        self.breaker = CircuitBreaker(settings.max_consecutive_errors)
        self.retry = RetryPolicy(
            settings.max_retries,
            settings.retry_base_delay_s,
            settings.retry_max_delay_s,
            0.25,
            settings.max_retry_time_s,
        )
        self._write_lock = asyncio.Lock()
        self._stop: RunState | None = None
        self._stop_reason = ""
        self._abort: RunAbort | None = None
        self._counts: Counter[str] = Counter()  # results of this session
        self._base: Counter[str] = Counter()  # results of earlier sessions (already_ok records)
        self._skipped = 0
        self._latencies: list[float] = []
        self._cost = 0.0
        self._tokens_in = self._tokens_out = 0
        self._models_seen: list[str] = []
        self._started = 0.0
        self._last_save = 0.0
        self._last_progress = 0.0
        self._total = 0
        self._batches = 0
        self._batch_index = 0
        self._capabilities = provider.capabilities(settings.model)

    # -- public ---------------------------------------------------------------------------------

    def request_stop(self, state: RunState, reason: str) -> None:
        """Ask the engine to finish the records in flight and stop in ``state``."""
        if self._stop is None:
            self._stop, self._stop_reason = state, reason
            logger.warning("Stop requested: %s (%s)", reason, state.value)

    async def run(self, items: list[PlanItem]) -> RunSummary:
        """Process ``items`` batch by batch; returns when done or stopped. Never raises for a
        record-level problem.

        Raises:
            asyncio.CancelledError: if the surrounding task is cancelled (after the state was
                written to the manifest).
        """
        todo = [item for item in items if item.uid not in self._already_ok]
        self._total = len(todo)
        self._skipped = len(items) - len(todo)
        batches = chunks(todo, self.settings.batch_size)
        self._batches = len(batches)
        self._started = self._last_save = self._clock()
        self._begin_session(len(items) - len(todo))
        monitor = asyncio.create_task(self._monitor())
        final = RunState.COMPLETED
        error: SaraError | None = None
        try:
            for index, batch in enumerate(batches):
                if self._stop is not None:
                    break
                self._batch_index = index
                await self._run_batch(index, batch)
                if self._abort is not None:
                    raise self._abort
                self._check_batch_rules(index)
            if self._stop is not None:
                final = self._stop
        except RunAbort as abort:
            final, error = abort.state, abort.error
            self._stop_reason = abort.reason
            logger.error("Run ended in state %s: %s", final.value, abort.reason)
        except asyncio.CancelledError:
            self._finish(RunState.INTERRUPTED, "cancelled", None)
            raise
        finally:
            monitor.cancel()
        self._finish(final, self._stop_reason, error)
        return self._summary(final, error)

    # -- session and batch bookkeeping -----------------------------------------------------------

    def _begin_session(self, skipped: int) -> None:
        m = self.manifest
        if skipped:
            # What earlier sessions achieved, from the record of truth (once per session).
            previous = self.store.last_results()
            self._base = Counter(
                row.status for uid, row in previous.items() if uid in self._already_ok
            )
        m.state = RunState.RUNNING.value
        m.started_at = m.started_at or now_iso()
        m.finished_at = ""
        m.stop_reason = ""
        m.sessions.append({"started": now_iso(), "planned": self._total, "skipped_ok": skipped})
        m.counts["total"] = max(m.counts.get("total", 0), self._total + skipped)
        self._save_manifest(force=True)
        logger.info(
            "Run %s: %d record(s) in %d batch(es), %d already done",
            m.run_id,
            self._total,
            self._batches,
            skipped,
        )

    def _save_manifest(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_save < self.settings.checkpoint_seconds:
            return
        self._last_save = now
        m = self.manifest
        merged = self._base + self._counts
        m.counts = {
            "total": max(m.counts.get("total", 0), self._skipped + self._total),
            **dict(merged),
            "done": sum(merged.values()),
        }
        m.usage = {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost": round(self._cost, 6),
            "currency": self.settings.currency,
        }
        m.llm["model_returned"] = list(self._models_seen)
        if self._latencies:
            ordered = sorted(self._latencies)
            m.metrics = {
                "latency_median_s": round(statistics.median(ordered), 3),
                "latency_p95_s": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
                "records_per_minute": round(
                    60 * sum(self._counts.values()) / max(self._clock() - self._started, 1e-6), 2
                ),
            }
        try:
            self.store.save_manifest(m)
        except StorageError as exc:
            # The results file is the record of truth; a failed manifest is reported, not fatal.
            logger.error("Manifest not saved: %s", exc.code)

    def _emit(self, *, force: bool = False, message: str = "") -> None:
        if self._progress is None:
            return
        now = self._clock()
        if not force and now - self._last_progress < 0.1:
            return
        self._last_progress = now
        session = sum(self._counts.values())
        merged = self._base + self._counts
        done = sum(merged.values())
        elapsed = now - self._started
        # The rest is estimated from the speed of this session only.
        eta = (elapsed / session) * (self._total - session) if session else None
        self._progress(
            Progress(
                state=self.manifest.state,
                done=done,
                total=self._skipped + self._total,
                ok=merged.get("ok", 0),
                errors=done - merged.get("ok", 0),
                cost=self._cost,
                batch=self._batch_index + 1,
                batches=self._batches,
                concurrency=self.concurrency.limit,
                elapsed_s=elapsed,
                eta_s=eta,
                message=message,
            )
        )

    async def _monitor(self) -> None:
        """Every second: look for a stop request; now and then save and show a heartbeat."""
        next_heartbeat = self._clock() + self.settings.heartbeat_seconds
        while True:
            await self._sleep(1.0)
            if self._control is not None:
                command = self._control()
                if command == "pause":
                    self.request_stop(RunState.PAUSED, "pause requested")
                elif command == "stop":
                    self.request_stop(RunState.INTERRUPTED, "stop requested")
            if self._heartbeat is not None and self._clock() >= next_heartbeat:
                next_heartbeat = self._clock() + self.settings.heartbeat_seconds
                try:
                    self._heartbeat()
                except SaraError as exc:
                    self._abort = self._abort or RunAbort(RunState.FAILED, "project lock lost", exc)
                    self.request_stop(RunState.FAILED, "project lock lost")
            self._save_manifest()

    def _finish(self, state: RunState, reason: str, error: SaraError | None) -> None:
        m = self.manifest
        m.state = state.value
        m.stop_reason = reason
        if state in (RunState.COMPLETED,):
            m.finished_at = now_iso()
        if error is not None:
            m.last_error = {"code": error.code, "message": error.user_message}
        if self._models_seen and len(set(self._models_seen)) > 1:
            note = f"The provider reported different model names: {', '.join(self._models_seen)}"
            if note not in m.warnings:
                m.warnings.append(note)
        self._save_manifest(force=True)
        self._emit(force=True, message=reason)
        logger.info("Run %s finished in state %s (%s)", m.run_id, state.value, reason or "-")

    def _summary(self, state: RunState, error: SaraError | None) -> RunSummary:
        merged = self._base + self._counts
        return RunSummary(
            state=state.value,
            total=self._skipped + self._total,
            done=sum(merged.values()),
            session_done=sum(self._counts.values()),
            by_status=dict(merged),
            cost=self._cost,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            stop_reason=self._stop_reason,
            last_error={"code": error.code, "message": error.user_message} if error else {},
            duration_s=self._clock() - self._started,
            batches_done=sum(1 for b in self.manifest.batches if b.get("status") == "verified"),
            warnings=list(self.manifest.warnings),
        )

    # -- one batch --------------------------------------------------------------------------------

    async def _run_batch(self, index: int, batch: list[PlanItem]) -> None:
        info = BatchInfo(index=index, size=len(batch), status="running", started=now_iso())
        self._upsert_batch(info)
        offset = self.store.results_size()
        queue: asyncio.Queue[PlanItem] = asyncio.Queue()
        for item in batch:
            queue.put_nowait(item)
        before = Counter(self._counts)
        workers = [
            asyncio.create_task(self._worker(queue, index))
            for _ in range(min(self.settings.concurrency, len(batch)))
        ]
        await self._wait_for(workers)
        after = Counter(self._counts)
        processed = sum(after.values()) - sum(before.values())
        info.done = processed
        info.ok = after.get("ok", 0) - before.get("ok", 0)
        info.errors = processed - info.ok
        info.finished = now_iso()
        self._verify_batch(info, batch, offset)
        self._upsert_batch(info)
        self._save_manifest(force=True)
        self._emit(force=True, message=f"batch {index + 1} of {self._batches}")

    async def _wait_for(self, workers: list[asyncio.Task[None]]) -> None:
        """Wait for the workers of a batch. After a stop request the requests in flight get
        ``stop_grace_seconds`` to finish; then they are cancelled (they will be tried again on
        resume, nothing was written for them)."""
        pending = set(workers)
        stopped_at: float | None = None
        while pending:
            _, pending = await asyncio.wait(pending, timeout=0.05)
            if self._stop is not None and stopped_at is None:
                stopped_at = self._clock()
            grace_over = stopped_at is not None and (
                self._clock() - stopped_at >= self.settings.stop_grace_seconds
            )
            if pending and grace_over:
                logger.warning(
                    "Cancelling %d request(s) still in flight after the grace time", len(pending)
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                return
        await asyncio.gather(*workers, return_exceptions=True)

    def _verify_batch(self, info: BatchInfo, batch: list[PlanItem], offset: int) -> None:
        """Check on disk that every processed record of the batch has a result line."""
        written = {row.study_uid for row in self.store.read_results_since(offset)}
        expected = {item.uid for item in batch} if info.done == len(batch) else None
        if expected is not None and not expected <= written:
            missing = len(expected - written)
            info.status = "failed"
            info.note = f"{missing} result(s) missing on disk"
            logger.error("Batch %d: %s", info.index + 1, info.note)
            raise RunAbort(
                RunState.FAILED,
                info.note,
                StorageError(info.note, code="E401", hint="Check the disk, then resume."),
            )
        if info.done < len(batch):
            info.status = "partial"
            info.note = f"{info.done} of {len(batch)} processed before the stop"
        else:
            info.status = "verified"
        logger.info(
            "Batch %d/%d %s: %d ok, %d failed",
            info.index + 1,
            self._batches,
            info.status,
            info.ok,
            info.errors,
        )

    def _check_batch_rules(self, index: int) -> None:
        """Pause if a batch failed too often or the failures in a row reached the limit."""
        info = self.manifest.batches[index] if index < len(self.manifest.batches) else {}
        size = int(info.get("done", 0))
        errors = int(info.get("errors", 0))
        if size >= MIN_RECORDS_FOR_RATE and errors / size > self.settings.max_batch_error_rate:
            raise RunAbort(
                RunState.PAUSED,
                f"{errors} of {size} records of batch {index + 1} failed",
                ProviderError(
                    f"{errors} of {size} records of batch {index + 1} failed",
                    code="E308",
                    hint="Read the log, fix the cause and resume.",
                ),
            )

    def _upsert_batch(self, info: BatchInfo) -> None:
        row = {
            "index": info.index,
            "size": info.size,
            "done": info.done,
            "ok": info.ok,
            "errors": info.errors,
            "status": info.status,
            "started": info.started,
            "finished": info.finished,
            "note": info.note,
        }
        batches = self.manifest.batches
        while len(batches) <= info.index:
            batches.append({})
        batches[info.index] = row

    # -- one record -------------------------------------------------------------------------------

    async def _worker(self, queue: asyncio.Queue[PlanItem], batch_index: int) -> None:
        while self._stop is None and self._abort is None:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if item.uid in self._already_ok:
                continue
            if self._cost_limit_reached():
                self.request_stop(RunState.PAUSED, "cost limit reached")
                self._abort = RunAbort(
                    RunState.PAUSED,
                    "cost limit reached",
                    ProviderError(
                        "The cost limit was reached",
                        code="E308",
                        hint="Raise limits.max_cost and resume.",
                    ),
                )
                return
            await self.concurrency.acquire()
            try:
                row = await self._process(item, batch_index)
            except RunAbort as abort:
                self._abort = self._abort or abort
                self.request_stop(abort.state, abort.reason)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a bug in one record must not end the run
                logger.exception("Unexpected error for record %s", item.uid)
                row = ResultRow(
                    study_uid=item.uid,
                    run_id=self.manifest.run_id,
                    status="api_error",
                    error_code="E999",
                    error_message=type(exc).__name__,
                    prompt_hash=self.builder.prefix_hash,
                    batch=batch_index,
                )
            finally:
                await self.concurrency.release()
            try:
                await self._commit(row)
            except RunAbort as abort:
                self._abort = self._abort or abort
                self.request_stop(abort.state, abort.reason)
                return

    def _cost_limit_reached(self) -> bool:
        limit = self.settings.max_cost
        if limit is None or self.price is None:
            return False
        done = sum(self._counts.values())
        average = self._cost / done if done else 0.0
        reserve = average * self.settings.concurrency  # what the requests in flight will add
        return self._cost + reserve >= limit

    def _price(self, tokens_in: int, tokens_out: int) -> float | None:
        if self.price is None:
            return None
        return (
            tokens_in / 1000 * self.price.input_per_1k
            + tokens_out / 1000 * self.price.output_per_1k
        )

    async def _commit(self, row: ResultRow) -> None:
        """Write the result line and update the counters (the single writer)."""
        async with self._write_lock:
            try:
                self.store.append_result(row)
            except StorageError as exc:
                raise RunAbort(RunState.FAILED, "results cannot be saved", exc) from exc
            self._counts[row.status] += 1
            self._tokens_in += row.tokens_in
            self._tokens_out += row.tokens_out
            self._cost += row.cost or 0.0
            self._latencies.append(row.latency_s)
            if row.status in ("parse_error", "api_error", "truncated"):
                self.breaker.record_failure()
            else:
                self.breaker.record_success()
            if row.is_ok:
                self.concurrency.on_success()
        if self.breaker.open:
            reason = f"{self.breaker.consecutive} records failed in a row"
            raise RunAbort(
                RunState.PAUSED,
                reason,
                ProviderError(reason, code="E308", hint="Read the log, fix the cause and resume."),
            )
        self._save_manifest()
        self._emit()

    def _request(self, parts: Any, max_output: int, extra_user: str = "") -> LLMRequest:
        return LLMRequest(
            system=parts.system,
            user=parts.user + extra_user,
            model=self.settings.model,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            max_output_tokens=max_output,
            seed=self.settings.seed,
            timeout_s=self.settings.timeout_s,
        )

    def _parse(self, response: LLMResponse, item: PlanItem) -> Answer:
        if self.builder.output_format == STRUCTURED:
            answer = parse_answer(response.text)
            check_quotes(answer, f"{item.title}\n{item.abstract}")
            return answer
        return parse_legacy(response.text)

    async def _process(self, item: PlanItem, batch_index: int) -> ResultRow:
        """Screen one record; a problem with the record becomes a result row, never an exception.

        Raises:
            RunAbort: only for problems that concern the whole run (key refused, credit used up).
        """
        parts = self.builder.build(item.title, item.abstract)
        base = ResultRow(
            study_uid=item.uid,
            run_id=self.manifest.run_id,
            status="api_error",
            prompt_hash=self.builder.prefix_hash,
            schema_version=self.builder.schema_version,
            batch=batch_index,
        )
        prompt_tokens = self.provider.count_tokens(parts.system + parts.user, self.settings.model)
        context = self._capabilities.context_tokens
        if context is not None and prompt_tokens + self.settings.max_output_tokens > context:
            return self._failed(
                base, "too_long", "E303", "The record does not fit into the context"
            )
        max_output = self.settings.max_output_tokens
        extra = ""
        length_retried = False
        parse_attempts = 0
        attempts = 0
        tokens_in = tokens_out = 0
        latency = 0.0
        flags: list[str] = []
        last_reason = ""
        while True:
            await self.limiter.acquire(prompt_tokens + self.settings.expected_output_tokens)
            request = self._request(parts, max_output, extra)
            attempts += 1
            try:
                response = await call_with_retry(
                    functools.partial(self.provider.complete, request),
                    self.retry,
                    sleep=self._sleep,
                    clock=self._clock,
                    rng=self._rng,
                    on_rate_limit=self.concurrency.on_rate_limited,
                )
            except AuthError as exc:
                raise RunAbort(RunState.FAILED, "the key was refused", exc) from exc
            except QuotaExceeded as exc:
                raise RunAbort(RunState.PAUSED, "the credit or quota is used up", exc) from exc
            except ContextTooLong as exc:
                return self._failed(base, "too_long", exc.code, exc.user_message, attempts)
            except ContentRefused as exc:
                return self._failed(base, "api_error", exc.code, exc.user_message, attempts)
            except ProviderError as exc:
                return self._failed(base, "api_error", exc.code, exc.user_message, attempts)
            self.limiter.correct(
                prompt_tokens + self.settings.expected_output_tokens,
                response.tokens_in + response.tokens_out,
            )
            tokens_in += response.tokens_in
            tokens_out += response.tokens_out
            latency += response.latency_s
            if response.model_returned and response.model_returned not in self._models_seen:
                self._models_seen.append(response.model_returned)
                if len(self._models_seen) > 1:
                    flags.append("model_changed")
            if response.finish_reason == "length":
                if not length_retried and max_output < MAX_OUTPUT_CAP:
                    length_retried = True
                    max_output = min(MAX_OUTPUT_CAP, max_output * LENGTH_RETRY_FACTOR)
                    flags.append("length_retry")
                    continue
                return self._failed(
                    base,
                    "truncated",
                    "E304",
                    "The answer was cut off",
                    attempts,
                    tokens_in,
                    tokens_out,
                    flags,
                )
            try:
                answer = self._parse(response, item)
            except ParseError as exc:
                last_reason = str(exc.details.get("reason", exc.user_message))
                parse_attempts += 1
                if parse_attempts > self.settings.max_parse_retries:
                    return self._failed(
                        base,
                        "parse_error",
                        "E304",
                        last_reason,
                        attempts,
                        tokens_in,
                        tokens_out,
                        flags,
                    )
                flags.append("parse_retry")
                extra = (
                    f"\n\nYour previous answer was not valid ({last_reason}). "
                    "Answer again with one valid JSON object only."
                )
                continue
            return self._success(
                base, answer, response, attempts, tokens_in, tokens_out, latency, flags
            )

    def _failed(
        self,
        base: ResultRow,
        status: str,
        code: str,
        message: str,
        attempts: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        flags: list[str] | None = None,
    ) -> ResultRow:
        logger.warning("Record %s: %s (%s)", base.study_uid, status, code)
        return base.model_copy(
            update={
                "status": status,
                "error_code": code,
                "error_message": message[:300],
                "attempts": attempts,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": self._price(tokens_in, tokens_out),
                "flags": flags or [],
            }
        )

    def _success(
        self,
        base: ResultRow,
        answer: Answer,
        response: LLMResponse,
        attempts: int,
        tokens_in: int,
        tokens_out: int,
        latency: float,
        flags: list[str],
    ) -> ResultRow:
        if answer.unverified_quotes:
            flags = [*flags, "quote_unverified"]
        if not answer.consistent:
            flags = [*flags, "inconsistent"]
        return base.model_copy(
            update={
                "status": "ok",
                "decision": answer.decision,
                "derived_decision": answer.derived_decision,
                "consistent": answer.consistent,
                "reasoning": answer.reasoning,
                "inclusion": [vars(v) for v in answer.inclusion],
                "exclusion": [vars(v) for v in answer.exclusion],
                "ambiguities": answer.ambiguities,
                "quote_unverified": answer.unverified_quotes,
                "model_returned": response.model_returned,
                "attempts": attempts,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": self._price(tokens_in, tokens_out),
                "latency_s": round(latency, 3),
                "flags": flags,
            }
        )
