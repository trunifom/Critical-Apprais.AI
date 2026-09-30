# core/estimator.py
# -*- coding: utf-8 -*-
"""
Token & cost estimation for a review run (PRISMA workflow support).

Design goals:
- UI-agnostic and testable (no Streamlit calls, no I/O in public API).
- Pluggable tokenizers (Strategy pattern), starting with a simple char-based
  heuristic and optional adapters for model-specific tokenizers (OpenAI tiktoken,
  Hugging Face tokenizers, etc.).
- Pluggable price sources (static values, CSV lookup, future remote API).
- Flexible estimation pipeline: shared payload (project, description, criteria,
  objectives, instruction) + per-item tokens (title + abstract) + output tokens.
- Configurable sampling for per-item estimation and fully overridable formula.

Best-practice references:
- OpenAI tiktoken (fast BPE tokenizer) – recommended for GPT models:
  https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken
- Anthropic token counting (Messages Count Tokens API):
  https://docs.anthropic.com/en/api/messages-count-tokens
- Hugging Face tokenizers summary (model-specific tokenization):
  https://huggingface.co/docs/transformers/en/tokenizer_summary
- Pricing norms & dynamics (examples; provider docs are the source of truth):
  https://platform.openai.com/docs/pricing
"""

from __future__ import annotations
import csv
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple, Union


# ──────────────────────────────────────────────────────────────────────────────
# Tokenizer Strategy (pluggable)
# ──────────────────────────────────────────────────────────────────────────────

class Tokenizer(Protocol):
    """
    Tokenizer interface; swap implementations without changing callers.

    Implementations should be pure and side-effect free. They must NOT do any
    network calls. If you need remote counting (e.g., Anthropic's Count Tokens
    API), use a separate service/wrapper at the application boundary and feed
    the exact token counts here.
    """
    def count(self, text: str) -> int:
        """Return number of tokens for given text."""

        return len(text.split())


@dataclass
class CharTokenizer:
    """
    Very rough tokenizer: ~1 token per N characters (including whitespace).

    This is deliberately simple for a UI preview. In production, prefer a
    model-native tokenizer (e.g., OpenAI tiktoken for GPT-family, or a
    Hugging Face tokenizer matching your target model).
    """
    chars_per_token: int = 4

    def count(self, text: str) -> int:
        if not text:
            return 0
        # Conservative rounding up; never return 0 for non-empty text
        return max(1, math.ceil(len(text) / max(1, self.chars_per_token)))


@dataclass
class TiktokenTokenizer:
    """
    OpenAI-compatible tokenizer via `tiktoken`. Requires the package to be
    available at runtime. Falls back to CharTokenizer if not installed.

    Usage:
        tok = TiktokenTokenizer("cl100k_base")  # or encoding name for your model
        n = tok.count("some text")
    """
    encoding_name: str = "cl100k_base"
    fallback: Tokenizer = field(default_factory=lambda: CharTokenizer())

    def __post_init__(self) -> None:
        try:
            import tiktoken  # type: ignore
            self._enc = tiktoken.get_encoding(self.encoding_name)
            self._ok = True
        except Exception:
            self._enc = None
            self._ok = False

    def count(self, text: str) -> int:
        if not text:
            return 0
        if not getattr(self, "_ok", False) or self._enc is None:
            return self.fallback.count(text)
        try:
            # NOTE: For chat messages, OpenAI has special counting rules
            # (system, user, assistant roles). For UI estimates, plain encoding
            # is usually sufficient. If you need chat-accurate counts, inject
            # a specialized estimator that follows the official formula.
            return len(self._enc.encode(text))
        except Exception:
            return self.fallback.count(text)


@dataclass
class HFTokenizer:
    """
    Hugging Face tokenizer adapter (model-specific). Requires `transformers`
    to be installed and a valid tokenizer identifier (local or hub).

    Example:
        tok = HFTokenizer("meta-llama/Meta-Llama-3-8B")
        n = tok.count("some text")
    """
    model_id: str
    fallback: Tokenizer = field(default_factory=lambda: CharTokenizer())

    def __post_init__(self) -> None:
        try:
            from transformers import AutoTokenizer  # type: ignore
            self._tok = AutoTokenizer.from_pretrained(self.model_id)
            self._ok = True
        except Exception:
            self._tok = None
            self._ok = False

    def count(self, text: str) -> int:
        if not text:
            return 0
        if not getattr(self, "_ok", False) or self._tok is None:
            return self.fallback.count(text)
        try:
            # `return_tensors=None` returns a dict with 'input_ids'
            ids = self._tok(text, add_special_tokens=False)["input_ids"]
            return len(ids)
        except Exception:
            return self.fallback.count(text)


# ──────────────────────────────────────────────────────────────────────────────
# Price Source Strategy (pluggable)
# ──────────────────────────────────────────────────────────────────────────────

class PriceSource(Protocol):
    """
    Strategy interface for looking up model prices.
    Implementations return a tuple:
        (input_per_1k: float, output_per_1k: float, currency: str)
    Or None if no price is known.
    """
    def get_prices(self, provider: str, model: str) -> Optional[Tuple[float, float, str]]:
        ...


@dataclass
class StaticPriceSource:
    """
    Static prices for a single (provider, model) tuple – easiest to start with.

    Example:
        src = StaticPriceSource(0.5, 1.5, currency="CHF")
        src.get_prices("openai", "gpt-4o-mini") -> (0.5, 1.5, "CHF")
    """
    input_per_1k: float
    output_per_1k: float
    currency: str = "USD"

    def get_prices(self, provider: str, model: str) -> Optional[Tuple[float, float, str]]:
        return (float(self.input_per_1k), float(self.output_per_1k), self.currency)


@dataclass
class CSVPriceSource:
    """
    Price lookup from a CSV file. Expected columns (case-insensitive):
      provider, model, price_input_per_1k, price_output_per_1k, currency

    - First matching row is returned.
    - Numeric parsing is tolerant (comma/point).
    """
    csv_path: str

    def get_prices(self, provider: str, model: str) -> Optional[Tuple[float, float, str]]:
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    p = (row.get("provider") or "").strip().lower()
                    m = (row.get("model") or "").strip().lower()
                    if p == (provider or "").strip().lower() and m == (model or "").strip().lower():
                        inp = _safe_float(row.get("price_input_per_1k"))
                        out = _safe_float(row.get("price_output_per_1k"))
                        cur = (row.get("currency") or "USD").strip().upper()
                        if inp is not None and out is not None:
                            return (inp, out, cur)
        except Exception:
            pass
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Estimator Config & Core
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EstimatorConfig:
    """
    Configuration for TokenEstimator.

    Parameters
    ----------
    tokenizer : Tokenizer
        Strategy for token counting (default: CharTokenizer()).
    price_source : Optional[PriceSource]
        Where to fetch prices (None → only tokens reported, no cost).
    shared_mode : str
        How to apply shared payload ("per_item" or "per_batch").
        - "per_item": shared tokens are added for each item (most common when
          you send one abstract per request).
        - "per_batch": shared tokens are counted once per batch; the caller must
          pass `batch_size` appropriately to `estimate_run()`.
    output_tokens_per_item : int
        Expected completion length per item (very rough; UI-level).
    cost_uncertainty : float
        ± band for cost range (e.g., 0.15 → ±15%).
    """
    tokenizer: Tokenizer = field(default_factory=lambda: CharTokenizer())
    price_source: Optional[PriceSource] = None
    shared_mode: str = "per_item"  # or "per_batch"
    output_tokens_per_item: int = 120
    cost_uncertainty: float = 0.15


class TokenEstimator:
    """
    Stateless estimator for tokens and costs. All methods are pure and take
    plain text inputs so you can call them in UI, worker, or tests.

    Typical usage:
        est = TokenEstimator(EstimatorConfig(
            tokenizer=TiktokenTokenizer("cl100k_base"),
            price_source=CSVPriceSource("prices.csv"),
            shared_mode="per_item",
            output_tokens_per_item=120,
        ))

        shared = est.build_shared_payload(criteria_text, project_title, project_desc,
                                          objectives, prompt_template)
        shared_tokens = est.estimate_shared_tokens(shared)

        per_item_tokens = est.estimate_per_item_tokens_from_samples(titles, abstracts, sample_size=20)

        summary = est.estimate_run(
            n_items=len_dataset,
            per_item_input_tokens=per_item_tokens,
            shared_tokens=shared_tokens,
            provider="openai",
            model="gpt-4o-mini"
        )
    """

    def __init__(self, cfg: Optional[EstimatorConfig] = None) -> None:
        self.cfg = cfg or EstimatorConfig()

    # ── Shared Payload ────────────────────────────────────────────────────
    def build_shared_payload(
        self,
        criteria_text: str,
        project_title: str,
        project_desc: str,
        objectives: Sequence[str],
        prompt_template: Optional[str] = None,
        include_parts: Optional[Dict[str, bool]] = None,
    ) -> str:
        """
        Compose the shared instruction text. The `include_parts` mask allows you
        to toggle components without touching the call sites (e.g., disable
        project_desc or objectives temporarily).

        include_parts keys:
            - "prompt_template"
            - "project_title"
            - "project_desc"
            - "objectives"
            - "criteria_text"
        """
        mask = {
            "prompt_template": True,
            "project_title": True,
            "project_desc": True,
            "objectives": True,
            "criteria_text": True,
        }
        if include_parts:
            mask.update(include_parts)

        parts: List[str] = []
        if prompt_template and mask["prompt_template"]:
            parts.append(prompt_template)
        if project_title and mask["project_title"]:
            parts.append(f"Project: {project_title}")
        if project_desc and mask["project_desc"]:
            parts.append(f"Description: {project_desc}")
        if objectives and mask["objectives"]:
            joined = ", ".join(o for o in objectives if (o or "").strip())
            if joined:
                parts.append("Objectives: " + joined)
        if criteria_text and mask["criteria_text"]:
            parts.append("Criteria: " + criteria_text)

        return "\n\n".join(parts)

    def estimate_shared_tokens(self, shared_payload: str, *, batch_size: int = 1) -> int:
        """
        Return shared-token contribution per item, honoring shared_mode:
        - per_item: tokens are counted for each item (returns count as-is)
        - per_batch: tokens are amortized over batch_size
        """
        base = self.cfg.tokenizer.count(shared_payload)
        if self.cfg.shared_mode == "per_batch":
            return max(1, math.ceil(base / max(1, batch_size)))
        # per_item
        return base

    # ── Per-item estimation from samples ──────────────────────────────────
    def estimate_per_item_tokens_from_samples(
        self,
        titles: Sequence[str],
        abstracts: Sequence[str],
        sample_size: int = 20,
        title_weight: float = 1.0,
        abstract_weight: float = 1.0,
    ) -> int:
        """
        Estimate per-item input tokens from up to `sample_size` pairs of
        titles/abstracts. Weights allow you to emphasize title/abstract if your
        prompt uses them asymmetrically.

        If no texts are provided, we fall back to a conservative heuristic.
        """
        n_titles = len(titles or [])
        n_abstracts = len(abstracts or [])
        n = max(n_titles, n_abstracts)
        if n == 0:
            # Heuristic: short title (~80 chars) + typical abstract (~1600 chars)
            return (
                int(title_weight * self.cfg.tokenizer.count("Title " * 20)) +
                int(abstract_weight * self.cfg.tokenizer.count("Abstract " * 200))
            )

        k = min(sample_size, n)
        total = 0
        for i in range(k):
            t = titles[i] if i < n_titles else ""
            a = abstracts[i] if i < n_abstracts else ""
            total += int(title_weight * self.cfg.tokenizer.count(t))
            total += int(abstract_weight * self.cfg.tokenizer.count(a))

        return max(1, math.ceil(total / k))

    # ── Run-level estimation ──────────────────────────────────────────────
    def estimate_run(
        self,
        n_items: int,
        per_item_input_tokens: int,
        shared_tokens: int,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute input/output/total tokens and an optional cost range.

        Notes:
        - shared_tokens is expected to be *per item* already (use shared_mode
          + batch_size via estimate_shared_tokens()).
        - Prices are fetched via self.cfg.price_source if provided and both
          provider+model are given.
        """
        n_items = max(0, int(n_items))
        per_item_input_tokens = max(0, int(per_item_input_tokens))
        shared_tokens = max(0, int(shared_tokens))

        input_total = n_items * (per_item_input_tokens + shared_tokens)
        out_per_item = max(0, int(self.cfg.output_tokens_per_item))
        output_total = n_items * out_per_item
        total_tokens = input_total + output_total

        out: Dict[str, Any] = {
            "input_tokens": int(input_total),
            "output_tokens": int(output_total),
            "total_tokens": int(total_tokens),
            "cost_range": None,
            "currency": None,
            "prices_used": None,
        }

        if self.cfg.price_source and provider and model:
            prices = self.cfg.price_source.get_prices(provider, model)
            if prices:
                price_in, price_out, currency = prices
                cost_in = (input_total / 1000.0) * float(price_in)
                cost_out = (output_total / 1000.0) * float(price_out)
                cost = cost_in + cost_out
                band = max(0.0, float(self.cfg.cost_uncertainty))
                low, high = (1.0 - band) * cost, (1.0 + band) * cost
                out.update({
                    "cost_range": (low, high),
                    "currency": currency,
                    "prices_used": {
                        "input_per_1k": price_in,
                        "output_per_1k": price_out,
                        "currency": currency,
                    }
                })

        return out
