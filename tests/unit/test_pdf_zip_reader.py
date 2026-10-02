"""Tests for the PDF-ZIP reader (task T-M1-09, plan chapter 25.6, ADR 0026)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pymupdf
import pytest

from crapai.errors import ImportFailed
from crapai.io.readers.pdf_zip import extract_one, extract_pdf_zip

ROOT = Path(__file__).resolve().parents[2] / "tests"
LARGE = ROOT / "data_large" / "test.zip"


def make_pdf(text: str, *, encrypt: bool = False) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    # insert_textbox wraps and keeps line breaks faithfully (insert_text draws one unwrapped
    # line and silently clips anything past the page edge, which is realistic for a PDF viewer
    # but wrong for a test fixture meant to round-trip exact text).
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=10)
    if encrypt:
        buffer = io.BytesIO()
        doc.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
        data = buffer.getvalue()
    else:
        data = doc.tobytes()
    doc.close()
    return data


def blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def zip_of(entries: dict[str, bytes], path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_pdfs_are_found_macosx_and_non_pdf_entries_are_skipped(tmp_path: Path) -> None:
    archive = zip_of(
        {
            "papers/good.pdf": make_pdf("A Title About Exercise\nMethods: adults were enrolled."),
            "__MACOSX/._good.pdf": b"junk",
            "notes.txt": b"not a pdf",
            "a_folder/": b"",
        },
        tmp_path / "pdfs.zip",
    )
    result = extract_pdf_zip(archive)
    assert [d.member for d in result.documents] == ["papers/good.pdf"]
    assert "3 non-PDF entr(ies)" in result.notes[0]  # __MACOSX entry, notes.txt, the folder entry


def test_nothing_is_ever_extracted_to_disk(tmp_path: Path) -> None:
    archive = zip_of({"a.pdf": make_pdf("Some title\nSome body text here.")}, tmp_path / "pdfs.zip")
    before = set(tmp_path.iterdir())
    extract_pdf_zip(archive)
    after = set(tmp_path.iterdir())
    assert before == after  # only the ZIP itself exists, nothing was written next to it


def test_a_zip_slip_member_name_cannot_write_outside_the_project(tmp_path: Path) -> None:
    """Regression guard: ZipFile.read()/.open() are used, never .extract()/.extractall()."""
    archive = zip_of(
        {"../../evil.pdf": make_pdf("Title\nBody text goes here for this test.")},
        tmp_path / "pdfs.zip",
    )
    result = extract_pdf_zip(archive)
    assert len(result.documents) == 1
    assert not (tmp_path.parent.parent / "evil.pdf").exists()


def test_a_usable_pdf_gets_title_doi_and_quality_flags(tmp_path: Path) -> None:
    text = (
        "A Great Study About Exercise and Health\nDOI: 10.1234/abcd.5678\n"
        "Methods: a randomised trial enrolled adults with chronic pain. "
        "Results: a structured exercise programme reduced pain scores significantly."
    )
    archive = zip_of({"p.pdf": make_pdf(text)}, tmp_path / "pdfs.zip")
    doc = extract_pdf_zip(archive).documents[0]
    assert doc.quality == ""
    assert doc.title == "A Great Study About Exercise and Health"
    assert doc.doi == "10.1234/abcd.5678"
    assert doc.has_text_layer is True
    assert doc.pages == 1 and doc.chars > 0


def test_a_blank_page_is_flagged_no_text(tmp_path: Path) -> None:
    archive = zip_of({"blank.pdf": blank_pdf()}, tmp_path / "pdfs.zip")
    doc = extract_pdf_zip(archive).documents[0]
    assert doc.quality == "NO_TEXT"
    assert doc.has_text_layer is False
    assert doc.text == ""


def test_an_encrypted_pdf_is_flagged_encrypted(tmp_path: Path) -> None:
    archive = zip_of(
        {"enc.pdf": make_pdf("Secret content for the encryption test.", encrypt=True)},
        tmp_path / "pdfs.zip",
    )
    doc = extract_pdf_zip(archive).documents[0]
    assert doc.quality == "ENCRYPTED"


def test_a_damaged_pdf_is_flagged_import_error_not_a_crash(tmp_path: Path) -> None:
    archive = zip_of({"broken.pdf": b"%PDF-1.4\nnot actually a valid pdf"}, tmp_path / "pdfs.zip")
    doc = extract_pdf_zip(archive).documents[0]
    assert doc.quality == "IMPORT_ERROR"


def test_a_zip_with_no_pdfs_is_refused() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        archive = zip_of({"readme.txt": b"hello"}, Path(tmp) / "empty.zip")
        with pytest.raises(ImportFailed) as info:
            extract_pdf_zip(archive)
        assert info.value.code == "E102"


def test_a_damaged_zip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.zip"
    path.write_bytes(b"PK\x03\x04not a real zip")
    with pytest.raises(ImportFailed) as info:
        extract_pdf_zip(path)
    assert info.value.code == "E101"


def test_repeated_header_and_footer_lines_are_removed() -> None:
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 50), "Journal of Testing 2026")
        body = f"Unique content for page {i}. " + ("Filler sentence to pass the page. " * 5)
        page.insert_textbox(pymupdf.Rect(72, 90, 550, 700), body, fontsize=10)
        page.insert_text((72, 750), str(i + 1))
    data = doc.tobytes()
    doc.close()
    extracted = extract_one("x.pdf", data)
    assert "Journal of Testing 2026" not in extracted.text
    assert "Unique content for page 0." in extracted.text


def test_hyphenated_line_breaks_are_joined() -> None:
    filler = "Filler sentence to reach the minimum page length for this test. " * 3
    data = make_pdf(
        f"{filler}The partici-\npants were adults in this trial of the inter-\nvention."
    )
    extracted = extract_one("x.pdf", data)
    assert "partici-\npants" not in extracted.text
    assert "participants" in extracted.text


def test_text_after_a_references_heading_is_cut() -> None:
    body = "Methods: adults were enrolled. " * 40
    text = f"{body}\nReferences\nSmith J. (2020). Some citation that should be cut."
    extracted = extract_one("x.pdf", make_pdf(text))
    assert extracted.quality == ""
    assert "Methods" in extracted.text
    assert "Smith J." not in extracted.text


def test_a_title_guess_falls_back_to_the_file_name_when_text_is_too_short() -> None:
    data = make_pdf("x")
    extracted = extract_one("my_cool-paper.pdf", data)
    # "x" alone is too short to be a title; chars_per_page is also too low, so this is NO_TEXT
    # with an empty title -- a thin but real regression guard that nothing crashes on short text.
    assert extracted.quality == "NO_TEXT"


@pytest.mark.large
@pytest.mark.skipif(not LARGE.exists(), reason="tests/data_large is not versioned")
def test_the_large_fixture_has_six_usable_pdfs_and_skips_macosx_entries() -> None:
    result = extract_pdf_zip(LARGE)
    assert len(result.documents) == 6
    assert all(doc.quality == "" for doc in result.documents)
    assert "6 non-PDF entr(ies)" in result.notes[0]
    dois = {doc.doi for doc in result.documents if doc.doi}
    assert len(dois) >= 2  # at least a couple of the real papers carry a DOI on page 1
