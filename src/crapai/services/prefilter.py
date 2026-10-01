"""Pre-filter service: apply the deterministic filters of ``project.yaml`` to a project.

Reads ``prefilters`` (language, year, publication types) from ``project.yaml`` unless the caller
passes a configuration, marks the records (see :mod:`crapai.prisma.prefilters`), writes
``records.csv`` back after a backup under the project lock, and records the result as a PRISMA
event. An unreadable ``project.yaml`` means no filters (logged), as for the other steps.

Order of work in a project: import, dedup (:mod:`crapai.services.dedup`), pre-filters, validity
(:mod:`crapai.services.validity`). ``crapai check`` runs them in that order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.config.models import Prefilters
from crapai.errors import SaraError
from crapai.io.records_store import read_records, write_records
from crapai.prisma.prefilters import PrefilterConfig, mark_prefilters
from crapai.project.workspace import Workspace
from crapai.services.events import record_prefilter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrefilterSummary:
    """What a pre-filter run did."""

    records: int
    removed: int
    by_reason: dict[str, int]
    passed_on_missing: dict[str, int]
    active: bool
    config_source: str  # "given", "project" or "default"
    events_written: bool = True  # False: the PRISMA event could not be written


def config_from_settings(settings: Prefilters) -> PrefilterConfig:
    """Translate the ``prefilters`` block of ``project.yaml`` into the filter configuration."""
    language, year, types = settings.language, settings.year, settings.publication_types
    keywords = settings.keywords
    return PrefilterConfig(
        language_allow=tuple(language.allow) if language else (),
        language_on_missing=language.on_missing if language else "pass",
        year_min=year.min if year else None,
        year_max=year.max if year else None,
        year_on_missing=year.on_missing if year else "pass",
        type_exclude=tuple(types.exclude) if types else (),
        type_on_missing=types.on_missing if types else "pass",
        keyword_include=tuple(keywords.include_any) if keywords else (),
        keyword_exclude=tuple(keywords.exclude_any) if keywords else (),
        keyword_case_sensitive=keywords.case_sensitive if keywords else False,
        keyword_on_missing=keywords.on_missing if keywords else "pass",
    )


def _configured(workspace: Workspace) -> PrefilterConfig | None:
    """The filters of ``project.yaml``, or None if the file is missing or invalid."""
    if not workspace.project_yaml.exists():
        return None
    try:
        return config_from_settings(load_project_config(workspace.project_yaml).prefilters)
    except SaraError as exc:
        logger.warning("project.yaml is not valid (%s); no pre-filters applied", exc.code)
        return None


def prefilter_project(
    workspace: Workspace, *, config: PrefilterConfig | None = None
) -> PrefilterSummary:
    """Mark records that fail a language, year or publication-type filter.

    Args:
        workspace: The project.
        config: Overrides the ``prefilters`` block of ``project.yaml``.

    Raises:
        StorageError: E402 if the project is in use, E404 for a damaged folder or ``records.csv``,
            E401 if ``records.csv`` is locked (nothing is changed).
    """
    workspace = Workspace.open(workspace.root)
    with workspace.lock():
        return apply_prefilters(workspace, config=config)


def apply_prefilters(
    workspace: Workspace, *, config: PrefilterConfig | None = None
) -> PrefilterSummary:
    """Mark records; the caller holds the project lock (see :func:`prefilter_project`)."""
    records = read_records(workspace.records_csv)
    if config is not None:
        chosen, source = config, "given"
    else:
        configured = _configured(workspace)
        chosen, source = (configured, "project") if configured else (PrefilterConfig(), "default")
    result = mark_prefilters(records, chosen)
    written = result.records != records
    if written:
        write_records(workspace.records_csv, result.records, backup_dir=workspace.backup_dir)
    events_ok = record_prefilter(workspace, len(result.records), result.by_reason)
    logger.info(
        "Pre-filters (settings from %s): %d of %d records marked; records.csv %s",
        source,
        result.removed,
        len(result.records),
        "rewritten" if written else "unchanged",
    )
    return PrefilterSummary(
        records=len(result.records),
        removed=result.removed,
        by_reason=result.by_reason,
        passed_on_missing=result.passed_on_missing,
        active=chosen.active,
        config_source=source,
        events_written=events_ok,
    )
