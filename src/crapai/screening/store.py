"""Files of a screening run: manifest, result lines, control file (plan chapters 11, 12.1, 28.4).

A run lives in ``runs/<run_id>/``:

``manifest.json``
    State, counters, hashes of everything that shaped the run, batch table, warnings. Replaced
    atomically (old or new, never half). The interface reads it to show progress.
``screening.jsonl``
    One line per finished record, **append only**. It is the record of truth: after a crash, every
    record with a line is done and is not paid for twice. A torn last line is cut before the next
    append (see :func:`crapai.project.atomic.append_lines`); an unreadable line in the middle is an
    error, not something to skip silently. A record can have several lines (a repeat after an
    error); the **last line wins**.
``control.json``
    A request from outside: ``{"command": "pause" | "stop"}``. The worker looks at it every second.

Nothing here talks to a provider. Every failure becomes a :class:`~crapai.errors.StorageError`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crapai.errors import StorageError
from crapai.project.atomic import append_lines, atomic_write_text

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA = 1
RESULT_STATUSES = ("ok", "parse_error", "api_error", "truncated", "too_long")
ERROR_STATUSES = frozenset(RESULT_STATUSES) - {"ok"}


class RunState(StrEnum):
    """Where a run is (plan chapter 28.5). ``completed`` and ``canceled`` are final."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"  # stopped on purpose or by a safety rule; resumable
    INTERRUPTED = "interrupted"  # stopped by Ctrl+C, a kill or a crash; resumable
    FAILED = "failed"  # e.g. wrong key, disk full; resumable after the cause is fixed
    COMPLETED = "completed"
    CANCELED = "canceled"

    @property
    def resumable(self) -> bool:
        """Whether ``--resume`` may continue this run."""
        return self in (RunState.PAUSED, RunState.INTERRUPTED, RunState.FAILED, RunState.RUNNING)


def now_iso() -> str:
    """The current time in UTC as ISO text (seconds)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class ResultRow(BaseModel):
    """The outcome for one record (one line of ``screening.jsonl``)."""

    model_config = ConfigDict(extra="forbid")

    study_uid: str
    run_id: str
    status: str
    decision: str = ""
    derived_decision: str = ""
    consistent: bool | None = None
    reasoning: str = ""
    inclusion: list[dict[str, str]] = Field(default_factory=list)
    exclusion: list[dict[str, str]] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    quote_unverified: list[str] = Field(default_factory=list)
    model_returned: str = ""
    prompt_hash: str = ""
    schema_version: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float | None = None
    latency_s: float = 0.0
    attempts: int = 0
    error_code: str = ""
    error_message: str = ""
    flags: list[str] = Field(default_factory=list)
    batch: int = 0
    timestamp: str = Field(default_factory=now_iso)
    # Used only by a resolution run (kind "adjudicate" or "discuss"; crapai adjudicate/discuss),
    # which settles a disagreement between two or more finished screening runs. Empty/unused for
    # an ordinary screening run.
    source_decisions: dict[str, str] = Field(default_factory=dict)  # run_id -> that run's decision
    consensus: bool | None = None  # discuss: whether every participant agreed; None otherwise
    rounds_used: int = 0  # discuss: reconsideration rounds actually used
    tie_break: str = ""  # discuss, no consensus: "majority" or "no_consensus"
    history: list[dict[str, Any]] = Field(default_factory=list)  # discuss: one entry per round

    @property
    def is_ok(self) -> bool:
        """True if the record was screened successfully."""
        return self.status == "ok"


@dataclass
class BatchInfo:
    """One batch ("package") of records and what became of it."""

    index: int
    size: int
    done: int = 0
    ok: int = 0
    errors: int = 0
    status: str = "pending"  # pending, running, verified, failed
    started: str = ""
    finished: str = ""
    note: str = ""


class Manifest(BaseModel):
    """``manifest.json``: what was run, with what, and how far it got."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(default=MANIFEST_SCHEMA, alias="schema")
    run_id: str
    kind: str = "full"  # full | sample
    state: str = RunState.CREATED.value
    created_at: str = Field(default_factory=now_iso)
    started_at: str = ""
    updated_at: str = Field(default_factory=now_iso)
    finished_at: str = ""
    software: dict[str, str] = Field(default_factory=dict)
    project_title: str = ""
    criteria_hash: str = ""
    objectives_hash: str = ""
    config_hash: str = ""
    prompt: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    run_settings: dict[str, Any] = Field(default_factory=dict)
    sample: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    batches: list[dict[str, Any]] = Field(default_factory=list)
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    last_error: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


def _corrupt(path: Path, what: str, exc: Exception) -> StorageError:
    logger.error("Cannot read %s (%s)", path.name, type(exc).__name__)
    return StorageError(
        f"{path.name} cannot be read ({what})",
        code="E404",
        hint="The run folder is damaged; restore it from a backup or start a new run.",
        details={"path": str(path)},
    )


@dataclass
class RunStore:
    """Reads and writes the files of one run.

    Args:
        folder: ``runs/<run_id>/`` (created by :meth:`create`).
    """

    folder: Path
    _results_cache: dict[str, ResultRow] = field(default_factory=dict, repr=False)

    @property
    def manifest_path(self) -> Path:
        """``manifest.json``."""
        return self.folder / "manifest.json"

    @property
    def results_path(self) -> Path:
        """``screening.jsonl``."""
        return self.folder / "screening.jsonl"

    @property
    def control_path(self) -> Path:
        """``control.json``."""
        return self.folder / "control.json"

    # -- manifest ------------------------------------------------------------------------------

    def create(self, manifest: Manifest) -> None:
        """Create the run folder and write the first manifest.

        Raises:
            StorageError: E401/E403 if it cannot be written; E405 if the run already exists.
        """
        if self.manifest_path.exists():
            raise StorageError(
                f"The run {self.folder.name} already exists",
                code="E405",
                details={"run": self.folder.name},
            )
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Cannot create the run folder ({type(exc).__name__})",
                code="E401",
                hint="Check that the project folder is writable.",
            ) from exc
        self.save_manifest(manifest)

    def save_manifest(self, manifest: Manifest) -> None:
        """Replace ``manifest.json`` atomically and stamp ``updated_at``."""
        manifest.updated_at = now_iso()
        text = json.dumps(manifest.model_dump(by_alias=True), ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.manifest_path, text)

    def load_manifest(self) -> Manifest:
        """Read ``manifest.json``.

        Raises:
            StorageError: E404 if it is missing or damaged.
        """
        try:
            return Manifest.model_validate(
                json.loads(self.manifest_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise _corrupt(self.manifest_path, "manifest", exc) from exc

    # -- results -------------------------------------------------------------------------------

    def append_result(self, row: ResultRow) -> None:
        """Append one result line and flush it to disk.

        Raises:
            StorageError: E401/E403 if the line cannot be written. The caller must stop the run:
                going on would spend money on answers that cannot be kept.
        """
        line = json.dumps(row.model_dump(), ensure_ascii=False, separators=(",", ":"))
        try:
            append_lines(self.results_path, [line])
        except OSError as exc:
            code = "E403" if getattr(exc, "errno", None) == 28 else "E401"
            logger.error(
                "Cannot append to %s (%s, %s)", self.results_path.name, type(exc).__name__, code
            )
            raise StorageError(
                f"Cannot save the result ({type(exc).__name__})",
                code=code,
                hint="Free disk space or close the program that holds the file; then resume.",
                details={"path": str(self.results_path)},
            ) from exc
        self._results_cache[row.study_uid] = row

    def read_results(self) -> list[ResultRow]:
        """All result lines in file order; a torn last line is ignored.

        Raises:
            StorageError: E404 if a line in the middle is unreadable.
        """
        path = self.results_path
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError) as exc:
            raise _corrupt(path, "results", exc) from exc
        if lines and lines[-1] == "":
            lines.pop()
        rows: list[ResultRow] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                rows.append(ResultRow.model_validate(json.loads(line)))
            except (ValueError, ValidationError) as exc:
                if number == len(lines):
                    logger.warning("Ignoring a torn last line in %s", path.name)
                    break
                raise StorageError(
                    f"{path.name}, line {number} cannot be read",
                    code="E404",
                    hint="The results file was edited by hand; restore it from a backup.",
                    details={"path": str(path), "line": number},
                ) from exc
        return rows

    def results_size(self) -> int:
        """Size of ``screening.jsonl`` in bytes (0 if there is none); a mark for the next read."""
        try:
            return self.results_path.stat().st_size
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise _corrupt(self.results_path, "results", exc) from exc

    def read_results_since(self, offset: int) -> list[ResultRow]:
        """The result lines written after byte ``offset`` (used to verify one batch cheaply).

        Raises:
            StorageError: E404 if the file cannot be read or a complete line is unreadable.
        """
        path = self.results_path
        if not path.exists():
            return []
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise _corrupt(path, "results", exc) from exc
        rows: list[ResultRow] = []
        for line in data.split("\n"):
            if not line.strip():
                continue
            try:
                rows.append(ResultRow.model_validate(json.loads(line)))
            except (ValueError, ValidationError) as exc:
                raise _corrupt(path, "a new result line", exc) from exc
        return rows

    def last_results(self) -> dict[str, ResultRow]:
        """The valid result per record: the last line of each ``study_uid``."""
        latest: dict[str, ResultRow] = {}
        for row in self.read_results():
            latest[row.study_uid] = row
        self._results_cache = dict(latest)
        return latest

    # -- control -------------------------------------------------------------------------------

    def write_control(self, command: str) -> None:
        """Ask the worker to ``pause`` or ``stop`` (from the interface or the command line)."""
        payload = {"command": command, "at": now_iso()}
        atomic_write_text(self.control_path, json.dumps(payload) + "\n")

    def read_control(self) -> str | None:
        """The pending command, or None. An unreadable control file is ignored (and logged)."""
        try:
            data = json.loads(self.control_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("control.json is unreadable; ignoring it")
            return None
        command = data.get("command") if isinstance(data, dict) else None
        return command if command in ("pause", "stop") else None

    def clear_control(self) -> None:
        """Remove a handled control request."""
        self.control_path.unlink(missing_ok=True)
