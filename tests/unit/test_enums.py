"""Enum values are persisted in logs and files, so they must never change silently."""

from crapai.enums import EventType, Framework, PreflightIssueCode, PreflightStatus, RunStatus


def test_string_enum_str_returns_value() -> None:
    assert str(PreflightStatus.WARNING) == "warning"
    assert PreflightStatus.OK == "ok"


def test_persisted_event_types_are_stable() -> None:
    expected = {
        "SOURCE_IMPORTED",
        "DEDUP_WITHIN_SOURCE",
        "MERGE_ALL_SOURCES",
        "DEDUP_GLOBAL",
        "SCREEN_TA",
        "SCREEN_FT",
        "EXPORT",
        "WARNING",
        "ERROR",
        "INFO",
    }
    assert {e.value for e in EventType} == expected


def test_run_status_and_framework_values() -> None:
    assert {s.value for s in RunStatus} == {"running", "completed", "failed", "canceled"}
    assert Framework.PICOS.value == "PICOS"


def test_preflight_issue_codes() -> None:
    assert PreflightIssueCode.NO_ABSTRACTS.value == "no_abstracts"
