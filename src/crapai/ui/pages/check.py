"""Check page: duplicates, pre-filters, validity, then cost and duration of a run."""

from __future__ import annotations

from typing import Any

from crapai.cost.duration import format_duration
from crapai.ui import actions
from crapai.ui.actions import CheckResult
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, metric_row, show_error
from crapai.ui.viewmodels import percent, status_icon

BLOCKING = {"no_records", "nothing_to_screen"}


def _report(st: Any, ctx: Context, result: CheckResult) -> None:
    report = result.report
    status = report.status.value
    icon = status_icon(status)
    headline = f"{icon} {ctx.messages.text(f'cli.check.status.{status}')}"
    {"ok": st.success, "warning": st.warning, "error": st.error}[status](headline)
    metric_row(
        st,
        [
            (ctx.t("bar.records"), report.records),
            (ctx.t("bar.duplicates"), report.duplicates),
            (ctx.t("bar.valid"), report.valid_for_model),
        ],
    )
    if report.sources:
        st.write(f"**{ctx.messages.text('cli.check.sources')}**")
        st.table(
            [
                {
                    ctx.t("data.source"): s.label,
                    ctx.t("bar.records"): s.records,
                    ctx.t("bar.abstracts"): percent(s.with_abstract, s.records),
                    ctx.t("bar.duplicates"): s.duplicates,
                    ctx.t("bar.valid"): s.valid_for_model,
                    ctx.t("data.status"): status_icon(s.status.value),
                }
                for s in report.sources
            ]
        )
    if report.by_reason:
        st.write(f"**{ctx.messages.text('cli.check.reasons')}**")
        st.table(
            [
                {
                    ctx.t("check.reason"): reason,
                    ctx.t("check.count"): count,
                    ctx.t("check.meaning"): ctx.messages.text(f"cli.check.reason.{reason}"),
                }
                for reason, count in sorted(report.by_reason.items())
            ]
        )
    for issue in report.issues:
        text = ctx.messages.text(
            f"cli.check.issue.{issue.value}",
            suspect=report.quality.get("suspect_concat", 0),
            retracted=report.retracted_included,
            problem=report.config_problem or "",
        )
        (st.error if issue.value in BLOCKING else st.warning)(text)


def _estimate(st: Any, ctx: Context, result: CheckResult) -> None:
    if result.estimate_error is not None:
        show_error(st, ctx, result.estimate_error)
        return
    estimate = result.estimate
    if estimate is None:
        st.info(ctx.t("check.no_estimate"))
        return
    run = estimate.estimate
    st.subheader(ctx.t("check.estimate"))
    st.caption(
        ctx.messages.text("cli.check.cost.model", provider=estimate.provider, model=estimate.model)
    )
    kind = "cli.check.cost.exact" if run.exact else "cli.check.cost.approximate"
    metric_row(
        st,
        [
            (ctx.t("check.input_tokens"), f"{run.input_tokens:,}"),
            (ctx.t("check.output_tokens"), f"{run.output_tokens:,}"),
            (ctx.t("check.duration"), format_duration(estimate.duration.seconds)),
        ],
    )
    st.caption(ctx.messages.text(kind))
    if run.cost is None:
        st.info(ctx.messages.text("cli.check.cost.no_price"))
    else:
        st.metric(
            ctx.t("check.cost", currency=run.currency),
            f"{run.cost_low:.4f} – {run.cost_high:.4f}",
            help=ctx.t("check.worst_case", worst=f"{run.cost_max:.4f}", currency=run.currency),
        )
    if estimate.over_limit:
        st.warning(ctx.messages.text("cli.check.cost.over_limit", max_cost=estimate.max_cost))


def render(st: Any, ctx: Context) -> None:
    """Draw the check page: a button, the report of the last check and the estimate."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("check.title"))
    intro(st, ctx, "check")
    read_only = st.checkbox(ctx.t("check.read_only"), key="check_read_only")
    if st.button(ctx.t("check.run"), key="run_check", type="primary"):
        with st.spinner(ctx.t("check.running")):
            outcome = actions.run_check(ctx.messages, folder, update=not read_only)
        st.session_state.pop("overview_token", None)
        st.session_state["check_outcome"] = outcome
    outcome = st.session_state.get("check_outcome")
    if outcome is None:
        st.info(ctx.t("check.not_run"))
        return
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return
    _report(st, ctx, outcome.value)
    _estimate(st, ctx, outcome.value)
