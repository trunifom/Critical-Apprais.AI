"""Tests for `crapai check`: preflight report, exit codes, texts (task T-M2-04)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from crapai.cli import app
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 3
runner = CliRunner()


def ris(tmp_path: Path, name: str, rows: list[tuple[str, str]]) -> Path:
    parts = []
    for index, (title, abstract) in enumerate(rows):
        lines = ["TY  - JOUR", f"TI  - {title}", f"DO  - 10.1/{name}{index}"]
        if abstract:
            lines.append(f"AB  - {abstract}")
        parts.append("\n".join([*lines, "ER  - "]))
    path = tmp_path / name
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def invoke(*args: object) -> Any:
    return runner.invoke(app, [str(a) for a in args], catch_exceptions=False)


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def load(project: Workspace, path: Path, label: str) -> None:
    import_source(project, ImportRequest(path, label=label))


def test_ready_project_exits_zero(project: Workspace, tmp_path: Path) -> None:
    load(project, ris(tmp_path, "a.ris", [(f"T{i}", ABSTRACT) for i in range(4)]), "PubMed")
    result = invoke("check", project.root, "--lang", "en")
    assert result.exit_code == 0, result.output
    assert "Preflight: OK. The project is ready for screening." in result.output
    assert "Records: 4, duplicates: 0, going to the model: 4" in result.output
    assert "PubMed: 4 records, 4 with abstract (100 %)" in result.output
    assert "Duplicates and validity were recalculated just now." in result.output


def test_warnings_exit_four_and_explain_themselves(project: Workspace, tmp_path: Path) -> None:
    rows = [
        ("Good", ABSTRACT),
        ("Broken", "cdoemveplaonpyinsgtrat " * 60),
        ("Front-matter", ""),
        ("N", ""),
    ]
    load(project, ris(tmp_path, "w.ris", rows), "W")
    result = invoke("check", project.root, "--lang", "en")
    assert result.exit_code == 4
    assert "Preflight: WARNING" in result.output
    assert "NOT_SCREENABLE: 1 (front or back matter, not a study)" in result.output
    assert "NO_ABSTRACT: 1 (no abstract)" in result.output
    assert "Fewer than 60 %" in result.output
    assert "1 abstract(s) look garbled" in result.output
    assert "Abstract quality: ok 1, short 0, suspect 1" in result.output


def test_nothing_to_screen_is_an_error_with_exit_one(project: Workspace) -> None:
    load(project, DATA / "example_db_nr1_total-15_duplicates-0.ris", "Db1")
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"] = {}  # the demo template filters by year; this test is about abstracts
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = invoke("check", project.root, "--lang", "en")
    assert result.exit_code == 1
    assert "Preflight: ERROR" in result.output and "No record can go to the model" in result.output
    assert "NO_ABSTRACT: 13" in result.output


def test_empty_project_is_an_error(project: Workspace) -> None:
    result = invoke("check", project.root, "--lang", "en")
    assert result.exit_code == 1 and "There are no records yet" in result.output


def test_german_texts(project: Workspace, tmp_path: Path) -> None:
    load(project, ris(tmp_path, "g.ris", [("A", ABSTRACT), ("B", "")]), "Quelle")
    result = invoke("check", project.root, "--lang", "de")
    assert result.exit_code == 4
    assert "Preflight: WARNUNG" in result.output
    assert "Datensätze: 2, Duplikate: 0, gehen ans Modell: 1" in result.output
    assert "NO_ABSTRACT: 1 (kein Abstract)" in result.output


def test_json_report_is_complete_and_stdout_only(project: Workspace, tmp_path: Path) -> None:
    load(
        project,
        ris(
            tmp_path,
            "j.ris",
            [("Study A on one topic", ABSTRACT), ("Study A on one topic", ABSTRACT), ("C", "")],
        ),
        "J",
    )
    result = CliRunner().invoke(app, ["check", str(project.root), "--json"])
    assert result.exit_code == 0  # 2 of 3 records have an abstract: 67 % is above the 60 % limit
    data = json.loads(result.stdout)
    assert data["status"] == "ok" and data["records"] == 3 and data["duplicates"] == 1
    assert data["issues"] == []
    assert data["valid_for_model"] == 1 and data["updated"] is True
    assert data["by_reason"] == {"DUPLICATE": 1, "NO_ABSTRACT": 1}
    (source,) = data["sources"]
    assert (source["label"], source["records"], source["with_abstract"]) == ("J", 3, 2)
    assert source["duplicates"] == 1 and source["valid_for_model"] == 1
    assert source["status"] == "ok" and source["issues"] == []


def test_read_only_leaves_records_untouched(project: Workspace, tmp_path: Path) -> None:
    load(
        project,
        ris(
            tmp_path,
            "r.ris",
            [("Dup of one long title", ABSTRACT), ("Dup of one long title", ABSTRACT)],
        ),
        "R",
    )
    before = project.records_csv.read_bytes()
    result = invoke("check", project.root, "--read-only", "--lang", "en")
    assert project.records_csv.read_bytes() == before
    assert "Read only: duplicates and validity were not recalculated." in result.output
    assert not any(r.is_duplicate for r in read_records(project.records_csv))
    invoke("check", project.root)
    assert sum(r.is_duplicate for r in read_records(project.records_csv)) == 1


def test_retracted_studies_and_broken_configuration_are_reported(tmp_path: Path) -> None:
    project = create_project(tmp_path / "blank")  # blank template: criteria not filled in yet
    nbib = tmp_path / "r.nbib"
    nbib.write_text(
        "PMID- 1\nTI  - Retracted study\nAB  - " + ABSTRACT + "\nPT  - Retracted Publication\n",
        encoding="utf-8",
    )
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"] = {"exclude_retracted": False}
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    load(project, nbib, "R")
    result = invoke("check", project.root, "--lang", "en")
    assert result.exit_code == 4
    assert "1 retracted publication(s) stay in the run" in result.output
    assert "project.yaml needs attention: criteria" in result.output


def test_errors_of_the_environment(project: Workspace, tmp_path: Path) -> None:
    missing = invoke("check", tmp_path / "nothing", "--lang", "en")
    assert missing.exit_code == 1 and "Error E404" in missing.output
    load(project, ris(tmp_path, "l.ris", [("A", ABSTRACT)]), "L")
    holder = project.lock()
    holder.acquire()
    try:
        busy = invoke("check", project.root, "--lang", "en")
        assert busy.exit_code == 2 and "Error E402" in busy.output
        assert invoke("check", project.root, "--read-only", "--lang", "en").exit_code == 0
    finally:
        holder.release()


def test_the_fixture_trio_reports_the_oracle_duplicates(project: Workspace) -> None:
    names = (
        "example_db_nr1_total-15_duplicates-0.ris",
        "example_db_nr2_total-10_duplicates-3.ris",
        "example_db_nr3_total-8_duplicates-2.ris",
    )
    for index, name in enumerate(names, start=1):
        load(project, DATA / name, f"Db{index}")
    data = json.loads(CliRunner().invoke(app, ["check", str(project.root), "--json"]).stdout)
    assert data["records"] == 31 and data["duplicates"] == 18  # oracle: 13 unique DOIs
    assert data["status"] == "error"  # none of these fixtures has an abstract
