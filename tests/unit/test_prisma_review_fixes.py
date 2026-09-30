"""Regression tests for defects found in the review of dedup, pre-filters, validity and criteria."""

from __future__ import annotations

from typing import Any

import pytest

from crapai.criteria.template import CriteriaTemplate
from crapai.io.records_store import Record
from crapai.prisma.dedup import (
    MIN_TITLE_WORDS,
    DedupConfig,
    doi_key,
    mark_duplicates,
    title_key,
)
from crapai.prisma.prefilters import (
    PrefilterConfig,
    languages_of,
    mark_prefilters,
    normalize_language,
)
from crapai.prisma.validity import classify_abstract

_counter = iter(range(10_000))


def rec(title: str = "", doi: str = "", **extra: Any) -> Record:
    values: dict[str, Any] = {
        "study_uid": f"u{next(_counter)}",
        "source_label": "S",
        "source_file": "f.ris",
        "source_row": 1,
        "source_format": "ris",
        "title": title,
        "doi": doi,
        "abstract": "An abstract of reasonable length. " * 5,
    }
    values.update(extra)
    return Record.model_validate(values)


# --- dedup: generic titles and DOI forms ---------------------------------------------------------


@pytest.mark.parametrize("title", ["Editorial", "Erratum", "Letter to editor", "Comment on X"])
def test_generic_short_titles_are_not_duplicates_of_each_other(title: str) -> None:
    result = mark_duplicates([rec(title), rec(title)])
    assert result.marked == 0  # used to merge two unrelated "Editorial" records


def test_short_titles_still_match_through_a_shared_doi() -> None:
    result = mark_duplicates([rec("Editorial", "10.1000/x"), rec("Editorial", "10.1000/x")])
    assert result.marked == 1 and result.by_method == {"doi": 1}


def test_a_title_of_four_words_matches() -> None:
    title = "Effects of exercise on depression"
    assert len(title.split()) >= MIN_TITLE_WORDS
    assert mark_duplicates([rec(title), rec(title.upper())]).marked == 1


def test_the_guard_is_configurable() -> None:
    records = [rec("Editorial"), rec("editorial.")]
    assert mark_duplicates(records, DedupConfig(min_title_words=1)).marked == 1
    with pytest.raises(ValueError):
        mark_duplicates(records, DedupConfig(min_title_words=0))


def test_title_key_is_empty_below_the_minimum() -> None:
    assert title_key("One two three") == "" and title_key("One two three four") != ""
    assert title_key("One two", min_words=2) == "one two"


@pytest.mark.parametrize(
    "a,b",
    [
        ("10.1000/ABC", "10.1000/abc"),
        ("https://doi.org/10.1000/abc", "10.1000/abc"),
        ("doi:10.1000/abc", "10.1000/ABC"),
    ],
)
def test_dois_are_compared_in_their_normalised_form(a: str, b: str) -> None:
    assert doi_key(a) == doi_key(b)
    result = mark_duplicates(
        [rec("First paper about one thing", a), rec("Other title entirely here", b)]
    )
    assert result.marked == 1 and result.by_method == {"doi": 1}


# --- pre-filters: language tags, unknown markers, year range -------------------------------------


@pytest.mark.parametrize("text", ["en-US", "en_GB", "English (United States)", "EN"])
def test_locale_tags_are_english(text: str) -> None:
    assert normalize_language(text) == "eng"
    assert languages_of(text) == (["eng"], True)
    config = PrefilterConfig(language_allow=("eng",), language_on_missing="exclude")
    assert mark_prefilters([rec(language=text)], config).removed == 0


@pytest.mark.parametrize("text", ["und", "mul", "zxx", "unk", "nan", "null", "Unknown", "n/a"])
def test_unknown_language_markers_count_as_missing(text: str) -> None:
    assert languages_of(text)[1] is False
    passes = PrefilterConfig(language_allow=("eng",))
    assert mark_prefilters([rec(language=text)], passes).removed == 0  # sent on to the model
    excludes = PrefilterConfig(language_allow=("eng",), language_on_missing="exclude")
    assert mark_prefilters([rec(language=text)], excludes).removed == 1


def test_a_real_other_language_is_still_excluded() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    assert mark_prefilters([rec(language="fre; und")], config).removed == 1


def test_an_inverted_year_range_is_refused() -> None:
    with pytest.raises(ValueError):
        PrefilterConfig(year_min=2025, year_max=2000)
    assert PrefilterConfig(year_min=2000, year_max=2000).year_active


def test_the_comparison_sets_are_computed_once() -> None:
    config = PrefilterConfig(language_allow=("de", "en"), type_exclude=(" Letter ",))
    assert config.allowed_languages is config.allowed_languages
    assert config.allowed_languages == {"ger", "eng"} and config.unwanted_types == {"letter"}


# --- validity: scripts without spaces ---------------------------------------------------------


def test_a_chinese_abstract_is_not_called_garbled() -> None:
    text = (
        "本研究调查了认知行为疗法对成年抑郁症患者的疗效，随机分配两百名参与者并随访十二个月。" * 4
    )
    assert classify_abstract(text) == "ok"  # used to be suspect_concat (one 90-character "word")


def test_a_short_japanese_note_is_short() -> None:
    assert classify_abstract("短い要約です。") == "short"


def test_a_garbled_latin_abstract_is_still_detected() -> None:
    assert classify_abstract("cdoemveplaonpyinsgtrat " * 60) == "suspect_concat"


def test_mixed_text_with_a_few_cjk_characters_uses_the_word_rules() -> None:
    text = "The trial enrolled adults and measured outcomes over twelve months (日本). " * 4
    assert classify_abstract(text) == "ok"


# --- criteria template ------------------------------------------------------------------------


def test_adding_a_custom_element_reaches_the_prompt() -> None:
    template = CriteriaTemplate("CUSTOM", custom_fields=["A"])
    template.add_custom_element("B")
    assert template.get_fields() == ["A", "B"]
    template.update_inclusion("B", "adults")
    assert "B" in template.to_prompt_string()


def test_removing_an_element_removes_it_from_the_prompt() -> None:
    template = CriteriaTemplate("PICOS")
    template.remove_custom_element("Outcome")
    assert "Outcome" not in template.get_fields()
    assert "Outcome" not in template.to_prompt_string()


def test_the_input_list_of_custom_fields_is_not_changed() -> None:
    fields = ["A"]
    CriteriaTemplate("CUSTOM", custom_fields=fields).add_custom_element("B")
    assert fields == ["A"]
