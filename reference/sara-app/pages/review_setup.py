# pages/review_setup.py
# -*- coding: utf-8 -*-
"""
Streamlit page: Criteria builder → file upload → preflight checks → start background run.

This page is refactored into modular functions to improve readability, maintainability,
and testability. The `main` function acts as an orchestrator, calling UI and logic
functions in a clear sequence.
"""

from __future__ import annotations

import os
import json
import uuid
import tempfile
import io
import zipfile
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pytz import timezone
import pandas as pd
import streamlit as st
from supabase import create_client, Client
from streamlit_lottie import st_lottie

from utils.login_manager import LoginManager
from utils.helpers import load_prompt_template
from utils.ui_helpers import (
    render_estimate_metrics,
    build_shared_payload_for_estimate,
    render_preflight_table,
    make_estimator,
    get_i18n,
    warn_if_missing_texts
)

from core.literature_database import LiteratureDatabase
from core.criteria_template import CriteriaTemplate
from core.file_handler import BibliographicConverter
from core.database import TaskUploader, TaskLogger
from core.prisma_workflow import PRISMAWorkflow
from core.preflight import PreflightService, PreflightConfig, PreflightFileResult

# --- Constants and Clients (loaded once at module level) ---
SUPABASE_URL = st.secrets["urls"]["supabase_url"]
SUPABASE_KEY = st.secrets["api_keys"]["supabase_key"]
MODEL = st.secrets["model_params"]["model"]
MODEL_PROVIDER = st.secrets.get("model_params", {}).get("provider", "openai")
LOTTIE_PATH = st.secrets["lottie"]["path"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
login_manager = LoginManager(supabase)

# ──────────────────────────────────────────────────────────────────────────────
# Refactored UI and Logic Functions
# ──────────────────────────────────────────────────────────────────────────────

def slugify(value: str) -> str:
    """
    Sanitizes a string to be safe for file and directory names.

    - Converts to lowercase.
    - Removes characters invalid in Windows/Linux file systems.
    - Replaces spaces and consecutive hyphens with a single hyphen.
    - Strips leading/trailing hyphens.
    - Truncates to a reasonable length (100 chars).
    """
    value = str(value).lower()
    # Remove invalid filesystem characters
    value = re.sub(r'[<>:"/\\|?*]', '', value)
    # Replace spaces and other separators with a single hyphen
    value = re.sub(r'[\s_]+', '-', value)
    # Remove consecutive hyphens
    value = re.sub(r'-+', '-', value)
    # Trim leading/trailing hyphens and truncate
    value = value.strip('-')[:100]
    return value

def setup_page(i18n) -> None:
    """
    Initializes the page: CSS, authentication, header, and Lottie animation.
    """
    st.markdown("""
    <style>
    div.stButton > button { width: 100%; height: 3em; font-size: 1.1em; }
    .status-ok {color: #2e7d32; font-weight: 600;}
    .status-warn {color: #f9a825; font-weight: 600;}
    .status-err {color: #c62828; font-weight: 600;}
    </style>
    """, unsafe_allow_html=True)

    login_manager.check_authentication()

    try:
        with open(LOTTIE_PATH, "r", encoding="utf-8") as f:
            lottie_data = json.load(f)
    except Exception:
        lottie_data = None

    c1, c2 = st.columns([3, 1])
    with c1:
        st.title(i18n.t("sections.page.title"))
        st.caption(i18n.t("sections.page.subtitle"))
    with c2:
        if lottie_data:
            st_lottie(lottie_data, speed=1, height=120, key="lottie_top")

def render_project_info_ui(i18n) -> Tuple[str, str]:
    """Renders UI for project title and description, returning the inputs."""
    st.header(i18n.t("sections.project.header"))
    with st.container(border=True):
        project_title = st.text_input(
            i18n.t("sections.project.fields.title.label"),
            placeholder=i18n.t("sections.project.fields.title.placeholder"),
            help=i18n.t("sections.project.fields.title.help"),
        )
        project_desc = st.text_area(
            i18n.t("sections.project.fields.description.label"),
            placeholder=i18n.t("sections.project.fields.description.placeholder"),
            help=i18n.t("sections.project.fields.description.help"),
        )
    return project_title, project_desc

def render_criteria_ui(i18n, lang: str) -> Tuple[str, CriteriaTemplate, List[str]]:
    """Renders UI for screening criteria, returning mode, criteria object, and objectives."""
    st.header(i18n.t("sections.screening.header"))
    with st.container(border=True):
        mode = st.radio(
            i18n.t("sections.screening.review_mode.label"),
            options=i18n.lst("sections.screening.review_mode.options"),
            index=0, help=i18n.t("sections.screening.review_mode.help"),
        )
        n_objectives = st.number_input(
            i18n.t("sections.screening.objectives.count_label"),
            min_value=1, max_value=10, value=1, step=1,
            help=i18n.t("sections.screening.objectives.count_help"),
        )
        framework = st.selectbox(
            i18n.t("sections.screening.framework.label"),
            options=i18n.lst("sections.screening.framework.options"),
            help=i18n.t("sections.screening.framework.help"),
        )
        st.info(i18n.t("sections.screening.frameworks_info"))

        st.subheader(i18n.t("sections.screening.objectives.list_header"))
        objectives = [st.text_input(i18n.tf("sections.screening.objectives.item_label", index=i + 1), key=f"objective_{i}") for i in range(int(n_objectives))]

        custom_fields = []
        if framework == "CUSTOM":
            st.subheader(i18n.t("sections.screening.custom_criteria.subheader"))
            new_field = st.text_input(i18n.t("sections.screening.custom_criteria.field_name_label"), key="custom_input")
            if st.button(i18n.t("sections.screening.custom_criteria.add_button"), key="add_custom_field"):
                selected = st.session_state.get("custom_fields", [])
                if new_field and new_field not in selected:
                    selected.append(new_field)
                    st.session_state.custom_fields = selected
            for idx, fld in enumerate(st.session_state.get("custom_fields", [])):
                c1, c2 = st.columns([4, 1])
                with c1: st.write(f"- {fld}")
                with c2:
                    if st.button(i18n.t("sections.screening.custom_criteria.remove_button"), key=f"remove_{idx}"):
                        st.session_state.custom_fields.remove(fld)
                        st.rerun()
            custom_fields = st.session_state.get("custom_fields", [])

        criteria = CriteriaTemplate(template_type=framework, custom_fields=custom_fields, lang=lang)
        st.subheader(i18n.t("sections.screening.inclusion_exclusion.subheader"))
        for field in criteria.inclusion.keys():
            col_inc, col_exc = st.columns(2)
            with col_inc:
                criteria.update_inclusion(field, st.text_input(i18n.tf("sections.screening.inclusion_exclusion.inclusion_label", field=field), key=f"inc_{field}"))
            with col_exc:
                criteria.update_exclusion(field, st.text_input(i18n.tf("sections.screening.inclusion_exclusion.exclusion_label", field=field), key=f"exc_{field}"))

    return mode, criteria, objectives

def render_upload_and_preflight_ui(i18n, mode: str, criteria: CriteriaTemplate, project_title: str, project_desc: str, objectives: List[str]) -> Tuple[List[Any], List[str], List[PreflightFileResult]]:
    """Renders file upload, labeling, preflight, and cost estimation. Returns uploaded files, labels, and preflight results."""
    uploaded_items, labels, preflight_rows = [], [], []
    estimator = make_estimator()

    if mode == "Abstract":
        st.header(i18n.t("sections.upload.abstract.header"))
        with st.container(border=True):
            st.write(i18n.t("sections.upload.abstract.instructions"))
            file_type = st.radio(i18n.t("sections.upload.abstract.file_type.label"), options=i18n.lst("sections.upload.abstract.file_type.options"), index=0, key="file_type")
            uploaded_items = st.file_uploader(i18n.t("sections.upload.abstract.file_uploader.label"), type=file_type.strip("."), accept_multiple_files=True, key="file_uploader")

            if uploaded_items:
                st.markdown(i18n.t("sections.upload.abstract.database_names_header"))
                for idx, uploaded in enumerate(uploaded_items):
                    default_label = os.path.splitext(uploaded.name)[0]
                    key = f"abstract_label_{idx}"
                    labels.append(st.text_input(i18n.tf("sections.upload.abstract.database_field.label", filename=uploaded.name), key=key, placeholder=i18n.t("sections.upload.abstract.database_field.placeholder"), help=i18n.t("sections.upload.abstract.database_field.help"), value=st.session_state.get(key, default_label)))

                pf_service = PreflightService(PreflightConfig(min_abstract_ratio_warn=0.60))
                preflight_rows = pf_service.analyze_many(uploaded_items, labels, mode)
                render_preflight_table(i18n, preflight_rows, mode=mode)
                st.markdown("---")

                prompt_text = load_prompt_template("abstract")
                shared_payload = build_shared_payload_for_estimate(estimator, criteria, project_title, project_desc, objectives, prompt_text)
                shared_tokens = estimator.estimate_shared_tokens(shared_payload, batch_size=1)
                per_item_tokens = estimator.estimate_per_item_tokens_from_samples(titles=[], abstracts=[], sample_size=20)
                n_items = sum(r.records_total for r in preflight_rows)
                summary = estimator.estimate_run(n_items=n_items, per_item_input_tokens=per_item_tokens, shared_tokens=shared_tokens, provider=MODEL_PROVIDER, model=MODEL)
                render_estimate_metrics(i18n, summary)

    elif mode == "Fulltext":
        st.header(i18n.t("sections.upload.fulltext.header"))
        with st.container(border=True):
            st.write(i18n.t("sections.upload.fulltext.instructions"))
            uploaded_archive = st.file_uploader(i18n.t("sections.upload.fulltext.file_uploader.label"), type="zip", accept_multiple_files=False, key="fulltext_uploader")
            if uploaded_archive:
                uploaded_items = [uploaded_archive]
                default_label = os.path.splitext(getattr(uploaded_archive, "name", "uploaded.zip"))[0]
                key = "fulltext_zip_label"
                labels.append(st.text_input(i18n.tf("sections.upload.fulltext.database_field.label", filename=getattr(uploaded_archive, "name", "uploaded.zip")), key=key, placeholder=i18n.t("sections.upload.fulltext.database_field.placeholder"), help=i18n.t("sections.upload.fulltext.database_field.help"), value=st.session_state.get(key, default_label)))

                pf_service = PreflightService(PreflightConfig())
                preflight_rows = pf_service.analyze_many(uploaded_items, labels, mode)
                n_records = render_preflight_table(i18n, preflight_rows, mode=mode)
                st.markdown("---")

                prompt_text = load_prompt_template("fulltext")
                shared_payload = build_shared_payload_for_estimate(estimator, criteria, project_title, project_desc, objectives, prompt_text)
                shared_tokens = estimator.estimate_shared_tokens(shared_payload, batch_size=1) * 2
                summary = estimator.estimate_run(per_item_input_tokens=450 * 12, shared_tokens=shared_tokens, n_items=n_records, provider=MODEL_PROVIDER, model=MODEL)
                render_estimate_metrics(i18n, summary)

    return uploaded_items, labels, preflight_rows

def handle_review_start(i18n, mode: str, project_title: str, criteria: CriteriaTemplate, objectives: List[str], uploaded_items: List[Any], labels: List[str]):
    """Processes uploaded files, creates a task in Supabase, and notifies the user."""
    file_info = {}
    record_count = 0
    uploader = TaskUploader(supabase)
    file_id = str(uuid.uuid4())

    # --- FIX: Sanitize project title before using it for filesystem operations ---
    sanitized_project_title = slugify(project_title)

    with st.spinner(i18n.t("notifications.processing_files")):
        if mode == "Abstract":
            db_instances = []
            for uploaded, lbl in zip(uploaded_items, labels):
                suffix = os.path.splitext(uploaded.name)[1]
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded.getbuffer())
                        tmp_path = tmp.name
                    
                    conv = BibliographicConverter(tmp_path, file_type=suffix.lstrip("."))
                    df = conv.to_dataframe()

                    # Add metadata columns directly to each dataframe
                    df["file_name"] = uploaded.name
                    df["source_label"] = lbl

                    # --- FIX: Sanitize label before using it in LiteratureDatabase ---
                    sanitized_label = slugify(lbl)
                    db = LiteratureDatabase(label=sanitized_label, dataframe=df, user_defined_source=lbl, source_file_name=uploaded.name, import_time=datetime.now(timezone(st.secrets['time']['timezone'])))
                    db_instances.append(db)
                except Exception as e:
                    st.error(i18n.tf("notifications.parse_error", filename=uploaded.name, error=e))
                    return
                finally:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.remove(tmp_path)

            workflow = st.session_state.get("workflow", PRISMAWorkflow(project_label=sanitized_project_title))
            for db in db_instances:
                workflow.add_source(db)
            st.session_state.workflow = workflow
            
            merged_df = workflow.merge_sources().get_dataframe()
            file_info = uploader.upload_dataframe(merged_df, file_id)
            record_count = len(merged_df)

        else:  # Fulltext mode
            arch = uploaded_items[0]
            fulltext_arch_name = getattr(arch, "name", "uploaded.zip")
            try:
                fulltext_arch_bytes = arch.getvalue()
                with zipfile.ZipFile(io.BytesIO(fulltext_arch_bytes)) as zf:
                    pdf_files = [name for name in zf.namelist() if not name.endswith('/') and not name.startswith('__MACOSX/') and not os.path.basename(name).startswith('._') and name.lower().endswith('.pdf')]
                    record_count = len(pdf_files)
                file_info = uploader.upload_archive(fulltext_arch_bytes, fulltext_arch_name, file_id, record_count=record_count)
            except Exception as e:
                st.error(i18n.tf("notifications.parse_error", filename=fulltext_arch_name, error=e))
                return

    # --- Common Logic: Log task to Supabase ---
    try:
        with st.spinner(i18n.t("notifications.creating_task")):
            logger = TaskLogger(supabase)
            data_type_value = "abstracts" if mode == "Abstract" else "fulltext"
            config_info = uploader.upload_prompt_config(criteria=criteria.to_prompt_string(), objectives=objectives, file_id=file_id, data_type=data_type_value)
            logger.log_task(file_id, file_info, config_info)

        user_email = st.session_state.get("user", {}).get("email") or "your registered e-mail address"
        st.success(i18n.tf("notifications.review_started", file_id=file_id))
        st.info(i18n.tf("notifications.background_info", email=user_email, total=record_count))
    except Exception as e:
        st.error(i18n.tf("notifications.log_failed", error=e))
        st.exception(e)

# ──────────────────────────────────────────────────────────────────────────────
# Main Orchestrator
# ──────────────────────────────────────────────────────────────────────────────
def main():
    """
    Main function to orchestrate the Streamlit page.
    It calls modular UI and logic functions in a clear sequence.
    """
    # 1. Initialize page and language
    lang = st.session_state.get("lang", "en")
    i18n = get_i18n()
    i18n.load(lang)
    warn_if_missing_texts(i18n)

    # 2. Render UI components and gather user inputs
    setup_page(i18n)
    project_title, project_desc = render_project_info_ui(i18n)
    mode, criteria, objectives = render_criteria_ui(i18n, lang)
    uploaded_items, labels, preflight_rows = render_upload_and_preflight_ui(i18n, mode, criteria, project_title, project_desc, objectives)

    # 3. Render the final "Start Review" section
    st.subheader(i18n.t("sections.start.button_label"))

    # Determine if the start button should be enabled
    labels_ok = all(lbl.strip() for lbl in labels) if labels else False
    preflight_ok = all(r.status.value != "error" for r in preflight_rows) if preflight_rows else False
    can_start = bool(project_title) and uploaded_items and labels_ok and any(obj.strip() for obj in objectives) and preflight_ok

    confirmed = st.checkbox(i18n.t("sections.start.confirm_label"), value=False, disabled=not can_start)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button(i18n.t("sections.start.button_label"), disabled=not (can_start and confirmed)):
            # 4. Execute the backend logic upon button click
            handle_review_start(i18n, mode, project_title, criteria, objectives, uploaded_items, labels)

if __name__ == "__main__":
    main()
