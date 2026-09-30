"""Tests for the pre-filter service and its place in the pipeline (task T-M2-08)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from crapai.cli import app
from crapai.config.loader import load_project_config
from crapai.io.records_store import read_records
from crapai.prisma.prefilters import PrefilterConfig
from crapai.project.workspace import Workspace
from crapai.services.cost import estimate_project
from crapai.services.dedup import dedup_project
from crapai.services.events import project_flow, read_events
from crapai.services.importing import ImportRequest, import_source
from crapai.services.prefilter import config_from_settings, prefilter_project
from crapai.services.project import create_project
from crapai.services.validity import validate_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5


def ris(tmp_path: Path, rows: list[dict[str, str]], name: str = "p.ris") -> Path:
    parts = []
    for index, row in enumerate(rows):
        lines = ["TY  - JOUR", f"TI  - {row['title']}", f"DO  - 10.1000/p{name}{index}"]
        for tag, key in (("LA", "language"), ("PY", "year"), ("AB", "abstract")):
            if row.get(key, "") != "":
                lines.append(f"{tag}  - {row[key]}")
        lines += [f"M3  - {t}" for t in row.get("types", "").split(";") if t]
        parts.append("\n".join([*lines, "ER  - "]))
    path = tmp_path / name
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


ROWS = [
    {"title": "Good", "language": "eng", "year": "2020", "abstract": ABSTRACT},
    {"title": "French", "language": "fre", "year": "2020", "abstract": ABSTRACT},
    {"title": "Old", "language": "eng", "year": "2001", "abstract": ABSTRACT},
    {"title": "Unknown", "abstract": ABSTRACT},
]


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(ris(tmp_path, ROWS), label="S"))
    return workspace


def set_prefilters(project: Workspace, block: dict[str, Any]) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"] = block
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


def reasons_of(project: Workspace) -> dict[str, str]:
    return {r.title: r.exclusion_reason for r in read_records(project.records_csv)}


def test_the_block_of_project_yaml_becomes_the_configuration(project: Workspace) -> None:
    config = config_from_settings(load_project_config(project.project_yaml).prefilters)
    assert config.language_allow == ("eng", "ger") and config.year_min == 2015
    assert config.type_exclude == ("Editorial", "Letter", "Comment") and config.active


def test_an_empty_block_gives_inactive_filters() -> None:
    from crapai.config.models import Prefilters

    assert not config_from_settings(Prefilters()).active


def test_project_settings_mark_the_records(project: Workspace) -> None:
    summary = prefilter_project(project)
    assert summary.config_source == "project" and summary.active
    assert summary.removed == 2 and summary.records == 4
    assert summary.by_reason == {"PREFILTER_LANGUAGE": 1, "PREFILTER_YEAR": 1}
    assert summary.passed_on_missing == {"language": 1, "year": 1, "type": 4}
    assert reasons_of(project) == {
        "Good": "",
        "French": "PREFILTER_LANGUAGE",
        "Old": "PREFILTER_YEAR",
        "Unknown": "",  # no language and no year: on_missing is pass
    }


def test_the_unknown_record_is_sent_on_by_default_and_excluded_on_request(
    project: Workspace,
) -> None:
    set_prefilters(project, {"language": {"allow": ["eng"], "on_missing": "exclude"}})
    prefilter_project(project)
    assert reasons_of(project)["Unknown"] == "PREFILTER_LANGUAGE"


def test_a_given_configuration_overrides_the_project(project: Workspace) -> None:
    summary = prefilter_project(project, config=PrefilterConfig(year_max=2010))
    assert summary.config_source == "given" and summary.by_reason == {"PREFILTER_YEAR": 2}


def test_no_filters_configured_marks_nothing_and_leaves_the_file_alone(project: Workspace) -> None:
    set_prefilters(project, {})
    before = project.records_csv.read_bytes()
    summary = prefilter_project(project)
    assert summary.removed == 0 and summary.active is False
    assert project.records_csv.read_bytes() == before


def test_an_invalid_project_yaml_means_no_filters(project: Workspace) -> None:
    project.project_yaml.write_text("prefilters: [broken", encoding="utf-8")
    summary = prefilter_project(project)
    assert summary.config_source == "default" and summary.removed == 0


def test_running_twice_changes_nothing_and_loosening_clears_marks(project: Workspace) -> None:
    prefilter_project(project)
    once = project.records_csv.read_bytes()
    prefilter_project(project)
    assert project.records_csv.read_bytes() == once
    set_prefilters(project, {"year": {"min": 2000}})
    prefilter_project(project)
    assert set(reasons_of(project).values()) == {""}


def test_records_are_never_removed(project: Workspace) -> None:
    prefilter_project(project)
    assert len(read_records(project.records_csv)) == 4


def test_pipeline_order_dedup_prefilter_validity(project: Workspace, tmp_path: Path) -> None:
    second = ris(tmp_path, [{"title": "French", "language": "fre", "year": "2020"}], "q.ris")
    import_source(project, ImportRequest(second, label="T"))
    dedup_project(project)
    prefilter_project(project)
    validate_project(project)
    marks = [(r.source_label, r.exclusion_reason) for r in read_records(project.records_csv)]
    # same title but different DOIs: not a duplicate (ADR 0018), so the language filter applies
    assert marks[-1] == ("T", "PREFILTER_LANGUAGE")
    first_run = project.records_csv.read_bytes()
    for _ in range(2):
        dedup_project(project)
        prefilter_project(project)
        validate_project(project)
    assert project.records_csv.read_bytes() == first_run


def test_filtered_records_do_not_reach_the_model_or_the_cost(project: Workspace) -> None:
    prefilter_project(project)
    validate_project(project)
    assert estimate_project(project).estimate.n_items == 2  # Good and Unknown


def test_the_event_and_the_flow_count_the_removed_records(project: Workspace) -> None:
    dedup_project(project)
    prefilter_project(project)
    validate_project(project)
    event = [e for e in read_events(project.events_jsonl) if e.kind == "prefilter"][-1]
    assert event.payload["removed"] == 2
    flow, warnings = project_flow(project)
    assert flow.records_identified_total == 4 and flow.records_after_deduplication == 4
    assert flow.records_removed_before_screening_other == 2
    assert flow.prefilter_reasons == {"PREFILTER_LANGUAGE": 1, "PREFILTER_YEAR": 1}
    assert flow.records_to_screen == 2 and warnings == []


def test_excluded_retracted_studies_join_the_prefilter_count_in_the_flow(
    project: Workspace,
) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["prefilters"]["exclude_retracted"] = True
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    records = read_records(project.records_csv)
    from crapai.io.records_store import write_records

    records[0] = records[0].model_copy(update={"is_retracted": True})
    write_records(project.records_csv, records)
    dedup_project(project)
    prefilter_project(project)
    validate_project(project)
    flow, _ = project_flow(project)
    assert flow.prefilter_reasons["RETRACTED"] == 1
    assert flow.records_removed_before_screening_other == 3 and flow.records_to_screen == 1


def test_crapai_check_runs_the_prefilters_and_explains_the_reasons(project: Workspace) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["check", str(project.root), "--lang", "en"])
    assert "PREFILTER_LANGUAGE: 1 (language not allowed by the pre-filter)" in result.output
    assert "PREFILTER_YEAR: 1 (year outside the pre-filter range)" in result.output
    german = runner.invoke(app, ["check", str(project.root), "--lang", "de"])
    assert "Sprache vom Vorfilter nicht zugelassen" in german.output
    data = json.loads(runner.invoke(app, ["check", str(project.root), "--json"]).stdout)
    assert data["by_reason"] == {"PREFILTER_LANGUAGE": 1, "PREFILTER_YEAR": 1}
    assert data["valid_for_model"] == 2
