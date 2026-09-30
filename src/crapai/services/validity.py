"""Validity service: mark records that must not go to the model (plan chapters 8.4 and 26.3).

Reads the project's ``records.csv``, sets ``NOT_SCREENABLE`` / ``RETRACTED`` / ``NO_ABSTRACT`` and
``abstract_quality`` with :func:`crapai.prisma.validity.mark_validity` and writes the file back
after a backup, under the project lock. The options come from the caller, else from ``project.yaml``
(``screening.include_title_only``, ``prefilters.exclude_retracted``), else they are off.

Order of work in a project: import, dedup (:mod:`crapai.services.dedup`), validity. The preflight
(``crapai check``, task T-M2-04) runs them in that order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.errors import SaraError
from crapai.io.records_store import read_records, write_records
from crapai.prisma.validity import QualityThresholds, ValidityConfig, mark_validity
from crapai.project.workspace import Workspace
from crapai.services.events import record_validity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValiditySummary:
    """What a validity run did."""

    records: int
    valid_for_model: int
    by_reason: dict[str, int]
    quality: dict[str, int]
    include_title_only: bool
    exclude_retracted: bool
    options_source: str  # "cli", "project" or "default"
    events_written: bool = True  # False: the PRISMA event could not be written


def _options_from_project(workspace: Workspace) -> tuple[bool, bool, QualityThresholds] | None:
    """The validity options from project.yaml (with the settings overrides), or None."""
    if not workspace.project_yaml.exists():
        return None
    try:
        config = load_project_config(workspace.project_yaml)
    except SaraError as exc:
        logger.warning("project.yaml is not valid (%s); using default validity options", exc.code)
        return None
    quality = QualityThresholds(**config.quality.model_dump())
    return config.screening.include_title_only, config.prefilters.exclude_retracted, quality


def validate_project(
    workspace: Workspace,
    *,
    include_title_only: bool | None = None,
    exclude_retracted: bool | None = None,
) -> ValiditySummary:
    """Mark records without abstract, front matter and (optionally) retracted studies.

    Args:
        workspace: The project.
        include_title_only: Overrides ``screening.include_title_only``.
        exclude_retracted: Overrides ``prefilters.exclude_retracted``.

    Raises:
        StorageError: E402 if the project is in use, E404 for a damaged folder or ``records.csv``,
            E401 if ``records.csv`` is locked (nothing is changed).
    """
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        return apply_validity(
            workspace, include_title_only=include_title_only, exclude_retracted=exclude_retracted
        )


def apply_validity(
    workspace: Workspace,
    *,
    include_title_only: bool | None = None,
    exclude_retracted: bool | None = None,
) -> ValiditySummary:
    """Mark invalid records; the caller holds the project lock (see :func:`validate_project`)."""
    records = read_records(workspace.records_csv)
    overridden = include_title_only is not None or exclude_retracted is not None
    stored = None if overridden else _options_from_project(workspace)
    source = "cli" if overridden else ("project" if stored is not None else "default")
    base_title, base_retracted, quality = (
        stored if stored is not None else (False, False, QualityThresholds())
    )
    config = ValidityConfig(
        include_title_only=base_title if include_title_only is None else include_title_only,
        exclude_retracted=base_retracted if exclude_retracted is None else exclude_retracted,
        quality=quality,
    )
    result = mark_validity(records, config)
    written = result.records != records
    if written:
        write_records(workspace.records_csv, result.records, backup_dir=workspace.backup_dir)
    without_abstract = sum(1 for r in result.records if not r.has_abstract)
    events_ok = record_validity(workspace, len(result.records), result.by_reason, without_abstract)
    logger.info(
        "Validity (options from %s): %d of %d records go to the model; records.csv %s",
        source,
        result.valid_for_model,
        len(result.records),
        "rewritten" if written else "unchanged",
    )
    return ValiditySummary(
        records=len(result.records),
        valid_for_model=result.valid_for_model,
        by_reason=result.by_reason,
        quality=result.quality,
        include_title_only=config.include_title_only,
        exclude_retracted=config.exclude_retracted,
        options_source=source,
        events_written=events_ok,
    )
