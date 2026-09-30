"""Tests for the validity service and the import -> dedup -> validity order (task T-M2-03)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crapai.errors import StorageError
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.dedup import dedup_project
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project
from crapai.services.validity import validate_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
ZOTERO = "pubmed_adhd_converted-zotero.ris"
NR1 = "example_db_nr1_total-15_duplicates-0.ris"
NR2 = "example_db_nr2_total-10_duplicates-3.ris"


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def set_options(workspace: Workspace, section: str, name: str, value: object) -> None:
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data[section][name] = value
    workspace.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_zotero_project_end_to_end(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / ZOTERO, label="Zotero"))
    summary = validate_project(project)
    oracle = EXPECTED[f"data/{ZOTERO}"]
    assert summary.records == oracle["records"] == 706
    assert summary.valid_for_model == oracle["abstracts"] == 156
    assert sum(summary.by_reason.values()) + summary.valid_for_model == 706
    assert 540 <= summary.by_reason["NO_ABSTRACT"] <= 550
    assert summary.by_reason["NOT_SCREENABLE"] >= 1 and summary.by_reason["EMPTY_RECORD"] == 2
    assert summary.options_source == "project"  # the demo project.yaml was readable
    stored = read_records(project.records_csv)
    assert len(stored) == 706  # nothing was removed
    reasons = {r.exclusion_reason for r in stored}
    assert reasons == {"", "NO_ABSTRACT", "NOT_SCREENABLE", "EMPTY_RECORD"}
    assert list(project.backup_dir.glob("records.*.csv"))
    assert not project.lock_file.exists()


def test_duplicate_keeps_its_reason_whichever_step_ran_first(project: Workspace) -> None:
    for name in (NR1, NR2):
        import_source(project, ImportRequest(DATA / name, label=name[:11]))
    validate_project(project)  # first every record without abstract gets NO_ABSTRACT ...
    dedup_project(project)  # ... then duplicates take precedence
    stored = read_records(project.records_csv)
    duplicates = [r for r in stored if r.is_duplicate]
    assert duplicates and {r.exclusion_reason for r in duplicates} == {"DUPLICATE"}
    validate_project(project)  # a later validity run must not undo it
    again = read_records(project.records_csv)
    assert {r.exclusion_reason for r in again if r.is_duplicate} == {"DUPLICATE"}
    assert {r.exclusion_reason for r in again if not r.is_duplicate} == {"NO_ABSTRACT"}


def test_options_come_from_the_command_line_then_the_project(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / NR1))
    strict = validate_project(project)
    assert strict.valid_for_model == 0 and strict.include_title_only is False

    set_options(project, "screening", "include_title_only", True)
    from_project = validate_project(project)
    assert from_project.options_source == "project" and from_project.include_title_only is True
    assert from_project.valid_for_model == 13  # every record now goes to the model by title

    override = validate_project(project, include_title_only=False)
    assert override.options_source == "cli" and override.valid_for_model == 0


def test_retracted_option_from_project_yaml(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / "pubmed-adhd-set.nbib", label="P"))
    assert "RETRACTED" not in validate_project(project).by_reason
    set_options(project, "prefilters", "exclude_retracted", True)
    summary = validate_project(project)
    assert summary.exclude_retracted is True and summary.options_source == "project"
    retracted = sum(r.is_retracted for r in read_records(project.records_csv))
    assert summary.by_reason.get("RETRACTED", 0) == retracted == 0  # the fixture has none


def test_invalid_project_yaml_falls_back_to_defaults(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / "example_AB_nr4.ris"))
    project.project_yaml.write_text("prefilters: [broken\n", encoding="utf-8")
    summary = validate_project(project)
    assert summary.options_source == "default" and summary.valid_for_model == 3


def test_empty_project_and_foreign_folder(project: Workspace, tmp_path: Path) -> None:
    summary = validate_project(project)
    assert (summary.records, summary.valid_for_model) == (0, 0)
    assert not project.records_csv.exists()
    with pytest.raises(StorageError) as info:
        validate_project(Workspace(tmp_path))
    assert info.value.code == "E404"


def test_busy_project_is_refused(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / "example_AB_nr4.ris"))
    before = project.records_csv.read_bytes()
    holder = project.lock()
    holder.acquire()
    try:
        with pytest.raises(StorageError) as info:
            validate_project(project)
        assert info.value.code == "E402"
    finally:
        holder.release()
    assert project.records_csv.read_bytes() == before


def test_second_run_changes_nothing_and_writes_no_backup(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / NR1))
    validate_project(project)
    content = project.records_csv.read_bytes()
    backups = sorted(project.backup_dir.glob("records.*.csv"))
    validate_project(project)
    assert project.records_csv.read_bytes() == content
    assert sorted(project.backup_dir.glob("records.*.csv")) == backups  # unchanged: no new copy
