"""Tests for the project service: init from templates and status (task T-M1-11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crapai.config.loader import load_project_config
from crapai.errors import ConfigError, SaraError, StorageError
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import (
    available_templates,
    create_project,
    project_status,
    read_template,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"


def test_bundled_templates_exist() -> None:
    assert available_templates() == ["blank", "demo"]


def test_demo_template_is_a_valid_complete_configuration(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "demo", template="demo")
    config = load_project_config(workspace.project_yaml)
    assert config.criteria.inclusion and config.screening.uncertain_policy == "include"
    assert config.llm.api_key_env == "SWISSGPT_API_KEY"  # a variable NAME, never a key
    assert "sk-" not in workspace.project_yaml.read_text(encoding="utf-8")


def test_bundled_demo_matches_the_example_in_templates() -> None:
    """The packaged demo must not drift from templates/project.example.yaml (except the title)."""
    example_path = Path(__file__).resolve().parents[2] / "templates" / "project.example.yaml"
    example = example_path.read_text(encoding="utf-8")
    demo = read_template("demo")
    strip = [line for line in example.splitlines() if not line.strip().startswith("title:")]
    strip_demo = [line for line in demo.splitlines() if not line.strip().startswith("title:")]
    assert strip == strip_demo


def test_blank_template_takes_the_folder_name_and_needs_criteria(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "my-review")
    text = workspace.project_yaml.read_text(encoding="utf-8")
    assert 'title: "my-review"' in text and "__TITLE__" not in text
    with pytest.raises(ConfigError) as info:
        load_project_config(workspace.project_yaml)
    assert info.value.details["problems"][0]["path"] == "criteria"  # inclusion still empty


def test_title_option_and_quote_safety(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p", title='My "quoted" review')
    import yaml

    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    assert data["project"]["title"] == 'My "quoted" review'


def test_template_from_a_file_path(tmp_path: Path) -> None:
    custom = tmp_path / "mine.yaml"
    custom.write_text(read_template("demo").replace("Demo review", "Mine"), encoding="utf-8")
    workspace = create_project(tmp_path / "p", template=str(custom))
    assert load_project_config(workspace.project_yaml).project.title.startswith("Mine")


def test_unknown_template_or_file_fails_before_creating_anything(tmp_path: Path) -> None:
    for template in ("nope", str(tmp_path / "missing.yaml")):
        with pytest.raises(ConfigError) as info:
            create_project(tmp_path / "p", template=template)
        assert info.value.code == "E203"
    assert not (tmp_path / "p").exists()


def test_existing_project_or_non_empty_folder_is_refused(tmp_path: Path) -> None:
    create_project(tmp_path / "p")
    with pytest.raises(StorageError):
        create_project(tmp_path / "p")
    own = tmp_path / "q"
    own.mkdir()
    (own / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(StorageError):
        create_project(own)
    assert (own / "file.txt").exists() and not (own / "project.yaml").exists()


def test_status_of_a_fresh_project(tmp_path: Path) -> None:
    create_project(tmp_path / "p", template="demo")
    status = project_status(tmp_path / "p")
    assert (status.records, status.with_abstract, status.imports) == (0, 0, ())
    assert status.config_ok and status.title and status.schema_version == 1 and not status.in_use


def test_status_after_imports(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p", template="demo")
    first = DATA / "example_db_nr2_total-10_duplicates-3.ris"
    import_source(workspace, ImportRequest(first, label="A"))
    import_source(workspace, ImportRequest(DATA / "citation-export.ris", label="Cochrane"))
    status = project_status(workspace.root)
    assert status.records == 16 and status.with_abstract == 6
    assert status.per_source == {"A": 10, "Cochrane": 6}
    assert [i.source_label for i in status.imports] == ["A", "Cochrane"]


def test_status_reports_invalid_config_without_failing(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p")  # blank: criteria missing
    status = project_status(workspace.root)
    assert not status.config_ok and "criteria" in (status.config_problem or "")
    workspace.project_yaml.unlink()
    assert project_status(workspace.root).config_problem == "project.yaml is missing"


def test_status_sees_a_running_lock_and_requires_a_project(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p", template="demo")
    with workspace.lock():
        assert project_status(workspace.root).in_use
    with pytest.raises(SaraError):
        project_status(tmp_path)  # a plain folder
