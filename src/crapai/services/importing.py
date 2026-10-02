"""Import service: from a source file to new rows in ``data/records.csv`` (plan chapter 8.2).

The steps, in an order that keeps the project consistent if the program is stopped half way:

1. hash the file and refuse a repeated import (E106) unless ``force``;
2. detect the format and read the file **before** anything is written, so a bad file leaves no
   trace;
3. copy the original to ``sources/`` (never overwritten, verified by hash);
4. normalise the records and rewrite ``records.csv`` atomically, after a backup;
5. append the entry to the import log last: it is the record that the import is complete.

The project lock is held for the whole time so two imports cannot overwrite each other.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from crapai.config.loader import load_project_config
from crapai.errors import ImportFailed, SaraError, StorageError
from crapai.io.fulltext_link import (
    UNMATCHED_REPORT_NAME,
    link_fulltext,
    write_unmatched_report,
)
from crapai.io.import_log import (
    ImportLogEntry,
    append_entry,
    ensure_not_imported,
    sha256_file,
)
from crapai.io.normalize import ImportContext, to_records
from crapai.io.readers.detect import SourceFormat, detect_format
from crapai.io.readers.dispatch import read_source
from crapai.io.readers.pdf_zip import extract_pdf_zip
from crapai.io.records_store import read_records, write_records
from crapai.project.workspace import Workspace
from crapai.services.events import record_import

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportRequest:
    """One file to import and how to read it."""

    path: Path
    label: str | None = None
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    mapping: dict[str, str] = field(default_factory=dict)
    force: bool = False


@dataclass(frozen=True)
class ImportSummary:
    """What an import did, for the CLI and the import log."""

    source_file: str
    source_label: str
    format: str
    sha256: str
    records: int
    abstracts: int
    empty_records: int
    total_records: int
    encoding: str | None
    notes: tuple[str, ...]
    column_map: dict[str, str]
    format_reason: str
    warnings: tuple[str, ...]
    mapping_source: str | None = None  # "cli", "project" or None (aliases only)
    unmatched: int = 0  # PDFs (ADR 0026) that matched no record; see reports/unmatched_pdfs.csv


def import_source(
    workspace: Workspace,
    request: ImportRequest,
    *,
    now: datetime | None = None,
) -> ImportSummary:
    """Import one file into the project.

    Raises:
        ImportFailed: E101-E104 for unreadable or unsuitable files, E106 for a repeated import.
        StorageError: E402 if another process uses the project, E404 for a damaged
            ``records.csv``, E401/E403 for write problems.
    """
    path = request.path
    if not path.is_file():
        raise ImportFailed(
            f"File not found: {path}",
            code="E101",
            hint="Check the path.",
            details={"path": str(path)},
        )
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        return _import_locked(workspace, request, now or datetime.now().astimezone())


def _import_locked(workspace: Workspace, request: ImportRequest, now: datetime) -> ImportSummary:
    path = request.path
    digest = sha256_file(path)
    ensure_not_imported(workspace.import_log, digest, force=request.force)

    if detect_format(path).format is SourceFormat.ZIP:
        # A ZIP of PDFs (ADR 0026) is not a bibliographic export: it adds full text to records
        # that (are expected to) already exist, matched by DOI/title, not new rows for every PDF.
        # That matching needs the project's existing records, which the generic read_source()
        # path below never sees, so it is handled separately from here on.
        return _import_fulltext_zip_locked(workspace, request, digest, now)

    mapping, mapping_source = _effective_mapping(workspace, request)
    result, detection = read_source(
        path,
        encoding=request.encoding,
        delimiter=request.delimiter,
        sheet=request.sheet,
        mapping=mapping or None,
    )

    stored = _copy_to_sources(path, workspace.sources_dir, digest)
    label = request.label or path.stem
    context = ImportContext(label, stored.name, result.format.value)
    new_records = to_records(result, context)

    existing = read_records(workspace.records_csv)
    write_records(
        workspace.records_csv,
        [*existing, *new_records],
        backup_dir=workspace.backup_dir,
        now=now,
    )

    abstracts = sum(1 for r in new_records if r.has_abstract)
    empty = sum(1 for r in new_records if r.exclusion_reason == "EMPTY_RECORD")
    notes = list(result.notes)
    if detection.extension_mismatch:
        notes.insert(0, detection.reason)
    entry = ImportLogEntry(
        timestamp=now,
        source_file=stored.name,
        sha256=digest,
        source_label=label,
        format=result.format.value,
        records=len(new_records),
        abstracts=abstracts,
        encoding=result.encoding,
        options=result.options,
        column_map=result.column_map,
        notes=notes,
        forced=request.force,
    )
    try:
        append_entry(workspace.import_log, entry)
    except OSError as exc:
        # The records are already saved; importing the file again would add them twice.
        logger.error("Import log not written (%s); the records were saved", type(exc).__name__)
        raise StorageError(
            f"The records of {path.name} were saved, but the import log could not be written "
            f"({type(exc).__name__})",
            code="E401",
            hint="Do not import this file again. Check data/records.import.jsonl and run "
            "'crapai status'.",
            details={"path": str(workspace.import_log)},
        ) from exc
    events_ok = record_import(workspace, label, stored.name, result.format.value, len(new_records))
    warnings = _warnings(len(new_records), abstracts, empty)
    if not events_ok:
        warnings.append("events_not_written")
    logger.info("Imported %d record(s) from %s as '%s'", len(new_records), path.name, label)
    return ImportSummary(
        source_file=stored.name,
        source_label=label,
        format=result.format.value,
        sha256=digest,
        records=len(new_records),
        abstracts=abstracts,
        empty_records=empty,
        total_records=len(existing) + len(new_records),
        encoding=result.encoding,
        notes=tuple(notes),
        column_map=dict(result.column_map),
        format_reason=detection.reason,
        warnings=tuple(warnings),
        mapping_source=mapping_source if result.column_map else None,
    )


def _import_fulltext_zip_locked(
    workspace: Workspace, request: ImportRequest, digest: str, now: datetime
) -> ImportSummary:
    """Import a ZIP of PDFs (ADR 0026): match each to an existing record, add one row per match.

    Unlike every other import, this never creates a "new paper": a PDF with no match is not
    added to ``records.csv`` at all (there is nothing in the project to attach it to), but it is
    never silently dropped either -- it goes to ``reports/unmatched_pdfs.csv``.
    """
    path = request.path
    zip_result = extract_pdf_zip(path)
    stored = _copy_to_sources(path, workspace.sources_dir, digest)
    label = request.label or path.stem
    existing = read_records(workspace.records_csv)
    link_result = link_fulltext(
        existing, zip_result.documents, source_label=label, source_file=stored.name
    )

    notes = list(zip_result.notes)
    warnings: list[str] = []
    if link_result.unmatched:
        report_path = workspace.reports_dir / UNMATCHED_REPORT_NAME
        write_unmatched_report(report_path, link_result.unmatched)
        notes.append(
            f"{len(link_result.unmatched)} of {len(zip_result.documents)} PDF(s) could not be "
            f"matched to a record; see {report_path.relative_to(workspace.root)}"
        )
        warnings.append("fulltext_unmatched")

    write_records(
        workspace.records_csv,
        [*existing, *link_result.new_records],
        backup_dir=workspace.backup_dir,
        now=now,
    )
    quality_issues = sum(1 for r in link_result.new_records if r.exclusion_reason)
    entry = ImportLogEntry(
        timestamp=now,
        source_file=stored.name,
        sha256=digest,
        source_label=label,
        format=SourceFormat.ZIP.value,
        records=len(link_result.new_records),
        abstracts=0,  # a fulltext row never carries its own abstract
        notes=notes,
        forced=request.force,
    )
    try:
        append_entry(workspace.import_log, entry)
    except OSError as exc:
        logger.error("Import log not written (%s); the records were saved", type(exc).__name__)
        raise StorageError(
            f"The records of {path.name} were saved, but the import log could not be written "
            f"({type(exc).__name__})",
            code="E401",
            hint="Do not import this file again. Check data/records.import.jsonl and run "
            "'crapai status'.",
            details={"path": str(workspace.import_log)},
        ) from exc
    events_ok = record_import(
        workspace, label, stored.name, SourceFormat.ZIP.value, len(link_result.new_records)
    )
    if not events_ok:
        warnings.append("events_not_written")
    logger.info(
        "Imported %d PDF(s) from %s as '%s' (%d unmatched, %d with a quality problem)",
        len(link_result.new_records), path.name, label, len(link_result.unmatched), quality_issues,
    )  # fmt: skip
    return ImportSummary(
        source_file=stored.name,
        source_label=label,
        format=SourceFormat.ZIP.value,
        sha256=digest,
        records=len(link_result.new_records),
        abstracts=0,
        empty_records=0,
        total_records=len(existing) + len(link_result.new_records),
        encoding=None,
        notes=tuple(notes),
        column_map={},
        format_reason="ZIP archive of PDFs (full text, ADR 0026)",
        warnings=tuple(warnings),
        unmatched=len(link_result.unmatched),
    )


def _effective_mapping(
    workspace: Workspace, request: ImportRequest
) -> tuple[dict[str, str], str | None]:
    """The column mapping for this file: command line, else ``import.mappings`` of project.yaml.

    An unreadable or invalid project.yaml is ignored here (the import does not need it) and logged.
    """
    if request.mapping:
        return dict(request.mapping), "cli"
    if not workspace.project_yaml.exists():
        return {}, None
    try:
        config = load_project_config(workspace.project_yaml)
    except SaraError as exc:
        logger.warning("project.yaml not used for column mappings (%s)", exc.code)
        return {}, None
    stored = config.import_settings.mappings.get(request.path.name, {})
    return (dict(stored), "project") if stored else ({}, None)


def _warnings(records: int, abstracts: int, empty: int) -> list[str]:
    warnings: list[str] = []
    if abstracts == 0:
        warnings.append("no_abstracts")
    elif abstracts / records < 0.6:
        warnings.append("low_abstract_ratio")
    if empty:
        warnings.append("empty_records")
    return warnings


def _copy_to_sources(path: Path, sources_dir: Path, digest: str) -> Path:
    """Copy the original into ``sources/`` without overwriting anything; verify the copy."""
    target = sources_dir / path.name
    try:
        sources_dir.mkdir(parents=True, exist_ok=True)
        counter = 2
        while target.exists():
            if sha256_file(target) == digest:
                return target  # the very same bytes are already there (forced re-import)
            target = sources_dir / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        shutil.copyfile(path, target)
    except OSError as exc:
        target.unlink(missing_ok=True)  # never leave a half-copied original behind
        code = "E403" if getattr(exc, "errno", None) == 28 else "E401"  # 28 = no space left
        logger.error("Cannot copy %s to sources/ (%s, %s)", path.name, type(exc).__name__, code)
        raise StorageError(
            f"Cannot copy {path.name} to sources/ ({type(exc).__name__})",
            code=code,
            hint="Free disk space or check the folder permissions; nothing was imported.",
            details={"path": str(path)},
        ) from exc
    if sha256_file(target) != digest:
        target.unlink(missing_ok=True)
        raise StorageError(
            f"Copying {path.name} to sources/ failed (checksum differs)",
            code="E401",
            hint="Check the disk and try again.",
            details={"path": str(path)},
        )
    return target
