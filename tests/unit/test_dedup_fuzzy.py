"""PMIDs and the optional fuzzy step of the duplicate search."""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

import pytest

from crapai.io.records_store import Record
from crapai.prisma import dedup as dd
from crapai.prisma.dedup import DedupConfig, mark_duplicates

_uid = itertools.count()
FUZZY = DedupConfig(fuzzy=True)


def rec(title: str = "", doi: str = "", **extra: Any) -> Record:
    values: dict[str, Any] = {
        "study_uid": f"u{next(_uid)}",
        "source_label": "A",
        "source_file": "f.ris",
        "source_row": 1,
        "source_format": "ris",
        "title": title,
        "doi": doi,
    }
    values.update(extra)
    return Record.model_validate(values)


T = "Effects of aerobic exercise on depressive symptoms in adults"


# --- PMID ---------------------------------------------------------------------------------------


def test_the_same_pmid_is_a_duplicate_in_the_default_strategy() -> None:
    result = mark_duplicates(
        [rec("Totally different wording here", pmid="123"), rec(T, pmid="123")]
    )
    assert result.marked == 1 and result.by_method == {"pmid": 1}


def test_records_without_a_pmid_are_never_duplicates_of_each_other() -> None:
    records = [rec(f"Study number {i} on a quite different subject") for i in range(5)]
    assert mark_duplicates(records).marked == 0
    assert mark_duplicates(records, DedupConfig(strategy="strict_ids")).marked == 0


def test_a_record_without_a_pmid_is_not_matched_to_one_with_a_pmid() -> None:
    assert (
        mark_duplicates([rec("Alpha beta gamma delta", pmid="7"), rec("One two three four")]).marked
        == 0
    )


def test_the_same_pmid_with_different_dois_is_not_merged() -> None:
    records = [rec(T, "10.1000/a", pmid="9"), rec(T, "10.1000/b", pmid="9")]
    assert mark_duplicates(records).marked == 0  # contradictory identifiers: do not guess


def test_doi_beats_pmid_as_the_reason() -> None:
    result = mark_duplicates([rec(T, "10.1000/a", pmid="9"), rec(T, "10.1000/a", pmid="9")])
    assert result.by_method == {"doi": 1}


def test_strict_ids_uses_doi_and_pmid_only() -> None:
    records = [rec(T, pmid="1"), rec(T, pmid="1"), rec(T), rec(T)]
    result = mark_duplicates(records, DedupConfig(strategy="strict_ids"))
    assert result.marked == 1 and result.by_method == {"pmid": 1}


def test_titles_are_compared_without_case_punctuation_or_accents() -> None:
    a, b = (
        rec("Résultats de l'étude: EFFETS du SPORT, en 2020!"),
        rec("resultats de l etude effets du sport en 2020"),
    )
    assert mark_duplicates([a, b]).marked == 1


# --- fuzzy --------------------------------------------------------------------------------------


def test_fuzzy_is_off_by_default() -> None:
    records = [rec(T), rec(T.replace("adults", "adult"))]
    assert mark_duplicates(records).marked == 0
    assert mark_duplicates(records, FUZZY).marked == 1


@pytest.mark.parametrize(
    "variant",
    [
        "Effects of aerobic exercise on depressive symptoms in adult",  # dropped letter
        "Effect of aerobic exercise on depressive symptoms in adults",  # changed ending
        "Effects of aerobic excercise on depressive symptoms in adults",  # typo
        "Effects of aerobic exercise on depressive symptoms in adults: a review.",  # suffix
        "effects of AEROBIC exercise on depressive symptoms in  adults",  # case and spaces
    ],
)
def test_fuzzy_finds_titles_with_small_differences(variant: str) -> None:
    result = mark_duplicates(
        [rec(T, year=2020), rec(variant, year=2020)], replace(FUZZY, fuzzy_threshold=0.9)
    )
    assert result.marked == 1


def test_fuzzy_records_its_method() -> None:
    result = mark_duplicates([rec(T), rec(T.replace("adults", "adult"))], FUZZY)
    assert result.by_method == {"fuzzy": 1}
    duplicate = next(r for r in result.records if r.is_duplicate)
    assert duplicate.dedup_method == "fuzzy" and "fuzzy" in duplicate.exclusion_details


def test_exact_matches_keep_their_stronger_reason_when_fuzzy_is_on() -> None:
    result = mark_duplicates([rec(T, "10.1000/a"), rec(T, "10.1000/a"), rec(T), rec(T)], FUZZY)
    assert sorted(result.by_method.items()) == [("doi", 1), ("title_norm", 2)]


def test_fuzzy_does_not_join_different_papers() -> None:
    records = [
        rec("Effects of aerobic exercise on depressive symptoms in adults"),
        rec("Effects of resistance training on anxiety symptoms in children"),
    ]
    assert mark_duplicates(records, FUZZY).marked == 0


def test_the_threshold_decides() -> None:
    records = [rec(T), rec("Effects of aerobic exercise on depressive symptoms in teenagers")]
    assert mark_duplicates(records, replace(FUZZY, fuzzy_threshold=0.99)).marked == 0
    assert mark_duplicates(records, replace(FUZZY, fuzzy_threshold=0.8)).marked == 1


def test_different_dois_veto_a_fuzzy_match() -> None:
    records = [rec(T, "10.1000/a"), rec(T.replace("adults", "adult"), "10.1000/b")]
    assert mark_duplicates(records, FUZZY).marked == 0


def test_years_too_far_apart_veto_a_fuzzy_match() -> None:
    near = [rec(T, year=2020), rec(T.replace("adults", "adult"), year=2021)]
    far = [rec(T, year=2010), rec(T.replace("adults", "adult"), year=2021)]
    assert mark_duplicates(near, FUZZY).marked == 1
    assert mark_duplicates(far, FUZZY).marked == 0
    assert mark_duplicates(far, replace(FUZZY, fuzzy_max_year_difference=20)).marked == 1
    unknown = [rec(T), rec(T.replace("adults", "adult"), year=2021)]
    assert mark_duplicates(unknown, FUZZY).marked == 1  # a missing year does not veto


def test_first_authors_must_agree_when_both_are_known() -> None:
    same = [
        rec(T, authors="Doe, Jane; Roe, R"),
        rec(T.replace("adults", "adult"), authors="Jane Doe"),
    ]
    other = [rec(T, authors="Doe, Jane"), rec(T.replace("adults", "adult"), authors="Smith, John")]
    assert mark_duplicates(same, FUZZY).marked == 1
    assert mark_duplicates(other, FUZZY).marked == 0
    assert mark_duplicates(other, replace(FUZZY, fuzzy_require_author_agreement=False)).marked == 1


def test_short_titles_are_not_fuzzy_candidates() -> None:
    assert mark_duplicates([rec("Editorial note"), rec("Editorial notes")], FUZZY).marked == 0


def test_strict_ids_ignores_the_fuzzy_switch() -> None:
    records = [rec(T), rec(T.replace("adults", "adult"))]
    assert mark_duplicates(records, replace(FUZZY, strategy="strict_ids")).marked == 0


def test_fuzzy_is_idempotent_and_keeps_the_most_complete_record() -> None:
    records = [rec(T), rec(T.replace("adults", "adult"), abstract="has one", has_abstract=True)]
    once = mark_duplicates(records, FUZZY)
    assert [r.is_duplicate for r in once.records] == [True, False]
    assert mark_duplicates(once.records, FUZZY).records == once.records


def test_generic_blocks_are_skipped_not_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dd, "MAX_BLOCK", 3)
    records = [rec(f"Identical generic start of a long title number {i}") for i in range(6)]
    assert mark_duplicates(records, replace(FUZZY, fuzzy_threshold=0.5)).marked == 0


def test_the_standard_library_path_and_rapidfuzz_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("rapidfuzz")
    a, b = T, T.replace("adults", "adult")
    with_package = dd._similarity(a, b)
    monkeypatch.setitem(__import__("sys").modules, "rapidfuzz", None)  # forces the fallback
    assert abs(dd._similarity(a, b) - with_package) < 0.05


def test_similarity_without_rapidfuzz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "rapidfuzz", None)
    assert dd._similarity("abc def", "abc def") == 1.0
    assert dd._similarity("abc def", "zzz yyy xxx www") < 0.5


def test_first_author_forms() -> None:
    assert dd._first_author("Doe, Jane; Roe, Richard") == "doe"
    assert dd._first_author("Jane Doe") == "doe"
    assert dd._first_author("") == ""


def test_a_large_project_finishes_in_reasonable_time() -> None:
    import time

    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    records = [
        rec(" ".join(words[(i * k) % 10] for k in range(1, 9)) + f" study {i}") for i in range(3000)
    ]
    started = time.monotonic()
    mark_duplicates(records, FUZZY)
    assert time.monotonic() - started < 60
