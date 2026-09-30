"""Tests for format detection (task T-M1-04, plan chapter 25.1)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from saralocal.errors import ImportFailed
from saralocal.io.readers.detect import (
    SNIFF_BYTES,
    DetectionResult,
    SourceFormat,
    decode_head,
    detect_format,
)

ROOT = Path(__file__).resolve().parents[2] / "tests"
DATA = ROOT / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
FIXTURES = [
    name.removeprefix("data/")
    for name, info in EXPECTED.items()
    if name.startswith("data/") and info.get("kind") in {"ris", "nbib", "bibtex"}
]


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_matches_the_oracle_kind(name: str) -> None:
    """Detection agrees with the independent oracle in EXPECTED.json for all small fixtures."""
    result = detect_format(DATA / name)
    assert result.format.value == EXPECTED[f"data/{name}"]["kind"], result.reason
    assert result.confidence >= 0.9


def test_nbib_saved_as_ris_is_detected_as_nbib_and_flagged() -> None:
    result = detect_format(DATA / "pubmed-adhd-set.ris")
    assert result.format is SourceFormat.NBIB
    assert result.extension_mismatch
    assert "MEDLINE" in result.reason and ".ris" in result.reason


def test_ris_with_txt_extension_is_detected_as_ris() -> None:
    result = detect_format(DATA / "example_AB_nr4.txt")
    assert result.format is SourceFormat.RIS
    assert not result.extension_mismatch  # .txt names no format, so there is nothing to contradict


def test_cochrane_bibtex_with_record_lines_and_cochrane_ris_with_two_spaces() -> None:
    assert detect_format(DATA / "citation-export.bib").format is SourceFormat.BIBTEX
    assert detect_format(DATA / "citation-export.ris").format is SourceFormat.RIS


def test_bibtex_after_blank_line_zotero_style() -> None:
    assert detect_format(DATA / "pubmed_adhd_converted-zotero.bib").format is SourceFormat.BIBTEX


def test_result_carries_type_confidence_and_reason() -> None:
    result = detect_format(DATA / "example_db_nr2_total-10_duplicates-3.ris")
    assert isinstance(result, DetectionResult)
    assert (result.format, result.extension_mismatch) == (SourceFormat.RIS, False)
    assert 0.0 < result.confidence <= 1.0 and result.reason
    assert result.encoding in {"utf-8-sig", "utf-8"}


def test_content_beats_extension(tmp_path: Path) -> None:
    """A BibTeX file named .ris is BibTeX; a RIS file named .bib is RIS."""
    bib = tmp_path / "x.ris"
    bib.write_text("@article{a,\n title={T}\n}\n", encoding="utf-8")
    assert detect_format(bib).format is SourceFormat.BIBTEX
    ris = tmp_path / "y.bib"
    ris.write_text("TY  - JOUR\nTI  - T\nER  - \n", encoding="utf-8")
    result = detect_format(ris)
    assert result.format is SourceFormat.RIS and result.extension_mismatch


def test_extension_is_only_a_low_confidence_fallback(tmp_path: Path) -> None:
    path = tmp_path / "odd.ris"
    path.write_text("nothing recognisable here, just words\n", encoding="utf-8")
    result = detect_format(path)
    assert result.format is SourceFormat.RIS and result.confidence < 0.5
    assert "not conclusive" in result.reason


def test_ris_without_ty_but_with_tags_has_medium_confidence(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("TI  - A\nAU  - B\nPY  - 2020\n", encoding="utf-8")
    result = detect_format(path)
    assert result.format is SourceFormat.RIS and result.confidence == 0.5


def test_mixed_markers_decided_by_first_record(tmp_path: Path) -> None:
    both = tmp_path / "m.txt"
    both.write_text("PMID- 123\nTI  - A\n\nTY  - JOUR\nTI  - B\n", encoding="utf-8")
    result = detect_format(both)
    assert result.format is SourceFormat.NBIB and result.confidence < 0.9


def test_unrecognised_text_raises_e101(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Dear reviewer, please find attached\n", encoding="utf-8")
    with pytest.raises(ImportFailed) as info:
        detect_format(path)
    assert info.value.code == "E101"


def test_empty_and_whitespace_only_files_raise_e102(tmp_path: Path) -> None:
    for content in (b"", b"  \r\n \n"):
        path = tmp_path / "empty.ris"
        path.write_bytes(content)
        with pytest.raises(ImportFailed) as info:
            detect_format(path)
        assert info.value.code == "E102"


def test_pdf_zip_xlsx_and_legacy_xls(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7\n%...")
    assert detect_format(pdf).format is SourceFormat.PDF

    plain_zip = tmp_path / "docs.zip"
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("a.pdf", b"%PDF-1.4")
    assert detect_format(plain_zip).format is SourceFormat.ZIP

    workbook = tmp_path / "sheet.dat"  # wrong extension on purpose
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    result = detect_format(workbook)
    assert result.format is SourceFormat.XLSX and result.encoding is None

    xls = tmp_path / "old.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    with pytest.raises(ImportFailed) as info:
        detect_format(xls)
    assert info.value.code == "E101" and ".xlsx" in (info.value.hint or "")


def test_damaged_zip_and_binary_garbage(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04" + b"garbage" * 10)
    with pytest.raises(ImportFailed):
        detect_format(broken)
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"abc\x00\x01\x02def")
    with pytest.raises(ImportFailed):
        detect_format(blob)


def test_cp1252_and_bom_files_are_sniffed(tmp_path: Path) -> None:
    cp = tmp_path / "cp.ris"
    text = "TY  - JOUR\nTI  - Größe der Stichprobe – Ähnlichkeit\nER  - \n"
    cp.write_bytes(text.encode("cp1252"))
    result = detect_format(cp)
    assert result.format is SourceFormat.RIS and result.encoding == "cp1252"
    bom = tmp_path / "bom.ris"
    bom.write_bytes(b"\xef\xbb\xbfTY  - JOUR\nTI  - T\nER  - \n")
    assert detect_format(bom).format is SourceFormat.RIS  # BOM does not hide the first tag


def test_multibyte_character_cut_at_sample_end_is_not_an_error(tmp_path: Path) -> None:
    body = "TY  - JOUR\nTI  - " + "ä" * (SNIFF_BYTES)  # 2 bytes per char, far beyond the sample
    path = tmp_path / "long.ris"
    path.write_text(body, encoding="utf-8")
    result = detect_format(path)
    assert result.format is SourceFormat.RIS and result.encoding == "utf-8-sig"


def test_decode_head_chain() -> None:
    assert decode_head(b"abc", truncated=False) == ("abc", "utf-8-sig")
    assert decode_head("é".encode("cp1252"), truncated=False) == ("é", "cp1252")
    assert decode_head(b"\x81", truncated=False)[1] == "latin-1"  # undefined in cp1252
