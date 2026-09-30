"""Project service: create a project folder and report its state (plan chapters 6 and 15.1).

``create_project`` builds the folder layout and writes ``project.yaml`` from a template.
``project_status`` reads what is on disk (records, imports, configuration, lock) without changing
anything, so it is safe to call while another process works on the project.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from saralocal.config.loader import load_project_config
from saralocal.errors import ConfigError, SaraError
from saralocal.io.import_log import ImportLogEntry, read_entries
from saralocal.io.records_store import read_records
from saralocal.project.atomic import atomic_write_text
from saralocal.project.workspace import Workspace

logger = logging.getLogger(__name__)

TEMPLATE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
TITLE_PLACEHOLDER = "__TITLE__"
DEFAULT_TEMPLATE = "blank"


def available_templates() -> list[str]:
    """Names of the templates shipped with the program."""
    folder = resources.files("saralocal.config").joinpath("templates")
    names = (item.name for item in folder.iterdir() if item.name.endswith(".yaml"))
    return sorted(name.removesuffix(".yaml") for name in names)


def read_template(name_or_path: str) -> str:
    """Return the text of a bundled template (by name) or of a YAML file (by path).

    Raises:
        ConfigError: (E203) if the name is unknown or the file cannot be read.
    """
    if TEMPLATE_NAME.match(name_or_path):
        resource = resources.files("saralocal.config").joinpath("templates", f"{name_or_path}.yaml")
        if not resource.is_file():
            raise ConfigError(
                f"Unknown template '{name_or_path}'",
                code="E203",
                hint="Available templates: " + ", ".join(available_templates()),
            )
        return resource.read_text(encoding="utf-8")
    path = Path(name_or_path)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(
            f"Template file cannot be read: {path}",
            code="E203",
            hint="Use a template name or the path of a UTF-8 YAML file.",
            details={"path": str(path)},
        ) from exc


def create_project(
    root: Path, *, template: str = DEFAULT_TEMPLATE, title: str | None = None
) -> Workspace:
    """Create a project folder with ``project.yaml`` from a template.

    Args:
        root: New (or empty) project folder.
        template: Bundled template name (``blank``, ``demo``) or path of a YAML file.
        title: Project title; defaults to the folder name for the ``blank`` template.

    Raises:
        ConfigError: (E203) for an unknown template.
        StorageError: (E404) if ``root`` is already a project or not empty.
    """
    text = read_template(template)  # fail before anything is created
    workspace = Workspace.create(root)
    text = text.replace(TITLE_PLACEHOLDER, (title or root.name).replace('"', "'"))
    if title and TITLE_PLACEHOLDER not in text:
        logger.info("Template has its own title; --title is ignored")
    atomic_write_text(workspace.project_yaml, text)
    logger.info("Created project %s from template %s", root, template)
    return workspace


@dataclass(frozen=True)
class ProjectStatus:
    """A read-only snapshot of a project folder."""

    root: Path
    schema_version: int
    records: int
    with_abstract: int
    empty_records: int
    duplicates: int
    per_source: dict[str, int]
    imports: tuple[ImportLogEntry, ...]
    config_ok: bool
    config_problem: str | None
    title: str | None
    in_use: bool


def project_status(root: Path) -> ProjectStatus:
    """Collect counts and checks for the project at ``root``.

    Raises:
        StorageError: (E404) if ``root`` is not a project folder or ``records.csv`` is damaged.
    """
    workspace = Workspace.open(root)
    records = read_records(workspace.records_csv)
    per_source = Counter(record.source_label for record in records)
    config_ok, problem, title = True, None, None
    if not workspace.project_yaml.exists():
        config_ok, problem = False, "project.yaml is missing"
    else:
        try:
            title = load_project_config(workspace.project_yaml).project.title
        except SaraError as exc:
            config_ok, problem = False, str(exc)
    info = workspace.lock().inspect()
    return ProjectStatus(
        root=workspace.root,
        schema_version=workspace.read_version(),
        records=len(records),
        with_abstract=sum(1 for r in records if r.has_abstract),
        empty_records=sum(1 for r in records if r.exclusion_reason == "EMPTY_RECORD"),
        duplicates=sum(1 for r in records if r.is_duplicate),
        per_source=dict(per_source),
        imports=tuple(read_entries(workspace.import_log)),
        config_ok=config_ok,
        config_problem=problem,
        title=title,
        in_use=info is not None and not info.stale,
    )
