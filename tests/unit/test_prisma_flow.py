"""Tests for the PRISMA flow numbers (task T-M2-07).

The arithmetic is checked against the predecessor: the read-only snapshot
``reference/sara-app/core/prisma_logger.py`` is loaded as an oracle (its ``core.enums`` import is
served by our identical ``crapai.enums``) and fed the same facts.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import crapai.enums as our_enums
from crapai.enums import DuplicatesReportingMode, PrismaStep, ScreeningPhase
from crapai.prisma import events as ev
from crapai.prisma.flow import build_flow, validate_flow

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference" / "sara-app" / "core" / "prisma_logger.py"
ALL = DuplicatesReportingMode.ALL_BEFORE_SCREENING
BETWEEN = DuplicatesReportingMode.BETWEEN_DATABASES_ONLY


def load_oracle() -> Any:
    if not REFERENCE.exists():
        pytest.skip("reference snapshot not available")
    package = types.ModuleType("core")
    package.__path__ = []  # type: ignore[attr-defined]
    saved = {name: sys.modules.get(name) for name in ("core", "core.enums")}
    sys.modules["core"] = package
    sys.modules["core.enums"] = our_enums
    try:
        spec = importlib.util.spec_from_file_location("prisma_logger_oracle", REFERENCE)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def scenario(within: dict[str, int], across: int, sizes: dict[str, int]) -> list[ev.PrismaEvent]:
    """Imports, the per-source dedup snapshot, the merge and the global dedup."""
    events = [ev.source_imported(label, f"{label}.ris", "ris", n) for label, n in sizes.items()]
    events += [ev.dedup_within_source(k, sizes[k], within.get(k, 0), "m") for k in sizes]
    merged = sum(sizes.values()) - sum(within.values())
    events.append(ev.merge_all_sources({k: sizes[k] - within.get(k, 0) for k in sizes}, merged))
    events.append(ev.dedup_global(merged, across, "m"))
    return events


def test_example_with_both_reporting_modes() -> None:
    events = scenario({"A": 2, "B": 1}, across=4, sizes={"A": 20, "B": 10, "C": 5})
    all_mode = build_flow(events, ALL)
    assert all_mode.records_identified_total == 35
    assert all_mode.records_identified_by_source == {"A": 20, "B": 10, "C": 5}
    assert all_mode.records_after_deduplication == 28
    assert all_mode.duplicates_removed == 7
    assert all_mode.records_removed_before_screening_other == 0
    assert all_mode.records_to_screen == 28
    between = build_flow(events, BETWEEN)
    assert between.duplicates_removed == 4
    assert between.records_removed_before_screening_other == 3  # within-source, booked as other
    assert between.records_after_deduplication == 28 and between.records_to_screen == 28


def test_mode_may_be_given_as_text_and_unknown_mode_is_an_error() -> None:
    assert build_flow([], "between_databases_only").duplicates_reporting_mode == BETWEEN.value
    with pytest.raises(ValueError):
        build_flow([], "nonsense")


def test_no_events_give_an_all_zero_flow() -> None:
    flow = build_flow([])
    assert flow.records_identified_total == 0 and flow.records_to_screen == 0
    assert flow.studies_included_in_review == 0
    assert validate_flow(flow) == []


def test_without_a_global_step_after_dedup_falls_back_to_within_source() -> None:
    events = [ev.source_imported("A", "a", "ris", 10), ev.dedup_within_source("A", 10, 4, "m")]
    flow = build_flow(events, ALL)
    assert flow.records_after_deduplication == 6 and flow.duplicates_removed == 4


def test_running_dedup_twice_does_not_count_twice() -> None:
    sizes = {"A": 10, "B": 10}
    once = scenario({"A": 2}, 3, sizes)
    snapshot = once[len(sizes) :]  # everything after the imports
    flow = build_flow(once + snapshot, ALL)
    assert flow == build_flow(once, ALL)
    assert flow.duplicates_removed == 5 and flow.records_after_deduplication == 15


def test_a_later_dedup_snapshot_replaces_the_earlier_one() -> None:
    imports = [ev.source_imported("A", "a", "ris", 10), ev.source_imported("B", "b", "ris", 10)]
    first = scenario({"A": 2}, 3, {"A": 10, "B": 10})[2:]
    second = [
        ev.dedup_within_source("A", 10, 0, "m"),
        ev.dedup_within_source("B", 10, 0, "m"),
        ev.dedup_global(20, 1, "m"),
    ]
    flow = build_flow(imports + first + second, ALL)
    assert flow.duplicates_removed == 1 and flow.records_after_deduplication == 19


def test_imports_add_up_across_files_with_the_same_label() -> None:
    events = [ev.source_imported("A", "a1", "ris", 3), ev.source_imported("A", "a2", "ris", 4)]
    assert build_flow(events).records_identified_by_source == {"A": 7}


def test_validity_snapshot_reports_missing_abstracts_latest_wins() -> None:
    events = [
        ev.validity_checked(10, {"NO_ABSTRACT": 4}),
        ev.validity_checked(10, {"NO_ABSTRACT": 2}),
    ]
    assert build_flow(events).records_with_missing_abstracts == 2


def test_prefilters_are_removed_before_screening_other() -> None:
    reasons = {"PREFILTER_YEAR": 3, "RETRACTED": 1}
    events = scenario({}, 2, {"A": 20}) + [ev.prefilter_applied(18, reasons)]
    for mode in (ALL, BETWEEN):
        flow = build_flow(events, mode)
        assert flow.records_removed_by_prefilter == 4
        assert flow.prefilter_reasons == reasons
        assert flow.records_removed_before_screening_other == 4
        assert flow.records_after_deduplication == 18 and flow.records_to_screen == 14
        assert validate_flow(flow) == []


def test_prefilter_snapshot_latest_wins() -> None:
    events = [ev.prefilter_applied(10, {"PREFILTER_YEAR": 5}), ev.prefilter_applied(10, {})]
    assert build_flow(events).records_removed_by_prefilter == 0


def test_ai_prefilter_is_removed_before_screening_other_in_its_own_field() -> None:
    """ADR 0029: a separate field from the deterministic prefilter, folded into the same
    'other' total and subtracted from 'to screen', so the arithmetic still balances."""
    reasons = {"AI_PREFILTER_JEV": 3}
    events = scenario({}, 2, {"A": 20}) + [ev.ai_prefilter_applied(18, 3, reasons)]
    for mode in (ALL, BETWEEN):
        flow = build_flow(events, mode)
        assert flow.records_removed_by_ai_prefilter == 3
        assert flow.ai_prefilter_reasons == reasons
        assert flow.records_removed_before_screening_other == 3
        assert flow.records_after_deduplication == 18 and flow.records_to_screen == 15
        assert validate_flow(flow) == []


def test_ai_prefilter_and_deterministic_prefilter_add_up_independently() -> None:
    events = (
        scenario({}, 0, {"A": 20})
        + [ev.prefilter_applied(20, {"PREFILTER_YEAR": 2})]
        + [ev.ai_prefilter_applied(20, 3, {"AI_PREFILTER_JEV": 3})]
    )
    flow = build_flow(events, ALL)
    assert flow.records_removed_by_prefilter == 2
    assert flow.records_removed_by_ai_prefilter == 3
    assert flow.records_removed_before_screening_other == 5
    assert flow.records_to_screen == 20 - 2 - 3


def test_ai_prefilter_snapshot_is_never_stale_after_a_later_dedup_run() -> None:
    """Unlike the deterministic pre-filter, dedup never replaces AI_PREFILTER_JEV (ADR 0029), so
    a dedup event coming after the AI pre-filter event must not flag it as stale."""
    events = [
        ev.ai_prefilter_applied(10, 2, {"AI_PREFILTER_JEV": 2}),
        *scenario({}, 1, {"A": 10}),
    ]
    flow = build_flow(events, ALL)
    assert flow.records_removed_by_ai_prefilter == 2
    assert "ai_prefilter" not in flow.stale_steps
    assert validate_flow(flow) == []


def test_ai_prefilter_snapshot_latest_wins() -> None:
    events = [
        ev.ai_prefilter_applied(10, 5, {"AI_PREFILTER_JEV": 5}),
        ev.ai_prefilter_applied(10, 0, {}),
    ]
    assert build_flow(events).records_removed_by_ai_prefilter == 0


def test_screening_phases_and_final_included() -> None:
    events = scenario({}, 0, {"A": 100}) + [
        ev.screening_done(ScreeningPhase.ABSTRACT, 20, 70),
        ev.screening_done(
            ScreeningPhase.FULLTEXT, 8, 12, reasons={"wrong population": 7, "x": 5}, run_id="r1"
        ),
        ev.screening_done(ScreeningPhase.FULLTEXT, 0, 1, reasons={"x": 1}, run_id="r1"),
    ]
    flow = build_flow(events, ALL)
    assert flow.records_screened_title_abstract == 90 and flow.records_excluded_title_abstract == 70
    assert flow.reports_assessed_for_eligibility == 21 and flow.reports_excluded_fulltext == 13
    assert flow.reports_excluded_reasons == {"wrong population": 7, "x": 6}
    assert flow.studies_included_in_review == 8  # full text decides if it ran
    assert build_flow(events, final_included=6).studies_included_in_review == 6
    assert build_flow(events[:-2], ALL).studies_included_in_review == 20


def test_to_dict_publishes_the_numbers_but_not_the_helper_inputs() -> None:
    data = build_flow(scenario({"A": 1}, 1, {"A": 5})).to_dict()
    assert data["records_identified_total"] == 5
    assert data["duplicates_reporting_mode"] == "all_before_screening"
    for hidden in ("ta_included", "dedup_global_before", "dedup_global_after"):
        assert hidden not in data
    assert "merged_before_global_dedup" not in data


def test_malformed_payload_values_count_as_zero() -> None:
    bad = ev.PrismaEvent(
        step="import",
        event_type="SOURCE_IMPORTED",
        payload={"source_label": "A", "records_identified": "x"},
    )
    info = ev.PrismaEvent(
        step="import", event_type="INFO", payload={"kind": "prefilter", "by_reason": 5}
    )
    flow = build_flow([bad, info])
    assert flow.records_identified_total == 0 and flow.records_removed_by_prefilter == 0


# --- validation -------------------------------------------------------------------------------


def codes(events: list[ev.PrismaEvent], mode: DuplicatesReportingMode = ALL) -> set[str]:
    return {w.code for w in validate_flow(build_flow(events, mode))}


def test_a_consistent_flow_has_no_warnings() -> None:
    assert codes(scenario({"A": 1}, 2, {"A": 10, "B": 5})) == set()


def test_dedup_after_above_before_is_reported() -> None:
    glob = ev.dedup_global(5, 0, "m")
    glob.payload["after"] = 9
    assert "DEDUP_AFTER_EXCEEDS_BEFORE" in codes([ev.source_imported("A", "a", "ris", 5), glob])


def test_merge_above_identified_is_reported() -> None:
    events = [ev.source_imported("A", "a", "ris", 5), ev.merge_all_sources({"A": 8}, 8)]
    assert "MERGED_EXCEEDS_IDENTIFIED" in codes(events)


def test_arithmetic_mismatch_is_reported_when_removals_exceed_the_records() -> None:
    glob = ev.dedup_global(5, 2, "m")
    glob.payload["removed"] = 9  # contradicts before=5, after=3
    events = [ev.source_imported("A", "a", "ris", 5), glob]
    assert "ARITHMETIC_MISMATCH" in codes(events, BETWEEN)


def test_too_many_screened_and_full_text_above_included_are_reported() -> None:
    events = scenario({}, 0, {"A": 10}) + [
        ev.screening_done(ScreeningPhase.ABSTRACT, 3, 20),
        ev.screening_done(ScreeningPhase.FULLTEXT, 2, 4),
    ]
    assert codes(events) == {"SCREENED_EXCEEDS_AVAILABLE", "FULLTEXT_EXCEEDS_INCLUDED"}


def test_warning_and_export_events_do_not_change_the_numbers() -> None:
    base = scenario({}, 1, {"A": 10})
    noisy = [
        *base,
        ev.warning(PrismaStep.MERGE, "x"),
        ev.PrismaEvent(step="export", event_type="EXPORT"),
    ]
    assert build_flow(noisy) == build_flow(base)


# --- oracle: the predecessor's logger ---------------------------------------------------------

FLOW_KEYS = (
    "records_identified_total",
    "records_identified_by_source",
    "duplicates_removed",
    "records_removed_before_screening_other",
    "records_after_deduplication",
    "records_with_missing_abstracts",
    "records_screened_title_abstract",
    "records_excluded_title_abstract",
    "reports_assessed_for_eligibility",
    "reports_excluded_fulltext",
    "reports_excluded_reasons",
    "studies_included_in_review",
)
Facts = tuple[dict[str, int], dict[str, int], int, int, tuple[int, int], tuple[int, int]]


def oracle_flow(facts: Facts, mode: DuplicatesReportingMode) -> dict[str, Any]:
    sizes, within, across, missing, ta, ft = facts
    logger = load_oracle().PRISMALogger("p", "t", duplicates_reporting_mode=mode)
    for label, n in sizes.items():
        logger.log_source_imported(label, label, f"{label}.ris", "ris", n)
    for label, n in sizes.items():
        marked = within.get(label, 0)
        logger.log_dedup_within_source(label, label, n, n - marked, "m", duplicates_marked=marked)
    merged = sum(sizes.values()) - sum(within.values())
    logger.log_merge_all_sources([], merged)
    logger.log_dedup_global(merged, merged - across, "m", duplicates_marked=across)
    logger.log_missing_abstracts_marked("across_sources", sum(sizes.values()), missing)
    logger.log_screening(ScreeningPhase.ABSTRACT, ta[0], ta[1])
    if ft != (0, 0):
        logger.log_screening(ScreeningPhase.FULLTEXT, ft[0], ft[1], reasons={"r": ft[1]})
    return logger.to_prisma_flow()  # type: ignore[no-any-return]


def our_flow(facts: Facts, mode: DuplicatesReportingMode) -> dict[str, Any]:
    sizes, within, across, missing, ta, ft = facts
    events = scenario(within, across, sizes)
    events.append(ev.validity_checked(sum(sizes.values()), {"NO_ABSTRACT": missing}))
    events.append(ev.screening_done(ScreeningPhase.ABSTRACT, *ta))
    if ft != (0, 0):
        events.append(
            ev.screening_done(ScreeningPhase.FULLTEXT, ft[0], ft[1], reasons={"r": ft[1]})
        )
    return build_flow(events, mode).to_dict()


def same_numbers(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return {k: actual[k] for k in FLOW_KEYS} == {k: expected[k] for k in FLOW_KEYS}


@pytest.mark.parametrize("mode", [ALL, BETWEEN])
def test_numbers_equal_the_predecessors_to_prisma_flow(mode: DuplicatesReportingMode) -> None:
    facts: Facts = ({"A": 120, "B": 80, "C": 40}, {"A": 10, "C": 3}, 25, 14, (30, 77), (12, 18))
    assert same_numbers(our_flow(facts, mode), oracle_flow(facts, mode))


@settings(max_examples=60, deadline=None)
@given(
    sizes=st.dictionaries(st.sampled_from("ABCD"), st.integers(1, 200), min_size=1),
    data=st.data(),
    mode=st.sampled_from([ALL, BETWEEN]),
)
def test_equal_to_the_predecessor_for_random_projects(
    sizes: dict[str, int], data: st.DataObject, mode: DuplicatesReportingMode
) -> None:
    within = {label: data.draw(st.integers(0, n - 1)) for label, n in sizes.items()}
    left = sum(sizes.values()) - sum(within.values())
    across = data.draw(st.integers(0, max(0, left - 1)))
    facts: Facts = (
        sizes,
        within,
        across,
        data.draw(st.integers(0, sum(sizes.values()))),
        (data.draw(st.integers(0, 50)), data.draw(st.integers(0, 50))),
        (data.draw(st.integers(0, 20)), data.draw(st.integers(0, 20))),
    )
    assert same_numbers(our_flow(facts, mode), oracle_flow(facts, mode))


# --- stale snapshots, repeated runs, independent arithmetic (review fixes) ----------------------


def test_records_imported_after_the_last_dedup_are_not_reported_as_duplicates() -> None:
    events = scenario({}, 10, {"A": 100})  # 100 records, 10 duplicates
    events.append(ev.source_imported("B", "b.ris", "ris", 50))  # dedup has not seen these
    flow = build_flow(events, ALL)
    assert flow.duplicates_removed == 10 and flow.records_after_deduplication == 140
    assert flow.records_to_screen == 140
    assert flow.stale_steps == ("dedup",)
    assert {w.code for w in validate_flow(flow)} >= {"STALE_DEDUP"}


def test_a_dedup_after_the_prefilter_makes_the_prefilter_stale_and_avoids_double_counting() -> None:
    events = scenario({}, 0, {"A": 100}) + [ev.prefilter_applied(100, {"PREFILTER_YEAR": 10})]
    assert build_flow(events).records_removed_by_prefilter == 10
    events += scenario({}, 4, {"A": 100})[1:]  # dedup runs again: 4 of those become duplicates
    flow = build_flow(events, ALL)
    assert flow.stale_steps == ("prefilter",)
    assert flow.records_removed_by_prefilter == 0 and flow.records_to_screen == 96
    assert "STALE_PREFILTER" in {w.code for w in validate_flow(flow)}


def test_a_dedup_after_the_validity_check_makes_it_stale() -> None:
    events = scenario({}, 0, {"A": 10}) + [ev.validity_checked(10, {"RETRACTED": 2}, 3)]
    assert build_flow(events).prefilter_reasons == {"RETRACTED": 2}
    events += scenario({}, 1, {"A": 10})[1:]
    flow = build_flow(events)
    assert flow.prefilter_reasons == {} and flow.records_with_missing_abstracts == 0
    assert "validity" in flow.stale_steps


def test_a_repeated_screening_run_replaces_the_earlier_one() -> None:
    events = scenario({}, 0, {"A": 300}) + [
        ev.screening_done(ScreeningPhase.ABSTRACT, 30, 170, run_id="run-1"),
        ev.screening_done(ScreeningPhase.ABSTRACT, 40, 160, run_id="run-2"),
    ]
    flow = build_flow(events)
    assert flow.records_screened_title_abstract == 200 and flow.studies_included_in_review == 40
    assert validate_flow(flow) == []


def test_events_of_one_run_add_up() -> None:
    events = scenario({}, 0, {"A": 300}) + [
        ev.screening_done(ScreeningPhase.ABSTRACT, 10, 90, run_id="r"),
        ev.screening_done(ScreeningPhase.ABSTRACT, 5, 95, run_id="r"),
    ]
    assert build_flow(events).records_screened_title_abstract == 200


def test_missing_abstracts_come_from_the_validity_event_not_from_the_reason() -> None:
    event = ev.validity_checked(300, {"DUPLICATE": 20}, without_abstract=300)
    assert build_flow([event]).records_with_missing_abstracts == 300
    assert ev.validity_checked(10, {"NO_ABSTRACT": 4}).payload["missing_count"] == 4


def test_arithmetic_checks_use_independent_numbers() -> None:
    events = scenario({"A": 2}, 3, {"A": 20})
    merge = next(e for e in events if e.event_type == "MERGE_ALL_SOURCES")
    merge.payload["merged_records_before_global_dedup"] = 17  # should be 20 - 2 = 18
    assert "ARITHMETIC_MISMATCH" in {w.code for w in validate_flow(build_flow(events))}
    consistent = scenario({"A": 2}, 3, {"A": 20})
    assert validate_flow(build_flow(consistent)) == []


@pytest.mark.parametrize(
    "value,expected", [(5, 5), (-3, 0), (4.9, 4), ("12", 12), (" 7 ", 7), ("x", 0), (None, 0),
                       (True, 0), (float("nan"), 0), (float("inf"), 0)],
)  # fmt: skip
def test_payload_numbers_are_read_defensively(value: object, expected: int) -> None:
    from crapai.prisma.flow import _int

    assert _int(value) == expected
