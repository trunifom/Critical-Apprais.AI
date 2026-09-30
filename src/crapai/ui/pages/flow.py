"""PRISMA flow page: the numbers of the flow diagram, derived from the project's events."""

from __future__ import annotations

from typing import Any

from crapai.enums import DuplicatesReportingMode
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import metric_row, show_error


def render(st: Any, ctx: Context) -> None:
    """Draw the PRISMA page: the flow numbers for the chosen way of counting duplicates."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("flow.title"))
    st.caption(ctx.t("flow.intro"))
    modes = [m.value for m in DuplicatesReportingMode]
    mode = st.selectbox(
        ctx.t("flow.mode"),
        modes,
        format_func=lambda value: ctx.t(f"flow.mode_{value}"),
        key="flow_mode",
    )
    outcome = actions.load_flow(ctx.messages, folder, mode)
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return
    assert outcome.value is not None
    flow, warnings = outcome.value
    for warning in warnings:
        st.warning(f"{warning.code}: {warning.message}")
    if warnings:
        st.caption(ctx.t("flow.stale_hint"))

    st.subheader(ctx.t("flow.identification"))
    metric_row(
        st,
        [
            (ctx.t("flow.identified"), flow.records_identified_total),
            (ctx.t("flow.duplicates"), flow.duplicates_removed),
            (ctx.t("flow.other"), flow.records_removed_before_screening_other),
            (ctx.t("flow.to_screen"), flow.records_to_screen),
        ],
    )
    if flow.records_identified_by_source:
        st.table(
            {
                ctx.t("data.source"): list(flow.records_identified_by_source),
                ctx.t("bar.records"): list(flow.records_identified_by_source.values()),
            }
        )
    if flow.prefilter_reasons:
        st.write(f"**{ctx.t('flow.prefilter')}**")
        st.table(
            {
                ctx.t("check.reason"): list(flow.prefilter_reasons),
                ctx.t("check.count"): list(flow.prefilter_reasons.values()),
            }
        )
    st.caption(ctx.t("flow.missing_abstracts", count=flow.records_with_missing_abstracts))
    if flow.records_identified_total == 0:
        st.info(ctx.t("flow.none_yet"))
