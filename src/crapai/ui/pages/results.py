"""Evaluation page: charts and tables of the screening results.

The data comes from one of two places:

* a **screening run of the open project** (the newest one, or any other with results), or
* an **exported results table** (CSV or XLSX from the Export page) that you upload, so a finished
  review can be looked at again without the project folder.

Everything is computed by :mod:`crapai.stats.results` and drawn by :mod:`crapai.ui.charts`; this
page only arranges the sections. Each section can be folded away.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from crapai.project.workspace import Workspace
from crapai.services.results import runs_with_results
from crapai.stats import results as stats
from crapai.ui import actions, charts
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, metric_row, show_error
from crapai.ui.viewmodels import percent

TABLE_ROWS = 500
TABLE_COLUMNS = (
    "title", "year", "source_label", "outcome", "exclusion_reason", "reasoning", "flags",
)  # fmt: skip


def _label(ctx: Context):  # type: ignore[no-untyped-def]
    return lambda name: ctx.t(f"outcome.{name}")


def _chart(st: Any, spec: dict[str, Any]) -> None:
    st.vega_lite_chart(spec, width="stretch", theme=None)


def _load(st: Any, ctx: Context) -> list[dict[str, Any]] | None:
    """Choose the source and return the table (None if there is nothing to show yet)."""
    sources = ["file"] if ctx.folder is None else ["project", "file"]
    source = st.radio(
        ctx.t("results.source"),
        sources,
        format_func=lambda value: ctx.t(f"results.source_{value}"),
        horizontal=True,
        key="results_source",
    )
    if source == "project":
        assert ctx.folder is not None
        runs = runs_with_results(Workspace(ctx.folder))
        if not runs:
            st.info(ctx.t("results.no_runs"))
            return None
        run_id = st.selectbox(ctx.t("results.run"), list(reversed(runs)), key="results_run")
        outcome = actions.load_results(ctx.messages, ctx.folder, run_id)
    else:
        st.caption(ctx.t("results.file_hint"))
        upload = st.file_uploader(
            ctx.t("results.upload"), type=["csv", "xlsx"], key="results_upload"
        )
        if upload is None:
            st.info(ctx.t("results.no_file"))
            return None
        outcome = actions.read_results_file(ctx.messages, upload.name, upload.getvalue())
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return None
    return outcome.value


def _summary(st: Any, ctx: Context, a: stats.Analysis, theme: str) -> None:
    label = _label(ctx)
    metric_row(
        st,
        [
            (ctx.t("results.total"), a.total),
            (label("INCLUDE"), a.by_outcome["INCLUDE"]),
            (label("EXCLUDE"), a.by_outcome["EXCLUDE"]),
            (label("UNCERTAIN"), a.by_outcome["UNCERTAIN"]),
            (label("ERROR"), a.by_outcome["ERROR"]),
        ],
    )
    if a.screened:
        st.caption(
            ctx.t(
                "results.shares",
                include=percent(a.by_outcome["INCLUDE"], a.screened),
                exclude=percent(a.by_outcome["EXCLUDE"], a.screened),
                uncertain=percent(a.by_outcome["UNCERTAIN"], a.screened),
            )
        )
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{ctx.t('results.donut')}**")
        _chart(st, charts.donut(a.by_outcome, theme, label))
    with right:
        st.markdown(f"**{ctx.t('results.bars')}**")
        items = [(label(n), c) for n, c in a.by_outcome.items() if c]
        _chart(
            st,
            charts.bars(
                items, theme, x_title=ctx.t("results.outcome"), y_title=ctx.t("results.count")
            ),
        )


def _sections(
    st: Any, ctx: Context, rows: list[dict[str, Any]], a: stats.Analysis, theme: str
) -> None:
    label = _label(ctx)
    with st.expander(ctx.t("results.s_decisions"), expanded=True):
        _summary(st, ctx, a, theme)
    if len(a.by_source) > 0:
        with st.expander(ctx.t("results.s_source"), expanded=True):
            st.caption(ctx.t("results.s_source_hint"))
            share = st.checkbox(ctx.t("results.shares_toggle"), key="results_normalise")
            _chart(
                st,
                charts.stacked(
                    a.by_source,
                    theme,
                    label,
                    category_title=ctx.t("results.source_label"),
                    count_title=ctx.t("results.share" if share else "results.count"),
                    horizontal=True,
                    normalise=share,
                ),
            )
    if a.by_year:
        with st.expander(ctx.t("results.s_year"), expanded=False):
            _chart(
                st,
                charts.stacked(
                    a.by_year,
                    theme,
                    label,
                    category_title=ctx.t("results.year"),
                    count_title=ctx.t("results.count"),
                    numeric_axis=True,
                ),
            )
    if a.word_bins:
        with st.expander(ctx.t("results.s_length"), expanded=False):
            st.caption(ctx.t("results.s_length_hint"))
            _chart(
                st,
                charts.histogram(
                    a.word_bins,
                    theme,
                    label,
                    x_title=ctx.t("results.words"),
                    y_title=ctx.t("results.count"),
                ),
            )
            left, right = st.columns(2)
            with left:
                st.markdown(f"**{ctx.t('results.box')}**")
                _chart(st, charts.boxplot(a.points, theme, label, y_title=ctx.t("results.words")))
            with right:
                st.markdown(f"**{ctx.t('results.scatter')}**")
                _chart(
                    st,
                    charts.scatter(
                        a.points,
                        theme,
                        label,
                        x_title=ctx.t("results.year"),
                        y_title=ctx.t("results.words"),
                    ),
                )
    if a.status_counts or a.flag_counts or a.consistency:
        with st.expander(ctx.t("results.s_quality"), expanded=False):
            st.caption(ctx.t("results.s_quality_hint"))
            columns = st.columns(3)
            for column, title, data in (
                (columns[0], "results.status", a.status_counts),
                (columns[1], "results.flags", a.flag_counts),
                (
                    columns[2],
                    "results.consistency",
                    {ctx.t(f"results.{k}"): v for k, v in a.consistency.items()},
                ),
            ):
                with column:
                    st.markdown(f"**{ctx.t(title)}**")
                    if data:
                        _chart(
                            st,
                            charts.bars(
                                list(data.items()),
                                theme,
                                x_title=ctx.t(title),
                                y_title=ctx.t("results.count"),
                            ),
                        )
                    else:
                        st.caption(ctx.t("results.none"))
    if a.batches:
        with st.expander(ctx.t("results.s_usage"), expanded=False):
            metric_row(
                st,
                [
                    (ctx.t("results.tokens_in"), f"{a.tokens_in:,}"),
                    (ctx.t("results.tokens_out"), f"{a.tokens_out:,}"),
                    (ctx.t("results.cost"), "-" if a.cost is None else f"{a.cost:.4f}"),
                ],
            )
            tokens = [(str(b["batch"]), b["tokens_in"] + b["tokens_out"]) for b in a.batches]
            _chart(
                st,
                charts.bars(
                    tokens,
                    theme,
                    x_title=ctx.t("results.batch"),
                    y_title=ctx.t("results.tokens"),
                    horizontal=False,
                ),
            )
            if a.latency_bins:
                st.markdown(f"**{ctx.t('results.latency')}**")
                _chart(
                    st,
                    charts.histogram(
                        a.latency_bins,
                        theme,
                        label,
                        x_title=ctx.t("results.seconds"),
                        y_title=ctx.t("results.count"),
                    ),
                )
    if a.reason_counts:
        with st.expander(ctx.t("results.s_reasons"), expanded=False):
            st.caption(ctx.t("results.s_reasons_hint"))
            _chart(
                st,
                charts.bars(
                    list(a.reason_counts.items()),
                    theme,
                    x_title=ctx.t("results.reason"),
                    y_title=ctx.t("results.count"),
                ),
            )
    if a.uncertain:
        with st.expander(
            ctx.t("results.s_uncertain", count=a.by_outcome["UNCERTAIN"]), expanded=False
        ):
            st.caption(ctx.t("results.s_uncertain_hint"))
            st.dataframe(
                [{k: r.get(k, "") for k in TABLE_COLUMNS} for r in a.uncertain],
                width="stretch",
                hide_index=True,
            )
    _table(st, ctx, rows)


def _table(st: Any, ctx: Context, rows: list[dict[str, Any]]) -> None:
    with st.expander(ctx.t("results.s_table"), expanded=False):
        chosen = st.multiselect(
            ctx.t("results.filter"),
            list(stats.OUTCOMES),
            default=[],
            format_func=_label(ctx),
            key="results_filter",
        )
        shown = [r for r in rows if not chosen or r.get("outcome") in chosen]
        st.caption(ctx.t("results.rows", shown=min(len(shown), TABLE_ROWS), total=len(shown)))
        st.dataframe(
            [{k: r.get(k, "") for k in TABLE_COLUMNS} for r in shown[:TABLE_ROWS]],
            width="stretch",
            hide_index=True,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(stats.RESULT_COLUMNS)
        for r in shown:
            writer.writerow(["" if r.get(c) is None else r.get(c) for c in stats.RESULT_COLUMNS])
        st.download_button(
            ctx.t("results.download"),
            data="﻿" + buffer.getvalue(),
            file_name="results-selection.csv",
            mime="text/csv",
            key="results_download",
        )


def _compare(st: Any, ctx: Context, folder: Any, available: list[str], theme: str) -> None:
    with st.expander(ctx.t("results.s_compare"), expanded=False):
        st.caption(ctx.t("results.s_compare_hint"))
        options = list(reversed(available))
        chosen = st.multiselect(
            ctx.t("results.compare_pick"),
            options,
            default=options[:2],
            key="results_compare_runs",
        )
        if len(chosen) < 2:
            st.info(ctx.t("results.compare_need_two"))
            return
        outcome = actions.compare_runs(ctx.messages, folder, chosen)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
            return
        assert outcome.value is not None
        rows, summary = outcome.value
        st.dataframe(
            [
                {
                    ctx.t("results.compare_run_a"): p.run_a,
                    ctx.t("results.compare_run_b"): p.run_b,
                    ctx.t("results.compare_n"): p.n,
                    ctx.t("results.compare_agreement"): f"{p.agreement * 100:.1f} %",
                    ctx.t("results.compare_kappa"): "-" if p.kappa is None else f"{p.kappa:.3f}",
                    ctx.t("results.compare_label"): p.label or "-",
                }
                for p in summary.pairwise
            ],
            width="stretch",
            hide_index=True,
        )
        if summary.fleiss_kappa is not None:
            metric_row(
                st,
                [
                    (
                        ctx.t("results.compare_fleiss"),
                        f"{summary.fleiss_kappa:.3f} ({summary.fleiss_label})",
                    ),
                    (ctx.t("results.compare_n_common"), summary.n_common),
                    (ctx.t("results.compare_unstable_count"), len(summary.unstable)),
                ],
            )
        label = _label(ctx)
        counts_by_run: dict[str, Counter[str]] = {run_id: Counter() for run_id in chosen}
        for row in rows:
            for run_id in chosen:
                decision = row.get(f"decision__{run_id}")
                if decision:
                    counts_by_run[run_id][str(decision)] += 1
        st.markdown(f"**{ctx.t('results.compare_chart')}**")
        _chart(
            st,
            charts.run_bars(
                counts_by_run,
                theme,
                label,
                run_ids=chosen,
                category_title=ctx.t("results.outcome"),
                count_title=ctx.t("results.count"),
                legend_title=ctx.t("results.compare_run_legend"),
            ),
        )
        if summary.unstable:
            with st.expander(
                ctx.t("results.compare_unstable", count=len(summary.unstable)), expanded=False
            ):
                unstable_rows = [
                    {"study_uid": u.study_uid, **u.decisions}
                    for u in summary.unstable[:TABLE_ROWS]
                ]
                st.dataframe(unstable_rows, width="stretch", hide_index=True)


def render(st: Any, ctx: Context) -> None:
    """Draw the evaluation page for the open project or for an uploaded results file."""
    st.header(ctx.t("results.title"))
    intro(st, ctx, "results")
    rows = _load(st, ctx)
    if rows is None:
        return
    analysis = stats.analyse(rows)
    theme = st.session_state.get("theme", "light")
    _sections(st, ctx, rows, analysis, theme)
    if ctx.folder is not None:
        available = runs_with_results(Workspace(ctx.folder))
        if len(available) >= 2:
            _compare(st, ctx, ctx.folder, available, theme)
