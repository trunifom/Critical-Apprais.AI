"""Catalogue of record-level exclusion reasons (plan chapter 26.3) and who owns which.

A record is *marked* with at most one ``exclusion_reason``; it is never deleted. The reasons are a
data contract (they are persisted in ``records.csv``). This module only groups them by the step that
sets them, so the steps agree on who may replace whom:

* import sets ``EMPTY_RECORD`` and ``IMPORT_ERROR``;
* dedup sets ``DUPLICATE`` and may replace a validity reason (PRISMA removes duplicates first);
* the validity check sets ``NOT_SCREENABLE``, ``RETRACTED`` and ``NO_ABSTRACT`` and never replaces
  another step's reason.
"""

from __future__ import annotations

REASON_DUPLICATE = "DUPLICATE"
REASON_EMPTY_RECORD = "EMPTY_RECORD"
REASON_IMPORT_ERROR = "IMPORT_ERROR"
REASON_NOT_SCREENABLE = "NOT_SCREENABLE"
REASON_RETRACTED = "RETRACTED"
REASON_NO_ABSTRACT = "NO_ABSTRACT"

VALIDITY_REASONS = frozenset({REASON_NOT_SCREENABLE, REASON_RETRACTED, REASON_NO_ABSTRACT})
