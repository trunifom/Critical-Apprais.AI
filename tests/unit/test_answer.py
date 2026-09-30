"""The model's answer: validation, consistency, quote check, legacy format (plan chapter 10)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from crapai.errors import ParseError
from crapai.screening import answer as a


def body(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inclusion": [{"criterion": "Population", "verdict": "met", "note": "adults", "quote": "adults were enrolled"}],
        "exclusion": [{"criterion": "Design", "verdict": "not_triggered", "note": "rct"}],
        "ambiguities": [],
        "reasoning": "Fits.",
        "decision": "INCLUDE",
    }  # fmt: skip
    data.update(changes)
    return data


def parse(**changes: Any) -> a.Answer:
    return a.parse_answer(json.dumps(body(**changes)))


def reason(text: str) -> str:
    with pytest.raises(ParseError) as info:
        a.parse_answer(text)
    assert info.value.code == "E304"
    return str(info.value.details["reason"])


def test_a_valid_answer_is_parsed() -> None:
    answer = parse()
    assert (
        answer.decision == "INCLUDE" and answer.derived_decision == "INCLUDE" and answer.consistent
    )
    assert answer.inclusion[0].criterion == "Population" and answer.inclusion[0].quote
    assert answer.reasoning == "Fits." and answer.ambiguities == []


@pytest.mark.parametrize(
    "wrapper", ["```json\n{}\n```", "```\n{}\n```", "Here is my answer:\n{}\nThanks", "  {}  "]
)
def test_fences_and_chatter_around_the_json_are_tolerated(wrapper: str) -> None:
    assert a.parse_answer(wrapper.replace("{}", json.dumps(body()))).decision == "INCLUDE"


@pytest.mark.parametrize(
    "text", ["", "   \n", "I think include", "{not json", "[1, 2]", '"INCLUDE"', "null"]
)
def test_unreadable_answers_are_errors_not_inclusions(text: str) -> None:
    reason(text)  # the predecessor counted all of these as an inclusion


def test_each_required_field_is_needed() -> None:
    for name in ("inclusion", "exclusion", "reasoning", "decision"):
        data = body()
        del data[name]
        assert name in reason(json.dumps(data))


def test_unknown_fields_are_refused() -> None:
    assert "unknown field" in reason(json.dumps(body(confidence=0.9)))


@pytest.mark.parametrize("decision", ["include", "MAYBE", "", None, 1])
def test_the_decision_must_be_one_of_three(decision: Any) -> None:
    assert "decision" in reason(json.dumps(body(decision=decision)))


@pytest.mark.parametrize(
    "changes",
    [
        {"inclusion": "met"},
        {"inclusion": ["x"]},
        {"inclusion": [{"verdict": "met"}]},
        {"inclusion": [{"criterion": "P", "verdict": "triggered"}]},
        {"exclusion": [{"criterion": "D", "verdict": "met"}]},
        {"exclusion": [{"criterion": " ", "verdict": "triggered"}]},
        {"inclusion": [{"criterion": "P", "verdict": "met", "note": 5}]},
        {"ambiguities": "none"},
        {"ambiguities": [1]},
        {"reasoning": 5},
    ],
)
def test_malformed_parts_are_refused(changes: dict[str, Any]) -> None:
    reason(json.dumps(body(**changes)))


def test_long_texts_are_cut_not_refused() -> None:
    answer = parse(
        reasoning="x" * 2000, inclusion=[{"criterion": "P", "verdict": "met", "note": "n" * 999}]
    )
    assert len(answer.reasoning) == a.MAX_REASONING and len(answer.inclusion[0].note) == a.MAX_NOTE


@pytest.mark.parametrize(
    "inclusion,exclusion,expected",
    [
        (["met", "met"], ["not_triggered"], "INCLUDE"),
        (["met", "met"], ["triggered"], "EXCLUDE"),
        (["met", "not_met"], ["not_triggered"], "EXCLUDE"),
        (["met", "unclear"], ["not_triggered"], "UNCERTAIN"),
        (["unclear"], ["unclear"], "UNCERTAIN"),
        (["met"], ["unclear"], "INCLUDE"),
        ([], [], "UNCERTAIN"),
        (["not_met", "unclear"], ["triggered"], "EXCLUDE"),
    ],
)
def test_the_derived_decision(inclusion: list[str], exclusion: list[str], expected: str) -> None:
    inc = [a.Verdict(f"i{n}", v) for n, v in enumerate(inclusion)]
    exc = [a.Verdict(f"e{n}", v) for n, v in enumerate(exclusion)]
    assert a.derive_decision(inc, exc) == expected


def test_a_contradicting_answer_is_marked_inconsistent_not_corrected() -> None:
    answer = parse(
        exclusion=[{"criterion": "Design", "verdict": "triggered", "note": "case report"}]
    )
    assert (
        answer.decision == "INCLUDE"
        and answer.derived_decision == "EXCLUDE"
        and not answer.consistent
    )


RECORD = "Effects of exercise\nAdults were enrolled in a randomised trial of aerobic exercise."


@pytest.mark.parametrize(
    "quote,found",
    [
        ("Adults were enrolled", True),
        ("adults   were\nenrolled!", True),  # case, blanks, punctuation do not matter
        ("Adults ... aerobic exercise", True),  # an ellipsis joins parts
        ("ADULTS WERE ENROLLED IN A RANDOMISED TRIAL", True),
        ("children were enrolled", False),
        ("Adults ... chemotherapy", False),
        ("", True),  # no quote, nothing to check
    ],
)
def test_quotes_must_come_from_the_record(quote: str, found: bool) -> None:
    answer = parse(
        inclusion=[{"criterion": "Population", "verdict": "met", "note": "n", "quote": quote}]
    )
    assert (a.check_quotes(answer, RECORD) == []) is found
    assert answer.unverified_quotes == ([] if found else ["Population"])


def test_quotes_of_exclusion_criteria_are_checked_too() -> None:
    answer = parse(
        exclusion=[
            {"criterion": "Design", "verdict": "not_triggered", "note": "n", "quote": "made up"}
        ]
    )
    assert a.check_quotes(answer, RECORD) == ["Design"]


@pytest.mark.parametrize(
    "text,decision",
    [
        ("Reasoning here.\nXXX", "EXCLUDE"),
        ("Reasoning.\nYYY", "INCLUDE"),
        ("yyy", "INCLUDE"),
        ("r\n'XXX'", "EXCLUDE"),
        ("r\n**YYY**", "INCLUDE"),
    ],
)
def test_the_legacy_last_line(text: str, decision: str) -> None:
    answer = a.parse_legacy(text)
    assert answer.decision == decision and answer.consistent


@pytest.mark.parametrize(
    "text", ["", "no decision here", "Final: maybe", "XXX is my answer", "YYY\nbut wait"]
)
def test_a_legacy_answer_without_a_clear_last_line_is_an_error(text: str) -> None:
    with pytest.raises(ParseError):
        a.parse_legacy(text)


def test_the_published_schema_names_the_required_fields_and_orders_the_decision_last() -> None:
    assert a.ANSWER_SCHEMA["required"] == ["inclusion", "exclusion", "reasoning", "decision"]
    assert list(a.ANSWER_SCHEMA["properties"])[-1] == "decision"
    assert a.ANSWER_SCHEMA["additionalProperties"] is False
