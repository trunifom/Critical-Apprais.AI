"""The command line reports every failure cleanly: exit code, log line and JSON error."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import crapai.cli as cli_module
from crapai.cli import app, error_json
from crapai.errors import StorageError
from crapai.i18n.messages import Messages, resolve_language
from crapai.project.lock import ProjectLock
from crapai.project.workspace import Workspace, cloud_sync_hint, cloud_sync_marker
from crapai.services.project import create_project

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


# --- language and texts never crash -----------------------------------------------------------


def test_a_project_yaml_in_another_encoding_does_not_crash_the_language_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANG", "de_CH.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    path = tmp_path / "project.yaml"
    path.write_bytes("project:\n  title: Über\n".encode("cp1252"))
    assert resolve_language(None, path) == "de"  # used to raise UnicodeDecodeError


def test_status_of_a_cp1252_project_yaml_is_a_message_not_a_traceback(project: Workspace) -> None:
    project.project_yaml.write_bytes("project:\n  title: Über\n".encode("cp1252"))
    result = runner.invoke(app, ["status", str(project.root), "--lang", "en"])
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, UnicodeDecodeError)


@pytest.mark.parametrize("template", ["{0", "{a.b}", "{:d}", "{x.y}"])
def test_a_malformed_translation_returns_the_template(template: str) -> None:
    messages = Messages("en")
    messages._i18n.t = lambda key: template  # type: ignore[method-assign]
    assert messages.text("some.key", x="v") == template


# --- errors are logged, printed and (in JSON mode) machine readable ---------------------------


def test_a_sara_error_is_logged_with_code_and_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="crapai.cli"):
        result = runner.invoke(app, ["check", str(tmp_path / "nothing"), "--lang", "en"])
    assert result.exit_code == 1
    assert any("E404" in r.getMessage() for r in caplog.records)


def test_json_mode_prints_an_error_document_on_stdout(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["check", str(tmp_path / "nothing"), "--json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert document["error"]["code"] == "E404" and document["error"]["message"]


def test_an_import_failure_in_json_mode_is_one_document(project: Workspace, tmp_path: Path) -> None:
    good = tmp_path / "a.ris"
    good.write_text("TY  - JOUR\nTI  - Good\nAB  - text\nER  - \n", encoding="utf-8")
    missing = tmp_path / "missing.ris"
    result = CliRunner().invoke(
        app, ["import", str(project.root), str(good), str(missing), "--json"]
    )
    document = json.loads(result.stdout)  # exactly one JSON document
    assert len(document["imported"]) == 1 and document["error"]["code"] == "E101"


def test_error_json_of_an_unexpected_exception_hides_the_message() -> None:
    document = error_json(RuntimeError("secret path C:/x"))
    assert document == {"code": "E999", "message": "RuntimeError", "hint": None}


def test_an_unexpected_error_in_the_estimate_does_not_hide_the_report(
    project: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.ris"
    source.write_text(
        "TY  - JOUR\nTI  - Study\nAB  - " + "A long enough abstract text. " * 5 + "\nER  - \n",
        encoding="utf-8",
    )
    runner.invoke(app, ["import", str(project.root), str(source)])

    def boom(workspace: Workspace) -> Any:
        raise OSError("disk trouble")

    monkeypatch.setattr(cli_module, "estimate_project", boom)
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert "Preflight:" in result.output and "The cost estimate is not available" in result.output
    assert result.exit_code == 4  # a warning, not a traceback


# --- log file ---------------------------------------------------------------------------------


def test_an_unwritable_log_file_does_not_stop_the_command(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("read-only share")

    for handler in list(logging.getLogger("crapai").handlers):
        logging.getLogger("crapai").removeHandler(handler)
    monkeypatch.setattr(cli_module.logging.handlers, "RotatingFileHandler", refuse)
    result = runner.invoke(app, ["dedup", str(project.root), "--lang", "en"])
    assert result.exit_code == 0 and "cannot write the log file" in result.stderr


def test_init_writes_the_creation_to_the_log(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "new"), "--lang", "en"])
    assert result.exit_code == 0
    for handler in logging.getLogger("crapai").handlers:
        handler.flush()
    log = (tmp_path / "new" / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "Created project new from template" in log


# --- synchronised folders ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,marker",
    [
        ("C:/Users/me/Dropbox/review", "dropbox"),
        ("C:/Users/me/OneDrive - Company/review", "onedrive"),
        ("C:/Users/me/OneDrive/review", "onedrive"),
        ("/home/me/SharePoint/review", "sharepoint"),
    ],
)
def test_real_sync_folders_are_recognised(path: str, marker: str) -> None:
    assert cloud_sync_marker(Path(path)) == marker
    assert marker in (cloud_sync_hint(Path(path)) or "")


@pytest.mark.parametrize("path", ["C:/Users/dropbox-fan-club/review", "C:/Users/mydropboxer/x"])
def test_a_name_that_merely_contains_the_word_is_no_sync_folder(path: str) -> None:
    assert cloud_sync_marker(Path(path)) is None


def test_init_warns_on_stderr_in_a_sync_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "cloud_sync_marker", lambda path: "dropbox")
    result = CliRunner().invoke(app, ["init", str(tmp_path / "n"), "--lang", "en"])
    assert result.exit_code == 0
    assert "synchronised location (dropbox)" in result.stderr


# --- crapai unlock ----------------------------------------------------------------------------


def stale_lock(project: Workspace) -> None:
    """Write the lock of a process that is long gone."""
    old = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    lock = ProjectLock(project.lock_file, pid=2**22 + 12345, now=lambda: old)
    lock.acquire()


def test_unlock_without_a_lock(project: Workspace) -> None:
    result = runner.invoke(app, ["unlock", str(project.root), "--lang", "en"])
    assert result.exit_code == 0 and "not in use" in result.output


def test_unlock_removes_a_stale_lock_with_yes(project: Workspace) -> None:
    stale_lock(project)
    blocked = runner.invoke(app, ["dedup", str(project.root), "--lang", "en"])
    assert blocked.exit_code == 2 and "E402" in blocked.output
    result = runner.invoke(app, ["unlock", str(project.root), "--yes", "--lang", "en"])
    assert result.exit_code == 0 and "Stale lock removed" in result.output
    assert not project.lock_file.exists()
    assert runner.invoke(app, ["dedup", str(project.root)]).exit_code == 0


def test_unlock_without_yes_and_without_a_terminal_changes_nothing(project: Workspace) -> None:
    stale_lock(project)
    result = runner.invoke(app, ["unlock", str(project.root), "--lang", "en"])
    assert result.exit_code == 1 and "Add --yes" in result.stderr
    assert project.lock_file.exists()


def test_unlock_asks_when_there_is_a_terminal(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_lock(project)
    monkeypatch.setattr(cli_module, "_interactive", lambda: True)
    declined = runner.invoke(app, ["unlock", str(project.root), "--lang", "en"], input="n\n")
    assert declined.exit_code == 1 and project.lock_file.exists()
    accepted = runner.invoke(app, ["unlock", str(project.root), "--lang", "en"], input="y\n")
    assert accepted.exit_code == 0 and not project.lock_file.exists()


def test_unlock_never_touches_the_lock_of_a_running_process(project: Workspace) -> None:
    holder = project.lock()
    holder.acquire()
    try:
        result = runner.invoke(app, ["unlock", str(project.root), "--yes", "--lang", "en"])
        assert result.exit_code == 2 and "in use by a running process" in result.stderr
        assert holder.held
    finally:
        holder.release()


def test_unlock_of_something_that_is_no_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["unlock", str(tmp_path / "x"), "--yes", "--lang", "en"])
    assert result.exit_code == 1 and "E404" in result.output


def test_error_hint_of_a_stale_lock_names_the_command(project: Workspace) -> None:
    stale_lock(project)
    with pytest.raises(StorageError) as info:
        project.lock().acquire()
    assert "crapai unlock" in (info.value.hint or "")
