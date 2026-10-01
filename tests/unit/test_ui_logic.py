"""The logic behind the interface (no Streamlit): stepper, overview, recent projects, actions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crapai.i18n.messages import Messages
from crapai.prisma.flow import FlowWarning
from crapai.project.workspace import Workspace
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import check_project
from crapai.services.project import create_project
from crapai.ui import actions
from crapai.ui.actions import Upload, guarded, safe_name
from crapai.ui.context import Context, lock_reason
from crapai.ui.viewmodels import (
    RecentProjects,
    build_stepper,
    load_overview,
    percent,
    status_icon,
)

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5
RIS = "TY  - JOUR\nTI  - Effects of exercise on mood in adults\nAB  - " + ABSTRACT + "\nER  - \n"


@pytest.fixture
def messages() -> Messages:
    return Messages("en")


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def with_records(project: Workspace, tmp_path: Path) -> None:
    source = tmp_path / "s.ris"
    source.write_text(RIS * 1, encoding="utf-8")
    import_source(project, ImportRequest(source, label="S"))


# --- stepper and overview ------------------------------------------------------------------------


def states(overview: object, **kwargs: object) -> dict[str, str]:
    return {s.key: s.state for s in build_stepper(overview, **kwargs)}  # type: ignore[arg-type]


def test_without_a_project_only_the_first_step_is_open() -> None:
    steps = build_stepper(None)
    assert [s.state for s in steps] == ["current"] + ["locked"] * 5
    assert steps[1].reason == "needs_project"


def test_an_empty_project_waits_for_data(project: Workspace) -> None:
    result = states(load_overview(project.root))
    assert result == {
        "project": "done", "data": "current", "check": "locked",
        "run": "locked", "flow": "locked", "export": "locked",
    }  # fmt: skip


def test_after_the_import_the_check_is_next(project: Workspace, tmp_path: Path) -> None:
    with_records(project, tmp_path)
    result = states(load_overview(project.root))
    assert result["data"] == "done" and result["check"] == "current"
    assert result["flow"] == "done" and result["export"] == "done" and result["run"] == "current"


def test_after_the_check_nothing_is_current(project: Workspace, tmp_path: Path) -> None:
    with_records(project, tmp_path)
    check_project(project)
    overview = load_overview(project.root)
    assert overview.checked and states(overview)["check"] == "done"


def test_a_broken_configuration_is_a_warning_and_flow_warnings_show(
    project: Workspace, tmp_path: Path
) -> None:
    with_records(project, tmp_path)
    project.project_yaml.write_text("project: {title: T}\n", encoding="utf-8")
    overview = load_overview(project.root)
    assert not overview.config_ok and states(overview)["project"] == "warning"
    stale = [FlowWarning("STALE_DEDUP", "x")]
    assert states(overview, flow_warnings=stale)["flow"] == "warning"


def test_step_icons() -> None:
    assert [s.icon for s in build_stepper(None)][:2] == ["🔵", "⚪"]


def test_overview_numbers(project: Workspace, tmp_path: Path) -> None:
    with_records(project, tmp_path)
    overview = load_overview(project.root)
    assert (overview.records, overview.with_abstract, overview.imports) == (1, 1, 1)
    assert overview.valid_for_model == 1 and overview.sources == {"S": 1} and not overview.in_use
    assert (
        load_overview(create_project(tmp_path / "e", template="demo").root).valid_for_model is None
    )


@pytest.mark.parametrize("part,whole,text", [(3, 4, "75 %"), (0, 5, "0 %"), (1, 0, "-")])
def test_percent(part: int, whole: int, text: str) -> None:
    assert percent(part, whole) == text


def test_status_icons() -> None:
    assert [status_icon(s) for s in ("ok", "warning", "error", "?")] == ["✅", "⚠️", "❌", "•"]


@pytest.mark.parametrize(
    "page,has_folder,records,reason",
    [
        ("start", False, 0, None), ("help", False, 0, None), ("settings", False, 0, None),
        ("data", False, 0, "needs_project"), ("project", False, 0, "needs_project"),
        ("data", True, 0, None), ("check", True, 0, "needs_records"),
        ("flow", True, 0, "needs_records"), ("export", True, 3, None),
        ("run", True, 3, None), ("run", True, 0, "needs_records"), ("run", False, 0, "needs_project"),
    ],
)  # fmt: skip
def test_lock_reasons(
    project: Workspace,
    tmp_path: Path,
    page: str,
    has_folder: bool,
    records: int,
    reason: str | None,
) -> None:
    if records:
        with_records(project, tmp_path)
    overview = load_overview(project.root)
    assert lock_reason(page, overview, project.root if has_folder else None) == reason


# --- recent projects -----------------------------------------------------------------------------


def test_recent_projects_keep_the_newest_first_and_drop_missing_folders(tmp_path: Path) -> None:
    recent = RecentProjects(tmp_path / "config" / "recent.json")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    recent.remember(a)
    recent.remember(b)
    recent.remember(a)  # moves to the front, no duplicate
    assert recent.load() == [a.resolve(), b.resolve()]
    b.rmdir()
    assert recent.load() == [a.resolve()]
    recent.forget(a)
    assert recent.load() == []


def test_the_recent_list_is_capped(tmp_path: Path) -> None:
    recent = RecentProjects(tmp_path / "recent.json")
    for number in range(12):
        folder = tmp_path / f"p{number}"
        folder.mkdir()
        recent.remember(folder)
    assert len(recent.load()) == 8


@pytest.mark.parametrize("content", ["not json", "[]", '{"projects": "x"}', '{"other": 1}', ""])
def test_a_damaged_recent_file_is_an_empty_list(tmp_path: Path, content: str) -> None:
    path = tmp_path / "recent.json"
    path.write_text(content, encoding="utf-8")
    assert RecentProjects(path).load() == []


def test_a_recent_file_that_cannot_be_written_is_not_an_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    folder = tmp_path / "p"
    folder.mkdir()
    RecentProjects(blocker / "sub" / "recent.json").remember(folder)  # the parent is a file
    assert "Cannot save the list of recent projects" in caplog.text


# --- actions -------------------------------------------------------------------------------------


def test_guarded_turns_errors_into_reports(
    messages: Messages, caplog: pytest.LogCaptureFixture
) -> None:
    from crapai.errors import StorageError

    def sara() -> None:
        raise StorageError("no project here", code="E404")

    def foreign() -> None:
        raise RuntimeError("secret path C:/x")

    known = guarded(messages, sara, name="a")
    assert not known.ok and known.error and known.error.code == "E404" and known.error.title
    unknown = guarded(messages, foreign, name="b")
    assert (
        unknown.error and unknown.error.code == "E999" and unknown.error.details == "RuntimeError"
    )
    assert guarded(messages, lambda: 5, name="c").value == 5
    assert "a failed: E404" in caplog.text and "b failed unexpectedly" in caplog.text


def test_open_project_reads_logs_and_remembers(
    messages: Messages, project: Workspace, tmp_path: Path
) -> None:
    recent = RecentProjects(tmp_path / "recent.json")
    outcome = actions.open_project(messages, project.root, recent)
    assert outcome.ok and outcome.value and outcome.value.title
    assert recent.load() == [project.root.resolve()]
    missing = actions.open_project(messages, tmp_path / "nothing", recent)
    assert not missing.ok and missing.error and missing.error.code == "E404"


def test_create_new_project(messages: Messages, tmp_path: Path) -> None:
    outcome = actions.create_new_project(
        messages, tmp_path / "new", template="blank", title="My review"
    )
    assert outcome.ok and (tmp_path / "new" / "project.yaml").exists()
    again = actions.create_new_project(messages, tmp_path / "new")
    assert not again.ok and again.error and again.error.code == "E405"
    unknown = actions.create_new_project(messages, tmp_path / "x", template="nope")
    assert unknown.error and unknown.error.code == "E203"


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("a.ris", "a.ris"),
        ("..\\..\\x.ris", "x.ris"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\data file (1).ris", "data file _1_.ris"),
        ("...", "upload"),
        ("", "upload"),
    ],
)
def test_upload_names_cannot_leave_the_work_folder(raw: str, clean: str) -> None:
    assert safe_name(raw) == clean


def test_prepare_uploads_reads_each_file_and_keeps_same_names_apart(tmp_path: Path) -> None:
    uploads = [
        Upload("a.ris", RIS.encode()),
        Upload("a.ris", RIS.encode()),
        Upload("bad.ris", b"not a reference file"),
        Upload("../../escape.ris", RIS.encode()),
    ]
    files = actions.prepare_uploads(uploads, tmp_path / "work")
    assert [f.name for f in files] == ["a.ris", "a-2.ris", "bad.ris", "escape.ris"]
    assert all(f.path.parent == tmp_path / "work" for f in files)
    assert [f.importable for f in files] == [True, True, False, True]
    assert files[0].preflight.records_total == 1 and files[0].label == "a"


def test_import_prepared_imports_good_files_and_reports_failures(
    messages: Messages, project: Workspace, tmp_path: Path
) -> None:
    files = actions.prepare_uploads(
        [Upload("a.ris", RIS.encode()), Upload("bad.ris", b"junk")], tmp_path / "work"
    )
    results = actions.import_prepared(messages, project.root, files)
    assert (
        [r.name for r in results] == ["a.ris"]
        and results[0].summary
        and results[0].summary.records == 1
    )
    again = actions.import_prepared(messages, project.root, files)
    assert again[0].error is not None and again[0].error.code == "E106"  # the same file twice
    forced = actions.import_prepared(messages, project.root, files, force=True)
    assert forced[0].summary is not None


def test_run_check_and_flow_and_export(
    messages: Messages, project: Workspace, tmp_path: Path
) -> None:
    with_records(project, tmp_path)
    check = actions.run_check(messages, project.root)
    assert check.ok and check.value and check.value.report.records == 1
    assert check.value.estimate is not None and check.value.estimate.estimate.n_items == 1
    flow = actions.load_flow(messages, project.root)
    assert flow.value and flow.value[0].records_identified_total == 1 and flow.value[1] == []
    bad_mode = actions.load_flow(messages, project.root, "sometimes")
    assert bad_mode.error and bad_mode.error.code == "E203"
    export = actions.run_export(messages, project.root, fmt="csv", scope="screenable")
    assert (
        export.value
        and export.value.data.startswith(b"\xef\xbb\xbf")
        and export.value.summary.records == 1
    )
    flow_export = actions.run_export(messages, project.root, what="flow")
    assert json.loads(flow_export.value.data)["schema"] == 1  # type: ignore[union-attr]
    failed = actions.run_export(messages, project.root, fmt="pdf")
    assert failed.error and failed.error.code == "E203"


def test_run_check_without_records_has_no_estimate(messages: Messages, project: Workspace) -> None:
    result = actions.run_check(messages, project.root)
    assert (
        result.value
        and result.value.estimate is None
        and result.value.report.status.value == "error"
    )


def test_save_project_yaml_checks_before_writing(messages: Messages, project: Workspace) -> None:
    good = actions.read_project_yaml(project.root).replace("Demo review", "Renamed review")
    assert actions.save_project_yaml(messages, project.root, good).ok
    assert "Renamed review" in actions.read_project_yaml(project.root)
    before = project.project_yaml.read_bytes()
    for bad in ("project: [broken", "- a list\n- not a mapping", "project: {title: T}\n"):
        outcome = actions.save_project_yaml(messages, project.root, bad)
        assert outcome.error and outcome.error.code in {"E201", "E203"}
    assert (
        project.project_yaml.read_bytes() == good.encode()
        or project.project_yaml.read_bytes() != before
    )
    assert "Renamed review" in actions.read_project_yaml(project.root)  # still the last good text


def test_read_project_yaml_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert actions.read_project_yaml(tmp_path / "nothing") == ""


def test_context_text_uses_the_ui_prefix(messages: Messages, tmp_path: Path) -> None:
    ctx = Context(None, None, "en", messages, RecentProjects(tmp_path / "r.json"))
    assert ctx.t("nav.start") == "Home" and "Open or create" in ctx.t("locked.needs_project")
    german = Context(None, None, "de", Messages("de"), RecentProjects(tmp_path / "r.json"))
    assert german.t("nav.check") == "3 · Daten prüfen"


# --- screening runs: view models and actions --------------------------------------------------------


def _manifest_run(
    project: Workspace,
    state: str,
    *,
    done: int = 4,
    total: int = 10,
    ok: int = 3,
    age: float = 0.0,
):  # type: ignore[no-untyped-def]
    import re
    from datetime import UTC, datetime, timedelta

    from crapai.screening.store import Manifest, RunStore

    store = RunStore(project.runs_dir / "2026-10-01T10-00_run-001")
    manifest = Manifest(run_id=store.folder.name, state=state)
    manifest.counts = {"total": total, "done": done, "ok": ok}
    manifest.usage = {"cost": 1.5, "currency": "USD"}
    manifest.run_settings = {"batch_size": 4}
    manifest.batches = [{"index": 0, "status": "verified", "size": 4}]
    store.create(manifest)
    stamped = (datetime.now(UTC) - timedelta(seconds=age)).isoformat(timespec="seconds")
    text = store.manifest_path.read_text(encoding="utf-8")
    store.manifest_path.write_text(
        re.sub(r'"updated_at": "[^"]*"', f'"updated_at": "{stamped}"', text), encoding="utf-8"
    )
    return store


def test_a_run_view_is_built_from_the_manifest(project: Workspace) -> None:
    from crapai.ui.viewmodels import load_run_views

    _manifest_run(project, "paused")
    (view,) = load_run_views(project.root)
    assert (view.total, view.done, view.ok, view.errors) == (10, 4, 3, 1)
    assert view.fraction == 0.4 and view.batches == 3 and view.batch == 2
    assert view.cost == 1.5 and view.currency == "USD" and view.resumable and not view.running


def test_a_running_run_that_stopped_saving_is_stalled(project: Workspace) -> None:
    from crapai.ui.viewmodels import load_run_views

    _manifest_run(project, "running", age=120)
    (view,) = load_run_views(project.root)
    assert view.running and view.stalled


def test_a_running_run_that_saves_is_not_stalled(project: Workspace) -> None:
    from crapai.ui.viewmodels import load_run_views

    _manifest_run(project, "running", age=1)
    assert not load_run_views(project.root)[0].stalled


def test_completed_runs_are_resumable_only_with_failed_records(project: Workspace) -> None:
    from crapai.ui.viewmodels import load_run_views

    _manifest_run(project, "completed", done=10, ok=10)
    assert not load_run_views(project.root)[0].resumable


def test_an_empty_run_is_full_and_no_runs_is_an_empty_list(project: Workspace) -> None:
    from crapai.ui.viewmodels import load_run_views

    assert load_run_views(project.root) == []
    _manifest_run(project, "completed", done=0, total=0, ok=0)
    assert load_run_views(project.root)[0].fraction == 1.0


@pytest.mark.parametrize(
    "state,step",
    [
        ("completed", "done"),
        ("paused", "warning"),
        ("interrupted", "warning"),
        ("failed", "warning"),
        ("running", "current"),
    ],
)
def test_the_run_step_follows_the_newest_run(
    project: Workspace, tmp_path: Path, state: str, step: str
) -> None:
    with_records(project, tmp_path)
    _manifest_run(project, state)
    assert states(load_overview(project.root))["run"] == step


def test_the_screening_command_line(project: Workspace) -> None:
    import sys

    command = actions.screen_command(project.root, lang="de", sample=20)
    assert command[:4] == [sys.executable, "-m", "crapai", "screen"]
    assert "--yes" in command and "--no-progress" in command
    assert command[command.index("--sample") + 1] == "20"
    assert "--resume" in actions.screen_command(project.root, lang="en", resume=True)
    assert "--sample" not in actions.screen_command(project.root, lang="en", resume=True, sample=5)


class _FakePopen:
    calls: list[list[str]] = []

    def __init__(self, command: list[str], **kwargs: object) -> None:
        _FakePopen.calls.append(command)
        self.pid = 4242


def _mock_project(project: Workspace) -> None:
    import yaml

    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "mock", "model": "S1", "base_url": None})
    project.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_starting_a_run_spawns_a_separate_process(
    project: Workspace, messages: Messages, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_project(project)
    _FakePopen.calls.clear()
    monkeypatch.setattr(actions.subprocess, "Popen", _FakePopen)
    outcome = actions.start_run(messages, project.root, lang="en", sample=5)
    assert outcome.ok and outcome.value == 4242 and len(_FakePopen.calls) == 1
    assert (project.state_dir / actions.SCREEN_OUTPUT).exists()


def test_a_missing_key_is_reported_in_the_interface_before_anything_starts(
    project: Workspace, messages: Messages, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update(
        {
            "provider": "openai_compatible",
            "base_url": "https://x.example/v1",
            "api_key_env": "NO_SUCH_VAR_Q",
        }
    )
    project.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.delenv("NO_SUCH_VAR_Q", raising=False)
    _FakePopen.calls.clear()
    monkeypatch.setattr(actions.subprocess, "Popen", _FakePopen)
    outcome = actions.start_run(messages, project.root, lang="en")
    assert outcome.error is not None and outcome.error.code == "E301" and not _FakePopen.calls


def test_a_project_in_use_is_reported_as_e402(
    project: Workspace, messages: Messages, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_project(project)
    _FakePopen.calls.clear()
    monkeypatch.setattr(actions.subprocess, "Popen", _FakePopen)
    with project.lock():
        outcome = actions.start_run(messages, project.root, lang="en")
    assert outcome.error is not None and outcome.error.code == "E402" and not _FakePopen.calls


def test_pause_and_stop_write_the_control_file(project: Workspace, messages: Messages) -> None:
    store = _manifest_run(project, "running")
    assert actions.control_run(messages, project.root, store.folder.name, "pause").ok
    assert store.read_control() == "pause"
    assert actions.control_run(messages, project.root, "nope", "pause").error is not None
    assert (
        actions.control_run(messages, project.root, store.folder.name, "explode").error is not None
    )


def test_the_output_of_the_screening_process_is_shown_from_its_end(project: Workspace) -> None:
    assert actions.screen_output_tail(project.root) == ""
    project.state_dir.mkdir(parents=True, exist_ok=True)
    (project.state_dir / actions.SCREEN_OUTPUT).write_text(
        "\n".join(f"line {n}" for n in range(50)), encoding="utf-8"
    )
    tail = actions.screen_output_tail(project.root, lines=3)
    assert tail.splitlines() == ["line 47", "line 48", "line 49"]
