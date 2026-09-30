"""Tests for the normalisation helpers (task T-M1-10, plan chapter 8.3)."""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from saralocal.io.normalize import clean_text, coerce_year, normalize_doi, normalize_list


def test_clean_text_applies_nfc() -> None:
    decomposed = "Café"  # e + combining acute
    assert clean_text(decomposed) == "Café"
    assert unicodedata.is_normalized("NFC", clean_text(decomposed))


def test_clean_text_removes_control_characters_but_keeps_text() -> None:
    assert clean_text("a\x00b\x07c\x0bd\x0ce\x1ff\x7f") == "abcdef"
    assert clean_text("tab\there\r\nnew\nline") == "tab here new line"


def test_clean_text_can_keep_line_breaks() -> None:
    assert clean_text("  a\nb  ", single_line=False) == "a\nb"
    assert clean_text("a\x00\nb", single_line=False) == "a\nb"


def test_clean_text_unescapes_html_entities_only_when_present() -> None:
    assert clean_text("Tom &amp; Jerry &lt;3 &#233;t&#xE9;") == "Tom & Jerry <3 été"
    assert clean_text("R&D and A & B; done") == "R&D and A & B; done"  # no entity: unchanged
    assert clean_text("&unknownthing;") == "&unknownthing;"  # unknown names stay as they are


def test_clean_text_of_empty_values() -> None:
    assert clean_text("") == "" and clean_text("   \n ") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1234/ABC.def", "10.1234/abc.def"),
        ("https://doi.org/10.1234/x", "10.1234/x"),
        ("http://dx.doi.org/10.1234/x", "10.1234/x"),
        ("HTTPS://DOI.ORG/10.1234/X", "10.1234/x"),
        ("doi:10.1234/x", "10.1234/x"),
        ("DOI: 10.1234/x", "10.1234/x"),
        ("doi.org/10.1234/x", "10.1234/x"),
        (" 10.1234/ x y ", "10.1234/xy"),
        ("10.1234/x.", "10.1234/x"),  # trailing punctuation from copy and paste
        ("10.1055/s-0040-1701658", "10.1055/s-0040-1701658"),
    ],
)
def test_normalize_doi(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "not a doi", "11.1234/x", "10.12/x", "10.1234/", "n/a"])
def test_normalize_doi_rejects_non_dois(raw: str) -> None:
    assert normalize_doi(raw) is None


def test_normalize_doi_is_idempotent() -> None:
    once = normalize_doi("https://doi.org/10.1234/ABC")
    assert once is not None and normalize_doi(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2021, 2021),
        ("2021", 2021),
        ("2020 Oct-Dec", 2020),
        ("2016///", 2016),
        ("published 1999.", 1999),
        (2021.0, 2021),
        ("1400", 1400),
        ("2100", 2100),
    ],
)
def test_coerce_year(raw: object, expected: int) -> None:
    assert coerce_year(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "n.d.", "1900s", "0000", "1399", "2101", True, "abc"])
def test_coerce_year_never_returns_a_placeholder(raw: object) -> None:
    assert coerce_year(raw) is None


def test_normalize_list() -> None:
    assert normalize_list("Doe, J;  Roe, R ;; Doe, J;") == "Doe, J; Roe, R"
    assert normalize_list("") == "" and normalize_list(" ; ") == ""
    assert normalize_list("a|b|c", separator="|") == "a; b; c"


@given(st.text(alphabet=st.characters(exclude_categories=["Cs"], exclude_characters="&")))
def test_clean_text_is_idempotent_and_free_of_controls(value: str) -> None:
    """Entities are excluded ('&amp;amp;' shrinks once per pass, so it cannot be idempotent)."""
    once = clean_text(value)
    assert clean_text(once) == once
    assert unicodedata.is_normalized("NFC", once)
    assert all(ord(c) >= 0x20 and ord(c) != 0x7F for c in once)
    assert "  " not in once and "\n" not in once


@given(st.integers(min_value=0, max_value=0x10FFFF))
def test_numeric_entities_never_leave_control_characters(code: int) -> None:
    cleaned = clean_text(f"a&#{code};b")
    assert all(ord(c) >= 0x20 and ord(c) != 0x7F for c in cleaned)
