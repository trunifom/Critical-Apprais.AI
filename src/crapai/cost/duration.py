"""Duration estimate of a screening run (plan chapter 8.5) and the cost confirmation rule.

A run is limited by whichever of three things is slowest:

``rpm``      requests per minute allowed by the provider (``limits.rpm``), one request per record
``tpm``      tokens per minute (``limits.tpm``), input plus expected output
``latency``  the time one request takes, divided by the number of parallel requests
             (``limits.max_concurrency``)

The latency of a request is not known beforehand; ``DurationConfig.seconds_per_request`` is a
working assumption (3 s for a short prompt) and is the weakest part of the estimate. The result is
a guide, not a promise. No I/O.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class DurationConfig:
    """Assumptions of the duration estimate.

    Attributes:
        seconds_per_request: Assumed time of one request (answer included).
    """

    seconds_per_request: float = 3.0


@dataclass(frozen=True)
class DurationEstimate:
    """Estimated wall-clock time of a run.

    Attributes:
        seconds: Estimated duration in seconds.
        limited_by: ``rpm``, ``tpm`` or ``latency``; ``none`` for an empty run.
    """

    seconds: float
    limited_by: str


def estimate_duration(
    n_items: int,
    total_tokens: int,
    *,
    rpm: int,
    tpm: int,
    max_concurrency: int,
    config: DurationConfig | None = None,
) -> DurationEstimate:
    """Estimate the duration of ``n_items`` requests with ``total_tokens`` tokens in all.

    Raises:
        ValueError: If ``rpm``, ``tpm`` or ``max_concurrency`` is not positive.
    """
    if rpm <= 0 or tpm <= 0 or max_concurrency <= 0:
        raise ValueError("rpm, tpm and max_concurrency must be positive")
    config = config or DurationConfig()
    if n_items <= 0:
        return DurationEstimate(0.0, "none")
    candidates = {
        "rpm": n_items / rpm * 60.0,
        "tpm": max(0, total_tokens) / tpm * 60.0,
        "latency": n_items * config.seconds_per_request / max_concurrency,
    }
    limited_by = max(candidates, key=lambda key: candidates[key])
    return DurationEstimate(candidates[limited_by], limited_by)


def format_duration(seconds: float) -> str:
    """A short human form: ``45 s``, ``12 min``, ``2 h 05 min`` (rounded up to whole seconds)."""
    total = max(0, int(-(-seconds // 1)))
    if total < 60:
        return f"{total} s"
    minutes = -(-total // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min"


class Confirmation(enum.Enum):
    """What a run must do before it starts (used by ``crapai screen``)."""

    PROCEED = "proceed"  # go on without asking
    ASK = "ask"  # show the estimate and ask the user
    REFUSE = "refuse"  # no terminal and no --yes: do not start


def decide_confirmation(*, yes: bool, interactive: bool) -> Confirmation:
    """The rule of plan 8.5: a run starts only after ``--yes`` or an answer at the terminal.

    Args:
        yes: ``--yes`` was given.
        interactive: stdin is a terminal, so the user can be asked.
    """
    if yes:
        return Confirmation.PROCEED
    return Confirmation.ASK if interactive else Confirmation.REFUSE
