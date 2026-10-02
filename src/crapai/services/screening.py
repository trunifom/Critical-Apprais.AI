"""Screening service: plan a run, start it, resume it, read its state (plan chapters 8.6, 11, 12.1).

This is the one place where everything meets: the project (records, settings, criteria), the prompt
builder, the provider, the engine and the run files. The command line and the interface both call
:func:`screen_project`; neither contains screening logic.

**Safety rules implemented here**

* The whole run holds the project lock, so no other command can change the records or settings
  while it works; a crashed run leaves a lock that ``crapai unlock`` can remove.
* A run is bound to a **fingerprint** of everything that shapes the answers (model, sampling,
  prompt text, answer format, criteria, objectives). ``--resume`` with a different fingerprint is
  refused with E204: results of different settings are never mixed in one run.
* The list of records of a run is written to ``plan.json`` first, so a resumed run (or a run that
  was started as a sample) continues with exactly the same records.
* A record with an ``ok`` result is never sent again. Records that failed are tried again on
  resume (switchable with ``run.retry_failed_on_resume``).
* Ctrl+C asks the engine to finish the records in flight and stop with state ``interrupted``; a
  second Ctrl+C stops at once (the results file stays valid).
* The key comes from the environment variable named in ``llm.api_key_env`` and is never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import random
import signal
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from crapai import __version__
from crapai.config.loader import load_project_config
from crapai.config.models import ProjectConfig
from crapai.enums import ScreeningPhase
from crapai.errors import AuthError, ConfigError, ImportFailed, SaraError
from crapai.io.import_log import sha256_file
from crapai.io.readers.pdf_zip import extract_one
from crapai.io.records_store import Record, read_records
from crapai.llm.base import LLMProvider
from crapai.llm.mock_provider import SCENARIOS, MockProvider
from crapai.llm.openai_provider import OpenAICompatibleProvider
from crapai.prisma import events as ev
from crapai.project.atomic import atomic_write_text
from crapai.project.workspace import Workspace
from crapai.prompts.builder import PromptBuilder, builder_for, hash_text
from crapai.screening.engine import (
    EngineSettings,
    PlanItem,
    Progress,
    RunSummary,
    ScreeningEngine,
)
from crapai.screening.store import Manifest, RunState, RunStore
from crapai.services.cost import find_price
from crapai.services.events import append_events

logger = logging.getLogger(__name__)

PLAN_NAME = "plan.json"


@dataclass
class RunOptions:
    """What the caller wants.

    Attributes:
        sample: Screen only this many records drawn at random (a trial run; not part of PRISMA).
        resume: A run id, or ``"latest"``, to continue instead of starting a new run.
        provider: A ready provider (tests and the demo); normally created from the settings.
        progress: Called with a :class:`~crapai.screening.engine.Progress` while the run works.
        retry_failed: Overrides ``run.retry_failed_on_resume`` for a resume.
        install_signal_handler: Handle Ctrl+C (only possible in the main thread).
    """

    sample: int | None = None
    resume: str | None = None
    provider: LLMProvider | None = None
    progress: Callable[[Progress], None] | None = None
    retry_failed: bool | None = None
    install_signal_handler: bool = True


@dataclass
class RunResult:
    """What a call of :func:`screen_project` leaves behind."""

    run_id: str
    summary: RunSummary
    manifest: Manifest
    folder: Path
    resumed: bool = False
    warnings: list[str] = field(default_factory=list)


# --- planning ---------------------------------------------------------------------------------


def _fulltext_anchors(records: list[Record]) -> list[Record]:
    """Records (not themselves a full-text attachment) that have >=1 usable attachment.

    "Usable" means a matched row (``fulltext_of`` points at it) with no quality problem
    (``exclusion_reason`` empty -- a matched but unreadable PDF, ``NO_TEXT``/``ENCRYPTED``/
    ``IMPORT_ERROR``, does not count). This is the full-text-mode counterpart of
    :func:`eligible_records`'s abstract check: a record with no usable full text is left out of
    the plan entirely, the same way a record with no abstract is today, rather than sent with
    nothing to screen.
    """
    usable_targets = {r.fulltext_of for r in records if r.fulltext_of and not r.exclusion_reason}
    return [
        r
        for r in records
        if not r.fulltext_of and not r.exclusion_reason and r.study_uid in usable_targets
    ]


def eligible_records(records: list[Record], config: ProjectConfig) -> list[Record]:
    """Records that go to the model: no exclusion reason (and an abstract, unless title-only).

    In full-text mode (``project.mode``, ADR 0026) this instead returns :func:`_fulltext_anchors`.
    """
    if config.project.mode == "fulltext":
        return _fulltext_anchors(records)
    title_only = config.screening.include_title_only
    return [r for r in records if not r.exclusion_reason and (r.abstract.strip() or title_only)]


def _fulltext_lookup(records: list[Record], workspace: Workspace) -> Callable[[Record], str]:
    """A function from an anchor record to its full text, re-read from its ZIP each time.

    The text itself is never stored in ``records.csv`` (too large for a CSV cell); only
    ``source_file``/``zip_member`` are, so every plan (a fresh run, or a ``--resume``) re-extracts
    it from the ZIP kept in ``sources/``. One record's PDF is a few hundred KB to a few MB, so
    re-opening the ZIP once per record (no caching across records) is simple and fast enough for
    the PDF counts a systematic review has (tens to low hundreds), even though several records
    from the same ZIP mean it is opened more than once.
    """
    attachment_by_anchor = {
        r.fulltext_of: r for r in records if r.fulltext_of and not r.exclusion_reason
    }

    def resolve(anchor: Record) -> str:
        attachment = attachment_by_anchor.get(anchor.study_uid)
        if attachment is None:
            return ""
        with zipfile.ZipFile(workspace.sources_dir / attachment.source_file) as archive:
            data = archive.read(attachment.zip_member)
        return extract_one(attachment.zip_member, data).text

    return resolve


def _plan_item(
    record: Record, config: ProjectConfig, *, fulltext_of: Callable[[Record], str] | None = None
) -> PlanItem:
    keywords = record.keywords if config.screening.include_keywords_in_prompt else ""
    fulltext = fulltext_of(record) if fulltext_of is not None else ""
    return PlanItem(record.study_uid, record.title, record.abstract, keywords, fulltext)


def plan_items(
    records: list[Record],
    config: ProjectConfig,
    *,
    sample: int | None = None,
    workspace: Workspace | None = None,
) -> list[PlanItem]:
    """The records of a run as plan items; with ``sample`` a reproducible random draw.

    The draw uses ``run.sample_seed`` and keeps the original order of the drawn records.
    ``workspace`` is required in full-text mode (to re-read a ZIP from ``sources/``); it is
    unused in abstract mode.
    """
    chosen = eligible_records(records, config)
    if sample is not None and 0 < sample < len(chosen):
        drawn = random.Random(config.run.sample_seed).sample(range(len(chosen)), sample)
        chosen = [chosen[i] for i in sorted(drawn)]
    fulltext_of = None
    if config.project.mode == "fulltext":
        assert workspace is not None, "full-text mode needs a workspace to re-read the ZIP"
        fulltext_of = _fulltext_lookup(records, workspace)
    return [_plan_item(r, config, fulltext_of=fulltext_of) for r in chosen]


def settings_from_config(config: ProjectConfig, *, keep_raw: bool | None = None) -> EngineSettings:
    """The engine's settings from the project configuration."""
    llm, limits, run = config.llm, config.limits, config.run
    return EngineSettings(
        model=llm.model,
        temperature=llm.temperature,
        top_p=llm.top_p if llm.top_p < 1.0 else None,
        seed=llm.seed,
        max_output_tokens=llm.max_output_tokens,
        expected_output_tokens=llm.expected_output_tokens,
        timeout_s=llm.timeout_s,
        concurrency=limits.max_concurrency,
        rpm=limits.rpm,
        tpm=limits.tpm,
        max_retries=limits.max_retries,
        max_parse_retries=limits.max_parse_retries,
        retry_base_delay_s=run.retry_base_delay_s,
        retry_max_delay_s=run.retry_max_delay_s,
        max_retry_time_s=run.max_retry_time_s,
        max_cost=limits.max_cost,
        batch_size=run.batch_size,
        max_batch_error_rate=run.max_batch_error_rate,
        max_consecutive_errors=run.max_consecutive_errors,
        checkpoint_seconds=run.checkpoint_seconds,
        heartbeat_seconds=run.heartbeat_seconds,
        stop_grace_seconds=run.stop_grace_seconds,
        keep_raw=config.output.keep_raw_responses if keep_raw is None else keep_raw,
        currency=limits.currency,
        mode=config.project.mode,
        fulltext_strategy=config.screening.fulltext.strategy,
    )


def fingerprint_parts(config: ProjectConfig, builder: PromptBuilder) -> dict[str, Any]:
    """Everything that shapes the answers of a run; two runs are comparable only if equal."""
    llm = config.llm
    return {
        "provider": llm.provider,
        "model": llm.model,
        "base_url": llm.base_url or "",
        "temperature": llm.temperature,
        "top_p": llm.top_p,
        "seed": llm.seed,
        "max_output_tokens": llm.max_output_tokens,
        "output_format": builder.output_format,
        "variant": builder.variant.id,
        "variant_version": builder.variant.version,
        "prompt_hash": builder.prefix_hash,
        "schema_version": builder.schema_version,
        "reasoning_language": config.screening.reasoning_language,
        "include_keywords_in_prompt": config.screening.include_keywords_in_prompt,
        # Only meaningful in full-text mode (ADR 0026), but harmless to always include: a changed
        # strategy would otherwise change how much of the text a resumed run sees, unnoticed.
        "fulltext_strategy": config.screening.fulltext.strategy,
    }


def fingerprint(parts: dict[str, Any]) -> str:
    """The hash of :func:`fingerprint_parts`."""
    return hash_text(json.dumps(parts, sort_keys=True, ensure_ascii=False))


def build_provider(
    provider_name: str,
    model: str,
    *,
    base_url: str | None = None,
    api_key_env: str = "",
    context_tokens: int | None = None,
    environ: dict[str, str] | None = None,
    source: str = "",
) -> LLMProvider:
    """Create a provider from its plain fields (also used to recreate an earlier run's provider).

    Args:
        source: What to name in the error if the key is missing (default: nothing extra).

    Raises:
        AuthError: E301 if the environment variable named by ``api_key_env`` is empty.
        ConfigError: E203 for a provider that is not implemented yet or an unknown mock scenario.
        ProviderError: E305 if the ``openai`` package is missing.
    """
    if provider_name == "mock":
        scenario = model if model in SCENARIOS else "S1"
        return MockProvider(scenario)
    if provider_name == "anthropic":
        raise ConfigError(
            "The provider 'anthropic' is not available in this version",
            code="E203",
            hint="Use openai or openai_compatible (for example SwissGPT).",
        )
    key = (environ if environ is not None else os.environ).get(api_key_env, "").strip()
    if not key:
        hint = f"Set {api_key_env} to the key"
        hint += f" {source}" if source else ""
        hint += " (it is never stored in the project)."
        raise AuthError(
            f"The environment variable {api_key_env} is not set", code="E301", hint=hint
        )
    return OpenAICompatibleProvider(
        key,
        base_url=base_url,
        name="openai" if provider_name == "openai" else "openai_compatible",
        context_tokens=context_tokens,
    )


def make_provider(config: ProjectConfig, environ: dict[str, str] | None = None) -> LLMProvider:
    """Create the provider named in the settings.

    Raises:
        AuthError: E301 if the environment variable named in ``llm.api_key_env`` is empty.
        ConfigError: E203 for a provider that is not implemented yet or an unknown mock scenario.
        ProviderError: E305 if the ``openai`` package is missing.
    """
    llm = config.llm
    return build_provider(
        llm.provider,
        llm.model,
        base_url=llm.base_url,
        api_key_env=llm.api_key_env,
        context_tokens=llm.context_tokens,
        environ=environ,
    )


# --- run folders ------------------------------------------------------------------------------


def run_folder(workspace: Workspace, run_id: str) -> Path:
    """``runs/<run_id>/``."""
    return workspace.runs_dir / run_id


def list_runs(workspace: Workspace) -> list[Manifest]:
    """The manifests of all runs, oldest first (a run with a damaged manifest is skipped)."""
    manifests: list[Manifest] = []
    if not workspace.runs_dir.is_dir():
        return manifests
    for folder in sorted(p for p in workspace.runs_dir.iterdir() if p.is_dir()):
        try:
            manifests.append(RunStore(folder).load_manifest())
        except SaraError as exc:
            logger.warning("Run folder %s skipped: %s", folder.name, exc.code)
    return manifests


def new_run_id(workspace: Workspace, now: datetime | None = None) -> str:
    """``2026-10-01T14-05_run-003``: time plus the next free number."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H-%M")
    existing = len(list(workspace.runs_dir.glob("*_run-*"))) if workspace.runs_dir.is_dir() else 0
    return f"{stamp}_run-{existing + 1:03d}"


def find_run(workspace: Workspace, which: str) -> RunStore:
    """The store of run ``which`` (an id, or ``latest`` for the newest resumable or last run).

    Raises:
        ConfigError: E203 if there is no such run.
    """
    runs = list_runs(workspace)
    if which == "latest":
        resumable = [m for m in runs if RunState(m.state).resumable]
        pool = resumable or runs
        if not pool:
            raise ConfigError(
                "There is no run to resume", code="E203", hint="Start one with 'crapai screen'."
            )
        return RunStore(run_folder(workspace, pool[-1].run_id))
    if not any(m.run_id == which for m in runs):
        raise ConfigError(
            f"There is no run '{which}'",
            code="E203",
            hint="Runs: " + (", ".join(m.run_id for m in runs) or "none yet"),
        )
    return RunStore(run_folder(workspace, which))


def request_control(workspace: Workspace, run_id: str, command: str) -> None:
    """Ask a running run to ``pause`` or ``stop`` (also from another process).

    Raises:
        ConfigError: E203 for an unknown command or run.
    """
    if command not in ("pause", "stop"):
        raise ConfigError(
            f"Unknown command '{command}'", code="E203", hint="Use 'pause' or 'stop'."
        )
    find_run(workspace, run_id).write_control(command)


# --- the run ----------------------------------------------------------------------------------


def _software() -> dict[str, str]:
    return {
        "name": "crapai",
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _new_manifest(
    run_id: str,
    config: ProjectConfig,
    builder: PromptBuilder,
    settings: EngineSettings,
    *,
    kind: str,
    sample: int | None,
    planned: int,
    records_hash: str,
) -> Manifest:
    parts = fingerprint_parts(config, builder)
    return Manifest(
        run_id=run_id,
        kind=kind,
        software=_software(),
        project_title=config.project.title,
        criteria_hash=hash_text(json.dumps(config.criteria.model_dump(), sort_keys=True)),
        objectives_hash=hash_text(json.dumps(config.objectives)),
        config_hash=fingerprint(parts),
        prompt={
            "variant": builder.variant.id,
            "variant_version": builder.variant.version,
            "hash": builder.prefix_hash,
            "schema_version": builder.schema_version,
            "output_format": builder.output_format,
        },
        llm={
            **{
                k: v
                for k, v in parts.items()
                if k in ("provider", "model", "temperature", "top_p", "seed", "max_output_tokens")
            },
            # Not secrets (the key itself never goes into a file): kept so that a later
            # resolution (crapai discuss) can recreate this exact provider for its run id.
            "base_url": config.llm.base_url or "",
            "api_key_env": config.llm.api_key_env,
            "model_returned": [],
            "determinism_guaranteed": False,
        },
        limits={
            "max_concurrency": settings.concurrency,
            "rpm": settings.rpm,
            "tpm": settings.tpm,
            "max_cost": settings.max_cost,
        },
        run_settings={
            "batch_size": settings.batch_size,
            "max_batch_error_rate": settings.max_batch_error_rate,
            "max_consecutive_errors": settings.max_consecutive_errors,
            "fingerprint_parts": parts,
        },
        sample={"size": sample, "seed": config.run.sample_seed} if sample else {},
        input={"records_csv_sha256": records_hash, "planned": planned},
        counts={"total": planned},
    )


def _differences(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))


def _write_plan(store: RunStore, items: list[PlanItem]) -> None:
    atomic_write_text(store.folder / PLAN_NAME, json.dumps({"uids": [i.uid for i in items]}) + "\n")


def _read_plan(store: RunStore) -> list[str]:
    try:
        data = json.loads((store.folder / PLAN_NAME).read_text(encoding="utf-8"))
        uids = data["uids"]
        if not isinstance(uids, list):
            raise TypeError("uids")
        return [str(u) for u in uids]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SaraError(
            f"The plan of run {store.folder.name} cannot be read",
            code="E404",
            hint="Start a new run.",
        ) from exc


def _prisma_event(workspace: Workspace, store: RunStore, manifest: Manifest, mode: str) -> None:
    """Write the aggregated result of a completed full run to the PRISMA event file.

    ``mode`` picks the phase (abstract or full-text, ADR 0026); ``prisma.flow.build_flow`` already
    reads both kinds of event, so no change is needed there.
    """
    rows = [r for r in store.last_results().values() if r.is_ok]
    included = sum(1 for r in rows if r.decision == "INCLUDE")
    excluded = sum(1 for r in rows if r.decision == "EXCLUDE")
    uncertain = sum(1 for r in rows if r.decision == "UNCERTAIN")
    phase = ScreeningPhase.FULLTEXT if mode == "fulltext" else ScreeningPhase.ABSTRACT
    event = ev.screening_done(phase, included, excluded, uncertain, run_id=manifest.run_id)
    try:
        append_events(workspace.events_jsonl, [event])
    except OSError as exc:
        logger.warning(
            "PRISMA event of run %s not written (%s)", manifest.run_id, type(exc).__name__
        )


def screen_project(workspace: Workspace, options: RunOptions | None = None) -> RunResult:
    """Screen the records of a project (new run, or resume), blocking until the run ends.

    Returns:
        A :class:`RunResult`; ``summary.state`` says how the run ended (``completed``,
        ``paused``, ``interrupted`` or ``failed``). Problems of single records are in the
        counts, not exceptions.

    Raises:
        ImportFailed: E102 if no record goes to the model.
        ConfigError: E203/E204 for unusable settings, an unknown run, or a resume whose
            settings changed.
        AuthError: E301 before anything is sent, if the key is missing.
        StorageError: E402 if the project is in use; E401/E403/E404 for file problems.
    """
    options = options or RunOptions()
    workspace = Workspace.open(workspace.root)
    with workspace.lock() as lock:
        config = load_project_config(workspace.project_yaml)
        if config.project.mode == "fulltext" and config.screening.fulltext.strategy == "map_reduce":
            # Chunking and the final call that weighs the collected evidence are not wired into
            # the engine yet (ADR 0026): refuse clearly up front rather than mis-screen silently.
            raise ConfigError(
                "screening.fulltext.strategy 'map_reduce' is not implemented yet",
                code="E203",
                hint="Use 'truncate' or 'sections' for full-text screening.",
            )
        builder = builder_for(config, workspace.prompts_dir)
        settings = settings_from_config(config)
        records = read_records(workspace.records_csv)
        price = find_price(workspace, config.llm.provider, config.llm.model)[0]
        resumed = options.resume is not None
        fulltext_of = (
            _fulltext_lookup(records, workspace) if config.project.mode == "fulltext" else None
        )
        if resumed:
            assert options.resume is not None
            store = find_run(workspace, options.resume)
            manifest = store.load_manifest()
            _check_resumable(manifest, config, builder, store)
            by_uid = {r.study_uid: r for r in records}
            items = [
                _plan_item(by_uid[u], config, fulltext_of=fulltext_of)
                for u in _read_plan(store)
                if u in by_uid
            ]
        else:
            items = plan_items(records, config, sample=options.sample, workspace=workspace)
            if not items:
                raise ImportFailed(
                    "No record goes to the model",
                    code="E102",
                    hint="Import records and run 'crapai check' first.",
                )
            store = RunStore(run_folder(workspace, new_run_id(workspace)))
            manifest = _new_manifest(
                store.folder.name, config, builder, settings,
                kind="sample" if options.sample else "full", sample=options.sample,
                planned=len(items), records_hash=sha256_file(workspace.records_csv),
            )  # fmt: skip
            store.create(manifest)
            _write_plan(store, items)
        provider = options.provider or make_provider(config)
        results = store.last_results()
        retry_failed = (
            config.run.retry_failed_on_resume
            if options.retry_failed is None
            else options.retry_failed
        )
        done = {uid for uid, row in results.items() if row.is_ok or (resumed and not retry_failed)}
        logger.info(
            "%s run %s: %d record(s), %d already done", "Resuming" if resumed else "Starting",
            manifest.run_id, len(items), len(done),
        )  # fmt: skip
        engine = ScreeningEngine(
            provider, builder, settings, store, manifest, price=price,
            progress=options.progress, control=store.read_control, heartbeat=lock.heartbeat,
            already_ok=done,
        )  # fmt: skip
        summary = _run_engine(engine, items, options.install_signal_handler)
        if summary.state == RunState.COMPLETED.value and manifest.kind == "full":
            _prisma_event(workspace, store, manifest, config.project.mode)
        store.clear_control()
    return RunResult(
        manifest.run_id, summary, manifest, store.folder, resumed, list(manifest.warnings)
    )


def _check_resumable(
    manifest: Manifest, config: ProjectConfig, builder: PromptBuilder, store: RunStore
) -> None:
    """Refuse a resume that makes no sense or whose settings changed.

    A *completed* run may be resumed only to repeat its failed records (plan AT2); if every
    record is ``ok`` there is nothing to do. ``canceled`` runs can never be resumed.
    """
    state = RunState(manifest.state)
    if state == RunState.COMPLETED:
        if all(row.is_ok for row in store.last_results().values()):
            raise ConfigError(
                f"The run {manifest.run_id} is completed and has no failed records",
                code="E203",
                hint="Start a new run with 'crapai screen'.",
            )
    elif not state.resumable:
        raise ConfigError(
            f"The run {manifest.run_id} is {state.value} and cannot be resumed",
            code="E203",
            hint="Start a new run with 'crapai screen'.",
        )
    current = fingerprint_parts(config, builder)
    old = manifest.run_settings.get("fingerprint_parts", {})
    if fingerprint(current) != manifest.config_hash:
        changed = _differences(old, current)
        raise ConfigError(
            f"The settings changed since the run started: {', '.join(changed) or 'unknown'}",
            code="E204",
            hint="Start a new run, or restore the earlier settings.",
            details={"changed": changed},
        )


def _run_engine(engine: ScreeningEngine, items: list[PlanItem], handle_sigint: bool) -> RunSummary:
    """Run the engine's event loop; Ctrl+C asks for a clean stop, a second one ends it at once."""

    async def main() -> RunSummary:
        loop = asyncio.get_running_loop()
        previous = None
        install = handle_sigint and threading.current_thread() is threading.main_thread()
        if install:

            def on_sigint(signum: int, frame: Any) -> None:
                if engine._stop is None:  # noqa: SLF001 - the service owns the engine
                    loop.call_soon_threadsafe(
                        engine.request_stop, RunState.INTERRUPTED, "interrupted (Ctrl+C)"
                    )
                else:
                    raise KeyboardInterrupt

            previous = signal.signal(signal.SIGINT, on_sigint)
        try:
            return await engine.run(items)
        finally:
            if install and previous is not None:
                signal.signal(signal.SIGINT, previous)

    return asyncio.run(main())
