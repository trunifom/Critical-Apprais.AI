"""Preflight: what will happen if the run starts? (plan chapter 8.5, from ``PreflightService``)

Two checks, both free of any UI framework and working on paths only:

``check_file``
    A dry read of one export file *before* it is imported: is it readable, how many records,
    how many with an abstract. Nothing is written. Used by the data page of the interface.
``check_project``
    The state of a project *before* screening: records per source, duplicates, why records do not go
    to the model, abstract quality, retracted studies that stay in. With ``update=True`` it first
    runs dedup, the pre-filters and the validity check in the right order (import, dedup,
    pre-filters, validity) so the numbers
    are current.

Results are machine readable: a :class:`~crapai.enums.PreflightStatus` and issue codes. The
``message_key`` values point into the i18n files; the language is chosen where the text is shown.

Status rules (plan chapter 8.5): ``ERROR`` if there are no records or nothing can go to the model;
``WARNING`` if fewer than 60 % of the records of a source have an abstract (records without one
are not screened but stay visible) or if noteworthy facts need attention; otherwise ``OK``.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from crapai.config.loader import describe_config_problem, load_project_config
from crapai.enums import PreflightIssueCode, PreflightStatus, StringEnum
from crapai.errors import ImportFailed, SaraError
from crapai.io.normalize import ImportContext, to_records
from crapai.io.readers.dispatch import read_source
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.services.dedup import apply_dedup
from crapai.services.prefilter import apply_prefilters
from crapai.services.validity import apply_validity

logger = logging.getLogger(__name__)

MIN_ABSTRACT_RATIO_WARN = 0.60


class ProjectIssue(StringEnum):
    """Findings of :func:`check_project` beyond the per-file codes of ``PreflightIssueCode``."""

    NO_RECORDS = "no_records"
    NOTHING_TO_SCREEN = "nothing_to_screen"
    LOW_ABSTRACT_RATIO = "low_abstract_ratio"
    SUSPECT_ABSTRACTS = "suspect_abstracts"
    RETRACTED_INCLUDED = "retracted_included"
    CONFIG_INVALID = "config_invalid"
    EVENTS_NOT_WRITTEN = "events_not_written"


@dataclass(frozen=True)
class PreflightConfig:
    """Thresholds of the preflight.

    Attributes:
        min_abstract_ratio_warn: Below this share of records with an abstract a source is warned.
    """

    min_abstract_ratio_warn: float = MIN_ABSTRACT_RATIO_WARN


# --- one file, before the import ------------------------------------------------------------


@dataclass
class PreflightFileResult:
    """Result of the dry read of one file (nothing was written).

    ``message_key`` is an i18n key, not a text. ``error_code`` is the catalogue code (E1xx) of the
    failure, if any; ``detail`` is the technical message for the log or details line.
    """

    filename: str
    label: str
    format: str = ""
    records_total: int = 0
    records_with_abstract: int = 0
    status: PreflightStatus = PreflightStatus.OK
    issues: list[PreflightIssueCode] = field(default_factory=list)
    message_key: str = "preflight.status.ok"
    error_code: str | None = None
    detail: str | None = None


def check_file(
    path: Path,
    label: str,
    *,
    config: PreflightConfig | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    sheet: str | None = None,
    mapping: dict[str, str] | None = None,
) -> PreflightFileResult:
    """Read ``path`` without importing it and judge the result.

    Never raises for a bad file: the problem becomes an ``ERROR`` result with an issue code.
    """
    config = config or PreflightConfig()
    result = PreflightFileResult(filename=path.name, label=label)
    try:
        read, detection = read_source(
            path, encoding=encoding, delimiter=delimiter, sheet=sheet, mapping=mapping
        )
    except ImportFailed as exc:
        logger.warning("Preflight of %s failed: %s", path.name, exc.code)
        result.status = PreflightStatus.ERROR
        result.error_code, result.detail = exc.code, exc.user_message
        if exc.code == "E102":
            result.issues.append(PreflightIssueCode.NO_RECORDS)
            result.message_key = "preflight.status.error_no_records"
        elif "detected" in exc.details:  # a PDF or ZIP: recognised, but not part of version 1
            result.issues.append(PreflightIssueCode.UNSUPPORTED_TYPE)
            result.message_key = "preflight.status.error_unparseable"
        else:
            result.issues.append(PreflightIssueCode.PARSE_FAILED)
            result.message_key = "preflight.status.error_unparseable"
        return result
    except SaraError as exc:
        logger.warning("Preflight of %s failed: %s", path.name, exc.code)
        result.status = PreflightStatus.ERROR
        result.issues.append(PreflightIssueCode.PARSE_FAILED)
        result.message_key = "preflight.status.error_unparseable"
        result.error_code, result.detail = exc.code, exc.user_message
        return result

    records = to_records(read, ImportContext(label, path.name, read.format.value))
    result.format = read.format.value
    result.records_total = len(records)
    result.records_with_abstract = sum(1 for r in records if r.has_abstract)
    if result.records_total == 0:  # readers raise E102 for this; kept as a safety net
        result.status = PreflightStatus.ERROR
        result.issues.append(PreflightIssueCode.NO_RECORDS)
        result.message_key = "preflight.status.error_no_records"
    elif result.records_with_abstract == 0:
        result.status = PreflightStatus.ERROR
        result.issues.append(PreflightIssueCode.NO_ABSTRACTS)
        result.message_key = "preflight.status.error_no_abstracts"
    elif result.records_with_abstract / result.records_total < config.min_abstract_ratio_warn:
        result.status = PreflightStatus.WARNING
        result.issues.append(PreflightIssueCode.LOW_ABSTRACT_RATIO)
        result.message_key = "preflight.status.warn_low_abstracts"
    if detection.extension_mismatch:
        logger.info("%s: %s", path.name, detection.reason)
    return result


# --- the project, before the run ------------------------------------------------------------


@dataclass
class SourceReport:
    """Numbers of one source (all records that share a ``source_label``)."""

    label: str
    records: int = 0
    with_abstract: int = 0
    duplicates: int = 0
    valid_for_model: int = 0
    status: PreflightStatus = PreflightStatus.OK
    issues: list[ProjectIssue] = field(default_factory=list)


@dataclass
class ProjectReport:
    """The state of a project before screening.

    Attributes:
        records: All records (nothing is ever removed).
        duplicates: Records marked as duplicates.
        by_reason: Records per ``exclusion_reason`` (reasons are exclusive, one per record).
        valid_for_model: Records that would be sent to the model.
        quality: Abstract quality counts (``ok``, ``short``, ``suspect_concat``).
        retracted_included: Retracted studies that stay in the run (not excluded).
        sources: One report per source, in order of first appearance.
        status: ``ERROR`` if nothing can be screened, ``WARNING`` if something needs attention.
        issues: Project-level findings.
        config_problem: First line of the problem with ``project.yaml``, or None.
        updated: True if dedup and validity were run as part of this check.
    """

    records: int = 0
    duplicates: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    valid_for_model: int = 0
    quality: dict[str, int] = field(default_factory=dict)
    retracted_included: int = 0
    sources: list[SourceReport] = field(default_factory=list)
    status: PreflightStatus = PreflightStatus.OK
    issues: list[ProjectIssue] = field(default_factory=list)
    config_problem: str | None = None
    updated: bool = False
    events_written: bool = True  # False: a PRISMA event could not be written


def _configured_thresholds(workspace: Workspace) -> PreflightConfig:
    """The thresholds of ``preflight:`` in project.yaml; the defaults if it cannot be read."""
    try:
        ratio = load_project_config(workspace.project_yaml).preflight.min_abstract_ratio
    except (SaraError, FileNotFoundError):
        return PreflightConfig()
    return PreflightConfig(min_abstract_ratio_warn=ratio)


def check_project(
    workspace: Workspace,
    *,
    update: bool = True,
    config: PreflightConfig | None = None,
) -> ProjectReport:
    """Judge the project. With ``update`` dedup and the validity check run first (and write).

    Raises:
        StorageError: E404 for a folder that is no project or a damaged ``records.csv``; E402/E401
            from the update steps if the project is in use or ``records.csv`` is locked.
    """
    workspace = Workspace.open(workspace.root)
    config = config or _configured_thresholds(workspace)
    events_ok = True
    if update:
        # One lock for the three steps and the read that follows: an import cannot slip in
        # between and make the report mix two states of the project.
        with workspace.lock():
            dedup = apply_dedup(workspace)
            prefilters = apply_prefilters(workspace)
            validity = apply_validity(workspace)
            records = read_records(workspace.records_csv)
        events_ok = dedup.events_written and prefilters.events_written and validity.events_written
    else:
        records = read_records(workspace.records_csv)

    report = ProjectReport(updated=update)
    by_source: dict[str, SourceReport] = {}
    reasons: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    for record in records:
        source = by_source.setdefault(record.source_label, SourceReport(record.source_label))
        source.records += 1
        source.with_abstract += int(record.has_abstract)
        source.duplicates += int(record.is_duplicate)
        if record.exclusion_reason:
            reasons[record.exclusion_reason] += 1
        else:
            source.valid_for_model += 1
        if record.abstract_quality:
            quality[record.abstract_quality] += 1
        if record.is_retracted and record.exclusion_reason != "RETRACTED":
            report.retracted_included += 1
    report.events_written = events_ok
    report.records = len(records)
    report.duplicates = sum(s.duplicates for s in by_source.values())
    report.by_reason = dict(reasons)
    report.quality = dict(quality)
    report.valid_for_model = sum(s.valid_for_model for s in by_source.values())
    report.sources = list(by_source.values())

    for source in report.sources:
        if source.with_abstract / source.records < config.min_abstract_ratio_warn:
            source.status = PreflightStatus.WARNING
            source.issues.append(ProjectIssue.LOW_ABSTRACT_RATIO)

    _judge(report, workspace, config)
    return report


def _judge(report: ProjectReport, workspace: Workspace, config: PreflightConfig) -> None:
    """Set the overall status and the project-level issues."""
    if report.records == 0:
        report.issues.append(ProjectIssue.NO_RECORDS)
    elif report.valid_for_model == 0:
        report.issues.append(ProjectIssue.NOTHING_TO_SCREEN)
    if any(ProjectIssue.LOW_ABSTRACT_RATIO in s.issues for s in report.sources):
        report.issues.append(ProjectIssue.LOW_ABSTRACT_RATIO)
    if report.quality.get("suspect_concat", 0):
        report.issues.append(ProjectIssue.SUSPECT_ABSTRACTS)
    if report.retracted_included:
        report.issues.append(ProjectIssue.RETRACTED_INCLUDED)
    if not report.events_written:
        report.issues.append(ProjectIssue.EVENTS_NOT_WRITTEN)
    if workspace.project_yaml.exists():
        try:
            load_project_config(workspace.project_yaml)
        except SaraError as exc:
            report.config_problem = describe_config_problem(exc)
            report.issues.append(ProjectIssue.CONFIG_INVALID)
    else:
        report.config_problem = "project.yaml is missing"
        report.issues.append(ProjectIssue.CONFIG_INVALID)

    blocking = {ProjectIssue.NO_RECORDS, ProjectIssue.NOTHING_TO_SCREEN}
    if blocking & set(report.issues):
        report.status = PreflightStatus.ERROR
    elif report.issues:
        report.status = PreflightStatus.WARNING
    logger.info(
        "Preflight: %s, %d of %d records go to the model, issues %s",
        report.status.value,
        report.valid_for_model,
        report.records,
        [issue.value for issue in report.issues],
    )
