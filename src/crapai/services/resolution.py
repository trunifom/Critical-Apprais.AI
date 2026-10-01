"""Settle a disagreement between two or more finished screening runs: adjudicate or discuss.

Not part of ``docs/PROJEKTPLAN.md``; requested by the project lead (2026-10-02, ADR 0025).

``adjudicate``
    A separate "master" model (the project's current ``llm:`` settings) reads the record, the
    criteria and every disagreeing run's decision and reasoning, and decides once, for itself.
``discuss``
    Each disagreeing run's **own** model (reconstructed from that run's own manifest, not the
    project's current ``llm:`` settings, which may since have moved on) reconsiders its decision,
    seeing the others' decision and reasoning, for up to ``discussion.max_rounds`` rounds. Without
    consensus, ``discussion.tie_break`` decides: the majority, or ``NO_CONSENSUS``.

A resolution is stored exactly like a screening run (``runs/<run-id>/manifest.json``,
``screening.jsonl``, ``control.json``) so that pause/stop/resume, the project lock and
``crapai runs`` all keep working unchanged; only ``manifest.kind`` (``adjudicate`` or ``discuss``)
and a handful of otherwise-unused :class:`~crapai.screening.store.ResultRow` fields
(``source_decisions``, ``consensus``, ``rounds_used``, ``tie_break``, ``history``) tell it apart
from an ordinary run. It never touches ``records.csv`` or the PRISMA event stream: it reconciles
the model's own decisions, not the project's screening progress. :func:`resolvable_runs` and
:mod:`crapai.services.results` keep such a run out of the ordinary results/compare views.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from crapai.config.loader import load_project_config
from crapai.config.models import ProjectConfig
from crapai.cost.estimator import cost_of
from crapai.cost.pricing import Price
from crapai.errors import (
    AuthError,
    ConfigError,
    ContextTooLong,
    ParseError,
    ProviderError,
    QuotaExceeded,
    StorageError,
)
from crapai.io.records_store import read_records
from crapai.llm.base import LLMProvider, LLMRequest, LLMResponse
from crapai.llm.resilience import RetryPolicy, call_with_retry
from crapai.project.atomic import atomic_write_text
from crapai.project.workspace import Workspace
from crapai.prompts.resolution import (
    DisputedItem,
    Opinion,
    build_adjudication_prompt,
    build_discussion_prompt,
)
from crapai.screening.answer import Answer, parse_answer
from crapai.screening.store import Manifest, ResultRow, RunState, RunStore, now_iso
from crapai.services.cost import find_price
from crapai.services.screening import build_provider, find_run, list_runs, new_run_id, run_folder
from crapai.stats.agreement import unstable_records
from crapai.stats.results import DECISIONS

logger = logging.getLogger(__name__)

METHODS: tuple[str, ...] = ("adjudicate", "discuss")
PLAN_NAME = "resolution_plan.json"
_SCHEMA_VERSION = 1


class _Abort(Exception):
    """A problem that ends the whole resolution, not just the item being settled (mirrors the
    screening engine's ``RunAbort``): the key was refused, or the credit/quota is used up."""

    def __init__(self, state: str, code: str, message: str) -> None:
        super().__init__(message)
        self.state = state
        self.code = code
        self.message = message


# --- which runs can be resolved, and what they disagree on ---------------------------------------


def resolvable_runs(workspace: Workspace) -> list[str]:
    """Finished screening runs (not resolutions themselves) that have results."""
    found = []
    for manifest in list_runs(workspace):
        if manifest.kind not in ("full", "sample"):
            continue
        if RunStore(run_folder(workspace, manifest.run_id)).results_size() > 0:
            found.append(manifest.run_id)
    return found


def _check_source_runs(workspace: Workspace, run_ids: Sequence[str]) -> None:
    """Validate ``run_ids`` before anything else happens (building a provider, opening a run).

    Checked in this order so the clearest problem is reported first: too few runs, a repeated
    run id (a run cannot disagree with itself), then an unknown or still-empty run.

    Raises:
        ConfigError: E203 for any of the three problems above.
    """
    if len(run_ids) < 2:
        raise ConfigError(
            "A resolution needs at least two run ids",
            code="E203",
            hint="Name two or more --runs, for example --runs run-001,run-002.",
        )
    if len(set(run_ids)) < len(run_ids):
        raise ConfigError(
            "The same run id was named more than once",
            code="E203",
            hint="Each --runs entry must be a different run.",
            details={"runs": list(run_ids)},
        )
    available = resolvable_runs(workspace)
    for run_id in run_ids:
        if run_id not in available:
            raise ConfigError(
                f"The run '{run_id}' is not a screening run with results",
                code="E203",
                hint="Runs that can be resolved: " + (", ".join(available) or "none"),
            )


def disputed_items(workspace: Workspace, run_ids: Sequence[str]) -> list[DisputedItem]:
    """Records every named run decided, but not all the same way (plan: ADR 0025).

    Raises:
        ConfigError: E203 if a run id is unknown or has no results.
    """
    _check_source_runs(workspace, run_ids)
    records = {r.study_uid: r for r in read_records(workspace.records_csv)}
    results_by_run = {
        run_id: find_run(workspace, run_id).last_results() for run_id in run_ids
    }
    decisions_by_run = {
        run_id: {
            uid: row.decision
            for uid, row in results.items()
            if row.status == "ok" and row.decision in DECISIONS
        }
        for run_id, results in results_by_run.items()
    }
    items: list[DisputedItem] = []
    for unstable in unstable_records(decisions_by_run, run_ids):
        record = records.get(unstable.study_uid)
        if record is None:
            continue
        opinions = [
            Opinion(
                run_id=run_id,
                decision=unstable.decisions[run_id],
                reasoning=results_by_run[run_id][unstable.study_uid].reasoning,
                model=results_by_run[run_id][unstable.study_uid].model_returned,
            )
            for run_id in run_ids
            if run_id in unstable.decisions
        ]
        items.append(
            DisputedItem(record.study_uid, record.title, record.abstract, record.keywords, opinions)
        )
    logger.info("%d disputed record(s) between run(s) %s", len(items), ", ".join(run_ids))
    return items


# --- calling a provider and parsing its answer, shared by both methods ---------------------------


async def _call_and_parse(
    provider: LLMProvider,
    system: str,
    user: str,
    llm: Any,
    retry: RetryPolicy,
    max_parse_retries: int,
) -> tuple[Answer, LLMResponse]:
    """One record's call, asked again (same retry rule as screening) if the answer is not valid."""
    extra = ""
    parse_attempts = 0
    while True:
        top_p = llm.top_p if llm.top_p is not None and llm.top_p < 1.0 else None
        request = LLMRequest(
            system=system,
            user=user + extra,
            model=llm.model,
            temperature=llm.temperature,
            top_p=top_p,
            max_output_tokens=llm.max_output_tokens,
            seed=llm.seed,
        )
        response = await call_with_retry(
            functools.partial(provider.complete, request), retry, clock=time.monotonic
        )
        try:
            return parse_answer(response.text), response
        except ParseError as exc:
            parse_attempts += 1
            if parse_attempts > max_parse_retries:
                raise
            reason = exc.details.get("reason", "")
            extra = (
                f"\n\nYour previous answer was not valid ({reason}). "
                "Answer again with one valid JSON object only."
            )


def _error_row(run_id: str, study_uid: str, source_decisions: dict[str, str], *, status: str,
               code: str, message: str) -> ResultRow:  # fmt: skip
    return ResultRow(
        study_uid=study_uid,
        run_id=run_id,
        status=status,
        error_code=code,
        error_message=message,
        schema_version=_SCHEMA_VERSION,
        source_decisions=source_decisions,
    )


# --- adjudicate: one master call per disputed record ----------------------------------------------


async def _adjudicate_item(
    item: DisputedItem,
    config: ProjectConfig,
    provider: LLMProvider,
    run_id: str,
    retry: RetryPolicy,
    max_parse_retries: int,
    price: Price | None,
) -> ResultRow:
    """Settle one record with the master model; never raises for a problem with this one item.

    Raises:
        AuthError: E301, ``QuotaExceeded``: E307 -- these end the whole run, not just this item.
    """
    source_decisions = {o.run_id: o.decision for o in item.opinions}
    system, user = build_adjudication_prompt(config, item)
    try:
        answer, response = await _call_and_parse(
            provider, system, user, config.llm, retry, max_parse_retries
        )
    except AuthError as exc:
        raise _Abort(RunState.FAILED.value, exc.code, exc.user_message) from exc
    except QuotaExceeded as exc:
        raise _Abort(RunState.PAUSED.value, exc.code, exc.user_message) from exc
    except ContextTooLong as exc:
        return _error_row(run_id, item.study_uid, source_decisions, status="too_long",
                           code=exc.code, message=exc.user_message)  # fmt: skip
    except ProviderError as exc:
        return _error_row(run_id, item.study_uid, source_decisions, status="api_error",
                           code=exc.code, message=exc.user_message)  # fmt: skip
    except ParseError as exc:
        reason = str(exc.details.get("reason", exc.user_message))
        return _error_row(run_id, item.study_uid, source_decisions, status="parse_error",
                           code=exc.code, message=reason)  # fmt: skip
    cost = cost_of(price, response.tokens_in, response.tokens_out) if price else None
    return ResultRow(
        study_uid=item.study_uid,
        run_id=run_id,
        status="ok",
        decision=answer.decision,
        derived_decision=answer.derived_decision,
        consistent=answer.consistent,
        reasoning=answer.reasoning,
        model_returned=response.model_returned,
        schema_version=_SCHEMA_VERSION,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        cost=cost,
        latency_s=response.latency_s,
        source_decisions=source_decisions,
        rounds_used=1,
    )


# --- discuss: the original models reconsider, round by round --------------------------------------


@dataclass(frozen=True)
class ParticipantConfig:
    """A source run's provider settings, read from **that run's own** manifest.

    Not the project's current ``llm:`` block, which may have moved on to a different model since
    the run finished -- a discussion must call each participant with the model that actually
    produced its original opinion.
    """

    run_id: str
    provider_name: str
    model: str
    base_url: str = ""
    api_key_env: str = ""
    temperature: float = 0.0
    top_p: float | None = None
    seed: int | None = None
    max_output_tokens: int = 800


def participant_config(workspace: Workspace, run_id: str) -> ParticipantConfig:
    """The provider settings the run ``run_id`` used (from its own ``manifest.json``)."""
    manifest = find_run(workspace, run_id).load_manifest()
    llm = manifest.llm
    return ParticipantConfig(
        run_id=run_id,
        provider_name=str(llm.get("provider", "")),
        model=str(llm.get("model", "")),
        base_url=str(llm.get("base_url") or ""),
        api_key_env=str(llm.get("api_key_env") or ""),
        temperature=float(llm.get("temperature", 0.0) or 0.0),
        top_p=llm.get("top_p"),
        seed=llm.get("seed"),
        max_output_tokens=int(llm.get("max_output_tokens", 800) or 800),
    )


def _tie_break(decisions: Sequence[str], setting: str) -> tuple[str, str]:
    """The decision ``setting`` gives, and the label that was actually applied.

    ``setting == "majority"`` only wins with a **strict** majority: the most common decision must
    have strictly more votes than the runner-up (``ranked[0][1] > ranked[1][1]``), or there is only
    one distinct decision at all (``len(ranked) == 1``). A real tie -- two decisions with the same
    vote count, for example 1 against 1 with two participants, or 2 against 2 with four -- always
    falls through to ``NO_CONSENSUS``/``"no_consensus"``, even when ``setting`` asked for a
    majority: there is no majority to apply in a tie, per the project lead's explicit decision.
    """
    if setting != "no_consensus":
        counts: dict[str, int] = {}
        for decision in decisions:
            counts[decision] = counts.get(decision, 0) + 1
        ranked = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            return ranked[0][0], "majority"
    return "NO_CONSENSUS", "no_consensus"


async def _discuss_item(
    item: DisputedItem,
    config: ProjectConfig,
    run_id: str,
    providers: dict[str, LLMProvider],
    participants: dict[str, ParticipantConfig],
    prices: dict[str, Price | None],
    retry: RetryPolicy,
    max_parse_retries: int,
    max_rounds: int,
    tie_break_setting: str,
) -> ResultRow:
    """Up to ``max_rounds`` reconsideration rounds; never raises for a problem with this item.

    Raises:
        AuthError: E301, ``QuotaExceeded``: E307 -- these end the whole run, not just this item.
    """
    opinions = {o.run_id: o for o in item.opinions}
    source_decisions = {run: o.decision for run, o in opinions.items()}
    history: list[dict[str, Any]] = [
        {"round": 0, "run_id": o.run_id, "decision": o.decision, "reasoning": o.reasoning}
        for o in item.opinions
    ]
    tokens_in = tokens_out = 0
    cost_total: float | None = None
    latency = 0.0
    rounds_used = 0
    for round_number in range(1, max_rounds + 1):
        changed: dict[str, Opinion] = {}
        for run, own in list(opinions.items()):
            others = [o for rid, o in opinions.items() if rid != run]
            system, user = build_discussion_prompt(config, item, own=own, others=others)
            try:
                answer, response = await _call_and_parse(
                    providers[run], system, user, participants[run], retry, max_parse_retries
                )
            except AuthError as exc:
                raise _Abort(RunState.FAILED.value, exc.code, exc.user_message) from exc
            except QuotaExceeded as exc:
                raise _Abort(RunState.PAUSED.value, exc.code, exc.user_message) from exc
            except (ProviderError, ParseError) as exc:
                code = getattr(exc, "code", "")
                history.append({"round": round_number, "run_id": run, "error": code})
                continue
            tokens_in += response.tokens_in
            tokens_out += response.tokens_out
            latency += response.latency_s
            price = prices.get(run)
            if price is not None:
                cost_total = (cost_total or 0.0) + cost_of(
                    price, response.tokens_in, response.tokens_out
                )
            model = response.model_returned or own.model
            changed[run] = Opinion(run, answer.decision, answer.reasoning, model)
            history.append(
                {
                    "round": round_number, "run_id": run,
                    "decision": answer.decision, "reasoning": answer.reasoning,
                }  # fmt: skip
            )
        opinions.update(changed)
        rounds_used = round_number
        if len({o.decision for o in opinions.values()}) == 1:
            final = next(iter(opinions.values())).decision
            texts = (f"{o.label}: {o.reasoning}" for o in opinions.values())
            reasoning = "; ".join(dict.fromkeys(texts))
            return ResultRow(
                study_uid=item.study_uid, run_id=run_id, status="ok", decision=final,
                reasoning=reasoning[:600], schema_version=_SCHEMA_VERSION,
                tokens_in=tokens_in, tokens_out=tokens_out, cost=cost_total, latency_s=latency,
                source_decisions=source_decisions, consensus=True, rounds_used=rounds_used,
                history=history,
            )  # fmt: skip
    final, tie_label = _tie_break([o.decision for o in opinions.values()], tie_break_setting)
    reasoning = f"No consensus after {rounds_used} round(s). "
    reasoning += "; ".join(f"{o.label}: {o.decision}" for o in opinions.values())
    return ResultRow(
        study_uid=item.study_uid, run_id=run_id, status="ok", decision=final,
        reasoning=reasoning[:600], schema_version=_SCHEMA_VERSION,
        tokens_in=tokens_in, tokens_out=tokens_out, cost=cost_total, latency_s=latency,
        source_decisions=source_decisions, consensus=False, rounds_used=rounds_used,
        tie_break=tie_label, history=history,
    )  # fmt: skip


# --- shared orchestration: manifest, resume, pause/stop, concurrency ------------------------------


@dataclass
class ResolutionOptions:
    """What the caller wants.

    Attributes:
        resume: A run id to continue instead of starting a new resolution.
        provider: Adjudicate only: a ready master provider (tests and the demo).
        providers: Discuss only: ``run_id -> provider`` (tests and the demo).
        max_rounds: Discuss only: overrides ``discussion.max_rounds``.
        tie_break: Discuss only: overrides ``discussion.tie_break``.
        progress: Called after every settled record.
    """

    resume: str | None = None
    provider: LLMProvider | None = None
    providers: dict[str, LLMProvider] | None = None
    max_rounds: int | None = None
    tie_break: str | None = None
    progress: Callable[[int, int], None] | None = None


@dataclass
class ResolutionResult:
    """What a call of :func:`adjudicate_project` or :func:`discuss_project` leaves behind."""

    run_id: str
    manifest: Manifest
    resumed: bool = False


def _write_plan(store: RunStore, study_uids: list[str]) -> None:
    atomic_write_text(store.folder / PLAN_NAME, json.dumps({"uids": study_uids}) + "\n")


def _read_plan(store: RunStore) -> list[str]:
    """The ``study_uid``s this resolution was planned for, or ``[]`` if the plan is unreadable.

    A resolution always plans at least one record (an empty disagreement refuses to even start,
    see :func:`_open_resolution`), so an empty result here always means the plan file is missing
    or damaged, never that the plan was legitimately empty. The resume path in
    :func:`_open_resolution` turns that into a clear error instead of silently treating every
    planned record as already done.
    """
    path = store.folder / PLAN_NAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("%s is unreadable (%s); treating the plan as empty", path.name, exc)
        return []
    return [str(u) for u in data.get("uids", [])]


def _changed_keys(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))


def _open_resolution(
    workspace: Workspace,
    method: str,
    run_ids: Sequence[str],
    settings: dict[str, Any],
    llm_snapshot: dict[str, Any],
    items: list[DisputedItem],
    *,
    project_title: str,
    resume: str | None,
) -> tuple[RunStore, Manifest, list[str], bool]:
    """Create a new resolution run, or resume one.

    Returns:
        ``(store, manifest, study_uids still to settle, resumed)``.

    Raises:
        ConfigError: E203 for an unusable resume target or nothing to resolve; E204 if the
            resumed run compared different runs or used different settings.
    """
    run_ids = list(run_ids)
    if resume is not None:
        store = find_run(workspace, resume)
        manifest = store.load_manifest()
        if manifest.kind != method:
            raise ConfigError(
                f"Run '{resume}' is a '{manifest.kind}' run, not '{method}'", code="E203"
            )
        # Compared as sets: --runs run-002,run-001 must resume a run started as run-001,run-002.
        # The order still matters for a *fresh* run (it shapes history/labels), just not for
        # recognising "same source runs" on resume.
        stored_run_ids = set(manifest.input.get("source_run_ids", []))
        if stored_run_ids != set(run_ids):
            raise ConfigError(
                f"Run '{resume}' compared different source runs",
                code="E204",
                details={"changed": ["source_run_ids"]},
            )
        changed = _changed_keys(manifest.run_settings, settings)
        if changed:
            raise ConfigError(
                f"Run '{resume}' used different settings", code="E204", details={"changed": changed}
            )
        if not RunState(manifest.state).resumable:
            raise ConfigError(
                f"Run '{resume}' is {manifest.state} and cannot be resumed", code="E203"
            )
        planned = _read_plan(store)
        if not planned:
            raise StorageError(
                f"The plan of run '{resume}' is missing or damaged",
                code="E404",
                hint="The run folder may be damaged; start a new resolution instead.",
                details={"path": str(store.folder / PLAN_NAME)},
            )
        done = {uid for uid, row in store.last_results().items() if row.is_ok}
        remaining = [uid for uid in planned if uid not in done]
        logger.info(
            "Resuming %s '%s': %d of %d disputed record(s) still to settle",
            method, resume, len(remaining), len(planned),
        )  # fmt: skip
        return store, manifest, remaining, True
    if not items:
        raise ConfigError(
            "These runs decided every record the same way; there is nothing to resolve",
            code="E203",
        )
    run_id = new_run_id(workspace)
    store = RunStore(run_folder(workspace, run_id))
    manifest = Manifest(
        run_id=run_id,
        kind=method,
        project_title=project_title,
        llm=llm_snapshot,
        run_settings=settings,
        input={"source_run_ids": run_ids, "disputed": len(items)},
        counts={"total": len(items)},
    )
    store.create(manifest)
    _write_plan(store, [i.study_uid for i in items])
    logger.info(
        "Started %s run '%s': %d disputed record(s) between %s",
        method, run_id, len(items), ", ".join(run_ids),
    )  # fmt: skip
    return store, manifest, [i.study_uid for i in items], False


async def _process_with_control(
    store: RunStore, items: list[Any], concurrency: int, handle: Callable[[Any], Any]
) -> tuple[str, dict[str, str]]:
    """Run ``handle`` over ``items`` with bounded concurrency, checking ``control.json`` between
    chunks.

    Returns:
        ``(state, last_error)``: the final :class:`RunState` value (``completed``, ``paused``,
        ``interrupted`` or ``failed``) and, for ``paused``/``failed``, the problem that ended the
        run (``{"code": ..., "message": ...}``), else ``{}``.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def bound(item: Any) -> None:
        async with semaphore:
            await handle(item)

    # control.json is only checked between chunks, not after every item: a resolution is usually
    # a small, bounded set of disputed records, so this coarser granularity (compared to the
    # screening engine's own batches) is a deliberate simplification, not an oversight (ADR 0025).
    chunk_size = max(1, concurrency * 2)
    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        # return_exceptions=True: without it, the first _Abort would make gather() return
        # immediately while its siblings in the same chunk keep running un-awaited in the
        # background (asyncio's documented behaviour) -- in-flight LLM calls that already cost
        # money would be silently dropped with no row and no log line. Waiting for every sibling
        # to finish first means each one still gets to append its ResultRow (ok or error) before
        # the abort is reported.
        results = await asyncio.gather(*(bound(item) for item in chunk), return_exceptions=True)
        abort = next((r for r in results if isinstance(r, _Abort)), None)
        if abort is not None:
            logger.warning(
                "Resolution aborted (%s): %s %s", abort.state, abort.code, abort.message
            )
            return abort.state, {"code": abort.code, "message": abort.message}
        other = next((r for r in results if isinstance(r, BaseException)), None)
        if other is not None:
            raise other
        command = store.read_control()
        if command in ("pause", "stop"):
            store.clear_control()
            done_so_far = start + len(chunk)
            logger.info(
                "Resolution %s by request after %d of %d record(s)",
                "stopped" if command == "stop" else "paused", done_so_far, len(items),
            )  # fmt: skip
            state = RunState.INTERRUPTED.value if command == "stop" else RunState.PAUSED.value
            return state, {}
    return RunState.COMPLETED.value, {}


def _finish(
    store: RunStore, manifest: Manifest, state: str, last_error: dict[str, str] | None = None
) -> Manifest:
    manifest.state = state
    if last_error:
        manifest.last_error = last_error
    if state == RunState.COMPLETED.value:
        manifest.finished_at = now_iso()
    results = store.last_results()
    manifest.counts["done"] = len(results)
    manifest.counts["ok"] = sum(1 for row in results.values() if row.is_ok)
    store.save_manifest(manifest)
    logger.info(
        "%s '%s' finished in state %s: %d of %d record(s) ok",
        manifest.kind, manifest.run_id, state, manifest.counts["ok"], manifest.counts["done"],
    )  # fmt: skip
    return manifest


async def _adjudicate_async(
    workspace: Workspace, run_ids: Sequence[str], options: ResolutionOptions
) -> ResolutionResult:
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        config = load_project_config(workspace.project_yaml)
        _check_source_runs(workspace, run_ids)
        items_all = disputed_items(workspace, run_ids) if options.resume is None else []
        provider = options.provider or build_provider(
            config.llm.provider,
            config.llm.model,
            base_url=config.llm.base_url,
            api_key_env=config.llm.api_key_env,
            context_tokens=config.llm.context_tokens,
        )
        llm_snapshot = {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "base_url": config.llm.base_url or "",
            "temperature": config.llm.temperature,
        }
        store, manifest, remaining, resumed = _open_resolution(
            workspace, "adjudicate", run_ids, {}, llm_snapshot, items_all,
            project_title=config.project.title, resume=options.resume,
        )  # fmt: skip
        # On a fresh start, items_all is already the full disputed set. On resume, it was never
        # computed (the records only need to be the same, not recomputed), so recompute it here
        # to turn "which study_uids are left" (remaining, from the plan file) back into the
        # DisputedItem objects (title/abstract/opinions) _adjudicate_item needs.
        by_uid = {i.study_uid: i for i in (items_all or disputed_items(workspace, run_ids))}
        items = [by_uid[uid] for uid in remaining if uid in by_uid]
        manifest.state = RunState.RUNNING.value
        manifest.started_at = manifest.started_at or now_iso()
        store.save_manifest(manifest)
        retry = RetryPolicy(
            max_retries=config.limits.max_retries,
            base_delay_s=config.run.retry_base_delay_s,
            max_delay_s=config.run.retry_max_delay_s,
            max_retry_time_s=config.run.max_retry_time_s,
        )
        price, _ = find_price(workspace, config.llm.provider, config.llm.model)
        total = len(_read_plan(store))
        settled = 0

        async def handle(item: DisputedItem) -> None:
            nonlocal settled
            row = await _adjudicate_item(
                item, config, provider, manifest.run_id, retry,
                config.limits.max_parse_retries, price,
            )  # fmt: skip
            store.append_result(row)
            settled += 1
            if options.progress is not None:
                options.progress(settled, total)

        state, last_error = await _process_with_control(
            store, items, config.limits.max_concurrency, handle
        )
        manifest = _finish(store, manifest, state, last_error)
        return ResolutionResult(run_id=manifest.run_id, manifest=manifest, resumed=resumed)


async def _discuss_async(
    workspace: Workspace, run_ids: Sequence[str], options: ResolutionOptions
) -> ResolutionResult:
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        config = load_project_config(workspace.project_yaml)
        # Validate the run ids, the round count and the tie-break rule *before* touching any
        # participant's manifest or building a provider: a bad --runs value should never fail
        # halfway through (for example after a key for one participant was already rejected).
        _check_source_runs(workspace, run_ids)
        # "is not None", not "or": 0 (rejected below) or "" must stay the caller's explicit
        # choice, not silently fall back to the configured default the way `or` would.
        max_rounds = (
            options.max_rounds if options.max_rounds is not None else config.discussion.max_rounds
        )
        if max_rounds < 1:
            raise ConfigError(
                "discussion.max_rounds must be at least 1",
                code="E203",
                hint="Set discussion.max_rounds in project.yaml, or pass --max-rounds >= 1.",
            )
        tie_break_setting = (
            options.tie_break if options.tie_break is not None else config.discussion.tie_break
        )
        if tie_break_setting not in ("majority", "no_consensus"):
            raise ConfigError(
                f"Unknown discussion.tie_break '{tie_break_setting}'",
                code="E203",
                hint="Use 'majority' or 'no_consensus'.",
            )
        participants = {run_id: participant_config(workspace, run_id) for run_id in run_ids}
        providers = options.providers or {
            run_id: build_provider(
                p.provider_name, p.model, base_url=p.base_url or None, api_key_env=p.api_key_env,
                source=f"used by run {run_id}",
            )  # fmt: skip
            for run_id, p in participants.items()
        }
        prices = {
            run_id: find_price(workspace, p.provider_name, p.model)[0]
            for run_id, p in participants.items()
        }
        items_all = disputed_items(workspace, run_ids) if options.resume is None else []
        llm_snapshot = {
            run_id: {"provider": p.provider_name, "model": p.model}
            for run_id, p in participants.items()
        }
        settings = {"max_rounds": max_rounds, "tie_break": tie_break_setting}
        store, manifest, remaining, resumed = _open_resolution(
            workspace, "discuss", run_ids, settings, llm_snapshot, items_all,
            project_title=config.project.title, resume=options.resume,
        )  # fmt: skip
        # See the matching comment in _adjudicate_async: recomputed on resume only.
        by_uid = {i.study_uid: i for i in (items_all or disputed_items(workspace, run_ids))}
        items = [by_uid[uid] for uid in remaining if uid in by_uid]
        manifest.state = RunState.RUNNING.value
        manifest.started_at = manifest.started_at or now_iso()
        store.save_manifest(manifest)
        retry = RetryPolicy(
            max_retries=config.limits.max_retries,
            base_delay_s=config.run.retry_base_delay_s,
            max_delay_s=config.run.retry_max_delay_s,
            max_retry_time_s=config.run.max_retry_time_s,
        )
        total = len(_read_plan(store))
        settled = 0

        async def handle(item: DisputedItem) -> None:
            nonlocal settled
            row = await _discuss_item(
                item, config, manifest.run_id, providers, participants, prices, retry,
                config.limits.max_parse_retries, max_rounds, tie_break_setting,
            )  # fmt: skip
            store.append_result(row)
            settled += 1
            if options.progress is not None:
                options.progress(settled, total)

        state, last_error = await _process_with_control(
            store, items, config.limits.max_concurrency, handle
        )
        manifest = _finish(store, manifest, state, last_error)
        return ResolutionResult(run_id=manifest.run_id, manifest=manifest, resumed=resumed)


def adjudicate_project(
    workspace: Workspace, run_ids: Sequence[str], options: ResolutionOptions | None = None
) -> ResolutionResult:
    """Settle every disagreement between ``run_ids`` with a single master call per record.

    Raises:
        ConfigError: E203/E204 for unusable runs, settings or a resume target.
        AuthError: E301 before anything is sent, if the master's key is missing.
    """
    return asyncio.run(_adjudicate_async(workspace, run_ids, options or ResolutionOptions()))


def discuss_project(
    workspace: Workspace, run_ids: Sequence[str], options: ResolutionOptions | None = None
) -> ResolutionResult:
    """Settle every disagreement between ``run_ids`` by letting their own models reconsider.

    Raises:
        ConfigError: E203/E204 for unusable runs, settings or a resume target.
        AuthError: E301 before anything is sent, if a participant's key is missing.
    """
    return asyncio.run(_discuss_async(workspace, run_ids, options or ResolutionOptions()))
