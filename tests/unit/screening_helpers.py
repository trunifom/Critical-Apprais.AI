"""Shared set-up for the tests of the screening engine (no network, no key)."""

from __future__ import annotations

from pathlib import Path

from crapai.config.models import ProjectConfig
from crapai.llm.mock_provider import MockProvider
from crapai.prompts.builder import builder_for
from crapai.screening.engine import EngineSettings, PlanItem, ScreeningEngine
from crapai.screening.store import Manifest, RunStore


def make_config(**screening: object) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project": {"title": "Exercise review"},
            "objectives": ["Does exercise help?"],
            "criteria": {
                "framework": "PICOS",
                "inclusion": {"Population": "adults"},
                "exclusion": {"Study Design": "case reports"},
            },
            "screening": dict(screening),
        }
    )


def make_items(count: int, *, marker: dict[int, str] | None = None) -> list[PlanItem]:
    marker = marker or {}
    return [
        PlanItem(
            uid=f"u{number:05d}",
            title=f"Study {number} {marker.get(number, '')}".strip(),
            abstract=f"Abstract: adults number {number} were enrolled in a trial. {marker.get(number, '')}",
        )
        for number in range(count)
    ]


def fast_settings(**changes: object) -> EngineSettings:
    """Settings without real waiting: tiny delays, big limits."""
    values: dict[str, object] = {
        "model": "mock-model",
        "concurrency": 3,
        "rpm": 10**6,
        "tpm": 10**9,
        "max_retries": 2,
        "retry_base_delay_s": 0.001,
        "retry_max_delay_s": 0.01,
        "max_retry_time_s": 5.0,
        "batch_size": 10,
        "max_consecutive_errors": 0,
        "max_batch_error_rate": 1.0,
        "checkpoint_seconds": 0.0,
        "heartbeat_seconds": 1000.0,
        "stop_grace_seconds": 1.0,
        "timeout_s": 5.0,
    }
    values.update(changes)
    return EngineSettings(**values)  # type: ignore[arg-type]


def make_engine(
    tmp_path: Path,
    provider: MockProvider,
    *,
    settings: EngineSettings | None = None,
    already_ok: set[str] | None = None,
    config: ProjectConfig | None = None,
    **extra: object,
) -> ScreeningEngine:
    config = config or make_config()
    store = RunStore(tmp_path / "runs" / "r1")
    if not store.manifest_path.exists():
        store.create(Manifest(run_id="r1"))
    manifest = store.load_manifest()
    return ScreeningEngine(
        provider,
        builder_for(config),
        settings or fast_settings(),
        store,
        manifest,
        already_ok=already_ok,
        **extra,  # type: ignore[arg-type]
    )
