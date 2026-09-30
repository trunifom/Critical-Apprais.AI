"""Duplicate marking (plan chapter 8.4): non-destructive, transparent, conservative.

Records are **marked, never removed**: a duplicate keeps its row, gets ``is_duplicate=True``, points
to the kept record with ``duplicate_of`` (its ``study_uid``), names the reason in ``dedup_method``
and, unless it already has one, ``exclusion_reason="DUPLICATE"``. The row count never changes.

Strategies (``project.yaml`` ``dedup.strategy``):

``doi_or_title`` (default)
    Same DOI, or same normalised title. A title match is ignored when it would join records with
    *different* DOIs (two different papers may share a short title such as "Editorial").
``strict_ids``
    Same DOI or same PMID; titles are never compared.
``title``
    Same normalised title.
``title_authors``
    Same normalised title and same normalised authors (both empty counts as the same).

Improvements over the predecessor (``literature_database.py``):

* titles are compared **normalised** (Unicode NFKD, no accents or punctuation, lower case);
* records **without** a title or DOI never match each other (the predecessor treated all empty
  titles as duplicates of one another);
* the kept record is the most complete one (abstract, then DOI, then PMID), the first in import
  order on ties;
* all helpers exist once.

Sensitivity first: when in doubt, records are *not* marked; a wrongly marked duplicate would
silently hide a study from the screening.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from crapai.io.records_store import Record

logger = logging.getLogger(__name__)

Strategy = Literal["doi_or_title", "strict_ids", "title", "title_authors"]
Keep = Literal["best", "first", "last"]

METHOD_DOI = "doi"
METHOD_PMID = "pmid"
METHOD_TITLE = "title_norm"
METHOD_TITLE_AUTHORS = "title_authors"

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(title: str) -> str:
    """Comparison form of a title: NFKD, no accents or punctuation, lower case, single spaces."""
    decomposed = unicodedata.normalize("NFKD", title)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", without_marks.casefold()).strip()


def normalize_authors(authors: str) -> str:
    """Comparison form of an author list (same rules as titles; ``;`` separators become spaces)."""
    return normalize_title(authors)


@dataclass(frozen=True)
class DedupConfig:
    """How to mark duplicates.

    Attributes:
        strategy: One of the four strategies described in the module docstring.
        keep: Which record of a group stays unmarked: ``best`` (most complete, first on ties),
            ``first`` or ``last`` in import order.
    """

    strategy: Strategy = "doi_or_title"
    keep: Keep = "best"


@dataclass
class DedupResult:
    """Outcome of one dedup run.

    Attributes:
        records: All records in the original order, with the duplicate marks applied. Row count and
            order equal the input.
        marked: Number of records marked as duplicates.
        groups: Number of duplicate groups (each has exactly one kept record).
        by_method: Marked records per ``dedup_method``.
        within_source: Marked records whose kept record has the same ``source_label``, per label
            (event ``DEDUP_WITHIN_SOURCE``).
        across_sources: Marked records whose kept record comes from another source
            (event ``DEDUP_GLOBAL``).
    """

    records: list[Record]
    marked: int = 0
    groups: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    within_source: dict[str, int] = field(default_factory=dict)
    across_sources: int = 0


class _Groups:
    """Union-find over record indices."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        root_a, root_b = self.find(first), self.find(second)
        if root_a != root_b:
            # keep the smaller index as root so groups are stable and ordered
            self._parent[max(root_a, root_b)] = min(root_a, root_b)

    def components(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = defaultdict(list)
        for index in range(len(self._parent)):
            groups[self.find(index)].append(index)
        return {root: members for root, members in groups.items() if len(members) > 1}


def _completeness(record: Record) -> tuple[int, int, int]:
    return (int(bool(record.abstract.strip())), int(bool(record.doi)), int(bool(record.pmid)))


def _choose_keeper(records: list[Record], members: list[int], keep: Keep) -> int:
    if keep == "last":
        return members[-1]
    if keep == "first":
        return members[0]
    # best: highest completeness; the earliest record wins ties (max returns the first maximum)
    return max(members, key=lambda index: _completeness(records[index]))


def _link_by_key(groups: _Groups, keys: dict[int, str]) -> None:
    """Union all records that share a non-empty key."""
    first_with_key: dict[str, int] = {}
    for index, key in keys.items():
        if not key:
            continue
        if key in first_with_key:
            groups.union(first_with_key[key], index)
        else:
            first_with_key[key] = index


def _link_titles_avoiding_doi_conflicts(groups: _Groups, records: list[Record]) -> None:
    """Union records with the same normalised title unless that joins different DOIs."""
    by_title: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        title = normalize_title(record.title)
        if title:
            by_title[title].append(index)
    for members in by_title.values():
        if len(members) < 2:
            continue
        dois = {records[index].doi for index in members if records[index].doi}
        if len(dois) > 1:
            continue  # different papers with a common title: do not guess
        for index in members[1:]:
            groups.union(members[0], index)


def _link_title_and_authors(groups: _Groups, records: list[Record]) -> None:
    keys = {
        index: (
            f"{normalize_title(record.title)}\x1f{normalize_authors(record.authors)}"
            if normalize_title(record.title)
            else ""
        )
        for index, record in enumerate(records)
    }
    _link_by_key(groups, keys)


def _method_for(strategy: Strategy, duplicate: Record, keeper: Record) -> str:
    if strategy == "title":
        return METHOD_TITLE
    if strategy == "title_authors":
        return METHOD_TITLE_AUTHORS
    if duplicate.doi and duplicate.doi == keeper.doi:
        return METHOD_DOI
    if strategy == "strict_ids":
        return METHOD_PMID
    return METHOD_TITLE


def clear_duplicate_marks(records: list[Record]) -> list[Record]:
    """Return copies without any earlier duplicate marks (so a new strategy starts clean).

    ``exclusion_reason`` is cleared only where it is ``DUPLICATE``; other reasons stay.
    """
    cleaned: list[Record] = []
    for record in records:
        if not (record.is_duplicate or record.duplicate_of or record.dedup_method):
            cleaned.append(record)
            continue
        update: dict[str, object] = {
            "is_duplicate": False,
            "duplicate_of": "",
            "dedup_method": "",
        }
        if record.exclusion_reason == "DUPLICATE":
            update["exclusion_reason"] = ""
            update["exclusion_details"] = ""
        cleaned.append(record.model_copy(update=update))
    return cleaned


def mark_duplicates(records: list[Record], config: DedupConfig | None = None) -> DedupResult:
    """Mark duplicates among ``records``. Earlier dedup marks are discarded first.

    Nothing is deleted, reordered or otherwise changed except the mark columns. Running it twice
    with the same configuration gives the same result.

    Raises:
        ValueError: if the strategy or ``keep`` value is unknown.
    """
    config = config or DedupConfig()
    if config.strategy not in ("doi_or_title", "strict_ids", "title", "title_authors"):
        raise ValueError(f"unknown dedup strategy: {config.strategy!r}")
    if config.keep not in ("best", "first", "last"):
        raise ValueError(f"unknown keep rule: {config.keep!r}")

    current = clear_duplicate_marks(records)
    groups = _Groups(len(current))
    if config.strategy == "doi_or_title":
        _link_by_key(groups, {i: r.doi for i, r in enumerate(current)})
        _link_titles_avoiding_doi_conflicts(groups, current)
    elif config.strategy == "strict_ids":
        _link_by_key(groups, {i: r.doi for i, r in enumerate(current)})
        _link_by_key(groups, {i: r.pmid for i, r in enumerate(current)})
    elif config.strategy == "title":
        _link_by_key(groups, {i: normalize_title(r.title) for i, r in enumerate(current)})
    else:
        _link_title_and_authors(groups, current)

    result = DedupResult(records=list(current))
    by_method: Counter[str] = Counter()
    within: Counter[str] = Counter()
    for members in groups.components().values():
        keeper_index = _choose_keeper(current, members, config.keep)
        keeper = current[keeper_index]
        result.groups += 1
        for index in members:
            if index == keeper_index:
                continue
            duplicate = current[index]
            method = _method_for(config.strategy, duplicate, keeper)
            update: dict[str, object] = {
                "is_duplicate": True,
                "duplicate_of": keeper.study_uid,
                "dedup_method": method,
            }
            if not duplicate.exclusion_reason:
                update["exclusion_reason"] = "DUPLICATE"
                update["exclusion_details"] = f"duplicate of {keeper.study_uid} ({method})"
            result.records[index] = duplicate.model_copy(update=update)
            result.marked += 1
            by_method[method] += 1
            if duplicate.source_label == keeper.source_label:
                within[duplicate.source_label] += 1
            else:
                result.across_sources += 1
    result.by_method = dict(by_method)
    result.within_source = dict(within)
    logger.info(
        "Marked %d duplicate(s) in %d group(s) with strategy %s",
        result.marked,
        result.groups,
        config.strategy,
    )
    return result
