"""Run page: honest about what this version can do (no model screening yet)."""

from __future__ import annotations

from typing import Any

from crapai.ui.context import Context
from crapai.ui.pages.common import show_locked


def render(st: Any, ctx: Context) -> None:
    """Draw the run page: what is not available yet and what can be done already."""
    st.header(ctx.t("run.title"))
    show_locked(st, ctx, "not_available")
    st.write(ctx.t("run.body"))
    st.markdown("\n".join(f"- {line}" for line in ctx.t("run.ready").split("|")))
