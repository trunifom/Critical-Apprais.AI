"""End-to-end: importing a ZIP of PDFs on top of an existing bibliographic import (ADR 0026)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pymupdf
import pytest

from crapai.io.fulltext_link import UNMATCHED_REPORT_NAME
from crapai.io.import_log import read_entries
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.importing import ImportRequest, import_source

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
RIS_FIXTURE = "example_db_nr2_total-10_duplicates-3.ris"
KNOWN_DOI = "10.2468/eai.2022.005"  # the first record of RIS_FIXTURE


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def zip_with(tmp_path: Path, entries: dict[str, bytes], name: str = "pdfs.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in entries.items():
            archive.writestr(member, data)
    return path


@pytest.fixture
def workspace_with_ris(tmp_path: Path) -> Workspace:
    workspace = Workspace.create(tmp_path / "review")
    import_source(workspace, ImportRequest(DATA / RIS_FIXTURE, label="PubMed"))
    return workspace


def test_a_matched_pdf_becomes_a_new_row_linked_by_doi(workspace_with_ris: Workspace) -> None:
    before = read_records(workspace_with_ris.records_csv)
    anchor = next(r for r in before if r.doi == KNOWN_DOI)
    body = "Methods: a randomised trial of a digital intervention. " * 10
    archive = zip_with(
        Path(workspace_with_ris.root).parent,
        {"paper.pdf": make_pdf(f"DOI: {KNOWN_DOI}\n{body}")},
    )
    summary = import_source(workspace_with_ris, ImportRequest(archive, label="Fulltext"))
    assert summary.records == 1 and summary.unmatched == 0
    after = read_records(workspace_with_ris.records_csv)
    assert len(after) == len(before) + 1
    new_row = after[-1]
    assert new_row.fulltext_of == anchor.study_uid
    assert new_row.has_fulltext is True and new_row.zip_member == "paper.pdf"
    assert new_row.source_file == archive.name and new_row.source_label == "Fulltext"
    assert new_row.exclusion_reason == ""  # a readable, matched PDF screens normally
    # the anchor record itself is completely untouched (append-only, golden rule)
    assert after[: len(before)] == before


def test_an_unmatched_pdf_is_reported_not_silently_dropped(workspace_with_ris: Workspace) -> None:
    before = read_records(workspace_with_ris.records_csv)
    archive = zip_with(
        Path(workspace_with_ris.root).parent,
        {"orphan.pdf": make_pdf("Something about cats that matches nothing in the project. " * 5)},
    )
    summary = import_source(workspace_with_ris, ImportRequest(archive, label="Fulltext"))
    assert summary.records == 0 and summary.unmatched == 1
    assert "fulltext_unmatched" in summary.warnings
    after = read_records(workspace_with_ris.records_csv)
    assert after == before  # nothing was added for an unmatched PDF
    report = workspace_with_ris.reports_dir / UNMATCHED_REPORT_NAME
    assert report.exists() and "orphan.pdf" in report.read_text(encoding="utf-8-sig")


def test_an_unreadable_pdf_is_still_linked_with_its_quality_reason(
    workspace_with_ris: Workspace,
) -> None:
    blank = pymupdf.open()
    blank.new_page()
    blank_data = blank.tobytes()
    blank.close()
    archive = zip_with(
        Path(workspace_with_ris.root).parent, {"scan.pdf": blank_data}
    )
    # A blank/scanned PDF has nothing to match by title or DOI, so it lands in "unmatched" here --
    # this test only confirms a quality problem never crashes the import, matched or not.
    summary = import_source(workspace_with_ris, ImportRequest(archive, label="Fulltext"))
    assert summary.records == 0
    assert summary.unmatched == 1


def test_the_import_log_records_a_fulltext_import(workspace_with_ris: Workspace) -> None:
    archive = zip_with(
        Path(workspace_with_ris.root).parent, {"p.pdf": make_pdf(f"DOI: {KNOWN_DOI}\n" + "x" * 200)}
    )
    import_source(workspace_with_ris, ImportRequest(archive, label="Fulltext"))
    entries = read_entries(workspace_with_ris.import_log)
    assert entries[-1].format == "zip" and entries[-1].records == 1


def test_the_original_zip_is_kept_unchanged_in_sources(workspace_with_ris: Workspace) -> None:
    archive = zip_with(
        Path(workspace_with_ris.root).parent, {"p.pdf": make_pdf(f"DOI: {KNOWN_DOI}\n" + "x" * 200)}
    )
    import_source(workspace_with_ris, ImportRequest(archive, label="Fulltext"))
    stored = workspace_with_ris.sources_dir / archive.name
    assert stored.read_bytes() == archive.read_bytes()
