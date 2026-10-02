"""End-to-end: screening in full-text mode (ADR 0026), MockProvider only."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import yaml

from crapai.errors import ConfigError
from crapai.io.records_store import read_records
from crapai.llm.mock_provider import MockProvider
from crapai.project.workspace import Workspace
from crapai.screening.store import RunStore
from crapai.services import screening as svc
from crapai.services.events import read_events
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
RIS_FIXTURE = "example_db_nr2_total-10_duplicates-3.ris"
KNOWN_DOI = "10.2468/eai.2022.005"  # the first record of RIS_FIXTURE


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _edit_yaml(workspace: Workspace, changes: dict[str, Any]) -> None:
    data: dict[str, Any] = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    for key, value in changes.items():
        section, field = key.split(".")
        data.setdefault(section, {})[field] = value
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def fulltext_project(tmp_path: Path) -> Workspace:
    """A demo project, one RIS import, and one PDF matched to its first record by DOI."""
    workspace = create_project(tmp_path / "review", template="demo")
    import_source(workspace, ImportRequest(DATA / RIS_FIXTURE, label="PubMed"))
    body = "Methods: a randomised trial of a digital health intervention. " * 20
    archive = tmp_path / "fulltexts.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("paper.pdf", make_pdf(f"DOI: {KNOWN_DOI}\n{body}"))
    import_source(workspace, ImportRequest(archive, label="Fulltext"))
    _edit_yaml(
        workspace,
        {
            "project.mode": "fulltext",
            "llm.provider": "mock",
            "llm.model": "S1",
            "llm.base_url": None,
            "screening.prompt_variant": "structured_fulltext",
            "screening.output_format": "structured",
        },
    )
    return workspace


def test_only_the_record_with_a_usable_fulltext_is_screened(fulltext_project: Workspace) -> None:
    result = svc.screen_project(
        fulltext_project,
        svc.RunOptions(provider=MockProvider("S1"), install_signal_handler=False),
    )
    assert result.summary.state == "completed"
    assert result.summary.total == 1  # the project has 10 records, only 1 has a matched PDF


def test_the_result_is_keyed_by_the_anchors_study_uid(fulltext_project: Workspace) -> None:
    records = read_records(fulltext_project.records_csv)
    anchor = next(r for r in records if r.doi == KNOWN_DOI)
    result = svc.screen_project(
        fulltext_project,
        svc.RunOptions(provider=MockProvider("S1"), install_signal_handler=False),
    )
    (row,) = RunStore(result.folder).last_results().values()
    assert row.study_uid == anchor.study_uid and row.status == "ok"
    assert row.decision in ("INCLUDE", "EXCLUDE", "UNCERTAIN")


def test_a_completed_run_writes_a_fulltext_prisma_event(fulltext_project: Workspace) -> None:
    svc.screen_project(
        fulltext_project,
        svc.RunOptions(provider=MockProvider("S1"), install_signal_handler=False),
    )
    events = read_events(fulltext_project.events_jsonl)
    assert any(e.event_type == "SCREEN_FT" for e in events)
    assert not any(e.event_type == "SCREEN_TA" for e in events)  # this run was fulltext, not TA


def test_map_reduce_is_refused_before_a_run_starts(fulltext_project: Workspace) -> None:
    _edit_yaml(fulltext_project, {"screening.fulltext": {"strategy": "map_reduce"}})
    with pytest.raises(ConfigError) as info:
        svc.screen_project(
            fulltext_project,
            svc.RunOptions(provider=MockProvider("S1"), install_signal_handler=False),
        )
    assert info.value.code == "E203" and "map_reduce" in str(info.value)


def test_resuming_a_fulltext_run_re_reads_the_same_pdf(fulltext_project: Workspace) -> None:
    # S7 with after=0: the very first call is refused (401) -> state "failed", resumable.
    first = svc.screen_project(
        fulltext_project,
        svc.RunOptions(
            provider=MockProvider("S7", after=0), install_signal_handler=False
        ),
    )
    assert first.summary.state == "failed"
    second = svc.screen_project(
        fulltext_project,
        svc.RunOptions(
            resume=first.run_id, provider=MockProvider("S1"), install_signal_handler=False
        ),
    )
    assert second.summary.state == "completed" and second.resumed is True
    (row,) = RunStore(second.folder).last_results().values()
    assert row.status == "ok"  # the resumed plan re-extracted the PDF text successfully
