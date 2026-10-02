"""Data page: choose files, see the dry read, import, and look at the records."""

from __future__ import annotations

from typing import Any

from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.ui import actions
from crapai.ui.actions import PreparedFile, Upload
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, show_error
from crapai.ui.viewmodels import percent, status_icon

ACCEPTED = ["ris", "nbib", "bib", "txt", "csv", "tsv", "xlsx", "zip"]
PREVIEW_ROWS = 200
PREVIEW_COLUMNS = ["title", "year", "authors", "source_label", "exclusion_reason", "doi"]


def _prepared(st: Any, ctx: Context, uploads: list[Any]) -> list[PreparedFile]:
    """Store the chosen files and dry-read them; the result is kept while the choice stays."""
    signature = tuple((u.name, u.size) for u in uploads)
    cached = st.session_state.get("prepared")
    if cached and cached[0] == signature:
        return cached[1]  # type: ignore[no-any-return]
    files = actions.prepare_uploads([Upload(u.name, u.getvalue()) for u in uploads])
    st.session_state["prepared"] = (signature, files)
    return files


def _table(st: Any, ctx: Context, files: list[PreparedFile]) -> None:
    rows = []
    for item in files:
        result = item.preflight
        rows.append(
            {
                ctx.t("data.file"): item.name,
                ctx.t("data.format"): result.format or "-",
                ctx.t("bar.records"): result.records_total,
                ctx.t("bar.abstracts"): percent(result.records_with_abstract, result.records_total),
                ctx.t("data.status"): f"{status_icon(result.status.value)} "
                + ctx.messages.text(result.message_key),
            }
        )
    st.table(rows)


def _import(st: Any, ctx: Context, files: list[PreparedFile], force: bool) -> None:
    folder = ctx.folder
    assert folder is not None
    for item in files:  # the label the user typed
        item.label = st.session_state.get(f"label-{item.name}", item.label).strip() or item.label
    with st.spinner(ctx.t("data.importing")):
        results = actions.import_prepared(ctx.messages, folder, files, force=force)
    for result in results:
        if result.error is not None:
            st.write(f"**{result.name}**")
            show_error(st, ctx, result.error)
            continue
        summary = result.summary
        assert summary is not None
        st.success(
            ctx.messages.text(
                "cli.import.done",
                records=summary.records,
                file=summary.source_file,
                label=summary.source_label,
                abstracts=summary.abstracts,
                total=summary.total_records,
            )
        )
        for note in summary.notes:
            st.caption(ctx.messages.text("cli.import.note", note=note))
        counts = {"empty_records": summary.empty_records, "fulltext_unmatched": summary.unmatched}
        for warning in summary.warnings:
            st.warning(ctx.messages.text(f"cli.warning.{warning}", count=counts.get(warning, 0)))
    st.session_state.pop("overview_token", None)
    st.session_state.pop("prepared", None)


def render(st: Any, ctx: Context) -> None:
    """Draw the data page: file choice, dry-read table, import button and records preview."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("data.title"))
    intro(st, ctx, "data")
    st.markdown(f"##### {ctx.t('data.step1')}")
    st.caption(ctx.t("data.step1_hint"))
    uploads = st.file_uploader(
        ctx.t("data.upload"), type=ACCEPTED, accept_multiple_files=True, key="uploader"
    )
    if uploads:
        files = _prepared(st, ctx, uploads)
        st.markdown(f"##### {ctx.t('data.step2')}")
        st.caption(ctx.t("data.step2_hint"))
        _table(st, ctx, files)
        for item in files:
            if item.importable:
                st.text_input(
                    ctx.t("data.label", file=item.name), value=item.label, key=f"label-{item.name}"
                )
            else:
                result = item.preflight
                st.error(f"{item.name}: {ctx.messages.text(result.message_key)}")
                if result.detail:
                    st.caption(f"{result.error_code}: {result.detail}")
        st.markdown(f"##### {ctx.t('data.step3')}")
        st.caption(ctx.t("data.step3_hint"))
        force = st.checkbox(ctx.t("data.force"), key="force_import")
        ready = [f for f in files if f.importable]
        if st.button(
            ctx.t("data.import_button"), key="import_button", disabled=not ready, type="primary"
        ):
            _import(st, ctx, files, force)
    else:
        st.session_state.pop("prepared", None)

    overview = ctx.overview
    if overview is None or overview.records == 0:
        st.info(ctx.t("data.empty"))
        return
    _history(st, ctx, folder)
    with st.expander(ctx.t("data.records"), expanded=True):
        _records(st, ctx, folder)


def _history(st: Any, ctx: Context, folder: Any) -> None:
    """The files imported so far: when, which source, how many records."""
    entries = actions.import_history(folder)
    if not entries:
        return
    with st.expander(ctx.t("data.history", count=len(entries)), expanded=False):
        st.caption(ctx.t("data.history_hint"))
        st.table(
            [
                {
                    ctx.t("data.when"): e.timestamp.strftime("%Y-%m-%d %H:%M"),
                    ctx.t("data.file"): e.source_file,
                    ctx.t("data.source"): e.source_label,
                    ctx.t("data.format"): e.format,
                    ctx.t("bar.records"): e.records,
                    ctx.t("bar.abstracts"): e.abstracts,
                }
                for e in entries
            ]
        )


def _records(st: Any, ctx: Context, folder: Any) -> None:
    records = read_records(Workspace(folder).records_csv)
    reasons = sorted({r.exclusion_reason for r in records if r.exclusion_reason})
    choice = st.selectbox(
        ctx.t("data.filter"),
        ["", "__none__", *reasons],
        format_func=lambda value: {
            "": ctx.t("data.all"),
            "__none__": ctx.t("data.no_reason"),
        }.get(value, value),
        key="records_filter",
    )
    if choice == "__none__":
        shown = [r for r in records if not r.exclusion_reason]
    elif choice:
        shown = [r for r in records if r.exclusion_reason == choice]
    else:
        shown = records
    st.caption(ctx.t("data.rows", shown=min(len(shown), PREVIEW_ROWS), total=len(shown)))
    st.dataframe(
        [{name: getattr(r, name) for name in PREVIEW_COLUMNS} for r in shown[:PREVIEW_ROWS]],
        width="stretch",
        hide_index=True,
    )
