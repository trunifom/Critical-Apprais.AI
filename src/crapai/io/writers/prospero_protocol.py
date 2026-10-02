"""A pre-filled PROSPERO protocol document, to speed up copying into PROSPERO's web form (ADR 0031).

PROSPERO (the international register of systematic review protocols, University of York) has no
public submission API -- only a web form that a named guarantor must confirm. This module therefore
never submits anything; it only writes a DOCX with as many of PROSPERO's form sections pre-filled
from data this project already has (:class:`~crapai.config.models.ProjectConfig`) as possible. A
field PROSPERO asks for that nothing here tracks (data extraction method, risk-of-bias assessment,
most of "Searches") is shown with a visible placeholder, never silently left out -- the document
says plainly where it is incomplete, exactly like :mod:`crapai.io.writers.docx_report` does for a
project with no finished run yet.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from crapai.config.models import ProjectConfig
from crapai.errors import ConfigError
from crapai.project.atomic import WriteResult, atomic_write_bytes

logger = logging.getLogger(__name__)

_PLACEHOLDER = "(please complete -- not tracked by this project)"
_SEARCH_NOTE = (
    "This project tracks only a language and a publication-year restriction, not a full search "
    "strategy or database list. Complete the database names, the exact search strings per "
    "database, and the search date here by hand."
)
_METHOD_NOTE = (
    "This project does not track the planned data-extraction method, risk-of-bias assessment "
    "tool, or synthesis method. Complete these sections by hand before submitting."
)


def _add_criteria(document: object, config: ProjectConfig) -> None:
    document.add_heading("Review question (eligibility criteria)", level=2)  # type: ignore[attr-defined]
    document.add_paragraph(f"Framework: {config.criteria.framework}")  # type: ignore[attr-defined]
    inclusion = {k: v for k, v in config.criteria.inclusion.items() if v.strip()}
    exclusion = {k: v for k, v in config.criteria.exclusion.items() if v.strip()}
    if inclusion:
        for key, value in inclusion.items():
            document.add_paragraph(f"Include {key}: {value}", style="List Bullet")  # type: ignore[attr-defined]
    else:
        document.add_paragraph(_PLACEHOLDER)  # type: ignore[attr-defined]
    for key, value in exclusion.items():
        document.add_paragraph(f"Exclude {key}: {value}", style="List Bullet")  # type: ignore[attr-defined]


def _add_admin(document: object, config: ProjectConfig) -> None:
    meta = config.prospero
    document.add_heading("Administrative information", level=2)  # type: ignore[attr-defined]
    rows = [
        ("Review title", config.project.title),
        ("Anticipated start date", meta.anticipated_start_date),
        ("Anticipated completion date", meta.anticipated_completion_date),
        ("Stage of review at time of registration", meta.review_stage.replace("_", " ")),
        ("Named review team members", "; ".join(meta.team_members)),
        ("Corresponding author", meta.corresponding_author),
        ("Funding sources", meta.funding),
        ("Conflicts of interest", meta.conflicts_of_interest),
        ("Prior or related registration", meta.prior_registration),
    ]
    table = document.add_table(rows=len(rows), cols=2)  # type: ignore[attr-defined]
    table.style = "Light Grid Accent 1"  # type: ignore[attr-defined]
    for index, (label, value) in enumerate(rows):
        table.rows[index].cells[0].text = label  # type: ignore[attr-defined]
        table.rows[index].cells[1].text = value.strip() or _PLACEHOLDER  # type: ignore[attr-defined]


def _add_searches(document: object, config: ProjectConfig) -> None:
    document.add_heading("Searches", level=2)  # type: ignore[attr-defined]
    document.add_paragraph(_SEARCH_NOTE)  # type: ignore[attr-defined]
    language = config.prefilters.language
    year = config.prefilters.year
    if language is not None and language.allow:
        document.add_paragraph(  # type: ignore[attr-defined]
            f"Language restriction: {', '.join(language.allow)}", style="List Bullet"
        )
    if year is not None and (year.min is not None or year.max is not None):
        low = year.min if year.min is not None else "open"
        high = year.max if year.max is not None else "open"
        document.add_paragraph(f"Publication year: {low}-{high}", style="List Bullet")  # type: ignore[attr-defined]


def build_prospero_protocol(config: ProjectConfig, *, now: datetime | None = None) -> object:
    """Build the PROSPERO protocol document (a ``docx.Document``, returned as ``object`` so this
    module can be imported without ``python-docx`` installed; only
    :func:`write_prospero_protocol` needs it).
    """
    try:
        from docx import Document
    except ImportError as exc:
        raise ConfigError(
            "Writing a PROSPERO protocol needs the package python-docx",
            code="E203",
            hint='Install it with: pip install "crapai[report]".',
        ) from exc

    document = Document()
    document.add_heading(f"PROSPERO protocol draft: {config.project.title}", level=1)
    document.add_paragraph(
        "This is a draft to copy into PROSPERO's own registration form "
        "(https://www.crd.york.ac.uk/prospero/) -- it is not submitted automatically; "
        "PROSPERO has no public submission API. Review every section before copying it over."
    )
    document.add_paragraph(
        f"Draft generated {(now or datetime.now()).astimezone().isoformat(timespec='seconds')} "
        "by Critical Apprais.AI."
    )
    _add_admin(document, config)
    document.add_heading("Condition or domain being studied", level=2)
    if config.objectives:
        for objective in config.objectives:
            document.add_paragraph(objective, style="List Bullet")
    else:
        document.add_paragraph(_PLACEHOLDER)
    if config.project.description.strip():
        document.add_paragraph(config.project.description.strip())
    _add_criteria(document, config)
    _add_searches(document, config)
    document.add_heading("Data extraction, risk of bias, synthesis", level=2)
    document.add_paragraph(_METHOD_NOTE)
    return document


def write_prospero_protocol(
    path: Path, config: ProjectConfig, *, now: datetime | None = None
) -> WriteResult:
    """Write the PROSPERO protocol draft as a ``.docx`` file (atomic; a locked target gives an
    alternative).

    Raises:
        ConfigError: E203 if ``python-docx`` is not installed.
        StorageError: E401/E403 from the atomic write.
    """
    import io as _io

    document = build_prospero_protocol(config, now=now)
    buffer = _io.BytesIO()
    document.save(buffer)  # type: ignore[attr-defined]
    logger.info("Writing the PROSPERO protocol draft to %s", path.name)
    return atomic_write_bytes(path, buffer.getvalue())
