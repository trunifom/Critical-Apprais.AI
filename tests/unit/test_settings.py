"""Nothing is hard-coded: thresholds and assumptions are settings, changeable without editing code.

Covers the new ``quality``, ``preflight`` and ``limits`` settings, the overrides file
(``project.overrides.yaml``), its layering, the source report and ``crapai config``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from crapai.cli import app
from crapai.config import overrides as ov
from crapai.config.loader import load_project_config, resolve_config
from crapai.config.models import QualitySettings
from crapai.errors import ConfigError
from crapai.prisma.validity import QualityThresholds, classify_abstract
from crapai.project.workspace import Workspace
from crapai.services.cost import estimate_project
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import check_project
from crapai.services.project import create_project
from crapai.services.validity import validate_project

runner = CliRunner()
ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    return create_project(tmp_path / "p", template="demo")


def load(project: Workspace, tmp_path: Path, abstract: str = ABSTRACT, count: int = 3) -> None:
    rows = "\n".join(
        f"TY  - JOUR\nTI  - Study number {i} about one topic\nDO  - 10.1000/s{i}\n"
        f"AB  - {abstract}\nER  - "
        for i in range(count)
    )
    source = tmp_path / "s.ris"
    source.write_text(rows + "\n", encoding="utf-8")
    import_source(project, ImportRequest(source, label="S"))


# --- defaults and validation ----------------------------------------------------------------------


def test_the_defaults_are_the_agreed_values() -> None:
    quality = QualitySettings()
    assert (quality.long_word_letters, quality.short_abstract_words) == (40, 40)
    assert QualityThresholds() == QualityThresholds(**quality.model_dump())


INVALID_BLOCKS = [
    {"quality": {"short_abstract_words": 0}},
    {"quality": {"typo": 1}},
    {"preflight": {"min_abstract_ratio": 1.5}},
    {"limits": {"cost_uncertainty": -0.1}},
    {"limits": {"seconds_per_request": 0}},
    {"dedup": {"fuzzy": {"max_year_difference": -1}}},
]


@pytest.mark.parametrize("block", INVALID_BLOCKS)
def test_invalid_values_are_refused_with_the_path(
    project: Workspace, block: dict[str, object]
) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    data.update(block)
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_project_config(project.project_yaml)
    assert info.value.code == "E203"


# --- thresholds reach the code ----------------------------------------------------------------


def test_quality_thresholds_are_parameters_of_the_classifier() -> None:
    text = "word " * 35
    assert classify_abstract(text) == "short"
    assert classify_abstract(text, QualityThresholds(short_abstract_words=30)) == "ok"
    glued = "x" * 50
    assert classify_abstract(f"{text} {glued}") == "suspect_concat"
    assert classify_abstract(f"{text} {glued}", QualityThresholds(long_word_letters=60)) == "short"
    cjk = "本研究调查了疗效" * 10  # 80 characters
    assert classify_abstract(cjk) == "short"
    assert classify_abstract(cjk, QualityThresholds(short_abstract_chars_unspaced=60)) == "ok"


def test_the_validity_service_uses_the_project_thresholds(
    project: Workspace, tmp_path: Path
) -> None:
    load(project, tmp_path, abstract="word " * 30)
    assert validate_project(project).quality == {"short": 3}
    ov.set_values(project.project_yaml, {"quality.short_abstract_words": 25})
    assert validate_project(project).quality == {"ok": 3}


def test_the_preflight_uses_the_ratio_of_the_project(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, count=2)
    rows = "TY  - JOUR\nTI  - Study without an abstract at all\nDO  - 10.1000/n1\nER  - \n"
    extra = tmp_path / "n.ris"
    extra.write_text(rows, encoding="utf-8")
    import_source(project, ImportRequest(extra, label="S"))  # 2 of 3 records have an abstract: 67 %
    assert not check_project(project).sources[0].issues
    ov.set_values(project.project_yaml, {"preflight.min_abstract_ratio": 0.9})
    assert [i.value for i in check_project(project).sources[0].issues] == ["low_abstract_ratio"]


def test_the_estimate_uses_the_assumptions_of_the_project(
    project: Workspace, tmp_path: Path
) -> None:
    load(project, tmp_path, count=4)
    base = estimate_project(project)
    ov.set_values(
        project.project_yaml,
        {
            "limits.seconds_per_request": 30.0,
            "llm.expected_output_tokens": 500,
            "limits.max_concurrency": 1,
        },
    )
    changed = estimate_project(project)
    assert changed.duration.seconds > base.duration.seconds * 10
    assert changed.estimate.output_tokens == 4 * 500


# --- the overrides file -------------------------------------------------------------------------


def test_set_values_writes_a_validated_file_and_keeps_project_yaml(project: Workspace) -> None:
    before = project.project_yaml.read_bytes()
    result = ov.set_values(project.project_yaml, {"llm.temperature": 0.3, "limits.rpm": 120})
    assert result == {"llm": {"temperature": 0.3}, "limits": {"rpm": 120}}
    assert project.project_yaml.read_bytes() == before  # comments stay
    text = (project.root / ov.OVERRIDES_NAME).read_text(encoding="utf-8")
    assert text.startswith("# Settings changed") and "rpm: 120" in text
    config = load_project_config(project.project_yaml)
    assert config.llm.temperature == 0.3 and config.limits.rpm == 120


def test_invalid_values_are_not_written(project: Workspace) -> None:
    with pytest.raises(ConfigError) as info:
        ov.set_values(project.project_yaml, {"limits.rpm": -5})
    assert info.value.code == "E203"
    assert not (project.root / ov.OVERRIDES_NAME).exists()
    with pytest.raises(ConfigError):
        ov.set_values(project.project_yaml, {"nonsense.key": 1})
    for bad in ("", ".", "a..b"):
        with pytest.raises(ConfigError):
            ov.set_values(project.project_yaml, {bad: 1})


def test_a_later_set_keeps_earlier_values_and_reset_removes_them(project: Workspace) -> None:
    ov.set_values(project.project_yaml, {"limits.rpm": 100})
    ov.set_values(project.project_yaml, {"limits.tpm": 5000, "llm.model": "gpt-4o"})
    assert set(ov.flatten(ov.read_overrides(project.project_yaml))) == {
        "limits.rpm",
        "limits.tpm",
        "llm.model",
    }
    assert ov.reset_values(project.project_yaml, ["limits.rpm", "unknown.key"]) == ["limits.rpm"]
    assert "limits.rpm" not in ov.flatten(ov.read_overrides(project.project_yaml))
    everything = ov.reset_values(project.project_yaml)
    assert everything == ["limits.tpm", "llm.model"]
    assert not (project.root / ov.OVERRIDES_NAME).exists()
    assert ov.reset_values(project.project_yaml) == []


def test_the_layers_and_their_precedence(project: Workspace, tmp_path: Path) -> None:
    user = tmp_path / "user.yaml"
    user.write_text("limits: {rpm: 11, tpm: 22, max_concurrency: 3}\n", encoding="utf-8")
    ov.set_values(project.project_yaml, {"limits.tpm": 33})
    env = {"CRAPAI_LIMITS__MAX_CONCURRENCY": "9"}
    config = resolve_config(
        project.project_yaml, cli={"limits": {"rpm": 44}}, environ=env, user_config_path=user
    )
    # cli beats env beats overrides beats project beats user
    assert (config.limits.rpm, config.limits.tpm, config.limits.max_concurrency) == (44, 33, 9)


def test_an_error_in_the_overrides_file_names_the_layer(project: Workspace) -> None:
    (project.root / ov.OVERRIDES_NAME).write_text("limits: {rpm: -1}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_project_config(project.project_yaml)
    assert ov.OVERRIDES_NAME in info.value.user_message


def test_a_broken_overrides_file_is_a_config_error(project: Workspace) -> None:
    (project.root / ov.OVERRIDES_NAME).write_text("limits: [broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        ov.read_overrides(project.project_yaml)


def test_flatten_treats_lists_and_empty_mappings_as_values() -> None:
    flat = ov.flatten({"a": {"b": [1, 2], "c": {}}, "d": 1})
    assert flat == {"a.b": [1, 2], "a.c": {}, "d": 1}


def test_effective_settings_name_the_source(
    project: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    ov.set_values(project.project_yaml, {"limits.rpm": 77})
    monkeypatch.setenv("CRAPAI_LIMITS__TPM", "4321")
    by_key = {s.key: s for s in ov.effective_settings(project.project_yaml)}
    assert (by_key["limits.rpm"].value, by_key["limits.rpm"].source) == (77, "overrides")
    assert (by_key["limits.tpm"].value, by_key["limits.tpm"].source) == (4321, "environment")
    assert by_key["project.language"].source == "project"
    assert by_key["import.mappings"].source == "default"
    assert by_key["quality.short_abstract_words"].value == 40


# --- the command -------------------------------------------------------------------------------


def test_config_set_show_and_reset(project: Workspace) -> None:
    root = str(project.root)
    done = runner.invoke(
        app,
        ["config", "set", root, "quality.short_abstract_words=30", "limits.rpm=90", "--lang", "en"],
    )
    assert done.exit_code == 0 and "Set limits.rpm = 90" in done.output
    shown = runner.invoke(app, ["config", "show", root, "--changed", "--lang", "en"])
    assert "quality.short_abstract_words = 30   [changed here]" in shown.output
    as_json = json.loads(CliRunner().invoke(app, ["config", "show", root, "--json"]).stdout)
    assert {"key": "limits.rpm", "value": 90, "source": "overrides"} in as_json
    back = runner.invoke(app, ["config", "reset", root, "limits.rpm", "--lang", "en"])
    assert back.exit_code == 0 and "1 setting(s) reset" in back.output
    assert "limits.rpm" not in runner.invoke(app, ["config", "show", root, "--changed"]).output
    nothing = runner.invoke(app, ["config", "reset", root, "--lang", "en"])
    assert "quality.short_abstract_words" not in nothing.output
    again = runner.invoke(app, ["config", "reset", root, "--lang", "de"])
    assert "Nichts zurückzusetzen" in again.output


@pytest.mark.parametrize(
    "assignment,code",
    [("nonsense", "E203"), ("limits.rpm=-3", "E203"), ("limits.unknown=1", "E203"), ("=5", "E203")],
)
def test_config_set_rejects_bad_input(project: Workspace, assignment: str, code: str) -> None:
    result = runner.invoke(app, ["config", "set", str(project.root), assignment, "--lang", "en"])
    assert result.exit_code == 1 and code in result.output
    assert not (project.root / ov.OVERRIDES_NAME).exists()


def test_config_on_a_folder_that_is_no_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "show", str(tmp_path / "nothing"), "--lang", "en"])
    assert result.exit_code == 1 and "E404" in result.output


def test_config_set_is_refused_while_the_project_is_in_use(project: Workspace) -> None:
    holder = project.lock()
    holder.acquire()
    try:
        result = runner.invoke(
            app, ["config", "set", str(project.root), "limits.rpm=50", "--lang", "en"]
        )
        assert result.exit_code == 2 and "E402" in result.output
    finally:
        holder.release()
