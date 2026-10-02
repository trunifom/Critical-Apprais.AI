"""`crapai jev-prefilter` (ADR 0029): the dedicated, explicit command for the optional AI pre-filter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from crapai.cli import app
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services import screening as svc
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

runner = CliRunner()

ROWS = [
    ("Clearly off-topic JEV_TRUE_HIGH", "JEV_TRUE_HIGH unrelated topic"),
    ("Ordinary study", "An ordinary abstract about adults and exercise over twelve weeks."),
]


def invoke(*args: object, expect: int | None = 0) -> Any:
    result = runner.invoke(app, [str(a) for a in args], catch_exceptions=False)
    if expect is not None:
        assert result.exit_code == expect, result.output
    return result


def make_project(tmp_path: Path, *, enabled: bool = True) -> Workspace:
    parts = [
        "\n".join(["TY  - JOUR", f"TI  - {title}", f"DO  - 10.1/c{i}", f"AB  - {abstract}", "ER  - "])
        for i, (title, abstract) in enumerate(ROWS)
    ]  # fmt: skip
    source = tmp_path / "s.ris"
    source.write_text("\n".join(parts) + "\n", encoding="utf-8")
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(source, label="S"))
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["ai_prefilter"] = {"enabled": enabled, "model": "mock"}
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return workspace


def reasons_of(workspace: Workspace) -> dict[str, str]:
    return {r.title: r.exclusion_reason for r in read_records(workspace.records_csv)}


def test_a_run_with_yes_marks_records_and_prints_the_summary(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("jev-prefilter", workspace.root, "--yes", "--lang", "en")
    assert "Jev pre-filter done: 1 of 2" in result.output
    assert reasons_of(workspace)["Clearly off-topic JEV_TRUE_HIGH"] == "AI_PREFILTER_JEV"
    assert reasons_of(workspace)["Ordinary study"] == ""


def test_json_output_is_machine_readable(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = runner.invoke(
        app, ["jev-prefilter", str(workspace.root), "--yes", "--json", "--lang", "en"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == {"records": 2, "eligible": 2, "checked": 2, "marked": 1, "cost": data["cost"]}


def test_without_yes_and_without_a_terminal_nothing_is_started(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("jev-prefilter", workspace.root, "--lang", "en", expect=1)
    assert "Nothing was started" in result.output
    assert set(reasons_of(workspace).values()) == {""}


def test_disabled_is_a_clear_error_not_a_crash(tmp_path: Path) -> None:
    workspace = make_project(tmp_path, enabled=False)
    result = invoke("jev-prefilter", workspace.root, "--yes", "--lang", "en", expect=1)
    assert "E203" in result.output
    assert "settings" in result.output.lower() or "einstellungen" in result.output.lower()


def test_a_question_at_the_terminal_can_be_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crapai.cli as cli

    workspace = make_project(tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    no = runner.invoke(app, ["jev-prefilter", str(workspace.root)], input="n\n")
    assert no.exit_code == 1 and set(reasons_of(workspace).values()) == {""}
    yes = runner.invoke(app, ["jev-prefilter", str(workspace.root)], input="y\n")
    assert yes.exit_code == 0
    assert reasons_of(workspace)["Clearly off-topic JEV_TRUE_HIGH"] == "AI_PREFILTER_JEV"


def test_a_marked_record_is_never_sent_to_the_real_screening_run(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    invoke("jev-prefilter", workspace.root, "--yes", "--lang", "en")
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "mock", "model": "S1", "base_url": None})
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    invoke("screen", workspace.root, "--yes", "--no-progress", "--lang", "en")
    assert len(svc.list_runs(workspace)) == 1
    manifest = svc.list_runs(workspace)[0]
    assert manifest.counts.get("total") == 1  # only "Ordinary study" went to the model
