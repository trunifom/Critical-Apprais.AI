"""Tests for the DOCX summary report writer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from crapai.config.models import ProjectConfig
from crapai.errors import ConfigError
from crapai.prisma.flow import PrismaFlow
from crapai.stats.results import Analysis

pytest.importorskip("docx")

from crapai.io.writers.docx_report import write_docx_report  # noqa: E402


def config(**overrides: object) -> ProjectConfig:
    data: dict[str, object] = {
        "project": {"title": "Exercise and depression review"},
        "objectives": ["Does exercise reduce depressive symptoms?"],
        "criteria": {
            "inclusion": {"Population": "Adults"},
            "exclusion": {"Study Design": "Case reports"},
        },
    }
    data.update(overrides)
    return ProjectConfig.model_validate(data)


def flow(**overrides: int) -> PrismaFlow:
    values: dict[str, int] = {
        "records_identified_total": 100,
        "duplicates_removed": 20,
        "records_screened_title_abstract": 75,
        "records_excluded_title_abstract": 50,
        "studies_included_in_review": 15,
    }
    values.update(overrides)
    return PrismaFlow(**values)  # type: ignore[arg-type]


def paragraphs(path: Path) -> list[str]:
    from docx import Document

    return [p.text for p in Document(path).paragraphs]


def test_the_report_carries_title_objectives_and_criteria(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    write_docx_report(path, config(), flow(), None)
    text = "\n".join(paragraphs(path))
    assert "Exercise and depression review" in text
    assert "Does exercise reduce depressive symptoms?" in text
    assert "Include Population: Adults" in text
    assert "Exclude Study Design: Case reports" in text


def test_the_flow_table_has_the_core_numbers(tmp_path: Path) -> None:
    from docx import Document

    path = tmp_path / "report.docx"
    write_docx_report(path, config(), flow(), None)
    table = Document(path).tables[0]
    rows = {row.cells[0].text: row.cells[1].text for row in table.rows[1:]}
    assert rows["Records identified"] == "100"
    assert rows["Duplicates removed"] == "20"
    assert rows["Studies included in review"] == "15"
    assert "Reports assessed for eligibility (full text)" not in rows  # no full-text stage here


def test_the_fulltext_stage_appears_only_when_it_happened(tmp_path: Path) -> None:
    from docx import Document

    path = tmp_path / "report.docx"
    write_docx_report(
        path, config(), flow(reports_assessed_for_eligibility=25, reports_excluded_fulltext=10), None
    )  # fmt: skip
    table = Document(path).tables[0]
    rows = {row.cells[0].text: row.cells[1].text for row in table.rows[1:]}
    assert rows["Reports assessed for eligibility (full text)"] == "25"
    assert rows["Excluded (full text)"] == "10"


def test_without_a_run_the_results_section_says_so(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    write_docx_report(path, config(), flow(), None)
    assert "No finished screening run yet." in "\n".join(paragraphs(path))


def test_with_a_run_the_results_table_shows_outcomes(tmp_path: Path) -> None:
    from docx import Document

    analysis = Analysis(total=75, by_outcome={"INCLUDE": 20, "EXCLUDE": 50, "UNCERTAIN": 5})
    path = tmp_path / "report.docx"
    write_docx_report(path, config(), flow(), ("run-001", analysis))
    text = "\n".join(paragraphs(path))
    assert "75 record(s) screened" in text and "run-001" in text
    outcome_table = Document(path).tables[1]
    rows = {row.cells[0].text: row.cells[1].text for row in outcome_table.rows[1:]}
    assert rows == {"EXCLUDE": "50", "INCLUDE": "20", "UNCERTAIN": "5"}


def test_without_a_description_no_blank_paragraph_is_added(tmp_path: Path) -> None:
    """config() sets no project.description; build_report must skip that paragraph entirely
    rather than add an empty one."""
    path = tmp_path / "report.docx"
    write_docx_report(path, config(), flow(), None)
    assert "" not in paragraphs(path)


def test_a_description_is_shown_right_after_the_title(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    described = config(project={"title": "T", "description": "A short description."})
    write_docx_report(path, described, flow(), None)
    texts = paragraphs(path)
    assert texts[0] == "T" and texts[1] == "A short description."


def test_without_python_docx_is_a_clear_e203(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in list(sys.modules):
        if name == "docx" or name.startswith("docx."):
            monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(ConfigError) as info:
        write_docx_report(tmp_path / "report.docx", config(), flow(), None)
    assert info.value.code == "E203" and "python-docx" in info.value.user_message
