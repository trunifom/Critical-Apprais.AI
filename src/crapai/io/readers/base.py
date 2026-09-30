"""Shared types and helpers of all import readers (plan chapters 25 and 26.1).

A reader turns one file into a :class:`ReadResult`: a list of :class:`RawRecord` whose ``fields``
use the internal column names of ``records.csv`` (chapter 26.1). Identity (``study_uid``), source
label, DOI/author normalisation and the CSV layout are added afterwards by ``io.normalize`` and
``io.records_store`` (task T-M1-10). Readers never drop data: everything that has no internal
column goes to ``extra`` and ends up in ``extra_json``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crapai.errors import ImportFailed
from crapai.io.readers.detect import ENCODING_CHAIN, SourceFormat

logger = logging.getLogger(__name__)


@dataclass
class RawRecord:
    """One bibliographic record as read from a source file.

    Attributes:
        source_row: 1-based position of the record in the file (record number, not line number).
        fields: Values by internal column name (``title``, ``abstract``, ``authors`` ...).
            Absent or empty values are simply missing; no placeholder values are ever invented.
        extra: Everything without an internal column, keyed by source tag (for example
            ``ris_C1``). Values are strings or lists of strings.
        notes: Import remarks for this record (for example "record not terminated by ER").
    """

    source_row: int
    fields: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ReadResult:
    """Everything a reader found in one file.

    Attributes:
        format: The format that was read.
        records: The records in file order.
        encoding: Text encoding used to decode the file (None for binary formats).
        notes: File-level remarks (discarded header lines, replaced characters ...).
        column_map: For table readers: internal column -> source column header that was used.
            Stored in ``project.yaml`` (``import.mappings``) so an import can be repeated.
        options: Reader settings that were applied (delimiter, sheet name ...), for the import log.
    """

    format: SourceFormat
    records: list[RawRecord]
    encoding: str | None = None
    notes: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


def decode_text(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    """Decode a whole file and normalise line endings to ``\\n``.

    Without ``encoding`` the chain of plan chapter 25.9 is used (``utf-8-sig``, ``utf-8``,
    ``cp1252``, ``latin-1``). With an explicit ``encoding`` (the ``--encoding`` option) decoding
    is strict.

    Returns:
        ``(text, encoding_used)``.

    Raises:
        ImportFailed: (E103) if an explicitly requested encoding cannot decode the file or is
            unknown.
    """
    if encoding is not None:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            raise ImportFailed(
                f"The file cannot be decoded as {encoding}",
                code="E103",
                hint="Try another encoding, for example --encoding cp1252.",
                details={"encoding": encoding},
            ) from exc
        return _normalise_newlines(text), encoding
    for candidate in ENCODING_CHAIN:
        try:
            return _normalise_newlines(data.decode(candidate)), candidate
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodes every byte sequence")  # pragma: no cover


def read_text_file(path: Path, encoding: str | None = None) -> tuple[str, str]:
    """Read ``path`` and decode it with :func:`decode_text`.

    Raises:
        ImportFailed: (E103) for an undecodable file with an explicit encoding, (E101) if the
            file cannot be opened.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImportFailed(
            f"{path.name} cannot be read ({type(exc).__name__})",
            code="E101",
            hint="Check that the file exists and is not open in another program.",
            details={"path": str(path)},
        ) from exc
    text, used = decode_text(data, encoding)
    logger.info("Read %s as %s (%d characters)", path.name, used, len(text))
    return text, used


def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def join_values(values: list[str]) -> str:
    """Join list values into the ``"a; b"`` form used by ``authors`` and ``keywords``."""
    return "; ".join(value for value in values if value)


def unique_in_order(values: list[str]) -> list[str]:
    """Remove duplicates but keep the order of first appearance."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
