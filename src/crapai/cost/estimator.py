"""Token and cost estimate of a screening run (plan chapter 8.5; rewrite of SARA-App ``estimator``).

Differences to the predecessor, which sampled 20 records and guessed when there were none:

* every record that goes to the model is counted with its **real** title and abstract, because the
  texts are local anyway;
* the shared part (instructions, objectives, criteria) is counted from the text that is actually
  sent, passed in by the caller;
* the tokenizer and the price come from :mod:`crapai.cost.tokenizers` and
  :mod:`crapai.cost.pricing`; an unknown model gives tokens without a cost;
* the result is a typed :class:`RunEstimate`, not a dictionary;
* there is no fixed guess for full texts: a longer text is simply counted as given.

The module has no I/O and no UI dependency. Output length cannot be known beforehand: the expected
value is ``output_tokens_per_item``; the worst case is ``max_output_tokens`` for every record.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from crapai.cost.pricing import Price
from crapai.cost.tokenizers import Tokenizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EstimatorConfig:
    """Assumptions of an estimate.

    Attributes:
        output_tokens_per_item: Expected answer length per record (structured decision and a
            short reason).
        max_output_tokens: Hard limit per answer (``llm.max_output_tokens``); used for the worst
            case.
        cost_uncertainty: Half width of the cost band, for example 0.15 for plus/minus 15 %.
    """

    output_tokens_per_item: int = 120
    max_output_tokens: int = 800
    cost_uncertainty: float = 0.15


@dataclass(frozen=True)
class RunEstimate:
    """Estimated size and cost of a run.

    Attributes:
        n_items: Records that would be sent.
        shared_tokens: Tokens of the shared part, sent with every record.
        item_tokens: Tokens of all records' title and abstract together.
        input_tokens: ``n_items * shared_tokens + item_tokens``.
        output_tokens: Expected answer tokens (``n_items * output_tokens_per_item``).
        tokenizer: Name of the counter used.
        exact: True if the counter is the model's own tokenizer, False for an approximation.
        price: The price used, or None if the model has no price.
        cost: Expected cost, or None without a price.
        cost_low: Lower end of the band, or None.
        cost_high: Upper end of the band, or None.
        cost_max: Worst case (every answer at the output limit), or None.
    """

    n_items: int
    shared_tokens: int
    item_tokens: int
    input_tokens: int
    output_tokens: int
    tokenizer: str
    exact: bool
    price: Price | None = None
    cost: float | None = None
    cost_low: float | None = None
    cost_high: float | None = None
    cost_max: float | None = None

    @property
    def total_tokens(self) -> int:
        """Input plus expected output tokens."""
        return self.input_tokens + self.output_tokens

    @property
    def currency(self) -> str | None:
        """Currency of the cost figures, or None without a price."""
        return self.price.currency if self.price else None

    @property
    def per_item_input_tokens(self) -> float:
        """Average input tokens per record including the shared part (0 without records)."""
        return self.input_tokens / self.n_items if self.n_items else 0.0


def build_shared_payload(
    *,
    instructions: str = "",
    project_title: str = "",
    project_description: str = "",
    objectives: Sequence[str] = (),
    criteria_text: str = "",
) -> str:
    """Compose the shared part of the prompt from its components, skipping empty ones.

    Used for the estimate until the prompt builder of milestone M3 supplies the exact text.
    """
    parts: list[str] = []
    if instructions.strip():
        parts.append(instructions.strip())
    if project_title.strip():
        parts.append(f"Project: {project_title.strip()}")
    if project_description.strip():
        parts.append(f"Description: {project_description.strip()}")
    goals = ", ".join(o.strip() for o in objectives if o.strip())
    if goals:
        parts.append(f"Objectives: {goals}")
    if criteria_text.strip():
        parts.append(f"Criteria: {criteria_text.strip()}")
    return "\n\n".join(parts)


def format_item(title: str, abstract: str) -> str:
    """The record part of a prompt as it is counted (title and abstract with their labels)."""
    return f"Title: {title}\nAbstract: {abstract}"


def cost_of(price: Price, input_tokens: int, output_tokens: int) -> float:
    """Cost of the given token numbers at ``price``."""
    return input_tokens / 1000.0 * price.input_per_1k + output_tokens / 1000.0 * price.output_per_1k


def estimate_run(
    items: Iterable[tuple[str, str]],
    shared_text: str,
    tokenizer: Tokenizer,
    *,
    price: Price | None = None,
    config: EstimatorConfig | None = None,
) -> RunEstimate:
    """Count a run.

    Args:
        items: ``(title, abstract)`` of every record that would be sent (for full texts, pass the
            extracted text as the second element).
        shared_text: The part sent with every record (instructions, objectives, criteria).
        tokenizer: The counter; see :func:`crapai.cost.tokenizers.tokenizer_for`.
        price: Price of the model, or None to report tokens only.
        config: Assumptions; defaults are used if omitted.

    Returns:
        The estimate; with a price it includes the expected cost, a band and the worst case.
    """
    config = config or EstimatorConfig()
    shared_tokens = tokenizer.count(shared_text)
    n_items = 0
    item_tokens = 0
    for title, abstract in items:
        n_items += 1
        item_tokens += tokenizer.count(format_item(title, abstract))
    input_tokens = n_items * shared_tokens + item_tokens
    output_tokens = n_items * max(0, config.output_tokens_per_item)

    estimate = RunEstimate(
        n_items=n_items,
        shared_tokens=shared_tokens,
        item_tokens=item_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokenizer=tokenizer.name,
        exact=tokenizer.exact,
    )
    if price is None:
        return estimate
    cost = cost_of(price, input_tokens, output_tokens)
    band = min(1.0, max(0.0, config.cost_uncertainty))  # the low end never goes below 0
    worst = cost_of(price, input_tokens, n_items * max(0, config.max_output_tokens))
    logger.info(
        "Estimate: %d records, %d input tokens, cost %.4f %s",
        n_items,
        input_tokens,
        cost,
        price.currency,
    )
    return replace(
        estimate,
        price=price,
        cost=cost,
        cost_low=(1.0 - band) * cost,
        cost_high=(1.0 + band) * cost,
        cost_max=max(worst, cost),
    )
