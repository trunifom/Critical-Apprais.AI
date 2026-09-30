"""Dedup service: mark duplicates in a project's ``records.csv`` (plan chapters 8.4 and 15.1).

The strategy comes from the command line, else from ``dedup.strategy`` in ``project.yaml`` (when the
file can be read), else from the default. The result is written back atomically after a backup,
under the project lock. Nothing is deleted; see :mod:`crapai.prisma.dedup`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.errors import SaraError
from crapai.io.records_store import read_records, write_records
from crapai.prisma.dedup import DedupConfig, DedupResult, Keep, Strategy, mark_duplicates
from crapai.project.workspace import Workspace
from crapai.services.events import record_dedup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DedupSummary:
    """What a dedup run did, for the CLI."""

    strategy: str
    keep: str
    strategy_source: str  # "cli", "project" or "default"
    records: int
    marked: int
    groups: int
    by_method: dict[str, int]
    within_source: dict[str, int]
    across_sources: int
    events_written: bool = True  # False: the PRISMA event could not be written


def _configured_strategy(workspace: Workspace) -> Strategy | None:
    """The strategy of ``project.yaml``, or None if the file is missing or invalid."""
    if not workspace.project_yaml.exists():
        return None
    try:
        return load_project_config(workspace.project_yaml).dedup.strategy
    except SaraError as exc:
        logger.warning("project.yaml is not valid (%s); using the default dedup strategy", exc.code)
        return None


def dedup_project(
    workspace: Workspace,
    *,
    strategy: Strategy | None = None,
    keep: Keep = "best",
) -> DedupSummary:
    """Mark duplicates in the project and rewrite ``records.csv``.

    Args:
        workspace: The project.
        strategy: Overrides ``dedup.strategy`` of ``project.yaml``.
        keep: Which record of a duplicate group stays unmarked.

    Raises:
        StorageError: E402 if the project is in use, E404 for a damaged folder or ``records.csv``,
            E401 if ``records.csv`` is locked (nothing is changed).
    """
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        return apply_dedup(workspace, strategy=strategy, keep=keep)


def apply_dedup(
    workspace: Workspace,
    *,
    strategy: Strategy | None = None,
    keep: Keep = "best",
) -> DedupSummary:
    """Mark duplicates; the caller holds the project lock (see :func:`dedup_project`)."""
    records = read_records(workspace.records_csv)
    if strategy is not None:
        chosen, source = strategy, "cli"
    else:
        configured = _configured_strategy(workspace)
        chosen, source = (configured, "project") if configured else ("doi_or_title", "default")
    result: DedupResult = mark_duplicates(records, DedupConfig(strategy=chosen, keep=keep))
    written = result.records != records
    if written:
        write_records(workspace.records_csv, result.records, backup_dir=workspace.backup_dir)
    events_ok = record_dedup(
        workspace, result.records, chosen, result.within_source, result.across_sources
    )
    logger.info(
        "Dedup (%s, keep=%s): %d of %d records marked in %d group(s); records.csv %s",
        chosen,
        keep,
        result.marked,
        len(result.records),
        result.groups,
        "rewritten" if written else "unchanged",
    )
    return DedupSummary(
        strategy=chosen,
        keep=keep,
        strategy_source=source,
        records=len(result.records),
        marked=result.marked,
        groups=result.groups,
        by_method=result.by_method,
        within_source=result.within_source,
        across_sources=result.across_sources,
        events_written=events_ok,
    )
