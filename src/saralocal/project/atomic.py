"""Atomic file writing for the project folder (plan chapters 6.1, 11 and 28.9).

Whole files are written to a temporary file in the same directory, flushed to disk and then moved
over the target with ``os.replace``. A crash or kill at any moment therefore leaves either the old
complete file or the new complete file, never a half-written one. A temporary file that is left
behind by a crash is harmless and is ignored by readers.

On Windows ``os.replace`` fails with ``PermissionError`` while another program (Excel, a virus
scanner, a sync client) holds the target. The write is retried a few times and, if the target stays
locked, the content is written to a timestamped alternative file so nothing is lost (error E401).
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from saralocal.errors import StorageError

logger = logging.getLogger(__name__)

DEFAULT_RETRIES = 5
DEFAULT_DELAY_S = 0.2


@dataclass(frozen=True)
class WriteResult:
    """Outcome of an atomic write.

    Attributes:
        path: The file that now holds the content.
        used_alternative: True if the requested target was locked and ``path`` is a
            timestamped alternative next to it (the caller must tell the user, code E401).
    """

    path: Path
    used_alternative: bool = False


def alternative_path(target: Path, now: datetime) -> Path:
    """Name of the fallback file, e.g. ``results.20260930-145501.xlsx`` next to ``results.xlsx``."""
    stamp = now.strftime("%Y%m%d-%H%M%S")
    return target.with_name(f"{target.stem}.{stamp}{target.suffix}")


def _temp_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.{os.getpid()}.tmp")


def _replace_with_retry(
    tmp: Path,
    target: Path,
    *,
    retries: int,
    delay_s: float,
    sleep: Callable[[float], None],
) -> bool:
    """Try ``os.replace(tmp, target)``; return False if the target stayed locked."""
    for attempt in range(retries + 1):
        try:
            os.replace(tmp, target)
            return True
        except PermissionError:
            if attempt == retries:
                return False
            logger.debug("Target %s is locked, retry %d of %d", target.name, attempt + 1, retries)
            sleep(delay_s)
    return False  # pragma: no cover - loop always returns


def atomic_write(
    target: Path,
    writer: Callable[[BinaryIO], None],
    *,
    retries: int = DEFAULT_RETRIES,
    delay_s: float = DEFAULT_DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = datetime.now,
) -> WriteResult:
    """Write ``target`` atomically; ``writer`` receives a binary file object for the temp file.

    If ``writer`` raises, or the process dies while writing, the target is untouched and the
    temporary file is removed (when the process is still alive to do so).

    Args:
        target: Final path. Its directory must exist.
        writer: Callback that writes the complete content to the given binary stream.
        retries: Extra attempts of ``os.replace`` after a ``PermissionError`` (default 5).
        delay_s: Pause between attempts in seconds (default 0.2).
        sleep: Injectable pause function (for tests).
        now: Injectable clock used for the alternative file name (for tests).

    Returns:
        A :class:`WriteResult`; check ``used_alternative`` to detect a locked target.

    Raises:
        StorageError: (E401) if neither the target nor the alternative file can be replaced;
            (E403) if the disk is full; (E401) for other operating-system errors.
    """
    tmp = _temp_path(target)
    try:
        with open(tmp, "wb") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        if _replace_with_retry(tmp, target, retries=retries, delay_s=delay_s, sleep=sleep):
            return WriteResult(target)
        alternative = alternative_path(target, now())
        if _replace_with_retry(tmp, alternative, retries=0, delay_s=0.0, sleep=sleep):
            logger.warning("%s is locked; wrote %s instead", target.name, alternative.name)
            return WriteResult(alternative, used_alternative=True)
        raise StorageError(
            f"Cannot write {target.name}: the file is locked",
            code="E401",
            hint="Close the file in Excel or another program and try again.",
            details={"path": str(target)},
        )
    except OSError as exc:
        code = "E403" if getattr(exc, "errno", None) == 28 else "E401"  # 28 = ENOSPC
        raise StorageError(
            f"Cannot write {target.name} ({type(exc).__name__})",
            code=code,
            hint="Free disk space or check the folder permissions."
            if code == "E403"
            else "Check that the folder exists and is writable.",
            details={"path": str(target)},
        ) from exc
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def atomic_write_bytes(target: Path, data: bytes, **options: object) -> WriteResult:
    """Atomically write ``data`` to ``target`` (see :func:`atomic_write` for options and errors)."""
    return atomic_write(target, lambda handle: handle.write(data), **options)  # type: ignore[arg-type]


def atomic_write_text(
    target: Path, text: str, *, encoding: str = "utf-8", **options: object
) -> WriteResult:
    """Atomically write ``text`` to ``target`` without newline translation.

    The text is encoded as-is (UTF-8 by default); use ``"\\n"`` inside the text, project files are
    LF internally. Excel exports that need a BOM pass ``encoding="utf-8-sig"``.
    """
    return atomic_write_bytes(target, text.encode(encoding), **options)
