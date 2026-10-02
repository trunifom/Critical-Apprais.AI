"""Tests for the optional Jev pre-filter service (ADR 0029)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crapai.config.models import AiPrefilterOptions
from crapai.errors import AuthError, ConfigError
from crapai.io.records_store import read_records, write_records
from crapai.llm.jev_client import MockJevClient
from crapai.project.workspace import Workspace
from crapai.services.ai_prefilter import ai_prefilter_project, build_client
from crapai.services.cost import estimate_ai_prefilter
from crapai.services.events import project_flow, read_events
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import check_project
from crapai.services.project import create_project

ABSTRACT_OK = "Adults with depression received a structured exercise programme over twelve weeks."

ROWS = [
    {"title": "Clearly off-topic JEV_TRUE_HIGH", "abstract": "JEV_TRUE_HIGH unrelated topic"},
    {"title": "Borderline JEV_TRUE_LOW", "abstract": "JEV_TRUE_LOW text"},
    {"title": "On topic JEV_FALSE", "abstract": "JEV_FALSE " + ABSTRACT_OK},
    {"title": "Ordinary", "abstract": ABSTRACT_OK},
]


def ris(tmp_path: Path, rows: list[dict[str, str]], name: str = "p.ris") -> Path:
    parts = []
    for index, row in enumerate(rows):
        lines = ["TY  - JOUR", f"TI  - {row['title']}", f"DO  - 10.1000/p{name}{index}"]
        if row.get("abstract", "") != "":
            lines.append(f"AB  - {row['abstract']}")
        parts.append("\n".join([*lines, "ER  - "]))
    path = tmp_path / name
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def enable_ai_prefilter(project: Workspace, **overrides: object) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["ai_prefilter"] = {"enabled": True, "model": "mock", **overrides}
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


def reasons_of(project: Workspace) -> dict[str, str]:
    return {r.title: r.exclusion_reason for r in read_records(project.records_csv)}


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(ris(tmp_path, ROWS), label="S"))
    enable_ai_prefilter(workspace)
    return workspace


def test_disabled_by_default_refuses_with_a_clear_error(tmp_path: Path) -> None:
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(ris(tmp_path, ROWS), label="S"))
    with pytest.raises(ConfigError) as info:
        ai_prefilter_project(workspace)
    assert info.value.code == "E203"


def test_only_high_confidence_true_answers_mark_a_record(project: Workspace) -> None:
    summary = ai_prefilter_project(project)
    assert summary.records == 4 and summary.eligible == 4 and summary.checked == 4
    assert summary.marked == 1
    reasons = reasons_of(project)
    assert reasons["Clearly off-topic JEV_TRUE_HIGH"] == "AI_PREFILTER_JEV"
    assert reasons["Borderline JEV_TRUE_LOW"] == ""  # true, but below the confidence floor
    assert reasons["On topic JEV_FALSE"] == ""
    assert reasons["Ordinary"] == ""


def test_exclusion_details_and_extra_json_are_filled(project: Workspace) -> None:
    ai_prefilter_project(project)
    marked = next(
        r for r in read_records(project.records_csv) if r.exclusion_reason == "AI_PREFILTER_JEV"
    )
    assert "Jev" in marked.exclusion_details and "confidence" in marked.exclusion_details
    assert marked.extra_json["jev"]["confidence"] == pytest.approx(0.95)
    assert marked.extra_json["jev"]["model"] == "mock"


def test_an_already_excluded_record_is_never_offered_to_jev(project: Workspace) -> None:
    records = read_records(project.records_csv)
    records[-1] = records[-1].model_copy(update={"exclusion_reason": "NO_ABSTRACT"})
    write_records(project.records_csv, records)
    summary = ai_prefilter_project(project)
    assert summary.eligible == 3  # the pre-excluded record was skipped, not sent


def test_running_twice_is_stable(project: Workspace) -> None:
    ai_prefilter_project(project)
    once = project.records_csv.read_bytes()
    ai_prefilter_project(project)
    assert project.records_csv.read_bytes() == once


def test_a_mark_survives_crapai_check(project: Workspace) -> None:
    ai_prefilter_project(project)
    check_project(project, update=True)
    assert reasons_of(project)["Clearly off-topic JEV_TRUE_HIGH"] == "AI_PREFILTER_JEV"


def test_the_event_and_flow_count_the_marked_records(project: Workspace) -> None:
    ai_prefilter_project(project)
    event = next(e for e in read_events(project.events_jsonl) if e.kind == "ai_prefilter_jev")
    assert event.payload["removed"] == 1
    flow, warnings = project_flow(project)
    assert flow.records_removed_by_ai_prefilter == 1
    assert flow.ai_prefilter_reasons == {"AI_PREFILTER_JEV": 1}
    assert warnings == []


def test_build_client_requires_a_key_unless_mock() -> None:
    with pytest.raises(AuthError):
        build_client(AiPrefilterOptions(enabled=True), environ={})
    assert isinstance(build_client(AiPrefilterOptions(enabled=True, model="mock")), MockJevClient)


def test_a_raised_confidence_floor_marks_fewer_records(project: Workspace) -> None:
    enable_ai_prefilter(project, confidence_floor=0.99)
    summary = ai_prefilter_project(project)
    assert summary.marked == 0  # the mock's 0.95 no longer clears the raised floor


def test_estimate_counts_the_same_records_a_real_run_would_offer(project: Workspace) -> None:
    estimate = estimate_ai_prefilter(project)
    assert estimate.n_items == 4 and estimate.tokens_in > 0
    assert estimate.price_file_found is False and estimate.cost is None


def test_estimate_uses_the_price_file_when_present(project: Workspace) -> None:
    project.pricing_csv.write_text(
        "provider,model,price_input_per_1k,price_output_per_1k,currency\n"
        "typesafe,mock,0.042,0,USD\n",
        encoding="utf-8",
    )
    estimate = estimate_ai_prefilter(project)
    assert estimate.price_file_found is True
    assert estimate.cost == pytest.approx(estimate.tokens_in / 1000 * 0.042)


def test_estimate_ignores_already_excluded_records(project: Workspace) -> None:
    records = read_records(project.records_csv)
    records[-1] = records[-1].model_copy(update={"exclusion_reason": "NO_ABSTRACT"})
    write_records(project.records_csv, records)
    assert estimate_ai_prefilter(project).n_items == 3
