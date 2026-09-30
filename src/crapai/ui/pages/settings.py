"""Settings page: language, paths, log level and the price list."""

from __future__ import annotations

import csv
import logging
from typing import Any

from crapai.cost.pricing import CsvPriceSource
from crapai.errors import SaraError
from crapai.logging_setup import LEVEL_ENV, LOG_FILE_NAME, resolve_level
from crapai.project.workspace import Workspace
from crapai.ui.context import Context
from crapai.ui.pages.common import show_error


def render(st: Any, ctx: Context) -> None:
    """Draw the settings page: language, paths, log level and the price list."""
    st.header(ctx.t("settings.title"))
    st.write(f"**{ctx.t('settings.language')}:** {ctx.lang}")
    st.caption(ctx.t("settings.language_hint"))
    st.write(f"**{ctx.t('settings.log_level')}:** {logging.getLevelName(resolve_level())}  ")
    st.caption(ctx.t("settings.log_level_hint", variable=LEVEL_ENV))
    st.write(f"**{ctx.t('settings.recent_file')}:** `{ctx.recent.path}`")
    folder = ctx.folder
    if folder is None:
        return
    workspace = Workspace(folder)
    st.write(f"**{ctx.t('settings.log_file')}:** `{workspace.state_dir / LOG_FILE_NAME}`")
    st.write(f"**{ctx.t('settings.exports')}:** `{workspace.exports_dir}`")

    st.subheader(ctx.t("settings.pricing"))
    st.caption(ctx.t("settings.pricing_hint"))
    path = workspace.pricing_csv
    if not path.exists():
        st.info(ctx.t("settings.no_pricing", path=path.name))
        return
    try:
        CsvPriceSource(path)  # validates the file and logs bad rows
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";" if ";" in handle.readline() else ","))
        st.dataframe(rows, use_container_width=True, hide_index=True)
    except SaraError as error:
        show_error(st, ctx, ctx.messages.error_report(error))
    except (OSError, UnicodeDecodeError, csv.Error):
        st.error(ctx.t("settings.pricing_unreadable", path=path.name))
