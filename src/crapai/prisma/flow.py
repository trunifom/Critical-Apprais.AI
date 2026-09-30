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
* ``SCREEN_TA`` and ``SCREEN_FT`` add up, as in the predecessor.

Two ways to report duplicates (``DuplicatesReportingMode``):

``ALL_BEFORE_SCREENING``
    Duplicates = everything removed by dedup (within + across sources).
``BETWEEN_DATABASES_ONLY``
    Duplicates = only those across sources; duplicates within a source are booked under
    "removed before screening (other)" so the arithmetic still balances.

Records removed by the pre-filters (and retracted studies, when they are excluded) are always
"other". No I/O, no network.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from crapai.enums import DuplicatesReportingMode, EventType
from crapai.prisma.events import PrismaEvent


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
        records_with_missing_abstracts: Records without abstract (transparency, not a PRISMA box).
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
    merged_before_global_dedup: int | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """The published numbers as a plain dictionary (``prisma_flow.json``)."""
        data = asdict(self)
        for key in ("ta_included", "dedup_global_before", "dedup_global_after"):
            data.pop(key)
        data.pop("merged_before_global_dedup")
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
    return int(value) if isinstance(value, (int, float)) else 0


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
    ta = {"included": 0, "excluded": 0}
    ft = {"included": 0, "excluded": 0}
    ft_reasons: dict[str, int] = {}

    for event in events:
        payload = event.payload
        if event.event_type == EventType.SOURCE_IMPORTED.value:
            label = str(payload.get("source_label", event.source_label or ""))
            identified[label] = identified.get(label, 0) + _int(payload.get("records_identified"))
        elif event.event_type == EventType.DEDUP_WITHIN_SOURCE.value:
            label = str(payload.get("source_label", event.source_label or ""))
            within_by_label[label] = _int(payload.get("removed"))
        elif event.event_type == EventType.MERGE_ALL_SOURCES.value:
            merged_before = _int(payload.get("merged_records_before_global_dedup"))
        elif event.event_type == EventType.DEDUP_GLOBAL.value:
            dedup_global = dict(payload)
        elif event.event_type == EventType.INFO.value and event.kind == "validity":
            missing = _int(payload.get("missing_count"))
            by_reason = payload.get("by_reason")
            retracted = _int(by_reason.get("RETRACTED")) if isinstance(by_reason, dict) else 0
        elif event.event_type == EventType.INFO.value and event.kind == "prefilter":
            by_reason = payload.get("by_reason")
            prefilter_reasons = (
                {str(k): _int(v) for k, v in by_reason.items()}
                if isinstance(by_reason, dict)
                else {}
            )
        elif event.event_type == EventType.SCREEN_TA.value:
            ta["included"] += _int(payload.get("included"))
            ta["excluded"] += _int(payload.get("excluded"))
        elif event.event_type == EventType.SCREEN_FT.value:
            ft["included"] += _int(payload.get("included"))
            ft["excluded"] += _int(payload.get("excluded"))
            reasons = payload.get("reasons")
            if isinstance(reasons, dict):
                for key, value in reasons.items():
                    ft_reasons[str(key)] = ft_reasons.get(str(key), 0) + _int(value)

    identified_total = sum(identified.values())
    within_total = sum(within_by_label.values())
    after_value = dedup_global.get("after")
    if after_value is not None:
        after_dedup = _int(after_value)
    else:
        after_dedup = max(0, identified_total - within_total)

    if mode == DuplicatesReportingMode.ALL_BEFORE_SCREENING:
        duplicates = max(0, identified_total - after_dedup)
        other_dedup = 0
    else:
        duplicates = _int(dedup_global.get("removed"))
        other_dedup = max(0, (identified_total - after_dedup) - duplicates)
    if retracted:  # excluded retracted studies count as a pre-filter (plan 35.4)
        prefilter_reasons["RETRACTED"] = retracted
    prefiltered = sum(prefilter_reasons.values())
    other = other_dedup + prefiltered

    ft_assessed = ft["included"] + ft["excluded"]
    if final_included is None:
        final_included = ft["included"] if ft_assessed > 0 else ta["included"]

    return PrismaFlow(
        records_identified_total=identified_total,
        records_identified_by_source=dict(identified),
        duplicates_removed=duplicates,
        records_removed_before_screening_other=other,
        records_removed_by_prefilter=prefiltered,
        prefilter_reasons=prefilter_reasons,
        records_after_deduplication=after_dedup,
        records_to_screen=max(0, identified_total - duplicates - other),
        records_with_missing_abstracts=missing,
        records_screened_title_abstract=ta["included"] + ta["excluded"],
        records_excluded_title_abstract=ta["excluded"],
        reports_assessed_for_eligibility=ft_assessed,
        reports_excluded_fulltext=ft["excluded"],
        reports_excluded_reasons=ft_reasons,
        studies_included_in_review=final_included,
        duplicates_reporting_mode=mode.value,
        ta_included=ta["included"],
        dedup_global_before=(
            _int(dedup_global["before"]) if dedup_global.get("before") is not None else None
        ),
        dedup_global_after=None if after_value is None else _int(after_value),
        merged_before_global_dedup=merged_before,
    )


def validate_flow(flow: PrismaFlow) -> list[FlowWarning]:
    """Plausibility checks of the flow (port of ``validate_rollup``); empty if all is well."""
    found: list[FlowWarning] = []
    if (
        flow.dedup_global_before is not None
        and flow.dedup_global_after is not None
        and flow.dedup_global_after > flow.dedup_global_before
    ):
        found.append(
            FlowWarning(
                "DEDUP_AFTER_EXCEEDS_BEFORE",
                "Global dedup: 'after' exceeds 'before'.",
                {"before": flow.dedup_global_before, "after": flow.dedup_global_after},
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
    balance = (
        flow.records_identified_total
        - flow.duplicates_removed
        - flow.records_removed_before_screening_other
    )
    expected = flow.records_after_deduplication - flow.records_removed_by_prefilter
    if balance != expected:
        found.append(
            FlowWarning(
                "ARITHMETIC_MISMATCH",
                "PRISMA arithmetic mismatch: identified - removed != records to screen.",
                {"identified_minus_removed": balance, "after_dedup_minus_prefilter": expected},
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
