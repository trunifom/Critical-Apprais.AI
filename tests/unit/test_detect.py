"""Tests for format detection (task T-M1-04, plan chapter 25.1)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from crapai.errors import ImportFailed
from crapai.io.readers.detect import (
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


# --- tables (CSV / TSV) ---


def write_table(path: Path, delimiter: str, rows: int = 8, encoding: str = "utf-8") -> Path:
    lines = [delimiter.join(["title", "abstract", "doi"])]
    for i in range(rows):
        lines.append(delimiter.join([f"Title {i}", f"An abstract, with a comma {i}", f"10.1/{i}"]))
    path.write_bytes(("\n".join(lines) + "\n").encode(encoding))
    return path


@pytest.mark.parametrize(
    ("delimiter", "expected"),
    [
        (",", SourceFormat.CSV),
        (";", SourceFormat.CSV),
        ("\t", SourceFormat.TSV),
        ("|", SourceFormat.CSV),
    ],
)
def test_table_delimiter_and_format(tmp_path: Path, delimiter: str, expected: SourceFormat) -> None:
    result = detect_format(write_table(tmp_path / "records.txt", delimiter))
    assert result.format is expected
    assert result.delimiter == delimiter
    assert result.confidence >= 0.8 and "columns" in result.reason


def test_semicolon_table_with_commas_inside_values_is_not_read_as_comma(tmp_path: Path) -> None:
    """Values contain commas ('An abstract, with a comma'); the semicolon still wins."""
    result = detect_format(write_table(tmp_path / "x.csv", ";"))
    assert result.delimiter == ";" and result.confidence == 0.9  # extension agrees


def test_quoted_separator_inside_values_keeps_the_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "q.csv"
    path.write_text('title,abstract\n"A, B","x, y, z"\n"C","d, e"\n', encoding="utf-8")
    result = detect_format(path)
    assert (result.format, result.delimiter) == (SourceFormat.CSV, ",")


def test_cp1252_semicolon_table_like_the_legacy_runs(tmp_path: Path) -> None:
    path = write_table(tmp_path / "legacy.csv", ";", encoding="cp1252")
    path.write_bytes(path.read_bytes().replace(b"Title 1", "Größe 1".encode("cp1252")))
    result = detect_format(path)
    assert result.delimiter == ";" and result.encoding == "cp1252"


def test_tsv_content_with_csv_extension_is_flagged(tmp_path: Path) -> None:
    result = detect_format(write_table(tmp_path / "export.csv", "\t"))
    assert result.format is SourceFormat.TSV and result.extension_mismatch
    assert "extension says .csv" in result.reason


def test_two_row_table_is_enough_but_one_line_is_not(tmp_path: Path) -> None:
    small = tmp_path / "s.csv"
    small.write_text("a,b\n1,2\n", encoding="utf-8")
    assert detect_format(small).format is SourceFormat.CSV
    one = tmp_path / "o.txt"
    one.write_text("just, one, line of prose\n", encoding="utf-8")
    with pytest.raises(ImportFailed):
        detect_format(one)


def test_prose_with_irregular_commas_is_not_a_table(tmp_path: Path) -> None:
    path = tmp_path / "letter.txt"
    path.write_text(
        "Dear all,\nthe attached list, as agreed, is complete.\nKind regards\nA, B, C, D\n",
        encoding="utf-8",
    )
    with pytest.raises(ImportFailed):
        detect_format(path)


def test_bibliographic_formats_win_over_table_detection() -> None:
    """RIS lines contain ' - ' and commas but must never be taken for a table."""
    for name in ("IEEE-Xplore_SR_2023-2024.ris", "pubmed-adhd-set.nbib", "citation-export.bib"):
        assert detect_format(DATA / name).format not in {SourceFormat.CSV, SourceFormat.TSV}


def test_legacy_run_csv_files_are_detected_as_tables() -> None:
    sample = next((ROOT / "legacy_runs").rglob("*.csv"))
    result = detect_format(sample)
    assert result.format is SourceFormat.CSV and result.delimiter == ";"


def test_a_missing_or_unopenable_file_is_an_import_error_not_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(ImportFailed) as missing:
        detect_format(tmp_path / "nope.ris")
    assert missing.value.code == "E101" and "nope.ris" in missing.value.user_message
    with pytest.raises(ImportFailed) as folder:
        detect_format(tmp_path)  # a directory cannot be read as a file
    assert folder.value.code == "E101"
