"""Tests for the Zotero import service (ADR 0030)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crapai.config.models import ZoteroSettings
from crapai.errors import AuthError, ImportFailed
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.project import create_project
from crapai.services.zotero_import import build_client, zotero_import_project
from crapai.zotero.client import MockZoteroClient

RIS_ONE = "TY  - JOUR\nTI  - Exercise therapy for mood disorders\nDO  - 10.1000/zz1\nAB  - An abstract.\nER  - \n"
RIS_TWO = (
    "TY  - JOUR\nTI  - Exercise therapy for mood disorders\nDO  - 10.1000/zz1\n"
    "AB  - An abstract.\nER  - \n"
    "TY  - JOUR\nTI  - A second unrelated study\nDO  - 10.1000/zz2\nAB  - Another abstract.\nER  - \n"
)


def set_zotero(project: Workspace, **overrides: object) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data["zotero"] = {"library_id": "123", "api_key_env": "", **overrides}
    project.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    set_zotero(workspace)
    return workspace


def test_a_successful_sync_imports_the_fetched_records(project: Workspace) -> None:
    summary = zotero_import_project(project, client=MockZoteroClient(RIS_TWO))
    assert summary.records == 2 and summary.source_label == "Zotero"
    titles = {r.title for r in read_records(project.records_csv)}
    assert titles == {"Exercise therapy for mood disorders", "A second unrelated study"}


def test_the_fetched_text_is_saved_under_sources(project: Workspace) -> None:
    zotero_import_project(project, client=MockZoteroClient(RIS_ONE))
    saved = list(project.sources_dir.glob("zotero-123-*.ris"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == RIS_ONE


def test_an_empty_library_is_import_failed(project: Workspace) -> None:
    with pytest.raises(ImportFailed):
        zotero_import_project(project, client=MockZoteroClient(""))


def test_a_repeated_sync_is_not_blocked_and_duplicates_are_found_by_dedup(
    project: Workspace,
) -> None:
    from crapai.services.dedup import dedup_project

    zotero_import_project(project, client=MockZoteroClient(RIS_ONE))
    # force=True stands in for the real case the module docstring describes: a live resync's text
    # is rarely byte-identical (item order/timestamps differ), so E106 would not fire naturally;
    # force here isolates the point of this test (dedup, not E106) from that byte-level detail.
    zotero_import_project(project, client=MockZoteroClient(RIS_ONE), force=True)
    assert len(read_records(project.records_csv)) == 2  # both rows kept, nothing silently merged
    result = dedup_project(project)
    assert result.marked == 1  # the second sync's copy is recognised as a duplicate by DOI


def test_bibtex_format_is_requested_and_saved_with_the_right_extension(project: Workspace) -> None:
    set_zotero(project, format="bibtex")
    bibtex = "@article{zz1,\n  title = {Exercise therapy for mood disorders},\n  doi = {10.1000/zz1}\n}\n"
    zotero_import_project(project, client=MockZoteroClient(bibtex))
    assert list(project.sources_dir.glob("zotero-123-*.bib"))


def test_build_client_requires_a_key_unless_api_key_env_is_empty() -> None:
    with pytest.raises(AuthError):
        build_client(ZoteroSettings(api_key_env="ZOTERO_API_KEY"), environ={})
    client = build_client(ZoteroSettings(api_key_env=""), environ={})
    client.close()
