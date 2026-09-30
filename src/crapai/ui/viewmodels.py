"""What the interface shows, computed without any Streamlit call (so it can be tested plainly).

The pages in ``crapai.ui.pages`` only draw. The decisions behind the drawing live here:

* which step of the workflow is done, current, locked or done-with-warnings (:func:`build_stepper`),
* the numbers of the status bar (:func:`load_overview`),
* the list of recent projects that is kept between sessions (:class:`RecentProjects`),
* small formatting helpers shared by the pages.

Nothing here writes to a project. :class:`RecentProjects` writes one small JSON file in the
user's configuration folder and ignores every problem with it: a missing or damaged list must never
stop the interface.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from crapai.config.loader import default_user_config_path
from crapai.errors import SaraError
from crapai.io.records_store import read_records
from crapai.prisma.flow import FlowWarning
from crapai.project.workspace import Workspace
from crapai.services.events import read_events
from crapai.services.project import ProjectStatus, project_status

logger = logging.getLogger(__name__)

StepState = Literal["done", "current", "locked", "warning"]
STEP_KEYS: tuple[str, ...] = ("project", "data", "check", "run", "flow", "export")
STATE_ICONS: dict[str, str] = {"done": "✅", "current": "🔵", "locked": "⚪", "warning": "⚠️"}
RECENT_MAX = 8
RECENT_FILE = "recent.json"


@dataclass(frozen=True)
class Overview:
    """The numbers of the status bar and the basis of the stepper.

    Attributes:
        folder: The project folder.
        title: Project title from ``project.yaml`` (None if it cannot be read).
        records: All records.
        with_abstract: Records with an abstract.
        duplicates: Records marked as duplicates.
        excluded: Records with any exclusion reason (duplicates included).
        valid_for_model: Records that would go to the model (no reason), or None if the
            project has no records.
        sources: Records per source label.
        imports: Number of imported files.
        config_ok: Whether ``project.yaml`` is complete and valid.
        config_problem: First line of the problem, if any.
        in_use: Another process holds the project lock.
        checked: Whether the check has run at least once (a validity event exists).
    """

    folder: Path
    title: str | None
    records: int
    with_abstract: int
    duplicates: int
    excluded: int
    valid_for_model: int | None
    sources: dict[str, int]
    imports: int
    config_ok: bool
    config_problem: str | None
    in_use: bool
    checked: bool


def overview_from_status(status: ProjectStatus, excluded: int, checked: bool) -> Overview:
    """Build an :class:`Overview` from the service's status and the exclusion count."""
    return Overview(
        folder=status.root,
        title=status.title,
        records=status.records,
        with_abstract=status.with_abstract,
        duplicates=status.duplicates,
        excluded=excluded,
        valid_for_model=(status.records - excluded) if status.records else None,
        sources=dict(status.per_source),
        imports=len(status.imports),
        config_ok=status.config_ok,
        config_problem=status.config_problem,
        in_use=status.in_use,
        checked=checked,
    )


def load_overview(folder: Path) -> Overview:
    """Read the overview of a project (read only).

    Raises:
        SaraError: E404 if ``folder`` is no project or ``records.csv`` is damaged.
    """
    status = project_status(folder)
    workspace = Workspace(status.root)
    records = read_records(workspace.records_csv)
    excluded = sum(1 for r in records if r.exclusion_reason)
    checked = any(event.kind == "validity" for event in read_events(workspace.events_jsonl))
    return overview_from_status(status, excluded, checked)


@dataclass(frozen=True)
class StepInfo:
    """One entry of the stepper.

    Attributes:
        key: One of :data:`STEP_KEYS`.
        state: ``done``, ``current``, ``locked`` or ``warning``.
        reason: Why a locked step is locked (a text key suffix, for example ``needs_records``).
    """

    key: str
    state: StepState
    reason: str = ""

    @property
    def icon(self) -> str:
        """The symbol that shows the state."""
        return STATE_ICONS[self.state]


def build_stepper(
    overview: Overview | None, *, flow_warnings: Sequence[FlowWarning] = ()
) -> list[StepInfo]:
    """The workflow steps and their state.

    The order is fixed: project, data, check, run, flow, export. A step is *locked* while its
    requirement is missing; the first step that is neither done nor locked is the *current* one.
    The ``run`` step (the model screening) is always locked in this version.

    Args:
        overview: The project overview, or None if no project is open.
        flow_warnings: Plausibility warnings of the PRISMA flow; they turn ``flow`` to a warning.
    """
    if overview is None:
        return [StepInfo("project", "current")] + [
            StepInfo(key, "locked", "needs_project") for key in STEP_KEYS[1:]
        ]
    project_ready = overview.config_ok
    has_records = overview.records > 0
    states: dict[str, tuple[StepState, str]] = {
        "project": ("done" if project_ready else "warning", ""),
        "data": ("done" if has_records else "current", ""),
        "check": (
            "locked" if not has_records else ("done" if overview.checked else "current"),
            "needs_records" if not has_records else "",
        ),
        "run": ("locked", "not_available"),
        "flow": (
            "locked" if not has_records else ("warning" if flow_warnings else "done"),
            "needs_records" if not has_records else "",
        ),
        "export": (
            "locked" if not has_records else "done",
            "needs_records" if not has_records else "",
        ),
    }
    steps = [StepInfo(key, state, reason) for key, (state, reason) in states.items()]
    return steps


def percent(part: int, whole: int) -> str:
    """``"75 %"`` for 3 of 4; ``"-"`` for an empty whole."""
    return f"{round(100 * part / whole)} %" if whole else "-"


def status_icon(status: str) -> str:
    """Symbol for a preflight status (``ok``, ``warning``, ``error``)."""
    return {"ok": "✅", "warning": "⚠️", "error": "❌"}.get(status, "•")


@dataclass
class RecentProjects:
    """The projects opened most recently, newest first, kept in the user's configuration folder.

    Args:
        path: The JSON file (default: ``~/.config/crapai/recent.json``).
    """

    path: Path = field(default_factory=lambda: default_user_config_path().with_name(RECENT_FILE))

    def load(self) -> list[Path]:
        """The remembered folders that still exist (a bad or missing file gives an empty list)."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            folders = [Path(item) for item in data["projects"] if isinstance(item, str)]
        except (OSError, ValueError, KeyError, TypeError):
            return []
        return [folder for folder in folders if folder.is_dir()][:RECENT_MAX]

    def remember(self, folder: Path) -> None:
        """Put ``folder`` first; problems writing the file are logged, never raised."""
        resolved = folder.resolve()
        others = [p for p in self.load() if p.resolve() != resolved]
        payload = {"projects": [str(p) for p in [resolved, *others][:RECENT_MAX]]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot save the list of recent projects (%s)", type(exc).__name__)

    def forget(self, folder: Path) -> None:
        """Remove ``folder`` from the list."""
        resolved = folder.resolve()
        kept = [str(p) for p in self.load() if p.resolve() != resolved]
        try:
            self.path.write_text(json.dumps({"projects": kept}, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot save the list of recent projects (%s)", type(exc).__name__)


def describe_problem(error: BaseException) -> str:
    """One line about an error for the log of the interface (code and type, never contents)."""
    if isinstance(error, SaraError):
        return f"{error.code}: {error.user_message}"
    return type(error).__name__
