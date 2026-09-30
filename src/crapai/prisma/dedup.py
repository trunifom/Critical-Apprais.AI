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

PMIDs link records too (``doi_or_title`` and ``strict_ids``): the same non-empty PMID is the
same paper unless the two records carry *different* DOIs. A record without a PMID never matches
another record without one: an empty field is "unknown", not a value.

Optional fuzzy step (``fuzzy`` in :class:`DedupConfig`, ``dedup.fuzzy`` in ``project.yaml``): titles
that differ by a typo, a dropped word or a changed ending are linked when their similarity reaches
the threshold, the publication years are close, no two different DOIs are involved and the first
authors agree. It needs no extra package (``difflib`` of the standard library, with candidate
blocking so that 80 000 records do not mean 3 billion comparisons); if ``rapidfuzz`` happens to be
installed it is used for speed and gives the same decisions. The method is recorded as ``fuzzy``.

Sensitivity first: when in doubt, records are *not* marked; a wrongly marked duplicate would
silently hide a study from the screening. Two more guards follow from that rule:

* a title of fewer than :data:`MIN_TITLE_WORDS` words ("Editorial", "Erratum", "Letter") is too
  generic to identify a paper and never matches by itself (a DOI or PMID still does);
* DOIs are compared in their normalised form (lower case, without ``https://doi.org/``), so
  records that were built by hand or by an older version still match.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from crapai.io.normalize import normalize_doi
from crapai.io.records_store import Record
from crapai.prisma.reasons import REASON_DUPLICATE, REPLACEABLE_BY_DEDUP

logger = logging.getLogger(__name__)

Strategy = Literal["doi_or_title", "strict_ids", "title", "title_authors"]
Keep = Literal["best", "first", "last"]

METHOD_DOI = "doi"
METHOD_PMID = "pmid"
METHOD_TITLE = "title_norm"
METHOD_TITLE_AUTHORS = "title_authors"
METHOD_FUZZY = "fuzzy"

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)

# Titles shorter than this (in words) are too generic to identify a paper (see module docstring).
MIN_TITLE_WORDS = 4


def normalize_title(title: str) -> str:
    """Comparison form of a title: NFKD, no accents or punctuation, lower case, single spaces."""
    decomposed = unicodedata.normalize("NFKD", title)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", without_marks.casefold()).strip()


def title_key(title: str, min_words: int = MIN_TITLE_WORDS) -> str:
    """Normalised title for matching, or ``""`` if it is too short to identify a paper."""
    normalised = normalize_title(title)
    return normalised if len(normalised.split()) >= min_words else ""


def doi_key(doi: str) -> str:
    """Comparison form of a DOI: normalised like the import does, else just lower case."""
    return normalize_doi(doi) or doi.strip().lower()


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
        min_title_words: A title with fewer words never matches by title alone (1 switches the
            guard off).
        fuzzy: Also link titles that are similar but not equal (see the module docstring).
        fuzzy_threshold: Similarity from 0 to 1 that counts as the same title.
        fuzzy_max_year_difference: Records further apart in years are never fuzzy duplicates.
        fuzzy_require_author_agreement: If both records have authors, the first author's family
            name must agree.
    """

    strategy: Strategy = "doi_or_title"
    keep: Keep = "best"
    min_title_words: int = MIN_TITLE_WORDS
    fuzzy: bool = False
    fuzzy_threshold: float = 0.94
    fuzzy_max_year_difference: int = 1
    fuzzy_require_author_agreement: bool = True


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
        """Root of the group that contains ``item`` (with path compression)."""
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        """Join the groups of the two records; the smaller index becomes the root."""
        root_a, root_b = self.find(first), self.find(second)
        if root_a != root_b:
            # keep the smaller index as root so groups are stable and ordered
            self._parent[max(root_a, root_b)] = min(root_a, root_b)

    def components(self) -> dict[int, list[int]]:
        """All groups with at least two members, by root, members in ascending order."""
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


def _link_titles_avoiding_doi_conflicts(
    groups: _Groups, records: list[Record], min_words: int
) -> None:
    """Union records with the same normalised title unless that joins different DOIs."""
    by_title: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        title = title_key(record.title, min_words)
        if title:
            by_title[title].append(index)
    for members in by_title.values():
        if len(members) < 2:
            continue
        dois = {doi_key(records[index].doi) for index in members if records[index].doi}
        if len(dois) > 1:
            continue  # different papers with a common title: do not guess
        for index in members[1:]:
            groups.union(members[0], index)


def _link_title_and_authors(groups: _Groups, records: list[Record], min_words: int) -> None:
    keys = {
        index: (
            f"{title_key(record.title, min_words)}\x1f{normalize_authors(record.authors)}"
            if title_key(record.title, min_words)
            else ""
        )
        for index, record in enumerate(records)
    }
    _link_by_key(groups, keys)


def _same_pmid(first: Record, second: Record) -> bool:
    return bool(first.pmid) and first.pmid == second.pmid


def _method_for(config: DedupConfig, duplicate: Record, keeper: Record, min_words: int) -> str:
    """Why ``duplicate`` was linked to ``keeper`` (the strongest evidence wins)."""
    if duplicate.doi and keeper.doi and doi_key(duplicate.doi) == doi_key(keeper.doi):
        return METHOD_DOI
    if config.strategy != "title_authors" and _same_pmid(duplicate, keeper):
        return METHOD_PMID
    same_title = title_key(duplicate.title, min_words) == title_key(keeper.title, min_words)
    if config.strategy == "title_authors" and same_title:
        return METHOD_TITLE_AUTHORS
    if same_title and title_key(duplicate.title, min_words):
        return METHOD_TITLE
    if config.fuzzy:
        return METHOD_FUZZY
    return METHOD_TITLE if config.strategy != "strict_ids" else METHOD_PMID


def _link_pmids(groups: _Groups, records: list[Record]) -> None:
    """Union records with the same non-empty PMID unless they carry different DOIs."""
    by_pmid: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        if record.pmid:  # an empty PMID is "unknown" and never matches anything
            by_pmid[record.pmid].append(index)
    for members in by_pmid.values():
        dois = {doi_key(records[i].doi) for i in members if records[i].doi}
        if len(members) < 2 or len(dois) > 1:
            continue
        for index in members[1:]:
            groups.union(members[0], index)


MAX_BLOCK = 300  # a block larger than this is a generic phrase, not a candidate group


def _first_author(authors: str) -> str:
    """Normalised family name of the first author ("Doe, Jane; Roe" and "Jane Doe" both: doe)."""
    first = authors.split(";")[0].strip()
    if "," in first:
        return normalize_title(first.split(",")[0])
    words = normalize_title(first).split()
    return words[-1] if words else ""


def _blocks(title: str) -> list[str]:
    """Keys under which similar titles meet: start, end and the three longest words."""
    words = title.split()
    longest = sorted(sorted(set(words), key=lambda w: (-len(w), w))[:3])
    keys = [f"s:{title[:18]}", f"e:{title[-18:]}"]
    if len(longest) == 3:
        keys.append("w:" + " ".join(longest))
    return keys


def _similarity(first: str, second: str) -> float:
    """Title similarity from 0 to 1 (rapidfuzz if installed, else difflib; same decisions)."""
    try:
        from rapidfuzz import fuzz  # type: ignore[import-not-found,unused-ignore]

        return float(fuzz.ratio(first, second)) / 100.0
    except ImportError:
        matcher = difflib.SequenceMatcher(None, first, second, autojunk=False)
        if matcher.real_quick_ratio() < 0.5 or matcher.quick_ratio() < 0.5:
            return 0.0
        return matcher.ratio()


def _fuzzy_pair(first: Record, second: Record, a: str, b: str, config: DedupConfig) -> bool:
    """Whether two records with the normalised titles ``a`` and ``b`` are fuzzy duplicates."""
    if first.doi and second.doi and doi_key(first.doi) != doi_key(second.doi):
        return False
    years_known = first.year is not None and second.year is not None
    if years_known and abs(first.year - second.year) > config.fuzzy_max_year_difference:  # type: ignore[operator]
        return False
    authors_known = first.authors and second.authors
    if (
        config.fuzzy_require_author_agreement
        and authors_known
        and _first_author(first.authors) != _first_author(second.authors)
    ):
        return False
    return _similarity(a, b) >= config.fuzzy_threshold


def _link_fuzzy(groups: _Groups, records: list[Record], config: DedupConfig) -> int:
    """Union records whose titles are similar; returns the number of pairs that were compared."""
    titles = {
        index: title_key(record.title, config.min_title_words)
        for index, record in enumerate(records)
    }
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, title in titles.items():
        if title:
            for key in _blocks(title):
                blocks[key].append(index)
    compared: set[tuple[int, int]] = set()
    for members in blocks.values():
        if len(members) < 2 or len(members) > MAX_BLOCK:
            if len(members) > MAX_BLOCK:
                logger.info(
                    "Fuzzy dedup: skipped a block of %d records (too generic)", len(members)
                )
            continue
        for position, first in enumerate(members):
            for second in members[position + 1 :]:
                pair = (first, second)
                if pair in compared or groups.find(first) == groups.find(second):
                    continue
                compared.add(pair)
                if _fuzzy_pair(
                    records[first], records[second], titles[first], titles[second], config
                ):
                    groups.union(first, second)
    return len(compared)


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
        if record.exclusion_reason == REASON_DUPLICATE:
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
    if config.min_title_words < 1:
        raise ValueError("min_title_words must be at least 1")
    min_words = config.min_title_words

    current = clear_duplicate_marks(records)
    groups = _Groups(len(current))
    if config.strategy == "doi_or_title":
        _link_by_key(groups, {i: doi_key(r.doi) if r.doi else "" for i, r in enumerate(current)})
        _link_pmids(groups, current)
        _link_titles_avoiding_doi_conflicts(groups, current, min_words)
    elif config.strategy == "strict_ids":
        _link_by_key(groups, {i: doi_key(r.doi) if r.doi else "" for i, r in enumerate(current)})
        _link_pmids(groups, current)
    elif config.strategy == "title":
        _link_by_key(groups, {i: title_key(r.title, min_words) for i, r in enumerate(current)})
    else:
        _link_title_and_authors(groups, current, min_words)
    if config.fuzzy and config.strategy != "strict_ids":
        compared = _link_fuzzy(groups, current, config)
        logger.info("Fuzzy dedup compared %d candidate pair(s)", compared)

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
            method = _method_for(config, duplicate, keeper, min_words)
            update: dict[str, object] = {
                "is_duplicate": True,
                "duplicate_of": keeper.study_uid,
                "dedup_method": method,
            }
            # DUPLICATE beats the validity and pre-filter reasons (PRISMA removes duplicates
            # first) but never replaces a reason set by the import (EMPTY_RECORD, IMPORT_ERROR).
            if not duplicate.exclusion_reason or duplicate.exclusion_reason in REPLACEABLE_BY_DEDUP:
                update["exclusion_reason"] = REASON_DUPLICATE
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
