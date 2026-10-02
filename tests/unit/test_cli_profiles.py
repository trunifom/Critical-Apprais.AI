"""Tests for `crapai profile save/load/list/show/delete` (ADR 0027)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crapai.cli import app
from crapai.config.loader import load_project_config
from crapai.services.project import create_project

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Every test gets its own, empty user config folder -- never the real one."""
    folder = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: folder)
    return folder


def invoke(*args: object):  # type: ignore[no-untyped-def]
    return runner.invoke(app, [str(a) for a in args])


def test_list_is_empty_before_anything_is_saved() -> None:
    result = invoke("profile", "list", "--lang", "en")
    assert result.exit_code == 0 and "No settings profiles" in result.output


def test_save_then_load_round_trips_into_another_project(tmp_path: Path) -> None:
    source = create_project(tmp_path / "source", template="demo")
    result = invoke("profile", "save", source.root, "my-design", "--lang", "en")
    assert result.exit_code == 0, result.output
    assert "my-design" in result.output

    assert invoke("profile", "list", "--lang", "en").output.strip() == "my-design"

    # "blank" has no criteria yet (by design -- load_project_config alone would refuse it), which
    # is exactly the case apply_profile is for: the profile's criteria complete it.
    target = create_project(tmp_path / "target", template="blank", title="Other review")
    result = invoke("profile", "load", target.root, "my-design", "--lang", "en")
    assert result.exit_code == 0, result.output

    source_config = load_project_config(source.project_yaml)
    target_config = load_project_config(target.project_yaml)
    assert target_config.criteria.inclusion == source_config.criteria.inclusion
    assert target_config.project.title == "Other review"  # project identity untouched


def test_loading_an_unknown_profile_is_a_clear_user_error(tmp_path: Path) -> None:
    project = create_project(tmp_path / "p", template="demo")
    result = invoke("profile", "load", project.root, "nope", "--lang", "en")
    assert result.exit_code == 1 and "E203" in result.output and "nope" in result.output


def test_show_prints_the_profile_as_json(tmp_path: Path) -> None:
    source = create_project(tmp_path / "source", template="demo")
    invoke("profile", "save", source.root, "my-design", "--lang", "en")
    result = invoke("profile", "show", "my-design", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["criteria"]["inclusion"]["Population"].startswith("Adults")


def test_delete_reports_whether_the_profile_existed(tmp_path: Path) -> None:
    source = create_project(tmp_path / "source", template="demo")
    invoke("profile", "save", source.root, "temp", "--lang", "en")
    assert invoke("profile", "delete", "temp", "--lang", "en").exit_code == 0
    missing = invoke("profile", "delete", "temp", "--lang", "en")
    assert missing.exit_code == 1 and "temp" in missing.output


def test_saving_overwrites_a_profile_of_the_same_name(tmp_path: Path) -> None:
    source = create_project(tmp_path / "source", template="demo")
    invoke("profile", "save", source.root, "design", "--lang", "en")
    other = create_project(tmp_path / "other", template="blank", title="Different")
    invoke(
        "config", "set", other.root, 'criteria.inclusion={"Population": "children"}', "--lang", "en"
    )
    invoke("profile", "save", other.root, "design", "--lang", "en")
    result = invoke("profile", "show", "design", "--json")
    data = json.loads(result.output)
    assert data["criteria"]["inclusion"]["Population"] == "children"
