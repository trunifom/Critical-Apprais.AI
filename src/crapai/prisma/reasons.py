"""Catalogue of record-level exclusion reasons (plan chapter 26.3) and who owns which.

A record is *marked* with at most one ``exclusion_reason``; it is never deleted. The reasons are a
data contract (they are persisted in ``records.csv``). This module only groups them by the step that
sets them, so the steps agree on who may replace whom:

* import sets ``EMPTY_RECORD`` and ``IMPORT_ERROR``;
* dedup sets ``DUPLICATE`` and may replace a validity or pre-filter reason (PRISMA removes
  duplicates first);
* the pre-filters set ``PREFILTER_LANGUAGE``, ``PREFILTER_YEAR`` and ``PREFILTER_TYPE`` and may
  replace a validity reason;
* the validity check sets ``NOT_SCREENABLE``, ``RETRACTED`` and ``NO_ABSTRACT`` and never replaces
  another step's reason.

Order of the steps: import, dedup, pre-filters, validity.
"""

from __future__ import annotations

REASON_DUPLICATE = "DUPLICATE"
REASON_EMPTY_RECORD = "EMPTY_RECORD"
REASON_IMPORT_ERROR = "IMPORT_ERROR"
REASON_NOT_SCREENABLE = "NOT_SCREENABLE"
REASON_RETRACTED = "RETRACTED"
REASON_NO_ABSTRACT = "NO_ABSTRACT"
REASON_PREFILTER_LANGUAGE = "PREFILTER_LANGUAGE"
REASON_PREFILTER_YEAR = "PREFILTER_YEAR"
REASON_PREFILTER_TYPE = "PREFILTER_TYPE"

VALIDITY_REASONS = frozenset({REASON_NOT_SCREENABLE, REASON_RETRACTED, REASON_NO_ABSTRACT})
PREFILTER_REASONS = frozenset(
    {REASON_PREFILTER_LANGUAGE, REASON_PREFILTER_YEAR, REASON_PREFILTER_TYPE}
)
# Reasons that a later step in the order may replace (dedup replaces both groups).
REPLACEABLE_BY_DEDUP = VALIDITY_REASONS | PREFILTER_REASONS
