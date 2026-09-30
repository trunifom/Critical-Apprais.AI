from typing import List, Dict, Any, Optional, Sequence
import streamlit as st
from i18n import I18n  # <- tiny loader (YAML + Python fallback)
from pathlib import Path

from core.preflight import PreflightFileResult
from core.estimator import (
    TokenEstimator,
    EstimatorConfig,
    CharTokenizer,
    TiktokenTokenizer,
    StaticPriceSource,
    CSVPriceSource
)

# Optional model pricing (for cost estimate UI). If not configured, we still show tokens.
MODEL_PRICE_INPUT_PER_1K  = st.secrets.get("model_params", {}).get("price_input_per_1k", None)
MODEL_PRICE_OUTPUT_PER_1K = st.secrets.get("model_params", {}).get("price_output_per_1k", None)
EST_OUTPUT_TOKENS_PER_ITEM = st.secrets.get("model_params", {}).get("estimated_output_tokens_per_item", 120)
PRICING_CSV_PATH           = st.secrets.get("model_params", {}).get("pricing_csv_path", None)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers: estimate panel + shared payload
# ──────────────────────────────────────────────────────────────────────────────
def render_estimate_metrics(i18n: I18n, summary: Optional[Dict[str, Any]]) -> None:
    """Render the estimate panel with dashes when summary is None."""
    st.subheader(i18n.t("estimate.header"))

    if not summary:
        colA, colB, colC, colD = st.columns(4)
        colA.metric(i18n.t("estimate.input_tokens"), "–")
        colB.metric(i18n.t("estimate.output_tokens"), "–")
        colC.metric(i18n.t("estimate.total_tokens"), "–")
        colD.metric(i18n.t("estimate.cost_range"), "–")
        st.caption(i18n.t("estimate.note"))
        return

    colA, colB, colC, colD = st.columns(4)
    colA.metric(i18n.t("estimate.input_tokens"), f"{summary['input_tokens']:,}")
    colB.metric(i18n.t("estimate.output_tokens"), f"{summary['output_tokens']:,}")
    colC.metric(i18n.t("estimate.total_tokens"), f"{summary['total_tokens']:,}")
    cost_display = "–"
    if summary.get("cost_range"):
        low, high = summary["cost_range"]
        currency = summary.get("currency") or ""
        cost_display = f"{low:,.2f}–{high:,.2f} {currency}"
    colD.metric(i18n.t("estimate.cost_range"), cost_display)
    st.caption(i18n.t("estimate.note"))

def build_shared_payload_for_estimate(
    estimator: TokenEstimator,
    criteria: Any,
    project_title: str,
    project_desc: str,
    objectives: Sequence[str],
    prompt_text: str,
) -> str:
    try:
        criteria_text = criteria.to_prompt_string()
    except Exception:
        criteria_text = ""

    return estimator.build_shared_payload(
        criteria_text=criteria_text,
        project_title=project_title,
        project_desc=project_desc,
        objectives=objectives,
        prompt_template=prompt_text,
        include_parts=None,
    )


def render_preflight_table(i18n: I18n, rows: List[PreflightFileResult], mode: str) -> int:
    """
    Render the preflight results table and return total records across rows.

    Args:
        i18n (I18n): The i18n instance for translation.
        rows (List[PreflightFileResult]): The preflight results to display.
        mode (str): The mode of the preflight (e.g., "full" or "abstract").

    Returns:
        int: The total number of records across all rows.
    """
    if not rows:
        return 0

    st.subheader(i18n.t("preflight.header"))
    is_abstract = mode.lower() == "abstract"

    # (label_key, column_width)
    headers = [
        ("preflight.table.headers.filename", 3),
        ("preflight.table.headers.label", 2),
        ("preflight.table.headers.records", 2),
    ]
    if is_abstract:
        headers.append(("preflight.table.headers.with_abstract", 2))
    headers.append(("preflight.table.headers.status", 2))

    # Header
    widths = [w for _, w in headers]
    for col, (key, _) in zip(st.columns(widths), headers):
        col.markdown(f"**{i18n.t(key)}**")

    # Rows
    status_class = {
        "ok": "status-ok",
        "warning": "status-warn",
        "error": "status-err",
    }

    total = 0
    for res in rows:
        total += int(res.records_total)
        cols = st.columns(widths)

        col_idx = 0
        cols[col_idx].write(res.filename); col_idx += 1
        cols[col_idx].write(res.label); col_idx += 1
        cols[col_idx].write(f"{res.records_total}"); col_idx += 1
        if is_abstract:
            cols[col_idx].write(f"{getattr(res, 'records_with_abstract', '')}"); col_idx += 1

        msg_key = res.message_keys[-1] if res.message_keys else "preflight.status.ok"
        cls = status_class.get(getattr(res.status, "value", "ok"), "status-ok")
        cols[col_idx].markdown(f"<span class='{cls}'>{i18n.t(msg_key)}</span>", unsafe_allow_html=True)

    # Single caption for both modes
    st.caption(i18n.t("preflight.note"))
    return total

# ──────────────────────────────────────────────────────────────────────────────
# Estimator & price source from secrets (UI-only best effort)
# ──────────────────────────────────────────────────────────────────────────────
def make_estimator() -> TokenEstimator:
    """
    Build a TokenEstimator with a tokenizer and optional pricing source.
    - Tokenizer: try tiktoken for OpenAI-compatible models; fallback to CharTokenizer.
    - Price source: use CSV if provided, otherwise static prices (if configured).
    """
    # 1) tokenizer
    # If you know your model uses OpenAI encodings, use TiktokenTokenizer;
    # else default to CharTokenizer (simple, offline).
    try:
        tokenizer = TiktokenTokenizer("cl100k_base")  # safe for many GPT-family models
    except Exception:
        tokenizer = CharTokenizer()

    # 2) price source (optional)
    price_source = None
    if PRICING_CSV_PATH:
        price_source = CSVPriceSource(PRICING_CSV_PATH)
    elif MODEL_PRICE_INPUT_PER_1K is not None and MODEL_PRICE_OUTPUT_PER_1K is not None:
        price_source = StaticPriceSource(
            input_per_1k=float(MODEL_PRICE_INPUT_PER_1K),
            output_per_1k=float(MODEL_PRICE_OUTPUT_PER_1K),
            currency="CHF"  # Adjust to your project default currency
        )

    cfg = EstimatorConfig(
        tokenizer=tokenizer,
        price_source=price_source,
        shared_mode="per_item",                # assume one request per item for the UI preview
        output_tokens_per_item=EST_OUTPUT_TOKENS_PER_ITEM,
        cost_uncertainty=0.15                  # ±15% range
    )
    return TokenEstimator(cfg)

# ──────────────────────────────────────────────────────────────────────────────
# i18n wiring (strictly separate text from logic)
# ──────────────────────────────────────────────────────────────────────────────
def get_i18n() -> I18n:
    """
    Create the loader pointing to project root (folder that contains texts/).
    If this file is at project_root/pages/review_setup.py, parents[1] is project_root.
    """
    project_root = Path(__file__).resolve().parents[1]
    return I18n(base_dir=str(project_root))


def warn_if_missing_texts(i18n: I18n) -> None:
    """
    Non-fatal validation: warn about missing keys, but do not st.stop().
    This avoids the 'render only first section' issue if YAML is incomplete.
    """
    REQUIRED = [
        # Page
        "sections.page.title",
        "sections.page.subtitle",
        # Project
        "sections.project.header",
        "sections.project.fields.title.label",
        "sections.project.fields.title.placeholder",
        "sections.project.fields.title.help",
        "sections.project.fields.description.label",
        "sections.project.fields.description.placeholder",
        "sections.project.fields.description.help",
        # Screening
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
        # Upload abstract
        "sections.upload.abstract.header",
        "sections.upload.abstract.instructions",
        "sections.upload.abstract.file_type.label",
        "sections.upload.abstract.file_type.options",
        "sections.upload.abstract.file_uploader.label",
        "sections.upload.abstract.database_names_header",
        "sections.upload.abstract.database_field.label",
        "sections.upload.abstract.database_field.placeholder",
        "sections.upload.abstract.database_field.help",
        # Upload fulltext
        "sections.upload.fulltext.header",
        "sections.upload.fulltext.instructions",
        "sections.upload.fulltext.file_type.label",
        "sections.upload.fulltext.file_type.options",
        "sections.upload.fulltext.file_uploader.label",
        "sections.upload.fulltext.database_names_header",
   
        # Preflight summary (new)
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
        # Estimation (new)
        "estimate.header",
        "estimate.input_tokens",
        "estimate.output_tokens",
        "estimate.total_tokens",
        "estimate.cost_range",
        "estimate.note",
        # Start
        "sections.start.confirm_label",
        "sections.start.button_label",
        "sections.start.total_records_preview",
        # Notifications
        "notifications.parse_error",
        "notifications.review_started",
        "notifications.log_failed",
        "notifications.background_info",
    ]
    missing = i18n.validate(REQUIRED)
    if missing:
        st.warning(
            "Missing text keys (served from Python fallback where possible):\n"
            + "\n".join(f"- `{m}`" for m in missing)
        )