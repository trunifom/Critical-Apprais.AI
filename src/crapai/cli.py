"""Command line of Critical Apprais.AI: init, import, status (plan chapters 15.1 and 27.10).

This is the only module (besides a future UI) that talks to the user. All work happens in the
service layer; this module parses arguments, chooses the language, prints results and turns
errors into exit codes:

* 0 = ok, 1 = user error (input, configuration), 2 = system error (file, lock, disk),
* 4 = result with warnings (for example records without abstracts).

``--json`` prints machine-readable results on stdout; all messages then go to stderr.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import logging
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from crapai import __version__
from crapai.branding import CLI_NAME, PRODUCT_NAME
from crapai.cli_progress import ProgressPrinter
from crapai.config.overrides import effective_settings, reset_values, set_values
from crapai.cost.duration import Confirmation, decide_confirmation, format_duration
from crapai.errors import UNEXPECTED_ERROR_CODE, ConfigError, SaraError
from crapai.i18n.messages import Messages, resolve_language
from crapai.logging_setup import attach_project_log, enable_console_log
from crapai.project.lock import pid_alive
from crapai.project.workspace import Workspace, cloud_sync_marker
from crapai.screening.store import RunStore
from crapai.services import resolution as resolution_service
from crapai.services import screening as screening_service
from crapai.services.cost import ProjectEstimate, estimate_project
from crapai.services.dedup import dedup_project
from crapai.services.export import (
    ExportSummary,
    export_flow,
    export_records,
)
from crapai.services.importing import ImportRequest, ImportSummary, import_source
from crapai.services.preflight import ProjectReport, check_project
from crapai.services.project import DEFAULT_TEMPLATE, create_project, project_status
from crapai.services.results import compare_runs, export_comparison, export_results
from crapai.stats.agreement import ComparisonSummary
from crapai.ui.context import PROJECT_ENV

logger = logging.getLogger("crapai.cli")

_verbose = False  # set by --verbose; read when the project log is attached

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SYSTEM_ERROR = 2
EXIT_INTERRUPTED = 3  # a run was paused or interrupted; it can be resumed
EXIT_WARNINGS = 4

# Preflight findings that stop the run (shown in red); all others are warnings (yellow).
BLOCKING = frozenset({"no_records", "nothing_to_screen"})
STRATEGIES = ("doi_or_title", "strict_ids", "title", "title_authors")
KEEP_RULES = ("best", "first", "last")

# Errors caused by the environment, not by the input (plan chapter 15.1: exit code 2).
# E404/E405 are deliberately NOT here even though they also cover "damaged file": in practice
# they most often mean "wrong path" / "already a project" (a user mistake), and 9 existing tests
# (test_cli_basic.py, test_check_command.py, test_export.py, ...) codify exit 1 for exactly that.
# Reclassifying them would fix a rare "corrupted file after a crash" case at the cost of breaking
# the common one; not worth it without a way to tell the two apart at this layer.
SYSTEM_ERROR_CODES = frozenset({"E401", "E402", "E403", UNEXPECTED_ERROR_CODE})
COMMAND = CLI_NAME

app = typer.Typer(
    name=COMMAND,
    help=f"{PRODUCT_NAME}: AI-assisted title/abstract screening for systematic reviews. "
    "Results are proposals for human review.",
    no_args_is_help=True,
    add_completion=False,
)

LangOption = Annotated[
    str | None, typer.Option("--lang", help="Message language: en or de (default: from project).")
]
JsonOption = Annotated[
    bool, typer.Option("--json", help="Print the result as JSON on stdout (messages to stderr).")
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{PRODUCT_NAME} {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", "-v", help="Also print detailed log lines (DEBUG) to the screen (stderr)."
        ),
    ] = False,
) -> None:
    """Project commands (init, import, status, dedup, check, export, unlock)."""
    global _verbose  # noqa: PLW0603 - the option is read later by _setup_file_log
    _verbose = verbose
    if verbose:
        enable_console_log(logging.DEBUG)


# --- helpers ----------------------------------------------------------------------------------


def _echo(message: str, *, json_mode: bool, colour: str | None = None) -> None:
    """Print a human message (stderr in JSON mode so stdout stays machine-readable)."""
    typer.secho(message, fg=colour, err=json_mode)


def _setup_file_log(folder: Path, messages: Messages) -> None:
    """Log to ``.crapai/app.log`` of the project (see :mod:`crapai.logging_setup`)."""
    problem = attach_project_log(folder, level=logging.DEBUG if _verbose else None)
    if problem:
        # A read-only share or a log held by another program must not stop the command itself.
        typer.secho(messages.text("cli.setup.log_warning", problem=problem), fg="yellow", err=True)


def error_json(error: Exception) -> dict[str, Any]:
    """The error as a JSON-able dictionary (code, message, hint); no details, no record content."""
    if isinstance(error, SaraError):
        return {"code": error.code, "message": error.user_message, "hint": error.hint}
    return {"code": UNEXPECTED_ERROR_CODE, "message": type(error).__name__, "hint": None}


def _interactive() -> bool:
    """True if the user can be asked a question (stdin is a terminal)."""
    return sys.stdin.isatty()


def _fail(error: Exception, messages: Messages, *, json_mode: bool) -> typer.Exit:
    """Report ``error`` (log, stderr, and in JSON mode also stdout) and return the exit for it.

    The caller raises the returned exit. Only the code and the message are logged: the error's
    ``details`` may hold paths and must never hold record content.
    """
    if isinstance(error, SaraError):
        code = EXIT_SYSTEM_ERROR if error.code in SYSTEM_ERROR_CODES else EXIT_USER_ERROR
        lines = messages.error_lines(error)
        logger.error("%s: %s", error.code, error.user_message)
    else:
        logger.exception("Unexpected error")
        code = EXIT_SYSTEM_ERROR
        lines = [
            f"{messages.text('cli.error.prefix', code=UNEXPECTED_ERROR_CODE)}: "
            f"{messages.text('cli.error.unexpected')}",
            f"{messages.text('cli.error.details')}: {type(error).__name__}",
        ]
    for line in lines:
        typer.secho(line, fg="red", err=True)
    if json_mode:
        typer.echo(json.dumps({"error": error_json(error)}, ensure_ascii=False, indent=2))
    return typer.Exit(code)


def _parse_mapping(pairs: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in pairs:
        target, sep, column = pair.partition("=")
        if not sep or not target.strip() or not column.strip():
            raise ConfigError(
                f"Invalid --map value '{pair}': expected target=<column>",
                code="E203",
                hint="Example: --map abstract=Zusammenfassung",
            )
        mapping[target.strip()] = column.strip()
    return mapping


def _labels_for(files: list[Path], labels: list[str]) -> list[str | None]:
    if not labels:
        return [None] * len(files)
    if len(labels) == 1:
        return [labels[0]] * len(files)
    if len(labels) != len(files):
        raise ConfigError(
            f"{len(labels)} --label values for {len(files)} files",
            code="E203",
            hint="Give one --label for all files, or exactly one per file, in the same order.",
        )
    return list(labels)


def _summary_json(summary: ImportSummary) -> dict[str, Any]:
    return {
        "source_file": summary.source_file,
        "source_label": summary.source_label,
        "format": summary.format,
        "format_reason": summary.format_reason,
        "sha256": summary.sha256,
        "records": summary.records,
        "abstracts": summary.abstracts,
        "empty_records": summary.empty_records,
        "total_records": summary.total_records,
        "encoding": summary.encoding,
        "column_map": summary.column_map,
        "mapping_source": summary.mapping_source,
        "notes": list(summary.notes),
        "warnings": list(summary.warnings),
    }


# --- commands ---------------------------------------------------------------------------------


@app.command("init")
def init_command(
    folder: Annotated[Path, typer.Argument(help="New project folder (must be new or empty).")],
    from_template: Annotated[
        str,
        typer.Option("--from-template", help="Template name (blank, demo) or path of a YAML file."),
    ] = DEFAULT_TEMPLATE,
    title: Annotated[str | None, typer.Option(help="Project title (default: folder name).")] = None,
    lang: LangOption = None,
) -> None:
    """Create a project folder with a project.yaml.

    Example: crapai init my-review --from-template demo
    """
    messages = Messages(resolve_language(lang))
    try:
        workspace = create_project(folder, template=from_template, title=title)
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    _setup_file_log(workspace.root, messages)
    logger.info("Created project %s from template %s", workspace.root.name, from_template)
    typer.secho(messages.text("cli.init.done", path=workspace.root), fg="green")
    marker = cloud_sync_marker(workspace.root)
    if marker:
        typer.secho(messages.text("cli.init.sync_warning", marker=marker), fg="yellow", err=True)
    typer.echo(messages.text("cli.init.next"))
    typer.echo(messages.text("cli.init.example", command=COMMAND, path=folder))


@app.command("import")
def import_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    files: Annotated[list[Path], typer.Argument(help="Export files (RIS, NBIB, ...).")],
    label: Annotated[
        list[str] | None,
        typer.Option("--label", help="Source name; once for all files or once per file."),
    ] = None,
    map_: Annotated[
        list[str] | None,
        typer.Option("--map", help="Table column: target=<column>, e.g. abstract=Summary."),
    ] = None,
    encoding: Annotated[str | None, typer.Option(help="Force a text encoding (cp1252).")] = None,
    delimiter: Annotated[str | None, typer.Option(help="Force the CSV field separator.")] = None,
    sheet: Annotated[str | None, typer.Option(help="Worksheet name for XLSX files.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Import files seen before again.")] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Import bibliographic exports into the project (records are added, never deleted).

    Example: crapai import my-review pubmed.ris embase.bib --label PubMed --label Embase
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    results: list[dict[str, Any]] = []
    exit_code = EXIT_OK
    try:
        mapping = _parse_mapping(map_ or [])
        labels = _labels_for(files, label or [])
        for path, file_label in zip(files, labels, strict=True):
            request = ImportRequest(
                path,
                label=file_label,
                encoding=encoding,
                delimiter=delimiter,
                sheet=sheet,
                mapping=mapping,
                force=force,
            )
            summary = import_source(Workspace(folder), request)
            results.append(_summary_json(summary))
            _print_import(summary, messages, json_mode=as_json)
            if summary.warnings:
                exit_code = EXIT_WARNINGS
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        if as_json:  # one JSON document: what was imported before the failure, and the failure
            document = {"imported": results, "error": error_json(error)}
            typer.echo(json.dumps(document, ensure_ascii=False, indent=2))
        raise _fail(error, messages, json_mode=False) from error
    if as_json:
        typer.echo(json.dumps({"imported": results}, ensure_ascii=False, indent=2))
    raise typer.Exit(exit_code)


def _print_import(summary: ImportSummary, messages: Messages, *, json_mode: bool) -> None:
    _echo(
        messages.text(
            "cli.import.done",
            records=summary.records,
            file=summary.source_file,
            label=summary.source_label,
            abstracts=summary.abstracts,
            total=summary.total_records,
        ),
        json_mode=json_mode,
        colour="green",
    )
    _echo(
        messages.text("cli.import.format", format=summary.format, reason=summary.format_reason),
        json_mode=json_mode,
    )
    if summary.encoding:
        _echo(messages.text("cli.import.encoding", encoding=summary.encoding), json_mode=json_mode)
    if summary.column_map:
        used = ", ".join(f"{target}={column}" for target, column in summary.column_map.items())
        from_project = summary.mapping_source == "project"
        key = "cli.import.mapping_project" if from_project else "cli.import.mapping"
        _echo(messages.text(key, mapping=used), json_mode=json_mode)
    for note in summary.notes:
        _echo(messages.text("cli.import.note", note=note), json_mode=json_mode)
    for warning in summary.warnings:
        _echo(
            messages.text(f"cli.warning.{warning}", count=summary.empty_records),
            json_mode=json_mode,
            colour="yellow",
        )


@app.command("status")
def status_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Show what the project contains: records, sources and configuration state.

    Example: crapai status my-review
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        status = project_status(folder)
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "folder": str(status.root),
                    "title": status.title,
                    "schema_version": status.schema_version,
                    "records": status.records,
                    "with_abstract": status.with_abstract,
                    "empty_records": status.empty_records,
                    "duplicates": status.duplicates,
                    "sources": status.per_source,
                    "configuration_ok": status.config_ok,
                    "configuration_problem": status.config_problem,
                    "in_use": status.in_use,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(messages.text("cli.status.title", title=status.title or folder.name))
    typer.echo(messages.text("cli.status.folder", path=status.root))
    typer.echo(
        messages.text(
            "cli.status.records",
            records=status.records,
            abstracts=status.with_abstract,
            empty=status.empty_records,
            duplicates=status.duplicates,
        )
    )
    if status.per_source:
        typer.echo(messages.text("cli.status.sources"))
        for source_label, count in status.per_source.items():
            typer.echo(messages.text("cli.status.source_line", label=source_label, count=count))
    else:
        typer.echo(messages.text("cli.status.no_records", command=COMMAND))
    if status.config_ok:
        typer.secho(messages.text("cli.status.config_ok"), fg="green")
    else:
        first_line = next(iter((status.config_problem or "").splitlines()), "")
        typer.secho(messages.text("cli.status.config_problem", problem=first_line), fg="yellow")
    if status.in_use:
        typer.secho(messages.text("cli.status.in_use"), fg="yellow")


@app.command("dedup")
def dedup_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    strategy: Annotated[
        str | None,
        typer.Option(help="doi_or_title, strict_ids, title, title_authors (default: project)."),
    ] = None,
    keep: Annotated[str, typer.Option(help="Record left unmarked: best, first, last.")] = "best",
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Mark duplicate records (nothing is deleted; earlier marks are recomputed).

    Example: crapai dedup my-review --strategy title
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        if strategy is not None and strategy not in STRATEGIES:
            raise ConfigError(
                f"Unknown strategy '{strategy}' (valid: {', '.join(STRATEGIES)})", code="E203"
            )
        if keep not in KEEP_RULES:
            raise ConfigError(
                f"Unknown keep rule '{keep}' (valid: {', '.join(KEEP_RULES)})", code="E203"
            )
        summary = dedup_project(
            Workspace(folder),
            strategy=strategy,  # type: ignore[arg-type]
            keep=keep,  # type: ignore[arg-type]
        )
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    exit_code = EXIT_OK if summary.events_written else EXIT_WARNINGS
    if as_json:
        typer.echo(json.dumps(dataclasses.asdict(summary), ensure_ascii=False, indent=2))
        raise typer.Exit(exit_code)
    if not summary.events_written:
        typer.secho(messages.text("cli.warning.events_not_written"), fg="yellow", err=True)
    source = messages.text(f"cli.dedup.source.{summary.strategy_source}")
    if summary.marked == 0:
        typer.echo(messages.text("cli.dedup.none", strategy=summary.strategy, source=source))
        raise typer.Exit(exit_code)
    typer.secho(
        messages.text(
            "cli.dedup.done",
            marked=summary.marked,
            records=summary.records,
            groups=summary.groups,
            strategy=summary.strategy,
            source=source,
        ),
        fg="green",
    )
    methods = ", ".join(f"{name}: {count}" for name, count in sorted(summary.by_method.items()))
    typer.echo(messages.text("cli.dedup.methods", methods=methods))
    typer.echo(
        messages.text(
            "cli.dedup.sources",
            within=sum(summary.within_source.values()),
            across=summary.across_sources,
        )
    )
    raise typer.Exit(exit_code)


@app.command("check")
def check_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    read_only: Annotated[
        bool,
        typer.Option("--read-only", help="Do not recalculate duplicates and validity first."),
    ] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Preflight: mark duplicates and unusable records, then report what would go to the model.

    Exit code 0 = ready, 4 = warnings, 1 = nothing can be screened.
    Example: crapai check my-review
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        report = check_project(Workspace(folder), update=not read_only)
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    estimate, estimate_problem = _estimate_for(folder, report)
    if as_json:
        data = _report_json(report)
        data["estimate"] = _estimate_json(estimate)
        data["estimate_problem"] = estimate_problem
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_report(report, messages)
        _print_estimate(estimate, estimate_problem, messages)
    status = report.status.value
    if status == "ok" and (estimate_problem or (estimate and estimate.over_limit)):
        status = "warning"
    raise typer.Exit({"ok": EXIT_OK, "warning": EXIT_WARNINGS, "error": EXIT_USER_ERROR}[status])


def _estimate_for(folder: Path, report: ProjectReport) -> tuple[ProjectEstimate | None, str | None]:
    """The cost estimate, or ``(None, problem)`` if it cannot be made; none if nothing is sent."""
    if report.valid_for_model == 0:
        return None, None
    try:
        return estimate_project(Workspace(folder)), None
    except SaraError as error:
        logger.warning("Cost estimate not available: %s", error.code)
        return None, f"{error.code}: {error.user_message}"
    except Exception as error:  # noqa: BLE001 - the estimate is optional; the report stands
        logger.exception("Cost estimate failed")
        return None, f"{UNEXPECTED_ERROR_CODE}: {type(error).__name__}"


def _estimate_json(estimate: ProjectEstimate | None) -> dict[str, Any] | None:
    if estimate is None:
        return None
    run = estimate.estimate
    return {
        "provider": estimate.provider,
        "model": estimate.model,
        "records": run.n_items,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "tokenizer": run.tokenizer,
        "tokens_exact": run.exact,
        "currency": run.currency,
        "cost": run.cost,
        "cost_low": run.cost_low,
        "cost_high": run.cost_high,
        "cost_max": run.cost_max,
        "price_valid_from": run.price.valid_from if run.price else None,
        "max_cost": estimate.max_cost,
        "over_limit": estimate.over_limit,
        "duration_seconds": math.ceil(estimate.duration.seconds),
        "duration_limited_by": estimate.duration.limited_by,
    }


def _print_estimate(
    estimate: ProjectEstimate | None, problem: str | None, messages: Messages
) -> None:
    if problem:
        typer.secho(messages.text("cli.check.cost.error", problem=problem), fg="yellow")
    if estimate is None:
        return
    run = estimate.estimate
    typer.echo(
        messages.text("cli.check.cost.model", provider=estimate.provider, model=estimate.model)
    )
    kind = messages.text("cli.check.cost.exact" if run.exact else "cli.check.cost.approximate")
    typer.echo(
        messages.text(
            "cli.check.cost.tokens", input=run.input_tokens, output=run.output_tokens, kind=kind
        )
    )
    if run.cost is None:
        typer.echo(messages.text("cli.check.cost.no_price"))
    else:
        typer.echo(
            messages.text(
                "cli.check.cost.cost",
                low=f"{run.cost_low:.4f}",
                high=f"{run.cost_high:.4f}",
                worst=f"{run.cost_max:.4f}",
                currency=run.currency,
                valid=(run.price.valid_from if run.price and run.price.valid_from else "?"),
            )
        )
    typer.echo(
        messages.text(
            "cli.check.cost.duration",
            duration=format_duration(estimate.duration.seconds),
            limit=messages.text(f"cli.check.cost.limit.{estimate.duration.limited_by}"),
        )
    )
    if estimate.over_limit:
        typer.secho(
            messages.text("cli.check.cost.over_limit", max_cost=estimate.max_cost), fg="yellow"
        )


def _report_json(report: ProjectReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "issues": [issue.value for issue in report.issues],
        "records": report.records,
        "duplicates": report.duplicates,
        "valid_for_model": report.valid_for_model,
        "by_reason": report.by_reason,
        "abstract_quality": report.quality,
        "retracted_included": report.retracted_included,
        "configuration_problem": report.config_problem,
        "updated": report.updated,
        "sources": [
            {
                "label": s.label,
                "records": s.records,
                "with_abstract": s.with_abstract,
                "duplicates": s.duplicates,
                "valid_for_model": s.valid_for_model,
                "status": s.status.value,
                "issues": [issue.value for issue in s.issues],
            }
            for s in report.sources
        ],
    }


def _print_report(report: ProjectReport, messages: Messages) -> None:
    colour = {"ok": "green", "warning": "yellow", "error": "red"}[report.status.value]
    typer.secho(messages.text(f"cli.check.status.{report.status.value}"), fg=colour, bold=True)
    typer.echo(
        messages.text(
            "cli.check.totals",
            records=report.records,
            duplicates=report.duplicates,
            valid=report.valid_for_model,
        )
    )
    if report.sources:
        typer.echo(messages.text("cli.check.sources"))
        for source in report.sources:
            percent = round(100 * source.with_abstract / source.records)
            typer.echo(
                messages.text(
                    "cli.check.source_line",
                    label=source.label,
                    records=source.records,
                    abstracts=source.with_abstract,
                    percent=percent,
                    duplicates=source.duplicates,
                    valid=source.valid_for_model,
                )
            )
    if report.by_reason:
        typer.echo(messages.text("cli.check.reasons"))
        for reason, count in sorted(report.by_reason.items()):
            meaning = messages.text(f"cli.check.reason.{reason}")
            typer.echo(
                messages.text("cli.check.reason_line", reason=reason, count=count, meaning=meaning)
            )
    if report.quality:
        typer.echo(
            messages.text(
                "cli.check.quality",
                ok=report.quality.get("ok", 0),
                short=report.quality.get("short", 0),
                suspect=report.quality.get("suspect_concat", 0),
            )
        )
    for issue in report.issues:
        typer.secho(
            messages.text(
                f"cli.check.issue.{issue.value}",
                suspect=report.quality.get("suspect_concat", 0),
                retracted=report.retracted_included,
                problem=report.config_problem or "",
            ),
            fg="red" if report.status.value == "error" and issue.value in BLOCKING else "yellow",
        )
    typer.echo(messages.text("cli.check.updated" if report.updated else "cli.check.read_only"))


config_app = typer.Typer(
    help="Show or change the settings of a project without editing project.yaml.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


def _parse_assignments(pairs: list[str]) -> dict[str, Any]:
    """Turn ``["llm.model=gpt-4o", ...]`` into ``{"llm.model": "gpt-4o", ...}``."""
    parsed: dict[str, Any] = {}
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        if not separator or not key.strip():
            raise ConfigError(
                f"Invalid setting '{pair}': expected section.key=value",
                code="E203",
                hint="Example: crapai config set my-review llm.model=gpt-4o",
            )
        try:
            parsed[key.strip()] = yaml.safe_load(raw)
        except yaml.YAMLError:
            parsed[key.strip()] = raw
    return parsed


@config_app.command("show")
def config_show(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    as_json: JsonOption = False,
    only_changed: Annotated[
        bool, typer.Option("--changed", help="Only settings changed outside project.yaml.")
    ] = False,
    lang: LangOption = None,
) -> None:
    """Show every setting with its value and where the value comes from.

    Sources: overrides (this command or the interface), environment, project (project.yaml),
    user (user configuration) or default.
    Example: crapai config show my-review --changed
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        settings = effective_settings(Workspace.open(folder).project_yaml)
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    if only_changed:
        settings = [s for s in settings if s.source in ("overrides", "environment", "user")]
    if as_json:
        rows = [{"key": s.key, "value": s.value, "source": s.source} for s in settings]
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    width = max((len(s.key) for s in settings), default=0)
    for setting in settings:
        source = messages.text(f"cli.config.source.{setting.source}")
        typer.echo(f"{setting.key.ljust(width)} = {setting.value!r}   [{source}]")


@config_app.command("set")
def config_set(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    assignments: Annotated[list[str], typer.Argument(help="section.key=value, one or more.")],
    lang: LangOption = None,
) -> None:
    """Change settings; they are checked first and kept in project.overrides.yaml.

    project.yaml is not touched (its comments stay). Undo with: crapai config reset.
    Example: crapai config set my-review quality.short_abstract_words=30 limits.rpm=200
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        workspace = Workspace.open(folder)
        values = _parse_assignments(assignments)
        with workspace.lock():
            set_values(workspace.project_yaml, values)
        logger.info("Changed setting(s): %s", ", ".join(sorted(values)))
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    for key in sorted(values):
        typer.secho(messages.text("cli.config.set_done", name=key, value=values[key]), fg="green")


@config_app.command("reset")
def config_reset(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    keys: Annotated[
        list[str] | None, typer.Argument(help="Settings to reset (default: all).")
    ] = None,
    lang: LangOption = None,
) -> None:
    """Undo changes made with `config set` or in the interface (back to project.yaml).

    Example: crapai config reset my-review limits.rpm
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        workspace = Workspace.open(folder)
        with workspace.lock():
            removed = reset_values(workspace.project_yaml, keys or None)
        logger.info("Reset %d setting(s)", len(removed))
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    if not removed:
        typer.echo(messages.text("cli.config.reset_none"))
        return
    typer.secho(messages.text("cli.config.reset_done", count=len(removed)), fg="green")


@app.command("export")
def export_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    what: Annotated[
        str, typer.Option("--what", help="records, results (screening results) or flow.")
    ] = "records",
    fmt: Annotated[str, typer.Option("--format", help="csv, xlsx or ris (records only).")] = "csv",
    scope: Annotated[
        str, typer.Option(help="all, screenable (go to the model) or excluded (have a reason).")
    ] = "all",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Target file (default: exports/ in the project)."),
    ] = None,
    delimiter: Annotated[
        str, typer.Option(help="CSV separator, for example ; for German Excel.")
    ] = ",",
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Do not protect cells that start like a spreadsheet formula."),
    ] = False,
    mode: Annotated[
        str | None, typer.Option(help="Flow only: all_before_screening or between_databases_only.")
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Results only: the run (default: the newest with results)."),
    ] = None,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Export the records (CSV, XLSX, RIS), the screening results (CSV, XLSX) or the PRISMA flow.

    The project is not changed. A target that is open in Excel is not overwritten: the export is
    saved under a timestamped name and the exit code is 4.
    Example: crapai export my-review --format xlsx --scope screenable
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        if what not in ("records", "results", "flow"):
            raise ConfigError(
                f"Unknown --what '{what}' (valid: records, results, flow)", code="E203"
            )
        separator = {"tab": "\t", "semicolon": ";", "comma": ","}.get(delimiter.lower(), delimiter)
        if what == "flow":
            summary = export_flow(Workspace(folder), output=output, mode=mode)
        elif what == "results":
            summary = export_results(
                Workspace(folder),
                fmt,
                run_id=run_id,
                output=output,
                delimiter=separator,
                guard_formulas=not raw,
            )
        else:
            summary = export_records(
                Workspace(folder),
                fmt,
                scope=scope,
                output=output,
                delimiter=separator,
                guard_formulas=not raw,
            )
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    if as_json:
        data = {**dataclasses.asdict(summary), "path": str(summary.path)}
        data["requested_path"] = str(summary.requested_path)
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_export(summary, messages)
    raise typer.Exit(EXIT_WARNINGS if summary.used_alternative else EXIT_OK)


def _print_export(summary: ExportSummary, messages: Messages) -> None:
    if summary.what == "flow":
        typer.secho(messages.text("cli.export.done_flow", path=summary.path), fg="green")
    else:
        typer.secho(
            messages.text(
                "cli.export.done",
                records=summary.records,
                scope=summary.scope,
                format=summary.format,
                path=summary.path,
            ),
            fg="green",
        )
    if summary.used_alternative:
        typer.secho(
            messages.text("cli.export.alternative", wanted=summary.requested_path.name),
            fg="yellow",
            err=True,
        )


@app.command("compare-runs")
def compare_runs_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    runs: Annotated[str, typer.Option("--runs", help="Two or more run ids, comma separated.")],
    fmt: Annotated[str, typer.Option("--format", help="csv or xlsx.")] = "csv",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Target file (default: exports/ in the project)."),
    ] = None,
    delimiter: Annotated[
        str, typer.Option(help="CSV separator, for example ; for German Excel.")
    ] = ",",
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Do not protect cells that start like a spreadsheet formula."),
    ] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Compare two or more screening runs: agreement, Cohen's/Fleiss' kappa, unstable records.

    Test-retest or a model comparison (plan chapter 14.1): screen the same records several times
    with separate 'crapai screen' calls (the same model again, or a different one each time), then
    compare the finished runs. Writes the joined table to exports/ (one row per record, one column
    group per run) and prints the agreement numbers; nothing in the project is changed.
    Exit code 0 = ok, 4 = the target file was locked (saved under another name), 1 = user error
    (fewer than two runs, an unknown run), 2 = system error.
    Example: crapai compare-runs my-review --runs run-001,run-002,run-003
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    run_ids = [r.strip() for r in runs.split(",") if r.strip()]
    try:
        separator = {"tab": "\t", "semicolon": ";", "comma": ","}.get(delimiter.lower(), delimiter)
        _, agreement_summary = compare_runs(Workspace(folder), run_ids)
        summary = export_comparison(
            Workspace(folder),
            run_ids,
            fmt,
            output=output,
            delimiter=separator,
            guard_formulas=not raw,
        )
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    if as_json:
        data = {
            "run_ids": list(agreement_summary.run_ids),
            "n_common": agreement_summary.n_common,
            "fleiss_kappa": agreement_summary.fleiss_kappa,
            "fleiss_label": agreement_summary.fleiss_label,
            "unstable": len(agreement_summary.unstable),
            "pairwise": [dataclasses.asdict(p) for p in agreement_summary.pairwise],
            "path": str(summary.path),
        }
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        raise typer.Exit(EXIT_WARNINGS if summary.used_alternative else EXIT_OK)
    _print_compare(agreement_summary, summary, messages)
    raise typer.Exit(EXIT_WARNINGS if summary.used_alternative else EXIT_OK)


def _print_compare(
    agreement_summary: ComparisonSummary, summary: ExportSummary, messages: Messages
) -> None:
    typer.secho(
        messages.text("cli.compare.done", records=summary.records, path=summary.path), fg="green"
    )
    for pair in agreement_summary.pairwise:
        typer.echo(
            messages.text(
                "cli.compare.pair",
                run_a=pair.run_a,
                run_b=pair.run_b,
                n=pair.n,
                agreement=f"{pair.agreement * 100:.1f}",
                kappa=f"{pair.kappa:.3f}" if pair.kappa is not None else "-",
                label=pair.label or "-",
            )
        )
    if agreement_summary.fleiss_kappa is not None:
        typer.echo(
            messages.text(
                "cli.compare.fleiss",
                n=agreement_summary.n_common,
                kappa=f"{agreement_summary.fleiss_kappa:.3f}",
                label=agreement_summary.fleiss_label,
            )
        )
    typer.echo(messages.text("cli.compare.unstable", count=len(agreement_summary.unstable)))
    if summary.used_alternative:
        typer.secho(
            messages.text("cli.export.alternative", wanted=summary.requested_path.name),
            fg="yellow",
            err=True,
        )


def _confirm_resolution(count: int, messages: Messages, *, as_json: bool) -> None:
    """Show how many records are disputed, and ask (plan 8.5's rule, reused here)."""
    _echo(messages.text("cli.resolve.disputed", count=count), json_mode=as_json)
    decision = decide_confirmation(yes=False, interactive=_interactive())
    if decision is Confirmation.REFUSE:
        typer.secho(messages.text("cli.resolve.declined"), fg="yellow", err=True)
        raise typer.Exit(EXIT_USER_ERROR)
    if not typer.confirm(messages.text("cli.resolve.confirm"), err=as_json):
        typer.echo(messages.text("cli.resolve.declined"), err=True)
        raise typer.Exit(EXIT_USER_ERROR)


def _resolution_exit_code(manifest: Any) -> int:
    state = manifest.state
    if state == "completed":
        ok = manifest.counts.get("ok", 0)
        done = manifest.counts.get("done", 0)
        return EXIT_WARNINGS if ok < done else EXIT_OK
    if state in ("paused", "interrupted"):
        return EXIT_INTERRUPTED
    code = manifest.last_error.get("code", "")
    return EXIT_SYSTEM_ERROR if code in SYSTEM_ERROR_CODES else EXIT_USER_ERROR


def _print_resolution_result(
    result: resolution_service.ResolutionResult,
    folder: Path,
    runs: str,
    messages: Messages,
    *,
    as_json: bool,
) -> int:
    manifest = result.manifest
    code = _resolution_exit_code(manifest)
    run_folder_path = Workspace(folder).runs_dir / result.run_id
    if as_json:
        rows = RunStore(run_folder_path).read_results()
        cost = sum((r.cost or 0.0) for r in rows if r.cost is not None)
        typer.echo(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "method": manifest.kind,
                    "state": manifest.state,
                    "resumed": result.resumed,
                    "done": manifest.counts.get("done", 0),
                    "total": manifest.counts.get("total", 0),
                    "ok": manifest.counts.get("ok", 0),
                    "cost": round(cost, 6) if any(r.cost is not None for r in rows) else None,
                    "tokens_in": sum(r.tokens_in for r in rows),
                    "tokens_out": sum(r.tokens_out for r in rows),
                    "stop_reason": manifest.stop_reason,
                    "last_error": manifest.last_error,
                    "warnings": manifest.warnings,
                    "folder": str(run_folder_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    colour = {"completed": "green", "paused": "yellow", "interrupted": "yellow"}.get(
        manifest.state, "red"
    )
    typer.secho(
        messages.text(
            f"cli.resolve.result.{manifest.state}",
            run_id=result.run_id,
            done=manifest.counts.get("done", 0),
            total=manifest.counts.get("total", 0),
            ok=manifest.counts.get("ok", 0),
        ),
        fg=colour,
        bold=True,
        err=as_json,
    )
    if manifest.last_error:
        typer.secho(
            messages.text(
                "cli.resolve.error_line",
                code=manifest.last_error.get("code", ""),
                message=manifest.last_error.get("message", ""),
            ),
            fg=colour,
            err=True,
        )
    results_file = run_folder_path / "screening.jsonl"
    _echo(messages.text("cli.resolve.files", path=results_file), json_mode=as_json)
    if manifest.state != "completed":
        _echo(
            messages.text(
                "cli.resolve.resume_hint",
                command=COMMAND,
                method=manifest.kind,
                folder=folder,
                runs=runs,
                run_id=result.run_id,
            ),
            json_mode=as_json,
        )
    return code


@app.command("adjudicate")
def adjudicate_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    runs: Annotated[str, typer.Option("--runs", help="Two or more run ids, comma separated.")],
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resolution run to continue.")
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Start without asking for confirmation.")
    ] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Settle every disagreement between two or more finished runs with one master call each.

    The master uses the project's current llm: settings (set them first, like for any other
    run); it sees the record, the criteria and every disagreeing run's decision and reasoning, and
    decides once, for itself. Only the disputed records are sent. The result is its own run (see
    'crapai runs'); records.csv is never touched.
    Exit code 0 = completed, 4 = completed with failed records, 3 = paused or interrupted
    (resumable with --resume), 1 = user error (bad input), 2 = system error.
    Example: crapai adjudicate my-review --runs run-001,run-002
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    run_ids = [r.strip() for r in runs.split(",") if r.strip()]
    workspace = Workspace(folder)
    try:
        if resume is None and not yes:
            count = len(resolution_service.disputed_items(workspace, run_ids))
            _confirm_resolution(count, messages, as_json=as_json)
        result = resolution_service.adjudicate_project(
            workspace, run_ids, resolution_service.ResolutionOptions(resume=resume)
        )
    except typer.Exit:
        raise
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    code = _print_resolution_result(result, folder, runs, messages, as_json=as_json)
    raise typer.Exit(code)


@app.command("discuss")
def discuss_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    runs: Annotated[str, typer.Option("--runs", help="Two or more run ids, comma separated.")],
    max_rounds: Annotated[
        int | None,
        typer.Option("--max-rounds", min=1, help="Overrides discussion.max_rounds."),
    ] = None,
    tie_break: Annotated[
        str | None,
        typer.Option(
            "--tie-break", help="majority or no_consensus; overrides discussion.tie_break."
        ),
    ] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resolution run to continue.")
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Start without asking for confirmation.")
    ] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Settle every disagreement between two or more finished runs by letting their own models
    reconsider, seeing each other's decision and reasoning, for up to discussion.max_rounds rounds.

    Each run is called with the model it originally used (read from its own manifest, not the
    project's current llm: settings, which may since have moved on). Without consensus,
    discussion.tie_break decides: the majority, or NO_CONSENSUS. Only the disputed records are
    sent. The result is its own run (see 'crapai runs'); records.csv is never touched.
    Exit code 0 = completed, 4 = completed with failed records, 3 = paused or interrupted
    (resumable with --resume), 1 = user error (bad input), 2 = system error.
    Example: crapai discuss my-review --runs run-001,run-002,run-003 --max-rounds 3
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    run_ids = [r.strip() for r in runs.split(",") if r.strip()]
    workspace = Workspace(folder)
    try:
        if tie_break is not None and tie_break not in ("majority", "no_consensus"):
            raise ConfigError(
                f"Unknown --tie-break '{tie_break}' (valid: majority, no_consensus)", code="E203"
            )
        if resume is None and not yes:
            count = len(resolution_service.disputed_items(workspace, run_ids))
            _confirm_resolution(count, messages, as_json=as_json)
        result = resolution_service.discuss_project(
            workspace,
            run_ids,
            resolution_service.ResolutionOptions(
                resume=resume, max_rounds=max_rounds, tie_break=tie_break
            ),
        )
    except typer.Exit:
        raise
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    code = _print_resolution_result(result, folder, runs, messages, as_json=as_json)
    raise typer.Exit(code)


def ui_command_line(
    folder: Path | None, port: int, headless: bool
) -> tuple[list[str], dict[str, str]]:
    """The command and environment that start the interface (local only, no telemetry).

    The interface listens on ``127.0.0.1`` only and Streamlit's usage statistics are switched off
    (ADR 0010: no telemetry). The project folder is handed over in an environment variable.
    """
    script = Path(__file__).resolve().parent / "ui" / "streamlit_app.py"
    command = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.address", "127.0.0.1",
        "--server.port", str(port),
        "--browser.gatherUsageStats", "false",
        "--theme.primaryColor", "#2F6FDE",  # radio buttons, check boxes, sliders
        "--client.showSidebarNavigation", "false",  # the interface has its own menu
        "--server.headless", "true" if headless else "false",
    ]  # fmt: skip
    environment = dict(os.environ)
    if folder is not None:
        environment[PROJECT_ENV] = str(folder.resolve())
    return command, environment


@app.command("ui")
def ui_command(
    folder: Annotated[
        Path | None, typer.Argument(help="Project folder to open (optional).")
    ] = None,
    port: Annotated[int, typer.Option(help="Local port of the interface.")] = 8501,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser window.")
    ] = False,
    lang: LangOption = None,
) -> None:
    """Start the local graphical interface in your browser (needs: pip install "crapai[ui]").

    The interface runs on this computer only (127.0.0.1) and sends no usage statistics.
    Example: crapai ui my-review
    """
    messages = Messages(resolve_language(lang, (folder or Path(".")) / "project.yaml"))
    try:
        if importlib.util.find_spec("streamlit") is None:
            raise ConfigError(
                "The interface needs the package streamlit",
                code="E203",
                hint='Install it with: pip install "crapai[ui]"',
            )
        if folder is not None:
            _setup_file_log(folder, messages)
            Workspace.open(folder)  # fail early with E404 instead of inside the browser
        command, environment = ui_command_line(folder, port, no_browser)
        logger.info("Starting the interface on port %d", port)
        typer.echo(messages.text("cli.ui.starting", port=port))
        result = subprocess.run(command, env=environment, check=False)  # noqa: S603
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    raise typer.Exit(result.returncode)


@app.command("unlock")
def unlock_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    yes: Annotated[bool, typer.Option("--yes", help="Remove a stale lock without asking.")] = False,
    lang: LangOption = None,
) -> None:
    """Remove a stale project lock left behind by a crashed or killed run.

    A lock is only removed when its process is gone and it has shown no sign of life for 60
    seconds; a lock of a running process is never touched.
    Example: crapai unlock my-review
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        lock = Workspace.open(folder).lock()
        info = lock.inspect()
        if info is None:
            typer.echo(messages.text("cli.unlock.none"))
            return
        if not info.stale:
            alive = pid_alive(info.pid)
            key = "cli.unlock.in_use" if alive or info.pid == 0 else "cli.unlock.not_stale"
            typer.secho(messages.text(key, pid=info.pid), fg="yellow", err=True)
            raise typer.Exit(EXIT_SYSTEM_ERROR)
        if not yes:
            if not _interactive():
                typer.echo(messages.text("cli.unlock.declined"), err=True)
                raise typer.Exit(EXIT_USER_ERROR)
            if not typer.confirm(messages.text("cli.unlock.confirm", pid=info.pid)):
                typer.echo(messages.text("cli.unlock.declined"))
                raise typer.Exit(EXIT_USER_ERROR)
        lock.remove_stale(info)
    except typer.Exit:
        raise
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    logger.info("Removed the stale project lock of PID %d", info.pid)
    typer.secho(messages.text("cli.unlock.removed"), fg="green")


@app.command("screen")
def screen_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    sample: Annotated[
        int | None,
        typer.Option(
            "--sample",
            min=1,
            help="Trial run with this many randomly drawn records (reproducible).",
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Continue the newest unfinished run (or the run named by --run-id).",
        ),
    ] = False,
    run_id: Annotated[
        str | None, typer.Option("--run-id", help="Run to resume (default: the newest).")
    ] = None,
    retry_failed: Annotated[
        bool | None,
        typer.Option(
            "--retry-failed/--no-retry-failed",
            help="On resume: try failed records again (default: run.retry_failed_on_resume).",
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Start without asking for confirmation.")
    ] = False,
    no_progress: Annotated[
        bool, typer.Option("--no-progress", help="Do not show the progress bar.")
    ] = False,
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """Screen the records of a project with the language model, in safe batches.

    The records go to the model in batches (run.batch_size); after each batch the results are
    checked on disk before the next one starts. Stop with Ctrl+C at any time: nothing done is
    lost and "crapai screen FOLDER --resume" continues with the records still open.
    Exit code 0 = completed, 4 = completed with failed records, 3 = paused or interrupted,
    1 = failed (user can fix), 2 = failed (system problem such as a full disk).
    Example: crapai screen my-review --sample 20
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    printer: ProgressPrinter | None = None
    try:
        workspace = Workspace.open(folder)
        if not resume:
            # Bring duplicates and validity up to date first, exactly like "crapai check".
            check_project(workspace, update=True)
        estimate, estimate_problem = _estimate_for_screen(workspace, resume)
        if not yes:
            _confirm_screen(estimate, estimate_problem, messages, as_json=as_json)
        if not as_json and not no_progress:
            printer = ProgressPrinter(messages)
        _echo(messages.text("cli.screen.stop_hint"), json_mode=as_json)
        result = screening_service.screen_project(
            workspace,
            screening_service.RunOptions(
                sample=sample,
                resume=(run_id or "latest") if (resume or run_id) else None,
                retry_failed=retry_failed,
                progress=printer,
            ),
        )
    except typer.Exit:
        raise
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        if printer is not None:
            printer.close()
        raise _fail(error, messages, json_mode=as_json) from error
    if printer is not None:
        printer.close()
    raise typer.Exit(_print_screen_result(result, folder, messages, as_json=as_json))


def _estimate_for_screen(workspace: Workspace, resume: bool) -> tuple[ProjectEstimate | None, str]:
    """The cost estimate shown before a run, or ``(None, reason)`` if there is none."""
    try:
        return estimate_project(workspace), ""
    except SaraError as error:
        logger.warning("Cost estimate not available: %s", error.code)
        return None, f"{error.code}: {error.user_message}"
    except Exception as error:  # noqa: BLE001 - the estimate is optional; the run goes on
        logger.exception("Cost estimate failed")
        return None, type(error).__name__


def _confirm_screen(
    estimate: ProjectEstimate | None, problem: str, messages: Messages, *, as_json: bool
) -> None:
    """Show the estimate and ask, or refuse if nobody can be asked (plan 8.5)."""
    if estimate is not None and estimate.estimate.cost is not None:
        run = estimate.estimate
        _echo(
            messages.text(
                "cli.screen.estimate",
                low=f"{run.cost_low:.4f}",
                high=f"{run.cost_high:.4f}",
                worst=f"{run.cost_max:.4f}",
                currency=run.currency,
                duration=format_duration(estimate.duration.seconds),
            ),
            json_mode=as_json,
        )
        if estimate.over_limit:
            _echo(
                messages.text("cli.screen.over_limit", max_cost=estimate.max_cost),
                json_mode=as_json,
                colour="yellow",
            )
    else:
        reason = problem or messages.text("cli.check.cost.no_price")
        _echo(messages.text("cli.screen.estimate_none", reason=reason), json_mode=as_json)
    decision = decide_confirmation(yes=False, interactive=_interactive())
    if decision is Confirmation.REFUSE:
        typer.secho(messages.text("cli.screen.declined"), fg="yellow", err=True)
        raise typer.Exit(EXIT_USER_ERROR)
    if not typer.confirm(messages.text("cli.screen.confirm"), err=as_json):
        typer.echo(messages.text("cli.screen.declined"), err=True)
        raise typer.Exit(EXIT_USER_ERROR)


def _screen_exit_code(result: screening_service.RunResult) -> int:
    """The exit code for how a run ended (see the docstring of the screen command)."""
    state = result.summary.state
    if state == "completed":
        return EXIT_WARNINGS if result.summary.errors else EXIT_OK
    if state in ("paused", "interrupted"):
        return EXIT_INTERRUPTED
    code = result.summary.last_error.get("code", "")
    return EXIT_SYSTEM_ERROR if code in SYSTEM_ERROR_CODES else EXIT_USER_ERROR


def _screen_json(result: screening_service.RunResult) -> dict[str, Any]:
    summary = result.summary
    return {
        "run_id": result.run_id,
        "state": summary.state,
        "resumed": result.resumed,
        "total": summary.total,
        "done": summary.done,
        "by_status": summary.by_status,
        "cost": round(summary.cost, 6),
        "tokens_in": summary.tokens_in,
        "tokens_out": summary.tokens_out,
        "stop_reason": summary.stop_reason,
        "last_error": summary.last_error,
        "warnings": result.warnings,
        "folder": str(result.folder),
    }


def _print_screen_result(
    result: screening_service.RunResult, folder: Path, messages: Messages, *, as_json: bool
) -> int:
    """Print how the run ended, what to do next, and return the exit code."""
    summary = result.summary
    code = _screen_exit_code(result)
    if as_json:
        typer.echo(json.dumps(_screen_json(result), ensure_ascii=False, indent=2))
    colour = {"completed": "green", "paused": "yellow", "interrupted": "yellow"}.get(
        summary.state, "red"
    )
    typer.secho(
        messages.text(
            f"cli.screen.result.{summary.state}",
            run_id=result.run_id,
            ok=summary.ok,
            errors=summary.errors,
            done=summary.done,
            total=summary.total,
            reason=summary.stop_reason or "-",
        ),
        fg=colour,
        bold=True,
        err=as_json,
    )
    if summary.last_error:
        typer.secho(
            messages.text(
                "cli.screen.error_line",
                code=summary.last_error.get("code", ""),
                message=summary.last_error.get("message", ""),
            ),
            fg=colour,
            err=True,
        )
    currency = result.manifest.usage.get("currency", "")
    _echo(
        messages.text(
            "cli.screen.usage",
            tokens_in=summary.tokens_in,
            tokens_out=summary.tokens_out,
            cost=f"{summary.cost:.4f}",
            currency=currency,
            duration=format_duration(summary.duration_s),
        ),
        json_mode=as_json,
    )
    for warning in result.warnings:
        _echo(messages.text("cli.screen.warning", text=warning), json_mode=as_json, colour="yellow")
    results_file = result.folder / "screening.jsonl"
    _echo(messages.text("cli.screen.files", path=results_file), json_mode=as_json)
    if summary.errors:
        _echo(
            messages.text("cli.screen.errors_hint", errors=summary.errors, file=results_file.name),
            json_mode=as_json,
            colour="yellow",
        )
    if summary.state != "completed" or summary.errors:
        _echo(
            messages.text("cli.screen.resume_hint", command=COMMAND, folder=folder),
            json_mode=as_json,
        )
    return code


@app.command("runs")
def runs_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    as_json: JsonOption = False,
    lang: LangOption = None,
) -> None:
    """List the screening runs of a project with their state and counts.

    Example: crapai runs my-review
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        manifests = screening_service.list_runs(Workspace.open(folder))
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=as_json) from error
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "run_id": m.run_id,
                        "state": m.state,
                        "kind": m.kind,
                        "counts": m.counts,
                        "usage": m.usage,
                        "stop_reason": m.stop_reason,
                        "updated_at": m.updated_at,
                    }
                    for m in manifests
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not manifests:
        typer.echo(messages.text("cli.runs.none", command=COMMAND, folder=folder))
        return
    typer.echo(messages.text("cli.runs.header"))
    for m in manifests:
        done = m.counts.get("done", 0)
        typer.echo(
            messages.text(
                "cli.runs.line",
                run_id=m.run_id,
                state=m.state,
                kind=m.kind,
                done=done,
                total=m.counts.get("total", 0),
                errors=done - m.counts.get("ok", 0),
                cost=f"{float(m.usage.get('cost', 0.0)):.4f}",
                currency=m.usage.get("currency", ""),
            )
        )


def _send_control(folder: Path, command: str, run_id: str | None, lang: str | None) -> None:
    """Write a pause/stop request for a running run (shared by the two commands)."""
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder, messages)
    try:
        workspace = Workspace.open(folder)
        store = screening_service.find_run(workspace, run_id or "latest")
        manifest = store.load_manifest()
        if manifest.state != "running":
            typer.secho(
                messages.text(
                    "cli.control.not_running",
                    run_id=manifest.run_id,
                    state=manifest.state,
                    command=command,
                ),
                fg="yellow",
                err=True,
            )
            raise typer.Exit(EXIT_USER_ERROR)
        screening_service.request_control(workspace, manifest.run_id, command)
    except typer.Exit:
        raise
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    logger.info("Sent %s to run %s", command, manifest.run_id)
    typer.echo(messages.text("cli.control.sent", command=command, run_id=manifest.run_id))


@app.command("pause")
def pause_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    run_id: Annotated[str | None, typer.Option("--run-id", help="Run (default: newest).")] = None,
    lang: LangOption = None,
) -> None:
    """Ask a running screening run (in another terminal or the interface) to pause.

    The requests in flight are finished, then the run stops in the state "paused".
    Example: crapai pause my-review
    """
    _send_control(folder, "pause", run_id, lang)


@app.command("stop")
def stop_command(
    folder: Annotated[Path, typer.Argument(help="Project folder.")],
    run_id: Annotated[str | None, typer.Option("--run-id", help="Run (default: newest).")] = None,
    lang: LangOption = None,
) -> None:
    """Ask a running screening run to stop (state "interrupted"; it can be resumed).

    Example: crapai stop my-review
    """
    _send_control(folder, "stop", run_id, lang)


def main() -> None:
    """Console-script entry point."""
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() != "utf-8":
            # Windows consoles default to cp1252; titles and messages contain other characters.
            # stderr matters too: in --json mode all messages and errors go there.
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
