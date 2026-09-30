"""Tests for atomic writing (task T-M1-03, plan chapter 28.9)."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import pytest

from saralocal.errors import StorageError
from saralocal.project import atomic
from saralocal.project.atomic import (
    alternative_path,
    atomic_write,
    atomic_write_bytes,
    atomic_write_text,
)

FIXED_NOW = datetime(2026, 9, 30, 14, 55, 1)


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def test_creates_and_replaces_file_without_leftovers(tmp_path: Path) -> None:
    target = tmp_path / "records.csv"
    result = atomic_write_text(target, "a,b\n1,2\n")
    assert result.path == target and not result.used_alternative
    assert target.read_bytes() == b"a,b\n1,2\n"  # no newline translation on Windows
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert leftovers(tmp_path) == []


def test_utf8_and_bom_encodings(tmp_path: Path) -> None:
    target = tmp_path / "x.csv"
    atomic_write_text(target, "Größe,Δ\n", encoding="utf-8-sig")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert target.read_text(encoding="utf-8-sig") == "Größe,Δ\n"


def test_failing_writer_keeps_old_file_and_removes_temp(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_bytes(b"OLD")

    def broken(handle: BinaryIO) -> None:
        handle.write(b"HALF")
        raise RuntimeError("disk exploded")

    with pytest.raises(RuntimeError):
        atomic_write(target, broken)
    assert target.read_bytes() == b"OLD"
    assert leftovers(tmp_path) == []


def test_killed_process_never_replaces_the_real_file(tmp_path: Path) -> None:
    """Kill test: the writer process dies hard (os._exit) after writing half of the content."""
    target = tmp_path / "data.csv"
    target.write_bytes(b"OLD COMPLETE CONTENT")
    script = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from saralocal.project.atomic import atomic_write

        def writer(handle):
            handle.write(b"HALF WRITTEN")
            handle.flush()
            os._exit(1)  # no cleanup, like a kill or a power failure

        atomic_write(Path(sys.argv[1]), writer)
        """
    )
    src = Path(atomic.__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(src)}
    proc = subprocess.run(
        [sys.executable, "-c", script, str(target)], env=env, capture_output=True, check=False
    )
    assert proc.returncode == 1
    assert target.read_bytes() == b"OLD COMPLETE CONTENT"
    # A leftover temp file may exist after a hard kill; it must never be the real file's name.
    assert all(name != target.name for name in leftovers(tmp_path))


def _lock_target(monkeypatch: pytest.MonkeyPatch, target: Path, failures: int) -> list[int]:
    """Make os.replace raise PermissionError for ``target`` the first ``failures`` times."""
    calls: list[int] = []
    real_replace = os.replace

    def fake(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == target:
            calls.append(1)
            if len(calls) <= failures:
                raise PermissionError("locked by Excel")
        real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", fake)
    return calls


def test_retries_five_times_at_200_ms_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "results.xlsx"
    calls = _lock_target(monkeypatch, target, failures=5)
    pauses: list[float] = []
    result = atomic_write_bytes(target, b"data", sleep=pauses.append)
    assert result.path == target and not result.used_alternative
    assert len(calls) == 6  # first try + 5 retries
    assert pauses == [0.2] * 5
    assert target.read_bytes() == b"data"


def test_locked_target_falls_back_to_timestamped_alternative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "results.xlsx"
    target.write_bytes(b"OPEN IN EXCEL")
    _lock_target(monkeypatch, target, failures=10**6)
    pauses: list[float] = []
    result = atomic_write_bytes(target, b"NEW", sleep=pauses.append, now=lambda: FIXED_NOW)
    assert result.used_alternative
    assert result.path == tmp_path / "results.20260930-145501.xlsx"
    assert result.path.read_bytes() == b"NEW"
    assert target.read_bytes() == b"OPEN IN EXCEL"  # untouched
    assert len(pauses) == 5
    assert leftovers(tmp_path) == []


def test_alternative_locked_too_raises_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_locked(src: object, dst: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(atomic.os, "replace", always_locked)
    target = tmp_path / "results.xlsx"
    with pytest.raises(StorageError) as info:
        atomic_write_bytes(target, b"x", sleep=lambda s: None)
    assert info.value.code == "E401"
    assert leftovers(tmp_path) == []


def test_missing_directory_is_a_storage_error(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        atomic_write_text(tmp_path / "no" / "such" / "file.csv", "x")
    assert info.value.code == "E401"


def test_alternative_path_keeps_suffix() -> None:
    assert alternative_path(Path("a/results.xlsx"), FIXED_NOW) == Path(
        "a/results.20260930-145501.xlsx"
    )
