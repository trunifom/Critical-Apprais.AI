"""Tests for the event file and the flow of a real project (task T-M2-07)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from crapai.enums import DuplicatesReportingMode
from crapai.errors import StorageError
from crapai.prisma import events as ev
from crapai.project.workspace import Workspace
from crapai.services.dedup import dedup_project
from crapai.services.events import append_events, project_flow, read_events, reporting_mode
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project
from crapai.services.validity import validate_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
TRIO = (
    "example_db_nr1_total-15_duplicates-0.ris",
    "example_db_nr2_total-10_duplicates-3.ris",
    "example_db_nr3_total-8_duplicates-2.ris",
)


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def load_trio(project: Workspace) -> None:
    for index, name in enumerate(TRIO, start=1):
        import_source(project, ImportRequest(DATA / name, label=f"Db{index}"))


# --- the file ---------------------------------------------------------------------------------


def test_append_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "events.jsonl"
    first = [ev.source_imported("A", "a", "ris", 1), ev.source_imported("B", "b", "ris", 2)]
    assert append_events(path, first) == 2
    assert append_events(path, [ev.source_imported("C", "c", "ris", 3)]) == 1
    assert [e.source_label for e in read_events(path)] == ["A", "B", "C"]
    assert path.read_text(encoding="utf-8").count("\n") == 3


def test_nothing_to_append_does_not_create_the_file(tmp_path: Path) -> None:
    assert append_events(tmp_path / "e.jsonl", []) == 0
    assert not (tmp_path / "e.jsonl").exists()
    assert read_events(tmp_path / "e.jsonl") == []


def test_a_half_written_last_line_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "e.jsonl"
    append_events(path, [ev.source_imported("A", "a", "ris", 1)])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"step":"imp')
    with caplog.at_level(logging.WARNING):
        assert len(read_events(path)) == 1
    assert "unreadable last line" in caplog.text


def test_an_unreadable_line_in_the_middle_is_e404(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    append_events(path, [ev.source_imported("A", "a", "ris", 1)])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("garbage\n")
    append_events(path, [ev.source_imported("B", "b", "ris", 1)])
    with pytest.raises(StorageError) as info:
        read_events(path)
    assert info.value.code == "E404" and info.value.details["line"] == 2


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    append_events(path, [ev.source_imported("A", "a", "ris", 1)])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n\n")
    assert len(read_events(path)) == 1


# --- the services write events ----------------------------------------------------------------


def test_an_import_writes_one_event(project: Workspace) -> None:
    import_source(project, ImportRequest(DATA / TRIO[0], label="Db1"))
    (event,) = read_events(project.events_jsonl)
    assert event.event_type == "SOURCE_IMPORTED" and event.source_label == "Db1"
    assert event.payload["records_identified"] == 13
    assert event.payload["file_type"] == "ris"


def test_a_failed_import_writes_no_event(project: Workspace, tmp_path: Path) -> None:
    bad = tmp_path / "x.ris"
    bad.write_text("not a reference file at all", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - any import error; the point is the event file
        import_source(project, ImportRequest(bad))
    assert not project.events_jsonl.exists()


def test_dedup_writes_a_snapshot_per_source_plus_merge_and_global(project: Workspace) -> None:
    load_trio(project)
    dedup_project(project)
    types = [e.event_type for e in read_events(project.events_jsonl)]
    assert types.count("SOURCE_IMPORTED") == 3
    assert types.count("DEDUP_WITHIN_SOURCE") == 3
    assert types[-2:] == ["MERGE_ALL_SOURCES", "DEDUP_GLOBAL"]


def test_validity_writes_a_validity_event(project: Workspace) -> None:
    load_trio(project)
    validate_project(project)
    last = read_events(project.events_jsonl)[-1]
    assert last.kind == "validity" and last.payload["total_count"] == 31


def test_the_flow_of_the_fixture_trio_matches_the_oracle(project: Workspace) -> None:
    load_trio(project)
    dedup_project(project)
    validate_project(project)
    flow, warnings = project_flow(project)
    assert flow.records_identified_total == 31  # 13 + 10 + 8 records in the three files
    assert flow.duplicates_removed == 18  # oracle: 13 unique DOIs
    assert flow.records_after_deduplication == 13 and flow.records_to_screen == 13
    assert flow.records_identified_by_source == {"Db1": 13, "Db2": 10, "Db3": 8}
    assert warnings == []


def test_repeating_dedup_and_validity_changes_no_number(project: Workspace) -> None:
    load_trio(project)
    dedup_project(project)
    validate_project(project)
    first, _ = project_flow(project)
    for _ in range(3):
        dedup_project(project)
        validate_project(project)
    assert project_flow(project)[0] == first


def test_within_and_across_source_duplicates_are_told_apart(
    project: Workspace, tmp_path: Path
) -> None:
    text = "TY  - JOUR\nTI  - {t}\nDO  - {d}\nER  - \n"
    a = tmp_path / "a.ris"
    a.write_text(
        text.format(t="One", d="10.1000/a")
        + text.format(t="One again", d="10.1000/a")
        + text.format(t="Two", d="10.1000/b"),
        encoding="utf-8",
    )
    b = tmp_path / "b.ris"
    b.write_text(
        text.format(t="Two", d="10.1000/b") + text.format(t="Three", d="10.1000/c"),
        encoding="utf-8",
    )
    import_source(project, ImportRequest(a, label="A"))
    import_source(project, ImportRequest(b, label="B"))
    dedup_project(project)
    both, _ = project_flow(project, DuplicatesReportingMode.ALL_BEFORE_SCREENING)
    only_between, _ = project_flow(project, "between_databases_only")
    assert both.records_identified_total == 5 and both.duplicates_removed == 2
    assert only_between.duplicates_removed == 1  # the one across A and B
    assert only_between.records_removed_before_screening_other == 1  # the one inside A
    assert both.records_to_screen == only_between.records_to_screen == 3


def test_the_mode_comes_from_project_yaml_unless_given(project: Workspace) -> None:
    assert reporting_mode(project) == DuplicatesReportingMode.ALL_BEFORE_SCREENING
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["dedup"]["reporting_mode"] = "between_databases_only"
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert reporting_mode(project) == DuplicatesReportingMode.BETWEEN_DATABASES_ONLY
    assert project_flow(project)[0].duplicates_reporting_mode == "between_databases_only"
    flow = project_flow(project, DuplicatesReportingMode.ALL_BEFORE_SCREENING)[0]
    assert flow.duplicates_reporting_mode == "all_before_screening"


def test_an_unusable_project_yaml_falls_back_to_the_default_mode(project: Workspace) -> None:
    project.project_yaml.write_text("not: [valid", encoding="utf-8")
    assert reporting_mode(project) == DuplicatesReportingMode.ALL_BEFORE_SCREENING


def test_the_flow_of_a_folder_that_is_no_project_is_e404(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        project_flow(Workspace(tmp_path / "nothing"))
    assert info.value.code == "E404"


def test_a_failing_event_file_does_not_undo_the_work(
    project: Workspace, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import_source(project, ImportRequest(DATA / TRIO[0], label="Db1"))

    def broken(path: Path, events: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr("crapai.services.events.append_events", broken)
    with caplog.at_level(logging.WARNING):
        summary = dedup_project(project)
    assert summary.records == 13
    assert "Could not write events.jsonl" in caplog.text
