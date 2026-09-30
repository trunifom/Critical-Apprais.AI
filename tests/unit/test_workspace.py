"""Tests for the project folder layout (task T-M1-03, plan chapter 6)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from saralocal.errors import StorageError
from saralocal.project.workspace import SCHEMA_VERSION, Workspace, cloud_sync_hint

EXPECTED_FOLDERS = {"sources", "data", "runs", "human", "reports", "prompts", ".sara"}


def test_create_builds_the_layout_of_chapter_6(tmp_path: Path) -> None:
    root = tmp_path / "my-review"
    workspace = Workspace.create(root)
    assert {p.name for p in root.iterdir() if p.is_dir()} == EXPECTED_FOLDERS
    assert workspace.version_file.read_text(encoding="utf-8").strip() == str(SCHEMA_VERSION)
    # Files are created later by their own tasks; only folders and the version exist now.
    assert not workspace.project_yaml.exists() and not workspace.records_csv.exists()


def test_paths_match_chapter_6(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.project_yaml == tmp_path / "project.yaml"
    assert ws.records_csv == tmp_path / "data" / "records.csv"
    assert ws.import_log == tmp_path / "data" / "records.import.jsonl"
    assert ws.backup_dir == tmp_path / "data" / ".backup"
    assert ws.lock_file == tmp_path / ".sara" / "lock"
    assert ws.version_file == tmp_path / ".sara" / "version"
    assert ws.app_log == tmp_path / ".sara" / "app.log"


def test_create_accepts_an_existing_empty_folder(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    assert (tmp_path / "sources").is_dir()


def test_create_refuses_existing_project_and_non_empty_folder(tmp_path: Path) -> None:
    Workspace.create(tmp_path / "a")
    with pytest.raises(StorageError) as info:
        Workspace.create(tmp_path / "a")
    assert info.value.code == "E404" and "already a project" in info.value.user_message

    other = tmp_path / "b"
    other.mkdir()
    (other / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(StorageError) as info2:
        Workspace.create(other)
    assert "not empty" in info2.value.user_message
    assert (other / "notes.txt").read_text(encoding="utf-8") == "keep me"  # nothing touched
    assert not (other / ".sara").exists()


def test_open_roundtrip(tmp_path: Path) -> None:
    created = Workspace.create(tmp_path / "p")
    opened = Workspace.open(tmp_path / "p")
    assert opened == created
    assert opened.read_version() == SCHEMA_VERSION


def test_open_rejects_a_plain_folder(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        Workspace.open(tmp_path)
    assert info.value.code == "E404" and "not a project folder" in info.value.user_message


@pytest.mark.parametrize("content", ["2\n", "0", "  \n"])
def test_open_rejects_other_or_damaged_versions(tmp_path: Path, content: str) -> None:
    ws = Workspace.create(tmp_path / "p")
    ws.version_file.write_text(content, encoding="utf-8")
    with pytest.raises(StorageError) as info:
        Workspace.open(ws.root)
    assert info.value.code == "E404"
    if content.strip():
        assert info.value.details["expected"] == SCHEMA_VERSION
        assert "migrate" in (info.value.hint or "")


def test_workspace_lock_uses_the_state_folder(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "p")
    with ws.lock():
        assert ws.lock_file.exists()
        with pytest.raises(StorageError) as info:
            ws.lock().acquire()
        assert info.value.code == "E402"
    assert not ws.lock_file.exists()


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/x/OneDrive - ZHAW/reviews/a",
        "C:/Users/x/Dropbox/reviews",
        "C:/Users/x/SharePoint/site/reviews",
        "/home/x/onedrive/reviews",
    ],
)
def test_cloud_sync_hint_detects_sync_folders(path: str) -> None:
    hint = cloud_sync_hint(Path(path))
    assert hint is not None and "non-synchronised" in hint


def test_cloud_sync_hint_is_none_for_plain_folders() -> None:
    assert cloud_sync_hint(Path("C:/Reviews/mine")) is None


def test_create_logs_a_warning_in_synchronised_folder(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "OneDrive" / "review"
    with caplog.at_level(logging.WARNING, logger="saralocal.project.workspace"):
        Workspace.create(root)
    assert any("synchronised" in record.message for record in caplog.records)
