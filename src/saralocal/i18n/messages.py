"""User-facing messages: texts by key and formatted error reports (ADR 0012, plan chapter 26.4).

Texts live in ``texts/*.yaml`` (never in code). Errors carry a code; the texts for ``errors.<code>``
say what happened and what to do, in the language of the project. The exception's own message is
shown as *details* because it names the concrete file or setting.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from saralocal.errors import UNEXPECTED_ERROR_CODE, SaraError
from saralocal.i18n.loader import I18n

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ("en", "de")
DEFAULT_LANGUAGE = "en"


def resolve_language(explicit: str | None = None, project_yaml: Path | None = None) -> str:
    """Choose the message language: explicit option, then ``project.language``, then ``LANG``.

    The project file is only peeked at (no validation), so a half-finished ``project.yaml`` does
    not stop the program from talking to the user.
    """
    if explicit:
        return explicit if explicit in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    if project_yaml is not None:
        try:
            data: Any = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
            language = data["project"]["language"]
            if language in SUPPORTED_LANGUAGES:
                return str(language)
        except (OSError, yaml.YAMLError, KeyError, TypeError):
            logger.debug("No usable project language in %s", project_yaml)
    environment = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    return "de" if environment.startswith("de") else DEFAULT_LANGUAGE


class Messages:
    """Message lookup for one language, falling back to English and then to the key itself."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        self._i18n = I18n()
        self._i18n.load(self.language)

    def text(self, key: str, **values: object) -> str:
        """The text for ``key`` with ``{placeholders}`` filled in; the key if it is unknown."""
        template = self._i18n.t(key)
        if not template:
            logger.warning("Missing text for %s", key)
            return key
        try:
            return template.format(**values)
        except (KeyError, IndexError):
            logger.warning("Text %s has placeholders that were not supplied", key)
            return template

    def error_lines(self, error: SaraError) -> list[str]:
        """Lines that report ``error``: code and title, technical details, what to do."""
        code = error.code
        title_key = f"errors.{code}.title"
        if not self._i18n.t(title_key):
            code_for_text = UNEXPECTED_ERROR_CODE
        else:
            code_for_text = code
        lines = [f"{self.text('cli.error.prefix', code=code)}: {self.text(f'errors.{code_for_text}.title')}"]
        if error.user_message:
            lines.append(f"{self.text('cli.error.details')}: {error.user_message}")
        action = self._i18n.t(f"errors.{code_for_text}.action") or error.hint
        if action:
            lines.append(f"{self.text('cli.error.action')}: {action}")
        return lines
