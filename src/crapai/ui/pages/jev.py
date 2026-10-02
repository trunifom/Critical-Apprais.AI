"""Jev pre-filter page (ADR 0029): a special, opt-in triage step, separate from the run page.

Jev is not a chat-completion language model: it answers one typed yes/no question per record with
a calibrated probability, never free text. It can only mark a record excluded (never included) and
gives no quote or reasoning for its answer, unlike the ordinary screening step. This page always
explains what it is and is not, even while switched off; it runs nothing by itself -- starting it
always needs ``ai_prefilter.enabled`` on in the settings *and* the confirmation checkbox below.
"""

from __future__ import annotations

from typing import Any

from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, show_error


def _explanation(st: Any, ctx: Context) -> None:
    st.info(ctx.t("jev.explanation"))


def _estimate(st: Any, ctx: Context, estimate: Any) -> None:
    if estimate.n_items == 0:
        st.info(ctx.t("jev.nothing_to_check"))
        return
    if estimate.cost is None:
        st.info(
            ctx.messages.text(
                "cli.jev.estimate_none", reason=ctx.messages.text("cli.check.cost.no_price")
            )
        )
        return
    st.info(
        ctx.messages.text(
            "cli.jev.estimate",
            n_items=estimate.n_items,
            tokens_in=estimate.tokens_in,
            cost=f"{estimate.cost:.4f}",
            currency="USD",
        )
    )


def _disabled_panel(st: Any, ctx: Context) -> None:
    st.warning(ctx.t("jev.disabled"))


def _enabled_panel(st: Any, ctx: Context) -> None:
    assert ctx.folder is not None
    estimate = actions.estimate_jev(ctx.messages, ctx.folder)
    if estimate.error is not None:
        st.info(ctx.messages.text("cli.jev.estimate_none", reason=estimate.error.title))
    elif estimate.value is not None:
        _estimate(st, ctx, estimate.value)
    agreed = st.checkbox(ctx.t("jev.confirm"), key="jev_confirm")
    if st.button(ctx.t("jev.start"), key="jev_start", type="primary", disabled=not agreed):
        with st.spinner(ctx.t("jev.running")):
            outcome = actions.run_jev_prefilter(ctx.messages, ctx.folder)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
            return
        summary = outcome.value
        assert summary is not None
        st.success(
            ctx.messages.text(
                "cli.jev.done",
                marked=summary.marked,
                eligible=summary.eligible,
                checked=summary.checked,
                records=summary.records,
                cost=f"{summary.cost:.4f}",
            )
        )
        st.session_state.pop("overview_token", None)


def render(st: Any, ctx: Context) -> None:
    """Draw the Jev pre-filter page: always the explanation, then the gated start panel."""
    folder = ctx.folder
    assert folder is not None
    st.header(ctx.t("jev.title"))
    intro(st, ctx, "jev")
    _explanation(st, ctx)
    config_outcome = actions.read_project_config(ctx.messages, folder)
    if config_outcome.error is not None:
        show_error(st, ctx, config_outcome.error)
        return
    config = config_outcome.value
    assert config is not None
    if not config.ai_prefilter.enabled:
        _disabled_panel(st, ctx)
        return
    st.caption(
        ctx.t(
            "jev.model_line",
            model=config.ai_prefilter.model,
            confidence_floor=config.ai_prefilter.confidence_floor,
        )
    )
    _enabled_panel(st, ctx)
