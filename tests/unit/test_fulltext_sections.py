"""Tests for section detection in a full text (plan chapter 29.8, ADR 0026)."""

from __future__ import annotations

from crapai.prompts.fulltext_sections import methods_results_discussion, split_sections

ARTICLE = """\
Abstract
This paper studies exercise and depression in adults.

Introduction
Depression is common. Exercise may help.

Methods
We enrolled 200 adults in a randomised trial.

Results
The exercise group improved significantly.

Discussion
These findings support exercise as an intervention.

References
Smith J. (2020). A citation.
"""


def test_every_section_is_found_in_order() -> None:
    sections = split_sections(ARTICLE)
    assert list(sections) == [
        "abstract", "introduction", "methods", "results", "discussion", "references",
    ]  # fmt: skip
    assert "200 adults" in sections["methods"]
    assert "Smith J." in sections["references"]


def test_methods_results_discussion_excludes_abstract_intro_and_references() -> None:
    reduced = methods_results_discussion(ARTICLE)
    assert "200 adults" in reduced and "improved significantly" in reduced and "support exercise" in reduced
    assert "Smith J." not in reduced
    assert "This paper studies" not in reduced  # abstract


def test_background_and_methodology_are_recognised_as_synonyms() -> None:
    text = "Background\nContext here.\n\nMethodology\nHow it was done.\n"
    sections = split_sections(text)
    assert sections == {"introduction": "Context here.", "methods": "How it was done."}


def test_a_text_with_no_recognisable_heading_returns_nothing() -> None:
    assert split_sections("Just a wall of text with no headings at all.") == {}
    assert methods_results_discussion("Just a wall of text with no headings at all.") == ""


def test_a_repeated_section_name_is_concatenated_in_order() -> None:
    text = "Methods\nFirst part.\n\nResults\nSome results.\n\nMethods\nSecond part (an addendum).\n"
    sections = split_sections(text)
    assert sections["methods"] == "First part.\n\nSecond part (an addendum)."


def test_a_heading_word_inside_a_sentence_is_not_mistaken_for_a_section_break() -> None:
    text = "Methods\nWe discuss our methods in detail, not as a results heading mid-sentence.\n"
    sections = split_sections(text)
    assert list(sections) == ["methods"]
