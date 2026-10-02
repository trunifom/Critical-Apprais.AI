"""Tests for duplicate marking (task T-M2-01, plan chapter 8.4)."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crapai.io.normalize import ImportContext, to_records
from crapai.io.readers.ris import read_ris
from crapai.io.records_store import Record, read_records, write_records
from crapai.prisma.dedup import (
    DedupConfig,
    clear_duplicate_marks,
    mark_duplicates,
    normalize_authors,
    normalize_title,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
_uid = itertools.count(1)


# The fixtures use short titles; the guard against generic titles is tested separately.
LOOSE = DedupConfig(min_title_words=1)


def rec(title: str = "", doi: str = "", *, label: str = "A", **extra: Any) -> Record:
    values: dict[str, Any] = {
        "study_uid": f"uid-{next(_uid)}",
        "source_label": label,
        "source_file": "f.ris",
        "source_row": 1,
        "source_format": "ris",
        "title": title,
        "doi": doi,
    }
    values.update(extra)
    if values.get("abstract"):
        values["has_abstract"] = True
    return Record(**values)


def load(name: str, label: str) -> list[Record]:
    result = read_ris(DATA / name)
    return to_records(result, ImportContext(label, name, "ris"))


# --- normalisation ---


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Explainable AI: A Review!", "explainable ai  a review"),
        ("Café Größe", "cafe grosse".replace("grosse", "große")),
        ("Understanding\tMachine   Learning", "understanding machine learning"),
        ("collegiate‐level athletes", "collegiate-level athletes"),
        ("ＡＢＣ　Study", "abc study"),  # full-width forms folded by NFKD
    ],
)
def test_titles_are_compared_normalised(a: str, b: str) -> None:
    assert normalize_title(a) == normalize_title(b)


def test_normalisation_keeps_real_differences() -> None:
    assert normalize_title("Effects of A on B") != normalize_title("Effects of B on A")
    assert normalize_title("") == "" and normalize_title(" - ! ") == ""
    assert normalize_authors("Doe, J; Roe, R") == "doe j roe r"


# --- acceptance criteria of the card ---


def test_example_db_nr2_has_three_duplicates_and_nr3_has_two() -> None:
    nr2 = mark_duplicates(load("example_db_nr2_total-10_duplicates-3.ris", "Db2"))
    nr3 = mark_duplicates(load("example_db_nr3_total-8_duplicates-2.ris", "Db3"))
    assert (len(nr2.records), nr2.marked) == (10, 3)
    assert (len(nr3.records), nr3.marked) == (8, 2)


def test_merged_trio_has_31_records_13_unique_dois_and_18_duplicates() -> None:
    oracle = EXPECTED["_derived/example_db_trio_merged"]
    records: list[Record] = []
    for index, name in enumerate(oracle["files"], start=1):
        records.extend(load(name, f"Db{index}"))
    result = mark_duplicates(records)
    assert len(result.records) == oracle["records_total"] == 31
    assert result.marked == oracle["duplicates_by_doi"] == 18
    kept_dois = {r.doi for r in result.records if not r.is_duplicate}
    assert len(kept_dois) == oracle["unique_doi"] == 13
    assert all(r.doi for r in result.records)  # every fixture record has a DOI
    counts = {}
    for record in records:  # oracle: groups are the DOIs that occur more than once
        counts[record.doi] = counts.get(record.doi, 0) + 1
    assert result.groups == sum(1 for n in counts.values() if n > 1)


def test_non_destructive_and_pointing_to_the_kept_record() -> None:
    records = load("example_db_nr2_total-10_duplicates-3.ris", "Db2")
    result = mark_duplicates(records)
    assert [r.study_uid for r in result.records] == [r.study_uid for r in records]  # same order
    by_uid = {r.study_uid: r for r in result.records}
    for record in result.records:
        if record.is_duplicate:
            keeper = by_uid[record.duplicate_of]
            assert not keeper.is_duplicate and keeper.doi == record.doi
            assert record.exclusion_reason == "DUPLICATE" and record.dedup_method == "doi"
            assert record.study_uid != keeper.study_uid
        else:
            assert record.duplicate_of == "" and record.exclusion_reason == ""
    assert [r.title for r in result.records] == [r.title for r in records]  # content untouched


def test_input_records_are_not_modified() -> None:
    records = load("example_db_nr2_total-10_duplicates-3.ris", "Db2")
    snapshot = [r.model_dump() for r in records]
    mark_duplicates(records)
    assert [r.model_dump() for r in records] == snapshot


# --- strategies ---


def test_doi_or_title_matches_by_doi_then_by_title() -> None:
    records = [
        rec("Paper One", "10.1/a"),
        rec("Totally different title", "10.1/a"),  # same DOI
        rec("Paper One", ""),  # same title, no DOI
        rec("Paper Two", "10.1/b"),
        rec("paper two!", "10.1/b"),
    ]
    result = mark_duplicates(records, LOOSE)
    assert [r.is_duplicate for r in result.records] == [False, True, True, False, True]
    assert result.by_method == {"doi": 2, "title_norm": 1}
    assert result.groups == 2


def test_a_fulltext_attachment_is_never_marked_a_duplicate_of_its_own_anchor() -> None:
    """Regression test (found live, end-to-end with crapai screen): a PDF attachment (ADR 0026)
    legitimately shares its DOI/title with the record it belongs to (crapai.io.fulltext_link
    matches it by exactly that). Treating it as an ordinary record used to mark one of the two a
    DUPLICATE of the other -- and crapai screen re-runs dedup before every run, so a full-text
    screening run would then find no eligible record at all."""
    anchor = rec("Exercise therapy for depression", "10.1/exc", study_uid="anchor-1")
    attachment = rec(
        "Exercise therapy for depression", "10.1/exc", study_uid="pdf-1", fulltext_of="anchor-1"
    )
    result = mark_duplicates([anchor, attachment])
    assert result.marked == 0
    for record in result.records:
        assert not record.is_duplicate and record.exclusion_reason != "DUPLICATE"


def test_two_fulltext_attachments_of_different_anchors_are_never_merged_with_each_other() -> None:
    first = rec("Study A", "10.1/same", study_uid="pdf-1", fulltext_of="anchor-1")
    second = rec("Study A", "10.1/same", study_uid="pdf-2", fulltext_of="anchor-2")
    assert mark_duplicates([first, second]).marked == 0


def test_same_title_but_different_dois_are_not_merged() -> None:
    records = [rec("Editorial", "10.1/x"), rec("Editorial", "10.1/y"), rec("Editorial", "")]
    result = mark_duplicates(records)
    assert result.marked == 0  # ambiguous: a wrong mark would hide a study


def test_records_without_title_or_doi_never_match_each_other() -> None:
    records = [rec("", ""), rec("", ""), rec("  ", ""), rec("", "10.1/a"), rec("", "10.1/b")]
    assert mark_duplicates(records).marked == 0


def test_strict_ids_use_doi_or_pmid_and_ignore_titles() -> None:
    records = [
        rec("Same title", "", pmid="1"),
        rec("Same title", "", pmid="2"),  # same title only: not a duplicate here
        rec("Other", "", pmid="1"),  # same PMID
        rec("Third", "10.1/z"),
        rec("Fourth", "10.1/z"),
    ]
    result = mark_duplicates(records, DedupConfig(strategy="strict_ids"))
    assert [r.is_duplicate for r in result.records] == [False, False, True, False, True]
    assert result.by_method == {"pmid": 1, "doi": 1}


def test_title_strategy_ignores_doi() -> None:
    records = [rec("Alpha study", "10.1/a"), rec("ALPHA STUDY.", "10.1/b")]
    assert mark_duplicates(records, replace(LOOSE, strategy="title")).marked == 1
    assert mark_duplicates(records, LOOSE).marked == 0  # doi_or_title respects the DOI conflict


def test_title_authors_needs_both() -> None:
    records = [
        rec("Alpha study", authors="Doe, J"),
        rec("Alpha study", authors="doe j"),
        rec("Alpha study", authors="Roe, R"),
        rec("Beta", authors=""),
        rec("Beta", authors=""),
    ]
    result = mark_duplicates(records, replace(LOOSE, strategy="title_authors"))
    assert [r.is_duplicate for r in result.records] == [False, True, False, False, True]
    assert result.by_method == {"title_authors": 2}


def test_unknown_strategy_or_keep_rule_is_rejected() -> None:
    with pytest.raises(ValueError):
        mark_duplicates([], DedupConfig(strategy="magic"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        mark_duplicates([], DedupConfig(keep="middle"))  # type: ignore[arg-type]
    assert mark_duplicates([]).marked == 0


# --- which record is kept ---


def test_the_most_complete_record_is_kept_first_on_ties() -> None:
    bare = rec("Paper", "10.1/a", label="A")
    with_abstract = rec("Paper", "10.1/a", label="B", abstract="Has an abstract")
    also_bare = rec("Paper", "10.1/a", label="C")
    result = mark_duplicates([bare, with_abstract, also_bare])
    assert [r.is_duplicate for r in result.records] == [True, False, True]
    kept_uid = with_abstract.study_uid
    assert result.records[0].duplicate_of == kept_uid == result.records[2].duplicate_of

    tie = mark_duplicates([rec("T", "10.1/t"), rec("T", "10.1/t")])
    assert [r.is_duplicate for r in tie.records] == [False, True]


def test_doi_beats_missing_doi_when_no_abstract_differs() -> None:
    no_doi = rec("Paper", "")
    with_doi = rec("Paper", "10.1/a")
    result = mark_duplicates([no_doi, with_doi], LOOSE)
    assert [r.is_duplicate for r in result.records] == [True, False]


@pytest.mark.parametrize(("keep", "kept"), [("first", 0), ("last", 2), ("best", 1)])
def test_keep_rules(keep: str, kept: int) -> None:
    records = [rec("P", "10.1/a"), rec("P", "10.1/a", abstract="x"), rec("P", "10.1/a")]
    result = mark_duplicates(records, DedupConfig(keep=keep))  # type: ignore[arg-type]
    assert [i for i, r in enumerate(result.records) if not r.is_duplicate] == [kept]


# --- existing marks, statistics, persistence ---


def test_existing_reasons_are_kept_and_a_new_run_starts_clean() -> None:
    empty = rec("", "10.1/a", exclusion_reason="EMPTY_RECORD", exclusion_details="neither")
    other = rec("Paper", "10.1/a")
    first = mark_duplicates([other, empty])
    assert first.records[1].is_duplicate and first.records[1].exclusion_reason == "EMPTY_RECORD"
    changed = mark_duplicates(first.records, DedupConfig(strategy="title"))  # DOI no longer counts
    assert changed.marked == 0
    assert not any(r.is_duplicate or r.duplicate_of or r.dedup_method for r in changed.records)
    assert changed.records[1].exclusion_reason == "EMPTY_RECORD"  # untouched by the reset
    assert changed.records[0].exclusion_reason == ""


def test_an_ai_prefilter_mark_is_never_replaced_by_dedup() -> None:
    """ADR 0029: AI_PREFILTER_JEV is not in REPLACEABLE_BY_DEDUP (unlike validity/prefilter
    reasons), so a record the AI pre-filter already excluded keeps that exact reason even if
    dedup would otherwise consider it a duplicate."""
    marked = rec("Paper", "10.1/a", exclusion_reason="AI_PREFILTER_JEV", exclusion_details="x")
    other = rec("Paper", "10.1/a")
    result = mark_duplicates([other, marked])
    assert result.records[1].exclusion_reason == "AI_PREFILTER_JEV"
    assert result.records[1].exclusion_details == "x"


def test_clear_marks_only_removes_the_duplicate_reason() -> None:
    marked = mark_duplicates([rec("P", "10.1/a"), rec("P", "10.1/a")]).records
    cleared = clear_duplicate_marks(marked)
    assert not any(r.is_duplicate or r.duplicate_of or r.exclusion_reason for r in cleared)


def test_idempotent() -> None:
    records = load("example_db_nr2_total-10_duplicates-3.ris", "Db2")
    once = mark_duplicates(records)
    twice = mark_duplicates(once.records)
    assert [r.model_dump() for r in twice.records] == [r.model_dump() for r in once.records]


def test_counts_within_and_across_sources() -> None:
    records = [
        rec("P1", "10.1/1", label="PubMed"),
        rec("P1", "10.1/1", label="PubMed"),  # within PubMed
        rec("P1", "10.1/1", label="Embase"),  # across
        rec("P2", "10.1/2", label="Embase"),
        rec("P2", "10.1/2", label="Embase"),  # within Embase
    ]
    result = mark_duplicates(records)
    assert result.marked == 3
    assert result.within_source == {"PubMed": 1, "Embase": 1}
    assert result.across_sources == 1


def test_marks_survive_the_records_file(tmp_path: Path) -> None:
    result = mark_duplicates(load("example_db_nr2_total-10_duplicates-3.ris", "Db2"))
    path = tmp_path / "records.csv"
    write_records(path, result.records)
    assert read_records(path) == result.records


# --- properties ---


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["", "Alpha", "alpha!", "Beta", "Gamma study", "GAMMA  study"]),
            st.sampled_from(["", "10.1/a", "10.1/b", "10.1/c"]),
            st.sampled_from(["A", "B"]),
        ),
        max_size=25,
    ),
    st.sampled_from(["doi_or_title", "strict_ids", "title", "title_authors"]),
    st.sampled_from(["best", "first", "last"]),
)
def test_invariants_for_arbitrary_input(
    rows: list[tuple[str, str, str]], strategy: str, keep: str
) -> None:
    records = [rec(title, doi, label=label) for title, doi, label in rows]
    result = mark_duplicates(records, DedupConfig(strategy=strategy, keep=keep))  # type: ignore[arg-type]
    assert [r.study_uid for r in result.records] == [r.study_uid for r in records]
    by_uid = {r.study_uid: r for r in result.records}
    assert result.marked == sum(r.is_duplicate for r in result.records)
    for record in result.records:
        if record.is_duplicate:
            keeper = by_uid[record.duplicate_of]
            assert not keeper.is_duplicate  # pointers never chain
            assert record.dedup_method and record.exclusion_reason == "DUPLICATE"
        else:
            assert not record.duplicate_of and not record.dedup_method
    assert all(not r.is_duplicate for r in result.records if not r.title and not r.doi)
    again = mark_duplicates(result.records, DedupConfig(strategy=strategy, keep=keep))  # type: ignore[arg-type]
    assert [r.model_dump() for r in again.records] == [r.model_dump() for r in result.records]
