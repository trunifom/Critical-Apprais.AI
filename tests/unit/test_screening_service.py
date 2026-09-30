"""The screening service: planning, runs, resume, sample, provider factory, events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from crapai.config.loader import load_project_config
from crapai.errors import AuthError, ConfigError, ImportFailed, ProviderError, StorageError
from crapai.io.records_store import read_records
from crapai.llm.mock_provider import MockProvider
from crapai.llm.openai_provider import OpenAICompatibleProvider
from crapai.project.workspace import Workspace
from crapai.screening.store import RunState
from crapai.services import screening as svc
from crapai.services.events import read_events
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5


def ris(tmp_path: Path, count: int) -> Path:
    parts = []
    for n in range(count):
        parts.append(
            "\n".join(
                ["TY  - JOUR", f"TI  - Study number {n} on exercise", f"DO  - 10.1000/s{n}",
                 "PY  - 2020", f"AB  - {ABSTRACT} Record {n}.", "ER  - "]
            )
        )  # fmt: skip
    path = tmp_path / "s.ris"
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def edit_yaml(workspace: Workspace, **sections: dict[str, Any]) -> None:
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    for name, values in sections.items():
        data.setdefault(name, {}).update(values)
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(ris(tmp_path, 25), label="S"))
    edit_yaml(
        workspace,
        llm={"provider": "mock", "model": "S1", "base_url": None},
        run={"batch_size": 10, "retry_base_delay_s": 0.001},
    )
    return workspace


def options(**changes: Any) -> svc.RunOptions:
    return svc.RunOptions(install_signal_handler=False, **changes)


def test_a_full_run_writes_the_run_folder_and_a_prisma_event(project: Workspace) -> None:
    result = svc.screen_project(project, options())
    assert result.summary.state == "completed" and result.summary.by_status == {"ok": 25}
    folder = project.root / "runs" / result.run_id
    assert {p.name for p in folder.iterdir()} >= {"manifest.json", "screening.jsonl", "plan.json"}
    assert not (folder / "control.json").exists()
    manifest = result.manifest
    assert manifest.kind == "full" and manifest.state == "completed" and len(manifest.batches) == 3
    assert manifest.config_hash.startswith("sha256:") and manifest.prompt["hash"].startswith(
        "sha256:"
    )
    events = [e for e in read_events(project.events_jsonl) if e.event_type == "SCREEN_TA"]
    assert len(events) == 1


def test_a_sample_run_draws_reproducibly_and_is_not_a_prisma_event(project: Workspace) -> None:
    first = svc.screen_project(project, options(sample=7))
    second = svc.screen_project(project, options(sample=7))
    assert first.summary.done == 7 and first.manifest.kind == "sample"
    plan_a = json.loads((first.folder / "plan.json").read_text(encoding="utf-8"))
    plan_b = json.loads((second.folder / "plan.json").read_text(encoding="utf-8"))
    assert plan_a == plan_b and first.run_id != second.run_id
    assert not [e for e in read_events(project.events_jsonl) if e.event_type == "SCREEN_TA"]


def test_a_sample_larger_than_the_pool_takes_everything(project: Workspace) -> None:
    assert svc.screen_project(project, options(sample=1000)).summary.done == 25


def test_records_with_an_exclusion_reason_are_not_sent(project: Workspace) -> None:
    from crapai.io.records_store import write_records

    records = read_records(project.records_csv)
    records[0].exclusion_reason = "DUPLICATE"
    write_records(project.records_csv, records)
    assert svc.screen_project(project, options()).summary.done == 24


def test_no_eligible_record_is_e102(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "q", template="demo")
    edit_yaml(workspace, llm={"provider": "mock", "model": "S1", "base_url": None})
    with pytest.raises(ImportFailed) as info:
        svc.screen_project(workspace, options())
    assert info.value.code == "E102"


def test_resume_after_a_pause_finishes_and_never_repeats_a_record(project: Workspace) -> None:
    provider = MockProvider("S14", after=12)
    edit_yaml(project, run={"batch_size": 50})
    first = svc.screen_project(project, options(provider=provider))
    assert first.summary.state == "paused" and first.summary.last_error["code"] == "E307"
    second = svc.screen_project(project, options(resume=first.run_id, provider=MockProvider("S1")))
    assert second.resumed and second.summary.state == "completed" and second.run_id == first.run_id
    lines = [
        json.loads(x)["study_uid"]
        for x in (first.folder / "screening.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) == len(set(lines)) == 25
    assert len([e for e in read_events(project.events_jsonl) if e.event_type == "SCREEN_TA"]) == 1


def test_resume_latest_finds_the_newest_run(project: Workspace) -> None:
    first = svc.screen_project(project, options(provider=MockProvider("S14", after=5)))
    second = svc.screen_project(project, options(resume="latest", provider=MockProvider("S1")))
    assert second.run_id == first.run_id


def test_changed_settings_refuse_the_resume_with_e204_and_name_the_change(
    project: Workspace,
) -> None:
    first = svc.screen_project(project, options(provider=MockProvider("S14", after=5)))
    edit_yaml(project, llm={"temperature": 0.7})
    with pytest.raises(ConfigError) as info:
        svc.screen_project(project, options(resume=first.run_id, provider=MockProvider("S1")))
    assert info.value.code == "E204" and any(
        "temperature" in c for c in info.value.details["changed"]
    )


def test_settings_that_do_not_shape_the_answers_may_change_between_sessions(
    project: Workspace,
) -> None:
    first = svc.screen_project(project, options(provider=MockProvider("S14", after=5)))
    edit_yaml(project, run={"batch_size": 7}, limits={"max_concurrency": 1})
    second = svc.screen_project(project, options(resume=first.run_id, provider=MockProvider("S1")))
    assert second.summary.state == "completed"


def test_a_completed_run_without_failures_has_nothing_to_resume(project: Workspace) -> None:
    done = svc.screen_project(project, options())
    with pytest.raises(ConfigError) as info:
        svc.screen_project(project, options(resume=done.run_id))
    assert info.value.code == "E203"


def test_an_unknown_run_is_an_error_with_the_known_ones_named(project: Workspace) -> None:
    svc.screen_project(project, options(sample=3))
    with pytest.raises(ConfigError):
        svc.screen_project(project, options(resume="nope"))


def test_resume_without_any_run_is_an_error(project: Workspace) -> None:
    with pytest.raises(ConfigError):
        svc.screen_project(project, options(resume="latest"))


def test_failed_records_are_retried_on_resume_unless_switched_off(project: Workspace) -> None:
    edit_yaml(
        project,
        run={"batch_size": 50, "max_batch_error_rate": 1.0, "max_consecutive_errors": 0},
        limits={"max_retries": 0},
    )
    first = svc.screen_project(project, options(provider=MockProvider("S4"), sample=None))
    bad = first.summary.errors
    assert bad > 0
    no_retry = svc.screen_project(
        project, options(resume=first.run_id, provider=MockProvider("S1"), retry_failed=False)
    )
    assert no_retry.summary.done == 0
    again = svc.screen_project(project, options(resume=first.run_id, provider=MockProvider("S1")))
    assert again.summary.done == bad and again.summary.by_status == {"ok": bad}
    final = again.manifest
    assert final.state == "completed" and not any(
        not r.is_ok for r in svc.find_run(project, first.run_id).last_results().values()
    )


def test_the_project_lock_is_held_during_the_run_and_released_after(project: Workspace) -> None:
    seen: list[bool] = []

    class Probe(MockProvider):
        async def complete(self, request):  # type: ignore[no-untyped-def]
            if not seen:
                try:
                    Workspace.open(project.root).lock().__enter__()
                    seen.append(False)
                except StorageError as exc:
                    seen.append(exc.code == "E402")
            return await super().complete(request)

    svc.screen_project(project, options(provider=Probe("S1")))
    assert seen == [True]
    with project.lock():
        pass  # released


def test_progress_is_delivered_to_the_caller(project: Workspace) -> None:
    seen: list[int] = []
    svc.screen_project(project, options(progress=lambda p: seen.append(p.done)))
    assert seen and seen[-1] == 25


def test_run_ids_are_unique_and_listed_oldest_first(project: Workspace) -> None:
    ids = [svc.screen_project(project, options(sample=2)).run_id for _ in range(3)]
    assert len(set(ids)) == 3
    assert [m.run_id for m in svc.list_runs(project)] == sorted(ids)


def test_control_requests_are_written_into_the_run_folder(project: Workspace) -> None:
    result = svc.screen_project(project, options(sample=2))
    svc.request_control(project, result.run_id, "pause")
    assert (result.folder / "control.json").exists()
    with pytest.raises(ConfigError):
        svc.request_control(project, result.run_id, "explode")


# --- provider factory -----------------------------------------------------------------------------


def config_with(project: Workspace, **llm: Any):  # type: ignore[no-untyped-def]
    edit_yaml(project, llm=llm)
    return load_project_config(project.project_yaml)


def test_mock_provider_uses_the_model_as_scenario(project: Workspace) -> None:
    provider = svc.make_provider(config_with(project, provider="mock", model="S3", base_url=None))
    assert isinstance(provider, MockProvider) and provider.scenario == "S3"


def test_a_missing_key_is_e301_and_names_the_variable_but_no_value(project: Workspace) -> None:
    config = config_with(
        project, provider="openai_compatible", base_url="https://x.example/v1", api_key_env="MY_KEY"
    )
    with pytest.raises(AuthError) as info:
        svc.make_provider(config, environ={})
    assert info.value.code == "E301" and "MY_KEY" in str(info.value)
    with pytest.raises(AuthError):
        svc.make_provider(config, environ={"MY_KEY": "   "})


def test_with_a_key_an_openai_provider_is_built_and_the_key_is_not_in_its_repr(
    project: Workspace,
) -> None:
    config = config_with(
        project, provider="openai_compatible", base_url="https://x.example/v1", api_key_env="MY_KEY"
    )
    provider = svc.make_provider(config, environ={"MY_KEY": "sk-secret-value"})
    assert isinstance(provider, OpenAICompatibleProvider)
    assert "sk-secret-value" not in repr(provider) and "sk-secret-value" not in repr(vars(provider))


def test_anthropic_is_not_available_yet(project: Workspace) -> None:
    with pytest.raises(ConfigError) as info:
        svc.make_provider(config_with(project, provider="anthropic", model="x", base_url=None))
    assert info.value.code == "E203"


def test_settings_follow_the_configuration(project: Workspace) -> None:
    edit_yaml(
        project,
        run={"batch_size": 123, "max_consecutive_errors": 9},
        limits={"max_concurrency": 4, "rpm": 77},
    )
    settings = svc.settings_from_config(load_project_config(project.project_yaml))
    assert (
        settings.batch_size,
        settings.max_consecutive_errors,
        settings.concurrency,
        settings.rpm,
    ) == (123, 9, 4, 77)


def test_a_provider_error_outside_the_run_is_not_swallowed(project: Workspace) -> None:
    edit_yaml(
        project,
        llm={
            "provider": "openai_compatible",
            "base_url": "https://x.example/v1",
            "api_key_env": "NO_SUCH_KEY_VAR_XYZ",
        },
    )
    with pytest.raises(AuthError):
        svc.screen_project(project, options())
    # nothing half-made is left behind that blocks the project
    with project.lock():
        pass
    assert isinstance(ProviderError("x", code="E305"), ProviderError)
    assert RunState.FAILED.resumable
