"""Export service: write the project's data for other tools (plan chapters 8.8, 15.1 and 25.8).

Two things can be exported, both read-only with respect to the project (nothing is changed, no
lock is needed: ``records.csv`` is replaced atomically, so a read never sees half a file):

``records``
    The records as CSV or XLSX (all 40 columns of ``records.csv``, sanitised for spreadsheets), or
    as RIS, BibTeX or NBIB/MEDLINE (for reference managers and screening tools). The scope selects
    all records, only those that go to the model, or only those that are marked with an exclusion
    reason.
``flow``
    The PRISMA 2020 flow numbers as ``prisma_flow.json`` with the plausibility warnings, derived
    from the event stream (:mod:`crapai.services.events`).

Files go to ``<project>/exports/`` unless the caller names a path. A target that is locked (open in
Excel) is not an error: the content is saved under a timestamped name and the summary says so.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from crapai.config.loader import load_project_config
from crapai.enums import DuplicatesReportingMode
from crapai.errors import ConfigError, SaraError
from crapai.io.records_store import RECORD_COLUMNS, Record, read_records
from crapai.io.writers.bibtex import write_bibtex
from crapai.io.writers.docx_report import write_docx_report
from crapai.io.writers.nbib import write_nbib
from crapai.io.writers.prisma_image import write_prisma_image
from crapai.io.writers.ris import write_ris
from crapai.io.writers.tables import write_csv, write_xlsx
from crapai.project.atomic import atomic_write_text
from crapai.project.workspace import Workspace
from crapai.services.events import project_flow, read_events
from crapai.stats.results import Analysis

logger = logging.getLogger(__name__)

RecordFormat = Literal["csv", "xlsx", "ris", "bibtex", "nbib"]
Scope = Literal["all", "screenable", "excluded"]
RECORD_FORMATS: tuple[str, ...] = ("csv", "xlsx", "ris", "bibtex", "nbib")
# File extension per format (only "bibtex" differs from its own name: ".bib", the usual extension).
_EXTENSIONS: dict[str, str] = {"bibtex": "bib"}
SCOPES: tuple[str, ...] = ("all", "screenable", "excluded")
FLOW_SCHEMA = 1


@dataclass(frozen=True)
class ExportSummary:
    """What an export wrote.

    Attributes:
        what: ``records``, ``flow`` or ``report``.
        format: ``csv``, ``xlsx``, ``ris``, ``bibtex``, ``nbib`` (records); ``json``, ``png``,
            ``svg`` (flow); or ``docx`` (report).
        path: The file that holds the content.
        requested_path: The file that was asked for (differs from ``path`` if it was locked).
        records: Number of records written (0 for the flow or the report).
        scope: Scope of a records export, ``""`` for the flow or the report.
        used_alternative: True if the target was locked and ``path`` is a timestamped copy.
    """

    what: str
    format: str
    path: Path
    requested_path: Path
    records: int = 0
    scope: str = ""
    used_alternative: bool = False


def select_records(records: list[Record], scope: str) -> list[Record]:
    """The records of a scope: ``all``, ``screenable`` (no exclusion reason) or ``excluded``.

    Raises:
        ConfigError: (E203) for an unknown scope.
    """
    if scope == "all":
        return list(records)
    if scope == "screenable":
        return [r for r in records if not r.exclusion_reason]
    if scope == "excluded":
        return [r for r in records if r.exclusion_reason]
    raise ConfigError(
        f"Unknown export scope '{scope}' (valid: {', '.join(SCOPES)})",
        code="E203",
        hint="Use --scope all, screenable or excluded.",
    )


def _target(workspace: Workspace, output: Path | None, default_name: str) -> Path:
    """The file to write: the requested path, or ``exports/<default_name>`` (folder created)."""
    if output is not None:
        if output.is_dir():
            raise ConfigError(
                f"{output} is a folder, not a file",
                code="E203",
                hint="Name the file, for example --output results.xlsx.",
            )
        if not output.parent.is_dir():
            raise ConfigError(
                f"The folder {output.parent} does not exist",
                code="E203",
                hint="Create the folder first or choose another --output.",
            )
        return output
    workspace.exports_dir.mkdir(parents=True, exist_ok=True)
    return workspace.exports_dir / default_name


def export_records(
    workspace: Workspace,
    fmt: str = "csv",
    *,
    scope: str = "all",
    output: Path | None = None,
    delimiter: str = ",",
    guard_formulas: bool = True,
    now: datetime | None = None,
) -> ExportSummary:
    """Write the records of the project to a CSV, XLSX, RIS, BibTeX or NBIB/MEDLINE file.

    Args:
        workspace: The project.
        fmt: ``csv``, ``xlsx``, ``ris``, ``bibtex`` or ``nbib``.
        scope: ``all``, ``screenable`` or ``excluded``.
        output: Target file; default ``exports/records-<scope>-<timestamp>.<fmt>``.
        delimiter: CSV separator (one character); ``;`` suits Excel with a German locale.
        guard_formulas: Write cells that start like a formula as text (CSV and XLSX).
        now: Clock for the default file name (for tests).

    Raises:
        ConfigError: E203 for an unknown format or scope, a bad target or separator, or XLSX
            without ``openpyxl``.
        StorageError: E404 for a folder that is no project or a damaged ``records.csv``; E401/E403
            if the file cannot be written.
    """
    if fmt not in RECORD_FORMATS:
        raise ConfigError(
            f"Unknown export format '{fmt}' (valid: {', '.join(RECORD_FORMATS)})",
            code="E203",
            hint="Use --format csv, xlsx, ris, bibtex or nbib.",
        )
    workspace = Workspace.open(workspace.root)
    everything = read_records(workspace.records_csv)
    selected = select_records(everything, scope)
    if fmt in ("ris", "bibtex", "nbib"):
        # A full-text attachment (``fulltext_of`` set, ADR 0026) is a PDF reference, not a
        # bibliographic record of its own -- it legitimately shares its DOI/title with the record
        # it belongs to (crapai.io.fulltext_link matches it by exactly that). A reference-manager
        # format would otherwise gain a spurious, near-duplicate entry for every full-text import;
        # CSV/XLSX keep it (they are the full data dump, all 40 columns of records.csv).
        selected = [r for r in selected if not r.fulltext_of]
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    extension = _EXTENSIONS.get(fmt, fmt)
    target = _target(workspace, output, f"records-{scope}-{stamp}.{extension}")
    if fmt == "csv":
        written = write_csv(
            target,
            RECORD_COLUMNS,
            (r.to_row() for r in selected),
            delimiter=delimiter,
            guard_formulas=guard_formulas,
        )
    elif fmt == "xlsx":
        written = write_xlsx(
            target, RECORD_COLUMNS, (r.to_row() for r in selected), guard_formulas=guard_formulas
        )
    elif fmt == "bibtex":
        written = write_bibtex(target, selected)
    elif fmt == "nbib":
        written = write_nbib(target, selected)
    else:
        written = write_ris(target, selected)
    logger.info(
        "Exported %d of %d record(s) (scope %s) as %s to %s",
        len(selected),
        len(everything),
        scope,
        fmt,
        written.path.name,
    )
    return ExportSummary(
        what="records",
        format=fmt,
        path=written.path,
        requested_path=target,
        records=len(selected),
        scope=scope,
        used_alternative=written.used_alternative,
    )


FLOW_FORMATS: tuple[str, ...] = ("json", "png", "svg")


def export_flow(
    workspace: Workspace,
    *,
    fmt: str = "json",
    output: Path | None = None,
    mode: DuplicatesReportingMode | str | None = None,
    now: datetime | None = None,
) -> ExportSummary:
    """Write the PRISMA flow as JSON (the numbers, warnings, mode) or as a PNG/SVG picture.

    The JSON file (``exports/prisma_flow.json`` by default) holds the numbers, the plausibility
    warnings (for example a stale dedup), the reporting mode and the number of events they were
    derived from. A PNG/SVG picture (``exports/prisma_flow.png``/``.svg``) draws the same numbers
    as a standard PRISMA 2020 box diagram (:mod:`crapai.io.writers.prisma_image`); it carries no
    warnings of its own, only the numbers.

    Raises:
        ConfigError: E203 for an unknown format/mode or a bad target, or (PNG/SVG only) if
            ``matplotlib`` is not installed.
        StorageError: E404 for a folder that is no project or a damaged event file; E401/E403 if
            the file cannot be written.
    """
    if fmt not in FLOW_FORMATS:
        raise ConfigError(
            f"Unknown format '{fmt}' for the PRISMA flow (valid: {', '.join(FLOW_FORMATS)})",
            code="E203",
            hint="Use --format json, png or svg.",
        )
    workspace = Workspace.open(workspace.root)
    flow, warnings = project_flow(workspace, mode)
    if fmt != "json":
        target = _target(workspace, output, f"prisma_flow.{fmt}")
        written = write_prisma_image(target, flow, fmt)
        logger.info("Exported the PRISMA flow as %s to %s", fmt, written.path.name)
        return ExportSummary(
            what="flow",
            format=fmt,
            path=written.path,
            requested_path=target,
            used_alternative=written.used_alternative,
        )
    document = {
        "schema": FLOW_SCHEMA,
        "generated_at": (now or datetime.now()).astimezone().isoformat(timespec="seconds"),
        "reporting_mode": flow.duplicates_reporting_mode,
        "events": len(read_events(workspace.events_jsonl)),
        "flow": flow.to_dict(),
        "warnings": [asdict(w) for w in warnings],
    }
    target = _target(workspace, output, "prisma_flow.json")
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    written = atomic_write_text(target, text)
    logger.info("Exported the PRISMA flow (%d warning(s)) to %s", len(warnings), written.path.name)
    return ExportSummary(
        what="flow",
        format="json",
        path=written.path,
        requested_path=target,
        used_alternative=written.used_alternative,
    )


def export_report(
    workspace: Workspace,
    *,
    output: Path | None = None,
    now: datetime | None = None,
) -> ExportSummary:
    """Write a readable Word summary (method, PRISMA flow, screening results) as ``.docx``.

    Uses only numbers this program already computes: the project's objectives and criteria, the
    PRISMA flow (same numbers as ``--what flow``) and the results of the newest finished run, if
    any (a project with no run yet still gets a report; that section just says so).

    Raises:
        ConfigError: E203 if ``python-docx`` is not installed, or a bad target.
        StorageError: E404 for a folder that is no project or damaged files; E401/E403 if the
            file cannot be written.
    """
    # Deferred: services.results imports from this module (ExportSummary, _target), so importing
    # it back at module level here would be a circular import.
    from crapai.services.results import results_table, runs_with_results
    from crapai.stats.results import analyse

    workspace = Workspace.open(workspace.root)
    config = load_project_config(workspace.project_yaml)
    flow, _warnings = project_flow(workspace)
    results: tuple[str, Analysis] | None = None
    if runs_with_results(workspace):
        try:
            run_id, rows = results_table(workspace)
            results = (run_id, analyse(rows))
        except SaraError as exc:
            logger.warning("Report: results table not available (%s)", exc.code)
    target = _target(workspace, output, f"report-{(now or datetime.now()):%Y%m%d-%H%M%S}.docx")
    written = write_docx_report(target, config, flow, results, now=now)
    logger.info("Exported the summary report to %s", written.path.name)
    return ExportSummary(
        what="report",
        format="docx",
        path=written.path,
        requested_path=target,
        used_alternative=written.used_alternative,
    )
