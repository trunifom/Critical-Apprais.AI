"""NBIB / MEDLINE reader (plan chapter 25.3).

PubMed's "MEDLINE" export pads tags to four characters (``PMID- 32559806``, ``TI  - Title``).
Long values wrap onto continuation lines that begin with six spaces; records are separated by a
blank line. Repeated tags (``FAU``, ``AU``, ``PT``, ``MH``, ``OT``, ``AID``, ``LID``) become lists.

The DOI is taken from the ``LID``/``AID`` entry that carries the ``[doi]`` marker. Retracted
publications are flagged with ``is_retracted``; nothing is lost: tags without an internal column
go to ``RawRecord.extra`` as ``nbib_<TAG>``.
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

# Tag: 2-4 characters padded with spaces to width four, then "- ". PMID is the record start.
TAG_LINE = re.compile(r"^([A-Z][A-Za-z0-9]{1,3}) {0,2}-(?: (.*))?$")
YEAR = re.compile(r"\b(1[4-9]\d{2}|20\d{2})\b")
DOI_MARKER = re.compile(r"\s*\[doi\]\s*$", re.IGNORECASE)
RETRACTION_TYPES = frozenset({"Retracted Publication", "Retraction of Publication"})
RETRACTED_TITLE = re.compile(r"^\s*retracted\s*:", re.IGNORECASE)

# Tags mapped to internal columns; every other tag ends up in ``extra``.
# Single-valued (first occurrence wins, later ones are kept in ``extra``):
SINGLE_TAGS: dict[str, str] = {
    "PMID": "pmid",
    "VI": "volume",
    "IP": "issue",
    "PG": "pages",
    "PMC": "pmcid",
}


def parse_nbib_text(text: str, *, encoding: str | None = None) -> ReadResult:
    """Parse MEDLINE text (line endings already normalised to ``\\n``).

    Raises:
        ImportFailed: (E102) if no record (``PMID-`` line) is found.
    """
    blocks: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in text.split("\n"):
        if not line.strip():
            current = None  # a blank line ends the record
            continue
        match = TAG_LINE.match(line)
        if match is not None:
            tag, value = match.group(1), (match.group(2) or "").strip()
            if tag == "PMID" or current is None:
                current = []
                blocks.append(current)
            current.append([tag, value])
        elif current:
            current[-1][1] = f"{current[-1][1]} {line.strip()}".strip()  # wrapped value
        # else: stray text outside a record is ignored
    records = [
        _to_record(index, block)
        for index, block in enumerate((b for b in blocks if _is_record(b)), start=1)
    ]
    if not records:
        raise ImportFailed(
            "No MEDLINE records (PMID lines) were found in the file",
            code="E102",
            hint="In PubMed choose 'Send to' > 'Citation manager' or Format 'MEDLINE'.",
        )
    return ReadResult(SourceFormat.NBIB, records, encoding=encoding)


def read_nbib(path: Path, *, encoding: str | None = None) -> ReadResult:
    """Read a NBIB/MEDLINE file (also one that was saved with the extension ``.ris``).

    Raises:
        ImportFailed: E101/E103 for unreadable or undecodable files, E102 for no records.
    """
    text, used = read_text_file(path, encoding)
    result = parse_nbib_text(text, encoding=used)
    logger.info("Read %d NBIB record(s) from %s", len(result.records), path.name)
    return result


def _is_record(block: list[list[str]]) -> bool:
    """A real record starts with PMID; blocks without it are stray text."""
    return bool(block) and block[0][0] == "PMID"


def _to_record(index: int, block: list[list[str]]) -> RawRecord:
    by_tag: dict[str, list[str]] = {}
    for tag, value in block:
        if value:
            by_tag.setdefault(tag, []).append(value)
    used: set[str] = set()
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    notes: list[str] = []

    def take(*tags: str) -> list[str]:
        collected: list[str] = []
        for tag in tags:
            used.add(tag)
            collected.extend(by_tag.get(tag, []))
        return collected

    publication_types = unique_in_order(take("PT"))
    fields["record_type"] = (
        "journal_article" if "Journal Article" in publication_types else "other"
    )
    if publication_types:
        fields["publication_types"] = join_values(publication_types)

    titles, translated = take("TI"), take("TT")
    if titles:
        fields["title"] = titles[0]
        if translated:
            fields["title_translated"] = translated[0]
    elif translated:
        fields["title"] = translated[0]  # original is not English: fall back to the translation
        notes.append("title taken from TT (translated title)")
    abstracts = take("AB")
    if abstracts:
        fields["abstract"] = "\n\n".join(unique_in_order(abstracts))
        fields["abstract_source"] = "AB"

    authors = unique_in_order(take("FAU")) or unique_in_order(take("AU"))
    if authors:
        fields["authors"] = join_values(authors)
    journal = take("JT") or take("TA")
    if journal:
        fields["journal"] = journal[0]
    # DP is only read here, not consumed: the full date stays in extra ("2020 Oct 15").
    year = _year(by_tag.get("DP", []))
    if year is not None:
        fields["year"] = year

    for tag, column in SINGLE_TAGS.items():
        values = take(tag)
        if values:
            fields[column] = values[0]
            if len(values) > 1:
                extra[f"nbib_{tag}"] = values[1:] if len(values) > 2 else values[1]

    doi, other_ids = _split_locators(take("LID", "AID"))
    if doi:
        fields["doi"] = doi
    if other_ids:
        extra["nbib_AID"] = other_ids[0] if len(other_ids) == 1 else other_ids

    languages = unique_in_order(take("LA"))
    if languages:
        fields["language"] = join_values(languages)
    mesh = unique_in_order(take("MH"))
    if mesh:
        fields["keywords_mesh"] = join_values(mesh)
    keywords = unique_in_order(take("OT"))
    if keywords:
        fields["keywords"] = join_values(keywords)

    retracted = bool(RETRACTION_TYPES.intersection(publication_types)) or bool(
        RETRACTED_TITLE.match(fields.get("title", ""))
    )
    fields["is_retracted"] = retracted
    if retracted:
        flagged = [t for t in publication_types if t in RETRACTION_TYPES]
        notes.append("retraction: " + (join_values(flagged) or "title starts with 'Retracted:'"))

    for tag, values in by_tag.items():
        if tag not in used:
            extra[f"nbib_{tag}"] = values[0] if len(values) == 1 else values
    return RawRecord(index, fields, extra, notes)


def _split_locators(values: list[str]) -> tuple[str, list[str]]:
    """Pick the DOI (entry marked ``[doi]``) from LID/AID values; return the other identifiers."""
    doi = ""
    others: list[str] = []
    for value in values:
        if DOI_MARKER.search(value):
            candidate = DOI_MARKER.sub("", value).strip()
            if not doi:
                doi = candidate
            elif candidate != doi:
                others.append(value)
        else:
            others.append(value)
    return doi, unique_in_order(others)


def _year(values: list[str]) -> int | None:
    """Year from ``DP`` (``2020 Oct``, ``2020 Oct-Dec``); the rest of the date stays in the file."""
    for value in values:
        match = YEAR.search(value)
        if match:
            return int(match.group(1))
    return None
