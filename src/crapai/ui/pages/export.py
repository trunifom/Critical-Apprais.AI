"""Export page: write a file into the project's ``exports/`` folder and offer it for download."""

from __future__ import annotations

from typing import Any

from crapai.project.workspace import Workspace
from crapai.services.export import RECORD_FORMATS, SCOPES
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, show_error

MAX_FILES = 30
MAX_DOWNLOAD = 50 * 1024 * 1024  # larger files stay in the folder
MIME = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ris": "application/x-research-info-systems",
    "bibtex": "application/x-bibtex",
    "nbib": "text/plain",
    "json": "application/json",
}


def render(st: Any, ctx: Context) -> None:
    """Draw the export page: choose what to write, write it, offer the download."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("export.title"))
    intro(st, ctx, "export")
    st.markdown(f"##### {ctx.t('export.step1')}")
    st.caption(ctx.t("export.step1_hint"))
    what = st.radio(
        ctx.t("export.what"),
        ["records", "results", "flow"],
        format_func=lambda value: ctx.t(f"export.what_{value}"),
        horizontal=True,
        key="export_what",
    )
    fmt, scope, delimiter = "csv", "all", ","
    if what in ("records", "results"):
        st.markdown(f"##### {ctx.t('export.step2')}")
        st.caption(ctx.t("export.step2_hint"))
        left, middle, right = st.columns(3)
        formats = RECORD_FORMATS if what == "records" else ("csv", "xlsx")
        fmt = left.selectbox(ctx.t("export.format"), formats, key=f"export_format_{what}")
        scope = "all"
        if what == "records":
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
    st.markdown(f"##### {ctx.t('export.step3')}")
    st.caption(ctx.t("export.step3_hint", folder=Workspace(folder).exports_dir))
    if st.button(ctx.t("export.button"), key="export_button", type="primary"):
        outcome = actions.run_export(
            ctx.messages, folder, what=what, fmt=fmt, scope=scope, delimiter=delimiter
        )
        st.session_state["export_outcome"] = outcome
    outcome = st.session_state.get("export_outcome")
    if outcome is not None:
        _show_outcome(st, ctx, outcome)
    _files(st, ctx, folder)


def _files(st: Any, ctx: Context, folder: Any) -> None:
    """Everything in the export folder, newest first, each with a download button."""
    files = actions.list_exports(folder)
    with st.expander(ctx.t("export.files", count=len(files)), expanded=False):
        st.caption(ctx.t("export.files_hint", folder=Workspace(folder).exports_dir))
        if not files:
            st.info(ctx.t("export.no_files"))
        for path in files[:MAX_FILES]:
            size = path.stat().st_size
            name_col, button_col = st.columns([4, 1])
            name_col.write(f"**{path.name}**  ·  {size / 1024:,.0f} KB")
            if size <= MAX_DOWNLOAD:
                button_col.download_button(
                    ctx.t("export.download"),
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=MIME.get(path.suffix.lstrip("."), "application/octet-stream"),
                    key=f"download_file_{path.name}",
                )


def _show_outcome(st: Any, ctx: Context, outcome: Any) -> None:
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
