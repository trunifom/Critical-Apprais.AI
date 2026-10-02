"""Catalogue of record-level exclusion reasons (plan chapter 26.3) and who owns which.

A record is *marked* with at most one ``exclusion_reason``; it is never deleted. The reasons are a
data contract (they are persisted in ``records.csv``). This module only groups them by the step that
sets them, so the steps agree on who may replace whom:

* import sets ``EMPTY_RECORD`` and ``IMPORT_ERROR``;
* dedup sets ``DUPLICATE`` and may replace a validity or pre-filter reason (PRISMA removes
  duplicates first);
* the pre-filters set ``PREFILTER_LANGUAGE``, ``PREFILTER_YEAR``, ``PREFILTER_TYPE`` and
  ``PREFILTER_KEYWORD`` and may replace a validity reason;
* the validity check sets ``NOT_SCREENABLE``, ``RETRACTED`` and ``NO_ABSTRACT`` and never replaces
  another step's reason;
* the optional AI pre-filter (``crapai jev-prefilter``, ADR 0029) sets ``AI_PREFILTER_JEV``. It is
  **not** part of the ``prefilters``/``validity`` ownership chain above: unlike those, it is never
  run automatically by ``crapai check``/``crapai screen``, so it must not be cleared or recomputed
  by them either (``mark_prefilters``/``mark_validity`` only ever touch their own reason sets).
  Dedup does not replace it (it is not in ``REPLACEABLE_BY_DEDUP``): a record the AI pre-filter has
  already excluded is left exactly as it is.

Order of the steps: import, dedup, pre-filters, validity. The AI pre-filter sits outside this
order; run it whenever you like, its mark survives every rerun of the other steps.
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
REASON_PREFILTER_KEYWORD = "PREFILTER_KEYWORD"
REASON_AI_PREFILTER_JEV = "AI_PREFILTER_JEV"

VALIDITY_REASONS = frozenset({REASON_NOT_SCREENABLE, REASON_RETRACTED, REASON_NO_ABSTRACT})
PREFILTER_REASONS = frozenset(
    {REASON_PREFILTER_LANGUAGE, REASON_PREFILTER_YEAR, REASON_PREFILTER_TYPE,
     REASON_PREFILTER_KEYWORD}
)  # fmt: skip
# Its own tier, deliberately outside PREFILTER_REASONS/VALIDITY_REASONS/REPLACEABLE_BY_DEDUP (see
# the module docstring): it must not be cleared by mark_prefilters()/mark_validity(), and dedup
# must not silently replace it the way it may replace the other two groups.
AI_PREFILTER_REASONS = frozenset({REASON_AI_PREFILTER_JEV})
# Reasons that a later step in the order may replace (dedup replaces both groups).
REPLACEABLE_BY_DEDUP = VALIDITY_REASONS | PREFILTER_REASONS
