"""The interface as a whole: page set-up, language, sidebar with the stepper, status bar, routing.

``main(st)`` is what ``streamlit_app.py`` runs on every interaction (Streamlit re-runs the script
from the top). It keeps almost nothing itself: the open project and the language live in
``st.session_state``, the read project overview is cached there until a file of the project
changes, and each page draws itself.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from crapai.branding import PRODUCT_NAME
from crapai.i18n.messages import SUPPORTED_LANGUAGES, Messages
from crapai.project.workspace import Workspace
from crapai.ui import actions
from crapai.ui.context import (
    PAGES,
    Context,
    initial_folder,
    initial_language,
    lock_reason,
)
from crapai.ui.pages.common import metric_row, show_error, show_locked
from crapai.ui.viewmodels import Overview, RecentProjects, build_stepper, percent

logger = logging.getLogger(__name__)

#: session keys that belong to the open project and must be dropped when another one is opened
PROJECT_KEYS = ("overview", "overview_token", "check_outcome", "export_outcome", "prepared")
LANGUAGE_NAMES = {"en": "English", "de": "Deutsch"}


def project_token(folder: Path) -> tuple[int, ...]:
    """Changes whenever a file of the project changes (used to reload the overview)."""
    workspace = Workspace(folder)
    paths = (
        workspace.records_csv,
        workspace.project_yaml,
        workspace.events_jsonl,
        workspace.lock_file,
    )
    token: list[int] = []
    for path in paths:
        try:
            token.append(path.stat().st_mtime_ns)
        except OSError:
            token.append(0)
    return tuple(token)


def page_module(name: str) -> ModuleType:
    """The module of a page (imported when first needed)."""
    return importlib.import_module(f"crapai.ui.pages.{name}")


def _reset_project_state(st: Any) -> None:
    for key in PROJECT_KEYS:
        st.session_state.pop(key, None)


def current_overview(
    st: Any, messages: Messages, folder: Path | None
) -> tuple[Overview | None, Any]:
    """The overview, reloaded only if a project file changed. Returns ``(overview, error)``."""
    if folder is None:
        return None, None
    token = project_token(folder)
    if st.session_state.get("overview_token") == token and "overview" in st.session_state:
        return st.session_state["overview"], None
    outcome = actions.open_project(messages, folder)
    if outcome.error is not None:
        return None, outcome.error
    st.session_state["overview"], st.session_state["overview_token"] = outcome.value, token
    return outcome.value, None


def render_sidebar(st: Any, ctx: Context) -> None:
    """Language, workflow pages with their state, and the button that closes the project."""
    with st.sidebar:
        st.title(PRODUCT_NAME)
        st.selectbox(
            ctx.t("language"),
            SUPPORTED_LANGUAGES,
            format_func=lambda code: LANGUAGE_NAMES[code],
            key="lang",
        )
        icons = {step.key: step.icon for step in build_stepper(ctx.overview)}
        st.radio(
            ctx.t("navigation"),
            PAGES,
            format_func=lambda page: f"{icons.get(page, '')} {ctx.t(f'nav.{page}')}".strip(),
            key="page",
        )
        if ctx.folder is not None:
            st.caption(f"📁 {ctx.folder}")
            if st.button(ctx.t("close_project"), key="close_project"):
                st.session_state["folder"] = None
                _reset_project_state(st)
                st.session_state["goto"] = "start"
                st.rerun()


def render_status_bar(st: Any, ctx: Context) -> None:
    """The numbers every page shows at its top (plan chapter 27.3)."""
    overview = ctx.overview
    if overview is None:
        st.caption(ctx.t("bar.no_project"))
        return
    valid = overview.valid_for_model if overview.valid_for_model is not None else 0
    metric_row(
        st,
        [
            (ctx.t("bar.project"), overview.title or overview.folder.name),
            (ctx.t("bar.records"), overview.records),
            (ctx.t("bar.abstracts"), percent(overview.with_abstract, overview.records)),
            (ctx.t("bar.duplicates"), overview.duplicates),
            (ctx.t("bar.valid"), valid),
        ],
    )
    if overview.in_use:
        st.warning(ctx.t("bar.in_use"))


def main(st: Any) -> None:
    """Draw one run of the interface."""
    st.set_page_config(page_title=PRODUCT_NAME, page_icon="📚", layout="wide")
    state = st.session_state
    state.setdefault("lang", initial_language())
    state.setdefault("folder", initial_folder())
    state.setdefault("page", "start" if state["folder"] is None else "project")
    if "goto" in state:  # a page asked to go elsewhere; the radio widget may only be set up here
        state["page"] = state.pop("goto")
    if state.get("_last_folder") != state["folder"]:
        _reset_project_state(st)
        state["_last_folder"] = state["folder"]

    messages = Messages(state["lang"])
    folder: Path | None = state["folder"]
    overview, error = current_overview(st, messages, folder)
    if error is not None:  # the folder cannot be opened: say why and go back to the start page
        logger.warning("Cannot open the project folder: %s", error.code)
        state["folder"], folder = None, None
        state["load_error"] = error
    ctx = Context(folder, overview, state["lang"], messages, RecentProjects())
    if state["page"] not in PAGES:
        state["page"] = "start"

    render_sidebar(st, ctx)
    render_status_bar(st, ctx)
    if "load_error" in state:
        show_error(st, ctx, state.pop("load_error"))
    page = state["page"]
    reason = lock_reason(page, overview, folder)
    if reason is not None:
        st.header(ctx.t(f"nav.{page}"))
        show_locked(st, ctx, reason)
        return
    page_module(page).render(st, ctx)
