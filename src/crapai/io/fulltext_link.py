"""Match a PDF to the bibliographic record it belongs to (plan chapter 25.6, ADR 0026).

A PDF found by :mod:`crapai.io.readers.pdf_zip` is not a new paper: it is the full text of a paper
that (is expected to) already sit in ``records.csv`` from an earlier RIS/NBIB/BibTeX/CSV/XLSX
import. Matching uses the same comparison keys as deduplication (:mod:`crapai.prisma.dedup`): first
DOI, then normalised title. A match becomes a **new row**, never an edit of the existing one
(append-only, plan chapter 8.3): the new row carries ``has_fulltext``, ``zip_member`` and
``fulltext_of`` (the matched record's ``study_uid``); the matched record itself is untouched. An
unmatched PDF gets no row at all -- there is no paper in the project to attach it to -- but it is
never silently dropped either: it comes back from :func:`link_fulltext` for the caller to report.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from crapai.io.normalize import clean_text, normalize_doi
from crapai.io.readers.pdf_zip import PdfDocument
from crapai.io.records_store import Record
from crapai.io.writers.tables import write_csv
from crapai.prisma.dedup import doi_key, title_key
from crapai.project.atomic import WriteResult

logger = logging.getLogger(__name__)

UNMATCHED_REPORT_NAME = "unmatched_pdfs.csv"
_UNMATCHED_HEADER = ("zip_member", "title_guess", "doi_guess", "pages", "quality", "quality_detail")


@dataclass(frozen=True)
class FulltextLinkResult:
    """What matching one PDF-ZIP against the existing records produced.

    Attributes:
        new_records: One row per PDF that was matched to an existing record (append to
            ``records.csv``).
        unmatched: PDFs that matched nothing (for :func:`write_unmatched_report`).
    """

    new_records: list[Record]
    unmatched: list[PdfDocument] = field(default_factory=list)


def link_fulltext(
    existing: list[Record],
    documents: list[PdfDocument],
    *,
    source_label: str,
    source_file: str,
    new_uid: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> FulltextLinkResult:
    """Match each PDF to a record in ``existing`` by DOI, then by normalised title.

    A PDF whose own quality is ``NO_TEXT``/``ENCRYPTED``/``IMPORT_ERROR`` still becomes a row if
    matched (with that value as ``exclusion_reason``): the plan-time fulltext lookup can then tell
    "no PDF was ever found for this record" from "a PDF was found but could not be read", instead
    of the two looking identical.
    """
    by_doi: dict[str, Record] = {}
    by_title: dict[str, Record] = {}
    for record in existing:
        if record.fulltext_of:
            continue  # a fulltext row is an attachment, never itself a match target
        doi = doi_key(record.doi)
        if doi:
            by_doi.setdefault(doi, record)
        title = title_key(record.title)
        if title:
            by_title.setdefault(title, record)

    new_records: list[Record] = []
    unmatched: list[PdfDocument] = []
    for row_number, doc in enumerate(documents, start=1):
        doi = normalize_doi(doc.doi) or ""
        target = by_doi.get(doi) if doi else None
        if target is None:
            title = title_key(doc.title)
            target = by_title.get(title) if title else None
        if target is None:
            unmatched.append(doc)
            continue
        new_records.append(
            Record(
                study_uid=new_uid(),
                source_label=source_label,
                source_file=source_file,
                source_row=row_number,
                source_format="pdf",
                record_type="other",
                title=clean_text(doc.title),
                doi=doi,
                has_fulltext=True,
                fulltext_of=target.study_uid,
                zip_member=doc.member,
                exclusion_reason=doc.quality,
                exclusion_details=doc.quality_detail,
                import_notes="; ".join(note for note in doc.notes if note),
                extra_json={
                    "pages": doc.pages,
                    "chars": doc.chars,
                    "chars_per_page": doc.chars_per_page,
                    "has_text_layer": doc.has_text_layer,
                },
            )
        )
    logger.info(
        "Full-text link: %d of %d PDF(s) matched an existing record",
        len(new_records), len(documents),
    )  # fmt: skip
    return FulltextLinkResult(new_records=new_records, unmatched=unmatched)


def write_unmatched_report(path: Path, unmatched: list[PdfDocument]) -> WriteResult:
    """Write the PDFs that matched no record to ``reports/unmatched_pdfs.csv`` (never dropped)."""
    rows = [
        [doc.member, doc.title, doc.doi, str(doc.pages), doc.quality, doc.quality_detail]
        for doc in unmatched
    ]
    return write_csv(path, _UNMATCHED_HEADER, rows)
