"""Text keys that the user interface and the command line rely on (plan chapter 27.7).

The list replaces the predecessor's ``REQUIRED`` list in ``warn_if_missing_texts``. A test checks
that every key exists in **both** languages, so a missing translation is found in development and
not by a user. Keys that only exist for one page are listed by page; per-error texts are derived
from the error catalogue.
"""

from __future__ import annotations

PAGE_KEYS: tuple[str, ...] = (
    # Setup sections carried over from the predecessor's page
    "sections.page.title",
    "sections.page.subtitle",
    "sections.project.header",
    "sections.project.fields.title.label",
    "sections.project.fields.title.placeholder",
    "sections.project.fields.title.help",
    "sections.project.fields.description.label",
    "sections.project.fields.description.placeholder",
    "sections.project.fields.description.help",
    "sections.screening.header",
    "sections.screening.review_mode.label",
    "sections.screening.review_mode.options",
    "sections.screening.review_mode.help",
    "sections.screening.objectives.count_label",
    "sections.screening.objectives.count_help",
    "sections.screening.objectives.list_header",
    "sections.screening.objectives.item_label",
    "sections.screening.framework.label",
    "sections.screening.framework.options",
    "sections.screening.framework.help",
    "sections.screening.frameworks_info",
    "sections.screening.custom_criteria.subheader",
    "sections.screening.custom_criteria.field_name_label",
    "sections.screening.custom_criteria.add_button",
    "sections.screening.custom_criteria.remove_button",
    "sections.screening.inclusion_exclusion.subheader",
    "sections.screening.inclusion_exclusion.inclusion_label",
    "sections.screening.inclusion_exclusion.exclusion_label",
    "sections.upload.abstract.header",
    "sections.upload.abstract.instructions",
    "sections.upload.abstract.file_type.label",
    "sections.upload.abstract.file_type.options",
    "sections.upload.abstract.file_uploader.label",
    "sections.upload.abstract.database_names_header",
    "sections.upload.abstract.database_field.label",
    "sections.upload.abstract.database_field.placeholder",
    "sections.upload.abstract.database_field.help",
    "sections.start.confirm_label",
    "sections.start.button_label",
    "sections.start.total_records_preview",
    "preflight.header",
    "preflight.table.headers.filename",
    "preflight.table.headers.label",
    "preflight.table.headers.records",
    "preflight.table.headers.with_abstract",
    "preflight.table.headers.status",
    "preflight.status.ok",
    "preflight.status.warn_low_abstracts",
    "preflight.status.error_unparseable",
    "preflight.status.error_no_records",
    "preflight.status.error_no_abstracts",
    "preflight.note",
    "estimate.header",
    "estimate.input_tokens",
    "estimate.output_tokens",
    "estimate.total_tokens",
    "estimate.cost_range",
    "estimate.note",
    "notifications.parse_error",
    "notifications.review_started",
    "notifications.log_failed",
    "notifications.background_info",
    # Pages of the local interface (plan chapter 27.3)
    "nav.start",
    "nav.project",
    "nav.criteria",
    "nav.data",
    "nav.run",
    "nav.results",
    "nav.prisma",
    "nav.evaluation",
    "nav.settings",
    "nav.help",
    "common.ai_notice",
    "common.sensitivity_notice",
    "start.title",
    "start.tagline",
    "start.purpose",
    "start.limits.text",
    "criteria_assistant.completeness",
    "criteria_assistant.prompt_preview",
    "criteria_assistant.trial_button",
    "data.header",
    "data.overview.records",
    "data.overview.valid",
    "run.header",
    "run.confirm",
    "run.start",
    "run.progress",
    "run.interrupted",
    "results.header",
    "results.detail.unusable",
    "prisma.header",
    "evaluation.header",
    "evaluation.sensitivity_hint",
    "settings.header",
    "settings.key.never_stored",
    "help.header",
    # Command line
    "cli.init.done",
    "cli.import.done",
    "cli.status.records",
    "cli.error.prefix",
    "cli.error.cause",
    "cli.error.details",
    "cli.error.action",
    "cli.error.unexpected",
)

# Codes of the error catalogue (plan chapter 26.4); each needs title, cause and action.
ERROR_CODES: tuple[str, ...] = (
    "E101", "E102", "E103", "E104", "E105", "E106",
    "E201", "E202", "E203",
    "E301", "E302", "E303", "E304", "E305", "E306", "E307",
    "E401", "E402", "E403", "E404",
    "E501", "E502",
    "E999",
)  # fmt: skip
ERROR_PARTS: tuple[str, ...] = ("title", "cause", "action")


def error_keys() -> tuple[str, ...]:
    """All ``errors.<code>.<part>`` keys the catalogue requires."""
    return tuple(f"errors.{code}.{part}" for code in ERROR_CODES for part in ERROR_PARTS)


def required_keys() -> tuple[str, ...]:
    """Every key that must exist in every language."""
    return PAGE_KEYS + error_keys()
