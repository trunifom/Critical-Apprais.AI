"""The state that every page of the interface shares for one browser session (no Streamlit here)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from crapai.i18n.messages import Messages, resolve_language
from crapai.ui.viewmodels import Overview, RecentProjects

PROJECT_ENV = "CRAPAI_UI_PROJECT"  # the folder that ``crapai ui FOLDER`` opens at the start
PAGES: tuple[str, ...] = (
    "start",
    "project",
    "data",
    "check",
    "run",
    "flow",
    "export",
    "settings",
    "help",
)
#: pages that need an open project (the others work without one)
NEEDS_PROJECT = frozenset({"project", "data", "check", "run", "flow", "export"})
#: pages that need records
NEEDS_RECORDS = frozenset({"check", "flow", "export"})


@dataclass
class Context:
    """Everything a page needs.

    Attributes:
        folder: The open project, or None.
        overview: Its overview (None until it could be read).
        lang: Message language, ``en`` or ``de``.
        messages: Texts in that language.
        recent: The list of recently opened projects.
    """

    folder: Path | None
    overview: Overview | None
    lang: str
    messages: Messages
    recent: RecentProjects

    def t(self, key: str, **values: object) -> str:
        """The interface text for ``key`` (see ``ui.*`` in the text files)."""
        return self.messages.text(f"ui.{key}", **values)


def initial_folder() -> Path | None:
    """The folder named by the command line (``crapai ui FOLDER``), if any."""
    value = os.environ.get(PROJECT_ENV, "").strip()
    return Path(value) if value else None


def initial_language() -> str:
    """The language at the start: from the environment (``LANG``), else English."""
    return resolve_language(None)


def lock_reason(page: str, overview: Overview | None, folder: Path | None) -> str | None:
    """Why a page cannot be used yet (a ``ui.locked.*`` key suffix), or None if it can."""
    if page == "run":
        return "not_available"
    if page in NEEDS_PROJECT and folder is None:
        return "needs_project"
    if page in NEEDS_RECORDS and (overview is None or overview.records == 0):
        return "needs_records"
    return None
