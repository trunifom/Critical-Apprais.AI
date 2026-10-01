"""The settings the interface lets you change, and how edited values become overrides.

Nothing here draws or imports Streamlit. The form is *data*: a list of sections, each with fields
(dotted setting name, kind, limits). The Settings page turns it into widgets; tests and the command
line can use the same list. Adding a setting to the form is one line here plus its two texts
(``ui.setting.<key>``) in the text files.

Edited values are compared with the values in force; only **differences** are written, to the
overrides file (:mod:`crapai.config.overrides`), so ``project.yaml`` and its comments stay as they
are and "reset" is always possible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

FieldKind = str  # "int", "float", "bool", "choice", "text", "list", "optional_float"


@dataclass(frozen=True)
class Field:
    """One editable setting.

    Attributes:
        key: Dotted name in the configuration, for example ``quality.short_abstract_words``.
        kind: ``int``, ``float``, ``bool``, ``choice``, ``text``, ``list`` (comma separated) or
            ``optional_float`` (empty = off).
        choices: The allowed values of a ``choice``.
        minimum: Lowest allowed number (``int``/``float``/``optional_float``).
        maximum: Highest allowed number.
        step: Step of the number widget.
    """

    key: str
    kind: FieldKind
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


@dataclass(frozen=True)
class Section:
    """A group of fields under one heading (``ui.section.<name>``)."""

    name: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


SECTIONS: tuple[Section, ...] = (
    Section(
        "dedup",
        (
            Field(
                "dedup.strategy", "choice", ("doi_or_title", "strict_ids", "title", "title_authors")
            ),
            Field("dedup.min_title_words", "int", minimum=1, maximum=20),
            Field("dedup.fuzzy.enabled", "bool"),
            Field("dedup.fuzzy.threshold", "float", minimum=0.5, maximum=1.0, step=0.01),
            Field("dedup.fuzzy.max_year_difference", "int", minimum=0, maximum=50),
            Field("dedup.fuzzy.require_author_agreement", "bool"),
            Field(
                "dedup.reporting_mode", "choice", ("all_before_screening", "between_databases_only")
            ),
        ),
    ),
    Section(
        "prefilters",
        (
            Field("prefilters.language.allow", "list"),
            Field("prefilters.exclude_retracted", "bool"),
            Field("prefilters.keywords.include_any", "list"),
            Field("prefilters.keywords.exclude_any", "list"),
        ),
    ),
    Section(
        "quality",
        (
            Field("quality.short_abstract_words", "int", minimum=1, maximum=2000),
            Field("quality.long_word_letters", "int", minimum=5, maximum=500),
            Field(
                "quality.garbled_mean_word_letters", "float", minimum=3.0, maximum=50.0, step=0.5
            ),
            Field("quality.min_words_for_mean", "int", minimum=1, maximum=1000),
            Field("quality.short_abstract_chars_unspaced", "int", minimum=1, maximum=5000),
            Field("preflight.min_abstract_ratio", "float", minimum=0.0, maximum=1.0, step=0.05),
        ),
    ),
    Section(
        "screening",
        (
            Field("screening.include_title_only", "bool"),
            Field("screening.include_keywords_in_prompt", "bool"),
            Field("screening.uncertain_policy", "choice", ("include", "exclude", "keep_separate")),
            Field("screening.decision_source", "choice", ("model", "rule")),
            Field("screening.reasoning_language", "choice", ("en", "de")),
        ),
    ),
    Section(
        "discussion",
        (
            Field("discussion.max_rounds", "int", minimum=1, maximum=20),
            Field("discussion.tie_break", "choice", ("majority", "no_consensus")),
        ),
    ),
    Section(
        "llm",
        (
            Field("llm.provider", "choice", ("openai", "anthropic", "openai_compatible", "mock")),
            Field("llm.model", "text"),
            Field("llm.base_url", "text"),
            Field("llm.api_key_env", "text"),
            Field("llm.temperature", "float", minimum=0.0, maximum=2.0, step=0.1),
            Field("llm.context_tokens", "optional_int", minimum=256),
            Field("llm.max_output_tokens", "int", minimum=16, maximum=100_000),
            Field("llm.expected_output_tokens", "int", minimum=1, maximum=100_000),
            Field("llm.timeout_s", "float", minimum=1.0, maximum=3600.0, step=5.0),
        ),
    ),
    Section(
        "run",
        (
            Field("run.batch_size", "int", minimum=1, maximum=1_000_000),
            Field("run.max_batch_error_rate", "float", minimum=0.0, maximum=1.0, step=0.05),
            Field("run.max_consecutive_errors", "int", minimum=0, maximum=100_000),
            Field("run.retry_failed_on_resume", "bool"),
            Field("run.checkpoint_seconds", "float", minimum=0.1, maximum=600.0, step=0.5),
            Field("run.stop_grace_seconds", "float", minimum=0.0, maximum=600.0, step=1.0),
            Field("run.sample_seed", "int", minimum=0, maximum=2_000_000_000),
            Field("run.retry_base_delay_s", "float", minimum=0.0, maximum=600.0, step=0.5),
            Field("run.retry_max_delay_s", "float", minimum=0.0, maximum=3600.0, step=1.0),
            Field("run.max_retry_time_s", "float", minimum=0.0, maximum=86_400.0, step=10.0),
        ),
    ),
    Section(
        "limits",
        (
            Field("limits.max_concurrency", "int", minimum=1, maximum=200),
            Field("limits.rpm", "int", minimum=1, maximum=1_000_000),
            Field("limits.tpm", "int", minimum=1, maximum=100_000_000),
            Field("limits.max_retries", "int", minimum=0, maximum=50),
            Field("limits.max_parse_retries", "int", minimum=0, maximum=10),
            Field("limits.max_cost", "optional_float", minimum=0.0),
            Field("limits.currency", "text"),
            Field("limits.seconds_per_request", "float", minimum=0.1, maximum=600.0, step=0.5),
            Field("limits.cost_uncertainty", "float", minimum=0.0, maximum=1.0, step=0.05),
        ),
    ),
)

ALL_FIELDS: dict[str, Field] = {f.key: f for section in SECTIONS for f in section.fields}


def parse_value(form_field: Field, raw: Any) -> Any:
    """Turn what a widget returned into the value to store.

    Raises:
        ValueError: if a text cannot be read as the kind's type (nothing is saved then).
    """
    kind = form_field.kind
    if kind == "list":
        if isinstance(raw, list):
            return raw
        return [part.strip() for part in str(raw).split(",") if part.strip()]
    if kind == "optional_int":
        text = "" if raw is None else str(raw).strip()
        return int(text) if text else None
    if kind == "optional_float":
        text = "" if raw is None else str(raw).strip()
        return float(text.replace(",", ".")) if text else None
    if kind == "text":
        text = "" if raw is None else str(raw).strip()
        return text or None if form_field.key in ("llm.base_url",) else text
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return bool(raw)
    return raw


def changes(current: Mapping[str, Any], edited: Mapping[str, Any]) -> dict[str, Any]:
    """The fields whose edited value differs from the value in force.

    Args:
        current: Dotted key to the effective value (from ``effective_settings``).
        edited: Dotted key to the raw widget value; keys that are not in the form are ignored.

    Raises:
        ValueError: naming the key, if a value cannot be parsed.
    """
    result: dict[str, Any] = {}
    for key, raw in edited.items():
        form_field = ALL_FIELDS.get(key)
        if form_field is None:
            continue
        try:
            value = parse_value(form_field, raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(key) from exc
        unset_and_empty = key not in current and value in (None, [], "")
        if value != current.get(key) and not unset_and_empty:
            result[key] = value
    return result
