"""Read any supported import file: detect the format, then call the matching reader.

This is the single entry point the import service uses, so the format decision (content first,
extension second, plan chapter 25.1) lives in one place. PDF and ZIP files are recognised but
refused: full-text screening is not part of version 1 (ADR 0015).
"""

from __future__ import annotations

import logging
from pathlib import Path

from saralocal.errors import ImportFailed
from saralocal.io.readers.base import ReadResult
from saralocal.io.readers.bibtex import read_bibtex
from saralocal.io.readers.detect import DetectionResult, SourceFormat, detect_format
from saralocal.io.readers.nbib import read_nbib
from saralocal.io.readers.ris import read_ris
from saralocal.io.readers.tabular import read_table

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
        ImportFailed: E101 (unknown format, or PDF/ZIP which v1 does not import), E102 (no
            records), E103 (undecodable), E104 (column not found).
    """
    detection = detect_format(path)
    fmt = detection.format
    if fmt in (SourceFormat.PDF, SourceFormat.ZIP):
        raise ImportFailed(
            f"{path.name}: importing PDF files or ZIP archives is not part of version 1",
            code="E101",
            hint="Import a bibliographic export (RIS, NBIB, BibTeX, CSV or XLSX).",
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
    logger.info("%s: %s (%s)", path.name, result.format.value, detection.reason)
    return result, detection
