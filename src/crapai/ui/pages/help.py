"""Help page: what the program does with your data, the error catalogue and the project log."""

from __future__ import annotations

from typing import Any

from crapai import __version__
from crapai.branding import PRODUCT_NAME
from crapai.logging_setup import read_log_tail
from crapai.ui.context import Context

LOG_LINES = 200


def error_catalogue(ctx: Context) -> list[dict[str, str]]:
    """The rows of the error table: code, what happened, what to do (in the session language)."""
    return [
        {
            ctx.t("help.code"): code,
            ctx.t("help.what"): ctx.messages.text(f"errors.{code}.title"),
            ctx.t("help.todo"): ctx.messages.text(f"errors.{code}.action"),
        }
        for code in ctx.messages.error_codes()
    ]


def render(st: Any, ctx: Context) -> None:
    """Draw the help page: privacy note, error catalogue and the log of the project."""
    st.header(ctx.t("help.title"))
    st.write(f"**{PRODUCT_NAME}** {__version__}")
    st.write(ctx.t("help.privacy"))
    st.warning(ctx.t("disclaimer"))
    st.subheader(ctx.t("help.errors"))
    st.dataframe(error_catalogue(ctx), use_container_width=True, hide_index=True)
    st.subheader(ctx.t("help.log"))
    if ctx.folder is None:
        st.info(ctx.t("locked.needs_project"))
        return
    lines = read_log_tail(ctx.folder, LOG_LINES)
    if not lines:
        st.info(ctx.t("help.no_log"))
        return
    st.button(ctx.t("help.refresh"), key="refresh_log")
    st.code("\n".join(lines), language="text")
    st.download_button(
        ctx.t("help.download_log"),
        data="\n".join(lines),
        file_name="crapai-log.txt",
        mime="text/plain",
        key="download_log",
    )
