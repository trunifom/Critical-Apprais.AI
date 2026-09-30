"""Token counters (plan chapters 8.5 and 29.4).

A tokenizer turns a text into a token count, locally and without any network call. Two are
provided:

``CharTokenizer``
    Characters divided by a constant, rounded up. Always available, never exact. Used for every
    provider without a local tokenizer (Anthropic, SwissGPT) and as fallback.
``TiktokenTokenizer``
    The OpenAI encoding through the optional package ``tiktoken`` (extra ``llm-openai``). Exact for
    OpenAI models. If the package or the encoding is missing it falls back to the character
    counter and says so through :attr:`exact`.

:func:`tokenizer_for` picks one for a provider and model. Every tokenizer has a ``name`` and an
``exact`` flag so that a report can say how the numbers were obtained.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# English text is about 4 characters per token, German more tokens per word (plan 29.4). The
# safety factor makes the fallback err on the high side so that cost is not underestimated.
DEFAULT_CHARS_PER_TOKEN = 4.0
FALLBACK_SAFETY_FACTOR = 1.10


class Tokenizer(Protocol):
    """Interface of a token counter. Implementations are pure and never use the network."""

    @property
    def name(self) -> str:
        """Short name of the counter, shown in reports."""
        ...

    @property
    def exact(self) -> bool:
        """True if the counts are those of the model's own tokenizer."""
        ...

    def count(self, text: str) -> int:
        """Return the number of tokens of ``text`` (0 for an empty text)."""
        ...


@dataclass(frozen=True)
class CharTokenizer:
    """Approximate counter: ``ceil(len(text) / chars_per_token * safety_factor)``.

    Args:
        chars_per_token: Average characters per token; must be positive.
        safety_factor: Multiplier on the result; 1.0 for a neutral count.
    """

    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN
    safety_factor: float = 1.0
    name: str = "chars"
    exact: bool = False

    def __post_init__(self) -> None:
        if self.chars_per_token <= 0 or self.safety_factor <= 0:
            raise ValueError("chars_per_token and safety_factor must be positive")

    def count(self, text: str) -> int:
        """Return the approximate token count; at least 1 for a non-empty text."""
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.chars_per_token * self.safety_factor))


class TiktokenTokenizer:
    """OpenAI tokenizer through ``tiktoken``, with a character fallback.

    Args:
        encoding_name: Name of the encoding, for example ``cl100k_base`` or ``o200k_base``.
        fallback: Counter used when ``tiktoken`` or the encoding is unavailable.

    Attributes:
        exact: True only if the real encoding is loaded.
        name: ``tiktoken:<encoding>`` if exact, else the name of the fallback.
    """

    def __init__(
        self, encoding_name: str = "o200k_base", fallback: Tokenizer | None = None
    ) -> None:
        self.encoding_name = encoding_name
        self.fallback: Tokenizer = fallback or CharTokenizer(safety_factor=FALLBACK_SAFETY_FACTOR)
        self._encoding: Any = None
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding(encoding_name)
        except Exception as exc:  # missing package, or encoding file not downloadable offline
            logger.info("tiktoken %s unavailable (%s); using characters", encoding_name, exc)
        self.exact = self._encoding is not None
        self.name = f"tiktoken:{encoding_name}" if self.exact else self.fallback.name

    def count(self, text: str) -> int:
        """Return the token count with the real encoding, or the fallback count."""
        if not text:
            return 0
        if self._encoding is None:
            return self.fallback.count(text)
        return len(self._encoding.encode(text, disallowed_special=()))


def tokenizer_for(provider: str, model: str = "") -> Tokenizer:
    """Choose the best available local tokenizer for a provider and model.

    OpenAI models get ``tiktoken`` (``o200k_base`` for the 4o/4.1/o-series, ``cl100k_base`` for
    older names). Everything else, including SwissGPT and Anthropic, gets the character counter
    with the safety factor: Anthropic counts tokens only through a network endpoint, and the
    models behind SwissGPT differ.
    """
    if provider.strip().lower() == "openai":
        name = model.strip().lower()
        older = name.startswith(("gpt-3.5", "gpt-4-")) or name == "gpt-4"
        return TiktokenTokenizer("cl100k_base" if older else "o200k_base")
    return CharTokenizer(safety_factor=FALLBACK_SAFETY_FACTOR)
