"""Tests for the project.yaml models (task T-M1-02, plan chapter 16)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from crapai.config.models import ProjectConfig

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "project.example.yaml"


def example() -> dict[str, Any]:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def error_locs(exc: ValidationError) -> set[str]:
    return {".".join(str(p) for p in err["loc"]) for err in exc.errors()}


def test_example_template_validates() -> None:
    config = ProjectConfig.model_validate(example())
    assert config.schema_version == 1
    assert config.llm.provider == "openai_compatible"
    assert config.llm.api_key_env == "SWISSGPT_API_KEY"
    assert config.criteria.inclusion["Population"].startswith("Adults")
    assert config.prefilters.language is not None
    assert config.prefilters.language.allow == ["eng", "ger"]
    assert config.prefilters.year is not None
    assert config.prefilters.year.min == 2015


def test_minimal_config_gets_sensitivity_first_defaults() -> None:
    config = ProjectConfig.model_validate(
        {"project": {"title": "T"}, "criteria": {"inclusion": {"Population": "adults"}}}
    )
    assert config.screening.uncertain_policy == "include"
    assert config.limits.max_concurrency == 5
    assert config.dedup.strategy == "doi_or_title"
    assert config.acknowledgements.data_transfer is False


def test_unknown_key_is_rejected() -> None:
    data = example()
    data["llm"]["temprature"] = 0.2  # typo
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert "llm.temprature" in error_locs(info.value)


def test_fulltext_mode_is_accepted() -> None:
    """ADR 0026 lifted ADR 0015's v1 restriction to abstract-only screening."""
    data = example()
    data["project"]["mode"] = "fulltext"
    config = ProjectConfig.model_validate(data)
    assert config.project.mode == "fulltext"
    assert config.screening.fulltext.strategy == "truncate"


def test_an_unknown_mode_is_still_rejected() -> None:
    data = example()
    data["project"]["mode"] = "section"
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_ai_prefilter_is_off_and_well_calibrated_by_default() -> None:
    """ADR 0029: the Jev pre-filter is opt-in; its confidence floor cannot go below the published
    calibration margin (Jev is only well calibrated at confidence >= ~0.9)."""
    config = ProjectConfig.model_validate(
        {"project": {"title": "T"}, "criteria": {"inclusion": {"Population": "adults"}}}
    )
    assert config.ai_prefilter.enabled is False
    assert config.ai_prefilter.confidence_floor == 0.9
    data = example()
    data["ai_prefilter"] = {"confidence_floor": 0.5}
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert "ai_prefilter.confidence_floor" in error_locs(info.value)


@pytest.mark.parametrize("value", ["sk-abc123DEF456ghi789", "my key", "KEY-WITH-DASH", "", "a=b"])
def test_api_key_field_accepts_only_variable_names(value: str) -> None:
    data = example()
    data["llm"]["api_key_env"] = value
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert "llm.api_key_env" in error_locs(info.value)
    # The rejected value (possibly a pasted secret) must not be echoed in the message text.
    assert "NAME of an environment variable" in str(info.value)
    if value:
        assert value not in str(info.value)


def test_no_field_can_hold_an_api_key() -> None:
    """A literal key under any plausible field name fails because unknown keys are forbidden."""
    for name in ("api_key", "key", "token", "secret"):
        data = example()
        data["llm"][name] = "sk-should-never-be-stored"
        with pytest.raises(ValidationError):
            ProjectConfig.model_validate(data)


def test_custom_framework_needs_custom_fields_and_vice_versa() -> None:
    data = example()
    data["criteria"]["framework"] = "CUSTOM"
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)
    data["criteria"]["custom_fields"] = ["Topic"]
    data["criteria"]["inclusion"] = {"Topic": "digital health"}
    data["criteria"]["exclusion"] = {}
    assert ProjectConfig.model_validate(data).criteria.framework == "CUSTOM"

    data = example()
    data["criteria"]["custom_fields"] = ["Topic"]  # PICOS + custom_fields
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_inclusion_criteria_are_required() -> None:
    data = example()
    data["criteria"]["inclusion"] = {"Population": "   ", "Outcome": ""}
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert "at least one inclusion criterion" in str(info.value)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("limits", "rpm", 0),
        ("limits", "max_concurrency", -1),
        ("limits", "max_cost", -0.5),
        ("llm", "temperature", 3),
        ("llm", "top_p", 0),
        ("dedup", "reporting_mode", "sometimes"),
        ("screening", "uncertain_policy", "maybe"),
        ("output", "csv_separator", ",,"),
    ],
)
def test_out_of_range_values_name_their_path(section: str, field: str, value: object) -> None:
    data = example()
    data[section][field] = value
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert f"{section}.{field}" in error_locs(info.value)


def test_null_cost_limit_means_no_limit() -> None:
    data = example()
    data["limits"]["max_cost"] = None
    assert ProjectConfig.model_validate(data).limits.max_cost is None


def test_base_url_rules() -> None:
    data = example()
    data["llm"]["base_url"] = None  # openai_compatible without URL
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)
    data = example()
    data["llm"].update(provider="openai", api_key_env="OPENAI_API_KEY")  # URL with plain openai
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_year_filter_bounds_must_be_ordered() -> None:
    data = example()
    data["prefilters"]["year"] = {"min": 2020, "max": 2010}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_keyword_filter_defaults_are_off() -> None:
    config = ProjectConfig.model_validate(example())
    assert config.prefilters.keywords is None
    assert config.screening.include_keywords_in_prompt is False


def test_keyword_filter_is_validated_like_the_other_filters() -> None:
    data = example()
    data["prefilters"]["keywords"] = {
        "include_any": ["diabetes"],
        "exclude_any": ["animal model"],
        "case_sensitive": True,
        "on_missing": "exclude",
    }
    config = ProjectConfig.model_validate(data)
    assert config.prefilters.keywords is not None
    assert config.prefilters.keywords.include_any == ["diabetes"]
    assert config.prefilters.keywords.on_missing == "exclude"


def test_keyword_filter_rejects_unknown_keys() -> None:
    data = example()
    data["prefilters"]["keywords"] = {"include_any": [], "typo": True}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_schema_version_must_be_1() -> None:
    data = example()
    data["schema"] = 2
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert "schema" in error_locs(info.value)


def test_dump_by_alias_round_trips() -> None:
    config = ProjectConfig.model_validate(example())
    dumped = config.model_dump(by_alias=True)
    assert dumped["schema"] == 1
    assert ProjectConfig.model_validate(dumped) == config


def test_import_mappings_section_is_optional_and_typed() -> None:
    assert ProjectConfig.model_validate(example()).import_settings.mappings == {}
    data = example()
    data["import"] = {"mappings": {"export.csv": {"abstract": "Zusammenfassung"}}}
    config = ProjectConfig.model_validate(data)
    assert config.import_settings.mappings["export.csv"] == {"abstract": "Zusammenfassung"}
    assert config.model_dump(by_alias=True)["import"] == {
        "mappings": {"export.csv": {"abstract": "Zusammenfassung"}}
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"mappings": ["not", "a", "mapping"]},
        {"mappings": {"export.csv": "not a mapping"}},
        {"mappings": {"export.csv": {"abstract": 5}}},
        {"mapping": {}},  # misspelt key
    ],
)
def test_import_mappings_reject_wrong_shapes(bad: dict[str, Any]) -> None:
    data = example()
    data["import"] = bad
    with pytest.raises(ValidationError) as info:
        ProjectConfig.model_validate(data)
    assert any(loc.startswith("import") for loc in error_locs(info.value))
