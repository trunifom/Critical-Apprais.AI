"""Project definition (description, questions, criteria) and the process overview."""

from __future__ import annotations

from pathlib import Path

import pytest
from results_helpers import project_with_run

from crapai.config.loader import resolve_config
from crapai.i18n.messages import Messages
from crapai.project.workspace import Workspace
from crapai.services.project import create_project
from crapai.ui import actions
from crapai.ui.definition import (
    FRAMEWORKS,
    Definition,
    framework_elements,
    load_definition,
    problems,
    to_settings,
)
from crapai.ui.viewmodels import (
    TRACKER_PAGES,
    build_tracker,
    load_overview,
    load_run_views,
    next_step,
)


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


# --- frameworks and definition --------------------------------------------------------------------


@pytest.mark.parametrize(
    "framework,first,count",
    [
        ("PICOS", "Population", 5),
        ("SPIDER", "Sample", 5),
        ("PECO", "Population", 4),
        ("PIRD", "Population", 4),
    ],
)
def test_framework_elements(framework: str, first: str, count: int) -> None:
    elements = framework_elements(framework)
    assert elements[0] == first and len(elements) == count


def test_a_custom_framework_uses_the_given_names_and_ignores_blanks() -> None:
    assert framework_elements("CUSTOM", ["Setting", " ", "Method "]) == ["Setting", "Method"]
    assert framework_elements("CUSTOM", []) == []
    assert set(FRAMEWORKS) == {"PICOS", "SPIDER", "PECO", "PIRD", "CUSTOM"}


def test_the_definition_in_force_is_read(project: Workspace) -> None:
    current = load_definition(project.root)
    assert current.title.startswith("Demo review") and current.framework == "PICOS"
    assert any(text.strip() for text in current.inclusion.values())


@pytest.mark.parametrize(
    "definition,expected",
    [
        (Definition(title="T", inclusion={"Population": "adults"}), []),
        (Definition(title="", inclusion={"Population": "adults"}), ["title"]),
        (Definition(title="T", inclusion={"Population": "  "}), ["inclusion"]),
        (
            Definition(title="T", inclusion={"Sample": "x"}),
            ["inclusion"],
        ),  # element of another framework
        (Definition(title="T", framework="CUSTOM"), ["custom_fields"]),
        (
            Definition(
                title="T", framework="CUSTOM", custom_fields=["Setting"], inclusion={"Setting": "x"}
            ),
            [],
        ),
    ],
)
def test_problems(definition: Definition, expected: list[str]) -> None:
    assert problems(definition) == expected


def test_settings_contain_only_the_elements_of_the_chosen_framework() -> None:
    values = to_settings(
        Definition(
            title=" T ",
            objectives=["a", " ", "b"],
            framework="PECO",
            inclusion={"Population": "x", "Sample": "y"},
        )
    )
    assert values["project.title"] == "T" and values["objectives"] == ["a", "b"]
    assert list(values["criteria.inclusion"]) == ["Population", "Exposure", "Comparison", "Outcome"]
    assert (
        values["criteria.inclusion"]["Population"] == "x" and values["criteria.custom_fields"] == []
    )


def test_saving_stores_the_definition_in_the_overrides_file_and_keeps_project_yaml(
    project: Workspace,
) -> None:
    before = project.project_yaml.read_bytes()
    messages = Messages("en")
    new = Definition(
        title="Exercise and mood",
        description="Adults only.",
        objectives=["Does exercise help?"],
        framework="SPIDER",
        inclusion={"Sample": "adults", "Design": "interviews"},
        exclusion={"Sample": "children"},
    )
    assert actions.save_definition(messages, project.root, new).ok
    assert project.project_yaml.read_bytes() == before
    assert (project.root / "project.overrides.yaml").exists()
    config = resolve_config(project.project_yaml)
    assert config.project.title == "Exercise and mood" and config.criteria.framework == "SPIDER"
    assert config.objectives == ["Does exercise help?"]
    loaded = load_definition(project.root)
    assert loaded.inclusion["Sample"] == "adults" and loaded.exclusion["Sample"] == "children"
    assert actions.criteria_filled(project.root) == 2


def test_the_saved_criteria_reach_the_prompt(project: Workspace) -> None:
    from crapai.prompts.builder import builder_for

    actions.save_definition(
        Messages("en"), project.root,
        Definition(title="T", framework="PICOS", inclusion={"Population": "ONLY-PENGUINS"}),
    )  # fmt: skip
    config = resolve_config(project.project_yaml)
    assert "ONLY-PENGUINS" in builder_for(config, project.prompts_dir).build("t", "a").user


def test_an_invalid_definition_writes_nothing(project: Workspace) -> None:
    outcome = actions.save_definition(
        Messages("en"),
        project.root,
        Definition(title="T", framework="NOPE", inclusion={"Population": "x"}),
    )
    assert outcome.error is not None
    assert not (project.root / "project.overrides.yaml").exists()


# --- the overview ----------------------------------------------------------------------------------------


def states(project: Workspace, criteria: int = 1, exports: int = 0) -> dict[str, str]:
    rows = build_tracker(
        load_overview(project.root),
        load_run_views(project.root),
        criteria_filled=criteria,
        exports=exports,
    )
    return {row.page: row.state for row in rows}


def test_the_steps_are_in_workflow_order_and_exactly_one_is_current(project: Workspace) -> None:
    result = states(project, criteria=0)
    assert list(result) == list(TRACKER_PAGES)
    assert result["project"] == "current" and result["data"] == "locked"
    assert list(result.values()).count("current") == 1


def test_a_finished_project_has_every_step_done(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path)
    rows = build_tracker(
        load_overview(workspace.root), load_run_views(workspace.root), criteria_filled=3, exports=1
    )
    assert all(row.state == "done" for row in rows) and next_step(rows) is None


def test_the_next_step_is_the_first_open_one(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path, with_run=False)
    rows = build_tracker(
        load_overview(workspace.root), load_run_views(workspace.root), criteria_filled=3, exports=0
    )
    following = next_step(rows)
    assert following is not None and following.page == "run" and following.state == "current"
    assert [r.state for r in rows[:3]] == ["done", "done", "done"]


def test_a_stopped_run_is_a_warning_and_comes_back_as_the_next_step(tmp_path: Path) -> None:
    from crapai.screening.store import RunStore

    workspace = project_with_run(tmp_path)
    store = RunStore(workspace.runs_dir / load_run_views(workspace.root)[-1].run_id)
    manifest = store.load_manifest()
    manifest.state = "paused"
    store.save_manifest(manifest)
    rows = build_tracker(
        load_overview(workspace.root), load_run_views(workspace.root), criteria_filled=3, exports=0
    )
    run = next(r for r in rows if r.page == "run")
    assert (
        run.state == "warning" and run.detail == "run_stopped" and run.values["state"] == "paused"
    )


def test_a_broken_project_file_is_the_first_problem(project: Workspace) -> None:
    project.project_yaml.write_text("project: {title: T}\n", encoding="utf-8")
    rows = build_tracker(load_overview(project.root), [], criteria_filled=0, exports=0)
    assert rows[0].state == "warning" and rows[0].detail == "project_broken"
    assert next_step(rows) is not None


def test_exports_and_import_history_are_listed(project: Workspace, tmp_path: Path) -> None:
    assert actions.list_exports(project.root) == [] and actions.import_history(project.root) == []
    project.exports_dir.mkdir(parents=True)
    (project.exports_dir / "a.csv").write_text("x", encoding="utf-8")
    newer = project.exports_dir / "b.csv"
    newer.write_text("y", encoding="utf-8")
    import os

    os.utime(project.exports_dir / "a.csv", (1, 1))
    assert [p.name for p in actions.list_exports(project.root)] == ["b.csv", "a.csv"]
    workspace = project_with_run(tmp_path / "w", with_run=False)
    history = actions.import_history(workspace.root)
    assert len(history) == 1 and history[0].source_label == "PubMed"
