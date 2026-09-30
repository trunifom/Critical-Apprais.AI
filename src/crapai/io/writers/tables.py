"""Table writers: CSV and XLSX for people who open the data in Excel (plan chapters 8.8 and 25.8).

``records.csv`` itself stays the canonical, byte-stable table. The files written here are
*exports* meant for a spreadsheet, so they differ in three ways:

* CSV gets a UTF-8 byte-order mark (Excel then reads umlauts correctly) and a separator the user
  can choose (``;`` for Excel in German locales);
* text that a spreadsheet would run as a formula (a cell starting with ``=``, ``+``, ``-``, ``@``,
  tab or carriage return) is written as text, so a hostile title such as ``=HYPERLINK(...)``
  cannot execute when the export is opened ("CSV injection");
* XLSX cells get no control characters (Excel cannot hold them) and the header is frozen.

Both writers write atomically and return the file that holds the content: a locked target (open in
Excel) gives a timestamped alternative next to it (see :mod:`crapai.project.atomic`).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from crapai.errors import ConfigError
from crapai.project.atomic import WriteResult, atomic_write_bytes

logger = logging.getLogger(__name__)

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
# Excel and XML cannot hold these control characters (tab, LF and CR are fine).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
XLSX_MAX_CELL_CHARS = 32_767  # Excel's limit for the text of one cell


def neutralise_formula(value: str) -> str:
    """Return ``value`` with a leading apostrophe if a spreadsheet would run it as a formula.

    A number such as ``-5`` or ``+3`` is text here too; the apostrophe keeps it a string, which is
    the safe choice for bibliographic data (titles and notes, never calculations).
    """
    return "'" + value if value.startswith(_FORMULA_START) else value


def write_csv(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    delimiter: str = ",",
    guard_formulas: bool = True,
) -> WriteResult:
    """Write a CSV file for Excel: UTF-8 with BOM, CRLF line ends, fields quoted where needed.

    Args:
        path: Target file (the folder must exist).
        header: Column names.
        rows: Data rows (text cells).
        delimiter: One character; ``;`` suits Excel with a German locale.
        guard_formulas: Neutralise cells that start like a formula (default).

    Raises:
        ConfigError: (E203) if ``delimiter`` is not exactly one character.
        StorageError: (E401/E403) from the atomic write.
    """
    if len(delimiter) != 1:
        raise ConfigError(
            f"The CSV separator must be one character, got '{delimiter}'",
            code="E203",
            hint="Use , or ; for example.",
        )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow([neutralise_formula(cell) if guard_formulas else cell for cell in row])
        count += 1
    logger.info("Writing %d row(s) to %s", count, path.name)
    return atomic_write_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def write_xlsx(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    sheet: str = "records",
    guard_formulas: bool = True,
) -> WriteResult:
    """Write an XLSX workbook with one sheet; the header row is bold, frozen and filterable.

    Raises:
        ConfigError: (E203) if the optional package ``openpyxl`` is not installed.
        StorageError: (E401/E403) from the atomic write.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:
        raise ConfigError(
            "Writing XLSX needs the package openpyxl",
            code="E203",
            hint='Install it with: pip install "crapai[import]", or export as CSV.',
        ) from exc

    def clean(cell: str) -> str:
        text = _CONTROL.sub("", cell)[:XLSX_MAX_CELL_CHARS]
        return neutralise_formula(text) if guard_formulas else text

    workbook = Workbook(write_only=False)
    worksheet = workbook.active
    worksheet.title = sheet[:31]  # Excel limits sheet names to 31 characters
    worksheet.append([clean(name) for name in header])
    count = 0
    for row in rows:
        worksheet.append([clean(cell) for cell in row])
        count += 1
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    buffer = io.BytesIO()
    workbook.save(buffer)
    logger.info("Writing %d row(s) to %s", count, path.name)
    return atomic_write_bytes(path, buffer.getvalue())
