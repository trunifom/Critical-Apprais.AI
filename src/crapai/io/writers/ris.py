"""RIS writer: bibliographic export for reference managers and screening tools (plan 25.8).

The output is meant for Zotero, EndNote, Covidence and Rayyan. Each record becomes one RIS entry.
The internal ``record_type`` is mapped back to a RIS ``TY`` value; the screening marks travel in
the standard note field so they are visible after the import:

* ``ID`` carries the ``study_uid`` (stable key for matching decisions back to records),
* ``N1`` carries lines such as ``Excluded before screening: DUPLICATE`` and ``Duplicate of: ...``.

Values are cleaned for the format: line breaks inside a value become spaces (a RIS value is one
line), and every entry ends with ``ER  - ``. The file is UTF-8 with LF line ends, which all the
tools above accept.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from crapai.io.readers.ris import RECORD_TYPES
from crapai.io.records_store import Record
from crapai.project.atomic import WriteResult, atomic_write_text

logger = logging.getLogger(__name__)

# internal type -> RIS type (first listed RIS type wins; ``other`` has no better name than GEN)
_TYPE_TO_RIS: dict[str, str] = {}
for _ris, _internal in RECORD_TYPES.items():
    _TYPE_TO_RIS.setdefault(_internal, _ris)
_TYPE_TO_RIS["other"] = "GEN"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _lines(tag: str, values: Iterable[str]) -> list[str]:
    return [f"{tag}  - {_one_line(v)}" for v in values if v and v.strip()]


def _split(value: str) -> list[str]:
    """Split a ``"a; b; c"`` column into its items."""
    return [item.strip() for item in value.split(";") if item.strip()]


def record_to_ris(record: Record) -> str:
    """One record as a RIS entry (text ending with ``ER  - ``)."""
    out: list[str] = [f"TY  - {_TYPE_TO_RIS.get(record.record_type, 'GEN')}"]
    out += _lines("ID", [record.study_uid])
    out += _lines("TI", [record.title])
    out += _lines("AU", _split(record.authors))
    out += _lines("A2", _split(record.editors))
    out += _lines("PY", [str(record.year)] if record.year is not None else [])
    out += _lines("JO", [record.journal])
    out += _lines("VL", [record.volume])
    out += _lines("IS", [record.issue])
    start, _, end = record.pages.partition("-")
    out += _lines("SP", [start.strip()])
    out += _lines("EP", [end.strip()])
    out += _lines("DO", [record.doi])
    out += _lines("UR", [record.url])
    out += _lines("AN", [record.pmid or record.accession_number])
    out += _lines("SN", [record.issn_isbn])
    out += _lines("LA", _split(record.language))
    out += _lines("KW", _split(record.keywords) + _split(record.keywords_mesh))
    out += _lines("AB", [record.abstract])
    notes = []
    if record.exclusion_reason:
        notes.append(f"Excluded before screening: {record.exclusion_reason}")
    if record.is_duplicate and record.duplicate_of:
        notes.append(f"Duplicate of: {record.duplicate_of}")
    if record.is_retracted:
        notes.append("Retracted publication")
    out += _lines("N1", notes)
    out.append("ER  - ")
    return "\n".join(out)


def write_ris(path: Path, records: Iterable[Record]) -> WriteResult:
    """Write ``records`` as one RIS file (atomic; a locked target gives an alternative file).

    Raises:
        StorageError: (E401/E403) from the atomic write.
    """
    entries = [record_to_ris(record) for record in records]
    logger.info("Writing %d RIS entr(ies) to %s", len(entries), path.name)
    text = "\n\n".join(entries) + ("\n" if entries else "")
    return atomic_write_text(path, text)
