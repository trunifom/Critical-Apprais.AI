"""Single-writer lock for a project folder (plan chapters 5.2 A9, 11 and 28.4).

The lock is a small JSON file (``.sara/lock``) with the owner's PID, a random token, the start time
and a heartbeat. An operating-system file lock is deliberately not used because it is unreliable on
network drives (chapter 28.9). The running process refreshes the heartbeat every 10 seconds
(:data:`HEARTBEAT_INTERVAL_S`); a lock counts as *stale* when its heartbeat is older than 60 seconds
(:data:`STALE_AFTER_S`) **and** the owning process no longer exists. A stale lock is taken over only
when the caller says so (the CLI asks the user first).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from saralocal.errors import StorageError
from saralocal.project.atomic import atomic_write_text

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 10.0
STALE_AFTER_S = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def pid_alive(pid: int) -> bool:
    """Return True if a process with this PID currently exists (best effort, no side effects)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)  # signal 0 only checks existence on POSIX
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but belongs to someone else
    return True


def _pid_alive_windows(pid: int) -> bool:
    # os.kill would terminate the process on Windows, so ask the Win32 API instead.
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED (5) means the process exists but we may not query it.
        return bool(ctypes.GetLastError() == 5)  # type: ignore[attr-defined,unused-ignore]
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return bool(code.value == still_active)
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True)
class LockInfo:
    """Content of a lock file plus the derived ``stale`` flag."""

    pid: int
    token: str
    started: datetime
    heartbeat: datetime
    stale: bool


class ProjectLock:
    """Exclusive lock on one project folder.

    Args:
        path: Location of the lock file (normally ``<project>/.sara/lock``).
        now: Injectable clock returning timezone-aware datetimes.
        pid: PID to record for this process.
        is_alive: Injectable process check (for tests).
        stale_after_s: Heartbeat age after which a lock may be stale.
    """

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] = _utc_now,
        pid: int | None = None,
        is_alive: Callable[[int], bool] = pid_alive,
        stale_after_s: float = STALE_AFTER_S,
    ) -> None:
        self.path = path
        self._now = now
        self._pid = os.getpid() if pid is None else pid
        self._is_alive = is_alive
        self._stale_after_s = stale_after_s
        self._token: str | None = None

    # -- inspection -----------------------------------------------------------------------

    def inspect(self) -> LockInfo | None:
        """Read the current lock, or None if there is none.

        An unreadable or malformed lock file is reported as stale (owner unknown, PID 0), because
        no live process can refresh it.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return LockInfo(0, "", self._now(), self._now(), stale=True)
        try:
            data: dict[str, Any] = json.loads(raw)
            pid = int(data["pid"])
            started = datetime.fromisoformat(data["started"])
            heartbeat = datetime.fromisoformat(data["heartbeat"])
            token = str(data["token"])
        except (ValueError, KeyError, TypeError):
            logger.warning("Lock file %s is malformed; treating it as stale", self.path)
            return LockInfo(0, "", self._now(), self._now(), stale=True)
        age = (self._now() - heartbeat).total_seconds()
        stale = age > self._stale_after_s and not self._is_alive(pid)
        return LockInfo(pid, token, started, heartbeat, stale)

    @property
    def held(self) -> bool:
        """True if this object currently owns the lock file."""
        info = self.inspect()
        return self._token is not None and info is not None and info.token == self._token

    # -- taking and releasing -------------------------------------------------------------

    def acquire(self, *, take_over_stale: bool = False) -> None:
        """Take the lock.

        Args:
            take_over_stale: If True, replace a stale lock instead of refusing.

        Raises:
            StorageError: (E402) if another live process holds the lock, or if the lock is stale
                and ``take_over_stale`` is False (``details["stale"]`` is True so that the caller
                can ask the user and retry).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._try_create():
            return
        info = self.inspect()
        if info is None:  # released between the two calls: try once more
            if self._try_create():
                return
            info = self.inspect()
        if info is not None and info.stale and take_over_stale:
            logger.warning("Taking over stale lock of PID %d", info.pid)
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            if self._try_create():
                return
        raise self._refusal(info)

    def _try_create(self) -> bool:
        """Create the lock file exclusively; False if it already exists."""
        token = secrets.token_hex(8)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        now = self._now()
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self._payload(token, now, now))
        self._token = token
        return True

    def _payload(self, token: str, started: datetime, heartbeat: datetime) -> str:
        return json.dumps(
            {
                "pid": self._pid,
                "token": token,
                "started": started.isoformat(),
                "heartbeat": heartbeat.isoformat(),
            }
        )

    def _refusal(self, info: LockInfo | None) -> StorageError:
        stale = bool(info and info.stale)
        if stale:
            return StorageError(
                "The project lock is stale (its owner is no longer running)",
                code="E402",
                hint="Confirm to take over the stale lock.",
                details={"path": str(self.path), "stale": True, "pid": info.pid if info else 0},
            )
        return StorageError(
            "The project is in use by another process",
            code="E402",
            hint="Finish the other run first, or wait until it has stopped.",
            details={"path": str(self.path), "stale": False, "pid": info.pid if info else 0},
        )

    def heartbeat(self) -> None:
        """Refresh the heartbeat. Call every :data:`HEARTBEAT_INTERVAL_S` seconds while running.

        Raises:
            StorageError: (E402) if the lock was lost, i.e. someone else took it over.
        """
        info = self.inspect()
        if self._token is None or info is None or info.token != self._token:
            raise StorageError(
                "The project lock was lost", code="E402", details={"path": str(self.path)}
            )
        atomic_write_text(self.path, self._payload(self._token, info.started, self._now()))

    def release(self) -> None:
        """Remove the lock file if this object owns it; otherwise do nothing."""
        if self.held:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
        self._token = None

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
