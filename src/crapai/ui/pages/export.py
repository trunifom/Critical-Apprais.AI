"""Export page: write a file into the project's ``exports/`` folder and offer it for download."""

from __future__ import annotations

from typing import Any

from crapai.services.export import RECORD_FORMATS, SCOPES
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import show_error

MIME = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ris": "application/x-research-info-systems",
    "json": "application/json",
}


def render(st: Any, ctx: Context) -> None:
    """Draw the export page: choose what to write, write it, offer the download."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("export.title"))
    st.caption(ctx.t("export.intro"))
    what = st.radio(
        ctx.t("export.what"),
        ["records", "flow"],
        format_func=lambda value: ctx.t(f"export.what_{value}"),
        horizontal=True,
        key="export_what",
    )
    fmt, scope, delimiter = "csv", "all", ","
    if what == "records":
        left, middle, right = st.columns(3)
        fmt = left.selectbox(ctx.t("export.format"), RECORD_FORMATS, key="export_format")
        scope = middle.selectbox(
            ctx.t("export.scope"),
            SCOPES,
            format_func=lambda value: ctx.t(f"export.scope_{value}"),
            key="export_scope",
        )
        if fmt == "csv":
            delimiter = right.selectbox(
                ctx.t("export.delimiter"),
                [",", ";"],
                format_func=lambda value: ctx.t(
                    "export.delimiter_semicolon" if value == ";" else "export.delimiter_comma"
                ),
                key="export_delimiter",
            )
    if st.button(ctx.t("export.button"), key="export_button", type="primary"):
        outcome = actions.run_export(
            ctx.messages, folder, what=what, fmt=fmt, scope=scope, delimiter=delimiter
        )
        st.session_state["export_outcome"] = outcome
    outcome = st.session_state.get("export_outcome")
    if outcome is None:
        return
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return
    result = outcome.value
    summary = result.summary
    if summary.what == "flow":
        st.success(ctx.messages.text("cli.export.done_flow", path=summary.path))
    else:
        st.success(
            ctx.messages.text(
                "cli.export.done",
                records=summary.records,
                scope=summary.scope,
                format=summary.format,
                path=summary.path,
            )
        )
    if summary.used_alternative:
        st.warning(ctx.messages.text("cli.export.alternative", wanted=summary.requested_path.name))
    st.download_button(
        ctx.t("export.download"),
        data=result.data,
        file_name=summary.path.name,
        mime=MIME.get(summary.format, "application/octet-stream"),
        key="export_download",
    )
