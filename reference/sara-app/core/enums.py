# -*- coding: utf-8 -*-
"""
Centralized enums used across SARA (PRISMA workflow, logging, UI, and services).

Goals:
- Single source of truth to avoid circular imports and inconsistent constants.
- String-valued enums to stay JSON/CSV/DB friendly without extra casting.
- Stable values to keep persisted logs and analytics compatible over time.

Conventions:
- Inherit from StringEnum (str + Enum). Its __str__ returns .value, so both
  str(MyEnum.FOO) and MyEnum.FOO.value yield the same, DB-ready string.
- Only use ASCII characters in enum values to remain storage/transport safe.
"""

from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
    """String-valued Enum that remains JSON/DB friendly."""
    def __str__(self) -> str:  # pragma: no cover
        return self.value


# ──────────────────────────────────────────────────────────────────────────────
# Preflight (UI-only validation of uploaded files)
# ──────────────────────────────────────────────────────────────────────────────

class PreflightStatus(StringEnum):
    """Overall status of a preflight check for a single file."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class PreflightIssueCode(StringEnum):
    """Machine-readable reason codes for preflight outcomes (used in i18n mapping)."""
    PARSE_FAILED = "parse_failed"
    NO_RECORDS = "no_records"
    NO_ABSTRACTS = "no_abstracts"
    LOW_ABSTRACT_RATIO = "low_abstract_ratio"
    UNSUPPORTED_TYPE = "unsupported_type"


# ──────────────────────────────────────────────────────────────────────────────
# PRISMA: coarse workflow states (optional, useful for UI)
# ──────────────────────────────────────────────────────────────────────────────

class PrismaWorkflowState(StringEnum):
    INITIAL = "initial"
    SOURCES_IMPORTED = "sources_imported"
    SOURCES_DEDUPED = "sources_deduped"      # optional per-source optimization
    MERGED = "merged"
    MERGED_DEDUPED = "merged_deduped"
    TITLE_ABSTRACT_SCREENED = "title_abstract_screened"
    FULLTEXT_SCREENED = "fulltext_screened"
    COMPLETED = "completed"


# ──────────────────────────────────────────────────────────────────────────────
# PRISMA: steps and event types used by the audit logger
# ──────────────────────────────────────────────────────────────────────────────

class PrismaStep(StringEnum):
    """High-level PRISMA steps used for event 'step' classification."""
    IMPORT = "import"
    DEDUP_PER_SOURCE = "dedup_per_source"
    MERGE = "merge"
    DEDUP_MERGED = "dedup_merged"
    SCREEN_ABSTRACT = "screen_abstract"
    SCREEN_FULLTEXT = "screen_fulltext"
    EXPORT = "export"


class EventType(StringEnum):
    """Fine-grained event types for the audit trail."""
    SOURCE_IMPORTED = "SOURCE_IMPORTED"
    DEDUP_WITHIN_SOURCE = "DEDUP_WITHIN_SOURCE"
    MERGE_ALL_SOURCES = "MERGE_ALL_SOURCES"
    DEDUP_GLOBAL = "DEDUP_GLOBAL"
    SCREEN_TA = "SCREEN_TA"
    SCREEN_FT = "SCREEN_FT"
    EXPORT = "EXPORT"
    WARNING = "WARNING"
    ERROR = "ERROR"
    INFO = "INFO"


class LogLevel(StringEnum):
    """Severity levels for events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class ScreeningPhase(StringEnum):
    """Screening phase classification."""
    ABSTRACT = "abstract"
    FULLTEXT = "fulltext"


class RunStatus(StringEnum):
    """Run lifecycle states."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class DuplicatesReportingMode(StringEnum):
    """
    Defines how 'duplicates removed' is reported for PRISMA:
    - ALL_BEFORE_SCREENING: counts ALL duplicates removed before screening
      (within-source + across-sources).
    - BETWEEN_DATABASES_ONLY: counts ONLY duplicates removed in the global
      cross-source dedup step; within-source removals are booked as 'other'.
    """
    ALL_BEFORE_SCREENING = "all_before_screening"
    BETWEEN_DATABASES_ONLY = "between_databases_only"


# ──────────────────────────────────────────────────────────────────────────────
# Misc. shared enums (optional but handy for payloads and UI)
# ──────────────────────────────────────────────────────────────────────────────

class ScreeningMode(StringEnum):
    ABSTRACT = "abstract"
    FULLTEXT = "fulltext"


class PrismaEventType(StringEnum):
    """Legacy/general-purpose event bucket for UI dashboards (optional)."""
    PROJECT_CREATED = "project_created"
    SOURCE_IMPORTED = "source_imported"
    SOURCE_DEDUPED = "source_deduped"
    MERGED = "merged"
    MERGED_DEDUPED = "merged_deduped"
    SCREEN_TITLE_ABSTRACT = "screen_title_abstract"
    SCREEN_FULLTEXT = "screen_fulltext"
    EXPORT = "export"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FileType(StringEnum):
    """Supported bibliographic file types (if needed in payloads/UI)."""
    RIS = "ris"
    BIB = "bib"
    CSV = "csv"
    ZIP = "zip"
    JSON = "json"


class Framework(StringEnum):
    """Search/screening frameworks."""
    PICOS = "PICOS"
    SPIDER = "SPIDER"
    PECO = "PECO"
    CUSTOM = "CUSTOM"


class LLMProvider(StringEnum):
    """LLM providers (expand as needed)."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"     # Gemini
    META = "meta"         # Llama
    XAI = "xai"           # Grok
    MISTRAL = "mistral"


__all__ = [
    # Preflight
    "PreflightStatus",
    "PreflightIssueCode",
    # PRISMA logging
    "PrismaStep",
    "EventType",
    "LogLevel",
    "ScreeningPhase",
    "RunStatus",
    "DuplicatesReportingMode",
    # Optional helpers
    "PrismaWorkflowState",
    "PrismaEventType",
    "ScreeningMode",
    "FileType",
    "Framework",
    "LLMProvider",
    # base
    "StringEnum",
]