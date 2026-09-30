"""Tests for the RIS reader (task T-M1-05, plan chapter 25.2, lesson L15)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from crapai.errors import ImportFailed
from crapai.io.readers.detect import SourceFormat
from crapai.io.readers.ris import parse_ris_text, read_ris

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
RIS_FIXTURES = sorted(
    name.removeprefix("data/")
    for name, info in EXPECTED.items()
    if name.startswith("data/") and info.get("kind") == "ris"
)


@pytest.mark.parametrize("name", RIS_FIXTURES)
def test_counts_equal_the_oracle(name: str) -> None:
    """Records, abstracts and DOIs equal tests/data/EXPECTED.json for every RIS fixture."""
    result = read_ris(DATA / name)
    expected = EXPECTED[f"data/{name}"]
    assert result.format is SourceFormat.RIS
    assert len(result.records) == expected["records"]
    assert sum(1 for r in result.records if r.fields.get("abstract")) == expected["abstracts"]
    assert sum(1 for r in result.records if r.fields.get("doi")) == expected["doi_count"]
    assert [r.source_row for r in result.records] == list(range(1, expected["records"] + 1))


def test_zotero_file_keeps_multi_line_abstracts_complete() -> None:
    """L15: the 129 continuation lines are appended, not dropped."""
    raw = (DATA / "pubmed_adhd_converted-zotero.ris").read_bytes().decode("utf-8-sig")
    lines = [ln for ln in raw.replace("\r\n", "\n").split("\n") if ln.strip()]
    tagless = [ln for ln in lines if not re.match(r"^[A-Z][A-Z0-9]\s{1,2}-", ln)]
    assert len(tagless) == 129  # the number named in the plan

    result = read_ris(DATA / "pubmed_adhd_converted-zotero.ris")
    abstracts = " ".join(r.fields.get("abstract", "") for r in result.records)
    # Every continuation line's text appears in some abstract (whitespace-normalised).
    squashed = re.sub(r"\s+", " ", abstracts)
    missing = [ln for ln in tagless if re.sub(r"\s+", " ", ln.strip()) not in squashed]
    assert missing == []
    assert "\n" not in abstracts.replace("\n\n", "")  # newlines only as AB/N2 separator


def test_continuation_lines_are_joined_with_one_space() -> None:
    text = (
        "TY  - JOUR\nTI  - Title\nAB  - First part\nsecond part\n  third part  \n"
        "KW  - x\nER  - \n"
    )
    record = parse_ris_text(text).records[0]
    assert record.fields["abstract"] == "First part second part third part"
    assert record.fields["keywords"] == "x"


def test_cochrane_header_lines_are_skipped_and_noted() -> None:
    result = read_ris(DATA / "citation-export.ris")
    first = result.records[0]
    assert first.fields["record_type"] == "journal_article"
    assert first.fields["title"]
    assert any("Record #1 of 6" in note for note in first.notes)
    assert "line(s) outside records" in result.notes[0]
    assert all(r.fields["record_type"] == "journal_article" for r in result.records)


def test_ieee_end_page_volume_and_keywords_are_mapped() -> None:
    """EP and VO are missing from the predecessor's tag list (L15); here they are mapped."""
    result = read_ris(DATA / "IEEE-Xplore_SR_2023-2024.ris")
    with_pages = [r for r in result.records if "-" in r.fields.get("pages", "")]
    assert with_pages, "SP-EP page ranges expected"
    assert any(r.fields.get("volume") for r in result.records)
    conference = [r for r in result.records if r.fields["record_type"] == "conference_paper"]
    assert conference and all(r.fields.get("journal") for r in conference)  # T2 = conference name
    keyword_total = sum(
        len(r.fields["keywords"].split("; ")) for r in result.records if r.fields.get("keywords")
    )
    assert keyword_total >= 500  # plan: 577 KW lines for 46 records (before de-duplication)


def test_zotero_specials_partial_date_missing_title_and_no_abstract_chapter() -> None:
    result = read_ris(DATA / "pubmed_adhd_converted-zotero.ris")
    front = next(r for r in result.records if r.fields.get("title") == "Front-matter")
    assert front.fields["record_type"] == "book_chapter"
    assert front.fields["year"] == 2016  # from PY; DA "2016///" is consistent
    assert "abstract" not in front.fields
    assert sum(1 for r in result.records if not r.fields.get("title")) == 2  # 706 TY, 704 TI
    assert any("ris_L1" in r.extra or "ris_L2" in r.extra for r in result.records)


def test_unknown_tags_go_to_extra_and_nothing_is_lost() -> None:
    text = (
        "TY  - JOUR\nTI  - T\nC1  - custom one\nC1  - custom two\nZZ  - odd\n"
        "L1  - file:///C:/Users/someone/paper.pdf\nID  - abc\nER  - \n"
    )
    record = parse_ris_text(text).records[0]
    assert record.extra["ris_C1"] == ["custom one", "custom two"]
    assert record.extra["ris_ZZ"] == "odd"
    assert record.extra["ris_L1"].startswith("file:///")  # kept, but dropped again on export
    assert record.extra["ris_ID"] == "abc"


def test_field_mapping_rules() -> None:
    text = (
        "TY  -  JOUR\n"  # Cochrane style: two spaces after the dash
        "T1  - Alt title\nTI  - Main title\n"
        "AU  - Doe, Jane\nA1  - Roe, Rick\nAU  - Doe, Jane\nA2  - Editor, Ed\n"
        "PY  - 2021/03/04/\nJO  - Journal of Tests\nJA  - J Test\n"
        "SP  - 100\nEP  - 120\nVL  - 12\nIS  - 3\nSN  - 1234-5678\n"
        "UR  - not a url\nUR  - https://example.org/a\nUR  - https://example.org/b\n"
        "DO  - 10.1234/x\nDO  - 10.1234/y\nLA  - eng\nKW  - a\nKW  - b\nKW  - a\n"
        "AB  - Abstract text\nN2  - Other abstract\nN1  - short note\nER  - \n"
    )
    record = parse_ris_text(text).records[0]
    f = record.fields
    assert f["title"] == "Main title" and record.extra["ris_T1"] == "Alt title"
    assert f["authors"] == "Doe, Jane; Roe, Rick" and f["editors"] == "Editor, Ed"
    assert f["year"] == 2021 and f["journal"] == "Journal of Tests"
    assert record.extra["ris_JA"] == "J Test"
    assert f["pages"] == "100-120" and f["volume"] == "12" and f["issue"] == "3"
    assert f["issn_isbn"] == "1234-5678" and f["language"] == "eng"
    assert f["url"] == "https://example.org/a" and record.extra["ris_UR"] == [
        "not a url",
        "https://example.org/b",
    ]
    assert f["doi"] == "10.1234/x" and record.extra["ris_DO"] == "10.1234/y"
    assert f["keywords"] == "a; b"
    assert f["abstract"] == "Abstract text\n\nOther abstract" and f["abstract_source"] == "AB"
    assert f["notes"] == "short note"


def test_abstract_falls_back_to_n1_only_when_long_and_no_other_abstract() -> None:
    long_note = "x" * 250
    with_n1 = parse_ris_text(f"TY  - JOUR\nTI  - T\nN1  - {long_note}\nER  - \n").records[0]
    assert with_n1.fields["abstract"] == long_note and with_n1.fields["abstract_source"] == "N1"
    assert "notes" not in with_n1.fields
    short = parse_ris_text("TY  - JOUR\nTI  - T\nN1  - short\nER  - \n").records[0]
    assert "abstract" not in short.fields and short.fields["notes"] == "short"
    n2 = parse_ris_text("TY  - JOUR\nTI  - T\nN2  - only n2\nER  - \n").records[0]
    assert n2.fields["abstract"] == "only n2" and n2.fields["abstract_source"] == "N2"


def test_year_never_becomes_a_placeholder() -> None:
    for line in ("PY  - n.d.", "PY  - 0000", "PY  - 3020", ""):
        record = parse_ris_text(f"TY  - JOUR\nTI  - T\n{line}\nER  - \n").records[0]
        assert "year" not in record.fields, line
    from_da = parse_ris_text("TY  - JOUR\nTI  - T\nDA  - 2016///\nER  - \n").records[0]
    assert from_da.fields["year"] == 2016


def test_record_type_table_and_unknown_type() -> None:
    def kind(ty: str) -> str:
        return parse_ris_text(f"TY  - {ty}\nTI  - T\nER  - \n").records[0].fields["record_type"]

    assert [kind(t) for t in ("JOUR", "EJOUR", "MGZN", "NEWS")] == ["journal_article"] * 4
    assert kind("CPAPER") == "conference_paper" and kind("BOOK") == "book"
    assert kind("THES") == "thesis" and kind("BLOG") == "web" and kind("UNPB") == "preprint"
    assert kind("COMP") == "other" and kind("ENCYC") == "other"  # occur in the fixtures
    record = parse_ris_text("TY  - COMP\nTI  - T\nER  - \n").records[0]
    assert record.extra["ris_TY"] == "COMP"  # the original type is not lost


def test_missing_er_missing_ty_and_empty_value_tags() -> None:
    no_er = parse_ris_text("TY  - JOUR\nTI  - A\nTY  - JOUR\nTI  - B\n")
    assert [r.fields["title"] for r in no_er.records] == ["A", "B"]
    assert all("not terminated by ER" in r.notes[-1] for r in no_er.records)

    with pytest.raises(ImportFailed):  # no TY anywhere: not RIS
        parse_ris_text("TI  - Orphan\nAU  - X, Y\nER  - \n")
    orphan = "TI  - Orphan\nER  - \nTY  - JOUR\nTI  - Real\nER  - \n"
    no_ty = parse_ris_text(orphan).records[0]
    assert no_ty.fields["title"] == "Orphan" and "record without TY line" in no_ty.notes

    empty = parse_ris_text("TY  - JOUR\nTI  - T\nAB  - \nER  - \n").records[0]
    assert "abstract" not in empty.fields


def test_no_records_raises_e102() -> None:
    for text in ("", "just prose\nwithout tags\n"):
        with pytest.raises(ImportFailed) as info:
            parse_ris_text(text)
        assert info.value.code == "E102"


def test_encoding_and_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "cp.ris"
    path.write_bytes("TY  - JOUR\r\nTI  - Größe – Ähnlichkeit\r\nER  - \r\n".encode("cp1252"))
    result = read_ris(path)
    assert result.encoding == "cp1252"
    assert result.records[0].fields["title"] == "Größe – Ähnlichkeit"
    forced = read_ris(path, encoding="cp1252")
    assert forced.encoding == "cp1252"
    with pytest.raises(ImportFailed) as info:
        read_ris(path, encoding="ascii")
    assert info.value.code == "E103"


def test_nbib_content_is_not_silently_read_as_ris() -> None:
    """A MEDLINE file has no TY lines, so the RIS reader refuses it (detect_format says NBIB)."""
    with pytest.raises(ImportFailed):
        read_ris(DATA / "pubmed-adhd-set.nbib")
