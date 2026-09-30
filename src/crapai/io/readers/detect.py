"""Detect the format of an import file by its content first and its extension second.

Plan chapter 25.1: the file extension is not a reliable feature (``pubmed-adhd-set.ris`` is a
MEDLINE/NBIB export, ``example_AB_nr4.txt`` is RIS). The result carries the format, a confidence
between 0 and 1 and a human-readable reason that the preflight shows to the user, for example
"content is a MEDLINE export, read as NBIB although the extension says .ris".

Only the first :data:`SNIFF_BYTES` of a file are examined, so detection is fast on large files.
"""

from __future__ import annotations

import codecs
import csv
import io
import logging
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from crapai.enums import StringEnum
from crapai.errors import ImportFailed

logger = logging.getLogger(__name__)

SNIFF_BYTES = 64 * 1024

# Text encodings tried in this order (plan chapter 25.9). latin-1 never fails, so it ends the chain.
ENCODING_CHAIN = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class SourceFormat(StringEnum):
    """Import formats known to the readers. The values are stored in the import log."""

    RIS = "ris"
    NBIB = "nbib"
    BIBTEX = "bibtex"
    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    ZIP = "zip"
    PDF = "pdf"


EXTENSION_FORMATS: dict[str, SourceFormat] = {
    ".ris": SourceFormat.RIS,
    ".nbib": SourceFormat.NBIB,
    ".bib": SourceFormat.BIBTEX,
    ".bibtex": SourceFormat.BIBTEX,
    ".csv": SourceFormat.CSV,
    ".tsv": SourceFormat.TSV,
    ".xlsx": SourceFormat.XLSX,
    ".zip": SourceFormat.ZIP,
    ".pdf": SourceFormat.PDF,
}

# Content signatures. RIS tags are "XX  - " (two characters, two spaces, dash); Cochrane writes
# two spaces after the dash. MEDLINE/NBIB starts every record with "PMID- ".
# The RIS parser accepts one or two spaces before the dash, so the sniffer does too.
_RIS_TYPE = re.compile(r"^TY {1,2}- +\S", re.MULTILINE)
_RIS_TAG = re.compile(r"^[A-Z][A-Z0-9] {1,2}- ", re.MULTILINE)
_NBIB_PMID = re.compile(r"^PMID- +\d", re.MULTILINE)
_BIBTEX_ENTRY = re.compile(r"^\s*@[A-Za-z]+\s*[{(]", re.MULTILINE)

# Candidate field separators for tables, in order of preference when several fit equally well.
DELIMITERS = (",", ";", "\t", "|")
MAX_SNIFF_ROWS = 50
MIN_ROW_AGREEMENT = 0.8

OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # legacy .xls


@dataclass(frozen=True)
class DetectionResult:
    """What was found out about an import file.

    Attributes:
        format: The detected format.
        confidence: 0 to 1; below 0.5 the decision rests on the extension alone.
        reason: Short English explanation, suitable for the preflight message.
        extension_mismatch: True if the extension names a different format than the content.
        encoding: Text encoding used for sniffing (None for binary formats).
        delimiter: Field separator for CSV/TSV, else None.
    """

    format: SourceFormat
    confidence: float
    reason: str
    extension_mismatch: bool = False
    encoding: str | None = None
    delimiter: str | None = None


def decode_head(head: bytes, *, truncated: bool) -> tuple[str, str]:
    """Decode sniffed bytes with the encoding chain; returns ``(text, encoding)``.

    A multi-byte character cut in half at the end of a truncated sample does not count as an error.
    """
    if truncated:
        # Drop an incomplete UTF-8 sequence at the cut so a valid UTF-8 file is not misjudged.
        for cut in range(4):
            candidate = head[: len(head) - cut] if cut else head
            try:
                return candidate.decode("utf-8-sig"), "utf-8-sig"
            except UnicodeDecodeError:
                continue
    for encoding in ENCODING_CHAIN:
        try:
            return head.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodes every byte sequence")  # pragma: no cover


def _extension_format(path: Path) -> SourceFormat | None:
    return EXTENSION_FORMATS.get(path.suffix.lower())


def _binary_format(path: Path, head: bytes) -> tuple[SourceFormat, str] | None:
    """Recognise PDF, ZIP/XLSX by magic bytes; raise for legacy .xls."""
    if head.startswith(b"%PDF-"):
        return SourceFormat.PDF, "content starts with the PDF signature"
    if head.startswith(OLE_MAGIC):
        raise ImportFailed(
            f"{path.name} is a legacy Excel file (.xls), which is not supported",
            code="E101",
            hint="Save the file as .xlsx or .csv in Excel and import that.",
            details={"path": str(path)},
        )
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            raise ImportFailed(
                f"{path.name} looks like a ZIP file but is damaged",
                code="E101",
                hint="Export the file again.",
                details={"path": str(path)},
            ) from None
        if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
            return SourceFormat.XLSX, "ZIP container with Excel workbook parts"
        return SourceFormat.ZIP, "ZIP archive"
    return None


def _sniff_bibliographic(text: str) -> tuple[SourceFormat, float, str] | None:
    """Tell RIS, NBIB and BibTeX apart from the text of the file head."""
    ris_type = _RIS_TYPE.search(text)
    nbib = _NBIB_PMID.search(text)
    if nbib and not ris_type:
        return SourceFormat.NBIB, 0.95, "content has MEDLINE 'PMID-' records"
    if ris_type and not nbib:
        return SourceFormat.RIS, 0.95, "content has RIS 'TY  -' records"
    if ris_type and nbib:
        # Both markers: whichever record style comes first decides, with less confidence.
        if nbib.start() < ris_type.start():
            return SourceFormat.NBIB, 0.6, "MEDLINE 'PMID-' comes before any RIS 'TY  -'"
        return SourceFormat.RIS, 0.6, "RIS 'TY  -' comes before any MEDLINE 'PMID-'"
    if _BIBTEX_ENTRY.search(text):
        return SourceFormat.BIBTEX, 0.95, "content has BibTeX '@type{' entries"
    if len(_RIS_TAG.findall(text)) >= 3:
        return SourceFormat.RIS, 0.5, "content has several 'XX  - ' tag lines but no 'TY' line"
    return None


def _sniff_delimited(text: str, *, truncated: bool) -> tuple[str, int, int] | None:
    """Find the field separator of a table sample.

    A separator fits when at least two rows exist, the most common row has two or more fields
    and at least 80 % of the rows have that same number of fields (quoted values with the
    separator inside do not disturb this because ``csv.reader`` honours quotes).

    Returns:
        ``(delimiter, fields_per_row, rows_examined)`` for the best fit, or None.
    """
    best: tuple[str, int, int] | None = None
    for delimiter in DELIMITERS:
        try:
            rows = [
                row
                for row in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any(cell.strip() for cell in row)
            ]
        except csv.Error:
            continue
        if truncated and rows:
            rows = rows[:-1]  # the last row may be cut off by the sample limit
        rows = rows[:MAX_SNIFF_ROWS]
        if len(rows) < 2:
            continue
        width, count = Counter(len(row) for row in rows).most_common(1)[0]
        if width < 2 or count / len(rows) < MIN_ROW_AGREEMENT:
            continue
        if best is None or width > best[1]:
            best = (delimiter, width, len(rows))
    return best


def detect_format(path: Path) -> DetectionResult:
    """Detect the format of ``path`` (content first, extension second).

    Raises:
        ImportFailed: (E102) for an empty file; (E101) if the file cannot be opened, the format is
            unknown, the file is a legacy ``.xls`` or a damaged ZIP.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(SNIFF_BYTES + 1)
    except OSError as exc:
        raise ImportFailed(
            f"{path.name} cannot be read ({type(exc).__name__})",
            code="E101",
            hint="Check that the file exists and is not open in another program.",
            details={"path": str(path)},
        ) from exc
    if not head.strip():
        raise ImportFailed(
            f"{path.name} is empty",
            code="E102",
            hint="Export the search results again.",
            details={"path": str(path)},
        )
    truncated = len(head) > SNIFF_BYTES
    head = head[:SNIFF_BYTES]
    by_extension = _extension_format(path)

    binary = _binary_format(path, head)
    if binary is not None:
        found, reason = binary
        return _finish(path, DetectionResult(found, 0.99, reason), by_extension)

    utf16 = head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    if b"\x00" in head and not utf16:
        raise ImportFailed(
            f"{path.name} is a binary file of an unknown type",
            code="E101",
            hint="Export as RIS, NBIB, BibTeX, CSV or XLSX.",
            details={"path": str(path)},
        )
    if utf16:
        text, encoding = (
            head[: len(head) - len(head) % 2].decode("utf-16", errors="replace"),
            "utf-16",
        )
    else:
        text, encoding = decode_head(head, truncated=truncated)

    sniffed = _sniff_bibliographic(text)
    if sniffed is not None:
        found, confidence, reason = sniffed
        return _finish(
            path, DetectionResult(found, confidence, reason, encoding=encoding), by_extension
        )

    table = _sniff_delimited(text, truncated=truncated)
    if table is not None:
        delimiter, width, rows = table
        found = SourceFormat.TSV if delimiter == "\t" else SourceFormat.CSV
        agrees = by_extension == found
        confidence = 0.9 if agrees else (0.8 if rows >= 5 else 0.6)
        name = "tab" if delimiter == "\t" else repr(delimiter)
        reason = f"content is a table with {width} columns separated by {name}"
        return _finish(
            path,
            DetectionResult(found, confidence, reason, encoding=encoding, delimiter=delimiter),
            by_extension,
        )

    if by_extension in (
        SourceFormat.RIS,
        SourceFormat.NBIB,
        SourceFormat.BIBTEX,
        SourceFormat.CSV,
        SourceFormat.TSV,
    ):
        # A table with a single column (only titles) or a first row cut off inside a quoted field
        # shows no separator; the extension decides, and --map can still name the columns.
        return DetectionResult(
            by_extension,
            0.3,
            f"content is not conclusive; taking the extension {path.suffix.lower()}",
            encoding=encoding,
            delimiter="\t" if by_extension == SourceFormat.TSV else None,
        )
    raise ImportFailed(
        f"The type of {path.name} was not recognised",
        code="E101",
        hint="Export the search results again as RIS, NBIB, BibTeX, CSV or XLSX.",
        details={"path": str(path)},
    )


def _finish(
    path: Path, result: DetectionResult, by_extension: SourceFormat | None
) -> DetectionResult:
    """Flag a disagreement between content and extension and extend the reason."""
    if by_extension is None or by_extension == result.format:
        return result
    suffix = path.suffix.lower()
    reason = f"{result.reason}; read as {result.format.value} although the extension says {suffix}"
    logger.info("%s: %s", path.name, reason)
    return DetectionResult(
        result.format,
        result.confidence,
        reason,
        extension_mismatch=True,
        encoding=result.encoding,
        delimiter=result.delimiter,
    )
