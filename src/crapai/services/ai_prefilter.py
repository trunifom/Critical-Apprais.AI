"""Optional AI pre-filter service: ask Jev whether a record clearly fails the criteria (ADR 0029).

Unlike :mod:`crapai.services.prefilter` (the deterministic language/year/type filters), this calls
an external service and costs money, so it is **never** run by ``crapai check``/``crapai screen``.
It is reached only through :func:`ai_prefilter_project`, called by the dedicated
``crapai jev-prefilter`` command or its GUI page -- and only when ``ai_prefilter.enabled`` is on in
``project.yaml``. A record it excludes is marked ``AI_PREFILTER_JEV`` (see
:mod:`crapai.prisma.reasons` for why that reason sits outside the automatic dedup/pre-filter/
validity chain) and never touched again by this service; a record it is not highly confident about
is left completely unchanged and goes to the ordinary, quote-bearing screening step as before.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.config.models import AiPrefilterOptions, ProjectConfig
from crapai.errors import AuthError, ConfigError, ProviderError, QuotaExceeded
from crapai.io.records_store import Record, read_records, write_records
from crapai.llm.jev_client import JevClient, MockJevClient
from crapai.llm.resilience import CircuitBreaker, RateLimiter, RetryPolicy, call_with_retry
from crapai.project.workspace import Workspace
from crapai.prompts.builder import criteria_block
from crapai.services.events import record_ai_prefilter

logger = logging.getLogger(__name__)

REASON = "AI_PREFILTER_JEV"
# A consecutive-failure limit is not user-configurable (unlike the screening engine): this is a
# small, one-shot, manually started step, not a long run that needs tuning of its own.
_BREAKER_THRESHOLD = 5

INSTRUCTIONS_TEMPLATE = (
    "Judge only from the title and abstract given as the state. Answer true only if it is clear "
    "that this record does NOT meet the inclusion criteria of this systematic review; answer "
    "false if it meets them, or if that is not clear from the title and abstract alone.\n\n"
    "{criteria}"
)


@dataclass(frozen=True)
class AiPrefilterSummary:
    """What one run of the AI pre-filter did.

    Attributes:
        records: Records in the project.
        eligible: Records that had no exclusion reason yet and were offered to Jev.
        checked: Of those, how many actually got an answer (others failed and were skipped).
        marked: Of those checked, how many were excluded (``AI_PREFILTER_JEV``).
        cost: Total USD cost reported by Jev across all requests.
        events_written: False if the PRISMA event could not be written.
    """

    records: int
    eligible: int
    checked: int
    marked: int
    cost: float
    events_written: bool = True


def build_client(
    options: AiPrefilterOptions, environ: dict[str, str] | None = None
) -> JevClient | MockJevClient:
    """The Jev client named by ``options``; ``model == "mock"`` needs no key (tests/demos).

    Raises:
        AuthError: E301 if the environment variable named by ``api_key_env`` is empty.
        ProviderError: E305 if the ``httpx`` package is missing.
    """
    if options.model == "mock":
        return MockJevClient()
    key = (environ if environ is not None else os.environ).get(options.api_key_env, "").strip()
    if not key:
        hint = f"Set {options.api_key_env} to the Jev API key (it is never stored in the project)."
        raise AuthError(
            f"The environment variable {options.api_key_env} is not set", code="E301", hint=hint
        )
    return JevClient(key, base_url=options.base_url, timeout_s=options.timeout_s)


def eligible_for_ai_prefilter(records: list[Record]) -> list[Record]:
    """Records with no exclusion reason yet and at least a title or an abstract to judge.

    Shared with :func:`crapai.services.cost.estimate_ai_prefilter` so the estimate counts exactly
    the records a real run would offer to Jev.
    """
    return [
        r for r in records if not r.exclusion_reason and (r.title.strip() or r.abstract.strip())
    ]


def _state_of(record: Record) -> str:
    return f"Title: {record.title}\nAbstract: {record.abstract}".strip()


async def _classify_all(
    targets: list[Record],
    options: AiPrefilterOptions,
    instructions: str,
    client: JevClient | MockJevClient,
) -> tuple[dict[str, Record], int, float]:
    """Ask Jev about every target; returns (marks by study_uid, checked count, total cost)."""
    limiter = RateLimiter(rpm=options.rpm, tpm=10**9)  # Jev has no published token-per-minute cap
    semaphore = asyncio.Semaphore(options.max_concurrency)
    breaker = CircuitBreaker(threshold=_BREAKER_THRESHOLD)
    policy = RetryPolicy(max_retries=options.max_retries)
    marks: dict[str, Record] = {}
    checked = 0
    cost = 0.0
    lock = asyncio.Lock()
    stop = asyncio.Event()

    async def worker(record: Record) -> None:
        nonlocal checked, cost
        async with semaphore:
            if stop.is_set():
                return
            state = _state_of(record)
            reserved = len(state) // 4
            await limiter.acquire(reserved)
            call = functools.partial(client.classify, state, instructions, model=options.model)
            try:
                decision = await call_with_retry(call, policy)
            except (AuthError, QuotaExceeded):
                stop.set()
                raise
            except ProviderError as error:
                breaker.record_failure()
                logger.warning(
                    "Jev pre-filter: record %s failed (%s)", record.study_uid, error.code
                )
                if breaker.open:
                    stop.set()
                return
            breaker.record_success()
            limiter.correct(reserved, decision.tokens_in)
            excluded = (
                decision.probability_true > decision.probability_false
                and decision.confidence >= options.confidence_floor
            )
            async with lock:
                checked += 1
                cost += decision.cost
                if excluded:
                    details = (
                        f"Jev ({options.model}): p(exclude)={decision.probability_true:.2f}, "
                        f"confidence={decision.confidence:.2f}"
                    )
                    marks[record.study_uid] = record.model_copy(
                        update={
                            "exclusion_reason": REASON,
                            "exclusion_details": details,
                            "extra_json": {
                                **record.extra_json,
                                "jev": {
                                    "model": decision.model_returned,
                                    "probability_true": decision.probability_true,
                                    "probability_false": decision.probability_false,
                                    "confidence": decision.confidence,
                                    "cost": decision.cost,
                                    "tokens_in": decision.tokens_in,
                                    "tokens_out": decision.tokens_out,
                                },
                            },
                        }
                    )
                if options.max_cost is not None and cost >= options.max_cost:
                    stop.set()

    await asyncio.gather(*(worker(record) for record in targets))
    return marks, checked, cost


def ai_prefilter_project(
    workspace: Workspace, *, client: JevClient | MockJevClient | None = None
) -> AiPrefilterSummary:
    """Run the Jev pre-filter once, under the project lock.

    Raises:
        ConfigError: E203 if ``ai_prefilter.enabled`` is off.
        AuthError: E301 if the API key is missing.
        StorageError: E402 if the project is in use, E404 for a damaged folder, E401 if
            ``records.csv`` is locked (nothing is changed).
    """
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        return apply_ai_prefilter(workspace, client=client)


def apply_ai_prefilter(
    workspace: Workspace, *, client: JevClient | MockJevClient | None = None
) -> AiPrefilterSummary:
    """Mark records; the caller holds the project lock (see :func:`ai_prefilter_project`)."""
    config: ProjectConfig = load_project_config(workspace.project_yaml)
    options = config.ai_prefilter
    if not options.enabled:
        raise ConfigError(
            "The Jev pre-filter is switched off (ai_prefilter.enabled is false)",
            code="E203",
            hint="Turn it on in the settings first, then run this command again.",
        )
    records = read_records(workspace.records_csv)
    targets = eligible_for_ai_prefilter(records)
    chosen_client = client or build_client(options)
    instructions = INSTRUCTIONS_TEMPLATE.format(criteria=criteria_block(config))
    try:
        marks, checked, cost = asyncio.run(
            _classify_all(targets, options, instructions, chosen_client)
        )
    finally:
        if client is None and hasattr(chosen_client, "aclose"):
            asyncio.run(chosen_client.aclose())
    updated = [marks.get(record.study_uid, record) for record in records]
    written = updated != records
    if written:
        write_records(workspace.records_csv, updated, backup_dir=workspace.backup_dir)
    by_reason = {REASON: len(marks)} if marks else {}
    events_ok = record_ai_prefilter(workspace, len(records), len(marks), by_reason)
    logger.info(
        "Jev pre-filter: %d of %d eligible record(s) marked %s; records.csv %s",
        len(marks),
        len(targets),
        REASON,
        "rewritten" if written else "unchanged",
    )
    return AiPrefilterSummary(
        records=len(records),
        eligible=len(targets),
        checked=checked,
        marked=len(marks),
        cost=cost,
        events_written=events_ok,
    )
