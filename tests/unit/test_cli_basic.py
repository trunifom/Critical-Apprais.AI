"""Tests for the command line: init, import, status (task T-M1-11, plan chapter 15.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crapai import cli
from crapai.cli import app
from crapai.io.records_store import read_records

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
RIS10 = DATA / "example_db_nr2_total-10_duplicates-3.ris"
runner = CliRunner()


def invoke(*args: object, catch: bool = False):  # type: ignore[no-untyped-def]
    return runner.invoke(app, [str(a) for a in args], catch_exceptions=catch)


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    folder = tmp_path / "demo"
    assert invoke("init", folder, "--from-template", "demo", "--lang", "en").exit_code == 0
    return folder


def test_acceptance_init_demo_then_import_writes_ten_records(tmp_path: Path) -> None:
    """The card's scenario: `crapai init demo --from-template demo`, then import 10 records."""
    folder = tmp_path / "demo"
    result = invoke("init", folder, "--from-template", "demo", "--lang", "en")
    assert result.exit_code == 0, result.output
    assert "Project created" in result.output and (folder / "project.yaml").is_file()

    result = invoke("import", folder, RIS10, "--label", "A", "--lang", "en")
    # Exit code 4 = "result with warnings" (plan chapter 15.1): these 10 records have no abstracts.
    assert result.exit_code == 4, result.output
    assert 'Imported 10 record(s) from example_db_nr2_total-10_duplicates-3.ris as "A"' in (
        result.output
    )
    assert len(read_records(folder / "data" / "records.csv")) == 10


def test_help_and_version() -> None:
    result = invoke("--help")
    assert result.exit_code == 0
    for word in ("init", "import", "status", "Critical Apprais.AI"):
        assert word in result.output
    assert "SARA" not in result.output.replace("--", "")  # never named after the predecessor
    assert invoke("--version").output.startswith("Critical Apprais.AI ")
    assert invoke().exit_code in (0, 2)  # no arguments: usage help


def test_init_blank_and_errors(tmp_path: Path) -> None:
    folder = tmp_path / "blank"
    result = invoke("init", folder, "--lang", "de")
    assert result.exit_code == 0 and "Projekt angelegt" in result.output
    again = invoke("init", folder, "--lang", "en")
    assert again.exit_code == 1  # user error, not a crash
    assert "Error E404" in again.output and "already a project folder" in again.output
    unknown = invoke("init", tmp_path / "x", "--from-template", "nope", "--lang", "en")
    assert unknown.exit_code == 1 and "Error E203" in unknown.output
    assert "(available: blank, demo)" in unknown.output
    assert not (tmp_path / "x").exists()


def test_import_several_files_with_labels_and_status(demo: Path) -> None:
    result = invoke(
        "import",
        demo,
        DATA / "example_db_nr1_total-15_duplicates-0.ris",
        RIS10,
        "--label",
        "Db1",
        "--label",
        "Db2",
        "--lang",
        "en",
    )
    assert result.exit_code == 4  # warnings: the fixtures hold no abstracts
    assert "Warning: none of these records has an abstract" in result.output
    assert result.output.count("Imported") == 2
    status = invoke("status", demo, "--lang", "en")
    assert status.exit_code == 0
    assert "Records: 23 (with abstract: 0, empty: 0, duplicates: 0)" in status.output
    assert "  Db1: 13" in status.output and "  Db2: 10" in status.output
    assert "Configuration: OK" in status.output


def test_one_label_applies_to_all_files_and_wrong_count_is_an_error(demo: Path) -> None:
    ok = invoke(
        "import",
        demo,
        DATA / "example_AB_nr4.ris",
        DATA / "citation-export.ris",
        "--label",
        "Same",
        "--lang",
        "en",
    )
    assert ok.exit_code == 0
    labels = {r.source_label for r in read_records(demo / "data" / "records.csv")}
    assert labels == {"Same"}
    bad = invoke(
        "import",
        demo,
        RIS10,
        DATA / "example_db_nr3_total-8_duplicates-2.ris",
        "--label",
        "a",
        "--label",
        "b",
        "--label",
        "c",
        "--lang",
        "en",
    )
    assert bad.exit_code == 1 and "3 --label values for 2 files" in bad.output


def test_repeated_import_is_e106_and_force_overrides(demo: Path) -> None:
    assert invoke("import", demo, RIS10, "--lang", "en").exit_code == 4
    again = invoke("import", demo, RIS10, "--lang", "en")
    assert again.exit_code == 1
    assert again.output.count("Error E106") == 1
    assert "Use --force to import it again" in again.output
    forced = invoke("import", demo, RIS10, "--force", "--lang", "en")
    assert forced.exit_code == 4
    assert len(read_records(demo / "data" / "records.csv")) == 20


def test_german_output_from_the_project_language(tmp_path: Path) -> None:
    folder = tmp_path / "p"
    invoke("init", folder, "--from-template", "demo")
    text = (folder / "project.yaml").read_text(encoding="utf-8")
    assert "language: de" in text  # the demo template is German
    result = invoke("import", folder, DATA / "citation-export.ris", "--label", "C")
    assert result.exit_code == 0
    assert "aus citation-export.ris" in result.output and "importiert" in result.output


def test_table_mapping_option_and_bad_mapping(demo: Path, tmp_path: Path) -> None:
    table = tmp_path / "in.csv"
    table.write_text("Name,Body\nPaper one,Text one\nPaper two,Text two\n", encoding="utf-8")
    failed = invoke("import", demo, table, "--lang", "en")
    assert failed.exit_code == 1 and "Error E104" in failed.output
    assert "--map abstract=" in failed.output
    ok = invoke(
        "import", demo, table, "--map", "title=Name", "--map", "abstract=Body", "--lang", "en"
    )
    assert ok.exit_code == 0 and "Columns used: title=Name, abstract=Body" in ok.output
    malformed = invoke("import", demo, table, "--map", "abstract", "--lang", "en")
    assert malformed.exit_code == 1 and "Error E203" in malformed.output


def test_import_errors_for_missing_folder_and_files(tmp_path: Path, demo: Path) -> None:
    not_a_project = invoke("import", tmp_path, RIS10, "--lang", "en")
    assert not_a_project.exit_code == 1 and "Error E404" in not_a_project.output
    missing = invoke("import", demo, tmp_path / "nope.ris", "--lang", "en")
    assert missing.exit_code == 1 and "Error E101" in missing.output


def test_locked_project_is_a_system_error_exit_2(demo: Path) -> None:
    from crapai.project.workspace import Workspace

    holder = Workspace(demo).lock()
    holder.acquire()
    try:
        result = invoke("import", demo, RIS10, "--lang", "en")
    finally:
        holder.release()
    assert result.exit_code == 2 and "Error E402" in result.output


def test_json_output_keeps_stdout_machine_readable(demo: Path) -> None:
    runner_split = CliRunner()
    result = runner_split.invoke(app, ["import", str(demo), str(RIS10), "--label", "A", "--json"])
    assert result.exit_code == 4
    data = json.loads(result.stdout)
    (entry,) = data["imported"]
    assert entry["records"] == 10 and entry["format"] == "ris" and len(entry["sha256"]) == 64
    assert "no_abstracts" in entry["warnings"]
    status = json.loads(runner_split.invoke(app, ["status", str(demo), "--json"]).stdout)
    assert status["records"] == 10 and status["sources"] == {"A": 10}
    assert status["configuration_ok"] is True and status["in_use"] is False


def test_status_of_empty_and_invalid_projects(tmp_path: Path) -> None:
    empty = tmp_path / "e"
    invoke("init", empty, "--from-template", "demo", "--lang", "en")
    out = invoke("status", empty, "--lang", "en").output
    assert "Records: 0" in out and "No records yet" in out
    blank = tmp_path / "b"
    invoke("init", blank, "--lang", "en")
    out = invoke("status", blank, "--lang", "en").output
    assert "Configuration needs attention" in out
    plain = invoke("status", tmp_path, "--lang", "en")
    assert plain.exit_code == 1 and "Error E404" in plain.output


def test_unexpected_error_becomes_e999_with_exit_2(
    demo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(cli, "import_source", boom)
    result = invoke("import", demo, RIS10, "--lang", "en")
    assert result.exit_code == 2
    assert "Error E999" in result.output and "RuntimeError" in result.output
    assert "secret internal detail" not in result.output  # no raw exception text for users


def test_project_log_file_is_written(demo: Path) -> None:
    invoke("import", demo, RIS10, "--lang", "en")
    log = (demo / ".crapai" / "app.log").read_text(encoding="utf-8")
    assert "Imported 10 record(s)" in log
    assert "Title" not in log  # no record content in the log


def test_repeated_table_import_uses_the_mapping_stored_in_project_yaml(
    tmp_path: Path, demo: Path
) -> None:
    import yaml

    table = tmp_path / "export.csv"
    table.write_text("Name,Body\nPaper one,Text one\nPaper two,Text two\n", encoding="utf-8")
    config_path = demo / "project.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["import"] = {"mappings": {"export.csv": {"title": "Name", "abstract": "Body"}}}
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    result = invoke("import", demo, table, "--lang", "en")
    assert result.exit_code == 0, result.output
    assert "Columns used (import.mappings in project.yaml):" in result.output
    assert "title=Name" in result.output and "abstract=Body" in result.output
    german = invoke("import", demo, table, "--force", "--lang", "de")
    assert "Verwendete Spalten (import.mappings in der project.yaml)" in german.output
    as_json = CliRunner().invoke(app, ["import", str(demo), str(table), "--force", "--json"])
    assert json.loads(as_json.stdout)["imported"][0]["mapping_source"] == "project"
