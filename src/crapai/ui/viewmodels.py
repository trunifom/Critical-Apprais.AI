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
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from crapai.config.loader import default_user_config_path
from crapai.errors import SaraError
from crapai.io.records_store import read_records
from crapai.prisma.flow import FlowWarning
from crapai.project.workspace import Workspace
from crapai.screening.store import Manifest, RunState, RunStore
from crapai.services import screening as screening_service
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
        run_state: State of the newest screening run (empty if there is none).
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
    run_state: str = ""


def overview_from_status(
    status: ProjectStatus, excluded: int, checked: bool, run_state: str = ""
) -> Overview:
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
        run_state=run_state,
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
    runs = screening_service.list_runs(workspace)
    return overview_from_status(status, excluded, checked, runs[-1].state if runs else "")


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
    The ``run`` step follows the newest screening run: ``done`` if it completed, ``warning`` if
    it was paused, interrupted or failed, otherwise ``current`` as soon as there are records.

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
        "run": _run_step(overview, has_records),
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


def _run_step(overview: Overview, has_records: bool) -> tuple[StepState, str]:
    """State of the ``run`` step from the state of the newest run."""
    if not has_records:
        return "locked", "needs_records"
    if overview.run_state == RunState.COMPLETED.value:
        return "done", ""
    if overview.run_state in (
        RunState.PAUSED.value,
        RunState.INTERRUPTED.value,
        RunState.FAILED.value,
    ):
        return "warning", ""
    return "current", ""


#: a running run whose manifest was not saved for this long (seconds) is shown as stalled
STALL_AFTER_S = 30.0


@dataclass(frozen=True)
class RunView:
    """One screening run as the run page shows it (built from ``manifest.json``).

    Attributes:
        run_id: Folder name of the run.
        state: A :class:`~crapai.screening.store.RunState` value.
        kind: ``full`` or ``sample``.
        total: Records of the whole run.
        done: Records with a result so far (all sessions).
        ok: Records screened successfully.
        errors: ``done`` minus ``ok``.
        cost: Cost so far.
        currency: Currency of the cost.
        batch: The batch being worked on (1-based; the last one when finished).
        batches: Number of batches of the whole run.
        stop_reason: Why the last session ended.
        last_error: ``{"code", "message"}`` of the problem that stopped the run, or empty.
        warnings: Notes of the run.
        batch_rows: The batch table of the manifest.
        updated_at: When the manifest was last saved (ISO text).
        age_s: Seconds since then, or None if unknown.
    """

    run_id: str
    state: str
    kind: str
    total: int
    done: int
    ok: int
    errors: int
    cost: float
    currency: str
    batch: int
    batches: int
    stop_reason: str
    last_error: dict[str, str]
    warnings: tuple[str, ...]
    batch_rows: tuple[dict[str, object], ...]
    updated_at: str
    age_s: float | None

    @property
    def fraction(self) -> float:
        """Progress between 0 and 1 (1 for an empty run)."""
        return min(1.0, self.done / self.total) if self.total else 1.0

    @property
    def running(self) -> bool:
        """True while the manifest says the run is working."""
        return self.state == RunState.RUNNING.value

    @property
    def stalled(self) -> bool:
        """True if the run claims to be working but has not saved anything for a while."""
        return self.running and self.age_s is not None and self.age_s > STALL_AFTER_S

    @property
    def resumable(self) -> bool:
        """Whether ``resume`` makes sense: unfinished, or completed with failed records."""
        if self.state == RunState.COMPLETED.value:
            return self.errors > 0
        return RunState(self.state).resumable


def run_view(manifest: Manifest, now: datetime | None = None) -> RunView:
    """Turn a manifest into a :class:`RunView`."""
    counts = manifest.counts
    total, done, ok = counts.get("total", 0), counts.get("done", 0), counts.get("ok", 0)
    size = int(manifest.run_settings.get("batch_size", 0) or 0)
    batches = math.ceil(total / size) if size else len(manifest.batches)
    verified = sum(1 for row in manifest.batches if row.get("status") == "verified")
    try:
        updated = datetime.fromisoformat(manifest.updated_at)
        age = max(0.0, ((now or datetime.now(UTC)) - updated).total_seconds())
    except ValueError:
        age = None
    return RunView(
        run_id=manifest.run_id,
        state=manifest.state,
        kind=manifest.kind,
        total=total,
        done=done,
        ok=ok,
        errors=max(0, done - ok),
        cost=float(manifest.usage.get("cost", 0.0) or 0.0),
        currency=str(manifest.usage.get("currency", "")),
        batch=min(verified + 1, max(batches, 1)),
        batches=batches,
        stop_reason=manifest.stop_reason,
        last_error=dict(manifest.last_error),
        warnings=tuple(manifest.warnings),
        batch_rows=tuple(manifest.batches),
        updated_at=manifest.updated_at,
        age_s=age,
    )


def load_run_views(folder: Path) -> list[RunView]:
    """All runs of a project, oldest first (damaged run folders are skipped and logged)."""
    return [run_view(m) for m in screening_service.list_runs(Workspace(folder))]


def failed_results(folder: Path, run_id: str, limit: int = 200) -> list[dict[str, str]]:
    """Records of a run whose last result is not ``ok``: title, status, code (first ``limit``)."""
    workspace = Workspace(folder)
    store = RunStore(workspace.runs_dir / run_id)
    titles = {r.study_uid: r.title for r in read_records(workspace.records_csv)}
    rows = [row for row in store.last_results().values() if not row.is_ok]
    return [
        {
            "title": titles.get(row.study_uid, row.study_uid),
            "status": row.status,
            "code": row.error_code,
            "message": row.error_message,
            "attempts": str(row.attempts),
        }
        for row in rows[:limit]
    ]


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
