"""Tests for the token counters (task T-M2-05)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crapai.cost.tokenizers import (
    FALLBACK_SAFETY_FACTOR,
    CharTokenizer,
    TiktokenTokenizer,
    tokenizer_for,
)


class FakeEncoding:
    """Stands in for a tiktoken encoding: one token per whitespace separated word."""

    def encode(self, text: str, disallowed_special: Any = ()) -> list[int]:
        return list(range(len(text.split())))


def install_fake_tiktoken(monkeypatch: pytest.MonkeyPatch, names: list[str] | None = None) -> None:
    module = types.ModuleType("tiktoken")

    def get_encoding(name: str) -> FakeEncoding:
        if names is not None:
            names.append(name)
        return FakeEncoding()

    module.get_encoding = get_encoding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tiktoken", module)


def block_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # import raises ImportError


def test_char_tokenizer_rounds_up_and_handles_empty() -> None:
    tok = CharTokenizer(chars_per_token=4)
    assert tok.count("") == 0
    assert tok.count("a") == 1
    assert tok.count("abcd") == 1
    assert tok.count("abcde") == 2
    assert tok.exact is False and tok.name == "chars"


def test_safety_factor_raises_the_count() -> None:
    assert CharTokenizer(4, 1.5).count("x" * 400) == 150


@pytest.mark.parametrize("chars,factor", [(0, 1.0), (-1, 1.0), (4, 0), (4, -1)])
def test_char_tokenizer_rejects_nonsense(chars: float, factor: float) -> None:
    with pytest.raises(ValueError):
        CharTokenizer(chars, factor)


@given(st.text(max_size=300))
def test_char_count_is_never_zero_for_text_and_monotonic(text: str) -> None:
    tok = CharTokenizer()
    assert (tok.count(text) == 0) == (text == "")
    assert tok.count(text + "x") >= tok.count(text)


def test_tiktoken_is_used_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_tiktoken(monkeypatch)
    tok = TiktokenTokenizer("o200k_base")
    assert tok.exact is True and tok.name == "tiktoken:o200k_base"
    assert tok.count("one two three") == 3
    assert tok.count("") == 0


def test_tiktoken_missing_falls_back_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    block_tiktoken(monkeypatch)
    tok = TiktokenTokenizer()
    assert tok.exact is False and tok.name == "chars"
    assert tok.count("x" * 100) == CharTokenizer(safety_factor=FALLBACK_SAFETY_FACTOR).count(
        "x" * 100
    )


def test_unknown_encoding_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("tiktoken")

    def get_encoding(name: str) -> FakeEncoding:
        raise ValueError("Unknown encoding")

    module.get_encoding = get_encoding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tiktoken", module)
    assert TiktokenTokenizer("nope").exact is False


@pytest.mark.parametrize(
    "model,encoding",
    [
        ("gpt-4o-mini", "o200k_base"),
        ("gpt-4.1", "o200k_base"),
        ("o3", "o200k_base"),
        ("gpt-4", "cl100k_base"),
        ("gpt-4-turbo", "cl100k_base"),
        ("gpt-3.5-turbo", "cl100k_base"),
        ("", "o200k_base"),
    ],
)
def test_openai_models_get_the_matching_encoding(
    monkeypatch: pytest.MonkeyPatch, model: str, encoding: str
) -> None:
    names: list[str] = []
    install_fake_tiktoken(monkeypatch, names)
    tok = tokenizer_for("OpenAI", model)
    assert names == [encoding] and tok.exact


@pytest.mark.parametrize("provider", ["anthropic", "swissgpt", "openai_compatible", "unknown"])
def test_other_providers_get_the_safe_character_counter(provider: str) -> None:
    tok = tokenizer_for(provider, "some-model")
    assert isinstance(tok, CharTokenizer)
    assert tok.exact is False and tok.safety_factor == FALLBACK_SAFETY_FACTOR
