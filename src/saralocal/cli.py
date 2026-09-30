"""Command line of Critical Apprais.AI: init, import, status (plan chapters 15.1 and 27.10).

This is the only module (besides a future UI) that talks to the user. All work happens in the
service layer; this module parses arguments, chooses the language, prints results and turns
errors into exit codes:

* 0 = ok, 1 = user error (input, configuration), 2 = system error (file, lock, disk),
* 4 = result with warnings (for example records without abstracts).

``--json`` prints machine-readable results on stdout; all messages then go to stderr.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from saralocal import __version__
from saralocal.branding import PRODUCT_NAME
from saralocal.errors import UNEXPECTED_ERROR_CODE, ConfigError, SaraError
from saralocal.i18n.messages import Messages, resolve_language
from saralocal.project.workspace import STATE_DIR_NAME, Workspace
from saralocal.services.importing import ImportRequest, ImportSummary, import_source
from saralocal.services.project import DEFAULT_TEMPLATE, create_project, project_status

logger = logging.getLogger("saralocal.cli")

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SYSTEM_ERROR = 2
EXIT_WARNINGS = 4

# Errors caused by the environment, not by the input (plan chapter 15.1: exit code 2).
SYSTEM_ERROR_CODES = frozenset({"E401", "E402", "E403", UNEXPECTED_ERROR_CODE})
COMMAND = "sara"  # provisional command name (task T-M0-03)

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
) -> None:
    """Project commands (init, import, status)."""


# --- helpers ----------------------------------------------------------------------------------


def _echo(message: str, *, json_mode: bool, colour: str | None = None) -> None:
    """Print a human message (stderr in JSON mode so stdout stays machine-readable)."""
    typer.secho(message, fg=colour, err=json_mode)


def _setup_file_log(folder: Path) -> None:
    """Log to ``.sara/app.log`` of the project (rotating), if the folder is a project."""
    state = folder / STATE_DIR_NAME
    if not state.is_dir():
        return
    root = logging.getLogger("saralocal")
    target = str((state / "app.log").resolve())
    for existing in list(root.handlers):
        if isinstance(existing, logging.handlers.RotatingFileHandler):
            if existing.baseFilename == target:
                return
            root.removeHandler(existing)  # a different project was used earlier in this process
            existing.close()
    handler = logging.handlers.RotatingFileHandler(
        target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _fail(error: Exception, messages: Messages, *, json_mode: bool) -> typer.Exit:
    """Report ``error`` and return the exit for it (the caller raises it)."""
    if isinstance(error, SaraError):
        code = EXIT_SYSTEM_ERROR if error.code in SYSTEM_ERROR_CODES else EXIT_USER_ERROR
        lines = messages.error_lines(error)
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
        "notes": list(summary.notes),
        "warnings": list(summary.warnings),
    }


# --- commands ---------------------------------------------------------------------------------


@app.command("init")
def init_command(
    folder: Annotated[Path, typer.Argument(help="New project folder (must be new or empty).")],
    from_template: Annotated[
        str,
        typer.Option(
            "--from-template", help="Template name (blank, demo) or path of a YAML file."
        ),
    ] = DEFAULT_TEMPLATE,
    title: Annotated[str | None, typer.Option(help="Project title (default: folder name).")] = None,
    lang: LangOption = None,
) -> None:
    """Create a project folder with a project.yaml.

    Example: sara init my-review --from-template demo
    """
    messages = Messages(resolve_language(lang))
    try:
        workspace = create_project(folder, template=from_template, title=title)
    except Exception as error:  # noqa: BLE001 - boundary: every error becomes an exit code
        raise _fail(error, messages, json_mode=False) from error
    _setup_file_log(workspace.root)
    typer.secho(messages.text("cli.init.done", path=workspace.root), fg="green")
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

    Example: sara import my-review pubmed.ris embase.bib --label PubMed --label Embase
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
    _setup_file_log(folder)
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
        if as_json:
            typer.echo(json.dumps({"imported": results}, ensure_ascii=False))
        raise _fail(error, messages, json_mode=as_json) from error
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
        _echo(messages.text("cli.import.mapping", mapping=used), json_mode=json_mode)
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

    Example: sara status my-review
    """
    messages = Messages(resolve_language(lang, folder / "project.yaml"))
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
        first_line = (status.config_problem or "").splitlines()[0] if status.config_problem else ""
        typer.secho(messages.text("cli.status.config_problem", problem=first_line), fg="yellow")
    if status.in_use:
        typer.secho(messages.text("cli.status.in_use"), fg="yellow")


def main() -> None:
    """Console-script entry point."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        # Windows consoles default to cp1252; titles and messages contain other characters.
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
