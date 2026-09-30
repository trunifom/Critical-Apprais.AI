import json

import pytest

from saralocal.criteria.template import CriteriaTemplate


def test_picos_fields_in_order() -> None:
    tpl = CriteriaTemplate("PICOS")
    assert tpl.get_fields() == [
        "Population",
        "Intervention",
        "Comparison",
        "Outcome",
        "Study Design",
    ]


def test_framework_name_is_case_insensitive() -> None:
    assert CriteriaTemplate("pird").get_fields()[0] == "Population"


def test_update_and_completeness() -> None:
    tpl = CriteriaTemplate("PECO")
    assert not tpl.is_complete()
    for field in tpl.get_fields():
        tpl.update_inclusion(field, "  something  ")
    assert tpl.is_complete()
    assert tpl.inclusion["Population"] == "something"  # stripped


def test_unknown_field_raises_key_error() -> None:
    with pytest.raises(KeyError):
        CriteriaTemplate("PICOS").update_inclusion("Nope", "x")


def test_invalid_framework_raises_value_error() -> None:
    with pytest.raises(ValueError):
        CriteriaTemplate("FOO")


def test_custom_fields_and_prompt_string() -> None:
    tpl = CriteriaTemplate("CUSTOM", custom_fields=["Population", "Outcome"])
    tpl.update_inclusion("Population", "school-aged children")
    text = tpl.to_prompt_string()
    assert "Framework: CUSTOM" in text
    assert "Population:" in text
    assert "Inclusion: school-aged children" in text
    assert "Exclusion: -" in text  # marker for empty values


def test_as_dict_is_json_serialisable() -> None:
    json.dumps(CriteriaTemplate("SPIDER").as_dict())
