"""PRISMA events: the audit trail of everything that changes the number of records (plan 12.2).

The event model of the predecessor (``PRISMALogger``) without its Supabase methods and without
its hidden in-memory rollup: events are plain, append-only facts (``events.jsonl``) and the flow
numbers are always **derived** from them by :mod:`crapai.prisma.flow`.

Event types and steps are the persisted values of :mod:`crapai.enums` (``EventType``,
``PrismaStep``). Facts for which the enums have no value of their own are recorded as ``INFO``
events with a ``kind`` in the payload:

``kind = "validity"``
    Result of the validity check (records without abstract, front matter, retracted).
``kind = "prefilter"``
    Records removed by the deterministic pre-filters (language, year, type, retracted).

Every function here is pure. Writing and reading the file is done by ``crapai.services.events``.
Nothing in this module uses the network or a database.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crapai.enums import EventType, LogLevel, PrismaStep, ScreeningPhase

EVENT_SCHEMA = 1


def utc_now() -> datetime:
    """The current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class PrismaEvent(BaseModel):
    """One fact of the record flow.

    Attributes:
        event_id: Unique id of the event.
        timestamp: When it happened (UTC).
        step: The PRISMA step (``PrismaStep`` value).
        event_type: The kind of event (``EventType`` value).
        level: ``info``, ``warning`` or ``error``.
        message: One English sentence for people reading the file.
        source_label: The source the event is about, if it is about one.
        run_id: The screening run, for events of a run; ``None`` for project events.
        payload: The numbers and settings; the flow reads them by key.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(default=EVENT_SCHEMA, alias="schema")
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    step: str
    event_type: str
    level: str = LogLevel.INFO.value
    message: str = ""
    source_label: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def kind(self) -> str | None:
        """The ``kind`` of an INFO event (``validity``, ``prefilter``), else None."""
        value = self.payload.get("kind")
        return value if isinstance(value, str) else None


def to_json_line(event: PrismaEvent) -> str:
    """The compact one-line JSON form that is appended to ``events.jsonl``."""
    return json.dumps(
        event.model_dump(mode="json", by_alias=True), ensure_ascii=False, separators=(",", ":")
    )


def from_json_line(line: str) -> PrismaEvent:
    """Parse one line of ``events.jsonl``.

    Raises:
        ValueError: If the line is not valid JSON or not a valid event (pydantic's
            ``ValidationError`` is a ``ValueError``).
    """
    return PrismaEvent.model_validate(json.loads(line))


# --- factories --------------------------------------------------------------------------------


def source_imported(
    source_label: str, source_file: str, file_format: str, records_identified: int
) -> PrismaEvent:
    """A file was imported: ``records_identified`` records entered the project."""
    return PrismaEvent(
        step=PrismaStep.IMPORT.value,
        event_type=EventType.SOURCE_IMPORTED.value,
        message=f"Imported source '{source_label}' with {records_identified} records.",
        source_label=source_label,
        payload={
            "source_label": source_label,
            "original_filename": source_file,
            "file_type": file_format,
            "records_identified": int(records_identified),
        },
    )


def dedup_within_source(source_label: str, before: int, marked: int, method: str) -> PrismaEvent:
    """Duplicates inside one source were marked (``marked`` of ``before`` records)."""
    return PrismaEvent(
        step=PrismaStep.DEDUP_PER_SOURCE.value,
        event_type=EventType.DEDUP_WITHIN_SOURCE.value,
        message=f"Duplicates within '{source_label}': {marked} marked (strategy={method}).",
        source_label=source_label,
        payload={
            "source_label": source_label,
            "before": int(before),
            "after": int(before) - int(marked),
            "removed": int(marked),
            "marked": int(marked),
            "method": method,
            "scope": "within_source",
        },
    )


def merge_all_sources(inputs: Mapping[str, int], merged_before_dedup: int) -> PrismaEvent:
    """All sources were merged; ``inputs`` maps each label to its records."""
    return PrismaEvent(
        step=PrismaStep.MERGE.value,
        event_type=EventType.MERGE_ALL_SOURCES.value,
        message=f"Merged {len(inputs)} source(s) into one dataset of {merged_before_dedup}.",
        payload={
            "inputs": dict(inputs),
            "merged_records_before_global_dedup": int(merged_before_dedup),
        },
    )


def dedup_global(before: int, marked: int, method: str) -> PrismaEvent:
    """Duplicates across sources were marked (``marked`` of ``before`` records)."""
    return PrismaEvent(
        step=PrismaStep.DEDUP_MERGED.value,
        event_type=EventType.DEDUP_GLOBAL.value,
        message=f"Duplicates across sources: {marked} marked (strategy={method}).",
        payload={
            "before": int(before),
            "after": int(before) - int(marked),
            "removed": int(marked),
            "marked": int(marked),
            "method": method,
            "scope": "across_sources",
        },
    )


def validity_checked(
    total: int, by_reason: Mapping[str, int], without_abstract: int | None = None
) -> PrismaEvent:
    """The validity check ran.

    Args:
        total: All records of the project.
        by_reason: Records per exclusion reason. It counts every reason that is set, including
            ``DUPLICATE`` and the import reasons, because a record carries one reason in all.
        without_abstract: Records without an abstract whatever their reason (also when
            ``include_title_only`` is on, and duplicates). Defaults to the ``NO_ABSTRACT`` count.
    """
    missing = int(by_reason.get("NO_ABSTRACT", 0) if without_abstract is None else without_abstract)
    return PrismaEvent(
        step=PrismaStep.DEDUP_MERGED.value,
        event_type=EventType.INFO.value,
        message=f"Validity check: {missing} of {total} records have no abstract.",
        payload={
            "kind": "validity",
            "total_count": int(total),
            "missing_count": missing,
            "by_reason": {k: int(v) for k, v in by_reason.items()},
        },
    )


def prefilter_applied(total: int, removed_by_reason: Mapping[str, int]) -> PrismaEvent:
    """Pre-filters ran: records removed before screening, per reason code."""
    removed = sum(int(v) for v in removed_by_reason.values())
    return PrismaEvent(
        step=PrismaStep.DEDUP_MERGED.value,
        event_type=EventType.INFO.value,
        message=f"Pre-filters removed {removed} of {total} records before screening.",
        payload={
            "kind": "prefilter",
            "total_count": int(total),
            "removed": removed,
            "by_reason": {k: int(v) for k, v in removed_by_reason.items()},
        },
    )


def ai_prefilter_applied(total: int, removed: int, by_reason: Mapping[str, int]) -> PrismaEvent:
    """The optional Jev pre-filter ran (ADR 0029): records marked ``AI_PREFILTER_JEV``.

    A deliberately separate ``kind`` from ``"prefilter"``: this step is never run automatically
    (unlike the deterministic pre-filters), so its snapshot must not be folded together with
    theirs -- a rerun of the deterministic pre-filters must not make this snapshot look stale or
    get merged into it (see :mod:`crapai.prisma.flow`).
    """
    return PrismaEvent(
        step=PrismaStep.DEDUP_MERGED.value,
        event_type=EventType.INFO.value,
        message=f"Jev pre-filter marked {removed} of {total} records before screening.",
        payload={
            "kind": "ai_prefilter_jev",
            "total_count": int(total),
            "removed": int(removed),
            "by_reason": {k: int(v) for k, v in by_reason.items()},
        },
    )


def screening_done(
    phase: ScreeningPhase,
    included: int,
    excluded: int,
    conflicts: int = 0,
    reasons: Mapping[str, int] | None = None,
    run_id: str | None = None,
) -> PrismaEvent:
    """Aggregated result of a screening phase (title/abstract or full text)."""
    abstract = phase == ScreeningPhase.ABSTRACT
    return PrismaEvent(
        step=(PrismaStep.SCREEN_ABSTRACT if abstract else PrismaStep.SCREEN_FULLTEXT).value,
        event_type=(EventType.SCREEN_TA if abstract else EventType.SCREEN_FT).value,
        message=(
            f"{'Title/abstract' if abstract else 'Full-text'} screening: "
            f"included={included}, excluded={excluded}, conflicts={conflicts}."
        ),
        run_id=run_id,
        payload={
            "included": int(included),
            "excluded": int(excluded),
            "conflicts": int(conflicts),
            "reasons": {k: int(v) for k, v in (reasons or {}).items()},
        },
    )


def warning(
    step: PrismaStep, message: str, payload: Mapping[str, Any] | None = None
) -> PrismaEvent:
    """A warning about the flow (for example an arithmetic mismatch)."""
    return PrismaEvent(
        step=step.value,
        event_type=EventType.WARNING.value,
        level=LogLevel.WARNING.value,
        message=message,
        payload=dict(payload or {}),
    )
