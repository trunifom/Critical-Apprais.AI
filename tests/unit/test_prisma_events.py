"""Tests for the PRISMA event model (task T-M2-07)."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest
from pydantic import ValidationError

from crapai.enums import EventType, LogLevel, PrismaStep, ScreeningPhase
from crapai.prisma import events as ev


def test_source_imported_has_the_contract_fields() -> None:
    event = ev.source_imported("PubMed", "p.nbib", "nbib", 12)
    assert event.event_type == EventType.SOURCE_IMPORTED.value
    assert event.step == PrismaStep.IMPORT.value
    assert event.level == LogLevel.INFO.value
    assert event.source_label == "PubMed" and event.run_id is None
    assert event.payload == {
        "source_label": "PubMed",
        "original_filename": "p.nbib",
        "file_type": "nbib",
        "records_identified": 12,
    }
    assert event.timestamp.tzinfo is UTC


def test_event_ids_are_unique() -> None:
    assert (
        ev.source_imported("a", "a", "ris", 1).event_id
        != ev.source_imported("a", "a", "ris", 1).event_id
    )


def test_json_line_round_trip_is_lossless_and_compact() -> None:
    event = ev.dedup_within_source("Ovid", 10, 3, "doi_or_title")
    line = ev.to_json_line(event)
    assert "\n" not in line and '"step":"dedup_per_source"' in line
    assert json.loads(line)["schema"] == ev.EVENT_SCHEMA
    assert ev.from_json_line(line) == event


def test_unicode_survives_the_round_trip() -> None:
    event = ev.source_imported("Zürich – Übersicht", "ä.ris", "ris", 1)
    assert "Zürich" in ev.to_json_line(event)
    assert ev.from_json_line(ev.to_json_line(event)).source_label == "Zürich – Übersicht"


@pytest.mark.parametrize(
    "line", ["", "not json", "[]", '{"step": "x"}', '{"step":"a","event_type":"b","bogus":1}']
)
def test_invalid_lines_raise_value_error(line: str) -> None:
    with pytest.raises(ValueError):
        ev.from_json_line(line)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ev.PrismaEvent(step="import", event_type="INFO", surprise=True)  # type: ignore[call-arg]


def test_dedup_events_carry_before_after_removed() -> None:
    within = ev.dedup_within_source("A", 10, 3, "title")
    assert (within.payload["before"], within.payload["after"], within.payload["removed"]) == (
        10,
        7,
        3,
    )
    assert (
        within.payload["scope"] == "within_source"
        and within.step == PrismaStep.DEDUP_PER_SOURCE.value
    )
    merged = ev.merge_all_sources({"A": 7, "B": 5}, 12)
    assert merged.payload["merged_records_before_global_dedup"] == 12
    assert merged.payload["inputs"] == {"A": 7, "B": 5}
    glob = ev.dedup_global(12, 2, "title")
    assert (glob.payload["after"], glob.payload["scope"]) == (10, "across_sources")
    assert glob.event_type == EventType.DEDUP_GLOBAL.value


def test_info_events_are_told_apart_by_kind() -> None:
    validity = ev.validity_checked(10, {"NO_ABSTRACT": 2, "DUPLICATE": 1})
    assert validity.event_type == EventType.INFO.value and validity.kind == "validity"
    assert validity.payload["missing_count"] == 2
    prefilter = ev.prefilter_applied(10, {"PREFILTER_YEAR": 2, "PREFILTER_LANGUAGE": 1})
    assert prefilter.kind == "prefilter" and prefilter.payload["removed"] == 3
    assert ev.source_imported("a", "a", "ris", 1).kind is None


def test_screening_events_follow_the_phase() -> None:
    ta = ev.screening_done(ScreeningPhase.ABSTRACT, 5, 20, 1, {"X": 2}, run_id="r1")
    assert ta.event_type == EventType.SCREEN_TA.value and ta.run_id == "r1"
    ft = ev.screening_done(ScreeningPhase.FULLTEXT, 2, 3)
    assert (
        ft.event_type == EventType.SCREEN_FT.value and ft.step == PrismaStep.SCREEN_FULLTEXT.value
    )
    assert ft.payload["reasons"] == {}


def test_warning_event_has_the_warning_level() -> None:
    event = ev.warning(PrismaStep.MERGE, "careful", {"a": 1})
    assert event.level == LogLevel.WARNING.value and event.event_type == EventType.WARNING.value
    assert event.payload == {"a": 1}


def test_no_network_or_database_import_in_the_modules() -> None:
    import crapai.prisma.events as events_module
    import crapai.prisma.flow as flow_module

    for module in (events_module, flow_module):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        for forbidden in ("supabase", "requests", "httpx", "urllib", "sqlite3", "openai"):
            assert f"import {forbidden}" not in source
