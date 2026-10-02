"""A readable Word summary report: method, PRISMA flow, screening results, for publications
and grant applications (ADR 0026/0027 session; the third export format requested after
BibTeX/NBIB and the PRISMA picture).

Draws only on data this program already computes -- :class:`~crapai.config.models.ProjectConfig`
(title, objectives, criteria), :class:`~crapai.prisma.flow.PrismaFlow` (the same numbers as the
JSON/picture exports) and :class:`~crapai.stats.results.Analysis` of the newest run with results
(:mod:`crapai.services.results`) -- nothing here invents a number. A project with no finished run
yet still gets a report: the results section is left out, with a visible note why.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from crapai.config.models import ProjectConfig
from crapai.errors import ConfigError
from crapai.prisma.flow import PrismaFlow
from crapai.project.atomic import WriteResult, atomic_write_bytes
from crapai.stats.results import Analysis

logger = logging.getLogger(__name__)

# (label, field, always shown even when zero -- a real zero is meaningful; an optional stage
# that simply did not apply, such as full-text screening, is left out instead of shown as 0)
_FLOW_ROWS = (
    ("Records identified", "records_identified_total", True),
    ("Duplicates removed", "duplicates_removed", True),
    ("Removed for other reasons before screening", "records_removed_before_screening_other", False),
    ("Records screened (title/abstract)", "records_screened_title_abstract", True),
    ("Excluded (title/abstract)", "records_excluded_title_abstract", True),
    ("Reports assessed for eligibility (full text)", "reports_assessed_for_eligibility", False),
    ("Excluded (full text)", "reports_excluded_fulltext", False),
    ("Studies included in review", "studies_included_in_review", True),
)


def _add_flow_table(document: object, flow: PrismaFlow) -> None:
    rows = [
        (label, getattr(flow, field))
        for label, field, always in _FLOW_ROWS
        if always or getattr(flow, field)
    ]
    table = document.add_table(rows=len(rows) + 1, cols=2)  # type: ignore[attr-defined]
    table.style = "Light Grid Accent 1"
    table.rows[0].cells[0].text = "PRISMA step"
    table.rows[0].cells[1].text = "n"
    for index, (label, count) in enumerate(rows, start=1):
        table.rows[index].cells[0].text = label
        table.rows[index].cells[1].text = str(count)


def _add_results_table(document: object, analysis: Analysis, run_id: str) -> None:
    document.add_heading(f"Screening results (run {run_id})", level=2)  # type: ignore[attr-defined]
    document.add_paragraph(  # type: ignore[attr-defined]
        f"{analysis.total} record(s) screened; "
        f"{analysis.tokens_in + analysis.tokens_out} token(s)"
        + (f", cost {analysis.cost:.2f}" if analysis.cost is not None else "") + "."
    )
    outcomes = sorted(analysis.by_outcome.items())
    table = document.add_table(rows=len(outcomes) + 1, cols=2)  # type: ignore[attr-defined]
    table.style = "Light Grid Accent 1"
    table.rows[0].cells[0].text = "Decision"
    table.rows[0].cells[1].text = "n"
    for index, (outcome, count) in enumerate(outcomes, start=1):
        table.rows[index].cells[0].text = outcome
        table.rows[index].cells[1].text = str(count)


def build_report(
    config: ProjectConfig,
    flow: PrismaFlow,
    results: tuple[str, Analysis] | None,
    *,
    now: datetime | None = None,
) -> object:
    """Build the report document (a ``docx.Document``, returned as ``object`` so this module can
    be imported without ``python-docx`` installed; only :func:`write_docx_report` needs it).
    """
    try:
        from docx import Document
    except ImportError as exc:
        raise ConfigError(
            "Writing a DOCX report needs the package python-docx",
            code="E203",
            hint='Install it with: pip install "crapai[report]".',
        ) from exc

    document = Document()
    document.add_heading(config.project.title, level=1)
    if config.project.description.strip():
        document.add_paragraph(config.project.description.strip())
    document.add_paragraph(
        f"Report generated {(now or datetime.now()).astimezone().isoformat(timespec='seconds')} "
        "by Critical Apprais.AI. Results are proposals; every decision was reviewed by a human."
    )

    document.add_heading("Objectives", level=2)
    if config.objectives:
        for objective in config.objectives:
            document.add_paragraph(objective, style="List Bullet")
    else:
        document.add_paragraph("(none recorded)")

    document.add_heading("Eligibility criteria", level=2)
    document.add_paragraph(f"Framework: {config.criteria.framework}")
    for key, value in config.criteria.inclusion.items():
        if value.strip():
            document.add_paragraph(f"Include {key}: {value}", style="List Bullet")
    for key, value in config.criteria.exclusion.items():
        if value.strip():
            document.add_paragraph(f"Exclude {key}: {value}", style="List Bullet")

    document.add_heading("PRISMA 2020 flow", level=2)
    _add_flow_table(document, flow)

    if results is not None:
        run_id, analysis = results
        _add_results_table(document, analysis, run_id)
    else:
        document.add_heading("Screening results", level=2)
        document.add_paragraph("No finished screening run yet.")

    return document


def write_docx_report(
    path: Path,
    config: ProjectConfig,
    flow: PrismaFlow,
    results: tuple[str, Analysis] | None,
    *,
    now: datetime | None = None,
) -> WriteResult:
    """Write the summary report as a ``.docx`` file (atomic; a locked target gives an alternative).

    Raises:
        ConfigError: E203 if ``python-docx`` is not installed.
        StorageError: E401/E403 from the atomic write.
    """
    import io as _io

    document = build_report(config, flow, results, now=now)
    buffer = _io.BytesIO()
    document.save(buffer)  # type: ignore[attr-defined]
    logger.info("Writing the DOCX report to %s", path.name)
    return atomic_write_bytes(path, buffer.getvalue())
