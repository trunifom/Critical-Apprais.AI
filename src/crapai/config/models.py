"""Pydantic models for ``project.yaml`` (plan chapter 16.1, schema version 1).

The models are the validated source of truth for the project configuration. Every model forbids
unknown keys, so typos are reported instead of silently ignored. API keys can never be stored:
``llm.api_key_env`` holds only the *name* of an environment variable, and values that are not a
valid variable name (for example a pasted key) are rejected.

Built-in defaults are the field defaults; the loader merges user config, project file,
environment and command line on top (chapter 16.3).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# POSIX-style environment variable name. Anything else (spaces, dashes, "sk-...") is not a name.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

PositiveInt = Annotated[int, Field(gt=0)]


class _Strict(BaseModel):
    """Base for all config models: unknown keys are errors, offending input is never echoed."""

    # hide_input_in_errors keeps a pasted secret out of ValidationError text (and thus out of logs).
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ProjectInfo(_Strict):
    """Title, language and mode of the review project."""

    title: str = Field(min_length=1)
    description: str = ""
    language: Literal["de", "en"] = "de"
    mode: Literal["abstract"] = "abstract"

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("mode", mode="before")
    @classmethod
    def _fulltext_is_not_in_v1(cls, value: object) -> object:
        # ADR 0015: full-text screening is not part of version 1; give a clear message.
        if value == "fulltext":
            raise ValueError("full-text screening is not supported in version 1; use 'abstract'")
        return value


class Criteria(_Strict):
    """Inclusion and exclusion criteria per framework element."""

    framework: Literal["PICOS", "SPIDER", "PECO", "PIRD", "CUSTOM"] = "PICOS"
    custom_fields: list[str] = Field(default_factory=list)
    inclusion: dict[str, str] = Field(default_factory=dict)
    exclusion: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_custom_and_inclusion(self) -> Criteria:
        if self.framework == "CUSTOM" and not self.custom_fields:
            raise ValueError("framework CUSTOM requires custom_fields")
        if self.framework != "CUSTOM" and self.custom_fields:
            raise ValueError("custom_fields is only allowed with framework CUSTOM")
        if not any(text.strip() for text in self.inclusion.values()):
            raise ValueError("at least one inclusion criterion is required")
        return self


class Fuzzy(_Strict):
    """Optional fuzzy duplicate detection (titles that differ by a typo or a dropped word).

    Attributes:
        enabled: Switch the fuzzy step on; off by default because it can mark wrongly.
        threshold: Title similarity from 0 to 1 that counts as the same paper.
        max_year_difference: Two records more than this many years apart are never fuzzy
            duplicates (publication years differ by one between print and online date).
        require_author_agreement: If both records have authors, the first author's family name
            must agree.
    """

    enabled: bool = False
    threshold: float = Field(default=0.94, ge=0.0, le=1.0)
    max_year_difference: int = Field(default=1, ge=0)
    require_author_agreement: bool = True


class Dedup(_Strict):
    """Duplicate marking strategy (records are marked, never deleted)."""

    strategy: Literal["doi_or_title", "strict_ids", "title", "title_authors"] = "doi_or_title"
    # Titles with fewer words never match by title alone ("Editorial", "Erratum"); 1 = off.
    min_title_words: PositiveInt = 4
    fuzzy: Fuzzy = Field(default_factory=Fuzzy)
    reporting_mode: Literal["all_before_screening", "between_databases_only"] = (
        "all_before_screening"
    )


class LanguageFilter(_Strict):
    """Deterministic language filter (ISO 639-2/-3 codes, e.g. ``eng``, ``ger``)."""

    allow: list[str] = Field(default_factory=list)
    # ``pass``: a record without the metadata goes on to the LLM (plan chapter 35.4).
    # ``exclude`` is an assumption of this implementation; the plan documents only ``pass``.
    on_missing: Literal["pass", "exclude"] = "pass"


class YearFilter(_Strict):
    """Deterministic publication-year filter (bounds are inclusive; null = open)."""

    min: int | None = None
    max: int | None = None
    on_missing: Literal["pass", "exclude"] = "pass"

    @model_validator(mode="after")
    def _ordered(self) -> YearFilter:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not be greater than max")
        return self


class PublicationTypeFilter(_Strict):
    """Deterministic publication-type filter."""

    exclude: list[str] = Field(default_factory=list)
    on_missing: Literal["pass", "exclude"] = "pass"


class Prefilters(_Strict):
    """Filters that run in code before the LLM (plan chapter 35.4, U3). All off by default."""

    language: LanguageFilter | None = None
    year: YearFilter | None = None
    publication_types: PublicationTypeFilter | None = None
    exclude_retracted: bool = False


class FulltextOptions(_Strict):
    """Reserved for a later version; accepted in the file so templates validate."""

    strategy: Literal["truncate", "sections", "map_reduce"] = "truncate"
    repeat_criteria_after_text: bool = False


class ScreeningOptions(_Strict):
    """How the screening prompt is built and how answers are interpreted."""

    prompt_variant: str = "gpt_improved_abstract"
    output_format: Literal["structured", "legacy_xxx_yyy"] = "structured"
    # Sensitivity first (plan chapter 35.2): uncertain records are included by default.
    uncertain_policy: Literal["include", "exclude", "keep_separate"] = "include"
    decision_source: Literal["model", "rule"] = "model"
    reasoning_language: Literal["en", "de"] = "en"
    include_title_only: bool = False
    fulltext: FulltextOptions = Field(default_factory=FulltextOptions)


class LlmSettings(_Strict):
    """Provider, model and sampling settings. Holds the NAME of the key variable, never the key."""

    provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    model: str = Field(default="gpt-4o-mini", min_length=1)
    base_url: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    seed: int | None = None
    max_output_tokens: PositiveInt = 800
    # Expected length of one answer, for the estimate; max_output_tokens is the hard limit.
    expected_output_tokens: PositiveInt = 120
    timeout_s: float = Field(default=60.0, gt=0.0)
    api_key_env: str = "OPENAI_API_KEY"

    @field_validator("api_key_env")
    @classmethod
    def _must_be_a_variable_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            # Deliberately do not echo the value: it might be a pasted key.
            raise ValueError(
                "api_key_env must be the NAME of an environment variable, not a key or secret"
            )
        return value

    @model_validator(mode="after")
    def _base_url_only_for_compatible(self) -> LlmSettings:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("provider openai_compatible requires base_url")
        if self.provider != "openai_compatible" and self.base_url:
            raise ValueError("base_url is only allowed with provider openai_compatible")
        return self


class Limits(_Strict):
    """Concurrency, rate limits, retries, cost cap and the assumptions of the estimate.

    Attributes:
        max_concurrency: Requests in flight at the same time.
        rpm: Requests per minute allowed by the provider.
        tpm: Tokens per minute allowed by the provider.
        max_retries: Retries after a server error, timeout or lost connection.
        max_parse_retries: Extra questions when the answer is not valid.
        max_cost: Stop the run before this amount is exceeded; ``null`` = no limit.
        currency: Currency of the price list and the cost figures.
        seconds_per_request: Assumed time of one request, for the duration estimate only.
        cost_uncertainty: Half width of the cost band in the estimate (0.15 = plus/minus 15 %).
    """

    max_concurrency: PositiveInt = 5
    rpm: PositiveInt = 500
    tpm: PositiveInt = 200_000
    max_retries: int = Field(default=5, ge=0)
    max_parse_retries: int = Field(default=2, ge=0)
    max_cost: float | None = Field(default=10.0, ge=0.0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    seconds_per_request: float = Field(default=3.0, gt=0.0)
    cost_uncertainty: float = Field(default=0.15, ge=0.0, le=1.0)


class QualitySettings(_Strict):
    """Thresholds of the abstract-quality hint (``ok``, ``short``, ``suspect_concat``).

    The hint never excludes a record; it only tells the preflight and the reader.

    Attributes:
        long_word_letters: A single word longer than this many letters looks glued together.
        short_abstract_words: An abstract with fewer words than this counts as ``short``.
        garbled_mean_word_letters: A mean word length above this (with enough words) looks
            garbled.
        min_words_for_mean: Fewer words than this are too few to judge the mean word length.
        short_abstract_chars_unspaced: Like ``short_abstract_words`` for Chinese, Japanese,
            Korean and Thai, which have no spaces: the abstract is short below this many
            characters.
    """

    long_word_letters: PositiveInt = 40
    short_abstract_words: PositiveInt = 40
    garbled_mean_word_letters: float = Field(default=9.0, gt=0.0)
    min_words_for_mean: PositiveInt = 30
    short_abstract_chars_unspaced: PositiveInt = 120


class PreflightSettings(_Strict):
    """Thresholds of ``crapai check``.

    Attributes:
        min_abstract_ratio: A source with a smaller share of records with an abstract gets a
            warning.
    """

    min_abstract_ratio: float = Field(default=0.60, ge=0.0, le=1.0)


class OutputSettings(_Strict):
    """Formatting of the written tables."""

    csv_separator: str = Field(default=",", min_length=1, max_length=1)
    csv_bom: bool = True
    keep_raw_responses: bool = False
    timezone: str = "Europe/Zurich"


class Acknowledgements(_Strict):
    """Confirmations given by the user (e.g. data transfer notice)."""

    data_transfer: bool = False


class ImportSettings(_Strict):
    """Settings for repeatable imports (plan chapter 25.5).

    ``mappings`` assigns table columns to internal columns per source file name, for example
    ``{"export.csv": {"abstract": "Zusammenfassung"}}``. It is used when the file is imported again
    and no ``--map`` option is given; an option on the command line always wins.
    """

    mappings: dict[str, dict[str, str]] = Field(default_factory=dict)


class ProjectConfig(_Strict):
    """Complete content of ``project.yaml``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    schema_version: Literal[1] = Field(default=1, alias="schema")
    project: ProjectInfo
    objectives: list[str] = Field(default_factory=list)
    criteria: Criteria
    dedup: Dedup = Field(default_factory=Dedup)
    prefilters: Prefilters = Field(default_factory=Prefilters)
    screening: ScreeningOptions = Field(default_factory=ScreeningOptions)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    limits: Limits = Field(default_factory=Limits)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    preflight: PreflightSettings = Field(default_factory=PreflightSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    acknowledgements: Acknowledgements = Field(default_factory=Acknowledgements)
    # "import" is a Python keyword, hence the alias; the YAML key is `import:`.
    import_settings: ImportSettings = Field(default_factory=ImportSettings, alias="import")
