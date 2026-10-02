"""Tests for matching a PDF to its bibliographic record (ADR 0026, plan chapter 25.6)."""

from __future__ import annotations

from pathlib import Path

from crapai.io.fulltext_link import link_fulltext, write_unmatched_report
from crapai.io.readers.pdf_zip import PdfDocument
from crapai.io.records_store import Record

UIDS = iter(f"uid-{n}" for n in range(1, 1000))


def new_uid() -> str:
    return next(UIDS)


def record(**overrides: object) -> Record:
    values: dict[str, object] = {
        "study_uid": "anchor-1",
        "source_label": "PubMed",
        "source_file": "pubmed.ris",
        "source_row": 1,
        "source_format": "ris",
    }
    values.update(overrides)
    return Record(**values)  # type: ignore[arg-type]


def doc(**overrides: object) -> PdfDocument:
    values: dict[str, object] = {"member": "a.pdf"}
    values.update(overrides)
    return PdfDocument(**values)  # type: ignore[arg-type]


def test_a_pdf_is_matched_by_doi_first() -> None:
    anchor = record(doi="10.1234/abcd.5678", title="Some unrelated title here")
    result = link_fulltext(
        [anchor],
        [doc(doi="10.1234/ABCD.5678", title="A totally different title")],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    assert len(result.new_records) == 1 and not result.unmatched
    new = result.new_records[0]
    assert new.fulltext_of == "anchor-1" and new.has_fulltext is True
    assert new.zip_member == "a.pdf" and new.study_uid == "uid-1"


def test_a_pdf_without_a_doi_is_matched_by_normalised_title() -> None:
    anchor = record(title="Exercise and Depression: A Randomised Controlled Trial")
    result = link_fulltext(
        [anchor],
        [doc(title="EXERCISE AND DEPRESSION, A RANDOMISED CONTROLLED TRIAL!!!")],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    assert len(result.new_records) == 1
    assert result.new_records[0].fulltext_of == "anchor-1"


def test_an_unmatched_pdf_gets_no_row_but_is_reported() -> None:
    anchor = record(title="Exercise and Depression: A Randomised Controlled Trial")
    result = link_fulltext(
        [anchor],
        [doc(title="Something Completely Unrelated About Cats")],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    assert result.new_records == []
    assert len(result.unmatched) == 1 and result.unmatched[0].title.startswith("Something")


def test_a_short_generic_title_never_matches_by_itself() -> None:
    """Mirrors the dedup rule: a title under MIN_TITLE_WORDS cannot identify a paper."""
    anchor = record(title="Editorial")
    result = link_fulltext(
        [anchor], [doc(title="Editorial")], source_label="PDFs", source_file="pdfs.zip"
    )
    assert result.new_records == [] and len(result.unmatched) == 1


def test_a_fulltext_row_is_never_itself_a_match_target() -> None:
    """Re-importing the same ZIP must not let a PDF match another PDF's row."""
    anchor = record(title="Exercise and Depression: A Randomised Controlled Trial")
    earlier_pdf_row = record(
        study_uid="earlier-pdf", title="", fulltext_of="anchor-1", has_fulltext=True
    )
    result = link_fulltext(
        [anchor, earlier_pdf_row],
        [doc(title="Exercise and Depression: A Randomised Controlled Trial")],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    assert len(result.new_records) == 1
    assert result.new_records[0].fulltext_of == "anchor-1"  # matched the anchor, not the PDF row


def test_a_quality_problem_is_still_recorded_when_matched() -> None:
    anchor = record(doi="10.1234/abcd.5678")
    result = link_fulltext(
        [anchor],
        [doc(doi="10.1234/abcd.5678", quality="NO_TEXT", quality_detail="probably scanned")],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    new = result.new_records[0]
    assert new.exclusion_reason == "NO_TEXT" and new.exclusion_details == "probably scanned"


def test_extracted_quality_flags_are_kept_in_extra_json() -> None:
    anchor = record(doi="10.1234/abcd.5678")
    result = link_fulltext(
        [anchor],
        [doc(doi="10.1234/abcd.5678", pages=8, chars=4000, chars_per_page=500.0, has_text_layer=True)],
        source_label="PDFs", source_file="pdfs.zip", new_uid=new_uid,
    )  # fmt: skip
    extra = result.new_records[0].extra_json
    assert extra["pages"] == 8 and extra["has_text_layer"] is True


def test_the_unmatched_report_is_written_as_csv(tmp_path: Path) -> None:
    path = tmp_path / "unmatched_pdfs.csv"
    write_unmatched_report(path, [doc(title="Orphan Paper", quality="")])
    text = path.read_text(encoding="utf-8-sig")
    assert "zip_member" in text and "Orphan Paper" in text
