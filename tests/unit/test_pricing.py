"""Tests for the price sources (task T-M2-05)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from crapai.cost.pricing import CsvPriceSource, Price, StaticPriceSource, parse_number
from crapai.errors import ConfigError

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "pricing.example.csv"
HEADER = "provider,model,price_input_per_1k,price_output_per_1k,currency,valid_from,source\n"


def write(tmp_path: Path, body: str, header: str = HEADER) -> Path:
    path = tmp_path / "pricing.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "text,expected",
    [("0.0006", 0.0006), ("0,0006", 0.0006), (" 2 ", 2.0), ("0", 0.0)],
)
def test_parse_number_accepts_point_and_comma(text: str, expected: float) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", [None, "", "abc", "-1", "nan", "1.2.3"])
def test_parse_number_rejects_invalid(text: str | None) -> None:
    assert parse_number(text) is None


def test_static_source_returns_the_same_price() -> None:
    price = Price(0.5, 1.5, "CHF")
    assert StaticPriceSource(price).get_price("any", "model") == price


def test_csv_lookup_ignores_case_and_keeps_all_columns(tmp_path: Path) -> None:
    path = write(tmp_path, 'OpenAI,GPT-4o-Mini,"0,00015",0.0006,usd,2026-09-30,provider page\n')
    source = CsvPriceSource(path)
    price = source.get_price(" openai ", "gpt-4o-mini")
    assert price == Price(0.00015, 0.0006, "USD", "2026-09-30", "provider page")
    assert len(source) == 1
    assert source.get_price("openai", "other") is None


def test_optional_columns_may_be_missing(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "openai,m,1,2\n",
        header="provider,model,price_input_per_1k,price_output_per_1k\n",
    )
    assert CsvPriceSource(path).get_price("openai", "m") == Price(1.0, 2.0, "USD", "", "")


def test_first_row_wins_and_bad_rows_are_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    body = "a,m,1,2,USD,,\na,m,9,9,USD,,\na,bad,x,2,USD,,\n,nomodel,1,1,USD,,\na,neg,-1,1,USD,,\n"
    with caplog.at_level(logging.WARNING):
        source = CsvPriceSource(write(tmp_path, body))
    assert len(source) == 1 and source.get_price("a", "m").input_per_1k == 1.0  # type: ignore[union-attr]
    assert sum("skipped" in r.message for r in caplog.records) == 3


def test_bom_and_empty_currency_default(tmp_path: Path) -> None:
    path = tmp_path / "pricing.csv"
    path.write_text("﻿" + HEADER + "a,m,1,2,,,\n", encoding="utf-8")
    assert CsvPriceSource(path).get_price("a", "m").currency == "USD"  # type: ignore[union-attr]


def test_missing_columns_give_e203(tmp_path: Path) -> None:
    path = write(tmp_path, "a,m,1\n", header="provider,model,price_input_per_1k\n")
    with pytest.raises(ConfigError) as info:
        CsvPriceSource(path)
    assert info.value.code == "E203"
    assert info.value.details["missing"] == ["price_output_per_1k"]


def test_unreadable_files_give_e203(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as missing:
        CsvPriceSource(tmp_path / "nothing.csv")
    assert missing.value.code == "E203"
    binary = tmp_path / "b.csv"
    binary.write_bytes(b"\xff\xfe\x00\x80\x81")
    with pytest.raises(ConfigError):
        CsvPriceSource(binary)


def test_header_only_file_is_an_empty_list(tmp_path: Path) -> None:
    source = CsvPriceSource(write(tmp_path, ""))
    assert len(source) == 0 and source.get_price("a", "m") is None


def test_the_shipped_example_file_is_readable() -> None:
    source = CsvPriceSource(TEMPLATE)
    price = source.get_price("openai", "gpt-4o-mini")
    assert price is not None and price.valid_from == "2026-09-30"
    assert "ILLUSTRATIVE" in price.source
