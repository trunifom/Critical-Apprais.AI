import math

from crapai.cost.estimator import (
    CharTokenizer,
    CSVPriceSource,
    EstimatorConfig,
    StaticPriceSource,
    TokenEstimator,
)


def test_char_tokenizer_rounds_up_and_handles_empty() -> None:
    tok = CharTokenizer(chars_per_token=4)
    assert tok.count("") == 0
    assert tok.count("abcde") == 2


def test_estimate_run_tokens_and_cost() -> None:
    est = TokenEstimator(
        EstimatorConfig(
            price_source=StaticPriceSource(0.5, 1.5, "CHF"),
            output_tokens_per_item=100,
            cost_uncertainty=0.1,
        )
    )
    out = est.estimate_run(
        n_items=10, per_item_input_tokens=300, shared_tokens=200, provider="openai", model="x"
    )
    assert out["input_tokens"] == 5000
    assert out["output_tokens"] == 1000
    assert out["total_tokens"] == 6000
    cost = 5.0 * 0.5 + 1.0 * 1.5
    low, high = out["cost_range"]
    assert math.isclose(low, cost * 0.9)
    assert math.isclose(high, cost * 1.1)
    assert out["currency"] == "CHF"


def test_no_price_source_means_no_cost() -> None:
    out = TokenEstimator().estimate_run(3, 100, 50, provider="p", model="m")
    assert out["cost_range"] is None


def test_csv_price_source(tmp_path) -> None:
    csv = tmp_path / "prices.csv"
    csv.write_text(
        "provider,model,price_input_per_1k,price_output_per_1k,currency\n"
        'openai,gpt-4o-mini,"0,00015",0.0006,usd\n',
        encoding="utf-8",
    )
    assert CSVPriceSource(str(csv)).get_prices("OpenAI", "GPT-4o-mini") == (0.00015, 0.0006, "USD")
    assert CSVPriceSource(str(csv)).get_prices("openai", "other") is None


def test_shared_payload_respects_mask() -> None:
    est = TokenEstimator()
    text = est.build_shared_payload(
        "crit", "Title", "Desc", ["o1", " "], "tmpl", include_parts={"project_desc": False}
    )
    assert "Description" not in text
    assert "Objectives: o1" in text
    assert "Criteria: crit" in text


def test_per_batch_mode_amortises_shared_tokens() -> None:
    est = TokenEstimator(EstimatorConfig(shared_mode="per_batch"))
    assert est.estimate_shared_tokens("x" * 400, batch_size=10) == 10  # 100 tokens / 10
