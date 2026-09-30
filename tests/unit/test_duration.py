"""Tests for the duration estimate, check cost output and confirmation rule (T-M2-06)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from crapai.cli import app
from crapai.cost.duration import (
    Confirmation,
    DurationConfig,
    decide_confirmation,
    estimate_duration,
    format_duration,
)
from crapai.project.workspace import Workspace
from crapai.services.cost import estimate_project
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 3
PRICES = (
    "provider,model,price_input_per_1k,price_output_per_1k,currency,valid_from,source\n"
    "anthropic,claude-sonnet-5-5,0.003,0.015,USD,2026-09-30,test\n"
)
runner = CliRunner()


def kwargs(**over: int) -> dict[str, int]:
    return {"rpm": 500, "tpm": 200_000, "max_concurrency": 5, **over}


# --- the arithmetic ---------------------------------------------------------------------------


def test_latency_limits_a_small_fast_run() -> None:
    result = estimate_duration(100, 50_000, **kwargs())  # 100 * 3 s / 5 = 60 s
    assert result.limited_by == "latency" and result.seconds == pytest.approx(60.0)


def test_requests_per_minute_can_limit() -> None:
    result = estimate_duration(1000, 10_000, **kwargs(rpm=100, max_concurrency=50))
    assert result.limited_by == "rpm" and result.seconds == pytest.approx(600.0)


def test_tokens_per_minute_can_limit() -> None:
    result = estimate_duration(100, 1_000_000, **kwargs(tpm=100_000, max_concurrency=50))
    assert result.limited_by == "tpm" and result.seconds == pytest.approx(600.0)


def test_the_assumed_latency_is_configurable() -> None:
    slow = estimate_duration(10, 100, **kwargs(), config=DurationConfig(seconds_per_request=10))
    assert slow.seconds == pytest.approx(20.0)


def test_an_empty_run_takes_no_time() -> None:
    assert estimate_duration(0, 0, **kwargs()).seconds == 0.0
    assert estimate_duration(0, 0, **kwargs()).limited_by == "none"


@pytest.mark.parametrize("bad", [{"rpm": 0}, {"tpm": 0}, {"max_concurrency": 0}, {"rpm": -1}])
def test_non_positive_limits_are_refused(bad: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        estimate_duration(10, 10, **kwargs(**bad))


@given(st.integers(1, 5000), st.integers(0, 10**7), st.integers(1, 1000), st.integers(1, 10**6))
def test_more_records_never_take_less_time(n: int, tokens: int, rpm: int, tpm: int) -> None:
    few = estimate_duration(n, tokens, rpm=rpm, tpm=tpm, max_concurrency=5)
    more = estimate_duration(n + 1, tokens, rpm=rpm, tpm=tpm, max_concurrency=5)
    assert more.seconds >= few.seconds > 0


@pytest.mark.parametrize(
    "seconds,text",
    [
        (0, "0 s"),
        (0.2, "1 s"),
        (45, "45 s"),
        (59.5, "1 min"),
        (60, "1 min"),
        (61, "2 min"),
        (720, "12 min"),
        (3600, "1 h 00 min"),
        (7500, "2 h 05 min"),
        (-5, "0 s"),
    ],
)
def test_durations_are_shown_in_a_short_human_form(seconds: float, text: str) -> None:
    assert format_duration(seconds) == text


# --- confirmation rule ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yes,interactive,expected",
    [
        (True, True, Confirmation.PROCEED),
        (True, False, Confirmation.PROCEED),
        (False, True, Confirmation.ASK),
        (False, False, Confirmation.REFUSE),
    ],
)
def test_a_run_needs_yes_or_a_terminal(
    yes: bool, interactive: bool, expected: Confirmation
) -> None:
    assert decide_confirmation(yes=yes, interactive=interactive) is expected


# --- in the project and in `crapai check` -----------------------------------------------------


def make_project(tmp_path: Path, priced: bool = True) -> Workspace:
    project = create_project(tmp_path / "p", template="demo")
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "anthropic", "model": "claude-sonnet-5-5", "base_url": None})
    data["prefilters"] = {}
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    rows = "\n".join(
        f"TY  - JOUR\nTI  - Study {i}\nDO  - 10.1000/d{i}\nAB  - {ABSTRACT}\nER  - "
        for i in range(4)
    )
    source = tmp_path / "s.ris"
    source.write_text(rows + "\n", encoding="utf-8")
    import_source(project, ImportRequest(source, label="S"))
    if priced:
        project.pricing_csv.write_text(PRICES, encoding="utf-8")
    return project


def set_limits(project: Workspace, **limits: object) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["limits"].update(limits)
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_the_project_estimate_uses_the_limits_of_project_yaml(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    set_limits(project, rpm=2, max_concurrency=10)
    duration = estimate_project(project).duration
    assert duration.limited_by == "rpm" and duration.seconds == pytest.approx(120.0)


def test_check_shows_cost_tokens_and_duration(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert result.exit_code == 0, result.output
    assert "Model: anthropic / claude-sonnet-5-5" in result.output
    assert "approximate, with a 10 % safety margin" in result.output
    assert "Cost: about " in result.output and "prices valid from 2026-09-30" in result.output
    assert "Duration: about 3 s (limited by the time a request takes)" in result.output


def test_check_in_german(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    result = runner.invoke(app, ["check", str(project.root), "--lang", "de"])
    assert "Kosten: etwa " in result.output and "Dauer: etwa 3 s" in result.output
    assert "näherungsweise" in result.output


def test_check_without_a_price_says_how_to_add_one(tmp_path: Path) -> None:
    project = make_project(tmp_path, priced=False)
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert result.exit_code == 0
    assert "no price for this model" in result.output and "pricing.csv" in result.output


def test_check_json_contains_the_estimate(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    data = json.loads(runner.invoke(app, ["check", str(project.root), "--json"]).stdout)
    estimate = data["estimate"]
    assert estimate["records"] == 4 and estimate["currency"] == "USD"
    assert estimate["cost_low"] < estimate["cost"] < estimate["cost_high"] <= estimate["cost_max"]
    assert estimate["tokens_exact"] is False and estimate["tokenizer"] == "chars"
    assert estimate["duration_seconds"] == 3 and estimate["duration_limited_by"] == "latency"
    assert data["estimate_problem"] is None and estimate["over_limit"] is False


def test_check_warns_when_the_worst_case_exceeds_max_cost(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    set_limits(project, max_cost=0.0001)
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert result.exit_code == 4
    assert "above limits.max_cost (0.0001)" in result.output


def test_check_survives_a_broken_price_file_with_a_warning(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.pricing_csv.write_text("provider,model\nx,y\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert result.exit_code == 4
    assert "The cost estimate is not available: E203" in result.output
    data = json.loads(runner.invoke(app, ["check", str(project.root), "--json"]).stdout)
    assert data["estimate"] is None and data["estimate_problem"].startswith("E203")


def test_nothing_to_send_shows_no_estimate(tmp_path: Path) -> None:
    project = create_project(tmp_path / "empty", template="demo")
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert result.exit_code == 1 and "Model:" not in result.output
