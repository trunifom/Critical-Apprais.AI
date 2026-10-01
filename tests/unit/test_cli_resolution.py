"""CLI: 'crapai adjudicate' and 'crapai discuss' (settle a disagreement between runs)."""

from __future__ import annotations

import json
from pathlib import Path

from results_helpers import project_with_run
from typer.testing import CliRunner

from crapai.cli import app
from crapai.llm.mock_provider import MockProvider
from crapai.screening.store import RunStore
from crapai.services import screening as svc
from crapai.services.results import runs_with_results


def two_runs(tmp_path: Path, scenario: str = "S1") -> tuple[Path, str, str]:
    workspace = project_with_run(tmp_path, scenario=scenario)
    run_a = runs_with_results(workspace)[0]
    before = set(runs_with_results(workspace))
    svc.screen_project(
        workspace, svc.RunOptions(provider=MockProvider(scenario), install_signal_handler=False)
    )
    run_b = next(r for r in runs_with_results(workspace) if r not in before)
    store = RunStore(workspace.runs_dir / run_b)
    uid, row = next(
        (u, r) for u, r in store.last_results().items() if r.status == "ok" and r.decision
    )
    flipped = "EXCLUDE" if row.decision != "EXCLUDE" else "INCLUDE"
    store.append_result(row.model_copy(update={"decision": flipped}))
    return workspace.root, run_a, run_b


def test_adjudicate_settles_the_record_with_the_mock_as_master(tmp_path: Path) -> None:
    root, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app,
        ["adjudicate", str(root), "--runs", f"{run_a},{run_b}", "--yes", "--lang", "en"],
    )
    assert result.exit_code == 0, result.output
    assert "completed" in result.output.lower()


def test_adjudicate_without_yes_asks_and_declines_without_a_terminal(tmp_path: Path) -> None:
    root, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app, ["adjudicate", str(root), "--runs", f"{run_a},{run_b}", "--lang", "en"]
    )
    assert result.exit_code == 1
    assert "disputed" in result.output.lower() or "declined" in result.output.lower()


def test_adjudicate_rejects_a_single_run(tmp_path: Path) -> None:
    root, run_a, _run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app, ["adjudicate", str(root), "--runs", run_a, "--yes", "--lang", "en"]
    )
    assert result.exit_code == 1


def test_discuss_as_json(tmp_path: Path) -> None:
    root, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "discuss", str(root), "--runs", f"{run_a},{run_b}", "--max-rounds", "1",
            "--yes", "--json",
        ],  # fmt: skip
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["method"] == "discuss" and data["state"] == "completed"
    assert data["done"] == 1


def test_discuss_rejects_a_bad_tie_break(tmp_path: Path) -> None:
    root, run_a, run_b = two_runs(tmp_path)
    result = CliRunner().invoke(
        app,
        ["discuss", str(root), "--runs", f"{run_a},{run_b}", "--tie-break", "nonsense", "--yes"],
    )
    assert result.exit_code != 0


def test_crapai_runs_lists_the_resolution_with_its_kind(tmp_path: Path) -> None:
    root, run_a, run_b = two_runs(tmp_path)
    CliRunner().invoke(app, ["adjudicate", str(root), "--runs", f"{run_a},{run_b}", "--yes"])
    result = CliRunner().invoke(app, ["runs", str(root), "--lang", "en"])
    assert "adjudicate" in result.output
