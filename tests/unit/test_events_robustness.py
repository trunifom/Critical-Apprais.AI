"""Event file and pipeline services under failure: unreadable files, repeated checks, gaps."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crapai.cli import app
from crapai.errors import ConfigError, StorageError
from crapai.project.workspace import Workspace
from crapai.services import events as events_service
from crapai.services.dedup import dedup_project
from crapai.services.events import project_flow, read_events, reporting_mode
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import ProjectIssue, check_project
from crapai.services.project import create_project
from crapai.services.validity import validate_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5
runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    rows = "\n".join(
        f"TY  - JOUR\nTI  - Study {i}\nDO  - 10.1000/s{i}\nPY  - 2020\nAB  - {ABSTRACT}\nER  - "
        for i in range(3)
    )
    source = tmp_path / "s.ris"
    source.write_text(rows + "\n", encoding="utf-8")
    import_source(workspace, ImportRequest(source, label="S"))
    return workspace


def kinds(project: Workspace) -> list[str]:
    return [e.kind or e.event_type for e in read_events(project.events_jsonl)]


# --- reading ----------------------------------------------------------------------------------


def test_a_non_utf8_event_file_is_e404_not_a_traceback(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'\xff\xfe{"step":"x"}\n')
    with pytest.raises(StorageError) as info:
        read_events(path)
    assert info.value.code == "E404"


def test_an_unreadable_event_path_is_e404(tmp_path: Path) -> None:
    folder = tmp_path / "events.jsonl"
    folder.mkdir()  # reading a directory as a file raises an OSError
    with pytest.raises(StorageError) as info:
        read_events(folder)
    assert info.value.code == "E404"


def test_an_unknown_reporting_mode_is_e203(project: Workspace) -> None:
    with pytest.raises(ConfigError) as info:
        project_flow(project, "sometimes")
    assert info.value.code == "E203" and "all_before_screening" in info.value.user_message


def test_an_unusable_project_yaml_is_logged_when_the_mode_falls_back(
    project: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    project.project_yaml.write_text("dedup: [broken", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        mode = reporting_mode(project)
    assert mode.value == "all_before_screening" and "project.yaml is unusable" in caplog.text


# --- repeated checks do not bloat the event file -----------------------------------------------


def test_repeating_the_check_does_not_append_unchanged_snapshots(project: Workspace) -> None:
    check_project(project)
    first = project.events_jsonl.read_bytes()
    for _ in range(3):
        check_project(project)
    assert project.events_jsonl.read_bytes() == first


def test_a_changed_snapshot_is_appended_and_later_ones_become_current(
    project: Workspace, tmp_path: Path
) -> None:
    check_project(project)
    before = len(read_events(project.events_jsonl))
    more = tmp_path / "t.ris"
    more.write_text(f"TY  - JOUR\nTI  - Extra\nAB  - {ABSTRACT}\nER  - \n", encoding="utf-8")
    import_source(project, ImportRequest(more, label="T"))
    check_project(project)
    flow, warnings = project_flow(project)
    assert len(read_events(project.events_jsonl)) > before
    assert flow.records_identified_total == 4 and flow.stale_steps == ()
    assert warnings == []  # the prefilter and validity snapshots were rewritten after the import


def test_an_import_after_the_check_is_reported_as_stale(project: Workspace, tmp_path: Path) -> None:
    check_project(project)
    more = tmp_path / "t.ris"
    more.write_text(f"TY  - JOUR\nTI  - Extra\nAB  - {ABSTRACT}\nER  - \n", encoding="utf-8")
    import_source(project, ImportRequest(more, label="T"))
    flow, warnings = project_flow(project)
    assert flow.stale_steps == ("dedup",)
    assert flow.duplicates_removed == 0 and flow.records_to_screen == 4
    assert {w.code for w in warnings} == {"STALE_DEDUP"}


def test_a_dedup_alone_after_the_check_marks_the_other_steps_stale(
    project: Workspace, tmp_path: Path
) -> None:
    same = tmp_path / "dup.ris"
    same.write_text(
        f"TY  - JOUR\nTI  - Study 0\nDO  - 10.1000/s0\nAB  - {ABSTRACT}\nER  - \n",
        encoding="utf-8",
    )
    import_source(project, ImportRequest(same, label="Dup"))
    validate_project(project)  # validity before dedup: the order the pipeline forbids
    dedup_project(project)
    flow, _ = project_flow(project)
    assert "validity" in flow.stale_steps


# --- a failing event write is reported, not hidden ---------------------------------------------


def break_events(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(path: Path, events: object) -> int:
        raise OSError("file held by a sync client")

    monkeypatch.setattr(events_service, "append_events", refuse)


def test_the_dedup_command_warns_and_exits_with_four(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_events(monkeypatch)
    result = runner.invoke(app, ["dedup", str(project.root), "--lang", "en"])
    assert result.exit_code == 4
    assert "PRISMA event file" in result.stderr


def test_the_dedup_json_output_stays_valid_and_carries_the_flag(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_events(monkeypatch)
    result = CliRunner().invoke(app, ["dedup", str(project.root), "--json"])
    assert result.exit_code == 4 and json.loads(result.stdout)["events_written"] is False


def test_the_import_command_warns_and_exits_with_four(
    project: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_events(monkeypatch)
    source = tmp_path / "u.ris"
    source.write_text(f"TY  - JOUR\nTI  - U\nAB  - {ABSTRACT}\nER  - \n", encoding="utf-8")
    result = runner.invoke(app, ["import", str(project.root), str(source), "--lang", "en"])
    assert result.exit_code == 4 and "PRISMA event file" in result.output


def test_the_check_reports_the_gap_as_a_warning(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_events(monkeypatch)
    report = check_project(project)
    assert ProjectIssue.EVENTS_NOT_WRITTEN in report.issues and not report.events_written
    result = runner.invoke(app, ["check", str(project.root), "--lang", "de"])
    assert result.exit_code == 4 and "Lücke" in result.output


def test_a_corrupt_event_file_does_not_stop_the_check(project: Workspace) -> None:
    check_project(project)
    with open(project.events_jsonl, "ab") as handle:
        handle.write(b"garbage\n")
    # the comparison cannot read the file: the snapshot is appended anyway and the work is kept
    report = check_project(project)
    assert report.records == 3


# --- one lock for the whole check --------------------------------------------------------------


def test_the_check_holds_one_lock_for_all_three_steps(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    acquired: list[int] = []
    real = Workspace.lock

    def counting(self: Workspace) -> object:
        acquired.append(1)
        return real(self)

    monkeypatch.setattr(Workspace, "lock", counting)
    check_project(project)
    assert len(acquired) == 1


def test_the_check_refuses_while_another_process_holds_the_project(project: Workspace) -> None:
    holder = project.lock()
    holder.acquire()
    try:
        with pytest.raises(StorageError) as info:
            check_project(project)
        assert info.value.code == "E402"
        assert check_project(project, update=False).records == 3  # read only still works
    finally:
        holder.release()
