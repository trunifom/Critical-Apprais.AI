"""What a click in the interface does: call the services and never let an error escape.

Every function here takes the :class:`~crapai.i18n.messages.Messages` of the session first and
returns an :class:`Outcome`: either the value or an
:class:`~crapai.i18n.messages.ErrorReport` in words the user can act on (code, what happened, what
to do). The pages only draw the outcome, so they contain no ``try`` blocks, and the error handling
is tested once, here, without Streamlit.

Errors are logged like on the command line: code and message only, and a full traceback in the log
file for anything unexpected. Uploaded files are stored under their base name only (a file named
``..\\..\\x.ris`` cannot leave the work folder).
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml

from crapai.config.loader import validate_config
from crapai.config.overrides import Setting, effective_settings, reset_values, set_values
from crapai.errors import ConfigError, SaraError
from crapai.i18n.messages import ErrorReport, Messages
from crapai.logging_setup import attach_project_log
from crapai.prisma.flow import FlowWarning, PrismaFlow
from crapai.project.atomic import atomic_write_text
from crapai.project.workspace import Workspace
from crapai.services.cost import ProjectEstimate, estimate_project
from crapai.services.events import project_flow
from crapai.services.export import ExportSummary, export_flow, export_records
from crapai.services.importing import ImportRequest, ImportSummary, import_source
from crapai.services.preflight import PreflightFileResult, ProjectReport, check_file, check_project
from crapai.services.project import DEFAULT_TEMPLATE, create_project
from crapai.ui.settings_form import changes
from crapai.ui.viewmodels import Overview, RecentProjects, load_overview

logger = logging.getLogger(__name__)
T = TypeVar("T")
_UNSAFE = re.compile(r"[^\w.\- ]+")


@dataclass(frozen=True)
class Outcome(Generic[T]):
    """The result of an action: a value, or an error report (never both)."""

    value: T | None = None
    error: ErrorReport | None = None

    @property
    def ok(self) -> bool:
        """True if the action worked."""
        return self.error is None


def guarded(messages: Messages, action: Callable[[], T], *, name: str) -> Outcome[T]:
    """Run ``action`` and turn any exception into an :class:`ErrorReport`.

    Args:
        messages: The session's messages (language of the report).
        action: The work to do.
        name: Short name of the action for the log.
    """
    try:
        return Outcome(value=action())
    except SaraError as error:
        logger.error("%s failed: %s: %s", name, error.code, error.user_message)
        return Outcome(error=messages.error_report(error))
    except Exception as error:  # noqa: BLE001 - boundary: the interface must never crash
        logger.exception("%s failed unexpectedly", name)
        return Outcome(error=messages.error_report(error))


def safe_name(name: str) -> str:
    """A file name without folders or odd characters (``..\\x.ris`` becomes ``x.ris``)."""
    base = Path(name.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", base).strip(" .")
    return cleaned or "upload"


# --- projects --------------------------------------------------------------------------------


def open_project(
    messages: Messages, folder: Path, recent: RecentProjects | None = None
) -> Outcome[Overview]:
    """Open a project folder: attach its log, remember it and read its overview."""

    def work() -> Overview:
        overview = load_overview(folder)
        problem = attach_project_log(folder)
        if problem:
            logger.warning("Project log not attached: %s", problem)
        (recent or RecentProjects()).remember(folder)
        logger.info("Opened project %s", folder.name)
        return overview

    return guarded(messages, work, name="open project")


def create_new_project(
    messages: Messages,
    folder: Path,
    *,
    template: str = DEFAULT_TEMPLATE,
    title: str | None = None,
) -> Outcome[Workspace]:
    """Create a project folder from a template."""

    def work() -> Workspace:
        workspace = create_project(folder, template=template, title=title or None)
        attach_project_log(workspace.root)
        logger.info("Created project %s from template %s", workspace.root.name, template)
        return workspace

    return guarded(messages, work, name="create project")


def read_project_yaml(folder: Path) -> str:
    """The text of ``project.yaml`` ("" if it cannot be read)."""
    try:
        return Workspace(folder).project_yaml.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def save_project_yaml(messages: Messages, folder: Path, text: str) -> Outcome[None]:
    """Validate the text as a complete ``project.yaml`` and save it atomically.

    Nothing is written if the text is not valid YAML or breaks the configuration rules; the
    error report names the field.
    """

    def work() -> None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(
                "project.yaml: invalid YAML", code="E203", hint=str(exc)[:200]
            ) from exc
        if not isinstance(data, dict):
            raise ConfigError("project.yaml: the top level must be a mapping", code="E203")
        validate_config(data)
        workspace = Workspace.open(folder)
        with workspace.lock():
            atomic_write_text(workspace.project_yaml, text)
        logger.info("Saved project.yaml of %s", folder.name)

    return guarded(messages, work, name="save project.yaml")


# --- settings --------------------------------------------------------------------------------


def load_settings(folder: Path) -> dict[str, Setting]:
    """Every setting in force with its value and source (empty if the project cannot be read)."""
    try:
        settings = effective_settings(Workspace(folder).project_yaml)
    except SaraError as error:
        logger.warning("Settings not readable: %s", error.code)
        return {}
    return {s.key: s for s in settings}


def save_settings(
    messages: Messages, folder: Path, edited: dict[str, Any]
) -> Outcome[dict[str, Any]]:
    """Store the settings that differ from the values in force; returns what was changed.

    Raises nothing: an invalid value becomes an error report and nothing is written.
    """

    def work() -> dict[str, Any]:
        workspace = Workspace.open(folder)
        current = {key: s.value for key, s in load_settings(folder).items()}
        try:
            diff = changes(current, edited)
        except ValueError as exc:
            raise ConfigError(
                f"The value of {exc} is not valid", code="E203", hint="Check the number or text."
            ) from exc
        if diff:
            with workspace.lock():
                set_values(workspace.project_yaml, diff)
            logger.info("Settings changed in the interface: %s", ", ".join(sorted(diff)))
        return diff

    return guarded(messages, work, name="save settings")


def reset_settings(messages: Messages, folder: Path) -> Outcome[list[str]]:
    """Remove every change made outside ``project.yaml`` (the overrides file)."""

    def work() -> list[str]:
        workspace = Workspace.open(folder)
        with workspace.lock():
            removed = reset_values(workspace.project_yaml)
        logger.info("Settings reset in the interface: %d", len(removed))
        return removed

    return guarded(messages, work, name="reset settings")


# --- import ----------------------------------------------------------------------------------


@dataclass
class Upload:
    """A file the user chose: its name and bytes."""

    name: str
    data: bytes


@dataclass
class PreparedFile:
    """An uploaded file stored in the work folder, with the result of its dry read."""

    name: str
    path: Path
    preflight: PreflightFileResult
    label: str = field(default="")

    @property
    def importable(self) -> bool:
        """False if the dry read found an error (nothing could be read)."""
        return self.preflight.status.value != "error"


def prepare_uploads(uploads: list[Upload], workdir: Path | None = None) -> list[PreparedFile]:
    """Store the uploads and run the dry read (``check_file``) on each; nothing is imported.

    A second file with the same name gets a number, so two uploads never overwrite each other.
    """
    folder = workdir or Path(tempfile.mkdtemp(prefix="crapai-upload-"))
    folder.mkdir(parents=True, exist_ok=True)
    prepared: list[PreparedFile] = []
    taken: set[str] = set()
    for upload in uploads:
        name = safe_name(upload.name)
        stem, suffix = Path(name).stem, Path(name).suffix
        counter = 2
        while name in taken:
            name, counter = f"{stem}-{counter}{suffix}", counter + 1
        taken.add(name)
        path = folder / name
        path.write_bytes(upload.data)
        label = Path(name).stem
        prepared.append(PreparedFile(name, path, check_file(path, label), label))
    return prepared


@dataclass
class ImportOutcome:
    """The result of importing one prepared file."""

    name: str
    summary: ImportSummary | None = None
    error: ErrorReport | None = None


def import_prepared(
    messages: Messages, folder: Path, files: list[PreparedFile], *, force: bool = False
) -> list[ImportOutcome]:
    """Import the importable files one by one; a failing file does not stop the others."""
    results: list[ImportOutcome] = []
    for item in files:
        if not item.importable:
            continue
        outcome = guarded(messages, _importer(folder, item, force), name=f"import {item.name}")
        results.append(ImportOutcome(item.name, outcome.value, outcome.error))
    return results


def _importer(folder: Path, item: PreparedFile, force: bool) -> Callable[[], ImportSummary]:
    """The import of one prepared file as a callable (keeps the loop above free of closures)."""

    def run() -> ImportSummary:
        request = ImportRequest(item.path, label=item.label or None, force=force)
        return import_source(Workspace(folder), request)

    return run


# --- check, flow, export ----------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """The preflight report plus the cost estimate (or why there is none)."""

    report: ProjectReport
    estimate: ProjectEstimate | None
    estimate_error: ErrorReport | None


def run_check(messages: Messages, folder: Path, *, update: bool = True) -> Outcome[CheckResult]:
    """Dedup, pre-filters and validity, then the report and the estimate (as ``crapai check``)."""

    def work() -> CheckResult:
        report = check_project(Workspace(folder), update=update)
        if report.valid_for_model == 0:
            return CheckResult(report, None, None)
        estimate = guarded(messages, lambda: estimate_project(Workspace(folder)), name="estimate")
        return CheckResult(report, estimate.value, estimate.error)

    return guarded(messages, work, name="check")


def load_flow(
    messages: Messages, folder: Path, mode: str | None = None
) -> Outcome[tuple[PrismaFlow, list[FlowWarning]]]:
    """The PRISMA flow numbers with their plausibility warnings."""
    return guarded(messages, lambda: project_flow(Workspace(folder), mode), name="flow")


@dataclass(frozen=True)
class ExportResult:
    """An export that was written, with its bytes ready for a download button."""

    summary: ExportSummary
    data: bytes


def run_export(
    messages: Messages,
    folder: Path,
    *,
    what: str = "records",
    fmt: str = "csv",
    scope: str = "all",
    delimiter: str = ",",
) -> Outcome[ExportResult]:
    """Write an export into the project's ``exports/`` folder and read it back for download."""

    def work() -> ExportResult:
        workspace = Workspace(folder)
        if what == "flow":
            summary = export_flow(workspace)
        else:
            summary = export_records(workspace, fmt, scope=scope, delimiter=delimiter)
        return ExportResult(summary, summary.path.read_bytes())

    return guarded(messages, work, name="export")
