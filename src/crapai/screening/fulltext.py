"""Fit a full text into the model's context window (plan chapters 8.9, 29.8, ADR 0026).

Three strategies (``screening.fulltext.strategy``):

``truncate``
    Cut the text to the token budget. Simple, cheapest, loses whatever falls after the cut.
``sections``
    Keep only Methods/Results/Discussion (:mod:`crapai.prompts.fulltext_sections`); falls back to
    ``truncate`` if no heading was recognised, rather than send an empty full text.
``map_reduce``
    Not prepared here: it needs several model calls (one per chunk, then a final call that
    weighs the collected evidence), not just text preparation. :func:`chunk_for_map_reduce` splits
    the text; :mod:`crapai.screening.engine` drives the calls.

Token budgets use the caller's own token counter (the engine's provider, or the project's chosen
:class:`~crapai.cost.tokenizers.Tokenizer` for a cost estimate), so a strategy never overshoots the
context window it was measured against; counting never sends the text anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from crapai.prompts.fulltext_sections import methods_results_discussion

#: a token counter: takes text, returns how many tokens it would be (never sends anything anywhere).
CountTokens = Callable[[str], int]

#: tokens reserved for the rest of the prompt (criteria, instructions, system) and the model's
#: answer, so `truncate`/`sections` leave room for more than just the article itself.
RESERVED_TOKENS = 2000
MIN_BUDGET_TOKENS = 500
TRUNCATION_NOTICE = "\n\n[... text truncated to fit the model's context window ...]"


@dataclass(frozen=True)
class PreparedFulltext:
    """The text to put in the prompt, and how it was obtained.

    Attributes:
        text: Ready to embed in the prompt (not yet escaped for the ``<record>`` tag).
        truncated: True if anything was cut.
        strategy_used: The strategy that actually produced ``text`` -- ``sections`` falls back to
            ``truncate`` when no heading is recognised, so this can differ from the configured
            ``strategy``.
    """

    text: str
    truncated: bool
    strategy_used: str


def _budget(max_context_tokens: int) -> int:
    return max(max_context_tokens - RESERVED_TOKENS, MIN_BUDGET_TOKENS)


def _fits(text: str, start: int, end: int, budget: int, count_tokens: CountTokens) -> bool:
    return count_tokens(text[start:end]) <= budget


def _longest_fit(text: str, start: int, budget: int, count_tokens: CountTokens) -> int:
    """The largest ``end`` (``start <= end <= len(text)``) such that ``text[start:end]`` fits."""
    lo, hi = start, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(text, start, mid, budget, count_tokens):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _truncate_to_budget(
    text: str, budget: int, count_tokens: CountTokens, *, strategy_used: str
) -> PreparedFulltext:
    if count_tokens(text) <= budget:
        return PreparedFulltext(text, truncated=False, strategy_used=strategy_used)
    end = max(_longest_fit(text, 0, budget, count_tokens), 1)
    return PreparedFulltext(
        text[:end].rstrip() + TRUNCATION_NOTICE, truncated=True, strategy_used=strategy_used
    )


def prepare_fulltext(
    text: str, *, strategy: str, max_context_tokens: int, count_tokens: CountTokens
) -> PreparedFulltext:
    """Fit ``text`` into the model's context window per ``strategy`` (``truncate``/``sections``).

    ``map_reduce`` is not accepted here (see the module docstring); passing it raises
    ``ValueError`` so a caller cannot silently fall through to ``truncate`` by mistake.
    """
    if strategy == "map_reduce":
        raise ValueError("map_reduce is driven by the engine via chunk_for_map_reduce(), not this")
    budget = _budget(max_context_tokens)
    if strategy == "sections":
        reduced = methods_results_discussion(text)
        if reduced:
            return _truncate_to_budget(reduced, budget, count_tokens, strategy_used="sections")
        # No heading was recognised (for example OCR output with no line breaks): better to send
        # the whole (truncated) text than nothing.
    return _truncate_to_budget(text, budget, count_tokens, strategy_used="truncate")


def chunk_for_map_reduce(
    text: str, *, max_context_tokens: int, count_tokens: CountTokens, overlap_chars: int = 200
) -> list[str]:
    """Split ``text`` into chunks that each fit the context window (plan chapter 29.8).

    Consecutive chunks overlap by roughly ``overlap_chars`` so a sentence split across a chunk
    boundary is not lost to both halves. A text that already fits is returned as a single chunk.
    """
    budget = _budget(max_context_tokens)
    if count_tokens(text) <= budget:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = max(_longest_fit(text, start, budget, count_tokens), start + 1)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
