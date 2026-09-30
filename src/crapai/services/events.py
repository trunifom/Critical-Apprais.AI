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

import json
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ValidationError

from crapai.config.loader import load_project_config
from crapai.enums import DuplicatesReportingMode
from crapai.errors import ConfigError, SaraError, StorageError
from crapai.io.records_store import Record
from crapai.prisma import events as ev
from crapai.prisma.events import PrismaEvent, from_json_line, to_json_line
from crapai.prisma.flow import FlowWarning, PrismaFlow, build_flow, validate_flow
from crapai.project.atomic import append_lines
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
    append_lines(path, lines)
    return len(lines)


def read_events(path: Path) -> list[PrismaEvent]:
    """Read all events; a missing file is an empty list.

    Raises:
        StorageError: E404 if a line in the middle of the file cannot be parsed.
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("Cannot read %s (%s)", path.name, type(exc).__name__)
        raise StorageError(
            f"{path.name} cannot be read ({type(exc).__name__})",
            code="E404",
            hint="The event file is unreadable or not UTF-8; restore it from a backup.",
            details={"path": str(path)},
        ) from exc
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


def _signature(event: PrismaEvent) -> tuple[str, str | None, str | None, str]:
    """What makes two events the same fact (ids and timestamps are ignored)."""
    payload = json.dumps(event.payload, sort_keys=True, ensure_ascii=False)
    return (event.event_type, event.kind, event.source_label, payload)


# Events after which an earlier snapshot of another step is no longer current.
_CHANGING_TYPES = frozenset(
    {"SOURCE_IMPORTED", "DEDUP_WITHIN_SOURCE", "MERGE_ALL_SOURCES", "DEDUP_GLOBAL"}
)


def _is_unchanged(existing: list[PrismaEvent], new: list[PrismaEvent]) -> bool:
    """True if ``new`` repeats the latest snapshot of its kind and nothing has changed since.

    A repeated ``crapai check`` would otherwise append the same snapshot every time. A snapshot
    is never skipped if an import or a *changed* dedup came after the previous one, because the
    flow treats the older snapshot as stale then.
    """
    wanted = [_signature(e) for e in new]
    # A dedup block is identified by its last event (the global step), a single event by itself.
    kind = (new[-1].event_type, new[-1].kind)
    last = -1
    for index, event in enumerate(existing):
        if (event.event_type, event.kind) == kind:
            last = index
    if last < 0:
        return False
    if kind[0] == "DEDUP_GLOBAL":
        block = existing[last - len(new) + 1 : last + 1]
        return [_signature(e) for e in block] == wanted
    if any(event.event_type in _CHANGING_TYPES for event in existing[last + 1 :]):
        return False
    return [_signature(existing[last])] == wanted


def _safe_append(workspace: Workspace, events: list[PrismaEvent], *, snapshot: bool = True) -> bool:
    """Append, but never let an audit-trail problem undo work that is already on disk.

    Args:
        workspace: The project.
        events: The events to write.
        snapshot: Skip the write if these events repeat the latest snapshot unchanged.

    Returns:
        True if the events are in the file (written now, or already there); False if they could
        not be written, so that the caller can tell the user (the flow has a gap then).
    """
    path = workspace.events_jsonl
    try:
        if snapshot and events:
            try:
                if _is_unchanged(read_events(path), events):
                    logger.debug("Event snapshot unchanged; not repeated in %s", path.name)
                    return True
            except SaraError:
                logger.warning("Cannot compare with %s; appending anyway", path.name)
        append_events(path, events)
    except OSError as exc:
        logger.warning(
            "Could not write %s (%s); rerun dedup and check to rebuild",
            path.name,
            type(exc).__name__,
        )
        return False
    return True


def record_import(
    workspace: Workspace, source_label: str, source_file: str, file_format: str, records: int
) -> bool:
    """Write the ``SOURCE_IMPORTED`` event of an import; False if it could not be written."""
    event = ev.source_imported(source_label, source_file, file_format, records)
    return _safe_append(workspace, [event], snapshot=False)


def record_dedup(
    workspace: Workspace,
    records: list[Record],
    strategy: str,
    within_source: Mapping[str, int],
    across_sources: int,
) -> bool:
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
    return _safe_append(workspace, new_events)


def record_validity(
    workspace: Workspace,
    total: int,
    by_reason: Mapping[str, int],
    without_abstract: int | None = None,
) -> bool:
    """Write the validity snapshot (records per exclusion reason, records without abstract)."""
    return _safe_append(workspace, [ev.validity_checked(total, by_reason, without_abstract)])


def record_prefilter(workspace: Workspace, total: int, by_reason: Mapping[str, int]) -> bool:
    """Write the pre-filter snapshot (records marked per ``PREFILTER_*`` reason)."""
    return _safe_append(workspace, [ev.prefilter_applied(total, by_reason)])


def reporting_mode(workspace: Workspace) -> DuplicatesReportingMode:
    """``dedup.reporting_mode`` of ``project.yaml``; the default if the file is unusable."""
    try:
        config = load_project_config(workspace.project_yaml)
        return DuplicatesReportingMode(config.dedup.reporting_mode)
    except (SaraError, FileNotFoundError) as exc:
        logger.warning(
            "project.yaml is unusable (%s); reporting duplicates as all_before_screening",
            getattr(exc, "code", type(exc).__name__),
        )
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
    if mode is None:
        chosen = reporting_mode(workspace)
    else:
        try:
            chosen = DuplicatesReportingMode(mode)
        except ValueError as exc:
            valid = ", ".join(m.value for m in DuplicatesReportingMode)
            raise ConfigError(
                f"Unknown reporting mode '{mode}' (valid: {valid})", code="E203"
            ) from exc
    flow = build_flow(read_events(workspace.events_jsonl), chosen)
    return flow, validate_flow(flow)
