"""Results service: the results table of a run, and its export (plan chapters 8.8 and 25.8).

``results_table`` joins the records of the project with the last result per record of a screening
run (the newest run that has results unless one is named). ``export_results`` writes that table as
CSV or XLSX into ``exports/``, with the same protections as the record export (formula guard,
Excel-friendly CSV, a locked target is saved under a timestamped name). The file can be read back
on the Evaluation page: :func:`crapai.stats.results.read_table_file`.

Nothing in the project is changed; no lock is needed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from crapai.errors import ConfigError
from crapai.io.records_store import read_records
from crapai.io.writers.tables import write_csv, write_xlsx
from crapai.project.workspace import Workspace
from crapai.screening.store import RunStore
from crapai.services.export import ExportSummary, _target
from crapai.services.screening import list_runs
from crapai.stats import agreement
from crapai.stats.agreement import ComparisonSummary
from crapai.stats.results import (
    DECISIONS,
    RESULT_COLUMNS,
    build_table,
    compare_columns,
    compare_table,
)

logger = logging.getLogger(__name__)

RESULT_FORMATS: tuple[str, ...] = ("csv", "xlsx")


def runs_with_results(workspace: Workspace) -> list[str]:
    """Ids of the runs that have at least one result line, oldest first."""
    found: list[str] = []
    for manifest in list_runs(workspace):
        store = RunStore(workspace.runs_dir / manifest.run_id)
        if store.results_size() > 0:
            found.append(manifest.run_id)
    return found


def results_table(
    workspace: Workspace, run_id: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """The results table of a run.

    Args:
        workspace: The project.
        run_id: The run; default the newest one with results.

    Returns:
        ``(run id, rows)``.

    Raises:
        ConfigError: E203 if the project has no run with results or the named run is unknown.
        StorageError: E404 for damaged files.
    """
    workspace = Workspace.open(workspace.root)
    available = runs_with_results(workspace)
    if run_id is None:
        if not available:
            raise ConfigError(
                "There are no screening results yet",
                code="E203",
                hint="Run the screening first (page 4, or 'crapai screen').",
            )
        run_id = available[-1]
    elif run_id not in available:
        raise ConfigError(
            f"The run '{run_id}' has no results",
            code="E203",
            hint="Runs with results: " + (", ".join(available) or "none"),
        )
    store = RunStore(workspace.runs_dir / run_id)
    rows = build_table(read_records(workspace.records_csv), store.last_results(), run_id)
    return run_id, rows


def _check_runs_have_results(workspace: Workspace, run_ids: Sequence[str]) -> None:
    if len(run_ids) < 2:
        raise ConfigError(
            "Comparing runs needs at least two run ids",
            code="E203",
            hint="Name two or more runs, for example --runs run-001,run-002.",
        )
    available = runs_with_results(workspace)
    for run_id in run_ids:
        if run_id not in available:
            raise ConfigError(
                f"The run '{run_id}' has no results",
                code="E203",
                hint="Runs with results: " + (", ".join(available) or "none"),
            )


def compare_runs(
    workspace: Workspace, run_ids: Sequence[str]
) -> tuple[list[dict[str, Any]], ComparisonSummary]:
    """Join the records of the project with the results of several runs, and their agreement.

    Args:
        workspace: The project.
        run_ids: Two or more runs to compare (test-retest or different models/settings).

    Returns:
        ``(rows, summary)``: one row per record (:func:`crapai.stats.results.compare_table`) and
        the pairwise/Fleiss agreement over the decided records (plan chapter 14.1).

    Raises:
        ConfigError: E203 for fewer than two runs, or a run without results.
    """
    workspace = Workspace.open(workspace.root)
    _check_runs_have_results(workspace, run_ids)
    run_ids = tuple(run_ids)
    records = read_records(workspace.records_csv)
    results_by_run = {
        run_id: RunStore(workspace.runs_dir / run_id).last_results() for run_id in run_ids
    }
    rows = compare_table(records, results_by_run, run_ids)
    decisions_by_run = {
        run_id: {
            uid: row.decision
            for uid, row in results.items()
            if row.status == "ok" and row.decision in DECISIONS
        }
        for run_id, results in results_by_run.items()
    }
    summary = agreement.compare(decisions_by_run, run_ids)
    logger.info(
        "Compared %d run(s): %d record(s) decided by all of them, Fleiss' kappa %s",
        len(run_ids),
        summary.n_common,
        summary.fleiss_kappa,
    )
    return rows, summary


def export_comparison(
    workspace: Workspace,
    run_ids: Sequence[str],
    fmt: str = "csv",
    *,
    output: Path | None = None,
    delimiter: str = ",",
    guard_formulas: bool = True,
    now: datetime | None = None,
) -> ExportSummary:
    """Write the comparison table of several runs to ``exports/compare-<runs>-<timestamp>.<fmt>``.

    Raises:
        ConfigError: E203 for an unknown format, fewer than two runs, or a run without results.
        StorageError: E404/E401/E403 for damaged or unwritable files.
    """
    if fmt not in RESULT_FORMATS:
        raise ConfigError(
            f"Unknown format '{fmt}' for the comparison (valid: {', '.join(RESULT_FORMATS)})",
            code="E203",
            hint="Use csv or xlsx.",
        )
    rows, summary = compare_runs(workspace, run_ids)
    columns = compare_columns(summary.run_ids)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    label = "-".join(run_id[:12] for run_id in summary.run_ids)
    target = _target(Workspace(workspace.root), output, f"compare-{label}-{stamp}.{fmt}")
    body = ([_cell(row.get(name)) for name in columns] for row in rows)
    if fmt == "csv":
        written = write_csv(
            target, columns, body, delimiter=delimiter, guard_formulas=guard_formulas
        )
    else:
        written = write_xlsx(
            target, columns, body, sheet="compare", guard_formulas=guard_formulas
        )
    logger.info(
        "Exported a comparison of %d run(s), %d row(s), as %s", len(run_ids), len(rows), fmt
    )
    return ExportSummary(
        what="compare",
        format=fmt,
        path=written.path,
        requested_path=target,
        records=len(rows),
        scope=",".join(summary.run_ids),
        used_alternative=written.used_alternative,
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def export_results(
    workspace: Workspace,
    fmt: str = "csv",
    *,
    run_id: str | None = None,
    output: Path | None = None,
    delimiter: str = ",",
    guard_formulas: bool = True,
    now: datetime | None = None,
) -> ExportSummary:
    """Write the results table of a run to ``exports/results-<run>-<timestamp>.<fmt>``.

    Raises:
        ConfigError: E203 for an unknown format, no results, or a bad target.
        StorageError: E404/E401/E403 for damaged or unwritable files.
    """
    if fmt not in RESULT_FORMATS:
        raise ConfigError(
            f"Unknown format '{fmt}' for the results (valid: {', '.join(RESULT_FORMATS)})",
            code="E203",
            hint="Use csv or xlsx.",
        )
    used_run, rows = results_table(workspace, run_id)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = _target(Workspace(workspace.root), output, f"results-{used_run[:16]}-{stamp}.{fmt}")
    body = ([_cell(row.get(name)) for name in RESULT_COLUMNS] for row in rows)
    if fmt == "csv":
        written = write_csv(
            target, RESULT_COLUMNS, body, delimiter=delimiter, guard_formulas=guard_formulas
        )
    else:
        written = write_xlsx(
            target, RESULT_COLUMNS, body, sheet="results", guard_formulas=guard_formulas
        )
    logger.info("Exported %d result row(s) of run %s as %s", len(rows), used_run, fmt)
    return ExportSummary(
        what="results",
        format=fmt,
        path=written.path,
        requested_path=target,
        records=len(rows),
        scope=used_run,
        used_alternative=written.used_alternative,
    )
