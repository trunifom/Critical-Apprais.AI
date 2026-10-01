"""Cost service: estimate what a run of this project would send and cost (plan chapter 8.5).

Reads ``records.csv`` (read only, no lock, nothing written) and ``project.yaml``. Only records that
would go to the model are counted: those without an exclusion reason. The price comes from the
project's ``pricing.csv`` if it exists; without that file, or for an unknown model, the result has
tokens but no cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.config.models import ProjectConfig
from crapai.cost.duration import DurationConfig, DurationEstimate, estimate_duration
from crapai.cost.estimator import EstimatorConfig, RunEstimate, build_shared_payload, estimate_run
from crapai.cost.pricing import CsvPriceSource, Price
from crapai.cost.tokenizers import tokenizer_for
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace
from crapai.prompts.builder import builder_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectEstimate:
    """Estimate of a project run together with what it was based on.

    Attributes:
        estimate: The numbers.
        provider: ``llm.provider`` of the project.
        model: ``llm.model`` of the project.
        max_cost: ``limits.max_cost`` (None = no limit).
        over_limit: True if the worst case exceeds ``max_cost`` (the run would stop early).
        price_file_found: Whether the project has a ``pricing.csv``.
        duration: Estimated wall-clock time from ``limits.rpm``, ``limits.tpm`` and
            ``limits.max_concurrency``.
    """

    estimate: RunEstimate
    provider: str
    model: str
    max_cost: float | None
    over_limit: bool
    price_file_found: bool
    duration: DurationEstimate


def criteria_text(config: ProjectConfig) -> str:
    """Flatten the criteria of a project into the text that goes into the prompt."""
    lines = [f"Include {key}: {value}" for key, value in config.criteria.inclusion.items()]
    lines += [f"Exclude {key}: {value}" for key, value in config.criteria.exclusion.items()]
    return "\n".join(lines)


def shared_text_of(config: ProjectConfig, instructions: str = "") -> str:
    """Shared prompt part from the project settings (until the prompt builder supplies it)."""
    return build_shared_payload(
        instructions=instructions,
        project_title=config.project.title,
        project_description=config.project.description,
        objectives=config.objectives,
        criteria_text=criteria_text(config),
    )


def find_price(workspace: Workspace, provider: str, model: str) -> tuple[Price | None, bool]:
    """Look the model up in the project's ``pricing.csv``.

    Returns:
        ``(price or None, whether the file exists)``.

    Raises:
        ConfigError: E203 if the file exists but is unusable.
    """
    if not workspace.pricing_csv.exists():
        return None, False
    return CsvPriceSource(workspace.pricing_csv).get_price(provider, model), True


def estimate_project(workspace: Workspace, *, instructions: str = "") -> ProjectEstimate:
    """Estimate tokens and cost of screening all records that would go to the model.

    The shared part is the **real prompt** of the run: the system prompt and the stable prefix
    (project, criteria, instructions) of the chosen prompt variant, exactly as
    :class:`~crapai.prompts.builder.PromptBuilder` will send them. ``instructions`` is used only
    for the legacy ``shared_text_of`` helper and is ignored here.

    Args:
        workspace: The project.
        instructions: Kept for compatibility; the variant supplies the instructions.

    Raises:
        ConfigError: E201/E203 if ``project.yaml`` or ``pricing.csv`` is unusable.
        StorageError: E404 for a folder that is no project or a damaged ``records.csv``.
    """
    workspace = Workspace.open(workspace.root)
    config = load_project_config(workspace.project_yaml)
    records = read_records(workspace.records_csv)
    include_keywords = config.screening.include_keywords_in_prompt
    items = [
        (
            r.title,
            f"{r.abstract}\nKeywords: {r.keywords}" if include_keywords and r.keywords.strip()
            else r.abstract,
        )
        for r in records
        if not r.exclusion_reason
    ]
    builder = builder_for(config, workspace.prompts_dir)
    shared_text = builder.system + "\n\n" + builder.prefix
    provider, model = config.llm.provider, config.llm.model
    price, found = find_price(workspace, provider, model)
    estimate = estimate_run(
        items,
        shared_text,
        tokenizer_for(provider, model),
        price=price,
        config=EstimatorConfig(
            output_tokens_per_item=config.llm.expected_output_tokens,
            max_output_tokens=config.llm.max_output_tokens,
            cost_uncertainty=config.limits.cost_uncertainty,
        ),
    )
    logger.info(
        "Estimate: %d record(s) for %s/%s, %d input tokens, tokenizer %s",
        estimate.n_items,
        provider,
        model,
        estimate.input_tokens,
        estimate.tokenizer,
    )
    limit = config.limits.max_cost
    over = limit is not None and estimate.cost_max is not None and estimate.cost_max > limit
    limits = config.limits
    duration = estimate_duration(
        estimate.n_items,
        estimate.total_tokens,
        rpm=limits.rpm,
        tpm=limits.tpm,
        max_concurrency=limits.max_concurrency,
        config=DurationConfig(seconds_per_request=limits.seconds_per_request),
    )
    return ProjectEstimate(estimate, provider, model, limit, over, found, duration)
