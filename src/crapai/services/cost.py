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
from crapai.cost.tokenizers import CharTokenizer, Tokenizer, tokenizer_for
from crapai.errors import ConfigError
from crapai.io.records_store import Record, read_records
from crapai.project.workspace import Workspace
from crapai.prompts.builder import builder_for
from crapai.screening.fulltext import DEFAULT_CONTEXT_TOKENS, prepare_fulltext
from crapai.services.ai_prefilter import eligible_for_ai_prefilter
from crapai.services.screening import eligible_records, fulltext_lookup

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


def _abstract_items(records: list[Record], config: ProjectConfig) -> list[tuple[str, str]]:
    include_keywords = config.screening.include_keywords_in_prompt
    return [
        (
            r.title,
            f"{r.abstract}\nKeywords: {r.keywords}"
            if include_keywords and r.keywords.strip()
            else r.abstract,
        )
        for r in eligible_records(records, config)
    ]


def _fulltext_items(
    records: list[Record], config: ProjectConfig, workspace: Workspace, tokenizer: Tokenizer
) -> list[tuple[str, str]]:
    """``(title, text)`` of every eligible record, already fitted to the context window.

    Using the *prepared* (possibly truncated/reduced) text rather than the raw full text means
    the estimate matches what :mod:`crapai.screening.engine` will actually send, instead of
    overestimating a ``truncate``/``sections`` run by the length of the part that gets cut.
    """
    resolve = fulltext_lookup(records, workspace)
    context = config.llm.context_tokens or DEFAULT_CONTEXT_TOKENS
    strategy = config.screening.fulltext.strategy
    items = []
    for record in eligible_records(records, config):
        prepared = prepare_fulltext(
            resolve(record), strategy=strategy, max_context_tokens=context,
            count_tokens=tokenizer.count,
        )  # fmt: skip
        items.append((record.title, prepared.text))
    return items


@dataclass(frozen=True)
class AiPrefilterEstimate:
    """Rough cost estimate of a ``crapai jev-prefilter`` run (ADR 0029).

    Jev pricing has no output cost (``usage.cost`` in the published pricing is input-tokens
    only), so unlike :class:`ProjectEstimate` there is a single cost figure, not a worst/likely
    case -- the character-based estimate already errs high (:class:`CharTokenizer`'s safety
    factor), so no further band is added.

    Attributes:
        n_items: Records that would be offered to Jev (no exclusion reason yet).
        tokens_in: Estimated input tokens across all of them (title + abstract + instructions).
        cost: Estimated USD cost, or None if the model has no price in ``pricing.csv``.
        price_file_found: Whether the project has a ``pricing.csv``.
    """

    n_items: int
    tokens_in: int
    cost: float | None
    price_file_found: bool


def estimate_ai_prefilter(workspace: Workspace) -> AiPrefilterEstimate:
    """Estimate the input tokens and cost of running the Jev pre-filter on this project now.

    Raises:
        ConfigError: E203 if ``project.yaml`` or ``pricing.csv`` is unusable.
        StorageError: E404 for a folder that is no project or a damaged ``records.csv``.
    """
    workspace = Workspace.open(workspace.root)
    config = load_project_config(workspace.project_yaml)
    records = read_records(workspace.records_csv)
    targets = eligible_for_ai_prefilter(records)
    tokenizer = CharTokenizer()
    instructions_tokens = tokenizer.count(criteria_text(config))
    tokens_in = sum(tokenizer.count(f"{r.title}\n{r.abstract}") for r in targets)
    tokens_in += instructions_tokens * len(targets)
    price, found = find_price(workspace, "typesafe", config.ai_prefilter.model)
    cost = tokens_in / 1000 * price.input_per_1k if price is not None else None
    return AiPrefilterEstimate(
        n_items=len(targets), tokens_in=tokens_in, cost=cost, price_file_found=found
    )


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
    if config.project.mode == "fulltext" and config.screening.fulltext.strategy == "map_reduce":
        # Mirrors screen_project()'s own refusal (ADR 0026): the engine does not implement
        # map_reduce yet, so an estimate for it would be an estimate for a run that cannot
        # actually start -- misleading, not merely incomplete.
        raise ConfigError(
            "screening.fulltext.strategy 'map_reduce' is not implemented yet",
            code="E203",
            hint="Use 'truncate' or 'sections' for full-text screening.",
        )
    records = read_records(workspace.records_csv)
    provider, model = config.llm.provider, config.llm.model
    tokenizer = tokenizer_for(provider, model)
    if config.project.mode == "fulltext":
        items = _fulltext_items(records, config, workspace, tokenizer)
    else:
        items = _abstract_items(records, config)
    builder = builder_for(config, workspace.prompts_dir)
    shared_text = builder.system + "\n\n" + builder.prefix
    price, found = find_price(workspace, provider, model)
    estimate = estimate_run(
        items,
        shared_text,
        tokenizer,
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
