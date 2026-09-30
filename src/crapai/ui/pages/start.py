"""Start page: open a project folder or create a new one."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import show_error

TEMPLATES = ("blank", "demo")


def open_folder(st: Any, ctx: Context, folder: Path) -> bool:
    """Open ``folder`` (shows the error if it cannot be opened); True if it worked."""
    outcome = actions.open_project(ctx.messages, folder, ctx.recent)
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return False
    st.session_state["folder"] = folder
    st.session_state.pop("overview_token", None)
    st.session_state["goto"] = "project"  # applied before the navigation widget is built
    st.rerun()
    return True


def render(st: Any, ctx: Context) -> None:
    """Draw the start page: open a recent or typed project folder, or create a new one."""
    st.header(ctx.t("start.title"))
    st.caption(ctx.t("tagline"))
    left, right = st.columns(2)

    with left:
        st.subheader(ctx.t("start.open"))
        recent = ctx.recent.load()
        if recent:
            st.caption(ctx.t("start.recent"))
            for index, path in enumerate(recent):
                if st.button(f"📁 {path.name}  —  {path}", key=f"recent-{index}"):
                    open_folder(st, ctx, path)
        else:
            st.caption(ctx.t("start.no_recent"))
        typed = st.text_input(ctx.t("start.folder"), key="open_folder_text")
        if st.button(ctx.t("start.open_button"), key="open_button", disabled=not typed.strip()):
            open_folder(st, ctx, Path(typed.strip()))

    with right:
        st.subheader(ctx.t("start.create"))
        target = st.text_input(ctx.t("start.new_folder"), key="create_folder_text")
        template = st.selectbox(
            ctx.t("start.template"),
            TEMPLATES,
            format_func=lambda name: ctx.t(f"start.template_{name}"),
            key="create_template",
        )
        title = st.text_input(ctx.t("start.new_title"), key="create_title")
        if st.button(
            ctx.t("start.create_button"), key="create_button", disabled=not target.strip()
        ):
            outcome = actions.create_new_project(
                ctx.messages, Path(target.strip()), template=template, title=title.strip() or None
            )
            if outcome.error is not None:
                show_error(st, ctx, outcome.error)
            elif outcome.value is not None:
                st.success(ctx.t("start.created", path=outcome.value.root))
                open_folder(st, ctx, outcome.value.root)
    st.warning(ctx.t("disclaimer"))
