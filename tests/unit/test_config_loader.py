"""Tests for the project.yaml loader (task T-M1-02): precise errors and merging."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crapai.config.loader import (
    deep_merge,
    env_overrides,
    load_project_config,
    parse_cli_overrides,
    read_yaml_mapping,
    resolve_config,
    validate_config,
)
from crapai.errors import ConfigError

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "project.example.yaml"


def write(tmp_path: Path, text: str, name: str = "project.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_template_loads() -> None:
    config = load_project_config(TEMPLATE)
    assert config.project.language == "de"
    assert config.llm.base_url == "https://api.prod.alpineai.ch/v1"


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_project_config(tmp_path / "nope.yaml")
    assert info.value.code == "E203"
    assert "not found" in info.value.user_message


def test_broken_yaml_reports_line(tmp_path: Path) -> None:
    path = write(tmp_path, "project:\n  title: [unclosed\n")
    with pytest.raises(ConfigError) as info:
        read_yaml_mapping(path)
    assert "invalid YAML" in info.value.user_message
    assert info.value.details["line"] is not None


def test_non_utf8_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_bytes("project:\n  title: Größe\n".encode("cp1252"))
    with pytest.raises(ConfigError) as info:
        read_yaml_mapping(path)
    assert "UTF-8" in (info.value.hint or "")


def test_empty_file_and_non_mapping(tmp_path: Path) -> None:
    assert read_yaml_mapping(write(tmp_path, "")) == {}
    with pytest.raises(ConfigError):
        read_yaml_mapping(write(tmp_path, "- a\n- b\n", "list.yaml"))


def test_missing_required_field_is_e201_and_names_the_path(tmp_path: Path) -> None:
    path = write(tmp_path, "schema: 1\nproject:\n  title: T\n")
    with pytest.raises(ConfigError) as info:
        load_project_config(path)
    err = info.value
    assert err.code == "E201"
    assert "criteria: required field is missing" in err.user_message
    assert err.details["problems"][0]["path"] == "criteria"


def test_invalid_value_is_e203_with_yaml_path_and_reason() -> None:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data["limits"]["rpm"] = 0
    with pytest.raises(ConfigError) as info:
        validate_config(data)
    err = info.value
    assert err.code == "E203"
    assert "limits.rpm" in err.user_message
    assert "greater than 0" in err.user_message


def test_unknown_key_message_suggests_checking_spelling() -> None:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data["llm"]["temprature"] = 1
    with pytest.raises(ConfigError) as info:
        validate_config(data)
    assert "llm.temprature: unknown setting" in info.value.user_message


def test_all_problems_are_listed_at_once() -> None:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data["limits"]["rpm"] = -1
    data["llm"]["top_p"] = 5
    with pytest.raises(ConfigError) as info:
        validate_config(data)
    paths = {p["path"] for p in info.value.details["problems"]}
    assert paths == {"limits.rpm", "llm.top_p"}
    assert "2 problem(s)" in info.value.user_message


def test_error_text_never_contains_a_pasted_secret() -> None:
    secret = "sk-live-0123456789abcdefSECRET"
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data["llm"]["api_key_env"] = secret
    with pytest.raises(ConfigError) as info:
        validate_config(data)
    assert "llm.api_key_env" in info.value.user_message
    assert secret not in str(info.value)
    assert secret not in repr(info.value.details)


def test_deep_merge_recurses_into_mappings_and_replaces_lists() -> None:
    base = {"llm": {"model": "a", "seed": 1}, "objectives": ["x"], "limits": {"rpm": 1}}
    override = {"llm": {"model": "b"}, "objectives": ["y", "z"], "limits": {"rpm": None}}
    merged = deep_merge(base, override)
    assert merged == {
        "llm": {"model": "b", "seed": 1},
        "objectives": ["y", "z"],
        "limits": {"rpm": None},
    }
    assert base["llm"] == {"model": "a", "seed": 1}  # inputs are not mutated


# --- precedence: CLI > env > project.yaml > user config > defaults (plan chapter 16.3) ---

NO_USER = Path("does-not-exist.yaml")


def project_file(tmp_path: Path, **llm: object) -> Path:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data["llm"].update(llm)
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_env_overrides_parse_nested_names_and_types() -> None:
    env = {
        "CRAPAI_LLM__MODEL": "gpt-4o",
        "CRAPAI_LIMITS__RPM": "120",
        "CRAPAI_OUTPUT__CSV_BOM": "false",
        "CRAPAI_LIMITS__MAX_COST": "null",
        "CRAPAI_UNRELATED": "x",  # no nesting separator: ignored
        "CRAPAI_LLM__": "x",  # empty key: ignored
        "OTHER__THING": "x",
    }
    assert env_overrides(env) == {
        "llm": {"model": "gpt-4o"},
        "limits": {"rpm": 120, "max_cost": None},
        "output": {"csv_bom": False},
    }


def test_cli_overrides_parse_and_reject_malformed() -> None:
    assert parse_cli_overrides(["llm.model=gpt-4o", "limits.rpm=100", "llm.seed=null"]) == {
        "llm": {"model": "gpt-4o", "seed": None},
        "limits": {"rpm": 100},
    }
    for bad in ("llm.model", "=x", ".x=1", "a..b=1"):
        with pytest.raises(ConfigError):
            parse_cli_overrides([bad])


def test_precedence_cli_over_env_over_project_over_user_over_default(tmp_path: Path) -> None:
    user = tmp_path / "user.yaml"
    user.write_text(
        yaml.safe_dump(
            {"limits": {"rpm": 1, "tpm": 1000, "max_retries": 9}, "llm": {"timeout_s": 5}}
        ),
        encoding="utf-8",
    )
    path = project_file(tmp_path, timeout_s=30)  # template sets rpm=500, tpm=200000 too
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["limits"]["tpm"]  # let the user layer win for tpm
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    config = resolve_config(
        path,
        cli={"limits": {"rpm": 7}},
        environ={"CRAPAI_LIMITS__RPM": "50", "CRAPAI_LIMITS__MAX_CONCURRENCY": "3"},
        user_config_path=user,
    )
    assert config.limits.rpm == 7  # CLI beats env (50), project (500), user (1)
    assert config.limits.max_concurrency == 3  # env beats project (5)
    assert config.llm.timeout_s == 30  # project beats user (5)
    assert config.limits.tpm == 1000  # user beats default (200000)
    assert config.limits.max_retries == 5  # project (template) beats user (9)
    assert config.output.csv_bom is True  # built-in default


def test_missing_user_config_is_fine_and_invalid_override_is_reported(tmp_path: Path) -> None:
    path = project_file(tmp_path)
    assert resolve_config(path, environ={}, user_config_path=NO_USER).limits.rpm == 500
    with pytest.raises(ConfigError) as info:
        resolve_config(path, environ={"CRAPAI_LIMITS__RPM": "-3"}, user_config_path=NO_USER)
    assert "limits.rpm" in info.value.user_message


def test_api_key_cannot_be_injected_through_env_or_cli(tmp_path: Path) -> None:
    path = project_file(tmp_path)
    for kwargs in (
        {"environ": {"CRAPAI_LLM__API_KEY": "sk-secret-value"}},
        {"cli": parse_cli_overrides(["llm.api_key=sk-secret-value"]), "environ": {}},
    ):
        with pytest.raises(ConfigError) as info:
            resolve_config(path, user_config_path=NO_USER, **kwargs)  # type: ignore[arg-type]
        assert "llm.api_key: unknown setting" in info.value.user_message
        assert "sk-secret-value" not in str(info.value)
