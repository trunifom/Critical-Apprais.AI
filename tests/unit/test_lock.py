"""Tests for the project lock with heartbeat (task T-M1-03)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from saralocal.errors import StorageError
from saralocal.project.lock import ProjectLock, pid_alive


class Clock:
    """Controllable clock."""

    def __init__(self) -> None:
        self.current = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def make(path: Path, clock: Clock, *, pid: int, alive: set[int] | None = None) -> ProjectLock:
    live = alive if alive is not None else {pid}
    return ProjectLock(path, now=clock, pid=pid, is_alive=lambda p: p in live)


def test_acquire_creates_lock_file_with_pid_and_times(tmp_path: Path) -> None:
    clock = Clock()
    lock = make(tmp_path / ".sara" / "lock", clock, pid=111)  # parent folder is created
    lock.acquire()
    info = lock.inspect()
    assert info is not None
    assert (info.pid, info.stale) == (111, False)
    assert info.started == info.heartbeat == clock.current
    assert lock.held


def test_second_holder_is_refused_with_e402(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "lock"
    first = make(path, clock, pid=1, alive={1, 2})
    second = make(path, clock, pid=2, alive={1, 2})
    first.acquire()
    with pytest.raises(StorageError) as info:
        second.acquire()
    assert info.value.code == "E402"
    assert info.value.details["stale"] is False
    assert not second.held and first.held


def test_release_allows_next_holder_and_ignores_foreign_lock(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "lock"
    first = make(path, clock, pid=1, alive={1, 2})
    second = make(path, clock, pid=2, alive={1, 2})
    first.acquire()
    second.release()  # not the owner: must not delete first's lock
    assert path.exists()
    first.release()
    assert not path.exists()
    second.acquire()
    assert second.held


def test_heartbeat_alone_is_not_enough_to_call_a_lock_stale(tmp_path: Path) -> None:
    """Old heartbeat but the process still exists (e.g. a long pause): not stale."""
    clock = Clock()
    path = tmp_path / "lock"
    make(path, clock, pid=1, alive={1}).acquire()
    clock.advance(600)
    other = make(path, clock, pid=2, alive={1, 2})
    info = other.inspect()
    assert info is not None and not info.stale
    with pytest.raises(StorageError) as err:
        other.acquire(take_over_stale=True)
    assert err.value.details["stale"] is False


def test_recent_heartbeat_of_dead_process_is_not_stale_yet(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "lock"
    make(path, clock, pid=1, alive={1}).acquire()
    clock.advance(59)
    other = make(path, clock, pid=2, alive={2})  # PID 1 is dead
    info = other.inspect()
    assert info is not None and not info.stale


def test_stale_lock_needs_confirmation_then_can_be_taken_over(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "lock"
    make(path, clock, pid=1, alive={1}).acquire()
    clock.advance(61)  # heartbeat older than 60 s and PID 1 is dead
    other = make(path, clock, pid=2, alive={2})
    info = other.inspect()
    assert info is not None and info.stale and info.pid == 1

    with pytest.raises(StorageError) as err:
        other.acquire()  # without confirmation
    assert err.value.details["stale"] is True

    other.acquire(take_over_stale=True)
    now = other.inspect()
    assert now is not None and now.pid == 2 and not now.stale
    assert other.held


def test_heartbeat_refreshes_time_and_keeps_start(tmp_path: Path) -> None:
    clock = Clock()
    lock = make(tmp_path / "lock", clock, pid=1)
    lock.acquire()
    started = clock.current
    clock.advance(10)
    lock.heartbeat()
    info = lock.inspect()
    assert info is not None
    assert info.started == started
    assert info.heartbeat == started + timedelta(seconds=10)
    clock.advance(55)  # 55 s after the last heartbeat: still fresh for others
    other = make(tmp_path / "lock", clock, pid=2, alive={2})
    fresh = other.inspect()
    assert fresh is not None and not fresh.stale


def test_heartbeat_after_takeover_reports_lost_lock(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "lock"
    old = make(path, clock, pid=1, alive={1})
    old.acquire()
    clock.advance(120)
    make(path, clock, pid=2, alive={2}).acquire(take_over_stale=True)
    with pytest.raises(StorageError) as err:
        old.heartbeat()
    assert err.value.code == "E402"
    old.release()  # must not delete the new owner's lock
    assert path.exists()


def test_malformed_lock_file_is_stale_and_can_be_replaced(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    path.write_text("{not json", encoding="utf-8")
    lock = make(path, Clock(), pid=5)
    info = lock.inspect()
    assert info is not None and info.stale
    lock.acquire(take_over_stale=True)
    assert lock.held


def test_context_manager_releases_even_on_error(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    with pytest.raises(RuntimeError), make(path, Clock(), pid=1):
        assert path.exists()
        raise RuntimeError("run crashed")
    assert not path.exists()


def test_pid_alive_for_own_and_finished_process() -> None:
    assert pid_alive(os.getpid())
    assert not pid_alive(0) and not pid_alive(-5)
    code = "import os; print(os.getpid())"
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
    finished_pid = int(child.stdout.decode().strip())
    assert not pid_alive(finished_pid)
