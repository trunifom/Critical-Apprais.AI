"""Tests for the BibTeX reader (task T-M1-07, plan chapter 25.4)."""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path

import pytest

from saralocal.errors import ImportFailed
from saralocal.io.readers.bibtex import (
    clean_abstract,
    clean_latex,
    parse_bibtex_text,
    read_bibtex,
)
from saralocal.io.readers.detect import SourceFormat

ROOT = Path(__file__).resolve().parents[2] / "tests"
DATA = ROOT / "data"
LARGE = ROOT / "data_large" / "citation-export_2.bib"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
BIB_FIXTURES = sorted(
    name.removeprefix("data/")
    for name, info in EXPECTED.items()
    if name.startswith("data/") and info.get("kind") == "bibtex"
)


@pytest.mark.parametrize("name", BIB_FIXTURES)
def test_entry_counts_equal_the_oracle(name: str) -> None:
    result = read_bibtex(DATA / name)
    assert result.format is SourceFormat.BIBTEX
    assert len(result.records) == EXPECTED[f"data/{name}"]["records"]


def test_cochrane_file_reads_48_entries_despite_record_lines() -> None:
    result = read_bibtex(DATA / "citation-export.bib")
    assert len(result.records) == 48
    assert "48 non-empty line(s) outside entries were skipped" in result.notes
    assert all(r.fields.get("abstract") for r in result.records)


def test_zotero_file_types_abstracts_and_dois() -> None:
    result = read_bibtex(DATA / "pubmed_adhd_converted-zotero.bib")
    assert len(result.records) == 706
    types = collections.Counter(r.extra["bib_type"] for r in result.records)
    assert dict(types) == {
        "article": 576,
        "book": 90,
        "misc": 29,
        "incollection": 9,
        "inproceedings": 2,
    }
    assert sum(1 for r in result.records if r.fields.get("abstract")) == 156  # same as the RIS twin
    assert sum(1 for r in result.records if r.fields.get("doi")) == 595
    assert sum(1 for r in result.records if not r.fields.get("title")) == 2  # 704 titles of 706


def test_bib_twin_agrees_with_ris_twin_on_titles() -> None:
    """The Zotero .bib and .ris hold the same 706 references; titles must agree."""
    from saralocal.io.readers.ris import read_ris

    bib = read_bibtex(DATA / "pubmed_adhd_converted-zotero.bib").records
    ris = read_ris(DATA / "pubmed_adhd_converted-zotero.ris").records
    same = sum(
        1 for b, r in zip(bib, ris, strict=True) if b.fields.get("title") == r.fields.get("title")
    )
    assert same >= 690  # a few differ in braces/dashes between the two exports


def test_cochrane_field_names_with_spaces_and_trial_registry() -> None:
    result = read_bibtex(DATA / "citation-export.bib")
    first = result.records[0]
    assert first.fields["publication_types"] == "Trial registry record"  # "publication type = {"
    assert first.fields["record_type"] == "trial_registry"
    assert "authors" not in first.fields  # only NCT04921410,
    assert first.fields["accession_number"] == "CTgov NCT04921410"
    assert first.fields["url"].startswith("https://")  # "URL" upper case is read
    registry = sum(1 for r in result.records if r.fields["record_type"] == "trial_registry")
    assert registry == 20


def test_typographic_hyphen_is_kept() -> None:
    """U+2010 in the source is kept (NFC only, no replacement), as the plan requires."""
    result = read_bibtex(DATA / "citation-export.bib")
    assert "collegiate\u2010level" in result.records[0].fields["abstract"]


@pytest.mark.large
@pytest.mark.skipif(not LARGE.exists(), reason="tests/data_large is not versioned")
def test_large_file_imports_within_time_limit() -> None:
    started = time.perf_counter()
    result = read_bibtex(LARGE)
    elapsed = time.perf_counter() - started
    assert len(result.records) == 1343
    assert elapsed < 30, f"took {elapsed:.1f} s"


def test_reading_writes_no_file_into_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The predecessor's bibReader path left side files behind; this reader must not."""
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    read_bibtex(DATA / "citation-export_1.bib")
    assert list(work.iterdir()) == []


SAMPLE = r"""
% a comment line
@string{jou = "Journal of Tests"}
@preamble{"\newcommand{\noop}[1]{}"}
@comment{ignored}
Record #1 of 3
@article{k1,
  author   = {Doe, Jane and M{\"u}ller, Hans and {World Health Organization}},
  title    = {{ADHD} in {Children}: 50\% \& more {\"u}ber},
  JOURNAL  = jou # {, } # "Series A",
  year     = 2021,
  month    = jan,
  pages    = {100--120},
  URL      = {https://example.org/x},
  keywords = {adhd, children; school},
  abstract = {Rates rose by 5\% in "adults" {and} more.},
  file     = {C:/Users/someone/Zotero/paper.pdf},
  custom   = {kept}
}
@book(k2,
  title = "A {Book} with a {\"}quoted{\"} word",
  author = "Roe, Rick",
  date = {2019-05-01}
)
@article{k1, title = {Duplicate key allowed}}
@misc{broken, title = {Unclosed value
@article{after, title = {Still read}}
"""


def test_sample_mapping_and_cleaning() -> None:
    result = parse_bibtex_text(SAMPLE)
    first = result.records[0]
    f = first.fields
    assert f["title"] == "ADHD in Children: 50% & more über"
    assert f["authors"] == "Doe, Jane; Müller, Hans; World Health Organization"
    assert f["journal"] == "Journal of Tests, Series A"  # macro # string # quoted part
    assert f["year"] == 2021 and f["pages"] == "100-120"
    assert f["url"] == "https://example.org/x"  # field names are case-insensitive
    assert f["keywords"] == "adhd; children; school"  # comma and semicolon separators
    assert f["abstract"] == 'Rates rose by 5% in "adults" {and} more.'  # minimal cleaning only
    assert first.extra["bib_custom"] == "kept" and first.extra["bib_key"] == "k1"
    assert "file" not in "".join(first.extra)  # local path is not imported
    assert "C:/Users" not in json.dumps(first.extra) + json.dumps(f)
    assert any("file field" in n for n in first.notes)


def test_parenthesis_delimiter_quotes_and_date_fallback() -> None:
    book = parse_bibtex_text(SAMPLE).records[1]
    assert book.fields["record_type"] == "book"
    # A quote inside braces belongs to the value; it does not end the quoted string.
    assert book.fields["title"].startswith("A Book with a")
    assert book.fields["title"].endswith("word")
    assert book.fields["year"] == 2019  # from date = {2019-05-01}


def test_duplicate_keys_are_allowed_and_damage_stays_local() -> None:
    records = parse_bibtex_text(SAMPLE).records
    assert [r.extra.get("bib_key") for r in records] == ["k1", "k2", "k1", "broken", "after"]
    broken = records[3]
    assert any("unbalanced" in n for n in broken.notes)
    assert records[4].fields["title"] == "Still read"  # the next entry is not swallowed
    assert [r.source_row for r in records] == [1, 2, 3, 4, 5]


def test_string_preamble_comment_are_not_records() -> None:
    result = parse_bibtex_text("@string{a = {x}}\n@comment{y}\n@article{k, title={T}}\n")
    assert len(result.records) == 1


def test_month_macros_and_bare_numbers() -> None:
    record = parse_bibtex_text("@article{k, title={T}, year=1999, volume=12, month=dec}").records[0]
    assert record.fields["year"] == 1999 and record.fields["volume"] == "12"
    assert record.extra["bib_month"] == "12"


def test_year_is_never_a_placeholder() -> None:
    record = parse_bibtex_text("@article{k, title={T}, year={n.d.}}").records[0]
    assert "year" not in record.fields


def test_no_entries_raises_e102() -> None:
    for text in ("", "Record #1 of 5\nsome prose\n", "@string{a={b}}"):
        with pytest.raises(ImportFailed) as info:
            parse_bibtex_text(text)
        assert info.value.code == "E102"


def test_clean_latex_and_clean_abstract() -> None:
    assert clean_latex("plain text") == "plain text"
    assert clean_latex("{ADHD} and {\\\"u}ber") == "ADHD and über"
    assert clean_latex("50\\% of {\\&}") == "50% of &"
    assert clean_latex("100% sure") == "100% sure"  # bare % must not start a comment
    assert clean_abstract("a  \n b \\% \\&") == "a b % &"


def test_pathological_long_line_is_fast() -> None:
    long_value = "word " * 40000  # a 200 kB single-line abstract
    started = time.perf_counter()
    result = parse_bibtex_text(f"@article{{k, title={{T}}, abstract={{{long_value}}}}}")
    assert time.perf_counter() - started < 2
    assert len(result.records[0].fields["abstract"]) > 190000


def test_encoding_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "x.bib"
    path.write_bytes("@article{k, title={Größe}}".encode("cp1252"))
    result = read_bibtex(path)
    assert result.encoding == "cp1252" and result.records[0].fields["title"] == "Größe"
