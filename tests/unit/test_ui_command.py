"""`crapai ui` starts Streamlit locally, without telemetry, and fails early with a clear message."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import crapai.cli as cli_module
from crapai.cli import app, ui_command_line
from crapai.services.project import create_project
from crapai.ui.context import PROJECT_ENV

runner = CliRunner()


class Finished:
    returncode = 0


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Finished:
        calls.append({"command": command, **kwargs})
        return Finished()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    return calls


def test_the_command_line_is_local_only_and_without_telemetry(tmp_path: Path) -> None:
    command, environment = ui_command_line(tmp_path, 8765, headless=True)
    assert command[:5] == [sys.executable, "-m", "streamlit", "run", command[4]]
    assert command[4].endswith("streamlit_app.py") and Path(command[4]).exists()
    flat = " ".join(command)
    assert "--server.address 127.0.0.1" in flat and "--server.port 8765" in flat
    assert "--browser.gatherUsageStats false" in flat and "--server.headless true" in flat
    assert environment[PROJECT_ENV] == str(tmp_path.resolve())
    # The pages/ folder next to the script must not become a second, technical menu.
    assert "--client.showSidebarNavigation false" in flat


def test_without_a_folder_the_environment_names_no_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROJECT_ENV, raising=False)
    _, environment = ui_command_line(None, 8501, headless=False)
    assert PROJECT_ENV not in environment


def test_the_command_starts_streamlit_with_the_project(
    launched: list[dict[str, Any]], tmp_path: Path
) -> None:
    project = create_project(tmp_path / "p", template="demo").root
    result = runner.invoke(
        app, ["ui", str(project), "--port", "8600", "--no-browser", "--lang", "en"]
    )
    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:8600" in result.output and "this computer only" in result.output
    (call,) = launched
    assert call["env"][PROJECT_ENV] == str(project.resolve()) and call["check"] is False


def test_the_exit_code_of_streamlit_is_passed_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Failed:
        returncode = 3

    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **k: Failed())
    assert runner.invoke(app, ["ui"]).exit_code == 3


def test_a_folder_that_is_no_project_fails_before_the_browser_opens(
    launched: list[dict[str, Any]], tmp_path: Path
) -> None:
    result = runner.invoke(app, ["ui", str(tmp_path / "nothing"), "--lang", "en"])
    assert result.exit_code == 1 and "E404" in result.output and launched == []


def test_a_missing_streamlit_is_explained(
    monkeypatch: pytest.MonkeyPatch, launched: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(cli_module.importlib.util, "find_spec", lambda name: None)
    result = runner.invoke(app, ["ui", "--lang", "en"])
    assert result.exit_code == 1 and "E203" in result.output and "crapai[ui]" in result.output
    assert launched == []


def test_the_german_text(launched: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["ui", "--lang", "de"])
    assert "nur auf diesem Rechner" in result.output
