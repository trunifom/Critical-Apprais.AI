"""Detect common article sections in a full text (plan chapter 29.8, ADR 0026).

A pure, best-effort heuristic: real articles format headings in many ways (numbered, bold,
all-caps, a different language), so this only recognises a heading that sits alone on its own
line and matches one of the common English names. A full text with no recognisable heading (for
example OCR output that lost the line breaks) returns an empty mapping; callers fall back to
``truncate`` in that case rather than send an empty prompt.
"""

from __future__ import annotations

import re

_HEADING_LINE = re.compile(
    r"^\s*(abstract|introduction|background|methods|materials and methods|methodology|"
    r"results|findings|discussion|conclusions?|references|bibliography|literatur)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Heading text (lower case) -> the section name callers use.
_CANONICAL = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "methods": "methods",
    "materials and methods": "methods",
    "methodology": "methods",
    "results": "results",
    "findings": "results",
    "discussion": "discussion",
    "conclusion": "discussion",
    "conclusions": "discussion",
    "references": "references",
    "bibliography": "references",
    "literatur": "references",
}

#: the sections most likely to carry the inclusion/exclusion criteria's evidence (plan 29.8);
#: Abstract/Introduction restate what the title/abstract stage already saw, References has none.
SECTIONS_FOR_SCREENING = ("methods", "results", "discussion")


def split_sections(text: str) -> dict[str, str]:
    """Split ``text`` by recognised heading lines, in document order.

    Returns an empty dict if no heading was found at all. Two headings that map to the same
    section (for example "Methods" and, later, "Materials and Methods") are concatenated in the
    order they appear.
    """
    matches = list(_HEADING_LINE.finditer(text))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = _CANONICAL[match.group(1).lower()]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if not body:
            continue
        sections[name] = f"{sections[name]}\n\n{body}" if name in sections else body
    return sections


def methods_results_discussion(text: str) -> str:
    """The sections most relevant to screening criteria, or ``""`` if none were recognised."""
    sections = split_sections(text)
    parts = [sections[name] for name in SECTIONS_FOR_SCREENING if name in sections]
    return "\n\n".join(parts)
