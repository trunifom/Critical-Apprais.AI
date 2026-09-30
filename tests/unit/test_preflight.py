"""Tests for the preflight: one file before the import, one project before the run (T-M2-04)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crapai.enums import PreflightIssueCode, PreflightStatus
from crapai.errors import StorageError
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import (
    PreflightConfig,
    ProjectIssue,
    check_file,
    check_project,
)
from crapai.services.project import create_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 3


def ris(tmp_path: Path, name: str, records: list[tuple[str, str]], extra: str = "") -> Path:
    """A RIS file with (title, abstract) records; an empty abstract means no AB line."""
    parts = []
    for index, (title, abstract) in enumerate(records):
        lines = ["TY  - JOUR", f"TI  - {title}", f"DO  - 10.1/{name}{index}"]
        if abstract:
            lines.append(f"AB  - {abstract}")
        if extra:
            lines.append(extra)
        parts.append("\n".join([*lines, "ER  - "]))
    path = tmp_path / name
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


# --- one file, before the import ---


def test_a_good_file_is_ok() -> None:
    result = check_file(DATA / "pubmed-adhd-set.nbib", "PubMed")
    assert (result.records_total, result.records_with_abstract) == (100, 94)
    assert result.status is PreflightStatus.OK and result.issues == []
    assert result.format == "nbib" and result.message_key == "preflight.status.ok"
    assert (result.filename, result.label) == ("pubmed-adhd-set.nbib", "PubMed")


def test_zotero_export_with_22_percent_abstracts_is_a_warning() -> None:
    result = check_file(DATA / "pubmed_adhd_converted-zotero.ris", "Zotero")
    oracle = EXPECTED["data/pubmed_adhd_converted-zotero.ris"]
    assert (result.records_total, result.records_with_abstract) == (
        oracle["records"],
        oracle["abstracts"],
    )
    assert result.status is PreflightStatus.WARNING
    assert result.issues == [PreflightIssueCode.LOW_ABSTRACT_RATIO]
    assert result.message_key == "preflight.status.warn_low_abstracts"


def test_a_file_without_any_abstract_is_an_error() -> None:
    result = check_file(DATA / "example_db_nr1_total-15_duplicates-0.ris", "Db1")
    assert result.status is PreflightStatus.ERROR and result.records_total == 13
    assert result.issues == [PreflightIssueCode.NO_ABSTRACTS]
    assert result.message_key == "preflight.status.error_no_abstracts"


@pytest.mark.parametrize(
    ("with_abstract", "status"), [(6, PreflightStatus.OK), (5, PreflightStatus.WARNING)]
)
def test_the_sixty_percent_boundary(
    tmp_path: Path, with_abstract: int, status: PreflightStatus
) -> None:
    rows = [(f"Title {i}", ABSTRACT if i < with_abstract else "") for i in range(10)]
    result = check_file(ris(tmp_path, "b.ris", rows), "B")
    assert result.records_with_abstract == with_abstract and result.status is status


def test_the_threshold_is_configurable(tmp_path: Path) -> None:
    path = ris(tmp_path, "c.ris", [("A", ABSTRACT), ("B", "")])
    assert check_file(path, "C").status is PreflightStatus.WARNING  # 50 % < 60 %
    lenient = check_file(path, "C", config=PreflightConfig(min_abstract_ratio_warn=0.4))
    assert lenient.status is PreflightStatus.OK


def test_unusable_files_become_error_results_and_never_raise(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n...")
    unsupported = check_file(pdf, "P")
    assert unsupported.issues == [PreflightIssueCode.UNSUPPORTED_TYPE]
    assert unsupported.error_code == "E101" and unsupported.status is PreflightStatus.ERROR

    empty = tmp_path / "empty.ris"
    empty.write_bytes(b"")
    assert check_file(empty, "E").issues == [PreflightIssueCode.NO_RECORDS]

    notes = tmp_path / "notes.txt"
    notes.write_text("Dear all, attached\n", encoding="utf-8")
    parse = check_file(notes, "N")
    assert parse.issues == [PreflightIssueCode.PARSE_FAILED] and parse.error_code == "E101"

    missing = check_file(tmp_path / "nope.ris", "M")
    assert missing.status is PreflightStatus.ERROR and missing.error_code == "E101"
    assert missing.issues == [PreflightIssueCode.PARSE_FAILED]


def test_column_problems_of_a_table_are_reported_with_their_code(tmp_path: Path) -> None:
    table = tmp_path / "in.csv"
    table.write_text("Name,Body\nA,x\nB,y\n", encoding="utf-8")
    failed = check_file(table, "T")
    assert failed.error_code == "E104" and failed.issues == [PreflightIssueCode.PARSE_FAILED]
    fixed = check_file(table, "T", mapping={"title": "Name", "abstract": "Body"})
    assert fixed.status is PreflightStatus.OK and fixed.records_total == 2


def test_the_file_check_writes_nothing(tmp_path: Path) -> None:
    source = ris(tmp_path, "w.ris", [("A", ABSTRACT)])
    before = sorted(p.name for p in tmp_path.iterdir())
    check_file(source, "W")
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no sources/, no records file
    assert source.read_text(encoding="utf-8").startswith("TY  - JOUR")


# --- the project, before the run ---


def set_retracted_option(workspace: Workspace, value: bool) -> None:
    import yaml

    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"]["exclude_retracted"] = value
    workspace.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def no_prefilters(project: Workspace) -> None:
    """The demo template filters by year; these tests are about abstracts, not metadata."""
    import yaml

    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"] = {}
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


def add(
    project: Workspace, tmp_path: Path, name: str, rows: list[tuple[str, str]], label: str
) -> None:
    import_source(project, ImportRequest(ris(tmp_path, name, rows), label=label))


def test_empty_project_is_an_error(project: Workspace) -> None:
    report = check_project(project)
    assert report.status is PreflightStatus.ERROR and report.issues == [ProjectIssue.NO_RECORDS]
    assert report.records == 0 and report.sources == []


def test_records_without_any_abstract_leave_nothing_to_screen(project: Workspace) -> None:
    first = DATA / "example_db_nr1_total-15_duplicates-0.ris"
    import_source(project, ImportRequest(first, label="A"))
    no_prefilters(project)
    report = check_project(project)
    assert report.status is PreflightStatus.ERROR
    assert ProjectIssue.NOTHING_TO_SCREEN in report.issues
    assert report.records == 13 and report.valid_for_model == 0
    assert report.by_reason == {"NO_ABSTRACT": 13}


def test_title_only_mode_makes_the_same_project_screenable(project: Workspace) -> None:
    import yaml

    first = DATA / "example_db_nr1_total-15_duplicates-0.ris"
    import_source(project, ImportRequest(first, label="A"))
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["screening"]["include_title_only"] = True
    data["prefilters"] = {}
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    report = check_project(project)
    assert report.valid_for_model == 13 and ProjectIssue.NOTHING_TO_SCREEN not in report.issues


def test_two_sources_with_different_coverage(project: Workspace, tmp_path: Path) -> None:
    add(project, tmp_path, "good.ris", [(f"G{i}", ABSTRACT) for i in range(5)], "Good")
    poor_rows = [(f"P{i}", ABSTRACT if i == 0 else "") for i in range(5)]
    add(project, tmp_path, "poor.ris", poor_rows, "Poor")
    report = check_project(project)
    good, poor = report.sources
    assert (good.label, good.records, good.with_abstract, good.status) == (
        "Good",
        5,
        5,
        PreflightStatus.OK,
    )
    assert (poor.label, poor.with_abstract, poor.status) == ("Poor", 1, PreflightStatus.WARNING)
    assert poor.issues == [ProjectIssue.LOW_ABSTRACT_RATIO] and good.issues == []
    assert report.status is PreflightStatus.WARNING
    assert report.valid_for_model == 6 and report.by_reason == {"NO_ABSTRACT": 4}


def test_duplicates_are_marked_and_counted_per_source(project: Workspace, tmp_path: Path) -> None:
    two = DATA / "example_db_nr2_total-10_duplicates-3.ris"
    three = DATA / "example_db_nr3_total-8_duplicates-2.ris"
    import_source(project, ImportRequest(two, label="Two"))
    import_source(project, ImportRequest(three, label="Three"))
    report = check_project(project)
    assert report.records == 18 and report.duplicates > 5  # within and across the two files
    assert sum(s.duplicates for s in report.sources) == report.duplicates
    assert report.by_reason.get("DUPLICATE") == report.duplicates
    assert sum(report.by_reason.values()) + report.valid_for_model == 18


def test_suspect_abstracts_and_included_retracted_studies_are_warned_about(
    project: Workspace, tmp_path: Path
) -> None:
    set_retracted_option(project, False)  # the demo project excludes them; here they stay in
    garbled = "cdoemveplaonpyinsgtrattegfic " * 40
    add(project, tmp_path, "s.ris", [("Fine", ABSTRACT), ("Broken", garbled)], "S")
    nbib = tmp_path / "r.nbib"
    nbib.write_text(
        "PMID- 1\nTI  - Retracted study\nAB  - " + ABSTRACT + "\nPT  - Retracted Publication\n",
        encoding="utf-8",
    )
    import_source(project, ImportRequest(nbib, label="R"))
    report = check_project(project)
    assert {ProjectIssue.SUSPECT_ABSTRACTS, ProjectIssue.RETRACTED_INCLUDED} <= set(report.issues)
    assert report.retracted_included == 1 and report.quality["suspect_concat"] == 1
    assert report.status is PreflightStatus.WARNING and report.valid_for_model == 3


def test_excluding_retracted_studies_removes_the_warning(
    project: Workspace, tmp_path: Path
) -> None:
    nbib = tmp_path / "r.nbib"
    nbib.write_text(
        "PMID- 1\nTI  - Retracted study\nAB  - " + ABSTRACT + "\nPT  - Retracted Publication\n",
        encoding="utf-8",
    )
    import_source(project, ImportRequest(nbib, label="R"))
    set_retracted_option(project, True)
    report = check_project(project)
    assert report.retracted_included == 0 and report.by_reason == {"RETRACTED": 1}
    assert ProjectIssue.RETRACTED_INCLUDED not in report.issues
    assert report.status is PreflightStatus.ERROR  # and now nothing is left to screen


def test_an_unfinished_project_file_is_a_warning_not_a_crash(tmp_path: Path) -> None:
    project = create_project(tmp_path / "blank")  # blank template: criteria still empty
    add(project, tmp_path, "a.ris", [("A", ABSTRACT)], "A")
    report = check_project(project)
    assert ProjectIssue.CONFIG_INVALID in report.issues
    assert report.config_problem == "criteria: at least one inclusion criterion is required"
    assert report.status is PreflightStatus.WARNING
    project.project_yaml.unlink()
    assert check_project(project).config_problem == "project.yaml is missing"


def test_update_false_reads_only(project: Workspace, tmp_path: Path) -> None:
    rows = [("Dup", ABSTRACT), ("Dup", ABSTRACT), ("No abstract", "")]
    add(project, tmp_path, "u.ris", rows, "U")
    before = project.records_csv.read_bytes()
    report = check_project(project, update=False)
    assert report.updated is False and project.records_csv.read_bytes() == before
    assert report.duplicates == 0  # nothing was marked yet
    updated = check_project(project)
    assert updated.updated is True and updated.duplicates == 1
    assert read_records(project.records_csv)[1].is_duplicate is True


def test_update_is_idempotent(project: Workspace, tmp_path: Path) -> None:
    add(project, tmp_path, "i.ris", [("A", ABSTRACT), ("A", ABSTRACT), ("Front-matter", "")], "I")
    first = check_project(project)
    content = project.records_csv.read_bytes()
    second = check_project(project)
    assert project.records_csv.read_bytes() == content
    assert (first.by_reason, first.valid_for_model) == (second.by_reason, second.valid_for_model)
    assert first.by_reason == {"DUPLICATE": 1, "NOT_SCREENABLE": 1}


def test_not_a_project_and_busy_project(project: Workspace, tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        check_project(Workspace(tmp_path / "nothing"))
    assert info.value.code == "E404"
    add(project, tmp_path, "l.ris", [("A", ABSTRACT)], "L")
    holder = project.lock()
    holder.acquire()
    try:
        with pytest.raises(StorageError) as busy:
            check_project(project)
        assert busy.value.code == "E402"
        assert check_project(project, update=False).records == 1  # reading needs no lock
    finally:
        holder.release()
