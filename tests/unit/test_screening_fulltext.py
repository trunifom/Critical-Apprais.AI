"""Tests for fitting a full text into the context window (plan chapters 8.9, 29.8, ADR 0026)."""

from __future__ import annotations

import pytest

from crapai.cost.tokenizers import CharTokenizer
from crapai.screening.fulltext import (
    TRUNCATION_NOTICE,
    chunk_for_map_reduce,
    prepare_fulltext,
)

TOKENIZER = CharTokenizer(chars_per_token=1.0)  # 1 char = 1 token, so budgets are exact in chars


def test_a_short_text_is_returned_unchanged() -> None:
    result = prepare_fulltext(
        "short text", strategy="truncate", max_context_tokens=3000, tokenizer=TOKENIZER
    )
    assert result.text == "short text" and not result.truncated
    assert result.strategy_used == "truncate"


def test_a_long_text_is_cut_to_the_budget_and_marked_truncated() -> None:
    text = "x" * 5000
    result = prepare_fulltext(
        text, strategy="truncate", max_context_tokens=2100, tokenizer=TOKENIZER
    )
    assert result.truncated is True
    assert result.text.endswith(TRUNCATION_NOTICE)
    assert len(result.text) < len(text)


def test_sections_strategy_keeps_only_methods_results_discussion() -> None:
    text = "Abstract\nSummary here.\n\nMethods\nWe did a trial.\n\nReferences\nSmith 2020.\n"
    result = prepare_fulltext(
        text, strategy="sections", max_context_tokens=3000, tokenizer=TOKENIZER
    )
    assert "We did a trial." in result.text
    assert "Summary here." not in result.text and "Smith 2020." not in result.text
    assert result.strategy_used == "sections"


def test_sections_strategy_falls_back_to_truncate_without_a_heading() -> None:
    result = prepare_fulltext(
        "just a wall of text, no headings", strategy="sections",
        max_context_tokens=3000, tokenizer=TOKENIZER,
    )  # fmt: skip
    assert result.strategy_used == "truncate" and not result.truncated


def test_map_reduce_is_rejected_here_not_silently_truncated() -> None:
    with pytest.raises(ValueError, match="map_reduce"):
        prepare_fulltext("x", strategy="map_reduce", max_context_tokens=3000, tokenizer=TOKENIZER)


def test_a_text_that_fits_is_a_single_chunk() -> None:
    chunks = chunk_for_map_reduce("short", max_context_tokens=3000, tokenizer=TOKENIZER)
    assert chunks == ["short"]


def test_a_long_text_is_split_into_several_overlapping_chunks() -> None:
    text = "".join(f"sentence {i}. " for i in range(2000))
    chunks = chunk_for_map_reduce(
        text, max_context_tokens=2100, tokenizer=TOKENIZER, overlap_chars=50
    )
    assert len(chunks) > 1
    assert "".join(chunks).startswith("sentence 0.")
    # every character of the original text appears somewhere (allowing for the overlap)
    assert chunks[-1].endswith(text[-20:])
    # consecutive chunks actually overlap (the tail of one reappears at the head of the next)
    assert any(chunks[i][-30:] in chunks[i + 1] for i in range(len(chunks) - 1))


def test_chunks_never_exceed_the_token_budget() -> None:
    text = "y" * 10_000
    chunks = chunk_for_map_reduce(text, max_context_tokens=2500, tokenizer=TOKENIZER)
    assert all(TOKENIZER.count(chunk) <= 2500 - 2000 for chunk in chunks)
