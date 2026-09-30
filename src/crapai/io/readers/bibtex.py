"""BibTeX reader (plan chapter 25.4).

The parser is a small tolerant scanner instead of a strict grammar, because real exports are not
valid BibTeX: Cochrane writes ``Record #1 of 48`` lines between the entries and field names with
spaces (``publication type = {...}``). It works in three steps:

1. Entries are located by ``@type{`` at the start of a line; everything outside entries is
   skipped and counted (pre-clean).
2. Each entry is read up to its matching closing brace, ends at the next entry start at the latest,
   so one damaged entry cannot swallow the rest of the file.
3. Values are ``{...}`` (nested), ``"..."`` or bare tokens, joined by ``#``; month macros are
   resolved, ``@string`` definitions serve as macros, ``@preamble``/``@comment`` are ignored.

Scanning uses ``str.find`` and a bracket regex instead of nested quantifiers, so long lines
(10 000+ characters) and the 11.5 MB Cochrane file cannot trigger catastrophic backtracking.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from crapai.errors import ImportFailed
from crapai.io.readers.base import (
    RawRecord,
    ReadResult,
    join_values,
    read_text_file,
    unique_in_order,
)
from crapai.io.readers.detect import SourceFormat

logger = logging.getLogger(__name__)

ENTRY_START = re.compile(r"^[ \t]*@([A-Za-z]+)[ \t]*([{(])", re.MULTILINE)
BRACKETS = re.compile(r"[{}]")
QUOTE_OR_BRACKET = re.compile(r'["{}]')
BARE_END = re.compile(r"[,}#)\s]")
YEAR = re.compile(r"\b(1[4-9]\d{2}|20\d{2}|2100)\b")
DASHES = re.compile(r"\s*(?:--+|–|—)\s*")
KEYWORD_SPLIT = re.compile(r"\s*[;,]\s*")
TRIAL_ID = re.compile(r"^\s*NCT\d+\s*,?\s*$", re.IGNORECASE)
URL = re.compile(r"^https?://", re.IGNORECASE)
LATEX_ESCAPE = re.compile(r"\\([&%$#_{}])")

SKIPPED_TYPES = frozenset({"string", "preamble", "comment"})
MONTHS = {
    name: str(number)
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}

RECORD_TYPES: dict[str, str] = {
    "article": "journal_article",
    "book": "book",
    "incollection": "book_chapter",
    "inbook": "book_chapter",
    "inproceedings": "conference_paper",
    "conference": "conference_paper",
    "proceedings": "conference_paper",
    "techreport": "report",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "unpublished": "preprint",
    "online": "web",
    "electronic": "web",
    "www": "web",
    "misc": "other",
}
DEFAULT_RECORD_TYPE = "other"

# Field name (lower-case, spaces -> underscore) -> internal column, single valued.
DIRECT_FIELDS: dict[str, str] = {
    "volume": "volume",
    "number": "issue",
    "doi": "doi",
    "pmid": "pmid",
    "pmcid": "pmcid",
    "accession_number": "accession_number",
    "publisher": "publisher",
    "address": "place",
    "edition": "edition",
    "shorttitle": "short_title",
    "note": "notes",
    "language": "language",
    "langid": "language",
    "publication_type": "publication_types",
}
# Fields dropped on purpose: local file paths of the exporting user (privacy, like RIS L1).
DROPPED_FIELDS = frozenset({"file"})


def parse_bibtex_text(text: str, *, encoding: str | None = None) -> ReadResult:
    """Parse BibTeX text (line endings already normalised to ``\\n``).

    Raises:
        ImportFailed: (E102) if no entry is found.
    """
    starts = list(ENTRY_START.finditer(text))
    file_notes: list[str] = []
    records: list[RawRecord] = []
    macros: dict[str, str] = {}
    cursor = 0  # end of the previous entry, to count skipped text outside entries
    outside_lines = 0
    for position, match in enumerate(starts):
        limit = starts[position + 1].start() if position + 1 < len(starts) else len(text)
        outside_lines += _count_lines(text, cursor, match.start())
        entry_type = match.group(1).lower()
        open_pos = match.end() - 1
        close_pos, balanced = _matching_close(text, open_pos, limit)
        cursor = close_pos + 1 if balanced else limit
        body = text[open_pos + 1 : close_pos]
        if entry_type == "string":  # @string{name = "value"}: usable as macro in later values
            for name, value in _parse_fields(body, 0, macros):
                macros[name] = value
            continue
        if entry_type in SKIPPED_TYPES:
            continue
        record = _read_entry(len(records) + 1, entry_type, body, macros)
        if not balanced:
            record.notes.append("entry has unbalanced braces; read up to the next entry")
        records.append(record)
    outside_lines += _count_lines(text, cursor, len(text))

    if outside_lines:
        file_notes.append(f"{outside_lines} non-empty line(s) outside entries were skipped")
    if not records:
        raise ImportFailed(
            "No BibTeX entries were found in the file",
            code="E102",
            hint="Export the search results again as BibTeX.",
        )
    return ReadResult(SourceFormat.BIBTEX, records, encoding=encoding, notes=file_notes)


def read_bibtex(path: Path, *, encoding: str | None = None) -> ReadResult:
    """Read a BibTeX file. No file is written anywhere (the predecessor's ``bibReader`` did).

    Raises:
        ImportFailed: E101/E103 for unreadable or undecodable files, E102 for no entries.
    """
    text, used = read_text_file(path, encoding)
    result = parse_bibtex_text(text, encoding=used)
    logger.info("Read %d BibTeX entrie(s) from %s", len(result.records), path.name)
    return result


# --- scanning helpers ---------------------------------------------------------------------


def _count_lines(text: str, start: int, end: int) -> int:
    """Number of non-empty lines in ``text[start:end]``."""
    if end <= start:
        return 0
    return sum(1 for line in text[start:end].split("\n") if line.strip())


def _matching_close(text: str, open_pos: int, limit: int) -> tuple[int, bool]:
    """Position of the bracket closing the one at ``open_pos``, searched before ``limit``.

    Returns ``(position, True)``, or ``(limit, False)`` when the braces are unbalanced.
    """
    if text[open_pos] == "(":
        # "@article(key, ...)": braces inside are values, so close at the last ")" of the entry.
        closing = text.rfind(")", open_pos, limit)
        return (closing, True) if closing != -1 else (limit, False)
    depth = 0
    for match in BRACKETS.finditer(text, open_pos, limit):
        depth += 1 if match.group() == "{" else -1
        if depth == 0:
            return match.start(), True
    return limit, False


def _read_entry(index: int, entry_type: str, body: str, macros: dict[str, str]) -> RawRecord:
    """Read cite key and fields from the text between the entry's outer brackets."""
    key, fields = _parse_body(body, macros)
    return _map_fields(index, entry_type, key, fields)


def _parse_body(body: str, macros: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    comma = body.find(",")
    equals = body.find("=")
    if comma == -1 or (equals != -1 and equals < comma):
        return "", _parse_fields(body, 0, macros)  # no cite key
    return body[:comma].strip(), _parse_fields(body, comma + 1, macros)


def _parse_fields(body: str, pos: int, macros: dict[str, str]) -> list[tuple[str, str]]:
    """Parse ``name = value, name = value`` pairs; tolerant of spaces in names and stray commas."""
    fields: list[tuple[str, str]] = []
    length = len(body)
    while pos < length:
        equals = body.find("=", pos)
        if equals == -1:
            break
        name = " ".join(body[pos:equals].replace(",", " ").split()).lower().replace(" ", "_")
        value, pos = _parse_value(body, equals + 1, macros)
        if name:
            fields.append((name, value))
    return fields


def _parse_value(body: str, pos: int, macros: dict[str, str]) -> tuple[str, int]:
    """Parse one value (parts joined by ``#``); returns ``(text, position after the value)``."""
    parts: list[str] = []
    length = len(body)
    while True:
        while pos < length and body[pos].isspace():
            pos += 1
        if pos >= length:
            break
        char = body[pos]
        if char == "{":
            close, _ = _matching_close(body, pos, length)
            parts.append(body[pos + 1 : close])
            pos = close + 1
        elif char == '"':
            text, pos = _quoted(body, pos)
            parts.append(text)
        else:
            end = BARE_END.search(body, pos)
            stop = end.start() if end else length
            token = body[pos:stop]
            lowered = token.lower()
            parts.append(macros.get(lowered) or MONTHS.get(lowered, token))
            pos = stop
        while pos < length and body[pos].isspace():
            pos += 1
        if pos < length and body[pos] == "#":
            pos += 1
            continue
        break
    while pos < length and body[pos] in ", \t\r\n":
        pos += 1
    return "".join(parts), pos


def _quoted(body: str, pos: int) -> tuple[str, int]:
    """Read ``"..."`` starting at the opening quote; quotes inside braces do not end it."""
    depth = 0
    for match in QUOTE_OR_BRACKET.finditer(body, pos + 1):
        char = match.group()
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth <= 0:
            return body[pos + 1 : match.start()], match.end()
    return body[pos + 1 :], len(body)


# --- mapping to internal columns ----------------------------------------------------------


def clean_latex(text: str) -> str:
    """Resolve LaTeX escapes and drop protective braces for titles, names and journals.

    Uses ``pylatexenc`` when installed (extra ``import``); a bare ``%`` is escaped first because
    LaTeX would treat the rest of the line as a comment. Without the library only the common
    escapes ``\\& \\% \\$ \\# \\_`` are resolved and braces are removed.
    """
    if not any(char in text for char in "\\{}$~"):
        return text
    if not any(char in text for char in "\\$~"):
        return _strip_braces(text)  # only protective braces: no need for the slow LaTeX parser
    try:
        from pylatexenc.latex2text import LatexNodes2Text
    except ImportError:  # pragma: no cover - the extra is normally installed
        return _strip_braces(LATEX_ESCAPE.sub(r"\1", text))
    protected = re.sub(r"(?<!\\)%", r"\\%", text)
    converted = LatexNodes2Text().latex_to_text(protected)
    return converted.replace(" ", " ")


def _strip_braces(text: str) -> str:
    return text.replace("{", "").replace("}", "")


def clean_abstract(text: str) -> str:
    """Change an abstract minimally: unescape ``\\% \\& ...`` and squeeze white space only."""
    return " ".join(LATEX_ESCAPE.sub(r"\1", text).split())


def _split_authors(value: str) -> list[str]:
    """Split ``A and B`` at brace depth 0 so ``{World Health Organization}`` stays whole."""
    names: list[str] = []
    depth = 0
    current: list[str] = []
    tokens = re.split(r"(\s+)", value)
    for token in tokens:
        if token.strip().lower() == "and" and depth == 0:
            names.append("".join(current).strip())
            current = []
            continue
        depth += token.count("{") - token.count("}")
        current.append(token)
    names.append("".join(current).strip())
    return [clean_latex(name).strip() for name in names if name.strip()]


def _year(*values: str) -> int | None:
    for value in values:
        match = YEAR.search(value)
        if match:
            return int(match.group(1))
    return None


def _map_fields(
    index: int, entry_type: str, key: str, fields: list[tuple[str, str]]
) -> RawRecord:
    by_name: dict[str, list[str]] = {}
    for name, value in fields:
        by_name.setdefault(name, []).append(value.strip())
    used: set[str] = set()
    mapped: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    notes: list[str] = []

    def first(*names: str) -> str:
        for name in names:
            used.add(name)
        for name in names:
            for value in by_name.get(name, []):
                if value:
                    return value
        return ""

    mapped["record_type"] = RECORD_TYPES.get(entry_type, DEFAULT_RECORD_TYPE)
    extra["bib_type"] = entry_type
    if key:
        extra["bib_key"] = key

    title = clean_latex(first("title")).strip()
    if title:
        mapped["title"] = title
    abstract = clean_abstract(first("abstract"))
    if abstract:
        mapped["abstract"] = abstract
        mapped["abstract_source"] = "AB"
    authors = _split_authors(first("author")) if by_name.get("author") else []
    if authors:
        mapped["authors"] = join_values(unique_in_order(authors))
    editors = _split_authors(first("editor")) if by_name.get("editor") else []
    if editors:
        mapped["editors"] = join_values(unique_in_order(editors))
    year = _year(first("year"), first("date"))
    if year is not None:
        mapped["year"] = year
    journal = clean_latex(first("journal", "journaltitle", "booktitle")).strip()
    if journal:
        mapped["journal"] = journal
    for name, column in DIRECT_FIELDS.items():
        value = clean_latex(first(name)).strip() if name != "doi" else first(name)
        if value and column not in mapped:
            mapped[column] = value
    pages = first("pages")
    if pages:
        mapped["pages"] = DASHES.sub("-", clean_latex(pages)).strip()
    url = first("url")
    if url:
        mapped["url"] = url
    issn_isbn = first("issn", "isbn")
    if issn_isbn:
        mapped["issn_isbn"] = issn_isbn
    keywords = [k for k in KEYWORD_SPLIT.split(clean_latex(first("keywords"))) if k]
    if keywords:
        mapped["keywords"] = join_values(unique_in_order(keywords))

    used.update(DROPPED_FIELDS)
    if any(by_name.get(name) for name in DROPPED_FIELDS):
        notes.append("file field (local path) was not imported")
    for name, values in by_name.items():
        if name not in used:
            extra[f"bib_{name}"] = values[0] if len(values) == 1 else values

    _mark_trial_registry(mapped, notes)
    return RawRecord(index, mapped, extra, notes)


def _mark_trial_registry(fields: dict[str, Any], notes: list[str]) -> None:
    """Cochrane trial-register entries: author is only ``NCT...`` and the journal is a URL."""
    authors = fields.get("authors", "")
    journal = fields.get("journal", "")
    if TRIAL_ID.match(authors) and URL.match(journal):
        fields["record_type"] = "trial_registry"
        del fields["authors"]  # the registry number is not a person
        notes.append("trial registry entry: author field held only the registry number")
