"""The estimate counts the real texts of a project, not a sample (task T-M2-05)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crapai.config.loader import load_project_config
from crapai.cost.estimator import format_item
from crapai.cost.tokenizers import CharTokenizer
from crapai.errors import ConfigError
from crapai.project.workspace import Workspace
from crapai.services.cost import criteria_text, estimate_project, shared_text_of
from crapai.services.importing import ImportRequest, import_source
from crapai.services.project import create_project

ANTHROPIC = {"provider": "anthropic", "model": "claude-sonnet-5-5", "base_url": None}
SHORT = "A short abstract. " * 5
LONG = "A much longer abstract about the trial and its outcomes. " * 40
PRICES = (
    "provider,model,price_input_per_1k,price_output_per_1k,currency,valid_from,source\n"
    "{provider},{model},0.5,1.5,CHF,2026-09-30,test\n"
)


def ris(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    parts = []
    for index, (title, abstract) in enumerate(rows):
        lines = ["TY  - JOUR", f"TI  - {title}", f"DO  - 10.1/e{index}"]
        if abstract:
            lines.append(f"AB  - {abstract}")
        parts.append("\n".join([*lines, "ER  - "]))
    path = tmp_path / "e.ris"
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def set_config(project: Workspace, **sections: dict[str, object]) -> None:
    data = yaml.safe_load(project.project_yaml.read_text(encoding="utf-8"))
    for name, values in sections.items():
        data.setdefault(name, {}).update(values)
    project.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Workspace:
    workspace = create_project(tmp_path / "p", template="demo")
    set_config(workspace, llm=ANTHROPIC)
    return workspace


def load(project: Workspace, tmp_path: Path, rows: list[tuple[str, str]]) -> None:
    import_source(project, ImportRequest(ris(tmp_path, rows), label="E"))


def test_every_record_is_counted_with_its_own_length(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", SHORT), ("Two", LONG)])
    result = estimate_project(project)
    tok = CharTokenizer(safety_factor=1.10)  # the character counter used for Anthropic
    expected = tok.count(format_item("One", SHORT.strip())) + tok.count(
        format_item("Two", LONG.strip())
    )
    assert result.estimate.n_items == 2
    assert result.estimate.item_tokens == expected
    assert result.estimate.tokenizer == "chars" and result.estimate.exact is False


def test_a_longer_abstract_costs_more_than_a_fixed_guess_would(
    project: Workspace, tmp_path: Path
) -> None:
    load(project, tmp_path, [("Short", SHORT)])
    short = estimate_project(project).estimate.item_tokens
    other = create_project(tmp_path / "q", template="demo")
    set_config(other, llm=ANTHROPIC)
    import_source(other, ImportRequest(ris(tmp_path, [("Short", LONG)]), label="E"))
    assert estimate_project(other).estimate.item_tokens > 5 * short  # no fixed per-record guess


def test_only_records_that_go_to_the_model_are_counted(project: Workspace, tmp_path: Path) -> None:
    from crapai.services.dedup import dedup_project
    from crapai.services.validity import validate_project

    load(project, tmp_path, [("Same", SHORT), ("Same", SHORT), ("No abstract", "")])
    dedup_project(project)
    validate_project(project)
    assert estimate_project(project).estimate.n_items == 1


def test_no_price_file_means_tokens_only(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", SHORT)])
    result = estimate_project(project)
    assert result.price_file_found is False
    assert result.estimate.cost is None and result.over_limit is False


def test_unknown_model_in_the_price_file_means_tokens_only(
    project: Workspace, tmp_path: Path
) -> None:
    load(project, tmp_path, [("One", SHORT)])
    project.pricing_csv.write_text(PRICES.format(provider="openai", model="x"), encoding="utf-8")
    result = estimate_project(project)
    assert result.price_file_found is True and result.estimate.cost is None


def test_price_from_the_project_file_gives_a_cost(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", SHORT), ("Two", LONG)])
    project.pricing_csv.write_text(
        PRICES.format(provider="anthropic", model="claude-sonnet-5-5"), encoding="utf-8"
    )
    result = estimate_project(project)
    est = result.estimate
    assert est.currency == "CHF" and est.price is not None and est.price.valid_from == "2026-09-30"
    assert est.cost == pytest.approx(est.input_tokens / 1000 * 0.5 + est.output_tokens / 1000 * 1.5)
    assert est.cost_low < est.cost < est.cost_high <= est.cost_max  # type: ignore[operator]


def test_max_cost_is_compared_with_the_worst_case(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", LONG)] * 1)
    project.pricing_csv.write_text(
        PRICES.format(provider="anthropic", model="claude-sonnet-5-5"), encoding="utf-8"
    )
    set_config(project, limits={"max_cost": 0.0001})
    tight = estimate_project(project)
    assert tight.over_limit is True and tight.max_cost == 0.0001
    set_config(project, limits={"max_cost": 100})
    assert estimate_project(project).over_limit is False
    set_config(project, limits={"max_cost": None})
    assert estimate_project(project).over_limit is False


def test_max_output_tokens_of_the_project_drive_the_worst_case(
    project: Workspace, tmp_path: Path
) -> None:
    load(project, tmp_path, [("One", SHORT)])
    project.pricing_csv.write_text(
        PRICES.format(provider="anthropic", model="claude-sonnet-5-5"), encoding="utf-8"
    )
    set_config(project, llm={"max_output_tokens": 2000})
    est = estimate_project(project).estimate
    assert est.cost_max == pytest.approx(est.input_tokens / 1000 * 0.5 + 2 * 1.5)


def test_a_broken_price_file_raises_e203(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", SHORT)])
    project.pricing_csv.write_text("provider,model\nx,y\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        estimate_project(project)
    assert info.value.code == "E203"


def test_estimate_writes_nothing(project: Workspace, tmp_path: Path) -> None:
    load(project, tmp_path, [("One", SHORT)])
    before = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    estimate_project(project)
    after = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    assert before == after


def test_shared_text_contains_criteria_and_objectives(project: Workspace) -> None:
    config = load_project_config(project.project_yaml)
    text = shared_text_of(config, "Decide.")
    assert text.startswith("Decide.")
    assert f"Project: {config.project.title}" in text
    assert criteria_text(config) in text and criteria_text(config)
