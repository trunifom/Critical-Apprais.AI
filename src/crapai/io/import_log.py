"""Import log ``data/records.import.jsonl`` and source file hashes (plan chapters 6.1, 8.2, 25.7).

Each imported file gets one JSON line: its SHA-256, label, format, counts, encoding, the column
mapping that was used and warnings. The hash detects a repeated import of the same file (error
E106, overridable with ``--force``). The log is append-only; a half-written **last** line (crash
while writing) is ignored on reading, an unreadable line in the **middle** is an error because it
points to manual edits (plan chapter 25.7).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crapai.errors import ImportFailed, StorageError
from crapai.project.atomic import append_lines

logger = logging.getLogger(__name__)

LOG_SCHEMA = 1
HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """SHA-256 of the file's bytes as a lower-case hex string (streamed, any file size)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ImportLogEntry(BaseModel):
    """One imported source file."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=LOG_SCHEMA, alias="schema")
    timestamp: datetime
    source_file: str
    sha256: str = Field(min_length=64, max_length=64)
    source_label: str
    format: str
    records: int = Field(ge=0)
    abstracts: int = Field(ge=0)
    encoding: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    column_map: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    forced: bool = False


def append_entry(log_path: Path, entry: ImportLogEntry) -> None:
    """Append one entry as a compact JSON line and flush it to disk."""
    line = json.dumps(
        entry.model_dump(mode="json", by_alias=True), ensure_ascii=False, separators=(",", ":")
    )
    append_lines(log_path, [line])


def read_entries(log_path: Path) -> list[ImportLogEntry]:
    """Read all entries; a missing file is an empty log.

    Raises:
        StorageError: (E404) if a line in the middle of the file cannot be parsed.
    """
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    entries: list[ImportLogEntry] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(ImportLogEntry.model_validate(json.loads(line)))
        except (ValueError, ValidationError) as exc:
            if number == len(lines):
                logger.warning("Ignoring an unreadable last line in %s (interrupted)", log_path)
                break
            raise StorageError(
                f"{log_path.name}, line {number} cannot be read",
                code="E404",
                hint="The import log was edited by hand; restore it from a backup.",
                details={"path": str(log_path), "line": number},
            ) from exc
    return entries


def find_previous_import(log_path: Path, sha256: str) -> ImportLogEntry | None:
    """The latest log entry for a file with this hash, or None."""
    for entry in reversed(read_entries(log_path)):
        if entry.sha256 == sha256:
            return entry
    return None


def ensure_not_imported(log_path: Path, sha256: str, *, force: bool = False) -> None:
    """Raise E106 if a file with this hash was imported before (unless ``force``).

    Raises:
        ImportFailed: (E106) with the earlier import's time, file name and label in ``details``.
    """
    previous = find_previous_import(log_path, sha256)
    if previous is None or force:
        return
    raise ImportFailed(
        f"This file was already imported as {previous.source_file} "
        f"({previous.records} records, {previous.timestamp.isoformat(timespec='seconds')})",
        code="E106",
        hint="Use --force to import it again; the records will be added a second time.",
        details={
            "sha256": sha256,
            "source_file": previous.source_file,
            "source_label": previous.source_label,
            "timestamp": previous.timestamp.isoformat(),
        },
    )
