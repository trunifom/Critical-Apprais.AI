"""Tests for the validity check: missing abstracts, NOT_SCREENABLE, retracted, quality (T-M2-03)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crapai.io.normalize import ImportContext, to_records
from crapai.io.readers.bibtex import read_bibtex
from crapai.io.readers.nbib import read_nbib
from crapai.io.readers.ris import read_ris
from crapai.io.records_store import Record
from crapai.prisma.dedup import mark_duplicates
from crapai.prisma.reasons import VALIDITY_REASONS
from crapai.prisma.validity import (
    NOT_SCREENABLE_TITLES,
    ValidityConfig,
    classify_abstract,
    is_not_screenable,
    mark_validity,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
_uid = itertools.count(1)
LONG_TEXT = "The trial enrolled adults and measured outcomes over twelve months. " * 4


def rec(title: str = "Some study", abstract: str = "", **extra: Any) -> Record:
    values: dict[str, Any] = {
        "study_uid": f"uid-{next(_uid)}",
        "source_label": "A",
        "source_file": "f.ris",
        "source_row": 1,
        "source_format": "ris",
        "title": title,
        "abstract": abstract,
        "has_abstract": bool(abstract),
    }
    values.update(extra)
    return Record(**values)


def reasons(result: Any) -> list[str]:
    return [r.exclusion_reason for r in result.records]


# --- abstract quality ---


def test_quality_classes() -> None:
    assert classify_abstract("") == "" and classify_abstract("   \n ") == ""
    assert classify_abstract(LONG_TEXT) == "ok"
    assert classify_abstract("Not available.") == "short"
    assert classify_abstract("word " * 39) == "short" and classify_abstract("word " * 40) == "ok"


def test_glued_or_garbled_text_is_suspect() -> None:
    glued = "x" * 41
    assert classify_abstract(f"{LONG_TEXT} {glued}") == "suspect_concat"
    assert classify_abstract(f"{LONG_TEXT} {'y' * 40}") == "ok"  # exactly the limit is allowed
    garbled = " ".join(["cdoemveplaonpyinsgtrattegfic"] * 40)  # mean length far above natural text
    assert classify_abstract(garbled) == "suspect_concat"


def test_german_compounds_and_long_technical_terms_are_not_suspect() -> None:
    german = (
        "Die Verarbeitungsgeschwindigkeit wurde bei Kindern mit und ohne Aufmerksamkeitsdefizit "
        "untersucht. Es zeigten sich keine Unterschiede zwischen den beiden Gruppen, jedoch "
        "eine deutliche Verbesserung der Leistung nach dem Training. Die Ergebnisse werden im "
        "Hinblick auf die entwicklungspsychologische Forschung diskutiert und eingeordnet."
    )
    assert classify_abstract(german + " " + german) == "ok"
    technical = (
        "Electroencephalography and magnetoencephalographic recordings were compared. " * 4
        + "The results were discussed in relation to previous work on the topic. " * 2
    )
    assert classify_abstract(technical) == "ok"


def test_cochrane_glued_words_are_a_known_limit() -> None:
    """The plan example ('stressmanagement') cannot be found without a dictionary."""
    parsed = read_bibtex(DATA / "citation-export.bib")
    records = to_records(parsed, ImportContext("C", "c.bib", "bibtex"))
    target = next(r for r in records if r.extra_json.get("bib_key") == "NCT0688187525")
    assert "stressmanagement" in target.abstract and "berecruited" in target.abstract
    assert classify_abstract(target.abstract) == "ok"  # documented limitation, see module docstring


# --- NOT_SCREENABLE ---


@pytest.mark.parametrize(
    "title",
    [
        "Front-matter",
        "FRONT MATTER",
        "Index",
        "Table of Contents",
        "Table of contents.",
        "Cover",
        "Back Matter",
        "Author Index",
        "Title page",
        "Contents",
    ],
)
def test_front_and_back_matter_titles(title: str) -> None:
    assert is_not_screenable(title)


@pytest.mark.parametrize(
    "title",
    [
        "Index of suspicion in paediatric sepsis",
        "A cover letter study",
        "Contents of tea: an assay",
        "Front matter of the brain",
        "",
        "Effects of exercise",
    ],
)
def test_real_study_titles_are_not_mistaken_for_front_matter(title: str) -> None:
    assert not is_not_screenable(title)


def test_the_title_list_can_be_extended() -> None:
    config = ValidityConfig(not_screenable_titles=NOT_SCREENABLE_TITLES | {"preface"})
    assert is_not_screenable("Preface", config) and not is_not_screenable("Preface")


# --- reasons and their order ---


def test_no_abstract_is_marked_but_the_record_is_kept() -> None:
    records = [rec("With", LONG_TEXT), rec("Without", "")]
    result = mark_validity(records)
    assert reasons(result) == ["", "NO_ABSTRACT"]
    assert result.records[1].exclusion_details == "no abstract"
    assert len(result.records) == 2 and result.valid_for_model == 1
    assert result.by_reason == {"NO_ABSTRACT": 1}


def test_title_only_mode_sends_records_without_abstract_to_the_model() -> None:
    result = mark_validity([rec("Without", "")], ValidityConfig(include_title_only=True))
    assert reasons(result) == [""] and result.valid_for_model == 1


def test_not_screenable_beats_no_abstract() -> None:
    result = mark_validity([rec("Front-matter", "")])
    assert reasons(result) == ["NOT_SCREENABLE"]
    assert "Front-matter" in result.records[0].exclusion_details


def test_not_screenable_applies_even_in_title_only_mode() -> None:
    result = mark_validity([rec("Index", "")], ValidityConfig(include_title_only=True))
    assert reasons(result) == ["NOT_SCREENABLE"]


def test_retracted_studies_stay_in_unless_excluded() -> None:
    retracted = rec("Study", LONG_TEXT, is_retracted=True)
    assert reasons(mark_validity([retracted])) == [""]  # flagged in the data, not excluded
    excluded = mark_validity([retracted], ValidityConfig(exclude_retracted=True))
    assert reasons(excluded) == ["RETRACTED"] and excluded.records[0].is_retracted is True
    both = mark_validity(
        [rec("Study", "", is_retracted=True)], ValidityConfig(exclude_retracted=True)
    )
    assert reasons(both) == ["RETRACTED"]  # RETRACTED is named before NO_ABSTRACT


def test_reasons_of_other_steps_are_never_overwritten() -> None:
    records = [
        rec("Dup", "", exclusion_reason="DUPLICATE", is_duplicate=True),
        rec("", "", exclusion_reason="EMPTY_RECORD"),
        rec("X", "", exclusion_reason="IMPORT_ERROR"),
    ]
    result = mark_validity(records)
    assert reasons(result) == ["DUPLICATE", "EMPTY_RECORD", "IMPORT_ERROR"]
    assert result.by_reason == {"DUPLICATE": 1, "EMPTY_RECORD": 1, "IMPORT_ERROR": 1}
    assert result.valid_for_model == 0


def test_switching_an_option_recomputes_validity_reasons() -> None:
    strict = mark_validity([rec("Without", "")])
    relaxed = mark_validity(strict.records, ValidityConfig(include_title_only=True))
    assert reasons(strict) == ["NO_ABSTRACT"] and reasons(relaxed) == [""]
    assert relaxed.records[0].exclusion_details == ""


def test_has_abstract_follows_the_text() -> None:
    liar = rec("T", "   ", has_abstract=True)  # whitespace only but flagged as present
    result = mark_validity([liar])
    assert result.records[0].has_abstract is False and reasons(result) == ["NO_ABSTRACT"]
    truthful = rec("T", LONG_TEXT, has_abstract=False)
    assert mark_validity([truthful]).records[0].has_abstract is True


def test_quality_is_stored_and_counted() -> None:
    records = [rec("a", LONG_TEXT), rec("b", "Short note."), rec("c", ""), rec("d", "z" * 45)]
    result = mark_validity(records)
    assert [r.abstract_quality for r in result.records] == ["ok", "short", "", "suspect_concat"]
    assert result.quality == {"ok": 1, "short": 1, "suspect_concat": 1}


def test_input_is_not_modified_and_the_run_is_idempotent() -> None:
    records = [rec("Front-matter", ""), rec("Without", ""), rec("Fine", LONG_TEXT)]
    snapshot = [r.model_dump() for r in records]
    once = mark_validity(records)
    assert [r.model_dump() for r in records] == snapshot
    twice = mark_validity(once.records)
    assert [r.model_dump() for r in twice.records] == [r.model_dump() for r in once.records]


def test_duplicate_marking_replaces_a_validity_reason_but_not_an_import_reason() -> None:
    """Order of work: dedup first in PRISMA. A duplicate without abstract counts as duplicate."""
    first = rec("Paper", "", doi="10.1/a")
    second = rec("Paper", "", doi="10.1/a")
    validated = mark_validity([first, second]).records
    assert reasons(type("R", (), {"records": validated})) == ["NO_ABSTRACT", "NO_ABSTRACT"]
    deduped = mark_duplicates(validated)
    assert [r.exclusion_reason for r in deduped.records] == ["NO_ABSTRACT", "DUPLICATE"]
    assert all(r in VALIDITY_REASONS or r == "DUPLICATE" for r in reasons(deduped))
    empty = rec("", "", doi="10.1/b", exclusion_reason="EMPTY_RECORD")
    twin = rec("Other", LONG_TEXT, doi="10.1/b")
    kept = mark_duplicates([twin, empty]).records
    assert [r.exclusion_reason for r in kept] == ["", "EMPTY_RECORD"]


# --- real fixtures (oracle numbers) ---


def load_ris(name: str) -> list[Record]:
    return to_records(read_ris(DATA / name), ImportContext("Src", name, "ris"))


def test_zotero_ris_about_550_records_lack_an_abstract() -> None:
    records = load_ris("pubmed_adhd_converted-zotero.ris")
    result = mark_validity(records)
    expected = EXPECTED["data/pubmed_adhd_converted-zotero.ris"]
    without = expected["records"] - expected["abstracts"]  # 706 - 156 = 550
    marked = result.by_reason
    assert without == 550
    # Every record without an abstract has exactly one reason: empty, front matter or no abstract.
    assert (
        marked.get("NO_ABSTRACT", 0)
        + marked.get("NOT_SCREENABLE", 0)
        + marked.get("EMPTY_RECORD", 0)
        == without
    )
    assert result.valid_for_model == expected["abstracts"]
    assert 540 <= marked["NO_ABSTRACT"] <= 550  # "about 550" of the card
    assert len(result.records) == 706


def test_zotero_front_matter_chapter_is_flagged() -> None:
    result = mark_validity(load_ris("pubmed_adhd_converted-zotero.ris"))
    front = [r for r in result.records if r.title == "Front-matter"]
    assert front and all(r.exclusion_reason == "NOT_SCREENABLE" for r in front)
    assert all(r.record_type == "book_chapter" for r in front)


def test_zotero_untitled_records_stay_empty_records() -> None:
    result = mark_validity(load_ris("pubmed_adhd_converted-zotero.ris"))
    untitled = [r for r in result.records if not r.title]
    assert len(untitled) == 2 and all(r.exclusion_reason == "EMPTY_RECORD" for r in untitled)


def test_zotero_garbled_abstract_is_flagged_as_suspect() -> None:
    result = mark_validity(load_ris("pubmed_adhd_converted-zotero.ris"))
    suspects = [r for r in result.records if r.abstract_quality == "suspect_concat"]
    assert suspects, "the interleaved (garbled) abstract of the Zotero file must be found"
    assert any("cdoemveplaonpyinsgtrattfic"[:12] in r.abstract for r in suspects)
    assert result.quality["suspect_concat"] == len(suspects) == 2  # the same broken text twice
    assert not any("Verarbeitungsgeschwindigkeit" in r.abstract for r in suspects)  # German is safe


def test_ris_fixtures_without_abstracts_are_all_marked() -> None:
    result = mark_validity(load_ris("example_db_nr1_total-15_duplicates-0.ris"))
    assert set(reasons(result)) == {"NO_ABSTRACT"} and result.valid_for_model == 0


def test_medline_note_with_a_very_short_abstract_is_flagged_short() -> None:
    records = to_records(read_nbib(DATA / "pubmed-adhd-set.nbib"), ImportContext("P", "p", "nbib"))
    result = mark_validity(records)
    assert result.quality.get("short", 0) >= 1
    assert result.by_reason["NO_ABSTRACT"] == 100 - 94  # 94 AB fields in 100 records


# --- property ---


@settings(max_examples=80, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["", "Study", "Index", "Front-matter", "Contents"]),
            st.sampled_from(["", "  ", "short abstract", LONG_TEXT]),
            st.booleans(),
        ),
        max_size=20,
    ),
    st.booleans(),
    st.booleans(),
)
def test_invariants(
    rows: list[tuple[str, str, bool]], title_only: bool, drop_retracted: bool
) -> None:
    records = [rec(title, abstract, is_retracted=retracted) for title, abstract, retracted in rows]
    config = ValidityConfig(include_title_only=title_only, exclude_retracted=drop_retracted)
    result = mark_validity(records, config)
    assert [r.study_uid for r in result.records] == [r.study_uid for r in records]
    assert result.valid_for_model == sum(1 for r in result.records if not r.exclusion_reason)
    assert sum(result.by_reason.values()) + result.valid_for_model == len(records)
    for record in result.records:
        assert record.has_abstract == bool(record.abstract.strip())
        if record.exclusion_reason == "NO_ABSTRACT":
            assert not record.abstract.strip() and not title_only
        if not record.exclusion_reason:
            assert not is_not_screenable(record.title)  # front matter never reaches the model
    again = mark_validity(result.records, config)
    assert [r.model_dump() for r in again.records] == [r.model_dump() for r in result.records]
