"""RIS reader (plan chapter 25.2).

RIS is line oriented: ``TAG␣␣-␣value``. This reader differs from the predecessor in the points of
lesson L15: tags are recognised by *pattern*, not by a fixed list, and lines without a tag are
**continuation lines** that are appended to the previous field. The old parser dropped them and
silently truncated multi-line abstracts (129 such lines in ``pubmed_adhd_converted-zotero.ris``).

Nothing is lost: tags without an internal column go to ``RawRecord.extra`` as ``ris_<TAG>``.
Header lines before a record (Cochrane: ``Record #1 of 6``, ``Provider: ...``) are skipped and
noted on the record that follows.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
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

Take = Callable[..., list[str]]  # take(*tags) -> values, marks the tags as consumed

# A tag is two characters (capital letter + capital letter or digit), one or two spaces, a dash.
# The value may be empty ("ER  - ").
TAG_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$")
YEAR = re.compile(r"\b(1[4-9]\d{2}|20\d{2}|2100)\b")
URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

MAX_HEADER_NOTE_CHARS = 200

# RIS TY -> record_type (plan chapter 25.2). CTLG and DATA follow the order of the plan table
# ("dataset / trial_registry"); the plan does not say more, so this pairing is an assumption.
RECORD_TYPES: dict[str, str] = {
    "JOUR": "journal_article",
    "EJOUR": "journal_article",
    "MGZN": "journal_article",
    "NEWS": "journal_article",
    "CONF": "conference_paper",
    "CPAPER": "conference_paper",
    "CHAP": "book_chapter",
    "ECHAP": "book_chapter",
    "BOOK": "book",
    "EBOOK": "book",
    "RPRT": "report",
    "GEN": "other",
    "UNPB": "preprint",
    "THES": "thesis",
    "DISS": "thesis",
    "ELEC": "web",
    "WEB": "web",
    "BLOG": "web",
    "CTLG": "dataset",
    "DATA": "trial_registry",
}
DEFAULT_RECORD_TYPE = "other"

# Tags that are read into a single-valued internal column: column -> tags by priority.
SINGLE_VALUE_TAGS: dict[str, tuple[str, ...]] = {
    "journal": ("JF", "JO", "T2", "JA", "J2"),
    "issn_isbn": ("SN",),
    "volume": ("VL", "VO"),
    "issue": ("IS",),
    "doi": ("DO",),
    "accession_number": ("AN",),
    "database_name": ("DB",),
    "database_provider": ("DP",),
    "language": ("LA",),
    "publisher": ("PB",),
    "place": ("CY",),
    "edition": ("ET",),
    "short_title": ("ST",),
}


def parse_ris_text(text: str, *, encoding: str | None = None) -> ReadResult:
    """Parse RIS text (line endings already normalised to ``\\n``).

    Raises:
        ImportFailed: (E102) if no record is found.
    """
    raw_records: list[tuple[list[tuple[str, str]], list[str]]] = []
    file_notes: list[str] = []
    current: list[list[str]] | None = None  # [tag, value] pairs, mutable for continuations
    current_notes: list[str] = []
    pending_header: list[str] = []
    discarded = 0
    type_lines = 0

    def finish(*, terminated: bool) -> None:
        nonlocal current, current_notes
        if current is None:
            return
        if not terminated:
            current_notes.append("record not terminated by ER")
        raw_records.append(([(tag, value) for tag, value in current], current_notes))
        current, current_notes = None, []

    for line in text.split("\n"):
        stripped = line.strip()
        match = TAG_LINE.match(line)
        if match is None:
            if not stripped:
                continue
            if current is not None and current:
                current[-1][1] = f"{current[-1][1]} {stripped}".strip()  # continuation (L15)
            else:
                pending_header.append(stripped)
                discarded += 1
            continue
        tag, value = match.group(1), match.group(2).strip()
        if tag == "TY":
            type_lines += 1
            finish(terminated=False)
            current = [["TY", value]]
            current_notes = _header_note(pending_header)
            pending_header = []
        elif tag == "ER":
            finish(terminated=True)
        else:
            if current is None:  # tags without a preceding TY: keep them as an implicit record
                current = []
                current_notes = _header_note(pending_header) + ["record without TY line"]
                pending_header = []
            current.append([tag, value])
    if current is not None:
        finish(terminated=False)

    if discarded:
        file_notes.append(f"{discarded} line(s) outside records were skipped")
    if not raw_records or type_lines == 0:
        # Without any TY line this is not RIS (a MEDLINE/NBIB file also has "TI  -" lines and
        # would otherwise be misread as one giant record).
        raise ImportFailed(
            "No RIS records (TY lines) were found in the file",
            code="E102",
            hint="Export the search results again as RIS, or check the file format.",
        )
    records = [
        _to_record(index, pairs, notes) for index, (pairs, notes) in enumerate(raw_records, start=1)
    ]
    return ReadResult(SourceFormat.RIS, records, encoding=encoding, notes=file_notes)


def read_ris(path: Path, *, encoding: str | None = None) -> ReadResult:
    """Read a RIS file.

    Args:
        path: File to read.
        encoding: Force a text encoding; by default the chain of plan chapter 25.9 is used.

    Raises:
        ImportFailed: E101/E103 for unreadable or undecodable files, E102 for no records.
    """
    text, used = read_text_file(path, encoding)
    result = parse_ris_text(text, encoding=used)
    logger.info("Read %d RIS record(s) from %s", len(result.records), path.name)
    return result


def _header_note(lines: list[str]) -> list[str]:
    """Turn skipped header lines before a record into one note (shortened)."""
    if not lines:
        return []
    joined = " | ".join(lines)
    if len(joined) > MAX_HEADER_NOTE_CHARS:
        joined = joined[: MAX_HEADER_NOTE_CHARS - 3] + "..."
    return [f"header lines skipped: {joined}"]


def _to_record(index: int, pairs: list[tuple[str, str]], notes: list[str]) -> RawRecord:
    """Map the tag/value pairs of one RIS record to internal columns and ``extra``."""
    by_tag: dict[str, list[str]] = {}
    for tag, value in pairs:
        if value:
            by_tag.setdefault(tag, []).append(value)
    used: set[str] = set()
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}

    def take(*tags: str) -> list[str]:
        """All values of the given tags in tag order; marks them as consumed."""
        collected: list[str] = []
        for tag in tags:
            used.add(tag)
            collected.extend(by_tag.get(tag, []))
        return collected

    ris_type = (by_tag.get("TY") or [""])[0].upper()
    used.add("TY")
    fields["record_type"] = RECORD_TYPES.get(ris_type, DEFAULT_RECORD_TYPE)
    if ris_type:
        extra["ris_TY"] = ris_type

    _map_title(fields, extra, take)
    _map_abstract(fields, extra, take, by_tag)
    authors = unique_in_order(take("AU", "A1"))
    if authors:
        fields["authors"] = join_values(authors)
    editors = unique_in_order(take("A2"))
    if editors:
        fields["editors"] = join_values(editors)
    year = _year(take("PY", "Y1"), take("DA"))
    if year is not None:
        fields["year"] = year
    for column, tags in SINGLE_VALUE_TAGS.items():
        values = take(*tags)
        if values:
            fields[column] = values[0]
            _keep_leftovers(extra, tags, by_tag, chosen=values[0])
    _map_url(fields, extra, take)
    pages = _pages(take("SP"), take("EP"))
    if pages:
        fields["pages"] = pages
    keywords = unique_in_order(take("KW"))
    if keywords:
        fields["keywords"] = join_values(keywords)

    # Everything not consumed above is kept, so a re-export can reproduce the source.
    for tag, values in by_tag.items():
        if tag not in used:
            extra[f"ris_{tag}"] = values[0] if len(values) == 1 else values
    return RawRecord(index, fields, extra, notes)


def _map_title(fields: dict[str, Any], extra: dict[str, Any], take: Take) -> None:
    titles = take("TI", "T1")
    if titles:
        fields["title"] = titles[0]
        others = [t for t in unique_in_order(titles[1:]) if t != titles[0]]
        if others:
            extra["ris_T1"] = others[0] if len(others) == 1 else others


def _map_abstract(
    fields: dict[str, Any], extra: dict[str, Any], take: Take, by_tag: dict[str, list[str]]
) -> None:
    ab = take("AB")
    n2 = take("N2")
    parts = unique_in_order(ab + n2)
    if parts:
        fields["abstract"] = "\n\n".join(parts)
        fields["abstract_source"] = "AB" if ab else "N2"
    notes = take("N1")
    if notes:
        longest = max(notes, key=len)
        if not parts and len(longest) > 200:
            # Some databases store the abstract in N1 (plan chapter 25.2).
            fields["abstract"] = longest
            fields["abstract_source"] = "N1"
            notes = [n for n in notes if n is not longest]
        if notes:
            fields["notes"] = join_values(notes)


def _keep_leftovers(
    extra: dict[str, Any], tags: tuple[str, ...], by_tag: dict[str, list[str]], *, chosen: str
) -> None:
    """Keep alternative values (lower-priority tags or repeated tags) of a single-valued column."""
    leftovers: dict[str, list[str]] = {}
    for tag in tags:
        for value in by_tag.get(tag, []):
            if value != chosen:
                leftovers.setdefault(tag, []).append(value)
    for tag, values in leftovers.items():
        extra[f"ris_{tag}"] = values[0] if len(values) == 1 else values


def _year(primary: list[str], date_values: list[str]) -> int | None:
    """First plausible year from PY/Y1, else from DA (``2016///``); never a placeholder."""
    for value in [*primary, *date_values]:
        match = YEAR.search(value)
        if match:
            return int(match.group(1))
    return None


def _map_url(fields: dict[str, Any], extra: dict[str, Any], take: Take) -> None:
    urls = unique_in_order(take("UR"))
    valid = [u for u in urls if URL.match(u)]
    if valid:
        fields["url"] = valid[0]
    rest = [u for u in urls if u != fields.get("url")]
    if rest:
        extra["ris_UR"] = rest[0] if len(rest) == 1 else rest


def _pages(start: list[str], end: list[str]) -> str:
    sp = start[0] if start else ""
    ep = end[0] if end else ""
    if sp and ep and sp != ep:
        return f"{sp}-{ep}"
    return sp or ep
