"""Normalisation helpers for imported bibliographic values (plan chapter 8.3).

Small pure functions, each with one job, so they are easy to test and to reuse in the dedup step.
Nothing here invents data: an unusable value becomes an empty string or ``None``, never a
placeholder (the predecessor used the year 1900).
"""

from __future__ import annotations

import html
import re
import unicodedata

# Control characters that Excel/XML cannot hold: 0x00-0x08, 0x0b, 0x0c, 0x0e-0x1f (plan 25.9).
# Tab (0x09), LF (0x0a) and CR (0x0d) are white space and handled separately.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{1,31});")
_DOI_PREFIX = re.compile(
    r"^(?:https?://)?(?:dx\.)?doi\.org/|^doi\s*:\s*|^https?://dx\.doi\.org/", re.IGNORECASE
)
_DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")
_YEAR = re.compile(r"\b(1[4-9]\d{2}|20\d{2}|2100)\b")
_TRAILING_DOI_PUNCTUATION = ".,;)]}>\"'"


def clean_text(value: str, *, single_line: bool = True) -> str:
    """Return ``value`` in Unicode NFC with control characters removed and white space tidied.

    Args:
        value: Raw text from a source file.
        single_line: If True (default) every run of white space, including line breaks, becomes
            one space; this is the rule for abstracts and titles (plan chapter 25.7). If False
            only the ends are stripped and line breaks are kept.
    """
    if not value:
        return ""
    text = html.unescape(value) if _ENTITY.search(value) else value
    # Order matters: entities such as &#1; can produce control characters, and removing controls
    # can leave a base letter next to a combining mark, so NFC comes last.
    text = unicodedata.normalize("NFC", _CONTROL.sub("", text))
    if single_line:
        return _WHITESPACE.sub(" ", text).strip()
    return text.strip()


def normalize_doi(value: str) -> str | None:
    """Normalise a DOI: lower case, no ``https://doi.org/`` or ``doi:`` prefix, no spaces.

    Returns:
        The DOI (``10.xxxx/...``), or ``None`` if the value does not have the shape of a DOI
        (the caller keeps the original in ``extra_json``).
    """
    text = clean_text(value)
    if not text:
        return None
    text = _DOI_PREFIX.sub("", text).replace(" ", "").lower()
    text = text.rstrip(_TRAILING_DOI_PUNCTUATION)
    return text if _DOI_SHAPE.match(text) else None


def coerce_year(value: object) -> int | None:
    """Return the first plausible year (1400 to 2100) found in ``value``, else ``None``."""
    if value is None or isinstance(value, bool):
        return None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def normalize_list(value: str, *, separator: str = ";") -> str:
    """Tidy a ``"A; B; C"`` list: trim entries, drop empty ones and exact duplicates."""
    if not value:
        return ""
    seen: dict[str, None] = {}
    for part in value.split(separator):
        entry = clean_text(part)
        if entry:
            seen.setdefault(entry, None)
    return "; ".join(seen)
