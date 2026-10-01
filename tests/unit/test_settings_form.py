"""The settings form: parsing, differences, saving through the actions, texts in both languages."""

from __future__ import annotations

from pathlib import Path

import pytest

from crapai.config.loader import load_project_config
from crapai.config.models import ProjectConfig
from crapai.i18n.messages import Messages
from crapai.project.workspace import Workspace
from crapai.services.project import create_project
from crapai.ui import actions
from crapai.ui.settings_form import ALL_FIELDS, SECTIONS, Field, changes, parse_value


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def current_values(project: Workspace) -> dict[str, object]:
    return {key: s.value for key, s in actions.load_settings(project.root).items()}


def test_every_field_is_a_real_setting_with_texts_in_both_languages(project: Workspace) -> None:
    settings = actions.load_settings(project.root)
    for key, form_field in ALL_FIELDS.items():
        assert key in settings or form_field.kind in {"list", "text"}, key  # e.g. unset base_url
        for lang in ("en", "de"):
            label = Messages(lang).text("ui.setting." + key.replace(".", "_"))
            assert label != "ui.setting." + key.replace(".", "_"), (lang, key)
    for section in SECTIONS:
        for lang in ("en", "de"):
            assert Messages(lang).text(f"ui.section.{section.name}") != f"ui.section.{section.name}"


def test_every_number_field_fits_the_configuration_model() -> None:
    """The form must never offer a value that the model then refuses."""
    defaults = ProjectConfig.model_construct()
    assert defaults is not None
    for form_field in ALL_FIELDS.values():
        if form_field.kind not in {"int", "float"}:
            continue
        for bound in (form_field.minimum, form_field.maximum):
            assert bound is not None, form_field.key


@pytest.mark.parametrize(
    "kind,raw,expected",
    [
        ("int", "7", 7),
        ("int", 7.0, 7),
        ("float", "0.5", 0.5),
        ("bool", 1, True),
        ("bool", 0, False),
        ("choice", "title", "title"),
        ("list", "eng, ger ,", ["eng", "ger"]),
        ("list", "", []),
        ("list", ["a"], ["a"]),
        ("optional_float", "", None),
        ("optional_float", "2,5", 2.5),
        ("optional_float", None, None),
        ("text", "  gpt-4o ", "gpt-4o"),
        ("text", None, ""),
    ],
)
def test_parse_value(kind: str, raw: object, expected: object) -> None:
    assert parse_value(Field("x.y", kind), raw) == expected


def test_an_empty_base_url_is_none() -> None:
    assert parse_value(Field("llm.base_url", "text"), "  ") is None
    assert parse_value(Field("llm.base_url", "text"), "https://x.ch/v1") == "https://x.ch/v1"


@pytest.mark.parametrize("kind,raw", [("int", "abc"), ("float", "x"), ("optional_float", "1.2.3")])
def test_unreadable_numbers_name_the_field(kind: str, raw: str) -> None:
    with pytest.raises(ValueError):
        parse_value(Field("a.b", kind), raw)
    with pytest.raises(ValueError, match="llm.timeout_s"):
        changes({"llm.timeout_s": 1.0}, {"llm.timeout_s": "oops"})


def test_only_differences_are_reported() -> None:
    current = {"limits.rpm": 500, "llm.model": "gpt-4o-mini", "dedup.fuzzy.enabled": False}
    edited = {
        "limits.rpm": 500,
        "llm.model": "gpt-4o",
        "dedup.fuzzy.enabled": False,
        "not.in.form": 1,
    }
    assert changes(current, edited) == {"llm.model": "gpt-4o"}


def test_an_unset_value_edited_to_empty_is_no_change() -> None:
    assert changes({}, {"prefilters.language.allow": "", "llm.base_url": ""}) == {}
    assert changes({}, {"prefilters.language.allow": "eng"}) == {
        "prefilters.language.allow": ["eng"]
    }


def test_saving_writes_only_the_overrides_and_reloads(project: Workspace) -> None:
    messages = Messages("en")
    before = project.project_yaml.read_bytes()
    edited = dict(current_values(project))
    edited["quality.short_abstract_words"] = 25
    edited["limits.max_cost"] = "12,5"
    edited["dedup.fuzzy.enabled"] = True
    outcome = actions.save_settings(messages, project.root, edited)
    assert outcome.ok and outcome.value == {
        "quality.short_abstract_words": 25,
        "limits.max_cost": 12.5,
        "dedup.fuzzy.enabled": True,
    }
    assert project.project_yaml.read_bytes() == before
    config = load_project_config(project.project_yaml)
    assert config.quality.short_abstract_words == 25 and config.dedup.fuzzy.enabled
    sources = {k: s.source for k, s in actions.load_settings(project.root).items()}
    assert sources["limits.max_cost"] == "overrides" and sources["limits.rpm"] == "project"


def test_saving_without_changes_writes_nothing(project: Workspace) -> None:
    outcome = actions.save_settings(Messages("en"), project.root, current_values(project))
    assert outcome.ok and outcome.value == {}
    assert not (project.root / "project.overrides.yaml").exists()


def test_an_invalid_value_is_reported_and_nothing_is_written(project: Workspace) -> None:
    edited = dict(current_values(project))
    edited["limits.rpm"] = -4
    outcome = actions.save_settings(Messages("en"), project.root, edited)
    assert outcome.error and outcome.error.code == "E203"
    assert not (project.root / "project.overrides.yaml").exists()
    edited["limits.rpm"] = 100
    edited["llm.temperature"] = "hot"
    bad = actions.save_settings(Messages("en"), project.root, edited)
    assert bad.error and bad.error.code == "E203" and "llm.temperature" in bad.error.details


def test_reset_brings_back_the_project_values(project: Workspace) -> None:
    messages = Messages("en")
    edited = dict(current_values(project))
    edited["limits.rpm"] = 77
    actions.save_settings(messages, project.root, edited)
    outcome = actions.reset_settings(messages, project.root)
    assert outcome.value == ["limits.rpm"]
    assert load_project_config(project.project_yaml).limits.rpm == 500
    assert actions.reset_settings(messages, project.root).value == []


def test_settings_of_a_broken_project_are_empty(tmp_path: Path) -> None:
    assert actions.load_settings(tmp_path / "nothing") == {}


def test_settings_cannot_be_saved_while_the_project_is_in_use(project: Workspace) -> None:
    holder = project.lock()
    holder.acquire()
    try:
        edited = dict(current_values(project))
        edited["limits.rpm"] = 10
        outcome = actions.save_settings(Messages("en"), project.root, edited)
        assert outcome.error and outcome.error.code == "E402"
    finally:
        holder.release()


# --- read_project_config / read_pricing_table (the page used to do this with its own try) --------


def test_read_project_config_returns_the_config(project: Workspace) -> None:
    outcome = actions.read_project_config(Messages("en"), project.root)
    assert outcome.error is None
    assert outcome.value is not None and outcome.value.project.title


def test_read_project_config_of_a_broken_project_is_an_error_report(tmp_path: Path) -> None:
    outcome = actions.read_project_config(Messages("en"), tmp_path / "nothing")
    assert outcome.value is None and outcome.error is not None


def test_read_pricing_table_keeps_every_row_and_the_right_columns(project: Workspace) -> None:
    """Regression test: a delimiter sniff must not consume the header before DictReader reads
    it, or the first data row is silently treated as the header (losing a row, mislabelling
    every column) -- see the 'wrote 2 rows, read 1 garbled row' bug this guards against."""
    path = project.pricing_csv
    path.write_text(
        "provider;model;price_input_per_1k;price_output_per_1k\n"
        "openai;gpt-4o-mini;0.1;0.2\n"
        "openai_compatible;neotron;0.3;0.4\n",
        encoding="utf-8",
    )
    outcome = actions.read_pricing_table(Messages("en"), path)
    assert outcome.error is None
    rows = outcome.value
    assert rows is not None and len(rows) == 2
    assert [r["provider"] for r in rows] == ["openai", "openai_compatible"]
    assert [r["model"] for r in rows] == ["gpt-4o-mini", "neotron"]


def test_read_pricing_table_reports_a_file_missing_required_columns(project: Workspace) -> None:
    path = project.pricing_csv
    path.write_text("foo,bar\n1,2\n", encoding="utf-8")  # no provider/model/price columns
    outcome = actions.read_pricing_table(Messages("en"), path)
    assert outcome.value is None and outcome.error is not None and outcome.error.code == "E203"
