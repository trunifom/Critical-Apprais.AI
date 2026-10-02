"""Tests for reusable settings profiles (ADR 0027)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crapai.config import profiles as pf
from crapai.config.loader import load_project_config
from crapai.config.overrides import overrides_path
from crapai.errors import ConfigError
from crapai.services.project import create_project


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Every test gets its own, empty ``~/.config/crapai/`` -- never the real user folder."""
    folder = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: folder)
    return folder


def test_profiles_dir_is_under_the_user_config_folder(home: Path) -> None:
    assert pf.profiles_dir() == home / ".config" / "crapai" / "profiles"


def test_an_invalid_name_is_refused() -> None:
    for bad in ("", "../escape", "a/b", "-starts-with-dash", "a" * 65):
        with pytest.raises(ConfigError) as info:
            pf.profile_path(bad)
        assert info.value.code == "E203"


def test_save_then_load_round_trips_the_portable_sections(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "review", template="demo")
    config = load_project_config(workspace.project_yaml)
    pf.save_profile("my-profile", config)

    loaded = pf.load_profile("my-profile")
    assert loaded.objectives == config.objectives
    assert loaded.criteria.inclusion == config.criteria.inclusion
    assert loaded.llm.provider == config.llm.provider
    assert loaded.screening.prompt_variant == config.screening.prompt_variant


def test_loading_an_unknown_profile_is_a_clear_error() -> None:
    with pytest.raises(ConfigError) as info:
        pf.load_profile("nope")
    assert info.value.code == "E203" and "nope" in str(info.value)


def test_list_profiles_is_sorted_and_empty_before_any_are_saved(tmp_path: Path) -> None:
    assert pf.list_profiles() == []
    workspace = create_project(tmp_path / "review", template="demo")
    config = load_project_config(workspace.project_yaml)
    pf.save_profile("zebra", config)
    pf.save_profile("apple", config)
    assert pf.list_profiles() == ["apple", "zebra"]


def test_delete_profile_reports_whether_it_existed() -> None:
    assert pf.delete_profile("nope") is False
    workspace_config = pf.SettingsProfile(criteria={"inclusion": {"Population": "adults"}})
    pf.profiles_dir().mkdir(parents=True, exist_ok=True)
    path = pf.profile_path("temp")
    path.write_text(
        yaml.safe_dump(workspace_config.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    assert pf.delete_profile("temp") is True
    assert not path.exists()


def test_applying_a_profile_writes_only_overrides_not_project_yaml(tmp_path: Path) -> None:
    source = create_project(tmp_path / "source", template="demo")
    source_config = load_project_config(source.project_yaml)
    pf.save_profile("design", source_config)

    target = create_project(tmp_path / "target", template="blank", title="Other review")
    original_yaml = target.project_yaml.read_text(encoding="utf-8")
    pf.apply_profile(target.project_yaml, "design")
    assert target.project_yaml.read_text(encoding="utf-8") == original_yaml  # untouched

    applied_config = load_project_config(target.project_yaml)
    assert applied_config.criteria.inclusion == source_config.criteria.inclusion
    assert applied_config.objectives == source_config.objectives
    assert applied_config.llm.provider == source_config.llm.provider
    assert applied_config.project.title == "Other review"  # project identity is never touched


def test_applying_a_profile_keeps_other_existing_overrides(tmp_path: Path) -> None:
    from crapai.config.overrides import set_values

    source = create_project(tmp_path / "source", template="demo")
    pf.save_profile("design", load_project_config(source.project_yaml))

    target = create_project(tmp_path / "target", template="demo")
    set_values(target.project_yaml, {"limits.rpm": 123})
    pf.apply_profile(target.project_yaml, "design")
    config = load_project_config(target.project_yaml)
    assert config.limits.rpm == 123  # an unrelated override survives the profile load


def test_applying_a_profile_is_undone_by_config_reset(tmp_path: Path) -> None:
    from crapai.config.overrides import reset_values

    source = create_project(tmp_path / "source", template="demo")
    source_config = load_project_config(source.project_yaml)
    source_config.criteria.inclusion["Population"] = "children"
    pf.save_profile("design", source_config)

    target = create_project(tmp_path / "target", template="demo")
    before = load_project_config(target.project_yaml).criteria.inclusion
    pf.apply_profile(target.project_yaml, "design")
    assert overrides_path(target.project_yaml).exists()
    reset_values(target.project_yaml)
    assert load_project_config(target.project_yaml).criteria.inclusion == before
