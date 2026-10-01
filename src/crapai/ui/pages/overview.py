"""Overview page: the steps of the process, what is done and what to do next."""

from __future__ import annotations

from typing import Any

from crapai.project.workspace import Workspace
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import intro
from crapai.ui.viewmodels import build_tracker, load_run_views, next_step


def _go(st: Any, page: str) -> None:
    st.session_state["goto"] = page
    st.rerun()


def render(st: Any, ctx: Context) -> None:
    """Draw the overview: a progress bar, one row per step with its state, and the next step."""
    folder, overview = ctx.folder, ctx.overview
    assert folder is not None and overview is not None
    st.header(ctx.t("overview.title"))
    intro(st, ctx, "overview")
    filled = actions.criteria_filled(folder)
    exports = len(actions.list_exports(folder))
    rows = build_tracker(overview, load_run_views(folder), criteria_filled=filled, exports=exports)
    done = sum(1 for row in rows if row.state == "done")
    st.progress(done / len(rows), text=ctx.t("overview.progress", done=done, total=len(rows)))

    following = next_step(rows)
    if following is not None:
        st.info(ctx.t("overview.next", step=ctx.t(f"nav.{following.page}")))
        if st.button(
            ctx.t("overview.go", step=ctx.t(f"nav.{following.page}")),
            key=f"overview_open_next_{following.page}",
            type="primary",
        ):
            _go(st, following.page)
    else:
        st.success(ctx.t("overview.all_done"))

    st.subheader(ctx.t("overview.steps"))
    for row in rows:
        icon_col, text_col, button_col = st.columns([1, 8, 2])
        icon_col.markdown(f"### {row.icon}")
        text_col.markdown(
            f'<span class="crapai-step">{ctx.t(f"nav.{row.page}")}</span>', unsafe_allow_html=True
        )
        text_col.caption(ctx.t(f"tracker.{row.detail}", **row.values))
        if button_col.button(ctx.t("overview.open"), key=f"overview_open_{row.page}"):
            _go(st, row.page)

    workspace = Workspace(folder)
    st.caption(ctx.t("overview.folder", path=workspace.root))
