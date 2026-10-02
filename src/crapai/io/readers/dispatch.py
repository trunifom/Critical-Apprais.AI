"""Read any supported import file: detect the format, then call the matching reader.

This is the single entry point the import service uses, so the format decision (content first,
extension second, plan chapter 25.1) lives in one place. A ZIP is handled one level up, in
:mod:`crapai.services.importing`: a ZIP of PDFs (ADR 0026) is matched against the project's
*existing* records, which this function has no access to (it only ever sees one file in
isolation), so it never reaches here. A bare, single PDF file is recognised but refused: only a
ZIP of PDFs is a supported way to bring in full text (ADR 0026).
"""

from __future__ import annotations

import logging
from pathlib import Path

from crapai.errors import ImportFailed
from crapai.io.readers.base import ReadResult
from crapai.io.readers.bibtex import read_bibtex
from crapai.io.readers.detect import DetectionResult, SourceFormat, detect_format
from crapai.io.readers.nbib import read_nbib
from crapai.io.readers.ris import read_ris
from crapai.io.readers.tabular import read_table

logger = logging.getLogger(__name__)


def read_source(
    path: Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    sheet: str | None = None,
    mapping: dict[str, str] | None = None,
) -> tuple[ReadResult, DetectionResult]:
    """Detect the format of ``path`` and read it.

    Args:
        path: The export file.
        encoding: Force a text encoding (``--encoding``).
        delimiter: Force the CSV/TSV separator.
        sheet: Worksheet name for XLSX (``--sheet``).
        mapping: Explicit column mapping for tables (``--map abstract=<column>``).

    Returns:
        ``(result, detection)``; ``detection.reason`` explains the format decision and
        ``detection.extension_mismatch`` tells the caller to show it.

    Raises:
        ImportFailed: E101 (unknown format, or a bare PDF file -- zip it to import full text),
            E102 (no records), E103 (undecodable), E104 (column not found).
    """
    detection = detect_format(path)
    fmt = detection.format
    if fmt is SourceFormat.PDF:
        raise ImportFailed(
            f"{path.name}: a single PDF file cannot be imported directly",
            code="E101",
            hint="Put PDFs in a ZIP archive and import that (ADR 0026), "
            "or import a bibliographic export (RIS, NBIB, BibTeX, CSV or XLSX).",
            details={"path": str(path), "detected": fmt.value},
        )
    if fmt is SourceFormat.ZIP:
        # services.importing intercepts a ZIP before calling read_source (it needs the project's
        # existing records to match PDFs against, which this function does not have); a direct
        # call here (or a ZIP that is not actually a PDF archive) is refused, not mis-read as a
        # table.
        raise ImportFailed(
            f"{path.name}: a ZIP archive is only supported as a ZIP of PDFs via 'crapai import'",
            code="E101",
            hint="Check that the ZIP contains PDF files, or import a bibliographic export.",
            details={"path": str(path), "detected": fmt.value},
        )
    if fmt is SourceFormat.RIS:
        result = read_ris(path, encoding=encoding)
    elif fmt is SourceFormat.NBIB:
        result = read_nbib(path, encoding=encoding)
    elif fmt is SourceFormat.BIBTEX:
        result = read_bibtex(path, encoding=encoding)
    else:
        result = read_table(
            path, encoding=encoding, delimiter=delimiter, sheet=sheet, mapping=mapping
        )
    if encoding is None and result.encoding not in (None, "utf-8", "utf-8-sig", "utf-16"):
        # The file is not valid UTF-8, so a legacy code page was guessed. Accented letters are
        # only right if the guess is right, hence a visible note (and --encoding to override).
        note = (
            f"the file is not valid UTF-8; it was decoded as {result.encoding} "
            "(use --encoding if accented letters look wrong)"
        )
        result.notes.insert(0, note)
        logger.warning("%s: %s", path.name, note)
    logger.info("%s: %s (%s)", path.name, result.format.value, detection.reason)
    return result, detection
