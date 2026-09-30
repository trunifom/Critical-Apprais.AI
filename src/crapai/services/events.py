"""Event service: the project's ``data/events.jsonl`` and the PRISMA flow (plan 8.8 and 12.2).

Appends :mod:`crapai.prisma.events` events to the file and reads them back. The import, dedup and
validity services call the ``record_*`` helpers after they have changed ``records.csv``; the flow
(:func:`project_flow`) is always derived from the file.

The file is append-only. A half-written last line (crash while writing) is ignored on reading, an
unreadable line in the middle is an error (manual edit), as for the import log. If an event cannot
be written the work that was already done stays valid: the failure is logged as a warning and the
caller continues, because the records on disk are the source of truth and the event stream can be
rebuilt by running dedup and the validity check again.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ValidationError

from crapai.config.loader import load_project_config
from crapai.enums import DuplicatesReportingMode
from crapai.errors import SaraError, StorageError
from crapai.io.records_store import Record
from crapai.prisma import events as ev
from crapai.prisma.events import PrismaEvent, from_json_line, to_json_line
from crapai.prisma.flow import FlowWarning, PrismaFlow, build_flow, validate_flow
from crapai.project.workspace import Workspace

logger = logging.getLogger(__name__)


def append_events(path: Path, events: Iterable[PrismaEvent]) -> int:
    """Append events as JSON lines and flush them to disk.

    Returns:
        The number of events written (0 writes nothing and does not create the file).

    Raises:
        OSError: If the file cannot be written.
    """
    lines = [to_json_line(event) for event in events]
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(lines)


def read_events(path: Path) -> list[PrismaEvent]:
    """Read all events; a missing file is an empty list.

    Raises:
        StorageError: E404 if a line in the middle of the file cannot be parsed.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    events: list[PrismaEvent] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            events.append(from_json_line(line))
        except (ValueError, ValidationError) as exc:
            if number == len(lines):
                logger.warning("Ignoring an unreadable last line in %s (interrupted)", path)
                break
            raise StorageError(
                f"{path.name}, line {number} cannot be read",
                code="E404",
                hint="The event file was edited by hand; restore it from a backup.",
                details={"path": str(path), "line": number},
            ) from exc
    return events


def _safe_append(workspace: Workspace, events: list[PrismaEvent]) -> None:
    """Append, but never let an audit-trail problem undo work that is already on disk."""
    try:
        append_events(workspace.events_jsonl, events)
    except OSError as exc:
        logger.warning(
            "Could not write %s (%s); rerun dedup and check to rebuild",
            workspace.events_jsonl.name,
            exc,
        )


def record_import(
    workspace: Workspace, source_label: str, source_file: str, file_format: str, records: int
) -> None:
    """Write the ``SOURCE_IMPORTED`` event of an import."""
    _safe_append(workspace, [ev.source_imported(source_label, source_file, file_format, records)])


def record_dedup(
    workspace: Workspace,
    records: list[Record],
    strategy: str,
    within_source: Mapping[str, int],
    across_sources: int,
) -> None:
    """Write the dedup snapshot: one event per source, the merge and the global step.

    ``records`` are all records after the run. The numbers replace those of earlier dedup runs
    when the flow is built.
    """
    per_source = Counter(r.source_label for r in records)
    new_events: list[PrismaEvent] = [
        ev.dedup_within_source(label, count, within_source.get(label, 0), strategy)
        for label, count in per_source.items()
    ]
    after_within = {
        label: count - within_source.get(label, 0) for label, count in per_source.items()
    }
    merged = sum(after_within.values())
    new_events.append(ev.merge_all_sources(after_within, merged))
    new_events.append(ev.dedup_global(merged, across_sources, strategy))
    _safe_append(workspace, new_events)


def record_validity(workspace: Workspace, total: int, by_reason: Mapping[str, int]) -> None:
    """Write the validity snapshot (records per exclusion reason, records without abstract)."""
    _safe_append(workspace, [ev.validity_checked(total, by_reason)])


def reporting_mode(workspace: Workspace) -> DuplicatesReportingMode:
    """``dedup.reporting_mode`` of ``project.yaml``; the default if the file is unusable."""
    try:
        return DuplicatesReportingMode(
            load_project_config(workspace.project_yaml).dedup.reporting_mode
        )
    except (SaraError, FileNotFoundError):
        return DuplicatesReportingMode.ALL_BEFORE_SCREENING


def project_flow(
    workspace: Workspace, mode: DuplicatesReportingMode | str | None = None
) -> tuple[PrismaFlow, list[FlowWarning]]:
    """The PRISMA flow numbers of a project and the failed plausibility checks.

    Args:
        workspace: The project.
        mode: Reporting mode; by default ``dedup.reporting_mode`` of ``project.yaml``.

    Raises:
        StorageError: E404 for a folder that is no project or a damaged event file.
    """
    workspace = Workspace.open(workspace.root)
    chosen = DuplicatesReportingMode(mode) if mode is not None else reporting_mode(workspace)
    flow = build_flow(read_events(workspace.events_jsonl), chosen)
    return flow, validate_flow(flow)
