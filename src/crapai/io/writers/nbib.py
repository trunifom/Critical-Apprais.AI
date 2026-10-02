"""NBIB/MEDLINE writer: bibliographic export (symmetric to the NBIB reader).

Follows PubMed's own layout: tags padded to width four (``PMID- 32559806``, ``TI  - Title``), one
``ER  -``-free record per block, separated by a blank line (MEDLINE itself has no explicit end
tag; a blank line is the separator the reader already expects). ``study_uid`` is written as a
``UID-`` tag (not a real MEDLINE tag, but round-trips through this program; MEDLINE readers that
don't know it will simply ignore it, like any other tag they don't recognise).

Unlike the RIS/BibTeX writers, screening marks (exclusion reason, duplicate, retracted) are not
embedded here: MEDLINE has no idiomatic free-text note field for this program to reuse, and
inventing a tag would not round-trip through real MEDLINE tools. Use the RIS or BibTeX export if
the marks need to travel with the file.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from crapai.io.records_store import Record
from crapai.project.atomic import WriteResult, atomic_write_text

logger = logging.getLogger(__name__)


def _tag(tag: str, value: str) -> str:
    return f"{tag.ljust(4)}- {' '.join(value.split())}"


def _lines(tag: str, values: Iterable[str]) -> list[str]:
    return [_tag(tag, v) for v in values if v and v.strip()]


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def record_to_nbib(record: Record) -> str:
    """One record as a MEDLINE block (lines joined by ``\\n``, no trailing blank line)."""
    out: list[str] = []
    out += _lines("PMID", [record.pmid])
    out += _lines("UID", [record.study_uid])
    out += _lines("TI", [record.title])
    out += _lines("FAU", _split(record.authors))
    out += _lines("JT", [record.journal])
    out += _lines("TA", [record.journal])
    if record.year is not None:
        out += _lines("DP", [str(record.year)])
    out += _lines("VI", [record.volume])
    out += _lines("IP", [record.issue])
    out += _lines("PG", [record.pages])
    if record.doi:
        out += _lines("AID", [f"{record.doi} [doi]"])
    out += _lines("PMC", [record.pmcid])
    out += _lines("LA", _split(record.language))
    out += _lines("MH", _split(record.keywords_mesh))
    out += _lines("OT", _split(record.keywords))
    out += _lines("AB", [record.abstract])
    return "\n".join(out)


def write_nbib(path: Path, records: Iterable[Record]) -> WriteResult:
    """Write ``records`` as one MEDLINE/NBIB file (atomic; a locked target gives an alternative).

    Raises:
        StorageError: (E401/E403) from the atomic write.
    """
    entries = [record_to_nbib(record) for record in records]
    logger.info("Writing %d NBIB record(s) to %s", len(entries), path.name)
    text = "\n\n".join(entries) + ("\n" if entries else "")
    return atomic_write_text(path, text)
