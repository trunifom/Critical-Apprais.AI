"""Logging for the command line and the interface: one setup, one format, no secrets.

The project log is ``.crapai/app.log`` (rotating, 1 MB x 3). Every line carries the time, the level,
a short *session id* (one per program start, so the lines of one run can be told apart in a log
that several runs share), the logger name and the message::

    2026-10-01 09:30:15,123 INFO [a1b2c3d4] crapai.services.dedup: Dedup (doi_or_title, ...)

What goes into the log is decided by the callers: counts, codes, file names, never titles,
abstracts or keys. As a second line of defence :class:`RedactingFilter` masks anything that looks
like a key or token before a line is written.

The level comes from the caller (``--verbose`` gives DEBUG), else from the environment variable
``CRAPAI_LOG_LEVEL`` (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``), else ``INFO``. A log file that
cannot be opened never stops the program: :func:`attach_project_log` returns a message instead.

This module uses the standard library only, so the core layers and the interface can share it.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import uuid
from collections import deque
from pathlib import Path
from typing import TextIO

from crapai.branding import STATE_DIR_NAME

LOGGER_NAME = "crapai"
LOG_FILE_NAME = "app.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
LEVEL_ENV = "CRAPAI_LOG_LEVEL"
FORMAT = "%(asctime)s %(levelname)s [%(session)s] %(name)s: %(message)s"
SESSION_ID = uuid.uuid4().hex[:8]  # one per program start

# Patterns of secrets: provider keys, bearer tokens and "key=value" pairs whose name says secret.
_SECRET_PATTERNS = (
    re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(
        r"(?i)\b([A-Za-z_]*(?:api[_-]?key|token|secret|password|passwd)[A-Za-z_]*)\s*([=:])\s*\S+"
    ),
)
_MASK = "***"


def redact(text: str) -> str:
    """Return ``text`` with keys, tokens and ``secret=value`` pairs replaced by ``***``."""
    text = _SECRET_PATTERNS[0].sub(_MASK, text)
    text = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)} {_MASK}", text)
    return _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}", text)


class RedactingFilter(logging.Filter):
    """Mask secrets in every record and add the session id (the format needs it)."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add the session id and mask secrets in the message; always keep the record."""
        record.session = SESSION_ID
        message = record.getMessage()
        masked = redact(message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


def resolve_level(explicit: str | int | None = None, *, verbose: bool = False) -> int:
    """The log level: ``verbose`` (DEBUG), else ``explicit``, else the environment, else INFO.

    Unknown names fall back to INFO instead of failing: a typo in an environment variable must
    not stop the program.
    """
    if verbose:
        return logging.DEBUG
    candidate = explicit if explicit is not None else os.environ.get(LEVEL_ENV, "")
    if isinstance(candidate, int):
        return candidate
    level = logging.getLevelName(str(candidate).strip().upper()) if str(candidate).strip() else None
    return level if isinstance(level, int) else logging.INFO


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def _replace_handler(tag: str, handler: logging.Handler | None) -> None:
    """Remove the handler with this tag (closing it) and install the new one."""
    root = _logger()
    for existing in list(root.handlers):
        if getattr(existing, "crapai_tag", None) == tag:
            root.removeHandler(existing)
            existing.close()
    if handler is not None:
        handler.crapai_tag = tag  # type: ignore[attr-defined]
        handler.addFilter(RedactingFilter())
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)


def attach_project_log(folder: Path, *, level: int | None = None) -> str | None:
    """Log to ``<folder>/.crapai/app.log`` (rotating). Safe to call again for the same folder.

    A different project replaces the handler of the earlier one. Nothing happens if ``folder`` is
    no project yet (no state folder).

    Returns:
        ``None`` if all is well, else a short English message why the log file is not available
        (the caller may show it once; the program goes on without a file log).
    """
    state = folder / STATE_DIR_NAME
    if not state.is_dir():
        return None
    target = str((state / LOG_FILE_NAME).resolve())
    root = _logger()
    chosen = resolve_level() if level is None else level
    for existing in root.handlers:
        already = (
            getattr(existing, "crapai_tag", None) == "project"
            and isinstance(existing, logging.handlers.RotatingFileHandler)
            and existing.baseFilename == target
        )
        if already:
            root.setLevel(chosen)
            return None
    try:
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
    except OSError as exc:
        return f"cannot write the log file ({type(exc).__name__})"
    _replace_handler("project", handler)
    root.setLevel(chosen)
    return None


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever ``sys.stderr`` is *now* (it is replaced while output is captured)."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self) -> TextIO:  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:  # the base class assigns one; it is ignored
        pass


def enable_console_log(level: int = logging.DEBUG) -> None:
    """Also print log lines to stderr (``--verbose``); safe to call again."""
    handler = _StderrHandler()
    handler.setLevel(level)
    _replace_handler("console", handler)
    root = _logger()
    root.setLevel(min(root.level or level, level))


def detach_all() -> None:
    """Remove and close every handler this module installed (tests, and before a folder moves)."""
    _replace_handler("project", None)
    _replace_handler("console", None)


def read_log_tail(folder: Path, lines: int = 200) -> list[str]:
    """The last ``lines`` lines of the project log (empty if there is none or it is unreadable)."""
    path = folder / STATE_DIR_NAME / LOG_FILE_NAME
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=max(1, lines))]
    except OSError:
        return []
