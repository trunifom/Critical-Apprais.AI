"""User-facing messages: texts by key and formatted error reports (ADR 0012, plan chapter 26.4).

Texts live in ``texts/*.yaml`` (never in code). Errors carry a code; the texts for ``errors.<code>``
say what happened and what to do, in the language of the project. The exception's own message is
shown as *details* because it names the concrete file or setting.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from crapai.errors import UNEXPECTED_ERROR_CODE, SaraError
from crapai.i18n.loader import I18n

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
        except (OSError, ValueError, yaml.YAMLError, KeyError, TypeError):
            # ValueError includes UnicodeDecodeError (project.yaml saved in another encoding)
            logger.debug("No usable project language in %s", project_yaml)
    environment = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    return "de" if environment.startswith("de") else DEFAULT_LANGUAGE


@dataclass(frozen=True)
class ErrorReport:
    """An error in words the user can act on.

    Attributes:
        code: The catalogue code, for example ``E404`` (``E999`` for anything unexpected).
        title: What happened, in one sentence.
        cause: Why it usually happens (may be empty).
        details: The concrete file or setting; for unexpected errors only the exception type.
        action: What the user can do next (may be empty).
    """

    code: str
    title: str
    cause: str
    details: str
    action: str


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
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            # a missing value, or a malformed translation such as '{0' or '{a.b}'
            logger.warning("Text %s has unusable placeholders", key)
            return template

    def maybe(self, key: str) -> str | None:
        """The text for ``key`` as it is written (no placeholders), or None if there is none.

        Used for optional texts such as help; a missing one is not an error and is not logged.
        """
        return self._i18n.t(key) or None

    def error_codes(self) -> list[str]:
        """The codes that have a text (``E101`` ...), sorted; the list behind the help page."""
        node = self._i18n._get_nested("errors")  # noqa: SLF001 - same package
        if not isinstance(node, dict):
            return []
        return sorted(code for code, value in node.items() if isinstance(value, dict))

    def _action(self, code: str, hint: str | None) -> str:
        """The catalogue advice for ``code`` followed by the raising code's own hint.

        The hint names the concrete next step ("Install it with: pip install ...") and must not be
        hidden by the general advice of the catalogue; if the hint repeats it, it is left out.
        """
        general = self._i18n.t(f"errors.{code}.action")
        if not hint or hint in general:
            return general
        return f"{general} {hint}".strip()

    def error_report(self, error: BaseException) -> ErrorReport:
        """The user-facing description of any error, for the command line and the interface.

        A :class:`~crapai.errors.SaraError` gets its catalogue texts (what happened, why, what to
        do); anything else is reported as the unexpected error ``E999`` with only the exception
        type, because the message of a foreign exception may hold paths or record content.
        """
        if isinstance(error, SaraError):
            code = error.code
            known = bool(self._i18n.t(f"errors.{code}.title"))
            text_code = code if known else UNEXPECTED_ERROR_CODE
            return ErrorReport(
                code=code,
                title=self.text(f"errors.{text_code}.title"),
                cause=self._i18n.t(f"errors.{text_code}.cause"),
                details=error.user_message,
                action=self._action(text_code, error.hint),
            )
        return ErrorReport(
            code=UNEXPECTED_ERROR_CODE,
            title=self.text("cli.error.unexpected"),
            cause="",
            details=type(error).__name__,
            action="",
        )

    def error_lines(self, error: SaraError) -> list[str]:
        """Lines that report ``error``: code and title, technical details, what to do."""
        report = self.error_report(error)
        lines = [f"{self.text('cli.error.prefix', code=report.code)}: {report.title}"]
        if report.cause:
            lines.append(f"{self.text('cli.error.cause')}: {report.cause}")
        if report.details:
            lines.append(f"{self.text('cli.error.details')}: {report.details}")
        if report.action:
            lines.append(f"{self.text('cli.error.action')}: {report.action}")
        return lines
