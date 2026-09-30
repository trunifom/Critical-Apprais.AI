"""Tests for the estimator arithmetic (task T-M2-05)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crapai.cost.estimator import (
    EstimatorConfig,
    build_shared_payload,
    cost_of,
    estimate_run,
    format_item,
)
from crapai.cost.pricing import Price
from crapai.cost.tokenizers import CharTokenizer

ONE_PER_CHAR = CharTokenizer(chars_per_token=1)


def test_tokens_add_up_from_real_texts() -> None:
    items = [("ab", "cde"), ("", "")]
    estimate = estimate_run(items, "x" * 10, ONE_PER_CHAR)
    per_record = [len(format_item(t, a)) for t, a in items]
    assert estimate.n_items == 2 and estimate.shared_tokens == 10
    assert estimate.item_tokens == sum(per_record)
    assert estimate.input_tokens == 2 * 10 + sum(per_record)
    assert estimate.output_tokens == 2 * 120
    assert estimate.total_tokens == estimate.input_tokens + estimate.output_tokens
    assert estimate.per_item_input_tokens == estimate.input_tokens / 2
    assert estimate.tokenizer == "chars" and estimate.exact is False


def test_no_items_is_a_valid_empty_estimate() -> None:
    estimate = estimate_run([], "shared", ONE_PER_CHAR, price=Price(1, 1))
    assert estimate.n_items == 0 and estimate.input_tokens == 0 and estimate.output_tokens == 0
    assert estimate.cost == 0 and estimate.per_item_input_tokens == 0.0


def test_iterators_are_consumed_once() -> None:
    estimate = estimate_run(iter([("a", "b")] * 3), "", ONE_PER_CHAR)
    assert estimate.n_items == 3


def test_cost_band_and_worst_case() -> None:
    price = Price(0.5, 1.5, "CHF")
    cfg = EstimatorConfig(output_tokens_per_item=100, max_output_tokens=400, cost_uncertainty=0.1)
    estimate = estimate_run([("t", "a")] * 10, "s" * 100, ONE_PER_CHAR, price=price, config=cfg)
    cost = cost_of(price, estimate.input_tokens, 1000)
    assert math.isclose(estimate.cost or 0, cost)
    assert math.isclose(estimate.cost_low or 0, cost * 0.9)
    assert math.isclose(estimate.cost_high or 0, cost * 1.1)
    assert math.isclose(estimate.cost_max or 0, cost_of(price, estimate.input_tokens, 4000))
    assert estimate.currency == "CHF" and estimate.price == price


def test_unknown_model_reports_tokens_only() -> None:
    estimate = estimate_run([("t", "a")], "s", ONE_PER_CHAR)
    assert estimate.price is None and estimate.currency is None
    assert estimate.cost is None and estimate.cost_low is None
    assert estimate.cost_high is None and estimate.cost_max is None


def test_worst_case_is_never_below_the_expected_cost() -> None:
    cfg = EstimatorConfig(output_tokens_per_item=500, max_output_tokens=100)
    estimate = estimate_run([("t", "a")], "s", ONE_PER_CHAR, price=Price(1, 1), config=cfg)
    assert (estimate.cost_max or 0) >= (estimate.cost or 0)


def test_negative_settings_do_not_produce_negative_numbers() -> None:
    cfg = EstimatorConfig(output_tokens_per_item=-5, max_output_tokens=-5, cost_uncertainty=-1)
    estimate = estimate_run([("t", "a")], "s", ONE_PER_CHAR, price=Price(1, 1), config=cfg)
    assert estimate.output_tokens == 0
    assert estimate.cost_low == estimate.cost == estimate.cost_high


def test_the_cost_formula_is_per_thousand() -> None:
    assert cost_of(Price(2.0, 4.0), 1000, 500) == 4.0


@given(
    st.lists(st.tuples(st.text(max_size=50), st.text(max_size=200)), max_size=20),
    st.text(max_size=100),
)
def test_more_records_never_cost_fewer_tokens(items: list[tuple[str, str]], shared: str) -> None:
    tok = CharTokenizer()
    base = estimate_run(items, shared, tok)
    more = estimate_run([*items, ("t", "a")], shared, tok)
    assert more.input_tokens > base.input_tokens
    assert base.input_tokens == base.n_items * base.shared_tokens + base.item_tokens


def test_shared_payload_skips_empty_parts() -> None:
    text = build_shared_payload(
        instructions=" Rate it. ",
        project_title="Title",
        project_description="",
        objectives=["o1", " ", "o2"],
        criteria_text="C",
    )
    assert text == "Rate it.\n\nProject: Title\n\nObjectives: o1, o2\n\nCriteria: C"
    assert "Description" not in text
    assert build_shared_payload() == ""


@pytest.mark.parametrize("n", [0, 1, 5])
def test_format_item_labels_both_parts(n: int) -> None:
    assert format_item("T" * n, "A" * n) == f"Title: {'T' * n}\nAbstract: {'A' * n}"
