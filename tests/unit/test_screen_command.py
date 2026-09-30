"""`crapai screen`, `runs`, `pause`, `stop` and the progress bar."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from crapai.cli import app
from crapai.cli_progress import ProgressPrinter, format_line, render_bar, thousands
from crapai.i18n.messages import Messages
from crapai.project.workspace import Workspace
from crapai.screening.engine import Progress
from crapai.screening.store import RunStore
from crapai.services import screening as svc
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5
runner = CliRunner()


def invoke(*args: object, expect: int | None = 0) -> Any:
    result = runner.invoke(app, [str(a) for a in args], catch_exceptions=False)
    if expect is not None:
        assert result.exit_code == expect, result.output
    return result


def make_project(tmp_path: Path, scenario: str = "S1", count: int = 12, **run: Any) -> Workspace:
    parts = [
        "\n".join(
            ["TY  - JOUR", f"TI  - Study {n} on exercise", f"DO  - 10.1/c{n}", "PY  - 2020",
             f"AB  - {ABSTRACT} Record {n}.", "ER  - "]
        )
        for n in range(count)
    ]  # fmt: skip
    source = tmp_path / "s.ris"
    source.write_text("\n".join(parts) + "\n", encoding="utf-8")
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(source, label="S"))
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "mock", "model": scenario, "base_url": None})
    data.setdefault("run", {}).update(
        {"batch_size": 5, "retry_base_delay_s": 0.001, "retry_max_delay_s": 0.01, **run}
    )
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return workspace


# --- command -------------------------------------------------------------------------------------


def test_a_run_with_yes_completes_with_exit_0_and_prints_the_summary(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("screen", workspace.root, "--yes", "--no-progress", "--lang", "en")
    assert "completed: 12 record(s) screened, 0 with errors" in result.output
    assert "Tokens:" in result.output and "screening.jsonl" in result.output
    assert len(svc.list_runs(workspace)) == 1


def test_json_output_is_machine_readable_and_messages_go_to_stderr(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = runner.invoke(app, ["screen", str(workspace.root), "--yes", "--json", "--lang", "en"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["state"] == "completed" and data["by_status"] == {"ok": 12} and data["total"] == 12
    assert data["run_id"] and data["last_error"] == {} and "folder" in data


def test_without_yes_and_without_a_terminal_nothing_is_started(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("screen", workspace.root, "--lang", "en", expect=1)
    assert "Nothing was started" in result.output
    assert svc.list_runs(workspace) == []


def test_a_question_at_the_terminal_can_be_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crapai.cli as cli

    workspace = make_project(tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    no = runner.invoke(app, ["screen", str(workspace.root), "--no-progress"], input="n\n")
    assert no.exit_code == 1 and svc.list_runs(workspace) == []
    yes = runner.invoke(app, ["screen", str(workspace.root), "--no-progress"], input="y\n")
    assert yes.exit_code == 0 and len(svc.list_runs(workspace)) == 1


def test_a_sample_run_screens_only_that_many(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = runner.invoke(app, ["screen", str(workspace.root), "--yes", "--sample", "4", "--json"])
    data = json.loads(result.stdout)
    assert data["done"] == 4 and svc.list_runs(workspace)[0].kind == "sample"


def test_failed_records_give_exit_code_4_and_a_hint_to_resume(tmp_path: Path) -> None:
    workspace = make_project(tmp_path, "S4", count=30, max_batch_error_rate=1.0)
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data.setdefault("limits", {})["max_retries"] = 0
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = invoke("screen", workspace.root, "--yes", "--no-progress", "--lang", "en", expect=4)
    assert "with errors" in result.output and "--resume" in result.output
    assert "ended with an error" in result.output


def test_a_paused_run_exits_with_3_and_resume_finishes_it(tmp_path: Path) -> None:
    workspace = make_project(tmp_path, "S14", count=30, batch_size=50)
    # S14 (credit used up after 10 calls) pauses the run.
    first = invoke("screen", workspace.root, "--yes", "--no-progress", "--lang", "en", expect=3)
    assert "PAUSED" in first.output and "E307" in first.output and "--resume" in first.output
    runs = svc.list_runs(workspace)
    assert runs[0].state == "paused"
    # The key situation is fixed: the same run continues, now with a working model.
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    store = RunStore(workspace.runs_dir / runs[0].run_id)
    assert store.last_results()
    data["llm"]["model"] = "S1"
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    # The model is part of the fingerprint: changing it must be refused (E204) ...
    refused = invoke("screen", workspace.root, "--yes", "--resume", "--lang", "en", expect=1)
    assert "E204" in refused.output


def test_resume_without_any_run_is_a_clear_error(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("screen", workspace.root, "--yes", "--resume", "--lang", "en", expect=1)
    assert "E203" in result.output


def test_an_unknown_project_folder_is_e404(tmp_path: Path) -> None:
    result = invoke("screen", tmp_path / "nope", "--yes", expect=1)
    assert "E404" in result.output or "E40" in result.output


def test_a_missing_key_is_e301_with_the_variable_name_and_nothing_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_project(tmp_path)
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update(
        {
            "provider": "openai_compatible",
            "base_url": "https://x.example/v1",
            "api_key_env": "NOPE_KEY_X",
        }
    )
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.delenv("NOPE_KEY_X", raising=False)
    result = invoke("screen", workspace.root, "--yes", "--lang", "en", expect=1)
    assert "E301" in result.output and "NOPE_KEY_X" in result.output


def test_the_log_file_of_the_project_records_the_run(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    invoke("screen", workspace.root, "--yes", "--no-progress")
    log = (workspace.root / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "Starting run" in log and "finished in state completed" in log


# --- runs, pause, stop ---------------------------------------------------------------------------


def test_runs_lists_states_and_counts(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    assert "No runs yet" in invoke("runs", workspace.root, "--lang", "en").output
    invoke("screen", workspace.root, "--yes", "--no-progress", "--sample", "3")
    text = invoke("runs", workspace.root, "--lang", "en").output
    assert "completed" in text and "sample" in text and "3/3 done" in text
    data = json.loads(invoke("runs", workspace.root, "--json").stdout)
    assert data[0]["state"] == "completed" and data[0]["counts"]["ok"] == 3


def test_pause_and_stop_are_refused_when_no_run_is_running(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    invoke("screen", workspace.root, "--yes", "--no-progress", "--sample", "2")
    for command in ("pause", "stop"):
        result = invoke(command, workspace.root, "--lang", "en", expect=1)
        assert "nothing to" in result.output
    assert invoke("pause", tmp_path / "nope", expect=None).exit_code != 0


def test_pause_writes_the_control_file_of_a_running_run(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    invoke("screen", workspace.root, "--yes", "--no-progress", "--sample", "2")
    run = svc.list_runs(workspace)[0]
    store = RunStore(workspace.runs_dir / run.run_id)
    manifest = store.load_manifest()
    manifest.state = "running"  # as if another process were working
    store.save_manifest(manifest)
    result = invoke("pause", workspace.root, "--lang", "en")
    assert "sent to run" in result.output and store.read_control() == "pause"
    invoke("stop", workspace.root)
    assert store.read_control() == "stop"


# --- progress bar --------------------------------------------------------------------------------


def progress(**changes: Any) -> Progress:
    values: dict[str, Any] = {
        "state": "running", "done": 50, "total": 100, "ok": 48, "errors": 2, "cost": 0.5,
        "batch": 2, "batches": 4, "concurrency": 5, "elapsed_s": 10.0, "eta_s": 600.0,
    }  # fmt: skip
    values.update(changes)
    return Progress(**values)


def test_thousands_and_bar_rendering() -> None:
    assert thousands(80000) == "80'000" and thousands(5) == "5"
    assert render_bar(0.5, 10) == "[#####.....]"
    assert render_bar(-1, 4) == "[....]" and render_bar(7, 4) == "[####]"


def test_the_line_shows_percent_counts_batch_cost_and_eta() -> None:
    line = format_line(progress(total=80000, done=40000), Messages("en"))
    assert " 50 %" in line and "40'000/80'000" in line and "batch 2/4" in line
    assert "errors 2" in line and "ETA 10 min" in line and line.startswith("[##########")
    german = format_line(progress(), Messages("de"))
    assert "Fehler 2" in german and "Päckchen 2/4" in german


def test_an_empty_run_is_shown_as_full_not_as_a_division_by_zero() -> None:
    assert "100 %" in format_line(progress(total=0, done=0, eta_s=None), Messages("en"))


def test_the_eta_is_unknown_at_the_start_and_after_the_end() -> None:
    assert "ETA ?" in format_line(progress(eta_s=None), Messages("en"))
    assert "ETA ?" in format_line(progress(state="completed"), Messages("en"))


def test_on_a_terminal_the_line_is_rewritten_and_ended_with_a_newline() -> None:
    stream = io.StringIO()
    now = [0.0]
    printer = ProgressPrinter(
        Messages("en"), stream, tty=True, min_interval=1.0, clock=lambda: now[0]
    )
    printer(progress(done=10))
    printer(progress(done=11))  # too soon: not drawn
    now[0] = 2.0
    printer(progress(done=12))
    printer(progress(state="completed", done=100, ok=100, errors=0))
    text = stream.getvalue()
    assert (
        text.count("\r") == 3 and text.endswith("\n") and "12/100" in text and "11/100" not in text
    )


def test_without_a_terminal_only_occasional_plain_lines_are_written() -> None:
    stream = io.StringIO()
    now = [0.0]
    printer = ProgressPrinter(
        Messages("en"), stream, tty=False, plain_interval=30.0, clock=lambda: now[0]
    )
    for done in range(1, 50):
        now[0] += 1.0
        printer(progress(done=done))
    printer(progress(batch=3, done=50))  # a new batch is always reported
    printer(progress(state="paused", done=51))
    lines = stream.getvalue().splitlines()
    assert "\r" not in stream.getvalue() and 3 <= len(lines) <= 6 and "paused" not in lines[-1]


def test_a_broken_output_never_stops_the_run() -> None:
    class Broken(io.StringIO):
        def write(self, _text: str) -> int:
            raise OSError("closed")

    printer = ProgressPrinter(Messages("en"), Broken(), tty=True)
    printer(progress())
    printer.close()
