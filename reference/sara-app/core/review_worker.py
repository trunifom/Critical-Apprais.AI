"""
ReviewWorker - background processing and notification with PRISMA integration.

This module implements a background worker that:
- fetches pending review tasks from Supabase,
- marks them as 'processing' and notifies the user with internationalized emails,
- converts input files into a standardized LiteratureDatabase container,
- orchestrates a PRISMA-compliant workflow (via PRISMAWorkflow),
- logs all steps to a PRISMA 2020 audit log (via PRISMALogger),
- runs model inference for valid records only (via AsyncModelInference),
- stores raw responses, audit logs and CSV results back to Supabase storage,
- notifies users about result availability using SMTP (fallback to MailerSend),
- sends a BCC of all emails to a configurable address for archival.

Key principles:
- No destructive operations on the dataset. Duplicates and missing abstracts are marked, not removed.
- A stable per-row identifier (study_uid) is used to re-align model results to the correct row.
- Full transparency via PRISMA audit logging and an exportable PRISMA flow summary.

Operational hardening:
- Uses 'upsert': 'true' for Storage uploads to avoid conflict errors.
- Performs an optional Storage permission probe at startup (warns early if writes are not allowed).
- Emits actionable error messages when Storage writes fail due to RLS (403).
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from supabase import Client
from storage3.exceptions import StorageApiError  # for clearer handling of Storage RLS errors

from core.literature_database import (
    LiteratureDatabase,
    DEFAULT_ABSTRACT_COLUMN,
    DEFAULT_TITLE_COLUMN,
)
from core.prisma_workflow import PRISMAWorkflow
from core.prisma_logger import PRISMALogger
from core.model_query import AsyncModelInference
from utils.helpers import extract_text_from_pdf_bytes
from background.mail_adapter import create_mailer_from_env_or_dict
from i18n import I18n

LOG = logging.getLogger(__name__)


# ----------------------------- Secrets / Configuration -------------------------------

def _get_secret(section: Optional[str], key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a secret value from Streamlit secrets or environment variables."""
    try:
        if hasattr(st, "secrets"):
            if section:
                return st.secrets.get(section, {}).get(key, default)
            return st.secrets.get(key, default)
    except Exception:
        pass
    env_key = f"{section.upper()}_{key.upper()}" if section else key.upper()
    return os.environ.get(env_key, default)


PROMPT_TYPE_ABSTRACT = _get_secret("prompt_params", "prompt_type_abstract")
PROMPT_TYPE_FULLTEXT = _get_secret("prompt_params", "prompt_type_fulltext")


# ------------------------------------ Worker ----------------------------------------

class ReviewWorker:
    """
    Background worker that processes queued review tasks with PRISMA compliance.

    Responsibilities:
    - Task lifecycle updates and user notifications (i18n-aware),
    - Data ingestion into LiteratureDatabase,
    - PRISMA workflow orchestration and audit logging,
    - Model inference for valid records and result alignment,
    - Storing artifacts (raw responses, CSV results, PRISMA flow log).
    """
    POLL_INTERVAL = 300
    TASKS_BUCKET = "review-tasks"
    RESULTS_BUCKET = "review-results"
    RAW_RESPONSES_FOLDER = "raw_responses"
    RESULTS_FOLDER = "results"

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        openai_key: str,
        prompts_path: str,
        i18n: I18n,
        mailersend_key: Optional[str] = None,
        smtp_secrets: Optional[dict] = None,
        poll_interval: int = POLL_INTERVAL,
        sender_email: Optional[str] = None,
        bcc_recipient: Optional[str] = None,
    ) -> None:
        LOG.info("Initializing ReviewWorker...")

        # Supabase client (project uses a Client-ctor shim; keep as-is for compatibility)
        self.supabase = Client(supabase_url, supabase_key)

        # AI / prompts
        self.openai_key = openai_key
        self.prompts_path = prompts_path

        # i18n templates for emails
        self.i18n = i18n

        # Email settings and services
        self.mailersend_key = mailersend_key
        self.poll_interval = poll_interval
        self.sender_email = sender_email or _get_secret("smtp", "sender", "noreply@sara-app.com")
        self.bcc_recipient = bcc_recipient or self.sender_email

        # SMTP mailer (gracefully fall back to MailerSend)
        try:
            self.mailer = create_mailer_from_env_or_dict(smtp_secrets)
            LOG.info("✅ SMTP mailer initialized successfully.")
        except Exception as exc:
            self.mailer = None
            LOG.warning("⚠️ SMTP mailer could not be initialized: %s. Will use MailerSend as fallback.", exc)

        # PRISMA runtime registries (per-task instances)
        self.prisma_workflows: Dict[str, PRISMAWorkflow] = {}
        self.prisma_loggers: Dict[str, PRISMALogger] = {}

        # Early permission probe for Storage writes (helps fail fast if using ANON key or missing policies)
        self._storage_write_probe()

        LOG.info("BCC for all outgoing emails will be sent to: %s", self.bcc_recipient)
        LOG.info("ReviewWorker initialized and ready.")

    # ----------------------------- Permission probe ----------------------------------

    def _storage_write_probe(self) -> None:
        """
        Attempt a tiny upsert into RESULTS_BUCKET to detect missing write permissions early.
        Logs a clear, actionable error if RLS blocks writes.
        """
        probe_path = f".probes/{uuid.uuid4()}.json"
        try:
            self.supabase.storage.from_(self.RESULTS_BUCKET).upload(
                probe_path,
                b"{}",
                {"content-type": "application/json", "upsert": "true"},
            )
            # best effort cleanup; ignore failures
            try:
                self.supabase.storage.from_(self.RESULTS_BUCKET).remove(probe_path)
            except Exception:
                pass
        except StorageApiError as e:
            LOG.error(
                "Supabase Storage write probe failed for bucket '%s'. "
                "Likely cause: using ANON key or missing write policies. "
                "Run worker with SERVICE_ROLE key or add Storage policies. Error: %s",
                self.RESULTS_BUCKET, e,
            )
            # Do not raise here to allow development iterations, but this saves time later.
        except Exception as e:
            LOG.warning("Unexpected error during Storage permission probe: %s", e)

    # ----------------------------- DB status updates --------------------------------

    def _update_task_status(self, task_id: str, updates: Dict[str, Any]) -> None:
        """Generic method to update a task in the database."""
        updates["updated_at"] = datetime.utcnow().isoformat()
        try:
            self.supabase.table("review_tasks").update(updates).eq("file_id", task_id).execute()
        except Exception:
            LOG.exception("Failed to update status for task %s with updates: %s", task_id, updates)

    def mark_task_processing(self, task_id: str) -> None:
        """Mark a task as 'processing'."""
        LOG.info("Updating task %s status to 'processing'.", task_id)
        self._update_task_status(task_id, {"status": "processing"})

    def mark_task_complete(self, task_id: str, results_path: str) -> None:
        """Mark a task as 'completed'."""
        LOG.info("✅ Task %s processing finished. Marking as 'completed'.", task_id)
        self._update_task_status(task_id, {"status": "completed", "results_path": results_path})

    def mark_sending_complete(self, task_id: str) -> None:
        """Mark a task as 'email_sent'."""
        LOG.info("✅ Final notification for task %s sent. Marking as 'email_sent'.", task_id)
        self._update_task_status(task_id, {"status": "email_sent"})

    def mark_task_failed(self, task_id: str, reason: Optional[str] = None) -> None:
        """Mark a task as 'failed'."""
        LOG.error("❌ Task %s failed. Reason: %s", task_id, reason)
        self._update_task_status(task_id, {"status": "failed", "results_path": None, "fail_reason": reason})

    # ----------------------------- Data I/O methods ---------------------------------

    def fetch_pending_tasks(self) -> List[Dict[str, Any]]:
        """Fetch tasks with 'pending' status."""
        try:
            resp = self.supabase.table("review_tasks").select("*").eq("status", "pending").execute()
            return resp.data or []
        except Exception:
            LOG.exception("Failed to fetch pending tasks from Supabase.")
            return []

    def read_stored_config(self, file_path: str) -> Dict[str, Any]:
        """Download and parse JSON config from storage."""
        cfg_resp = self.supabase.storage.from_(self.TASKS_BUCKET).download(file_path)
        try:
            if isinstance(cfg_resp, (bytes, bytearray)):
                return json.loads(cfg_resp.decode("utf-8"))
            return json.loads(cfg_resp)
        except Exception:
            LOG.exception("Failed to parse JSON config at %s.", file_path)
            return {}

    def upload_file(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        """
        Upload bytes to a specified storage bucket, overwriting if the file exists.

        Uses 'upsert': 'true' so re-processing a task can update existing artifacts.
        Raises StorageApiError on permission issues, which is caught by the caller.
        """
        LOG.debug("Uploading %d bytes to %s at %s (upsert).", len(data), bucket, path)
        file_options = {"content-type": content_type, "upsert": "true"}
        self.supabase.storage.from_(bucket).upload(path, data, file_options)

    # ----------------------------- Email notifications ------------------------------

    def _send_generic_email(self, user_email: str, subject: str, text: str, html: str) -> bool:
        """
        Internal email sending logic with SMTP and MailerSend fallback.
        Automatically sends a BCC to the configured `bcc_recipient`.
        """
        bcc_list = [self.bcc_recipient] if self.bcc_recipient else None

        # Attempt SMTP first
        if self.mailer:
            try:
                self.mailer.send_email(to=[user_email], subject=subject, text=text, html=html, bcc=bcc_list)
                LOG.info(
                    "SMTP notification ('%s') sent to %s with BCC to %s.",
                    subject, user_email, self.bcc_recipient,
                )
                return True
            except Exception:
                LOG.exception("SMTP send failed for %s. Attempting MailerSend fallback.", user_email)

        # Fallback to MailerSend API
        if not self.mailersend_key:
            LOG.error("No MailerSend key configured and SMTP failed/unavailable. Cannot send email to %s.", user_email)
            return False

        headers = {"Authorization": f"Bearer {self.mailersend_key}", "Content-Type": "application/json"}
        bcc_payload = [{"email": self.bcc_recipient}] if self.bcc_recipient else []
        payload = {
            "from": {"email": self.sender_email, "name": "SARA"},
            "to": [{"email": user_email}],
            "bcc": bcc_payload,
            "subject": subject,
            "text": text,
            "html": html,
        }
        try:
            resp = requests.post("https://api.mailersend.com/v1/email", json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            LOG.info(
                "MailerSend notification ('%s') sent to %s with BCC to %s.",
                subject, user_email, self.bcc_recipient,
            )
            return True
        except requests.RequestException:
            LOG.exception("MailerSend fallback request failed for %s.", user_email)
            return False

    def send_processing_notification(self, user_email: str, project_title: str, task_id: str) -> bool:
        """Send an email notifying the user that their task is now being processed."""
        LOG.info("Sending 'processing' notification to %s for project '%s'.", user_email, project_title)
        subject = self.i18n.tf("emails.processing.subject", project_title=project_title)
        html_body = self.i18n.tf("emails.processing.html_body", project_title=project_title, task_id=task_id)
        text_body = self.i18n.tf("emails.processing.text_body", project_title=project_title, task_id=task_id)
        return self._send_generic_email(user_email, subject, text_body, html_body)

    def send_completion_notification(self, user_email: str, project_title: str, download_url: str, task_id: str) -> bool:
        """Send an email with the link to the results."""
        LOG.info("Sending 'completion' notification to %s for project '%s'.", user_email, project_title)
        subject = self.i18n.tf("emails.completion.subject", project_title=project_title)
        html_body = self.i18n.tf("emails.completion.html_body", project_title=project_title, download_url=download_url, task_id=task_id)
        text_body = self.i18n.tf("emails.completion.text_body", project_title=project_title, download_url=download_url, task_id=task_id)
        return self._send_generic_email(user_email, subject, text_body, html_body)

    # ----------------------------- PRISMA helpers -----------------------------------

    def _initialize_prisma_logger(self, task_id: str, project_title: str) -> PRISMALogger:
        """Create and register a PRISMALogger instance for this task."""
        logger = PRISMALogger(
            project_id=task_id,
            project_title=project_title,
            user_id=None,
            supabase_client=self.supabase,
        )
        self.prisma_loggers[task_id] = logger
        return logger

    def _initialize_prisma_workflow(self, task_id: str, project_label: str) -> PRISMAWorkflow:
        """Create and register a PRISMAWorkflow instance for this task."""
        wf = PRISMAWorkflow(project_label=project_label, log_dir=os.path.join(os.getcwd(), "prisma_logs"))
        self.prisma_workflows[task_id] = wf
        return wf

    def _generate_and_upload_prisma_flow(self, task_id: str) -> Optional[str]:
        """Generate PRISMA flow JSON and upload it to results storage. Returns path on success."""
        logger = self.prisma_loggers.get(task_id)
        if not logger:
            return None
        flow_json = json.dumps(logger.to_prisma_flow(), indent=2).encode("utf-8")
        path = f"{self.RESULTS_FOLDER}/{task_id}_prisma_flow.json"
        self.upload_file(self.RESULTS_BUCKET, path, flow_json, "application/json")
        return path

    def _cleanup_prisma_resources(self, task_id: str) -> None:
        """Remove PRISMA resources for a finished task."""
        if task_id in self.prisma_workflows:
            del self.prisma_workflows[task_id]
        if task_id in self.prisma_loggers:
            del self.prisma_loggers[task_id]

    # ----------------------------- Ingestion helpers --------------------------------

    def _create_literature_database_from_csv_bytes(
        self, file_bytes: bytes, source_label: str, file_name: str
    ) -> LiteratureDatabase:
        """
        Convert CSV bytes into a LiteratureDatabase with minimal normalization.
        - does not assume specific column names beyond common 'title' and 'abstract'.
        """
        df = pd.read_csv(io.BytesIO(file_bytes))
        # Tag the source for transparency and later multi-source workflows
        if "source_label" not in df.columns:
            df["source_label"] = source_label
        return LiteratureDatabase(
            label=source_label,
            dataframe=df,
            user_defined_source=source_label,
            source_file_name=file_name,
            import_time=datetime.utcnow(),
        )

    def _create_literature_database_from_zip_bytes(
        self, file_bytes: bytes, source_label: str, file_name: str
    ) -> LiteratureDatabase:
        """
        Convert a ZIP of PDFs into a LiteratureDatabase:
        - one row per PDF with title derived from filename and abstract as extracted full text.
        """
        rows: List[Dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            for name in z.namelist():
                if name.lower().endswith(".pdf") and not name.startswith("__MACOSX"):
                    with z.open(name) as fh:
                        text = extract_text_from_pdf_bytes(fh.read()) or ""
                        rows.append({
                            DEFAULT_TITLE_COLUMN: os.path.splitext(os.path.basename(name))[0],
                            DEFAULT_ABSTRACT_COLUMN: text,
                            "filename": os.path.basename(name),
                            "source_label": source_label,
                            "has_fulltext": True,
                        })
        df = pd.DataFrame(rows)
        return LiteratureDatabase(
            label=source_label,
            dataframe=df,
            user_defined_source=source_label,
            source_file_name=file_name,
            import_time=datetime.utcnow(),
        )

    def _load_literature_database_from_storage(self, file_path: str) -> LiteratureDatabase:
        """
        Download a CSV or ZIP file from storage and convert it into a LiteratureDatabase.
        - CSV: uses existing 'abstract' column if present; otherwise no special handling is required.
        - ZIP: extracts text from PDFs and populates the 'abstract' column with full text.
        """
        file_bytes = self.supabase.storage.from_(self.TASKS_BUCKET).download(file_path)
        file_name = os.path.basename(file_path)
        source_label = os.path.splitext(file_name)[0]

        if file_path.lower().endswith(".csv"):
            return self._create_literature_database_from_csv_bytes(file_bytes, source_label, file_name)
        if file_path.lower().endswith(".zip"):
            return self._create_literature_database_from_zip_bytes(file_bytes, source_label, file_name)
        raise ValueError(f"Unsupported file type: {file_path}")

    # ----------------------------- Main task processing ------------------------------

    def process_task(self, task: Dict[str, Any]) -> None:
        """
        Process a single review task end-to-end:
        - read config and notify user,
        - ingest data as LiteratureDatabase,
        - run PRISMA-compliant marking and logging,
        - run model on valid records only,
        - store artifacts and notify user.
        """
        if not task or "file_id" not in task:
            LOG.warning("Received an invalid or empty task payload: %s", task)
            return

        task_id = task["file_id"]
        LOG.info("▶️ Picked up task %s for processing.", task_id)

        prisma_logger: Optional[PRISMALogger] = None
        try:
            # Read task config
            config = self.read_stored_config(task["config_path"])
            recipient = config.get("notification_email") or task.get("email") or _get_secret(None, "notification_email")
            if not recipient:
                self.mark_task_failed(task_id, reason="No recipient email configured or found in the task record.")
                return
            project_title = config.get("project_title", f"Review Task {task_id[:8]}")
            data_type = config.get("data_type", "abstracts")  # "abstracts" | "full-texts"

            # Mark task processing and notify user
            self.mark_task_processing(task_id)
            self.send_processing_notification(recipient, project_title, task_id)

            # Initialize PRISMA logger and workflow
            prisma_logger = self._initialize_prisma_logger(task_id, project_title)
            wf = self._initialize_prisma_workflow(task_id, project_label=f"{project_title}_{task_id[:8]}")

            # Capture LLM metadata for the audit log
            llm_info = {
                "provider": "OpenAI",
                "model": config.get("model_name", "gpt-4o"),
                "temperature": config.get("temperature", 0.0),
                "prompt_type_abstract": PROMPT_TYPE_ABSTRACT,
                "prompt_type_fulltext": PROMPT_TYPE_FULLTEXT,
            }
            prisma_logger.start_run(
                framework=config.get("framework", "PICOS"),
                criteria=config.get("criteria", {}),
                objectives=config.get("objectives", []),
                mode=data_type,
                llm_info=llm_info,
            )

            # Ingest data as LiteratureDatabase
            lit_db = self._load_literature_database_from_storage(task["file_path"])
            source_id = f"{task_id}:{lit_db.label}"
            prisma_logger.log_source_imported(
                source_id=source_id,
                source_label=lit_db.label,
                original_filename=lit_db.source_file_name or "",
                file_type=os.path.splitext(lit_db.source_file_name or "")[1].lstrip(".") or "csv",
                records_identified=len(lit_db.df),
            )

            # Mark duplicates (non-destructive)
            before_size = len(lit_db.df)
            dups_marked = lit_db.mark_duplicates(strategy="doi_or_title", keep="first")
            prisma_logger.log_dedup_within_source(
                source_id=source_id,
                source_label=lit_db.label,
                before=before_size,
                after=before_size,  # We do not delete rows; mark-only pipeline
                method="doi_or_title",
                duplicates_marked=dups_marked,
            )

            # Mark missing abstracts
            missing_count = lit_db.mark_missing_abstracts(DEFAULT_ABSTRACT_COLUMN)
            prisma_logger.log_missing_abstracts_marked(
                scope="within_source",
                total_count=len(lit_db.df),
                missing_count=missing_count,
                source_id=source_id,
                source_label=lit_db.label,
            )

            # Build workflow and merge (single-source today; multi-source ready)
            wf.add_source(lit_db)
            merged_db = wf.merge_sources()
            prisma_logger.log_merge_all_sources(
                inputs=[{
                    "source_id": source_id,
                    "source_label": lit_db.label,
                    "records_after_within_source_dedup": len(lit_db.df)  # identical to before_size in mark-only
                }],
                merged_records_before_global_dedup=len(merged_db.df),
            )

            # Obtain valid records for LLM (keep status cols to access study_uid)
            filtered_df, _original_index = wf.get_valid_records_merged(include_status_columns=True)
            LOG.info("Valid records for model inference: %d (of %d total).", len(filtered_df), len(merged_db.df))

            # Prepare model inputs
            abstract_col = DEFAULT_ABSTRACT_COLUMN if DEFAULT_ABSTRACT_COLUMN in filtered_df.columns else filtered_df.columns[0]
            dataset_list: List[str] = filtered_df[abstract_col].astype(str).tolist()
            study_uids: List[str] = filtered_df["study_uid"].tolist()

            # Run model inference
            prompt_type = PROMPT_TYPE_FULLTEXT if data_type == "full-texts" else PROMPT_TYPE_ABSTRACT
            LOG.info(
                "Starting model inference for task %s (data_type: %s, model: %s).",
                task_id, data_type, llm_info["model"],
            )
            model = AsyncModelInference(self.prompts_path, dataset_list, self.openai_key, prompt_type, data_type)
            responses = model.run_inference(config.get("objectives", []), config.get("criteria", []))
            LOG.info("Model inference completed for task %s.", task_id)

            # Convert responses to DataFrame and align to study_uid
            df_responses = AsyncModelInference.response_to_dataframe(responses, dataset_list)
            df_responses.insert(0, "study_uid", study_uids)

            # Re-integrate results into the full dataset (left merge by study_uid)
            full_df = merged_db.df.copy()
            response_cols = [c for c in df_responses.columns if c != "study_uid"]
            merged_results = full_df.merge(df_responses[["study_uid"] + response_cols], on="study_uid", how="left")

            # Store raw responses (enriched with study_uid for traceability)
            enriched_responses: List[Dict[str, Any]] = []
            for i, r in enumerate(responses or []):
                payload = r if isinstance(r, dict) else {"response": r}
                uid = study_uids[i] if i < len(study_uids) else None
                enriched_responses.append({"study_uid": uid, **(payload or {})})
            raw_json_bytes = json.dumps(enriched_responses, ensure_ascii=False).encode("utf-8")
            raw_json_path = f"{self.RAW_RESPONSES_FOLDER}/{task_id}.json"
            self.upload_file(self.RESULTS_BUCKET, raw_json_path, raw_json_bytes, "application/json")

            # Store PRISMA flow JSON
            prisma_flow_path = self._generate_and_upload_prisma_flow(task_id) or ""

            # Store full results CSV (all rows, marked + model outputs if available)
            csv_bytes = merged_results.to_csv(index=False).encode("utf-8")
            output_path = f"{self.RESULTS_FOLDER}/{task_id}.csv"
            self.upload_file(self.RESULTS_BUCKET, output_path, csv_bytes, "text/csv")

            # PRISMA export event
            prisma_logger.log_export(
                outputs={
                    "csv_path": output_path,
                    "raw_json_path": raw_json_path,
                    "prisma_flow_path": prisma_flow_path,
                    "total_records": int(len(merged_db.df)),
                    "valid_records": int(len(filtered_df)),
                    "excluded_duplicates": int(dups_marked),
                    "excluded_no_abstract": int(missing_count),
                }
            )

            # Finalize PRISMA run
            prisma_logger.end_run()

            # Mark task complete and notify user
            self.mark_task_complete(task_id, output_path)
            result_url = self.supabase.storage.from_(self.RESULTS_BUCKET).get_public_url(output_path)
            email_sent = self.send_completion_notification(recipient, project_title, result_url, task_id)
            if email_sent:
                self.mark_sending_complete(task_id)
            else:
                self.mark_task_failed(task_id, reason="Email notification failed after processing.")

        except StorageApiError as exc:
            # Common case: RLS blocks storage writes when using ANON key or missing policies
            LOG.exception(
                "Storage upload failed for task %s. This usually indicates missing write privileges "
                "for Storage (RLS). Run the worker with a Supabase SERVICE_ROLE key or add write policies. Error: %s",
                task_id, exc,
            )
            try:
                if prisma_logger:
                    prisma_logger.end_run(status="FAILED", message=str(exc))
            except Exception:
                LOG.debug("Failed to end PRISMA run after Storage exception for task %s.", task_id)
            self.mark_task_failed(task_id, reason=f"Storage write failed (RLS/policy): {exc}")

        except Exception as exc:
            LOG.exception("An unhandled error occurred while processing task %s.", task_id)
            # Ensure PRISMA run is closed as FAILED
            try:
                if prisma_logger:
                    prisma_logger.end_run(status="FAILED", message=str(exc))
            except Exception:
                LOG.debug("Failed to end PRISMA run after exception for task %s.", task_id)
            self.mark_task_failed(task_id, reason=f"An unexpected error occurred: {exc}")

        finally:
            self._cleanup_prisma_resources(task_id)

    # ----------------------------- Legacy helper (unused now) -----------------------

    def _extract_data_from_storage(self, file_path: str) -> Tuple[List[str], List[str]]:
        """
        Legacy helper preserved for backward compatibility.
        Returns (dataset_list, titles) extracted from CSV/ZIP.
        Prefer using LiteratureDatabase via _load_literature_database_from_storage().
        """
        dataset_list: List[str] = []
        titles: List[str] = []
        file_bytes = self.supabase.storage.from_(self.TASKS_BUCKET).download(file_path)

        if file_path.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
            text_col = "abstract" if "abstract" in df.columns else df.columns[0]
            dataset_list = df[text_col].astype(str).tolist()
            titles = df[DEFAULT_TITLE_COLUMN].astype(str).tolist() if DEFAULT_TITLE_COLUMN in df.columns else []
        elif file_path.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                for name in z.namelist():
                    if name.lower().endswith(".pdf") and not name.startswith('__MACOSX'):
                        with z.open(name) as fh:
                            text = extract_text_from_pdf_bytes(fh.read())
                            dataset_list.append(text)
                            titles.append(os.path.basename(name))
        else:
            raise ValueError(f"Unsupported file type: {file_path}")

        return dataset_list, titles

    # -------------------------------- Main polling loop ------------------------------

    def run(self) -> None:
        """Main polling loop to fetch and process tasks."""
        LOG.info("Worker is running and polling for tasks every %d seconds.", self.poll_interval)
        while True:
            try:
                tasks = self.fetch_pending_tasks()
                if not tasks:
                    LOG.debug("No pending tasks found. Sleeping...")
                    time.sleep(self.poll_interval)
                    continue

                LOG.info("Found %d pending task(s). Processing them now.", len(tasks))
                for task in tasks:
                    self.process_task(task)

            except Exception:
                LOG.exception("Unhandled exception in main worker loop. Will sleep and retry.")

            LOG.info("Finished processing cycle. Sleeping for %d seconds.", self.poll_interval)
            time.sleep(self.poll_interval)