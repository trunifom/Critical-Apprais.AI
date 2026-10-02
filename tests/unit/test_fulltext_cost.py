"""The cost estimate in full-text mode uses the matched PDF's text, truncated (ADR 0026)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import yaml

from crapai.errors import ConfigError
from crapai.project.workspace import Workspace
from crapai.services.cost import estimate_project
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
RIS_FIXTURE = "example_db_nr2_total-10_duplicates-3.ris"
KNOWN_DOI = "10.2468/eai.2022.005"


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
    workspace = create_project(tmp_path / "review", template="demo")
    import_source(workspace, ImportRequest(DATA / RIS_FIXTURE, label="PubMed"))
    # insert_textbox silently inserts nothing at all once the text overflows the page (a PyMuPDF
    # quirk, confirmed empirically) rather than clipping to what fits, so this stays well under
    # that cliff (~100 repeats on an A4/Letter page at fontsize 10) while still being long enough
    # to exceed a small token budget.
    body = "Methods: a randomised trial of a digital health intervention. " * 70
    archive = tmp_path / "fulltexts.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("paper.pdf", make_pdf(f"DOI: {KNOWN_DOI}\n{body}"))
    import_source(workspace, ImportRequest(archive, label="Fulltext"))
    _edit_yaml(
        workspace,
        {
            "project.mode": "fulltext",
            "screening.prompt_variant": "structured_fulltext",
            "screening.output_format": "structured",
        },
    )
    return workspace


def test_only_the_record_with_a_usable_fulltext_is_estimated(fulltext_project: Workspace) -> None:
    result = estimate_project(fulltext_project)
    assert result.estimate.n_items == 1


def test_a_long_fulltext_is_truncated_before_counting(fulltext_project: Workspace) -> None:
    _edit_yaml(fulltext_project, {"llm.context_tokens": 600})
    small_context = estimate_project(fulltext_project).estimate.item_tokens
    _edit_yaml(fulltext_project, {"llm.context_tokens": 100_000})
    large_context = estimate_project(fulltext_project).estimate.item_tokens
    assert small_context < large_context  # the small context window cut the text shorter


def test_map_reduce_is_refused_for_the_estimate_too(fulltext_project: Workspace) -> None:
    _edit_yaml(fulltext_project, {"screening.fulltext": {"strategy": "map_reduce"}})
    with pytest.raises(ConfigError) as info:
        estimate_project(fulltext_project)
    assert info.value.code == "E203" and "map_reduce" in str(info.value)
