"""Cost service: estimate what a run of this project would send and cost (plan chapter 8.5).

Reads ``records.csv`` (read only, no lock, nothing written) and ``project.yaml``. Only records that
would go to the model are counted: those without an exclusion reason. The price comes from the
project's ``pricing.csv`` if it exists; without that file, or for an unknown model, the result has
tokens but no cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from crapai.config.loader import load_project_config
from crapai.config.models import ProjectConfig
from crapai.cost.estimator import EstimatorConfig, RunEstimate, build_shared_payload, estimate_run
from crapai.cost.pricing import CsvPriceSource, Price
from crapai.cost.tokenizers import tokenizer_for
from crapai.io.records_store import read_records
from crapai.project.workspace import Workspace


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
    """

    estimate: RunEstimate
    provider: str
    model: str
    max_cost: float | None
    over_limit: bool
    price_file_found: bool


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

    Args:
        workspace: The project.
        instructions: Instruction text of the chosen prompt variant, if known.

    Raises:
        ConfigError: E201/E203 if ``project.yaml`` or ``pricing.csv`` is unusable.
        StorageError: E404 for a folder that is no project or a damaged ``records.csv``.
    """
    workspace = Workspace.open(workspace.root)
    config = load_project_config(workspace.project_yaml)
    records = read_records(workspace.records_csv)
    items = [(r.title, r.abstract) for r in records if not r.exclusion_reason]
    provider, model = config.llm.provider, config.llm.model
    price, found = find_price(workspace, provider, model)
    estimate = estimate_run(
        items,
        shared_text_of(config, instructions),
        tokenizer_for(provider, model),
        price=price,
        config=EstimatorConfig(max_output_tokens=config.llm.max_output_tokens),
    )
    limit = config.limits.max_cost
    over = limit is not None and estimate.cost_max is not None and estimate.cost_max > limit
    return ProjectEstimate(estimate, provider, model, limit, over, found)
