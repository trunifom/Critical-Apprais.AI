"""Read full-text PDFs from a ZIP archive (plan chapter 25.6, task T-M1-09, ADR 0026).

This is **not** a bibliographic reader like the others in this package: a PDF-ZIP does not add new
papers to the review, it adds the full text of papers that are (expected to be) already in
``records.csv`` from an earlier bibliographic import. Matching a PDF to its record (by DOI, then by
title) is done by :mod:`crapai.io.fulltext_link`, which needs the project's existing records; that
is why this module only extracts (pure, no project access) and :mod:`crapai.services.importing`
does the matching and writing.

The ZIP is never extracted to disk (only ``ZipFile.read``/``.open``, never ``.extract*``, so a
crafted entry path such as ``../../etc/passwd`` cannot write anywhere -- "zip-slip"). Entries that
are directories, start with ``__MACOSX/`` or whose base name starts with ``._`` (both are macOS
archiving artefacts), or do not end in ``.pdf``, are skipped and counted, never read.

Each PDF is extracted with PyMuPDF first (``get_text("text", sort=True)``, which reads a page in
visual rather than stream order -- important for multi-column articles); pdfplumber is the fallback
if PyMuPDF raises or returns no text. The result is cleaned (de-hyphenation, ligatures, repeated
headers/footers, page numbers, collapsed blank lines) and optionally cut at the bibliography, then
scored with quality flags: ``has_text_layer``, ``pages``, ``chars``, ``chars_per_page``. A PDF with
too little text per page is probably scanned without OCR (``NO_TEXT``); one PyMuPDF reports as
needing a password is ``ENCRYPTED``; anything else that fails to open or parse is ``IMPORT_ERROR``.
These three are already part of ``records.csv``'s exclusion reason catalogue (plan chapter 26.3).
"""

from __future__ import annotations

import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crapai.errors import ImportFailed

logger = logging.getLogger(__name__)

MAX_PDF_MB = 50
MAX_PAGES = 200
PER_PDF_TIMEOUT_S = 60.0
# Below this many characters per page, a PDF is treated as scanned without a usable text layer.
MIN_CHARS_PER_PAGE = 100

_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:[Pp]age\s+)?\d{1,4}(?:\s*/\s*\d{1,4})?\s*$")
_BLANK_RUN = re.compile(r"\n{3,}")
_REFERENCES_HEADING = re.compile(
    r"^\s*(references|bibliography|literatur|literaturverzeichnis)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LIGATURES = str.maketrans(
    {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬆ": "st"}
)


class _PdfTimeout(Exception):
    """A single PDF took longer than :data:`PER_PDF_TIMEOUT_S` to extract."""


@dataclass
class PdfDocument:
    """One PDF found in the ZIP, extracted and scored.

    Attributes:
        member: Its exact path inside the ZIP (never a path on disk -- the PDF is never
            extracted); this is what :class:`~crapai.io.records_store.Record.zip_member` stores.
        title: Guessed from the PDF's own metadata, else its first substantial line, else the
            file name.
        doi: The first DOI-shaped string found on the first two pages, or ``""``.
        text: The cleaned full text (empty if ``quality`` is set).
        pages, chars, chars_per_page, has_text_layer: Quality flags (plan chapter 25.6).
        quality: ``""`` (usable), or one of ``NO_TEXT``/``ENCRYPTED``/``IMPORT_ERROR`` -- values
            already in :data:`crapai.io.records_store.EXCLUSION_REASONS`.
        quality_detail: Human-readable reason, for ``exclusion_details``.
        notes: Import remarks (truncation, fallback extractor used, ...).
    """

    member: str
    title: str = ""
    doi: str = ""
    text: str = ""
    pages: int = 0
    chars: int = 0
    chars_per_page: float = 0.0
    has_text_layer: bool = False
    quality: str = ""
    quality_detail: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class PdfZipResult:
    """Everything found in one ZIP archive.

    Attributes:
        documents: One per PDF member that was found (including unusable ones, flagged in
            ``quality`` -- a bad PDF is reported, never silently skipped).
        notes: Archive-level remarks (how many non-PDF entries were skipped and why).
    """

    documents: list[PdfDocument]
    notes: list[str] = field(default_factory=list)


def _is_pdf_member(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    if name.endswith("/"):
        return False
    if name.startswith("__MACOSX/"):
        return False
    base = name.rsplit("/", 1)[-1]
    if base.startswith("._"):
        return False
    return base.lower().endswith(".pdf")


def _ligatures_and_hyphens(text: str) -> str:
    text = text.translate(_LIGATURES)
    return _HYPHEN_BREAK.sub(r"\1\2", text)


def _strip_repeated_lines(pages: list[str]) -> list[str]:
    """Remove a line that recurs, stripped and verbatim, on more than half the pages."""
    if len(pages) < 3:
        return pages
    counts: dict[str, int] = {}
    per_page_lines = [[line.strip() for line in page.split("\n")] for page in pages]
    for lines in per_page_lines:
        for line in set(lines):
            if line:
                counts[line] = counts.get(line, 0) + 1
    threshold = len(pages) / 2
    repeated = {line for line, count in counts.items() if count > threshold}
    cleaned = []
    for lines in per_page_lines:
        kept = [
            line
            for line in lines
            if line.strip() not in repeated and not _PAGE_NUMBER_LINE.match(line)
        ]
        cleaned.append("\n".join(kept))
    return cleaned


def _cut_at_references(text: str) -> str:
    match = _REFERENCES_HEADING.search(text)
    # Require some real body first, so a short "References" heading used as a section label
    # elsewhere (unlikely, but cheap to guard) cannot truncate almost the whole article.
    return text[: match.start()] if match and match.start() > 500 else text


def _clean_text(raw_pages: list[str]) -> str:
    pages = _strip_repeated_lines(raw_pages)
    text = _ligatures_and_hyphens("\n".join(pages))
    text = _BLANK_RUN.sub("\n\n", text)
    return _cut_at_references(text).strip()


_DOI_LINE = re.compile(r"^\s*doi\s*:?\s*10\.", re.IGNORECASE)


def _guess_title(meta_title: str, text: str, member: str) -> str:
    cleaned_meta = meta_title.strip()
    if len(cleaned_meta) >= 8:
        return cleaned_meta
    for line in text.split("\n"):
        candidate = line.strip()
        if (
            len(candidate) >= 8
            and not _PAGE_NUMBER_LINE.match(candidate)
            and not _DOI_LINE.match(candidate)
        ):
            return candidate
    stem = member.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return re.sub(r"[_-]+", " ", stem).strip()


def _extract_pages(doc: Any, deadline: float) -> list[str]:
    pages: list[str] = []
    for index in range(min(doc.page_count, MAX_PAGES)):
        if time.monotonic() > deadline:
            raise _PdfTimeout(f"took longer than {PER_PDF_TIMEOUT_S:.0f}s")
        pages.append(doc[index].get_text("text", sort=True))
    return pages


def _extract_with_pdfplumber(data: bytes, deadline: float) -> list[str]:
    import io as _io

    import pdfplumber  # optional extra, imported where used (ADR 0026)

    pages: list[str] = []
    with pdfplumber.open(_io.BytesIO(data)) as doc:
        for index, page in enumerate(doc.pages):
            if index >= MAX_PAGES:
                break
            if time.monotonic() > deadline:
                raise _PdfTimeout(f"took longer than {PER_PDF_TIMEOUT_S:.0f}s")
            pages.append(page.extract_text() or "")
    return pages


def extract_one(member: str, data: bytes) -> PdfDocument:
    """Extract and score one PDF's bytes (also used to re-read a single member at plan time)."""
    if len(data) > MAX_PDF_MB * 1024 * 1024:
        return PdfDocument(
            member=member,
            quality="IMPORT_ERROR",
            quality_detail=f"larger than {MAX_PDF_MB} MB, not read",
        )
    import pymupdf  # optional extra, imported where used (ADR 0026)

    deadline = time.monotonic() + PER_PDF_TIMEOUT_S
    notes: list[str] = []
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any failure to open becomes IMPORT_ERROR, not a crash
        return PdfDocument(
            member=member, quality="IMPORT_ERROR", quality_detail=type(exc).__name__
        )
    try:
        if doc.needs_pass:
            return PdfDocument(member=member, quality="ENCRYPTED", quality_detail="password set")
        pages = _extract_pages(doc, deadline)
        meta_title = str(doc.metadata.get("title") or "") if doc.metadata else ""
        page_count = doc.page_count
    except _PdfTimeout as exc:
        return PdfDocument(member=member, quality="IMPORT_ERROR", quality_detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - a parse failure becomes IMPORT_ERROR, not a crash
        return PdfDocument(
            member=member, quality="IMPORT_ERROR", quality_detail=type(exc).__name__
        )
    finally:
        doc.close()
    chars = sum(len(p) for p in pages)
    if chars < MIN_CHARS_PER_PAGE and page_count > 0:
        # PyMuPDF found (almost) no text: likely scanned, worth one fallback try before giving up.
        try:
            pages = _extract_with_pdfplumber(data, deadline)
            notes.append("text extracted with pdfplumber (PyMuPDF found none)")
        except _PdfTimeout as exc:
            return PdfDocument(member=member, quality="IMPORT_ERROR", quality_detail=str(exc))
        except Exception:  # noqa: BLE001 - keep the (empty) PyMuPDF result rather than crash
            logger.info("%s: pdfplumber fallback failed too", member)
        chars = sum(len(p) for p in pages)
    text = _clean_text(pages)
    chars_per_page = chars / page_count if page_count else 0.0
    has_text_layer = chars_per_page >= MIN_CHARS_PER_PAGE
    if not has_text_layer:
        return PdfDocument(
            member=member,
            pages=page_count,
            chars=chars,
            chars_per_page=round(chars_per_page, 1),
            has_text_layer=False,
            quality="NO_TEXT",
            quality_detail=f"{chars_per_page:.0f} characters/page, probably scanned without OCR",
            notes=notes,
        )
    doi_match = _DOI.search(text[:4000])
    return PdfDocument(
        member=member,
        title=_guess_title(meta_title, text, member),
        doi=doi_match.group(0).rstrip(".,;)]}") if doi_match else "",
        text=text,
        pages=page_count,
        chars=chars,
        chars_per_page=round(chars_per_page, 1),
        has_text_layer=True,
        notes=notes,
    )


def extract_pdf_zip(path: Path) -> PdfZipResult:
    """Read every PDF in the ZIP at ``path`` (never extracted to disk).

    Raises:
        ImportFailed: E101 if the ZIP is damaged, E102 if it has no PDF entries at all.
    """
    try:
        import pymupdf  # noqa: F401 - fail fast with a clear message if the extra is missing
    except ImportError as exc:
        from crapai.errors import ConfigError  # only needed on this error path

        raise ConfigError(
            "Reading PDFs needs the package pymupdf",
            code="E203",
            hint='Install it with: pip install "crapai[import]".',
        ) from exc
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            pdf_infos = [info for info in infos if _is_pdf_member(info)]
            skipped = len(infos) - len(pdf_infos)
            if not pdf_infos:
                raise ImportFailed(
                    f"{path.name} has no PDF files in it",
                    code="E102",
                    hint="Check the ZIP; __MACOSX/ and non-PDF entries do not count.",
                    details={"path": str(path)},
                )
            documents = []
            for info in pdf_infos:
                data = archive.read(info)  # read only -- never .extract()/.extractall()
                documents.append(extract_one(info.filename, data))
    except zipfile.BadZipFile as exc:
        raise ImportFailed(
            f"{path.name} looks like a ZIP file but is damaged",
            code="E101",
            hint="Export or re-zip the file again.",
            details={"path": str(path)},
        ) from exc
    notes = [f"{skipped} non-PDF entr(ies) in the ZIP were skipped"] if skipped else []
    usable = sum(1 for d in documents if not d.quality)
    logger.info(
        "Read %d PDF(s) from %s (%d usable, %d skipped entries)",
        len(documents), path.name, usable, skipped,
    )  # fmt: skip
    return PdfZipResult(documents=documents, notes=notes)
