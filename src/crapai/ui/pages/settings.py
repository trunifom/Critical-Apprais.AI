"""Settings page: every important setting as a form, where each value comes from, paths, prices."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from crapai.logging_setup import LEVEL_ENV, LOG_FILE_NAME, resolve_level
from crapai.project.workspace import Workspace
from crapai.ui import actions
from crapai.ui.context import Context
from crapai.ui.pages.common import intro, show_error
from crapai.ui.settings_form import SECTIONS, Field

VERSION_KEY = "settings_version"


def _label(ctx: Context, key: str) -> str:
    return ctx.t("setting." + key.replace(".", "_"))


def _widget(st: Any, ctx: Context, form_field: Field, value: Any, key: str) -> Any:
    """Draw the widget for one field and return what the user entered (raw)."""
    label = _label(ctx, form_field.key)
    kind = form_field.kind
    if kind == "bool":
        return st.checkbox(label, value=bool(value), key=key)
    if kind == "choice":
        choices = list(form_field.choices)
        index = choices.index(value) if value in choices else 0
        return st.selectbox(label, choices, index=index, key=key)
    if kind == "int":
        return st.number_input(
            label,
            min_value=int(form_field.minimum or 0),
            max_value=int(form_field.maximum) if form_field.maximum is not None else None,
            value=int(value if value is not None else (form_field.minimum or 0)),
            step=1,
            key=key,
        )
    if kind == "float":
        return st.number_input(
            label,
            min_value=float(form_field.minimum or 0.0),
            max_value=float(form_field.maximum) if form_field.maximum is not None else None,
            value=float(value if value is not None else (form_field.minimum or 0.0)),
            step=float(form_field.step or 0.1),
            key=key,
        )
    if kind == "list":
        return st.text_input(label, value=", ".join(value or []), key=key)
    text = "" if value is None else str(value)  # text and optional_float
    return st.text_input(label, value=text, key=key)


def _report(st: Any, ctx: Context, count: int, done: str, none: str) -> None:
    st.session_state.pop("overview_token", None)
    st.success(ctx.t(done, count=count) if count else ctx.t(none))


def _form(st: Any, ctx: Context, folder: Path) -> None:
    st.subheader(ctx.t("settings.form"))
    st.caption(ctx.t("settings_form.intro"))
    settings = actions.load_settings(folder)
    if not settings:
        return
    version = st.session_state.get(VERSION_KEY, 0)
    edited: dict[str, Any] = {}
    with st.form(f"settings-form-{version}"):
        for section in SECTIONS:
            with st.expander(ctx.t(f"section.{section.name}"), expanded=section.name == "quality"):
                for form_field in section.fields:
                    setting = settings.get(form_field.key)
                    edited[form_field.key] = _widget(
                        st,
                        ctx,
                        form_field,
                        setting.value if setting else None,
                        f"set::{form_field.key}::{version}",
                    )
                    if setting and setting.source == "overrides":
                        st.caption("↳ " + ctx.t("settings_form.changed_here"))
        saved = st.form_submit_button(
            ctx.t("settings_form.save"), type="primary", key="save_settings"
        )
    if saved:
        outcome = actions.save_settings(ctx.messages, folder, edited)
        if outcome.error is not None:
            show_error(st, ctx, outcome.error)
        else:
            st.session_state[VERSION_KEY] = version + 1
            _report(
                st, ctx, len(outcome.value or {}), "settings_form.saved", "settings_form.unchanged"
            )
    if st.button(ctx.t("settings_form.reset"), key="reset_settings"):
        outcome_reset = actions.reset_settings(ctx.messages, folder)
        if outcome_reset.error is not None:
            show_error(st, ctx, outcome_reset.error)
        else:
            st.session_state[VERSION_KEY] = version + 1
            _report(
                st,
                ctx,
                len(outcome_reset.value or []),
                "settings_form.reset_done",
                "settings_form.reset_none",
            )
    with st.expander(ctx.t("settings_form.sources")):
        st.dataframe(
            [{"key": s.key, "value": str(s.value), "source": s.source} for s in settings.values()],
            width="stretch",
            hide_index=True,
        )


def render(st: Any, ctx: Context) -> None:
    """Draw the settings page: form, sources of the values, paths and the price list."""
    st.header(ctx.t("settings.title"))
    intro(st, ctx, "settings")
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
    _form(st, ctx, folder)

    st.subheader(ctx.t("settings.pricing"))
    st.caption(ctx.t("settings.pricing_hint"))
    path = workspace.pricing_csv
    if not path.exists():
        st.info(ctx.t("settings.no_pricing", path=path.name))
        return
    outcome = actions.read_pricing_table(ctx.messages, path)
    if outcome.error is not None:
        show_error(st, ctx, outcome.error)
        return
    st.dataframe(outcome.value, width="stretch", hide_index=True)
