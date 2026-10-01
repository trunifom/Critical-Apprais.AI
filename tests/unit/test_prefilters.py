"""Tests for the deterministic pre-filters (task T-M2-08)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crapai.io.records_store import Record
from crapai.prisma.dedup import DedupConfig, mark_duplicates
from crapai.prisma.prefilters import (
    PrefilterConfig,
    languages_of,
    mark_prefilters,
    normalize_language,
    normalize_type,
)
from crapai.prisma.validity import mark_validity


def rec(uid: str = "r1", **fields: object) -> Record:
    base: dict[str, object] = {
        "study_uid": uid,
        "source_label": "S",
        "source_file": "s.ris",
        "source_row": 1,
        "source_format": "ris",
        "title": f"Title {uid}",
        "abstract": "An abstract of reasonable length. " * 5,
    }
    base.update(fields)
    return Record.model_validate(base)


def reasons(records: list[Record], config: PrefilterConfig) -> list[str]:
    return [r.exclusion_reason for r in mark_prefilters(records, config).records]


# --- language ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,code",
    [
        ("eng", "eng"),
        ("EN", "eng"),
        ("English", "eng"),
        ("de", "ger"),
        ("deu", "ger"),
        ("ger", "ger"),
        ("German", "ger"),
        ("fra", "fre"),
        (" Français. ", "fre"),
        ("xyz", "xyz"),
        ("", None),
        ("  ", None),
    ],
)
def test_language_names_and_codes_are_normalised(text: str, code: str | None) -> None:
    assert normalize_language(text) == code


def test_several_languages_are_split_on_common_separators() -> None:
    assert languages_of("eng; ger") == (["eng", "ger"], True)
    assert languages_of("English, French / Spanish") == (["eng", "fre", "spa"], True)
    assert languages_of("") == ([], False)


def test_unrecognisable_language_text_counts_as_missing() -> None:
    assert languages_of("n/a")[1] is False
    assert languages_of("see text")[1] is False
    assert languages_of("xyz")[1] is True  # a well-formed three-letter code is kept


def test_language_filter_keeps_allowed_and_marks_the_rest() -> None:
    config = PrefilterConfig(language_allow=("eng", "deu"))
    records = [rec("a", language="eng"), rec("b", language="fre"), rec("c", language="German")]
    assert reasons(records, config) == ["", "PREFILTER_LANGUAGE", ""]


def test_a_record_with_several_languages_passes_if_any_is_allowed() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    assert reasons([rec(language="fre; eng")], config) == [""]
    assert reasons([rec(language="fre; spa")], config) == ["PREFILTER_LANGUAGE"]


def test_missing_language_passes_by_default_and_is_counted() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    result = mark_prefilters([rec("a"), rec("b", language="n/a")], config)
    assert [r.exclusion_reason for r in result.records] == ["", ""]
    assert result.passed_on_missing == {"language": 2} and result.removed == 0


def test_missing_language_can_be_excluded() -> None:
    config = PrefilterConfig(language_allow=("eng",), language_on_missing="exclude")
    result = mark_prefilters([rec("a")], config)
    assert result.records[0].exclusion_reason == "PREFILTER_LANGUAGE"
    assert result.records[0].exclusion_details == "language: missing"


def test_language_details_name_the_language_and_the_allowed_list() -> None:
    config = PrefilterConfig(language_allow=("ger", "eng"))
    (record,) = mark_prefilters([rec(language="fre")], config).records
    assert record.exclusion_details == "language: fre (allowed: eng, ger)"


# --- year -------------------------------------------------------------------------------------


def test_year_bounds_are_inclusive() -> None:
    config = PrefilterConfig(year_min=2015, year_max=2020)
    years = [2014, 2015, 2018, 2020, 2021]
    assert reasons([rec(str(y), year=y) for y in years], config) == [
        "PREFILTER_YEAR",
        "",
        "",
        "",
        "PREFILTER_YEAR",
    ]


def test_open_bounds() -> None:
    assert reasons([rec(year=1900)], PrefilterConfig(year_min=2015)) == ["PREFILTER_YEAR"]
    assert reasons([rec(year=2999)], PrefilterConfig(year_min=2015)) == [""]
    assert reasons([rec(year=2999)], PrefilterConfig(year_max=2020)) == ["PREFILTER_YEAR"]


def test_missing_year_follows_on_missing() -> None:
    record = rec(year=None)
    assert reasons([record], PrefilterConfig(year_min=2015)) == [""]
    excluded = PrefilterConfig(year_min=2015, year_on_missing="exclude")
    assert reasons([record], excluded) == ["PREFILTER_YEAR"]
    assert mark_prefilters([record], PrefilterConfig(year_min=2015)).passed_on_missing == {
        "year": 1
    }


def test_year_details_show_the_range() -> None:
    (record,) = mark_prefilters([rec(year=2001)], PrefilterConfig(year_min=2015)).records
    assert record.exclusion_details == "year: 2001 (range: 2015-open)"


# --- publication type -------------------------------------------------------------------------


def test_type_filter_is_case_and_space_insensitive_and_any_match_excludes() -> None:
    config = PrefilterConfig(type_exclude=("Editorial", "letter"))
    records = [
        rec("a", publication_types="Journal Article"),
        rec("b", publication_types="Journal Article; Editorial"),
        rec("c", publication_types="  LETTER "),
        rec("d", publication_types="Letter to the editor"),  # not an exact type
    ]
    assert reasons(records, config) == ["", "PREFILTER_TYPE", "PREFILTER_TYPE", ""]
    assert normalize_type("  Case   Report ") == "case report"


def test_missing_type_follows_on_missing() -> None:
    config = PrefilterConfig(type_exclude=("Editorial",))
    assert reasons([rec()], config) == [""]
    excluded = PrefilterConfig(type_exclude=("Editorial",), type_on_missing="exclude")
    assert reasons([rec()], excluded) == ["PREFILTER_TYPE"]


# --- keywords -----------------------------------------------------------------------------------


def test_keyword_exclude_matches_title_abstract_and_keywords() -> None:
    config = PrefilterConfig(keyword_exclude=("zebrafish",))
    records = [
        rec("a", title="A study of zebrafish embryos"),
        rec("b", abstract="We studied Zebrafish models of disease. " * 3),
        rec("c", keywords="cardiology; zebrafish; genetics"),
        rec("d", title="Human trial", abstract="No match here.", keywords="oncology"),
    ]
    assert reasons(records, config) == [
        "PREFILTER_KEYWORD",
        "PREFILTER_KEYWORD",
        "PREFILTER_KEYWORD",
        "",
    ]


def test_keyword_include_requires_at_least_one_match() -> None:
    config = PrefilterConfig(keyword_include=("diabetes", "insulin"))
    records = [
        rec("a", abstract="A trial about insulin resistance. " * 3),
        rec("b", keywords="diabetes mellitus"),
        rec("c", title="Unrelated topic", abstract="Nothing relevant. " * 3),
    ]
    assert reasons(records, config) == ["", "", "PREFILTER_KEYWORD"]


def test_keyword_exclude_wins_over_include() -> None:
    config = PrefilterConfig(keyword_include=("diabetes",), keyword_exclude=("animal model",))
    record = rec(abstract="Diabetes in an animal model. " * 3)
    assert reasons([record], config) == ["PREFILTER_KEYWORD"]


def test_keyword_matching_is_case_insensitive_by_default() -> None:
    config = PrefilterConfig(keyword_exclude=("Zebrafish",))
    assert reasons([rec(title="ZEBRAFISH study")], config) == ["PREFILTER_KEYWORD"]


def test_keyword_case_sensitive_requires_exact_case() -> None:
    config = PrefilterConfig(keyword_exclude=("Zebrafish",), keyword_case_sensitive=True)
    assert reasons([rec(title="zebrafish study")], config) == [""]
    assert reasons([rec(title="Zebrafish study")], config) == ["PREFILTER_KEYWORD"]


def test_missing_text_follows_keyword_on_missing() -> None:
    record = rec(title="", abstract="", keywords="", keywords_mesh="")
    config = PrefilterConfig(keyword_include=("x",))
    assert reasons([record], config) == [""]
    assert mark_prefilters([record], config).passed_on_missing == {"keyword": 1}
    excluded = PrefilterConfig(keyword_include=("x",), keyword_on_missing="exclude")
    assert reasons([record], excluded) == ["PREFILTER_KEYWORD"]


def test_keyword_filter_is_off_by_default_and_counted_in_active() -> None:
    assert not PrefilterConfig().keyword_active
    assert PrefilterConfig(keyword_exclude=("x",)).active
    assert PrefilterConfig(keyword_include=("x",)).active


# --- combination and ownership ----------------------------------------------------------------


def test_the_first_applicable_filter_is_the_reason_and_details_list_all() -> None:
    config = PrefilterConfig(language_allow=("eng",), year_min=2015, type_exclude=("Editorial",))
    record = rec(language="fre", year=2001, publication_types="Editorial")
    (marked,) = mark_prefilters([record], config).records
    assert marked.exclusion_reason == "PREFILTER_LANGUAGE"
    assert marked.exclusion_details.count(";") == 2
    assert (
        "year: 2001" in marked.exclusion_details and "type: Editorial" in marked.exclusion_details
    )


def test_no_configuration_changes_nothing() -> None:
    records = [rec("a", language="fre", year=1900)]
    result = mark_prefilters(records)
    assert result.records == records and result.removed == 0 and not PrefilterConfig().active


def test_reasons_of_import_and_dedup_are_never_replaced() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    records = [
        rec("a", language="fre", exclusion_reason="DUPLICATE", exclusion_details="d"),
        rec("b", language="fre", exclusion_reason="EMPTY_RECORD"),
        rec("c", language="fre", exclusion_reason="IMPORT_ERROR"),
    ]
    result = mark_prefilters(records, config)
    assert [r.exclusion_reason for r in result.records] == [
        "DUPLICATE",
        "EMPTY_RECORD",
        "IMPORT_ERROR",
    ]
    assert result.skipped == 3 and result.removed == 0


def test_a_prefilter_replaces_a_validity_reason() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    records = [rec("a", language="fre", exclusion_reason="NO_ABSTRACT", exclusion_details="x")]
    assert reasons(records, config) == ["PREFILTER_LANGUAGE"]
    kept = [rec("b", language="eng", exclusion_reason="NO_ABSTRACT", exclusion_details="x")]
    assert reasons(kept, config) == ["NO_ABSTRACT"]  # not hit: the validity reason stays


def test_changing_the_settings_clears_old_marks() -> None:
    records = [rec("a", language="fre")]
    marked = mark_prefilters(records, PrefilterConfig(language_allow=("eng",))).records
    assert marked[0].exclusion_reason == "PREFILTER_LANGUAGE"
    loosened = mark_prefilters(marked, PrefilterConfig(language_allow=("eng", "fre"))).records
    assert loosened[0].exclusion_reason == "" and loosened[0].exclusion_details == ""
    off = mark_prefilters(marked).records
    assert off[0].exclusion_reason == ""


def test_counts_by_reason_and_input_is_not_modified() -> None:
    config = PrefilterConfig(language_allow=("eng",), year_min=2015)
    records = [
        rec("a", language="fre"),
        rec("b", language="eng", year=2000),
        rec("c", language="eng"),
    ]
    snapshot = [r.model_copy() for r in records]
    result = mark_prefilters(records, config)
    assert result.by_reason == {"PREFILTER_LANGUAGE": 1, "PREFILTER_YEAR": 1}
    assert result.removed == 2 and records == snapshot
    assert len(result.records) == 3


def test_marking_is_idempotent() -> None:
    config = PrefilterConfig(language_allow=("eng",), year_min=2015)
    records = [rec("a", language="fre"), rec("b", year=2000), rec("c")]
    once = mark_prefilters(records, config).records
    assert mark_prefilters(once, config).records == once


# --- order of the steps: dedup, pre-filters, validity -----------------------------------------


def test_dedup_replaces_a_prefilter_reason() -> None:
    a = rec("a", title="Same", doi="10.1000/x", language="fre")
    b = rec("b", title="Same", doi="10.1000/x", language="fre")
    marked = mark_prefilters([a, b], PrefilterConfig(language_allow=("eng",))).records
    assert [r.exclusion_reason for r in marked] == ["PREFILTER_LANGUAGE"] * 2
    result = mark_duplicates(marked, DedupConfig())
    assert sorted(r.exclusion_reason for r in result.records) == ["DUPLICATE", "PREFILTER_LANGUAGE"]


def test_validity_keeps_a_prefilter_reason_in_either_order() -> None:
    config = PrefilterConfig(language_allow=("eng",))
    records = [rec("a", language="fre", abstract="")]
    validity_first = mark_prefilters(mark_validity(records).records, config).records
    prefilter_first = mark_validity(mark_prefilters(records, config).records).records
    assert validity_first[0].exclusion_reason == prefilter_first[0].exclusion_reason
    assert prefilter_first[0].exclusion_reason == "PREFILTER_LANGUAGE"


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["", "eng", "ger", "fre", "n/a", "eng; fre"]),
            st.one_of(st.none(), st.integers(1990, 2030)),
            st.sampled_from(["", "Journal Article", "Editorial", "Journal Article; Letter"]),
        ),
        max_size=25,
    )
)
def test_a_record_is_marked_only_if_a_present_value_fails_a_filter(
    rows: list[tuple[str, int | None, str]],
) -> None:
    config = PrefilterConfig(
        language_allow=("eng",), year_min=2000, year_max=2020, type_exclude=("Editorial", "Letter")
    )
    records = [
        rec(str(i), language=lang, year=y, publication_types=t)
        for i, (lang, y, t) in enumerate(rows)
    ]
    for (language, year, types), record in zip(
        rows, mark_prefilters(records, config).records, strict=True
    ):
        fails_language = language not in ("", "n/a") and "eng" not in language
        fails_year = year is not None and not 2000 <= year <= 2020
        fails_type = any(
            t in ("Editorial", "Letter") for t in (p.strip() for p in types.split(";"))
        )
        assert bool(record.exclusion_reason) == (fails_language or fails_year or fails_type)
