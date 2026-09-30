"""Deterministic pre-filters: language, year, publication type (plan chapter 35.4, U3).

Some criteria are metadata and should never be left to the model (a group of researchers found
that the model did not recognise the language of studies). These filters run in code **before** the
model and never consume tokens. Records are marked, never removed:

``PREFILTER_LANGUAGE``  the record's language is not in ``allow``
``PREFILTER_YEAR``      the year is outside ``min``/``max`` (bounds inclusive)
``PREFILTER_TYPE``      a publication type is in ``exclude``

If several filters apply, the first in this order is the reason and the details name all of them.
Retracted publications are handled by the validity check (``exclude_retracted``), not here.

Rules:

* A filter uses only the metadata that is present. If the field is missing, ``on_missing`` decides:
  ``pass`` (default) sends the record on to the model, ``exclude`` marks it. A language text that
  cannot be recognised counts as missing.
* Languages are compared as ISO 639-2 codes (``ger`` and ``deu``, ``de`` and ``German`` are the
  same). A record with several languages passes if any of them is allowed.
* A record with several publication types is excluded if any of them is on the list (case and
  spacing do not matter).
* Records that already carry a reason from the import or from dedup are left alone. Earlier
  ``PREFILTER_*`` marks are recomputed from scratch, so changing the settings works. A pre-filter
  reason may replace a validity reason (as ``DUPLICATE`` does); the validity check never
  replaces it.
  Order of the steps: import, dedup, pre-filters, validity.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from crapai.io.records_store import Record
from crapai.prisma.reasons import (
    PREFILTER_REASONS,
    REASON_PREFILTER_LANGUAGE,
    REASON_PREFILTER_TYPE,
    REASON_PREFILTER_YEAR,
    VALIDITY_REASONS,
)

logger = logging.getLogger(__name__)

OnMissing = Literal["pass", "exclude"]

# name or code -> ISO 639-2/B code. Keys are lower case; the list covers the usual languages of
# systematic reviews. Other three-letter codes are kept as they are.
_LANGUAGE_TABLE: dict[str, tuple[str, ...]] = {
    "eng": ("en", "eng", "english"),
    "ger": ("de", "ger", "deu", "german", "deutsch"),
    "fre": ("fr", "fre", "fra", "french", "français", "francais"),
    "spa": ("es", "spa", "spanish", "español", "espanol"),
    "ita": ("it", "ita", "italian", "italiano"),
    "dut": ("nl", "dut", "nld", "dutch", "nederlands"),
    "por": ("pt", "por", "portuguese", "português", "portugues"),
    "rus": ("ru", "rus", "russian"),
    "chi": ("zh", "chi", "zho", "chinese"),
    "jpn": ("ja", "jpn", "japanese"),
    "kor": ("ko", "kor", "korean"),
    "swe": ("sv", "swe", "swedish"),
    "dan": ("da", "dan", "danish"),
    "nor": ("no", "nor", "norwegian"),
    "fin": ("fi", "fin", "finnish"),
    "pol": ("pl", "pol", "polish"),
    "cze": ("cs", "cze", "ces", "czech"),
    "tur": ("tr", "tur", "turkish"),
    "ara": ("ar", "ara", "arabic"),
    "heb": ("he", "heb", "hebrew"),
    "gre": ("el", "gre", "ell", "greek"),
    "hun": ("hu", "hun", "hungarian"),
    "rum": ("ro", "rum", "ron", "romanian"),
    "lat": ("la", "lat", "latin"),
    "und": ("und", "undetermined"),
}
_LANGUAGE_LOOKUP = {alias: code for code, aliases in _LANGUAGE_TABLE.items() for alias in aliases}
_SPLIT = re.compile(r"[;,/|]+")


def normalize_language(text: str) -> str | None:
    """One language name or code as an ISO 639-2 code; None if it is empty.

    Known names and two- or three-letter codes are mapped (``de``, ``deu`` and ``German`` give
    ``ger``). Any other value is returned lower-cased so that it can still be matched exactly.
    """
    value = text.strip().lower().strip(".")
    if not value:
        return None
    return _LANGUAGE_LOOKUP.get(value, value)


def languages_of(text: str) -> tuple[list[str], bool]:
    """The recognised languages of a record's ``language`` field.

    Returns:
        ``(codes, recognised)``: the normalised codes in order, and whether at least one of them is
        a known language or a well-formed three-letter code. A text such as ``"n/a"`` or
        ``"see text"`` is not recognised and counts as missing.
    """
    codes = [c for c in (normalize_language(p) for p in _SPLIT.split(text)) if c]
    recognised = [c for c in codes if c in _LANGUAGE_TABLE or re.fullmatch(r"[a-z]{3}", c)]
    return codes, bool(recognised)


def normalize_type(text: str) -> str:
    """A publication type without case and surplus blanks (``" Letter "`` gives ``letter``)."""
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class PrefilterConfig:
    """Settings of the pre-filters; an empty ``language_allow`` etc. switches a filter off.

    Attributes:
        language_allow: Allowed languages (names or codes); empty = no language filter.
        language_on_missing: What to do with records whose language is missing or unrecognised.
        year_min: Earliest year (inclusive) or None.
        year_max: Latest year (inclusive) or None.
        year_on_missing: What to do with records without a year.
        type_exclude: Publication types to exclude; empty = no type filter.
        type_on_missing: What to do with records without any publication type.
    """

    language_allow: tuple[str, ...] = ()
    language_on_missing: OnMissing = "pass"
    year_min: int | None = None
    year_max: int | None = None
    year_on_missing: OnMissing = "pass"
    type_exclude: tuple[str, ...] = ()
    type_on_missing: OnMissing = "pass"

    @property
    def language_active(self) -> bool:
        """True if a language filter is configured."""
        return bool(self.language_allow)

    @property
    def year_active(self) -> bool:
        """True if a year bound is configured."""
        return self.year_min is not None or self.year_max is not None

    @property
    def type_active(self) -> bool:
        """True if a publication-type filter is configured."""
        return bool(self.type_exclude)

    @property
    def active(self) -> bool:
        """True if at least one filter is configured."""
        return self.language_active or self.year_active or self.type_active


@dataclass
class PrefilterResult:
    """Outcome of a pre-filter run.

    Attributes:
        records: All records in the original order, with the marks applied.
        removed: Records marked by the pre-filters.
        by_reason: Marked records per ``PREFILTER_*`` code.
        passed_on_missing: Records that were not filtered only because the metadata was missing
            (per filter: ``language``, ``year``, ``type``); they go to the model.
        skipped: Records ignored because the import or dedup already gave them a reason.
    """

    records: list[Record]
    removed: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    passed_on_missing: dict[str, int] = field(default_factory=dict)
    skipped: int = 0


def _language_hit(record: Record, config: PrefilterConfig, missing: Counter[str]) -> str | None:
    if not config.language_active:
        return None
    allowed = {normalize_language(a) for a in config.language_allow}
    codes, recognised = languages_of(record.language)
    if not recognised:
        if config.language_on_missing == "exclude":
            return "language: missing"
        missing["language"] += 1
        return None
    if allowed & set(codes):
        return None
    wanted = ", ".join(sorted(a for a in allowed if a))
    return f"language: {', '.join(codes)} (allowed: {wanted})"


def _year_hit(record: Record, config: PrefilterConfig, missing: Counter[str]) -> str | None:
    if not config.year_active:
        return None
    if record.year is None:
        if config.year_on_missing == "exclude":
            return "year: missing"
        missing["year"] += 1
        return None
    low = config.year_min if config.year_min is not None else "open"
    high = config.year_max if config.year_max is not None else "open"
    if config.year_min is not None and record.year < config.year_min:
        return f"year: {record.year} (range: {low}-{high})"
    if config.year_max is not None and record.year > config.year_max:
        return f"year: {record.year} (range: {low}-{high})"
    return None


def _type_hit(record: Record, config: PrefilterConfig, missing: Counter[str]) -> str | None:
    if not config.type_active:
        return None
    types = [t.strip() for t in record.publication_types.split(";") if t.strip()]
    if not types:
        if config.type_on_missing == "exclude":
            return "type: missing"
        missing["type"] += 1
        return None
    unwanted = {normalize_type(t) for t in config.type_exclude}
    hits = [t for t in types if normalize_type(t) in unwanted]
    return f"type: {', '.join(hits)}" if hits else None


def mark_prefilters(
    records: list[Record], config: PrefilterConfig | None = None
) -> PrefilterResult:
    """Apply the pre-filters to all records.

    Earlier ``PREFILTER_*`` marks are cleared first. The input list and its records are not
    modified.
    """
    config = config or PrefilterConfig()
    result = PrefilterResult(records=[])
    reasons: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    for record in records:
        current = record.exclusion_reason
        update: dict[str, object] = {}
        if current in PREFILTER_REASONS:
            current = ""
            update["exclusion_reason"] = ""
            update["exclusion_details"] = ""
        if current and current not in VALIDITY_REASONS:
            result.skipped += 1
            result.records.append(record.model_copy(update=update) if update else record)
            continue
        hits = [
            (code, text)
            for code, text in (
                (REASON_PREFILTER_LANGUAGE, _language_hit(record, config, missing)),
                (REASON_PREFILTER_YEAR, _year_hit(record, config, missing)),
                (REASON_PREFILTER_TYPE, _type_hit(record, config, missing)),
            )
            if text
        ]
        if hits:
            update["exclusion_reason"] = hits[0][0]
            update["exclusion_details"] = "; ".join(text for _, text in hits)
            reasons[hits[0][0]] += 1
        result.records.append(record.model_copy(update=update) if update else record)
    result.removed = sum(reasons.values())
    result.by_reason = dict(reasons)
    result.passed_on_missing = dict(missing)
    logger.info(
        "Pre-filters: %d of %d records marked %s; passed for missing metadata %s",
        result.removed,
        len(records),
        dict(reasons),
        dict(missing),
    )
    return result
