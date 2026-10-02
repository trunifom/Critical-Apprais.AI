"""The ``data/records.csv`` file: model, writer and reader (plan chapters 7, 25.7 and 26.1).

``records.csv`` is the single source of truth for all records. The format is fixed by the plan:
RFC 4180, UTF-8 without BOM, ``\\n`` line ends, comma separator, minimal quoting, empty value =
null, booleans ``true``/``false``, lists separated by ``"; "`` and the rest of the source fields
as compact JSON in ``extra_json``. The column order below is a data contract (chapter 26.1).

Writing is atomic (temp file + ``os.replace``) and, before an existing file is replaced, a copy is
kept in ``data/.backup/`` (the newest five are retained, chapter 28.9).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from crapai.errors import StorageError
from crapai.project.atomic import atomic_write

logger = logging.getLogger(__name__)

RECORD_COLUMNS: tuple[str, ...] = (
    "study_uid",
    "source_label",
    "source_file",
    "source_row",
    "source_format",
    "record_type",
    "title",
    "abstract",
    "abstract_source",
    "abstract_quality",
    "authors",
    "editors",
    "year",
    "journal",
    "volume",
    "issue",
    "pages",
    "doi",
    "pmid",
    "pmcid",
    "accession_number",
    "issn_isbn",
    "url",
    "language",
    "keywords",
    "keywords_mesh",
    "publication_types",
    "is_retracted",
    "is_duplicate",
    "duplicate_of",
    "dedup_method",
    "has_abstract",
    "exclusion_reason",
    "exclusion_details",
    "has_fulltext",
    "fulltext_path",
    "fulltext_of",
    "zip_member",
    "import_notes",
    "extra_json",
)
BOOLEAN_COLUMNS = frozenset({"is_retracted", "is_duplicate", "has_abstract", "has_fulltext"})
INTEGER_COLUMNS = frozenset({"source_row", "year"})

SOURCE_FORMATS = frozenset({"ris", "bib", "nbib", "csv", "xlsx", "pdf"})
RECORD_TYPES = frozenset(
    {
        "journal_article",
        "conference_paper",
        "book",
        "book_chapter",
        "report",
        "thesis",
        "preprint",
        "web",
        "dataset",
        "trial_registry",
        "other",
    }
)
EXCLUSION_REASONS = frozenset(
    {
        "",
        "DUPLICATE",
        "NO_ABSTRACT",
        "NO_TEXT",
        "ENCRYPTED",
        "EMPTY_RECORD",
        "NOT_SCREENABLE",
        "IMPORT_ERROR",
        "RETRACTED",
        "PREFILTER_LANGUAGE",
        "PREFILTER_YEAR",
        "PREFILTER_TYPE",
        "PREFILTER_KEYWORD",
        "AI_PREFILTER_JEV",
    }
)

BACKUP_KEEP = 5


class Record(BaseModel):
    """One row of ``records.csv``. Empty strings stand for "no value"."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    study_uid: str = Field(min_length=1)
    source_label: str
    source_file: str
    source_row: int = Field(ge=1)
    source_format: str
    record_type: str = "other"
    title: str = ""
    abstract: str = ""
    abstract_source: str = ""
    abstract_quality: str = ""
    authors: str = ""
    editors: str = ""
    year: int | None = None
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    accession_number: str = ""
    issn_isbn: str = ""
    url: str = ""
    language: str = ""
    keywords: str = ""
    keywords_mesh: str = ""
    publication_types: str = ""
    is_retracted: bool = False
    is_duplicate: bool = False
    duplicate_of: str = ""
    dedup_method: str = ""
    has_abstract: bool = False
    exclusion_reason: str = ""
    exclusion_details: str = ""
    has_fulltext: bool = False
    fulltext_path: str = ""
    fulltext_of: str = ""
    zip_member: str = ""
    import_notes: str = ""
    extra_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_format")
    @classmethod
    def _known_source_format(cls, value: str) -> str:
        if value not in SOURCE_FORMATS:
            raise ValueError(f"source_format must be one of {sorted(SOURCE_FORMATS)}")
        return value

    @field_validator("record_type")
    @classmethod
    def _known_record_type(cls, value: str) -> str:
        if value not in RECORD_TYPES:
            raise ValueError(f"record_type must be one of {sorted(RECORD_TYPES)}")
        return value

    @field_validator("exclusion_reason")
    @classmethod
    def _known_exclusion_reason(cls, value: str) -> str:
        if value not in EXCLUSION_REASONS:
            raise ValueError("exclusion_reason is not in the catalogue (plan chapter 26.3)")
        return value

    def to_row(self) -> list[str]:
        """The record as CSV cells in :data:`RECORD_COLUMNS` order."""
        return [_cell(name, getattr(self, name)) for name in RECORD_COLUMNS]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Record:
        """Build a record from the cells of one CSV row (keys are the column names)."""
        values: dict[str, Any] = {}
        for name in RECORD_COLUMNS:
            text = row.get(name, "")
            if name in BOOLEAN_COLUMNS:
                values[name] = _parse_bool(name, text)
            elif name in INTEGER_COLUMNS:
                values[name] = int(text) if text != "" else None
            elif name == "extra_json":
                values[name] = json.loads(text) if text else {}
            else:
                values[name] = text
        return cls.model_validate(values)


def _cell(name: str, value: Any) -> str:
    if name in BOOLEAN_COLUMNS:
        return "true" if value else "false"
    if name == "extra_json":
        if not value:
            return ""
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


def _parse_bool(name: str, text: str) -> bool:
    if text in ("true", "false"):
        return text == "true"
    if text == "":
        return False
    raise ValueError(f"{name} must be 'true' or 'false', got {text!r}")


# --- writing -------------------------------------------------------------------------------


def _write_rows(handle: BinaryIO, records: Iterable[Record]) -> None:
    text = io.TextIOWrapper(handle, encoding="utf-8", newline="", write_through=True)
    try:
        writer = csv.writer(text, delimiter=",", quotechar='"', lineterminator="\n")
        writer.writerow(RECORD_COLUMNS)
        for record in records:
            writer.writerow(record.to_row())
        text.flush()
    finally:
        text.detach()  # the atomic writer owns (and closes) the underlying file


def backup_records(
    path: Path, backup_dir: Path, *, now: datetime, keep: int = BACKUP_KEEP
) -> Path | None:
    """Copy ``path`` to ``backup_dir/records.<timestamp>.csv`` and keep the newest ``keep`` copies.

    Returns:
        The backup path, or None if ``path`` does not exist yet.
    """
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    content = path.read_bytes()
    existing = sorted(backup_dir.glob("records.*.csv"))
    if existing and existing[-1].read_bytes() == content:
        # Retrying a write that failed (file open in Excel) must not push real history out of
        # the five kept copies with identical ones.
        return existing[-1]
    target = backup_dir / f"records.{now.strftime('%Y%m%d-%H%M%S-%f')}.csv"
    target.write_bytes(content)
    backups = sorted(backup_dir.glob("records.*.csv"))
    for old in backups[:-keep] if keep > 0 else backups:
        old.unlink()
    return target


def write_records(
    path: Path,
    records: Iterable[Record],
    *,
    backup_dir: Path | None = None,
    now: datetime | None = None,
    allow_alternative: bool = False,
) -> Path:
    """Write ``records`` to ``path`` atomically; back up an existing file first.

    ``records.csv`` is the one canonical table, so by default a locked file (for example open
    in Excel) is an **error** and no side file is left behind: a copy under another name would
    leave the project without the new records while the import log claims success.

    Args:
        allow_alternative: Accept the timestamped alternative file of the atomic writer when the
            target is locked (for derived exports, never for ``records.csv``).

    Returns:
        The path that was written.

    Raises:
        StorageError: E401 if the file is locked (and ``allow_alternative`` is off), E401/E403
            for other write problems.
    """
    materialised = list(records)
    if backup_dir is not None:
        backup_records(path, backup_dir, now=now or datetime.now())
    result = atomic_write(path, lambda handle: _write_rows(handle, materialised))
    if result.used_alternative and not allow_alternative:
        result.path.unlink(missing_ok=True)
        raise StorageError(
            f"{path.name} is locked (open in another program); nothing was changed",
            code="E401",
            hint="Close the file in Excel or another program and try again.",
            details={"path": str(path)},
        )
    logger.info("Wrote %d record(s) to %s", len(materialised), result.path.name)
    return result.path


# --- reading -------------------------------------------------------------------------------


def read_records(path: Path) -> list[Record]:
    """Read ``records.csv`` (a missing file is an empty project).

    Raises:
        StorageError: (E404) if the header differs from the contract, a row is invalid or the
            file is not readable as UTF-8 CSV (saved in another encoding by a spreadsheet); the
            message names the line where there is one so the file can be repaired.
    """
    if not path.exists():
        return []
    try:
        return _read_records(path)
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        logger.error("Cannot read %s (%s)", path.name, type(exc).__name__)
        raise StorageError(
            f"{path.name} cannot be read ({type(exc).__name__})",
            code="E404",
            hint="Restore records.csv from data/.backup/ (a spreadsheet may have re-saved it "
            "in another encoding).",
            details={"path": str(path)},
        ) from exc


def _read_records(path: Path) -> list[Record]:
    """The parsing behind :func:`read_records`, without the translation of low-level errors."""
    csv.field_size_limit(max(csv.field_size_limit(), 50_000_000))
    with open(path, encoding="utf-8-sig", newline="") as handle:  # tolerate a BOM added by Excel
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return []
        if tuple(header) != RECORD_COLUMNS:
            missing = [c for c in RECORD_COLUMNS if c not in header]
            unknown = [c for c in header if c not in RECORD_COLUMNS]
            raise StorageError(
                f"{path.name} does not have the expected columns "
                f"(missing: {missing or 'none'}, unknown: {unknown or 'none'}, or wrong order)",
                code="E404",
                hint="The project folder may be outdated; run 'crapai migrate' or use a backup.",
                details={"path": str(path), "missing": missing, "unknown": unknown},
            )
        records: list[Record] = []
        for row in reader:
            line = reader.line_num
            if not row:
                continue
            if len(row) != len(RECORD_COLUMNS):
                raise _row_error(path, line, f"{len(row)} cells instead of {len(RECORD_COLUMNS)}")
            try:
                records.append(Record.from_row(dict(zip(RECORD_COLUMNS, row, strict=True))))
            except (ValueError, ValidationError) as exc:
                raise _row_error(path, line, _first_reason(exc)) from exc
        return records


def _first_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors(include_input=False)[0]
        return f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
    return str(exc)


def _row_error(path: Path, line: int, reason: str) -> StorageError:
    return StorageError(
        f"{path.name}, line {line}: {reason}",
        code="E404",
        hint="Correct the value or restore data/.backup/records.<time>.csv.",
        details={"path": str(path), "line": line},
    )
