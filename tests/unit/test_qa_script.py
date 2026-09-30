"""The quality-gate script runs the steps of the CI in order and stops at the first failure."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "qa.py"


@pytest.fixture
def qa() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qa_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["qa_script"] = module
    spec.loader.exec_module(module)
    return module


def names(plan: list[tuple[str, list[str]]]) -> list[str]:
    return [name for name, _ in plan]


def test_the_default_plan_is_lint_format_types_tests(qa: ModuleType) -> None:
    assert names(qa.steps(fast=False, fix=False)) == ["lint", "format", "types", "tests"]


def test_fix_runs_ruff_first(qa: ModuleType) -> None:
    assert names(qa.steps(fast=False, fix=True))[:2] == ["ruff fix", "ruff format"]


def test_live_tests_are_never_part_of_the_gates(qa: ModuleType) -> None:
    tests = dict(qa.steps(fast=False, fix=False))["tests"]
    assert tests[len(tests) - 1 - tests[::-1].index("-m") + 1] == "not live"


def test_fast_fixes_the_seed_and_stops_early(qa: ModuleType) -> None:
    tests = dict(qa.steps(fast=True, fix=False))["tests"]
    assert "--hypothesis-seed=0" in tests and "-x" in tests


def test_format_paths_leave_the_documents_alone(qa: ModuleType) -> None:
    assert "docs" not in qa.FORMAT_PATHS and {"src", "tests"} <= set(qa.FORMAT_PATHS)


def test_main_stops_at_the_first_failing_step(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []

    class Done:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def fake_run(command: list[str], **kwargs: object) -> Done:
        ran.append(command[2])
        return Done(3 if command[2] == "mypy" else 0)

    monkeypatch.setattr(qa.subprocess, "run", fake_run)
    assert qa.main([]) == 3
    assert ran == ["ruff", "ruff", "mypy"]  # pytest never started
    assert "FAILED (3)" in capsys.readouterr().out


def test_main_succeeds_when_every_step_does(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Done:
        returncode = 0

    monkeypatch.setattr(qa.subprocess, "run", lambda *a, **k: Done())
    assert qa.main(["--ci"]) == 0
    assert "All gates passed." in capsys.readouterr().out
