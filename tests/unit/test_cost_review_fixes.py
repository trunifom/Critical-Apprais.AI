"""Regression tests for defects found in the review of the cost and configuration code."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pytest

from crapai.config.loader import resolve_config
from crapai.cost.estimator import EstimatorConfig, estimate_run
from crapai.cost.pricing import CsvPriceSource, Price, parse_number
from crapai.cost.tokenizers import CharTokenizer
from crapai.errors import ConfigError
from crapai.services.preflight import check_file

HEADER = "provider,model,price_input_per_1k,price_output_per_1k,currency,valid_from,source\n"
TODAY = dt.date(2026, 10, 1)


def write(tmp_path: Path, body: str, header: str = HEADER) -> Path:
    path = tmp_path / "pricing.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


@pytest.mark.parametrize("text", ["inf", "-inf", "1e400", "Infinity", "nan"])
def test_infinite_prices_are_rejected(text: str) -> None:
    assert parse_number(text) is None


def test_a_semicolon_file_from_excel_is_read(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "openai;gpt-4o-mini;0,00015;0,0006;usd;2026-09-30;x\n",
        header=HEADER.replace(",", ";"),
    )
    assert CsvPriceSource(path).get_price("openai", "gpt-4o-mini") == Price(
        0.00015, 0.0006, "USD", "2026-09-30", "x"
    )


def test_the_latest_price_in_force_wins_whatever_the_row_order(tmp_path: Path) -> None:
    body = "a,m,2,4,USD,2026-06-01,new\na,m,1,2,USD,2025-01-01,old\na,m,9,9,USD,2027-01-01,future\n"
    source = CsvPriceSource(write(tmp_path, body), today=TODAY)
    assert source.get_price("a", "m").source == "new"  # type: ignore[union-attr]


def test_a_row_without_a_date_is_the_oldest_and_the_first_wins_on_a_tie(tmp_path: Path) -> None:
    body = (
        "a,m,1,1,USD,,first\na,m,2,2,USD,,second\n"
        "a,n,5,5,USD,2026-01-01,dated\na,n,6,6,USD,,undated\n"
    )
    source = CsvPriceSource(write(tmp_path, body), today=TODAY)
    assert source.get_price("a", "m").source == "first"  # type: ignore[union-attr]
    assert source.get_price("a", "n").source == "dated"  # type: ignore[union-attr]


def test_only_a_future_price_falls_back_to_it_rather_than_to_nothing(tmp_path: Path) -> None:
    source = CsvPriceSource(write(tmp_path, "a,m,9,9,USD,2030-01-01,later\n"), today=TODAY)
    assert source.get_price("a", "m") is not None  # better than no price at all


def test_a_cost_band_above_100_percent_never_makes_a_negative_low_end() -> None:
    estimate = estimate_run(
        [("t", "a")], "s", CharTokenizer(1), price=Price(1, 1),
        config=EstimatorConfig(cost_uncertainty=1.5),
    )  # fmt: skip
    assert estimate.cost_low == 0.0 and estimate.cost_high == pytest.approx(
        2 * (estimate.cost or 0)
    )


def test_east_asian_text_is_counted_per_character() -> None:
    tokenizer = CharTokenizer()
    chinese = "这是一个关于临床试验的摘要" * 20  # 13 characters, repeated
    assert tokenizer.count(chinese) == len(chinese) == 260
    assert tokenizer.count("a" * 240) == 60  # Latin text: 4 characters per token
    assert tokenizer.count("日本語のabstract") == 4 + 2


def test_the_layers_behind_a_configuration_error_are_named(tmp_path: Path) -> None:
    project = tmp_path / "project.yaml"
    project.write_text("project:\n  title: T\ncriteria:\n  inclusion: {a: b}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as plain:
        resolve_config(
            project,
            environ={"CRAPAI_LLM__PROVIDER": "nonsense"},
            user_config_path=tmp_path / "none.yaml",
        )
    assert "merged with: environment variables" in plain.value.user_message
    assert "project.yaml" in plain.value.user_message
    with pytest.raises(ConfigError) as cli:
        resolve_config(
            project,
            cli={"llm": {"temperature": 99}},
            environ={},
            user_config_path=tmp_path / "none.yaml",
        )
    assert "merged with: command line" in cli.value.user_message


def test_a_bad_project_yaml_alone_is_not_blamed_on_other_layers(tmp_path: Path) -> None:
    project = tmp_path / "project.yaml"
    project.write_text(
        "project:\n  title: T\nllm:\n  temperature: 99\ncriteria:\n  inclusion: {a: b}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as info:
        resolve_config(project, environ={}, user_config_path=tmp_path / "none.yaml")
    assert "merged with" not in info.value.user_message


def test_a_failed_file_preflight_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = tmp_path / "x.ris"
    broken.write_text("not a reference file", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result = check_file(broken, "X")
    assert result.status.value == "error"
    assert "Preflight of x.ris failed" in caplog.text
