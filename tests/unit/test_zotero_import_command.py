"""`crapai zotero-import` (ADR 0030): the dedicated command for the read-only Zotero pull."""

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
from crapai.services.project import create_project

runner = CliRunner()

RIS_TEXT = (
    "TY  - JOUR\nTI  - Exercise therapy for mood disorders\nDO  - 10.1000/zz1\n"
    "AB  - An abstract about exercise and mood.\nER  - \n"
)


def invoke(*args: object, expect: int | None = 0) -> Any:
    result = runner.invoke(app, [str(a) for a in args], catch_exceptions=False)
    if expect is not None:
        assert result.exit_code == expect, result.output
    return result


def make_project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["zotero"] = {"library_id": "123", "api_key_env": ""}
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return workspace


@pytest.fixture(autouse=True)
def mock_zotero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real client with a scripted one so no test touches the network."""
    from crapai.services import zotero_import as module
    from crapai.zotero.client import MockZoteroClient

    monkeypatch.setattr(module, "build_client", lambda *a, **kw: MockZoteroClient(RIS_TEXT))


def test_a_sync_imports_the_fetched_records_and_prints_the_summary(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = invoke("zotero-import", workspace.root, "--lang", "en")
    assert "record(s)" in result.output.lower() or "imported" in result.output.lower()
    titles = {r.title for r in read_records(workspace.records_csv)}
    assert titles == {"Exercise therapy for mood disorders"}


def test_json_output_is_machine_readable(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    result = runner.invoke(
        app, ["zotero-import", str(workspace.root), "--json", "--lang", "en"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["records"] == 1 and data["source_label"] == "Zotero"


def test_a_custom_label_is_used(tmp_path: Path) -> None:
    workspace = make_project(tmp_path)
    invoke("zotero-import", workspace.root, "--label", "My Library", "--lang", "en")
    assert {r.source_label for r in read_records(workspace.records_csv)} == {"My Library"}


def test_on_a_non_project_is_e404(tmp_path: Path) -> None:
    result = invoke("zotero-import", tmp_path / "nothing", "--lang", "en", expect=1)
    assert "E404" in result.output
