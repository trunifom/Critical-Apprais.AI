"""BibTeX writer: bibliographic export for reference managers (symmetric to the BibTeX reader).

Each record becomes one ``@type{key, ...}`` entry; ``key`` is the ``study_uid`` (stable, lets a
decision be matched back to the entry after import elsewhere). Screening marks travel in the
``note`` field, the same idea as the RIS writer's ``N1``: ``Excluded before screening: DUPLICATE``,
``Duplicate of: ...``, ``Retracted publication``.

Field values are braced (``title = {...}``); a literal ``{``/``}``/``\\`` in a value is escaped so
it cannot break out of the braces. Authors are joined with `` and ``, BibTeX's own separator
(different from the ``"; "`` used in ``records.csv``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from crapai.io.readers.bibtex import RECORD_TYPES
from crapai.io.records_store import Record
from crapai.project.atomic import WriteResult, atomic_write_text

logger = logging.getLogger(__name__)

# internal type -> BibTeX entry type (first listed BibTeX type wins; "other" has no better fit)
_TYPE_TO_BIBTEX: dict[str, str] = {}
for _entry_type, _internal in RECORD_TYPES.items():
    _TYPE_TO_BIBTEX.setdefault(_internal, _entry_type)
_TYPE_TO_BIBTEX["other"] = "misc"

_ESCAPE = str.maketrans({"\\": r"\\", "{": r"\{", "}": r"\}"})


def _braced(value: str) -> str:
    return "{" + " ".join(value.split()).translate(_ESCAPE) + "}"


def _split(value: str) -> list[str]:
    """Split a ``"a; b; c"`` column into its items."""
    return [item.strip() for item in value.split(";") if item.strip()]


def record_to_bibtex(record: Record) -> str:
    """One record as a BibTeX entry (text with no trailing blank line)."""
    entry_type = _TYPE_TO_BIBTEX.get(record.record_type, "misc")
    fields: list[tuple[str, str]] = []
    if record.title:
        fields.append(("title", record.title))
    authors = _split(record.authors)
    if authors:
        fields.append(("author", " and ".join(authors)))
    if record.year is not None:
        fields.append(("year", str(record.year)))
    if record.journal:
        fields.append(("journal", record.journal))
    if record.volume:
        fields.append(("volume", record.volume))
    if record.issue:
        fields.append(("number", record.issue))
    if record.pages:
        fields.append(("pages", record.pages))
    if record.doi:
        fields.append(("doi", record.doi))
    if record.url:
        fields.append(("url", record.url))
    if record.issn_isbn:
        fields.append(("issn", record.issn_isbn))
    language = _split(record.language)
    if language:
        fields.append(("langid", "; ".join(language)))
    keywords = _split(record.keywords) + _split(record.keywords_mesh)
    if keywords:
        fields.append(("keywords", "; ".join(keywords)))
    if record.abstract:
        fields.append(("abstract", record.abstract))
    notes = []
    if record.exclusion_reason:
        notes.append(f"Excluded before screening: {record.exclusion_reason}")
    if record.is_duplicate and record.duplicate_of:
        notes.append(f"Duplicate of: {record.duplicate_of}")
    if record.is_retracted:
        notes.append("Retracted publication")
    if notes:
        fields.append(("note", "; ".join(notes)))
    body = ",\n".join(f"  {name} = {_braced(value)}" for name, value in fields)
    return f"@{entry_type}{{{record.study_uid},\n{body}\n}}"


def write_bibtex(path: Path, records: Iterable[Record]) -> WriteResult:
    """Write ``records`` as one BibTeX file (atomic; a locked target gives an alternative file).

    Raises:
        StorageError: (E401/E403) from the atomic write.
    """
    entries = [record_to_bibtex(record) for record in records]
    logger.info("Writing %d BibTeX entr(ies) to %s", len(entries), path.name)
    text = "\n\n".join(entries) + ("\n" if entries else "")
    return atomic_write_text(path, text)
