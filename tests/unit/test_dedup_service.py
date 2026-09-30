"""Tests for the dedup service and the `crapai dedup` command (task T-M2-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crapai.cli import app
from crapai.errors import StorageError
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.dedup import dedup_project
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
TRIO = [
    "example_db_nr1_total-15_duplicates-0.ris",
    "example_db_nr2_total-10_duplicates-3.ris",
    "example_db_nr3_total-8_duplicates-2.ris",
]
runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    for index, name in enumerate(TRIO, start=1):
        import_source(workspace, ImportRequest(DATA / name, label=f"Db{index}"))
    return workspace


def test_trio_gets_18_marked_duplicates_and_keeps_all_31_rows(project: Workspace) -> None:
    before = read_records(project.records_csv)
    summary = dedup_project(project)
    after = read_records(project.records_csv)
    assert (summary.records, summary.marked) == (31, 18)
    assert len(after) == len(before) == 31
    assert [r.study_uid for r in after] == [r.study_uid for r in before]  # same rows, same order
    assert sum(r.is_duplicate for r in after) == 18
    assert {r.doi for r in after if not r.is_duplicate} == {r.doi for r in before}  # 13 DOIs stay
    assert summary.across_sources > 0 and summary.by_method == {"doi": 18}
    assert list(project.backup_dir.glob("records.*.csv"))  # backup before the rewrite
    assert not project.lock_file.exists()


def test_strategy_comes_from_the_command_line_then_project_then_default(project: Workspace) -> None:
    assert dedup_project(project, strategy="title").strategy_source == "cli"
    assert dedup_project(project).strategy_source == "project"  # demo template: doi_or_title
    project.project_yaml.unlink()
    summary = dedup_project(project)
    assert (summary.strategy, summary.strategy_source) == ("doi_or_title", "default")


def test_invalid_project_yaml_falls_back_to_the_default(project: Workspace) -> None:
    project.project_yaml.write_text("dedup:\n  strategy: nonsense\n", encoding="utf-8")
    summary = dedup_project(project)
    assert summary.strategy_source == "default" and summary.marked == 18


def test_second_run_is_stable_and_a_new_strategy_starts_clean(project: Workspace) -> None:
    first = dedup_project(project)
    marks = [
        (r.study_uid, r.is_duplicate, r.duplicate_of) for r in read_records(project.records_csv)
    ]
    second = dedup_project(project)
    assert (second.marked, second.groups) == (first.marked, first.groups)
    assert marks == [
        (r.study_uid, r.is_duplicate, r.duplicate_of) for r in read_records(project.records_csv)
    ]
    dedup_project(project, strategy="strict_ids")  # no PMIDs in these fixtures: DOI only
    assert sum(r.is_duplicate for r in read_records(project.records_csv)) == 18


def test_project_in_use_is_refused_and_nothing_changes(project: Workspace) -> None:
    holder = project.lock()
    holder.acquire()
    try:
        with pytest.raises(StorageError) as info:
            dedup_project(project)
        assert info.value.code == "E402"
    finally:
        holder.release()
    assert not any(r.is_duplicate for r in read_records(project.records_csv))


def test_not_a_project_folder(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        dedup_project(Workspace(tmp_path))
    assert info.value.code == "E404"


def test_empty_project_is_fine(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "e", template="demo")
    summary = dedup_project(workspace)
    assert (summary.records, summary.marked) == (0, 0)
    assert not workspace.records_csv.exists()  # nothing to rewrite


# --- command ---


def test_command_marks_and_reports_in_both_languages(project: Workspace) -> None:
    result = runner.invoke(app, ["dedup", str(project.root), "--lang", "en"])
    assert result.exit_code == 0, result.output
    assert "Duplicates marked: 18 of 31 records" in result.output
    assert "Nothing was deleted" in result.output and "doi: 18" in result.output
    german = runner.invoke(app, ["dedup", str(project.root), "--lang", "de"])
    assert german.exit_code == 0 and "Duplikate markiert: 18 von 31 Datensätzen" in german.output


def test_command_options_json_and_errors(project: Workspace, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["dedup", str(project.root), "--strategy", "title", "--keep", "last", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["strategy"] == "title" and data["keep"] == "last" and data["records"] == 31
    assert data["strategy_source"] == "cli"

    for bad in (["--strategy", "magic"], ["--keep", "middle"]):
        failed = runner.invoke(app, ["dedup", str(project.root), *bad, "--lang", "en"])
        assert failed.exit_code == 1 and "Error E203" in failed.output and "valid:" in failed.output
    missing = runner.invoke(app, ["dedup", str(tmp_path), "--lang", "en"])
    assert missing.exit_code == 1 and "Error E404" in missing.output


def test_command_without_duplicates(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(DATA / TRIO[0], label="Db1"))
    result = runner.invoke(app, ["dedup", str(workspace.root), "--lang", "en"])
    assert result.exit_code == 0 and "No duplicates found" in result.output
