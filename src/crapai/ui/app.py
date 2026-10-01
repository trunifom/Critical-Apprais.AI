"""The interface as a whole: page set-up, language, sidebar with the stepper, status bar, routing.

``main(st)`` is what ``streamlit_app.py`` runs on every interaction (Streamlit re-runs the script
from the top). It keeps almost nothing itself: the open project and the language live in
``st.session_state``, the read project overview is cached there until a file of the project
changes, and each page draws itself.
"""

from __future__ import annotations

import html
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
from crapai.ui.kit import Themed
from crapai.ui.pages.common import metric_row, show_error, show_locked
from crapai.ui.theme import SIZES, THEMES, UiPrefs, build_css
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


#: sidebar menu: (group title text key or "", pages); every page is a button
NAV_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("", ("start",)),
    ("nav_group.work", ("project", "data", "check", "run", "flow", "export")),
    ("nav_group.more", ("settings", "help")),
)
PAGE_ICONS = {"start": "🏠", "settings": "⚙️", "help": "❓"}


def _go(st: Any, page: str) -> None:
    st.session_state["goto"] = page
    st.rerun()


def render_sidebar(st: Any, ui: Any, ctx: Context, prefs: UiPrefs) -> None:
    """Title, display choices, the menu as buttons in groups, and the open project.

    Args:
        st: Streamlit itself (for the sidebar block and state).
        ui: The cover around it (:class:`~crapai.ui.kit.Themed`) that adds help and notices.
        ctx: The session context.
        prefs: Where the choices of language, design and text size are remembered.
    """
    state = st.session_state
    with st.sidebar:
        st.markdown(
            f'<div class="crapai-brand">{PRODUCT_NAME}</div>'
            f'<div class="crapai-brand-sub">{ctx.t("tagline")}</div>',
            unsafe_allow_html=True,
        )
        ui.selectbox(
            ctx.t("language"),
            SUPPORTED_LANGUAGES,
            format_func=lambda code: LANGUAGE_NAMES[code],
            key="lang",
        )
        dark = state["theme"] == "dark"
        if ui.button(
            ctx.t("theme.to_light" if dark else "theme.to_dark"),
            key="theme_toggle",
            use_container_width=True,
        ):
            state["theme"] = "light" if dark else "dark"
            st.rerun()
        large = state["size"] == "large"
        if ui.button(
            ctx.t("size.to_small" if large else "size.to_large"),
            key="size_toggle",
            use_container_width=True,
        ):
            state["size"] = "normal" if large else "large"
            st.rerun()
        icons = {step.key: step.icon for step in build_stepper(ctx.overview)}
        for group, pages in NAV_GROUPS:
            if group:
                st.markdown(
                    f'<div class="crapai-nav-title">{ctx.t(group)}</div>', unsafe_allow_html=True
                )
            for page in pages:
                icon = icons.get(page) or PAGE_ICONS.get(page, "")
                current = state["page"] == page
                if ui.button(
                    f"{icon} {ctx.t(f'nav.{page}')}".strip(),
                    key=f"nav_{page}",
                    type="primary" if current else "secondary",
                    use_container_width=True,
                ):
                    _go(st, page)
        if ctx.folder is not None:
            st.markdown(
                f'<div class="crapai-project">📁 {html.escape(str(ctx.folder))}</div>',
                unsafe_allow_html=True,
            )
            if ui.button(ctx.t("close_project"), key="close_project"):
                state["folder"] = None
                _reset_project_state(st)
                _go(st, "start")
    chosen = {"lang": state["lang"], "theme": state["theme"], "size": state["size"]}
    if state.get("_prefs_saved") != chosen:  # remember the choices for the next session
        prefs.save(**chosen)
        state["_prefs_saved"] = chosen


def render_status_bar(st: Any, ctx: Context) -> None:
    """The project name and the numbers every page shows at its top (plan chapter 27.3)."""
    overview = ctx.overview
    if overview is None:
        st.caption(ctx.t("bar.no_project"))
        return
    valid = overview.valid_for_model if overview.valid_for_model is not None else 0
    st.markdown(
        f'<div class="crapai-title">{html.escape(overview.title or overview.folder.name)}</div>',
        unsafe_allow_html=True,
    )
    metric_row(
        st,
        [
            (ctx.t("bar.records"), overview.records),
            (ctx.t("bar.abstracts"), percent(overview.with_abstract, overview.records)),
            (ctx.t("bar.duplicates"), overview.duplicates),
            (ctx.t("bar.valid"), valid),
        ],
    )
    if overview.in_use:
        st.warning(ctx.t("bar.in_use"))


def browser_theme(st: Any) -> str | None:
    """The theme Streamlit is drawn in (``light``/``dark``) or None if it cannot be told."""
    try:
        value = st.context.theme.type
    except Exception:  # noqa: BLE001 - older Streamlit, tests, no browser yet
        return None
    return value if value in THEMES else None


def main(st: Any) -> None:
    """Draw one run of the interface."""
    st.set_page_config(page_title=PRODUCT_NAME, page_icon="📚", layout="wide")
    state = st.session_state
    prefs = UiPrefs()
    saved = prefs.load()
    state.setdefault("lang", saved.get("lang") or initial_language())
    state.setdefault("theme", saved.get("theme") or browser_theme(st) or "light")
    state.setdefault("size", saved.get("size") or "normal")
    if state["theme"] not in THEMES or state["size"] not in SIZES:
        state["theme"], state["size"] = "light", "normal"
    state.setdefault("folder", initial_folder())
    state.setdefault("page", "start" if state["folder"] is None else "project")
    if "goto" in state:  # a button asked to go elsewhere
        state["page"] = state.pop("goto")
    if state.get("_last_folder") != state["folder"]:
        _reset_project_state(st)
        state["_last_folder"] = state["folder"]

    st.markdown(
        f"<style>{build_css(state['theme'], state['size'], browser_theme(st))}</style>",
        unsafe_allow_html=True,
    )
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
    ui = Themed(st, ctx.help_for)
    state["missing_help"] = ui.missing  # filled while the pages draw; read by the tests

    render_sidebar(st, ui, ctx, prefs)
    render_status_bar(ui, ctx)
    if "load_error" in state:
        show_error(ui, ctx, state.pop("load_error"))
    page = state["page"]
    reason = lock_reason(page, overview, folder)
    if reason is not None:
        ui.header(ctx.t(f"nav.{page}"))
        show_locked(ui, ctx, reason)
        return
    page_module(page).render(ui, ctx)
