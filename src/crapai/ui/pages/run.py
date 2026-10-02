"""Run page: start, watch, pause, stop and resume a screening run.

The run itself works in a **separate process** (``python -m crapai screen ...``, started by
:func:`crapai.ui.actions.start_run`); this page never screens anything. It only

* starts that process and asks it to pause or stop (a small file, ``control.json``),
* reads ``manifest.json`` of the runs and draws the state: a progress bar that refreshes itself
  every two seconds while a run is working, the counts, the batch table, the problem that stopped
  a run and what to do about it.

Because the state lives in files, closing the tab, restarting the interface or starting the
interface later on shows the same picture, and a run started here can be resumed from the command
line and the other way round.
"""

from __future__ import annotations

import time
from typing import Any

from crapai.cost.duration import format_duration
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, metric_row, show_error
from crapai.ui.viewmodels import RunView, failed_results, load_run_views

REFRESH_SECONDS = 2
START_WAIT_SECONDS = 60  # how long to wait for the new process to write its first manifest


def _percent(view: RunView) -> int:
    return int(view.fraction * 100)


def _progress(st: Any, ctx: Context, view: RunView) -> None:
    """The progress bar and the counts of one run."""
    st.progress(
        view.fraction,
        text=ctx.t("run.progress", done=view.done, total=view.total, percent=_percent(view)),
    )
    metric_row(
        st,
        [
            (ctx.t("run.ok"), view.ok),
            (ctx.t("run.errors"), view.errors),
            (ctx.t("run.cost", currency=view.currency), f"{view.cost:.4f}"),
            (ctx.t("run.batch"), f"{view.batch}/{view.batches}"),
        ],
    )


def _batch_table(st: Any, ctx: Context, view: RunView) -> None:
    rows = [
        {
            ctx.t("run.col.batch"): int(row.get("index", 0)) + 1,  # type: ignore[call-overload]
            ctx.t("run.col.size"): row.get("size", 0),
            ctx.t("run.col.done"): row.get("done", 0),
            ctx.t("run.col.ok"): row.get("ok", 0),
            ctx.t("run.col.errors"): row.get("errors", 0),
            ctx.t("run.col.status"): row.get("status", ""),
        }
        for row in view.batch_rows
        if row
    ]
    if rows:
        with st.expander(ctx.t("run.batches"), expanded=view.running):
            st.dataframe(rows, width="stretch", hide_index=True)


def _live(st: Any, ctx: Context, run_id: str) -> None:
    """The part that refreshes itself while a run works."""
    assert ctx.folder is not None
    view = next((v for v in load_run_views(ctx.folder) if v.run_id == run_id), None)
    if view is None or not view.running:
        st.session_state.pop("starting_since", None)
        st.rerun()  # the run ended: draw the final state on the whole page
        return
    _progress(st, ctx, view)
    if view.stalled:
        st.warning(ctx.t("run.stalled", age=format_duration(view.age_s or 0)))
    left, right, _ = st.columns([1, 1, 4])
    if left.button(ctx.t("run.pause"), key="run_pause"):
        _control(st, ctx, view.run_id, "pause")
    if right.button(ctx.t("run.stop"), key="run_stop"):
        _control(st, ctx, view.run_id, "stop")
    _batch_table(st, ctx, view)


def _control(st: Any, ctx: Context, run_id: str, command: str) -> None:
    assert ctx.folder is not None
    outcome = actions.control_run(ctx.messages, ctx.folder, run_id, command)
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
    else:
        st.info(ctx.t("run.control_sent", command=command))


def _final_state(st: Any, ctx: Context, view: RunView) -> None:
    """How the newest run ended, in words, with the code and what to do."""
    text = ctx.messages.text(
        f"cli.screen.result.{view.state}",
        run_id=view.run_id,
        ok=view.ok,
        errors=view.errors,
        done=view.done,
        total=view.total,
        reason=view.stop_reason or "-",
    )
    if view.state == "completed":
        (st.warning if view.errors else st.success)(text)
    elif view.state in ("paused", "interrupted"):
        st.warning(text)
    elif view.state == "running":
        st.error(ctx.t("run.stalled", age=format_duration(view.age_s or 0)))
    else:
        st.error(text)
    if view.last_error:
        st.error(
            ctx.messages.text(
                "cli.screen.error_line",
                code=view.last_error.get("code", ""),
                message=view.last_error.get("message", ""),
            ).strip()
        )
    for warning in view.warnings:
        st.warning(ctx.messages.text("cli.screen.warning", text=warning))
    _progress(st, ctx, view)
    _batch_table(st, ctx, view)
    if view.errors:
        assert ctx.folder is not None
        rows = failed_results(ctx.folder, view.run_id)
        with st.expander(ctx.t("run.failed_records", count=view.errors)):
            st.dataframe(rows, width="stretch", hide_index=True)
            st.caption(ctx.t("run.failed_hint"))


def _start_panel(st: Any, ctx: Context, *, resume_view: RunView | None) -> None:
    """Settings summary, estimate and the start (or resume) button."""
    assert ctx.folder is not None
    config_outcome = actions.read_project_config(ctx.messages, ctx.folder)
    if config_outcome.error is not None:
        show_error(st, ctx, config_outcome.error)
        return
    config = config_outcome.value
    assert config is not None
    st.caption(
        ctx.t(
            "run.model_line",
            provider=config.llm.provider,
            model=config.llm.model,
            variant=config.screening.prompt_variant,
            batch_size=config.run.batch_size,
        )
    )
    map_reduce_blocked = False
    if config.project.mode == "fulltext":
        st.caption(ctx.t("run.fulltext_line", strategy=config.screening.fulltext.strategy))
        if config.screening.fulltext.strategy == "map_reduce":
            map_reduce_blocked = True
            st.warning(ctx.t("run.map_reduce_warning"))
    if config.llm.provider not in ("mock",):
        st.caption(ctx.t("run.key_hint", variable=config.llm.api_key_env))
    estimate = actions.estimate_run(ctx.messages, ctx.folder)
    if estimate.error is not None:
        st.info(ctx.messages.text("cli.screen.estimate_none", reason=estimate.error.title))
    elif estimate.value is not None:
        _estimate(st, ctx, estimate.value)

    sample = 0
    if resume_view is None:
        sample = int(
            st.number_input(ctx.t("run.sample"), min_value=0, value=0, step=10, key="run_sample")
        )
    agreed = st.checkbox(ctx.t("run.confirm"), key="run_confirm")
    label = ctx.t("run.resume") if resume_view is not None else ctx.t("run.start")
    if st.button(
        label, key="run_start", type="primary", disabled=not agreed or map_reduce_blocked
    ):
        outcome = actions.start_run(
            ctx.messages,
            ctx.folder,
            lang=ctx.lang,
            sample=sample or None,
            resume=resume_view is not None,
        )
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
            return
        st.session_state["starting_since"] = time.monotonic()
        st.session_state.pop("overview_token", None)
        st.rerun()


def _estimate(st: Any, ctx: Context, estimate: Any) -> None:
    run = estimate.estimate
    if run.cost is None:
        st.info(
            ctx.messages.text(
                "cli.screen.estimate_none", reason=ctx.messages.text("cli.check.cost.no_price")
            )
        )
        return
    st.info(
        ctx.messages.text(
            "cli.screen.estimate",
            low=f"{run.cost_low:.4f}",
            high=f"{run.cost_high:.4f}",
            worst=f"{run.cost_max:.4f}",
            currency=run.currency,
            duration=format_duration(estimate.duration.seconds),
        )
    )
    if estimate.over_limit:
        st.warning(ctx.messages.text("cli.screen.over_limit", max_cost=estimate.max_cost))


def _starting(st: Any, ctx: Context) -> None:
    """Wait (refreshing) for the new process to show up; give up with its output after a while."""
    assert ctx.folder is not None
    since = st.session_state.get("starting_since")
    if since is None:
        return
    waited = time.monotonic() - since
    if waited > START_WAIT_SECONDS:
        st.session_state.pop("starting_since", None)
        st.error(ctx.t("run.start_failed"))
        output = actions.screen_output_tail(ctx.folder)
        if output:
            st.code(output, language="text")
        return
    st.info(ctx.t("run.starting"))


def _history(st: Any, ctx: Context, views: list[RunView]) -> None:
    rows = [
        {
            ctx.t("run.col.run"): v.run_id,
            ctx.t("run.col.state"): v.state,
            ctx.t("run.col.kind"): v.kind,
            ctx.t("run.col.progress"): f"{v.done}/{v.total}",
            ctx.t("run.col.errors"): v.errors,
            ctx.t("run.col.cost"): f"{v.cost:.4f} {v.currency}",
            ctx.t("run.col.updated"): v.updated_at,
        }
        for v in reversed(views)
    ]
    with st.expander(ctx.t("run.history", count=len(rows))):
        st.dataframe(rows, width="stretch", hide_index=True)


def render(st: Any, ctx: Context) -> None:
    """Draw the run page for the open project."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("run.title"))
    intro(st, ctx, "run")
    views = load_run_views(folder)
    active = next((v for v in reversed(views) if v.running and not v.stalled), None)
    starting = "starting_since" in st.session_state

    if active is not None:
        st.session_state.pop("starting_since", None)
        st.subheader(ctx.t("run.running", run_id=active.run_id))
        fragment = getattr(st, "fragment", None)
        if fragment is not None:
            fragment(run_every=REFRESH_SECONDS)(_live)(st, ctx, active.run_id)
        else:  # very old Streamlit: a static picture and a refresh button
            _progress(st, ctx, active)
            st.button(ctx.t("run.refresh"), key="run_refresh")
        _history(st, ctx, views)
        return

    if starting:
        _starting(st, ctx)
        fragment = getattr(st, "fragment", None)
        if fragment is not None:
            fragment(run_every=REFRESH_SECONDS)(_watch_start)(st, ctx)

    latest = views[-1] if views else None
    if starting:
        pass  # the previous state would only confuse while the new process comes up
    elif latest is not None:
        _final_state(st, ctx, latest)
    else:
        st.info(ctx.t("run.no_runs"))
        output = actions.screen_output_tail(folder)
        if output:
            with st.expander(ctx.t("run.output")):
                st.code(output, language="text")

    st.divider()
    resumable = latest if latest is not None and latest.resumable else None
    if resumable is not None:
        st.subheader(ctx.t("run.resume_title"))
        st.caption(ctx.t("run.resume_info"))
    else:
        st.subheader(ctx.t("run.new_title"))
    if not starting:
        _start_panel(st, ctx, resume_view=resumable)
    if resumable is not None and not starting:
        st.caption(ctx.t("run.new_instead"))
    if views:
        _history(st, ctx, views)


def _watch_start(st: Any, ctx: Context) -> None:
    """Refreshes the page as soon as the new process has written its manifest."""
    assert ctx.folder is not None
    if any(v.running for v in load_run_views(ctx.folder)) or (
        "starting_since" not in st.session_state
    ):
        st.rerun()
