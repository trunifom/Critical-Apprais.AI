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

import csv
import logging
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml

from crapai.config.loader import load_project_config, validate_config
from crapai.config.models import ProjectConfig
from crapai.config.overrides import Setting, effective_settings, reset_values, set_values
from crapai.config.profiles import apply_profile, list_profiles, save_profile
from crapai.cost.pricing import CsvPriceSource
from crapai.errors import ConfigError, SaraError, StorageError
from crapai.i18n.messages import ErrorReport, Messages
from crapai.logging_setup import attach_project_log
from crapai.prisma.flow import FlowWarning, PrismaFlow
from crapai.project.atomic import atomic_write_text
from crapai.project.workspace import Workspace
from crapai.services import screening as screening_service
from crapai.services.ai_prefilter import AiPrefilterSummary, ai_prefilter_project
from crapai.services.cost import (
    AiPrefilterEstimate,
    ProjectEstimate,
    estimate_ai_prefilter,
    estimate_project,
)
from crapai.services.events import project_flow
from crapai.services.export import ExportSummary, export_flow, export_records, export_report
from crapai.services.importing import ImportRequest, ImportSummary, import_source
from crapai.services.preflight import PreflightFileResult, ProjectReport, check_file, check_project
from crapai.services.project import DEFAULT_TEMPLATE, create_project, project_status
from crapai.services.results import compare_runs as compare_runs_service
from crapai.services.results import export_results, results_table
from crapai.stats.agreement import ComparisonSummary
from crapai.stats.results import read_table_file
from crapai.ui import definition as definition_module
from crapai.ui.definition import Definition
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


def saved_profile_names() -> list[str]:
    """Names of every saved settings profile, sorted (empty if none are saved, never raises)."""
    try:
        return list_profiles()
    except SaraError as error:
        logger.warning("Settings profiles not readable: %s", error.code)
        return []


def save_as_profile(messages: Messages, folder: Path, name: str) -> Outcome[Path]:
    """Save this project's effective objectives/criteria/screening/llm as a named profile."""

    def work() -> Path:
        config = load_project_config(Workspace.open(folder).project_yaml)
        path = save_profile(name, config)
        logger.info("Saved settings profile '%s' from the interface", name)
        return path

    return guarded(messages, work, name="save profile")


def load_profile_into(messages: Messages, folder: Path, name: str) -> Outcome[dict[str, Any]]:
    """Load a saved profile into this project's overrides (``project.yaml`` stays untouched)."""

    def work() -> dict[str, Any]:
        workspace = Workspace.open(folder)
        with workspace.lock():
            sections = apply_profile(workspace.project_yaml, name)
        logger.info("Loaded settings profile '%s' in the interface", name)
        return sections

    return guarded(messages, work, name="load profile")


def read_pricing_table(messages: Messages, path: Path) -> Outcome[list[dict[str, str]]]:
    """The project's ``pricing.csv`` as rows for display (validated, delimiter detected)."""

    def work() -> list[dict[str, str]]:
        CsvPriceSource(path)  # validates the file and logs any bad row
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.readline()
            handle.seek(0)  # the sniff above must not consume the header row for DictReader
            return list(csv.DictReader(handle, delimiter=";" if ";" in sample else ","))

    return guarded(messages, work, name="read pricing table")


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
            # fmt defaults to "csv" (the page's general default, meant for records/results);
            # for flow that means "json", the original behaviour -- the page can still choose
            # png/svg explicitly (see ui/pages/export.py).
            summary = export_flow(workspace, fmt="json" if fmt == "csv" else fmt)
        elif what == "report":
            summary = export_report(workspace)
        elif what == "results":
            summary = export_results(workspace, fmt, delimiter=delimiter)
        else:
            summary = export_records(workspace, fmt, scope=scope, delimiter=delimiter)
        return ExportResult(summary, summary.path.read_bytes())

    return guarded(messages, work, name="export")


# --- screening runs -----------------------------------------------------------------------------

#: file in ``.crapai/`` that receives what the screening process prints (for a crash at the start)
SCREEN_OUTPUT = "screen.out"


def screen_command(
    folder: Path, *, lang: str, sample: int | None = None, resume: bool = False
) -> list[str]:
    """The command line of the screening process (``python -m crapai screen ...``)."""
    command = [sys.executable, "-m", "crapai", "screen", str(folder), "--yes", "--no-progress"]
    command += ["--lang", lang]
    if resume:
        command.append("--resume")
    elif sample:
        command += ["--sample", str(sample)]
    return command


def start_run(
    messages: Messages,
    folder: Path,
    *,
    lang: str,
    sample: int | None = None,
    resume: bool = False,
) -> Outcome[int]:
    """Start a screening run in a **separate process** and return its process id.

    The run does not depend on the browser: closing the tab or the interface does not stop it, and
    the page finds it again through ``manifest.json`` (architecture decision 0006). Everything that
    can be checked beforehand is checked here, so that a wrong key or a busy project is reported
    in the interface at once and not only in a file: the project must not be in use, the settings
    must be valid, and the provider must be usable (key present).

    Returns:
        The outcome with the process id, or an error report (E402 in use, E301 key, E203/E201
        settings, E404 no project).
    """

    def work() -> int:
        workspace = Workspace.open(folder)
        info = workspace.lock().inspect()
        if info is not None and not info.stale:
            raise StorageError(
                "The project is in use by another process",
                code="E402",
                hint="Wait until it has finished, or stop that run first.",
            )
        config = load_project_config(workspace.project_yaml)
        screening_service.make_provider(config)  # raises E301/E203 before anything is started
        workspace.state_dir.mkdir(parents=True, exist_ok=True)
        command = screen_command(folder, lang=lang, sample=sample, resume=resume)
        flags = 0
        extra: dict[str, Any] = {}
        if sys.platform == "win32":
            # Own process group, no console window: Ctrl+C in the interface must not reach it.
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            extra["start_new_session"] = True
        with (workspace.state_dir / SCREEN_OUTPUT).open("ab") as output:
            process = subprocess.Popen(  # noqa: S603 - a fixed argument list, no shell
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                cwd=folder,
                creationflags=flags,
                **extra,
            )
        logger.info("Started the screening process (PID %d)", process.pid)
        return process.pid

    return guarded(messages, work, name="start run")


def control_run(messages: Messages, folder: Path, run_id: str, command: str) -> Outcome[None]:
    """Ask a running run to ``pause`` or ``stop`` (it reacts within a few seconds)."""

    def work() -> None:
        screening_service.request_control(Workspace.open(folder), run_id, command)
        logger.info("Sent %s to run %s", command, run_id)

    return guarded(messages, work, name=f"{command} run")


def estimate_run(messages: Messages, folder: Path) -> Outcome[ProjectEstimate]:
    """The cost and time estimate shown before a run starts."""
    return guarded(messages, lambda: estimate_project(Workspace.open(folder)), name="estimate")


def read_project_config(messages: Messages, folder: Path) -> Outcome[ProjectConfig]:
    """``project.yaml``, validated (no ``try`` needed on the page that only shows it)."""
    return guarded(
        messages, lambda: load_project_config(folder / "project.yaml"), name="read project config"
    )


def estimate_jev(messages: Messages, folder: Path) -> Outcome[AiPrefilterEstimate]:
    """The cost estimate shown before a Jev pre-filter run starts (ADR 0029)."""
    return guarded(
        messages, lambda: estimate_ai_prefilter(Workspace.open(folder)), name="estimate jev"
    )


def run_jev_prefilter(messages: Messages, folder: Path) -> Outcome[AiPrefilterSummary]:
    """Run the Jev pre-filter once, synchronously (it is fast/cheap; no background process)."""
    return guarded(
        messages, lambda: ai_prefilter_project(Workspace.open(folder)), name="jev pre-filter"
    )


def screen_output_tail(folder: Path, lines: int = 20) -> str:
    """The last lines the screening process printed (empty if there are none)."""
    try:
        text = (Workspace(folder).state_dir / SCREEN_OUTPUT).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


# --- project definition and files ----------------------------------------------------------------


def load_definition(messages: Messages, folder: Path) -> Outcome[Definition]:
    """Description, research questions and criteria in force."""
    return guarded(
        messages, lambda: definition_module.load_definition(folder), name="load definition"
    )


def save_definition(messages: Messages, folder: Path, definition: Definition) -> Outcome[None]:
    """Store a definition in the overrides file (``project.yaml`` stays as it is).

    Raises nothing: invalid input becomes an error report and nothing is written.
    """

    def work() -> None:
        workspace = Workspace.open(folder)
        values = definition_module.to_settings(definition)
        with workspace.lock():
            set_values(workspace.project_yaml, values)
        logger.info("Project definition saved (%s)", definition.framework)

    return guarded(messages, work, name="save definition")


def criteria_filled(folder: Path) -> int:
    """How many framework elements have an inclusion criterion (0 if unreadable)."""
    try:
        current = definition_module.load_definition(folder)
        elements = definition_module.framework_elements(current.framework, current.custom_fields)
    except SaraError:
        return 0
    return sum(1 for name in elements if current.inclusion.get(name, "").strip())


def list_exports(folder: Path) -> list[Path]:
    """Files in the project's export folder, newest first (empty if there is none)."""
    exports = Workspace(folder).exports_dir
    try:
        files = [p for p in exports.iterdir() if p.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def import_history(folder: Path) -> list[Any]:
    """The files imported so far (oldest first); empty if the project cannot be read."""
    try:
        return list(project_status(folder).imports)
    except SaraError:
        return []


# --- evaluation ---------------------------------------------------------------------


def load_results(
    messages: Messages, folder: Path, run_id: str | None
) -> Outcome[list[dict[str, Any]]]:
    """The results table of a run of the project (the newest one if ``run_id`` is None)."""
    return guarded(
        messages, lambda: results_table(Workspace(folder), run_id)[1], name="load results"
    )


def read_results_file(messages: Messages, name: str, data: bytes) -> Outcome[list[dict[str, Any]]]:
    """A results table from an uploaded CSV or XLSX file (checked; nothing is stored)."""
    return guarded(messages, lambda: read_table_file(name, data), name="read results file")


def compare_runs(
    messages: Messages, folder: Path, run_ids: list[str]
) -> Outcome[tuple[list[dict[str, Any]], ComparisonSummary]]:
    """Join and compare several finished runs of the project (plan chapter 14.1)."""
    return guarded(
        messages, lambda: compare_runs_service(Workspace(folder), run_ids), name="compare runs"
    )
