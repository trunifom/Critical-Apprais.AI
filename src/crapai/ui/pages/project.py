"""Project page: state of the project and a checked editor for project.yaml."""

from __future__ import annotations

from typing import Any

from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import metric_row, show_error
from crapai.ui.viewmodels import percent


def render(st: Any, ctx: Context) -> None:
    """Draw the project page: state, key numbers and the checked editor of project.yaml."""
    overview, folder = ctx.overview, ctx.folder
    if overview is None or folder is None:
        return
    st.header(ctx.t("project.title"))
    st.subheader(overview.title or folder.name)
    st.caption(str(folder))
    if overview.config_ok:
        st.success(ctx.messages.text("cli.status.config_ok"))
    else:
        first = next(iter((overview.config_problem or "").splitlines()), "")
        st.warning(ctx.messages.text("cli.status.config_problem", problem=first))
    if overview.in_use:
        st.warning(ctx.messages.text("cli.status.in_use"))
    metric_row(
        st,
        [
            (ctx.t("bar.records"), overview.records),
            (ctx.t("bar.abstracts"), percent(overview.with_abstract, overview.records)),
            (ctx.t("bar.duplicates"), overview.duplicates),
            (ctx.t("project.imports"), overview.imports),
        ],
    )
    if overview.sources:
        st.write(f"**{ctx.t('project.sources')}**")
        st.table(
            {
                ctx.t("project.source"): list(overview.sources),
                ctx.t("bar.records"): list(overview.sources.values()),
            }
        )

    st.subheader(ctx.t("project.edit"))
    st.caption(ctx.t("project.edit_hint"))
    text = st.text_area(
        "project.yaml",
        actions.read_project_yaml(folder),
        height=420,
        key="yaml_text",
        label_visibility="collapsed",
    )
    if st.button(ctx.t("project.save"), key="save_yaml"):
        outcome = actions.save_project_yaml(ctx.messages, folder, text)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
        else:
            st.session_state.pop("overview_token", None)
            st.success(ctx.t("project.saved"))
