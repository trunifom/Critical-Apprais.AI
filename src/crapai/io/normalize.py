"""Normalisation helpers for imported bibliographic values (plan chapter 8.3).

Small pure functions, each with one job, so they are easy to test and to reuse in the dedup step.
Nothing here invents data: an unusable value becomes an empty string or ``None``, never a
placeholder (the predecessor used the year 1900).
"""

from __future__ import annotations

import html
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crapai.io.readers.base import RawRecord, ReadResult
from crapai.io.records_store import RECORD_TYPES, Record

# Control characters that Excel/XML cannot hold: 0x00-0x08, 0x0b, 0x0c, 0x0e-0x1f (plan 25.9).
# Tab (0x09), LF (0x0a) and CR (0x0d) are white space and handled separately.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{1,31});")
_DOI_PREFIX = re.compile(
    r"^(?:https?://)?(?:dx\.)?doi\.org/|^doi\s*:\s*|^https?://dx\.doi\.org/", re.IGNORECASE
)
_DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")
_YEAR = re.compile(r"\b(1[4-9]\d{2}|20\d{2}|2100)\b")
_TRAILING_DOI_PUNCTUATION = ".,;)]}>\"'"


def clean_text(value: str, *, single_line: bool = True) -> str:
    """Return ``value`` in Unicode NFC with control characters removed and white space tidied.

    Args:
        value: Raw text from a source file.
        single_line: If True (default) every run of white space, including line breaks, becomes
            one space; this is the rule for abstracts and titles (plan chapter 25.7). If False
            only the ends are stripped and line breaks are kept.
    """
    if not value:
        return ""
    text = html.unescape(value) if _ENTITY.search(value) else value
    # Order matters: entities such as &#1; can produce control characters, and removing controls
    # can leave a base letter next to a combining mark, so NFC comes last.
    text = unicodedata.normalize("NFC", _CONTROL.sub("", text))
    if single_line:
        return _WHITESPACE.sub(" ", text).strip()
    return text.strip()


def normalize_doi(value: str) -> str | None:
    """Normalise a DOI: lower case, no ``https://doi.org/`` or ``doi:`` prefix, no spaces.

    Returns:
        The DOI (``10.xxxx/...``), or ``None`` if the value does not have the shape of a DOI
        (the caller keeps the original in ``extra_json``).
    """
    text = clean_text(value)
    if not text:
        return None
    text = _DOI_PREFIX.sub("", text).replace(" ", "").lower()
    text = text.rstrip(_TRAILING_DOI_PUNCTUATION)
    return text if _DOI_SHAPE.match(text) else None


def coerce_year(value: object) -> int | None:
    """Return the first plausible year (1400 to 2100) found in ``value``, else ``None``."""
    if value is None or isinstance(value, bool):
        return None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def normalize_list(value: str, *, separator: str = ";") -> str:
    """Tidy a ``"A; B; C"`` list: trim entries, drop empty ones and exact duplicates."""
    if not value:
        return ""
    seen: dict[str, None] = {}
    for part in value.split(separator):
        entry = clean_text(part)
        if entry:
            seen.setdefault(entry, None)
    return "; ".join(seen)


# --- from a reader's RawRecord to a records.csv Record ---------------------------------------

# Columns that hold plain single-line text. ``authors``-like lists are handled separately.
_TEXT_COLUMNS = (
    "title",
    "abstract",
    "abstract_source",
    "abstract_quality",
    "journal",
    "volume",
    "issue",
    "pages",
    "pmid",
    "pmcid",
    "accession_number",
    "issn_isbn",
    "url",
    "language",
)
_LIST_COLUMNS = ("authors", "editors", "keywords", "keywords_mesh", "publication_types")
# ReadResult formats -> the source_format values of records.csv (plan chapter 26.1).
SOURCE_FORMAT_NAMES = {
    "ris": "ris",
    "nbib": "nbib",
    "bibtex": "bib",
    "csv": "csv",
    "tsv": "csv",
    "xlsx": "xlsx",
    "pdf": "pdf",
}


@dataclass(frozen=True)
class ImportContext:
    """Facts about the source file that every record of one import shares.

    Attributes:
        source_label: The user's name for the source, for example ``PubMed``.
        source_file: File name below ``sources/``.
        source_format: A :class:`~crapai.io.readers.detect.SourceFormat` value, for example
            ``bibtex``; it is translated to the ``records.csv`` name (``bib``).
        new_uid: Factory for ``study_uid`` values (UUID4 by default; injectable for tests).
    """

    source_label: str
    source_file: str
    source_format: str
    new_uid: Callable[[], str] = field(default=lambda: str(uuid.uuid4()))


def to_record(raw: RawRecord, context: ImportContext) -> Record:
    """Turn a reader's :class:`RawRecord` into a normalised :class:`Record`.

    Rules (plan chapters 8.3, 25 and 26): text is cleaned (NFC, control characters, white space,
    HTML entities), the DOI is normalised (an invalid one is kept in ``extra_json`` as
    ``doi_invalid``), lists are tidied, the year is coerced without placeholders, and a record
    with neither title nor abstract is marked ``EMPTY_RECORD``. Every field without a column in
    ``records.csv`` (for example ``notes``) and every reader ``extra`` entry goes to
    ``extra_json``, so nothing is lost. The record gets a new ``study_uid``.
    """
    fields = dict(raw.fields)
    extra: dict[str, Any] = {}
    values: dict[str, Any] = {}

    for column in _TEXT_COLUMNS:
        values[column] = clean_text(str(fields.pop(column, "") or ""))
    for column in _LIST_COLUMNS:
        values[column] = normalize_list(str(fields.pop(column, "") or ""))
    values["year"] = coerce_year(fields.pop("year", None))

    raw_doi = clean_text(str(fields.pop("doi", "") or ""))
    doi = normalize_doi(raw_doi)
    values["doi"] = doi or ""
    if raw_doi and doi is None:
        extra["doi_invalid"] = raw_doi

    record_type = str(fields.pop("record_type", "") or "other")
    if record_type not in RECORD_TYPES:
        extra["record_type_raw"] = record_type
        record_type = "other"
    values["record_type"] = record_type
    values["is_retracted"] = bool(fields.pop("is_retracted", False))

    # What is left has no column in records.csv: keep it, cleaned, in extra_json.
    for name, value in fields.items():
        extra[name] = clean_text(value, single_line=False) if isinstance(value, str) else value
    extra.update(raw.extra)
    values["extra_json"] = extra

    values["has_abstract"] = bool(values["abstract"])
    if not values["title"] and not values["abstract"]:
        values["exclusion_reason"] = "EMPTY_RECORD"
        values["exclusion_details"] = "neither title nor abstract"
    values["import_notes"] = "; ".join(note for note in raw.notes if note)

    return Record(
        study_uid=context.new_uid(),
        source_label=context.source_label,
        source_file=context.source_file,
        source_row=raw.source_row,
        source_format=SOURCE_FORMAT_NAMES.get(context.source_format, context.source_format),
        **values,
    )


def to_records(result: ReadResult, context: ImportContext) -> list[Record]:
    """Normalise all records of one file, in file order."""
    return [to_record(raw, context) for raw in result.records]
