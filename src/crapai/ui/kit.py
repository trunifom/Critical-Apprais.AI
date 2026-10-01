"""A thin cover around ``streamlit`` that the pages draw with.

The pages call ``st.info(...)``, ``st.button(...)`` and so on. The cover keeps their code
unchanged but adds two things in one place:

* **Own notice boxes.** ``info``, ``success``, ``warning`` and ``error`` draw boxes whose colours
  come from the chosen palette (:mod:`crapai.ui.theme`), so text stays readable in the light and
  in the dark design. Streamlit's own alerts take their colours from Streamlit's theme, which can
  differ from the chosen one.
* **Help for every control.** A widget that has a ``key`` gets a help text (the small question
  mark next to the label, or a tooltip on a button) from the text files, ``ui.tip.<id>``. The id
  is derived from the key (see :func:`help_id`). A control without a help text is recorded in
  ``missing`` so a test can fail on it.

Everything else is passed through to Streamlit unchanged. The cover is also placed around the
columns that ``columns()`` returns, so controls inside columns get the same treatment.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

#: widget functions that accept ``help=``
HELPED = (
    "button", "checkbox", "text_input", "text_area", "number_input", "selectbox", "radio",
    "multiselect", "file_uploader", "download_button", "form_submit_button", "toggle", "slider",
)  # fmt: skip
ICONS = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "⛔"}
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_VERSION = re.compile(r"::\d+$")


def help_id(key: str) -> str:
    """The id of the help text for a widget key.

    ``set::dedup.fuzzy.enabled::3`` (a settings field) becomes ``setting.dedup_fuzzy_enabled``;
    ``recent-2`` becomes ``recent``; ``label-file.ris`` becomes ``label``; other keys are used as
    they are.
    """
    if key.startswith("set::"):
        field = _VERSION.sub("", key[len("set::") :])
        return "setting." + field.replace(".", "_")
    for prefix in ("recent-", "label-"):
        if key.startswith(prefix):
            return prefix[:-1]
    return key


def notice_html(kind: str, body: object) -> str:
    """The HTML of one notice box (text is escaped; ``**bold**`` and line breaks are kept)."""
    text = html.escape(str(body))
    text = _BOLD.sub(r"<b>\1</b>", text).replace("\n", "<br>")
    return (
        f'<div class="crapai-notice crapai-{kind}" role="alert">'
        f'<span class="crapai-icon">{ICONS[kind]}</span><div>{text}</div></div>'
    )


class Themed:
    """Streamlit (or a column of it) with own notices and automatic help texts.

    Args:
        target: ``streamlit`` itself or a container such as a column.
        help_for: Returns the help text for a help id, or None if there is none.
        missing: A set that collects the ids of controls without a help text (for tests).
    """

    def __init__(
        self,
        target: Any,
        help_for: Callable[[str], str | None],
        missing: set[str] | None = None,
    ) -> None:
        self._target = target
        self._help_for = help_for
        self.missing: set[str] = missing if missing is not None else set()

    def __enter__(self) -> Any:
        """``with column:`` enters the wrapped container."""
        return self._target.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._target.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if name in HELPED and callable(attribute):
            return self._with_help(attribute)
        if name == "columns":
            return self._columns(attribute)
        return attribute

    def _with_help(self, function: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            key = kwargs.get("key")
            if key is not None and "help" not in kwargs:
                ident = help_id(str(key))
                text = self._help_for(ident)
                if text:
                    kwargs["help"] = text
                else:
                    self.missing.add(ident)
            return function(*args, **kwargs)

        return call

    def _columns(self, function: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            return [Themed(c, self._help_for, self.missing) for c in function(*args, **kwargs)]

        return call

    def _notice(self, kind: str, body: object) -> None:
        self._target.markdown(notice_html(kind, body), unsafe_allow_html=True)

    def info(self, body: object, **_: Any) -> None:
        """A blue notice."""
        self._notice("info", body)

    def success(self, body: object, **_: Any) -> None:
        """A green notice."""
        self._notice("success", body)

    def warning(self, body: object, **_: Any) -> None:
        """An amber notice."""
        self._notice("warning", body)

    def error(self, body: object, **_: Any) -> None:
        """A red notice."""
        self._notice("error", body)
