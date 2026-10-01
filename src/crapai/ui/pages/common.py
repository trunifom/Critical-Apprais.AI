"""Drawing helpers shared by the pages: errors, the locked-page notice, small tables."""

from __future__ import annotations

from typing import Any

from crapai.i18n.messages import ErrorReport
from crapai.ui.context import Context


def show_error(st: Any, ctx: Context, report: ErrorReport) -> None:
    """Show an error the way plan chapter 27.2 asks: code, what happened, what to do.

    There is never a stack trace. The details sit in an expander together with a copyable text for
    a bug report.
    """
    st.error(f"{ctx.messages.text('cli.error.prefix', code=report.code)}: {report.title}")
    if report.action:
        st.info(f"{ctx.messages.text('cli.error.action')}: {report.action}")
    with st.expander(ctx.t("error.details")):
        if report.cause:
            st.write(f"**{ctx.messages.text('cli.error.cause')}:** {report.cause}")
        if report.details:
            st.write(f"**{ctx.messages.text('cli.error.details')}:** {report.details}")
        st.code(f"{report.code}: {report.title}\n{report.details}", language="text")


INTRO_PARTS = ("goal", "what", "how", "result")


def intro(st: Any, ctx: Context, page: str) -> None:
    """The short introduction at the top of a page: goal, what happens, how to use it, result.

    It sits in an expander, so it can be folded away once it is known.
    """
    with st.expander(ctx.t("intro.title"), expanded=True):
        for part in INTRO_PARTS:
            st.markdown(
                f'<div class="crapai-intro-row"><span class="crapai-intro-label">'
                f"{ctx.t(f'intro.label.{part}')}</span>"
                f'<span class="crapai-intro-text">{ctx.t(f"intro.{page}.{part}")}</span></div>',
                unsafe_allow_html=True,
            )


def show_locked(st: Any, ctx: Context, reason: str) -> None:
    """Explain why a page cannot be used yet."""
    st.info(ctx.t(f"locked.{reason}"))


def metric_row(st: Any, items: list[tuple[str, object]]) -> None:
    """A row of metric tiles: ``[(label, value), ...]``."""
    columns = st.columns(len(items))
    for column, (label, value) in zip(columns, items, strict=True):
        column.metric(label, value)
