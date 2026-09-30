"""PRISMA 2020 flow numbers, derived from the event stream (plan 8.8 and 12.2).

Port of ``PRISMALogger.to_prisma_flow`` and ``validate_rollup`` of the predecessor. The difference:
there is no hidden in-memory rollup. :func:`build_flow` folds a list of
:class:`~crapai.prisma.events.PrismaEvent` into the numbers every time, so the numbers always agree
with ``events.jsonl`` and a wrong number can be traced to the event that produced it.

Rules of the fold:

* ``SOURCE_IMPORTED`` adds up (every import adds records).
* Dedup, validity and pre-filter events are **snapshots** of a whole-project recalculation: for each
  source the latest ``DEDUP_WITHIN_SOURCE`` counts, the latest ``DEDUP_GLOBAL``, the latest
  validity and the latest pre-filter event. Running dedup twice therefore does not count twice.
* A snapshot can be **stale**. Dedup is computed from the duplicates it found, never from the
  import total, so records imported after the last dedup are not reported as duplicates; they
  count as "to screen" and the flow says so (``STALE_DEDUP``). A pre-filter or validity snapshot
  that is older than the latest dedup is ignored (dedup may have re-labelled those records) and
  reported as stale, so nothing is subtracted twice.
* ``SCREEN_TA`` and ``SCREEN_FT``: the events of the **latest run** of a phase count (all events
  that share its ``run_id``; an event without a run id counts on its own). A repeated run therefore
  replaces the earlier one instead of doubling it.

Two ways to report duplicates (``DuplicatesReportingMode``):

``ALL_BEFORE_SCREENING``
    Duplicates = everything removed by dedup (within + across sources).
``BETWEEN_DATABASES_ONLY``
    Duplicates = only those across sources; duplicates within a source are booked under
    "removed before screening (other)" so the arithmetic still balances.

Records removed by the pre-filters (and retracted studies, when they are excluded) are always
"other". Records that are not sent to the model for another reason (front matter, no abstract)
are **not** removed here: they stay in "records to screen" and are visible in
``records_with_missing_abstracts``; the screening step reports them as not assessed. No I/O, no
network.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from crapai.enums import DuplicatesReportingMode, EventType
from crapai.prisma.events import PrismaEvent

_INTERNAL_FIELDS = (
    "ta_included",
    "dedup_global_before",
    "dedup_global_after",
    "merged_before_global_dedup",
    "within_source_removed",
    "stale_steps",
)


@dataclass(frozen=True)
class PrismaFlow:
    """The numbers of a PRISMA 2020 flow diagram.

    Attributes:
        records_identified_total: Records imported from all sources.
        records_identified_by_source: Imported records per source label.
        duplicates_removed: Duplicates, counted as the reporting mode says.
        records_removed_before_screening_other: Removed for other reasons before screening
            (within-source duplicates in ``BETWEEN_DATABASES_ONLY`` mode, plus pre-filters).
        records_removed_by_prefilter: Part of the above that the pre-filters removed.
        prefilter_reasons: Pre-filter removals per reason code.
        records_after_deduplication: Identified minus all duplicates, before pre-filters.
        records_to_screen: Identified minus duplicates minus other removals.
        records_with_missing_abstracts: Records without an abstract, duplicates included
            (transparency, not a PRISMA box).
        records_screened_title_abstract: Included plus excluded at title/abstract level.
        records_excluded_title_abstract: Excluded at title/abstract level.
        reports_assessed_for_eligibility: Included plus excluded at full-text level.
        reports_excluded_fulltext: Excluded at full-text level.
        reports_excluded_reasons: Full-text exclusions per reason.
        studies_included_in_review: Final number of included studies.
        duplicates_reporting_mode: The mode the numbers follow.
    """

    records_identified_total: int = 0
    records_identified_by_source: dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    records_removed_before_screening_other: int = 0
    records_removed_by_prefilter: int = 0
    prefilter_reasons: dict[str, int] = field(default_factory=dict)
    records_after_deduplication: int = 0
    records_to_screen: int = 0
    records_with_missing_abstracts: int = 0
    records_screened_title_abstract: int = 0
    records_excluded_title_abstract: int = 0
    reports_assessed_for_eligibility: int = 0
    reports_excluded_fulltext: int = 0
    reports_excluded_reasons: dict[str, int] = field(default_factory=dict)
    studies_included_in_review: int = 0
    duplicates_reporting_mode: str = DuplicatesReportingMode.ALL_BEFORE_SCREENING.value
    # inputs kept for validation; not part of the published numbers
    ta_included: int = field(default=0, repr=False)
    dedup_global_before: int | None = field(default=None, repr=False)
    dedup_global_after: int | None = field(default=None, repr=False)
    dedup_global_removed: int | None = field(default=None, repr=False)
    merged_before_global_dedup: int | None = field(default=None, repr=False)
    within_source_removed: int = field(default=0, repr=False)
    stale_steps: tuple[str, ...] = field(default=(), repr=False)

    def to_dict(self) -> dict[str, Any]:
        """The published numbers as a plain dictionary (``prisma_flow.json``)."""
        data = asdict(self)
        for key in (*_INTERNAL_FIELDS, "dedup_global_removed"):
            data.pop(key)
        return data


@dataclass(frozen=True)
class FlowWarning:
    """A failed plausibility check of the flow.

    Attributes:
        code: Stable code such as ``ARITHMETIC_MISMATCH``.
        message: English explanation.
        payload: The numbers involved.
    """

    code: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


def _int(value: Any) -> int:
    """A non-negative integer from a payload value; anything unusable counts as 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, float):
        return max(0, int(value)) if math.isfinite(value) else 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _int_mapping(value: Any) -> dict[str, int]:
    """A ``{name: count}`` mapping from a payload value; anything else is empty."""
    if not isinstance(value, dict):
        return {}
    return {str(key): _int(item) for key, item in value.items()}


def _screening(events: list[PrismaEvent]) -> tuple[int, int, dict[str, int]]:
    """``(included, excluded, reasons)`` of the latest run among the events of one phase."""
    if not events:
        return 0, 0, {}
    last = events[-1]
    chosen = [last] if last.run_id is None else [e for e in events if e.run_id == last.run_id]
    included = sum(_int(e.payload.get("included")) for e in chosen)
    excluded = sum(_int(e.payload.get("excluded")) for e in chosen)
    reasons: dict[str, int] = {}
    for event in chosen:
        for key, value in _int_mapping(event.payload.get("reasons")).items():
            reasons[key] = reasons.get(key, 0) + value
    return included, excluded, reasons


def build_flow(
    events: Iterable[PrismaEvent],
    mode: DuplicatesReportingMode | str = DuplicatesReportingMode.ALL_BEFORE_SCREENING,
    *,
    final_included: int | None = None,
) -> PrismaFlow:
    """Fold events into the flow numbers.

    Args:
        events: The events in file order (later events of a snapshot kind win).
        mode: How to report duplicates.
        final_included: The final number of included studies; if None it is taken from the last
            screening phase that ran (full text if any, else title/abstract).

    Raises:
        ValueError: If ``mode`` is not a known reporting mode.
    """
    mode = DuplicatesReportingMode(mode)
    identified: dict[str, int] = {}
    within_by_label: dict[str, int] = {}
    dedup_global: dict[str, Any] = {}
    merged_before: int | None = None
    missing = 0
    retracted = 0
    prefilter_reasons: dict[str, int] = {}
    screening: dict[str, list[PrismaEvent]] = {
        EventType.SCREEN_TA.value: [],
        EventType.SCREEN_FT.value: [],
    }
    last_import = last_dedup = last_prefilter = last_validity = -1

    for position, event in enumerate(events):
        payload = event.payload
        if event.event_type == EventType.SOURCE_IMPORTED.value:
            label = str(payload.get("source_label", event.source_label or ""))
            identified[label] = identified.get(label, 0) + _int(payload.get("records_identified"))
            last_import = position
        elif event.event_type == EventType.DEDUP_WITHIN_SOURCE.value:
            label = str(payload.get("source_label", event.source_label or ""))
            within_by_label[label] = _int(payload.get("removed"))
        elif event.event_type == EventType.MERGE_ALL_SOURCES.value:
            merged_before = _int(payload.get("merged_records_before_global_dedup"))
        elif event.event_type == EventType.DEDUP_GLOBAL.value:
            dedup_global = dict(payload)
            last_dedup = position
        elif event.event_type == EventType.INFO.value and event.kind == "validity":
            missing = _int(payload.get("missing_count"))
            retracted = _int_mapping(payload.get("by_reason")).get("RETRACTED", 0)
            last_validity = position
        elif event.event_type == EventType.INFO.value and event.kind == "prefilter":
            prefilter_reasons = _int_mapping(payload.get("by_reason"))
            last_prefilter = position
        elif event.event_type in screening:
            screening[event.event_type].append(event)

    stale: list[str] = []
    if last_dedup >= 0 and last_import > last_dedup:
        stale.append("dedup")
    if last_dedup >= 0 and 0 <= last_prefilter < last_dedup:
        stale.append("prefilter")
        prefilter_reasons = {}
    if last_dedup >= 0 and 0 <= last_validity < last_dedup:
        stale.append("validity")
        missing, retracted = 0, 0
    if retracted:  # excluded retracted studies count as a pre-filter (plan 35.4)
        prefilter_reasons["RETRACTED"] = retracted

    identified_total = sum(identified.values())
    within_total = sum(within_by_label.values())
    across_removed = _int(dedup_global.get("removed"))
    # Duplicates come from the dedup events alone: records imported after the last dedup are not
    # duplicates, they are simply not checked yet.
    all_duplicates = min(identified_total, within_total + across_removed)
    after_dedup = identified_total - all_duplicates

    if mode == DuplicatesReportingMode.ALL_BEFORE_SCREENING:
        duplicates, other_dedup = all_duplicates, 0
    else:
        duplicates = min(identified_total, across_removed)
        other_dedup = all_duplicates - duplicates
    prefiltered = sum(prefilter_reasons.values())

    ta_included, ta_excluded, _ = _screening(screening[EventType.SCREEN_TA.value])
    ft_included, ft_excluded, ft_reasons = _screening(screening[EventType.SCREEN_FT.value])
    ft_assessed = ft_included + ft_excluded
    if final_included is None:
        final_included = ft_included if ft_assessed > 0 else ta_included

    return PrismaFlow(
        records_identified_total=identified_total,
        records_identified_by_source=dict(identified),
        duplicates_removed=duplicates,
        records_removed_before_screening_other=other_dedup + prefiltered,
        records_removed_by_prefilter=prefiltered,
        prefilter_reasons=prefilter_reasons,
        records_after_deduplication=after_dedup,
        records_to_screen=max(0, after_dedup - prefiltered),
        records_with_missing_abstracts=missing,
        records_screened_title_abstract=ta_included + ta_excluded,
        records_excluded_title_abstract=ta_excluded,
        reports_assessed_for_eligibility=ft_assessed,
        reports_excluded_fulltext=ft_excluded,
        reports_excluded_reasons=ft_reasons,
        studies_included_in_review=final_included,
        duplicates_reporting_mode=mode.value,
        ta_included=ta_included,
        dedup_global_before=(
            _int(dedup_global["before"]) if dedup_global.get("before") is not None else None
        ),
        dedup_global_after=(
            _int(dedup_global["after"]) if dedup_global.get("after") is not None else None
        ),
        dedup_global_removed=(across_removed if dedup_global else None),
        merged_before_global_dedup=merged_before,
        within_source_removed=within_total,
        stale_steps=tuple(stale),
    )


def validate_flow(flow: PrismaFlow) -> list[FlowWarning]:
    """Plausibility checks of the flow (port of ``validate_rollup``); empty if all is well."""
    found: list[FlowWarning] = []
    for step in flow.stale_steps:
        found.append(
            FlowWarning(
                f"STALE_{step.upper()}",
                f"The {step} step is out of date (records changed since it ran); run "
                "'crapai check' again.",
                {"step": step},
            )
        )
    before, after, removed = (
        flow.dedup_global_before,
        flow.dedup_global_after,
        flow.dedup_global_removed,
    )
    if before is not None and after is not None and after > before:
        found.append(
            FlowWarning(
                "DEDUP_AFTER_EXCEEDS_BEFORE",
                "Global dedup: 'after' exceeds 'before'.",
                {"before": before, "after": after},
            )
        )
    if (
        before is not None
        and after is not None
        and removed is not None
        and after != max(0, before - removed)
    ):
        found.append(
            FlowWarning(
                "ARITHMETIC_MISMATCH",
                "Global dedup: before - removed != after.",
                {"before": before, "removed": removed, "after": after},
            )
        )
    if (
        flow.merged_before_global_dedup is not None
        and "dedup" not in flow.stale_steps
        and flow.merged_before_global_dedup
        != flow.records_identified_total - flow.within_source_removed
    ):
        found.append(
            FlowWarning(
                "ARITHMETIC_MISMATCH",
                "Merged records != identified - duplicates within sources.",
                {
                    "merged_before": flow.merged_before_global_dedup,
                    "identified_total": flow.records_identified_total,
                    "within_source_removed": flow.within_source_removed,
                },
            )
        )
    if (
        flow.merged_before_global_dedup is not None
        and flow.merged_before_global_dedup > flow.records_identified_total
    ):
        found.append(
            FlowWarning(
                "MERGED_EXCEEDS_IDENTIFIED",
                "Merged-before-global-dedup exceeds the identified total.",
                {
                    "merged_before": flow.merged_before_global_dedup,
                    "identified_total": flow.records_identified_total,
                },
            )
        )
    if flow.records_screened_title_abstract > flow.records_to_screen:
        found.append(
            FlowWarning(
                "SCREENED_EXCEEDS_AVAILABLE",
                "More records screened at title/abstract than available after removals.",
                {
                    "screened": flow.records_screened_title_abstract,
                    "records_to_screen": flow.records_to_screen,
                },
            )
        )
    if flow.reports_assessed_for_eligibility > flow.ta_included:
        found.append(
            FlowWarning(
                "FULLTEXT_EXCEEDS_INCLUDED",
                "Full-text assessed exceeds title/abstract included (check pipeline rules).",
                {
                    "ft_assessed": flow.reports_assessed_for_eligibility,
                    "ta_included": flow.ta_included,
                },
            )
        )
    return found
